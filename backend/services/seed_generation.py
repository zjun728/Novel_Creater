"""Transient seed inspiration with an idempotent, safe attempt ledger."""

from __future__ import annotations

import asyncio
import json
import math
import time
from typing import Literal, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.market_analysis import parse_market_analysis
from backend.domain.provider_policy import provider_is_generation_ready
from backend.domain.seeds import (
    MAX_SEED_ASSISTANT_LENGTH,
    MAX_SEED_CHAT_TURNS,
    MAX_SEED_PROVENANCE_SNAPSHOTS,
    SeedAssistantTurn,
    SeedChatTurn,
    SeedInspirationFailure,
    parse_seed_assistant_turn,
)
from backend.gateways.seed_provider import SeedProviderError
from backend.prompts.seed import build_seed_inspiration_messages
from backend.security.provider_secrets import (
    normalize_provider_secrets,
    provider_response_text_contains_secret,
    provider_response_value_contains_secret,
    validate_provider_response_text,
)


SEED_INSPIRATION_POLICY_VERSION = "seed-inspiration-policy-v1"
CANCELLATION_CLEANUP_TIMEOUT_SECONDS = 2.0
FAILURE_TERMINAL_WRITE_ATTEMPTS = 2
_RETRYABLE_MYSQL_ERRORS = frozenset({1205, 1213, 3572})
_STRICT = ConfigDict(
    strict=True,
    frozen=True,
    extra="forbid",
    populate_by_name=True,
    str_strip_whitespace=True,
    hide_input_in_errors=True,
)


