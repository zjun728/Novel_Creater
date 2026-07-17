from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from backend import http_errors
from backend.domain.model_bindings import TASK_KEYS
from backend.domain.seeds import SeedPayload
from backend.gateways.chapter_draft_provider import ChapterDraftProviderError
from backend.repositories.canon import CanonRepository
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.repositories.contracts import ContractRepository
from backend.repositories.model_bindings import ModelBindingRepository
from backend.repositories.planning import PlanningRepository
from backend.repositories.projects import ProjectRepository
from backend.repositories.seeds import SeedRepository
from backend.repositories.story_engines import StoryEngineRepository
from backend.services.canon import CanonService, CommitCanonRevision
from backend.services.chapter_draft_generation import (
    ChapterDraftGenerationFailed,
    ChapterDraftGenerationService,
    GenerateWorkingDraft,
)
from backend.services.chapter_sessions import (
    ChapterSessionService,
    CreateChapterSession,
    SaveDraftCandidate,
    SaveWorkingDraft,
)
from backend.services.contracts import (
    ConfirmContracts,
    ContractService,
    SaveContractDraft,
)
from backend.services.model_bindings import ModelBindingService
from backend.services.planning import CreateInitialPlan, PlanningService
from backend.services.project_lifecycle import (
    CreateProject,
    ProjectLifecycleService,
    ProjectResult,
)
from backend.services.projections import build_projection_bundle
from backend.services.seeds import (
    CreateSeed,
    DeleteSeed,
    EditSeed,
    SeedService,
    SelectSeed,
)
from backend.services.story_engines import (
    CreateManualStoryEngineBatch,
    ReserveStoryEngineBatch,
    StoryEngineBatchResult,
    StoryEngineService,
)
from backend.tests.integration.test_contract_drafts import (
    BATCH as CONTRACT_BATCH,
    BINDING as CONTRACT_BINDING,
    PROJECT as WRITE_FENCE_PROJECT,
    PROVIDER as CONTRACT_PROVIDER,
    _bootstrap as bootstrap_contract_fixture,
    _draft as contract_draft,
)
from backend.tests.support.disposable_mysql import transaction_factory_for
from backend.tests.support.story_engine_fakes import CountingGateway, three_options


pytestmark = pytest.mark.mysql


PROJECT_ID = "60000000-0000-0000-0000-000000000001"


def _project(
    project_id: str = PROJECT_ID, title: str = "Archive integration"
) -> CreateProject:
    return CreateProject(id=project_id, title=title)


async def _foundation_snapshot(session, project_id: str = PROJECT_ID) -> dict:
    return {
        "canon": await session.fetchall(
            """SELECT revision_number,content_hash
                 FROM canon_revisions WHERE project_id=%s
                 ORDER BY revision_number""",
            (project_id,),
        ),
        "projection": await session.fetchall(
            """SELECT canon_revision_number,projection_revision_number,content_hash
                 FROM projection_heads WHERE project_id=%s""",
            (project_id,),
        ),
        "contract": await session.fetchall(
            """SELECT revision,creation_hash,style_hash
                 FROM project_contract_heads WHERE project_id=%s""",
            (project_id,),
        ),
        "binding_revisions": await session.fetchall(
            """SELECT revision,content_hash,source_project_id
                 FROM project_model_binding_revisions WHERE project_id=%s
                 ORDER BY revision""",
            (project_id,),
        ),
        "binding_head": await session.fetchall(
            """SELECT revision,content_hash
                 FROM project_model_binding_heads WHERE project_id=%s""",
            (project_id,),
        ),
        "binding_items": await session.fetchall(
            """SELECT i.task_key,i.resolution_status,i.item_hash
                 FROM project_model_binding_items i
                 JOIN project_model_binding_revisions r
                   ON r.id=i.binding_revision_id
                 WHERE r.project_id=%s ORDER BY i.task_key""",
            (project_id,),
        ),
    }


def _seed_payload(title: str) -> SeedPayload:
    return SeedPayload(
        title=title,
        genre="history",
        logline="A test-only logline",
        protagonist="Tester",
        desire="Preserve history",
        coreConflict="Archived boundary",
        worldPressure="Concurrent changes",
        openingHook="A project is archived",
        differentiation="Immutable integration fixture",
    )


async def _seed_snapshot(session, project_id: str = PROJECT_ID) -> dict:
    return {
        "identities": await session.fetchall(
            """SELECT id,status FROM creative_seeds
                 WHERE project_id=%s ORDER BY id""",
            (project_id,),
        ),
        "revisions": await session.fetchall(
            """SELECT r.id,r.revision,r.content_hash
                 FROM creative_seed_revisions r
                 JOIN creative_seeds s ON s.id=r.seed_id
                 WHERE s.project_id=%s ORDER BY r.seed_id,r.revision""",
            (project_id,),
        ),
        "heads": await session.fetchall(
            """SELECT h.seed_id,h.revision,h.content_hash
                 FROM creative_seed_heads h
                 JOIN creative_seeds s ON s.id=h.seed_id
                 WHERE s.project_id=%s ORDER BY h.seed_id""",
            (project_id,),
        ),
        "selection": await session.fetchall(
            """SELECT seed_id,seed_revision_id,seed_hash,selection_revision
                 FROM project_selected_seeds WHERE project_id=%s""",
            (project_id,),
        ),
    }


