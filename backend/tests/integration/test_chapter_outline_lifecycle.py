from __future__ import annotations

import asyncio
import importlib

import pytest

from backend.domain.json_contracts import canonical_hash
from backend.domain.chapter_outlines import EditableChapterOutlineContent
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.services.chapter_sessions import (
    ChapterSessionService,
    CreateChapterSession,
    SaveDraftCandidate,
    SaveWorkingDraft,
)
from backend.services.chapter_outlines import (
    ChapterOutlineConflict,
    ChapterOutlinePreconditionFailed,
    ChapterOutlineService,
    ConfirmChapterOutlineDraft,
    CreateChapterOutlineDraft,
    SaveChapterOutlineDraft,
)
from backend.services.planning import (
    ConfirmPlanningDraft,
    CreatePlanningDraft,
    SavePlanningDraft,
)
from backend.tests.integration.test_planning_aggregate_lifecycle import (
    NOW,
    PROJECT,
    _advance_basis,
    _editable as _editable_planning,
    _prepare,
    _save_complete,
)
from backend.tests.integration.test_seed_revisions import connection_factory_for
from backend.tests.support.disposable_mysql import transaction_factory_for


pytestmark = pytest.mark.mysql
_CONCURRENCY_TIMEOUT = 5


def _consume_future_exception(future):
    if not future.cancelled():
        future.exception()


async def _await_race_tasks(*tasks):
    aggregate = asyncio.gather(*tasks)
    try:
        return await asyncio.wait_for(
            asyncio.shield(aggregate),
            timeout=_CONCURRENCY_TIMEOUT,
        )
    except asyncio.TimeoutError:
        aggregate.add_done_callback(_consume_future_exception)
        raise


async def _cancel_race_tasks(*tasks):
    tasks = tuple(task for task in tasks if task is not None)
    for task in tasks:
        if not task.done():
            task.cancel()
    if not tasks:
        return None
    cleanup = asyncio.gather(*tasks, return_exceptions=True)
    try:
        await asyncio.wait_for(
            asyncio.shield(cleanup),
            timeout=_CONCURRENCY_TIMEOUT,
        )
    except asyncio.TimeoutError as error:
        for task in tasks:
            if not task.done():
                task.cancel()
        cleanup.add_done_callback(_consume_future_exception)
        return error
    return None


@pytest.mark.asyncio
async def test_real_mysql_manual_outline_create_is_singleton(disposable_mysql):
    planning_service = await _prepare(disposable_mysql)
    saved_planning = await _save_complete(planning_service)
    await planning_service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            saved_planning.draft_id,
            saved_planning.draft_revision,
            saved_planning.content_hash,
            "confirm-for-manual-outline",
        )
    )
    service = ChapterOutlineService(
        _repository(),
        ChapterSessionRepository(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
        id_factory=lambda: "9c000000-0000-0000-0000-000000000001",
        clock=lambda: NOW + 100,
    )

    first = await service.create_draft(
        CreateChapterOutlineDraft(PROJECT, 1)
    )
    replay = await service.create_draft(
        CreateChapterOutlineDraft(PROJECT, 1)
    )

    assert first == replay
    assert first.draft_revision == 1
    assert first.content.schema_version == "chapter-outline-draft-v1"
    assert first.status == "current"


@pytest.mark.asyncio
async def test_real_mysql_concurrent_outline_create_replays_committed_draft(
    disposable_mysql,
):
    planning_service = await _prepare(disposable_mysql)
    saved_planning = await _save_complete(planning_service)
    await planning_service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            saved_planning.draft_id,
            saved_planning.draft_revision,
            saved_planning.content_hash,
            "confirm-before-concurrent-outline-create",
        )
    )
    inserted = asyncio.Event()
    release_insert = asyncio.Event()
    lock_attempted = asyncio.Event()
    transaction_factory = transaction_factory_for(
        disposable_mysql.connection_config
    )
    first_service = ChapterOutlineService(
        _PauseAfterInsertRepository(
            _repository(),
            inserted=inserted,
            release=release_insert,
        ),
        ChapterSessionRepository(),
        transaction_factory=transaction_factory,
        id_factory=lambda: "9c100000-0000-0000-0000-000000000001",
        clock=lambda: NOW + 110,
    )
    second_service = ChapterOutlineService(
        _LockProbeRepository(
            _repository(),
            lock_attempted=lock_attempted,
        ),
        ChapterSessionRepository(),
        transaction_factory=transaction_factory,
        id_factory=lambda: "9c100000-0000-0000-0000-000000000002",
        clock=lambda: NOW + 111,
    )

    first_task = None
    second_task = None
    primary_error = None
    try:
        first_task = asyncio.create_task(
            first_service.create_draft(
                CreateChapterOutlineDraft(PROJECT, 1)
            )
        )
        await asyncio.wait_for(
            inserted.wait(),
            timeout=_CONCURRENCY_TIMEOUT,
        )
        second_task = asyncio.create_task(
            second_service.create_draft(
                CreateChapterOutlineDraft(PROJECT, 1)
            )
        )
        await asyncio.wait_for(
            lock_attempted.wait(),
            timeout=_CONCURRENCY_TIMEOUT,
        )
        release_insert.set()
        first, second = await _await_race_tasks(first_task, second_task)
    except BaseException as error:
        primary_error = error
        raise
    finally:
        release_insert.set()
        cleanup_error = await _cancel_race_tasks(first_task, second_task)
        if cleanup_error is not None and primary_error is None:
            raise cleanup_error

    assert second == first
    rows = await disposable_mysql.session.fetchall(
        """SELECT id,status FROM chapter_outline_drafts
            WHERE project_id=%s AND chapter_num=1""",
        (PROJECT,),
    )
    assert rows == [
        {
            "id": "9c100000-0000-0000-0000-000000000001",
            "status": "active",
        }
    ]


def _ref(node):
    return {
        "id": node.id,
        "revision": node.revision,
        "contentHash": node.content_hash,
    }


