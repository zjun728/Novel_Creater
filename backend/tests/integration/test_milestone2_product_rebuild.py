from __future__ import annotations

import json
from uuid import uuid4

import pytest

from backend.domain.bibles import BiblePayload, canonical_bible_hash
from backend.domain.contracts import CreationContractPayload, StyleContractPayload
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.planning import (
    DraftPlanningAggregate,
    normalize_planning_aggregate,
)
from backend.domain.seeds import SeedPayload
from backend.domain.story_engines import StoryEngineOption
from backend.repositories.model_bindings import ModelBindingRepository
from backend.repositories.projects import ProjectRepository
from backend.repositories.seeds import SeedRepository
from backend.schema_manifest import manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from backend.scripts.reset_writer_core_data import (
    ResetRequest,
    ResetValidationError,
    reset_writer_core_data,
)
from backend.scripts.verify_milestone2_product import verify_milestone2_product
from backend.services.model_bindings import ModelBindingService
from backend.services.contracts import style_contract_hash
from backend.services.project_lifecycle import CreateProject, ProjectLifecycleService
from backend.services.seeds import CreateSeed, SeedService, SelectSeed
from backend.tests.support.disposable_mysql import transaction_factory_for


pytestmark = pytest.mark.mysql

PROJECT_ID = "11111111-1111-1111-1111-111111111111"
PROVIDER_ID = "22222222-2222-2222-2222-222222222222"
SEED_TITLES = ("永乐长明", "文渊山海", "典镇山河")


def request() -> ResetRequest:
    return ResetRequest(
        project_title="永乐大典",
        seed_titles=SEED_TITLES,
        preferred_provider_name="联通云",
        preferred_model="deepseek-v4-flash",
    )


def seed_payload(title: str) -> SeedPayload:
    return SeedPayload(
        title=title,
        genre="历史穿越",
        logline=f"{title}的测试梗概",
        protagonist="沈砚",
        desire="守住典籍",
        coreConflict="时间不足",
        worldPressure="局势持续收紧",
        openingHook="异常典籍出现",
        differentiation=f"{title}的差异化方向",
    )


async def install_foundation(disposable) -> None:
    await disposable.session.execute(
        """INSERT INTO provider_profiles
           (id,name,provider_type,model_name,base_url,api_key,enabled,
            sort_order,stream,max_context_tokens,max_output_tokens,temperature,
            top_p,supports_json,supports_streaming,notes,thinking,
            lifecycle_status,revision,deleted_at,created_at,updated_at)
           VALUES (%s,'联通云','openai-compatible','deepseek-v4-flash',
                   'https://provider.invalid/v1','integration-secret',1,
                   0,1,200000,4096,0.8,0.9,1,1,'',NULL,
                   'active',1,NULL,1,1)""",
        (PROVIDER_ID,),
    )
    transaction = transaction_factory_for(disposable.connection_config)
    ids = iter(
        f"30000000-0000-0000-0000-{number:012d}" for number in range(1, 100)
    )
    bindings = ModelBindingService(
        ModelBindingRepository(id_factory=ids.__next__, clock=lambda: 10),
        transaction_factory=transaction,
    )
    projects = ProjectLifecycleService(
        ProjectRepository(id_factory=ids.__next__, clock=lambda: 10),
        transaction,
        model_binding_service=bindings,
    )
    await projects.create(CreateProject(
        id=PROJECT_ID,
        title="永乐大典",
        genre="历史穿越",
        description="exact current-schema reset integration",
        target_words=1_000_000,
        target_chapters=300,
    ))
    seeds = SeedService(
        SeedRepository(),
        transaction_factory=transaction,
        id_factory=ids.__next__,
        clock=lambda: 20,
    )
    created = [
        await seeds.create(CreateSeed(project_id=PROJECT_ID, payload=seed_payload(title)))
        for title in SEED_TITLES
    ]
    selected = created[-1]
    await seeds.select(SelectSeed(
        project_id=PROJECT_ID,
        seed_id=selected.id,
        expected_seed_revision=1,
        expected_selection_revision=0,
    ))
    binding = await disposable.session.fetchone(
        """SELECT binding_revision_id,content_hash
           FROM project_model_binding_heads WHERE project_id=%s""",
        (PROJECT_ID,),
    )
    await disposable.session.execute(
        """INSERT INTO market_analyses
           (id,project_id,binding_revision_id,binding_hash,input_manifest_json,
            input_manifest_hash,policy_version,idempotency_key,request_hash,
            status,analysis_json,result_hash,public_error_code,created_at,completed_at)
           VALUES ('market-analysis-1',%s,%s,%s,'{}',%s,'test-policy',%s,%s,
                   'failed',NULL,NULL,'EXPECTED_TEST_FAILURE',30,31)""",
        (
            PROJECT_ID,
            binding["binding_revision_id"],
            binding["content_hash"],
            "a" * 64,
            "b" * 64,
            "c" * 64,
        ),
    )
    await disposable.session.execute(
        "UPDATE projects SET current_chapter=7 WHERE id=%s",
        (PROJECT_ID,),
    )


