from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from hashlib import sha256

import pytest

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.model_bindings import TASK_KEYS, BindingItem, BindingRevision
from backend.http_errors import ProjectArchived
from backend.repositories.contracts import ContractRepository
from backend.services.contracts import (
    AssetRevisionRef,
    ConfirmContracts,
    ContractAlreadyConfirmed,
    ContractConflict,
    ContractDraftIncomplete,
    ContractDraftInput,
    ContractNotFound,
    ContractService,
    CorpusSourceRef,
    SaveContractDraft,
)
from backend.tests.support.contract_fakes import SEED_PAYLOAD, style_asset
from backend.tests.support.disposable_mysql import transaction_factory_for
from backend.tests.support.story_engine_fakes import option


pytestmark = pytest.mark.mysql

PROJECT = "81000000-0000-0000-0000-000000000001"
SEED = "81000000-0000-0000-0000-000000000002"
SEED_REV = "81000000-0000-0000-0000-000000000003"
PROVIDER = "81000000-0000-0000-0000-000000000004"
BINDING = "81000000-0000-0000-0000-000000000005"
BATCH = "81000000-0000-0000-0000-000000000006"
ENGINE = "81000000-0000-0000-0000-000000000007"
STYLE = "81000000-0000-0000-0000-000000000008"
CARD = "81000000-0000-0000-0000-000000000009"
SOURCE = "81000000-0000-0000-0000-000000000010"
CREATION = "81000000-0000-0000-0000-000000000011"
STYLE_CONTRACT = "81000000-0000-0000-0000-000000000012"
SOURCE_REV = "81000000-0000-0000-0000-000000000013"
CHAPTER = "81000000-0000-0000-0000-000000000014"
FRAGMENT = "81000000-0000-0000-0000-000000000015"


