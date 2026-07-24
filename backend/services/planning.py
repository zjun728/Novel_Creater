"""Transactional lifecycle for the single revisioned Planning aggregate."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Any, Callable, Mapping
from uuid import uuid4

from pydantic import ValidationError

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.planning import (
    DraftPlanningAggregate,
    PlanningAggregate,
    PlanningDomainError,
    normalize_planning_aggregate,
    validate_confirmable_planning,
)
from backend.http_errors import ProjectArchived as RepositoryProjectArchived


_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_BASIS_FIELDS = (
    "selection_revision",
    "seed_id",
    "seed_revision_id",
    "seed_hash",
    "contract_revision",
    "creation_contract_id",
    "creation_hash",
    "style_contract_id",
    "style_hash",
    "bible_revision",
    "bible_revision_id",
    "bible_hash",
)


class PlanningError(RuntimeError):
    pass


class PlanningNotFound(PlanningError):
    pass


class PlanningArchived(PlanningError):
    pass


class PlanningRequestInvalid(PlanningError):
    pass


class PlanningPreconditionFailed(PlanningError):
    pass


class PlanningConflict(PlanningError):
    pass


@dataclass(frozen=True)
class CreatePlanningDraft:
    project_id: str
    idempotency_key: str


@dataclass(frozen=True)
class SavePlanningDraft:
    project_id: str
    draft_id: str
    expected_revision: int
    expected_hash: str
    content: Mapping[str, object]
    idempotency_key: str


@dataclass(frozen=True)
class ConfirmPlanningDraft:
    project_id: str
    draft_id: str
    expected_draft_revision: int
    expected_draft_hash: str
    idempotency_key: str


@dataclass(frozen=True)
class PlanningDraftResult:
    project_id: str
    draft_id: str
    base_head_revision: int
    draft_revision: int
    content_hash: str
    content: PlanningAggregate
    status: str
    capacity_policy: dict[str, int]


@dataclass(frozen=True)
class PlanningRevisionResult:
    project_id: str
    planning_revision_id: str
    revision: int
    parent_revision: int
    content_hash: str
    content: PlanningAggregate


@dataclass(frozen=True)
class PlanningHeadResult:
    revision: int
    planning_revision_id: str | None
    content_hash: str | None


@dataclass(frozen=True)
class PlanningCapabilities:
    view: bool
    edit: bool
    confirm: bool
    generate: bool


@dataclass(frozen=True)
class PlanningState:
    project_id: str
    basis_status: str
    head: PlanningHeadResult
    draft: PlanningDraftResult | None
    future_plan: PlanningAggregate | None
    actual_progress: tuple[object, ...]
    canon_projection_status: dict[str, object]
    capacity_policy: dict[str, int] | None
    capabilities: PlanningCapabilities
    archived: bool


class PlanningService:
    def __init__(
        self,
        repository,
        *,
        transaction_factory,
        connection_factory=None,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], int] | None = None,
        failpoint: Callable[[str], None] | None = None,
    ):
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.connection_factory = connection_factory
        self.id_factory = id_factory or (lambda: str(uuid4()))
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.failpoint = failpoint

    async def create_draft(
        self, command: CreatePlanningDraft
    ) -> PlanningDraftResult:
        self._validate_project_and_key(command.project_id, command.idempotency_key)
        async with self.transaction_factory() as session:
            await self._require_active_project(session, command.project_id)
            basis = await self._require_current_basis(session, command.project_id)
            head = await self._require_head(session, command.project_id)
            active = await self.repository.read_active_draft(
                session, command.project_id
            )
            if active is not None and self._basis_matches(active, basis):
                return self._draft_result(active, basis)
            if active is not None:
                if not await self.repository.supersede_draft(
                    session,
                    command.project_id,
                    active["id"],
                    self.clock(),
                ):
                    raise PlanningConflict("active Planning Draft changed")

            content = (
                self._planning_from_json(head["content_json"])
                if int(head["revision"]) > 0
                else self._empty_planning()
            )
            now = self.clock()
            row = {
                "id": self.id_factory(),
                "project_id": command.project_id,
                "active_slot": 1,
                "base_head_revision": int(head["revision"]),
                "draft_revision": 1,
                **self._basis_values(basis),
                "content_json": self._planning_json(content),
                "content_hash": content.content_hash,
                "source_attempt_id": None,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }
            if not await self.repository.insert_draft(session, row):
                raise PlanningConflict("Planning Draft was not created")
            return self._draft_result(row, basis)

    async def save_draft(
        self, command: SavePlanningDraft
    ) -> PlanningDraftResult:
        self._validate_save(command)
        superseded = False
        result = None
        async with self.transaction_factory() as session:
            await self._require_active_project(session, command.project_id)
            basis = await self._require_current_basis(session, command.project_id)
            head = await self._require_head(session, command.project_id)
            draft = await self.repository.read_draft(
                session, command.project_id, command.draft_id
            )
            self._require_active_draft(draft)
            if not self._basis_matches(draft, basis):
                if not await self.repository.supersede_draft(
                    session,
                    command.project_id,
                    command.draft_id,
                    self.clock(),
                ):
                    raise PlanningConflict("Planning Draft changed")
                superseded = True
            else:
                self._require_draft_cas(
                    draft,
                    command.expected_revision,
                    command.expected_hash,
                )
                previous_confirmed = (
                    self._planning_from_json(head["content_json"])
                    if int(head["revision"]) > 0
                    else None
                )
                previous_draft = self._planning_from_json(draft["content_json"])
                try:
                    normalized = normalize_planning_aggregate(
                        DraftPlanningAggregate.model_validate(command.content),
                        previous_confirmed=previous_confirmed,
                        previous_draft=previous_draft,
                        id_factory=self.id_factory,
                    )
                except ValidationError as exc:
                    raise PlanningRequestInvalid(
                        "Planning content is invalid"
                    ) from exc
                except PlanningDomainError as exc:
                    raise PlanningRequestInvalid(str(exc)) from exc
                row = {
                    **draft,
                    "draft_revision": int(draft["draft_revision"]) + 1,
                    "content_json": self._planning_json(normalized),
                    "content_hash": normalized.content_hash,
                    "status": "active",
                    "updated_at": self.clock(),
                }
                if not await self.repository.update_draft_cas(
                    session,
                    row,
                    expected_revision=command.expected_revision,
                    expected_hash=command.expected_hash,
                ):
                    raise PlanningConflict("Planning draft revision conflict")
                result = self._draft_result(row, basis)
        if superseded:
            raise PlanningPreconditionFailed(
                "Planning Draft is superseded by the current Seed, Contract, or Bible"
            )
        assert result is not None
        return result

    async def confirm_draft(
        self, command: ConfirmPlanningDraft
    ) -> PlanningRevisionResult:
        self._validate_confirm(command)
        fingerprint = canonical_hash(
            {
                "projectId": command.project_id,
                "draftId": command.draft_id,
                "draftRevision": command.expected_draft_revision,
                "draftHash": command.expected_draft_hash,
            }
        )
        superseded = False
        result = None
        async with self.transaction_factory() as session:
            await self._require_active_project(session, command.project_id)
            basis = await self._require_current_basis(session, command.project_id)
            head = await self._require_head(session, command.project_id)
            draft = await self.repository.read_draft(
                session, command.project_id, command.draft_id
            )
            if draft is None:
                raise PlanningNotFound("Planning Draft not found")
            projection = await self.repository.lock_projection_head(
                session, command.project_id
            )
            if projection is None:
                raise PlanningPreconditionFailed("Canon/Projection head is missing")
            request = await self.repository.find_confirmation(
                session, command.project_id, command.idempotency_key
            )
            if request is not None:
                if request["request_fingerprint"] != fingerprint:
                    raise PlanningConflict("idempotency key fingerprint conflict")
                if request["status"] == "succeeded":
                    result = await self._confirmed_result(
                        session,
                        command.project_id,
                        int(request["result_revision"]),
                        request["result_hash"],
                    )
                    return result
                raise PlanningConflict("Planning confirmation is pending")

            if draft["status"] != "active" or draft.get("active_slot") != 1:
                raise PlanningConflict("Planning Draft is not active")
            if not self._basis_matches(draft, basis):
                if not await self.repository.supersede_draft(
                    session,
                    command.project_id,
                    command.draft_id,
                    self.clock(),
                ):
                    raise PlanningConflict("Planning Draft changed")
                superseded = True
            else:
                self._require_draft_cas(
                    draft,
                    command.expected_draft_revision,
                    command.expected_draft_hash,
                )
                canon_revision = int(projection["canon_revision_number"])
                projection_revision = int(
                    projection["projection_revision_number"]
                )
                if canon_revision != projection_revision:
                    raise PlanningPreconditionFailed(
                        "Canon and Projection are not synchronized"
                    )
                now = self.clock()
                request_row = {
                    "id": self.id_factory(),
                    "project_id": command.project_id,
                    "planning_draft_id": command.draft_id,
                    "draft_revision": command.expected_draft_revision,
                    "draft_hash": command.expected_draft_hash,
                    "expected_head_revision": int(head["revision"]),
                    "idempotency_key": command.idempotency_key,
                    "request_fingerprint": fingerprint,
                    "status": "pending",
                    "created_at": now,
                }
                if not await self.repository.insert_confirmation_pending(
                    session, request_row
                ):
                    raise PlanningConflict("Planning confirmation was not reserved")
                self._hit("after_confirmation_pending")

                content = self._planning_from_json(draft["content_json"])
                try:
                    validate_confirmable_planning(content)
                except PlanningDomainError as exc:
                    raise PlanningPreconditionFailed(str(exc)) from exc
                revision_number = int(head["revision"]) + 1
                revision_row = {
                    "id": self.id_factory(),
                    "project_id": command.project_id,
                    "revision": revision_number,
                    "parent_revision": int(head["revision"]),
                    **self._basis_values(basis),
                    "content_json": self._planning_json(content),
                    "content_hash": content.content_hash,
                    "created_at": now,
                }
                if not await self.repository.insert_revision(
                    session, revision_row
                ):
                    raise PlanningConflict("Planning revision was not inserted")
                self._hit("after_revision_insert")

                head_row = {
                    "project_id": command.project_id,
                    "revision": revision_number,
                    "planning_revision_id": revision_row["id"],
                    "content_hash": content.content_hash,
                    "updated_at": now,
                }
                if not await self.repository.advance_head_cas(
                    session, head_row, int(head["revision"])
                ):
                    raise PlanningConflict("Planning head revision conflict")
                self._hit("after_head_advance")

                terminal_draft = {
                    **draft,
                    "status": "confirmed",
                    "updated_at": now,
                }
                if not await self.repository.update_draft_cas(
                    session,
                    terminal_draft,
                    expected_revision=command.expected_draft_revision,
                    expected_hash=command.expected_draft_hash,
                ):
                    raise PlanningConflict("Planning Draft changed during confirmation")
                self._hit("after_draft_confirmed")

                confirmation_row = {
                    "project_id": command.project_id,
                    "idempotency_key": command.idempotency_key,
                    "request_fingerprint": fingerprint,
                    "status": "succeeded",
                    "planning_revision_id": revision_row["id"],
                    "result_revision": revision_number,
                    "result_hash": content.content_hash,
                    "completed_at": now,
                }
                if not await self.repository.finish_confirmation(
                    session, confirmation_row
                ):
                    raise PlanningConflict("Planning confirmation was not completed")
                self._hit("after_confirmation_succeeded")
                result = self._revision_result(revision_row)
        if superseded:
            raise PlanningPreconditionFailed(
                "Planning Draft is superseded by the current Seed, Contract, or Bible"
            )
        assert result is not None
        return result

    async def history(self, project_id: str) -> tuple[PlanningRevisionResult, ...]:
        self._validate_project(project_id)
        async with self._read_connection() as session:
            project = await self.repository.read_project_any(session, project_id)
            if project is None:
                raise PlanningNotFound("Project not found")
            rows = await self.repository.list_revisions(session, project_id)
            return tuple(self._revision_result(row) for row in rows)

    async def get_state(self, project_id: str) -> PlanningState:
        self._validate_project(project_id)
        async with self._read_connection() as session:
            project = await self.repository.read_project_any(session, project_id)
            if project is None:
                raise PlanningNotFound("Project not found")
            basis = await self.repository.read_current_basis(session, project_id)
            head = await self.repository.lock_planning_head(session, project_id)
            if head is None:
                raise PlanningPreconditionFailed("Planning head is missing")
            draft_row = await self.repository.read_active_draft(session, project_id)
            projection = await self.repository.read_projection_head(
                session, project_id
            )
            future = (
                self._planning_from_json(head["content_json"])
                if int(head["revision"]) > 0
                else None
            )
            draft = (
                self._draft_result(draft_row, basis)
                if draft_row is not None
                and basis is not None
                and self._basis_matches(draft_row, basis)
                else None
            )
            projection_status = self._projection_status(projection)
            archived = project.get("archived_at") is not None
            capacity_policy = (
                self._capacity_policy(basis) if basis is not None else None
            )
            confirmable = (
                not archived
                and draft is not None
                and projection_status["synchronized"] is True
                and self._is_confirmable(draft.content)
            )
            return PlanningState(
                project_id=project_id,
                basis_status=(
                    "current" if basis is not None else "unavailable"
                ),
                head=PlanningHeadResult(
                    revision=int(head["revision"]),
                    planning_revision_id=head["planning_revision_id"],
                    content_hash=head["content_hash"],
                ),
                draft=draft,
                future_plan=future,
                actual_progress=(),
                canon_projection_status=projection_status,
                capacity_policy=capacity_policy,
                capabilities=PlanningCapabilities(
                    view=True,
                    edit=not archived and capacity_policy is not None,
                    confirm=confirmable,
                    generate=False,
                ),
                archived=archived,
            )

    async def _confirmed_result(
        self,
        session,
        project_id: str,
        revision: int,
        content_hash: str,
    ) -> PlanningRevisionResult:
        rows = await self.repository.list_revisions(session, project_id)
        for row in rows:
            if (
                int(row["revision"]) == revision
                and row["content_hash"] == content_hash
            ):
                return self._revision_result(row)
        raise PlanningConflict("confirmed Planning revision is missing")

    async def _require_active_project(self, session, project_id: str):
        observed = await self.repository.read_project_any(session, project_id)
        if observed is None:
            raise PlanningNotFound("Project not found")
        if observed.get("archived_at") is not None:
            raise PlanningArchived("Project is archived")
        try:
            project = await self.repository.lock_active_project(
                session, project_id
            )
        except RepositoryProjectArchived:
            raise PlanningArchived("Project is archived") from None
        if project is not None:
            return project
        current = await self.repository.read_project_any(session, project_id)
        if current is not None and current.get("archived_at") is not None:
            raise PlanningArchived("Project is archived")
        raise PlanningNotFound("Project not found")

    async def _require_current_basis(self, session, project_id: str):
        basis = await self.repository.read_current_basis(session, project_id)
        if basis is None:
            raise PlanningPreconditionFailed(
                "current confirmed Seed, Contract, Style, and Bible are required"
            )
        return basis

    async def _require_head(self, session, project_id: str):
        head = await self.repository.lock_planning_head(session, project_id)
        if head is None:
            raise PlanningPreconditionFailed("Planning head is missing")
        if int(head["revision"]) > 0 and (
            head.get("planning_revision_id") is None
            or head.get("content_hash") is None
            or head.get("content_json") is None
        ):
            raise PlanningPreconditionFailed("Planning head revision is incomplete")
        return head

    def _empty_planning(self) -> PlanningAggregate:
        payload: dict[str, object] = {
            "schemaVersion": "planning-v1",
            "activeStoryBlockId": None,
            "volumes": (),
            "plots": (),
            "storyBlocks": (),
        }
        content_hash = canonical_hash(payload)
        return PlanningAggregate.model_validate(
            {**payload, "contentHash": content_hash}
        )

    def _planning_from_json(self, value: object) -> PlanningAggregate:
        if isinstance(value, PlanningAggregate):
            return value
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("utf-8")
        if isinstance(value, str):
            value = json.loads(value)
        return PlanningAggregate.model_validate(value)

    def _planning_json(self, value: PlanningAggregate) -> str:
        return canonical_json(value.model_dump(mode="json", by_alias=True))

    def _basis_values(self, basis: Mapping[str, Any]) -> dict[str, Any]:
        return {field: basis[field] for field in _BASIS_FIELDS}

    def _basis_matches(
        self,
        row: Mapping[str, Any],
        basis: Mapping[str, Any],
    ) -> bool:
        return all(row.get(field) == basis.get(field) for field in _BASIS_FIELDS)

    def _capacity_policy(self, basis: Mapping[str, Any]) -> dict[str, int]:
        value = basis["chapter_capacity_policy"]
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("utf-8")
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise PlanningPreconditionFailed(
                    "chapter capacity policy is invalid"
                ) from exc
        if not isinstance(value, Mapping):
            raise PlanningPreconditionFailed("chapter capacity policy is invalid")
        word_range = value.get("chapterWordRangePreference")
        if (
            not isinstance(word_range, (list, tuple))
            or len(word_range) != 2
            or any(type(item) is not int for item in word_range)
        ):
            raise PlanningPreconditionFailed("chapter capacity policy is invalid")
        target_min, target_max = word_range
        if not 0 < target_min <= target_max:
            raise PlanningPreconditionFailed("chapter capacity policy is invalid")
        result = {
            "targetMin": target_min,
            "targetMax": target_max,
            "softCeiling": target_max,
        }
        return result

    def _draft_result(
        self,
        row: Mapping[str, Any],
        basis: Mapping[str, Any],
    ) -> PlanningDraftResult:
        return PlanningDraftResult(
            project_id=str(row["project_id"]),
            draft_id=str(row["id"]),
            base_head_revision=int(row["base_head_revision"]),
            draft_revision=int(row["draft_revision"]),
            content_hash=str(row["content_hash"]),
            content=self._planning_from_json(row["content_json"]),
            status=str(row["status"]),
            capacity_policy=self._capacity_policy(basis),
        )

    def _revision_result(
        self, row: Mapping[str, Any]
    ) -> PlanningRevisionResult:
        return PlanningRevisionResult(
            project_id=str(row["project_id"]),
            planning_revision_id=str(row["id"]),
            revision=int(row["revision"]),
            parent_revision=int(row["parent_revision"]),
            content_hash=str(row["content_hash"]),
            content=self._planning_from_json(row["content_json"]),
        )

    def _projection_status(
        self, row: Mapping[str, Any] | None
    ) -> dict[str, object]:
        if row is None:
            raise PlanningPreconditionFailed("Canon/Projection head is missing")
        canon = int(row["canon_revision_number"])
        projection = int(row["projection_revision_number"])
        return {
            "canonRevision": canon,
            "projectionRevision": projection,
            "contentHash": row["content_hash"],
            "synchronized": canon == projection,
        }

    def _is_confirmable(self, content: PlanningAggregate) -> bool:
        try:
            validate_confirmable_planning(content)
        except PlanningDomainError:
            return False
        return True

    def _require_active_draft(self, row: Mapping[str, Any] | None) -> None:
        if row is None:
            raise PlanningNotFound("Planning Draft not found")
        if row["status"] != "active" or row.get("active_slot") != 1:
            raise PlanningConflict("Planning Draft is not active")

    def _require_draft_cas(
        self,
        row: Mapping[str, Any],
        expected_revision: int,
        expected_hash: str,
    ) -> None:
        if (
            int(row["draft_revision"]) != expected_revision
            or row["content_hash"] != expected_hash
        ):
            raise PlanningConflict("Planning draft revision conflict")

    def _validate_project(self, project_id: str) -> None:
        if not isinstance(project_id, str) or not project_id.strip():
            raise PlanningRequestInvalid("project_id is required")

    def _validate_project_and_key(
        self, project_id: str, idempotency_key: str
    ) -> None:
        self._validate_project(project_id)
        if _IDEMPOTENCY_KEY.fullmatch(idempotency_key or "") is None:
            raise PlanningRequestInvalid("idempotency key is invalid")

    def _validate_save(self, command: SavePlanningDraft) -> None:
        self._validate_project_and_key(
            command.project_id, command.idempotency_key
        )
        if not command.draft_id:
            raise PlanningRequestInvalid("draft_id is required")
        if command.expected_revision < 1:
            raise PlanningRequestInvalid("expected draft revision is invalid")
        if _HASH.fullmatch(command.expected_hash or "") is None:
            raise PlanningRequestInvalid("expected draft hash is invalid")
        if not isinstance(command.content, Mapping):
            raise PlanningRequestInvalid("Planning content is required")

    def _validate_confirm(self, command: ConfirmPlanningDraft) -> None:
        self._validate_project_and_key(
            command.project_id, command.idempotency_key
        )
        if not command.draft_id:
            raise PlanningRequestInvalid("draft_id is required")
        if command.expected_draft_revision < 1:
            raise PlanningRequestInvalid("expected draft revision is invalid")
        if _HASH.fullmatch(command.expected_draft_hash or "") is None:
            raise PlanningRequestInvalid("expected draft hash is invalid")

    def _hit(self, stage: str) -> None:
        if self.failpoint is not None:
            self.failpoint(stage)

    def _read_connection(self):
        if self.connection_factory is None:
            raise RuntimeError("Planning read connection is unavailable")
        return self.connection_factory()


__all__ = (
    "ConfirmPlanningDraft",
    "CreatePlanningDraft",
    "PlanningArchived",
    "PlanningCapabilities",
    "PlanningConflict",
    "PlanningDraftResult",
    "PlanningError",
    "PlanningHeadResult",
    "PlanningNotFound",
    "PlanningPreconditionFailed",
    "PlanningRequestInvalid",
    "PlanningRevisionResult",
    "PlanningService",
    "PlanningState",
    "SavePlanningDraft",
)
