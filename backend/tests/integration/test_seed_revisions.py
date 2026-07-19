from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

import aiomysql
import pytest

from backend.domain.seeds import SeedPayload
from backend.http_errors import ProjectBusy, SeedConflict, SeedLocked, SeedNotFound
from backend.repositories.seeds import SeedRepository
from backend.services.seeds import (
    ArchiveSeed,
    CreateSeed,
    DeleteSeed,
    EditSeed,
    RestoreSeed,
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
           (id,project_id,revision,selection_revision,seed_id,seed_revision_id,seed_hash,
            binding_revision_id,binding_hash,channel_profile_key,
            genre_profile_key,quality_charter_version,total_word_min,
            total_word_max,chapter_capacity_policy,reference_manifest_json,
            reference_manifest_hash,content_json,content_hash,confirmed_at)
           VALUES (%s,%s,1,%s,%s,%s,%s,%s,%s,'default','mystery','quality-v1',
                   90000,110000,'按情节自然切章','{}',%s,'{}',%s,3)""",
        (
            creation_id, project_id, seed.selection_revision, seed.id, seed.revision_id,
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


async def install_first_final_chapter(session, project_id: str, seed) -> None:
    bible_id = str(uuid4())
    volume_id = str(uuid4())
    block_id = str(uuid4())
    chapter_session_id = str(uuid4())
    candidate_id = str(uuid4())
    change_set_id = str(uuid4())
    finalization_id = str(uuid4())
    final_chapter_id = str(uuid4())
    bible_hash = "1" * 64
    planning_hash = "2" * 64
    candidate_hash = "3" * 64
    change_set_hash = "4" * 64
    await session.execute(
        """INSERT INTO creation_bible_revisions
           (id,project_id,revision,selection_revision,seed_id,seed_revision_id,
            seed_hash,contract_revision,contract_hash,binding_revision_id,
            binding_hash,policy_version,content_json,content_hash,confirmed_at)
           VALUES (%s,%s,1,%s,%s,%s,%s,1,%s,NULL,NULL,'test-v1','{}',%s,4)""",
        (
            bible_id, project_id, seed.selection_revision, seed.id,
            seed.revision_id, seed.content_hash, "c" * 64, bible_hash,
        ),
    )
    await session.execute(
        """INSERT INTO project_bible_heads
           (project_id,revision,bible_revision_id,content_hash,updated_at)
           VALUES (%s,1,%s,%s,4)""",
        (project_id, bible_id, bible_hash),
    )
    await session.execute(
        """INSERT INTO volume_plans
           (id,project_id,selection_revision,contract_revision,contract_hash,
            bible_revision,bible_hash,manifest_hash,volume_num,title,
            direction_json,revision,status,created_at,updated_at)
           VALUES (%s,%s,%s,1,%s,1,%s,%s,1,'Volume','{}',1,'active',5,5)""",
        (
            volume_id, project_id, seed.selection_revision, "c" * 64,
            bible_hash, planning_hash,
        ),
    )
    await session.execute(
        """INSERT INTO story_blocks
           (id,project_id,volume_plan_id,block_num,title,goal_json,revision,
            status,created_at,updated_at)
           VALUES (%s,%s,%s,1,'Block','{}',1,'active',5,5)""",
        (block_id, project_id, volume_id),
    )
    await session.execute(
        """INSERT INTO chapter_sessions
           (id,project_id,selection_revision,contract_revision,contract_hash,
            bible_revision,bible_hash,volume_plan_id,planning_manifest_hash,
            story_block_id,chapter_num,expected_canon_revision,
            expected_story_block_revision,planning_snapshot_json,status,
            created_at,finalized_at)
           VALUES (%s,%s,%s,1,%s,1,%s,%s,%s,%s,1,0,1,'{}','final',6,7)""",
        (
            chapter_session_id, project_id, seed.selection_revision,
            "c" * 64, bible_hash, volume_id, planning_hash, block_id,
        ),
    )
    await session.execute(
        """INSERT INTO draft_candidates
           (id,project_id,chapter_session_id,working_draft_revision,content,
            content_hash,provenance_json,created_at)
           VALUES (%s,%s,%s,1,'draft',%s,'{}',6)""",
        (candidate_id, project_id, chapter_session_id, candidate_hash),
    )
    await session.execute(
        """INSERT INTO finalization_change_sets
           (id,project_id,draft_candidate_id,extraction_id,candidate_hash,
            expected_canon_revision,expected_story_block_revision,payload_json,
            content_hash,created_at,confirmed_at)
           VALUES (%s,%s,%s,'test-extraction',%s,0,1,'{}',%s,6,7)""",
        (
            change_set_id, project_id, candidate_id, candidate_hash,
            change_set_hash,
        ),
    )
    await session.execute(
        """INSERT INTO finalization_records
           (id,project_id,chapter_session_id,draft_candidate_id,change_set_id,
            idempotency_key,candidate_hash,change_set_hash,
            expected_canon_revision,committed_canon_revision,
            result_payload_json,finalized_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0,1,'{}',7)""",
        (
            finalization_id, project_id, chapter_session_id, candidate_id,
            change_set_id, "5" * 64, candidate_hash, change_set_hash,
        ),
    )
    await session.execute(
        """INSERT INTO final_chapters
           (id,project_id,chapter_session_id,draft_candidate_id,
            finalization_record_id,chapter_num,title,content,content_hash,
            canon_revision,story_block_revision,planning_snapshot_json,
            finalized_at)
           VALUES (%s,%s,%s,%s,%s,1,'Final','final',%s,1,1,'{}',7)""",
        (
            final_chapter_id, project_id, chapter_session_id, candidate_id,
            finalization_id, "6" * 64,
        ),
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
    assert sum(
        isinstance(item, (ProjectBusy, SeedConflict)) for item in outcomes
    ) == 1
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
async def test_project_lock_owner_causes_bounded_seed_busy(disposable_mysql):
    await insert_project(disposable_mysql.session, "p1")
    service = SeedService(
        SeedRepository(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
    )
    created = await service.create(
        CreateSeed(project_id="p1", payload=payload("锁竞争"))
    )
    raw = await aiomysql.connect(
        **{**disposable_mysql.connection_config, "autocommit": False}
    )
    owner = _TestDatabaseSession(raw)
    try:
        await raw.begin()
        await owner.fetchone(
            "SELECT id FROM projects WHERE id='p1' FOR UPDATE"
        )
        with pytest.raises(ProjectBusy):
            await asyncio.wait_for(
                service.edit(
                    EditSeed(
                        project_id="p1", seed_id=created.id,
                        payload=payload("不得等待"),
                        expected_seed_revision=1,
                        expected_selection_revision=0,
                    )
                ),
                timeout=2,
            )
    finally:
        await raw.rollback()
        raw.close()


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
    await install_matching_contract(disposable_mysql.session, "p1", selection)
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

    with pytest.raises(SeedLocked):
        await service.delete(
            DeleteSeed(
                project_id="p1", seed_id=selected_seed.id,
                expected_seed_revision=edited.revision,
                expected_selection_revision=edited.selection_revision,
            )
        )
    assert (await disposable_mysql.session.fetchone(
        "SELECT status FROM creative_seeds WHERE id=%s", (selected_seed.id,)
    ))["status"] == "candidate"

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
async def test_archive_restore_preserves_historically_selected_seed_and_selection_ledger(
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
    seed_a = await service.create(
        CreateSeed(project_id="p1", payload=payload("历史选种"))
    )
    seed_b = await service.create(
        CreateSeed(project_id="p1", payload=payload("当前选种"))
    )
    selection_a = await service.select(
        SelectSeed(
            project_id="p1",
            seed_id=seed_a.id,
            expected_seed_revision=1,
            expected_selection_revision=0,
        )
    )
    selection_b = await service.select(
        SelectSeed(
            project_id="p1",
            seed_id=seed_b.id,
            expected_seed_revision=1,
            expected_selection_revision=selection_a.selection_revision,
        )
    )

    await service.archive(
        ArchiveSeed(
            project_id="p1",
            seed_id=seed_a.id,
            expected_seed_revision=1,
            expected_selection_revision=selection_b.selection_revision,
        )
    )

    archived = await disposable_mysql.session.fetchone(
        "SELECT status FROM creative_seeds WHERE id=%s",
        (seed_a.id,),
    )
    current = await disposable_mysql.session.fetchone(
        """SELECT seed_id,seed_revision_id,selection_revision
             FROM project_selected_seeds WHERE project_id='p1'"""
    )
    history = await disposable_mysql.session.fetchall(
        """SELECT selection_revision,seed_id,seed_revision_id
             FROM project_seed_selection_revisions
            WHERE project_id='p1' ORDER BY selection_revision"""
    )
    assert archived == {"status": "archived"}
    assert await disposable_mysql.session.fetchone(
        "SELECT revision_id,revision FROM creative_seed_heads WHERE seed_id=%s",
        (seed_a.id,),
    ) == {"revision_id": seed_a.revision_id, "revision": 1}
    assert current == {
        "seed_id": seed_b.id,
        "seed_revision_id": seed_b.revision_id,
        "selection_revision": 2,
    }
    assert history == [
        {
            "selection_revision": 1,
            "seed_id": seed_a.id,
            "seed_revision_id": seed_a.revision_id,
        },
        {
            "selection_revision": 2,
            "seed_id": seed_b.id,
            "seed_revision_id": seed_b.revision_id,
        },
    ]

    restored = await service.restore(
        RestoreSeed(
            project_id="p1",
            seed_id=seed_a.id,
            expected_seed_revision=1,
            expected_selection_revision=selection_b.selection_revision,
        )
    )
    assert restored.status == "candidate"
    assert restored.capabilities.canPermanentlyDelete is False
    with pytest.raises(SeedLocked):
        await service.delete(
            DeleteSeed(
                project_id="p1", seed_id=seed_a.id,
                expected_seed_revision=1,
                expected_selection_revision=selection_b.selection_revision,
            )
        )


@pytest.mark.asyncio
async def test_a_to_b_to_a_never_revives_old_contract_generation(disposable_mysql):
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
    seed_a = await service.create(CreateSeed(project_id="p1", payload=payload("A")))
    seed_b = await service.create(CreateSeed(project_id="p1", payload=payload("B")))
    first_a = await service.select(
        SelectSeed(
            project_id="p1", seed_id=seed_a.id,
            expected_seed_revision=1, expected_selection_revision=0,
        )
    )
    await install_matching_contract(disposable_mysql.session, "p1", first_a)
    selected_b = await service.select(
        SelectSeed(
            project_id="p1", seed_id=seed_b.id,
            expected_seed_revision=1,
            expected_selection_revision=first_a.selection_revision,
        )
    )
    third_generation = await service.select(
        SelectSeed(
            project_id="p1", seed_id=seed_a.id,
            expected_seed_revision=1,
            expected_selection_revision=selected_b.selection_revision,
        )
    )

    active = await service.get_selected("p1")
    old_contract = await disposable_mysql.session.fetchone(
        """SELECT selection_revision,seed_id,seed_revision_id,seed_hash
             FROM creation_contracts WHERE project_id='p1'"""
    )

    assert third_generation.selection_revision == 3
    assert active.active_selection.selection_revision == 3
    assert active.active_selection.seed_id == seed_a.id
    assert active.seed_ready is False
    assert active.contract_ready is False
    assert active.reasons == ("selected_seed_drift",)
    assert old_contract == {
        "selection_revision": 1,
        "seed_id": seed_a.id,
        "seed_revision_id": seed_a.revision_id,
        "seed_hash": seed_a.content_hash,
    }


@pytest.mark.asyncio
async def test_first_final_chapter_locks_only_selection_history(disposable_mysql):
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
    historical = await service.create(
        CreateSeed(project_id="p1", payload=payload("历史"))
    )
    selected = await service.create(
        CreateSeed(project_id="p1", payload=payload("当前"))
    )
    free = await service.create(
        CreateSeed(project_id="p1", payload=payload("未引用"))
    )
    historical_selection = await service.select(
        SelectSeed(
            project_id="p1", seed_id=historical.id,
            expected_seed_revision=1, expected_selection_revision=0,
        )
    )
    active = await service.select(
        SelectSeed(
            project_id="p1", seed_id=selected.id,
            expected_seed_revision=1,
            expected_selection_revision=historical_selection.selection_revision,
        )
    )
    await install_matching_contract(disposable_mysql.session, "p1", active)
    await install_first_final_chapter(disposable_mysql.session, "p1", active)

    created_after_final = await service.create(
        CreateSeed(project_id="p1", payload=payload("定稿后候选"))
    )
    edited_free = await service.edit(
        EditSeed(
            project_id="p1", seed_id=free.id, payload=payload("未引用改"),
            expected_seed_revision=1,
            expected_selection_revision=active.selection_revision,
        )
    )
    await service.delete(
        DeleteSeed(
            project_id="p1", seed_id=created_after_final.id,
            expected_seed_revision=1,
            expected_selection_revision=active.selection_revision,
        )
    )
    archived = await service.archive(
        ArchiveSeed(
            project_id="p1", seed_id=historical.id,
            expected_seed_revision=1,
            expected_selection_revision=active.selection_revision,
        )
    )
    restored = await service.restore(
        RestoreSeed(
            project_id="p1", seed_id=historical.id,
            expected_seed_revision=1,
            expected_selection_revision=active.selection_revision,
        )
    )

    assert edited_free.revision == 2
    assert archived.status == "archived"
    assert restored.status == "candidate"
    assert await disposable_mysql.session.fetchone(
        "SELECT id FROM creative_seeds WHERE id=%s",
        (created_after_final.id,),
    ) is None
    listed = {item.id: item for item in await service.list("p1")}
    historical_facts = listed[historical.id].capabilities
    selected_facts = listed[selected.id].capabilities
    free_facts = listed[free.id].capabilities
    assert (
        historical_facts.referenced,
        historical_facts.hasFinalChapters,
        historical_facts.canEdit,
        historical_facts.canArchive,
        historical_facts.canPermanentlyDelete,
    ) == (True, True, False, True, False)
    assert (
        selected_facts.referenced,
        selected_facts.canEdit,
        selected_facts.canSelect,
        selected_facts.canArchive,
        selected_facts.canPermanentlyDelete,
    ) == (True, False, False, False, False)
    assert (
        free_facts.referenced,
        free_facts.canEdit,
        free_facts.canSelect,
        free_facts.canArchive,
        free_facts.canPermanentlyDelete,
    ) == (False, True, False, True, True)

    with pytest.raises(SeedLocked):
        await service.edit(
            EditSeed(
                project_id="p1", seed_id=selected.id,
                payload=payload("不得改"), expected_seed_revision=1,
                expected_selection_revision=active.selection_revision,
            )
        )
    with pytest.raises(SeedLocked):
        await service.select(
            SelectSeed(
                project_id="p1", seed_id=free.id,
                expected_seed_revision=edited_free.revision,
                expected_selection_revision=active.selection_revision,
            )
        )
    with pytest.raises(SeedLocked):
        await service.delete(
            DeleteSeed(
                project_id="p1", seed_id=historical.id,
                expected_seed_revision=1,
                expected_selection_revision=active.selection_revision,
            )
        )


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
