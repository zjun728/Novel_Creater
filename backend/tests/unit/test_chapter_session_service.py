from __future__ import annotations

import pytest

from backend import http_errors


PLANNING_ID = "planning-revision-1"
PLANNING_HASH = "a" * 64
BLOCK_ID = "story-block-1"
BLOCK_HASH = "b" * 64
OUTLINE_ID = "outline-revision-1"
OUTLINE_HASH = "c" * 64
PROJECTION_HASH = "d" * 64


class FakeChapterRepository:
    def __init__(self):
        self.archived = False
        self.project = {"id": "p1", "current_chapter": 0}
        self.outline = {
            "planning_revision_id": PLANNING_ID,
            "planning_revision": 1,
            "planning_hash": PLANNING_HASH,
            "current_planning_revision_id": PLANNING_ID,
            "current_planning_revision": 1,
            "current_planning_hash": PLANNING_HASH,
            "planning_selection_revision": 1,
            "planning_seed_id": "seed-a",
            "planning_seed_revision_id": "seed-revision-a",
            "planning_seed_hash": "1" * 64,
            "planning_contract_revision": 1,
            "planning_creation_contract_id": "creation-a",
            "planning_creation_hash": "2" * 64,
            "planning_style_contract_id": "style-a",
            "planning_style_hash": "3" * 64,
            "planning_bible_revision": 1,
            "planning_bible_revision_id": "bible-a",
            "planning_bible_hash": "4" * 64,
            "current_selection_revision": 1,
            "current_seed_id": "seed-a",
            "current_seed_revision_id": "seed-revision-a",
            "current_seed_hash": "1" * 64,
            "current_contract_revision": 1,
            "current_creation_contract_id": "creation-a",
            "current_creation_hash": "2" * 64,
            "current_style_contract_id": "style-a",
            "current_style_hash": "3" * 64,
            "current_bible_revision": 1,
            "current_bible_revision_id": "bible-a",
            "current_bible_hash": "4" * 64,
            "story_block_id": BLOCK_ID,
            "story_block_revision": 2,
            "story_block_hash": BLOCK_HASH,
            "chapter_outline_revision_id": OUTLINE_ID,
            "chapter_outline_revision": 3,
            "chapter_outline_hash": OUTLINE_HASH,
            "canon_revision": 0,
            "projection_revision": 0,
            "projection_hash": PROJECTION_HASH,
            "chapter_outline": {
                "chapterGoal": "主角第一次靠典籍知识解决眼前麻烦",
                "storyBlockRef": {
                    "id": BLOCK_ID,
                    "revision": 2,
                    "contentHash": BLOCK_HASH,
                },
                "scenes": ["织机故障", "主角判断木轴受潮"],
            },
        }
        self.projection = {
            "canon_revision_number": 0,
            "projection_revision_number": 0,
            "content_hash": PROJECTION_HASH,
        }
        self.sessions = []
        self.working_drafts = {}
        self.candidates = []
        self.chapter_reads = []
        self.max_final_chapter = None
        self.call_order = []
        self.active_error = None

    async def lock_project(self, session, project_id):
        self.call_order.append("lock_project")
        if self.archived:
            raise http_errors.ProjectArchived()
        return self.project if project_id == "p1" else None

    async def read_active_session(self, session, project_id):
        self.call_order.append("read_active_session")
        if self.active_error is not None:
            raise self.active_error
        return next(
            (
                {
                    "id": row["id"],
                    "project_id": row["project_id"],
                    "chapter_num": row["chapter_num"],
                    "status": row["status"],
                }
                for row in reversed(self.sessions)
                if row["project_id"] == project_id
                and row["status"] == "drafting"
            ),
            None,
        )

    async def read_max_final_chapter_number(self, session, project_id):
        self.call_order.append("read_max_final_chapter_number")
        return self.max_final_chapter

    async def read_current_outline(self, session, project_id, chapter_number):
        self.call_order.append("read_current_outline")
        if project_id != "p1" or chapter_number != 1:
            return None
        return self.outline

    async def read_projection_head(self, session, project_id):
        self.call_order.append("read_projection_head")
        return self.projection

    async def read_chapter_session(self, session, project_id, chapter_number):
        self.call_order.append("read_chapter_session")
        self.chapter_reads.append((project_id, chapter_number))
        return next(
            (
                row
                for row in reversed(self.sessions)
                if row["project_id"] == project_id
                and row["chapter_num"] == chapter_number
            ),
            None,
        )

    async def read_session_by_id(self, session, project_id, chapter_session_id):
        return next(
            (
                row
                for row in self.sessions
                if row["project_id"] == project_id
                and row["id"] == chapter_session_id
            ),
            None,
        )

    async def insert_chapter_session(self, session, row):
        self.call_order.append("insert_chapter_session")
        self.sessions.append(row)
        return True

    async def read_working_draft(self, session, chapter_session_id):
        self.call_order.append("read_working_draft")
        return self.working_drafts.get(chapter_session_id)

    async def upsert_working_draft(self, session, row):
        self.call_order.append("upsert_working_draft")
        self.working_drafts[row["chapter_session_id"]] = row
        return True

    async def insert_candidate(self, session, row):
        if any(item["content_hash"] == row["content_hash"] for item in self.candidates):
            return False
        self.candidates.append(row)
        return True

    async def list_candidates(self, session, chapter_session_id):
        return [
            item
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


def create_command(**overrides):
    from backend.services.chapter_sessions import CreateChapterSession

    values = {
        "project_id": "p1",
        "chapter_number": 1,
        "expected_planning_revision": 1,
        "expected_planning_hash": PLANNING_HASH,
        "expected_outline_revision": 3,
        "expected_outline_hash": OUTLINE_HASH,
        "expected_canon_revision": 0,
    }
    values.update(overrides)
    return CreateChapterSession(**values)


@pytest.mark.parametrize(
    ("active_session", "max_final_chapter", "expected"),
    (
        (None, None, 1),
        (None, 7, 8),
        ({"chapter_num": 4}, 99, 4),
    ),
)
def test_authoritative_chapter_uses_active_then_final_then_one(
    active_session,
    max_final_chapter,
    expected,
):
    from backend.repositories.chapter_sessions import (
        authoritative_chapter as repository_authoritative_chapter,
    )
    from backend.services.chapter_outlines import (
        authoritative_chapter as outline_authoritative_chapter,
    )
    from backend.services.chapter_sessions import (
        authoritative_chapter as session_authoritative_chapter,
    )

    assert outline_authoritative_chapter is repository_authoritative_chapter
    assert session_authoritative_chapter is repository_authoritative_chapter
    assert (
        repository_authoritative_chapter(active_session, max_final_chapter)
        == expected
    )


@pytest.mark.asyncio
async def test_get_chapter_session_reads_exact_chapter_and_never_latest():
    from backend.services.chapter_sessions import ChapterSessionService

    repo = FakeChapterRepository()
    service = ChapterSessionService(
        repo,
        transaction_factory=tx_factory,
        connection_factory=tx_factory,
    )
    created = await service.create_session(create_command())
    repo.chapter_reads.clear()

    chapter_one = await service.get("p1", 1)
    chapter_two = await service.get("p1", 2)

    assert chapter_one.session.id == created.session.id
    assert chapter_two is None
    assert repo.chapter_reads == [("p1", 1), ("p1", 2)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("project_id", "chapter_number"),
    (("", 1), ("p1", 0)),
)
async def test_get_chapter_session_validates_project_and_chapter(
    project_id,
    chapter_number,
):
    from backend.services.chapter_sessions import (
        ChapterSessionRequestInvalid,
        ChapterSessionService,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(
        repo,
        transaction_factory=tx_factory,
        connection_factory=tx_factory,
    )

    with pytest.raises(ChapterSessionRequestInvalid):
        await service.get(project_id, chapter_number)

    assert repo.chapter_reads == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("chapter_number", 0),
        ("chapter_number", True),
        ("chapter_number", "1"),
        ("chapter_number", None),
        ("expected_planning_revision", 0),
        ("expected_planning_revision", True),
        ("expected_planning_revision", "1"),
        ("expected_planning_revision", None),
        ("expected_planning_hash", "A" * 64),
        ("expected_planning_hash", "a" * 63),
        ("expected_planning_hash", None),
        ("expected_outline_revision", 0),
        ("expected_outline_revision", False),
        ("expected_outline_revision", "3"),
        ("expected_outline_revision", None),
        ("expected_outline_hash", "not-a-hash"),
        ("expected_outline_hash", None),
        ("expected_canon_revision", -1),
        ("expected_canon_revision", False),
        ("expected_canon_revision", "0"),
        ("expected_canon_revision", None),
    ),
)
async def test_create_session_service_rejects_invalid_six_value_command(
    field,
    value,
):
    from backend.services.chapter_sessions import (
        ChapterSessionRequestInvalid,
        ChapterSessionService,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)

    with pytest.raises(ChapterSessionRequestInvalid):
        await service.create_session(create_command(**{field: value}))

    assert repo.sessions == []
    assert repo.working_drafts == {}


