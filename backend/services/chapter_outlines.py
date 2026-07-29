"""Transactional manual ChapterOutline Draft, confirmation, and read models."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Callable, Literal, Mapping
from urllib.parse import quote
from uuid import uuid4

from pydantic import ValidationError

from backend.domain.chapter_outlines import (
    ChapterOutline,
    ChapterOutlineDomainError,
    DraftChapterOutline,
    EditableChapterOutlineContent,
    OutlineCapacityPolicy,
    normalize_chapter_outline,
)
from backend.domain.json_contracts import canonical_hash
from backend.domain.planning import PlanningAggregate
from backend.domain.provider_policy import provider_is_generation_ready
from backend.http_errors import ProjectArchived as RepositoryProjectArchived
from backend.repositories.chapter_sessions import (
    ActiveChapterSessionConflict,
    authoritative_chapter,
)
from backend.repositories.planning import PlanningRepository
from backend.security.provider_secrets import (
    normalize_provider_secrets,
    provider_public_fields_contain_secret,
)


_HASH = re.compile(r"^[0-9a-f]{64}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_TERMINAL_OPERATION_STATUSES = frozenset(
    {"pending", "succeeded", "failed", "superseded"}
)
_SAFE_OPERATION_FAILURE_CODES = frozenset(
    {
        "ChapterOutlineGenerationCancelled",
        "ChapterOutlineProviderFailed",
        "ChapterOutlineProviderResultInvalid",
    }
)
_PLANNING_BASIS_FIELDS = (
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


class ChapterOutlineError(RuntimeError):
    pass


class ChapterOutlineNotFound(ChapterOutlineError):
    pass


class ChapterOutlineArchived(ChapterOutlineError):
    pass


class ChapterOutlineRequestInvalid(ChapterOutlineError):
    pass


class ChapterOutlinePreconditionFailed(ChapterOutlineError):
    pass


class ChapterOutlineConflict(ChapterOutlineError):
    pass


@dataclass(frozen=True)
class CreateChapterOutlineDraft:
    project_id: str
    chapter_number: int


@dataclass(frozen=True)
class SaveChapterOutlineDraft:
    project_id: str
    chapter_number: int
    draft_id: str
    expected_draft_revision: int
    expected_draft_hash: str
    content: EditableChapterOutlineContent


@dataclass(frozen=True)
class ConfirmChapterOutlineDraft:
    project_id: str
    chapter_number: int
    draft_id: str
    expected_draft_revision: int
    expected_draft_hash: str
    expected_head_revision: int
    idempotency_key: str


@dataclass(frozen=True)
class PlanningAuthorityResult:
    planning_revision_id: str
    revision: int
    content_hash: str
    content: PlanningAggregate | None


@dataclass(frozen=True)
class CanonProjectionAuthorityResult:
    canon_revision: int
    projection_revision: int
    content_hash: str
    synchronized: bool


@dataclass(frozen=True)
class ChapterOutlineBasisResult:
    planning: PlanningAuthorityResult
    canon_projection: CanonProjectionAuthorityResult


@dataclass(frozen=True)
class ChapterOutlineDraftResult:
    project_id: str
    chapter_number: int
    draft_id: str
    base_head_revision: int
    draft_revision: int
    content_hash: str
    content: EditableChapterOutlineContent
    basis: ChapterOutlineBasisResult
    status: Literal["current", "superseded"]


@dataclass(frozen=True)
class ChapterOutlineRevisionResult:
    project_id: str
    chapter_number: int
    outline_revision_id: str
    revision: int
    parent_revision: int
    content_hash: str
    content: EditableChapterOutlineContent
    basis: ChapterOutlineBasisResult
    display_status: str = "current"
    display_reason: str = "currentOutlineHead"


@dataclass(frozen=True)
class ActiveChapterSessionResult:
    chapter_session_id: str
    chapter_number: int
    status: str
    planning_revision_id: str
    planning_revision: int
    planning_hash: str
    outline_revision_id: str
    outline_revision: int
    outline_hash: str


@dataclass(frozen=True)
class ChapterOutlineCapabilities:
    view: bool
    create_draft: bool
    edit_draft: bool
    generate: bool
    confirm: bool
    start_session: bool


@dataclass(frozen=True)
class PendingChapterOutlineOperation:
    operation_id: str
    status: Literal["pending"]


@dataclass(frozen=True)
class ChapterOutlineState:
    project_id: str
    lifecycle: Literal["active", "archived"]
    authoritative_chapter_number: int
    target_path: str
    planning_authority: PlanningAuthorityResult | None
    canon_projection_authority: CanonProjectionAuthorityResult | None
    confirmed_outline: ChapterOutlineRevisionResult | None
    draft: ChapterOutlineDraftResult | None
    active_session: ActiveChapterSessionResult | None
    pending_operation: PendingChapterOutlineOperation | None
    capabilities: ChapterOutlineCapabilities
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ChapterOutlineOperationResult:
    operation_id: str
    status: str
    failure_code: str | None
    loaded: bool
    loaded_draft_revision: int | None


class ChapterOutlineService:
    def __init__(
        self,
        repository,
        chapter_repository,
        *,
        transaction_factory,
        planning_repository=None,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], int] | None = None,
        failpoint: Callable[[str], None] | None = None,
    ):
        self.repository = repository
        self.chapter_repository = chapter_repository
        self.planning_repository = planning_repository or PlanningRepository()
        self.transaction_factory = transaction_factory
        self.id_factory = id_factory or (lambda: str(uuid4()))
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.failpoint = failpoint

    async def create_draft(
        self,
        command: CreateChapterOutlineDraft,
    ) -> ChapterOutlineDraftResult:
        self._validate_project_chapter(
            command.project_id,
            command.chapter_number,
        )
        async with self.transaction_factory() as session:
            await self._require_active_project(session, command.project_id)
            chapter_number, active_session = await self._chapter_authority(
                session,
                command.project_id,
            )
            self._require_requested_chapter(
                command.chapter_number,
                chapter_number,
            )
            self._require_no_active_session(active_session)
            authorities = await self._require_authorities(
                session,
                command.project_id,
            )
            head = await self.repository.lock_outline_head(
                session,
                command.project_id,
                chapter_number,
            )
            head_revision = self._head_revision(head)
            active = await self.repository.read_active_draft(
                session,
                command.project_id,
                chapter_number,
            )
            if active is not None and self._draft_is_current(
                active,
                authorities,
                head_revision,
            ):
                return self._draft_result(active)
            if active is not None:
                if not await self.repository.supersede_draft(
                    session,
                    command.project_id,
                    chapter_number,
                    str(active["id"]),
                ):
                    raise ChapterOutlineConflict(
                        "active ChapterOutline Draft changed"
                    )

            content = EditableChapterOutlineContent()
            content_payload = self._editable_payload(content)
            now = self.clock()
            row = {
                "id": self.id_factory(),
                "project_id": command.project_id,
                "chapter_num": chapter_number,
                "base_head_revision": head_revision,
                "draft_revision": 1,
                **self._authority_values(authorities),
                "content": content_payload,
                "content_hash": canonical_hash(content_payload),
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }
            if not await self.repository.insert_draft(session, row):
                raise ChapterOutlineConflict(
                    "ChapterOutline Draft was not created"
                )
            return self._draft_result(row)

    async def save_draft(
        self,
        command: SaveChapterOutlineDraft,
    ) -> ChapterOutlineDraftResult:
        self._validate_save(command)
        superseded = False
        result = None
        async with self.transaction_factory() as session:
            await self._require_active_project(session, command.project_id)
            chapter_number, active_session = await self._chapter_authority(
                session,
                command.project_id,
            )
            self._require_requested_chapter(
                command.chapter_number,
                chapter_number,
            )
            self._require_no_active_session(active_session)
            authorities = await self._require_authorities(
                session,
                command.project_id,
            )
            head = await self.repository.lock_outline_head(
                session,
                command.project_id,
                chapter_number,
            )
            draft = await self.repository.read_draft(
                session,
                command.project_id,
                chapter_number,
                command.draft_id,
            )
            self._require_active_draft(draft)
            if not self._draft_is_current(
                draft,
                authorities,
                self._head_revision(head),
            ):
                if not await self.repository.supersede_draft(
                    session,
                    command.project_id,
                    chapter_number,
                    command.draft_id,
                ):
                    raise ChapterOutlineConflict(
                        "ChapterOutline Draft changed"
                    )
                superseded = True
            else:
                self._require_draft_cas(
                    draft,
                    command.expected_draft_revision,
                    command.expected_draft_hash,
                )
                content_payload = self._editable_payload(command.content)
                row = {
                    **draft,
                    "draft_revision": int(draft["draft_revision"]) + 1,
                    "content": content_payload,
                    "content_hash": canonical_hash(content_payload),
                    "status": "active",
                    "updated_at": self.clock(),
                }
                if not await self.repository.update_draft_cas(
                    session,
                    row,
                    command.expected_draft_revision,
                    command.expected_draft_hash,
                ):
                    raise ChapterOutlineConflict(
                        "ChapterOutline Draft revision conflict"
                    )
                result = self._draft_result(row)
        if superseded:
            raise ChapterOutlinePreconditionFailed(
                "ChapterOutline Draft basis is superseded"
            )
        assert result is not None
        return result

    async def confirm_draft(
        self,
        command: ConfirmChapterOutlineDraft,
    ) -> ChapterOutlineRevisionResult:
        self._validate_confirm(command)
        fingerprint = canonical_hash(
            {
                "projectId": command.project_id,
                "chapterNumber": command.chapter_number,
                "draftId": command.draft_id,
                "draftRevision": command.expected_draft_revision,
                "draftHash": command.expected_draft_hash,
                "expectedHeadRevision": command.expected_head_revision,
            }
        )
        superseded = False
        result = None
        async with self.transaction_factory() as session:
            await self._require_active_project(session, command.project_id)
            authoritative_number, active_session = await self._chapter_authority(
                session,
                command.project_id,
            )
            authorities = await self._read_current_authorities(
                session,
                command.project_id,
            )
            head = await self.repository.lock_outline_head(
                session,
                command.project_id,
                command.chapter_number,
            )
            head_revision = self._head_revision(head)
            draft = await self.repository.read_draft(
                session,
                command.project_id,
                command.chapter_number,
                command.draft_id,
            )
            request = await self.repository.find_confirmation(
                session,
                command.project_id,
                command.chapter_number,
                command.idempotency_key,
            )
            if request is not None:
                if request["request_fingerprint"] != fingerprint:
                    raise ChapterOutlineConflict(
                        "idempotency key fingerprint conflict"
                    )
                if request["status"] == "succeeded":
                    return await self._confirmed_result(
                        session,
                        command.project_id,
                        command.chapter_number,
                        str(request["outline_revision_id"]),
                        int(request["result_revision"]),
                        str(request["result_hash"]),
                    )
                raise ChapterOutlineConflict(
                    "ChapterOutline confirmation is pending"
                )

            self._require_requested_chapter(
                command.chapter_number,
                authoritative_number,
            )
            self._require_no_active_session(active_session)
            authorities = self._validate_authorities(authorities)
            chapter_number = authoritative_number
            if draft is None:
                raise ChapterOutlineNotFound(
                    "ChapterOutline Draft not found"
                )
            self._require_active_draft(draft)
            if not self._draft_is_current(
                draft,
                authorities,
                head_revision,
            ):
                if not await self.repository.supersede_draft(
                    session,
                    command.project_id,
                    chapter_number,
                    command.draft_id,
                ):
                    raise ChapterOutlineConflict(
                        "ChapterOutline Draft changed"
                    )
                superseded = True
            else:
                self._require_synchronized_projection(authorities)
                self._require_draft_cas(
                    draft,
                    command.expected_draft_revision,
                    command.expected_draft_hash,
                )
                if head_revision != command.expected_head_revision:
                    raise ChapterOutlineConflict(
                        "ChapterOutline head revision conflict"
                    )
                planning = self._planning(authorities["planning_content"])
                capacity = self._capacity_policy(
                    authorities["chapter_capacity_policy"]
                )
                editable = self._editable(draft["content"])
                try:
                    outline = normalize_chapter_outline(
                        self._confirmable_draft(
                            editable,
                            chapter_number,
                            authorities,
                            capacity,
                        ),
                        planning=planning,
                        authoritative_chapter_number=chapter_number,
                        planning_revision_id=str(
                            authorities["planning_revision_id"]
                        ),
                        planning_revision=int(
                            authorities["planning_revision"]
                        ),
                        capacity_policy=capacity,
                        canon_revision=int(authorities["canon_revision"]),
                        projection_revision=int(
                            authorities["projection_revision"]
                        ),
                        projection_hash=str(
                            authorities["projection_hash"]
                        ),
                    )
                except (ValidationError, ChapterOutlineDomainError) as exc:
                    raise ChapterOutlinePreconditionFailed(
                        "ChapterOutline content is not confirmable"
                    ) from exc

                now = self.clock()
                request_row = {
                    "id": self.id_factory(),
                    "project_id": command.project_id,
                    "chapter_num": chapter_number,
                    "chapter_outline_draft_id": command.draft_id,
                    "draft_revision": command.expected_draft_revision,
                    "draft_hash": command.expected_draft_hash,
                    "expected_head_revision": command.expected_head_revision,
                    **self._authority_values(authorities),
                    "idempotency_key": command.idempotency_key,
                    "request_fingerprint": fingerprint,
                    "created_at": now,
                }
                if not await self.repository.insert_confirmation_pending(
                    session,
                    request_row,
                ):
                    raise ChapterOutlineConflict(
                        "ChapterOutline confirmation was not reserved"
                    )
                self._hit("after_confirmation_pending")

                revision_number = head_revision + 1
                revision_row = {
                    "id": self.id_factory(),
                    "project_id": command.project_id,
                    "chapter_num": chapter_number,
                    "revision": revision_number,
                    "parent_revision": head_revision,
                    **self._authority_values(authorities),
                    "content": outline.model_dump(
                        mode="json",
                        by_alias=True,
                    ),
                    "content_hash": outline.content_hash,
                    "created_at": now,
                }
                if not await self.repository.insert_revision(
                    session,
                    revision_row,
                ):
                    raise ChapterOutlineConflict(
                        "ChapterOutline revision was not inserted"
                    )
                self._hit("after_revision_insert")

                head_row = {
                    "project_id": command.project_id,
                    "chapter_num": chapter_number,
                    "revision": revision_number,
                    "outline_revision_id": revision_row["id"],
                    "content_hash": outline.content_hash,
                    "updated_at": now,
                }
                if not await self.repository.advance_head_cas(
                    session,
                    head_row,
                    head_revision,
                ):
                    raise ChapterOutlineConflict(
                        "ChapterOutline head revision conflict"
                    )
                self._hit("after_head_advance")

                if not await self.repository.update_draft_cas(
                    session,
                    {
                        **draft,
                        "status": "confirmed",
                        "updated_at": now,
                    },
                    command.expected_draft_revision,
                    command.expected_draft_hash,
                ):
                    raise ChapterOutlineConflict(
                        "ChapterOutline Draft changed during confirmation"
                    )
                self._hit("after_draft_confirmed")

                if not await self.repository.finish_confirmation(
                    session,
                    {
                        **request_row,
                        "status": "succeeded",
                        "outline_revision_id": revision_row["id"],
                        "result_revision": revision_number,
                        "result_hash": outline.content_hash,
                        "public_error_code": None,
                        "completed_at": now,
                    },
                ):
                    raise ChapterOutlineConflict(
                        "ChapterOutline confirmation was not completed"
                    )
                self._hit("after_confirmation_succeeded")
                result = self._revision_result(revision_row)
        if superseded:
            raise ChapterOutlinePreconditionFailed(
                "ChapterOutline Draft basis is superseded"
            )
        assert result is not None
        return result

    async def get_current(self, project_id: str) -> ChapterOutlineState:
        return await self._get_state(project_id, expected_chapter=None)

    async def get(
        self,
        project_id: str,
        chapter_number: int,
    ) -> ChapterOutlineState:
        self._validate_project_chapter(project_id, chapter_number)
        return await self._get_state(
            project_id,
            expected_chapter=chapter_number,
        )

    async def history(
        self,
        project_id: str,
        chapter_number: int,
    ) -> tuple[ChapterOutlineRevisionResult, ...]:
        self._validate_project_chapter(project_id, chapter_number)
        async with self.transaction_factory() as session:
            project = await self._require_project_any(session, project_id)
            authoritative_number, _ = await self._chapter_authority(
                session,
                project_id,
            )
            authorities = await self._read_current_authorities(
                session,
                project_id,
            )
            head = await self.repository.read_outline_head(
                session,
                project_id,
                chapter_number,
            )
            pinned = await self.chapter_repository.read_chapter_session(
                session,
                project_id,
                chapter_number,
            )
            rows = await self.repository.list_revisions(
                session,
                project_id,
                chapter_number,
            )
            archived = project.get("archived_at") is not None
            return tuple(
                self._revision_result(
                    row,
                    display_status=self._history_status(
                        row,
                        archived=archived,
                        authoritative_number=authoritative_number,
                        authorities=authorities,
                        head=head,
                        pinned=pinned,
                    )[0],
                    display_reason=self._history_status(
                        row,
                        archived=archived,
                        authoritative_number=authoritative_number,
                        authorities=authorities,
                        head=head,
                        pinned=pinned,
                    )[1],
                )
                for row in rows
            )

    async def get_operation_by_key(
        self,
        project_id: str,
        idempotency_key: str,
    ) -> ChapterOutlineOperationResult:
        self._validate_project(project_id)
        if _IDEMPOTENCY_KEY.fullmatch(idempotency_key or "") is None:
            raise ChapterOutlineRequestInvalid(
                "idempotency key is invalid"
            )
        async with self.transaction_factory() as session:
            await self._require_project_any(session, project_id)
            row = await self.repository.read_attempt_by_key(
                session,
                project_id,
                idempotency_key,
            )
            if row is None:
                raise ChapterOutlineNotFound(
                    "ChapterOutline operation not found"
                )
            return self._operation_result(row)

    async def get_operation(
        self,
        project_id: str,
        operation_id: str,
    ) -> ChapterOutlineOperationResult:
        self._validate_project(project_id)
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ChapterOutlineRequestInvalid(
                "operation_id is required"
            )
        async with self.transaction_factory() as session:
            await self._require_project_any(session, project_id)
            row = await self.repository.read_attempt(
                session,
                project_id,
                operation_id,
            )
            if row is None:
                raise ChapterOutlineNotFound(
                    "ChapterOutline operation not found"
                )
            return self._operation_result(row)

    async def _get_state(
        self,
        project_id: str,
        *,
        expected_chapter: int | None,
    ) -> ChapterOutlineState:
        self._validate_project(project_id)
        async with self.transaction_factory() as session:
            project = await self._lock_project_snapshot(
                session,
                project_id,
            )
            chapter_number, active_session = await self._chapter_authority(
                session,
                project_id,
            )
            if (
                expected_chapter is not None
                and expected_chapter != chapter_number
            ):
                raise ChapterOutlineConflict(
                    "requested chapter differs from server authority"
                )
            authorities = await self._read_current_authorities(
                session,
                project_id,
            )
            head = await self.repository.read_outline_head(
                session,
                project_id,
                chapter_number,
            )
            draft_row = await self.repository.read_active_draft(
                session,
                project_id,
                chapter_number,
            )
            pending_attempt = (
                await self.repository.read_active_attempt(
                    session,
                    str(draft_row["id"]),
                )
                if draft_row is not None
                else None
            )
            binding = await self.planning_repository.lock_planning_binding(
                session,
                project_id,
            )
            generation_pending = (
                pending_attempt is not None
                and pending_attempt.get("status") == "pending"
            )
            session_row = (
                await self.chapter_repository.read_chapter_session(
                    session,
                    project_id,
                    chapter_number,
                )
                if active_session is not None
                else None
            )
            archived = project.get("archived_at") is not None
            planning_authority = self._state_planning_authority(
                authorities,
                session_row,
            )
            projection_authority = self._state_projection_authority(
                authorities,
                session_row,
            )
            confirmed = self._state_confirmed_outline(
                project_id,
                chapter_number,
                head,
                authorities,
                session_row,
                archived,
            )
            draft = (
                self._draft_result(
                    draft_row,
                    status=(
                        "current"
                        if authorities is not None
                        and self._draft_is_current(
                            draft_row,
                            authorities,
                            self._head_revision(head),
                        )
                        else "superseded"
                    ),
                )
                if draft_row is not None
                else None
            )
            active_result = (
                self._session_result(session_row)
                if session_row is not None
                else None
            )
            synchronized = (
                projection_authority is not None
                and projection_authority.synchronized
            )
            mutations_allowed = (
                not archived
                and active_result is None
                and authorities is not None
            )
            current_draft = (
                draft is not None and draft.status == "current"
            )
            confirmed_current = (
                confirmed is not None
                and confirmed.display_status == "current"
            )
            capabilities = ChapterOutlineCapabilities(
                view=True,
                create_draft=mutations_allowed and not current_draft,
                edit_draft=mutations_allowed and current_draft,
                generate=(
                    mutations_allowed
                    and active_session is None
                    and current_draft
                    and not generation_pending
                    and synchronized
                    and self._planning_binding_ready(binding)
                ),
                confirm=(
                    mutations_allowed
                    and current_draft
                    and synchronized
                    and self._content_is_confirmable(
                        draft.content,
                        chapter_number,
                        authorities,
                    )
                ),
                start_session=(
                    mutations_allowed
                    and synchronized
                    and confirmed_current
                ),
            )
            return ChapterOutlineState(
                project_id=project_id,
                lifecycle="archived" if archived else "active",
                authoritative_chapter_number=chapter_number,
                target_path=self._writer_path(project_id, chapter_number),
                planning_authority=planning_authority,
                canon_projection_authority=projection_authority,
                confirmed_outline=confirmed,
                draft=draft,
                active_session=active_result,
                pending_operation=(
                    PendingChapterOutlineOperation(
                        operation_id=pending_attempt["operation_id"],
                        status="pending",
                    )
                    if pending_attempt is not None
                    and pending_attempt.get("status") == "pending"
                    and isinstance(
                        pending_attempt.get("operation_id"),
                        str,
                    )
                    and pending_attempt["operation_id"]
                    else None
                ),
                capabilities=capabilities,
                reasons=self._state_reasons(
                    archived=archived,
                    active_session=active_result,
                    authorities=authorities,
                    projection=projection_authority,
                    draft=draft,
                    confirmed=confirmed,
                ),
            )

    @staticmethod
    def _writer_path(project_id: str, chapter_number: int) -> str:
        return (
            f"/projects/{quote(str(project_id), safe='')}/"
            f"write/chapters/{chapter_number}"
        )

    @staticmethod
    def _planning_binding_ready(
        binding: Mapping[str, object] | None,
    ) -> bool:
        if binding is None:
            return False
        try:
            secrets = normalize_provider_secrets(
                (binding["api_key"], binding["base_url"])
            )
            public_model = {
                "providerId": binding["provider_id"],
                "modelName": binding["model_name_snapshot"],
            }
            return (
                binding["binding_task_key"] == "planning"
                and binding["resolution_status"] == "bound"
                and binding["provider_id"] == binding["id"]
                and binding["model_name_snapshot"] == binding["model_name"]
                and int(binding["binding_revision"]) > 0
                and _HASH.fullmatch(str(binding["binding_hash"])) is not None
                and provider_is_generation_ready(binding)
                and not provider_public_fields_contain_secret(
                    public_model,
                    secrets,
                )
            )
        except (KeyError, TypeError, ValueError, UnicodeError):
            return False

    async def _chapter_authority(self, session, project_id: str):
        try:
            active = await self.chapter_repository.read_active_session(
                session,
                project_id,
            )
        except ActiveChapterSessionConflict:
            raise ChapterOutlineConflict(
                "active ChapterSession authority is inconsistent"
            ) from None
        maximum = await self.chapter_repository.read_max_final_chapter_number(
            session,
            project_id,
        )
        return authoritative_chapter(active, maximum), active

    async def _require_active_project(self, session, project_id: str):
        try:
            project = await self.repository.lock_project(
                session,
                project_id,
            )
        except RepositoryProjectArchived:
            raise ChapterOutlineArchived("Project is archived") from None
        if project is None:
            raise ChapterOutlineNotFound("Project not found")
        return project

    async def _require_project_any(self, session, project_id: str):
        project = await self.repository.read_project_any(session, project_id)
        if project is None:
            raise ChapterOutlineNotFound("Project not found")
        return project

    async def _lock_project_snapshot(self, session, project_id: str):
        try:
            project = await self.repository.lock_project(
                session,
                project_id,
            )
        except RepositoryProjectArchived:
            project = None
        if project is None:
            project = await self.repository.read_project_any(
                session,
                project_id,
            )
        if project is None:
            raise ChapterOutlineNotFound("Project not found")
        return project

    async def _require_authorities(self, session, project_id: str):
        authorities = await self._read_current_authorities(
            session,
            project_id,
        )
        return self._validate_authorities(authorities)

    async def _read_current_authorities(self, session, project_id: str):
        basis = await self.planning_repository.read_current_basis(
            session,
            project_id,
        )
        head = await self.planning_repository.lock_planning_head(
            session,
            project_id,
        )
        if (
            basis is None
            or head is None
            or int(head["revision"]) < 1
            or any(
                head.get(field) != basis.get(field)
                for field in _PLANNING_BASIS_FIELDS
            )
        ):
            return None
        authorities = await self.repository.read_current_authorities(
            session,
            project_id,
        )
        if authorities is None:
            return None
        if (
            authorities.get("planning_revision_id")
            != head.get("planning_revision_id")
            or authorities.get("planning_revision") != head.get("revision")
            or authorities.get("planning_hash") != head.get("content_hash")
        ):
            return None
        return {
            **authorities,
            "chapter_capacity_policy": basis["chapter_capacity_policy"],
        }

    def _validate_authorities(self, authorities):
        if authorities is None:
            raise ChapterOutlinePreconditionFailed(
                "current Planning and Canon/Projection are required"
            )
        try:
            self._planning(authorities["planning_content"])
            self._capacity_policy(authorities["chapter_capacity_policy"])
        except (
            KeyError,
            TypeError,
            ValueError,
            ValidationError,
            json.JSONDecodeError,
        ) as exc:
            raise ChapterOutlinePreconditionFailed(
                "current Planning authority is invalid"
            ) from exc
        return authorities

    def _require_synchronized_projection(
        self,
        authorities: Mapping[str, object],
    ) -> None:
        if int(authorities["canon_revision"]) != int(
            authorities["projection_revision"]
        ):
            raise ChapterOutlinePreconditionFailed(
                "Canon and Projection must be synchronized"
            )
        if _HASH.fullmatch(
            str(authorities.get("projection_hash") or "")
        ) is None:
            raise ChapterOutlinePreconditionFailed(
                "Projection authority is invalid"
            )

    async def _confirmed_result(
        self,
        session,
        project_id: str,
        chapter_number: int,
        outline_revision_id: str,
        revision: int,
        content_hash: str,
    ) -> ChapterOutlineRevisionResult:
        rows = await self.repository.list_revisions(
            session,
            project_id,
            chapter_number,
        )
        for row in rows:
            if (
                str(row["id"]) == outline_revision_id
                and int(row["revision"]) == revision
                and str(row["content_hash"]) == content_hash
            ):
                return self._revision_result(row)
        raise ChapterOutlineConflict(
            "confirmed ChapterOutline revision is missing"
        )

    def _confirmable_draft(
        self,
        editable: EditableChapterOutlineContent,
        chapter_number: int,
        authorities: Mapping[str, object],
        capacity_policy: OutlineCapacityPolicy,
    ) -> DraftChapterOutline:
        payload = self._editable_payload(editable)
        payload.pop("schemaVersion")
        return DraftChapterOutline.model_validate(
            {
                "schemaVersion": "chapter-outline-v1",
                "chapterNumber": chapter_number,
                "planningRevisionId": authorities[
                    "planning_revision_id"
                ],
                "planningRevision": int(
                    authorities["planning_revision"]
                ),
                "planningHash": authorities["planning_hash"],
                **payload,
                "capacityPolicy": capacity_policy.model_dump(
                    mode="json",
                    by_alias=True,
                ),
            }
        )

    def _content_is_confirmable(
        self,
        content: EditableChapterOutlineContent,
        chapter_number: int,
        authorities: Mapping[str, object] | None,
    ) -> bool:
        if authorities is None:
            return False
        try:
            capacity = self._capacity_policy(
                authorities["chapter_capacity_policy"]
            )
            draft = self._confirmable_draft(
                content,
                chapter_number,
                authorities,
                capacity,
            )
            normalize_chapter_outline(
                draft,
                planning=self._planning(authorities["planning_content"]),
                authoritative_chapter_number=chapter_number,
                planning_revision_id=str(
                    authorities["planning_revision_id"]
                ),
                planning_revision=int(authorities["planning_revision"]),
                capacity_policy=capacity,
                canon_revision=int(authorities["canon_revision"]),
                projection_revision=int(
                    authorities["projection_revision"]
                ),
                projection_hash=str(authorities["projection_hash"]),
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            ValidationError,
            ChapterOutlineDomainError,
        ):
            return False
        return True

    def _draft_result(
        self,
        row: Mapping[str, object],
        *,
        status: Literal["current", "superseded"] | None = None,
    ) -> ChapterOutlineDraftResult:
        return ChapterOutlineDraftResult(
            project_id=str(row["project_id"]),
            chapter_number=int(row["chapter_num"]),
            draft_id=str(row["id"]),
            base_head_revision=int(row["base_head_revision"]),
            draft_revision=int(row["draft_revision"]),
            content_hash=str(row["content_hash"]),
            content=self._editable(row["content"]),
            basis=self._basis_result(row),
            status=status or self._draft_display_status(row),
        )

    def _draft_display_status(
        self,
        row: Mapping[str, object],
    ) -> Literal["current", "superseded"]:
        status = str(row["status"])
        if status == "active":
            return "current"
        if status == "superseded":
            return "superseded"
        raise ValueError("invalid ChapterOutline Draft status")

    def _revision_result(
        self,
        row: Mapping[str, object],
        *,
        display_status: str = "current",
        display_reason: str = "currentOutlineHead",
    ) -> ChapterOutlineRevisionResult:
        return ChapterOutlineRevisionResult(
            project_id=str(row["project_id"]),
            chapter_number=int(row["chapter_num"]),
            outline_revision_id=str(row["id"]),
            revision=int(row["revision"]),
            parent_revision=int(row["parent_revision"]),
            content_hash=str(row["content_hash"]),
            content=self._editable_from_outline(row["content"]),
            basis=self._basis_result(row),
            display_status=display_status,
            display_reason=display_reason,
        )

    def _basis_result(
        self,
        row: Mapping[str, object],
        *,
        planning_content: PlanningAggregate | None = None,
    ) -> ChapterOutlineBasisResult:
        canon = int(row["canon_revision"])
        projection = int(row["projection_revision"])
        return ChapterOutlineBasisResult(
            planning=PlanningAuthorityResult(
                planning_revision_id=str(row["planning_revision_id"]),
                revision=int(row["planning_revision"]),
                content_hash=str(row["planning_hash"]),
                content=planning_content,
            ),
            canon_projection=CanonProjectionAuthorityResult(
                canon_revision=canon,
                projection_revision=projection,
                content_hash=str(row["projection_hash"]),
                synchronized=canon == projection,
            ),
        )

    def _state_planning_authority(
        self,
        authorities: Mapping[str, object] | None,
        session_row: Mapping[str, object] | None,
    ) -> PlanningAuthorityResult | None:
        if session_row is not None:
            return PlanningAuthorityResult(
                planning_revision_id=str(
                    session_row["planning_revision_id"]
                ),
                revision=int(session_row["planning_revision"]),
                content_hash=str(session_row["planning_hash"]),
                content=None,
            )
        if authorities is None:
            return None
        try:
            content = self._planning(authorities["planning_content"])
        except (KeyError, TypeError, ValueError, ValidationError):
            content = None
        return PlanningAuthorityResult(
            planning_revision_id=str(
                authorities["planning_revision_id"]
            ),
            revision=int(authorities["planning_revision"]),
            content_hash=str(authorities["planning_hash"]),
            content=content,
        )

    def _state_projection_authority(
        self,
        authorities: Mapping[str, object] | None,
        session_row: Mapping[str, object] | None,
    ) -> CanonProjectionAuthorityResult | None:
        if session_row is not None:
            canon = int(session_row["outline_canon_revision"])
            projection = int(
                session_row["outline_projection_revision"]
            )
            return CanonProjectionAuthorityResult(
                canon_revision=canon,
                projection_revision=projection,
                content_hash=str(session_row["outline_projection_hash"]),
                synchronized=canon == projection,
            )
        if authorities is None:
            return None
        canon = int(authorities["canon_revision"])
        projection = int(authorities["projection_revision"])
        return CanonProjectionAuthorityResult(
            canon_revision=canon,
            projection_revision=projection,
            content_hash=str(authorities["projection_hash"]),
            synchronized=canon == projection,
        )

    def _state_confirmed_outline(
        self,
        project_id: str,
        chapter_number: int,
        head: Mapping[str, object] | None,
        authorities: Mapping[str, object] | None,
        session_row: Mapping[str, object] | None,
        archived: bool,
    ) -> ChapterOutlineRevisionResult | None:
        if session_row is not None:
            row = {
                "id": session_row["chapter_outline_revision_id"],
                "project_id": project_id,
                "chapter_num": chapter_number,
                "revision": session_row["chapter_outline_revision"],
                "parent_revision": max(
                    int(session_row["chapter_outline_revision"]) - 1,
                    0,
                ),
                "content_hash": session_row["chapter_outline_hash"],
                "planning_revision_id": session_row[
                    "planning_revision_id"
                ],
                "planning_revision": session_row["planning_revision"],
                "planning_hash": session_row["planning_hash"],
                "canon_revision": session_row["outline_canon_revision"],
                "projection_revision": session_row[
                    "outline_projection_revision"
                ],
                "projection_hash": session_row["outline_projection_hash"],
                "content": session_row["chapter_outline"],
            }
            return self._revision_result(
                row,
                display_status="archived" if archived else "session_pinned",
                display_reason=(
                    "projectArchived"
                    if archived
                    else "chapterSessionPinned"
                ),
            )
        if head is None or int(head["revision"]) == 0:
            return None
        current = (
            authorities is not None
            and self._basis_matches(head, authorities)
        )
        return self._revision_result(
            {
                **head,
                "id": head["outline_revision_id"],
            },
            display_status=(
                "archived"
                if archived
                else ("current" if current else "superseded")
            ),
            display_reason=(
                "projectArchived"
                if archived
                else (
                    "currentOutlineHead"
                    if current
                    else "newerPlanningOrProjection"
                )
            ),
        )

    def _session_result(
        self,
        row: Mapping[str, object],
    ) -> ActiveChapterSessionResult:
        return ActiveChapterSessionResult(
            chapter_session_id=str(row["id"]),
            chapter_number=int(row["chapter_num"]),
            status=str(row["status"]),
            planning_revision_id=str(row["planning_revision_id"]),
            planning_revision=int(row["planning_revision"]),
            planning_hash=str(row["planning_hash"]),
            outline_revision_id=str(
                row["chapter_outline_revision_id"]
            ),
            outline_revision=int(row["chapter_outline_revision"]),
            outline_hash=str(row["chapter_outline_hash"]),
        )

    def _history_status(
        self,
        row: Mapping[str, object],
        *,
        archived: bool,
        authoritative_number: int,
        authorities: Mapping[str, object] | None,
        head: Mapping[str, object] | None,
        pinned: Mapping[str, object] | None,
    ) -> tuple[str, str]:
        if archived:
            return "archived", "projectArchived"
        if (
            pinned is not None
            and str(pinned["chapter_outline_revision_id"])
            == str(row["id"])
            and int(pinned["chapter_outline_revision"])
            == int(row["revision"])
            and str(pinned["chapter_outline_hash"])
            == str(row["content_hash"])
        ):
            return "session_pinned", "chapterSessionPinned"
        if (
            int(row["chapter_num"]) == authoritative_number
            and head is not None
            and int(head["revision"]) == int(row["revision"])
            and str(head["outline_revision_id"]) == str(row["id"])
            and authorities is not None
            and self._basis_matches(row, authorities)
        ):
            return "current", "currentOutlineHead"
        return "superseded", "newerChapterPlanningOrProjection"

    def _operation_result(
        self,
        row: Mapping[str, object],
    ) -> ChapterOutlineOperationResult:
        status = str(row.get("status") or "")
        if status not in _TERMINAL_OPERATION_STATUSES:
            status = "failed"
        failure = row.get("failure_code")
        failure_code = (
            str(failure)
            if failure in _SAFE_OPERATION_FAILURE_CODES
            else None
        )
        loaded_revision = row.get("loaded_outline_draft_revision")
        loaded = (
            status == "succeeded"
            and loaded_revision is not None
            and row.get("loaded_at") is not None
        )
        return ChapterOutlineOperationResult(
            operation_id=str(row["operation_id"]),
            status=status,
            failure_code=failure_code,
            loaded=loaded,
            loaded_draft_revision=(
                int(loaded_revision) if loaded else None
            ),
        )

    def _state_reasons(
        self,
        *,
        archived: bool,
        active_session: ActiveChapterSessionResult | None,
        authorities: Mapping[str, object] | None,
        projection: CanonProjectionAuthorityResult | None,
        draft: ChapterOutlineDraftResult | None,
        confirmed: ChapterOutlineRevisionResult | None,
    ) -> tuple[str, ...]:
        reasons = []
        if archived:
            reasons.append("projectArchived")
        if active_session is not None:
            reasons.append("activeSessionPinsAuthorities")
        if authorities is None:
            reasons.append("planningOrProjectionUnavailable")
        if projection is not None and not projection.synchronized:
            reasons.append("canonProjectionMismatch")
        if draft is not None and draft.status == "superseded":
            reasons.append("outlineDraftSuperseded")
        if confirmed is None:
            reasons.append("confirmedOutlineUnavailable")
        elif confirmed.display_status == "superseded":
            reasons.append("confirmedOutlineSuperseded")
        return tuple(reasons)

    def _authority_values(
        self,
        authorities: Mapping[str, object],
    ) -> dict[str, object]:
        return {
            "planning_revision_id": authorities["planning_revision_id"],
            "planning_revision": int(authorities["planning_revision"]),
            "planning_hash": authorities["planning_hash"],
            "canon_revision": int(authorities["canon_revision"]),
            "projection_revision": int(
                authorities["projection_revision"]
            ),
            "projection_hash": authorities["projection_hash"],
        }

    def _basis_matches(
        self,
        row: Mapping[str, object],
        authorities: Mapping[str, object],
    ) -> bool:
        return self._authority_values(row) == self._authority_values(
            authorities
        )

    def _draft_is_current(
        self,
        row: Mapping[str, object],
        authorities: Mapping[str, object],
        head_revision: int,
    ) -> bool:
        return (
            str(row.get("status")) == "active"
            and row.get("active_slot", 1) == 1
            and int(row["base_head_revision"]) == head_revision
            and self._basis_matches(row, authorities)
        )

    def _editable(
        self,
        value: object,
    ) -> EditableChapterOutlineContent:
        if isinstance(value, EditableChapterOutlineContent):
            return value
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("utf-8")
        if isinstance(value, str):
            value = json.loads(value)
        return EditableChapterOutlineContent.model_validate(value)

    def _editable_from_outline(
        self,
        value: object,
    ) -> EditableChapterOutlineContent:
        if isinstance(value, ChapterOutline):
            raw = value.model_dump(mode="json", by_alias=True)
        else:
            if isinstance(value, (bytes, bytearray)):
                value = bytes(value).decode("utf-8")
            if isinstance(value, str):
                value = json.loads(value)
            if not isinstance(value, Mapping):
                raise ChapterOutlinePreconditionFailed(
                    "ChapterOutline content is invalid"
                )
            raw = dict(value)
        aliases = {
            field.alias
            for field in EditableChapterOutlineContent.model_fields.values()
        }
        editable = {
            key: raw[key]
            for key in aliases
            if key in raw
        }
        editable["schemaVersion"] = "chapter-outline-draft-v1"
        return EditableChapterOutlineContent.model_validate(editable)

    def _editable_payload(
        self,
        content: EditableChapterOutlineContent,
    ) -> dict[str, object]:
        if not isinstance(content, EditableChapterOutlineContent):
            raise ChapterOutlineRequestInvalid(
                "editable ChapterOutline content is required"
            )
        return content.model_dump(mode="json", by_alias=True)

    def _planning(self, value: object) -> PlanningAggregate:
        if isinstance(value, PlanningAggregate):
            return value
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("utf-8")
        if isinstance(value, str):
            value = json.loads(value)
        return PlanningAggregate.model_validate(value)

    def _capacity_policy(self, value: object) -> OutlineCapacityPolicy:
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("utf-8")
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, Mapping):
            raise ValueError("chapter capacity policy is invalid")
        word_range = value.get("chapterWordRangePreference")
        if (
            not isinstance(word_range, (list, tuple))
            or len(word_range) != 2
            or any(type(item) is not int for item in word_range)
        ):
            raise ValueError("chapter capacity policy is invalid")
        target_min, target_max = word_range
        return OutlineCapacityPolicy.model_validate(
            {
                "targetMin": target_min,
                "targetMax": target_max,
                "softCeiling": target_max,
            }
        )

    def _require_requested_chapter(
        self,
        requested: int,
        authoritative: int,
    ) -> None:
        if requested != authoritative:
            raise ChapterOutlineConflict(
                "requested chapter differs from server authority"
            )

    def _require_no_active_session(
        self,
        active_session: Mapping[str, object] | None,
    ) -> None:
        if active_session is not None:
            raise ChapterOutlineConflict(
                "active ChapterSession makes Outline read-only"
            )

    def _require_active_draft(
        self,
        row: Mapping[str, object] | None,
    ) -> None:
        if row is None:
            raise ChapterOutlineNotFound(
                "ChapterOutline Draft not found"
            )
        if row["status"] != "active" or row.get("active_slot", 1) != 1:
            raise ChapterOutlineConflict(
                "ChapterOutline Draft is not active"
            )

    def _require_draft_cas(
        self,
        row: Mapping[str, object],
        expected_revision: int,
        expected_hash: str,
    ) -> None:
        if (
            int(row["draft_revision"]) != expected_revision
            or str(row["content_hash"]) != expected_hash
        ):
            raise ChapterOutlineConflict(
                "ChapterOutline Draft revision conflict"
            )

    @staticmethod
    def _head_revision(head: Mapping[str, object] | None) -> int:
        return 0 if head is None else int(head["revision"])

    def _validate_project(self, project_id: str) -> None:
        if not isinstance(project_id, str) or not project_id.strip():
            raise ChapterOutlineRequestInvalid("project_id is required")

    def _validate_project_chapter(
        self,
        project_id: str,
        chapter_number: int,
    ) -> None:
        self._validate_project(project_id)
        if type(chapter_number) is not int or chapter_number < 1:
            raise ChapterOutlineRequestInvalid(
                "chapter_number is invalid"
            )

    def _validate_save(
        self,
        command: SaveChapterOutlineDraft,
    ) -> None:
        self._validate_project_chapter(
            command.project_id,
            command.chapter_number,
        )
        if not command.draft_id:
            raise ChapterOutlineRequestInvalid("draft_id is required")
        if command.expected_draft_revision < 1:
            raise ChapterOutlineRequestInvalid(
                "expected Draft revision is invalid"
            )
        if _HASH.fullmatch(command.expected_draft_hash or "") is None:
            raise ChapterOutlineRequestInvalid(
                "expected Draft hash is invalid"
            )
        if not isinstance(
            command.content,
            EditableChapterOutlineContent,
        ):
            raise ChapterOutlineRequestInvalid(
                "editable ChapterOutline content is required"
            )

    def _validate_confirm(
        self,
        command: ConfirmChapterOutlineDraft,
    ) -> None:
        self._validate_project_chapter(
            command.project_id,
            command.chapter_number,
        )
        if not command.draft_id:
            raise ChapterOutlineRequestInvalid("draft_id is required")
        if command.expected_draft_revision < 1:
            raise ChapterOutlineRequestInvalid(
                "expected Draft revision is invalid"
            )
        if _HASH.fullmatch(command.expected_draft_hash or "") is None:
            raise ChapterOutlineRequestInvalid(
                "expected Draft hash is invalid"
            )
        if command.expected_head_revision < 0:
            raise ChapterOutlineRequestInvalid(
                "expected head revision is invalid"
            )
        if _IDEMPOTENCY_KEY.fullmatch(
            command.idempotency_key or ""
        ) is None:
            raise ChapterOutlineRequestInvalid(
                "idempotency key is invalid"
            )

    def _hit(self, stage: str) -> None:
        if self.failpoint is not None:
            self.failpoint(stage)


__all__ = (
    "ActiveChapterSessionResult",
    "CanonProjectionAuthorityResult",
    "ChapterOutlineArchived",
    "ChapterOutlineBasisResult",
    "ChapterOutlineCapabilities",
    "ChapterOutlineConflict",
    "ChapterOutlineDraftResult",
    "ChapterOutlineError",
    "ChapterOutlineNotFound",
    "ChapterOutlineOperationResult",
    "ChapterOutlinePreconditionFailed",
    "ChapterOutlineRequestInvalid",
    "ChapterOutlineRevisionResult",
    "ChapterOutlineService",
    "ChapterOutlineState",
    "ConfirmChapterOutlineDraft",
    "CreateChapterOutlineDraft",
    "PlanningAuthorityResult",
    "SaveChapterOutlineDraft",
    "authoritative_chapter",
)
