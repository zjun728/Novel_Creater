"""Atomic internal service for appending one Canon revision."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import re
import time
from typing import Literal
from uuid import uuid4

from backend.database import transaction
from backend.domain.canon import (
    CanonConflict, CanonEventInput, CanonValidationError, EntityType,
    find_hard_conflicts, normalize_name, resolve_alias, thaw_json,
)
from backend.services.projections import build_projection_bundle


_IDEMPOTENCY_KEY = re.compile(r"[0-9a-f]{64}\Z")
_RUNTIME_SOURCE_TYPES = frozenset({"finalization", "manual_test"})
SourceType = Literal["finalization", "manual_test"]


def _id(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CanonValidationError(
            f"{field_name} must be a non-empty trimmed string"
        )


def _tuple(value: object, field_name: str) -> None:
    if type(value) is not tuple:
        raise CanonValidationError(f"{field_name} must be a tuple")


def _unique_ids(values: tuple, noun: str) -> None:
    seen = set()
    for value in values:
        if value.id in seen:
            raise CanonValidationError(f"duplicate {noun} id: {value.id}")
        seen.add(value.id)


@dataclass(frozen=True)
class CanonEntityCreate:
    id: str
    entity_type: EntityType
    canonical_name: str

    def __post_init__(self) -> None:
        _id(self.id, "entity id")
        try:
            entity_type = EntityType(self.entity_type)
        except (TypeError, ValueError) as exc:
            raise CanonValidationError("entity_type is not allowed") from exc
        object.__setattr__(self, "entity_type", entity_type)
        normalize_name(self.canonical_name)


@dataclass(frozen=True)
class AliasCreate:
    id: str
    entity_id: str
    alias: str

    def __post_init__(self) -> None:
        _id(self.id, "alias id")
        _id(self.entity_id, "alias entity_id")
        normalize_name(self.alias)


@dataclass(frozen=True)
class CanonEventCreate:
    id: str
    event: CanonEventInput

    def __post_init__(self) -> None:
        _id(self.id, "event id")
        if type(self.event) is not CanonEventInput:
            raise CanonValidationError("event must be a CanonEventInput")
        if self.event.entity_id is not None:
            _id(self.event.entity_id, "event entity_id")


@dataclass(frozen=True)
class CommitCanonRevision:
    project_id: str
    expected_head: int
    idempotency_key: str
    source_type: SourceType
    source_id: str | None
    entities: tuple[CanonEntityCreate, ...]
    aliases: tuple[AliasCreate, ...]
    events: tuple[CanonEventCreate, ...]

    def __post_init__(self) -> None:
        _id(self.project_id, "project_id")
        if type(self.expected_head) is not int or self.expected_head < 0:
            raise CanonValidationError("expected_head must be a non-negative integer")
        if not isinstance(self.idempotency_key, str) or not _IDEMPOTENCY_KEY.fullmatch(
            self.idempotency_key
        ):
            raise CanonValidationError(
                "idempotency_key must be exactly 64 lowercase hexadecimal characters"
            )
        if self.source_type not in _RUNTIME_SOURCE_TYPES:
            raise CanonValidationError(
                "source_type must be finalization or manual_test for ordinary commits"
            )
        if self.source_id is not None:
            _id(self.source_id, "source_id")
        for field_name, expected_type in (
            ("entities", CanonEntityCreate),
            ("aliases", AliasCreate),
            ("events", CanonEventCreate),
        ):
            values = getattr(self, field_name)
            _tuple(values, field_name)
            if any(type(value) is not expected_type for value in values):
                raise CanonValidationError(
                    f"{field_name} must contain only {expected_type.__name__} values"
                )
        _unique_ids(self.entities, "entity")
        _unique_ids(self.aliases, "alias")
        _unique_ids(self.events, "event")


@dataclass(frozen=True)
class CommitCanonResult:
    revision_id: str
    revision_number: int
    projection_hash: str
    idempotent: bool

    def __post_init__(self) -> None:
        _id(self.revision_id, "revision_id")
        if type(self.revision_number) is not int or self.revision_number < 0:
            raise CanonValidationError(
                "revision_number must be a non-negative integer"
            )
        if not isinstance(self.projection_hash, str) or not _IDEMPOTENCY_KEY.fullmatch(
            self.projection_hash
        ):
            raise CanonValidationError(
                "projection_hash must be exactly 64 lowercase hexadecimal characters"
            )
        if type(self.idempotent) is not bool:
            raise CanonValidationError("idempotent must be a boolean")

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> "CommitCanonResult":
        return cls(
            revision_id=row["id"],
            revision_number=row["revision_number"],
            projection_hash=row["content_hash"],
            idempotent=True,
        )


class CanonHeadMismatch(RuntimeError):
    def __init__(self, *, expected: int, actual: int):
        self.expected = expected
        self.actual = actual
        super().__init__(f"expected Canon head {expected}, found {actual}")


class CanonHardConflictError(RuntimeError):
    def __init__(self, conflicts: tuple[CanonConflict, ...]):
        self.conflicts = conflicts
        super().__init__(f"Canon commit has {len(conflicts)} hard conflict(s)")


class CanonService:
    def __init__(
        self, repository, *, transaction_factory=transaction,
        id_factory=None, clock=None,
    ):
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.id_factory = id_factory or (lambda: str(uuid4()))
        self.clock = clock or (lambda: int(time.time() * 1000))

    def _created_at(self) -> int:
        value = self.clock()
        if isinstance(value, datetime):
            return int(value.timestamp() * 1000)
        if type(value) is int and value >= 0:
            return value
        raise CanonValidationError("clock must return a datetime or non-negative integer")

    async def commit(self, request: CommitCanonRevision) -> CommitCanonResult:
        if type(request) is not CommitCanonRevision:
            raise CanonValidationError("request must be a CommitCanonRevision")
        async with self.transaction_factory() as session:
            head = await self.repository.lock_head(session, request.project_id)
            existing = await self.repository.find_idempotent(
                session, request.project_id, request.idempotency_key,
            )
            if existing is not None:
                return CommitCanonResult.from_row(existing)
            if head != request.expected_head:
                raise CanonHeadMismatch(expected=request.expected_head, actual=head)

            await self._validate_references(session, request)
            incoming = tuple(item.event for item in request.events)
            scopes = tuple(sorted({
                (event.entity_id, event.field_path)
                for event in incoming
                if event.fact_kind.value == "stable_definition"
            }))
            existing_events = await self.repository.list_active_stable_events(
                session, request.project_id, scopes,
            )
            conflicts = find_hard_conflicts(existing_events, incoming)
            if conflicts:
                raise CanonHardConflictError(conflicts)

            revision_number = head + 1
            revision_id = self.id_factory()
            _id(revision_id, "generated revision id")
            created_at = self._created_at()
            revision = {
                "id": revision_id,
                "project_id": request.project_id,
                "revision_number": revision_number,
                "parent_revision_number": head,
                "idempotency_key": request.idempotency_key,
                "source_type": request.source_type,
                "source_id": request.source_id,
                "content_hash": "0" * 64,
                "created_at": created_at,
            }
            await self.repository.insert_revision(session, revision)
            await self.repository.insert_entities(
                session, self._entity_rows(request, revision_number, created_at),
            )
            await self.repository.insert_aliases(
                session, self._alias_rows(request, revision_number, created_at),
            )
            await self.repository.insert_events(
                session,
                self._event_rows(
                    request, revision_id, revision_number, created_at,
                ),
            )
            events = await self.repository.list_confirmed_events(
                session, request.project_id,
            )
            bundle = build_projection_bundle(revision_number, events)
            await self.repository.replace_projections(
                session, request.project_id, bundle,
            )
            await self.repository.set_revision_content_hash(
                session, revision_id, bundle.content_hash,
            )
            await self.repository.advance_heads(
                session, request.project_id, revision_number, bundle.content_hash,
            )
            return CommitCanonResult(
                revision_id=revision_id,
                revision_number=revision_number,
                projection_hash=bundle.content_hash,
                idempotent=False,
            )

    async def _validate_references(self, session, request: CommitCanonRevision) -> None:
        incoming_ids = {item.id for item in request.entities}
        referenced_ids = {item.entity_id for item in request.aliases}
        referenced_ids.update(
            item.event.entity_id
            for item in request.events
            if item.event.entity_id is not None
        )
        required_existing = tuple(sorted(referenced_ids - incoming_ids))
        existing_ids = set(await self.repository.list_existing_entity_ids(
            session, request.project_id, required_existing,
        ))
        missing = set(required_existing) - existing_ids
        if missing:
            raise CanonValidationError(
                f"unknown entity_id: {sorted(missing)[0]}"
            )
        for normalized_alias in sorted({
            normalize_name(item.alias) for item in request.aliases
        }):
            rows = await self.repository.list_alias_matches(
                session, request.project_id, normalized_alias,
            )
            resolve_alias(normalized_alias, rows)

    @staticmethod
    def _entity_rows(request, revision_number: int, created_at: int):
        return tuple({
            "id": item.id, "project_id": request.project_id,
            "entity_type": item.entity_type.value,
            "canonical_name": item.canonical_name.strip(),
            "normalized_name": normalize_name(item.canonical_name),
            "created_revision": revision_number, "created_at": created_at,
        } for item in request.entities)

    @staticmethod
    def _alias_rows(request, revision_number: int, created_at: int):
        return tuple({
            "id": item.id, "project_id": request.project_id,
            "entity_id": item.entity_id, "alias": item.alias.strip(),
            "normalized_alias": normalize_name(item.alias),
            "created_revision": revision_number, "created_at": created_at,
        } for item in request.aliases)

    @staticmethod
    def _event_rows(
        request, revision_id: str, revision_number: int, created_at: int,
    ):
        rows = []
        for event_order, item in enumerate(request.events, start=1):
            event = item.event
            rows.append({
                "id": item.id, "project_id": request.project_id,
                "revision_id": revision_id, "revision_number": revision_number,
                "event_order": event_order, "entity_id": event.entity_id,
                "fact_kind": event.fact_kind.value,
                "field_path": event.field_path,
                "value": thaw_json(event.value),
                "evidence": thaw_json(event.evidence),
                "effective_start_chapter": event.effective_start_chapter,
                "effective_end_chapter": event.effective_end_chapter,
                "assertion_operator": event.assertion_operator.value,
                "value_cardinality": event.value_cardinality.value,
                "confirmation_status": event.confirmation_status.value,
                "created_at": created_at,
            })
        return tuple(rows)
