from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

import aiomysql
import pytest

from backend.domain.seeds import SeedPayload
from backend.http_errors import SeedConflict, SeedNotFound
from backend.repositories.seeds import SeedRepository
from backend.services.seeds import (
    CreateSeed,
    DeleteSeed,
    EditSeed,
    SeedService,
    SelectSeed,
)
from backend.tests.support.disposable_mysql import (
    _TestDatabaseSession,
    transaction_factory_for,
)


pytestmark = pytest.mark.mysql


def payload(title: str) -> SeedPayload:
    return SeedPayload(
        title=title,
        genre="悬疑",
        logline="失踪者从未来寄回一封信。",
        protagonist="档案员林岚",
        desire="找回失踪的姐姐",
        coreConflict="公开真相会改写姐姐存在的时间线",
        worldPressure="城市每天遗忘一段公共记忆",
        openingHook="一封信盖着明日邮戳",
        differentiation="用档案缺页呈现时间变化",
    )


def connection_factory_for(config):
    config = {**config, "autocommit": True}

    @asynccontextmanager
    async def connection_factory():
        raw = await aiomysql.connect(**config)
        try:
            yield _TestDatabaseSession(raw)
        finally:
            raw.close()

    return connection_factory


async def insert_project(session, project_id: str):
    await session.execute(
        """INSERT INTO projects
           (id,title,genre,description,target_words,target_chapters,status,
            current_chapter,created_at,updated_at)
           VALUES (%s,'Integration','悬疑','test',100000,100,'drafting',0,1,1)""",
        (project_id,),
    )


async def install_matching_contract(session, project_id: str, seed):
    binding_id = str(uuid4())
    creation_id = str(uuid4())
    style_id = str(uuid4())
    await session.execute(
        """INSERT INTO project_model_binding_revisions
           (id,project_id,revision,content_hash,source_project_id,created_at)
           VALUES (%s,%s,1,%s,NULL,2)""",
        (binding_id, project_id, "b" * 64),
    )
    await session.execute(
        """INSERT INTO creation_contracts
           (id,project_id,revision,seed_id,seed_revision_id,seed_hash,
            binding_revision_id,binding_hash,channel_profile_key,
            genre_profile_key,quality_charter_version,total_word_min,
            total_word_max,chapter_capacity_policy,reference_manifest_json,
            reference_manifest_hash,content_json,content_hash,confirmed_at)
           VALUES (%s,%s,1,%s,%s,%s,%s,%s,'default','mystery','quality-v1',
                   90000,110000,'按情节自然切章','{}',%s,'{}',%s,3)""",
        (
            creation_id, project_id, seed.id, seed.revision_id,
            seed.content_hash, binding_id, "b" * 64, "e" * 64, "c" * 64,
        ),
    )
    await session.execute(
        """INSERT INTO style_contracts
           (id,project_id,creation_contract_id,revision,merged_style_json,
            likes_json,dislikes_json,content_hash,confirmed_at)
           VALUES (%s,%s,%s,1,'{}','[]','[]',%s,3)""",
        (style_id, project_id, creation_id, "d" * 64),
    )
    await session.execute(
        """INSERT INTO project_contract_heads
           (project_id,revision,creation_contract_id,style_contract_id,
            creation_hash,style_hash,updated_at)
           VALUES (%s,1,%s,%s,%s,%s,3)""",
        (project_id, creation_id, style_id, "c" * 64, "d" * 64),
    )


@pytest.mark.asyncio
async def test_concurrent_stale_writer_preserves_old_revision_and_cross_project_scope(
    disposable_mysql,
):
    await insert_project(disposable_mysql.session, "p1")
    await insert_project(disposable_mysql.session, "p2")
    service = SeedService(
        SeedRepository(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
        connection_factory=connection_factory_for(
            disposable_mysql.connection_config
        ),
    )
    created = await service.create(CreateSeed(project_id="p1", payload=payload("原始")))
    other = await service.create(CreateSeed(project_id="p2", payload=payload("他项")))
    original = await disposable_mysql.session.fetchone(
        """SELECT payload_json,content_hash FROM creative_seed_revisions
           WHERE seed_id=%s AND revision=1""",
        (created.id,),
    )

    commands = (
        EditSeed(
            project_id="p1", seed_id=created.id, payload=payload("改写甲"),
            expected_seed_revision=1, expected_selection_revision=0,
        ),
        EditSeed(
            project_id="p1", seed_id=created.id, payload=payload("改写乙"),
            expected_seed_revision=1, expected_selection_revision=0,
        ),
    )
    outcomes = await asyncio.gather(
        *(service.edit(command) for command in commands),
        return_exceptions=True,
    )
    assert sum(not isinstance(item, BaseException) for item in outcomes) == 1
    assert sum(isinstance(item, SeedConflict) for item in outcomes) == 1
    assert await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM creative_seed_revisions WHERE seed_id=%s",
        (created.id,),
    ) == {"count": 2}
    assert await disposable_mysql.session.fetchone(
        """SELECT payload_json,content_hash FROM creative_seed_revisions
           WHERE seed_id=%s AND revision=1""",
        (created.id,),
    ) == original

    with pytest.raises(SeedNotFound):
        await service.select(
            SelectSeed(
                project_id="p1", seed_id=other.id,
                expected_seed_revision=1, expected_selection_revision=0,
            )
        )
    assert await disposable_mysql.session.fetchone(
        "SELECT project_id FROM project_selected_seeds WHERE project_id='p1'"
    ) is None


