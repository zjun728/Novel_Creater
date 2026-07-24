from __future__ import annotations

import pytest

from backend.repositories.seeds import SeedRepository
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
async def test_archived_project_seed_reads_disable_mutations_but_keep_facts(
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

    listed = {item.id: item for item in await service.list("p1")}
    selected = await service.get_selected("p1")

    assert (
        listed[free.id].capabilities.referenced,
        listed[free.id].capabilities.hasFinalChapters,
    ) == (False, True)
    assert (
        listed[selected_seed.id].capabilities.referenced,
        listed[selected_seed.id].capabilities.hasFinalChapters,
    ) == (True, True)
    assert selected.active_selection is not None
    assert (
        selected.active_selection.seed.capabilities.referenced,
        selected.active_selection.seed.capabilities.hasFinalChapters,
    ) == (True, True)
    for item in (*listed.values(), selected.active_selection.seed):
        assert (
            item.capabilities.canEdit,
            item.capabilities.canSelect,
            item.capabilities.canArchive,
            item.capabilities.canRestore,
            item.capabilities.canPermanentlyDelete,
        ) == (False, False, False, False, False)