def canonical_bible() -> BiblePayload:
    item = lambda identifier, text: {"id": identifier, "text": text}
    return BiblePayload.model_validate(
        {
            "premiseAndPromise": "主角追查异变典籍，并以每次选择的代价守住历史。",
            "worldRules": (item("history-cost", "改写历史必须付出可追踪的代价。"),),
            "powerOrProgressionSystem": "通过校勘异变典籍获得线索，而非无代价升级。",
            "protagonist": "沈砚克制谨慎，但会为守住同伴承担风险。",
            "coreCast": (item("companion", "同伴直率，持续挑战主角的保守判断。"),),
            "factions": (item("archive", "守典司试图封存所有异常典籍。"),),
            "longTermConflicts": (item("truth", "保存真相与维持秩序长期冲突。"),),
            "relationshipDynamics": (item("trust", "主角与同伴从互疑走向有限信任。"),),
            "toneAndNarrativeBoundaries": "清楚好读，以人物选择推动情节。",
            "continuityGuardrails": (item("no-free-win", "任何关键胜利必须伴随损失。"),),
            "openDesignQuestions": (item("traitor", "守典司内应的真实身份尚未确定。"),),
        },
        strict=True,
    )


def canonical_planning():
    return normalize_planning_aggregate(
        DraftPlanningAggregate.model_validate(
            {
                "activeStoryBlockRef": "block",
                "volumes": [{
                    "clientNodeKey": "volume",
                    "lifecycle": "active",
                    "order": 1,
                    "title": "第一卷",
                    "coreChange": "主角建立第一个可靠据点。",
                    "mainPressure": "追兵逼近。",
                    "ensembleFocus": ["主角", "同伴"],
                    "forbiddenEvents": ["不可提前揭示幕后人"],
                }],
                "plots": [{
                    "clientNodeKey": "plot",
                    "lifecycle": "active",
                    "order": 1,
                    "title": "立足主线",
                    "plotType": "main",
                    "storyQuestion": "主角如何活下来？",
                    "futureDirection": "从逃亡转为主动布局。",
                    "expectedPayoff": "建立据点。",
                    "relatedCharacters": ["主角"],
                }],
                "storyBlocks": [{
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
                    "stages": [{
                        "clientNodeKey": "stage",
                        "lifecycle": "active",
                        "order": 1,
                        "title": "寻找缺口",
                        "purpose": "确认封锁薄弱处。",
                        "dramaticQuestion": "能否在暴露前找到缺口？",
                        "sceneTasks": [{
                            "clientNodeKey": "scene",
                            "lifecycle": "active",
                            "order": 1,
                            "task": "观察换岗。",
                            "completionEvidence": "取得换岗间隔。",
                        }],
                    }],
                }],
            }
        ),
        previous_confirmed=None,
        previous_draft=None,
        id_factory=iter(
            f"planning-node-{number}" for number in range(1, 6)
        ).__next__,
    )