async def _bootstrap(session):
    seed_hash = canonical_hash(SEED_PAYLOAD)
    engine_payload = option(1)
    engine_hash = canonical_hash(engine_payload)
    style_payload = style_asset(flavor="克制现实主义")
    style_hash = canonical_hash(style_payload)
    card_payload = {"schemaVersion": "experience-card-v1", "rule": "选择不可逆"}
    card_hash = canonical_hash(card_payload)
    source_hash = "e" * 64
    binding_items = tuple(BindingItem(
        task_key=task, resolution_status="bound", provider_id=PROVIDER,
        provider_name_snapshot="Contract Provider",
        model_name_snapshot="test-model",
    ) for task in TASK_KEYS)
    binding_hash = canonical_hash(BindingRevision(
        project_id=PROJECT, revision=1, items=binding_items,
    ))
    now = 1_900_000_000_000
    fragment_text = "A" * 300
    fragment_hash = sha256(fragment_text.encode("utf-8")).hexdigest()
    await session.execute(
        """INSERT INTO projects
           (id,title,genre,description,target_words,target_chapters,status,
            current_chapter,created_at,updated_at)
           VALUES (%s,'contract integration','fantasy','test',100000,100,
                   'drafting',0,%s,%s)""",
        (PROJECT, now, now),
    )
    await session.execute(
        "INSERT INTO creative_seeds VALUES (%s,%s,'candidate',%s,%s)",
        (SEED, PROJECT, now, now),
    )
    await session.execute(
        """INSERT INTO creative_seed_revisions
           (id,project_id,seed_id,revision,payload_json,content_hash,created_at)
           VALUES (%s,%s,%s,1,%s,%s,%s)""",
        (SEED_REV, PROJECT, SEED, canonical_json(SEED_PAYLOAD), seed_hash, now),
    )
    await session.execute(
        "INSERT INTO creative_seed_heads VALUES (%s,%s,1,%s,%s)",
        (SEED, SEED_REV, seed_hash, now),
    )
    await session.execute(
        """INSERT INTO project_seed_selection_revisions
           (project_id,selection_revision,seed_id,seed_revision_id,seed_hash,selected_at)
           VALUES (%s,1,%s,%s,%s,%s)""",
        (PROJECT, SEED, SEED_REV, seed_hash, now),
    )
    await session.execute(
        "INSERT INTO project_selected_seeds VALUES (%s,%s,%s,%s,1,%s,%s)",
        (PROJECT, SEED, SEED_REV, seed_hash, now, now),
    )
    await session.execute(
        """INSERT INTO provider_profiles
           (id,name,provider_type,model_name,base_url,api_key,enabled,sort_order,
            stream,max_context_tokens,max_output_tokens,temperature,top_p,
            supports_json,supports_streaming,notes,thinking,lifecycle_status,
            deleted_at,created_at,updated_at)
           VALUES (%s,'Contract Provider','openai-compatible','test-model',
                   'https://test.invalid',
                   'test-only-key',1,1,1,100000,4096,0.7,0.9,1,1,'',NULL,
                   'active',NULL,%s,%s)""",
        (PROVIDER, now, now),
    )
    await session.execute(
        """INSERT INTO project_model_binding_revisions
           (id,project_id,revision,content_hash,source_project_id,created_at)
           VALUES (%s,%s,1,%s,NULL,%s)""",
        (BINDING, PROJECT, binding_hash, now),
    )
    for item in binding_items:
        await session.execute(
            """INSERT INTO project_model_binding_items
               (binding_revision_id,task_key,resolution_status,provider_id,
                provider_name_snapshot,model_name_snapshot,item_hash)
               VALUES (%s,%s,'bound',%s,'Contract Provider','test-model',%s)""",
            (BINDING, item.task_key, PROVIDER, canonical_hash(item)),
        )
    await session.execute(
        "INSERT INTO project_model_binding_heads VALUES (%s,1,%s,%s,%s)",
        (PROJECT, BINDING, binding_hash, now),
    )
    await session.execute(
        """INSERT INTO story_engine_batches
           (id,project_id,selection_revision,source_type,seed_id,seed_revision_id,seed_hash,
            binding_revision_id,binding_hash,provider_id,model_name_snapshot,
            idempotency_key,request_json,request_hash,status,attempt_id,
            attempt_started_at,lease_expires_at,raw_response_text,
            raw_response_hash,public_error_code,created_at,finished_at)
           VALUES (%s,%s,1,'manual',%s,%s,%s,NULL,NULL,NULL,NULL,'manual-key',
                   '{}',%s,'succeeded',NULL,NULL,NULL,NULL,NULL,NULL,%s,%s)""",
        (BATCH, PROJECT, SEED, SEED_REV, seed_hash, "a" * 64, now, now),
    )
    await session.execute(
        """INSERT INTO story_engine_options
           (id,project_id,selection_revision,batch_id,option_order,payload_json,content_hash,created_at)
           VALUES (%s,%s,1,%s,1,%s,%s,%s)""",
        (ENGINE, PROJECT, BATCH, canonical_json(engine_payload), engine_hash, now),
    )
    await session.execute(
        """INSERT INTO style_templates
           (id,stable_key,revision,name,payload_json,provenance_json,content_hash,
            status,created_at) VALUES (%s,'restrained',1,'克制现实',%s,'{}',%s,
            'active',%s)""",
        (STYLE, canonical_json(style_payload), style_hash, now),
    )
    await session.execute(
        "INSERT INTO style_template_heads VALUES ('restrained',%s,1,%s,%s)",
        (STYLE, style_hash, now),
    )
    await session.execute(
        """INSERT INTO experience_cards
           (id,stable_key,revision,title,category,payload_json,provenance_json,
            content_hash,status,created_at) VALUES (%s,'choice',1,'选择代价',
            'plot_organization',%s,'{}',%s,'active',%s)""",
        (CARD, canonical_json(card_payload), card_hash, now),
    )
    await session.execute(
        "INSERT INTO experience_card_heads VALUES ('choice',%s,1,%s,%s)",
        (CARD, card_hash, now),
    )
    await session.execute(
        """INSERT INTO corpus_blobs
           (content_hash,byte_length,storage_key,created_at)
           VALUES (%s,10,'corpus/authorized',%s)""",
        (source_hash, now),
    )
    await session.execute(
        """INSERT INTO corpus_sources
           (id,source_key,archived_at,created_at,updated_at)
           VALUES (%s,'authorized',NULL,%s,%s)""",
        (SOURCE, now, now),
    )
    await session.execute(
        """INSERT INTO corpus_source_revisions
           (id,source_id,revision,content_hash,relative_path,display_name,author,
            reference_tags_json,notes,provenance_json,byte_length,encoding,
            parser_version,normalizer_version,fragmenter_version,index_version,
            status,public_error_code,imported_at,analyzed_at,created_at)
           VALUES (%s,%s,1,%s,
                   'authorized.txt','授权作品','作者','[]','','{}',10,'utf-8',
                   'p1','n1','f1','i1','analyzed',NULL,%s,%s,%s)""",
        (SOURCE_REV, SOURCE, source_hash, now, now, now),
    )
    await session.execute(
        """INSERT INTO corpus_source_heads
           (source_id,revision_id,revision,content_hash,updated_at)
           VALUES (%s,%s,1,%s,%s)""",
        (SOURCE, SOURCE_REV, source_hash, now),
    )
    await session.execute(
        """INSERT INTO corpus_chapters
           (id,corpus_source_id,source_revision_id,source_revision,source_hash,
            chapter_order,title,raw_byte_start,raw_byte_end,
            normalized_char_start,normalized_char_end,normalized_text,
            content_hash,created_at)
           VALUES (%s,%s,%s,1,%s,1,'第一章',0,300,0,300,%s,%s,%s)""",
        (CHAPTER, SOURCE, SOURCE_REV, source_hash, "A" * 300, "c" * 64, now),
    )
    await session.execute(
        """INSERT INTO corpus_fragments
           (id,corpus_source_id,corpus_chapter_id,fragment_order,
            chapter_char_start,chapter_char_end,normalized_text,content_hash,
            index_payload,analysis_version,created_at)
           VALUES (%s,%s,%s,1,0,300,%s,%s,'{}','analysis-v1',%s)""",
        (FRAGMENT, SOURCE, CHAPTER, fragment_text, fragment_hash, now),
    )
    await session.execute(
        "INSERT INTO project_contract_heads VALUES (%s,0,NULL,NULL,NULL,NULL,%s)",
        (PROJECT, now),
    )
    return {
        "seed_hash": seed_hash,
        "engine_hash": engine_hash,
        "style_hash": style_hash,
        "card_hash": card_hash,
        "source_hash": source_hash,
        "binding_hash": binding_hash,
        "fragment_hash": fragment_hash,
    }


