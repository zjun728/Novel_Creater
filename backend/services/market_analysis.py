"""Freeze market facts, call one Provider outside transactions, then fence publish."""

from __future__ import annotations

import asyncio
import json
import math
import time
from typing import Literal, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.market_analysis import (
    MARKET_ANALYSIS_POLICY_VERSION,
    MAX_ANALYSIS_SNAPSHOTS,
    MarketAnalysis,
    MarketAnalysisFailure,
    parse_market_analysis,
)
from backend.domain.provider_policy import provider_is_generation_ready
from backend.gateways.market_analysis_provider import MarketAnalysisProviderError
from backend.prompts.market_analysis import build_market_analysis_messages
from backend.security.provider_secrets import (
    normalize_provider_secrets,
    provider_response_text_contains_secret,
    provider_response_value_contains_secret,
    validate_provider_response_text,
)


_STRICT = ConfigDict(
    strict=True,
    frozen=True,
    extra="forbid",
    str_strip_whitespace=True,
    hide_input_in_errors=True,
)
_SAFE_FAILURE_CODES = frozenset(
    {
        "MARKET_ANALYSIS_CANCELLED",
        "MARKET_ANALYSIS_PROVIDER_FAILED",
        "MARKET_ANALYSIS_INVALID_RESPONSE",
    }
)
CANCELLATION_CLEANUP_TIMEOUT_SECONDS = 2.0


