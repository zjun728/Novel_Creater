from __future__ import annotations

import pytest

from backend.domain.finalization import change_set_hash
from backend.repositories.finalization import FinalizationRepository
from backend.repositories.novel_downloads import NovelDownloadRepository
from backend.services.finalization_commit import CommitFinalization
from backend.tests.integration.test_atomic_finalization_mysql import (
    HASH_B,
    PROJECT_ID,
    SESSION_ID,
    _seed,
    _service,
)
from backend.tests.support.disposable_mysql import transaction_factory_for


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_load_snapshot_compiles_against_disposable_empty_schema(disposable_mysql):
    transaction_factory = transaction_factory_for(disposable_mysql.connection_config)
    async with transaction_factory() as session:
        assert await NovelDownloadRepository().load_finalized_snapshot(
            session, "00000000-0000-0000-0000-000000000099",
        ) is None


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_load_snapshot_ignores_changed_current_head_and_uses_final_pins(
    disposable_mysql,
):
    transaction_factory = transaction_factory_for(disposable_mysql.connection_config)
    async with transaction_factory() as session:
        planning, change_set = await _seed(session, transaction_factory)
    service = _service(transaction_factory, FinalizationRepository(), (
        "50000000-0000-4000-8000-000000000011",
        "50000000-0000-4000-8000-000000000012",
        "50000000-0000-4000-8000-000000000013",
    ))
    await service.commit(CommitFinalization(
        project_id=PROJECT_ID, chapter_session_id=SESSION_ID,
        idempotency_key=HASH_B, expected_revision=1,
        expected_revision_hash=change_set_hash(change_set),
    ))

    async with transaction_factory() as session:
        snapshot = await NovelDownloadRepository().load_finalized_snapshot(
            session, PROJECT_ID,
        )
        head = await session.fetchone(
            "SELECT revision,content_hash FROM project_planning_heads WHERE project_id=%s",
            (PROJECT_ID,),
        )
    assert snapshot is not None
    assert snapshot.chapters[0].chapter_number == 1
    assert snapshot.chapters[0].volume_title == "第一卷"
    assert head["revision"] == 2
    assert head["content_hash"] != planning.content_hash