_DEFAULT_REFS = object()


def _draft(
    facts,
    *,
    stage="assets",
    likes=("选择有代价",),
    dislikes=("空泛升级",),
    experience_card_refs=_DEFAULT_REFS,
    corpus_source_refs=_DEFAULT_REFS,
):
    common = {
        "schemaVersion": "contract-draft-v2",
        "draftStage": stage,
        "engineOptionId": ENGINE,
        "engineHash": facts["engine_hash"],
        "channelProfileKey": "web-fiction",
        "genreProfileKey": "fantasy",
        "qualityCharterVersion": "quality-v1",
        "targetTotalWords": 150_000,
        "expectedVolumeCount": 3,
        "expectedChapterCount": 60,
        "chapterWordRangePreference": (2_000, 3_000),
        "prohibitedDirections": ("不写无代价升级",),
        "authorNotes": "人物选择优先。",
    }
    if stage == "engine":
        return ContractDraftInput(**common)

    style = {
        "primaryStyleRef": AssetRevisionRef(
            id=STYLE, revision=1, contentHash=facts["style_hash"]
        ),
        "likes": likes,
        "dislikes": dislikes,
    }
    if stage == "style":
        return ContractDraftInput(**common, **style)

    if experience_card_refs is _DEFAULT_REFS:
        experience_card_refs = (AssetRevisionRef(
            id=CARD, revision=1, contentHash=facts["card_hash"]
        ),)
    if corpus_source_refs is _DEFAULT_REFS:
        corpus_source_refs = (CorpusSourceRef(
            id=SOURCE, revisionId=SOURCE_REV,
            revision=1, contentHash=facts["source_hash"],
            selectionMode="author",
            fragments=({
                "chapterId": CHAPTER,
                "fragmentId": FRAGMENT,
                "fragmentHash": facts["fragment_hash"],
                "chapterCharStart": 10,
                "chapterCharEnd": 110,
                "referenceUse": "style",
            },),
            pinnedHistoricalRevision=False,
        ),)
    return ContractDraftInput(
        **common,
        **style,
        experienceCardRefs=experience_card_refs,
        corpusSourceRefs=corpus_source_refs,
    )


