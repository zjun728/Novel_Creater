from __future__ import annotations

from copy import deepcopy
import hashlib

import pytest

from backend import http_errors
from backend.domain.json_contracts import canonical_hash


PLANNING_ID = "planning-revision-1"
PLANNING_HASH = "a" * 64
BLOCK_ID = "story-block-1"
BLOCK_HASH = "b" * 64
OUTLINE_ID = "outline-revision-1"
OUTLINE_HASH = "c" * 64
PROJECTION_HASH = "d" * 64
FREEZE_KEY_1 = "11111111-1111-1111-1111-111111111111"
FREEZE_KEY_2 = "22222222-2222-2222-2222-222222222222"
FREEZE_KEY_3 = "33333333-3333-3333-3333-333333333333"
FREEZE_KEY_4 = "44444444-4444-4444-4444-444444444444"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def candidate_command(repo, chapter_session_id, *, idempotency_key=FREEZE_KEY_1):
    from backend.services.chapter_sessions import SaveDraftCandidate

    draft = repo.working_drafts[chapter_session_id]
    return SaveDraftCandidate(
        project_id="p1",
        chapter_session_id=chapter_session_id,
        expected_working_draft_revision=draft["revision"],
        expected_content_hash=draft["content_hash"],
        idempotency_key=idempotency_key,
    )


def load_candidate_command(repo, chapter_session_id, candidate_id):
    from backend.services.chapter_sessions import LoadDraftCandidate

    draft = repo.working_drafts[chapter_session_id]
    return LoadDraftCandidate(
        project_id="p1",
        chapter_session_id=chapter_session_id,
        candidate_id=candidate_id,
        expected_working_draft_revision=draft["revision"],
        expected_content_hash=draft["content_hash"],
    )