@pytest.mark.asyncio
async def test_create_session_requires_current_confirmed_outline():
    from backend.services.chapter_sessions import (
        ChapterSessionPreconditionFailed,
        ChapterSessionService,
    )

    repo = FakeChapterRepository()
    repo.outline = None
    service = ChapterSessionService(repo, transaction_factory=tx_factory)

    with pytest.raises(ChapterSessionPreconditionFailed, match="outline"):
        await service.create_session(create_command())

    assert repo.sessions == []
    assert repo.working_drafts == {}


@pytest.mark.asyncio
async def test_create_session_rejects_requested_chapter_outside_server_authority():
    from backend.services.chapter_sessions import (
        ChapterSessionConflict,
        ChapterSessionService,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    first = await service.create_session(create_command())
    repo.call_order.clear()

    with pytest.raises(ChapterSessionConflict, match="server authority"):
        await service.create_session(create_command(chapter_number=2))

    assert len(repo.sessions) == 1
    assert repo.sessions[0]["id"] == first.session.id
    assert repo.call_order == ["lock_project", "read_active_session"]


@pytest.mark.asyncio
async def test_active_session_replays_exact_pins_without_revalidating_new_heads():
    from backend.services.chapter_sessions import ChapterSessionService

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    first = await service.create_session(create_command())
    repo.outline = None
    repo.projection = None
    repo.call_order.clear()

    replay = await service.create_session(create_command())

    assert replay.session.id == first.session.id
    assert repo.call_order == [
        "lock_project",
        "read_active_session",
        "read_chapter_session",
        "read_working_draft",
    ]


@pytest.mark.asyncio
async def test_active_session_replay_rejects_browser_pins_that_do_not_match():
    from backend.services.chapter_sessions import (
        ChapterSessionConflict,
        ChapterSessionService,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    await service.create_session(create_command())
    repo.call_order.clear()

    with pytest.raises(ChapterSessionConflict, match="pins"):
        await service.create_session(
            create_command(expected_outline_hash="e" * 64)
        )

    assert len(repo.sessions) == 1
    assert repo.call_order == [
        "lock_project",
        "read_active_session",
        "read_chapter_session",
    ]


@pytest.mark.asyncio
async def test_no_active_session_calculates_from_final_before_outline_read():
    from backend.services.chapter_sessions import (
        ChapterSessionPreconditionFailed,
        ChapterSessionService,
    )

    repo = FakeChapterRepository()
    repo.max_final_chapter = 7
    service = ChapterSessionService(repo, transaction_factory=tx_factory)

    with pytest.raises(ChapterSessionPreconditionFailed, match="outline"):
        await service.create_session(create_command(chapter_number=8))

    assert repo.call_order == [
        "lock_project",
        "read_active_session",
        "read_max_final_chapter_number",
        "read_current_outline",
    ]


@pytest.mark.asyncio
async def test_create_session_checks_archived_project_before_all_authority_reads():
    from backend.services.chapter_sessions import ChapterSessionService

    repo = FakeChapterRepository()
    repo.archived = True
    service = ChapterSessionService(repo, transaction_factory=tx_factory)

    with pytest.raises(http_errors.ProjectArchived):
        await service.create_session(create_command())

    assert repo.call_order == ["lock_project"]
    assert repo.sessions == []
    assert repo.working_drafts == {}


@pytest.mark.asyncio
async def test_split_active_session_authority_maps_to_fixed_session_conflict():
    from backend.repositories.chapter_sessions import (
        ActiveChapterSessionConflict,
    )
    from backend.services.chapter_sessions import (
        ChapterSessionConflict,
        ChapterSessionService,
    )

    repo = FakeChapterRepository()
    repo.active_error = ActiveChapterSessionConflict(
        "raw duplicate rows: secret",
    )
    service = ChapterSessionService(repo, transaction_factory=tx_factory)

    with pytest.raises(
        ChapterSessionConflict,
        match="authority is inconsistent",
    ) as caught:
        await service.create_session(create_command())

    assert "secret" not in str(caught.value)
    assert repo.call_order == ["lock_project", "read_active_session"]
    assert repo.sessions == []
    assert repo.working_drafts == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("expected_planning_revision", 2, "Planning"),
        ("expected_planning_hash", "e" * 64, "Planning"),
        ("expected_outline_revision", 4, "Outline"),
        ("expected_outline_hash", "f" * 64, "Outline"),
    ),
)
async def test_create_session_rejects_browser_revision_or_hash_drift(
    field, value, message,
):
    from backend.services.chapter_sessions import (
        ChapterSessionConflict,
        ChapterSessionService,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)

    with pytest.raises(ChapterSessionConflict, match=message):
        await service.create_session(create_command(**{field: value}))

    assert repo.sessions == []
    assert repo.working_drafts == {}


