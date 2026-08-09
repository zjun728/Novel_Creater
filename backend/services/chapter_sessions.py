from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import time
from typing import Any, Mapping
from uuid import UUID, uuid4

from backend.domain.drafts import (
    ChapterSessionView,
    ChapterWorkspace,
    DraftCandidateView,
    WorkingDraftView,
)
from backend.domain.json_contracts import canonical_hash
from backend.http_errors import ProjectNotFound
from backend.repositories.chapter_sessions import (
    ActiveChapterSessionConflict,
    authoritative_chapter,
)


class ChapterSessionError(RuntimeError):
    pass


class ChapterSessionNotFound(ChapterSessionError):
    pass


class ChapterSessionConflict(ChapterSessionError):
    pass


class ChapterSessionPreconditionFailed(ChapterSessionError):
    pass


class ChapterSessionRequestInvalid(ChapterSessionError):
    pass


def _canonical_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except (ValueError, AttributeError, TypeError):
        return False


@dataclass(frozen=True)
class CreateChapterSession:
    project_id: str
    chapter_number: int
    expected_planning_revision: int
    expected_planning_hash: str
    expected_outline_revision: int
    expected_outline_hash: str
    expected_canon_revision: int


@dataclass(frozen=True)
class SaveWorkingDraft:
    project_id: str
    chapter_session_id: str
    expected_revision: int
    expected_content_hash: str
    content: str


@dataclass(frozen=True)
class SaveDraftCandidate:
    project_id: str
    chapter_session_id: str
    expected_working_draft_revision: int
    expected_content_hash: str
    idempotency_key: str


@dataclass(frozen=True)
class LoadDraftCandidate:
    project_id: str
    chapter_session_id: str
    candidate_id: str
    expected_working_draft_revision: int
    expected_content_hash: str


@dataclass(frozen=True)
class CandidateSaveResult:
    workspace: ChapterWorkspace
    saved_candidate_id: str

    @property
    def project_id(self) -> str:
        return self.workspace.project_id

    @property
    def session(self) -> ChapterSessionView:
        return self.workspace.session

    @property
    def working_draft(self) -> WorkingDraftView:
        return self.workspace.working_draft

    @property
    def candidates(self) -> tuple[DraftCandidateView, ...]:
        return self.workspace.candidates