def _services(disposable_mysql):
    transaction = transaction_factory_for(disposable_mysql.connection_config)

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    bindings = ModelBindingService(
        ModelBindingRepository(),
        transaction_factory=transaction,
        connection_factory=read_connection,
    )
    projects = ProjectLifecycleService(
        ProjectRepository(),
        transaction,
        read_connection,
        model_binding_service=bindings,
    )
    return projects, bindings, transaction, read_connection


async def _wait(event: asyncio.Event) -> None:
    await asyncio.wait_for(event.wait(), timeout=10)


class _PairStartGate:
    def __init__(self):
        self.arrivals = 0
        self.both_arrived = asyncio.Event()
        self.release = asyncio.Event()
        self.connection_ids = set()

    async def arrive(self, session) -> None:
        self.connection_ids.add(id(session.raw))
        self.arrivals += 1
        if self.arrivals == 2:
            self.both_arrived.set()
        await _wait(self.release)


class _PairStartRepository(ProjectRepository):
    def __init__(self, gate: _PairStartGate):
        super().__init__()
        self.gate = gate

    async def lock_any(self, session, project_id):
        await self.gate.arrive(session)
        return await super().lock_any(session, project_id)


async def _run_lifecycle_pair(
    disposable_mysql,
    operation,
):
    transaction = transaction_factory_for(disposable_mysql.connection_config)
    gate = _PairStartGate()
    services = [
        ProjectLifecycleService(_PairStartRepository(gate), transaction),
        ProjectLifecycleService(_PairStartRepository(gate), transaction),
    ]
    tasks = [
        asyncio.create_task(operation(service))
        for service in services
    ]
    try:
        await _wait(gate.both_arrived)
        assert len(gate.connection_ids) == 2
        gate.release.set()
        return await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=10,
        )
    finally:
        gate.release.set()
        for task in tasks:
            if not task.done():
                task.cancel()


async def _prepare_reservable_story_engine(disposable_mysql):
    projects, _, transaction, read_connection = _services(disposable_mysql)
    await projects.create(_project())
    seeds = SeedService(
        SeedRepository(),
        transaction_factory=transaction,
        connection_factory=read_connection,
        id_factory=iter(
            f"74000000-0000-0000-0000-{number:012d}"
            for number in range(20)
        ).__next__,
    )
    seed = await seeds.create(
        CreateSeed(project_id=PROJECT_ID, payload=_seed_payload("Reservable"))
    )
    await seeds.select(
        SelectSeed(
            project_id=PROJECT_ID,
            seed_id=seed.id,
            expected_seed_revision=1,
            expected_selection_revision=0,
        )
    )
    now = 1_720_000_000_000
    await disposable_mysql.session.execute(
        """INSERT INTO provider_profiles
           (id,name,provider_type,model_name,base_url,api_key,enabled,sort_order,
            stream,max_context_tokens,max_output_tokens,temperature,top_p,
            supports_json,supports_streaming,notes,thinking,lifecycle_status,
            deleted_at,created_at,updated_at)
           VALUES ('provider-seed','Seed Provider','openai','seed-model',
                   'https://test.invalid','test-only-key',1,0,0,10000,1000,
                   0.2,1.0,1,0,'test only',NULL,'active',NULL,%s,%s)""",
        (now, now),
    )
    binding = await disposable_mysql.session.fetchone(
        """SELECT binding_revision_id
             FROM project_model_binding_heads WHERE project_id=%s""",
        (PROJECT_ID,),
    )
    await disposable_mysql.session.execute(
        """UPDATE project_model_binding_items
           SET resolution_status='bound',
               provider_id='provider-seed',
               provider_name_snapshot='Seed Provider',
               model_name_snapshot='seed-model'
           WHERE binding_revision_id=%s AND task_key='seed'""",
        (binding["binding_revision_id"],),
    )
    return projects, transaction


@pytest.mark.asyncio
async def test_archive_and_restore_preserve_workflow_and_foundations(
    disposable_mysql,
):
    projects, _, _, _ = _services(disposable_mysql)
    await projects.create(_project())
    before = await _foundation_snapshot(disposable_mysql.session)

    archived = await projects.archive(PROJECT_ID, 0)

    assert archived.status == "drafting"
    assert archived.archived_at is not None
    assert archived.lifecycle_revision == 1
    assert await projects.list_active() == []
    assert [row.id for row in await projects.list_archived()] == [PROJECT_ID]
    with pytest.raises(http_errors.ProjectArchived):
        await projects.get(PROJECT_ID)
    assert (
        await projects.get(PROJECT_ID, include_archived=True)
    ).lifecycle_revision == 1
    with pytest.raises(http_errors.ProjectArchived):
        await projects.archive(PROJECT_ID, 1)
    assert await _foundation_snapshot(disposable_mysql.session) == before

    restored = await projects.restore(PROJECT_ID, 1)

    assert restored.status == "drafting"
    assert restored.archived_at is None
    assert restored.lifecycle_revision == 2
    assert [row.id for row in await projects.list_active()] == [PROJECT_ID]
    assert await projects.list_archived() == []
    assert await _foundation_snapshot(disposable_mysql.session) == before


