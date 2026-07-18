"""Transactional orchestration for auditable story-engine batches."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import time
from types import MappingProxyType
from typing import Literal
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.provider_policy import provider_is_generation_ready
from backend.domain.seeds import SeedPayload
from backend.domain.story_engines import StoryEngineOption, validate_three_options
from backend.gateways.story_engine_provider import (
    PROVIDER_TIMEOUT_SECONDS,
    StoryEngineProviderHTTPError,
    StoryEngineProviderResponseError,
)
from backend.http_errors import (
    ProjectNotFound,
    StoryEngineBatchConflict,
    StoryEngineBatchNotFound,
    StoryEnginePreconditionFailed,
)
from backend.prompts.story_engine import build_story_engine_messages
from backend.security.provider_secrets import (
    normalize_provider_secrets,
    provider_response_text_contains_secret,
    provider_response_value_contains_secret,
    validate_provider_response_text,
)


RESERVED_TIMEOUT_MS = 300_000
RUNNING_LEASE_MS = 240_000
_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "outcome_unknown"})
_SAFE_FAILURE_CODES = frozenset(
    {"provider_failed", "provider_timeout", "invalid_response"}
)
DEFAULT_CHANNEL_PROFILE = MappingProxyType(
    {
        "schemaVersion": "writer-channel-profile-v1",
        "key": "male-qidian-qq-longform",
        "audience": "男频长篇",
        "readingModel": "起点/QQ阅读型",
        "storyPriority": "好读、情节丰满、持续追读优先，不追求文学腔",
    }
)


@dataclass(frozen=True)
class ReserveStoryEngineBatch:
    project_id: str
    idempotency_key: str


@dataclass(frozen=True)
class CreateManualStoryEngineBatch:
    project_id: str
    idempotency_key: str
    options: tuple[StoryEngineOption, ...]

    def __post_init__(self) -> None:
        validate_three_options(self.options)


class StoryEngineOptionResult(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    id: str
    option_order: int
    content_hash: str
    payload: StoryEngineOption


class StoryEngineBatchResult(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    id: str
    project_id: str
    source_type: Literal["provider", "manual"]
    seed_id: str
    selection_revision: int
    seed_revision_id: str
    seed_hash: str
    binding_revision_id: str | None
    binding_hash: str | None
    provider_id: str | None
    model_name_snapshot: str | None
    idempotency_key: str
    request_hash: str
    status: Literal[
        "reserved", "running", "succeeded", "failed", "outcome_unknown"
    ]
    attempt_id: str | None
    attempt_started_at: int | None
    lease_expires_at: int | None
    raw_response_text: str | None
    raw_response_hash: str | None
    public_error_code: str | None
    created_at: int
    finished_at: int | None
    options: tuple[StoryEngineOptionResult, ...]


class RecoverableStoryEngineBatchResult(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    id: str
    status: Literal["reserved", "running", "outcome_unknown"]
    public_error_code: str | None
    created_at: int
    finished_at: int | None


class StoryEngineService:
    def __init__(
        self,
        repository,
        *,
        transaction_factory,
        connection_factory,
        id_factory=None,
        clock=None,
        provider_gateway=None,
    ):
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.connection_factory = connection_factory
        self.id_factory = id_factory or (lambda: str(uuid4()))
        self.clock = clock or (lambda: int(time.time() * 1000))
        # Reserved for Task 3 dependency injection. Task 2 never calls it.
        self.provider_gateway = provider_gateway

    async def list_recoverable(
        self, project_id: str
    ) -> tuple[RecoverableStoryEngineBatchResult, ...]:
        async with self.connection_factory() as session:
            if await self.repository.read_project(session, project_id) is None:
                raise StoryEngineBatchNotFound()
            rows = await self.repository.list_recoverable_batches(
                session, project_id, limit=10
            )
        return tuple(
            RecoverableStoryEngineBatchResult(
                id=row["id"],
                status=row["status"],
                public_error_code=row.get("public_error_code"),
                created_at=int(row["created_at"]),
                finished_at=(
                    int(row["finished_at"])
                    if row.get("finished_at") is not None
                    else None
                ),
            )
            for row in rows
        )

    @staticmethod
    def _request(
        source_type: str,
        seed: dict,
        *,
        binding=None,
        options=None,
        seed_payload: SeedPayload | None = None,
        channel_profile=None,
        genre_profile=None,
        generation_config=None,
    ):
        request = {
            "sourceType": source_type,
            "seed": {
                "selectionRevision": seed["selection_revision"],
                "id": seed["seed_id"],
                "revisionId": seed["seed_revision_id"],
                "hash": seed["seed_hash"],
            },
        }
        if binding is not None:
            request["binding"] = {
                "revisionId": binding["binding_revision_id"],
                "hash": binding["binding_hash"],
            }
            request["provider"] = {
                "id": binding["provider_id"],
                "modelName": binding["model_name_snapshot"],
            }
            request["seed"]["payload"] = seed_payload.model_dump(mode="json")
            request["channelProfile"] = dict(channel_profile)
            request["genreProfile"] = dict(genre_profile)
            request["generationConfig"] = (
                dict(generation_config)
                if generation_config is not None
                else None
            )
        if options is not None:
            request["options"] = [
                option.model_dump(mode="json") for option in options
            ]
        return request

    async def _load_result(self, session, project_id: str, batch_id: str):
        batch = await self.repository.read_batch(session, project_id, batch_id)
        if batch is None:
            raise StoryEngineBatchNotFound()
        option_rows = await self.repository.list_options(
            session, project_id, batch_id
        )
        options = []
        for row in option_rows:
            payload = row["payload_json"]
            if isinstance(payload, (bytes, bytearray)):
                payload = payload.decode("utf-8")
            payload_json = (
                payload if isinstance(payload, str) else canonical_json(payload)
            )
            options.append(
                StoryEngineOptionResult(
                    id=row["id"],
                    option_order=int(row["option_order"]),
                    content_hash=row["content_hash"],
                    payload=StoryEngineOption.model_validate_json(payload_json),
                )
            )
        return StoryEngineBatchResult(
            id=batch["id"],
            project_id=batch["project_id"],
            source_type=batch["source_type"],
            seed_id=batch["seed_id"],
            selection_revision=int(batch["selection_revision"]),
            seed_revision_id=batch["seed_revision_id"],
            seed_hash=batch["seed_hash"],
            binding_revision_id=batch.get("binding_revision_id"),
            binding_hash=batch.get("binding_hash"),
            provider_id=batch.get("provider_id"),
            model_name_snapshot=batch.get("model_name_snapshot"),
            idempotency_key=batch["idempotency_key"],
            request_hash=batch["request_hash"],
            status=batch["status"],
            attempt_id=batch.get("attempt_id"),
            attempt_started_at=batch.get("attempt_started_at"),
            lease_expires_at=batch.get("lease_expires_at"),
            raw_response_text=batch.get("raw_response_text"),
            raw_response_hash=batch.get("raw_response_hash"),
            public_error_code=batch.get("public_error_code"),
            created_at=int(batch["created_at"]),
            finished_at=batch.get("finished_at"),
            options=tuple(options),
        )

    async def _replay_or_conflict(
        self, session, project_id: str, idempotency_key: str, request_hash: str
    ):
        existing = await self.repository.lock_batch_by_key(
            session, project_id, idempotency_key
        )
        if existing is None:
            return None
        if existing["request_hash"] != request_hash:
            raise StoryEngineBatchConflict()
        return await self._load_result(session, project_id, existing["id"])

    def _batch_row(
        self,
        *,
        project_id: str,
        source_type: str,
        seed: dict,
        binding: dict | None,
        idempotency_key: str,
        request: dict,
        status: str,
        now: int,
    ) -> dict:
        return {
            "id": self.id_factory(),
            "project_id": project_id,
            "selection_revision": int(seed["selection_revision"]),
            "source_type": source_type,
            "seed_id": seed["seed_id"],
            "seed_revision_id": seed["seed_revision_id"],
            "seed_hash": seed["seed_hash"],
            "binding_revision_id": binding["binding_revision_id"] if binding else None,
            "binding_hash": binding["binding_hash"] if binding else None,
            "provider_id": binding["provider_id"] if binding else None,
            "model_name_snapshot": binding["model_name_snapshot"] if binding else None,
            "idempotency_key": idempotency_key,
            "request": request,
            "request_json": canonical_json(request),
            "request_hash": canonical_hash(request),
            "status": status,
            "attempt_id": None,
            "attempt_started_at": None,
            "lease_expires_at": None,
            "raw_response_text": None,
            "raw_response_hash": None,
            "public_error_code": None,
            "created_at": now,
            "finished_at": now if status == "succeeded" else None,
        }

    def _option_rows(
        self,
        project_id: str,
        batch_id: str,
        selection_revision: int,
        options: tuple[StoryEngineOption, ...],
        now: int,
    ) -> tuple[dict, ...]:
        validate_three_options(options)
        return tuple(
            {
                "id": self.id_factory(),
                "project_id": project_id,
                "selection_revision": selection_revision,
                "batch_id": batch_id,
                "option_order": index,
                "payload_json": canonical_json(option),
                "content_hash": canonical_hash(option),
                "created_at": now,
            }
            for index, option in enumerate(options, 1)
        )

    async def create_manual(
        self, command: CreateManualStoryEngineBatch
    ) -> StoryEngineBatchResult:
        options = validate_three_options(command.options)
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(session, command.project_id) is None:
                raise StoryEngineBatchNotFound()
            seed = await self.repository.lock_selected_seed(session, command.project_id)
            if seed is None:
                raise StoryEnginePreconditionFailed()
            request = self._request("manual", seed, options=options)
            request_hash = canonical_hash(request)
            replay = await self._replay_or_conflict(
                session, command.project_id, command.idempotency_key, request_hash
            )
            if replay is not None:
                return replay
            now = self.clock()
            row = self._batch_row(
                project_id=command.project_id,
                source_type="manual",
                seed=seed,
                binding=None,
                idempotency_key=command.idempotency_key,
                request=request,
                status="succeeded",
                now=now,
            )
            await self.repository.insert_batch(session, row)
            await self.repository.insert_options(
                session,
                self._option_rows(
                    command.project_id,
                    row["id"],
                    int(seed["selection_revision"]),
                    options,
                    now,
                ),
            )
            return await self._load_result(session, command.project_id, row["id"])

    async def reserve_provider(
        self, command: ReserveStoryEngineBatch
    ) -> StoryEngineBatchResult:
        result, _, _ = await self._reserve_provider(command)
        return result

    @staticmethod
    def _seed_payload(seed: dict) -> SeedPayload:
        payload = seed["payload_json"]
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            return SeedPayload.model_validate_json(payload)
        return SeedPayload.model_validate(payload)

    async def _reserve_provider(self, command: ReserveStoryEngineBatch):
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(session, command.project_id) is None:
                raise StoryEngineBatchNotFound()
            seed = await self.repository.lock_selected_seed(session, command.project_id)
            binding = await self.repository.lock_seed_binding(
                session, command.project_id
            )
            if seed is None or binding is None:
                raise StoryEnginePreconditionFailed()
            seed_payload = self._seed_payload(seed)
            generation_config = self._generation_config(binding)
            genre_profile = {
                "schemaVersion": "writer-genre-profile-v1",
                "projectGenre": seed["project_genre"],
                "seedGenre": seed_payload.genre,
            }
            request = self._request(
                "provider",
                seed,
                binding=binding,
                seed_payload=seed_payload,
                channel_profile=DEFAULT_CHANNEL_PROFILE,
                genre_profile=genre_profile,
                generation_config=generation_config,
            )
            request_hash = canonical_hash(request)
            replay = await self._replay_or_conflict(
                session, command.project_id, command.idempotency_key, request_hash
            )
            if replay is not None:
                return replay, False, None
            now = self.clock()
            row = self._batch_row(
                project_id=command.project_id,
                source_type="provider",
                seed=seed,
                binding=binding,
                idempotency_key=command.idempotency_key,
                request=request,
                status="reserved",
                now=now,
            )
            await self.repository.insert_batch(session, row)
            result = await self._load_result(session, command.project_id, row["id"])
            return result, True, request

    @staticmethod
    def _generation_config(binding) -> dict[str, int | float] | None:
        if binding.get("provider_id") is None:
            return None
        temperature = binding.get("temperature")
        max_output_tokens = binding.get("max_output_tokens")
        if isinstance(temperature, bool) or isinstance(max_output_tokens, bool):
            return None
        try:
            normalized_temperature = float(temperature)
            normalized_max_output = int(max_output_tokens)
        except (TypeError, ValueError, OverflowError):
            return None
        if (
            not math.isfinite(normalized_temperature)
            or normalized_max_output <= 0
        ):
            return None
        return {
            "temperature": normalized_temperature,
            "maxOutputTokens": normalized_max_output,
        }

    @staticmethod
    def _provider_is_callable(
        provider,
        model_name_snapshot: str | None,
        generation_config,
    ) -> bool:
        if (
            provider is None
            or not isinstance(model_name_snapshot, str)
            or generation_config is None
        ):
            return False
        return (
            provider_is_generation_ready(provider)
            and provider["model_name"] == model_name_snapshot
        )

    @staticmethod
    def _normalize_provider_connection(provider: dict) -> dict:
        normalized = dict(provider)
        for field in ("base_url", "api_key"):
            value = normalized.get(field)
            if isinstance(value, str):
                normalized[field] = value.strip()
        return normalized

    @staticmethod
    def _connection_secrets(provider: dict) -> tuple[str, ...]:
        return normalize_provider_secrets(
            (provider.get("api_key"), provider.get("base_url"))
        )

    @classmethod
    def _response_contains_connection_secret(
        cls,
        raw_response_text: str,
        provider: dict,
    ) -> bool:
        return provider_response_text_contains_secret(
            raw_response_text,
            cls._connection_secrets(provider),
        )

    @classmethod
    def _decoded_payload_contains_connection_secret(
        cls,
        payload: object,
        provider: dict,
    ) -> bool:
        return provider_response_value_contains_secret(
            payload,
            cls._connection_secrets(provider),
        )

    @classmethod
    def _parse_provider_options(cls, raw_response_text: str, provider: dict):
        payload = json.loads(raw_response_text)
        if cls._decoded_payload_contains_connection_secret(payload, provider):
            raise ValueError("provider response rejected")
        if not isinstance(payload, dict) or set(payload) != {"options"}:
            raise ValueError("response must contain only options")
        raw_options = payload["options"]
        if not isinstance(raw_options, list) or len(raw_options) != 3:
            raise ValueError("response must contain three options")
        tuple_fields = {
            "ensembleRoles",
            "satisfactionSources",
            "longFormVariation",
            "risks",
        }
        options = []
        for raw_option in raw_options:
            if not isinstance(raw_option, dict):
                raise ValueError("option must be an object")
            normalized = {
                key: tuple(value)
                if key in tuple_fields and isinstance(value, list)
                else value
                for key, value in raw_option.items()
            }
            options.append(StoryEngineOption.model_validate(normalized))
        validated = validate_three_options(tuple(options))
        if provider_response_value_contains_secret(
            tuple(item.model_dump(mode="json") for item in validated),
            cls._connection_secrets(provider),
        ):
            raise ValueError("provider response rejected")
        return validated

    async def mark_outcome_unknown(
        self, project_id: str, batch_id: str, attempt_id: str
    ) -> StoryEngineBatchResult:
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(session, project_id) is None:
                raise ProjectNotFound()
            changed = await self.repository.cas_unknown_attempt(
                session,
                project_id,
                batch_id,
                attempt_id,
                {"finished_at": self.clock()},
            )
            if not changed:
                raise StoryEngineBatchConflict()
            return await self._load_result(session, project_id, batch_id)

    async def generate_provider(
        self, command: ReserveStoryEngineBatch
    ) -> StoryEngineBatchResult:
        batch, created, request = await self._reserve_provider(command)
        if not created:
            return batch

        async with self.transaction_factory() as session:
            if await self.repository.lock_project(session, command.project_id) is None:
                raise StoryEngineBatchNotFound()
            stored = await self.repository.read_batch(
                session, command.project_id, batch.id
            )
            if stored is None:
                raise StoryEngineBatchNotFound()
            provider = None
            if stored.get("provider_id") is not None:
                provider = await self.repository.lock_provider_connection(
                    session, stored["provider_id"]
                )
            if (
                self.provider_gateway is None
                or not self._provider_is_callable(
                    provider,
                    stored.get("model_name_snapshot"),
                    request["generationConfig"],
                )
            ):
                changed = await self.repository.cas_fail_configuration(
                    session,
                    command.project_id,
                    batch.id,
                    {"finished_at": self.clock()},
                )
                if not changed:
                    raise StoryEngineBatchConflict()
                return await self._load_result(session, command.project_id, batch.id)

            now = self.clock()
            attempt_id = self.id_factory()
            changed = await self.repository.cas_start_attempt(
                session,
                command.project_id,
                batch.id,
                {
                    "attempt_id": attempt_id,
                    "attempt_started_at": now,
                    "lease_expires_at": now + RUNNING_LEASE_MS,
                },
            )
            if not changed:
                raise StoryEngineBatchConflict()
            provider = self._normalize_provider_connection(dict(provider))

        messages = build_story_engine_messages(
            request["seed"]["payload"],
            request["channelProfile"],
            request["genreProfile"],
        )
        try:
            raw_response_text = await self.provider_gateway.generate(
                provider=provider,
                messages=messages,
                generation_config=request["generationConfig"],
            )
        except StoryEngineProviderHTTPError:
            return await self.fail_attempt(
                command.project_id, batch.id, attempt_id, "provider_failed"
            )
        except StoryEngineProviderResponseError as error:
            if error.response_hash is not None:
                return await self.fail_attempt(
                    command.project_id,
                    batch.id,
                    attempt_id,
                    "invalid_response",
                    raw_response_hash=error.response_hash,
                )
            return await self.fail_attempt(
                command.project_id, batch.id, attempt_id, "provider_failed"
            )
        except (TimeoutError, httpx.TransportError):
            return await self.mark_outcome_unknown(
                command.project_id, batch.id, attempt_id
            )

        raw_response_hash = None
        try:
            raw_response_text = validate_provider_response_text(raw_response_text)
            raw_response_hash = sha256(
                raw_response_text.encode("utf-8")
            ).hexdigest()
            if self._response_contains_connection_secret(
                raw_response_text,
                provider,
            ):
                raise ValueError("provider response rejected")
            options = self._parse_provider_options(raw_response_text, provider)
        except (TypeError, ValueError, RecursionError):
            return await self.fail_attempt(
                command.project_id,
                batch.id,
                attempt_id,
                (
                    "invalid_response"
                    if raw_response_hash is not None
                    else "provider_failed"
                ),
                raw_response_hash=raw_response_hash,
            )
        return await self.succeed_attempt(
            command.project_id,
            batch.id,
            attempt_id,
            raw_response_text,
            options,
        )

    async def get(self, project_id: str, batch_id: str) -> StoryEngineBatchResult:
        async with self.connection_factory() as session:
            if await self.repository.read_project(session, project_id) is None:
                raise StoryEngineBatchNotFound()
            return await self._load_result(session, project_id, batch_id)

    async def start_attempt(
        self, project_id: str, batch_id: str
    ) -> StoryEngineBatchResult:
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(session, project_id) is None:
                raise StoryEngineBatchNotFound()
            if await self.repository.read_batch(session, project_id, batch_id) is None:
                raise StoryEngineBatchNotFound()
            now = self.clock()
            changed = await self.repository.cas_start_attempt(
                session,
                project_id,
                batch_id,
                {
                    "attempt_id": self.id_factory(),
                    "attempt_started_at": now,
                    "lease_expires_at": now + RUNNING_LEASE_MS,
                },
            )
            if not changed:
                raise StoryEngineBatchConflict()
            return await self._load_result(session, project_id, batch_id)

    async def succeed_attempt(
        self,
        project_id: str,
        batch_id: str,
        attempt_id: str,
        raw_response_text: str,
        options: tuple[StoryEngineOption, ...],
    ) -> StoryEngineBatchResult:
        options = validate_three_options(options)
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(session, project_id) is None:
                raise StoryEngineBatchNotFound()
            batch = await self.repository.read_batch(session, project_id, batch_id)
            if batch is None:
                raise StoryEngineBatchNotFound()
            now = self.clock()
            changed = await self.repository.cas_succeed_attempt(
                session,
                project_id,
                batch_id,
                attempt_id,
                {
                    "raw_response_text": None,
                    "raw_response_hash": sha256(
                        raw_response_text.encode("utf-8")
                    ).hexdigest(),
                    "finished_at": now,
                },
            )
            if not changed:
                raise StoryEngineBatchConflict()
            await self.repository.insert_options(
                session,
                self._option_rows(
                    project_id,
                    batch_id,
                    int(batch["selection_revision"]),
                    options,
                    now,
                ),
            )
            return await self._load_result(session, project_id, batch_id)

    async def fail_attempt(
        self,
        project_id: str,
        batch_id: str,
        attempt_id: str,
        public_error_code: str,
        *,
        raw_response_hash: str | None = None,
    ) -> StoryEngineBatchResult:
        if public_error_code not in _SAFE_FAILURE_CODES:
            raise ValueError("unsupported public error code")
        if public_error_code == "invalid_response":
            if raw_response_hash is None or (
                len(raw_response_hash) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in raw_response_hash
                )
            ):
                raise ValueError("invalid response hash evidence")
        elif raw_response_hash is not None:
            raise ValueError("invalid response hash evidence")
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(session, project_id) is None:
                raise StoryEngineBatchNotFound()
            if await self.repository.read_batch(session, project_id, batch_id) is None:
                raise StoryEngineBatchNotFound()
            changed = await self.repository.cas_fail_attempt(
                session,
                project_id,
                batch_id,
                attempt_id,
                {
                    "raw_response_text": None,
                    "raw_response_hash": raw_response_hash,
                    "public_error_code": public_error_code,
                    "finished_at": self.clock(),
                },
            )
            if not changed:
                raise StoryEngineBatchConflict()
            return await self._load_result(session, project_id, batch_id)

    async def reconcile(
        self, project_id: str, batch_id: str
    ) -> StoryEngineBatchResult:
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(session, project_id) is None:
                raise StoryEngineBatchNotFound()
            batch = await self.repository.read_batch(session, project_id, batch_id)
            if batch is None:
                raise StoryEngineBatchNotFound()
            if batch["status"] in _TERMINAL_STATUSES or batch["source_type"] == "manual":
                return await self._load_result(session, project_id, batch_id)
            now = self.clock()
            if batch["status"] == "reserved":
                await self.repository.cas_reconcile_reserved(
                    session,
                    project_id,
                    batch_id,
                    {"finished_at": now},
                    now - RESERVED_TIMEOUT_MS,
                )
            elif batch["status"] == "running":
                await self.repository.cas_reconcile_running(
                    session,
                    project_id,
                    batch_id,
                    {"attempt_id": batch["attempt_id"], "finished_at": now},
                    now,
                )
            return await self._load_result(session, project_id, batch_id)
