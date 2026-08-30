"""Explicit versioned saves for global Topic Center library records."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import time
from typing import Any, Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.topics import (
    TopicCandidatePayload,
    TopicDirectionPayload,
    TopicEvidenceRef,
    TopicFailure,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _new_id() -> str:
    return str(uuid4())


class _LibraryCommand(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )


PayloadT = TypeVar("PayloadT", TopicDirectionPayload, TopicCandidatePayload)


class _SaveTopicValue(_LibraryCommand, Generic[PayloadT]):
    discussion_id: str = Field(alias="discussionId", min_length=1, max_length=36)
    message_id: str = Field(alias="messageId", min_length=1, max_length=36)
    payload: PayloadT
    evidence: tuple[TopicEvidenceRef, ...] = Field(default=(), max_length=4)
    idempotency_key: str = Field(
        alias="idempotencyKey",
        pattern=r"^[A-Za-z0-9_-]{64}$",
    )

    @field_validator("evidence", mode="before")
    @classmethod
    def freeze_evidence(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("evidence")
    @classmethod
    def unique_evidence(
        cls,
        value: tuple[TopicEvidenceRef, ...],
    ) -> tuple[TopicEvidenceRef, ...]:
        identities = tuple(item.snapshot_id for item in value)
        if len(identities) != len(set(identities)):
            raise ValueError("topic evidence IDs must be unique")
        return value


class SaveTopicDirection(_SaveTopicValue[TopicDirectionPayload]):
    direction_id: str | None = Field(
        default=None,
        alias="directionId",
        min_length=1,
        max_length=36,
    )
    expected_version: int | None = Field(
        default=None,
        alias="expectedVersion",
        gt=0,
    )

    @model_validator(mode="after")
    def matching_version_target(self):
        if (self.direction_id is None) != (self.expected_version is None):
            raise ValueError("direction ID and expected version must be supplied together")
        return self


class SaveTopicCandidate(_SaveTopicValue[TopicCandidatePayload]):
    candidate_id: str | None = Field(
        default=None,
        alias="candidateId",
        min_length=1,
        max_length=36,
    )
    expected_version: int | None = Field(
        default=None,
        alias="expectedVersion",
        gt=0,
    )

    @model_validator(mode="after")
    def matching_version_target(self):
        if (self.candidate_id is None) != (self.expected_version is None):
            raise ValueError("candidate ID and expected version must be supplied together")
        return self


class ArchiveTopicCandidate(_LibraryCommand):
    candidate_id: str = Field(alias="candidateId", min_length=1, max_length=36)
    expected_version: int = Field(alias="expectedVersion", gt=0)


class TopicLibraryService:
    def __init__(
        self,
        repository,
        *,
        transaction_factory,
        connection_factory,
        id_factory: Callable[[], str] = _new_id,
        clock: Callable[[], int] = _now_ms,
    ) -> None:
        self._repository = repository
        self._transaction = transaction_factory
        self._connection = connection_factory
        self._id = id_factory
        self._clock = clock

    @staticmethod
    def _result(row: Mapping, kind: str) -> dict[str, Any]:
        return {
            f"{kind}Id": row[f"{kind}_id"],
            "versionId": row["id"],
            "version": int(row["version"]),
            "contentHash": row["content_hash"],
            "payload": row["payload"],
            "basis": row["basis"],
        }

    @staticmethod
    def _request_hash(command: BaseModel) -> str:
        return canonical_hash(command.model_dump(mode="json", by_alias=True))

    @staticmethod
    def _basis(message: Mapping, evidence) -> dict[str, Any]:
        return {
            "message": {
                "id": message["id"],
                "contentHash": message["content_hash"],
            },
            "evidence": [
                {
                    "snapshotId": item["id"],
                    "contentHash": item["content_hash"],
                    "sourceId": item["source_id"],
                }
                for item in evidence
            ],
        }

    async def _lock_basis(self, session, command):
        discussion = await self._repository.lock_discussion(
            session,
            command.discussion_id,
        )
        if discussion is None:
            raise TopicFailure("TOPIC_NOT_FOUND")
        message = await self._repository.lock_message(
            session,
            discussion_id=command.discussion_id,
            message_id=command.message_id,
        )
        if message is None:
            raise TopicFailure("TOPIC_NOT_FOUND")
        evidence = await self._repository.lock_snapshot_evidence(
            session,
            command.evidence,
        )
        return self._basis(message, evidence)

    @staticmethod
    def _replay(existing: Mapping, request_hash: str, kind: str):
        if existing["request_hash"] != request_hash:
            raise TopicFailure("TOPIC_REQUEST_CONFLICT")
        return TopicLibraryService._result(existing, kind)

    async def save_direction(self, command: SaveTopicDirection):
        request_hash = self._request_hash(command)
        async with self._transaction() as session:
            identity = (
                await self._repository.lock_direction(
                    session,
                    command.direction_id,
                )
                if command.direction_id is not None
                else None
            )
            existing = await self._repository.find_direction_version_by_key(
                session,
                command.idempotency_key,
            )
            if existing is not None:
                return self._replay(existing, request_hash, "direction")
            basis = await self._lock_basis(session, command)
            now = self._clock()
            if command.direction_id is None:
                direction_id = self._id()
                version = 1
                await self._repository.insert_direction_identity(
                    session,
                    {
                        "id": direction_id,
                        "current_version": version,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            else:
                direction_id = command.direction_id
                if identity is None:
                    raise TopicFailure("TOPIC_NOT_FOUND")
                if identity["current_version"] != command.expected_version:
                    raise TopicFailure("TOPIC_VERSION_CONFLICT")
                version = command.expected_version + 1
            row = self._version_row(
                command=command,
                kind="direction",
                identity_id=direction_id,
                version=version,
                basis=basis,
                request_hash=request_hash,
                now=now,
            )
            await self._repository.insert_direction_version(session, row)
            if command.direction_id is not None:
                changed = await self._repository.advance_direction(
                    session,
                    direction_id=direction_id,
                    expected_version=command.expected_version,
                    version=version,
                    updated_at=now,
                )
                if not changed:
                    raise TopicFailure("TOPIC_VERSION_CONFLICT")
            return self._result({**row, "payload": command.payload.model_dump(
                mode="json", by_alias=True
            ), "basis": basis}, "direction")

    async def save_candidate(self, command: SaveTopicCandidate):
        request_hash = self._request_hash(command)
        async with self._transaction() as session:
            identity = (
                await self._repository.lock_candidate(
                    session,
                    command.candidate_id,
                )
                if command.candidate_id is not None
                else None
            )
            existing = await self._repository.find_candidate_version_by_key(
                session,
                command.idempotency_key,
            )
            if existing is not None:
                return self._replay(existing, request_hash, "candidate")
            basis = await self._lock_basis(session, command)
            now = self._clock()
            if command.candidate_id is None:
                candidate_id = self._id()
                version = 1
                await self._repository.insert_candidate_identity(
                    session,
                    {
                        "id": candidate_id,
                        "status": "active",
                        "current_version": version,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            else:
                candidate_id = command.candidate_id
                if identity is None:
                    raise TopicFailure("TOPIC_NOT_FOUND")
                if identity["status"] == "archived":
                    raise TopicFailure("TOPIC_CANDIDATE_ARCHIVED")
                if identity["current_version"] != command.expected_version:
                    raise TopicFailure("TOPIC_VERSION_CONFLICT")
                version = command.expected_version + 1
            row = self._version_row(
                command=command,
                kind="candidate",
                identity_id=candidate_id,
                version=version,
                basis=basis,
                request_hash=request_hash,
                now=now,
            )
            await self._repository.insert_candidate_version(session, row)
            if command.candidate_id is not None:
                changed = await self._repository.advance_candidate(
                    session,
                    candidate_id=candidate_id,
                    expected_version=command.expected_version,
                    version=version,
                    updated_at=now,
                )
                if not changed:
                    raise TopicFailure("TOPIC_VERSION_CONFLICT")
            return self._result({**row, "payload": command.payload.model_dump(
                mode="json", by_alias=True
            ), "basis": basis}, "candidate")

    def _version_row(
        self,
        *,
        command,
        kind: str,
        identity_id: str,
        version: int,
        basis: dict[str, Any],
        request_hash: str,
        now: int,
    ) -> dict[str, Any]:
        payload = command.payload.model_dump(mode="json", by_alias=True)
        return {
            "id": self._id(),
            f"{kind}_id": identity_id,
            "version": version,
            "payload_json": canonical_json(payload),
            "content_hash": canonical_hash(payload),
            "discussion_id": command.discussion_id,
            "basis_json": canonical_json(basis),
            "basis_hash": canonical_hash(basis),
            "idempotency_key": command.idempotency_key,
            "request_hash": request_hash,
            "created_at": now,
        }

    async def archive_candidate(self, command: ArchiveTopicCandidate):
        async with self._transaction() as session:
            candidate = await self._repository.lock_candidate(
                session,
                command.candidate_id,
            )
            if candidate is None:
                raise TopicFailure("TOPIC_NOT_FOUND")
            if candidate["status"] == "archived":
                raise TopicFailure("TOPIC_CANDIDATE_ARCHIVED")
            if candidate["current_version"] != command.expected_version:
                raise TopicFailure("TOPIC_VERSION_CONFLICT")
            now = self._clock()
            changed = await self._repository.archive_candidate(
                session,
                candidate_id=command.candidate_id,
                expected_version=command.expected_version,
                updated_at=now,
            )
            if not changed:
                raise TopicFailure("TOPIC_VERSION_CONFLICT")
            return {
                "candidateId": command.candidate_id,
                "version": command.expected_version,
                "status": "archived",
                "updatedAt": now,
            }

    async def list_directions(self, *, offset: int = 0, limit: int = 50):
        async with self._connection() as session:
            return await self._repository.list_directions(
                session,
                offset=offset,
                limit=limit,
            )

    async def read_direction(self, direction_id: str):
        async with self._connection() as session:
            value = await self._repository.read_direction(session, direction_id)
        if value is None:
            raise TopicFailure("TOPIC_NOT_FOUND")
        return value

    async def list_candidates(
        self,
        *,
        status: str = "active",
        offset: int = 0,
        limit: int = 50,
    ):
        async with self._connection() as session:
            return await self._repository.list_candidates(
                session,
                status=status,
                offset=offset,
                limit=limit,
            )

    async def read_candidate(self, candidate_id: str):
        async with self._connection() as session:
            value = await self._repository.read_candidate(session, candidate_id)
        if value is None:
            raise TopicFailure("TOPIC_NOT_FOUND")
        return value


__all__ = (
    "ArchiveTopicCandidate",
    "SaveTopicCandidate",
    "SaveTopicDirection",
    "TopicLibraryService",
)
