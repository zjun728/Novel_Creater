from __future__ import annotations

import pytest

from backend import http_errors


class FakeChapterRepository:
    def __init__(self):
        self.archived = False
        self.project = {"id": "p1", "current_chapter": 0}
        self.canon = {"canon_revision_number": 0}
        self.plan = {
            "manifest_hash": "a" * 64,
            "selection_revision": 3,
            "contract_revision": 1,
            "contract_hash": "c" * 64,
            "bible_revision": 2,
            "bible_hash": "b" * 64,
            "volume": {"id": "volume-1"},
            "block": {
                "id": "block-1", "project_id": "p1", "revision": 1,
                "title": "典籍入山河", "payload": {"goal": "入局"},
            },
            "stages": [{
                "id": "stage-1", "project_id": "p1", "story_block_id": "block-1",
                "stage_order": 1, "title": "入局", "payload": {"purpose": "入局"},
                "revision": 1, "status": "in_progress",
            }],
            "scene_tasks": [{
                "id": "task-1", "project_id": "p1", "story_stage_id": "stage-1",
                "task_order": 1, "payload": {"task": "写一个具体麻烦"},
                "revision": 1, "status": "pending",
            }],
        }
        self.session = None
        self.sessions = []
        self.generation_current = True
        self.working_draft = None
        self.working_drafts = {}
        self.candidates = []

    async def lock_project(self, session, project_id):
        if self.archived:
            raise http_errors.ProjectArchived()
        return self.project if project_id == "p1" else None

    async def read_active_plan(self, session, project_id):
        return self.plan

    async def read_projection_head(self, session, project_id):
        return self.canon

    def _effective_status(self, row):
        current = (
            self.generation_current
            and row["selection_revision"] == self.plan["selection_revision"]
            and row["contract_revision"] == self.plan["contract_revision"]
            and row["contract_hash"] == self.plan["contract_hash"]
            and row["bible_revision"] == self.plan["bible_revision"]
            and row["bible_hash"] == self.plan["bible_hash"]
            and row["volume_plan_id"] == self.plan["volume"]["id"]
            and row["planning_manifest_hash"] == self.plan["manifest_hash"]
        )
        return row["status"] if current else "superseded"

    async def read_chapter_session(
        self, session, project_id, chapter_num, generation=None,
    ):
        for row in reversed(self.sessions):
            if row["chapter_num"] != chapter_num:
                continue
            if generation is not None and any(
                row[key] != generation[key]
                for key in (
                    "selection_revision", "contract_revision", "contract_hash",
                    "bible_revision", "bible_hash", "volume_plan_id",
                    "planning_manifest_hash",
                )
            ):
                continue
            return row | {"effective_status": self._effective_status(row)}
        return None

    async def read_latest_chapter_session(self, session, project_id):
        if self.session is None:
            return None
        return self.session | {"effective_status": self._effective_status(self.session)}

    async def read_session_by_id(self, session, project_id, chapter_session_id):
        for row in self.sessions:
            if row["id"] == chapter_session_id:
                return row | {"effective_status": self._effective_status(row)}
        return None

    async def insert_chapter_session(self, session, row):
        self.session = row
        self.sessions.append(row)
        return True

    async def read_working_draft(self, session, chapter_session_id):
        row = self.working_drafts.get(chapter_session_id)
        if row is None:
            return None
        chapter_session = next(
            item for item in self.sessions if item["id"] == chapter_session_id
        )
        return row | {"effective_status": self._effective_status(chapter_session)}

    async def upsert_working_draft(self, session, row):
        self.working_draft = row
        self.working_drafts[row["chapter_session_id"]] = row
        return True

    async def insert_candidate(self, session, row):
        if any(item["content_hash"] == row["content_hash"] for item in self.candidates):
            return False
        self.candidates.append(row)
        return True

    async def list_candidates(self, session, chapter_session_id):
        chapter_session = next(
            item for item in self.sessions if item["id"] == chapter_session_id
        )
        effective_status = self._effective_status(chapter_session)
        return [
            item | {"effective_status": effective_status}
            for item in self.candidates
            if item["chapter_session_id"] == chapter_session_id
        ]


class FakeTx:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def tx_factory():
    return FakeTx()


@pytest.mark.asyncio
async def test_create_session_requires_active_planning():
    from backend.services.chapter_sessions import (
        ChapterSessionPreconditionFailed,
        ChapterSessionService,
        CreateChapterSession,
    )

    repo = FakeChapterRepository()
    repo.plan = None
    service = ChapterSessionService(repo, transaction_factory=tx_factory)

    with pytest.raises(ChapterSessionPreconditionFailed, match="planning"):
        await service.create_session(CreateChapterSession(
            project_id="p1", expected_story_block_revision=1,
            expected_canon_revision=0,
        ))


@pytest.mark.asyncio
async def test_create_session_creates_empty_working_draft_without_candidate():
    from backend.services.chapter_sessions import ChapterSessionService, CreateChapterSession

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)

    result = await service.create_session(CreateChapterSession(
        project_id="p1", expected_story_block_revision=1,
        expected_canon_revision=0,
    ))

    assert result.session.chapter_num == 1
    assert result.session.status == "drafting"
    assert result.working_draft.revision == 1
    assert result.working_draft.content == ""
    assert result.candidates == ()
    assert repo.session["expected_story_block_revision"] == 1
    assert repo.session["selection_revision"] == 3
    assert repo.session["contract_revision"] == 1
    assert repo.session["contract_hash"] == "c" * 64
    assert repo.session["bible_revision"] == 2
    assert repo.session["bible_hash"] == "b" * 64
    assert repo.session["volume_plan_id"] == "volume-1"
    assert repo.session["planning_manifest_hash"] == "a" * 64
    assert repo.working_draft["source_payload"]["source"] == "manual-empty"