async def _table_count(session, table):
    row = await session.fetchone(f"SELECT COUNT(*) AS count FROM {table}")
    return int(row["count"])


@pytest.mark.asyncio
async def test_real_progressive_draft_saves_engine_style_assets_as_versions_1_2_3(
    disposable_mysql,
):
    facts = await _bootstrap(disposable_mysql.session)
    service = _service(disposable_mysql)

    engine = await service.save_draft(SaveContractDraft(
        PROJECT, 0, _draft(facts, stage="engine")
    ))
    assert engine.draft_version == 1
    assert engine.draft.draftStage == "engine"
    assert engine.draft.primaryStyleRef is None
    assert engine.draft.experienceCardRefs is None
    loaded_engine = await service.get_draft(PROJECT)
    assert replace(loaded_engine, document_projection=None) == engine
    assert loaded_engine.document_projection.selected_engine.name == "方案 1"
    assert loaded_engine.document_projection.primary_style is None

    style = await service.save_draft(SaveContractDraft(
        PROJECT, 1, _draft(facts, stage="style")
    ))
    assert style.draft_version == 2
    assert style.draft.draftStage == "style"
    assert style.draft.primaryStyleRef.id == STYLE
    assert style.draft.experienceCardRefs is None
    loaded_style = await service.get_draft(PROJECT)
    assert replace(loaded_style, document_projection=None) == style
    assert loaded_style.document_projection.primary_style.name == "克制现实"
    assert loaded_style.document_projection.primary_style.revision == 1

    assets = await service.save_draft(SaveContractDraft(
        PROJECT, 2, _draft(facts)
    ))
    assert assets.draft_version == 3
    assert assets.draft.draftStage == "assets"
    assert assets.draft.is_complete is True
    assert assets.draft.experienceCardRefs[0].id == CARD
    assert assets.draft.corpusSourceRefs[0].id == SOURCE
    loaded_assets = await service.get_draft(PROJECT)
    assert replace(loaded_assets, document_projection=None) == assets


@pytest.mark.asyncio
async def test_real_archived_project_reads_existing_draft_but_rejects_preview_and_save(
    disposable_mysql,
):
    facts = await _bootstrap(disposable_mysql.session)
    service = _service(disposable_mysql)
    saved = await service.save_draft(SaveContractDraft(
        PROJECT, 0, _draft(facts)
    ))
    before = await disposable_mysql.session.fetchone(
        "SELECT draft_version,content_hash FROM project_contract_drafts WHERE project_id=%s",
        (PROJECT,),
    )
    await disposable_mysql.session.execute(
        "UPDATE projects SET archived_at=%s,lifecycle_revision=1 WHERE id=%s",
        (1_900_000_000_500, PROJECT),
    )

    assert replace(
        await service.get_draft(PROJECT), document_projection=None
    ) == saved
    with pytest.raises(ContractNotFound):
        await service.preview(PROJECT)
    with pytest.raises(ProjectArchived):
        await service.save_draft(SaveContractDraft(
            PROJECT, saved.draft_version, _draft(facts)
        ))

    assert await disposable_mysql.session.fetchone(
        "SELECT draft_version,content_hash FROM project_contract_drafts WHERE project_id=%s",
        (PROJECT,),
    ) == before