@pytest.mark.asyncio
async def test_create_session_rejects_outline_bound_to_noncurrent_planning():
    from backend.services.chapter_sessions import (
        ChapterSessionConflict,
        ChapterSessionService,
    )

    repo = FakeChapterRepository()
    repo.outline["current_planning_revision"] = 2
    repo.outline["current_planning_hash"] = "e" * 64
    service = ChapterSessionService(repo, transaction_factory=tx_factory)

    with pytest.raises(ChapterSessionConflict, match="Planning"):
        await service.create_session(create_command())

    assert repo.sessions == []


@pytest.mark.asyncio
async def test_create_session_rejects_outline_from_previous_generation_even_when_head_matches():
    from backend.services.chapter_sessions import (
        ChapterSessionConflict,
        ChapterSessionService,
    )

    repo = FakeChapterRepository()
    repo.outline.update(
        current_selection_revision=2,
        current_seed_id="seed-b",
        current_seed_revision_id="seed-revision-b",
        current_seed_hash="5" * 64,
        current_contract_revision=2,
        current_creation_contract_id="creation-b",
        current_creation_hash="6" * 64,
        current_style_contract_id="style-b",
        current_style_hash="7" * 64,
        current_bible_revision=2,
        current_bible_revision_id="bible-b",
        current_bible_hash="8" * 64,
    )
    service = ChapterSessionService(repo, transaction_factory=tx_factory)

    with pytest.raises(ChapterSessionConflict, match="generation"):
        await service.create_session(create_command())

    assert repo.sessions == []
    assert repo.working_drafts == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("canon_revision", "projection_revision"),
    ((1, 0), (0, 1)),
)
async def test_create_session_requires_synchronized_canon_and_projection(
    canon_revision, projection_revision,
):
    from backend.services.chapter_sessions import (
        ChapterSessionPreconditionFailed,
        ChapterSessionService,
    )

    repo = FakeChapterRepository()
    repo.projection["canon_revision_number"] = canon_revision
    repo.projection["projection_revision_number"] = projection_revision
    service = ChapterSessionService(repo, transaction_factory=tx_factory)

    with pytest.raises(
        ChapterSessionPreconditionFailed,
        match="Canon.*Projection",
    ):
        await service.create_session(create_command())

    assert repo.sessions == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "value"),
    (
        ("canon_revision_number", 1),
        ("projection_revision_number", 1),
        ("content_hash", "e" * 64),
    ),
)
async def test_create_session_rejects_current_heads_that_differ_from_outline_baseline(
    key, value,
):
    from backend.services.chapter_sessions import (
        ChapterSessionConflict,
        ChapterSessionService,
    )

    repo = FakeChapterRepository()
    if key in {"canon_revision_number", "projection_revision_number"}:
        repo.projection["canon_revision_number"] = value
        repo.projection["projection_revision_number"] = value
    else:
        repo.projection[key] = value
    service = ChapterSessionService(repo, transaction_factory=tx_factory)

    with pytest.raises(ChapterSessionConflict, match="baseline"):
        await service.create_session(
            create_command(
                expected_canon_revision=repo.projection[
                    "canon_revision_number"
                ],
            )
        )

    assert repo.sessions == []