async def install_canonical_prerequisites(
    session,
    *,
    include_bible_and_planning: bool,
) -> dict[str, str]:
    selected = await session.fetchone(
        """SELECT selected.seed_id,selected.seed_revision_id,selected.seed_hash,
                  selected.selection_revision,revision.payload_json
             FROM project_selected_seeds selected
             JOIN creative_seed_revisions revision
               ON revision.id=selected.seed_revision_id
            WHERE selected.project_id=%s""",
        (PROJECT_ID,),
    )
    binding = await session.fetchone(
        """SELECT binding_revision_id,revision,content_hash
             FROM project_model_binding_heads WHERE project_id=%s""",
        (PROJECT_ID,),
    )
    selected_seed = SeedPayload.model_validate(
        json.loads(selected["payload_json"])
        if isinstance(selected["payload_json"], str)
        else selected["payload_json"],
        strict=True,
    )
    engine = StoryEngineOption(
        name="典籍追索",
        storyPromise="沿异变典籍持续揭开历史危机。",
        protagonistDesire="守住典籍和同伴。",
        sustainedPressure="追兵与历史异变不断收紧。",
        growthDirection="从孤身守典成长为能承担共同选择的人。",
        conflictLoop="发现异变、追查线索、承担校勘代价。",
        ensembleRoles=({"role": "同伴", "purpose": "挑战主角的保守判断。"},),
        advantageAndCost="能辨认异变文字，但每次使用都会暴露位置。",
        satisfactionSources=("真相翻转",),
        longFormVariation=("个人、朝堂、时代三层危机。",),
        endingAnchor="主角守住共同记忆并接受个人代价。",
        risks=("追索结构重复",),
        differentiation="典籍异变直接改变现实。",
    )
    creation_id = str(uuid4())
    style_id = str(uuid4())
    creation = CreationContractPayload(
        schemaVersion="creation-contract-v1",
        channelProfileKey="web-fiction",
        genreProfileKey="history-transmigration",
        qualityCharterVersion="quality-v1",
        selectionRevision=selected["selection_revision"],
        selectedSeed=selected_seed,
        seedRevisionId=selected["seed_revision_id"],
        seedHash=selected["seed_hash"],
        selectedEngine=engine,
        engineOptionId="engine-option-1",
        engineHash=canonical_hash(engine),
        primaryStyleRef={
            "id": "style-primary",
            "revision": 1,
            "contentHash": "a" * 64,
        },
        secondaryStyleRef=None,
        experienceCardRefs=(),
        corpusSourceRefs=(),
        targetTotalWords=1_000_000,
        expectedVolumeCount=10,
        expectedChapterCount=300,
        chapterWordRangePreference=(2_500, 3_500),
        prohibitedDirections=("不写无代价升级",),
        authorNotes="人物选择优先。",
        modelBindingRef={
            "id": binding["binding_revision_id"],
            "revision": binding["revision"],
            "contentHash": binding["content_hash"],
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
    creation_hash = canonical_hash(creation)
    style_hash = style_contract_hash(style, (), ())
    reference_manifest = {
        "schemaVersion": "contract-reference-manifest-v1",
        "seedRef": {
            "id": selected["seed_id"],
            "revisionId": selected["seed_revision_id"],
            "contentHash": selected["seed_hash"],
        },
        "engineRef": {
            "id": "engine-option-1",
            "batchId": "engine-batch-1",
            "contentHash": canonical_hash(engine),
        },
        "bindingRef": {
            "id": binding["binding_revision_id"],
            "revision": binding["revision"],
            "contentHash": binding["content_hash"],
        },
        "styleRefs": [{
            "id": "style-primary",
            "revision": 1,
            "contentHash": "a" * 64,
        }],
        "experienceCardRefs": [],
        "corpusSourceRefs": [],
    }
    capacity_policy = canonical_json({
        "expectedVolumeCount": creation.expectedVolumeCount,
        "expectedChapterCount": creation.expectedChapterCount,
        "chapterWordRangePreference": list(
            creation.chapterWordRangePreference
        ),
    })
    await session.execute(
        """INSERT INTO creation_contracts
           (id,project_id,revision,selection_revision,seed_id,seed_revision_id,
            seed_hash,binding_revision_id,binding_hash,channel_profile_key,
            genre_profile_key,quality_charter_version,total_word_min,
            total_word_max,chapter_capacity_policy,reference_manifest_json,
            reference_manifest_hash,content_json,content_hash,confirmed_at)
           VALUES (%s,%s,1,%s,%s,%s,%s,%s,%s,'web-fiction',
                   'history-transmigration','quality-v1',1000000,1000000,
                   %s,%s,%s,%s,%s,30)""",
        (
            creation_id,
            PROJECT_ID,
            selected["selection_revision"],
            selected["seed_id"],
            selected["seed_revision_id"],
            selected["seed_hash"],
            binding["binding_revision_id"],
            binding["content_hash"],
            capacity_policy,
            canonical_json(reference_manifest),
            canonical_hash(reference_manifest),
            canonical_json(creation),
            creation_hash,
        ),
    )
    await session.execute(
        """INSERT INTO style_contracts
           (id,project_id,creation_contract_id,revision,merged_style_json,
            likes_json,dislikes_json,content_hash,confirmed_at)
           VALUES (%s,%s,%s,1,%s,'[]','[]',%s,30)""",
        (style_id, PROJECT_ID, creation_id, canonical_json(style), style_hash),
    )
    await session.execute(
        """UPDATE project_contract_heads
              SET revision=1,creation_contract_id=%s,style_contract_id=%s,
                  creation_hash=%s,style_hash=%s,updated_at=30
            WHERE project_id=%s""",
        (creation_id, style_id, creation_hash, style_hash, PROJECT_ID),
    )
    result = {
        "creation_id": creation_id,
        "creation_hash": creation_hash,
        "style_id": style_id,
        "style_hash": style_hash,
    }
    if not include_bible_and_planning:
        return result

    bible = canonical_bible()
    bible_id = str(uuid4())
    bible_hash = canonical_bible_hash(bible)
    await session.execute(
        """INSERT INTO creation_bible_revisions
           (id,project_id,revision,selection_revision,seed_id,seed_revision_id,
            seed_hash,contract_revision,creation_contract_id,creation_hash,
            style_contract_id,style_hash,binding_revision_id,binding_hash,
            policy_version,content_json,content_hash,confirmed_at)
           VALUES (%s,%s,1,%s,%s,%s,%s,1,%s,%s,%s,%s,NULL,NULL,
                   'creation-bible-v1',%s,%s,31)""",
        (
            bible_id,
            PROJECT_ID,
            selected["selection_revision"],
            selected["seed_id"],
            selected["seed_revision_id"],
            selected["seed_hash"],
            creation_id,
            creation_hash,
            style_id,
            style_hash,
            canonical_json(bible),
            bible_hash,
        ),
    )
    await session.execute(
        """UPDATE project_bible_heads
              SET revision=1,bible_revision_id=%s,content_hash=%s,updated_at=31
            WHERE project_id=%s""",
        (bible_id, bible_hash, PROJECT_ID),
    )
    planning = canonical_planning()
    planning_id = str(uuid4())
    await session.execute(
        """INSERT INTO planning_revisions
           (id,project_id,revision,parent_revision,selection_revision,seed_id,
            seed_revision_id,seed_hash,contract_revision,creation_contract_id,
            creation_hash,style_contract_id,style_hash,bible_revision,
            bible_revision_id,bible_hash,content_json,content_hash,created_at)
           VALUES (%s,%s,1,0,%s,%s,%s,%s,1,%s,%s,%s,%s,1,%s,%s,%s,%s,32)""",
        (
            planning_id,
            PROJECT_ID,
            selected["selection_revision"],
            selected["seed_id"],
            selected["seed_revision_id"],
            selected["seed_hash"],
            creation_id,
            creation_hash,
            style_id,
            style_hash,
            bible_id,
            bible_hash,
            canonical_json(planning.model_dump(mode="json", by_alias=True)),
            planning.content_hash,
        ),
    )
    await session.execute(
        """UPDATE project_planning_heads
              SET revision=1,planning_revision_id=%s,content_hash=%s,updated_at=32
            WHERE project_id=%s""",
        (planning_id, planning.content_hash, PROJECT_ID),
    )
    return {
        **result,
        "bible_id": bible_id,
        "bible_hash": bible_hash,
        "planning_id": planning_id,
        "planning_hash": planning.content_hash,
    }


async def install_contract_reference_rows(session) -> None:
    contract = await session.fetchone(
        """SELECT creation_contract_id,style_contract_id
             FROM project_contract_heads WHERE project_id=%s""",
        (PROJECT_ID,),
    )
    style_payload = {"schemaVersion": "style-template-v1", "voice": "克制"}
    card_payload = {"schemaVersion": "experience-card-v1", "rule": "选择有代价"}
    style_hash = canonical_hash(style_payload)
    card_hash = canonical_hash(card_payload)
    source_hash = "e" * 64
    fragment_hash = "f" * 64
    await session.execute(
        """INSERT INTO style_templates
           (id,stable_key,revision,name,payload_json,provenance_json,content_hash,
            status,created_at)
           VALUES ('reset-style','reset-style',1,'重置风格',%s,'{}',%s,'active',40)""",
        (canonical_json(style_payload), style_hash),
    )
    await session.execute(
        """INSERT INTO experience_cards
           (id,stable_key,revision,title,category,payload_json,provenance_json,
            content_hash,status,created_at)
           VALUES ('reset-card','reset-card',1,'重置经验','plot_organization',
                   %s,'{}',%s,'active',40)""",
        (canonical_json(card_payload), card_hash),
    )
    await session.execute(
        """INSERT INTO corpus_blobs
           (content_hash,byte_length,storage_key,created_at)
           VALUES (%s,10,'corpus/reset-source',40)""",
        (source_hash,),
    )
    await session.execute(
        """INSERT INTO corpus_sources
           (id,source_key,archived_at,created_at,updated_at)
           VALUES ('reset-source','reset-source',NULL,40,40)"""
    )
    await session.execute(
        """INSERT INTO corpus_source_revisions
           (id,source_id,revision,content_hash,relative_path,display_name,author,
            reference_tags_json,notes,provenance_json,byte_length,encoding,
            parser_version,normalizer_version,fragmenter_version,index_version,
            status,public_error_code,imported_at,analyzed_at,created_at)
           VALUES ('reset-source-rev','reset-source',1,%s,'reset.txt','重置语料',
                   '测试','[]','','{}',10,'utf-8','p1','n1','f1','i1',
                   'analyzed',NULL,40,40,40)""",
        (source_hash,),
    )
    await session.execute(
        """INSERT INTO corpus_chapters
           (id,corpus_source_id,source_revision_id,source_revision,source_hash,
            chapter_order,title,raw_byte_start,raw_byte_end,
            normalized_char_start,normalized_char_end,normalized_text,
            content_hash,created_at)
           VALUES ('reset-chapter','reset-source','reset-source-rev',1,%s,1,
                   '第一章',0,300,0,300,%s,%s,40)""",
        (source_hash, "A" * 300, "c" * 64),
    )
    await session.execute(
        """INSERT INTO corpus_fragments
           (id,corpus_source_id,corpus_chapter_id,fragment_order,
            chapter_char_start,chapter_char_end,normalized_text,content_hash,
            index_payload,analysis_version,created_at)
           VALUES ('reset-fragment','reset-source','reset-chapter',1,0,300,
                   %s,%s,'{}','analysis-v1',40)""",
        ("A" * 300, fragment_hash),
    )
    await session.execute(
        """INSERT INTO style_contract_template_refs
           VALUES (%s,'primary','reset-style',1,%s,1)""",
        (contract["style_contract_id"], style_hash),
    )
    await session.execute(
        """INSERT INTO creation_contract_experience_refs
           VALUES (%s,'reset-card',1,%s,1)""",
        (contract["creation_contract_id"], card_hash),
    )
    await session.execute(
        """INSERT INTO creation_contract_corpus_refs
           VALUES (%s,'reset-source',1,%s,'author',1)""",
        (contract["creation_contract_id"], source_hash),
    )
    await session.execute(
        """INSERT INTO creation_contract_corpus_fragment_refs
           VALUES (%s,'reset-source',1,%s,'reset-chapter','reset-fragment',
                   %s,0,100,'style',1)""",
        (contract["creation_contract_id"], source_hash, fragment_hash),
    )


@pytest.mark.asyncio
async def test_exact_current_schema_reset_preserves_foundation_and_clears_derived(
    disposable_mysql,
):
    await install_foundation(disposable_mysql)
    await install_canonical_prerequisites(
        disposable_mysql.session,
        include_bible_and_planning=False,
    )
    await install_contract_reference_rows(disposable_mysql.session)
    for table in (
        "style_contract_template_refs",
        "creation_contract_experience_refs",
        "creation_contract_corpus_refs",
        "creation_contract_corpus_fragment_refs",
    ):
        assert await disposable_mysql.session.fetchone(
            f"SELECT COUNT(*) AS count FROM {table}"
        ) == {"count": 1}
    output: list[str] = []

    dry = await reset_writer_core_data(
        disposable_mysql.session,
        database_name=disposable_mysql.database_name,
        confirm_reset=disposable_mysql.database_name,
        request=request(),
        output=output.append,
    )
    assert dry.executed is False
    assert await disposable_mysql.session.fetchone(
        "SELECT id FROM market_analyses WHERE project_id=%s", (PROJECT_ID,)
    ) == {"id": "market-analysis-1"}
    assert "integration-secret" not in output[0]
    assert "api_key" not in output[0].lower()

    report = await reset_writer_core_data(
        disposable_mysql.session,
        database_name=disposable_mysql.database_name,
        confirm_reset=disposable_mysql.database_name,
        request=request(),
        execute=True,
        output=lambda _value: None,
        now_ms=lambda: 100,
        id_factory=lambda: "40000000-0000-0000-0000-000000000001",
    )
    assert report.executed is True
    assert await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM market_analyses WHERE project_id=%s",
        (PROJECT_ID,),
    ) == {"count": 0}
    assert await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM creative_seeds WHERE project_id=%s",
        (PROJECT_ID,),
    ) == {"count": 3}
    assert await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM provider_profiles",
    ) == {"count": 1}
    for table in (
        "style_contract_template_refs",
        "creation_contract_experience_refs",
        "creation_contract_corpus_refs",
        "creation_contract_corpus_fragment_refs",
    ):
        assert await disposable_mysql.session.fetchone(
            f"SELECT COUNT(*) AS count FROM {table}"
        ) == {"count": 0}
    assert await disposable_mysql.session.fetchone(
        """SELECT current_chapter FROM projects WHERE id=%s""", (PROJECT_ID,)
    ) == {"current_chapter": 0}
    for table in (
        "project_contract_heads",
        "project_bible_heads",
        "project_planning_heads",
    ):
        assert await disposable_mysql.session.fetchone(
            f"SELECT revision FROM {table} WHERE project_id=%s", (PROJECT_ID,)
        ) == {"revision": 0}
    assert await disposable_mysql.session.fetchone(
        """SELECT COUNT(*) AS count FROM project_chapter_outline_heads
           WHERE project_id=%s""",
        (PROJECT_ID,),
    ) == {"count": 0}

    receipt = await verify_milestone2_product(
        disposable_mysql.session,
        expected_database=disposable_mysql.database_name,
    )
    assert receipt["schemaVersion"] == EXPECTED_SCHEMA_VERSION
    assert receipt["manifestHash"] == manifest_hash()
    assert receipt["project"]["planningRevision"] == 0