@pytest.mark.asyncio
async def test_selected_edit_reports_contract_drift_and_delete_preserves_dependencies(
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
    selected_seed = await service.create(
        CreateSeed(project_id="p1", payload=payload("选中"))
    )
    selection = await service.select(
        SelectSeed(
            project_id="p1", seed_id=selected_seed.id,
            expected_seed_revision=1, expected_selection_revision=0,
        )
    )
    await install_matching_contract(disposable_mysql.session, "p1", selected_seed)
    ready = await service.get_selected("p1")
    assert ready.seed_ready is True
    assert ready.reasons == ("binding_not_verified",)

    edited = await service.edit(
        EditSeed(
            project_id="p1", seed_id=selected_seed.id,
            payload=payload("选中改写"), expected_seed_revision=1,
            expected_selection_revision=selection.selection_revision,
        )
    )
    drift = await service.get_selected("p1")
    assert drift.seed_ready is False
    assert drift.reasons == ("selected_seed_drift",)

    await service.delete(
        DeleteSeed(
            project_id="p1", seed_id=selected_seed.id,
            expected_seed_revision=edited.revision,
            expected_selection_revision=edited.selection_revision,
        )
    )
    assert (await disposable_mysql.session.fetchone(
        "SELECT status FROM creative_seeds WHERE id=%s", (selected_seed.id,)
    ))["status"] == "archived"

    free = await service.create(CreateSeed(project_id="p1", payload=payload("自由")))
    await service.delete(
        DeleteSeed(
            project_id="p1", seed_id=free.id,
            expected_seed_revision=1,
            expected_selection_revision=edited.selection_revision,
        )
    )
    assert await disposable_mysql.session.fetchone(
        "SELECT id FROM creative_seeds WHERE id=%s", (free.id,)
    ) is None


@pytest.mark.asyncio
async def test_edit_failure_rolls_back_revision_append(disposable_mysql):
    await insert_project(disposable_mysql.session, "p1")
    factory = transaction_factory_for(disposable_mysql.connection_config)
    normal = SeedService(
        SeedRepository(), transaction_factory=factory,
        connection_factory=connection_factory_for(
            disposable_mysql.connection_config
        ),
    )
    created = await normal.create(CreateSeed(project_id="p1", payload=payload("原始")))

    class FailingRepository(SeedRepository):
        async def update_head(self, session, row):
            raise RuntimeError("test-only injected failure")

    failing = SeedService(FailingRepository(), transaction_factory=factory)
    with pytest.raises(RuntimeError, match="test-only"):
        await failing.edit(
            EditSeed(
                project_id="p1", seed_id=created.id,
                payload=payload("不可提交"), expected_seed_revision=1,
                expected_selection_revision=0,
            )
        )
    assert await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM creative_seed_revisions WHERE seed_id=%s",
        (created.id,),
    ) == {"count": 1}
    assert await disposable_mysql.session.fetchone(
        "SELECT revision FROM creative_seed_heads WHERE seed_id=%s", (created.id,)
    ) == {"revision": 1}


@pytest.mark.asyncio
async def test_explicit_selection_refreshes_selected_at_while_edit_preserves_it(
    disposable_mysql,
):
    await insert_project(disposable_mysql.session, "p1")
    now = {"value": 10}
    service = SeedService(
        SeedRepository(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
        connection_factory=connection_factory_for(
            disposable_mysql.connection_config
        ),
        clock=lambda: now["value"],
    )
    first = await service.create(CreateSeed(project_id="p1", payload=payload("甲")))
    second = await service.create(CreateSeed(project_id="p1", payload=payload("乙")))

    now["value"] = 100
    await service.select(
        SelectSeed(
            project_id="p1", seed_id=first.id,
            expected_seed_revision=1, expected_selection_revision=0,
        )
    )
    assert await disposable_mysql.session.fetchone(
        """SELECT seed_id,selection_revision,selected_at,updated_at
           FROM project_selected_seeds WHERE project_id='p1'"""
    ) == {
        "seed_id": first.id,
        "selection_revision": 1,
        "selected_at": 100,
        "updated_at": 100,
    }

    now["value"] = 200
    await service.select(
        SelectSeed(
            project_id="p1", seed_id=second.id,
            expected_seed_revision=1, expected_selection_revision=1,
        )
    )
    assert await disposable_mysql.session.fetchone(
        """SELECT seed_id,selection_revision,selected_at,updated_at
           FROM project_selected_seeds WHERE project_id='p1'"""
    ) == {
        "seed_id": second.id,
        "selection_revision": 2,
        "selected_at": 200,
        "updated_at": 200,
    }

    now["value"] = 300
    await service.edit(
        EditSeed(
            project_id="p1", seed_id=second.id, payload=payload("乙改"),
            expected_seed_revision=1, expected_selection_revision=2,
        )
    )
    assert await disposable_mysql.session.fetchone(
        """SELECT seed_id,selection_revision,selected_at,updated_at
           FROM project_selected_seeds WHERE project_id='p1'"""
    ) == {
        "seed_id": second.id,
        "selection_revision": 3,
        "selected_at": 200,
        "updated_at": 300,
    }
