from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
from uuid import uuid4

import aiomysql
import pytest

from backend.domain.canon import (
    AssertionOperator,
    CanonEventInput,
    ConfirmationStatus,
    FactKind,
    ValueCardinality,
)
from backend.domain.chapter_outlines import (
    DraftChapterOutline,
    OutlineCapacityPolicy,
    normalize_chapter_outline,
)
from backend.domain.bibles import BiblePayload, canonical_bible_hash
from backend.domain.contracts import CreationContractPayload, StyleContractPayload
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.planning import DraftPlanningAggregate, normalize_planning_aggregate
from backend.domain.seeds import (
    SeedInspirationFailure,
    SeedPayload,
    SeedProvenanceSelection,
)
from backend.domain.story_engines import StoryEngineOption
from backend.http_errors import (
    ProjectArchived,
    ProjectBusy,
    SeedAlreadyConfirmed,
    SeedConflict,
    SeedLocked,
    SeedNotFound,
)
from backend.repositories.seeds import SeedRepository
from backend.repositories.canon import CanonRepository
from backend.services.canon import (
    CanonEventCreate,
    CanonService,
    CommitCanonRevision,
)
from backend.services.contracts import style_contract_hash
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
from backend.services.project_lifecycle import ProjectLifecycleService
from backend.services.projections import build_projection_bundle
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


async def _release_and_reap_first_request(first_request, release):
    release.set()
    try:
        return await asyncio.wait_for(asyncio.shield(first_request), timeout=2)
    finally:
        if not first_request.done():
            first_request.cancel()
        await asyncio.gather(first_request, return_exceptions=True)


async def insert_project(session, project_id: str):
    await session.execute(
        """INSERT INTO projects
           (id,title,genre,description,target_words,target_chapters,status,
            current_chapter,created_at,updated_at)
           VALUES (%s,'Integration','悬疑','test',100000,100,'drafting',0,1,1)""",
        (project_id,),
    )