@pytest.mark.asyncio
async def test_lifecycle_cas_and_archived_only_permanent_delete(
    disposable_mysql,
):
    projects, _, _, _ = _services(disposable_mysql)
    await projects.create(_project())

    with pytest.raises(http_errors.ProjectLifecycleConflict):
        await projects.permanently_delete(PROJECT_ID, 0)
    await projects.archive(PROJECT_ID, 0)
    with pytest.raises(http_errors.ProjectLifecycleConflict):
        await projects.restore(PROJECT_ID, 0)
    await projects.restore(PROJECT_ID, 1)
    with pytest.raises(http_errors.ProjectLifecycleConflict):
        await projects.archive(PROJECT_ID, 1)
    await projects.archive(PROJECT_ID, 2)
    with pytest.raises(http_errors.ProjectLifecycleConflict):
        await projects.permanently_delete(PROJECT_ID, 2)

    await projects.permanently_delete(PROJECT_ID, 3)

    assert await disposable_mysql.session.fetchone(
        "SELECT * FROM projects WHERE id=%s", (PROJECT_ID,)
    ) is None
    after_delete = await _foundation_snapshot(disposable_mysql.session)
    assert all(not rows for rows in after_delete.values()), after_delete


@pytest.mark.asyncio
async def test_same_title_rename_is_a_successful_mysql_no_op(disposable_mysql):
    projects, _, _, _ = _services(disposable_mysql)
    await projects.create(_project(title="Unchanged"))

    result = await projects.rename(PROJECT_ID, "Unchanged")

    assert result.title == "Unchanged"
    row = await disposable_mysql.session.fetchone(
        """SELECT title,archived_at,lifecycle_revision
             FROM projects WHERE id=%s""",
        (PROJECT_ID,),
    )
    assert row == {
        "title": "Unchanged",
        "archived_at": None,
        "lifecycle_revision": 0,
    }


@pytest.mark.asyncio
async def test_real_rename_lock_then_archive_keeps_new_title_and_archives(
    disposable_mysql,
):
    projects, _, transaction, _ = _services(disposable_mysql)
    await projects.create(_project(title="Original"))
    rename_locked = asyncio.Event()
    archive_attempted = asyncio.Event()
    release_rename = asyncio.Event()
    connection_ids = set()

    class RenameFirstRepository(ProjectRepository):
        async def lock_active_project(self, session, project_id):
            row = await super().lock_active_project(session, project_id)
            connection_ids.add(id(session.raw))
            rename_locked.set()
            await _wait(release_rename)
            return row

    class ArchiveSecondRepository(ProjectRepository):
        async def lock_any(self, session, project_id):
            connection_ids.add(id(session.raw))
            archive_attempted.set()
            return await super().lock_any(session, project_id)

    rename_service = ProjectLifecycleService(
        RenameFirstRepository(), transaction
    )
    archive_service = ProjectLifecycleService(
        ArchiveSecondRepository(), transaction
    )
    rename_task = asyncio.create_task(
        rename_service.rename(PROJECT_ID, "Renamed")
    )
    archive_task = None
    try:
        await _wait(rename_locked)
        archive_task = asyncio.create_task(
            archive_service.archive(PROJECT_ID, 0)
        )
        await _wait(archive_attempted)
        assert len(connection_ids) == 2
        release_rename.set()
        rename_result, archive_result = await asyncio.wait_for(
            asyncio.gather(rename_task, archive_task),
            timeout=10,
        )
    finally:
        release_rename.set()
        for task in (rename_task, archive_task):
            if task is not None and not task.done():
                task.cancel()

    assert rename_result.title == "Renamed"
    assert archive_result.lifecycle_revision == 1
    row = await disposable_mysql.session.fetchone(
        """SELECT title,archived_at,lifecycle_revision
             FROM projects WHERE id=%s""",
        (PROJECT_ID,),
    )
    assert row["title"] == "Renamed"
    assert row["archived_at"] is not None
    assert row["lifecycle_revision"] == 1


@pytest.mark.asyncio
async def test_real_archive_lock_then_rename_returns_project_archived(
    disposable_mysql,
):
    projects, _, transaction, _ = _services(disposable_mysql)
    await projects.create(_project(title="Original"))
    archive_locked = asyncio.Event()
    rename_attempted = asyncio.Event()
    release_archive = asyncio.Event()
    connection_ids = set()

    class ArchiveFirstRepository(ProjectRepository):
        async def lock_any(self, session, project_id):
            row = await super().lock_any(session, project_id)
            connection_ids.add(id(session.raw))
            archive_locked.set()
            await _wait(release_archive)
            return row

    class RenameSecondRepository(ProjectRepository):
        async def lock_active_project(self, session, project_id):
            connection_ids.add(id(session.raw))
            rename_attempted.set()
            return await super().lock_active_project(session, project_id)

    archive_service = ProjectLifecycleService(
        ArchiveFirstRepository(), transaction
    )
    rename_service = ProjectLifecycleService(
        RenameSecondRepository(), transaction
    )
    archive_task = asyncio.create_task(
        archive_service.archive(PROJECT_ID, 0)
    )
    rename_task = None
    try:
        await _wait(archive_locked)
        rename_task = asyncio.create_task(
            rename_service.rename(PROJECT_ID, "Must not land")
        )
        await _wait(rename_attempted)
        assert len(connection_ids) == 2
        release_archive.set()
        archive_result, rename_result = await asyncio.wait_for(
            asyncio.gather(
                archive_task,
                rename_task,
                return_exceptions=True,
            ),
            timeout=10,
        )
    finally:
        release_archive.set()
        for task in (archive_task, rename_task):
            if task is not None and not task.done():
                task.cancel()

    assert isinstance(archive_result, ProjectResult)
    assert isinstance(rename_result, http_errors.ProjectArchived)
    row = await disposable_mysql.session.fetchone(
        """SELECT title,archived_at,lifecycle_revision
             FROM projects WHERE id=%s""",
        (PROJECT_ID,),
    )
    assert row["title"] == "Original"
    assert row["archived_at"] is not None
    assert row["lifecycle_revision"] == 1