@pytest.mark.asyncio
async def test_schema_mismatch_rejects_before_foundation_read_or_write(
    disposable_mysql,
):
    await install_foundation(disposable_mysql)
    await disposable_mysql.session.execute(
        "UPDATE schema_metadata SET manifest_hash=%s WHERE singleton_id=1",
        ("0" * 64,),
    )

    class Recording:
        def __init__(self, session):
            self.session = session
            self.calls = []

        async def fetchall(self, sql, args=None):
            self.calls.append(("fetchall", sql))
            return await self.session.fetchall(sql, args)

        async def fetchone(self, sql, args=None):
            self.calls.append(("fetchone", sql))
            return await self.session.fetchone(sql, args)

        async def execute(self, sql, args=None):
            self.calls.append(("execute", sql))
            return await self.session.execute(sql, args)

    proxy = Recording(disposable_mysql.session)
    with pytest.raises(ResetValidationError, match="initialize_database"):
        await reset_writer_core_data(
            proxy,
            database_name=disposable_mysql.database_name,
            confirm_reset=disposable_mysql.database_name,
            request=request(),
            execute=True,
            output=lambda _value: None,
        )
    assert not any("`projects`" in sql for _, sql in proxy.calls)
    assert not any(kind == "execute" for kind, _ in proxy.calls)


