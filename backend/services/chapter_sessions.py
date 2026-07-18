from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time
from typing import Any, Mapping
from uuid import uuid4

from backend.domain.drafts import (
    ChapterSessionView,
    ChapterWorkspace,
    DraftCandidateView,
    WorkingDraftView,
)
from backend.http_errors import ProjectNotFound


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


@dataclass(frozen=True)
class CreateChapterSession:
    project_id: str
    expected_story_block_revision: int
    expected_canon_revision: int


@dataclass(frozen=True)
class SaveWorkingDraft:
    project_id: str
    chapter_session_id: str
    expected_revision: int
    content: str


@dataclass(frozen=True)
class SaveDraftCandidate:
    project_id: str
    chapter_session_id: str
    expected_working_draft_revision: int


class ChapterSessionService:
    def __init__(self, repository, *, transaction_factory, connection_factory=None):
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.connection_factory = connection_factory

    async def get_current(self, project_id: str) -> ChapterWorkspace | None:
        if self.connection_factory is None:
            raise RuntimeError("Chapter session read connection is unavailable")
        async with self.connection_factory() as session:
            current = await self.repository.read_latest_chapter_session(session, project_id)
            if current is None:
                return None
            return await self._workspace(session, current)

    async def create_session(self, command: CreateChapterSession) -> ChapterWorkspace:
        if not command.project_id:
            raise ChapterSessionRequestInvalid("project_id is required")
        async with self.transaction_factory() as session:
            project = await self.repository.lock_project(session, command.project_id)
            if project is None:
                raise ChapterSessionNotFound("Project not found")
            plan = await self.repository.read_active_plan(session, command.project_id)
            if plan is None:
                raise ChapterSessionPreconditionFailed("active planning is required")
            block = plan["block"]
            if int(block["revision"]) != command.expected_story_block_revision:
                raise ChapterSessionConflict("story block revision drift")
            canon = await self.repository.read_projection_head(session, command.project_id)
            canon_revision = int((canon or {}).get("canon_revision_number") or 0)
            if canon_revision != command.expected_canon_revision:
                raise ChapterSessionConflict("canon revision drift")
            chapter_num = int(project.get("current_chapter") or 0) + 1
            existing = await self.repository.read_chapter_session(
                session, command.project_id, chapter_num,
            )
            if existing is not None:
                return await self._workspace(session, existing)
            now = int(time.time() * 1000)
            session_row = {
                "id": str(uuid4()), "project_id": command.project_id,
                "selection_revision": int(plan["selection_revision"]),
                "contract_revision": int(plan["contract_revision"]),
                "contract_hash": plan["contract_hash"],
                "bible_revision": int(plan["bible_revision"]),
                "bible_hash": plan["bible_hash"],
                "volume_plan_id": plan["volume"]["id"],
                "planning_manifest_hash": plan["manifest_hash"],
                "story_block_id": block["id"], "chapter_num": chapter_num,
                "expected_canon_revision": canon_revision,
                "expected_story_block_revision": int(block["revision"]),
                "planning_snapshot": self._planning_snapshot(plan),
                "status": "drafting", "created_at": now, "finalized_at": None,
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

    async def save_working_draft(self, command: SaveWorkingDraft) -> ChapterWorkspace:
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(
                session, command.project_id
            ) is None:
                raise ProjectNotFound()
            chapter_session = await self.repository.read_session_by_id(
                session, command.project_id, command.chapter_session_id,
            ) if hasattr(self.repository, "read_session_by_id") else None
            if chapter_session is None:
                latest = await self.repository.read_latest_chapter_session(
                    session, command.project_id,
                )
                if latest and latest["id"] == command.chapter_session_id:
                    chapter_session = latest
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
            if current is None or int(current["revision"]) != command.expected_revision:
                raise ChapterSessionConflict("working draft revision drift")
            row = self._working_row(
                command.project_id,
                command.chapter_session_id,
                revision=command.expected_revision + 1,
                content=command.content,
                source_payload=current.get("source_payload") or current.get("source_payload_json") or {},
                updated_at=int(time.time() * 1000),
                draft_id=current["id"],
            )
            if not await self.repository.upsert_working_draft(session, row):
                raise ChapterSessionConflict("working draft was not saved")
            return await self._workspace(session, chapter_session)

    async def save_candidate(self, command: SaveDraftCandidate) -> ChapterWorkspace:
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(
                session, command.project_id
            ) is None:
                raise ProjectNotFound()
            chapter_session = await self.repository.read_session_by_id(
                session, command.project_id, command.chapter_session_id,
            ) if hasattr(self.repository, "read_session_by_id") else None
            if chapter_session is None:
                latest = await self.repository.read_latest_chapter_session(
                    session, command.project_id,
                )
                if latest and latest["id"] == command.chapter_session_id:
                    chapter_session = latest
            if chapter_session is None:
                raise ChapterSessionNotFound("Chapter session not found")
            if chapter_session.get(
                "effective_status", chapter_session["status"]
            ) == "superseded":
                raise ChapterSessionConflict("Chapter session is superseded")
            draft = await self.repository.read_working_draft(session, command.chapter_session_id)
            if draft is None:
                raise ChapterSessionPreconditionFailed("working draft is required")
            if int(draft["revision"]) != command.expected_working_draft_revision:
                raise ChapterSessionConflict("working draft revision drift")
            if not str(draft["content"]).strip():
                raise ChapterSessionPreconditionFailed("working draft content is empty")
            candidate = {
                "id": str(uuid4()), "project_id": command.project_id,
                "chapter_session_id": command.chapter_session_id,
                "working_draft_revision": int(draft["revision"]),
                "content": draft["content"], "content_hash": draft["content_hash"],
                "provenance": {
                    "source": "explicit-save-candidate",
                    "workingDraftRevision": int(draft["revision"]),
                },
                "created_at": int(time.time() * 1000),
            }
            await self.repository.insert_candidate(session, candidate)
            return await self._workspace(session, chapter_session)

    async def _workspace(self, session, chapter_session: Mapping[str, Any]) -> ChapterWorkspace:
        draft = await self.repository.read_working_draft(session, chapter_session["id"])
        candidates = await self.repository.list_candidates(session, chapter_session["id"])
        if draft is None:
            raise ChapterSessionPreconditionFailed("working draft is required")
        return ChapterWorkspace(
            project_id=chapter_session["project_id"],
            session=self._session_view(chapter_session),
            working_draft=self._draft_view(draft),
            candidates=tuple(self._candidate_view(row) for row in candidates),
        )

    def _planning_snapshot(self, plan: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "manifestHash": plan.get("manifest_hash"),
            "storyBlock": plan["block"]["payload"],
            "storyBlockId": plan["block"]["id"],
            "storyBlockRevision": int(plan["block"]["revision"]),
            "stages": [stage["payload"] for stage in plan.get("stages", ())],
            "sceneTasks": [task["payload"] for task in plan.get("scene_tasks", ())],
        }

    def _working_row(
        self, project_id: str, chapter_session_id: str, *, revision: int,
        content: str, source_payload: Mapping[str, Any], updated_at: int,
        draft_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": draft_id or str(uuid4()), "project_id": project_id,
            "chapter_session_id": chapter_session_id, "revision": revision,
            "content": content, "content_hash": self._content_hash(content),
            "source_payload": dict(source_payload), "updated_at": updated_at,
        }

    def _content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _session_view(self, row) -> ChapterSessionView:
        return ChapterSessionView(
            id=row["id"], project_id=row["project_id"],
            story_block_id=row["story_block_id"], chapter_num=int(row["chapter_num"]),
            expected_canon_revision=int(row["expected_canon_revision"]),
            expected_story_block_revision=int(row["expected_story_block_revision"]),
            planning_snapshot=row["planning_snapshot"],
            status=row.get("effective_status", row["status"]),
            selection_revision=int(row["selection_revision"]),
            contract_revision=int(row["contract_revision"]),
            contract_hash=row["contract_hash"],
            bible_revision=int(row["bible_revision"]),
            bible_hash=row["bible_hash"],
            volume_plan_id=row["volume_plan_id"],
            planning_manifest_hash=row["planning_manifest_hash"],
        )

    def _draft_view(self, row) -> WorkingDraftView:
        return WorkingDraftView(
            id=row["id"], project_id=row["project_id"],
            chapter_session_id=row["chapter_session_id"],
            revision=int(row["revision"]), content=row["content"],
            content_hash=row["content_hash"],
            source_payload=row.get("source_payload") or {},
        )

    def _candidate_view(self, row) -> DraftCandidateView:
        return DraftCandidateView(
            id=row["id"], project_id=row["project_id"],
            chapter_session_id=row["chapter_session_id"],
            working_draft_revision=int(row["working_draft_revision"]),
            content=row["content"], content_hash=row["content_hash"],
            provenance=row.get("provenance") or {},
        )
