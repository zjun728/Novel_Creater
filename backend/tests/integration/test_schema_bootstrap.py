import aiomysql
import pytest

from backend.schema_manifest import manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION, SchemaMismatch, verify_schema_version
from backend.scripts.initialize_database import InitializationError, initialize_database


EXPECTED_TABLES = {
    "schema_metadata", "projects", "creative_seeds", "creative_seed_revisions",
    "creative_seed_heads", "project_seed_selection_revisions",
    "project_selected_seeds", "provider_profiles",
    "provider_profile_mutation_requests", "application_settings",
    "project_model_binding_revisions", "project_model_binding_items",
    "project_model_binding_heads", "style_templates", "style_template_heads",
    "experience_cards", "experience_card_heads", "corpus_blobs",
    "corpus_sources", "corpus_source_revisions", "corpus_source_heads",
    "corpus_chapters", "corpus_fragments", "corpus_import_runs",
    "corpus_source_deletions",
    "market_sources", "market_source_refresh_states",
    "market_source_policy_revisions", "market_source_policy_heads",
    "market_refresh_requests", "market_snapshots", "market_snapshot_entries",
    "market_snapshot_manifests", "market_analyses",
    "seed_inspiration_attempts", "seed_inspiration_requests",
    "asset_recommendation_attempts", "asset_recommendation_requests",
    "style_trial_attempts", "style_trial_requests",
    "story_engine_batches", "story_engine_options", "project_contract_drafts",
    "creation_contracts", "style_contracts", "project_contract_heads",
    "contract_confirmation_requests", "creation_contract_engine_refs",
    "style_contract_template_refs", "creation_contract_experience_refs",
    "creation_contract_corpus_refs",
    "creation_contract_corpus_fragment_refs",
    "project_bible_drafts", "bible_generation_attempts",
    "creation_bible_revisions", "project_bible_heads",
    "bible_confirmation_requests", "volume_plans", "story_blocks",
    "story_stages", "scene_tasks", "chapter_sessions", "working_drafts",
    "draft_candidates", "finalization_change_sets", "finalization_records",
    "final_chapters", "canon_entities", "entity_aliases", "canon_revisions",
    "canon_events", "current_state_projections", "memory_views",
    "arc_projections", "plot_thread_projections", "projection_heads",
    "reference_uses",
}

TASK_KEYS = (
    "seed", "planning", "writing", "audit",
    "summary", "extraction", "polish", "market",
)
NOW = 1_720_000_000_123
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
PROJECT_ID = "00000000-0000-0000-0000-000000000001"
BINDING_ID = "00000000-0000-0000-0000-000000000002"


async def _insert_project(session, project_id=PROJECT_ID):
    await session.execute(
        """INSERT INTO projects
           (id,title,genre,description,target_words,target_chapters,status,
            current_chapter,created_at,updated_at)
           VALUES (%s,'Foundation','fantasy','fixture',100000,100,'drafting',0,%s,%s)""",
        (project_id, NOW, NOW),
    )


async def _insert_foundation_project(
    session,
    *,
    project_id=PROJECT_ID,
    binding_id=BINDING_ID,
    binding_hash=HASH_A,
):
    await _insert_project(session, project_id)
    await session.execute(
        """INSERT INTO project_model_binding_revisions
           (id,project_id,revision,content_hash,source_project_id,created_at)
           VALUES (%s,%s,1,%s,NULL,%s)""",
        (binding_id, project_id, binding_hash, NOW),
    )
    for task_key in TASK_KEYS:
        await session.execute(
            """INSERT INTO project_model_binding_items
               (binding_revision_id,task_key,resolution_status,provider_id,
                provider_name_snapshot,model_name_snapshot,item_hash)
               VALUES (%s,%s,'unbound',NULL,NULL,NULL,%s)""",
            (binding_id, task_key, binding_hash),
        )
    await session.execute(
        """INSERT INTO project_model_binding_heads
           (project_id,revision,binding_revision_id,content_hash,updated_at)
           VALUES (%s,1,%s,%s,%s)""",
        (project_id, binding_id, binding_hash, NOW),
    )
    await session.execute(
        """INSERT INTO project_contract_heads
           (project_id,revision,creation_contract_id,style_contract_id,
            creation_hash,style_hash,updated_at)
           VALUES (%s,0,NULL,NULL,NULL,NULL,%s)""",
        (project_id, NOW),
    )
    await session.execute(
        """INSERT INTO project_bible_heads
           (project_id,revision,bible_revision_id,content_hash,updated_at)
           VALUES (%s,0,NULL,NULL,%s)""",
        (project_id, NOW),
    )