class AnalyzeMarket(BaseModel):
    model_config = _STRICT

    project_id: str = Field(min_length=1, max_length=36)
    snapshot_ids: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_ANALYSIS_SNAPSHOTS,
    )
    idempotency_key: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]{64}$",
    )

    @field_validator("snapshot_ids", mode="before")
    @classmethod
    def freeze_ids(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        if len(self.snapshot_ids) != len(set(self.snapshot_ids)):
            raise ValueError("snapshot IDs must be unique")
        if any(not item or len(item) > 36 for item in self.snapshot_ids):
            raise ValueError("snapshot ID is invalid")
        return self


class MarketAnalysisResult(BaseModel):
    model_config = _STRICT

    id: str
    project_id: str
    input_manifest_hash: str
    policy_version: str
    status: Literal[
        "reserved", "running", "succeeded", "failed", "outcome_unknown"
    ]
    analysis: MarketAnalysis | None
    result_hash: str | None
    public_error_code: str | None
    created_at: int
    completed_at: int | None


class MarketAnalysisService:
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

    @staticmethod
    def _analysis_value(value) -> MarketAnalysis | None:
        if value is None:
            return None
        if isinstance(value, str):
            value = json.loads(value)
        return MarketAnalysis.model_validate(value)

    @classmethod
    def _result(cls, row: dict) -> MarketAnalysisResult:
        return MarketAnalysisResult(
            id=row["id"],
            project_id=row["project_id"],
            input_manifest_hash=row["input_manifest_hash"],
            policy_version=row["policy_version"],
            status=row["status"],
            analysis=cls._analysis_value(row.get("analysis_json")),
            result_hash=row.get("result_hash"),
            public_error_code=row.get("public_error_code"),
            created_at=int(row["created_at"]),
            completed_at=(
                int(row["completed_at"])
                if row.get("completed_at") is not None
                else None
            ),
        )

    @staticmethod
    def _request_hash(command: AnalyzeMarket) -> str:
        return canonical_hash(
            {
                "projectId": command.project_id,
                "snapshotIds": list(command.snapshot_ids),
                "promptPolicyVersion": MARKET_ANALYSIS_POLICY_VERSION,
            }
        )

    @staticmethod
    def _provider_ready(inputs: dict) -> bool:
        provider = inputs.get("provider")
        if not isinstance(provider, dict):
            return False
        return bool(
            inputs.get("resolution_status") == "bound"
            and inputs.get("provider_id") == provider.get("id")
            and inputs.get("model_name_snapshot") == provider.get("model_name")
            and provider_is_generation_ready(provider)
            and int(provider.get("supports_json") or 0) == 1
        )

    @staticmethod
    def _generation_config(provider: dict) -> dict:
        try:
            temperature = float(provider["temperature"])
            max_tokens = int(provider["max_output_tokens"])
        except (KeyError, TypeError, ValueError, OverflowError):
            raise MarketAnalysisFailure("MARKET_ANALYSIS_NOT_READY") from None
        if (
            not math.isfinite(temperature)
            or temperature < 0
            or max_tokens <= 0
        ):
            raise MarketAnalysisFailure("MARKET_ANALYSIS_NOT_READY")
        return {"temperature": temperature, "maxOutputTokens": max_tokens}

    @staticmethod
    def _input_manifest(inputs: dict) -> dict:
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
            "binding": {
                "revisionId": inputs["binding_revision_id"],
                "hash": inputs["binding_hash"],
            },
            "promptPolicyVersion": MARKET_ANALYSIS_POLICY_VERSION,
        }

    async def _reserve(self, command: AnalyzeMarket):
        request_hash = self._request_hash(command)
        async with self._transaction() as session:
            project = await self.repository.lock_analysis_project(
                session,
                command.project_id,
            )
            if project is None or project.get("archived_at") is not None:
                raise MarketAnalysisFailure("MARKET_ANALYSIS_NOT_READY")
            existing = await self.repository.lock_analysis_by_key(
                session,
                command.project_id,
                command.idempotency_key,
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise MarketAnalysisFailure(
                        "MARKET_ANALYSIS_IDEMPOTENCY_CONFLICT"
                    )
                return self._result(existing), None
            inputs = await self.repository.lock_analysis_inputs(
                session,
                command.project_id,
                command.snapshot_ids,
            )
            if (
                not self._provider_ready(inputs)
                or tuple(
                    item.get("id") for item in inputs.get("snapshots", ())
                )
                != command.snapshot_ids
            ):
                raise MarketAnalysisFailure("MARKET_ANALYSIS_NOT_READY")
            provider = dict(inputs["provider"])
            for key in ("base_url", "api_key"):
                provider[key] = str(provider[key]).strip()
            generation_config = self._generation_config(provider)
            manifest = self._input_manifest(inputs)
            row = {
                "id": self._id(),
                "project_id": command.project_id,
                "binding_revision_id": inputs["binding_revision_id"],
                "binding_hash": inputs["binding_hash"],
                "input_manifest_json": canonical_json(manifest),
                "input_manifest_hash": canonical_hash(manifest),
                "policy_version": MARKET_ANALYSIS_POLICY_VERSION,
                "idempotency_key": command.idempotency_key,
                "request_hash": request_hash,
                "status": "running",
                "analysis_json": None,
                "result_hash": None,
                "public_error_code": None,
                "created_at": self._clock(),
                "completed_at": None,
            }
            await self.repository.insert_analysis(session, row)
        return self._result(row), {
            "inputs": inputs,
            "provider": provider,
            "generation_config": generation_config,
        }

    async def _load(self, project_id: str, analysis_id: str):
        async with self._connection() as session:
            row = await self.repository.read_analysis(
                session,
                project_id,
                analysis_id,
            )
        if row is None:
            raise MarketAnalysisFailure("MARKET_ANALYSIS_NOT_FOUND")
        return self._result(row)

    async def _persist_failure(
        self,
        project_id: str,
        analysis_id: str,
        code: str,
    ) -> None:
        if code not in _SAFE_FAILURE_CODES:
            raise ValueError("unsupported market analysis failure code")
        async with self._transaction() as session:
            changed = await self.repository.fail_analysis(
                session,
                project_id=project_id,
                analysis_id=analysis_id,
                public_error_code=code,
                completed_at=self._clock(),
            )
            if not changed:
                row = await self.repository.read_analysis(
                    session,
                    project_id,
                    analysis_id,
                )
                if row is None or row.get("status") not in {
                    "succeeded",
                    "failed",
                    "outcome_unknown",
                }:
                    raise MarketAnalysisFailure(
                        "MARKET_ANALYSIS_IDEMPOTENCY_CONFLICT"
                    )

    async def _fail(
        self,
        project_id: str,
        analysis_id: str,
        code: str,
    ):
        await self._persist_failure(project_id, analysis_id, code)
        return await self._load(project_id, analysis_id)

    @staticmethod
    async def _await_cancellation_cleanup(
        cleanup: asyncio.Task,
    ) -> BaseException | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + CANCELLATION_CLEANUP_TIMEOUT_SECONDS
        while not cleanup.done():
            remaining = deadline - loop.time()
            if remaining <= 0:
                cleanup.cancel()
                cleanup.add_done_callback(
                    lambda task: (
                        task.exception()
                        if not task.cancelled()
                        else None
                    )
                )
                return TimeoutError(
                    "market analysis cancellation cleanup timed out"
                )
            try:
                done, _ = await asyncio.wait((cleanup,), timeout=remaining)
            except asyncio.CancelledError:
                continue
            if not done:
                cleanup.cancel()
                cleanup.add_done_callback(
                    lambda task: (
                        task.exception()
                        if not task.cancelled()
                        else None
                    )
                )
                return TimeoutError(
                    "market analysis cancellation cleanup timed out"
                )
        try:
            cleanup.result()
        except BaseException as error:
            return error
        return None

    async def _handle_cancellation(
        self,
        project_id: str,
        analysis_id: str,
        cancellation: asyncio.CancelledError,
    ) -> None:
        cleanup = asyncio.create_task(
            self._persist_failure(
                project_id,
                analysis_id,
                "MARKET_ANALYSIS_CANCELLED",
            ),
            name=f"market-analysis-cancel-{analysis_id}",
        )
        cleanup_error = await self._await_cancellation_cleanup(cleanup)
        if cleanup_error is not None:
            raise BaseExceptionGroup(
                "market analysis cancellation cleanup failed",
                [cancellation, cleanup_error],
            ) from None

    @staticmethod
    def _contains_raw_copy(
        analysis: MarketAnalysis,
        snapshots: tuple[dict, ...],
    ) -> bool:
        output = canonical_json(analysis)
        for snapshot in snapshots:
            source_url = snapshot.get("source_url")
            if isinstance(source_url, str) and source_url in output:
                return True
            for entry in snapshot["entries"]:
                work_url = entry.get("work_url")
                if isinstance(work_url, str) and work_url in output:
                    return True
                stack = [entry.get("public_metrics")]
                while stack:
                    value = stack.pop()
                    if isinstance(value, dict):
                        stack.extend(value.values())
                    elif isinstance(value, (list, tuple)):
                        stack.extend(value)
                    elif (
                        isinstance(value, str)
                        and len(value) >= 80
                        and value in output
                    ):
                        return True
        return False

    async def _execute_reserved(
        self,
        command: AnalyzeMarket,
        reserved: MarketAnalysisResult,
        context: dict,
    ) -> MarketAnalysisResult:
        inputs = context["inputs"]
        provider = context["provider"]
        try:
            messages = build_market_analysis_messages(inputs["snapshots"])
            raw = await self._gateway.generate(
                provider=provider,
                messages=messages,
                generation_config=context["generation_config"],
            )
        except (MarketAnalysisProviderError, TimeoutError):
            return await self._fail(
                command.project_id,
                reserved.id,
                "MARKET_ANALYSIS_PROVIDER_FAILED",
            )
        except ValueError:
            return await self._fail(
                command.project_id,
                reserved.id,
                "MARKET_ANALYSIS_INVALID_RESPONSE",
            )
        secrets = normalize_provider_secrets(
            (provider.get("api_key"), provider.get("base_url"))
        )
        try:
            raw = validate_provider_response_text(raw)
            if provider_response_text_contains_secret(raw, secrets):
                raise ValueError("provider response rejected")
            decoded = json.loads(raw)
            if provider_response_value_contains_secret(decoded, secrets):
                raise ValueError("provider response rejected")
            analysis = parse_market_analysis(
                decoded,
                snapshot_ids=command.snapshot_ids,
            )
            if self._contains_raw_copy(analysis, inputs["snapshots"]):
                raise ValueError("provider response copied source content")
        except (TypeError, ValueError, RecursionError):
            return await self._fail(
                command.project_id,
                reserved.id,
                "MARKET_ANALYSIS_INVALID_RESPONSE",
            )
        analysis_json = canonical_json(analysis)
        result_hash = canonical_hash(analysis)
        async with self._transaction() as session:
            await self.repository.publish_analysis(
                session,
                project_id=command.project_id,
                analysis_id=reserved.id,
                binding_revision_id=inputs["binding_revision_id"],
                binding_hash=inputs["binding_hash"],
                snapshots=inputs["snapshots"],
                analysis_json=analysis_json,
                result_hash=result_hash,
                completed_at=self._clock(),
            )
        return await self._load(command.project_id, reserved.id)

    async def analyze(self, command: AnalyzeMarket) -> MarketAnalysisResult:
        reserved, context = await self._reserve(command)
        if context is None:
            return reserved
        try:
            return await self._execute_reserved(command, reserved, context)
        except asyncio.CancelledError as cancellation:
            await self._handle_cancellation(
                command.project_id,
                reserved.id,
                cancellation,
            )
            raise

    async def get(
        self,
        project_id: str,
        analysis_id: str,
    ) -> MarketAnalysisResult:
        return await self._load(project_id, analysis_id)