class GenerateSeedInspiration(BaseModel):
    model_config = _STRICT

    project_id: str = Field(min_length=1, max_length=36)
    transcript: tuple[SeedChatTurn, ...] = Field(
        min_length=1,
        max_length=MAX_SEED_CHAT_TURNS,
    )
    snapshot_ids: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_SEED_PROVENANCE_SNAPSHOTS,
    )
    analysis_id: str = Field(min_length=1, max_length=36)
    idempotency_key: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]{64}$",
    )

    @field_validator("transcript", "snapshot_ids", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_ordered_ids(self) -> Self:
        if len(self.snapshot_ids) != len(set(self.snapshot_ids)):
            raise ValueError("snapshot IDs must be unique")
        if any(not item or len(item) > 36 for item in self.snapshot_ids):
            raise ValueError("snapshot ID is invalid")
        return self


class SeedInspirationResult(BaseModel):
    model_config = _STRICT

    attempt_id: str | None
    status: Literal["succeeded", "failed", "outcome_unknown"]
    assistant_turn: SeedAssistantTurn | None
    result_hash: str | None
    public_error_code: str | None
    created_at: int
    completed_at: int


class SeedGenerationService:
    def __init__(
        self,
        repository,
        *,
        transaction_factory,
        connection_factory,
        provider_gateway,
        id_factory=None,
        clock=None,
    ) -> None:
        self.repository = repository
        self._transaction = transaction_factory
        self._connection = connection_factory
        self._gateway = provider_gateway
        self._id = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._terminalizers: set[asyncio.Task] = set()

    @staticmethod
    def _request_hash(command: GenerateSeedInspiration) -> str:
        return canonical_hash(
            {
                "projectId": command.project_id,
                "transcript": [
                    item.model_dump(mode="json") for item in command.transcript
                ],
                "snapshotIds": list(command.snapshot_ids),
                "analysisId": command.analysis_id,
                "policyVersion": SEED_INSPIRATION_POLICY_VERSION,
            }
        )

    @staticmethod
    def _provider_ready(inputs: dict) -> bool:
        provider = inputs.get("provider")
        return bool(
            isinstance(provider, dict)
            and inputs.get("resolution_status") == "bound"
            and inputs.get("provider_id") == provider.get("id")
            and inputs.get("model_name_snapshot") == provider.get("model_name")
            and provider_is_generation_ready(provider)
        )

    @staticmethod
    def _generation_config(provider: dict) -> dict:
        try:
            temperature = float(provider["temperature"])
            max_tokens = int(provider["max_output_tokens"])
        except (KeyError, TypeError, ValueError, OverflowError):
            raise SeedInspirationFailure("SEED_INSPIRATION_NOT_READY") from None
        if (
            not math.isfinite(temperature)
            or temperature < 0
            or max_tokens <= 0
        ):
            raise SeedInspirationFailure("SEED_INSPIRATION_NOT_READY")
        return {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }

    @staticmethod
    def _json_mapping(value: object) -> dict:
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict):
            raise ValueError("stored JSON is invalid")
        return value

    @staticmethod
    def _mysql_error_number(error: BaseException) -> int | None:
        pending = [error]
        seen: set[int] = set()
        while pending:
            current = pending.pop()
            if id(current) in seen:
                continue
            seen.add(id(current))
            if current.args and type(current.args[0]) is int:
                return current.args[0]
            pending.extend(
                item
                for item in (
                    current.__cause__,
                    current.__context__,
                )
                if item is not None
            )
            nested = getattr(current, "exceptions", ())
            if isinstance(nested, tuple):
                pending.extend(
                    item for item in nested if isinstance(item, BaseException)
                )
        return None

    @classmethod
    def _validate_inputs(
        cls,
        command: GenerateSeedInspiration,
        inputs: dict,
    ) -> None:
        snapshots = tuple(inputs.get("snapshots") or ())
        if tuple(item.get("id") for item in snapshots) != command.snapshot_ids:
            raise SeedInspirationFailure("SEED_INSPIRATION_NOT_READY")
        analysis = inputs.get("analysis")
        if (
            not isinstance(analysis, dict)
            or analysis.get("id") != command.analysis_id
            or analysis.get("status", "succeeded") != "succeeded"
            or not analysis.get("result_hash")
            or not analysis.get("input_manifest_hash")
        ):
            raise SeedInspirationFailure("SEED_INSPIRATION_NOT_READY")
        try:
            manifest = cls._json_mapping(analysis["input_manifest_json"])
            frozen = tuple(manifest["snapshots"])
        except (KeyError, TypeError, ValueError):
            raise SeedInspirationFailure("SEED_INSPIRATION_NOT_READY") from None
        expected = tuple(
            (
                item["id"],
                item["content_hash"],
                item["manifest_hash"],
                item["source_id"],
            )
            for item in snapshots
        )
        actual = tuple(
            (
                item.get("id"),
                item.get("hash"),
                item.get("manifestHash"),
                item.get("sourceId"),
            )
            for item in frozen
            if isinstance(item, dict)
        )
        if actual != expected:
            raise SeedInspirationFailure("SEED_INSPIRATION_NOT_READY")
        analysis_json = cls._json_mapping(analysis["analysis_json"])
        try:
            parse_market_analysis(
                analysis_json,
                snapshot_ids=command.snapshot_ids,
            )
        except ValueError:
            raise SeedInspirationFailure("SEED_INSPIRATION_NOT_READY")

    @staticmethod
    def _manifest(
        command: GenerateSeedInspiration,
        inputs: dict,
    ) -> dict:
        return {
            "snapshots": [
                {
                    "id": item["id"],
                    "sourceId": item["source_id"],
                    "hash": item["content_hash"],
                    "manifestHash": item["manifest_hash"],
                }
                for item in inputs["snapshots"]
            ],
            "analysis": {
                "id": inputs["analysis"]["id"],
                "hash": inputs["analysis"]["result_hash"],
                "manifestHash": inputs["analysis"]["input_manifest_hash"],
            },
            "binding": {
                "revisionId": inputs["binding_revision_id"],
                "hash": inputs["binding_hash"],
            },
            "transcriptHash": canonical_hash(
                {
                    "turns": [
                        item.model_dump(mode="json")
                        for item in command.transcript
                    ]
                }
            ),
            "policyVersion": SEED_INSPIRATION_POLICY_VERSION,
        }

    @staticmethod
    def _result_from_rows(
        request: dict,
        attempt: dict | None,
    ) -> SeedInspirationResult:
        status = request["status"]
        assistant = None
        if status == "succeeded":
            if attempt is None:
                raise SeedInspirationFailure("SEED_INSPIRATION_NOT_FOUND")
            value = attempt.get("result_json")
            if isinstance(value, str):
                value = json.loads(value)
            assistant = parse_seed_assistant_turn(value)
        created_at = (
            attempt.get("created_at")
            if attempt is not None
            else request["created_at"]
        )
        completed_at = (
            attempt.get("completed_at")
            if attempt is not None
            else request["completed_at"]
        )
        return SeedInspirationResult(
            attempt_id=request.get("attempt_id"),
            status=status,
            assistant_turn=assistant,
            result_hash=request.get("result_hash"),
            public_error_code=request.get("public_error_code"),
            created_at=int(created_at),
            completed_at=int(completed_at),
        )

    async def _reserve_once(
        self,
        command: GenerateSeedInspiration,
        reservation_state: dict,
    ):
        request_hash = self._request_hash(command)
        async with self._transaction() as session:
            project = await self.repository.lock_inspiration_project(
                session,
                command.project_id,
            )
            if project is None or project.get("archived_at") is not None:
                raise SeedInspirationFailure("SEED_INSPIRATION_NOT_FOUND")
            existing = await self.repository.lock_inspiration_request(
                session,
                command.project_id,
                command.idempotency_key,
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise SeedInspirationFailure(
                        "SEED_INSPIRATION_IDEMPOTENCY_CONFLICT"
                    )
                if existing["status"] == "reserved":
                    raise SeedInspirationFailure(
                        "SEED_INSPIRATION_IN_PROGRESS"
                    )
                attempt = (
                    await self.repository.read_inspiration_attempt(
                        session,
                        command.project_id,
                        existing["attempt_id"],
                    )
                    if existing.get("attempt_id")
                    else None
                )
                return self._result_from_rows(existing, attempt), None
            inputs = await self.repository.lock_inspiration_inputs(
                session,
                command.project_id,
                command.snapshot_ids,
                command.analysis_id,
            )
            if not self._provider_ready(inputs):
                raise SeedInspirationFailure("SEED_INSPIRATION_NOT_READY")
            self._validate_inputs(command, inputs)
            provider = dict(inputs["provider"])
            for key in ("base_url", "api_key"):
                provider[key] = str(provider[key]).strip()
            generation_config = self._generation_config(provider)
            manifest = self._manifest(command, inputs)
            request_id = self._id()
            attempt_id = self._id()
            now = self._clock()
            request = {
                "id": request_id,
                "project_id": command.project_id,
                "idempotency_key": command.idempotency_key,
                "request_hash": request_hash,
                "status": "reserved",
                "attempt_id": None,
                "result_hash": None,
                "public_error_code": None,
                "created_at": now,
                "completed_at": None,
            }
            primary = inputs["snapshots"][0]
            attempt = {
                "id": attempt_id,
                "project_id": command.project_id,
                "selection_revision": inputs.get("selection_revision"),
                "market_source_id": primary["source_id"],
                "market_snapshot_id": primary["id"],
                "market_snapshot_hash": primary["content_hash"],
                "market_analysis_id": inputs["analysis"]["id"],
                "market_analysis_hash": inputs["analysis"]["result_hash"],
                "binding_revision_id": inputs["binding_revision_id"],
                "binding_hash": inputs["binding_hash"],
                "input_manifest_json": canonical_json(manifest),
                "input_manifest_hash": canonical_hash(manifest),
                "status": "running",
                "result_json": None,
                "result_hash": None,
                "public_error_code": None,
                "created_at": now,
                "completed_at": None,
            }
            reservation_state["context"] = {
                "request": request,
                "attempt": attempt,
                "inputs": inputs,
                "provider": provider,
                "generation_config": generation_config,
            }
            await self.repository.insert_inspiration_request(session, request)
            await self.repository.insert_inspiration_attempt(session, attempt)
        return None, reservation_state["context"]

    async def _reserve(self, command: GenerateSeedInspiration):
        reservation_state: dict = {}
        try:
            return await self._reserve_once(command, reservation_state)
        except Exception as error:
            if self._mysql_error_number(error) in _RETRYABLE_MYSQL_ERRORS:
                raise SeedInspirationFailure(
                    "SEED_INSPIRATION_IN_PROGRESS"
                ) from None
            context = reservation_state.get("context")
            if context is not None:
                reconciled = await self._reconcile_terminal_or_fail(
                    command,
                    context,
                    "SEED_INSPIRATION_RESERVATION_FAILED",
                    missing_is_unresolved=True,
                )
                if reconciled is not None:
                    return reconciled, None
            raise

    async def _load_attempt(
        self,
        project_id: str,
        attempt_id: str,
    ) -> dict:
        async with self._connection() as session:
            row = await self.repository.read_inspiration_attempt(
                session,
                project_id,
                attempt_id,
            )
        if row is None:
            raise SeedInspirationFailure("SEED_INSPIRATION_NOT_FOUND")
        return row

    async def _publish(
        self,
        command: GenerateSeedInspiration,
        context: dict,
        *,
        result_json: str,
        result_hash: str,
        completed_at: int,
    ) -> None:
        inputs = context["inputs"]
        async with self._transaction() as session:
            await self.repository.publish_inspiration(
                session,
                project_id=command.project_id,
                idempotency_key=command.idempotency_key,
                request_hash=context["request"]["request_hash"],
                attempt_id=context["attempt"]["id"],
                binding_revision_id=inputs["binding_revision_id"],
                binding_hash=inputs["binding_hash"],
                snapshots=inputs["snapshots"],
                analysis_id=inputs["analysis"]["id"],
                analysis_hash=inputs["analysis"]["result_hash"],
                analysis_manifest_hash=inputs["analysis"][
                    "input_manifest_hash"
                ],
                result_json=result_json,
                result_hash=result_hash,
                completed_at=completed_at,
            )

    async def _write_failure(
        self,
        command: GenerateSeedInspiration,
        context: dict,
        code: str,
        *,
        outcome_unknown: bool,
        completed_at: int,
    ) -> None:
        attempt = context["attempt"]
        async with self._transaction() as session:
            await self.repository.fail_inspiration(
                session,
                project_id=command.project_id,
                idempotency_key=command.idempotency_key,
                attempt_id=attempt["id"],
                attempt_status=(
                    "outcome_unknown" if outcome_unknown else "failed"
                ),
                request_status=(
                    "outcome_unknown" if outcome_unknown else "failed"
                ),
                public_error_code=code,
                completed_at=completed_at,
            )

    async def _fail(
        self,
        command: GenerateSeedInspiration,
        context: dict,
        code: str,
        *,
        outcome_unknown: bool = False,
    ) -> SeedInspirationResult:
        completed_at = self._clock()
        last_error: Exception | None = None
        for _ in range(FAILURE_TERMINAL_WRITE_ATTEMPTS):
            try:
                await self._write_failure(
                    command,
                    context,
                    code,
                    outcome_unknown=outcome_unknown,
                    completed_at=completed_at,
                )
            except Exception as error:
                last_error = error
            terminal = await self._load_attempt(
                command.project_id,
                context["attempt"]["id"],
            )
            if terminal["status"] != "running":
                return self._result_from_terminal(context, terminal)
        if last_error is not None:
            raise last_error
        raise RuntimeError("seed inspiration terminal state did not advance")

    @classmethod
    def _result_from_terminal(
        cls,
        context: dict,
        terminal: dict,
    ) -> SeedInspirationResult:
        status = terminal["status"]
        request = {
            **context["request"],
            "status": status,
            "attempt_id": (
                terminal["id"]
                if status in {"succeeded", "outcome_unknown"}
                else None
            ),
            "result_hash": (
                terminal.get("result_hash")
                if status == "succeeded"
                else None
            ),
            "public_error_code": terminal.get("public_error_code"),
            "completed_at": terminal["completed_at"],
        }
        return cls._result_from_rows(
            request,
            terminal if status in {"succeeded", "outcome_unknown"} else None,
        )

    async def _reconcile_terminal_or_fail(
        self,
        command: GenerateSeedInspiration,
        context: dict,
        failure_code: str,
        *,
        missing_is_unresolved: bool = False,
    ) -> SeedInspirationResult | None:
        try:
            terminal = await self._load_attempt(
                command.project_id,
                context["attempt"]["id"],
            )
        except SeedInspirationFailure:
            if missing_is_unresolved:
                return None
            raise
        if terminal["status"] != "running":
            return self._result_from_terminal(context, terminal)
        try:
            return await self._fail(
                command,
                context,
                failure_code,
            )
        except Exception:
            terminal = await self._load_attempt(
                command.project_id,
                context["attempt"]["id"],
            )
            if terminal["status"] != "running":
                return self._result_from_terminal(context, terminal)
            raise

    async def _execute(
        self,
        command: GenerateSeedInspiration,
        context: dict,
    ) -> SeedInspirationResult:
        try:
            messages = build_seed_inspiration_messages(
                transcript=command.transcript,
                inputs=context["inputs"],
            )
            raw = await self._gateway.generate(
                provider=context["provider"],
                messages=messages,
                generation_config=context["generation_config"],
            )
        except SeedProviderError:
            return await self._fail(
                command,
                context,
                "SEED_INSPIRATION_PROVIDER_FAILED",
            )
        except TimeoutError:
            return await self._fail(
                command,
                context,
                "SEED_INSPIRATION_PROVIDER_FAILED",
            )
        except ValueError:
            return await self._fail(
                command,
                context,
                "SEED_INSPIRATION_INVALID_RESPONSE",
            )
        except Exception:
            return await self._fail(
                command,
                context,
                "SEED_INSPIRATION_PROVIDER_FAILED",
            )
        secrets = normalize_provider_secrets(
            (
                context["provider"].get("api_key"),
                context["provider"].get("base_url"),
            )
        )
        try:
            raw = validate_provider_response_text(raw, strip=True)
            if provider_response_text_contains_secret(raw, secrets):
                raise ValueError("provider response rejected")
            assistant = parse_seed_assistant_turn(
                {"role": "assistant", "content": raw}
            )
            if provider_response_value_contains_secret(
                assistant.model_dump(mode="json"),
                secrets,
            ):
                raise ValueError("provider response rejected")
            if self._echoes_transcript(
                assistant.content,
                command.transcript,
            ):
                raise ValueError("provider copied working transcript")
        except (TypeError, ValueError, RecursionError):
            return await self._fail(
                command,
                context,
                "SEED_INSPIRATION_INVALID_RESPONSE",
            )
        result_json = canonical_json(assistant)
        result_hash = canonical_hash(assistant)
        completed_at = self._clock()
        publication = asyncio.create_task(
            self._publish(
                command,
                context,
                result_json=result_json,
                result_hash=result_hash,
                completed_at=completed_at,
            ),
            name=f"seed-inspiration-publish-{context['attempt']['id']}",
        )
        context["publication_task"] = publication
        try:
            await asyncio.shield(publication)
        except asyncio.CancelledError:
            raise
        except Exception:
            return await self._reconcile_terminal_or_fail(
                command,
                context,
                "SEED_INSPIRATION_PUBLICATION_FAILED",
            )
        terminal = await self._load_attempt(
            command.project_id,
            context["attempt"]["id"],
        )
        request = {
            **context["request"],
            "status": terminal["status"],
            "attempt_id": (
                terminal["id"] if terminal["status"] == "succeeded" else None
            ),
            "result_hash": terminal.get("result_hash"),
            "public_error_code": terminal.get("public_error_code"),
            "completed_at": terminal["completed_at"],
        }
        return self._result_from_rows(
            request,
            terminal if terminal["status"] == "succeeded" else None,
        )

    @staticmethod
    def _value_contains_transcript(
        value: object,
        turns: list[dict],
    ) -> bool:
        pending = [value]
        visited = 0
        while pending and visited < 256:
            current = pending.pop()
            visited += 1
            if current == turns:
                return True
            if isinstance(current, dict):
                if current.get("currentTranscript") == turns:
                    return True
                pending.extend(current.values())
            elif isinstance(current, list):
                pending.extend(current)
        return False

    @staticmethod
    def _echoes_transcript(
        content: str,
        transcript: tuple[SeedChatTurn, ...],
    ) -> bool:
        stripped = content.strip()
        turns = [
            turn.model_dump(mode="json")
            for turn in transcript
        ]
        if any(stripped == turn["content"].strip() for turn in turns):
            return True
        frozen_documents = (
            canonical_json(turns),
            canonical_json({"currentTranscript": turns}),
        )
        if any(document in stripped for document in frozen_documents):
            return True
        decoder = json.JSONDecoder()
        bounded = stripped[:MAX_SEED_ASSISTANT_LENGTH]
        for index, character in enumerate(bounded):
            if character not in "[{":
                continue
            try:
                parsed, _ = decoder.raw_decode(bounded, index)
            except (TypeError, ValueError, RecursionError):
                continue
            if SeedGenerationService._value_contains_transcript(
                parsed,
                turns,
            ):
                return True
        return False

    async def _cancel(
        self,
        command: GenerateSeedInspiration,
        context: dict,
        cancellation: asyncio.CancelledError,
    ) -> None:
        cleanup = asyncio.create_task(
            self._reconcile_cancellation(
                command,
                context,
            ),
            name=f"seed-inspiration-cancel-{context['attempt']['id']}",
        )
        cleanup_error = await self._await_cancellation_cleanup(cleanup)
        if cleanup_error is not None:
            raise BaseExceptionGroup(
                "seed inspiration cancellation cleanup failed",
                [cancellation, cleanup_error],
            ) from None

    async def _reconcile_cancellation(
        self,
        command: GenerateSeedInspiration,
        context: dict,
    ) -> None:
        publication = context.get("publication_task")
        if isinstance(publication, asyncio.Task):
            try:
                await asyncio.shield(publication)
            except BaseException:
                pass
        terminal = await self._load_attempt(
            command.project_id,
            context["attempt"]["id"],
        )
        if terminal["status"] != "running":
            return
        await self._fail(
            command,
            context,
            "SEED_INSPIRATION_CANCELLED",
            outcome_unknown=True,
        )

    async def _await_owned_task(
        self,
        task: asyncio.Task,
    ) -> tuple[bool, object | None, BaseException | None]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + CANCELLATION_CLEANUP_TIMEOUT_SECONDS
        while not task.done():
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False, None, None
            try:
                done, _ = await asyncio.wait((task,), timeout=remaining)
            except asyncio.CancelledError:
                continue
            if not done:
                return False, None, None
        try:
            return True, task.result(), None
        except BaseException as error:
            return True, None, error

    async def _recover_cancelled_reservation(
        self,
        command: GenerateSeedInspiration,
        reservation: asyncio.Task,
    ) -> None:
        try:
            _, context = await reservation
        except BaseException:
            return
        if context is not None:
            await self._reconcile_cancellation(command, context)

    async def _cancel_reservation(
        self,
        command: GenerateSeedInspiration,
        reservation: asyncio.Task,
        cancellation: asyncio.CancelledError,
    ) -> None:
        completed, result, error = await self._await_owned_task(reservation)
        if completed:
            if error is None:
                _, context = result
                if context is not None:
                    await self._cancel(command, context, cancellation)
            return
        recovery = asyncio.create_task(
            self._recover_cancelled_reservation(command, reservation),
            name=f"seed-inspiration-reserve-recovery-{command.project_id}",
        )
        self._transfer_terminalizer(recovery)

    async def _await_cancellation_cleanup(
        self,
        cleanup: asyncio.Task,
    ) -> BaseException | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + CANCELLATION_CLEANUP_TIMEOUT_SECONDS
        while not cleanup.done():
            remaining = deadline - loop.time()
            if remaining <= 0:
                self._transfer_terminalizer(cleanup)
                return None
            try:
                done, _ = await asyncio.wait((cleanup,), timeout=remaining)
            except asyncio.CancelledError:
                continue
            if not done:
                self._transfer_terminalizer(cleanup)
                return None
        try:
            cleanup.result()
        except BaseException as error:
            return error
        return None

    def _transfer_terminalizer(self, cleanup: asyncio.Task) -> None:
        self._terminalizers.add(cleanup)

        def release(task: asyncio.Task) -> None:
            self._terminalizers.discard(task)
            if not task.cancelled():
                task.exception()

        cleanup.add_done_callback(release)

    async def generate(
        self,
        command: GenerateSeedInspiration,
    ) -> SeedInspirationResult:
        reservation = asyncio.create_task(
            self._reserve(command),
            name=f"seed-inspiration-reserve-{command.project_id}",
        )
        try:
            replay, context = await asyncio.shield(reservation)
        except asyncio.CancelledError as cancellation:
            await self._cancel_reservation(
                command,
                reservation,
                cancellation,
            )
            raise
        if context is None:
            return replay
        try:
            return await self._execute(command, context)
        except asyncio.CancelledError as cancellation:
            await self._cancel(command, context, cancellation)
            raise