def _editable_outline(planning):
    volume = planning.volumes[0]
    block = planning.story_blocks[0]
    stage = block.stages[0]
    task = stage.scene_tasks[0]
    return EditableChapterOutlineContent.model_validate(
        {
            "schemaVersion": "chapter-outline-draft-v1",
            "volumeRef": _ref(volume),
            "storyBlockRef": _ref(block),
            "stageRefs": [_ref(stage)],
            "sceneTaskRefs": [_ref(task)],
            "chapterGoal": "找到封锁线缺口。",
            "expectedCharacters": ["主角", "同伴"],
            "continuation": ["承接被困局面"],
            "plannedTasks": ["观察换岗"],
            "scenes": ["废弃驿站侦察"],
            "forbiddenEarlyEvents": ["不可提前揭示内应"],
        }
    )


@pytest.mark.asyncio
async def test_real_mysql_manual_outline_save_confirm_replay_and_history(
    disposable_mysql,
):
    planning_service = await _prepare(disposable_mysql)
    saved_planning = await _save_complete(planning_service)
    planning = await planning_service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            saved_planning.draft_id,
            saved_planning.draft_revision,
            saved_planning.content_hash,
            "confirm-for-outline-workflow",
        )
    )
    ids = iter(
        (
            "9d000000-0000-0000-0000-000000000001",
            "9d000000-0000-0000-0000-000000000002",
            "9d000000-0000-0000-0000-000000000003",
        )
    )
    service = ChapterOutlineService(
        _repository(),
        ChapterSessionRepository(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
        id_factory=ids.__next__,
        clock=lambda: NOW + 200,
    )
    draft = await service.create_draft(
        CreateChapterOutlineDraft(PROJECT, 1)
    )
    with pytest.raises(ChapterOutlineConflict):
        await service.save_draft(
            SaveChapterOutlineDraft(
                PROJECT,
                1,
                draft.draft_id,
                draft.draft_revision,
                "f" * 64,
                _editable_outline(planning.content),
            )
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
    assert saved.status == "current"
    command = ConfirmChapterOutlineDraft(
        PROJECT,
        1,
        saved.draft_id,
        saved.draft_revision,
        saved.content_hash,
        0,
        "confirm-outline-workflow",
    )
    confirmed = await service.confirm_draft(command)
    await disposable_mysql.session.execute(
        """UPDATE projection_heads
              SET projection_revision_number=1
            WHERE project_id=%s""",
        (PROJECT,),
    )
    replay = await service.confirm_draft(command)
    await disposable_mysql.session.execute(
        """UPDATE projection_heads
              SET projection_revision_number=canon_revision_number
            WHERE project_id=%s""",
        (PROJECT,),
    )

    assert replay == confirmed
    assert confirmed.revision == 1
    assert confirmed.content.chapter_goal == "找到封锁线缺口。"
    current = await service.get_current(PROJECT)
    assert current.target_path == f"/projects/{PROJECT}/write/chapters/1"
    assert current.confirmed_outline == confirmed
    assert current.draft is None
    assert current.capabilities.start_session is True
    history = await service.history(PROJECT, 1)
    assert [(item.revision, item.display_status) for item in history] == [
        (1, "current")
    ]

    with pytest.raises(ChapterOutlineConflict):
        await service.confirm_draft(
            ConfirmChapterOutlineDraft(
                PROJECT,
                1,
                saved.draft_id,
                saved.draft_revision,
                saved.content_hash,
                1,
                "confirm-outline-workflow",
            )
        )
    chapter_service = ChapterSessionService(
        ChapterSessionRepository(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
    )
    await chapter_service.create_session(
        CreateChapterSession(
            PROJECT,
            1,
            planning.revision,
            planning.content_hash,
            confirmed.revision,
            confirmed.content_hash,
            0,
        )
    )
    assert await service.confirm_draft(command) == confirmed


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ("save", "confirm"))
async def test_real_mysql_outline_mutation_allows_drafting_session_committed_while_waiting(
    disposable_mysql,
    mutation,
):
    planning_service = await _prepare(disposable_mysql)
    saved_planning = await _save_complete(planning_service)
    planning = await planning_service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            saved_planning.draft_id,
            saved_planning.draft_revision,
            saved_planning.content_hash,
            f"confirm-before-outline-{mutation}-wait",
        )
    )
    ids = iter(
        (
            "9d100000-0000-0000-0000-000000000001",
            "9d100000-0000-0000-0000-000000000002",
            "9d100000-0000-0000-0000-000000000003",
            "9d100000-0000-0000-0000-000000000004",
        )
    )
    transaction_factory = transaction_factory_for(
        disposable_mysql.connection_config
    )
    setup_service = ChapterOutlineService(
        _repository(),
        ChapterSessionRepository(),
        transaction_factory=transaction_factory,
        id_factory=ids.__next__,
        clock=lambda: NOW + 250,
    )
    first_draft = await setup_service.create_draft(
        CreateChapterOutlineDraft(PROJECT, 1)
    )
    saved_first = await setup_service.save_draft(
        SaveChapterOutlineDraft(
            PROJECT,
            1,
            first_draft.draft_id,
            first_draft.draft_revision,
            first_draft.content_hash,
            _editable_outline(planning.content),
        )
    )
    confirmed = await setup_service.confirm_draft(
        ConfirmChapterOutlineDraft(
            PROJECT,
            1,
            saved_first.draft_id,
            saved_first.draft_revision,
            saved_first.content_hash,
            0,
            f"confirm-outline-before-{mutation}-wait",
        )
    )
    second_draft = await setup_service.create_draft(
        CreateChapterOutlineDraft(PROJECT, 1)
    )
    saved_second = await setup_service.save_draft(
        SaveChapterOutlineDraft(
            PROJECT,
            1,
            second_draft.draft_id,
            second_draft.draft_revision,
            second_draft.content_hash,
            _editable_outline(planning.content),
        )
    )
    lock_attempted = asyncio.Event()
    mutation_service = ChapterOutlineService(
        _LockProbeRepository(
            _repository(),
            lock_attempted=lock_attempted,
        ),
        ChapterSessionRepository(),
        transaction_factory=transaction_factory,
        id_factory=lambda: "9d100000-0000-0000-0000-000000000005",
        clock=lambda: NOW + 251,
    )
    if mutation == "save":
        command = SaveChapterOutlineDraft(
            PROJECT,
            1,
            saved_second.draft_id,
            saved_second.draft_revision,
            saved_second.content_hash,
            _editable_outline(planning.content),
        )
        mutate = mutation_service.save_draft
    else:
        command = ConfirmChapterOutlineDraft(
            PROJECT,
            1,
            saved_second.draft_id,
            saved_second.draft_revision,
            saved_second.content_hash,
            confirmed.revision,
            "confirm-outline-after-session-wait",
        )
        mutate = mutation_service.confirm_draft

    chapter_repository = ChapterSessionRepository()
    mutation_task = None
    primary_error = None
    try:
        async with transaction_factory() as blocker:
            await chapter_repository.lock_project(blocker, PROJECT)
            outline = await chapter_repository.read_current_outline(
                blocker,
                PROJECT,
                1,
            )
            mutation_task = asyncio.create_task(mutate(command))
            await asyncio.wait_for(
                lock_attempted.wait(),
                timeout=_CONCURRENCY_TIMEOUT,
            )
            assert await chapter_repository.insert_chapter_session(
                blocker,
                {
                    "id": "9d100000-0000-0000-0000-000000000006",
                    "project_id": PROJECT,
                    "planning_revision_id": outline["planning_revision_id"],
                    "planning_revision": outline["planning_revision"],
                    "planning_hash": outline["planning_hash"],
                    "story_block_id": outline["story_block_id"],
                    "story_block_revision": outline["story_block_revision"],
                    "story_block_hash": outline["story_block_hash"],
                    "chapter_outline_revision_id": (
                        outline["chapter_outline_revision_id"]
                    ),
                    "chapter_outline_revision": (
                        outline["chapter_outline_revision"]
                    ),
                    "chapter_outline_hash": outline["chapter_outline_hash"],
                    "chapter_num": 1,
                    "expected_canon_revision": outline["canon_revision"],
                    "status": "drafting",
                    "created_at": NOW + 252,
                    "finalized_at": None,
                },
            )

        await _await_race_tasks(mutation_task)
    except BaseException as error:
        primary_error = error
        raise
    finally:
        cleanup_error = await _cancel_race_tasks(mutation_task)
        if cleanup_error is not None and primary_error is None:
            raise cleanup_error
    persisted_draft = await disposable_mysql.session.fetchone(
        """SELECT status,draft_revision,content_hash
             FROM chapter_outline_drafts
            WHERE project_id=%s AND id=%s""",
        (PROJECT, saved_second.draft_id),
    )
    assert persisted_draft == {
        "status": "active" if mutation == "save" else "confirmed",
        "draft_revision": (
            saved_second.draft_revision + 1
            if mutation == "save"
            else saved_second.draft_revision
        ),
        "content_hash": saved_second.content_hash,
    }
    revision_count = await disposable_mysql.session.fetchone(
        """SELECT COUNT(*) AS revision_count
             FROM chapter_outline_revisions
            WHERE project_id=%s""",
        (PROJECT,),
    )
    assert revision_count["revision_count"] == (1 if mutation == "save" else 2)