async def _insert_market_context(
    session,
    *,
    project_id=PROJECT_ID,
    binding_id=BINDING_ID,
    binding_hash=HASH_A,
):
    source_id = "00000000-0000-0000-0000-000000000110"
    snapshot_id = "00000000-0000-0000-0000-000000000111"
    analysis_id = "00000000-0000-0000-0000-000000000112"
    snapshot_hash = HASH_B
    analysis_hash = HASH_C
    await session.execute(
        """INSERT INTO market_sources
           (id,stable_key,adapter_key,display_name,public_config_json,status,
            created_at,updated_at)
           VALUES (%s,'review-source','manual','Review Source','{}','active',%s,%s)""",
        (source_id, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO market_snapshots
           (id,source_id,captured_at,platform,ranking_name,category,source_url,
            content_hash,entry_count,created_at)
           VALUES (%s,%s,%s,'review','ranking','fiction',
                   'https://market.test/ranking',%s,1,%s)""",
        (snapshot_id, source_id, NOW, snapshot_hash, NOW),
    )
    await session.execute(
        """INSERT INTO market_analyses
           (id,project_id,binding_revision_id,binding_hash,input_manifest_json,
            input_manifest_hash,policy_version,idempotency_key,request_hash,
            status,analysis_json,result_hash,public_error_code,created_at,
            completed_at)
           VALUES (%s,%s,%s,%s,'{}',%s,'review-v1',%s,%s,'succeeded','{}',
                   %s,NULL,%s,%s)""",
        (
            analysis_id, project_id, binding_id, binding_hash, HASH_A,
            "m" * 64, HASH_B, analysis_hash, NOW, NOW,
        ),
    )
    return {
        "source_id": source_id,
        "snapshot_id": snapshot_id,
        "snapshot_hash": snapshot_hash,
        "analysis_id": analysis_id,
        "analysis_hash": analysis_hash,
    }


async def _insert_active_provider(session, provider_id, name):
    await session.execute(
        """INSERT INTO provider_profiles
           (id,name,provider_type,model_name,base_url,api_key,enabled,sort_order,
            stream,max_context_tokens,max_output_tokens,temperature,top_p,
            supports_json,supports_streaming,notes,thinking,lifecycle_status,
            deleted_at,created_at,updated_at)
           VALUES (%s,%s,'openai','model','https://provider.test','secret',1,0,
                   1,128000,8192,0.700,1.000,1,1,'',NULL,'active',NULL,%s,%s)""",
        (provider_id, name, NOW, NOW),
    )


async def _insert_revision_one_contracts(session):
    seed_id = "00000000-0000-0000-0000-000000000040"
    seed_revision_id = "00000000-0000-0000-0000-000000000041"
    creation_id = "00000000-0000-0000-0000-000000000042"
    style_id = "00000000-0000-0000-0000-000000000043"
    await _insert_foundation_project(session)
    await session.execute(
        "INSERT INTO creative_seeds (id,project_id,status,created_at,updated_at) VALUES (%s,%s,'candidate',%s,%s)",
        (seed_id, PROJECT_ID, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO creative_seed_revisions
           (id,project_id,seed_id,revision,payload_json,content_hash,created_at)
           VALUES (%s,%s,%s,1,%s,%s,%s)""",
        (seed_revision_id, PROJECT_ID, seed_id, '{}', HASH_A, NOW),
    )
    await session.execute(
        """INSERT INTO project_seed_selection_revisions
           (project_id,selection_revision,seed_id,seed_revision_id,seed_hash,selected_at)
           VALUES (%s,1,%s,%s,%s,%s)""",
        (PROJECT_ID, seed_id, seed_revision_id, HASH_A, NOW),
    )
    await session.execute(
        """INSERT INTO project_selected_seeds
           (project_id,seed_id,seed_revision_id,seed_hash,selection_revision,
            selected_at,updated_at)
           VALUES (%s,%s,%s,%s,1,%s,%s)""",
        (PROJECT_ID, seed_id, seed_revision_id, HASH_A, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO creation_contracts
           (id,project_id,revision,selection_revision,seed_id,seed_revision_id,seed_hash,
            binding_revision_id,binding_hash,channel_profile_key,genre_profile_key,
            quality_charter_version,total_word_min,total_word_max,
            chapter_capacity_policy,reference_manifest_json,
            reference_manifest_hash,content_json,content_hash,confirmed_at)
           VALUES (%s,%s,1,1,%s,%s,%s,%s,%s,'web','fantasy','quality-v1',
                   80000,120000,'按情节自然切章','{}',%s,%s,%s,%s)""",
        (creation_id, PROJECT_ID, seed_id, seed_revision_id, HASH_A, BINDING_ID, HASH_A, HASH_A, '{}', HASH_B, NOW),
    )
    await session.execute(
        """INSERT INTO style_contracts
           (id,project_id,creation_contract_id,revision,merged_style_json,
            likes_json,dislikes_json,content_hash,confirmed_at)
           VALUES (%s,%s,%s,1,%s,%s,%s,%s,%s)""",
        (style_id, PROJECT_ID, creation_id, '{}', '[]', '[]', HASH_C, NOW),
    )
    return creation_id, style_id


async def _insert_seed_revision(
    session,
    *,
    project_id=PROJECT_ID,
    seed_id="00000000-0000-0000-0000-000000000060",
    revision_id="00000000-0000-0000-0000-000000000061",
    content_hash=HASH_A,
):
    await session.execute(
        "INSERT INTO creative_seeds (id,project_id,status,created_at,updated_at) VALUES (%s,%s,'candidate',%s,%s)",
        (seed_id, project_id, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO creative_seed_revisions
           (id,project_id,seed_id,revision,payload_json,content_hash,created_at)
           VALUES (%s,%s,%s,1,%s,%s,%s)""",
        (revision_id, project_id, seed_id, '{}', content_hash, NOW),
    )
    return seed_id, revision_id


async def _insert_selection_revision(
    session,
    *,
    project_id=PROJECT_ID,
    seed_id,
    seed_revision_id,
    seed_hash=HASH_A,
    selection_revision=1,
):
    await session.execute(
        """INSERT INTO project_seed_selection_revisions
           (project_id,selection_revision,seed_id,seed_revision_id,seed_hash,selected_at)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (
            project_id, selection_revision, seed_id, seed_revision_id,
            seed_hash, NOW,
        ),
    )


async def _insert_provider_batch_state(
    session,
    *,
    status,
    attempt_id,
    attempt_started_at,
    lease_expires_at,
    raw_response_text,
    raw_response_hash,
    public_error_code,
    finished_at,
    provider_bound=True,
):
    provider_id = "00000000-0000-0000-0000-000000000090"
    batch_id = "00000000-0000-0000-0000-000000000091"
    await _insert_foundation_project(session)
    if provider_bound:
        await _insert_active_provider(session, provider_id, "Provider batch state")
    seed_id, seed_revision_id = await _insert_seed_revision(session)
    await _insert_selection_revision(
        session, seed_id=seed_id, seed_revision_id=seed_revision_id,
    )
    columns = (
        "id,project_id,selection_revision,source_type,seed_id,seed_revision_id,seed_hash,"
        "binding_revision_id,binding_hash,provider_id,model_name_snapshot,"
        "idempotency_key,request_json,request_hash,status,attempt_id,"
        "attempt_started_at,lease_expires_at,raw_response_text,raw_response_hash,"
        "public_error_code,created_at,finished_at"
    )
    placeholders = ",".join(("%s",) * 23)
    await session.execute(
        f"INSERT INTO story_engine_batches ({columns}) VALUES ({placeholders})",
        (
            batch_id, PROJECT_ID, 1, "provider", seed_id, seed_revision_id, HASH_A,
            BINDING_ID, HASH_A,
            provider_id if provider_bound else None,
            "model" if provider_bound else None,
            "i" * 64, "{}", HASH_B,
            status, attempt_id, attempt_started_at, lease_expires_at,
            raw_response_text, raw_response_hash, public_error_code, NOW,
            finished_at,
        ),
    )
    return batch_id


@pytest.mark.mysql
@pytest.mark.parametrize(
    ("status", "public_error_code", "finished_at"),
    (
        ("reserved", None, None),
        ("failed", "not_started", NOW),
        ("failed", "provider_configuration", NOW),
    ),
)
async def test_provider_null_snapshot_accepts_only_unattempted_states(
    disposable_mysql, status, public_error_code, finished_at,
):
    batch_id = await _insert_provider_batch_state(
        disposable_mysql.session,
        status=status,
        attempt_id=None,
        attempt_started_at=None,
        lease_expires_at=None,
        raw_response_text=None,
        raw_response_hash=None,
        public_error_code=public_error_code,
        finished_at=finished_at,
        provider_bound=False,
    )
    row = await disposable_mysql.session.fetchone(
        "SELECT status,provider_id,attempt_id FROM story_engine_batches WHERE id=%s",
        (batch_id,),
    )
    assert row == {"status": status, "provider_id": None, "attempt_id": None}


@pytest.mark.mysql
@pytest.mark.parametrize(
    (
        "status", "raw_response_text", "raw_response_hash",
        "public_error_code",
    ),
    (
        ("running", None, None, None),
        ("succeeded", "raw", HASH_C, None),
        ("failed", None, None, "provider_failed"),
        ("outcome_unknown", None, None, "outcome_unknown"),
    ),
)
async def test_provider_null_snapshot_rejects_every_attempted_state(
    disposable_mysql,
    status,
    raw_response_text,
    raw_response_hash,
    public_error_code,
):
    with pytest.raises(aiomysql.OperationalError, match="Check constraint"):
        await _insert_provider_batch_state(
            disposable_mysql.session,
            status=status,
            attempt_id="00000000-0000-0000-0000-000000000092",
            attempt_started_at=NOW,
            lease_expires_at=NOW,
            raw_response_text=raw_response_text,
            raw_response_hash=raw_response_hash,
            public_error_code=public_error_code,
            finished_at=None if status == "running" else NOW,
            provider_bound=False,
        )


async def _insert_cross_project_provenance_fixture(session):
    creation_id, _ = await _insert_revision_one_contracts(session)
    other_project = "00000000-0000-0000-0000-000000000070"
    other_seed = "00000000-0000-0000-0000-000000000071"
    other_seed_revision = "00000000-0000-0000-0000-000000000072"
    other_batch = "00000000-0000-0000-0000-000000000073"
    other_option = "00000000-0000-0000-0000-000000000074"
    await _insert_project(session, other_project)
    await _insert_seed_revision(
        session,
        project_id=other_project,
        seed_id=other_seed,
        revision_id=other_seed_revision,
    )
    await _insert_selection_revision(
        session,
        project_id=other_project,
        seed_id=other_seed,
        seed_revision_id=other_seed_revision,
    )
    await session.execute(
        """INSERT INTO story_engine_batches
           (id,project_id,selection_revision,source_type,seed_id,seed_revision_id,seed_hash,
            binding_revision_id,binding_hash,provider_id,model_name_snapshot,
            idempotency_key,request_json,request_hash,status,attempt_id,
            attempt_started_at,lease_expires_at,raw_response_text,raw_response_hash,
            public_error_code,created_at,finished_at)
           VALUES (%s,%s,1,'manual',%s,%s,%s,NULL,NULL,NULL,NULL,%s,%s,%s,
                   'succeeded',NULL,NULL,NULL,NULL,NULL,NULL,%s,%s)""",
        (
            other_batch, other_project, other_seed, other_seed_revision,
            HASH_A, "7" * 64, '{}', HASH_B, NOW, NOW,
        ),
    )
    await session.execute(
        """INSERT INTO story_engine_options
           (id,project_id,selection_revision,batch_id,option_order,payload_json,content_hash,created_at)
           VALUES (%s,%s,1,%s,1,%s,%s,%s)""",
        (other_option, other_project, other_batch, '{}', HASH_C, NOW),
    )
    return creation_id, other_seed_revision, other_option


async def _insert_corpus_source(session, status, public_error_code, analyzed_at):
    source_id = "00000000-0000-0000-0000-000000000080"
    revision_id = "00000000-0000-0000-0000-000000000081"
    content_hash = "8" * 64
    await session.execute(
        """INSERT INTO corpus_sources
           (id,source_key,archived_at,created_at,updated_at)
           VALUES (%s,'source.state',NULL,%s,%s)""",
        (source_id, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO corpus_blobs
           (content_hash,byte_length,storage_key,created_at)
           VALUES (%s,10,'corpus/source.state',%s)""",
        (content_hash, NOW),
    )
    await session.execute(
        """INSERT INTO corpus_source_revisions
           (id,source_id,revision,content_hash,relative_path,display_name,author,
            reference_tags_json,notes,provenance_json,byte_length,encoding,
            parser_version,normalizer_version,fragmenter_version,index_version,
            status,public_error_code,imported_at,analyzed_at,created_at)
           VALUES (%s,%s,1,%s,'state.txt','State','Author','[]','','{}',10,
                   'utf-8','p1','n1','f1','i1',%s,%s,%s,%s,%s)""",
        (
            revision_id, source_id, content_hash, status, public_error_code,
            NOW, analyzed_at, NOW,
        ),
    )


async def _index_column_sequences(session, table_name):
    rows = await session.fetchall(f"SHOW INDEX FROM `{table_name}`")
    by_name = {}
    for row in rows:
        by_name.setdefault(row["Key_name"], []).append(
            (row["Seq_in_index"], row["Column_name"])
        )
    return {
        tuple(column for _, column in sorted(columns))
        for columns in by_name.values()
    }


@pytest.mark.mysql
@pytest.mark.parametrize(
    ("enabled", "api_key", "base_url"),
    (
        (1, "", ""),
        (0, "secret", ""),
        (0, "", "https://provider.test"),
    ),
)
async def test_deleted_provider_rejects_enabled_or_retained_connection_secrets(
    disposable_mysql, enabled, api_key, base_url,
):
    provider_id = "00000000-0000-0000-0000-000000000030"
    await _insert_active_provider(disposable_mysql.session, provider_id, "Provider invalid delete")
    with pytest.raises(Exception):
        await disposable_mysql.session.execute(
            """UPDATE provider_profiles
               SET lifecycle_status='deleted',deleted_at=%s,enabled=%s,
                   api_key=%s,base_url=%s
               WHERE id=%s""",
            (NOW, enabled, api_key, base_url, provider_id),
        )


@pytest.mark.mysql
async def test_deleted_provider_accepts_disabled_and_cleared_connection_fields(disposable_mysql):
    await disposable_mysql.session.execute(
        """INSERT INTO provider_profiles
           (id,name,provider_type,model_name,base_url,api_key,enabled,sort_order,
            stream,max_context_tokens,max_output_tokens,temperature,top_p,
            supports_json,supports_streaming,notes,thinking,lifecycle_status,
            deleted_at,created_at,updated_at)
           VALUES ('00000000-0000-0000-0000-000000000031','Provider deleted',
                   'openai','model','','',0,0,1,128000,8192,0.700,1.000,
                   1,1,'',NULL,'deleted',%s,%s,%s)""",
        (NOW, NOW, NOW),
    )


@pytest.mark.mysql
@pytest.mark.parametrize(
    ("head_revision", "head_hash"),
    ((2, HASH_A), (1, HASH_B)),
)
async def test_seed_head_rejects_revision_or_hash_mismatch(
    disposable_mysql, head_revision, head_hash,
):
    await _insert_project(disposable_mysql.session)
    seed_id, revision_id = await _insert_seed_revision(disposable_mysql.session)
    with pytest.raises(Exception):
        await disposable_mysql.session.execute(
            """INSERT INTO creative_seed_heads
               (seed_id,revision_id,revision,content_hash,updated_at)
               VALUES (%s,%s,%s,%s,%s)""",
            (seed_id, revision_id, head_revision, head_hash, NOW),
        )


@pytest.mark.mysql
async def test_seed_head_accepts_matching_revision_identity_and_hash(disposable_mysql):
    await _insert_project(disposable_mysql.session)
    seed_id, revision_id = await _insert_seed_revision(disposable_mysql.session)
    await disposable_mysql.session.execute(
        """INSERT INTO creative_seed_heads
           (seed_id,revision_id,revision,content_hash,updated_at)
           VALUES (%s,%s,1,%s,%s)""",
        (seed_id, revision_id, HASH_A, NOW),
    )


@pytest.mark.mysql
@pytest.mark.parametrize("reference_kind", ("draft", "engine_ref"))
async def test_contract_provenance_rejects_cross_project_seed_or_option(
    disposable_mysql, reference_kind,
):
    creation_id, other_seed_revision, other_option = (
        await _insert_cross_project_provenance_fixture(disposable_mysql.session)
    )
    if reference_kind == "draft":
        sql = """INSERT INTO project_contract_drafts
                 (project_id,id,base_head_revision,selection_revision,
                  seed_revision_id,seed_hash,
                  engine_option_id,draft_json,content_hash,draft_version,
                  created_at,updated_at)
                 VALUES (%s,'00000000-0000-0000-0000-000000000075',0,1,%s,
                         %s,%s,%s,%s,1,%s,%s)"""
        params = (
            PROJECT_ID, other_seed_revision, HASH_A, other_option, '{}',
            HASH_B, NOW, NOW,
        )
    else:
        sql = """INSERT INTO creation_contract_engine_refs
                 (creation_contract_id,project_id,engine_option_id,engine_hash)
                 VALUES (%s,%s,%s,%s)"""
        params = (creation_id, PROJECT_ID, other_option, HASH_C)
    with pytest.raises(Exception):
        await disposable_mysql.session.execute(sql, params)


@pytest.mark.mysql
@pytest.mark.parametrize(
    ("status", "public_error_code", "analyzed_at"),
    (
        ("analyzed", None, None),
        ("imported", None, NOW),
        ("failed", "parse_failed", NOW),
    ),
)
async def test_corpus_source_rejects_inconsistent_terminal_timestamps(
    disposable_mysql, status, public_error_code, analyzed_at,
):
    with pytest.raises(Exception):
        await _insert_corpus_source(
            disposable_mysql.session, status, public_error_code, analyzed_at,
        )


@pytest.mark.mysql
@pytest.mark.parametrize(
    ("status", "public_error_code", "analyzed_at"),
    (
        ("imported", None, None),
        ("analyzed", None, NOW),
        ("failed", "parse_failed", None),
    ),
)
async def test_corpus_source_accepts_closed_status_states(
    disposable_mysql, status, public_error_code, analyzed_at,
):
    await _insert_corpus_source(
        disposable_mysql.session, status, public_error_code, analyzed_at,
    )


@pytest.mark.mysql
async def test_provenance_composite_foreign_keys_have_mysql_indexes(disposable_mysql):
    expected = {
        "creative_seed_revisions": {("project_id", "id")},
        "story_engine_batches": {("project_id", "id")},
        "story_engine_options": {
            ("project_id", "id"),
            ("project_id", "batch_id", "selection_revision"),
        },
        "project_contract_drafts": {
            ("project_id", "seed_revision_id"),
            ("project_id", "engine_option_id", "selection_revision"),
        },
        "creation_contract_engine_refs": {
            ("project_id", "creation_contract_id"),
            ("project_id", "engine_option_id"),
        },
    }
    for table_name, required in expected.items():
        actual = await _index_column_sequences(disposable_mysql.session, table_name)
        assert required <= actual, (table_name, actual)


@pytest.mark.mysql
async def test_fresh_bootstrap_has_exact_mysql8_schema_and_no_business_rows(disposable_mysql):
    version = await disposable_mysql.session.fetchone("SELECT VERSION() AS version")
    rows = await disposable_mysql.session.fetchall(
        """SELECT TABLE_NAME, ENGINE, TABLE_COLLATION
           FROM information_schema.TABLES
           WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME""",
        (disposable_mysql.database_name,),
    )
    metadata = await disposable_mysql.session.fetchone(
        "SELECT schema_version, manifest_hash FROM schema_metadata WHERE singleton_id=1"
    )

    assert {row["TABLE_NAME"] for row in rows} == EXPECTED_TABLES
    assert int(version["version"].split(".", 1)[0]) == 8
    assert len(rows) == len(EXPECTED_TABLES)
    assert {row["ENGINE"] for row in rows} == {"InnoDB"}
    assert {row["TABLE_COLLATION"] for row in rows} == {"utf8mb4_0900_ai_ci"}
    assert metadata == {
        "schema_version": EXPECTED_SCHEMA_VERSION,
        "manifest_hash": manifest_hash(),
    }
    settings = await disposable_mysql.session.fetchone(
        "SELECT singleton_id,fallback_provider_id,revision,updated_at "
        "FROM application_settings"
    )
    assert settings == {
        "singleton_id": 1,
        "fallback_provider_id": None,
        "revision": 0,
        "updated_at": 0,
    }
    for table_name in EXPECTED_TABLES - {"schema_metadata", "application_settings"}:
        row = await disposable_mysql.session.fetchone(f"SELECT COUNT(*) AS count FROM `{table_name}`")
        assert row["count"] == 0, table_name


@pytest.mark.mysql
async def test_seed_inspiration_attempt_can_pin_market_before_seed_selection(
    disposable_mysql,
):
    session = disposable_mysql.session
    await _insert_foundation_project(session)
    market = await _insert_market_context(session)
    attempt_id = "00000000-0000-0000-0000-000000000113"

    await session.execute(
        """INSERT INTO seed_inspiration_attempts
           (id,project_id,selection_revision,market_source_id,
            market_snapshot_id,market_snapshot_hash,market_analysis_id,
            market_analysis_hash,binding_revision_id,binding_hash,
            input_manifest_json,input_manifest_hash,status,result_json,
            result_hash,public_error_code,created_at,completed_at)
           VALUES (%s,%s,NULL,%s,%s,%s,%s,%s,%s,%s,'{}',%s,'reserved',
                   NULL,NULL,NULL,%s,NULL)""",
        (
            attempt_id, PROJECT_ID, market["source_id"], market["snapshot_id"],
            market["snapshot_hash"], market["analysis_id"],
            market["analysis_hash"], BINDING_ID, HASH_A, HASH_B, NOW,
        ),
    )

    row = await session.fetchone(
        """SELECT selection_revision,market_source_id,market_snapshot_id,
                  market_snapshot_hash,market_analysis_id,market_analysis_hash,
                  binding_revision_id,binding_hash,input_manifest_hash
             FROM seed_inspiration_attempts WHERE id=%s""",
        (attempt_id,),
    )
    assert row == {
        "selection_revision": None,
        "market_source_id": market["source_id"],
        "market_snapshot_id": market["snapshot_id"],
        "market_snapshot_hash": market["snapshot_hash"],
        "market_analysis_id": market["analysis_id"],
        "market_analysis_hash": market["analysis_hash"],
        "binding_revision_id": BINDING_ID,
        "binding_hash": HASH_A,
        "input_manifest_hash": HASH_B,
    }
    assert await session.fetchone(
        "SELECT 1 AS present FROM project_seed_selection_revisions "
        "WHERE project_id=%s",
        (PROJECT_ID,),
    ) is None


@pytest.mark.mysql
@pytest.mark.parametrize(
    ("attempt_table", "request_table"),
    (
        ("seed_inspiration_attempts", "seed_inspiration_requests"),
        ("asset_recommendation_attempts", "asset_recommendation_requests"),
        ("style_trial_attempts", "style_trial_requests"),
    ),
)
async def test_generation_request_ledgers_reject_cross_project_and_hash_splices(
    disposable_mysql, attempt_table, request_table,
):
    session = disposable_mysql.session
    other_project = "00000000-0000-0000-0000-000000000120"
    other_binding = "00000000-0000-0000-0000-000000000121"
    await _insert_foundation_project(session)
    await _insert_foundation_project(
        session,
        project_id=other_project,
        binding_id=other_binding,
        binding_hash=HASH_B,
    )
    attempt_id = "00000000-0000-0000-0000-000000000122"
    if attempt_table == "seed_inspiration_attempts":
        market = await _insert_market_context(session)
        await session.execute(
            """INSERT INTO seed_inspiration_attempts
               (id,project_id,selection_revision,market_source_id,
                market_snapshot_id,market_snapshot_hash,market_analysis_id,
                market_analysis_hash,binding_revision_id,binding_hash,
                input_manifest_json,input_manifest_hash,status,result_json,
                result_hash,public_error_code,created_at,completed_at)
               VALUES (%s,%s,NULL,%s,%s,%s,%s,%s,%s,%s,'{}',%s,'succeeded',
                       '{}',%s,NULL,%s,%s)""",
            (
                attempt_id, PROJECT_ID, market["source_id"],
                market["snapshot_id"], market["snapshot_hash"],
                market["analysis_id"], market["analysis_hash"], BINDING_ID,
                HASH_A, HASH_B, HASH_C, NOW, NOW,
            ),
        )
    else:
        seed_id, seed_revision_id = await _insert_seed_revision(session)
        await _insert_selection_revision(
            session, seed_id=seed_id, seed_revision_id=seed_revision_id,
        )
        await session.execute(
            f"""INSERT INTO {attempt_table}
                (id,project_id,selection_revision,binding_revision_id,
                 binding_hash,input_manifest_json,input_manifest_hash,status,
                 result_json,result_hash,public_error_code,created_at,completed_at)
                VALUES (%s,%s,1,%s,%s,'{{}}',%s,'succeeded','{{}}',%s,NULL,%s,%s)""",
            (
                attempt_id, PROJECT_ID, BINDING_ID, HASH_A, HASH_B,
                HASH_C, NOW, NOW,
            ),
        )

    insert_request = f"""INSERT INTO {request_table}
        (id,project_id,idempotency_key,request_hash,status,attempt_id,
         result_hash,public_error_code,created_at,completed_at)
        VALUES (%s,%s,%s,%s,'succeeded',%s,%s,NULL,%s,%s)"""
    with pytest.raises(Exception):
        await session.execute(
            insert_request,
            (
                "00000000-0000-0000-0000-000000000123",
                other_project, "x" * 64, HASH_A, attempt_id, HASH_C, NOW, NOW,
            ),
        )
    with pytest.raises(Exception):
        await session.execute(
            insert_request,
            (
                "00000000-0000-0000-0000-000000000124",
                PROJECT_ID, "y" * 64, HASH_A, attempt_id, HASH_B, NOW, NOW,
            ),
        )
    await session.execute(
        insert_request,
        (
            "00000000-0000-0000-0000-000000000125",
            PROJECT_ID, "z" * 64, HASH_A, attempt_id, HASH_C, NOW, NOW,
        ),
    )


@pytest.mark.mysql
async def test_generation_roots_reject_splices_and_allow_same_numbers_after_switch(
    disposable_mysql,
):
    session = disposable_mysql.session
    creation_one, _ = await _insert_revision_one_contracts(session)
    seed_id = "00000000-0000-0000-0000-000000000040"
    seed_revision_id = "00000000-0000-0000-0000-000000000041"
    creation_two = "00000000-0000-0000-0000-000000000130"
    bible_one = "00000000-0000-0000-0000-000000000131"
    bible_two = "00000000-0000-0000-0000-000000000132"
    contract_two_hash = "d" * 64
    bible_one_hash = "e" * 64
    bible_two_hash = "f" * 64
    await _insert_selection_revision(
        session,
        seed_id=seed_id,
        seed_revision_id=seed_revision_id,
        selection_revision=2,
    )
    await session.execute(
        """INSERT INTO creation_contracts
           (id,project_id,revision,selection_revision,seed_id,seed_revision_id,
            seed_hash,binding_revision_id,binding_hash,channel_profile_key,
            genre_profile_key,quality_charter_version,total_word_min,
            total_word_max,chapter_capacity_policy,reference_manifest_json,
            reference_manifest_hash,content_json,content_hash,confirmed_at)
           SELECT %s,project_id,2,2,seed_id,seed_revision_id,seed_hash,
                  binding_revision_id,binding_hash,channel_profile_key,
                  genre_profile_key,quality_charter_version,total_word_min,
                  total_word_max,chapter_capacity_policy,reference_manifest_json,
                  reference_manifest_hash,content_json,%s,confirmed_at
             FROM creation_contracts WHERE id=%s""",
        (creation_two, contract_two_hash, creation_one),
    )

    with pytest.raises(Exception):
        await session.execute(
            """INSERT INTO creation_bible_revisions
               (id,project_id,revision,selection_revision,seed_id,
                seed_revision_id,seed_hash,contract_revision,contract_hash,
                binding_revision_id,binding_hash,policy_version,content_json,
                content_hash,confirmed_at)
               VALUES ('00000000-0000-0000-0000-000000000133',%s,1,2,%s,%s,
                       %s,1,%s,%s,%s,'review-v1','{}',%s,%s)""",
            (
                PROJECT_ID, seed_id, seed_revision_id, HASH_A, HASH_B,
                BINDING_ID, HASH_A, "9" * 64, NOW,
            ),
        )
    await session.execute(
        """INSERT INTO creation_bible_revisions
           (id,project_id,revision,selection_revision,seed_id,seed_revision_id,
            seed_hash,contract_revision,contract_hash,binding_revision_id,
            binding_hash,policy_version,content_json,content_hash,confirmed_at)
           VALUES (%s,%s,1,1,%s,%s,%s,1,%s,%s,%s,'review-v1','{}',%s,%s)""",
        (
            bible_one, PROJECT_ID, seed_id, seed_revision_id, HASH_A, HASH_B,
            BINDING_ID, HASH_A, bible_one_hash, NOW,
        ),
    )
    await session.execute(
        """INSERT INTO creation_bible_revisions
           (id,project_id,revision,selection_revision,seed_id,seed_revision_id,
            seed_hash,contract_revision,contract_hash,binding_revision_id,
            binding_hash,policy_version,content_json,content_hash,confirmed_at)
           VALUES (%s,%s,2,2,%s,%s,%s,2,%s,%s,%s,'review-v1','{}',%s,%s)""",
        (
            bible_two, PROJECT_ID, seed_id, seed_revision_id, HASH_A,
            contract_two_hash, BINDING_ID, HASH_A, bible_two_hash, NOW,
        ),
    )

    bible_draft_two = "00000000-0000-0000-0000-000000000142"
    bible_draft_two_hash = "4" * 64
    await session.execute(
        """INSERT INTO project_bible_drafts
           (project_id,id,base_head_revision,selection_revision,seed_id,
            seed_revision_id,seed_hash,contract_revision,contract_hash,
            binding_revision_id,binding_hash,policy_version,draft_json,
            content_hash,draft_version,created_at,updated_at)
           VALUES (%s,%s,1,2,%s,%s,%s,2,%s,%s,%s,'review-v1','{}',%s,1,%s,%s)""",
        (
            PROJECT_ID, bible_draft_two, seed_id, seed_revision_id, HASH_A,
            contract_two_hash, BINDING_ID, HASH_A, bible_draft_two_hash, NOW, NOW,
        ),
    )
    with pytest.raises(Exception):
        await session.execute(
            """INSERT INTO bible_confirmation_requests
               (id,project_id,selection_revision,contract_revision,contract_hash,
                draft_id,draft_version,draft_hash,idempotency_key,request_hash,
                status,bible_revision_id,result_revision,result_hash,created_at,
                completed_at)
               VALUES ('00000000-0000-0000-0000-000000000143',%s,2,2,%s,%s,1,
                       %s,%s,%s,'succeeded',%s,1,%s,%s,%s)""",
            (
                PROJECT_ID, contract_two_hash, bible_draft_two,
                bible_draft_two_hash, "5" * 64, "6" * 64, bible_one,
                bible_one_hash, NOW, NOW,
            ),
        )
    await session.execute(
        """INSERT INTO bible_confirmation_requests
           (id,project_id,selection_revision,contract_revision,contract_hash,
            draft_id,draft_version,draft_hash,idempotency_key,request_hash,
            status,bible_revision_id,result_revision,result_hash,created_at,
            completed_at)
           VALUES ('00000000-0000-0000-0000-000000000144',%s,2,2,%s,%s,1,
                   %s,%s,%s,'succeeded',%s,2,%s,%s,%s)""",
        (
            PROJECT_ID, contract_two_hash, bible_draft_two, bible_draft_two_hash,
            "7" * 64, "8" * 64, bible_two, bible_two_hash, NOW, NOW,
        ),
    )

    with pytest.raises(Exception):
        await session.execute(
            """INSERT INTO volume_plans
               (id,project_id,selection_revision,contract_revision,
                contract_hash,bible_revision,bible_hash,manifest_hash,
                volume_num,title,direction_json,revision,status,created_at,
                updated_at)
               VALUES ('00000000-0000-0000-0000-000000000134',%s,2,1,%s,1,
                       %s,%s,1,'splice','{}',1,'active',%s,%s)""",
            (PROJECT_ID, HASH_B, bible_one_hash, "1" * 64, NOW, NOW),
        )

    volume_one = "00000000-0000-0000-0000-000000000135"
    volume_two = "00000000-0000-0000-0000-000000000136"
    block_one = "00000000-0000-0000-0000-000000000137"
    block_two = "00000000-0000-0000-0000-000000000138"
    manifest_one = "2" * 64
    manifest_two = "3" * 64
    await session.execute(
        """INSERT INTO volume_plans
           (id,project_id,selection_revision,contract_revision,contract_hash,
            bible_revision,bible_hash,manifest_hash,volume_num,title,
            direction_json,revision,status,created_at,updated_at)
           VALUES (%s,%s,1,1,%s,1,%s,%s,1,'generation one','{}',1,'active',
                   %s,%s)""",
        (volume_one, PROJECT_ID, HASH_B, bible_one_hash, manifest_one, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO volume_plans
           (id,project_id,selection_revision,contract_revision,contract_hash,
            bible_revision,bible_hash,manifest_hash,volume_num,title,
            direction_json,revision,status,created_at,updated_at)
           VALUES (%s,%s,2,2,%s,2,%s,%s,1,'generation two','{}',1,'active',
                   %s,%s)""",
        (
            volume_two, PROJECT_ID, contract_two_hash, bible_two_hash,
            manifest_two, NOW, NOW,
        ),
    )
    for block_id, volume_id in (
        (block_one, volume_one),
        (block_two, volume_two),
    ):
        await session.execute(
            """INSERT INTO story_blocks
               (id,project_id,volume_plan_id,block_num,title,goal_json,revision,
                status,created_at,updated_at)
               VALUES (%s,%s,%s,1,'block','{}',1,'active',%s,%s)""",
            (block_id, PROJECT_ID, volume_id, NOW, NOW),
        )

    session_columns = (
        "id,project_id,selection_revision,contract_revision,contract_hash,"
        "bible_revision,bible_hash,volume_plan_id,planning_manifest_hash,"
        "story_block_id,chapter_num,expected_canon_revision,"
        "expected_story_block_revision,planning_snapshot_json,status,"
        "created_at,finalized_at"
    )
    placeholders = ",".join(("%s",) * 17)
    await session.execute(
        f"INSERT INTO chapter_sessions ({session_columns}) VALUES ({placeholders})",
        (
            "00000000-0000-0000-0000-000000000139", PROJECT_ID, 1, 1,
            HASH_B, 1, bible_one_hash, volume_one, manifest_one, block_one, 1,
            0, 1, "{}", "drafting", NOW, None,
        ),
    )
    with pytest.raises(Exception):
        await session.execute(
            f"INSERT INTO chapter_sessions ({session_columns}) VALUES ({placeholders})",
            (
                "00000000-0000-0000-0000-000000000140", PROJECT_ID, 2, 2,
                contract_two_hash, 2, bible_two_hash, volume_one, manifest_one,
                block_one, 1, 0, 1, "{}", "drafting", NOW, None,
            ),
        )
    await session.execute(
        f"INSERT INTO chapter_sessions ({session_columns}) VALUES ({placeholders})",
        (
            "00000000-0000-0000-0000-000000000141", PROJECT_ID, 2, 2,
            contract_two_hash, 2, bible_two_hash, volume_two, manifest_two,
            block_two, 1, 0, 1, "{}", "drafting", NOW, None,
        ),
    )

    counts = await session.fetchone(
        """SELECT
             (SELECT COUNT(*) FROM volume_plans WHERE volume_num=1) AS volumes,
             (SELECT COUNT(*) FROM story_blocks WHERE block_num=1) AS blocks,
             (SELECT COUNT(*) FROM chapter_sessions WHERE chapter_num=1) AS sessions"""
    )
    assert counts == {"volumes": 2, "blocks": 2, "sessions": 2}


@pytest.mark.mysql
async def test_explicit_foundation_fixture_has_eight_bindings_and_zero_contract_head(disposable_mysql):
    await _insert_foundation_project(disposable_mysql.session)
    items = await disposable_mysql.session.fetchall(
        "SELECT task_key,resolution_status FROM project_model_binding_items WHERE binding_revision_id=%s ORDER BY task_key",
        (BINDING_ID,),
    )
    binding_head = await disposable_mysql.session.fetchone(
        "SELECT revision,binding_revision_id FROM project_model_binding_heads WHERE project_id=%s",
        (PROJECT_ID,),
    )
    contract_head = await disposable_mysql.session.fetchone(
        "SELECT revision,creation_contract_id,style_contract_id FROM project_contract_heads WHERE project_id=%s",
        (PROJECT_ID,),
    )
    assert len(items) == 8
    assert {row["task_key"] for row in items} == set(TASK_KEYS)
    assert {row["resolution_status"] for row in items} == {"unbound"}
    assert binding_head == {"revision": 1, "binding_revision_id": BINDING_ID}
    assert contract_head == {
        "revision": 0,
        "creation_contract_id": None,
        "style_contract_id": None,
    }


@pytest.mark.mysql
async def test_seed_foreign_keys_are_composite_and_assets_are_global(disposable_mysql):
    session = disposable_mysql.session
    other_project = "00000000-0000-0000-0000-000000000010"
    seed_id = "00000000-0000-0000-0000-000000000011"
    revision_id = "00000000-0000-0000-0000-000000000012"
    other_seed_id = "00000000-0000-0000-0000-000000000013"
    await _insert_project(session)
    await _insert_project(session, other_project)
    await session.execute(
        "INSERT INTO creative_seeds (id,project_id,status,created_at,updated_at) VALUES (%s,%s,'candidate',%s,%s)",
        (seed_id, PROJECT_ID, NOW, NOW),
    )
    await session.execute(
        "INSERT INTO creative_seeds (id,project_id,status,created_at,updated_at) VALUES (%s,%s,'candidate',%s,%s)",
        (other_seed_id, other_project, NOW, NOW),
    )
    with pytest.raises(Exception):
        await session.execute(
            """INSERT INTO creative_seed_revisions
               (id,project_id,seed_id,revision,payload_json,content_hash,created_at)
               VALUES ('00000000-0000-0000-0000-000000000014',%s,%s,1,%s,%s,%s)""",
            (other_project, seed_id, '{}', HASH_A, NOW),
        )
    await session.execute(
        """INSERT INTO creative_seed_revisions
           (id,project_id,seed_id,revision,payload_json,content_hash,created_at)
           VALUES (%s,%s,%s,1,%s,%s,%s)""",
        (revision_id, PROJECT_ID, seed_id, '{}', HASH_A, NOW),
    )
    with pytest.raises(Exception):
        await session.execute(
            """INSERT INTO creative_seed_heads
               (seed_id,revision_id,revision,content_hash,updated_at)
               VALUES (%s,%s,1,%s,%s)""",
            (other_seed_id, revision_id, HASH_A, NOW),
        )
    await session.execute(
        """INSERT INTO project_seed_selection_revisions
           (project_id,selection_revision,seed_id,seed_revision_id,seed_hash,selected_at)
           VALUES (%s,1,%s,%s,%s,%s)""",
        (PROJECT_ID, seed_id, revision_id, HASH_A, NOW),
    )
    await session.execute(
        """INSERT INTO project_selected_seeds
           (project_id,seed_id,seed_revision_id,seed_hash,selection_revision,selected_at,updated_at)
           VALUES (%s,%s,%s,%s,1,%s,%s)""",
        (PROJECT_ID, seed_id, revision_id, HASH_A, NOW, NOW),
    )
    with pytest.raises(Exception):
        await session.execute(
            """INSERT INTO project_selected_seeds
               (project_id,seed_id,seed_revision_id,seed_hash,selection_revision,selected_at,updated_at)
               VALUES (%s,%s,%s,%s,1,%s,%s)""",
            (other_project, seed_id, revision_id, HASH_A, NOW, NOW),
        )

    global_tables = (
        "style_templates", "style_template_heads", "experience_cards",
        "experience_card_heads", "corpus_blobs", "corpus_sources",
        "corpus_source_revisions", "corpus_source_heads",
        "corpus_chapters", "corpus_fragments", "corpus_import_runs",
    )
    for table_name in global_tables:
        columns = await session.fetchall(
            """SELECT COLUMN_NAME FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s""",
            (disposable_mysql.database_name, table_name),
        )
        assert "project_id" not in {row["COLUMN_NAME"] for row in columns}


@pytest.mark.mysql
async def test_succeeded_confirmation_rejects_result_revision_not_owned_by_contracts(disposable_mysql):
    creation_id, style_id = await _insert_revision_one_contracts(disposable_mysql.session)
    with pytest.raises(Exception):
        await disposable_mysql.session.execute(
            """INSERT INTO contract_confirmation_requests
               (id,project_id,selection_revision,idempotency_key,request_hash,status,
                creation_contract_id,style_contract_id,result_revision,
                public_error_code,created_at,completed_at)
               VALUES ('00000000-0000-0000-0000-000000000044',%s,1,%s,%s,
                       'succeeded',%s,%s,99,NULL,%s,%s)""",
            (PROJECT_ID, "d" * 64, "e" * 64, creation_id, style_id, NOW, NOW),
        )


@pytest.mark.mysql
@pytest.mark.parametrize(
    ("status", "public_error_code"),
    (("succeeded", None), ("failed", "provider_failed"), ("outcome_unknown", "outcome_unknown")),
)
async def test_provider_terminal_batch_rejects_missing_lease_marker(
    disposable_mysql, status, public_error_code,
):
    session = disposable_mysql.session
    provider_id = "00000000-0000-0000-0000-000000000050"
    seed_id = "00000000-0000-0000-0000-000000000051"
    seed_revision_id = "00000000-0000-0000-0000-000000000052"
    await _insert_foundation_project(session)
    await _insert_active_provider(session, provider_id, "Provider terminal lease")
    await session.execute(
        "INSERT INTO creative_seeds (id,project_id,status,created_at,updated_at) VALUES (%s,%s,'candidate',%s,%s)",
        (seed_id, PROJECT_ID, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO creative_seed_revisions
           (id,project_id,seed_id,revision,payload_json,content_hash,created_at)
           VALUES (%s,%s,%s,1,%s,%s,%s)""",
        (seed_revision_id, PROJECT_ID, seed_id, '{}', HASH_A, NOW),
    )
    await _insert_selection_revision(
        session, seed_id=seed_id, seed_revision_id=seed_revision_id,
    )
    with pytest.raises(Exception):
        await session.execute(
            """INSERT INTO story_engine_batches
               (id,project_id,selection_revision,source_type,seed_id,seed_revision_id,seed_hash,
                binding_revision_id,binding_hash,provider_id,model_name_snapshot,
                idempotency_key,request_json,request_hash,status,attempt_id,
                attempt_started_at,lease_expires_at,raw_response_text,
                raw_response_hash,public_error_code,created_at,finished_at)
               VALUES ('00000000-0000-0000-0000-000000000053',%s,1,'provider',
                       %s,%s,%s,%s,%s,%s,'model',%s,%s,%s,%s,
                       '00000000-0000-0000-0000-000000000054',%s,NULL,
                       'response',%s,%s,%s,%s)""",
            (
                PROJECT_ID, seed_id, seed_revision_id, HASH_A, BINDING_ID,
                HASH_A, provider_id, "f" * 64, '{}', HASH_B, status, NOW,
                HASH_C, public_error_code, NOW, NOW,
            ),
        )


@pytest.mark.mysql
async def test_provider_not_started_failure_accepts_no_attempt_or_raw_markers(
    disposable_mysql,
):
    batch_id = await _insert_provider_batch_state(
        disposable_mysql.session,
        status="failed",
        attempt_id=None,
        attempt_started_at=None,
        lease_expires_at=None,
        raw_response_text=None,
        raw_response_hash=None,
        public_error_code="not_started",
        finished_at=NOW,
    )
    row = await disposable_mysql.session.fetchone(
        """SELECT status,public_error_code,attempt_id,attempt_started_at,
                  lease_expires_at,raw_response_text,raw_response_hash,finished_at
           FROM story_engine_batches WHERE id=%s""",
        (batch_id,),
    )
    assert row == {
        "status": "failed",
        "public_error_code": "not_started",
        "attempt_id": None,
        "attempt_started_at": None,
        "lease_expires_at": None,
        "raw_response_text": None,
        "raw_response_hash": None,
        "finished_at": NOW,
    }


@pytest.mark.mysql
async def test_provider_outcome_unknown_accepts_exact_attempt_state(
    disposable_mysql,
):
    attempt_id = "00000000-0000-0000-0000-000000000092"
    batch_id = await _insert_provider_batch_state(
        disposable_mysql.session,
        status="outcome_unknown",
        attempt_id=attempt_id,
        attempt_started_at=NOW,
        lease_expires_at=NOW,
        raw_response_text=None,
        raw_response_hash=None,
        public_error_code="outcome_unknown",
        finished_at=NOW,
    )
    row = await disposable_mysql.session.fetchone(
        """SELECT status,public_error_code,attempt_id,attempt_started_at,
                  lease_expires_at,raw_response_text,raw_response_hash,finished_at
           FROM story_engine_batches WHERE id=%s""",
        (batch_id,),
    )
    assert row == {
        "status": "outcome_unknown",
        "public_error_code": "outcome_unknown",
        "attempt_id": attempt_id,
        "attempt_started_at": NOW,
        "lease_expires_at": NOW,
        "raw_response_text": None,
        "raw_response_hash": None,
        "finished_at": NOW,
    }


@pytest.mark.mysql
async def test_provider_succeeded_accepts_hash_only_and_never_plaintext(
    disposable_mysql,
):
    attempt_id = "00000000-0000-0000-0000-000000000092"
    batch_id = await _insert_provider_batch_state(
        disposable_mysql.session,
        status="succeeded",
        attempt_id=attempt_id,
        attempt_started_at=NOW,
        lease_expires_at=NOW,
        raw_response_text=None,
        raw_response_hash=HASH_C,
        public_error_code=None,
        finished_at=NOW,
    )
    row = await disposable_mysql.session.fetchone(
        """SELECT status,raw_response_text,raw_response_hash
           FROM story_engine_batches WHERE id=%s""",
        (batch_id,),
    )
    assert row == {
        "status": "succeeded",
        "raw_response_text": None,
        "raw_response_hash": HASH_C,
    }


@pytest.mark.mysql
@pytest.mark.parametrize(
    (
        "status", "attempt_id", "attempt_started_at", "lease_expires_at",
        "raw_response_text", "raw_response_hash", "public_error_code",
        "finished_at",
    ),
    (
        ("failed", "00000000-0000-0000-0000-000000000092", NOW, NOW,
         None, None, "invalid_response", NOW),
        ("failed", "00000000-0000-0000-0000-000000000092", NOW, NOW,
         None, HASH_C, "provider_failed", NOW),
        ("succeeded", "00000000-0000-0000-0000-000000000092", NOW, NOW,
         None, None, None, NOW),
        ("succeeded", "00000000-0000-0000-0000-000000000092", NOW, NOW,
         "raw", HASH_C, None, NOW),
        ("failed", "00000000-0000-0000-0000-000000000092", NOW, NOW,
         None, None, "not_started", NOW),
        ("failed", None, None, None, None, None, "provider_failed", NOW),
        ("outcome_unknown", None, None, None, None, None, "outcome_unknown", NOW),
        ("outcome_unknown", "00000000-0000-0000-0000-000000000092", NOW,
         NOW, None, None, "provider_failed", NOW),
        ("outcome_unknown", "00000000-0000-0000-0000-000000000092", NOW,
         NOW, "raw", HASH_C, "outcome_unknown", NOW),
        ("failed", None, None, None, "raw", HASH_C, "not_started", NOW),
        ("failed", None, None, None, None, None, "not_started", None),
    ),
)
async def test_provider_terminal_batch_rejects_non_exact_attempt_states(
    disposable_mysql,
    status,
    attempt_id,
    attempt_started_at,
    lease_expires_at,
    raw_response_text,
    raw_response_hash,
    public_error_code,
    finished_at,
):
    with pytest.raises(aiomysql.OperationalError, match="Check constraint"):
        await _insert_provider_batch_state(
            disposable_mysql.session,
            status=status,
            attempt_id=attempt_id,
            attempt_started_at=attempt_started_at,
            lease_expires_at=lease_expires_at,
            raw_response_text=raw_response_text,
            raw_response_hash=raw_response_hash,
            public_error_code=public_error_code,
            finished_at=finished_at,
        )


@pytest.mark.mysql
async def test_specialized_asset_refs_accept_valid_and_reject_invalid_revisions(disposable_mysql):
    session = disposable_mysql.session
    seed_id = "00000000-0000-0000-0000-000000000020"
    seed_revision_id = "00000000-0000-0000-0000-000000000021"
    batch_id = "00000000-0000-0000-0000-000000000022"
    option_id = "00000000-0000-0000-0000-000000000023"
    creation_id = "00000000-0000-0000-0000-000000000024"
    style_contract_id = "00000000-0000-0000-0000-000000000025"
    style_asset_id = "00000000-0000-0000-0000-000000000026"
    card_id = "00000000-0000-0000-0000-000000000027"
    source_id = "00000000-0000-0000-0000-000000000028"
    await _insert_foundation_project(session)
    await session.execute(
        "INSERT INTO creative_seeds (id,project_id,status,created_at,updated_at) VALUES (%s,%s,'candidate',%s,%s)",
        (seed_id, PROJECT_ID, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO creative_seed_revisions
           (id,project_id,seed_id,revision,payload_json,content_hash,created_at)
           VALUES (%s,%s,%s,1,%s,%s,%s)""",
        (seed_revision_id, PROJECT_ID, seed_id, '{}', HASH_A, NOW),
    )
    await _insert_selection_revision(
        session, seed_id=seed_id, seed_revision_id=seed_revision_id,
    )
    await session.execute(
        """INSERT INTO story_engine_batches
           (id,project_id,selection_revision,source_type,seed_id,seed_revision_id,seed_hash,
            binding_revision_id,binding_hash,provider_id,model_name_snapshot,
            idempotency_key,request_json,request_hash,status,attempt_id,
            attempt_started_at,lease_expires_at,raw_response_text,raw_response_hash,
            public_error_code,created_at,finished_at)
           VALUES (%s,%s,1,'manual',%s,%s,%s,NULL,NULL,NULL,NULL,%s,%s,%s,
                   'succeeded',NULL,NULL,NULL,NULL,NULL,NULL,%s,%s)""",
        (batch_id, PROJECT_ID, seed_id, seed_revision_id, HASH_A, HASH_B, '{}', HASH_B, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO story_engine_options
           (id,project_id,selection_revision,batch_id,option_order,payload_json,content_hash,created_at)
           VALUES (%s,%s,1,%s,1,%s,%s,%s)""",
        (option_id, PROJECT_ID, batch_id, '{}', HASH_C, NOW),
    )
    await session.execute(
        """INSERT INTO project_contract_drafts
           (project_id,id,base_head_revision,selection_revision,seed_revision_id,seed_hash,
            engine_option_id,draft_json,content_hash,draft_version,created_at,updated_at)
           VALUES (%s,'00000000-0000-0000-0000-000000000029',0,1,%s,%s,%s,%s,%s,1,%s,%s)""",
        (PROJECT_ID, seed_revision_id, HASH_A, option_id, '{}', HASH_B, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO creation_contracts
           (id,project_id,revision,selection_revision,seed_id,seed_revision_id,seed_hash,
            binding_revision_id,binding_hash,channel_profile_key,genre_profile_key,
            quality_charter_version,total_word_min,total_word_max,
            chapter_capacity_policy,reference_manifest_json,
            reference_manifest_hash,content_json,content_hash,confirmed_at)
           VALUES (%s,%s,1,1,%s,%s,%s,%s,%s,'web','fantasy','quality-v1',
                   80000,120000,'按情节自然切章','{}',%s,%s,%s,%s)""",
        (creation_id, PROJECT_ID, seed_id, seed_revision_id, HASH_A, BINDING_ID, HASH_A, HASH_A, '{}', HASH_B, NOW),
    )
    await session.execute(
        """INSERT INTO style_contracts
           (id,project_id,creation_contract_id,revision,merged_style_json,
            likes_json,dislikes_json,content_hash,confirmed_at)
           VALUES (%s,%s,%s,1,%s,%s,%s,%s,%s)""",
        (style_contract_id, PROJECT_ID, creation_id, '{}', '[]', '[]', HASH_C, NOW),
    )
    await session.execute(
        """INSERT INTO style_templates
           (id,stable_key,revision,name,payload_json,provenance_json,content_hash,status,created_at)
           VALUES (%s,'style.test',1,'Style',%s,%s,%s,'active',%s)""",
        (style_asset_id, '{}', '{}', HASH_A, NOW),
    )
    await session.execute(
        """INSERT INTO experience_cards
           (id,stable_key,revision,title,category,payload_json,provenance_json,content_hash,status,created_at)
           VALUES (%s,'card.test',1,'Card','plot_organization',%s,%s,%s,'active',%s)""",
        (card_id, '{}', '{}', HASH_B, NOW),
    )
    await session.execute(
        """INSERT INTO corpus_blobs
           (content_hash,byte_length,storage_key,created_at)
           VALUES (%s,10,'corpus/source.test',%s)""",
        (HASH_C, NOW),
    )
    await session.execute(
        """INSERT INTO corpus_sources
           (id,source_key,archived_at,created_at,updated_at)
           VALUES (%s,'source.test',NULL,%s,%s)""",
        (source_id, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO corpus_source_revisions
           (id,source_id,revision,content_hash,relative_path,display_name,author,
            reference_tags_json,notes,provenance_json,byte_length,encoding,
            parser_version,normalizer_version,fragmenter_version,index_version,
            status,public_error_code,imported_at,analyzed_at,created_at)
           VALUES ('00000000-0000-0000-0000-000000000035',%s,1,%s,
                   'book.txt','Book','Author','[]','','{}',10,'utf-8',
                   'p1','n1','f1','i1','analyzed',NULL,%s,%s,%s)""",
        (source_id, HASH_C, NOW, NOW, NOW),
    )

    await session.execute(
        "INSERT INTO creation_contract_engine_refs (creation_contract_id,project_id,engine_option_id,engine_hash) VALUES (%s,%s,%s,%s)",
        (creation_id, PROJECT_ID, option_id, HASH_C),
    )
    with pytest.raises(Exception):
        await session.execute(
            """INSERT INTO style_contract_template_refs
               (style_contract_id,role,style_template_id,asset_revision,asset_hash,sort_order)
               VALUES (%s,'primary',%s,1,%s,1)""",
            (style_contract_id, style_asset_id, HASH_B),
        )
    await session.execute(
        """INSERT INTO style_contract_template_refs
           (style_contract_id,role,style_template_id,asset_revision,asset_hash,sort_order)
           VALUES (%s,'primary',%s,1,%s,1)""",
        (style_contract_id, style_asset_id, HASH_A),
    )
    with pytest.raises(Exception):
        await session.execute(
            """INSERT INTO creation_contract_experience_refs
               (creation_contract_id,experience_card_id,asset_revision,asset_hash,sort_order)
               VALUES (%s,%s,1,%s,1)""",
            (creation_id, card_id, HASH_A),
        )
    await session.execute(
        """INSERT INTO creation_contract_experience_refs
           (creation_contract_id,experience_card_id,asset_revision,asset_hash,sort_order)
           VALUES (%s,%s,1,%s,1)""",
        (creation_id, card_id, HASH_B),
    )
    await session.execute(
        """INSERT INTO creation_contract_corpus_refs
           (creation_contract_id,corpus_source_id,source_revision,source_hash,selection_mode,sort_order)
           VALUES (%s,%s,1,%s,'author',1)""",
        (creation_id, source_id, HASH_C),
    )
    invalid_id = "00000000-0000-0000-0000-000000000099"
    invalid_statements = (
        ("INSERT INTO creation_contract_engine_refs (creation_contract_id,project_id,engine_option_id,engine_hash) VALUES (%s,%s,%s,%s)", (invalid_id, PROJECT_ID, option_id, HASH_C)),
        ("INSERT INTO style_contract_template_refs (style_contract_id,role,style_template_id,asset_revision,asset_hash,sort_order) VALUES (%s,'secondary',%s,2,%s,2)", (style_contract_id, style_asset_id, HASH_A)),
        ("INSERT INTO creation_contract_experience_refs (creation_contract_id,experience_card_id,asset_revision,asset_hash,sort_order) VALUES (%s,%s,2,%s,2)", (creation_id, card_id, HASH_B)),
        ("INSERT INTO creation_contract_corpus_refs (creation_contract_id,corpus_source_id,source_revision,source_hash,selection_mode,sort_order) VALUES (%s,%s,2,%s,'system',2)", (creation_id, source_id, HASH_C)),
    )
    for sql, params in invalid_statements:
        with pytest.raises(Exception):
            await session.execute(sql, params)


@pytest.mark.mysql
async def test_initializer_refuses_second_run_on_non_empty_database(disposable_mysql):
    with pytest.raises(InitializationError, match="not empty"):
        await initialize_database(
            disposable_mysql.admin_session,
            disposable_mysql.database_name,
            disposable_mysql.database_name,
            123,
        )
    rows = await disposable_mysql.session.fetchall(
        "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s",
        (disposable_mysql.database_name,),
    )
    assert {row["TABLE_NAME"] for row in rows} == EXPECTED_TABLES


@pytest.mark.mysql
async def test_metadata_mismatch_is_read_only_and_does_not_run_ddl(disposable_mysql):
    before = await disposable_mysql.session.fetchall(
        "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME",
        (disposable_mysql.database_name,),
    )
    await disposable_mysql.session.execute(
        "UPDATE schema_metadata SET schema_version=%s WHERE singleton_id=1",
        ("broken-version",),
    )
    with pytest.raises(SchemaMismatch, match="broken-version"):
        await verify_schema_version(disposable_mysql.session)
    after = await disposable_mysql.session.fetchall(
        "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME",
        (disposable_mysql.database_name,),
    )
    assert after == before