class FakeChapterRepository:
    _BASIS_KEYS = (
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
        self.reject_candidate_insert = False
        self.reject_freeze_request_insert = False
        self.working_draft_cas_calls = []
        self.freeze_requests = []
        self.recovery_rows = []
        self.reject_recovery_insert = False
        self.reject_working_draft_upsert = False

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

    async def lock_session_for_operation(
        self, session, project_id, chapter_session_id
    ):
        self.call_order.append("lock_session_for_operation")
        return await self.read_session_by_id(
            session, project_id, chapter_session_id
        )

    async def insert_chapter_session(self, session, row):
        self.call_order.append("insert_chapter_session")
        self.sessions.append(row)
        return True

    async def read_working_draft(self, session, chapter_session_id):
        self.call_order.append("read_working_draft")
        return self.working_drafts.get(chapter_session_id)

    async def lock_working_draft_for_operation(
        self, session, project_id, chapter_session_id
    ):
        self.call_order.append("lock_working_draft_for_operation")
        draft = self.working_drafts.get(chapter_session_id)
        if draft is None or draft["project_id"] != project_id:
            return None
        return draft

    async def upsert_working_draft(
        self,
        session,
        row,
        *,
        expected_revision=None,
        expected_content_hash=None,
    ):
        self.call_order.append("upsert_working_draft")
        if self.reject_working_draft_upsert:
            return False
        if expected_revision is not None or expected_content_hash is not None:
            self.working_draft_cas_calls.append(
                (expected_revision, expected_content_hash)
            )
            current = self.working_drafts.get(row["chapter_session_id"])
            if (
                expected_revision is None
                or expected_content_hash is None
                or current is None
                or current["revision"] != expected_revision
                or current["content_hash"] != expected_content_hash
            ):
                return False
        self.working_drafts[row["chapter_session_id"]] = row
        return True

    async def insert_working_draft_revision(self, session, row):
        self.call_order.append("insert_working_draft_revision")
        if self.reject_recovery_insert:
            return False
        self.recovery_rows.append(row)
        return True

    async def insert_candidate(self, session, row):
        if self.reject_candidate_insert:
            return False
        basis = self._basis_payload(row)
        if basis is None:
            return False
        for item in self.candidates:
            if (
                item["chapter_session_id"] == row["chapter_session_id"]
                and item["content_hash"] == row["content_hash"]
                and item["basis_hash"] == row["basis_hash"]
            ):
                return self._basis_payload(item) == basis
        self.candidates.append(row)
        return True

    async def read_candidate_by_identity(
        self, session, chapter_session_id, content_hash, basis_hash
    ):
        return next(
            (
                item for item in self.candidates
                if item["chapter_session_id"] == chapter_session_id
                and item["content_hash"] == content_hash
                and item["basis_hash"] == basis_hash
            ),
            None,
        )

    async def read_candidate_freeze_request(
        self, session, chapter_session_id, idempotency_key
    ):
        return next(
            (
                item for item in self.freeze_requests
                if item["chapter_session_id"] == chapter_session_id
                and item["idempotency_key"] == idempotency_key
            ),
            None,
        )

    async def insert_candidate_freeze_request(self, session, row):
        if self.reject_freeze_request_insert:
            return False
        self.freeze_requests.append(row)
        return True

    def _basis_payload(self, row):
        provenance = row.get("provenance")
        if not isinstance(provenance, dict):
            return None
        try:
            payload = {key: provenance[key] for key in self._BASIS_KEYS}
        except KeyError:
            return None
        return payload if canonical_hash(payload) == row.get("basis_hash") else None

    async def list_candidates(self, session, chapter_session_id):
        return [
            item
            for item in self.candidates
            if item["chapter_session_id"] == chapter_session_id
        ]

    async def read_candidate_for_load(
        self, session, project_id, chapter_session_id, candidate_id
    ):
        self.call_order.append("read_candidate_for_load")
        return next(
            (
                item
                for item in self.candidates
                if item["project_id"] == project_id
                and item["chapter_session_id"] == chapter_session_id
                and item["id"] == candidate_id
            ),
            None,
        )


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


def test_candidate_view_does_not_expose_raw_provenance():
    from backend.domain.drafts import DraftCandidateView

    assert "provenance" not in DraftCandidateView.__dataclass_fields__
    assert "basis_hash" not in DraftCandidateView.__dataclass_fields__


@pytest.mark.asyncio
async def test_fake_candidate_identity_matches_repository_contract():
    repo = FakeChapterRepository()
    basis = {
        "schemaVersion": "draft-candidate-basis-v1",
        "outlineRevisionId": "outline-revision-1",
        "outlineRevision": 1,
        "outlineHash": "a" * 64,
        "planningRevisionId": "planning-revision-1",
        "planningRevision": 1,
        "planningHash": "b" * 64,
        "canonRevision": 0,
        "projectionRevision": 0,
        "projectionHash": "c" * 64,
    }
    row = {
        "id": "candidate-1",
        "chapter_session_id": "session-1",
        "content_hash": "d" * 64,
        "basis_hash": canonical_hash(basis),
        "provenance": {"source": "save", "workingDraftRevision": 2, **basis},
    }

    assert await repo.insert_candidate(None, row)
    assert await repo.insert_candidate(None, {**row, "id": "candidate-2"})
    assert len(repo.candidates) == 1
    assert await repo.insert_candidate(
        None,
        {**row, "id": "candidate-3", "chapter_session_id": "session-2"},
    )
    assert len(repo.candidates) == 2
    mismatched = {
        **row,
        "id": "candidate-4",
        "provenance": {**row["provenance"], "outlineRevision": 2},
    }
    assert not await repo.insert_candidate(None, mismatched)


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
    repo.sessions[0]["active_draft_operation_id"] = (
        "30000000-0000-0000-0000-000000000001"
    )
    repo.chapter_reads.clear()

    chapter_one = await service.get("p1", 1)
    chapter_two = await service.get("p1", 2)

    assert chapter_one.session.id == created.session.id
    assert chapter_one.active_draft_operation_id == (
        "30000000-0000-0000-0000-000000000001"
    )
    assert chapter_two is None
    assert repo.chapter_reads == [("p1", 1), ("p1", 2)]


@pytest.mark.asyncio
async def test_workspace_rejects_malformed_active_draft_operation_authority():
    from backend.services.chapter_sessions import (
        ChapterSessionConflict,
        ChapterSessionService,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(
        repo,
        transaction_factory=tx_factory,
        connection_factory=tx_factory,
    )
    await service.create_session(create_command())
    repo.sessions[0]["active_draft_operation_id"] = "not-a-uuid"

    with pytest.raises(ChapterSessionConflict):
        await service.get("p1", 1)


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
        "read_current_outline",
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
            expected_content_hash=sha256_text(""),
            content="沈清源站在织机前，先听见的是木轴发涩的吱呀声。",
        )
    )

    assert updated.working_draft.revision == 2
    assert updated.working_draft.content.startswith("沈清源")
    assert updated.candidates == ()
    assert repo.candidates == []
    assert repo.working_draft_cas_calls == [(1, sha256_text(""))]