@pytest.mark.asyncio
async def test_real_mysql_outline_basis_drift_supersedes_draft(
    disposable_mysql,
):
    planning_service = await _prepare(disposable_mysql)
    saved_planning = await _save_complete(planning_service)
    planning = await planning_service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            saved_planning.draft_id,
            saved_planning.draft_revision,
            saved_planning.content_hash,
            "confirm-for-outline-drift",
        )
    )
    service = ChapterOutlineService(
        _repository(),
        ChapterSessionRepository(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
        id_factory=lambda: "9e000000-0000-0000-0000-000000000001",
        clock=lambda: NOW + 300,
    )
    draft = await service.create_draft(
        CreateChapterOutlineDraft(PROJECT, 1)
    )
    await disposable_mysql.session.execute(
        """UPDATE projection_heads
              SET canon_revision_number=1,projection_revision_number=1
            WHERE project_id=%s""",
        (PROJECT,),
    )

    with pytest.raises(ChapterOutlinePreconditionFailed):
        await service.save_draft(
            SaveChapterOutlineDraft(
                PROJECT,
                1,
                draft.draft_id,
                draft.draft_revision,
                draft.content_hash,
                _editable_outline(planning.content),
            )
        )

    row = await disposable_mysql.session.fetchone(
        """SELECT status,active_slot
             FROM chapter_outline_drafts
            WHERE project_id=%s AND id=%s""",
        (PROJECT, draft.draft_id),
    )
    assert row == {"status": "superseded", "active_slot": None}


@pytest.mark.asyncio
async def test_real_mysql_outline_rejects_stale_planning_head_after_basis_advance(
    disposable_mysql,
):
    planning_service = await _prepare(disposable_mysql)
    saved_planning = await _save_complete(planning_service)
    planning = await planning_service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            saved_planning.draft_id,
            saved_planning.draft_revision,
            saved_planning.content_hash,
            "confirm-before-upstream-basis-advance",
        )
    )
    service = ChapterOutlineService(
        _repository(),
        ChapterSessionRepository(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
        id_factory=lambda: "9e080000-0000-0000-0000-000000000001",
        clock=lambda: NOW + 325,
    )
    draft = await service.create_draft(
        CreateChapterOutlineDraft(PROJECT, 1)
    )
    selected = await disposable_mysql.session.fetchone(
        """SELECT seed_id,seed_revision_id
             FROM project_selected_seeds
            WHERE project_id=%s""",
        (PROJECT,),
    )
    await _advance_basis(
        disposable_mysql.session,
        2,
        "4",
        target_seed_id=selected["seed_id"],
        target_seed_revision_id=selected["seed_revision_id"],
    )

    planning_state = await planning_service.get_state(PROJECT)
    assert planning_state.future_plan is None
    state = await service.get_current(PROJECT)
    assert state.planning_authority is None
    assert state.capabilities.create_draft is False
    assert state.capabilities.edit_draft is False
    assert state.capabilities.generate is False
    assert state.capabilities.confirm is False
    assert state.capabilities.start_session is False

    with pytest.raises(ChapterOutlinePreconditionFailed):
        await service.create_draft(CreateChapterOutlineDraft(PROJECT, 1))
    with pytest.raises(ChapterOutlinePreconditionFailed):
        await service.save_draft(
            SaveChapterOutlineDraft(
                PROJECT,
                1,
                draft.draft_id,
                draft.draft_revision,
                draft.content_hash,
                _editable_outline(planning.content),
            )
        )
    with pytest.raises(ChapterOutlinePreconditionFailed):
        await service.confirm_draft(
            ConfirmChapterOutlineDraft(
                PROJECT,
                1,
                draft.draft_id,
                draft.draft_revision,
                draft.content_hash,
                0,
                "confirm-after-upstream-basis-advance",
            )
        )
    revision_count = await disposable_mysql.session.fetchone(
        """SELECT COUNT(*) AS revision_count
             FROM chapter_outline_revisions
            WHERE project_id=%s""",
        (PROJECT,),
    )
    assert revision_count["revision_count"] == 0


@pytest.mark.asyncio
async def test_real_mysql_outline_confirm_supersedes_mismatched_basis(
    disposable_mysql,
):
    planning_service = await _prepare(disposable_mysql)
    saved_planning = await _save_complete(planning_service)
    planning = await planning_service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            saved_planning.draft_id,
            saved_planning.draft_revision,
            saved_planning.content_hash,
            "confirm-for-outline-confirm-drift",
        )
    )
    ids = iter(
        (
            "9e100000-0000-0000-0000-000000000001",
            "9e100000-0000-0000-0000-000000000002",
        )
    )
    service = ChapterOutlineService(
        _repository(),
        ChapterSessionRepository(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
        id_factory=ids.__next__,
        clock=lambda: NOW + 350,
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
    await disposable_mysql.session.execute(
        """UPDATE projection_heads
              SET projection_revision_number=1
            WHERE project_id=%s""",
        (PROJECT,),
    )

    with pytest.raises(ChapterOutlinePreconditionFailed):
        await service.confirm_draft(
            ConfirmChapterOutlineDraft(
                PROJECT,
                1,
                saved.draft_id,
                saved.draft_revision,
                saved.content_hash,
                0,
                "confirm-outline-after-drift",
            )
        )

    row = await disposable_mysql.session.fetchone(
        """SELECT status,active_slot
             FROM chapter_outline_drafts
            WHERE project_id=%s AND id=%s""",
        (PROJECT, saved.draft_id),
    )
    assert row == {"status": "superseded", "active_slot": None}


@pytest.mark.asyncio
async def test_real_mysql_outline_confirmation_failpoint_rolls_back(
    disposable_mysql,
):
    planning_service = await _prepare(disposable_mysql)
    saved_planning = await _save_complete(planning_service)
    planning = await planning_service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            saved_planning.draft_id,
            saved_planning.draft_revision,
            saved_planning.content_hash,
            "confirm-for-outline-rollback",
        )
    )
    ids = iter(
        (
            "9f000000-0000-0000-0000-000000000001",
            "9f000000-0000-0000-0000-000000000002",
            "9f000000-0000-0000-0000-000000000003",
        )
    )

    def failpoint(stage):
        if stage == "after_head_advance":
            raise RuntimeError("outline rollback sentinel")

    service = ChapterOutlineService(
        _repository(),
        ChapterSessionRepository(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
        id_factory=ids.__next__,
        clock=lambda: NOW + 400,
        failpoint=failpoint,
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
    with pytest.raises(RuntimeError, match="rollback sentinel"):
        await service.confirm_draft(
            ConfirmChapterOutlineDraft(
                PROJECT,
                1,
                saved.draft_id,
                saved.draft_revision,
                saved.content_hash,
                0,
                "confirm-outline-rollback",
            )
        )

    counts = {}
    for table in (
        "chapter_outline_revisions",
        "project_chapter_outline_heads",
        "chapter_outline_confirmation_requests",
    ):
        row = await disposable_mysql.session.fetchone(
            f"SELECT COUNT(*) AS count FROM {table} WHERE project_id=%s",
            (PROJECT,),
        )
        counts[table] = row["count"]
    persisted_draft = await disposable_mysql.session.fetchone(
        """SELECT status,draft_revision,content_hash
             FROM chapter_outline_drafts
            WHERE project_id=%s AND id=%s""",
        (PROJECT, saved.draft_id),
    )

    assert counts == {
        "chapter_outline_revisions": 0,
        "project_chapter_outline_heads": 0,
        "chapter_outline_confirmation_requests": 0,
    }
    assert persisted_draft == {
        "status": "active",
        "draft_revision": saved.draft_revision,
        "content_hash": saved.content_hash,
    }


@pytest.mark.asyncio
async def test_real_mysql_outline_history_and_active_session_pin_exact_authority(
    disposable_mysql,
):
    planning_service = await _prepare(disposable_mysql)
    saved_planning = await _save_complete(planning_service)
    planning_one = await planning_service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            saved_planning.draft_id,
            saved_planning.draft_revision,
            saved_planning.content_hash,
            "confirm-planning-one-for-history",
        )
    )
    outline_ids = iter(
        f"9a100000-0000-0000-0000-{number:012d}"
        for number in range(1, 20)
    )
    transaction = transaction_factory_for(
        disposable_mysql.connection_config
    )
    service = ChapterOutlineService(
        _repository(),
        ChapterSessionRepository(),
        transaction_factory=transaction,
        id_factory=outline_ids.__next__,
        clock=lambda: NOW + 500,
    )

    async def confirm_outline(planning, expected_head, key):
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
        return await service.confirm_draft(
            ConfirmChapterOutlineDraft(
                PROJECT,
                1,
                saved.draft_id,
                saved.draft_revision,
                saved.content_hash,
                expected_head,
                key,
            )
        )

    async def advance_planning(title, key):
        draft = await planning_service.create_draft(
            CreatePlanningDraft(PROJECT, f"create-{key}")
        )
        saved = await planning_service.save_draft(
            SavePlanningDraft(
                PROJECT,
                draft.draft_id,
                draft.draft_revision,
                draft.content_hash,
                _editable_planning(draft.content, title=title),
                f"save-{key}",
            )
        )
        return await planning_service.confirm_draft(
            ConfirmPlanningDraft(
                PROJECT,
                saved.draft_id,
                saved.draft_revision,
                saved.content_hash,
                f"confirm-{key}",
            )
        )

    outline_one = await confirm_outline(
        planning_one,
        0,
        "confirm-outline-one-for-history",
    )
    planning_two = await advance_planning(
        "第二版第一卷",
        "planning-two-for-history",
    )
    assert (await service.history(PROJECT, 1))[0].display_status == (
        "superseded"
    )

    outline_two = await confirm_outline(
        planning_two,
        1,
        "confirm-outline-two-for-history",
    )
    chapter_service = ChapterSessionService(
        ChapterSessionRepository(),
        transaction_factory=transaction,
    )
    chapter_session = await chapter_service.create_session(
        CreateChapterSession(
            PROJECT,
            1,
            planning_two.revision,
            planning_two.content_hash,
            outline_two.revision,
            outline_two.content_hash,
            0,
        )
    )

    await advance_planning(
        "第三版第一卷",
        "planning-three-after-session",
    )
    current = await service.get_current(PROJECT)

    assert current.active_session.chapter_session_id == (
        chapter_session.session.id
    )
    assert current.planning_authority.revision == 3
    assert current.confirmed_outline.outline_revision_id == (
        outline_two.outline_revision_id
    )
    assert current.confirmed_outline.display_status == "superseded"
    assert current.capabilities == type(current.capabilities)(
        view=True,
        create_draft=True,
        edit_draft=False,
        generate=False,
        confirm=False,
        start_session=False,
    )
    history = await service.history(PROJECT, 1)
    assert [
        (item.outline_revision_id, item.display_status)
        for item in history
    ] == [
        (outline_two.outline_revision_id, "session_pinned"),
        (outline_one.outline_revision_id, "superseded"),
    ]

    await disposable_mysql.session.execute(
        "UPDATE projects SET archived_at=%s WHERE id=%s",
        (NOW + 600, PROJECT),
    )
    archived = await service.get_current(PROJECT)
    assert archived.lifecycle == "archived"
    assert all(
        item.display_status == "archived"
        for item in await service.history(PROJECT, 1)
    )


