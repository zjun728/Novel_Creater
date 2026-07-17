from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from backend import http_errors
from backend.domain.model_bindings import TASK_KEYS
from backend.domain.seeds import SeedPayload
from backend.repositories.model_bindings import ModelBindingRepository
from backend.repositories.projects import ProjectRepository
from backend.repositories.seeds import SeedRepository
from backend.services.model_bindings import ModelBindingService
from backend.services.projects import CreateProject, ProjectService, UpdateProject
from backend.services.seeds import (
    CreateSeed,
    DeleteSeed,
    EditSeed,
    SeedService,
    SelectSeed,
)
from backend.tests.support.disposable_mysql import transaction_factory_for


pytestmark = pytest.mark.mysql


PROJECT_ID = "60000000-0000-0000-0000-000000000001"


def _project(
    project_id: str = PROJECT_ID, title: str = "Archive integration"
) -> CreateProject:
    return CreateProject(
        id=project_id,
        title=title,
        genre="history",
        description="test only",
        target_words=1_000,
        target_chapters=10,
    )


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


@pytest.mark.asyncio
async def test_delete_archives_project_without_changing_immutable_foundations(
    disposable_mysql,
):
    transaction = transaction_factory_for(disposable_mysql.connection_config)

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    bindings = ModelBindingService(
        ModelBindingRepository(),
        transaction_factory=transaction,
        connection_factory=read_connection,
    )
    service = ProjectService(
        ProjectRepository(),
        transaction,
        read_connection,
        model_binding_service=bindings,
    )

    await service.create(_project())
    before = await _foundation_snapshot(disposable_mysql.session)
    assert len(before["canon"]) == 1
    assert len(before["projection"]) == 1
    assert len(before["contract"]) == 1
    assert len(before["binding_revisions"]) == 1
    assert len(before["binding_head"]) == 1
    assert len(before["binding_items"]) == len(TASK_KEYS) == 8

    await service.delete(PROJECT_ID)

    archived = await disposable_mysql.session.fetchone(
        "SELECT * FROM projects WHERE id=%s", (PROJECT_ID,)
    )
    assert archived is not None
    assert archived["status"] == "drafting"
    assert archived["archived_at"] is not None
    assert archived["lifecycle_revision"] == 1
    assert await _foundation_snapshot(disposable_mysql.session) == before
    assert not await service.list()
    assert await service.get(PROJECT_ID) is None
    with pytest.raises(http_errors.ProjectNotFound):
        await service.content_state(PROJECT_ID)

    archived_before_second_delete = dict(archived)
    with pytest.raises(http_errors.ProjectNotFound):
        await service.delete(PROJECT_ID)

    assert await disposable_mysql.session.fetchone(
        "SELECT * FROM projects WHERE id=%s", (PROJECT_ID,)
    ) == archived_before_second_delete
    assert await _foundation_snapshot(disposable_mysql.session) == before


@pytest.mark.asyncio
async def test_stale_update_cannot_revive_project_after_concurrent_archive(
    disposable_mysql,
):
    transaction = transaction_factory_for(disposable_mysql.connection_config)
    update_write_reached = asyncio.Event()
    allow_update_write = asyncio.Event()
    update_lock_acquired = asyncio.Event()
    delete_lock_attempted = asyncio.Event()

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    class UpdateGateRepository(ProjectRepository):
        async def lock_active_project(self, session, project_id):
            row = await super().lock_active_project(session, project_id)
            update_lock_acquired.set()
            return row

        async def update(self, session, project_id, changes):
            update_write_reached.set()
            await allow_update_write.wait()
            return await super().update(session, project_id, changes)

    class DeleteGateRepository(ProjectRepository):
        async def lock_active_project(self, session, project_id):
            delete_lock_attempted.set()
            return await super().lock_active_project(session, project_id)

    bindings = ModelBindingService(
        ModelBindingRepository(), transaction_factory=transaction
    )
    creator = ProjectService(
        ProjectRepository(clock=iter(range(1_000, 2_000)).__next__),
        transaction,
        read_connection,
        model_binding_service=bindings,
    )
    await creator.create(_project())
    update_service = ProjectService(
        UpdateGateRepository(clock=iter(range(2_000, 3_000)).__next__),
        transaction,
        read_connection,
    )
    delete_service = ProjectService(
        DeleteGateRepository(clock=iter(range(3_000, 4_000)).__next__),
        transaction,
        read_connection,
    )

    update_task = asyncio.create_task(
        update_service.update(
            PROJECT_ID, UpdateProject(title="Stale title", status="drafting")
        )
    )
    await update_write_reached.wait()
    delete_task = asyncio.create_task(delete_service.delete(PROJECT_ID))
    await delete_lock_attempted.wait()

    if not update_lock_acquired.is_set():
        await delete_task
    allow_update_write.set()
    update_result, delete_result = await asyncio.gather(
        update_task, delete_task, return_exceptions=True
    )

    assert not isinstance(update_result, BaseException)
    assert delete_result is None
    row = await disposable_mysql.session.fetchone(
        """SELECT title,status,archived_at,lifecycle_revision
             FROM projects WHERE id=%s""",
        (PROJECT_ID,),
    )
    assert row["title"] == "Stale title"
    assert row["status"] == "drafting"
    assert row["archived_at"] is not None
    assert row["lifecycle_revision"] == 1