@pytest.mark.asyncio
async def test_save_working_draft_requires_revision_and_hash():
    from backend.services.chapter_sessions import (
        ChapterSessionConflict,
        ChapterSessionService,
        SaveWorkingDraft,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    created = await service.create_session(create_command())
    current = dict(repo.working_drafts[created.session.id])

    with pytest.raises(ChapterSessionConflict, match="revision or hash drift"):
        await service.save_working_draft(SaveWorkingDraft(
            project_id="p1",
            chapter_session_id=created.session.id,
            expected_revision=current["revision"],
            expected_content_hash="0" * 64,
            content="作者刚刚输入的正文",
        ))

    assert repo.working_drafts[created.session.id] == current
    assert repo.candidates == []


@pytest.mark.asyncio
async def test_save_working_draft_is_noop_for_current_content_and_authority():
    from backend.services.chapter_sessions import ChapterSessionService, SaveWorkingDraft

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    created = await service.create_session(create_command())
    current = repo.working_drafts[created.session.id]
    repo.call_order.clear()

    result = await service.save_working_draft(SaveWorkingDraft(
        project_id="p1",
        chapter_session_id=created.session.id,
        expected_revision=current["revision"],
        expected_content_hash=current["content_hash"],
        content=current["content"],
    ))

    assert result.working_draft.revision == current["revision"]
    assert result.working_draft.content_hash == current["content_hash"]
    assert "upsert_working_draft" not in repo.call_order
    assert repo.working_draft_cas_calls == []


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
            expected_content_hash=sha256_text(""),
            content="沈清源站在织机前，先听见的是木轴发涩的吱呀声。",
        )
    )

    result = await service.save_candidate(candidate_command(repo, created.session.id))

    assert len(result.candidates) == 1
    assert result.candidates[0].working_draft_revision == 2
    assert result.candidates[0].content == result.working_draft.content
    assert result.candidates[0].content_hash == result.working_draft.content_hash


