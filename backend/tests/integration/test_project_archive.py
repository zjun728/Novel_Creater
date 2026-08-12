from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from backend import http_errors
from backend.domain.bibles import BiblePayload
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.model_bindings import TASK_KEYS
from backend.domain.planning import (
    DraftPlanningAggregate,
    normalize_planning_aggregate,
)
from backend.domain.seeds import SeedPayload
from backend.repositories.canon import CanonRepository
from backend.repositories.contracts import ContractRepository
from backend.repositories.model_bindings import ModelBindingRepository
from backend.repositories.planning import PlanningRepository
from backend.repositories.projects import ProjectRepository
from backend.repositories.seeds import SeedRepository
from backend.repositories.story_engines import StoryEngineRepository
from backend.services.bibles import BIBLE_POLICY_VERSION
from backend.services.canon import CanonService, CommitCanonRevision
from backend.services.contracts import (
    ConfirmContracts,
    ContractService,
    SaveContractDraft,
)
from backend.services.model_bindings import ModelBindingService
from backend.services.project_lifecycle import (
    CreateProject,
    ProjectLifecycleService,
    ProjectResult,
)
from backend.services.planning_generation import (
    PLANNING_GENERATION_LEASE_MS,
    GeneratePlanningDraft,
    PlanningGenerationService,
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


async def _insert_confirmed_bible(
    session,
    confirmed,
    *,
    bible_id: str,
    now: int,
    content: dict | None = None,
) -> None:
    if content is None:
        content = {
            "schemaVersion": "creation-bible-v1",
            "projectId": confirmed.project_id,
            "contractRevision": confirmed.revision,
        }
    content_hash = canonical_hash(content)
    await session.execute(
        """INSERT INTO creation_bible_revisions
           (id,project_id,revision,selection_revision,seed_id,seed_revision_id,
            seed_hash,contract_revision,creation_contract_id,creation_hash,
            style_contract_id,style_hash,binding_revision_id,binding_hash,
            policy_version,content_json,content_hash,confirmed_at)
           VALUES (%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                   'test-bible-v1',%s,%s,%s)""",
        (
            bible_id,
            confirmed.project_id,
            confirmed.selection_revision,
            confirmed.seed_ref.id,
            confirmed.seed_ref.revision_id,
            confirmed.seed_ref.content_hash,
            confirmed.revision,
            confirmed.creation_contract_id,
            confirmed.creation_hash,
            confirmed.style_contract_id,
            confirmed.style_hash,
            confirmed.binding_ref.id,
            confirmed.binding_ref.content_hash,
            canonical_json(content),
            content_hash,
            now,
        ),
    )
    await session.execute(
        """INSERT INTO project_bible_heads
           (project_id,revision,bible_revision_id,content_hash,updated_at)
           VALUES (%s,1,%s,%s,%s)""",
        (confirmed.project_id, bible_id, content_hash, now),
    )


def _canonical_planning():
    return normalize_planning_aggregate(
        DraftPlanningAggregate.model_validate(
            {
                "activeStoryBlockRef": "block",
                "volumes": [
                    {
                        "clientNodeKey": "volume",
                        "lifecycle": "active",
                        "order": 1,
                        "title": "第一卷",
                        "coreChange": "主角建立第一个可靠据点。",
                        "mainPressure": "追兵逼近。",
                        "ensembleFocus": ["主角", "同伴"],
                        "forbiddenEvents": ["不可提前揭示幕后人"],
                    }
                ],
                "plots": [
                    {
                        "clientNodeKey": "plot",
                        "lifecycle": "active",
                        "order": 1,
                        "title": "立足主线",
                        "plotType": "main",
                        "storyQuestion": "主角如何活下来？",
                        "futureDirection": "从逃亡转为主动布局。",
                        "expectedPayoff": "建立据点。",
                        "relatedCharacters": ["主角"],
                    }
                ],
                "storyBlocks": [
                    {
                        "clientNodeKey": "block",
                        "lifecycle": "active",
                        "order": 1,
                        "title": "夜渡封锁线",
                        "volumeRef": "volume",
                        "plotRefs": ["plot"],
                        "entrySituation": "二人被困。",
                        "blockGoal": "穿过封锁线。",
                        "mainPressure": "追兵压缩路线。",
                        "expectedChange": "二人建立信任。",
                        "openQuestions": ["内应是谁"],
                        "involvedCharacters": ["主角", "同伴"],
                        "stages": [
                            {
                                "clientNodeKey": "stage",
                                "lifecycle": "active",
                                "order": 1,
                                "title": "寻找缺口",
                                "purpose": "确认封锁薄弱处。",
                                "dramaticQuestion": "能否在暴露前找到缺口？",
                                "sceneTasks": [
                                    {
                                        "clientNodeKey": "task",
                                        "lifecycle": "active",
                                        "order": 1,
                                        "task": "观察换岗。",
                                        "completionEvidence": "取得换岗间隔。",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ),
        previous_confirmed=None,
        previous_draft=None,
        id_factory=iter(
            f"8d000000-0000-0000-0000-{number:012d}"
            for number in range(100, 105)
        ).__next__,
    )


async def _planning_basis(session, project_id: str):
    return await session.fetchone(
        """SELECT selected.selection_revision,selected.seed_id,
                  selected.seed_revision_id,selected.seed_hash,
                  contract.revision AS contract_revision,
                  contract.creation_contract_id,contract.creation_hash,
                  contract.style_contract_id,contract.style_hash,
                  bible.revision AS bible_revision,
                  bible.bible_revision_id,bible.content_hash AS bible_hash
             FROM project_selected_seeds selected
             JOIN project_contract_heads contract
               ON contract.project_id=selected.project_id
             JOIN project_bible_heads bible
               ON bible.project_id=selected.project_id
            WHERE selected.project_id=%s""",
        (project_id,),
    )


async def _insert_confirmed_planning(session, project_id: str, now: int):
    planning = _canonical_planning()
    content_json = canonical_json(
        planning.model_dump(mode="json", by_alias=True)
    )
    basis = await _planning_basis(session, project_id)
    assert basis is not None
    parameters = (
        project_id,
        basis["selection_revision"],
        basis["seed_id"],
        basis["seed_revision_id"],
        basis["seed_hash"],
        basis["contract_revision"],
        basis["creation_contract_id"],
        basis["creation_hash"],
        basis["style_contract_id"],
        basis["style_hash"],
        basis["bible_revision"],
        basis["bible_revision_id"],
        basis["bible_hash"],
        content_json,
        planning.content_hash,
        now,
    )
    await session.execute(
        """INSERT INTO planning_drafts
           (id,project_id,active_slot,base_head_revision,draft_revision,
            selection_revision,seed_id,seed_revision_id,seed_hash,
            contract_revision,creation_contract_id,creation_hash,
            style_contract_id,style_hash,bible_revision,bible_revision_id,
            bible_hash,content_json,content_hash,source_attempt_id,status,
            created_at,updated_at)
           VALUES ('8d000000-0000-0000-0001-000000000001',%s,NULL,0,1,
                   %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,
                   'confirmed',%s,%s)""",
        (*parameters, now),
    )
    await session.execute(
        """INSERT INTO planning_revisions
           (id,project_id,revision,parent_revision,selection_revision,seed_id,
            seed_revision_id,seed_hash,contract_revision,creation_contract_id,
            creation_hash,style_contract_id,style_hash,bible_revision,
            bible_revision_id,bible_hash,content_json,content_hash,created_at)
           VALUES ('8d000000-0000-0000-0001-000000000002',%s,1,0,%s,%s,%s,
                   %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        parameters,
    )
    assert await session.execute(
        """INSERT INTO project_planning_heads
           (project_id,revision,planning_revision_id,content_hash,updated_at)
           VALUES (%s,1,'8d000000-0000-0000-0001-000000000002',%s,%s)""",
        (project_id, planning.content_hash, now),
    ) == 1
    return planning


async def _write_current_planning_draft(
    transaction,
    project_id: str,
    now: int,
    *,
    after_lock=None,
    fail_after_lock: bool = False,
):
    planning = _canonical_planning()
    async with transaction() as session:
        repository = ProjectRepository()
        project = await repository.lock_active_project(session, project_id)
        if project is None:
            if await repository.lock_any(session, project_id) is not None:
                raise http_errors.ProjectArchived()
            raise http_errors.ProjectNotFound()
        if after_lock is not None:
            await after_lock(session)
        if fail_after_lock:
            raise RuntimeError("controlled planning write failure")
        basis = await _planning_basis(session, project_id)
        assert basis is not None
        await session.execute(
            """INSERT INTO planning_drafts
               (id,project_id,active_slot,base_head_revision,draft_revision,
                selection_revision,seed_id,seed_revision_id,seed_hash,
                contract_revision,creation_contract_id,creation_hash,
                style_contract_id,style_hash,bible_revision,bible_revision_id,
                bible_hash,content_json,content_hash,source_attempt_id,status,
                created_at,updated_at)
               VALUES ('8d000000-0000-0000-0001-000000000003',%s,1,1,2,
                       %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,
                       'active',%s,%s)""",
            (
                project_id,
                basis["selection_revision"],
                basis["seed_id"],
                basis["seed_revision_id"],
                basis["seed_hash"],
                basis["contract_revision"],
                basis["creation_contract_id"],
                basis["creation_hash"],
                basis["style_contract_id"],
                basis["style_hash"],
                basis["bible_revision"],
                basis["bible_revision_id"],
                basis["bible_hash"],
                canonical_json(
                    planning.model_dump(mode="json", by_alias=True)
                ),
                planning.content_hash,
                now,
                now,
            ),
        )
    return planning


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
async def test_preparation_snapshot_tracks_archive_and_restore_without_model_secrets(
    disposable_mysql,
):
    projects, _, transaction, read_connection = _services(disposable_mysql)
    await projects.create(_project())
    preparation_service = ProjectLifecycleService(
        ProjectRepository(),
        transaction,
        read_connection,
        contract_service=ContractService(
            ContractRepository(),
            transaction_factory=transaction,
            connection_factory=read_connection,
        ),
    )

    active = await preparation_service.preparation(PROJECT_ID)
    assert active.lifecycle == "active"
    assert active.active_selection == "missing"
    assert active.next_action == "select_seed"
    assert active.planning == "missing"
    assert active.planning_operation is None
    assert len(active.model_tasks) == len(TASK_KEYS)
    assert all(item.readiness == "not_ready" for item in active.model_tasks)

    await projects.archive(PROJECT_ID, 0)
    archived = await preparation_service.preparation(PROJECT_ID)
    assert archived.lifecycle == "archived"
    assert archived.next_action == "archived_read_only"
    assert archived.target_path is None
    assert archived.planning == "missing"
    assert archived.planning_operation is None
    assert archived.capabilities.model_dump() == {
        "view_preparation": True,
        "edit_contract": False,
        "edit_bible": False,
        "generate_bible": False,
    }

    await projects.restore(PROJECT_ID, 1)
    restored = await preparation_service.preparation(PROJECT_ID)
    assert restored.lifecycle == "active"
    assert restored.next_action == "select_seed"
    public = restored.model_dump(mode="json", by_alias=True)
    serialized = str(public).lower()
    for forbidden in ("provider", "baseurl", "apikey", "password", "dsn"):
        assert forbidden not in serialized


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
async def test_archived_project_keeps_seed_reads_but_blocks_writes_and_inheritance(
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
    listed, selected_read = seed_results[4:]
    assert [item.id for item in listed] == [seed.id]
    assert selected_read.active_selection is not None
    assert selected_read.active_selection.seed_id == seed.id
    assert (
        selected_read.active_selection.selection_revision
        == selected.selection_revision
    )
    assert all(
        result.project_id == PROJECT_ID
        for result in binding_results[:2]
    )
    assert (
        binding_results[0].revision,
        binding_results[0].content_hash,
    ) == (
        binding_results[1].revision,
        binding_results[1].content_hash,
    )
    assert isinstance(binding_results[2], http_errors.ProjectArchived)
    assert await _seed_snapshot(disposable_mysql.session) == seeds_before
    assert await _foundation_snapshot(disposable_mysql.session) == foundation_before

    next_project_id = "60000000-0000-0000-0000-000000000002"
    await projects.create(_project(next_project_id, "No archived inheritance"))
    inherited = await bindings.get_current(next_project_id)
    assert inherited.source_project_id is None


def _planning_generation_bible() -> dict:
    payload = BiblePayload.model_validate(
        {
            "premiseAndPromise": (
                "一个被追捕的记录者必须保存真相，同时承担公开真相的关系代价。"
            ),
            "worldRules": (
                {
                    "id": "world-rule-1",
                    "text": "任何超常力量都必须留下可追踪且不可撤销的代价。",
                },
            ),
            "powerOrProgressionSystem": (
                "成长依靠选择、训练和有限资源，不允许无依据跃升。"
            ),
            "protagonist": "主角谨慎、重视证据，并会承担自己选择的后果。",
            "coreCast": (
                {
                    "id": "cast-1",
                    "text": "同伴拥有独立目标，不是主角的功能性附庸。",
                },
            ),
            "factions": (
                {
                    "id": "faction-1",
                    "text": "地方势力围绕安全、秩序与真相形成竞争。",
                },
            ),
            "longTermConflicts": (
                {
                    "id": "conflict-1",
                    "text": "保存真相与维持眼前秩序的冲突会逐步升级。",
                },
            ),
            "relationshipDynamics": (
                {
                    "id": "relationship-1",
                    "text": "信任只能通过共同选择和公开代价逐步建立。",
                },
            ),
            "toneAndNarrativeBoundaries": (
                "保持克制，让人物行动承担情绪和选择的后果。"
            ),
            "continuityGuardrails": (
                {
                    "id": "guardrail-1",
                    "text": "已经付出的代价不能被无条件撤销。",
                },
            ),
            "openDesignQuestions": (
                {
                    "id": "question-1",
                    "text": "第一阶段需要决定哪段关系最先承受代价。",
                },
            ),
        },
        strict=True,
    )
    return payload.model_dump(mode="json")


async def _prepare_planning_race(
    disposable_mysql,
    *,
    generation_basis: bool = False,
):
    facts = await bootstrap_contract_fixture(disposable_mysql.session)
    now = 1_900_000_000_050
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
    await _insert_confirmed_bible(
        disposable_mysql.session,
        confirmed,
        bible_id="8e000000-0000-0000-0002-000000000001",
        now=now,
        content=(
            _planning_generation_bible()
            if generation_basis
            else None
        ),
    )
    planning = await _insert_confirmed_planning(
        disposable_mysql.session,
        WRITE_FENCE_PROJECT,
        now,
    )
    return transaction, planning, now


def _preparation_service(transaction, read_connection):
    return ProjectLifecycleService(
        ProjectRepository(),
        transaction,
        read_connection,
        contract_service=ContractService(
            ContractRepository(),
            transaction_factory=transaction,
            connection_factory=read_connection,
        ),
    )


async def _make_preparation_bible_current(session):
    await session.execute(
        """UPDATE creation_bible_revisions
              SET policy_version=%s
            WHERE project_id=%s""",
        (BIBLE_POLICY_VERSION, WRITE_FENCE_PROJECT),
    )


async def _insert_pending_planning_attempt(
    session,
    *,
    draft_id,
    attempt_id,
    operation_id,
    idempotency_key,
    fencing_token,
    now,
):
    binding = await session.fetchone(
        """SELECT head.binding_revision_id,head.revision AS binding_revision,
                  head.content_hash AS binding_hash,item.provider_id,
                  item.model_name_snapshot
             FROM project_model_binding_heads head
             JOIN project_model_binding_items item
               ON item.binding_revision_id=head.binding_revision_id
              AND item.task_key='planning'
            WHERE head.project_id=%s""",
        (WRITE_FENCE_PROJECT,),
    )
    assert binding is not None
    manifest = {"schemaVersion": "planning-generation-v1"}
    await session.execute(
        """INSERT INTO planning_generation_attempts
           (id,project_id,draft_id,operation_id,active_slot,idempotency_key,
            request_fingerprint,binding_revision_id,binding_revision,binding_hash,
            provider_id,model_name_snapshot,fencing_token,lease_expires_at,
            input_manifest_json,input_manifest_hash,result_content_json,
            result_content_hash,loaded_draft_revision,loaded_at,failure_code,
            status,created_at,updated_at)
           VALUES (%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                   NULL,NULL,NULL,NULL,NULL,'pending',%s,%s)""",
        (
            attempt_id,
            WRITE_FENCE_PROJECT,
            draft_id,
            operation_id,
            idempotency_key,
            "f" * 64,
            binding["binding_revision_id"],
            binding["binding_revision"],
            binding["binding_hash"],
            binding["provider_id"],
            binding["model_name_snapshot"],
            fencing_token,
            now + 60_000,
            canonical_json(manifest),
            canonical_hash(manifest),
            now,
            now,
        ),
    )


async def _insert_valid_chapter_session(session, *, now, chapter_num=7):
    planning = await session.fetchone(
        """SELECT id,revision,content_hash
             FROM planning_revisions
            WHERE project_id=%s AND revision=1""",
        (WRITE_FENCE_PROJECT,),
    )
    assert planning is not None
    outline_id = "8f000000-0000-0000-0001-000000000001"
    outline = {"chapter": chapter_num}
    outline_hash = canonical_hash(outline)
    await session.execute(
        """INSERT INTO chapter_outline_revisions
           (id,project_id,chapter_num,revision,parent_revision,
            planning_revision_id,planning_revision,planning_hash,
            canon_revision,projection_revision,projection_hash,
            content_json,content_hash,created_at)
           VALUES (%s,%s,%s,1,0,%s,%s,%s,0,0,%s,%s,%s,%s)""",
        (
            outline_id,
            WRITE_FENCE_PROJECT,
            chapter_num,
            planning["id"],
            planning["revision"],
            planning["content_hash"],
            "0" * 64,
            canonical_json(outline),
            outline_hash,
            now,
        ),
    )
    session_id = "8f000000-0000-0000-0002-000000000001"
    await session.execute(
        """INSERT INTO chapter_sessions
           (id,project_id,planning_revision_id,planning_revision,planning_hash,
            story_block_id,story_block_revision,story_block_hash,
            chapter_outline_revision_id,chapter_outline_revision,
            chapter_outline_hash,chapter_num,expected_canon_revision,status,
            created_at,finalized_at)
           VALUES (%s,%s,%s,%s,%s,%s,1,%s,%s,1,%s,%s,0,'drafting',%s,NULL)""",
        (
            session_id,
            WRITE_FENCE_PROJECT,
            planning["id"],
            planning["revision"],
            planning["content_hash"],
            "8f000000-0000-0000-0003-000000000001",
            "1" * 64,
            outline_id,
            outline_hash,
            chapter_num,
            now,
        ),
    )
    await session.execute(
        """INSERT INTO working_drafts
           (id,project_id,chapter_session_id,revision,content,content_hash,
            source_payload_json,updated_at)
           VALUES (%s,%s,%s,1,%s,%s,%s,%s)""",
        (
            "8f000000-0000-0000-0004-000000000001",
            WRITE_FENCE_PROJECT,
            session_id,
            "working draft",
            canonical_hash("working draft"),
            canonical_json({}),
            now,
        ),
    )


@pytest.mark.asyncio
async def test_preparation_keeps_confirmed_planning_as_archived_read_only_entry(
    disposable_mysql,
):
    transaction, _, _ = await _prepare_planning_race(disposable_mysql)
    await _make_preparation_bible_current(disposable_mysql.session)

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    service = _preparation_service(transaction, read_connection)
    active = await service.preparation(WRITE_FENCE_PROJECT)
    assert active.planning == "current"
    assert active.outline == "missing"
    assert active.authoritative_chapter_number == 1
    assert active.next_action == "prepare_chapter_outline"
    assert (
        active.target_path
        == f"/projects/{WRITE_FENCE_PROJECT}/planning/story-blocks"
    )

    await service.archive(WRITE_FENCE_PROJECT, 0)
    archived = await service.preparation(WRITE_FENCE_PROJECT)
    assert archived.lifecycle == "archived"
    assert archived.planning == "current"
    assert archived.next_action == "archived_read_only"
    assert (
        archived.target_path
        == f"/projects/{WRITE_FENCE_PROJECT}/planning/volumes"
    )


@pytest.mark.asyncio
async def test_preparation_recovers_real_pending_planning_operation_without_secrets(
    disposable_mysql,
):
    transaction, _, now = await _prepare_planning_race(disposable_mysql)
    await _make_preparation_bible_current(disposable_mysql.session)
    await _write_current_planning_draft(
        transaction,
        WRITE_FENCE_PROJECT,
        now + 1,
    )
    binding = await disposable_mysql.session.fetchone(
        """SELECT head.binding_revision_id,head.revision AS binding_revision,
                  head.content_hash AS binding_hash,item.provider_id,
                  item.model_name_snapshot
             FROM project_model_binding_heads head
             JOIN project_model_binding_items item
               ON item.binding_revision_id=head.binding_revision_id
              AND item.task_key='planning'
            WHERE head.project_id=%s""",
        (WRITE_FENCE_PROJECT,),
    )
    assert binding is not None
    manifest = {"schemaVersion": "planning-generation-v1"}
    await disposable_mysql.session.execute(
        """INSERT INTO planning_generation_attempts
           (id,project_id,draft_id,operation_id,active_slot,idempotency_key,
            request_fingerprint,binding_revision_id,binding_revision,binding_hash,
            provider_id,model_name_snapshot,fencing_token,lease_expires_at,
            input_manifest_json,input_manifest_hash,result_content_json,
            result_content_hash,loaded_draft_revision,loaded_at,failure_code,
            status,created_at,updated_at)
           VALUES ('8e000000-0000-0000-0003-000000000001',%s,
                   '8d000000-0000-0000-0001-000000000003',
                   '8e000000-0000-0000-0003-000000000002',1,
                   'pending-preparation',%s,%s,%s,%s,%s,%s,1,%s,%s,%s,
                   NULL,NULL,NULL,NULL,NULL,'pending',%s,%s)""",
        (
            WRITE_FENCE_PROJECT,
            "f" * 64,
            binding["binding_revision_id"],
            binding["binding_revision"],
            binding["binding_hash"],
            binding["provider_id"],
            binding["model_name_snapshot"],
            now + 60_000,
            canonical_json(manifest),
            canonical_hash(manifest),
            now + 2,
            now + 2,
        ),
    )

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    result = await _preparation_service(
        transaction,
        read_connection,
    ).preparation(WRITE_FENCE_PROJECT)
    public = result.model_dump(mode="json", by_alias=True)

    assert result.planning == "draft"
    assert result.next_action == "recover_planning_operation"
    assert public["planningOperation"] == {
        "operationId": "8e000000-0000-0000-0003-000000000002",
        "status": "pending",
    }
    for forbidden in (
        "providerId",
        "modelName",
        "inputManifest",
        "prompt",
        "raw",
        "apiKey",
    ):
        assert forbidden not in str(public)


@pytest.mark.asyncio
async def test_preparation_chooses_pending_attempt_for_current_active_draft(
    disposable_mysql,
):
    transaction, _, now = await _prepare_planning_race(disposable_mysql)
    await _make_preparation_bible_current(disposable_mysql.session)
    await disposable_mysql.session.execute(
        """UPDATE planning_drafts
              SET status='superseded'
            WHERE project_id=%s
              AND id='8d000000-0000-0000-0001-000000000001'""",
        (WRITE_FENCE_PROJECT,),
    )
    await _write_current_planning_draft(
        transaction,
        WRITE_FENCE_PROJECT,
        now + 1,
    )
    await _insert_pending_planning_attempt(
        disposable_mysql.session,
        draft_id="8d000000-0000-0000-0001-000000000001",
        attempt_id="8e000000-0000-0000-0004-000000000001",
        operation_id="8e000000-0000-0000-0004-000000000002",
        idempotency_key="old-draft-token-2",
        fencing_token=2,
        now=now + 2,
    )
    current_operation_id = "8e000000-0000-0000-0004-000000000003"
    await _insert_pending_planning_attempt(
        disposable_mysql.session,
        draft_id="8d000000-0000-0000-0001-000000000003",
        attempt_id="8e000000-0000-0000-0004-000000000004",
        operation_id=current_operation_id,
        idempotency_key="current-draft-token-1",
        fencing_token=1,
        now=now + 3,
    )

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    result = await _preparation_service(
        transaction,
        read_connection,
    ).preparation(WRITE_FENCE_PROJECT)

    assert result.next_action == "recover_planning_operation"
    assert result.planning_operation is not None
    assert result.planning_operation.operation_id == current_operation_id


@pytest.mark.asyncio
async def test_preparation_ignores_old_draft_attempt_and_continues_writing(
    disposable_mysql,
):
    transaction, _, now = await _prepare_planning_race(disposable_mysql)
    await _make_preparation_bible_current(disposable_mysql.session)
    await disposable_mysql.session.execute(
        """UPDATE planning_drafts
              SET status='superseded'
            WHERE project_id=%s
              AND id='8d000000-0000-0000-0001-000000000001'""",
        (WRITE_FENCE_PROJECT,),
    )
    await _insert_pending_planning_attempt(
        disposable_mysql.session,
        draft_id="8d000000-0000-0000-0001-000000000001",
        attempt_id="8e000000-0000-0000-0005-000000000001",
        operation_id="8e000000-0000-0000-0005-000000000002",
        idempotency_key="old-draft-only",
        fencing_token=2,
        now=now + 2,
    )
    await _insert_valid_chapter_session(
        disposable_mysql.session,
        now=now + 3,
    )

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    result = await _preparation_service(
        transaction,
        read_connection,
    ).preparation(WRITE_FENCE_PROJECT)

    assert result.planning_operation is None
    assert result.next_action == "continue_writing"
    assert result.target_path.endswith("/write/chapters/7")


@pytest.mark.asyncio
async def test_preparation_operation_selection_is_stable_when_tokens_and_times_match(
    disposable_mysql,
):
    transaction, _, now = await _prepare_planning_race(disposable_mysql)
    await _make_preparation_bible_current(disposable_mysql.session)
    await disposable_mysql.session.execute(
        """UPDATE planning_drafts
              SET status='superseded'
            WHERE project_id=%s
              AND id='8d000000-0000-0000-0001-000000000001'""",
        (WRITE_FENCE_PROJECT,),
    )
    await _write_current_planning_draft(
        transaction,
        WRITE_FENCE_PROJECT,
        now + 1,
    )
    await _insert_pending_planning_attempt(
        disposable_mysql.session,
        draft_id="8d000000-0000-0000-0001-000000000001",
        attempt_id="8e000000-0000-0000-0006-000000000001",
        operation_id="8e000000-0000-0000-0006-000000000099",
        idempotency_key="same-token-time-old",
        fencing_token=1,
        now=now + 2,
    )
    current_operation_id = "8e000000-0000-0000-0006-000000000001"
    await _insert_pending_planning_attempt(
        disposable_mysql.session,
        draft_id="8d000000-0000-0000-0001-000000000003",
        attempt_id="8e000000-0000-0000-0006-000000000002",
        operation_id=current_operation_id,
        idempotency_key="same-token-time-current",
        fencing_token=1,
        now=now + 2,
    )

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    service = _preparation_service(transaction, read_connection)
    first = await service.preparation(WRITE_FENCE_PROJECT)
    second = await service.preparation(WRITE_FENCE_PROJECT)

    assert first.planning_operation is not None
    assert second.planning_operation is not None
    assert first.planning_operation.operation_id == current_operation_id
    assert second.planning_operation.operation_id == current_operation_id


class _MutablePlanningClock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


class _BlockingPlanningProvider:
    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(self, **_kwargs):
        self.entered.set()
        await _wait(self.release)
        return {
            "activeStoryBlockRef": None,
            "volumes": [],
            "plots": [],
            "storyBlocks": [],
        }


async def _start_blocked_planning_generation(
    disposable_mysql,
    *,
    id_prefix,
):
    transaction, planning, now = await _prepare_planning_race(
        disposable_mysql,
        generation_basis=True,
    )
    await _write_current_planning_draft(
        transaction,
        WRITE_FENCE_PROJECT,
        now + 1,
    )
    clock = _MutablePlanningClock(now + 10)
    gateway = _BlockingPlanningProvider()
    identifiers = iter(
        f"{id_prefix}-0000-0000-0000-{number:012d}"
        for number in range(1, 20)
    )
    generation = PlanningGenerationService(
        PlanningRepository(),
        provider_gateway=gateway,
        transaction_factory=transaction,
        id_factory=identifiers.__next__,
        clock=clock,
    )
    task = asyncio.create_task(
        generation.generate(
            GeneratePlanningDraft(
                project_id=WRITE_FENCE_PROJECT,
                draft_id="8d000000-0000-0000-0001-000000000003",
                draft_revision=2,
                draft_hash=planning.content_hash,
                idempotency_key=f"planning-lifecycle-{id_prefix}",
                author_instructions="",
            )
        )
    )
    await _wait(gateway.entered)
    pending = await disposable_mysql.session.fetchone(
        """SELECT status,active_slot,lease_expires_at
             FROM planning_generation_attempts
            WHERE project_id=%s
            ORDER BY created_at DESC,id DESC LIMIT 1""",
        (WRITE_FENCE_PROJECT,),
    )
    assert pending["status"] == "pending"
    assert pending["active_slot"] == 1
    assert pending["lease_expires_at"] > clock()
    return transaction, clock, gateway, task


@pytest.mark.asyncio
async def test_active_planning_generation_lease_blocks_archive_until_terminal(
    disposable_mysql,
):
    transaction, clock, gateway, generation_task = (
        await _start_blocked_planning_generation(
            disposable_mysql,
            id_prefix="8a100000",
        )
    )
    lifecycle = ProjectLifecycleService(
        ProjectRepository(clock=clock),
        transaction,
    )
    try:
        try:
            archive_result = await lifecycle.archive(WRITE_FENCE_PROJECT, 0)
        except BaseException as exc:
            archive_result = exc
    finally:
        gateway.release.set()
    (result,) = await _settle_race_tasks((generation_task,))

    assert isinstance(archive_result, http_errors.ProjectBusy)
    assert result.status in {"succeeded", "failed"}
    terminal = await disposable_mysql.session.fetchone(
        """SELECT status,active_slot
             FROM planning_generation_attempts
            WHERE project_id=%s
            ORDER BY created_at DESC,id DESC LIMIT 1""",
        (WRITE_FENCE_PROJECT,),
    )
    assert terminal["status"] in {"succeeded", "failed"}
    assert terminal["active_slot"] is None
    archived = await lifecycle.archive(WRITE_FENCE_PROJECT, 0)
    assert archived.archived_at is not None


@pytest.mark.asyncio
async def test_expired_planning_lease_allows_archive_and_publish_stays_fenced(
    disposable_mysql,
):
    transaction, clock, gateway, generation_task = (
        await _start_blocked_planning_generation(
            disposable_mysql,
            id_prefix="8a200000",
        )
    )
    clock.value += PLANNING_GENERATION_LEASE_MS + 1
    lifecycle = ProjectLifecycleService(
        ProjectRepository(clock=clock),
        transaction,
    )
    archived = await lifecycle.archive(WRITE_FENCE_PROJECT, 0)
    gateway.release.set()
    result = await asyncio.wait_for(generation_task, timeout=10)

    assert archived.archived_at is not None
    assert result.status == "superseded"
    assert result.loaded is False
    assert result.loaded_draft_revision is None
    draft = await disposable_mysql.session.fetchone(
        """SELECT draft_revision,source_attempt_id
             FROM planning_drafts
            WHERE id='8d000000-0000-0000-0001-000000000003'""",
    )
    assert draft == {"draft_revision": 2, "source_attempt_id": None}
    attempt = await disposable_mysql.session.fetchone(
        """SELECT status,active_slot,result_content_json,
                  result_content_hash,loaded_draft_revision
             FROM planning_generation_attempts
            WHERE project_id=%s
            ORDER BY created_at DESC,id DESC LIMIT 1""",
        (WRITE_FENCE_PROJECT,),
    )
    assert attempt == {
        "status": "superseded",
        "active_slot": None,
        "result_content_json": None,
        "result_content_hash": None,
        "loaded_draft_revision": None,
    }


class _ArchiveAttemptRepository(ProjectRepository):
    def __init__(self, attempted, connection_ids):
        super().__init__()
        self.attempted = attempted
        self.connection_ids = connection_ids

    async def lock_any(self, session, project_id):
        self.connection_ids["archive"] = id(session.raw)
        self.attempted.set()
        return await super().lock_any(session, project_id)


def _consume_future_exception(future):
    if not future.cancelled():
        future.exception()


async def _settle_race_tasks(tasks, *, timeout=10):
    tasks = tuple(task for task in tasks if task is not None)
    if not tasks:
        return ()

    aggregate = asyncio.gather(*tasks, return_exceptions=True)
    try:
        return tuple(
            await asyncio.wait_for(asyncio.shield(aggregate), timeout=timeout)
        )
    except asyncio.TimeoutError:
        for task in tasks:
            if not task.done():
                task.cancel()

        cleanup = asyncio.gather(*tasks, return_exceptions=True)
        try:
            return tuple(
                await asyncio.wait_for(asyncio.shield(cleanup), timeout=timeout)
            )
        except asyncio.TimeoutError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            aggregate.add_done_callback(_consume_future_exception)
            cleanup.add_done_callback(_consume_future_exception)
            raise


@pytest.mark.asyncio
async def test_generation_archive_cleanup_bounds_and_consumes_early_failures():
    blocker_started = asyncio.Event()
    blocker_cancelled = asyncio.Event()

    async def fail_early():
        raise RuntimeError("controlled early archive failure")

    async def block_until_cancelled():
        blocker_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            blocker_cancelled.set()

    failed = asyncio.create_task(fail_early())
    blocked = asyncio.create_task(block_until_cancelled())
    await _wait(blocker_started)

    results = await asyncio.wait_for(
        _settle_race_tasks((failed, blocked), timeout=0.1),
        timeout=1,
    )

    assert isinstance(results[0], RuntimeError)
    assert isinstance(results[1], asyncio.CancelledError)
    assert blocker_cancelled.is_set()
    assert failed.done() and blocked.done()


async def _run_planning_archive_race(
    disposable_mysql,
    *,
    fail_write: bool,
):
    transaction, planning, now = await _prepare_planning_race(disposable_mysql)
    connection_ids = {}
    archive_attempted = asyncio.Event()
    archive_completed = asyncio.Event()
    write_entered = asyncio.Event()
    release_write = asyncio.Event()
    archive_service = ProjectLifecycleService(
        _ArchiveAttemptRepository(archive_attempted, connection_ids),
        transaction,
    )

    async def hold_project_lock(session):
        connection_ids["planning"] = id(session.raw)
        write_entered.set()
        await _wait(release_write)

    async def archive_with_completion():
        try:
            return await archive_service.archive(WRITE_FENCE_PROJECT, 0)
        finally:
            archive_completed.set()

    planning_task = asyncio.create_task(
        _write_current_planning_draft(
            transaction,
            WRITE_FENCE_PROJECT,
            now + 1,
            after_lock=hold_project_lock,
            fail_after_lock=fail_write,
        )
    )
    archive_task = None
    try:
        await _wait(write_entered)
        archive_task = asyncio.create_task(archive_with_completion())
        await _wait(archive_attempted)
        assert set(connection_ids) == {"planning", "archive"}
        assert len(set(connection_ids.values())) == 2
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(archive_completed.wait(), timeout=0.1)
        assert not archive_task.done()
        release_write.set()
        planning_result, archive_result = await _settle_race_tasks(
            (planning_task, archive_task)
        )
    finally:
        release_write.set()
        await _settle_race_tasks((planning_task, archive_task))

    return {
        "planning": planning,
        "planning_result": planning_result,
        "archive_result": archive_result,
    }


@pytest.mark.asyncio
async def test_real_planning_write_lock_then_archive_commits_before_archive(
    disposable_mysql,
):
    race = await _run_planning_archive_race(
        disposable_mysql,
        fail_write=False,
    )

    assert race["planning_result"].content_hash == race["planning"].content_hash
    assert isinstance(race["archive_result"], ProjectResult)
    draft = await disposable_mysql.session.fetchone(
        """SELECT draft_revision,content_hash,status
             FROM planning_drafts
            WHERE id='8d000000-0000-0000-0001-000000000003'""",
    )
    project = await disposable_mysql.session.fetchone(
        """SELECT archived_at,lifecycle_revision FROM projects WHERE id=%s""",
        (WRITE_FENCE_PROJECT,),
    )
    assert draft == {
        "draft_revision": 2,
        "content_hash": race["planning"].content_hash,
        "status": "active",
    }
    assert project["archived_at"] is not None
    assert project["lifecycle_revision"] == 1


@pytest.mark.asyncio
async def test_real_planning_write_failure_rolls_back_then_archive_succeeds(
    disposable_mysql,
):
    race = await _run_planning_archive_race(
        disposable_mysql,
        fail_write=True,
    )

    assert isinstance(
        race["planning_result"],
        RuntimeError,
    )
    assert isinstance(race["archive_result"], ProjectResult)
    draft = await disposable_mysql.session.fetchone(
        """SELECT id FROM planning_drafts
            WHERE id='8d000000-0000-0000-0001-000000000003'""",
    )
    project = await disposable_mysql.session.fetchone(
        """SELECT archived_at,lifecycle_revision FROM projects WHERE id=%s""",
        (WRITE_FENCE_PROJECT,),
    )
    assert draft is None
    assert project["archived_at"] is not None
    assert project["lifecycle_revision"] == 1


@pytest.mark.asyncio
async def test_archive_blocks_writes_and_restore_reopens_future_writes_but_keeps_confirmed_baseline_locked(
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
    await _insert_confirmed_bible(
        disposable_mysql.session,
        confirmed,
        bible_id="8f000000-0000-0000-0004-000000000001",
        now=now,
    )
    planning = await _insert_confirmed_planning(
        disposable_mysql.session,
        WRITE_FENCE_PROJECT,
        now,
    )
    planning_before_archive = await disposable_mysql.session.fetchone(
        """SELECT head.revision,head.content_hash,revision.content_json
             FROM project_planning_heads head
             JOIN planning_revisions revision
               ON revision.project_id=head.project_id
              AND revision.id=head.planning_revision_id
              AND revision.revision=head.revision
              AND revision.content_hash=head.content_hash
            WHERE head.project_id=%s""",
        (WRITE_FENCE_PROJECT,),
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
    assert await disposable_mysql.session.fetchone(
        """SELECT head.revision,head.content_hash,revision.content_json
             FROM project_planning_heads head
             JOIN planning_revisions revision
               ON revision.project_id=head.project_id
              AND revision.id=head.planning_revision_id
              AND revision.revision=head.revision
              AND revision.content_hash=head.content_hash
            WHERE head.project_id=%s""",
        (WRITE_FENCE_PROJECT,),
    ) == planning_before_archive
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
            _write_current_planning_draft(
                transaction,
                WRITE_FENCE_PROJECT,
                now + 1,
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
    }
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
    assert await disposable_mysql.session.fetchone(
        """SELECT id FROM planning_drafts
            WHERE id='8d000000-0000-0000-0001-000000000003'"""
    ) is None

    await disposable_mysql.session.execute(
        """UPDATE story_engine_batches
              SET status='failed',public_error_code='provider_failed',
                  raw_response_hash=NULL,finished_at=%s
            WHERE id=%s""",
        (now + 1, CONTRACT_BATCH),
    )
    restored = await project_service.restore(WRITE_FENCE_PROJECT, 1)
    confirmed_seed_after_restore = await capture(
        seed_service.create(
            CreateSeed(
                project_id=WRITE_FENCE_PROJECT,
                payload=_seed_payload("Restored seed"),
            )
        )
    )
    planning_after_restore = await _write_current_planning_draft(
        transaction,
        WRITE_FENCE_PROJECT,
        now + 2,
    )

    assert restored.archived_at is None
    assert isinstance(confirmed_seed_after_restore, http_errors.SeedAlreadyConfirmed)
    assert planning_after_restore.content_hash == planning.content_hash
    assert await disposable_mysql.session.fetchone(
        """SELECT project_id,status,draft_revision FROM planning_drafts
            WHERE id='8d000000-0000-0000-0001-000000000003'"""
    ) == {
        "project_id": WRITE_FENCE_PROJECT,
        "status": "active",
        "draft_revision": 2,
    }
