from __future__ import annotations

import asyncio

import pytest

from backend.repositories.projects import ProjectRepository
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.repositories.planning import PlanningRepository
from backend.services.chapter_outlines import (
    ChapterOutlineService,
    ConfirmChapterOutlineDraft,
    CreateChapterOutlineDraft,
    SaveChapterOutlineDraft,
)
from backend.services.chapter_sessions import (
    ChapterSessionService,
    CreateChapterSession,
)
from backend.services.planning import ConfirmPlanningDraft
from backend.services.project_lifecycle import ProjectLifecycleService
from backend.tests.integration.test_chapter_outline_lifecycle import (
    NOW,
    PROJECT,
    _editable_outline,
    _repository,
)
from backend.tests.integration.test_planning_aggregate_lifecycle import (
    _prepare,
    _save_complete,
)
from backend.tests.support.disposable_mysql import transaction_factory_for


pytestmark = pytest.mark.mysql
_TIMEOUT = 5


class _FakeOutlineGateway:
    def __init__(self, output, *, hook=None):
        self.output = output
        self.hook = hook
        self.calls = []

    async def generate(self, *, provider, model_name, manifest):
        self.calls.append((dict(provider), model_name, manifest))
        if self.hook is not None:
            await self.hook()
        return self.output


class _BlockingOutlineGateway(_FakeOutlineGateway):
    def __init__(self, output):
        super().__init__(output)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        self.entered.set()
        await self.release.wait()
        return self.output


async def _finish_generation(task, gateway):
    gateway.release.set()
    return await asyncio.wait_for(task, timeout=_TIMEOUT)


async def _prepared_outline(disposable_mysql):
    planning_service = await _prepare(disposable_mysql)
    saved_planning = await _save_complete(planning_service)
    planning = await planning_service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            saved_planning.draft_id,
            saved_planning.draft_revision,
            saved_planning.content_hash,
            "confirm-for-outline-generation",
        )
    )
    transaction = transaction_factory_for(
        disposable_mysql.connection_config
    )
    manual = ChapterOutlineService(
        _repository(),
        ChapterSessionRepository(),
        planning_repository=PlanningRepository(),
        transaction_factory=transaction,
        id_factory=iter(
            f"9e000000-0000-0000-0000-{number:012d}"
            for number in range(1, 30)
        ).__next__,
        clock=lambda: NOW + 700,
    )
    draft = await manual.create_draft(
        CreateChapterOutlineDraft(PROJECT, 1)
    )
    return planning, draft, manual, transaction


@pytest.mark.asyncio
async def test_real_mysql_generation_reserves_and_join_loads_exact_outline_draft(
    disposable_mysql,
):
    from backend.services.chapter_outline_generation import (
        ChapterOutlineGenerationService,
        GenerateChapterOutline,
    )

    planning, draft, _manual, transaction = await _prepared_outline(
        disposable_mysql
    )
    gateway = _FakeOutlineGateway(_editable_outline(planning.content))
    ids = iter(
        (
            "9e000000-0000-0000-0000-000000000002",
            "9e000000-0000-0000-0000-000000000003",
        )
    )
    service = ChapterOutlineGenerationService(
        _repository(),
        ChapterSessionRepository(),
        planning_repository=PlanningRepository(),
        provider_gateway=gateway,
        transaction_factory=transaction,
        id_factory=ids.__next__,
        clock=lambda: NOW + 701,
    )

    result = await service.generate(
        GenerateChapterOutline(
            PROJECT,
            1,
            draft.draft_id,
            draft.draft_revision,
            draft.content_hash,
            "real-outline-generation",
            "强化人物选择。",
        )
    )

    assert result.status == "succeeded"
    assert result.loaded is True
    assert result.loaded_draft_revision == draft.draft_revision + 1
    assert result.model.model_name == "test-model"
    assert len(gateway.calls) == 1
    persisted = await disposable_mysql.session.fetchone(
        """SELECT * FROM chapter_outline_generation_attempts
            WHERE project_id=%s AND operation_id=%s""",
        (PROJECT, result.operation_id),
    )
    loaded = await disposable_mysql.session.fetchone(
        "SELECT * FROM chapter_outline_drafts WHERE id=%s",
        (draft.draft_id,),
    )
    assert persisted["status"] == "succeeded"
    assert persisted["loaded_outline_draft_revision"] == (
        draft.draft_revision + 1
    )
    assert loaded["source_attempt_id"] == persisted["id"]
    observed = await service.get_operation_by_key(
        PROJECT, "real-outline-generation"
    )
    assert observed == result