@pytest.mark.asyncio
async def test_save_working_draft_updates_revision_and_does_not_create_candidate():
    from backend.services.chapter_sessions import (
        ChapterSessionService,
        CreateChapterSession,
        SaveWorkingDraft,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    created = await service.create_session(CreateChapterSession(
        project_id="p1", expected_story_block_revision=1,
        expected_canon_revision=0,
    ))

    updated = await service.save_working_draft(SaveWorkingDraft(
        project_id="p1",
        chapter_session_id=created.session.id,
        expected_revision=1,
        content="沈清源站在织机前，先听见的是木轴发涩的吱呀声。",
    ))

    assert updated.working_draft.revision == 2
    assert updated.working_draft.content.startswith("沈清源")
    assert updated.candidates == ()
    assert repo.candidates == []


@pytest.mark.asyncio
async def test_generation_drift_returns_superseded_workspace_and_rejects_writes():
    from backend.services.chapter_sessions import (
        ChapterSessionConflict,
        ChapterSessionService,
        CreateChapterSession,
        SaveDraftCandidate,
        SaveWorkingDraft,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(
        repo,
        transaction_factory=tx_factory,
        connection_factory=tx_factory,
    )
    created = await service.create_session(
        CreateChapterSession(
            project_id="p1",
            expected_story_block_revision=1,
            expected_canon_revision=0,
        )
    )
    await service.save_working_draft(
        SaveWorkingDraft(
            project_id="p1",
            chapter_session_id=created.session.id,
            expected_revision=1,
            content="旧代际正文",
        )
    )
    await service.save_candidate(
        SaveDraftCandidate(
            project_id="p1",
            chapter_session_id=created.session.id,
            expected_working_draft_revision=2,
        )
    )
    repo.generation_current = False

    current = await service.get_current("p1")
    assert current.session.status == "superseded"
    assert current.working_draft.status == "superseded"
    assert current.candidates[0].status == "superseded"

    with pytest.raises(ChapterSessionConflict, match="superseded"):
        await service.save_working_draft(
            SaveWorkingDraft(
                project_id="p1",
                chapter_session_id=created.session.id,
                expected_revision=1,
                content="不得复活旧代际",
            )
        )


@pytest.mark.asyncio
async def test_seed_switch_creates_same_number_session_in_new_generation():
    from backend.services.chapter_sessions import (
        ChapterSessionService,
        CreateChapterSession,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    first = await service.create_session(
        CreateChapterSession(
            project_id="p1",
            expected_story_block_revision=1,
            expected_canon_revision=0,
        )
    )
    repo.plan = {
        **repo.plan,
        "selection_revision": 4,
        "manifest_hash": "d" * 64,
        "volume": {"id": "volume-2"},
        "block": {
            **repo.plan["block"],
            "id": "block-2",
        },
    }

    second = await service.create_session(
        CreateChapterSession(
            project_id="p1",
            expected_story_block_revision=1,
            expected_canon_revision=0,
        )
    )

    assert second.session.id != first.session.id
    assert second.session.chapter_num == first.session.chapter_num == 1
    assert second.session.selection_revision == 4
    old = await repo.read_session_by_id(object(), "p1", first.session.id)
    assert old["effective_status"] == "superseded"
    assert (await repo.read_working_draft(object(), first.session.id))[
        "effective_status"
    ] == "superseded"


@pytest.mark.asyncio
async def test_save_candidate_freezes_current_working_draft_explicitly():
    from backend.services.chapter_sessions import (
        ChapterSessionService,
        CreateChapterSession,
        SaveDraftCandidate,
        SaveWorkingDraft,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    created = await service.create_session(CreateChapterSession(
        project_id="p1", expected_story_block_revision=1,
        expected_canon_revision=0,
    ))
    await service.save_working_draft(SaveWorkingDraft(
        project_id="p1",
        chapter_session_id=created.session.id,
        expected_revision=1,
        content="沈清源站在织机前，先听见的是木轴发涩的吱呀声。",
    ))

    result = await service.save_candidate(SaveDraftCandidate(
        project_id="p1",
        chapter_session_id=created.session.id,
        expected_working_draft_revision=2,
    ))

    assert len(result.candidates) == 1
    assert result.candidates[0].working_draft_revision == 2
    assert result.candidates[0].content == result.working_draft.content
    assert result.candidates[0].content_hash == result.working_draft.content_hash


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ("working-draft", "candidate"))
async def test_existing_draft_writes_recheck_active_project(operation):
    from backend.services.chapter_sessions import (
        ChapterSessionService,
        CreateChapterSession,
        SaveDraftCandidate,
        SaveWorkingDraft,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    created = await service.create_session(CreateChapterSession(
        project_id="p1", expected_story_block_revision=1,
        expected_canon_revision=0,
    ))
    await service.save_working_draft(SaveWorkingDraft(
        project_id="p1",
        chapter_session_id=created.session.id,
        expected_revision=1,
        content="归档前正文",
    ))
    repo.archived = True

    if operation == "working-draft":
        awaitable = service.save_working_draft(SaveWorkingDraft(
            project_id="p1",
            chapter_session_id=created.session.id,
            expected_revision=2,
            content="不能保存",
        ))
    else:
        awaitable = service.save_candidate(SaveDraftCandidate(
            project_id="p1",
            chapter_session_id=created.session.id,
            expected_working_draft_revision=2,
        ))

    with pytest.raises(http_errors.ProjectArchived):
        await awaitable

    assert repo.working_draft["content"] == "归档前正文"
    assert repo.candidates == []
