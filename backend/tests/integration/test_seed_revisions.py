from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from uuid import uuid4

import aiomysql
import pytest

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.seeds import (
    SeedInspirationFailure,
    SeedPayload,
    SeedProvenanceSelection,
)
from backend.http_errors import (
    ProjectArchived,
    ProjectBusy,
    SeedConflict,
    SeedLocked,
    SeedNotFound,
)
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
from backend.services.seed_generation import (
    GenerateSeedInspiration,
    SeedGenerationService,
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


@pytest.mark.asyncio
async def test_archived_project_retains_readable_seed_state_but_rejects_mutations(
    disposable_mysql,
):
    async def complete_seed_state():
        session = disposable_mysql.session
        return {
            "identities": await session.fetchall(
                """SELECT id,project_id,status,created_at,updated_at
                     FROM creative_seeds WHERE project_id='p1' ORDER BY id"""
            ),
            "heads": await session.fetchall(
                """SELECT h.seed_id,h.revision_id,h.revision,h.content_hash,
                          h.updated_at
                     FROM creative_seed_heads h
                     JOIN creative_seeds s ON s.id=h.seed_id
                    WHERE s.project_id='p1' ORDER BY h.seed_id"""
            ),
            "revisions": await session.fetchall(
                """SELECT id,project_id,seed_id,revision,payload_json,
                          content_hash,created_at
                     FROM creative_seed_revisions
                    WHERE project_id='p1' ORDER BY seed_id,revision"""
            ),
            "selection": await session.fetchall(
                """SELECT project_id,seed_id,seed_revision_id,seed_hash,
                          selection_revision,selected_at,updated_at
                     FROM project_selected_seeds
                    WHERE project_id='p1'"""
            ),
            "selection_ledger": await session.fetchall(
                """SELECT project_id,selection_revision,seed_id,
                          seed_revision_id,seed_hash,selected_at
                     FROM project_seed_selection_revisions
                    WHERE project_id='p1' ORDER BY selection_revision"""
            ),
        }

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
    seed = await service.create(CreateSeed(project_id="p1", payload=payload("保留")))
    selection = await service.select(
        SelectSeed(
            project_id="p1",
            seed_id=seed.id,
            expected_seed_revision=seed.revision,
            expected_selection_revision=0,
        )
    )
    restorable = await service.create(
        CreateSeed(project_id="p1", payload=payload("已归档候选"))
    )
    await service.archive(
        ArchiveSeed(
            project_id="p1",
            seed_id=restorable.id,
            expected_seed_revision=restorable.revision,
            expected_selection_revision=selection.selection_revision,
        )
    )
    await disposable_mysql.session.execute(
        """UPDATE projects
              SET archived_at=2,lifecycle_revision=lifecycle_revision+1
            WHERE id='p1'"""
    )
    state_before = await complete_seed_state()

    listed = await service.list("p1")
    selected = await service.get_selected("p1")

    assert {item.id: item.status for item in listed} == {
        seed.id: "candidate",
        restorable.id: "archived",
    }
    assert selected.active_selection is not None
    assert selected.active_selection.seed_id == seed.id
    assert selected.active_selection.selection_revision == 1

    commands = (
        lambda: service.create(
            CreateSeed(project_id="p1", payload=payload("禁止创建"))
        ),
        lambda: service.edit(
            EditSeed(
                project_id="p1",
                seed_id=seed.id,
                payload=payload("禁止编辑"),
                expected_seed_revision=seed.revision,
                expected_selection_revision=selection.selection_revision,
            )
        ),
        lambda: service.select(
            SelectSeed(
                project_id="p1",
                seed_id=seed.id,
                expected_seed_revision=seed.revision,
                expected_selection_revision=selection.selection_revision,
            )
        ),
        lambda: service.delete(
            DeleteSeed(
                project_id="p1",
                seed_id=seed.id,
                expected_seed_revision=seed.revision,
                expected_selection_revision=selection.selection_revision,
            )
        ),
        lambda: service.archive(
            ArchiveSeed(
                project_id="p1",
                seed_id=seed.id,
                expected_seed_revision=seed.revision,
                expected_selection_revision=selection.selection_revision,
            )
        ),
        lambda: service.restore(
            RestoreSeed(
                project_id="p1",
                seed_id=restorable.id,
                expected_seed_revision=restorable.revision,
                expected_selection_revision=selection.selection_revision,
            )
        ),
    )
    for command in commands:
        with pytest.raises(ProjectArchived):
            await command()
        assert await complete_seed_state() == state_before

    state_after = await complete_seed_state()
    assert state_after == state_before


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


@pytest.mark.asyncio
async def test_explicit_ai_chat_save_freezes_provenance_and_replays_exactly_once(
    disposable_mysql,
):
    project_id = "p1"
    source_id = str(uuid4())
    policy_id = str(uuid4())
    snapshot_id = str(uuid4())
    manifest_id = str(uuid4())
    binding_id = str(uuid4())
    analysis_id = str(uuid4())
    attempt_id = str(uuid4())
    await insert_project(disposable_mysql.session, project_id)
    await disposable_mysql.session.execute(
        """INSERT INTO market_sources
           (id,stable_key,adapter_key,display_name,public_config_json,status,
            created_at,updated_at)
           VALUES (%s,'test-source','manual_snapshot','Test','{}','active',1,1)""",
        (source_id,),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO market_source_policy_revisions
           (id,source_id,revision,policy_status,policy_version,checked_at,
            evidence_url,evidence_hash,allowed_origins_json,path_prefixes_json,
            enabled,interval_minutes,next_run_at,content_hash,created_at)
           VALUES (%s,%s,1,'manual_only','test-v1',1,
                   'https://www.qidian.com/rank/newsign/',%s,'[]','[]',
                   0,360,NULL,%s,1)""",
        (policy_id, source_id, "1" * 64, "2" * 64),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO market_snapshots
           (id,source_id,captured_at,platform,ranking_name,category,source_url,
            content_hash,entry_count,created_at)
           VALUES (%s,%s,10,'qidian','newsign','male',
                   'https://www.qidian.com/rank/newsign/',%s,1,10)""",
        (snapshot_id, source_id, "3" * 64),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO market_snapshot_manifests
           (id,source_id,snapshot_id,snapshot_hash,policy_revision_id,
            policy_revision,policy_hash,adapter_version,manifest_json,
            manifest_hash,created_at)
           VALUES (%s,%s,%s,%s,%s,1,%s,'manual-v1','{}',%s,10)""",
        (
            manifest_id,
            source_id,
            snapshot_id,
            "3" * 64,
            policy_id,
            "2" * 64,
            "4" * 64,
        ),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO project_model_binding_revisions
           (id,project_id,revision,content_hash,source_project_id,created_at)
           VALUES (%s,%s,1,%s,NULL,2)""",
        (binding_id, project_id, "5" * 64),
    )
    analysis_manifest = (
        '{"binding":{"hash":"' + "5" * 64 + '","revisionId":"' + binding_id
        + '"},"promptPolicyVersion":"market-analysis-policy-v1",'
        + '"snapshots":[{"hash":"' + "3" * 64 + '","id":"' + snapshot_id
        + '","manifestHash":"' + "4" * 64 + '","sourceId":"' + source_id
        + '"}]}'
    )
    await disposable_mysql.session.execute(
        """INSERT INTO market_analyses
           (id,project_id,binding_revision_id,binding_hash,input_manifest_json,
            input_manifest_hash,policy_version,idempotency_key,request_hash,
            status,analysis_json,result_hash,public_error_code,created_at,
            completed_at)
           VALUES (%s,%s,%s,%s,%s,%s,'market-analysis-policy-v1',%s,%s,
                   'succeeded','{}',%s,NULL,20,21)""",
        (
            analysis_id,
            project_id,
            binding_id,
            "5" * 64,
            analysis_manifest,
            "6" * 64,
            "a" * 64,
            "b" * 64,
            "7" * 64,
        ),
    )
    inspiration_manifest = (
        '{"analysis":{"hash":"' + "7" * 64 + '","id":"' + analysis_id
        + '"},"binding":{"hash":"' + "5" * 64 + '","revisionId":"' + binding_id
        + '"},"snapshot":{"hash":"' + "3" * 64 + '","id":"' + snapshot_id
        + '","manifestHash":"' + "4" * 64 + '"},"transcriptHash":"' + "8" * 64
        + '"}'
    )
    assistant = (
        '{"content":"以永乐大典为冲突发动机。","role":"assistant"}'
    )
    await disposable_mysql.session.execute(
        """INSERT INTO seed_inspiration_attempts
           (id,project_id,selection_revision,market_source_id,
            market_snapshot_id,market_snapshot_hash,market_analysis_id,
            market_analysis_hash,binding_revision_id,binding_hash,
            input_manifest_json,input_manifest_hash,status,result_json,
            result_hash,public_error_code,created_at,completed_at)
           VALUES (%s,%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,'succeeded',
                   %s,%s,NULL,30,31)""",
        (
            attempt_id,
            project_id,
            source_id,
            snapshot_id,
            "3" * 64,
            analysis_id,
            "7" * 64,
            binding_id,
            "5" * 64,
            inspiration_manifest,
            "8" * 64,
            assistant,
            "9" * 64,
        ),
    )
    service = SeedService(
        SeedRepository(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
        connection_factory=connection_factory_for(
            disposable_mysql.connection_config
        ),
    )
    command = CreateSeed(
        project_id=project_id,
        payload=payload("显式保存"),
        provenance=SeedProvenanceSelection(
            kind="ai_chat",
            snapshotIds=(snapshot_id,),
            analysisId=analysis_id,
            inspirationAttemptId=attempt_id,
            publicNotes=("作者已编辑最终九字段。",),
        ),
        idempotency_key="s" * 64,
    )

    first = await service.create(command)
    replay = await service.create(command)

    assert replay == first
    assert first.content_hash == canonical_hash(payload("显式保存"))
    assert first.content_hash != first.provenance.provenance_hash
    assert first.provenance.kind == "ai_chat"
    assert first.provenance.snapshots[0].hash == "3" * 64
    assert first.provenance.analysis.hash == "7" * 64
    assert first.provenance.inspiration_attempt.result_hash == "9" * 64
    assert await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM creative_seed_revisions WHERE project_id=%s",
        (project_id,),
    ) == {"count": 1}


@pytest.mark.asyncio
async def test_plural_inspiration_attempt_is_transient_and_real_repository_replays_once(
    disposable_mysql,
):
    project_id = "p1"
    provider_id = str(uuid4())
    binding_id = str(uuid4())
    await insert_project(disposable_mysql.session, project_id)
    await disposable_mysql.session.execute(
        """INSERT INTO provider_profiles
           (id,name,provider_type,model_name,base_url,api_key,enabled,sort_order,
            stream,max_context_tokens,max_output_tokens,temperature,top_p,
            supports_json,supports_streaming,notes,thinking,lifecycle_status,
            revision,deleted_at,created_at,updated_at)
           VALUES (%s,'Seed Test','openai-compatible','deepseek-v4-flash',
                   'https://provider.invalid/v1','PRIVATE_TEST_KEY',1,0,0,
                   64000,1600,0.700,0.950,1,1,'','{}','active',1,NULL,1,1)""",
        (provider_id,),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO project_model_binding_revisions
           (id,project_id,revision,content_hash,source_project_id,created_at)
           VALUES (%s,%s,1,%s,NULL,2)""",
        (binding_id, project_id, "5" * 64),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO project_model_binding_items
           (binding_revision_id,task_key,resolution_status,provider_id,
            provider_name_snapshot,model_name_snapshot,item_hash)
           VALUES (%s,'seed','bound',%s,'Seed Test','deepseek-v4-flash',%s)""",
        (binding_id, provider_id, "6" * 64),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO project_model_binding_heads
           (project_id,revision,binding_revision_id,content_hash,updated_at)
           VALUES (%s,1,%s,%s,2)""",
        (project_id, binding_id, "5" * 64),
    )
    snapshot_rows = []
    for index, (platform, source_url) in enumerate(
        (
            ("qidian", "https://www.qidian.com/rank/newsign/"),
            ("qq_reading", "https://book.qq.com/book-rank"),
        ),
        1,
    ):
        source_id = str(uuid4())
        policy_id = str(uuid4())
        snapshot_id = str(uuid4())
        snapshot_hash = str(index) * 64
        manifest_hash = chr(96 + index) * 64
        await disposable_mysql.session.execute(
            """INSERT INTO market_sources
               (id,stable_key,adapter_key,display_name,public_config_json,status,
                created_at,updated_at)
               VALUES (%s,%s,'manual_snapshot',%s,'{}','active',1,1)""",
            (source_id, f"integration-{index}", f"Source {index}"),
        )
        await disposable_mysql.session.execute(
            """INSERT INTO market_source_policy_revisions
               (id,source_id,revision,policy_status,policy_version,checked_at,
                evidence_url,evidence_hash,allowed_origins_json,
                path_prefixes_json,enabled,interval_minutes,next_run_at,
                content_hash,created_at)
               VALUES (%s,%s,1,'manual_only','test-v1',1,%s,%s,'[]','[]',
                       0,360,NULL,%s,1)""",
            (policy_id, source_id, source_url, "7" * 64, "8" * 64),
        )
        await disposable_mysql.session.execute(
            """INSERT INTO market_snapshots
               (id,source_id,captured_at,platform,ranking_name,category,
                source_url,content_hash,entry_count,created_at)
               VALUES (%s,%s,%s,%s,'rank','male',%s,%s,1,%s)""",
            (
                snapshot_id,
                source_id,
                10 + index,
                platform,
                source_url,
                snapshot_hash,
                10 + index,
            ),
        )
        await disposable_mysql.session.execute(
            """INSERT INTO market_snapshot_manifests
               (id,source_id,snapshot_id,snapshot_hash,policy_revision_id,
                policy_revision,policy_hash,adapter_version,manifest_json,
                manifest_hash,created_at)
               VALUES (%s,%s,%s,%s,%s,1,%s,'manual-v1','{}',%s,%s)""",
            (
                str(uuid4()),
                source_id,
                snapshot_id,
                snapshot_hash,
                policy_id,
                "8" * 64,
                manifest_hash,
                10 + index,
            ),
        )
        await disposable_mysql.session.execute(
            """INSERT INTO market_snapshot_entries
               (id,source_id,snapshot_id,rank_number,title,author,category,
                work_url,public_metrics_json,content_hash,created_at)
               VALUES (%s,%s,%s,1,%s,%s,'玄幻',%s,'{}',%s,%s)""",
            (
                str(uuid4()),
                source_id,
                snapshot_id,
                f"公开作品{index}",
                f"公开作者{index}",
                f"https://example.com/book/{index}",
                "9" * 64,
                10 + index,
            ),
        )
        snapshot_rows.append(
            {
                "id": snapshot_id,
                "sourceId": source_id,
                "hash": snapshot_hash,
                "manifestHash": manifest_hash,
            }
        )
    analysis_id = str(uuid4())
    analysis_manifest = {
        "snapshots": snapshot_rows,
        "binding": {"revisionId": binding_id, "hash": "5" * 64},
        "promptPolicyVersion": "market-analysis-policy-v1",
    }
    snapshot_ids = tuple(item["id"] for item in snapshot_rows)
    analysis_json = {
        "currentHeat": [
            {
                "text": "两份公开榜单均出现穿越升级题材。",
                "snapshotIds": list(snapshot_ids),
                "inference": False,
            }
        ],
        "growthDirections": [],
        "crowding": [],
        "opportunities": [],
        "uncertainties": [],
        "sourceCoverage": {
            "snapshotIds": list(snapshot_ids),
            "summary": "两份冻结公开榜单。",
        },
    }
    await disposable_mysql.session.execute(
        """INSERT INTO market_analyses
           (id,project_id,binding_revision_id,binding_hash,input_manifest_json,
            input_manifest_hash,policy_version,idempotency_key,request_hash,
            status,analysis_json,result_hash,public_error_code,created_at,
            completed_at)
           VALUES (%s,%s,%s,%s,%s,%s,'market-analysis-policy-v1',%s,%s,
                   'succeeded',%s,%s,NULL,20,21)""",
        (
            analysis_id,
            project_id,
            binding_id,
            "5" * 64,
            canonical_json(analysis_manifest),
            canonical_hash(analysis_manifest),
            "a" * 64,
            "b" * 64,
            canonical_json(analysis_json),
            "c" * 64,
        ),
    )

    class FakeGateway:
        calls = 0

        async def generate(self, **_values):
            self.calls += 1
            return "把知识优势拆成三次递进兑现，并让群像角色争夺解释权。"

    gateway = FakeGateway()
    ids = iter((str(uuid4()), str(uuid4())))
    service = SeedGenerationService(
        SeedRepository(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
        connection_factory=connection_factory_for(
            disposable_mysql.connection_config
        ),
        provider_gateway=gateway,
        id_factory=lambda: next(ids),
        clock=lambda: 100,
    )
    command = GenerateSeedInspiration(
        project_id=project_id,
        transcript=({"role": "user", "content": "写一个明代穿越群像故事。"},),
        snapshot_ids=snapshot_ids,
        analysis_id=analysis_id,
        idempotency_key="i" * 64,
    )

    first = await service.generate(command)
    replay = await service.generate(command)

    assert first == replay
    assert first.status == "succeeded"
    assert gateway.calls == 1
    assert await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM creative_seeds WHERE project_id=%s",
        (project_id,),
    ) == {"count": 0}
    stored = await disposable_mysql.session.fetchone(
        """SELECT input_manifest_json,result_json
             FROM seed_inspiration_attempts WHERE project_id=%s""",
        (project_id,),
    )
    manifest = stored["input_manifest_json"]
    if isinstance(manifest, str):
        manifest = json.loads(manifest)
    assert [item["id"] for item in manifest["snapshots"]] == list(snapshot_ids)
    assert "写一个明代穿越群像故事" not in canonical_json(manifest)
    result_json = stored["result_json"]
    if isinstance(result_json, str):
        result_json = json.loads(result_json)
    assert result_json == {
        "content": "把知识优势拆成三次递进兑现，并让群像角色争夺解释权。",
        "role": "assistant",
    }

    class BlockingReservationRepository(SeedRepository):
        def __init__(self):
            self.reservation_started = asyncio.Event()
            self.release_reservation = asyncio.Event()
            self.follower_lock_started = asyncio.Event()
            self.lock_calls = 0

        async def lock_inspiration_project(self, session, requested_project_id):
            self.lock_calls += 1
            if self.lock_calls == 2:
                self.follower_lock_started.set()
            return await super().lock_inspiration_project(
                session,
                requested_project_id,
            )

        async def insert_inspiration_request(self, session, row):
            await super().insert_inspiration_request(session, row)
            self.reservation_started.set()
            await self.release_reservation.wait()

    class BlockingGateway:
        def __init__(self):
            self.calls = 0
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def generate(self, **_values):
            self.calls += 1
            self.started.set()
            await self.release.wait()
            return "把知识优势拆成三次递进兑现，并让群像角色争夺解释权。"

    repository = BlockingReservationRepository()
    concurrent_gateway = BlockingGateway()
    concurrent_ids = iter((str(uuid4()), str(uuid4())))
    concurrent_service = SeedGenerationService(
        repository,
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
        connection_factory=connection_factory_for(
            disposable_mysql.connection_config
        ),
        provider_gateway=concurrent_gateway,
        id_factory=lambda: next(concurrent_ids),
        clock=lambda: 200,
    )
    concurrent_command = command.model_copy(
        update={"idempotency_key": "j" * 64}
    )
    owner = asyncio.create_task(concurrent_service.generate(concurrent_command))
    follower = None
    try:
        await asyncio.wait_for(repository.reservation_started.wait(), timeout=2)
        follower = asyncio.create_task(
            concurrent_service.generate(concurrent_command)
        )
        await asyncio.wait_for(
            repository.follower_lock_started.wait(),
            timeout=2,
        )
        with pytest.raises(SeedInspirationFailure) as in_progress:
            await asyncio.wait_for(follower, timeout=2)
        assert in_progress.value.code == "SEED_INSPIRATION_IN_PROGRESS"

        repository.release_reservation.set()
        await asyncio.wait_for(concurrent_gateway.started.wait(), timeout=2)
        concurrent_gateway.release.set()
        concurrent_result = await asyncio.wait_for(owner, timeout=2)
        concurrent_replay = await asyncio.wait_for(
            concurrent_service.generate(concurrent_command),
            timeout=2,
        )
    finally:
        repository.release_reservation.set()
        concurrent_gateway.release.set()
        pending = tuple(
            task
            for task in (owner, follower)
            if task is not None and not task.done()
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    assert concurrent_result.status == "succeeded"
    assert concurrent_replay == concurrent_result
    assert concurrent_gateway.calls == 1

    publication_attempt_locked = asyncio.Event()
    release_publication = asyncio.Event()
    create_snapshot_locked = asyncio.Event()
    publication_attempt_id = str(uuid4())
    publication_request_id = str(uuid4())
    base_publication_transaction = transaction_factory_for(
        disposable_mysql.connection_config
    )
    publication_transaction_count = 0

    class PublicationBarrierSession:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def fetchone(self, sql, args=None):
            row = await self._inner.fetchone(sql, args)
            normalized = " ".join(sql.split())
            if normalized.startswith(
                "SELECT status FROM seed_inspiration_attempts"
            ):
                publication_attempt_locked.set()
                await release_publication.wait()
            return row

    @asynccontextmanager
    async def publication_transaction():
        nonlocal publication_transaction_count
        publication_transaction_count += 1
        call = publication_transaction_count
        async with base_publication_transaction() as session:
            yield (
                PublicationBarrierSession(session)
                if call == 2
                else session
            )

    base_create_transaction = transaction_factory_for(
        disposable_mysql.connection_config
    )

    class CreateBarrierSession:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def fetchall(self, sql, args=None):
            rows = await self._inner.fetchall(sql, args)
            if (
                "FROM market_snapshots snapshot" in sql
                and "snapshot.source_url" in sql
            ):
                create_snapshot_locked.set()
            return rows

    @asynccontextmanager
    async def create_transaction():
        async with base_create_transaction() as session:
            yield CreateBarrierSession(session)

    publication_gateway = FakeGateway()
    publication_service = SeedGenerationService(
        SeedRepository(),
        transaction_factory=publication_transaction,
        connection_factory=connection_factory_for(
            disposable_mysql.connection_config
        ),
        provider_gateway=publication_gateway,
        id_factory=iter(
            (publication_request_id, publication_attempt_id)
        ).__next__,
        clock=lambda: 300,
    )
    publication_command = command.model_copy(
        update={"idempotency_key": "k" * 64}
    )
    seed_service = SeedService(
        SeedRepository(),
        transaction_factory=create_transaction,
        connection_factory=connection_factory_for(
            disposable_mysql.connection_config
        ),
        clock=lambda: 301,
    )
    create_command = CreateSeed(
        project_id=project_id,
        payload=payload("并发显式保存"),
        provenance=SeedProvenanceSelection(
            kind="ai_chat",
            snapshotIds=snapshot_ids,
            analysisId=analysis_id,
            inspirationAttemptId=publication_attempt_id,
            publicNotes=("作者已编辑最终九字段。",),
        ),
        idempotency_key="t" * 64,
    )
    publication_task = asyncio.create_task(
        publication_service.generate(publication_command)
    )
    create_task = None
    snapshot_locked_before_release = False
    try:
        await asyncio.wait_for(publication_attempt_locked.wait(), timeout=2)
        create_task = asyncio.create_task(seed_service.create(create_command))
        try:
            await asyncio.wait_for(
                create_snapshot_locked.wait(),
                timeout=0.25,
            )
            snapshot_locked_before_release = True
        except TimeoutError:
            pass
        release_publication.set()
        publication_result, created_seed = await asyncio.wait_for(
            asyncio.gather(publication_task, create_task),
            timeout=4,
        )
    finally:
        release_publication.set()
        pending = tuple(
            item
            for item in (publication_task, create_task)
            if item is not None and not item.done()
        )
        for item in pending:
            item.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    assert snapshot_locked_before_release is False
    assert publication_result.status == "succeeded"
    assert created_seed.provenance.inspiration_attempt.id == (
        publication_attempt_id
    )
    publication_replay = await publication_service.generate(
        publication_command
    )
    assert publication_replay == publication_result
    assert publication_gateway.calls == 1
    assert await disposable_mysql.session.fetchone(
        """SELECT COUNT(*) AS count
             FROM seed_inspiration_requests
            WHERE project_id=%s AND status='reserved'""",
        (project_id,),
    ) == {"count": 0}
    assert await disposable_mysql.session.fetchone(
        """SELECT COUNT(*) AS count
             FROM seed_inspiration_attempts
            WHERE project_id=%s AND status='running'""",
        (project_id,),
    ) == {"count": 0}