@pytest.mark.asyncio
async def test_real_mysql_drafting_session_keeps_r1_while_outline_advances_to_r2(
    disposable_mysql,
):
    planning_service = await _prepare(disposable_mysql)
    saved_planning = await _save_complete(planning_service)
    planning = await planning_service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            saved_planning.draft_id,
            saved_planning.draft_revision,
            saved_planning.content_hash,
            "confirm-planning-for-drafting-adjustment",
        )
    )
    transaction = transaction_factory_for(disposable_mysql.connection_config)
    outline_service = ChapterOutlineService(
        _repository(),
        ChapterSessionRepository(),
        transaction_factory=transaction,
    )

    first_draft = await outline_service.create_draft(
        CreateChapterOutlineDraft(PROJECT, 1)
    )
    first_saved = await outline_service.save_draft(
        SaveChapterOutlineDraft(
            PROJECT,
            1,
            first_draft.draft_id,
            first_draft.draft_revision,
            first_draft.content_hash,
            _editable_outline(planning.content),
        )
    )
    outline_r1 = await outline_service.confirm_draft(
        ConfirmChapterOutlineDraft(
            PROJECT,
            1,
            first_saved.draft_id,
            first_saved.draft_revision,
            first_saved.content_hash,
            0,
            "adopt-outline-r1-for-drafting-adjustment",
        )
    )
    chapter_service = ChapterSessionService(
        ChapterSessionRepository(),
        transaction_factory=transaction,
        connection_factory=connection_factory_for(
            disposable_mysql.connection_config
        ),
    )
    workspace = await chapter_service.create_session(
        CreateChapterSession(
            PROJECT,
            1,
            planning.revision,
            planning.content_hash,
            outline_r1.revision,
            outline_r1.content_hash,
            0,
        )
    )
    saved_workspace = await chapter_service.save_working_draft(
        SaveWorkingDraft(
            PROJECT,
            workspace.session.id,
            workspace.working_draft.revision,
            "保留的正文工作稿",
        )
    )
    candidate_workspace = await chapter_service.save_candidate(
        SaveDraftCandidate(
            PROJECT,
            workspace.session.id,
            saved_workspace.working_draft.revision,
        )
    )
    before_session = await disposable_mysql.session.fetchone(
        """SELECT id,chapter_outline_revision,chapter_outline_hash,status
             FROM chapter_sessions WHERE id=%s""",
        (workspace.session.id,),
    )

    adjustment = await outline_service.create_draft(
        CreateChapterOutlineDraft(PROJECT, 1)
    )

    assert adjustment.base_head_revision == outline_r1.revision
    assert adjustment.content == outline_r1.content.model_copy(
        update={"schema_version": "chapter-outline-draft-v1"}
    )
    adjusted_content = adjustment.content.model_copy(
        update={
            "chapter_goal": "调整后的本章目标。",
            "scenes": ("调整后的场景。",),
        }
    )
    saved_adjustment = await outline_service.save_draft(
        SaveChapterOutlineDraft(
            PROJECT,
            1,
            adjustment.draft_id,
            adjustment.draft_revision,
            adjustment.content_hash,
            adjusted_content,
        )
    )
    outline_r2 = await outline_service.confirm_draft(
        ConfirmChapterOutlineDraft(
            PROJECT,
            1,
            saved_adjustment.draft_id,
            saved_adjustment.draft_revision,
            saved_adjustment.content_hash,
            outline_r1.revision,
            "adopt-outline-r2-for-drafting-adjustment",
        )
    )
    after_session = await disposable_mysql.session.fetchone(
        """SELECT id,chapter_outline_revision,chapter_outline_hash,status
             FROM chapter_sessions WHERE id=%s""",
        (workspace.session.id,),
    )
    head = await disposable_mysql.session.fetchone(
        """SELECT revision,outline_revision_id FROM project_chapter_outline_heads
             WHERE project_id=%s AND chapter_num=%s""",
        (PROJECT, 1),
    )
    preserved_workspace = await chapter_service.get(PROJECT, 1)
    current = await outline_service.get_current(PROJECT)

    assert after_session == before_session
    assert after_session["chapter_outline_revision"] == outline_r1.revision
    assert head == {"revision": outline_r2.revision, "outline_revision_id": outline_r2.outline_revision_id}
    assert current.confirmed_outline.outline_revision_id == outline_r2.outline_revision_id
    assert current.confirmed_outline.revision == outline_r2.revision
    assert current.confirmed_outline.display_status == "current"
    assert current.active_session.outline_revision == outline_r1.revision
    assert current.planning_authority.revision == planning.revision
    assert current.canon_projection_authority.canon_revision == 0
    assert preserved_workspace is not None
    assert preserved_workspace.working_draft.content == "保留的正文工作稿"
    assert [candidate.content for candidate in preserved_workspace.candidates] == [
        candidate_workspace.candidates[0].content
    ]