@pytest.mark.asyncio
async def test_concurrent_double_delete_has_one_success_and_preserves_history(
    disposable_mysql,
):
    transaction = transaction_factory_for(disposable_mysql.connection_config)
    both_attempted = asyncio.Event()
    release_locks = asyncio.Event()

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    class PairGateRepository(ProjectRepository):
        def __init__(self):
            super().__init__(clock=iter(range(4_000, 5_000)).__next__)
            self.attempts = 0

        async def lock_active_project(self, session, project_id):
            self.attempts += 1
            if self.attempts == 2:
                both_attempted.set()
            await release_locks.wait()
            return await super().lock_active_project(session, project_id)

    bindings = ModelBindingService(
        ModelBindingRepository(), transaction_factory=transaction
    )
    creator = ProjectService(
        ProjectRepository(clock=iter(range(5_000, 6_000)).__next__),
        transaction,
        read_connection,
        model_binding_service=bindings,
    )
    await creator.create(_project())
    before = await _foundation_snapshot(disposable_mysql.session)
    service = ProjectService(PairGateRepository(), transaction, read_connection)

    tasks = [
        asyncio.create_task(service.delete(PROJECT_ID)),
        asyncio.create_task(service.delete(PROJECT_ID)),
    ]
    await both_attempted.wait()
    release_locks.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, http_errors.ProjectNotFound) for result in results) == 1
    assert (
        await disposable_mysql.session.fetchone(
            """SELECT status,archived_at,lifecycle_revision
                 FROM projects WHERE id=%s""",
            (PROJECT_ID,),
        )
    ) == {
        "status": "drafting",
        "archived_at": 4_000,
        "lifecycle_revision": 1,
    }
    assert await _foundation_snapshot(disposable_mysql.session) == before


@pytest.mark.asyncio
async def test_archived_project_blocks_seed_and_binding_resources_and_inheritance(
    disposable_mysql,
):
    transaction = transaction_factory_for(disposable_mysql.connection_config)

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    bindings = ModelBindingService(
        ModelBindingRepository(
            id_factory=(f"71000000-0000-0000-0000-{n:012d}" for n in range(50)).__next__,
            clock=iter(range(7_000, 8_000)).__next__,
        ),
        transaction_factory=transaction,
        connection_factory=read_connection,
    )
    projects = ProjectService(
        ProjectRepository(
            id_factory=(f"72000000-0000-0000-0000-{n:012d}" for n in range(50)).__next__,
            clock=iter(range(8_000, 9_000)).__next__,
        ),
        transaction,
        read_connection,
        model_binding_service=bindings,
    )
    seeds = SeedService(
        SeedRepository(),
        transaction_factory=transaction,
        connection_factory=read_connection,
        id_factory=(f"73000000-0000-0000-0000-{n:012d}" for n in range(50)).__next__,
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
    await projects.delete(PROJECT_ID)

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

    assert all(isinstance(result, http_errors.SeedNotFound) for result in seed_results)
    assert all(
        isinstance(result, http_errors.BindingNotFound)
        for result in binding_results
    )
    assert await _seed_snapshot(disposable_mysql.session) == seeds_before
    assert await _foundation_snapshot(disposable_mysql.session) == foundation_before

    next_project_id = "60000000-0000-0000-0000-000000000002"
    await projects.create(_project(next_project_id, "No archived inheritance"))
    inherited = await bindings.get_current(next_project_id)
    assert inherited.source_project_id is None
