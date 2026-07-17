from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from backend import http_errors
from backend.domain.model_bindings import TASK_KEYS
from backend.domain.seeds import SeedPayload
from backend.repositories.model_bindings import ModelBindingRepository
from backend.repositories.projects import ProjectRepository
from backend.repositories.seeds import SeedRepository
from backend.services.model_bindings import ModelBindingService
from backend.services.project_lifecycle import (
    CreateProject,
    ProjectLifecycleService,
)
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
        isinstance(result, http_errors.SeedNotFound)
        for result in seed_results
    )
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