def _repository():
    module = importlib.import_module("backend.repositories.chapter_outlines")
    return module.ChapterOutlineRepository()


class _DelegatingOutlineRepository:
    def __init__(self, delegate):
        self._delegate = delegate

    def __getattr__(self, name):
        return getattr(self._delegate, name)


class _PauseAfterInsertRepository(_DelegatingOutlineRepository):
    def __init__(self, delegate, *, inserted, release):
        super().__init__(delegate)
        self._inserted = inserted
        self._release = release

    async def insert_draft(self, session, row):
        inserted = await self._delegate.insert_draft(session, row)
        self._inserted.set()
        await asyncio.wait_for(
            self._release.wait(),
            timeout=_CONCURRENCY_TIMEOUT,
        )
        return inserted


class _LockProbeRepository(_DelegatingOutlineRepository):
    def __init__(self, delegate, *, lock_attempted):
        super().__init__(delegate)
        self._lock_attempted = lock_attempted

    async def lock_project(self, session, project_id):
        self._lock_attempted.set()
        return await self._delegate.lock_project(session, project_id)


async def _clone_row(session, table, where, args, **overrides):
    source = await session.fetchone(
        f"SELECT * FROM {table} WHERE {where}",
        args,
    )
    assert source is not None
    cloned = {**source, **overrides}
    columns = tuple(cloned)
    await session.execute(
        f"""INSERT INTO {table} ({",".join(columns)})
            VALUES ({",".join("%s" for _ in columns)})""",
        tuple(cloned[column] for column in columns),
    )
    return cloned