@pytest.mark.asyncio
async def test_create_session_pins_server_joined_planning_block_outline_and_canon():
    from backend.services.chapter_sessions import ChapterSessionService

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)

    result = await service.create_session(create_command())

    assert result.session.chapter_num == 1
    assert result.session.status == "drafting"
    assert result.working_draft.revision == 1
    assert result.working_draft.content == ""
    assert result.candidates == ()
    assert repo.sessions[0] == {
        "id": result.session.id,
        "project_id": "p1",
        "planning_revision_id": PLANNING_ID,
        "planning_revision": 1,
        "planning_hash": PLANNING_HASH,
        "story_block_id": BLOCK_ID,
        "story_block_revision": 2,
        "story_block_hash": BLOCK_HASH,
        "chapter_outline_revision_id": OUTLINE_ID,
        "chapter_outline_revision": 3,
        "chapter_outline_hash": OUTLINE_HASH,
        "chapter_num": 1,
        "expected_canon_revision": 0,
        "chapter_outline": repo.outline["chapter_outline"],
        "status": "drafting",
        "created_at": repo.sessions[0]["created_at"],
        "finalized_at": None,
    }
    assert result.session.planning_revision_id == PLANNING_ID
    assert result.session.planning_revision == 1
    assert result.session.planning_hash == PLANNING_HASH
    assert result.session.story_block_id == BLOCK_ID
    assert result.session.story_block_revision == 2
    assert result.session.story_block_hash == BLOCK_HASH
    assert result.session.chapter_outline_revision_id == OUTLINE_ID
    assert result.session.chapter_outline_revision == 3
    assert result.session.chapter_outline_hash == OUTLINE_HASH
    assert result.session.expected_canon_revision == 0
    assert repo.working_drafts[result.session.id]["source_payload"] == {
        "source": "manual-empty",
    }