@pytest.mark.parametrize("stage", ("engine", "style"))
@pytest.mark.asyncio
async def test_real_incomplete_draft_preview_and_confirm_are_422_without_writes(
    disposable_mysql, stage
):
    facts = await _bootstrap(disposable_mysql.session)
    service = _service(disposable_mysql)
    saved = await service.save_draft(SaveContractDraft(
        PROJECT, 0, _draft(facts, stage=stage)
    ))

    with pytest.raises(ContractDraftIncomplete) as preview_error:
        await service.preview(PROJECT)
    with pytest.raises(ContractDraftIncomplete) as confirm_error:
        await service.confirm(ConfirmContracts(
            project_id=PROJECT,
            idempotency_key=f"incomplete-{stage}",
            expected_draft_version=saved.draft_version,
            expected_draft_hash=saved.content_hash,
        ))

    for error in (preview_error.value, confirm_error.value):
        assert error.status_code == 422
        assert error.code == "ContractDraftIncomplete"
    for table in (
        "creation_contracts",
        "style_contracts",
        "creation_contract_engine_refs",
        "style_contract_template_refs",
        "creation_contract_experience_refs",
        "creation_contract_corpus_refs",
        "contract_confirmation_requests",
    ):
        assert await _table_count(disposable_mysql.session, table) == 0
    head = await disposable_mysql.session.fetchone(
        "SELECT revision FROM project_contract_heads WHERE project_id=%s",
        (PROJECT,),
    )
    assert head["revision"] == 0
    assert replace(
        await service.get_draft(PROJECT), document_projection=None
    ) == saved


@pytest.mark.asyncio
async def test_real_assets_stage_with_explicit_empty_arrays_can_preview(
    disposable_mysql,
):
    facts = await _bootstrap(disposable_mysql.session)
    service = _service(disposable_mysql)
    saved = await service.save_draft(SaveContractDraft(
        PROJECT,
        0,
        _draft(
            facts,
            likes=(),
            dislikes=(),
            experience_card_refs=(),
            corpus_source_refs=(),
        ),
    ))

    preview = await service.preview(PROJECT)

    assert saved.draft.draftStage == "assets"
    assert saved.draft.experienceCardRefs == ()
    assert saved.draft.corpusSourceRefs == ()
    assert preview.contract_ready is True, preview.reasons
    assert preview.reasons == ()
    assert preview.experience_card_refs == ()
    assert preview.corpus_source_refs == ()
    assert preview.likes == ()
    assert preview.dislikes == ()
    assert preview.creation_contract is not None
    assert preview.style_contract is not None


def _service(disposable_mysql):
    tx = transaction_factory_for(disposable_mysql.connection_config)

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    ids = iter(
        f"82000000-0000-0000-0000-{number:012d}" for number in range(1, 100)
    )
    return ContractService(
        ContractRepository(), transaction_factory=tx,
        connection_factory=read_connection,
        id_factory=lambda: next(ids), clock=lambda: 1_900_000_000_100,
    )