async def _clone_outline_basis(
    session,
    planning_row,
    binding,
    target_project,
):
    identifiers = {
        "seed": "9b000000-0000-0000-0000-000000000001",
        "seed_revision": "9b000000-0000-0000-0000-000000000002",
        "binding": "9b000000-0000-0000-0000-000000000003",
        "creation": "9b000000-0000-0000-0000-000000000004",
        "style": "9b000000-0000-0000-0000-000000000005",
        "bible": "9b000000-0000-0000-0000-000000000006",
        "planning": "9b000000-0000-0000-0000-000000000007",
    }
    await _clone_row(
        session,
        "projects",
        "id=%s",
        (PROJECT,),
        id=target_project,
        title="Outline isolation project",
    )
    await _clone_row(
        session,
        "creative_seeds",
        "project_id=%s AND id=%s",
        (PROJECT, planning_row["seed_id"]),
        id=identifiers["seed"],
        project_id=target_project,
    )
    await _clone_row(
        session,
        "creative_seed_revisions",
        "project_id=%s AND id=%s",
        (PROJECT, planning_row["seed_revision_id"]),
        id=identifiers["seed_revision"],
        project_id=target_project,
        seed_id=identifiers["seed"],
    )
    await _clone_row(
        session,
        "project_seed_selection_revisions",
        "project_id=%s AND selection_revision=%s",
        (PROJECT, planning_row["selection_revision"]),
        project_id=target_project,
        seed_id=identifiers["seed"],
        seed_revision_id=identifiers["seed_revision"],
    )
    await _clone_row(
        session,
        "project_model_binding_revisions",
        "project_id=%s AND id=%s",
        (PROJECT, binding["binding_revision_id"]),
        id=identifiers["binding"],
        project_id=target_project,
        source_project_id=None,
    )
    await _clone_row(
        session,
        "creation_contracts",
        "project_id=%s AND id=%s",
        (PROJECT, planning_row["creation_contract_id"]),
        id=identifiers["creation"],
        project_id=target_project,
        seed_id=identifiers["seed"],
        seed_revision_id=identifiers["seed_revision"],
        binding_revision_id=identifiers["binding"],
    )
    await _clone_row(
        session,
        "style_contracts",
        "project_id=%s AND id=%s",
        (PROJECT, planning_row["style_contract_id"]),
        id=identifiers["style"],
        project_id=target_project,
        creation_contract_id=identifiers["creation"],
    )
    await _clone_row(
        session,
        "creation_bible_revisions",
        "project_id=%s AND id=%s",
        (PROJECT, planning_row["bible_revision_id"]),
        id=identifiers["bible"],
        project_id=target_project,
        seed_id=identifiers["seed"],
        seed_revision_id=identifiers["seed_revision"],
        creation_contract_id=identifiers["creation"],
        style_contract_id=identifiers["style"],
        binding_revision_id=identifiers["binding"],
    )
    cloned_planning = await _clone_row(
        session,
        "planning_revisions",
        "project_id=%s AND id=%s",
        (PROJECT, planning_row["id"]),
        id=identifiers["planning"],
        project_id=target_project,
        seed_id=identifiers["seed"],
        seed_revision_id=identifiers["seed_revision"],
        creation_contract_id=identifiers["creation"],
        style_contract_id=identifiers["style"],
        bible_revision_id=identifiers["bible"],
    )
    return cloned_planning, identifiers["binding"]


