from __future__ import annotations

import asyncio
import json
import re

import pytest

from backend import http_errors
from backend.repositories.chapter_outlines import ChapterOutlineRepository
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.services.chapter_outlines import (
    ChapterOutlineService,
    ConfirmChapterOutlineDraft,
    CreateChapterOutlineDraft,
    SaveChapterOutlineDraft,
)
from backend.services.chapter_sessions import (
    ChapterSessionConflict,
    ChapterSessionPreconditionFailed,
    ChapterSessionService,
    CreateChapterSession,
    SaveDraftCandidate,
    SaveWorkingDraft,
)
from backend.services.planning import ConfirmPlanningDraft
from backend.tests.integration.test_chapter_outline_lifecycle import (
    _editable_outline,
)
from backend.tests.integration.test_planning_aggregate_lifecycle import (
    NOW,
    PROJECT,
    _prepare,
    _save_complete,
)
from backend.tests.support.disposable_mysql import transaction_factory_for


pytestmark = pytest.mark.mysql
_DATABASE_NAME = re.compile(r"novel_creator_test_[0-9a-f]{32}")
_TIMEOUT = 5


async def _prove_owned_database(disposable_mysql):
    selected = await disposable_mysql.session.fetchone(
        "SELECT DATABASE() AS database_name"
    )
    assert selected == {"database_name": disposable_mysql.database_name}
    assert _DATABASE_NAME.fullmatch(disposable_mysql.database_name)


async def _confirmed_planning(disposable_mysql):
    planning_service = await _prepare(disposable_mysql)
    saved = await _save_complete(planning_service)
    confirmed = await planning_service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            saved.draft_id,
            saved.draft_revision,
            saved.content_hash,
            "confirm-for-authoritative-session",
        )
    )
    return planning_service, confirmed


async def _confirmed_outline(disposable_mysql):
    planning_service, planning = await _confirmed_planning(disposable_mysql)
    ids = iter(
        f"9e000000-0000-0000-0000-{number:012d}"
        for number in range(1, 20)
    )
    service = ChapterOutlineService(
        ChapterOutlineRepository(),
        ChapterSessionRepository(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
        id_factory=ids.__next__,
        clock=lambda: NOW + 900,
    )
    draft = await service.create_draft(
        CreateChapterOutlineDraft(PROJECT, 1)
    )
    saved = await service.save_draft(
        SaveChapterOutlineDraft(
            PROJECT,
            1,
            draft.draft_id,
            draft.draft_revision,
            draft.content_hash,
            _editable_outline(planning.content),
        )
    )
    confirmed = await service.confirm_draft(
        ConfirmChapterOutlineDraft(
            PROJECT,
            1,
            saved.draft_id,
            saved.draft_revision,
            saved.content_hash,
            0,
            "confirm-authoritative-session-outline",
        )
    )
    return planning_service, planning, confirmed


def _create_command(planning, outline, chapter_number=1):
    return CreateChapterSession(
        PROJECT,
        chapter_number,
        planning.revision,
        planning.content_hash,
        outline.revision,
        outline.content_hash,
        0,
    )


async def _counts(session):
    sessions = await session.fetchone(
        "SELECT COUNT(*) AS count FROM chapter_sessions WHERE project_id=%s",
        (PROJECT,),
    )
    drafts = await session.fetchone(
        "SELECT COUNT(*) AS count FROM working_drafts WHERE project_id=%s",
        (PROJECT,),
    )
    return sessions["count"], drafts["count"]


@pytest.mark.asyncio
async def test_concurrent_different_chapters_create_only_authority_and_replay(
    disposable_mysql,
):
    await _prove_owned_database(disposable_mysql)
    _, planning, outline = await _confirmed_outline(disposable_mysql)
    inserted = asyncio.Event()
    release = asyncio.Event()
    lock_attempted = asyncio.Event()
    transaction_factory = transaction_factory_for(
        disposable_mysql.connection_config
    )
    first_service = ChapterSessionService(
        _PauseAfterSessionInsert(
            inserted=inserted,
            release=release,
        ),
        transaction_factory=transaction_factory,
    )
    second_service = ChapterSessionService(
        _LockProbeRepository(lock_attempted=lock_attempted),
        transaction_factory=transaction_factory,
    )
    first_task = asyncio.create_task(
        first_service.create_session(_create_command(planning, outline, 1))
    )
    second_task = None
    try:
        await asyncio.wait_for(inserted.wait(), timeout=_TIMEOUT)
        second_task = asyncio.create_task(
            second_service.create_session(
                _create_command(planning, outline, 2)
            )
        )
        await asyncio.wait_for(lock_attempted.wait(), timeout=_TIMEOUT)
        assert not second_task.done()
        release.set()
        first = await asyncio.wait_for(first_task, timeout=_TIMEOUT)
        with pytest.raises(
            ChapterSessionConflict,
            match="server authority",
        ):
            await asyncio.wait_for(second_task, timeout=_TIMEOUT)
    finally:
        release.set()
        for task in (first_task, second_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (first_task, second_task) if task is not None),
            return_exceptions=True,
        )

    await disposable_mysql.session.execute(
        """UPDATE project_planning_heads
              SET revision=0,planning_revision_id=NULL,content_hash=NULL
            WHERE project_id=%s""",
        (PROJECT,),
    )
    replay = await second_service.create_session(
        _create_command(planning, outline, 1)
    )
    assert replay.session.id == first.session.id
    assert await _counts(disposable_mysql.session) == (1, 1)
    persisted = await disposable_mysql.session.fetchone(
        """SELECT chapter_num,planning_revision,planning_hash,
                  chapter_outline_revision,chapter_outline_hash,
                  expected_canon_revision,status
             FROM chapter_sessions WHERE project_id=%s""",
        (PROJECT,),
    )
    assert persisted == {
        "chapter_num": 1,
        "planning_revision": planning.revision,
        "planning_hash": planning.content_hash,
        "chapter_outline_revision": outline.revision,
        "chapter_outline_hash": outline.content_hash,
        "expected_canon_revision": 0,
        "status": "drafting",
    }


