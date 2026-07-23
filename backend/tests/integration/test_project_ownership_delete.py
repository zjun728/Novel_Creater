from __future__ import annotations

import pytest
from pymysql.err import IntegrityError

from backend.repositories.projects import ProjectRepository
from backend.tests.support.disposable_mysql import transaction_factory_for


pytestmark = pytest.mark.mysql

NOW = 1_720_000_000_000
PROJECT_ID = "10000000-0000-0000-0000-000000000001"
CLONE_ID = "10000000-0000-0000-0000-000000000002"
SEED_ID = "20000000-0000-0000-0000-000000000001"
SEED_REVISION_ID = "20000000-0000-0000-0000-000000000002"
PROVIDER_ID = "30000000-0000-0000-0000-000000000001"
BINDING_ID = "30000000-0000-0000-0000-000000000002"
CLONE_BINDING_ID = "30000000-0000-0000-0000-000000000003"
BATCH_ID = "40000000-0000-0000-0000-000000000001"
OPTION_ID = "40000000-0000-0000-0000-000000000002"
CREATION_ID = "50000000-0000-0000-0000-000000000001"
STYLE_CONTRACT_ID = "50000000-0000-0000-0000-000000000002"
CONTRACT_DRAFT_ID = "50000000-0000-0000-0000-000000000003"
CONFIRMATION_ID = "50000000-0000-0000-0000-000000000004"
STYLE_TEMPLATE_ID = "60000000-0000-0000-0000-000000000001"
EXPERIENCE_CARD_ID = "60000000-0000-0000-0000-000000000002"
CORPUS_SOURCE_ID = "60000000-0000-0000-0000-000000000003"
CORPUS_CHAPTER_ID = "60000000-0000-0000-0000-000000000004"
CORPUS_FRAGMENT_ID = "60000000-0000-0000-0000-000000000005"
CORPUS_IMPORT_ID = "60000000-0000-0000-0000-000000000006"
CORPUS_REVISION_ID = "60000000-0000-0000-0000-000000000007"
BIBLE_REVISION_ID = "60000000-0000-0000-0000-000000000008"
MARKET_SOURCE_ID = "60000000-0000-0000-0000-000000000009"
MARKET_SNAPSHOT_ID = "60000000-0000-0000-0000-000000000010"
MARKET_ANALYSIS_ID = "60000000-0000-0000-0000-000000000011"
SEED_ATTEMPT_ID = "60000000-0000-0000-0000-000000000012"
SEED_REQUEST_ID = "60000000-0000-0000-0000-000000000013"
ASSET_ATTEMPT_ID = "60000000-0000-0000-0000-000000000014"
ASSET_REQUEST_ID = "60000000-0000-0000-0000-000000000015"
STYLE_ATTEMPT_ID = "60000000-0000-0000-0000-000000000016"
STYLE_REQUEST_ID = "60000000-0000-0000-0000-000000000017"
VOLUME_ID = "70000000-0000-0000-0000-000000000001"
BLOCK_ID = "70000000-0000-0000-0000-000000000002"
SESSION_ID = "70000000-0000-0000-0000-000000000003"
CANDIDATE_ID = "70000000-0000-0000-0000-000000000004"
STAGE_ID = "70000000-0000-0000-0000-000000000005"
SCENE_ID = "70000000-0000-0000-0000-000000000006"
WORKING_ID = "70000000-0000-0000-0000-000000000007"
CHANGE_SET_ID = "70000000-0000-0000-0000-000000000008"
FINALIZATION_ID = "70000000-0000-0000-0000-000000000009"
FINAL_CHAPTER_ID = "70000000-0000-0000-0000-000000000010"
ENTITY_ID = "80000000-0000-0000-0000-000000000001"
CANON_REVISION_ID = "80000000-0000-0000-0000-000000000002"
ALIAS_ID = "80000000-0000-0000-0000-000000000004"

PRIVATE_TABLES_WITHOUT_CLONE_ROWS = (
    "creative_seeds",
    "creative_seed_revisions",
    "creative_seed_heads",
    "project_seed_selection_revisions",
    "project_selected_seeds",
    "project_model_binding_items",
    "project_model_binding_heads",
    "market_analyses",
    "seed_inspiration_attempts",
    "seed_inspiration_requests",
    "asset_recommendation_attempts",
    "asset_recommendation_requests",
    "style_trial_attempts",
    "style_trial_requests",
    "story_engine_batches",
    "story_engine_options",
    "project_contract_drafts",
    "creation_contracts",
    "style_contracts",
    "project_contract_heads",
    "contract_confirmation_requests",
    "creation_contract_engine_refs",
    "style_contract_template_refs",
    "creation_contract_experience_refs",
    "creation_contract_corpus_refs",
    "creation_bible_revisions",
    "project_bible_heads",
    "volume_plans",
    "story_blocks",
    "story_stages",
    "scene_tasks",
    "chapter_sessions",
    "working_drafts",
    "draft_candidates",
    "finalization_change_sets",
    "finalization_records",
    "final_chapters",
    "canon_entities",
    "entity_aliases",
    "canon_revisions",
    "canon_events",
    "current_state_projections",
    "memory_views",
    "arc_projections",
    "plot_thread_projections",
    "projection_heads",
    "reference_uses",
)