@pytest.mark.asyncio
async def test_real_draft_preview_cas_and_confirmed_contract_is_locked(disposable_mysql):
    facts = await _bootstrap(disposable_mysql.session)
    service = _service(disposable_mysql)
    created = await service.save_draft(SaveContractDraft(PROJECT, 0, _draft(facts)))
    assert replace(
        await service.get_draft(PROJECT), document_projection=None
    ) == created
    preview = await service.preview(PROJECT)
    assert preview.contract_ready is True, preview.reasons
    assert preview.creation_hash and preview.style_hash

    contenders = await asyncio.gather(
        service.save_draft(SaveContractDraft(
            PROJECT, 1, _draft(facts, likes=("甲",))
        )),
        service.save_draft(SaveContractDraft(
            PROJECT, 1, _draft(facts, likes=("乙",))
        )),
        return_exceptions=True,
    )
    assert sum(getattr(item, "draft_version", None) == 2 for item in contenders) == 1
    assert sum(isinstance(item, ContractConflict) for item in contenders) == 1
    preview = await service.preview(PROJECT)

    now = 1_900_000_000_200
    reference_manifest = service._reference_manifest(preview)
    await disposable_mysql.session.execute(
        """INSERT INTO creation_contracts
           (id,project_id,revision,selection_revision,seed_id,seed_revision_id,seed_hash,
            binding_revision_id,binding_hash,channel_profile_key,
            genre_profile_key,quality_charter_version,total_word_min,total_word_max,
            chapter_capacity_policy,reference_manifest_json,
            reference_manifest_hash,content_json,content_hash,confirmed_at)
           VALUES (%s,%s,1,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                   %s,%s,%s,%s,%s,%s,%s)""",
        (CREATION, PROJECT, SEED, SEED_REV, facts["seed_hash"], BINDING,
         facts["binding_hash"], preview.creation_contract.channelProfileKey,
         preview.creation_contract.genreProfileKey,
         preview.creation_contract.qualityCharterVersion,
         preview.creation_contract.targetTotalWords,
         preview.creation_contract.targetTotalWords,
         canonical_json({
             "expectedVolumeCount": preview.creation_contract.expectedVolumeCount,
             "expectedChapterCount": preview.creation_contract.expectedChapterCount,
             "chapterWordRangePreference": list(
                 preview.creation_contract.chapterWordRangePreference
             ),
         }),
         canonical_json(reference_manifest), canonical_hash(reference_manifest),
         canonical_json(preview.creation_contract), preview.creation_hash, now),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO style_contracts
           (id,project_id,creation_contract_id,revision,merged_style_json,
            likes_json,dislikes_json,content_hash,confirmed_at)
           VALUES (%s,%s,%s,1,%s,%s,%s,%s,%s)""",
        (STYLE_CONTRACT, PROJECT, CREATION, canonical_json(preview.style_contract),
         canonical_json(list(preview.likes)), canonical_json(list(preview.dislikes)),
         preview.style_hash, now),
    )
    await disposable_mysql.session.execute(
        "INSERT INTO creation_contract_engine_refs VALUES (%s,%s,%s,%s)",
        (CREATION, PROJECT, ENGINE, facts["engine_hash"]),
    )
    await disposable_mysql.session.execute(
        "INSERT INTO style_contract_template_refs VALUES (%s,'primary',%s,1,%s,1)",
        (STYLE_CONTRACT, STYLE, facts["style_hash"]),
    )
    await disposable_mysql.session.execute(
        "INSERT INTO creation_contract_experience_refs VALUES (%s,%s,1,%s,1)",
        (CREATION, CARD, facts["card_hash"]),
    )
    await disposable_mysql.session.execute(
        "INSERT INTO creation_contract_corpus_refs VALUES (%s,%s,1,%s,'author',1)",
        (CREATION, SOURCE, facts["source_hash"]),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO creation_contract_corpus_fragment_refs
           (creation_contract_id,corpus_source_id,source_revision,source_hash,
            corpus_chapter_id,corpus_fragment_id,fragment_hash,
            chapter_char_start,chapter_char_end,reference_use,sort_order)
           VALUES (%s,%s,1,%s,%s,%s,%s,10,110,'style',1)""",
        (CREATION, SOURCE, facts["source_hash"], CHAPTER, FRAGMENT,
         facts["fragment_hash"]),
    )
    await disposable_mysql.session.execute(
        "DELETE FROM project_contract_drafts WHERE project_id=%s", (PROJECT,)
    )
    await disposable_mysql.session.execute(
        """UPDATE project_contract_heads SET revision=1,creation_contract_id=%s,
               style_contract_id=%s,creation_hash=%s,style_hash=%s,updated_at=%s
           WHERE project_id=%s""",
        (CREATION, STYLE_CONTRACT, preview.creation_hash, preview.style_hash, now, PROJECT),
    )

    with pytest.raises(ContractAlreadyConfirmed):
        await service.clone_revision(PROJECT, 1)
    assert await _table_count(disposable_mysql.session, "project_contract_drafts") == 0
    assert await _table_count(disposable_mysql.session, "creation_contracts") == 1