@pytest.mark.asyncio
async def test_unconfirmed_or_current_drifted_outline_cannot_create_session(
    disposable_mysql,
):
    await _prove_owned_database(disposable_mysql)
    _, planning = await _confirmed_planning(disposable_mysql)
    outline_service = ChapterOutlineService(
        ChapterOutlineRepository(),
        ChapterSessionRepository(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
        id_factory=lambda: "9e100000-0000-0000-0000-000000000001",
        clock=lambda: NOW + 910,
    )
    await outline_service.create_draft(
        CreateChapterOutlineDraft(PROJECT, 1)
    )
    service = ChapterSessionService(
        ChapterSessionRepository(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
    )
    missing_command = CreateChapterSession(
        PROJECT,
        1,
        planning.revision,
        planning.content_hash,
        1,
        "a" * 64,
        0,
    )

    with pytest.raises(
        ChapterSessionPreconditionFailed,
        match="confirmed outline",
    ):
        await service.create_session(missing_command)
    assert await _counts(disposable_mysql.session) == (0, 0)


@pytest.mark.asyncio
async def test_current_planning_drift_and_archived_project_fail_closed(
    disposable_mysql,
):
    await _prove_owned_database(disposable_mysql)
    _, planning, outline = await _confirmed_outline(disposable_mysql)
    service = ChapterSessionService(
        ChapterSessionRepository(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
    )
    await disposable_mysql.session.execute(
        """UPDATE project_planning_heads
              SET revision=0,planning_revision_id=NULL,content_hash=NULL
            WHERE project_id=%s""",
        (PROJECT,),
    )

    with pytest.raises(ChapterSessionConflict, match="Planning"):
        await service.create_session(_create_command(planning, outline))
    assert await _counts(disposable_mysql.session) == (0, 0)

    await disposable_mysql.session.execute(
        "UPDATE projects SET archived_at=%s WHERE id=%s",
        (NOW + 920, PROJECT),
    )
    with pytest.raises(http_errors.ProjectArchived):
        await service.create_session(_create_command(planning, outline))
    assert await _counts(disposable_mysql.session) == (0, 0)


@pytest.mark.asyncio
async def test_candidate_basis_follows_current_outline_not_immutable_session(
    disposable_mysql,
):
    await _prove_owned_database(disposable_mysql)
    _, planning, outline_r1 = await _confirmed_outline(disposable_mysql)
    transaction_factory = transaction_factory_for(
        disposable_mysql.connection_config
    )
    service = ChapterSessionService(
        ChapterSessionRepository(),
        transaction_factory=transaction_factory,
        connection_factory=transaction_factory,
    )
    created = await service.create_session(_create_command(planning, outline_r1))
    await service.save_working_draft(
        SaveWorkingDraft(PROJECT, created.session.id, 1, "候选稿 A")
    )
    await service.save_candidate(SaveDraftCandidate(PROJECT, created.session.id, 2))

    ids = iter(
        f"9e200000-0000-0000-0000-{number:012d}"
        for number in range(1, 20)
    )
    outline_service = ChapterOutlineService(
        ChapterOutlineRepository(),
        ChapterSessionRepository(),
        transaction_factory=transaction_factory,
        id_factory=ids.__next__,
        clock=lambda: NOW + 950,
    )
    draft = await outline_service.create_draft(
        CreateChapterOutlineDraft(PROJECT, 1)
    )
    saved = await outline_service.save_draft(
        SaveChapterOutlineDraft(
            PROJECT,
            1,
            draft.draft_id,
            draft.draft_revision,
            draft.content_hash,
            _editable_outline(planning.content),
        )
    )
    outline_r2 = await outline_service.confirm_draft(
        ConfirmChapterOutlineDraft(
            PROJECT,
            1,
            saved.draft_id,
            saved.draft_revision,
            saved.content_hash,
            outline_r1.revision,
            "adjust-outline-before-finalization",
        )
    )
    replay = await service.save_candidate(
        SaveDraftCandidate(PROJECT, created.session.id, 2)
    )
    await service.save_working_draft(
        SaveWorkingDraft(PROJECT, created.session.id, 2, "候选稿 A")
    )
    third = await service.save_candidate(
        SaveDraftCandidate(PROJECT, created.session.id, 3)
    )

    workspace = await service.get(PROJECT, 1)

    candidate_a, candidate_b = workspace.candidates
    assert candidate_a.basis_status == "stale"
    assert candidate_a.outline_revision == outline_r1.revision
    assert candidate_b.basis_status == "current"
    assert candidate_b.outline_revision == outline_r2.revision
    assert candidate_b.canon_revision == 0
    assert workspace.session.chapter_outline_revision == outline_r1.revision
    assert candidate_a.content_hash == candidate_b.content_hash
    assert len(replay.candidates) == len(third.candidates) == 2
    rows = await disposable_mysql.session.fetchall(
        """SELECT id,content_hash,basis_hash,working_draft_revision,provenance_json
             FROM draft_candidates
            WHERE chapter_session_id=%s
            ORDER BY created_at,id""",
        (created.session.id,),
    )
    assert len(rows) == 2
    assert rows[0]["content_hash"] == rows[1]["content_hash"]
    assert rows[0]["id"] != rows[1]["id"]
    assert rows[0]["basis_hash"] != rows[1]["basis_hash"]
    assert rows[1]["working_draft_revision"] == 2
    stored_basis = json.loads(rows[1]["provenance_json"])
    assert stored_basis["workingDraftRevision"] == 2
    assert stored_basis["outlineRevision"] == outline_r2.revision


@pytest.mark.asyncio
async def test_final_session_rejects_candidate_save_without_creating_row(
    disposable_mysql,
):
    await _prove_owned_database(disposable_mysql)
    _, planning, outline = await _confirmed_outline(disposable_mysql)
    transaction_factory = transaction_factory_for(disposable_mysql.connection_config)
    service = ChapterSessionService(
        ChapterSessionRepository(), transaction_factory=transaction_factory
    )
    created = await service.create_session(_create_command(planning, outline))
    await service.save_working_draft(
        SaveWorkingDraft(PROJECT, created.session.id, 1, "不可保存的候选稿")
    )
    await disposable_mysql.session.execute(
        "UPDATE chapter_sessions SET status='final' WHERE id=%s",
        (created.session.id,),
    )

    with pytest.raises(ChapterSessionConflict, match="finalized"):
        await service.save_candidate(SaveDraftCandidate(PROJECT, created.session.id, 2))

    row = await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM draft_candidates WHERE chapter_session_id=%s",
        (created.session.id,),
    )
    assert row == {"count": 0}


@pytest.mark.asyncio
async def test_working_draft_failure_rolls_back_session_and_draft(
    disposable_mysql,
):
    await _prove_owned_database(disposable_mysql)
    _, planning, outline = await _confirmed_outline(disposable_mysql)
    service = ChapterSessionService(
        _RejectAfterWorkingDraftInsert(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
    )

    with pytest.raises(
        ChapterSessionConflict,
        match="working draft was not created",
    ):
        await service.create_session(_create_command(planning, outline))

    assert await _counts(disposable_mysql.session) == (0, 0)


class _PauseAfterSessionInsert(ChapterSessionRepository):
    def __init__(self, *, inserted, release):
        self._inserted = inserted
        self._release = release

    async def insert_chapter_session(self, session, row):
        changed = await super().insert_chapter_session(session, row)
        self._inserted.set()
        await asyncio.wait_for(self._release.wait(), timeout=_TIMEOUT)
        return changed


class _LockProbeRepository(ChapterSessionRepository):
    def __init__(self, *, lock_attempted):
        self._lock_attempted = lock_attempted

    async def lock_project(self, session, project_id):
        self._lock_attempted.set()
        return await super().lock_project(session, project_id)


class _RejectAfterWorkingDraftInsert(ChapterSessionRepository):
    async def upsert_working_draft(
        self,
        session,
        row,
        *,
        expected_revision=None,
        expected_content_hash=None,
    ):
        assert await super().upsert_working_draft(
            session,
            row,
            expected_revision=expected_revision,
            expected_content_hash=expected_content_hash,
        )
        return False
