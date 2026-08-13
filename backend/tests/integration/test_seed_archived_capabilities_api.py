from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.repositories.seeds import SeedRepository
from backend.domain.routers import seeds
from backend.security.redaction import install_error_handlers
from backend.services.seeds import CreateSeed, SeedService, SelectSeed
from backend.tests.integration.test_seed_revisions import (
    connection_factory_for,
    install_first_final_chapter,
    install_matching_contract,
    insert_project,
    payload,
)
from backend.tests.support.disposable_mysql import transaction_factory_for


pytestmark = pytest.mark.mysql


@pytest.mark.asyncio
async def test_archived_seed_read_routes_serialize_disabled_capabilities(
    disposable_mysql,
):
    await insert_project(disposable_mysql.session, "p1")
    service = SeedService(
        SeedRepository(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
        connection_factory=connection_factory_for(
            disposable_mysql.connection_config
        ),
    )
    free = await service.create(
        CreateSeed(project_id="p1", payload=payload("可编辑候选"))
    )
    selected_seed = await service.create(
        CreateSeed(project_id="p1", payload=payload("已选择候选"))
    )
    selection = await service.select(
        SelectSeed(
            project_id="p1",
            seed_id=selected_seed.id,
            expected_seed_revision=selected_seed.revision,
            expected_selection_revision=0,
        )
    )
    await install_matching_contract(disposable_mysql.session, "p1", selection)
    await install_first_final_chapter(
        disposable_mysql.session,
        disposable_mysql.connection_config,
        "p1",
        selection,
    )
    await disposable_mysql.session.execute(
        """UPDATE projects
              SET archived_at=2,lifecycle_revision=lifecycle_revision+1
            WHERE id='p1'"""
    )
    app = FastAPI()
    app.include_router(seeds.router, prefix="/api")
    app.dependency_overrides[seeds.get_seed_service] = lambda: service
    install_error_handlers(app)

    with TestClient(app, raise_server_exceptions=False) as client:
        listed = client.get("/api/projects/p1/seeds")
        selected = client.get("/api/projects/p1/selected-seed")

    assert listed.status_code == selected.status_code == 200
    listed_by_id = {item["id"]: item for item in listed.json()}
    selected_seed_json = selected.json()["activeSelection"]["seed"]
    assert (
        listed_by_id[free.id]["capabilities"]["referenced"],
        listed_by_id[free.id]["capabilities"]["hasFinalChapters"],
    ) == (False, True)
    assert (
        selected_seed_json["capabilities"]["referenced"],
        selected_seed_json["capabilities"]["hasFinalChapters"],
    ) == (True, True)
    for item in (*listed_by_id.values(), selected_seed_json):
        capabilities = item["capabilities"]
        assert (
            capabilities["canEdit"],
            capabilities["canSelect"],
            capabilities["canArchive"],
            capabilities["canRestore"],
            capabilities["canPermanentlyDelete"],
        ) == (False, False, False, False, False)