@pytest.mark.asyncio
async def test_real_same_revision_double_lifecycle_commands_have_one_winner(
    disposable_mysql,
):
    projects, _, _, _ = _services(disposable_mysql)
    await projects.create(_project())

    archive_results = await _run_lifecycle_pair(
        disposable_mysql,
        lambda service: service.archive(PROJECT_ID, 0),
    )
    assert sum(isinstance(result, ProjectResult) for result in archive_results) == 1
    assert sum(
        isinstance(result, http_errors.ProjectArchived)
        for result in archive_results
    ) == 1
    archived = await disposable_mysql.session.fetchone(
        """SELECT archived_at,lifecycle_revision
             FROM projects WHERE id=%s""",
        (PROJECT_ID,),
    )
    assert archived["archived_at"] is not None
    assert archived["lifecycle_revision"] == 1

    restore_results = await _run_lifecycle_pair(
        disposable_mysql,
        lambda service: service.restore(PROJECT_ID, 1),
    )
    assert sum(isinstance(result, ProjectResult) for result in restore_results) == 1
    assert sum(
        isinstance(result, http_errors.ProjectLifecycleConflict)
        for result in restore_results
    ) == 1
    restored = await disposable_mysql.session.fetchone(
        """SELECT archived_at,lifecycle_revision
             FROM projects WHERE id=%s""",
        (PROJECT_ID,),
    )
    assert restored == {"archived_at": None, "lifecycle_revision": 2}

    await projects.archive(PROJECT_ID, 2)
    delete_results = await _run_lifecycle_pair(
        disposable_mysql,
        lambda service: service.permanently_delete(PROJECT_ID, 3),
    )
    assert sum(result is None for result in delete_results) == 1
    assert sum(
        isinstance(result, http_errors.ProjectNotFound)
        for result in delete_results
    ) == 1
    assert await disposable_mysql.session.fetchone(
        "SELECT * FROM projects WHERE id=%s", (PROJECT_ID,)
    ) is None


@pytest.mark.asyncio
async def test_real_reservation_lock_then_archive_returns_project_busy(
    disposable_mysql,
):
    _, transaction = await _prepare_reservable_story_engine(disposable_mysql)
    reservation_locked = asyncio.Event()
    archive_attempted = asyncio.Event()
    release_reservation = asyncio.Event()
    connection_ids = set()

    class ReservationFirstRepository(StoryEngineRepository):
        async def lock_project(self, session, project_id):
            row = await super().lock_project(session, project_id)
            connection_ids.add(id(session.raw))
            reservation_locked.set()
            await _wait(release_reservation)
            return row

    class ArchiveSecondRepository(ProjectRepository):
        async def lock_any(self, session, project_id):
            connection_ids.add(id(session.raw))
            archive_attempted.set()
            return await super().lock_any(session, project_id)

    gateway = CountingGateway()
    story_service = StoryEngineService(
        ReservationFirstRepository(),
        transaction_factory=transaction,
        connection_factory=transaction,
        provider_gateway=gateway,
    )
    archive_service = ProjectLifecycleService(
        ArchiveSecondRepository(), transaction
    )
    reservation_task = asyncio.create_task(
        story_service.reserve_provider(
            ReserveStoryEngineBatch(PROJECT_ID, "reservation-first")
        )
    )
    archive_task = None
    try:
        await _wait(reservation_locked)
        archive_task = asyncio.create_task(
            archive_service.archive(PROJECT_ID, 0)
        )
        await _wait(archive_attempted)
        assert len(connection_ids) == 2
        release_reservation.set()
        reservation_result, archive_result = await asyncio.wait_for(
            asyncio.gather(
                reservation_task,
                archive_task,
                return_exceptions=True,
            ),
            timeout=10,
        )
    finally:
        release_reservation.set()
        for task in (reservation_task, archive_task):
            if task is not None and not task.done():
                task.cancel()

    assert isinstance(reservation_result, StoryEngineBatchResult)
    assert reservation_result.status == "reserved"
    assert isinstance(archive_result, http_errors.ProjectBusy)
    assert gateway.calls == 0
    project = await disposable_mysql.session.fetchone(
        """SELECT archived_at,lifecycle_revision
             FROM projects WHERE id=%s""",
        (PROJECT_ID,),
    )
    assert project == {"archived_at": None, "lifecycle_revision": 0}