@pytest.mark.asyncio
async def test_save_candidate_replays_same_key_and_rejects_a_changed_fingerprint():
    from backend.services.chapter_sessions import (
        ChapterSessionConflict,
        ChapterSessionService,
        SaveDraftCandidate,
        SaveWorkingDraft,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    created = await service.create_session(create_command())
    await service.save_working_draft(SaveWorkingDraft(
        "p1", created.session.id, 1, sha256_text(""), "屏幕正文"
    ))
    command = candidate_command(repo, created.session.id, idempotency_key=FREEZE_KEY_1)

    first = await service.save_candidate(command)
    replay = await service.save_candidate(command)

    assert first.candidates[-1].id == replay.candidates[-1].id
    assert len(repo.candidates) == len(repo.freeze_requests) == 1
    with pytest.raises(ChapterSessionConflict, match="idempotency"):
        await service.save_candidate(SaveDraftCandidate(
            project_id="p1",
            chapter_session_id=created.session.id,
            expected_working_draft_revision=command.expected_working_draft_revision,
            expected_content_hash="0" * 64,
            idempotency_key=FREEZE_KEY_1,
        ))
    with pytest.raises(ChapterSessionConflict, match="revision or hash drift"):
        await service.save_candidate(SaveDraftCandidate(
            project_id="p1",
            chapter_session_id=created.session.id,
            expected_working_draft_revision=command.expected_working_draft_revision,
            expected_content_hash="0" * 64,
            idempotency_key=FREEZE_KEY_2,
        ))


@pytest.mark.asyncio
async def test_save_candidate_replay_returns_original_id_after_a_later_candidate():
    from backend.services.chapter_sessions import (
        ChapterSessionService,
        SaveWorkingDraft,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    created = await service.create_session(create_command())
    first_draft = await service.save_working_draft(SaveWorkingDraft(
        "p1", created.session.id, 1, sha256_text(""), "候选稿 A"
    ))
    first_command = candidate_command(
        repo, created.session.id, idempotency_key=FREEZE_KEY_1,
    )
    first = await service.save_candidate(first_command)
    later_draft = await service.save_working_draft(SaveWorkingDraft(
        "p1", created.session.id, first_draft.working_draft.revision,
        first_draft.working_draft.content_hash, "候选稿 B",
    ))
    await service.save_candidate(candidate_command(
        repo, created.session.id, idempotency_key=FREEZE_KEY_2,
    ))

    replay = await service.save_candidate(first_command)

    assert later_draft.working_draft.content == "候选稿 B"
    assert replay.saved_candidate_id == first.saved_candidate_id
    assert len(repo.candidates) == len(repo.freeze_requests) == 2


@pytest.mark.asyncio
async def test_save_candidate_replay_survives_a_finalized_session():
    from backend.services.chapter_sessions import (
        ChapterSessionConflict,
        ChapterSessionService,
        SaveDraftCandidate,
        SaveWorkingDraft,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    created = await service.create_session(create_command())
    await service.save_working_draft(SaveWorkingDraft(
        "p1", created.session.id, 1, sha256_text(""), "可重放候选稿"
    ))
    command = candidate_command(repo, created.session.id, idempotency_key=FREEZE_KEY_1)
    first = await service.save_candidate(command)
    repo.sessions[0]["status"] = "final"

    replay = await service.save_candidate(command)

    assert replay.saved_candidate_id == first.saved_candidate_id
    assert len(repo.candidates) == len(repo.freeze_requests) == 1
    with pytest.raises(ChapterSessionConflict, match="idempotency"):
        await service.save_candidate(SaveDraftCandidate(
            project_id="p1",
            chapter_session_id=created.session.id,
            expected_working_draft_revision=command.expected_working_draft_revision,
            expected_content_hash="0" * 64,
            idempotency_key=command.idempotency_key,
        ))


@pytest.mark.asyncio
@pytest.mark.parametrize("idempotency_key", (
    "freeze-1",
    "11111111-1111-1111-1111-11111111111A",
    "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA",
))
async def test_save_candidate_requires_canonical_lowercase_uuid_idempotency_key(
    idempotency_key,
):
    from backend.services.chapter_sessions import (
        ChapterSessionRequestInvalid,
        ChapterSessionService,
        SaveWorkingDraft,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    created = await service.create_session(create_command())
    await service.save_working_draft(SaveWorkingDraft(
        "p1", created.session.id, 1, sha256_text(""), "正文"
    ))

    with pytest.raises(ChapterSessionRequestInvalid):
        await service.save_candidate(candidate_command(
            repo, created.session.id, idempotency_key=idempotency_key,
        ))


@pytest.mark.asyncio
async def test_save_candidate_reuses_identity_for_a_different_key():
    from backend.services.chapter_sessions import (
        ChapterSessionService,
        SaveWorkingDraft,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    created = await service.create_session(create_command())
    await service.save_working_draft(SaveWorkingDraft(
        "p1", created.session.id, 1, sha256_text(""), "同一可见正文"
    ))

    first = await service.save_candidate(
        candidate_command(repo, created.session.id, idempotency_key=FREEZE_KEY_1)
    )
    second = await service.save_candidate(
        candidate_command(repo, created.session.id, idempotency_key=FREEZE_KEY_2)
    )

    assert first.candidates[-1].id == second.candidates[-1].id
    assert len(repo.candidates) == 1
    assert len(repo.freeze_requests) == 2


@pytest.mark.asyncio
async def test_save_candidate_exact_identity_replay_is_idempotent():
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
            "p1", created.session.id, 1, sha256_text(""), "同一候选正文"
        )
    )
    command = candidate_command(repo, created.session.id)

    first = await service.save_candidate(command)
    replay = await service.save_candidate(command)

    assert len(first.candidates) == len(replay.candidates) == 1
    assert len(repo.candidates) == 1


@pytest.mark.asyncio
async def test_save_candidate_reports_explicit_repository_identity_conflict():
    from backend.services.chapter_sessions import (
        ChapterSessionConflict,
        ChapterSessionService,
        SaveDraftCandidate,
        SaveWorkingDraft,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    created = await service.create_session(create_command())
    await service.save_working_draft(
        SaveWorkingDraft(
            "p1", created.session.id, 1, sha256_text(""), "冲突候选正文"
        )
    )
    repo.reject_candidate_insert = True

    with pytest.raises(ChapterSessionConflict, match="candidate identity conflict"):
        await service.save_candidate(candidate_command(repo, created.session.id))


@pytest.mark.asyncio
async def test_candidates_stamp_current_outline_basis_and_derive_staleness():
    from backend.services.chapter_sessions import (
        ChapterSessionService,
        SaveDraftCandidate,
        SaveWorkingDraft,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(
        repo,
        transaction_factory=tx_factory,
        connection_factory=tx_factory,
    )
    created = await service.create_session(create_command())
    await service.save_working_draft(
        SaveWorkingDraft(
            project_id="p1",
            chapter_session_id=created.session.id,
            expected_revision=1,
            expected_content_hash=sha256_text(""),
            content="候选稿 A",
        )
    )
    await service.save_candidate(
        candidate_command(repo, created.session.id, idempotency_key=FREEZE_KEY_3)
    )

    repo.outline.update(
        chapter_outline_revision_id="outline-revision-2",
        chapter_outline_revision=4,
        chapter_outline_hash="e" * 64,
        planning_revision_id="planning-revision-2",
        planning_revision=2,
        planning_hash="f" * 64,
        canon_revision=4,
        projection_revision=4,
        projection_hash="9" * 64,
    )
    await service.save_working_draft(
        SaveWorkingDraft(
            project_id="p1",
            chapter_session_id=created.session.id,
            expected_revision=2,
            expected_content_hash=sha256_text("候选稿 A"),
            content="候选稿 B",
        )
    )
    await service.save_candidate(
        candidate_command(repo, created.session.id, idempotency_key=FREEZE_KEY_4)
    )
    repo.candidates.append({
        "id": "legacy-candidate",
        "project_id": "p1",
        "chapter_session_id": created.session.id,
        "working_draft_revision": 1,
        "content": "旧候选稿",
        "content_hash": "h" * 64,
        "provenance": {"source": "legacy"},
    })

    workspace = await service.get("p1", 1)

    first, second, legacy = workspace.candidates
    assert first.basis_status == "stale"
    assert first.outline_revision == 3
    assert second.basis_status == "current"
    assert second.outline_revision == 4
    assert second.canon_revision == 4
    assert legacy.basis_status == "stale"
    assert workspace.session.chapter_outline_revision == 3


@pytest.mark.asyncio
async def test_save_candidate_requires_drafting_session_and_current_outline():
    from backend.services.chapter_sessions import (
        ChapterSessionConflict,
        ChapterSessionPreconditionFailed,
        ChapterSessionService,
        SaveDraftCandidate,
        SaveWorkingDraft,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    created = await service.create_session(create_command())
    await service.save_working_draft(
        SaveWorkingDraft(
            "p1", created.session.id, 1, sha256_text(""), "可以冻结的正文"
        )
    )
    repo.sessions[0]["status"] = "final"

    with pytest.raises(ChapterSessionConflict, match="finalized"):
        await service.save_candidate(candidate_command(repo, created.session.id))

    repo.sessions[0]["status"] = "drafting"
    repo.outline = None
    with pytest.raises(
        ChapterSessionPreconditionFailed,
        match="current Outline authority",
    ):
        await service.save_candidate(candidate_command(repo, created.session.id))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("outlineRevision", True),
        ("outlineRevision", 3.0),
        ("outlineHash", "A" * 64),
        ("schemaVersion", "draft-candidate-basis-v0"),
        ("basis_hash", "0" * 64),
    ),
)
async def test_malformed_candidate_basis_fails_closed_without_public_metadata(
    field,
    value,
):
    from backend.services.chapter_sessions import (
        ChapterSessionService,
        SaveDraftCandidate,
        SaveWorkingDraft,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(
        repo,
        transaction_factory=tx_factory,
        connection_factory=tx_factory,
    )
    created = await service.create_session(create_command())
    await service.save_working_draft(
        SaveWorkingDraft(
            "p1", created.session.id, 1, sha256_text(""), "损坏基础候选稿"
        )
    )
    await service.save_candidate(candidate_command(repo, created.session.id))
    if field == "basis_hash":
        repo.candidates[0][field] = value
    else:
        repo.candidates[0]["provenance"][field] = value

    candidate = (await service.get("p1", 1)).candidates[0]

    assert candidate.basis_status == "stale"
    assert (
        candidate.outline_revision_id,
        candidate.outline_revision,
        candidate.outline_hash,
        candidate.planning_revision_id,
        candidate.planning_revision,
        candidate.planning_hash,
        candidate.canon_revision,
        candidate.projection_revision,
        candidate.projection_hash,
    ) == (None,) * 9


@pytest.mark.asyncio
async def test_load_candidate_atomically_replaces_working_draft_with_recovery():
    from backend.services.chapter_sessions import (
        ChapterSessionService,
        SaveWorkingDraft,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    created = await service.create_session(create_command())
    first = await service.save_working_draft(SaveWorkingDraft(
        "p1", created.session.id, 1, sha256_text(""), "候选稿甲",
    ))
    saved = await service.save_candidate(
        candidate_command(repo, created.session.id)
    )
    candidate_id = saved.saved_candidate_id
    await service.save_working_draft(SaveWorkingDraft(
        "p1", created.session.id, first.working_draft.revision,
        first.working_draft.content_hash, "当前工作稿乙",
    ))
    frozen_candidates = deepcopy(repo.candidates)
    repo.call_order.clear()

    result = await service.load_candidate(
        load_candidate_command(repo, created.session.id, candidate_id)
    )

    assert result.working_draft.revision == 4
    assert result.working_draft.content == "候选稿甲"
    assert result.working_draft.content_hash == sha256_text("候选稿甲")
    assert result.working_draft.source_payload == {
        "source": "candidate-load",
        "candidateId": candidate_id,
        "candidateContentHash": sha256_text("候选稿甲"),
        "baseWorkingDraftRevision": 3,
    }
    assert len(result.candidates) == len(repo.candidates) == 1
    assert repo.candidates == frozen_candidates
    assert result.candidates[0].created_at == repo.candidates[0]["created_at"]
    assert [row["snapshot_role"] for row in repo.recovery_rows] == [
        "before", "after",
    ]
    assert all(row["replacement_reason"] == "candidate_load"
               for row in repo.recovery_rows)
    assert all(row["source_operation_id"] is None
               for row in repo.recovery_rows)
    assert all(row["source_candidate_id"] == candidate_id
               for row in repo.recovery_rows)
    assert repo.call_order[:5] == [
        "lock_project",
        "lock_session_for_operation",
        "lock_working_draft_for_operation",
        "read_candidate_for_load",
        "insert_working_draft_revision",
    ]
    assert repo.call_order.count("insert_working_draft_revision") == 2


@pytest.mark.asyncio
async def test_load_candidate_allows_stale_basis_and_keeps_it_visible():
    from backend.services.chapter_sessions import ChapterSessionService, SaveWorkingDraft

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    created = await service.create_session(create_command())
    await service.save_working_draft(SaveWorkingDraft(
        "p1", created.session.id, 1, sha256_text(""), "旧基线候选",
    ))
    saved = await service.save_candidate(candidate_command(repo, created.session.id))
    repo.outline["chapter_outline_hash"] = "e" * 64

    result = await service.load_candidate(
        load_candidate_command(repo, created.session.id, saved.saved_candidate_id)
    )

    assert result.working_draft.content == "旧基线候选"
    assert result.candidates[0].basis_status == "stale"


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_state", ("active", "finalized", "superseded"))
async def test_load_candidate_rejects_nonexclusive_or_closed_session(blocked_state):
    from backend.services.chapter_sessions import ChapterSessionConflict, ChapterSessionService

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    created = await service.create_session(create_command())
    repo.working_drafts[created.session.id].update(
        content="候选", content_hash=sha256_text("候选")
    )
    saved = await service.save_candidate(candidate_command(repo, created.session.id))
    session = repo.sessions[0]
    if blocked_state == "active":
        session["active_draft_operation_id"] = FREEZE_KEY_4
    else:
        session["effective_status"] = blocked_state

    with pytest.raises(ChapterSessionConflict):
        await service.load_candidate(
            load_candidate_command(repo, created.session.id, saved.saved_candidate_id)
        )

    assert repo.recovery_rows == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    ("missing", "cross_owner", "corrupt", "utf8", "cas", "recovery", "upsert"),
)
async def test_load_candidate_fails_closed_before_publishing_invalid_state(failure):
    from backend.services.chapter_sessions import (
        ChapterSessionConflict,
        ChapterSessionNotFound,
        ChapterSessionService,
    )

    repo = FakeChapterRepository()
    service = ChapterSessionService(repo, transaction_factory=tx_factory)
    created = await service.create_session(create_command())
    repo.working_drafts[created.session.id].update(
        content="候选", content_hash=sha256_text("候选")
    )
    saved = await service.save_candidate(candidate_command(repo, created.session.id))
    command = load_candidate_command(repo, created.session.id, saved.saved_candidate_id)
    if failure == "missing":
        command = type(command)(**{**command.__dict__, "candidate_id": "missing"})
    elif failure == "cross_owner":
        repo.candidates[0]["project_id"] = "p2"
    elif failure == "corrupt":
        repo.candidates[0]["content_hash"] = "f" * 64
    elif failure == "utf8":
        repo.candidates[0]["content"] = "\ud800"
    elif failure == "cas":
        command = type(command)(**{
            **command.__dict__, "expected_content_hash": "f" * 64,
        })
    elif failure == "recovery":
        repo.reject_recovery_insert = True
    else:
        repo.reject_working_draft_upsert = True

    expected_error = (
        ChapterSessionNotFound
        if failure in {"missing", "cross_owner"}
        else ChapterSessionConflict
    )
    with pytest.raises(expected_error):
        await service.load_candidate(command)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("project_id", ""),
        ("chapter_session_id", ""),
        ("candidate_id", ""),
        ("expected_working_draft_revision", True),
        ("expected_working_draft_revision", 0),
        ("expected_content_hash", "A" * 64),
    ),
)
async def test_load_candidate_validates_closed_command(field, value):
    from backend.services.chapter_sessions import (
        ChapterSessionRequestInvalid,
        ChapterSessionService,
        LoadDraftCandidate,
    )

    service = ChapterSessionService(
        FakeChapterRepository(), transaction_factory=tx_factory
    )
    values = {
        "project_id": "p1",
        "chapter_session_id": "session-1",
        "candidate_id": "candidate-1",
        "expected_working_draft_revision": 1,
        "expected_content_hash": "a" * 64,
    }
    values[field] = value

    with pytest.raises(ChapterSessionRequestInvalid):
        await service.load_candidate(LoadDraftCandidate(**values))

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
            expected_content_hash=sha256_text(""),
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
                expected_content_hash=sha256_text("归档前正文"),
                content="不能保存",
            )
        )
    else:
        awaitable = service.save_candidate(candidate_command(repo, created.session.id))

    with pytest.raises(http_errors.ProjectArchived):
        await awaitable

    assert repo.working_drafts[created.session.id]["content"] == "归档前正文"
    assert repo.candidates == []