@pytest.mark.asyncio
async def test_real_mysql_author_save_during_generation_terminally_supersedes(
    disposable_mysql,
):
    from backend.services.chapter_outline_generation import (
        ChapterOutlineGenerationService,
        GenerateChapterOutline,
    )

    planning, draft, manual, transaction = await _prepared_outline(
        disposable_mysql
    )

    async def author_save():
        await manual.save_draft(
            SaveChapterOutlineDraft(
                PROJECT,
                1,
                draft.draft_id,
                draft.draft_revision,
                draft.content_hash,
                _editable_outline(planning.content),
            )
        )

    gateway = _FakeOutlineGateway(
        _editable_outline(planning.content),
        hook=author_save,
    )
    ids = iter(
        (
            "9f000000-0000-0000-0000-000000000002",
            "9f000000-0000-0000-0000-000000000003",
        )
    )
    service = ChapterOutlineGenerationService(
        _repository(),
        ChapterSessionRepository(),
        planning_repository=PlanningRepository(),
        provider_gateway=gateway,
        transaction_factory=transaction,
        id_factory=ids.__next__,
        clock=lambda: NOW + 702,
    )

    result = await service.generate(
        GenerateChapterOutline(
            PROJECT,
            1,
            draft.draft_id,
            draft.draft_revision,
            draft.content_hash,
            "outline-save-drift",
            "",
        )
    )

    assert result.status == "superseded"
    assert result.loaded is False
    assert result.loaded_draft_revision is None
    persisted = await disposable_mysql.session.fetchone(
        """SELECT status,result_content_json,
                  loaded_outline_draft_revision
             FROM chapter_outline_generation_attempts
            WHERE project_id=%s AND operation_id=%s""",
        (PROJECT, result.operation_id),
    )
    assert persisted == {
        "status": "superseded",
        "result_content_json": None,
        "loaded_outline_draft_revision": None,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("same_key", (True, False))
async def test_real_mysql_same_and_different_key_reservations_do_not_deadlock(
    disposable_mysql,
    same_key,
):
    from backend.services.chapter_outline_generation import (
        ChapterOutlineGenerationConflict,
        ChapterOutlineGenerationService,
        GenerateChapterOutline,
    )

    planning, draft, _manual, transaction = await _prepared_outline(
        disposable_mysql
    )
    gateway = _BlockingOutlineGateway(_editable_outline(planning.content))
    ids = iter(
        f"a1000000-0000-0000-0000-{number:012d}"
        for number in range(1, 10)
    )
    service = ChapterOutlineGenerationService(
        _repository(),
        ChapterSessionRepository(),
        planning_repository=PlanningRepository(),
        provider_gateway=gateway,
        transaction_factory=transaction,
        id_factory=ids.__next__,
        clock=lambda: NOW + 710,
    )
    command = GenerateChapterOutline(
        PROJECT,
        1,
        draft.draft_id,
        draft.draft_revision,
        draft.content_hash,
        "same-key" if same_key else "first-key",
        "",
    )
    original = asyncio.create_task(service.generate(command))
    try:
        await asyncio.wait_for(gateway.entered.wait(), timeout=_TIMEOUT)
        competing = GenerateChapterOutline(
            PROJECT,
            1,
            draft.draft_id,
            draft.draft_revision,
            draft.content_hash,
            command.idempotency_key if same_key else "different-key",
            "",
        )
        if same_key:
            replay = await asyncio.wait_for(
                service.generate(competing), timeout=_TIMEOUT
            )
            assert replay.status == "pending"
        else:
            with pytest.raises(ChapterOutlineGenerationConflict):
                await asyncio.wait_for(
                    service.generate(competing), timeout=_TIMEOUT
                )
    finally:
        terminal = await _finish_generation(original, gateway)

    assert terminal.status == "succeeded"
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_real_mysql_publish_and_confirm_follow_one_lock_order(
    disposable_mysql,
):
    from backend.services.chapter_outline_generation import (
        ChapterOutlineGenerationService,
        GenerateChapterOutline,
    )

    planning, draft, manual, transaction = await _prepared_outline(
        disposable_mysql
    )
    saved = await manual.save_draft(
        SaveChapterOutlineDraft(
            PROJECT,
            1,
            draft.draft_id,
            draft.draft_revision,
            draft.content_hash,
            _editable_outline(planning.content),
        )
    )
    gateway = _BlockingOutlineGateway(_editable_outline(planning.content))
    ids = iter(
        f"a2000000-0000-0000-0000-{number:012d}"
        for number in range(1, 10)
    )
    generation = ChapterOutlineGenerationService(
        _repository(),
        ChapterSessionRepository(),
        planning_repository=PlanningRepository(),
        provider_gateway=gateway,
        transaction_factory=transaction,
        id_factory=ids.__next__,
        clock=lambda: NOW + 720,
    )
    command = GenerateChapterOutline(
        PROJECT,
        1,
        saved.draft_id,
        saved.draft_revision,
        saved.content_hash,
        "publish-confirm-order",
        "",
    )
    pending = asyncio.create_task(generation.generate(command))
    try:
        await asyncio.wait_for(gateway.entered.wait(), timeout=_TIMEOUT)
        confirmed = await asyncio.wait_for(
            manual.confirm_draft(
                ConfirmChapterOutlineDraft(
                    PROJECT,
                    1,
                    saved.draft_id,
                    saved.draft_revision,
                    saved.content_hash,
                    0,
                    "confirm-during-generation",
                )
            ),
            timeout=_TIMEOUT,
        )
    finally:
        generated = await _finish_generation(pending, gateway)

    assert confirmed.revision == 1
    assert generated.status == "superseded"


@pytest.mark.asyncio
async def test_real_mysql_publish_and_session_create_follow_one_lock_order(
    disposable_mysql,
):
    from backend.services.chapter_outline_generation import (
        ChapterOutlineGenerationService,
        GenerateChapterOutline,
    )

    planning, first, manual, transaction = await _prepared_outline(
        disposable_mysql
    )
    saved = await manual.save_draft(
        SaveChapterOutlineDraft(
            PROJECT,
            1,
            first.draft_id,
            first.draft_revision,
            first.content_hash,
            _editable_outline(planning.content),
        )
    )
    confirmed = await manual.confirm_draft(
        ConfirmChapterOutlineDraft(
            PROJECT,
            1,
            saved.draft_id,
            saved.draft_revision,
            saved.content_hash,
            0,
            "confirm-before-session-race",
        )
    )
    second = await manual.create_draft(
        CreateChapterOutlineDraft(PROJECT, 1)
    )
    gateway = _BlockingOutlineGateway(_editable_outline(planning.content))
    ids = iter(
        f"a3000000-0000-0000-0000-{number:012d}"
        for number in range(1, 10)
    )
    generation = ChapterOutlineGenerationService(
        _repository(),
        ChapterSessionRepository(),
        planning_repository=PlanningRepository(),
        provider_gateway=gateway,
        transaction_factory=transaction,
        id_factory=ids.__next__,
        clock=lambda: NOW + 730,
    )
    pending = asyncio.create_task(
        generation.generate(
            GenerateChapterOutline(
                PROJECT,
                1,
                second.draft_id,
                second.draft_revision,
                second.content_hash,
                "publish-session-order",
                "",
            )
        )
    )
    try:
        await asyncio.wait_for(gateway.entered.wait(), timeout=_TIMEOUT)
        created = await asyncio.wait_for(
            ChapterSessionService(
                ChapterSessionRepository(),
                transaction_factory=transaction,
            ).create_session(
                CreateChapterSession(
                    PROJECT,
                    1,
                    planning.revision,
                    planning.content_hash,
                    confirmed.revision,
                    confirmed.content_hash,
                    0,
                )
            ),
            timeout=_TIMEOUT,
        )
    finally:
        generated = await _finish_generation(pending, gateway)

    assert created.session.chapter_num == 1
    assert generated.status == "superseded"


@pytest.mark.asyncio
async def test_real_mysql_publish_and_archive_follow_one_lock_order(
    disposable_mysql,
):
    from backend.services.chapter_outline_generation import (
        ChapterOutlineGenerationService,
        GenerateChapterOutline,
    )

    planning, draft, _manual, transaction = await _prepared_outline(
        disposable_mysql
    )
    gateway = _BlockingOutlineGateway(_editable_outline(planning.content))
    ids = iter(
        f"a4000000-0000-0000-0000-{number:012d}"
        for number in range(1, 10)
    )
    generation = ChapterOutlineGenerationService(
        _repository(),
        ChapterSessionRepository(),
        planning_repository=PlanningRepository(),
        provider_gateway=gateway,
        transaction_factory=transaction,
        id_factory=ids.__next__,
        clock=lambda: NOW + 740,
    )
    pending = asyncio.create_task(
        generation.generate(
            GenerateChapterOutline(
                PROJECT,
                1,
                draft.draft_id,
                draft.draft_revision,
                draft.content_hash,
                "publish-archive-order",
                "",
            )
        )
    )
    try:
        await asyncio.wait_for(gateway.entered.wait(), timeout=_TIMEOUT)
        project = await disposable_mysql.session.fetchone(
            "SELECT lifecycle_revision FROM projects WHERE id=%s",
            (PROJECT,),
        )
        archived = await asyncio.wait_for(
            ProjectLifecycleService(
                ProjectRepository(clock=lambda: NOW + 741),
                transaction,
            ).archive(PROJECT, int(project["lifecycle_revision"])),
            timeout=_TIMEOUT,
        )
    finally:
        generated = await _finish_generation(pending, gateway)

    assert archived.archived_at is not None
    assert generated.status == "superseded"