@pytest.mark.asyncio
async def test_real_archive_lock_then_reservation_cannot_create_busy_operation(
    disposable_mysql,
):
    _, transaction = await _prepare_reservable_story_engine(disposable_mysql)
    archive_locked = asyncio.Event()
    reservation_attempted = asyncio.Event()
    release_archive = asyncio.Event()
    connection_ids = set()

    class ArchiveFirstRepository(ProjectRepository):
        async def lock_any(self, session, project_id):
            row = await super().lock_any(session, project_id)
            connection_ids.add(id(session.raw))
            archive_locked.set()
            await _wait(release_archive)
            return row

    class ReservationSecondRepository(StoryEngineRepository):
        async def lock_project(self, session, project_id):
            connection_ids.add(id(session.raw))
            reservation_attempted.set()
            return await super().lock_project(session, project_id)

    gateway = CountingGateway()
    archive_service = ProjectLifecycleService(
        ArchiveFirstRepository(), transaction
    )
    story_service = StoryEngineService(
        ReservationSecondRepository(),
        transaction_factory=transaction,
        connection_factory=transaction,
        provider_gateway=gateway,
    )
    archive_task = asyncio.create_task(
        archive_service.archive(PROJECT_ID, 0)
    )
    reservation_task = None
    try:
        await _wait(archive_locked)
        reservation_task = asyncio.create_task(
            story_service.reserve_provider(
                ReserveStoryEngineBatch(PROJECT_ID, "archive-first")
            )
        )
        await _wait(reservation_attempted)
        assert len(connection_ids) == 2
        release_archive.set()
        archive_result, reservation_result = await asyncio.wait_for(
            asyncio.gather(
                archive_task,
                reservation_task,
                return_exceptions=True,
            ),
            timeout=10,
        )
    finally:
        release_archive.set()
        for task in (archive_task, reservation_task):
            if task is not None and not task.done():
                task.cancel()

    assert isinstance(archive_result, ProjectResult)
    assert isinstance(reservation_result, http_errors.ProjectArchived)
    assert gateway.calls == 0
    project = await disposable_mysql.session.fetchone(
        """SELECT archived_at,lifecycle_revision
             FROM projects WHERE id=%s""",
        (PROJECT_ID,),
    )
    assert project["archived_at"] is not None
    assert project["lifecycle_revision"] == 1
    busy_count = await disposable_mysql.session.fetchone(
        """SELECT COUNT(*) AS count FROM story_engine_batches
           WHERE project_id=%s
             AND status IN ('reserved','running','outcome_unknown')""",
        (PROJECT_ID,),
    )
    assert busy_count == {"count": 0}


@pytest.mark.asyncio
async def test_archived_project_blocks_seed_and_binding_resources_and_inheritance(
    disposable_mysql,
):
    projects, bindings, transaction, read_connection = _services(disposable_mysql)
    seeds = SeedService(
        SeedRepository(),
        transaction_factory=transaction,
        connection_factory=read_connection,
        id_factory=(
            f"73000000-0000-0000-0000-{n:012d}" for n in range(50)
        ).__next__,
        clock=iter(range(9_000, 10_000)).__next__,
    )
    await projects.create(_project())
    seed = await seeds.create(
        CreateSeed(project_id=PROJECT_ID, payload=_seed_payload("Original"))
    )
    selected = await seeds.select(
        SelectSeed(
            project_id=PROJECT_ID,
            seed_id=seed.id,
            expected_seed_revision=1,
            expected_selection_revision=0,
        )
    )
    foundation_before = await _foundation_snapshot(disposable_mysql.session)
    seeds_before = await _seed_snapshot(disposable_mysql.session)
    await projects.archive(PROJECT_ID, 0)

    async def capture(awaitable):
        try:
            return await awaitable
        except BaseException as exc:
            return exc

    seed_results = [
        await capture(
            seeds.create(
                CreateSeed(project_id=PROJECT_ID, payload=_seed_payload("New"))
            )
        ),
        await capture(
            seeds.edit(
                EditSeed(
                    project_id=PROJECT_ID,
                    seed_id=seed.id,
                    payload=_seed_payload("Edited"),
                    expected_seed_revision=1,
                    expected_selection_revision=selected.selection_revision,
                )
            )
        ),
        await capture(
            seeds.select(
                SelectSeed(
                    project_id=PROJECT_ID,
                    seed_id=seed.id,
                    expected_seed_revision=1,
                    expected_selection_revision=selected.selection_revision,
                )
            )
        ),
        await capture(
            seeds.delete(
                DeleteSeed(
                    project_id=PROJECT_ID,
                    seed_id=seed.id,
                    expected_seed_revision=1,
                    expected_selection_revision=selected.selection_revision,
                )
            )
        ),
        await capture(seeds.list(PROJECT_ID)),
        await capture(seeds.get_selected(PROJECT_ID)),
    ]
    binding_results = [
        await capture(bindings.get_current(PROJECT_ID)),
        await capture(bindings.get_status(PROJECT_ID)),
        await capture(
            bindings.replace_all(
                PROJECT_ID, 1, {task_key: None for task_key in TASK_KEYS}
            )
        ),
    ]

    assert all(
        isinstance(result, http_errors.ProjectArchived)
        for result in seed_results[:4]
    )
    assert all(
        isinstance(result, http_errors.SeedNotFound)
        for result in seed_results[4:]
    )
    assert all(
        isinstance(result, http_errors.BindingNotFound)
        for result in binding_results[:2]
    )
    assert isinstance(binding_results[2], http_errors.ProjectArchived)
    assert await _seed_snapshot(disposable_mysql.session) == seeds_before
    assert await _foundation_snapshot(disposable_mysql.session) == foundation_before

    next_project_id = "60000000-0000-0000-0000-000000000002"
    await projects.create(_project(next_project_id, "No archived inheritance"))
    inherited = await bindings.get_current(next_project_id)
    assert inherited.source_project_id is None


