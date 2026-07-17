from __future__ import annotations

import pytest


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
STYLE_TEMPLATE_ID = "60000000-0000-0000-0000-000000000001"
EXPERIENCE_CARD_ID = "60000000-0000-0000-0000-000000000002"
CORPUS_SOURCE_ID = "60000000-0000-0000-0000-000000000003"
CORPUS_CHAPTER_ID = "60000000-0000-0000-0000-000000000004"
VOLUME_ID = "70000000-0000-0000-0000-000000000001"
BLOCK_ID = "70000000-0000-0000-0000-000000000002"
SESSION_ID = "70000000-0000-0000-0000-000000000003"
CANDIDATE_ID = "70000000-0000-0000-0000-000000000004"
ENTITY_ID = "80000000-0000-0000-0000-000000000001"
CANON_REVISION_ID = "80000000-0000-0000-0000-000000000002"


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
        """INSERT INTO experience_cards
           (id,stable_key,revision,title,category,payload_json,provenance_json,
            content_hash,status,created_at)
           VALUES (%s,'shared-card',1,'Shared Card','pacing','{}','{}',%s,
                   'active',%s)""",
        (EXPERIENCE_CARD_ID, "b" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO corpus_sources
           (id,source_key,revision,relative_path,title,author,source_hash,file_size,
            encoding,parser_version,normalizer_version,fragmenter_version,
            index_version,status,public_error_code,imported_at,analyzed_at)
           VALUES (%s,'shared-source',1,'shared.txt','Shared Source','Test',%s,4,
                   'utf-8','p1','n1','f1','i1','analyzed',NULL,%s,%s)""",
        (CORPUS_SOURCE_ID, "c" * 64, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO corpus_chapters
           (id,corpus_source_id,chapter_order,title,raw_byte_start,raw_byte_end,
            normalized_char_start,normalized_char_end,normalized_text,
            content_hash,created_at)
           VALUES (%s,%s,1,'Shared Chapter',0,4,0,4,'text',%s,%s)""",
        (CORPUS_CHAPTER_ID, CORPUS_SOURCE_ID, "d" * 64, NOW),
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
           (id,project_id,source_type,seed_id,seed_revision_id,seed_hash,
            binding_revision_id,binding_hash,provider_id,model_name_snapshot,
            idempotency_key,request_json,request_hash,status,attempt_id,
            attempt_started_at,lease_expires_at,raw_response_text,
            raw_response_hash,public_error_code,created_at,finished_at)
           VALUES (%s,%s,'manual',%s,%s,%s,NULL,NULL,NULL,NULL,%s,'{}',%s,
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
           (id,project_id,batch_id,option_order,payload_json,content_hash,created_at)
           VALUES (%s,%s,%s,1,'{}',%s,%s)""",
        (OPTION_ID, PROJECT_ID, BATCH_ID, "5" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO creation_contracts
           (id,project_id,revision,seed_id,seed_revision_id,seed_hash,
            binding_revision_id,binding_hash,channel_profile_key,genre_profile_key,
            quality_charter_version,total_word_min,total_word_max,
            chapter_capacity_policy,reference_manifest_json,
            reference_manifest_hash,content_json,content_hash,confirmed_at)
           VALUES (%s,%s,1,%s,%s,%s,%s,%s,'channel','genre','q1',1,2,
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


async def _insert_planning_draft_canon_and_projections(session) -> None:
    await session.execute(
        """INSERT INTO volume_plans
           (id,project_id,volume_num,title,direction_json,revision,status,
            created_at,updated_at)
           VALUES (%s,%s,1,'Volume','{}',1,'active',%s,%s)""",
        (VOLUME_ID, PROJECT_ID, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO story_blocks
           (id,project_id,volume_plan_id,block_num,title,goal_json,revision,status,
            created_at,updated_at)
           VALUES (%s,%s,%s,1,'Block','{}',1,'active',%s,%s)""",
        (BLOCK_ID, PROJECT_ID, VOLUME_ID, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO chapter_sessions
           (id,project_id,story_block_id,chapter_num,expected_canon_revision,
            expected_story_block_revision,planning_snapshot_json,status,
            created_at,finalized_at)
           VALUES (%s,%s,%s,1,1,1,'{}','drafting',%s,NULL)""",
        (SESSION_ID, PROJECT_ID, BLOCK_ID, NOW),
    )
    await session.execute(
        """INSERT INTO draft_candidates
           (id,project_id,chapter_session_id,working_draft_revision,content,
            content_hash,provenance_json,created_at)
           VALUES (%s,%s,%s,1,'draft',%s,'{}',%s)""",
        (CANDIDATE_ID, PROJECT_ID, SESSION_ID, "9" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO canon_entities
           (id,project_id,entity_type,canonical_name,normalized_name,
            created_revision,created_at)
           VALUES (%s,%s,'person','Name','name',1,%s)""",
        (ENTITY_ID, PROJECT_ID, NOW),
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
async def test_direct_project_delete_cascades_private_rows_and_detaches_clone_provenance(
    disposable_mysql,
):
    session = disposable_mysql.session
    await _insert_project(session, PROJECT_ID, "Owned")
    await _insert_project(session, CLONE_ID, "Clone")
    await _insert_shared_rows(session)
    await _insert_seed_engine_and_contracts(session)
    await _insert_planning_draft_canon_and_projections(session)

    assert await session.execute(
        "DELETE FROM projects WHERE id=%s", (PROJECT_ID,)
    ) == 1

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
    for table, row_id in (
        ("provider_profiles", PROVIDER_ID),
        ("style_templates", STYLE_TEMPLATE_ID),
        ("experience_cards", EXPERIENCE_CARD_ID),
        ("corpus_sources", CORPUS_SOURCE_ID),
        ("corpus_chapters", CORPUS_CHAPTER_ID),
    ):
        assert await session.fetchone(
            f"SELECT id FROM {table} WHERE id=%s", (row_id,)
        ) == {"id": row_id}
