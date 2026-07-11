import pytest

from backend.schema_manifest import manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION, SchemaMismatch, verify_schema_version
from backend.scripts.initialize_database import InitializationError, initialize_database


EXPECTED_TABLES = {
    "schema_metadata", "projects", "creative_seeds", "project_selected_seeds",
    "provider_profiles", "task_model_bindings", "task_model_binding_items",
    "creation_contracts", "style_contracts", "contract_asset_refs",
    "volume_plans", "story_blocks", "story_stages", "scene_tasks",
    "chapter_sessions", "working_drafts", "draft_candidates",
    "finalization_change_sets", "finalization_records", "final_chapters",
    "canon_entities", "entity_aliases", "canon_revisions", "canon_events",
    "current_state_projections", "memory_views", "arc_projections",
    "plot_thread_projections", "projection_heads", "corpus_sources",
    "corpus_chapters", "style_templates", "experience_cards", "reference_uses",
}


@pytest.mark.mysql
async def test_fresh_bootstrap_has_exact_mysql8_schema(disposable_mysql):
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
    assert len(rows) == 34
    assert {row["ENGINE"] for row in rows} == {"InnoDB"}
    assert all(row["TABLE_COLLATION"].startswith("utf8mb4_") for row in rows)
    assert metadata == {
        "schema_version": EXPECTED_SCHEMA_VERSION,
        "manifest_hash": manifest_hash(),
    }


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