@pytest.mark.asyncio
async def test_release_and_reap_first_request_cancels_a_timed_out_task():
    blocked = asyncio.Event()
    first_request = asyncio.create_task(blocked.wait())
    try:
        with pytest.raises(asyncio.TimeoutError):
            await _release_and_reap_first_request(first_request, asyncio.Event())
        assert first_request.done()
        assert first_request.cancelled()
    finally:
        if not first_request.done():
            first_request.cancel()
        await asyncio.gather(first_request, return_exceptions=True)


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
    restorable = await service.create(
        CreateSeed(project_id="p1", payload=payload("已归档候选"))
    )
    selection = await service.select(
        SelectSeed(
            project_id="p1",
            seed_id=seed.id,
            expected_seed_revision=seed.revision,
            expected_selection_revision=0,
        )
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


async def install_matching_contract(
    session,
    project_id: str,
    seed,
    *,
    use_existing_foundation: bool = False,
):
    if use_existing_foundation:
        binding = await session.fetchone(
            """SELECT binding_revision_id,content_hash
                 FROM project_model_binding_heads WHERE project_id=%s""",
            (project_id,),
        )
        binding_id = binding["binding_revision_id"]
        binding_hash = binding["content_hash"]
    else:
        binding_id = str(uuid4())
        binding_hash = "b" * 64
        await session.execute(
            """INSERT INTO project_model_binding_revisions
               (id,project_id,revision,content_hash,source_project_id,created_at)
               VALUES (%s,%s,1,%s,NULL,2)""",
            (binding_id, project_id, binding_hash),
        )
    creation_id = str(uuid4())
    style_id = str(uuid4())
    seed_row = await session.fetchone(
        "SELECT payload_json FROM creative_seed_revisions WHERE id=%s",
        (seed.revision_id,),
    )
    selected_seed = SeedPayload.model_validate(
        json.loads(seed_row["payload_json"])
        if isinstance(seed_row["payload_json"], str)
        else seed_row["payload_json"],
        strict=True,
    )
    engine = StoryEngineOption(
        name="档案追索",
        storyPromise="沿失踪档案持续揭开时间异常。",
        protagonistDesire="找回失踪的姐姐。",
        sustainedPressure="城市记忆不断被改写。",
        growthDirection="从孤身查案成长为守护共同记忆的人。",
        conflictLoop="发现缺页、追查证词、承担改写代价。",
        ensembleRoles=({"role": "同伴", "purpose": "挑战主角的判断。"},),
        advantageAndCost="能读取残留记忆，但会遗忘私人经历。",
        satisfactionSources=("真相翻转",),
        longFormVariation=("个人、城市、时代三层记忆危机。",),
        endingAnchor="主角保住共同记忆并接受个人代价。",
        risks=("档案结构重复",),
        differentiation="档案缺页直接呈现时间改写。",
    )
    creation = CreationContractPayload(
        schemaVersion="creation-contract-v1",
        channelProfileKey="web-fiction",
        genreProfileKey="mystery",
        qualityCharterVersion="quality-v1",
        selectionRevision=seed.selection_revision,
        selectedSeed=selected_seed,
        seedRevisionId=seed.revision_id,
        seedHash=seed.content_hash,
        selectedEngine=engine,
        engineOptionId="engine-option-1",
        engineHash=canonical_hash(engine),
        primaryStyleRef={
            "id": "style-primary", "revision": 1, "contentHash": "a" * 64,
        },
        secondaryStyleRef=None,
        experienceCardRefs=(),
        corpusSourceRefs=(),
        targetTotalWords=100_000,
        expectedVolumeCount=1,
        expectedChapterCount=30,
        chapterWordRangePreference=(2_500, 3_500),
        prohibitedDirections=("不写无代价升级",),
        authorNotes="人物选择优先。",
        modelBindingRef={
            "id": binding_id, "revision": 1, "contentHash": binding_hash,
        },
    )
    style = StyleContractPayload(
        schemaVersion="style-contract-v1",
        readingExperience="清楚好读",
        narrativeDistance="近距离第三人称",
        sentenceParagraphRhythm="行动短促，反思舒展",
        dictionDensity="低修辞密度",
        dialogueAndSubtext="对白体现人物立场",
        characterVoices=("主角克制", "同伴直接"),
        emotionAndInteriority="用选择承载情绪",
        actionExplanationEnvironment="先动作后解释",
        primaryRules=("讲清故事",),
        secondaryFlavor=None,
        risks=("节奏过快",),
    )
    creation_json = canonical_json(creation)
    creation_hash = canonical_hash(creation)
    style_json = canonical_json(style)
    style_hash = style_contract_hash(style, (), ())
    reference_manifest = {
        "schemaVersion": "contract-reference-manifest-v1",
        "seedRef": {
            "id": seed.id,
            "revisionId": seed.revision_id,
            "contentHash": seed.content_hash,
        },
        "engineRef": {
            "id": "engine-option-1",
            "batchId": "engine-batch-1",
            "contentHash": canonical_hash(engine),
        },
        "bindingRef": {
            "id": binding_id,
            "revision": 1,
            "contentHash": binding_hash,
        },
        "styleRefs": [{
            "id": "style-primary",
            "revision": 1,
            "contentHash": "a" * 64,
        }],
        "experienceCardRefs": [],
        "corpusSourceRefs": [],
    }
    reference_manifest_json = canonical_json(reference_manifest)
    reference_manifest_hash = canonical_hash(reference_manifest)
    capacity_policy = canonical_json({
        "expectedVolumeCount": creation.expectedVolumeCount,
        "expectedChapterCount": creation.expectedChapterCount,
        "chapterWordRangePreference": list(
            creation.chapterWordRangePreference
        ),
    })
    await session.execute(
        """INSERT INTO creation_contracts
           (id,project_id,revision,selection_revision,seed_id,seed_revision_id,seed_hash,
            binding_revision_id,binding_hash,channel_profile_key,
            genre_profile_key,quality_charter_version,total_word_min,
            total_word_max,chapter_capacity_policy,reference_manifest_json,
            reference_manifest_hash,content_json,content_hash,confirmed_at)
           VALUES (%s,%s,1,%s,%s,%s,%s,%s,%s,'web-fiction','mystery','quality-v1',
                   100000,100000,%s,%s,%s,%s,%s,3)""",
        (
            creation_id, project_id, seed.selection_revision, seed.id, seed.revision_id,
            seed.content_hash, binding_id, binding_hash,
            capacity_policy,
            reference_manifest_json, reference_manifest_hash,
            creation_json, creation_hash,
        ),
    )
    await session.execute(
        """INSERT INTO style_contracts
           (id,project_id,creation_contract_id,revision,merged_style_json,
            likes_json,dislikes_json,content_hash,confirmed_at)
           VALUES (%s,%s,%s,1,%s,'[]','[]',%s,3)""",
        (style_id, project_id, creation_id, style_json, style_hash),
    )
    if use_existing_foundation:
        await session.execute(
            """UPDATE project_contract_heads
                  SET revision=1,creation_contract_id=%s,style_contract_id=%s,
                      creation_hash=%s,style_hash=%s,updated_at=3
                WHERE project_id=%s""",
            (creation_id, style_id, creation_hash, style_hash, project_id),
        )
    else:
        await session.execute(
            """INSERT INTO project_contract_heads
               (project_id,revision,creation_contract_id,style_contract_id,
                creation_hash,style_hash,updated_at)
               VALUES (%s,1,%s,%s,%s,%s,3)""",
            (project_id, creation_id, style_id, creation_hash, style_hash),
        )


async def install_first_final_chapter(
    session,
    connection_config,
    project_id: str,
    seed,
    *,
    use_existing_foundation: bool = False,
) -> None:
    bible_id = str(uuid4())
    planning_id = str(uuid4())
    outline_id = str(uuid4())
    chapter_session_id = str(uuid4())
    candidate_id = str(uuid4())
    quality_report_id = str(uuid4())
    change_set_id = str(uuid4())
    change_set_revision_id = str(uuid4())
    finalization_id = str(uuid4())
    final_chapter_id = str(uuid4())
    contract = await session.fetchone(
        """SELECT creation_contract_id,creation_hash,style_contract_id,style_hash
             FROM project_contract_heads WHERE project_id=%s AND revision=1""",
        (project_id,),
    )
    projection = build_projection_bundle(0, ())
    projection_hash = projection.content_hash
    if not use_existing_foundation:
        await session.execute(
            """INSERT INTO canon_revisions
               (id,project_id,revision_number,parent_revision_number,
                idempotency_key,source_type,source_id,content_hash,created_at)
               VALUES (%s,%s,0,0,%s,'bootstrap',NULL,%s,4)""",
            (
                str(uuid4()),
                project_id,
                ProjectLifecycleService.bootstrap_idempotency_key(project_id),
                projection_hash,
            ),
        )
        await session.execute(
            """INSERT INTO projection_heads
               (project_id,canon_revision_number,projection_revision_number,
                content_hash,updated_at)
               VALUES (%s,0,0,%s,4)""",
            (project_id, projection_hash),
        )
    projection_head = await session.fetchone(
        """SELECT canon_revision_number,projection_revision_number,content_hash
             FROM projection_heads WHERE project_id=%s""",
        (project_id,),
    )
    assert projection_head == {
        "canon_revision_number": 0,
        "projection_revision_number": 0,
        "content_hash": projection_hash,
    }
    item = lambda identifier, text: {"id": identifier, "text": text}
    bible_payload = BiblePayload.model_validate(
        {
            "premiseAndPromise": "档案员追查未来来信，并守住城市的共同记忆。",
            "worldRules": (item("memory-cost", "改写记忆必须付出可追踪代价。"),),
            "powerOrProgressionSystem": "通过还原档案真相获得线索，而非无代价升级。",
            "protagonist": "林岚克制谨慎，但会为姐姐和同伴承担风险。",
            "coreCast": (item("companion", "同伴直接，持续挑战林岚的保守判断。"),),
            "factions": (item("archive", "档案局试图封存所有异常记录。"),),
            "longTermConflicts": (item("truth", "公开真相与维持城市记忆长期冲突。"),),
            "relationshipDynamics": (item("trust", "林岚与同伴从互疑走向有限信任。"),),
            "toneAndNarrativeBoundaries": "清楚好读，以人物选择推动情节。",
            "continuityGuardrails": (item("no-free-win", "关键胜利必须伴随损失。"),),
            "openDesignQuestions": (item("sender", "未来来信的真正发送者尚未确定。"),),
        },
        strict=True,
    )
    bible_json = canonical_json(bible_payload)
    bible_hash = canonical_bible_hash(bible_payload)
    await session.execute(
        """INSERT INTO creation_bible_revisions
           (id,project_id,revision,selection_revision,seed_id,seed_revision_id,
            seed_hash,contract_revision,creation_contract_id,creation_hash,
            style_contract_id,style_hash,binding_revision_id,binding_hash,
            policy_version,content_json,content_hash,confirmed_at)
           VALUES (%s,%s,1,%s,%s,%s,%s,1,%s,%s,%s,%s,NULL,NULL,'test-v1',
                   %s,%s,4)""",
        (
            bible_id, project_id, seed.selection_revision, seed.id,
            seed.revision_id, seed.content_hash,
            contract["creation_contract_id"], contract["creation_hash"],
            contract["style_contract_id"], contract["style_hash"],
            bible_json, bible_hash,
        ),
    )
    if use_existing_foundation:
        await session.execute(
            """UPDATE project_bible_heads
                  SET revision=1,bible_revision_id=%s,content_hash=%s,updated_at=4
                WHERE project_id=%s""",
            (bible_id, bible_hash, project_id),
        )
    else:
        await session.execute(
            """INSERT INTO project_bible_heads
               (project_id,revision,bible_revision_id,content_hash,updated_at)
               VALUES (%s,1,%s,%s,4)""",
            (project_id, bible_id, bible_hash),
        )
    planning = normalize_planning_aggregate(
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
                                        "clientNodeKey": "scene",
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
        id_factory=iter(str(uuid4()) for _ in range(5)).__next__,
    )
    planning_json = canonical_json(
        planning.model_dump(mode="json", by_alias=True)
    )
    planning_hash = planning.content_hash
    await session.execute(
        """INSERT INTO planning_revisions
           (id,project_id,revision,parent_revision,selection_revision,seed_id,
            seed_revision_id,seed_hash,contract_revision,creation_contract_id,
            creation_hash,style_contract_id,style_hash,bible_revision,
            bible_revision_id,bible_hash,content_json,content_hash,created_at)
           VALUES (%s,%s,1,0,%s,%s,%s,%s,1,%s,%s,%s,%s,1,%s,%s,%s,%s,5)""",
        (
            planning_id, project_id, seed.selection_revision, seed.id,
            seed.revision_id, seed.content_hash,
            contract["creation_contract_id"], contract["creation_hash"],
            contract["style_contract_id"], contract["style_hash"],
            bible_id, bible_hash, planning_json, planning_hash,
        ),
    )
    if use_existing_foundation:
        await session.execute(
            """UPDATE project_planning_heads
                  SET revision=1,planning_revision_id=%s,content_hash=%s,updated_at=5
                WHERE project_id=%s""",
            (planning_id, planning_hash, project_id),
        )
    else:
        await session.execute(
            """INSERT INTO project_planning_heads
               (project_id,revision,planning_revision_id,content_hash,updated_at)
               VALUES (%s,1,%s,%s,5)""",
            (project_id, planning_id, planning_hash),
        )
    block = planning.story_blocks[0]
    stage = block.stages[0]
    scene_task = stage.scene_tasks[0]
    node_ref = lambda node: {
        "id": node.id,
        "revision": node.revision,
        "contentHash": node.content_hash,
    }
    capacity = OutlineCapacityPolicy.model_validate(
        {"targetMin": 2500, "targetMax": 3200, "softCeiling": 3800}
    )
    outline = normalize_chapter_outline(
        DraftChapterOutline.model_validate(
            {
                "schemaVersion": "chapter-outline-v1",
                "chapterNumber": 1,
                "planningRevisionId": planning_id,
                "planningRevision": 1,
                "planningHash": planning_hash,
                "volumeRef": node_ref(planning.volumes[0]),
                "storyBlockRef": node_ref(block),
                "stageRefs": [node_ref(stage)],
                "sceneTaskRefs": [node_ref(scene_task)],
                "chapterGoal": "找到封锁线缺口。",
                "expectedCharacters": ["主角", "同伴"],
                "continuation": ["承接被困局面"],
                "plannedTasks": ["观察换岗"],
                "scenes": ["废弃驿站侦察"],
                "forbiddenEarlyEvents": ["不可提前揭示内应"],
                "capacityPolicy": capacity.model_dump(
                    mode="json", by_alias=True
                ),
            }
        ),
        planning=planning,
        authoritative_chapter_number=1,
        planning_revision_id=planning_id,
        planning_revision=1,
        capacity_policy=capacity,
        canon_revision=projection_head["canon_revision_number"],
        projection_revision=projection_head["projection_revision_number"],
        projection_hash=projection_head["content_hash"],
    )
    outline_json = canonical_json(
        outline.model_dump(mode="json", by_alias=True)
    )
    outline_hash = outline.content_hash
    await session.execute(
        """INSERT INTO chapter_outline_revisions
           (id,project_id,chapter_num,revision,parent_revision,
            planning_revision_id,planning_revision,planning_hash,
            canon_revision,projection_revision,projection_hash,
            content_json,content_hash,created_at)
           VALUES (%s,%s,1,1,0,%s,1,%s,0,0,%s,%s,%s,5)""",
        (
            outline_id, project_id, planning_id, planning_hash,
            projection_hash, outline_json, outline_hash,
        ),
    )
    await session.execute(
        """INSERT INTO project_chapter_outline_heads
           (project_id,chapter_num,revision,outline_revision_id,
            content_hash,updated_at)
           VALUES (%s,1,1,%s,%s,5)""",
        (project_id, outline_id, outline_hash),
    )
    await session.execute(
        """INSERT INTO chapter_sessions
           (id,project_id,planning_revision_id,planning_revision,planning_hash,
            story_block_id,story_block_revision,story_block_hash,
            chapter_outline_revision_id,chapter_outline_revision,
            chapter_outline_hash,chapter_num,expected_canon_revision,status,
            created_at,finalized_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,0,'drafting',6,NULL)""",
        (
            chapter_session_id, project_id, planning_id, 1, planning_hash,
            block.id, block.revision, block.content_hash,
            outline_id, 1, outline_hash,
        ),
    )
    working_content = "draft"
    working_hash = hashlib.sha256(working_content.encode("utf-8")).hexdigest()
    working_source = canonical_json(
        {
            "operation": "generate",
            "planningRevisionId": planning_id,
            "outlineRevisionId": outline_id,
        }
    )
    await session.execute(
        """INSERT INTO working_drafts
           (id,project_id,chapter_session_id,revision,content,content_hash,
            source_payload_json,updated_at)
           VALUES (%s,%s,%s,1,%s,%s,%s,6)""",
        (
            str(uuid4()), project_id, chapter_session_id,
            working_content, working_hash, working_source,
        ),
    )
    candidate_content = "draft"
    candidate_hash = hashlib.sha256(candidate_content.encode("utf-8")).hexdigest()
    candidate_provenance = canonical_json(
        {"source": "working-draft", "workingDraftRevision": 1}
    )
    await session.execute(
        """INSERT INTO draft_candidates
           (id,project_id,chapter_session_id,working_draft_revision,content,
            content_hash,basis_hash,provenance_json,created_at)
           VALUES (%s,%s,%s,1,%s,%s,%s,%s,6)""",
        (
            candidate_id, project_id, chapter_session_id,
            candidate_content, candidate_hash, "a" * 64, candidate_provenance,
        ),
    )
    change_set_payload = {
        "candidateId": candidate_id,
        "events": [],
        "expectedCanonRevision": projection_head["canon_revision_number"],
    }
    change_set_json = canonical_json(change_set_payload)
    change_set_hash = canonical_hash(change_set_payload)
    context_manifest_hash = canonical_hash({})
    quality_report_hash = canonical_hash(
        {"candidateId": candidate_id, "status": "completed"}
    )
    await session.execute(
        """INSERT INTO candidate_quality_reports
           (id,project_id,chapter_session_id,draft_candidate_id,candidate_hash,
            expected_canon_revision,expected_planning_hash,
            expected_outline_hash,policy_version,context_manifest_hash,
            provider_id,provider_profile_revision,model_name_snapshot,status,
            deterministic_blocks_json,findings_json,content_hash,created_at)
           VALUES (%s,%s,%s,%s,%s,0,%s,%s,'v1',%s,NULL,NULL,NULL,
                   'completed','[]','[]',%s,6)""",
        (
            quality_report_id, project_id, chapter_session_id, candidate_id,
            candidate_hash, planning_hash, outline_hash,
            context_manifest_hash, quality_report_hash,
        ),
    )
    await session.execute(
        """INSERT INTO finalization_change_sets
           (id,project_id,chapter_session_id,draft_candidate_id,
            quality_report_id,extraction_id,idempotency_key,
            request_fingerprint,active_slot,candidate_hash,
            expected_canon_revision,expected_planning_hash,
            expected_outline_hash,context_manifest_json,context_manifest_hash,
            status,current_revision,current_revision_hash,confirmed_revision,
            confirmed_revision_hash,created_at,updated_at,confirmed_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s,0,%s,%s,'{}',%s,
                   'committed',1,%s,1,%s,6,7,7)""",
        (
            change_set_id, project_id, chapter_session_id, candidate_id,
            quality_report_id, str(uuid4()), canonical_hash(
                {"chapterSessionId": chapter_session_id, "action": "prepare"}
            ), canonical_hash(
                {"candidateId": candidate_id, "expectedCanonRevision": 0}
            ), candidate_hash, planning_hash, outline_hash,
            context_manifest_hash, change_set_hash, change_set_hash,
        ),
    )
    await session.execute(
        """INSERT INTO finalization_change_set_revisions
           (id,project_id,change_set_id,revision,payload_json,content_hash,
            source,created_at)
           VALUES (%s,%s,%s,1,%s,%s,'extraction',6)""",
        (
            change_set_revision_id, project_id, change_set_id,
            change_set_json, change_set_hash,
        ),
    )
    canon_event = CanonEventCreate(
        id=str(uuid4()),
        event=CanonEventInput(
            entity_id=None,
            fact_kind=FactKind.DYNAMIC_EVENT,
            field_path="chapter.1.finalized",
            value={"status": "final"},
            evidence={
                "chapterSessionId": chapter_session_id,
                "draftCandidateId": candidate_id,
            },
            effective_start_chapter=1,
            effective_end_chapter=1,
            confirmation_status=ConfirmationStatus.CONFIRMED,
            assertion_operator=AssertionOperator.EQUALS,
            value_cardinality=ValueCardinality.SINGLE,
        ),
    )
    canon_result = await CanonService(
        CanonRepository(clock=lambda: 7),
        transaction_factory=transaction_factory_for(connection_config),
        clock=lambda: 7,
    ).commit(
        CommitCanonRevision(
            project_id=project_id,
            expected_head=projection_head["canon_revision_number"],
            idempotency_key=canonical_hash(
                {
                    "projectId": project_id,
                    "changeSetHash": change_set_hash,
                    "source": "finalization",
                }
            ),
            source_type="finalization",
            source_id=finalization_id,
            entities=(),
            aliases=(),
            events=(canon_event,),
        )
    )
    finalization_key = canonical_hash(
        {
            "projectId": project_id,
            "candidateHash": candidate_hash,
            "changeSetHash": change_set_hash,
        }
    )
    finalization_result = canonical_json(
        {
            "chapterNumber": 1,
            "committedCanonRevision": canon_result.revision_number,
            "projectionHash": canon_result.projection_hash,
        }
    )
    await session.execute(
        """INSERT INTO finalization_records
           (id,project_id,chapter_session_id,draft_candidate_id,change_set_id,
            change_set_revision,idempotency_key,request_fingerprint,
            candidate_hash,change_set_hash,
            expected_canon_revision,committed_canon_revision,
            result_payload_json,finalized_at)
           VALUES (%s,%s,%s,%s,%s,1,%s,%s,%s,%s,0,%s,%s,7)""",
        (
            finalization_id, project_id, chapter_session_id, candidate_id,
            change_set_id, finalization_key, canonical_hash(
                {"changeSetId": change_set_id, "revision": 1}
            ), candidate_hash, change_set_hash,
            canon_result.revision_number, finalization_result,
        ),
    )
    final_content = "final"
    final_content_hash = hashlib.sha256(final_content.encode("utf-8")).hexdigest()
    await session.execute(
        """INSERT INTO final_chapters
           (id,project_id,chapter_session_id,draft_candidate_id,
            finalization_record_id,chapter_num,title,content,content_hash,
            canon_revision,planning_revision_id,planning_revision,
            planning_hash,chapter_outline_revision_id,
            chapter_outline_revision,chapter_outline_hash,finalized_at)
           VALUES (%s,%s,%s,%s,%s,1,'Final',%s,%s,%s,%s,1,%s,%s,1,%s,7)""",
        (
            final_chapter_id, project_id, chapter_session_id, candidate_id,
            finalization_id, final_content, final_content_hash,
            canon_result.revision_number, planning_id, planning_hash,
            outline_id, outline_hash,
        ),
    )
    await session.execute(
        """UPDATE chapter_sessions
              SET status='final',finalized_at=7
            WHERE id=%s AND project_id=%s AND status='drafting'""",
        (chapter_session_id, project_id),
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
async def test_confirmed_selection_rejects_edits_and_preserves_contract_evidence(
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
    free = await service.create(CreateSeed(project_id="p1", payload=payload("自由")))
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

    with pytest.raises(SeedAlreadyConfirmed):
        await service.edit(
            EditSeed(
                project_id="p1", seed_id=selected_seed.id,
                payload=payload("选中改写"), expected_seed_revision=1,
                expected_selection_revision=selection.selection_revision,
            )
        )
    unchanged = await service.get_selected("p1")
    assert unchanged.seed_ready is True
    assert unchanged.reasons == ("binding_not_verified",)

    with pytest.raises(SeedLocked):
        await service.delete(
            DeleteSeed(
                project_id="p1", seed_id=selected_seed.id,
                expected_seed_revision=selected_seed.revision,
                expected_selection_revision=selection.selection_revision,
            )
        )
    assert (await disposable_mysql.session.fetchone(
        "SELECT status FROM creative_seeds WHERE id=%s", (selected_seed.id,)
    ))["status"] == "candidate"

    await service.delete(
        DeleteSeed(
            project_id="p1", seed_id=free.id,
            expected_seed_revision=1,
            expected_selection_revision=selection.selection_revision,
        )
    )
    assert await disposable_mysql.session.fetchone(
        "SELECT id FROM creative_seeds WHERE id=%s", (free.id,)
    ) is None


@pytest.mark.asyncio
async def test_confirmed_selection_allows_unreferenced_candidate_cleanup_only(
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
        CreateSeed(project_id="p1", payload=payload("确认选种"))
    )
    seed_b = await service.create(
        CreateSeed(project_id="p1", payload=payload("可清理候选"))
    )
    selection_a = await service.select(
        SelectSeed(
            project_id="p1",
            seed_id=seed_a.id,
            expected_seed_revision=1,
            expected_selection_revision=0,
        )
    )
    await service.archive(
        ArchiveSeed(
            project_id="p1",
            seed_id=seed_b.id,
            expected_seed_revision=1,
            expected_selection_revision=selection_a.selection_revision,
        )
    )

    archived = await disposable_mysql.session.fetchone(
        "SELECT status FROM creative_seeds WHERE id=%s",
        (seed_b.id,),
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
    assert current == {
        "seed_id": seed_a.id,
        "seed_revision_id": seed_a.revision_id,
        "selection_revision": 1,
    }
    assert history == [
        {
            "selection_revision": 1,
            "seed_id": seed_a.id,
            "seed_revision_id": seed_a.revision_id,
        }
    ]

    with pytest.raises(SeedAlreadyConfirmed):
        await service.restore(
            RestoreSeed(
                project_id="p1",
                seed_id=seed_b.id,
                expected_seed_revision=1,
                expected_selection_revision=selection_a.selection_revision,
            )
        )
    await service.delete(
        DeleteSeed(
            project_id="p1", seed_id=seed_b.id,
            expected_seed_revision=1,
            expected_selection_revision=selection_a.selection_revision,
        )
    )
    assert await disposable_mysql.session.fetchone(
        "SELECT id FROM creative_seeds WHERE id=%s", (seed_b.id,)
    ) is None
    with pytest.raises(SeedLocked):
        await service.delete(
            DeleteSeed(
                project_id="p1", seed_id=seed_a.id,
                expected_seed_revision=1,
                expected_selection_revision=selection_a.selection_revision,
            )
        )


@pytest.mark.asyncio
async def test_second_selection_keeps_first_selection_head_and_single_ledger_row(disposable_mysql):
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
    attempts = await asyncio.gather(
        service.select(
            SelectSeed(
                project_id="p1", seed_id=seed_b.id,
                expected_seed_revision=1,
                expected_selection_revision=first_a.selection_revision,
            )
        ),
        service.select(
            SelectSeed(
                project_id="p1", seed_id=seed_a.id,
                expected_seed_revision=1,
                expected_selection_revision=first_a.selection_revision,
            )
        ),
        return_exceptions=True,
    )

    active = await service.get_selected("p1")
    old_contract = await disposable_mysql.session.fetchone(
        """SELECT selection_revision,seed_id,seed_revision_id,seed_hash
             FROM creation_contracts WHERE project_id='p1'"""
    )

    assert all(
        isinstance(error, (SeedAlreadyConfirmed, ProjectBusy))
        for error in attempts
    )
    assert active.active_selection.selection_revision == 1
    assert active.active_selection.seed_id == seed_a.id
    assert active.seed_ready is True
    assert active.contract_ready is False
    assert active.reasons == ("binding_not_verified",)
    assert old_contract == {
        "selection_revision": 1,
        "seed_id": seed_a.id,
        "seed_revision_id": seed_a.revision_id,
        "seed_hash": seed_a.content_hash,
    }
    assert await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM project_seed_selection_revisions WHERE project_id='p1'"
    ) == {"count": 1}


@pytest.mark.asyncio
async def test_two_first_selection_requests_create_exactly_one_generation(
    disposable_mysql,
):
    class FirstProjectLockBarrierRepository(SeedRepository):
        def __init__(self):
            self.first_project_lock_acquired = asyncio.Event()
            self.release_first_request = asyncio.Event()
            self._first_lock = True

        async def lock_project(self, session, project_id):
            project = await super().lock_project(session, project_id)
            if self._first_lock:
                self._first_lock = False
                self.first_project_lock_acquired.set()
                await self.release_first_request.wait()
            return project

    await insert_project(disposable_mysql.session, "p1")
    setup_service = SeedService(
        SeedRepository(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
        connection_factory=connection_factory_for(
            disposable_mysql.connection_config
        ),
    )
    seed_a = await setup_service.create(
        CreateSeed(project_id="p1", payload=payload("A"))
    )
    seed_b = await setup_service.create(
        CreateSeed(project_id="p1", payload=payload("B"))
    )
    repository = FirstProjectLockBarrierRepository()
    service = SeedService(
        repository,
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
        connection_factory=connection_factory_for(
            disposable_mysql.connection_config
        ),
    )
    first_request = asyncio.create_task(
        service.select(
            SelectSeed(
                project_id="p1", seed_id=seed_a.id,
                expected_seed_revision=1, expected_selection_revision=0,
            )
        )
    )
    selected = None
    try:
        await asyncio.wait_for(repository.first_project_lock_acquired.wait(), timeout=2)
        with pytest.raises(ProjectBusy):
            await asyncio.wait_for(
                service.select(
                    SelectSeed(
                        project_id="p1", seed_id=seed_b.id,
                        expected_seed_revision=1, expected_selection_revision=0,
                    )
                ),
                timeout=2,
            )
    finally:
        selected = await _release_and_reap_first_request(
            first_request, repository.release_first_request
        )

    assert selected.id == seed_a.id
    assert await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM project_selected_seeds WHERE project_id='p1'"
    ) == {"count": 1}
    assert await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM project_seed_selection_revisions WHERE project_id='p1'"
    ) == {"count": 1}


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
    active = historical_selection
    await install_matching_contract(disposable_mysql.session, "p1", active)
    await install_first_final_chapter(
        disposable_mysql.session,
        disposable_mysql.connection_config,
        "p1",
        active,
    )
    final_authority = await disposable_mysql.session.fetchone(
        """SELECT session.status,session.finalized_at,
                  head.canon_revision_number,head.projection_revision_number,
                  (SELECT COUNT(*) FROM canon_revisions
                    WHERE project_id='p1') AS canon_revision_count,
                  (SELECT COUNT(*) FROM canon_events
                    WHERE project_id='p1' AND revision_number=1) AS canon_event_count,
                  (SELECT COUNT(*) FROM working_drafts
                    WHERE project_id='p1' AND revision=1) AS working_draft_count
             FROM chapter_sessions session
             JOIN projection_heads head ON head.project_id=session.project_id
            WHERE session.project_id='p1'"""
    )
    assert final_authority == {
        "status": "final",
        "finalized_at": 7,
        "canon_revision_number": 1,
        "projection_revision_number": 1,
        "canon_revision_count": 2,
        "canon_event_count": 1,
        "working_draft_count": 1,
    }
    bible_authority = await disposable_mysql.session.fetchone(
        """SELECT bible.id,bible.content_json,bible.content_hash,
                  head.bible_revision_id,head.content_hash AS head_hash,
                  planning.bible_revision_id AS planning_bible_revision_id,
                  planning.bible_hash AS planning_bible_hash
             FROM creation_bible_revisions bible
             JOIN project_bible_heads head
               ON head.project_id=bible.project_id
              AND head.bible_revision_id=bible.id
             JOIN planning_revisions planning
               ON planning.project_id=bible.project_id
              AND planning.bible_revision_id=bible.id
            WHERE bible.project_id='p1' AND bible.revision=1"""
    )
    bible_json = (
        json.loads(bible_authority["content_json"])
        if isinstance(bible_authority["content_json"], str)
        else bible_authority["content_json"]
    )
    for field_name in (
        "worldRules",
        "coreCast",
        "factions",
        "longTermConflicts",
        "relationshipDynamics",
        "continuityGuardrails",
        "openDesignQuestions",
    ):
        if isinstance(bible_json.get(field_name), list):
            bible_json[field_name] = tuple(bible_json[field_name])
    stored_bible = BiblePayload.model_validate(bible_json, strict=True)
    assert bible_authority["content_hash"] == canonical_bible_hash(stored_bible)
    assert bible_authority["bible_revision_id"] == bible_authority["id"]
    assert bible_authority["planning_bible_revision_id"] == bible_authority["id"]
    assert bible_authority["head_hash"] == bible_authority["content_hash"]
    assert bible_authority["planning_bible_hash"] == bible_authority["content_hash"]

    with pytest.raises(SeedAlreadyConfirmed):
        await service.create(CreateSeed(project_id="p1", payload=payload("定稿后候选")))
    with pytest.raises(SeedAlreadyConfirmed):
        await service.edit(
            EditSeed(
                project_id="p1", seed_id=free.id, payload=payload("未引用改"),
                expected_seed_revision=1,
                expected_selection_revision=active.selection_revision,
            )
        )
    archived = await service.archive(
        ArchiveSeed(
            project_id="p1", seed_id=free.id,
            expected_seed_revision=1,
            expected_selection_revision=active.selection_revision,
        )
    )
    assert archived.status == "archived"
    with pytest.raises(SeedAlreadyConfirmed):
        await service.restore(
            RestoreSeed(
                project_id="p1", seed_id=free.id,
                expected_seed_revision=1,
                expected_selection_revision=active.selection_revision,
            )
        )
    listed = {item.id: item for item in await service.list("p1")}
    historical_facts = listed[historical.id].capabilities
    free_facts = listed[free.id].capabilities
    assert (
        historical_facts.referenced,
        historical_facts.hasFinalChapters,
        historical_facts.canEdit,
        historical_facts.canArchive,
        historical_facts.canPermanentlyDelete,
    ) == (True, True, False, False, False)
    assert (
        free_facts.referenced,
        free_facts.canEdit,
        free_facts.canSelect,
        free_facts.canArchive,
        free_facts.canPermanentlyDelete,
    ) == (False, False, False, False, True)

    with pytest.raises(SeedAlreadyConfirmed):
        await service.edit(
            EditSeed(
                project_id="p1", seed_id=historical.id,
                payload=payload("不得改"), expected_seed_revision=1,
                expected_selection_revision=active.selection_revision,
            )
        )
    with pytest.raises(SeedAlreadyConfirmed):
        await service.select(
            SelectSeed(
                project_id="p1", seed_id=free.id,
                expected_seed_revision=free.revision,
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
    await service.delete(
        DeleteSeed(
            project_id="p1", seed_id=free.id,
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
async def test_confirmed_selection_timestamp_cannot_be_refreshed_or_advanced(
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
    with pytest.raises(SeedAlreadyConfirmed):
        await service.select(
            SelectSeed(
                project_id="p1", seed_id=second.id,
                expected_seed_revision=1, expected_selection_revision=1,
            )
        )
    now["value"] = 300
    with pytest.raises(SeedAlreadyConfirmed):
        await service.edit(
            EditSeed(
                project_id="p1", seed_id=first.id, payload=payload("甲改"),
                expected_seed_revision=1, expected_selection_revision=1,
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
