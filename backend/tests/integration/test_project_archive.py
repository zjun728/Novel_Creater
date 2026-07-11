from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from backend import http_errors
from backend.domain.model_bindings import TASK_KEYS
from backend.repositories.model_bindings import ModelBindingRepository
from backend.repositories.projects import ProjectRepository
from backend.services.model_bindings import ModelBindingService
from backend.services.projects import CreateProject, ProjectService
from backend.tests.support.disposable_mysql import transaction_factory_for


pytestmark = pytest.mark.mysql


PROJECT_ID = "60000000-0000-0000-0000-000000000001"


def _project() -> CreateProject:
    return CreateProject(
        id=PROJECT_ID,
        title="Archive integration",
        genre="history",
        description="test only",
        target_words=1_000,
        target_chapters=10,
    )


async def _foundation_snapshot(session) -> dict:
    return {
        "canon": await session.fetchall(
            """SELECT revision_number,content_hash
                 FROM canon_revisions WHERE project_id=%s
                 ORDER BY revision_number""",
            (PROJECT_ID,),
        ),
        "projection": await session.fetchall(
            """SELECT canon_revision_number,projection_revision_number,content_hash
                 FROM projection_heads WHERE project_id=%s""",
            (PROJECT_ID,),
        ),
        "contract": await session.fetchall(
            """SELECT revision,creation_hash,style_hash
                 FROM project_contract_heads WHERE project_id=%s""",
            (PROJECT_ID,),
        ),
        "binding_revisions": await session.fetchall(
            """SELECT revision,content_hash,source_project_id
                 FROM project_model_binding_revisions WHERE project_id=%s
                 ORDER BY revision""",
            (PROJECT_ID,),
        ),
        "binding_head": await session.fetchall(
            """SELECT revision,content_hash
                 FROM project_model_binding_heads WHERE project_id=%s""",
            (PROJECT_ID,),
        ),
        "binding_items": await session.fetchall(
            """SELECT i.task_key,i.resolution_status,i.item_hash
                 FROM project_model_binding_items i
                 JOIN project_model_binding_revisions r
                   ON r.id=i.binding_revision_id
                 WHERE r.project_id=%s ORDER BY i.task_key""",
            (PROJECT_ID,),
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
    assert archived["status"] == "archived"
    assert await _foundation_snapshot(disposable_mysql.session) == before
    assert not await service.list()
    assert await service.get(PROJECT_ID) is None

    archived_before_second_delete = dict(archived)
    with pytest.raises(http_errors.ProjectNotFound):
        await service.delete(PROJECT_ID)

    assert await disposable_mysql.session.fetchone(
        "SELECT * FROM projects WHERE id=%s", (PROJECT_ID,)
    ) == archived_before_second_delete
    assert await _foundation_snapshot(disposable_mysql.session) == before