@pytest.mark.asyncio
async def test_real_mysql_outline_draft_attempt_revision_and_confirmation_lifecycle(
    disposable_mysql,
):
    planning_service = await _prepare(disposable_mysql)
    saved_planning = await _save_complete(planning_service)
    planning = await planning_service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            saved_planning.draft_id,
            saved_planning.draft_revision,
            saved_planning.content_hash,
            "confirm-for-outline-repository",
        )
    )
    repository = _repository()
    session = disposable_mysql.session

    selected = await session.fetchone("SELECT DATABASE() AS database_name")
    assert selected["database_name"] == disposable_mysql.database_name
    assert disposable_mysql.database_name.startswith("novel_creator_test_")

    authorities = await repository.read_current_authorities(session, PROJECT)
    assert authorities["planning_revision_id"] == planning.planning_revision_id
    assert authorities["planning_revision"] == planning.revision
    assert authorities["planning_hash"] == planning.content_hash
    assert isinstance(authorities["planning_content"], dict)
    assert authorities["canon_revision"] == 0
    assert authorities["projection_revision"] == 0

    assert await ChapterSessionRepository().read_active_session(
        session, PROJECT
    ) is None
    assert (
        await ChapterSessionRepository().read_max_final_chapter_number(
            session, PROJECT
        )
        is None
    )

    initial_content = {"z": [], "chapterGoal": "先观察封锁线。"}
    initial_hash = canonical_hash(initial_content)
    draft = {
        "id": "9a000000-0000-0000-0000-000000000001",
        "project_id": PROJECT,
        "chapter_num": 1,
        "base_head_revision": 0,
        "draft_revision": 1,
        "planning_revision_id": planning.planning_revision_id,
        "planning_revision": planning.revision,
        "planning_hash": planning.content_hash,
        "canon_revision": authorities["canon_revision"],
        "projection_revision": authorities["projection_revision"],
        "projection_hash": authorities["projection_hash"],
        "content": initial_content,
        "content_hash": initial_hash,
        "status": "active",
        "created_at": NOW + 10,
        "updated_at": NOW + 10,
    }
    assert await repository.insert_draft(session, draft)
    persisted = await repository.read_active_draft(session, PROJECT, 1)
    assert persisted["content"] == initial_content
    assert "content_json" not in persisted

    saved_content = {"chapterGoal": "确认换岗间隔。", "z": ["later"]}
    saved_hash = canonical_hash(saved_content)
    saved_draft = {
        **draft,
        "draft_revision": 2,
        "content": saved_content,
        "content_hash": saved_hash,
        "updated_at": NOW + 11,
    }
    assert await repository.update_draft_cas(
        session,
        saved_draft,
        expected_revision=1,
        expected_hash=initial_hash,
    )
    assert not await repository.update_draft_cas(
        session,
        {**saved_draft, "draft_revision": 3},
        expected_revision=1,
        expected_hash=initial_hash,
    )

    binding = await session.fetchone(
        """SELECT head.binding_revision_id,head.revision AS binding_revision,
                  head.content_hash AS binding_hash,item.provider_id,
                  item.model_name_snapshot
             FROM project_model_binding_heads head
             JOIN project_model_binding_items item
               ON item.binding_revision_id=head.binding_revision_id
              AND item.task_key='planning'
            WHERE head.project_id=%s""",
        (PROJECT,),
    )
    manifest = {"chapterNumber": 1, "safe": True}
    attempt = {
        "id": "9a000000-0000-0000-0000-000000000002",
        "project_id": PROJECT,
        "outline_draft_id": draft["id"],
        "operation_id": "9a000000-0000-0000-0000-000000000003",
        "idempotency_key": "outline-generation-1",
        "request_fingerprint": "d" * 64,
        "binding_revision_id": binding["binding_revision_id"],
        "binding_revision": binding["binding_revision"],
        "binding_hash": binding["binding_hash"],
        "provider_id": binding["provider_id"],
        "model_name_snapshot": binding["model_name_snapshot"],
        "fencing_token": await repository.next_fencing_token(
            session, draft["id"]
        ),
        "lease_expires_at": NOW + 100,
        "input_manifest": manifest,
        "input_manifest_hash": canonical_hash(manifest),
        "created_at": NOW + 12,
        "updated_at": NOW + 12,
    }
    assert await repository.insert_attempt(session, attempt)
    assert (
        await repository.lock_active_attempt(session, draft["id"])
    )["input_manifest"] == manifest

    generated_content = {"chapterGoal": "穿过封锁线。", "z": ["generated"]}
    generated_hash = canonical_hash(generated_content)
    assert await repository.load_result_into_draft(
        session,
        draft["id"],
        2,
        saved_hash,
        attempt["operation_id"],
        attempt["fencing_token"],
        generated_content,
        generated_hash,
        NOW + 13,
    )
    loaded = await repository.read_draft(session, PROJECT, 1, draft["id"])
    completed_attempt = await repository.read_attempt(
        session, PROJECT, attempt["operation_id"]
    )
    assert loaded["draft_revision"] == 3
    assert loaded["content"] == generated_content
    assert loaded["source_attempt_id"] == attempt["id"]
    assert completed_attempt["status"] == "succeeded"
    assert completed_attempt["result_content"] == generated_content
    assert completed_attempt["loaded_outline_draft_revision"] == 3

    revision = {
        "id": "9a000000-0000-0000-0000-000000000004",
        "project_id": PROJECT,
        "chapter_num": 1,
        "revision": 1,
        "parent_revision": 0,
        "planning_revision_id": planning.planning_revision_id,
        "planning_revision": planning.revision,
        "planning_hash": planning.content_hash,
        "canon_revision": authorities["canon_revision"],
        "projection_revision": authorities["projection_revision"],
        "projection_hash": authorities["projection_hash"],
        "content": generated_content,
        "content_hash": generated_hash,
        "created_at": NOW + 14,
    }
    assert await repository.insert_revision(session, revision)
    head = {
        "project_id": PROJECT,
        "chapter_num": 1,
        "revision": 1,
        "outline_revision_id": revision["id"],
        "content_hash": generated_hash,
        "updated_at": NOW + 14,
    }
    assert await repository.advance_head_cas(session, head, 0)
    assert not await repository.advance_head_cas(session, head, 0)
    current = await repository.read_outline_head(session, PROJECT, 1)
    assert current["outline_revision_id"] == revision["id"]
    assert current["content"] == generated_content

    confirmation = {
        "id": "9a000000-0000-0000-0000-000000000005",
        "project_id": PROJECT,
        "chapter_num": 1,
        "chapter_outline_draft_id": draft["id"],
        "draft_revision": 3,
        "draft_hash": generated_hash,
        "expected_head_revision": 0,
        "planning_revision_id": planning.planning_revision_id,
        "planning_revision": planning.revision,
        "planning_hash": planning.content_hash,
        "canon_revision": authorities["canon_revision"],
        "projection_revision": authorities["projection_revision"],
        "projection_hash": authorities["projection_hash"],
        "idempotency_key": "confirm-outline-1",
        "request_fingerprint": "e" * 64,
        "created_at": NOW + 14,
    }
    assert await repository.insert_confirmation_pending(session, confirmation)
    assert await repository.update_draft_cas(
        session,
        {**loaded, "status": "confirmed", "updated_at": NOW + 15},
        expected_revision=3,
        expected_hash=generated_hash,
    )
    assert await repository.finish_confirmation(
        session,
        {
            **confirmation,
            "status": "succeeded",
            "outline_revision_id": revision["id"],
            "result_revision": 1,
            "result_hash": generated_hash,
            "public_error_code": None,
            "completed_at": NOW + 15,
        },
    )
    replay = await repository.find_confirmation(
        session, PROJECT, 1, "confirm-outline-1"
    )
    assert replay["status"] == "succeeded"
    assert replay["outline_revision_id"] == revision["id"]
    history = await repository.list_revisions(session, PROJECT, 1)
    assert tuple(item["revision"] for item in history) == (1,)
    assert history[0]["content"] == generated_content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "extra_args", "terminal_status"),
    (
        ("supersede_attempt", (), "superseded"),
        ("fail_attempt", ("ProviderFailed",), "failed"),
    ),
)
async def test_real_mysql_terminal_attempt_cas_is_project_scoped(
    disposable_mysql,
    method,
    extra_args,
    terminal_status,
):
    planning_service = await _prepare(disposable_mysql)
    saved_planning = await _save_complete(planning_service)
    planning = await planning_service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            saved_planning.draft_id,
            saved_planning.draft_revision,
            saved_planning.content_hash,
            f"confirm-for-{method}-isolation",
        )
    )
    session = disposable_mysql.session
    repository = _repository()
    authorities = await repository.read_current_authorities(session, PROJECT)
    binding = await session.fetchone(
        """SELECT head.binding_revision_id,head.revision AS binding_revision,
                  head.content_hash AS binding_hash,item.provider_id,
                  item.model_name_snapshot
             FROM project_model_binding_heads head
             JOIN project_model_binding_items item
               ON item.binding_revision_id=head.binding_revision_id
              AND item.task_key='planning'
            WHERE head.project_id=%s""",
        (PROJECT,),
    )
    source_planning = await session.fetchone(
        """SELECT * FROM planning_revisions
            WHERE project_id=%s AND id=%s""",
        (PROJECT, planning.planning_revision_id),
    )
    other_project = "9b000000-0000-0000-0000-000000000010"
    other_planning, other_binding = await _clone_outline_basis(
        session,
        source_planning,
        binding,
        other_project,
    )
    shared_operation = "9b000000-0000-0000-0000-000000000011"
    projects = (
        (
            PROJECT,
            "9b000000-0000-0000-0000-000000000012",
            "9b000000-0000-0000-0000-000000000013",
            planning.planning_revision_id,
            planning.revision,
            planning.content_hash,
            binding["binding_revision_id"],
            binding["binding_revision"],
            binding["binding_hash"],
        ),
        (
            other_project,
            "9b000000-0000-0000-0000-000000000014",
            "9b000000-0000-0000-0000-000000000015",
            other_planning["id"],
            other_planning["revision"],
            other_planning["content_hash"],
            other_binding,
            binding["binding_revision"],
            binding["binding_hash"],
        ),
    )
    for index, (
        project_id,
        draft_id,
        attempt_id,
        planning_id,
        planning_revision,
        planning_hash,
        binding_id,
        binding_revision,
        binding_hash,
    ) in enumerate(projects):
        content = {"chapterGoal": f"project-{index}"}
        content_hash = canonical_hash(content)
        assert await repository.insert_draft(
            session,
            {
                "id": draft_id,
                "project_id": project_id,
                "chapter_num": 1,
                "base_head_revision": 0,
                "draft_revision": 1,
                "planning_revision_id": planning_id,
                "planning_revision": planning_revision,
                "planning_hash": planning_hash,
                "canon_revision": authorities["canon_revision"],
                "projection_revision": authorities["projection_revision"],
                "projection_hash": authorities["projection_hash"],
                "content": content,
                "content_hash": content_hash,
                "status": "active",
                "created_at": NOW + 20 + index,
                "updated_at": NOW + 20 + index,
            },
        )
        manifest = {"project": index}
        assert await repository.insert_attempt(
            session,
            {
                "id": attempt_id,
                "project_id": project_id,
                "outline_draft_id": draft_id,
                "operation_id": shared_operation,
                "idempotency_key": f"shared-operation-{index}",
                "request_fingerprint": str(index) * 64,
                "binding_revision_id": binding_id,
                "binding_revision": binding_revision,
                "binding_hash": binding_hash,
                "provider_id": binding["provider_id"],
                "model_name_snapshot": binding["model_name_snapshot"],
                "fencing_token": 1,
                "lease_expires_at": NOW + 100,
                "input_manifest": manifest,
                "input_manifest_hash": canonical_hash(manifest),
                "created_at": NOW + 20 + index,
                "updated_at": NOW + 20 + index,
            },
        )

    terminal = getattr(repository, method)
    changed = await terminal(
        session,
        PROJECT,
        shared_operation,
        1,
        *extra_args,
    )
    rows = await session.fetchall(
        """SELECT project_id,status,active_slot,failure_code
             FROM chapter_outline_generation_attempts
            WHERE operation_id=%s ORDER BY project_id""",
        (shared_operation,),
    )
    by_project = {row["project_id"]: row for row in rows}

    assert by_project[PROJECT]["status"] == terminal_status
    assert by_project[PROJECT]["active_slot"] is None
    assert by_project[other_project] == {
        "project_id": other_project,
        "status": "pending",
        "active_slot": 1,
        "failure_code": None,
    }
    assert changed is True