@pytest.mark.asyncio
async def test_save_working_draft_updates_revision_and_does_not_create_candidate():
    from backend.services.chapter_sessions import (
        ChapterSessionService,
        SaveWorkingDraft,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    created = await service.create_session(create_command())

    updated = await service.save_working_draft(
        SaveWorkingDraft(
            project_id="p1",
            chapter_session_id=created.session.id,
            expected_revision=1,
            content="沈清源站在织机前，先听见的是木轴发涩的吱呀声。",
        )
    )

    assert updated.working_draft.revision == 2
    assert updated.working_draft.content.startswith("沈清源")
    assert updated.candidates == ()
    assert repo.candidates == []


@pytest.mark.asyncio
async def test_save_candidate_freezes_current_working_draft_explicitly():
    from backend.services.chapter_sessions import (
        ChapterSessionService,
        SaveDraftCandidate,
        SaveWorkingDraft,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    created = await service.create_session(create_command())
    await service.save_working_draft(
        SaveWorkingDraft(
            project_id="p1",
            chapter_session_id=created.session.id,
            expected_revision=1,
            content="沈清源站在织机前，先听见的是木轴发涩的吱呀声。",
        )
    )

    result = await service.save_candidate(
        SaveDraftCandidate(
            project_id="p1",
            chapter_session_id=created.session.id,
            expected_working_draft_revision=2,
        )
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].working_draft_revision == 2
    assert result.candidates[0].content == result.working_draft.content
    assert result.candidates[0].content_hash == result.working_draft.content_hash


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ("working-draft", "candidate"))
async def test_existing_draft_writes_recheck_active_project(operation):
    from backend.services.chapter_sessions import (
        ChapterSessionService,
        SaveDraftCandidate,
        SaveWorkingDraft,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    created = await service.create_session(create_command())
    await service.save_working_draft(
        SaveWorkingDraft(
            project_id="p1",
            chapter_session_id=created.session.id,
            expected_revision=1,
            content="归档前正文",
        )
    )
    repo.archived = True

    if operation == "working-draft":
        awaitable = service.save_working_draft(
            SaveWorkingDraft(
                project_id="p1",
                chapter_session_id=created.session.id,
                expected_revision=2,
                content="不能保存",
            )
        )
    else:
        awaitable = service.save_candidate(
            SaveDraftCandidate(
                project_id="p1",
                chapter_session_id=created.session.id,
                expected_working_draft_revision=2,
            )
        )

    with pytest.raises(http_errors.ProjectArchived):
        await awaitable

    assert repo.working_drafts[created.session.id]["content"] == "归档前正文"
    assert repo.candidates == []