class _GeneratedDraftGateway:
    def __init__(self):
        self.calls = 0

    async def generate(self, **_kwargs):
        self.calls += 1
        return "测试生成正文"


async def _prepare_generation_race(disposable_mysql):
    facts = await bootstrap_contract_fixture(disposable_mysql.session)
    now = 1_900_000_000_050
    empty_hash = build_projection_bundle(0, ()).content_hash
    await disposable_mysql.session.execute(
        """INSERT INTO canon_revisions
           (id,project_id,revision_number,parent_revision_number,idempotency_key,
            source_type,source_id,content_hash,created_at)
           VALUES ('8e000000-0000-0000-0000-000000000001',%s,0,0,%s,
                   'bootstrap',NULL,%s,%s)""",
        (WRITE_FENCE_PROJECT, "0" * 64, empty_hash, now),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO projection_heads
           (project_id,canon_revision_number,projection_revision_number,
            content_hash,updated_at)
           VALUES (%s,0,0,%s,%s)""",
        (WRITE_FENCE_PROJECT, empty_hash, now),
    )
    transaction = transaction_factory_for(disposable_mysql.connection_config)

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    contract_service = ContractService(
        ContractRepository(),
        transaction_factory=transaction,
        connection_factory=read_connection,
        id_factory=iter(
            f"8e000000-0000-0000-0001-{number:012d}"
            for number in range(100, 500)
        ).__next__,
        clock=lambda: now,
    )
    saved_contract = await contract_service.save_draft(
        SaveContractDraft(
            WRITE_FENCE_PROJECT,
            0,
            contract_draft(facts),
        )
    )
    confirmed = await contract_service.confirm(
        ConfirmContracts(
            WRITE_FENCE_PROJECT,
            "generation-race-confirm",
            saved_contract.draft_version,
            saved_contract.content_hash,
        )
    )
    planning_service = PlanningService(
        PlanningRepository(),
        transaction_factory=transaction,
        connection_factory=read_connection,
    )
    plan = await planning_service.create_initial_plan(
        CreateInitialPlan(
            WRITE_FENCE_PROJECT,
            confirmed.revision,
            "generation-race-plan",
        )
    )
    chapter_service = ChapterSessionService(
        ChapterSessionRepository(),
        transaction_factory=transaction,
        connection_factory=read_connection,
    )
    workspace = await chapter_service.create_session(
        CreateChapterSession(
            WRITE_FENCE_PROJECT,
            plan.active_block.revision,
            0,
        )
    )
    workspace = await chapter_service.save_working_draft(
        SaveWorkingDraft(
            WRITE_FENCE_PROJECT,
            workspace.session.id,
            workspace.working_draft.revision,
            "归档竞争前的作者正文。",
        )
    )
    return transaction, workspace


class _BlockingGenerationGateway:
    def __init__(self, *, outcome):
        self.outcome = outcome
        self.calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(self, **_kwargs):
        self.calls += 1
        self.entered.set()
        await _wait(self.release)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class _GenerationConnectionRepository(ChapterSessionRepository):
    def __init__(self, connection_ids):
        super().__init__()
        self.connection_ids = connection_ids

    async def lock_project(self, session, project_id):
        self.connection_ids["generation"] = id(session.raw)
        return await super().lock_project(session, project_id)


class _ArchiveAttemptRepository(ProjectRepository):
    def __init__(self, attempted, connection_ids):
        super().__init__()
        self.attempted = attempted
        self.connection_ids = connection_ids

    async def lock_any(self, session, project_id):
        self.connection_ids["archive"] = id(session.raw)
        self.attempted.set()
        return await super().lock_any(session, project_id)


async def _run_generation_archive_race(
    disposable_mysql,
    *,
    provider_outcome,
):
    transaction, workspace = await _prepare_generation_race(disposable_mysql)
    connection_ids = {}
    archive_attempted = asyncio.Event()
    archive_completed = asyncio.Event()
    gateway = _BlockingGenerationGateway(outcome=provider_outcome)
    generation_service = ChapterDraftGenerationService(
        _GenerationConnectionRepository(connection_ids),
        provider_gateway=gateway,
        transaction_factory=transaction,
    )
    archive_service = ProjectLifecycleService(
        _ArchiveAttemptRepository(archive_attempted, connection_ids),
        transaction,
    )
    command = GenerateWorkingDraft(
        WRITE_FENCE_PROJECT,
        workspace.session.id,
        workspace.working_draft.revision,
    )

    async def archive_with_completion():
        try:
            return await archive_service.archive(WRITE_FENCE_PROJECT, 0)
        finally:
            archive_completed.set()

    generation_task = asyncio.create_task(
        generation_service.generate_working_draft(command)
    )
    archive_task = None
    try:
        await _wait(gateway.entered)
        archive_task = asyncio.create_task(archive_with_completion())
        await _wait(archive_attempted)
        assert set(connection_ids) == {"generation", "archive"}
        assert len(set(connection_ids.values())) == 2
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(archive_completed.wait(), timeout=0.1)
        assert not archive_task.done()
        gateway.release.set()
        generation_result, archive_result = await asyncio.wait_for(
            asyncio.gather(
                generation_task,
                archive_task,
                return_exceptions=True,
            ),
            timeout=10,
        )
    finally:
        gateway.release.set()
        pending = [
            task for task in (generation_task, archive_task)
            if task is not None and not task.done()
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    return {
        "workspace": workspace,
        "gateway": gateway,
        "generation_result": generation_result,
        "archive_result": archive_result,
    }


@pytest.mark.asyncio
async def test_real_generation_lock_then_archive_commits_draft_before_archive(
    disposable_mysql,
):
    generated = "模型完成的测试正文。"
    race = await _run_generation_archive_race(
        disposable_mysql,
        provider_outcome=generated,
    )

    assert race["gateway"].calls == 1
    assert race["generation_result"].working_draft.content == generated
    assert isinstance(race["archive_result"], ProjectResult)
    draft = await disposable_mysql.session.fetchone(
        """SELECT revision,content FROM working_drafts
           WHERE chapter_session_id=%s""",
        (race["workspace"].session.id,),
    )
    project = await disposable_mysql.session.fetchone(
        """SELECT archived_at,lifecycle_revision FROM projects WHERE id=%s""",
        (WRITE_FENCE_PROJECT,),
    )
    assert draft == {
        "revision": race["workspace"].working_draft.revision + 1,
        "content": generated,
    }
    assert project["archived_at"] is not None
    assert project["lifecycle_revision"] == 1


@pytest.mark.asyncio
async def test_real_generation_failure_rolls_back_then_archive_succeeds(
    disposable_mysql,
):
    race = await _run_generation_archive_race(
        disposable_mysql,
        provider_outcome=ChapterDraftProviderError("fake provider failure"),
    )

    assert race["gateway"].calls == 1
    assert isinstance(
        race["generation_result"],
        ChapterDraftGenerationFailed,
    )
    assert isinstance(race["archive_result"], ProjectResult)
    draft = await disposable_mysql.session.fetchone(
        """SELECT revision,content FROM working_drafts
           WHERE chapter_session_id=%s""",
        (race["workspace"].session.id,),
    )
    project = await disposable_mysql.session.fetchone(
        """SELECT archived_at,lifecycle_revision FROM projects WHERE id=%s""",
        (WRITE_FENCE_PROJECT,),
    )
    assert draft == {
        "revision": race["workspace"].working_draft.revision,
        "content": race["workspace"].working_draft.content,
    }
    assert project["archived_at"] is not None
    assert project["lifecycle_revision"] == 1


@pytest.mark.asyncio
async def test_archived_project_rejects_every_known_write_and_restore_reopens_writes(
    disposable_mysql,
):
    facts = await bootstrap_contract_fixture(disposable_mysql.session)
    now = 1_900_000_000_050
    empty_hash = build_projection_bundle(0, ()).content_hash
    await disposable_mysql.session.execute(
        """INSERT INTO canon_revisions
           (id,project_id,revision_number,parent_revision_number,idempotency_key,
            source_type,source_id,content_hash,created_at)
           VALUES ('8f000000-0000-0000-0000-000000000001',%s,0,0,%s,
                   'bootstrap',NULL,%s,%s)""",
        (WRITE_FENCE_PROJECT, empty_hash, empty_hash, now),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO projection_heads
           (project_id,canon_revision_number,projection_revision_number,
            content_hash,updated_at)
           VALUES (%s,0,0,%s,%s)""",
        (WRITE_FENCE_PROJECT, empty_hash, now),
    )
    transaction = transaction_factory_for(disposable_mysql.connection_config)

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    project_service = ProjectLifecycleService(
        ProjectRepository(), transaction, read_connection
    )
    seed_service = SeedService(
        SeedRepository(),
        transaction_factory=transaction,
        connection_factory=read_connection,
        id_factory=iter(
            f"8f000000-0000-0000-0000-{number:012d}"
            for number in range(100, 200)
        ).__next__,
    )
    binding_service = ModelBindingService(
        ModelBindingRepository(),
        transaction_factory=transaction,
        connection_factory=read_connection,
    )
    contract_service = ContractService(
        ContractRepository(),
        transaction_factory=transaction,
        connection_factory=read_connection,
        id_factory=iter(
            f"8f000000-0000-0000-0001-{number:012d}"
            for number in range(100, 500)
        ).__next__,
        clock=lambda: now,
    )
    saved_contract = await contract_service.save_draft(
        SaveContractDraft(
            WRITE_FENCE_PROJECT,
            0,
            contract_draft(facts),
        )
    )
    confirmed = await contract_service.confirm(
        ConfirmContracts(
            WRITE_FENCE_PROJECT,
            "write-fence-confirm",
            saved_contract.draft_version,
            saved_contract.content_hash,
        )
    )
    planning_service = PlanningService(
        PlanningRepository(),
        transaction_factory=transaction,
        connection_factory=read_connection,
    )
    plan = await planning_service.create_initial_plan(
        CreateInitialPlan(
            WRITE_FENCE_PROJECT,
            confirmed.revision,
            "write-fence-plan",
        )
    )
    chapter_repository = ChapterSessionRepository()
    chapter_service = ChapterSessionService(
        chapter_repository,
        transaction_factory=transaction,
        connection_factory=read_connection,
    )
    workspace = await chapter_service.create_session(
        CreateChapterSession(
            WRITE_FENCE_PROJECT,
            plan.active_block.revision,
            0,
        )
    )
    await chapter_service.save_working_draft(
        SaveWorkingDraft(
            WRITE_FENCE_PROJECT,
            workspace.session.id,
            workspace.working_draft.revision,
            "归档前的有效工作稿。",
        )
    )
    generated_gateway = _GeneratedDraftGateway()
    generation_service = ChapterDraftGenerationService(
        chapter_repository,
        provider_gateway=generated_gateway,
        transaction_factory=transaction,
    )
    story_service = StoryEngineService(
        StoryEngineRepository(),
        transaction_factory=transaction,
        connection_factory=read_connection,
        provider_gateway=CountingGateway(),
    )
    canon_service = CanonService(
        CanonRepository(),
        transaction_factory=transaction,
        id_factory=lambda: "8f000000-0000-0000-0002-000000000001",
        clock=lambda: now,
    )

    await project_service.archive(WRITE_FENCE_PROJECT, 0)
    await disposable_mysql.session.execute(
        """UPDATE story_engine_batches
              SET source_type='provider',binding_revision_id=%s,binding_hash=%s,
                  provider_id=%s,model_name_snapshot='test-model',
                  status='running',
                  attempt_id='8f000000-0000-0000-0003-000000000001',
                  attempt_started_at=%s,lease_expires_at=%s,finished_at=NULL
            WHERE id=%s""",
        (
            CONTRACT_BINDING,
            facts["binding_hash"],
            CONTRACT_PROVIDER,
            now,
            now + 60_000,
            CONTRACT_BATCH,
        ),
    )

    async def capture(awaitable):
        try:
            return await awaitable
        except BaseException as exc:
            return exc

    results = {
        "seed": await capture(
            seed_service.create(
                CreateSeed(
                    project_id=WRITE_FENCE_PROJECT,
                    payload=_seed_payload("Blocked seed"),
                )
            )
        ),
        "binding": await capture(
            binding_service.replace_all(
                WRITE_FENCE_PROJECT,
                1,
                {task_key: None for task_key in TASK_KEYS},
            )
        ),
        "contract": await capture(
            contract_service.save_draft(
                SaveContractDraft(
                    WRITE_FENCE_PROJECT,
                    0,
                    contract_draft(facts),
                )
            )
        ),
        "planning": await capture(
            planning_service.create_initial_plan(
                CreateInitialPlan(
                    WRITE_FENCE_PROJECT,
                    confirmed.revision,
                    "blocked-plan",
                )
            )
        ),
        "story-engine": await capture(
            story_service.create_manual(
                CreateManualStoryEngineBatch(
                    WRITE_FENCE_PROJECT,
                    "blocked-manual",
                    three_options(),
                )
            )
        ),
        "chapter-session": await capture(
            chapter_service.create_session(
                CreateChapterSession(
                    WRITE_FENCE_PROJECT,
                    plan.active_block.revision,
                    0,
                )
            )
        ),
    }
    current_draft = await disposable_mysql.session.fetchone(
        "SELECT revision FROM working_drafts WHERE chapter_session_id=%s",
        (workspace.session.id,),
    )
    results["working-draft"] = await capture(
        chapter_service.save_working_draft(
            SaveWorkingDraft(
                WRITE_FENCE_PROJECT,
                workspace.session.id,
                int(current_draft["revision"]),
                "不能落入归档项目。",
            )
        )
    )
    current_draft = await disposable_mysql.session.fetchone(
        "SELECT revision FROM working_drafts WHERE chapter_session_id=%s",
        (workspace.session.id,),
    )
    results["candidate"] = await capture(
        chapter_service.save_candidate(
            SaveDraftCandidate(
                WRITE_FENCE_PROJECT,
                workspace.session.id,
                int(current_draft["revision"]),
            )
        )
    )
    results["generated-draft"] = await capture(
        generation_service.generate_working_draft(
            GenerateWorkingDraft(
                WRITE_FENCE_PROJECT,
                workspace.session.id,
                int(current_draft["revision"]),
            )
        )
    )
    results["outcome-unknown"] = await capture(
        story_service.mark_outcome_unknown(
            WRITE_FENCE_PROJECT,
            CONTRACT_BATCH,
            "8f000000-0000-0000-0003-000000000001",
        )
    )
    results["canon"] = await capture(
        canon_service.commit(
            CommitCanonRevision(
                project_id=WRITE_FENCE_PROJECT,
                expected_head=0,
                idempotency_key="f" * 64,
                source_type="manual_test",
                source_id=None,
                entities=(),
                aliases=(),
                events=(),
            )
        )
    )

    assert all(
        isinstance(result, http_errors.ProjectArchived)
        for result in results.values()
    ), {
        name: type(result).__name__
        for name, result in results.items()
    }
    assert generated_gateway.calls == 0

    await disposable_mysql.session.execute(
        """UPDATE story_engine_batches
              SET status='failed',public_error_code='provider_failed',
                  raw_response_hash=NULL,finished_at=%s
            WHERE id=%s""",
        (now + 1, CONTRACT_BATCH),
    )
    restored = await project_service.restore(WRITE_FENCE_PROJECT, 1)
    created_after_restore = await seed_service.create(
        CreateSeed(
            project_id=WRITE_FENCE_PROJECT,
            payload=_seed_payload("Restored seed"),
        )
    )

    assert restored.archived_at is None
    assert created_after_restore.project_id == WRITE_FENCE_PROJECT