class ChapterSessionService:
    _CANDIDATE_BASIS_SCHEMA_VERSION = "draft-candidate-basis-v1"
    _CANDIDATE_BASIS_KEYS = (
        "schemaVersion",
        "outlineRevisionId",
        "outlineRevision",
        "outlineHash",
        "planningRevisionId",
        "planningRevision",
        "planningHash",
        "canonRevision",
        "projectionRevision",
        "projectionHash",
    )
    _GENERATION_FIELDS = (
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

    def __init__(self, repository, *, transaction_factory, connection_factory=None):
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.connection_factory = connection_factory

    async def get(
        self,
        project_id: str,
        chapter_number: int,
    ) -> ChapterWorkspace | None:
        if not project_id or chapter_number < 1:
            raise ChapterSessionRequestInvalid(
                "project and chapter are required",
            )
        if self.connection_factory is None:
            raise RuntimeError("Chapter session read connection is unavailable")
        async with self.connection_factory() as session:
            chapter_session = await self.repository.read_chapter_session(
                session,
                project_id,
                chapter_number,
            )
            if chapter_session is None:
                return None
            return await self._workspace(session, chapter_session)

    async def create_session(self, command: CreateChapterSession) -> ChapterWorkspace:
        self._validate_create_command(command)
        async with self.transaction_factory() as session:
            project = await self.repository.lock_project(session, command.project_id)
            if project is None:
                raise ChapterSessionNotFound("Project not found")
            try:
                active = await self.repository.read_active_session(
                    session,
                    command.project_id,
                )
            except ActiveChapterSessionConflict:
                raise ChapterSessionConflict(
                    "active ChapterSession authority is inconsistent"
                ) from None
            if active is not None:
                chapter_number = authoritative_chapter(active, None)
                self._require_authoritative_chapter(
                    command.chapter_number,
                    chapter_number,
                )
                existing = await self.repository.read_chapter_session(
                    session,
                    command.project_id,
                    chapter_number,
                )
                if (
                    existing is None
                    or existing["id"] != active["id"]
                    or not self._matches_create_command(existing, command)
                ):
                    raise ChapterSessionConflict(
                        "active ChapterSession pins differ from request"
                    )
                return await self._workspace(session, existing)

            maximum = await self.repository.read_max_final_chapter_number(
                session,
                command.project_id,
            )
            chapter_number = authoritative_chapter(None, maximum)
            self._require_authoritative_chapter(
                command.chapter_number,
                chapter_number,
            )
            outline = await self.repository.read_current_outline(
                session,
                command.project_id,
                chapter_number,
            )
            if outline is None:
                raise ChapterSessionPreconditionFailed(
                    "current confirmed outline is required",
                )
            self._require_current_outline(outline, command)

            projection = await self.repository.read_projection_head(
                session,
                command.project_id,
            )
            if projection is None:
                raise ChapterSessionPreconditionFailed(
                    "Canon and Projection heads are required",
                )
            self._require_current_projection(outline, projection, command)
            existing = await self.repository.read_chapter_session(
                session,
                command.project_id,
                chapter_number,
            )
            if existing is not None:
                raise ChapterSessionConflict(
                    "existing ChapterSession conflicts with server authority"
                )

            canon_revision = int(projection["canon_revision_number"])

            now = int(time.time() * 1000)
            session_row = {
                "id": str(uuid4()),
                "project_id": command.project_id,
                "planning_revision_id": outline["planning_revision_id"],
                "planning_revision": int(outline["planning_revision"]),
                "planning_hash": outline["planning_hash"],
                "story_block_id": outline["story_block_id"],
                "story_block_revision": int(outline["story_block_revision"]),
                "story_block_hash": outline["story_block_hash"],
                "chapter_outline_revision_id": outline[
                    "chapter_outline_revision_id"
                ],
                "chapter_outline_revision": int(
                    outline["chapter_outline_revision"],
                ),
                "chapter_outline_hash": outline["chapter_outline_hash"],
                "chapter_num": chapter_number,
                "expected_canon_revision": canon_revision,
                "chapter_outline": outline["chapter_outline"],
                "status": "drafting",
                "created_at": now,
                "finalized_at": None,
            }
            if not await self.repository.insert_chapter_session(session, session_row):
                raise ChapterSessionConflict("chapter session was not created")
            draft_row = self._working_row(
                command.project_id,
                session_row["id"],
                revision=1,
                content="",
                source_payload={"source": "manual-empty"},
                updated_at=now,
            )
            if not await self.repository.upsert_working_draft(session, draft_row):
                raise ChapterSessionConflict("working draft was not created")
            return await self._workspace(session, session_row)

    def _require_authoritative_chapter(
        self,
        requested: int,
        authoritative: int,
    ) -> None:
        if requested != authoritative:
            raise ChapterSessionConflict(
                "requested chapter differs from server authority"
            )

    def _require_current_outline(
        self,
        outline: Mapping[str, Any],
        command: CreateChapterSession,
    ) -> None:
        if (
            outline.get("current_planning_revision_id")
            != outline["planning_revision_id"]
            or int(outline.get("current_planning_revision") or 0)
            != int(outline["planning_revision"])
            or outline.get("current_planning_hash")
            != outline["planning_hash"]
        ):
            raise ChapterSessionConflict(
                "Planning head differs from the confirmed Outline",
            )
        if any(
            outline.get(f"planning_{field}")
            != outline.get(f"current_{field}")
            for field in self._GENERATION_FIELDS
        ):
            raise ChapterSessionConflict(
                "Planning generation differs from current authorities",
            )
        if (
            command.expected_planning_revision
            != int(outline["planning_revision"])
            or command.expected_planning_hash != outline["planning_hash"]
        ):
            raise ChapterSessionConflict("Planning revision drift")
        if (
            command.expected_outline_revision
            != int(outline["chapter_outline_revision"])
            or command.expected_outline_hash
            != outline["chapter_outline_hash"]
        ):
            raise ChapterSessionConflict("Outline revision drift")

    def _require_current_projection(
        self,
        outline: Mapping[str, Any],
        projection: Mapping[str, Any],
        command: CreateChapterSession,
    ) -> None:
        canon_revision = int(projection["canon_revision_number"])
        projection_revision = int(
            projection["projection_revision_number"],
        )
        if canon_revision != projection_revision:
            raise ChapterSessionPreconditionFailed(
                "Canon and Projection must be synchronized",
            )
        if canon_revision != command.expected_canon_revision:
            raise ChapterSessionConflict("Canon revision drift")
        if (
            canon_revision != int(outline["canon_revision"])
            or projection_revision != int(outline["projection_revision"])
            or projection["content_hash"] != outline["projection_hash"]
        ):
            raise ChapterSessionConflict(
                "current Canon/Projection differs from Outline baseline",
            )

    async def save_working_draft(self, command: SaveWorkingDraft) -> ChapterWorkspace:
        self._validate_save_working_draft_command(command)
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(
                session, command.project_id
            ) is None:
                raise ProjectNotFound()
            chapter_session = await self.repository.read_session_by_id(
                session, command.project_id, command.chapter_session_id,
            )
            if chapter_session is None:
                raise ChapterSessionNotFound("Chapter session not found")
            effective_status = chapter_session.get(
                "effective_status", chapter_session["status"]
            )
            if effective_status == "superseded":
                raise ChapterSessionConflict("Chapter session is superseded")
            if effective_status != "drafting":
                raise ChapterSessionConflict("Chapter session is finalized")
            current = await self.repository.read_working_draft(
                session, command.chapter_session_id,
            )
            if (
                current is None
                or int(current["revision"]) != command.expected_revision
                or current["content_hash"] != command.expected_content_hash
            ):
                raise ChapterSessionConflict("working draft revision or hash drift")
            if current["content"] == command.content:
                return await self._workspace(session, chapter_session)
            content_hash = self._content_hash(command.content)
            row = self._working_row(
                command.project_id,
                command.chapter_session_id,
                revision=command.expected_revision + 1,
                content=command.content,
                content_hash=content_hash,
                source_payload=current.get("source_payload") or current.get("source_payload_json") or {},
                updated_at=int(time.time() * 1000),
                draft_id=current["id"],
            )
            if not await self.repository.upsert_working_draft(
                session,
                row,
                expected_revision=command.expected_revision,
                expected_content_hash=command.expected_content_hash,
            ):
                raise ChapterSessionConflict("working draft revision or hash drift")
            return await self._workspace(session, chapter_session)

    async def save_candidate(
        self,
        command: SaveDraftCandidate,
    ) -> CandidateSaveResult:
        self._validate_save_candidate_command(command)
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(
                session, command.project_id
            ) is None:
                raise ProjectNotFound()
            chapter_session = await self.repository.read_session_by_id(
                session, command.project_id, command.chapter_session_id,
            )
            if chapter_session is None:
                raise ChapterSessionNotFound("Chapter session not found")
            request_hash = canonical_hash({
                "projectId": command.project_id,
                "chapterSessionId": command.chapter_session_id,
                "workingDraftRevision": command.expected_working_draft_revision,
                "contentHash": command.expected_content_hash,
            })
            freeze_request = await self.repository.read_candidate_freeze_request(
                session,
                command.chapter_session_id,
                command.idempotency_key,
            )
            if freeze_request is not None:
                if freeze_request["request_hash"] != request_hash:
                    raise ChapterSessionConflict("candidate idempotency conflict")
                return CandidateSaveResult(
                    await self._workspace(session, chapter_session),
                    str(freeze_request["draft_candidate_id"]),
                )
            effective_status = chapter_session.get(
                "effective_status", chapter_session["status"]
            )
            if effective_status == "superseded":
                raise ChapterSessionConflict("Chapter session is superseded")
            if effective_status != "drafting":
                raise ChapterSessionConflict("Chapter session is finalized")
            authority = await self.repository.read_current_outline(
                session,
                command.project_id,
                int(chapter_session["chapter_num"]),
            )
            if authority is None:
                raise ChapterSessionPreconditionFailed(
                    "current Outline authority is required"
                )
            basis, basis_hash = self._candidate_basis(authority)
            draft = await self.repository.read_working_draft(session, command.chapter_session_id)
            if draft is None:
                raise ChapterSessionPreconditionFailed("working draft is required")
            if (
                int(draft["revision"])
                != command.expected_working_draft_revision
                or draft["content_hash"] != command.expected_content_hash
            ):
                raise ChapterSessionConflict("working draft revision or hash drift")
            if not str(draft["content"]).strip():
                raise ChapterSessionPreconditionFailed("working draft content is empty")
            candidate = {
                "id": str(uuid4()), "project_id": command.project_id,
                "chapter_session_id": command.chapter_session_id,
                "working_draft_revision": int(draft["revision"]),
                "content": draft["content"], "content_hash": draft["content_hash"],
                "basis_hash": basis_hash,
                "provenance": {
                    "source": "explicit-save-candidate",
                    "workingDraftRevision": int(draft["revision"]),
                    **basis,
                },
                "created_at": int(time.time() * 1000),
            }
            if not await self.repository.insert_candidate(session, candidate):
                raise ChapterSessionConflict("candidate identity conflict")
            persisted_candidate = await self.repository.read_candidate_by_identity(
                session,
                command.chapter_session_id,
                candidate["content_hash"],
                basis_hash,
            )
            if persisted_candidate is None:
                raise ChapterSessionConflict("candidate identity conflict")
            if not await self.repository.insert_candidate_freeze_request(session, {
                "id": str(uuid4()),
                "project_id": command.project_id,
                "chapter_session_id": command.chapter_session_id,
                "idempotency_key": command.idempotency_key,
                "request_hash": request_hash,
                "draft_candidate_id": persisted_candidate["id"],
                "created_at": int(time.time() * 1000),
            }):
                raise ChapterSessionConflict("candidate freeze request conflict")
            return CandidateSaveResult(
                await self._workspace(session, chapter_session),
                str(persisted_candidate["id"]),
            )

    async def load_candidate(
        self,
        command: LoadDraftCandidate,
    ) -> ChapterWorkspace:
        self._validate_load_candidate_command(command)
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(
                session, command.project_id
            ) is None:
                raise ProjectNotFound()
            locked_session = await self.repository.lock_session_for_operation(
                session, command.project_id, command.chapter_session_id,
            )
            if locked_session is None:
                raise ChapterSessionNotFound("Chapter session not found")
            chapter_session = await self.repository.read_session_by_id(
                session, command.project_id, command.chapter_session_id,
            )
            if chapter_session is None:
                raise ChapterSessionNotFound("Chapter session not found")
            effective_status = chapter_session.get(
                "effective_status", chapter_session["status"]
            )
            if effective_status == "superseded":
                raise ChapterSessionConflict("Chapter session is superseded")
            if effective_status != "drafting":
                raise ChapterSessionConflict("Chapter session is finalized")
            if chapter_session.get("active_draft_operation_id") is not None:
                raise ChapterSessionConflict("draft operation is active")
            draft = await self.repository.lock_working_draft_for_operation(
                session, command.project_id, command.chapter_session_id,
            )
            if draft is None:
                raise ChapterSessionPreconditionFailed("working draft is required")
            if (
                int(draft["revision"])
                != command.expected_working_draft_revision
                or draft["content_hash"] != command.expected_content_hash
            ):
                raise ChapterSessionConflict("working draft revision or hash drift")
            candidate = await self.repository.read_candidate_for_load(
                session,
                command.project_id,
                command.chapter_session_id,
                command.candidate_id,
            )
            if candidate is None:
                raise ChapterSessionConflict("candidate is unavailable")
            content = candidate.get("content")
            content_hash = candidate.get("content_hash")
            try:
                verified_content_hash = (
                    self._content_hash(content) if type(content) is str else None
                )
            except UnicodeEncodeError:
                verified_content_hash = None
            if (
                type(content) is not str
                or type(content_hash) is not str
                or re.fullmatch(r"[0-9a-f]{64}", content_hash) is None
                or verified_content_hash != content_hash
            ):
                raise ChapterSessionConflict("candidate content is invalid")
            now = int(time.time() * 1000)
            next_revision = int(draft["revision"]) + 1
            recovery_common = {
                "project_id": command.project_id,
                "chapter_session_id": command.chapter_session_id,
                "working_draft_id": draft["id"],
                "replacement_reason": "candidate_load",
                "source_operation_id": None,
                "source_candidate_id": candidate["id"],
                "created_at": now,
            }
            if not await self.repository.insert_working_draft_revision(
                session,
                {
                    **recovery_common,
                    "id": str(uuid4()),
                    "working_draft_revision": int(draft["revision"]),
                    "snapshot_role": "before",
                    "content": draft["content"],
                    "content_hash": draft["content_hash"],
                },
            ):
                raise ChapterSessionConflict("candidate load recovery conflict")
            row = self._working_row(
                command.project_id,
                command.chapter_session_id,
                revision=next_revision,
                content=content,
                content_hash=content_hash,
                source_payload={
                    "source": "candidate-load",
                    "candidateId": candidate["id"],
                    "candidateContentHash": content_hash,
                    "baseWorkingDraftRevision": int(draft["revision"]),
                },
                updated_at=now,
                draft_id=draft["id"],
            )
            if not await self.repository.upsert_working_draft(
                session,
                row,
                expected_revision=command.expected_working_draft_revision,
                expected_content_hash=command.expected_content_hash,
            ):
                raise ChapterSessionConflict("working draft revision or hash drift")
            if not await self.repository.insert_working_draft_revision(
                session,
                {
                    **recovery_common,
                    "id": str(uuid4()),
                    "working_draft_revision": next_revision,
                    "snapshot_role": "after",
                    "content": content,
                    "content_hash": content_hash,
                },
            ):
                raise ChapterSessionConflict("candidate load recovery conflict")
            return await self._workspace(session, chapter_session)

    async def _workspace(self, session, chapter_session: Mapping[str, Any]) -> ChapterWorkspace:
        draft = await self.repository.read_working_draft(session, chapter_session["id"])
        candidates = await self.repository.list_candidates(session, chapter_session["id"])
        authority = await self.repository.read_current_outline(
            session,
            chapter_session["project_id"],
            int(chapter_session["chapter_num"]),
        )
        if draft is None:
            raise ChapterSessionPreconditionFailed("working draft is required")
        active_draft_operation_id = chapter_session.get(
            "active_draft_operation_id"
        )
        if (
            active_draft_operation_id is not None
            and not _canonical_uuid(active_draft_operation_id)
        ):
            raise ChapterSessionConflict(
                "active draft operation authority is invalid"
            )
        return ChapterWorkspace(
            project_id=chapter_session["project_id"],
            session=self._session_view(chapter_session),
            working_draft=self._draft_view(draft),
            candidates=tuple(
                self._candidate_view(row, authority) for row in candidates
            ),
            active_draft_operation_id=active_draft_operation_id,
        )

    def _validate_create_command(self, command: CreateChapterSession) -> None:
        if (
            type(command.project_id) is not str
            or not command.project_id
            or type(command.chapter_number) is not int
            or command.chapter_number < 1
            or type(command.expected_planning_revision) is not int
            or command.expected_planning_revision < 1
            or type(command.expected_outline_revision) is not int
            or command.expected_outline_revision < 1
            or type(command.expected_canon_revision) is not int
            or command.expected_canon_revision < 0
            or type(command.expected_planning_hash) is not str
            or re.fullmatch(
                r"[0-9a-f]{64}",
                command.expected_planning_hash,
            ) is None
            or type(command.expected_outline_hash) is not str
            or re.fullmatch(
                r"[0-9a-f]{64}",
                command.expected_outline_hash,
            ) is None
        ):
            raise ChapterSessionRequestInvalid(
                "chapter session create command is invalid",
            )

    def _validate_save_working_draft_command(
        self,
        command: SaveWorkingDraft,
    ) -> None:
        if (
            type(command.project_id) is not str
            or not command.project_id
            or type(command.chapter_session_id) is not str
            or not command.chapter_session_id
            or type(command.expected_revision) is not int
            or command.expected_revision < 1
            or type(command.expected_content_hash) is not str
            or re.fullmatch(r"[0-9a-f]{64}", command.expected_content_hash)
            is None
            or type(command.content) is not str
            or len(command.content) > 100_000
        ):
            raise ChapterSessionRequestInvalid(
                "working draft save command is invalid",
            )

    def _validate_save_candidate_command(
        self,
        command: SaveDraftCandidate,
    ) -> None:
        if (
            type(command.project_id) is not str
            or not command.project_id
            or type(command.chapter_session_id) is not str
            or not command.chapter_session_id
            or type(command.expected_working_draft_revision) is not int
            or command.expected_working_draft_revision < 1
            or type(command.expected_content_hash) is not str
            or re.fullmatch(r"[0-9a-f]{64}", command.expected_content_hash)
            is None
            or type(command.idempotency_key) is not str
            or re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                command.idempotency_key,
            ) is None
        ):
            raise ChapterSessionRequestInvalid(
                "candidate save command is invalid",
            )

    def _validate_load_candidate_command(
        self,
        command: LoadDraftCandidate,
    ) -> None:
        if (
            type(command.project_id) is not str
            or not command.project_id
            or type(command.chapter_session_id) is not str
            or not command.chapter_session_id
            or type(command.candidate_id) is not str
            or not command.candidate_id
            or type(command.expected_working_draft_revision) is not int
            or command.expected_working_draft_revision < 1
            or type(command.expected_content_hash) is not str
            or re.fullmatch(r"[0-9a-f]{64}", command.expected_content_hash)
            is None
        ):
            raise ChapterSessionRequestInvalid(
                "candidate load command is invalid",
            )

    def _matches_create_command(
        self,
        session: Mapping[str, Any],
        command: CreateChapterSession,
    ) -> bool:
        return (
            int(session["chapter_num"]) == command.chapter_number
            and int(session["planning_revision"])
            == command.expected_planning_revision
            and session["planning_hash"] == command.expected_planning_hash
            and int(session["chapter_outline_revision"])
            == command.expected_outline_revision
            and session["chapter_outline_hash"]
            == command.expected_outline_hash
            and int(session["expected_canon_revision"])
            == command.expected_canon_revision
        )

    def _working_row(
        self, project_id: str, chapter_session_id: str, *, revision: int,
        content: str, source_payload: Mapping[str, Any], updated_at: int,
        draft_id: str | None = None, content_hash: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": draft_id or str(uuid4()), "project_id": project_id,
            "chapter_session_id": chapter_session_id, "revision": revision,
            "content": content,
            "content_hash": content_hash or self._content_hash(content),
            "source_payload": dict(source_payload), "updated_at": updated_at,
        }

    def _candidate_basis(
        self,
        authority: Mapping[str, Any],
    ) -> tuple[dict[str, Any], str]:
        payload = {
            "schemaVersion": self._CANDIDATE_BASIS_SCHEMA_VERSION,
            "outlineRevisionId": authority["chapter_outline_revision_id"],
            "outlineRevision": int(authority["chapter_outline_revision"]),
            "outlineHash": authority["chapter_outline_hash"],
            "planningRevisionId": authority["planning_revision_id"],
            "planningRevision": int(authority["planning_revision"]),
            "planningHash": authority["planning_hash"],
            "canonRevision": int(authority["canon_revision"]),
            "projectionRevision": int(authority["projection_revision"]),
            "projectionHash": authority["projection_hash"],
        }
        return payload, canonical_hash(payload)

    def _content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _session_view(self, row) -> ChapterSessionView:
        return ChapterSessionView(
            id=row["id"],
            project_id=row["project_id"],
            planning_revision_id=row["planning_revision_id"],
            planning_revision=int(row["planning_revision"]),
            planning_hash=row["planning_hash"],
            story_block_id=row["story_block_id"],
            story_block_revision=int(row["story_block_revision"]),
            story_block_hash=row["story_block_hash"],
            chapter_outline_revision_id=row["chapter_outline_revision_id"],
            chapter_outline_revision=int(row["chapter_outline_revision"]),
            chapter_outline_hash=row["chapter_outline_hash"],
            chapter_num=int(row["chapter_num"]),
            expected_canon_revision=int(row["expected_canon_revision"]),
            status=row.get("effective_status", row["status"]),
        )

    def _draft_view(self, row) -> WorkingDraftView:
        return WorkingDraftView(
            id=row["id"], project_id=row["project_id"],
            chapter_session_id=row["chapter_session_id"],
            revision=int(row["revision"]), content=row["content"],
            content_hash=row["content_hash"],
            source_payload=row.get("source_payload") or {},
            status=row.get("effective_status", "drafting"),
        )

    def _candidate_view(
        self,
        row,
        authority: Mapping[str, Any] | None,
    ) -> DraftCandidateView:
        basis = self._validated_candidate_basis(row)
        matches = basis is not None and authority is not None and (
            basis["outlineRevisionId"]
            == authority["chapter_outline_revision_id"]
            and basis["outlineRevision"]
            == authority["chapter_outline_revision"]
            and basis["outlineHash"] == authority["chapter_outline_hash"]
            and basis["planningRevisionId"]
            == authority["planning_revision_id"]
            and basis["planningRevision"]
            == authority["planning_revision"]
            and basis["planningHash"] == authority["planning_hash"]
        )
        return DraftCandidateView(
            id=row["id"], project_id=row["project_id"],
            chapter_session_id=row["chapter_session_id"],
            working_draft_revision=int(row["working_draft_revision"]),
            content=row["content"], content_hash=row["content_hash"],
            outline_revision_id=None if basis is None else basis["outlineRevisionId"],
            outline_revision=None if basis is None else basis["outlineRevision"],
            outline_hash=None if basis is None else basis["outlineHash"],
            planning_revision_id=None if basis is None else basis["planningRevisionId"],
            planning_revision=None if basis is None else basis["planningRevision"],
            planning_hash=None if basis is None else basis["planningHash"],
            canon_revision=None if basis is None else basis["canonRevision"],
            projection_revision=None if basis is None else basis["projectionRevision"],
            projection_hash=None if basis is None else basis["projectionHash"],
            basis_status="current" if matches else "stale",
            created_at=int(row.get("created_at") or 0),
            status=row.get("effective_status", "drafting"),
        )

    def _validated_candidate_basis(self, row) -> dict[str, Any] | None:
        provenance = row.get("provenance")
        basis_hash = row.get("basis_hash")
        if not isinstance(provenance, Mapping):
            return None
        try:
            payload = {key: provenance[key] for key in self._CANDIDATE_BASIS_KEYS}
        except KeyError:
            return None
        if payload["schemaVersion"] != self._CANDIDATE_BASIS_SCHEMA_VERSION:
            return None
        if any(
            type(payload[key]) is not str or not payload[key]
            for key in ("outlineRevisionId", "planningRevisionId")
        ):
            return None
        if any(
            type(payload[key]) is not int or payload[key] < minimum
            for key, minimum in (
                ("outlineRevision", 1),
                ("planningRevision", 1),
                ("canonRevision", 0),
                ("projectionRevision", 0),
            )
        ):
            return None
        if any(
            type(payload[key]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", payload[key]) is None
            for key in ("outlineHash", "planningHash", "projectionHash")
        ):
            return None
        if (
            type(basis_hash) is not str
            or re.fullmatch(r"[0-9a-f]{64}", basis_hash) is None
            or basis_hash != canonical_hash(payload)
        ):
            return None
        return payload