@pytest.mark.asyncio
async def test_verifier_accepts_real_continuous_positive_planning_prerequisites(
    disposable_mysql,
):
    await install_foundation(disposable_mysql)
    await install_canonical_prerequisites(
        disposable_mysql.session,
        include_bible_and_planning=True,
    )
    await disposable_mysql.session.execute(
        "UPDATE projects SET current_chapter=0 WHERE id=%s",
        (PROJECT_ID,),
    )
    await disposable_mysql.session.execute(
        "DELETE FROM market_analyses WHERE project_id=%s",
        (PROJECT_ID,),
    )

    receipt = await verify_milestone2_product(
        disposable_mysql.session,
        expected_database=disposable_mysql.database_name,
        expected_planning_revision=1,
    )
    assert receipt["project"]["planningRevision"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("table", "column", "replacement", "expected_error"),
    (
        (
            "creation_contracts",
            "content_json",
            '{"invalid":"contract"}',
            "Contract/Style",
        ),
        (
            "planning_revisions",
            "content_json",
            '{"invalid":"planning"}',
            "Planning",
        ),
        (
            "creation_contracts",
            "reference_manifest_json",
            '{"invalid":"manifest"}',
            "reference manifest",
        ),
    ),
)
async def test_verifier_rejects_real_tampered_positive_prerequisite_payload(
    disposable_mysql,
    table,
    column,
    replacement,
    expected_error,
):
    await install_foundation(disposable_mysql)
    await install_canonical_prerequisites(
        disposable_mysql.session,
        include_bible_and_planning=True,
    )
    await disposable_mysql.session.execute(
        f"UPDATE {table} SET {column}=%s WHERE project_id=%s",
        (replacement, PROJECT_ID),
    )
    await disposable_mysql.session.execute(
        "UPDATE projects SET current_chapter=0 WHERE id=%s",
        (PROJECT_ID,),
    )
    await disposable_mysql.session.execute(
        "DELETE FROM market_analyses WHERE project_id=%s",
        (PROJECT_ID,),
    )

    with pytest.raises(RuntimeError, match=expected_error):
        await verify_milestone2_product(
            disposable_mysql.session,
            expected_database=disposable_mysql.database_name,
            expected_planning_revision=1,
        )
