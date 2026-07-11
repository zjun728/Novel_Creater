"""Transactional orchestration for auditable story-engine batches."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import time
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.story_engines import StoryEngineOption, validate_three_options
from backend.http_errors import (
    StoryEngineBatchConflict,
    StoryEngineBatchNotFound,
    StoryEnginePreconditionFailed,
)


RESERVED_TIMEOUT_MS = 300_000
PROVIDER_TIMEOUT_SECONDS = 180
RUNNING_LEASE_MS = 240_000
_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "outcome_unknown"})
_SAFE_FAILURE_CODES = frozenset(
    {"provider_failed", "provider_timeout", "invalid_response"}
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

    @staticmethod
    def _request(source_type: str, seed: dict, *, binding=None, options=None):
        request = {
            "sourceType": source_type,
            "seed": {
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
        options: tuple[StoryEngineOption, ...],
        now: int,
    ) -> tuple[dict, ...]:
        validate_three_options(options)
        return tuple(
            {
                "id": self.id_factory(),
                "project_id": project_id,
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
                self._option_rows(command.project_id, row["id"], options, now),
            )
            return await self._load_result(session, command.project_id, row["id"])

    async def reserve_provider(
        self, command: ReserveStoryEngineBatch
    ) -> StoryEngineBatchResult:
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(session, command.project_id) is None:
                raise StoryEngineBatchNotFound()
            seed = await self.repository.lock_selected_seed(session, command.project_id)
            binding = await self.repository.lock_seed_binding(
                session, command.project_id
            )
            if seed is None or binding is None:
                raise StoryEnginePreconditionFailed()
            request = self._request("provider", seed, binding=binding)
            request_hash = canonical_hash(request)
            replay = await self._replay_or_conflict(
                session, command.project_id, command.idempotency_key, request_hash
            )
            if replay is not None:
                return replay
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
            return await self._load_result(session, command.project_id, row["id"])

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
                    "raw_response_text": raw_response_text,
                    "raw_response_hash": sha256(
                        raw_response_text.encode("utf-8")
                    ).hexdigest(),
                    "finished_at": now,
                },
            )
            if not changed:
                raise StoryEngineBatchConflict()
            await self.repository.insert_options(
                session, self._option_rows(project_id, batch_id, options, now)
            )
            return await self._load_result(session, project_id, batch_id)

    async def fail_attempt(
        self,
        project_id: str,
        batch_id: str,
        attempt_id: str,
        public_error_code: str,
    ) -> StoryEngineBatchResult:
        if public_error_code not in _SAFE_FAILURE_CODES:
            raise ValueError("unsupported public error code")
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
                {"public_error_code": public_error_code, "finished_at": self.clock()},
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