async def _insert_project(session, project_id: str, title: str) -> None:
    await session.execute(
        """INSERT INTO projects
           (id,title,genre,description,target_words,target_chapters,status,
            current_chapter,created_at,updated_at)
           VALUES (%s,%s,'history','ownership test',100000,100,'active',0,%s,%s)""",
        (project_id, title, NOW, NOW),
    )


async def _insert_shared_rows(session) -> None:
    await session.execute(
        """INSERT INTO provider_profiles
           (id,name,provider_type,model_name,base_url,api_key,enabled,sort_order,
            stream,max_context_tokens,max_output_tokens,temperature,top_p,
            supports_json,supports_streaming,notes,thinking,lifecycle_status,
            deleted_at,created_at,updated_at)
           VALUES (%s,'shared-provider','test','test-model','https://test.invalid',
                   'test-only',1,0,0,4096,1024,0.5,0.9,1,0,'test',NULL,
                   'active',NULL,%s,%s)""",
        (PROVIDER_ID, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO style_templates
           (id,stable_key,revision,name,payload_json,provenance_json,content_hash,
            status,created_at)
           VALUES (%s,'shared-style',1,'Shared Style','{}','{}',%s,'active',%s)""",
        (STYLE_TEMPLATE_ID, "a" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO style_template_heads
           (stable_key,style_template_id,revision,content_hash,updated_at)
           VALUES ('shared-style',%s,1,%s,%s)""",
        (STYLE_TEMPLATE_ID, "a" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO experience_cards
           (id,stable_key,revision,title,category,payload_json,provenance_json,
            content_hash,status,created_at)
           VALUES (%s,'shared-card',1,'Shared Card','pacing','{}','{}',%s,
                   'active',%s)""",
        (EXPERIENCE_CARD_ID, "b" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO experience_card_heads
           (stable_key,experience_card_id,revision,content_hash,updated_at)
           VALUES ('shared-card',%s,1,%s,%s)""",
        (EXPERIENCE_CARD_ID, "b" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO corpus_blobs
           (content_hash,byte_length,storage_key,created_at)
           VALUES (%s,4,'corpus/shared-source',%s)""",
        ("c" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO corpus_sources
           (id,source_key,archived_at,created_at,updated_at)
           VALUES (%s,'shared-source',NULL,%s,%s)""",
        (CORPUS_SOURCE_ID, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO corpus_source_revisions
           (id,source_id,revision,content_hash,relative_path,display_name,author,
            reference_tags_json,notes,provenance_json,byte_length,encoding,
            parser_version,normalizer_version,fragmenter_version,index_version,
            status,public_error_code,imported_at,analyzed_at,created_at)
           VALUES (%s,%s,1,%s,'shared.txt','Shared Source','Test','[]','','{}',
                   4,'utf-8','p1','n1','f1','i1','analyzed',NULL,%s,%s,%s)""",
        (CORPUS_REVISION_ID, CORPUS_SOURCE_ID, "c" * 64, NOW, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO corpus_source_heads
           (source_id,revision_id,revision,content_hash,updated_at)
           VALUES (%s,%s,1,%s,%s)""",
        (CORPUS_SOURCE_ID, CORPUS_REVISION_ID, "c" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO corpus_chapters
           (id,corpus_source_id,source_revision_id,source_revision,source_hash,
            chapter_order,title,raw_byte_start,raw_byte_end,
            normalized_char_start,normalized_char_end,normalized_text,
            content_hash,created_at)
           VALUES (%s,%s,%s,1,%s,1,'Shared Chapter',0,4,0,4,'text',%s,%s)""",
        (
            CORPUS_CHAPTER_ID,
            CORPUS_SOURCE_ID,
            CORPUS_REVISION_ID,
            "c" * 64,
            "d" * 64,
            NOW,
        ),
    )
    await session.execute(
        """INSERT INTO corpus_fragments
           (id,corpus_source_id,corpus_chapter_id,fragment_order,chapter_char_start,
            chapter_char_end,normalized_text,content_hash,index_payload,
            analysis_version,created_at)
           VALUES (%s,%s,%s,1,0,4,'text',%s,'{}','a1',%s)""",
        (
            CORPUS_FRAGMENT_ID,
            CORPUS_SOURCE_ID,
            CORPUS_CHAPTER_ID,
            "3" * 64,
            NOW,
        ),
    )
    await session.execute(
        """INSERT INTO corpus_import_runs
           (id,idempotency_key,request_hash,relative_path,content_hash,status,
            corpus_source_id,source_revision_id,source_revision,public_error_code,
            parser_versions_json,created_at,completed_at)
           VALUES (%s,%s,%s,'shared.txt',%s,'succeeded',%s,%s,1,NULL,'{}',%s,%s)""",
        (
            CORPUS_IMPORT_ID,
            "4" * 64,
            "5" * 64,
            "c" * 64,
            CORPUS_SOURCE_ID,
            CORPUS_REVISION_ID,
            NOW,
            NOW,
        ),
    )
    await session.execute(
        """INSERT INTO market_sources
           (id,stable_key,adapter_key,display_name,public_config_json,status,
            created_at,updated_at)
           VALUES (%s,'shared-market','manual','Shared Market','{}','active',
                   %s,%s)""",
        (MARKET_SOURCE_ID, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO market_snapshots
           (id,source_id,captured_at,platform,ranking_name,category,source_url,
            content_hash,entry_count,created_at)
           VALUES (%s,%s,%s,'test','ranking','fiction',
                   'https://market.test/shared',%s,1,%s)""",
        (MARKET_SNAPSHOT_ID, MARKET_SOURCE_ID, NOW, "9" * 64, NOW),
    )


async def _insert_seed_engine_and_contracts(session) -> None:
    await session.execute(
        """INSERT INTO creative_seeds
           (id,project_id,status,created_at,updated_at)
           VALUES (%s,%s,'candidate',%s,%s)""",
        (SEED_ID, PROJECT_ID, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO creative_seed_revisions
           (id,project_id,seed_id,revision,payload_json,content_hash,created_at)
           VALUES (%s,%s,%s,1,'{}',%s,%s)""",
        (SEED_REVISION_ID, PROJECT_ID, SEED_ID, "e" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO creative_seed_heads
           (seed_id,revision_id,revision,content_hash,updated_at)
           VALUES (%s,%s,1,%s,%s)""",
        (SEED_ID, SEED_REVISION_ID, "e" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO project_seed_selection_revisions
           (project_id,selection_revision,seed_id,seed_revision_id,seed_hash,
            selected_at)
           VALUES (%s,1,%s,%s,%s,%s)""",
        (PROJECT_ID, SEED_ID, SEED_REVISION_ID, "e" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO project_selected_seeds
           (project_id,seed_id,seed_revision_id,seed_hash,selection_revision,
            selected_at,updated_at)
           VALUES (%s,%s,%s,%s,1,%s,%s)""",
        (PROJECT_ID, SEED_ID, SEED_REVISION_ID, "e" * 64, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO project_model_binding_revisions
           (id,project_id,revision,content_hash,source_project_id,created_at)
           VALUES (%s,%s,1,%s,NULL,%s)""",
        (BINDING_ID, PROJECT_ID, "f" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO project_model_binding_items
           (binding_revision_id,task_key,resolution_status,provider_id,
            provider_name_snapshot,model_name_snapshot,item_hash)
           VALUES (%s,'writing','bound',%s,'shared-provider','test-model',%s)""",
        (BINDING_ID, PROVIDER_ID, "1" * 64),
    )
    await session.execute(
        """INSERT INTO project_model_binding_heads
           (project_id,revision,binding_revision_id,content_hash,updated_at)
           VALUES (%s,1,%s,%s,%s)""",
        (PROJECT_ID, BINDING_ID, "f" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO project_model_binding_revisions
           (id,project_id,revision,content_hash,source_project_id,created_at)
           VALUES (%s,%s,1,%s,%s,%s)""",
        (CLONE_BINDING_ID, CLONE_ID, "2" * 64, PROJECT_ID, NOW),
    )
    await session.execute(
        """INSERT INTO story_engine_batches
           (id,project_id,selection_revision,source_type,seed_id,seed_revision_id,seed_hash,
            binding_revision_id,binding_hash,provider_id,model_name_snapshot,
            idempotency_key,request_json,request_hash,status,attempt_id,
            attempt_started_at,lease_expires_at,raw_response_text,
            raw_response_hash,public_error_code,created_at,finished_at)
           VALUES (%s,%s,1,'manual',%s,%s,%s,NULL,NULL,NULL,NULL,%s,'{}',%s,
                   'succeeded',NULL,NULL,NULL,NULL,NULL,NULL,%s,%s)""",
        (
            BATCH_ID,
            PROJECT_ID,
            SEED_ID,
            SEED_REVISION_ID,
            "e" * 64,
            "3" * 64,
            "4" * 64,
            NOW,
            NOW,
        ),
    )
    await session.execute(
        """INSERT INTO story_engine_options
           (id,project_id,selection_revision,batch_id,option_order,payload_json,
            content_hash,created_at)
           VALUES (%s,%s,1,%s,1,'{}',%s,%s)""",
        (OPTION_ID, PROJECT_ID, BATCH_ID, "5" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO project_contract_drafts
           (project_id,id,selection_revision,base_head_revision,seed_revision_id,seed_hash,
            engine_option_id,draft_json,content_hash,draft_version,created_at,
            updated_at)
           VALUES (%s,%s,1,0,%s,%s,%s,'{}',%s,1,%s,%s)""",
        (
            PROJECT_ID,
            CONTRACT_DRAFT_ID,
            SEED_REVISION_ID,
            "e" * 64,
            OPTION_ID,
            "6" * 64,
            NOW,
            NOW,
        ),
    )
    await session.execute(
        """INSERT INTO creation_contracts
           (id,project_id,revision,selection_revision,seed_id,seed_revision_id,seed_hash,
            binding_revision_id,binding_hash,channel_profile_key,genre_profile_key,
            quality_charter_version,total_word_min,total_word_max,
            chapter_capacity_policy,reference_manifest_json,
            reference_manifest_hash,content_json,content_hash,confirmed_at)
           VALUES (%s,%s,1,1,%s,%s,%s,%s,%s,'channel','genre','q1',1,2,
                   'fixed','{}',%s,'{}',%s,%s)""",
        (
            CREATION_ID,
            PROJECT_ID,
            SEED_ID,
            SEED_REVISION_ID,
            "e" * 64,
            BINDING_ID,
            "f" * 64,
            "6" * 64,
            "7" * 64,
            NOW,
        ),
    )
    await session.execute(
        """INSERT INTO style_contracts
           (id,project_id,creation_contract_id,revision,merged_style_json,
            likes_json,dislikes_json,content_hash,confirmed_at)
           VALUES (%s,%s,%s,1,'{}','[]','[]',%s,%s)""",
        (STYLE_CONTRACT_ID, PROJECT_ID, CREATION_ID, "8" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO project_contract_heads
           (project_id,revision,creation_contract_id,style_contract_id,
            creation_hash,style_hash,updated_at)
           VALUES (%s,1,%s,%s,%s,%s,%s)""",
        (
            PROJECT_ID,
            CREATION_ID,
            STYLE_CONTRACT_ID,
            "7" * 64,
            "8" * 64,
            NOW,
        ),
    )
    await session.execute(
        """INSERT INTO contract_confirmation_requests
           (id,project_id,selection_revision,idempotency_key,request_hash,status,
            creation_contract_id,style_contract_id,result_revision,
            public_error_code,created_at,completed_at)
           VALUES (%s,%s,1,%s,%s,'succeeded',%s,%s,1,NULL,%s,%s)""",
        (
            CONFIRMATION_ID,
            PROJECT_ID,
            "9" * 64,
            "a" * 64,
            CREATION_ID,
            STYLE_CONTRACT_ID,
            NOW,
            NOW,
        ),
    )
    await session.execute(
        """INSERT INTO creation_contract_engine_refs
           (creation_contract_id,project_id,engine_option_id,engine_hash)
           VALUES (%s,%s,%s,%s)""",
        (CREATION_ID, PROJECT_ID, OPTION_ID, "5" * 64),
    )
    await session.execute(
        """INSERT INTO style_contract_template_refs
           (style_contract_id,role,style_template_id,asset_revision,asset_hash,
            sort_order)
           VALUES (%s,'primary',%s,1,%s,1)""",
        (STYLE_CONTRACT_ID, STYLE_TEMPLATE_ID, "a" * 64),
    )
    await session.execute(
        """INSERT INTO creation_contract_experience_refs
           (creation_contract_id,experience_card_id,asset_revision,asset_hash,
            sort_order)
           VALUES (%s,%s,1,%s,1)""",
        (CREATION_ID, EXPERIENCE_CARD_ID, "b" * 64),
    )
    await session.execute(
        """INSERT INTO creation_contract_corpus_refs
           (creation_contract_id,corpus_source_id,source_revision,source_hash,
            selection_mode,sort_order)
           VALUES (%s,%s,1,%s,'author',1)""",
        (CREATION_ID, CORPUS_SOURCE_ID, "c" * 64),
    )
    await session.execute(
        """INSERT INTO creation_bible_revisions
           (id,project_id,revision,selection_revision,seed_id,seed_revision_id,
            seed_hash,contract_revision,creation_contract_id,creation_hash,
            style_contract_id,style_hash,binding_revision_id,binding_hash,
            policy_version,content_json,content_hash,confirmed_at)
           VALUES (%s,%s,1,1,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,'test-bible-v1',
                   '{}',%s,%s)""",
        (
            BIBLE_REVISION_ID,
            PROJECT_ID,
            SEED_ID,
            SEED_REVISION_ID,
            "e" * 64,
            CREATION_ID,
            "7" * 64,
            STYLE_CONTRACT_ID,
            "8" * 64,
            BINDING_ID,
            "f" * 64,
            "0" * 64,
            NOW,
        ),
    )
    await session.execute(
        """INSERT INTO project_bible_heads
           (project_id,revision,bible_revision_id,content_hash,updated_at)
           VALUES (%s,1,%s,%s,%s)""",
        (PROJECT_ID, BIBLE_REVISION_ID, "0" * 64, NOW),
    )


async def _insert_generation_ledgers(session) -> None:
    await session.execute(
        """INSERT INTO market_analyses
           (id,project_id,binding_revision_id,binding_hash,input_manifest_json,
            input_manifest_hash,policy_version,idempotency_key,request_hash,
            status,analysis_json,result_hash,public_error_code,created_at,
            completed_at)
           VALUES (%s,%s,%s,%s,'{}',%s,'ownership-v1',%s,%s,'succeeded','{}',
                   %s,NULL,%s,%s)""",
        (
            MARKET_ANALYSIS_ID, PROJECT_ID, BINDING_ID, "f" * 64,
            "a" * 64, "b" * 64, "c" * 64, "d" * 64, NOW, NOW,
        ),
    )
    await session.execute(
        """INSERT INTO seed_inspiration_attempts
           (id,project_id,selection_revision,market_source_id,
            market_snapshot_id,market_snapshot_hash,market_analysis_id,
            market_analysis_hash,binding_revision_id,binding_hash,
            input_manifest_json,input_manifest_hash,status,result_json,
            result_hash,public_error_code,created_at,completed_at)
           VALUES (%s,%s,NULL,%s,%s,%s,%s,%s,%s,%s,'{}',%s,'succeeded','{}',
                   %s,NULL,%s,%s)""",
        (
            SEED_ATTEMPT_ID, PROJECT_ID, MARKET_SOURCE_ID, MARKET_SNAPSHOT_ID,
            "9" * 64, MARKET_ANALYSIS_ID, "d" * 64, BINDING_ID, "f" * 64,
            "e" * 64, "1" * 64, NOW, NOW,
        ),
    )
    for attempt_table, request_table, attempt_id, request_id, result_hash in (
        (
            "seed_inspiration_attempts", "seed_inspiration_requests",
            SEED_ATTEMPT_ID, SEED_REQUEST_ID, "1" * 64,
        ),
        (
            "asset_recommendation_attempts", "asset_recommendation_requests",
            ASSET_ATTEMPT_ID, ASSET_REQUEST_ID, "2" * 64,
        ),
        (
            "style_trial_attempts", "style_trial_requests",
            STYLE_ATTEMPT_ID, STYLE_REQUEST_ID, "3" * 64,
        ),
    ):
        if attempt_table != "seed_inspiration_attempts":
            await session.execute(
                f"""INSERT INTO {attempt_table}
                    (id,project_id,selection_revision,binding_revision_id,
                     binding_hash,input_manifest_json,input_manifest_hash,
                     status,result_json,result_hash,public_error_code,created_at,
                     completed_at)
                    VALUES (%s,%s,1,%s,%s,'{{}}',%s,'succeeded','{{}}',%s,
                            NULL,%s,%s)""",
                (
                    attempt_id, PROJECT_ID, BINDING_ID, "f" * 64,
                    "4" * 64, result_hash, NOW, NOW,
                ),
            )
        await session.execute(
            f"""INSERT INTO {request_table}
                (id,project_id,idempotency_key,request_hash,status,attempt_id,
                 result_hash,public_error_code,created_at,completed_at)
                VALUES (%s,%s,%s,%s,'succeeded',%s,%s,NULL,%s,%s)""",
            (
                request_id, PROJECT_ID, request_id.replace("-", ""),
                "5" * 64, attempt_id, result_hash, NOW, NOW,
            ),
        )


async def _insert_planning_draft_canon_and_projections(session) -> None:
    await session.execute(
        """INSERT INTO volume_plans
           (id,project_id,selection_revision,contract_revision,contract_hash,
            bible_revision,bible_hash,manifest_hash,volume_num,title,
            direction_json,revision,status,created_at,updated_at)
           VALUES (%s,%s,1,1,%s,1,%s,%s,1,'Volume','{}',1,'active',%s,%s)""",
        (VOLUME_ID, PROJECT_ID, "7" * 64, "0" * 64, "2" * 64, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO story_blocks
           (id,project_id,volume_plan_id,block_num,title,goal_json,revision,status,
            created_at,updated_at)
           VALUES (%s,%s,%s,1,'Block','{}',1,'active',%s,%s)""",
        (BLOCK_ID, PROJECT_ID, VOLUME_ID, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO story_stages
           (id,project_id,story_block_id,stage_order,title,plan_json,revision,
            status,created_at,updated_at)
           VALUES (%s,%s,%s,1,'Stage','{}',1,'in_progress',%s,%s)""",
        (STAGE_ID, PROJECT_ID, BLOCK_ID, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO scene_tasks
           (id,project_id,story_stage_id,task_order,task_json,revision,status,
            created_at,updated_at)
           VALUES (%s,%s,%s,1,'{}',1,'in_progress',%s,%s)""",
        (SCENE_ID, PROJECT_ID, STAGE_ID, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO chapter_sessions
           (id,project_id,selection_revision,contract_revision,contract_hash,
            bible_revision,bible_hash,volume_plan_id,planning_manifest_hash,
            story_block_id,chapter_num,expected_canon_revision,
            expected_story_block_revision,planning_snapshot_json,status,
            created_at,finalized_at)
           VALUES (%s,%s,1,1,%s,1,%s,%s,%s,%s,1,1,1,'{}','drafting',%s,NULL)""",
        (
            SESSION_ID,
            PROJECT_ID,
            "7" * 64,
            "0" * 64,
            VOLUME_ID,
            "2" * 64,
            BLOCK_ID,
            NOW,
        ),
    )
    await session.execute(
        """INSERT INTO working_drafts
           (id,project_id,chapter_session_id,revision,content,content_hash,
            source_payload_json,updated_at)
           VALUES (%s,%s,%s,1,'working',%s,'{}',%s)""",
        (WORKING_ID, PROJECT_ID, SESSION_ID, "6" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO draft_candidates
           (id,project_id,chapter_session_id,working_draft_revision,content,
            content_hash,provenance_json,created_at)
           VALUES (%s,%s,%s,1,'draft',%s,'{}',%s)""",
        (CANDIDATE_ID, PROJECT_ID, SESSION_ID, "9" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO finalization_change_sets
           (id,project_id,draft_candidate_id,extraction_id,candidate_hash,
            expected_canon_revision,expected_story_block_revision,payload_json,
            content_hash,created_at,confirmed_at)
           VALUES (%s,%s,%s,'extraction',%s,1,1,'{}',%s,%s,%s)""",
        (CHANGE_SET_ID, PROJECT_ID, CANDIDATE_ID, "9" * 64, "7" * 64, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO finalization_records
           (id,project_id,chapter_session_id,draft_candidate_id,change_set_id,
            idempotency_key,candidate_hash,change_set_hash,
            expected_canon_revision,committed_canon_revision,
            result_payload_json,finalized_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1,2,'{}',%s)""",
        (
            FINALIZATION_ID,
            PROJECT_ID,
            SESSION_ID,
            CANDIDATE_ID,
            CHANGE_SET_ID,
            "8" * 64,
            "9" * 64,
            "7" * 64,
            NOW,
        ),
    )
    await session.execute(
        """INSERT INTO final_chapters
           (id,project_id,chapter_session_id,draft_candidate_id,
            finalization_record_id,chapter_num,title,content,content_hash,
            canon_revision,story_block_revision,planning_snapshot_json,
            finalized_at)
           VALUES (%s,%s,%s,%s,%s,1,'Final','final',%s,2,1,'{}',%s)""",
        (
            FINAL_CHAPTER_ID,
            PROJECT_ID,
            SESSION_ID,
            CANDIDATE_ID,
            FINALIZATION_ID,
            "a" * 64,
            NOW,
        ),
    )
    await session.execute(
        """INSERT INTO canon_entities
           (id,project_id,entity_type,canonical_name,normalized_name,
            created_revision,created_at)
           VALUES (%s,%s,'person','Name','name',1,%s)""",
        (ENTITY_ID, PROJECT_ID, NOW),
    )
    await session.execute(
        """INSERT INTO entity_aliases
           (id,project_id,entity_id,alias,normalized_alias,created_revision,
            created_at)
           VALUES (%s,%s,%s,'Alias','alias',1,%s)""",
        (ALIAS_ID, PROJECT_ID, ENTITY_ID, NOW),
    )
    await session.execute(
        """INSERT INTO canon_revisions
           (id,project_id,revision_number,parent_revision_number,idempotency_key,
            source_type,source_id,content_hash,created_at)
           VALUES (%s,%s,1,0,%s,'manual_test',NULL,%s,%s)""",
        (CANON_REVISION_ID, PROJECT_ID, "a" * 64, "b" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO canon_events
           (id,project_id,revision_id,revision_number,event_order,entity_id,
            fact_kind,field_path,value_json,evidence_json,effective_start_chapter,
            effective_end_chapter,assertion_operator,value_cardinality,
            confirmation_status,created_at)
           VALUES ('80000000-0000-0000-0000-000000000003',%s,%s,1,1,%s,
                   'claim','name','{}','{}',NULL,NULL,'equals','single',
                   'confirmed',%s)""",
        (PROJECT_ID, CANON_REVISION_ID, ENTITY_ID, NOW),
    )
    projection_rows = (
        (
            "current_state_projections",
            """(id,project_id,revision_number,entity_id,field_path,payload_json,
                 content_hash,created_at)
               VALUES ('90000000-0000-0000-0000-000000000001',%s,1,%s,
                       'name','{}',%s,%s)""",
            (PROJECT_ID, ENTITY_ID, "c" * 64, NOW),
        ),
        (
            "memory_views",
            """(id,project_id,revision_number,entity_id,subject_key,payload_json,
                 content_hash,created_at)
               VALUES ('90000000-0000-0000-0000-000000000002',%s,1,%s,
                       'subject','{}',%s,%s)""",
            (PROJECT_ID, ENTITY_ID, "d" * 64, NOW),
        ),
        (
            "arc_projections",
            """(id,project_id,revision_number,entity_id,arc_key,payload_json,
                 content_hash,created_at)
               VALUES ('90000000-0000-0000-0000-000000000003',%s,1,%s,
                       'arc','{}',%s,%s)""",
            (PROJECT_ID, ENTITY_ID, "e" * 64, NOW),
        ),
        (
            "plot_thread_projections",
            """(id,project_id,revision_number,entity_id,subject_key,field_path,
                 payload_json,content_hash,created_at)
               VALUES ('90000000-0000-0000-0000-000000000004',%s,1,%s,
                       'plot','state','{}',%s,%s)""",
            (PROJECT_ID, ENTITY_ID, "f" * 64, NOW),
        ),
    )
    for table, values, args in projection_rows:
        await session.execute(f"INSERT INTO {table} {values}", args)
    await session.execute(
        """INSERT INTO projection_heads
           (project_id,canon_revision_number,projection_revision_number,
            content_hash,updated_at)
           VALUES (%s,1,1,%s,%s)""",
        (PROJECT_ID, "1" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO reference_uses
           (id,project_id,chapter_session_id,draft_candidate_id,corpus_source_id,
            corpus_chapter_id,location_start,location_end,reference_purpose,
            referenced_text_hash,created_at)
           VALUES ('90000000-0000-0000-0000-000000000005',%s,%s,%s,%s,%s,
                   0,4,'generation',%s,%s)""",
        (
            PROJECT_ID,
            SESSION_ID,
            CANDIDATE_ID,
            CORPUS_SOURCE_ID,
            CORPUS_CHAPTER_ID,
            "2" * 64,
            NOW,
        ),
    )


@pytest.mark.asyncio
async def test_permanent_delete_removes_owned_graph_and_detaches_clone_provenance(
    disposable_mysql,
):
    session = disposable_mysql.session
    await _insert_project(session, PROJECT_ID, "Owned")
    await _insert_project(session, CLONE_ID, "Clone")
    await _insert_shared_rows(session)
    await _insert_seed_engine_and_contracts(session)
    await _insert_generation_ledgers(session)
    await _insert_planning_draft_canon_and_projections(session)

    assert await session.execute(
        """UPDATE projects SET archived_at=%s,lifecycle_revision=1
           WHERE id=%s""",
        (NOW, PROJECT_ID),
    ) == 1
    assert await ProjectRepository().permanently_delete(
        session, PROJECT_ID, 1
    ) is True

    assert await session.fetchone(
        "SELECT id FROM projects WHERE id=%s", (PROJECT_ID,)
    ) is None
    assert await session.fetchone(
        "SELECT id FROM projects WHERE id=%s", (CLONE_ID,)
    ) == {"id": CLONE_ID}
    assert await session.fetchone(
        """SELECT source_project_id FROM project_model_binding_revisions
           WHERE id=%s""",
        (CLONE_BINDING_ID,),
    ) == {"source_project_id": None}
    assert await session.fetchone(
        "SELECT COUNT(*) AS count FROM project_model_binding_revisions"
    ) == {"count": 1}
    for table in PRIVATE_TABLES_WITHOUT_CLONE_ROWS:
        assert await session.fetchone(
            f"SELECT COUNT(*) AS count FROM {table}"
        ) == {"count": 0}, table
    for table, row_id in (
        ("provider_profiles", PROVIDER_ID),
        ("style_templates", STYLE_TEMPLATE_ID),
        ("experience_cards", EXPERIENCE_CARD_ID),
        ("corpus_sources", CORPUS_SOURCE_ID),
        ("corpus_chapters", CORPUS_CHAPTER_ID),
        ("corpus_fragments", CORPUS_FRAGMENT_ID),
        ("corpus_import_runs", CORPUS_IMPORT_ID),
        ("corpus_source_revisions", CORPUS_REVISION_ID),
        ("market_sources", MARKET_SOURCE_ID),
        ("market_snapshots", MARKET_SNAPSHOT_ID),
    ):
        assert await session.fetchone(
            f"SELECT id FROM {table} WHERE id=%s", (row_id,)
        ) == {"id": row_id}
    assert await session.fetchone(
        """SELECT style_template_id FROM style_template_heads
           WHERE stable_key='shared-style'"""
    ) == {"style_template_id": STYLE_TEMPLATE_ID}
    assert await session.fetchone(
        """SELECT experience_card_id FROM experience_card_heads
           WHERE stable_key='shared-card'"""
    ) == {"experience_card_id": EXPERIENCE_CARD_ID}
    assert await session.fetchone(
        """SELECT revision_id FROM corpus_source_heads
           WHERE source_id=%s""",
        (CORPUS_SOURCE_ID,),
    ) == {"revision_id": CORPUS_REVISION_ID}
    assert await session.fetchone(
        "SELECT content_hash FROM corpus_blobs WHERE content_hash=%s",
        ("c" * 64,),
    ) == {"content_hash": "c" * 64}


@pytest.mark.asyncio
async def test_permanent_delete_failure_rolls_back_the_entire_owned_graph(
    disposable_mysql,
):
    session = disposable_mysql.session
    await _insert_project(session, PROJECT_ID, "Rollback")
    await _insert_project(session, CLONE_ID, "Clone")
    await _insert_shared_rows(session)
    await _insert_seed_engine_and_contracts(session)
    await _insert_generation_ledgers(session)
    await _insert_planning_draft_canon_and_projections(session)
    await session.execute(
        """UPDATE projects SET archived_at=%s,lifecycle_revision=1
           WHERE id=%s""",
        (NOW, PROJECT_ID),
    )

    class FailingDeleteRepository(ProjectRepository):
        async def _delete_owned_graph(self, tx_session, project_id):
            await super()._delete_owned_graph(tx_session, project_id)
            raise RuntimeError("controlled permanent-delete failure")

    transaction = transaction_factory_for(disposable_mysql.connection_config)
    with pytest.raises(RuntimeError, match="controlled permanent-delete failure"):
        async with transaction() as tx_session:
            await FailingDeleteRepository().permanently_delete(
                tx_session, PROJECT_ID, 1
            )

    assert await session.fetchone(
        "SELECT id FROM projects WHERE id=%s", (PROJECT_ID,)
    ) == {"id": PROJECT_ID}
    for table in (
        "project_seed_selection_revisions",
        "creation_contracts",
        "creation_bible_revisions",
        "volume_plans",
        "chapter_sessions",
        "final_chapters",
        "market_analyses",
        "seed_inspiration_attempts",
        "seed_inspiration_requests",
        "asset_recommendation_attempts",
        "asset_recommendation_requests",
        "style_trial_attempts",
        "style_trial_requests",
    ):
        assert await session.fetchone(
            f"SELECT COUNT(*) AS count FROM {table} WHERE project_id=%s",
            (PROJECT_ID,),
        ) == {"count": 1}, table
    assert await session.fetchone(
        "SELECT source_project_id FROM project_model_binding_revisions WHERE id=%s",
        (CLONE_BINDING_ID,),
    ) == {"source_project_id": PROJECT_ID}
    assert await session.fetchone(
        "SELECT id FROM corpus_sources WHERE id=%s", (CORPUS_SOURCE_ID,)
    ) == {"id": CORPUS_SOURCE_ID}


@pytest.mark.asyncio
async def test_cross_project_private_parent_references_are_rejected_by_family(
    disposable_mysql,
):
    session = disposable_mysql.session
    await _insert_project(session, PROJECT_ID, "Owned")
    await _insert_project(session, CLONE_ID, "Clone")
    await _insert_shared_rows(session)
    await _insert_seed_engine_and_contracts(session)
    await _insert_generation_ledgers(session)
    await _insert_planning_draft_canon_and_projections(session)

    cases = (
        (
            "seed",
            """INSERT INTO project_selected_seeds
               (project_id,seed_id,seed_revision_id,seed_hash,
                selection_revision,selected_at,updated_at)
               VALUES (%s,%s,%s,%s,1,%s,%s)""",
            (CLONE_ID, SEED_ID, SEED_REVISION_ID, "e" * 64, NOW, NOW),
            "DELETE FROM project_selected_seeds WHERE project_id=%s",
            (CLONE_ID,),
        ),
        (
            "binding",
            """INSERT INTO project_model_binding_heads
               (project_id,revision,binding_revision_id,content_hash,updated_at)
               VALUES (%s,1,%s,%s,%s)""",
            (CLONE_ID, BINDING_ID, "f" * 64, NOW),
            "DELETE FROM project_model_binding_heads WHERE project_id=%s",
            (CLONE_ID,),
        ),
        (
            "contracts",
            """INSERT INTO project_contract_drafts
               (project_id,id,selection_revision,base_head_revision,
                seed_revision_id,seed_hash,
                engine_option_id,draft_json,content_hash,draft_version,
                created_at,updated_at)
               VALUES (%s,'99000000-0000-0000-0000-000000000001',1,0,%s,%s,
                       %s,'{}',%s,1,%s,%s)""",
            (
                CLONE_ID,
                SEED_REVISION_ID,
                "e" * 64,
                OPTION_ID,
                "1" * 64,
                NOW,
                NOW,
            ),
            "DELETE FROM project_contract_drafts WHERE project_id=%s",
            (CLONE_ID,),
        ),
        (
            "planning",
            """INSERT INTO chapter_sessions
               (id,project_id,selection_revision,contract_revision,contract_hash,
                bible_revision,bible_hash,volume_plan_id,planning_manifest_hash,
                story_block_id,chapter_num,
                expected_canon_revision,expected_story_block_revision,
                planning_snapshot_json,status,created_at,finalized_at)
               VALUES ('99000000-0000-0000-0000-000000000002',%s,1,1,%s,
                       1,%s,%s,%s,%s,2,1,1,'{}','drafting',%s,NULL)""",
            (
                CLONE_ID,
                "7" * 64,
                "0" * 64,
                VOLUME_ID,
                "2" * 64,
                BLOCK_ID,
                NOW,
            ),
            """DELETE FROM chapter_sessions
               WHERE id='99000000-0000-0000-0000-000000000002'""",
            None,
        ),
        (
            "draft-finalization",
            """INSERT INTO finalization_change_sets
               (id,project_id,draft_candidate_id,extraction_id,candidate_hash,
                expected_canon_revision,expected_story_block_revision,
                payload_json,content_hash,created_at,confirmed_at)
               VALUES ('99000000-0000-0000-0000-000000000003',%s,%s,
                       'cross-extraction',%s,2,1,'{}',%s,%s,NULL)""",
            (CLONE_ID, CANDIDATE_ID, "2" * 64, "5" * 64, NOW),
            """DELETE FROM finalization_change_sets
               WHERE id='99000000-0000-0000-0000-000000000003'""",
            None,
        ),
        (
            "canon",
            """INSERT INTO entity_aliases
               (id,project_id,entity_id,alias,normalized_alias,
                created_revision,created_at)
               VALUES ('99000000-0000-0000-0000-000000000004',%s,%s,
                       'Cross','cross',1,%s)""",
            (CLONE_ID, ENTITY_ID, NOW),
            """DELETE FROM entity_aliases
               WHERE id='99000000-0000-0000-0000-000000000004'""",
            None,
        ),
        (
            "projections",
            """INSERT INTO current_state_projections
               (id,project_id,revision_number,entity_id,field_path,
                payload_json,content_hash,created_at)
               VALUES ('99000000-0000-0000-0000-000000000005',%s,1,%s,
                       'cross','{}',%s,%s)""",
            (CLONE_ID, ENTITY_ID, "3" * 64, NOW),
            """DELETE FROM current_state_projections
               WHERE id='99000000-0000-0000-0000-000000000005'""",
            None,
        ),
        (
            "reference-uses",
            """INSERT INTO reference_uses
               (id,project_id,chapter_session_id,draft_candidate_id,
                corpus_source_id,corpus_chapter_id,location_start,location_end,
                reference_purpose,referenced_text_hash,created_at)
               VALUES ('99000000-0000-0000-0000-000000000006',%s,%s,%s,
                       %s,%s,10,14,'review',%s,%s)""",
            (
                CLONE_ID,
                SESSION_ID,
                CANDIDATE_ID,
                CORPUS_SOURCE_ID,
                CORPUS_CHAPTER_ID,
                "4" * 64,
                NOW,
            ),
            """DELETE FROM reference_uses
               WHERE id='99000000-0000-0000-0000-000000000006'""",
            None,
        ),
    )

    accepted = []
    for family, sql, args, cleanup_sql, cleanup_args in cases:
        try:
            await session.execute(sql, args)
        except IntegrityError:
            continue
        accepted.append(family)
        await session.execute(cleanup_sql, cleanup_args)

    assert accepted == []
