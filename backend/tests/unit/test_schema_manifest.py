from __future__ import annotations

import re
from hashlib import sha256

from backend import schema_manifest
from backend.schema_manifest import (
    FRAGMENTS,
    created_table_names,
    manifest_hash,
    read_statements,
)


EXPECTED_FRAGMENTS = (
    "00_metadata.sql",
    "10_core.sql",
    "15_assets.sql",
    "20_contracts.sql",
    "30_planning.sql",
    "40_drafts.sql",
    "50_canon.sql",
    "60_projections.sql",
    "70_corpus.sql",
)

EXPECTED_TABLES = {
    "schema_metadata",
    "projects",
    "creative_seeds",
    "creative_seed_revisions",
    "creative_seed_heads",
    "project_selected_seeds",
    "provider_profiles",
    "project_model_binding_revisions",
    "project_model_binding_items",
    "project_model_binding_heads",
    "style_templates",
    "style_template_heads",
    "experience_cards",
    "experience_card_heads",
    "corpus_sources",
    "corpus_chapters",
    "corpus_fragments",
    "corpus_import_runs",
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
    "volume_plans",
    "story_blocks",
    "story_stages",
    "scene_tasks",
    "chapter_sessions",
    "working_drafts",
    "draft_candidates",
    "final_chapters",
    "finalization_change_sets",
    "finalization_records",
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
}


def _compact(statement: str) -> str:
    return " ".join(statement.lower().split())


def _table_statement(table_name: str) -> str:
    prefix = f"create table {table_name} "
    return next(
        _compact(statement)
        for statement in read_statements()
        if _compact(statement).startswith(prefix)
    )


def test_manifest_has_exact_ordered_fragments_and_tables():
    assert FRAGMENTS == EXPECTED_FRAGMENTS
    assert set(created_table_names()) == EXPECTED_TABLES
    assert len(created_table_names()) == len(EXPECTED_TABLES) == 49
    assert set(created_table_names()).isdisjoint(
        {"task_model_bindings", "task_model_binding_items", "contract_asset_refs"}
    )


def test_manifest_uses_portable_normalized_hash(monkeypatch):
    statements = read_statements()
    expected_payload = "\n;-- statement\n".join(statements).encode("utf-8")
    assert manifest_hash() == sha256(expected_payload).hexdigest()
    assert len(manifest_hash()) == 64

    crlf_fragments = {}
    for fragment in FRAGMENTS:
        source = (schema_manifest.SCHEMA_DIR / fragment).read_text(encoding="utf-8")
        normalized = source.replace("\r\n", "\n").replace("\r", "\n")
        crlf_fragments[fragment] = normalized.replace("\n", "\r\n")

    class FakeFragment:
        def __init__(self, name):
            self.name = name

        def read_text(self, *, encoding):
            assert encoding == "utf-8"
            return crlf_fragments[self.name]

    class FakeSchemaDirectory:
        def __truediv__(self, fragment):
            return FakeFragment(fragment)

    monkeypatch.setattr(schema_manifest, "SCHEMA_DIR", FakeSchemaDirectory())
    assert manifest_hash() == sha256(expected_payload).hexdigest()


def test_manifest_parser_accepts_leading_sql_comments(monkeypatch):
    fragments = {name: "" for name in FRAGMENTS}
    fragments[FRAGMENTS[0]] = """-- bootstrap metadata comment
CREATE TABLE commented_table (
  id INT PRIMARY KEY
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement
"""

    class FakeFragment:
        def __init__(self, name):
            self.name = name

        def read_text(self, *, encoding):
            assert encoding == "utf-8"
            return fragments[self.name]

    class FakeSchemaDirectory:
        def __truediv__(self, fragment):
            return FakeFragment(fragment)

    monkeypatch.setattr(schema_manifest, "SCHEMA_DIR", FakeSchemaDirectory())
    assert created_table_names() == ("commented_table",)


def test_statement_delimiter_only_splits_when_it_is_an_independent_line(monkeypatch):
    fragments = {name: "" for name in FRAGMENTS}
    fragments[FRAGMENTS[0]] = """CREATE TABLE delimiter_example (
  id INT PRIMARY KEY,
  note VARCHAR(200) NOT NULL DEFAULT ';-- statement'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement
-- a comment mentioning ;-- statement must not split anything
CREATE TABLE second_example (
  id INT PRIMARY KEY
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement
"""

    class FakeFragment:
        def __init__(self, name):
            self.name = name

        def read_text(self, *, encoding):
            assert encoding == "utf-8"
            return fragments[self.name]

    class FakeSchemaDirectory:
        def __truediv__(self, fragment):
            return FakeFragment(fragment)

    monkeypatch.setattr(schema_manifest, "SCHEMA_DIR", FakeSchemaDirectory())
    statements = read_statements()
    assert len(statements) == 2
    assert "DEFAULT ';-- statement'" in statements[0]
    assert created_table_names() == ("delimiter_example", "second_example")


def test_fragments_are_the_only_create_only_empty_database_ddl_path():
    statements = read_statements()
    upper = "\n".join(statements).upper()
    for banned in (
        "ALTER TABLE",
        "CREATE DATABASE",
        "IF NOT EXISTS",
        "CREATE TRIGGER",
        "CREATE PROCEDURE",
        "CREATE EVENT",
        "MIGRATION",
        "COMPATIBILITY",
    ):
        assert banned not in upper
    assert all(not statement.lstrip().upper().startswith("USE ") for statement in statements)
    assert all(
        _compact(statement).startswith("create table ")
        for statement in statements
    )


def test_every_table_uses_mysql8_storage_contract():
    for table_name in EXPECTED_TABLES:
        statement = _table_statement(table_name)
        assert "engine=innodb" in statement
        assert "default charset=utf8mb4" in statement
        assert "collate=utf8mb4_0900_ai_ci" in statement


def test_revisioned_seed_and_selection_contracts_are_exact():
    seeds = _table_statement("creative_seeds")
    assert "unique key uq_seed_project_id (project_id, id)" in seeds
    assert "check (status in ('candidate','archived'))" in seeds
    revisions = _table_statement("creative_seed_revisions")
    for contract in (
        "unique key uq_seed_revision (seed_id, revision)",
        "unique key uq_seed_revision_id (seed_id, id)",
        "unique key uq_seed_revision_project_id (project_id, id)",
        "foreign key (project_id, seed_id) references creative_seeds(project_id, id) on delete restrict",
        "check (revision > 0)",
    ):
        assert contract in revisions
    heads = _table_statement("creative_seed_heads")
    assert "foreign key (seed_id, revision_id, revision, content_hash) references creative_seed_revisions(seed_id, id, revision, content_hash) on delete restrict" in heads
    selected = _table_statement("project_selected_seeds")
    assert "foreign key (project_id, seed_id) references creative_seeds(project_id, id) on delete restrict" in selected
    assert "foreign key (seed_id, seed_revision_id) references creative_seed_revisions(seed_id, id) on delete restrict" in selected


def test_provider_and_binding_revisions_encode_closed_state_spaces():
    providers = _table_statement("provider_profiles")
    assert "lifecycle_status varchar(16) not null" in providers
    assert "deleted_at bigint null" in providers
    assert "check (lifecycle_status in ('active','deleted'))" in providers
    revisions = _table_statement("project_model_binding_revisions")
    assert "unique key uq_binding_revision (project_id, revision)" in revisions
    assert "unique key uq_binding_revision_id (project_id, id)" in revisions
    items = _table_statement("project_model_binding_items")
    assert "primary key (binding_revision_id, task_key)" in items
    for task_key in (
        "seed", "planning", "writing", "audit",
        "summary", "extraction", "polish", "market",
    ):
        assert f"'{task_key}'" in items
    assert "check (resolution_status in ('bound','unbound'))" in items
    assert "foreign key (provider_id) references provider_profiles(id) on delete restrict" in items
    heads = _table_statement("project_model_binding_heads")
    assert "foreign key (project_id, binding_revision_id) references project_model_binding_revisions(project_id, id) on delete restrict" in heads


def test_global_assets_have_revision_heads_and_no_project_ownership():
    for table_name in (
        "style_templates", "style_template_heads", "experience_cards",
        "experience_card_heads", "corpus_sources", "corpus_chapters",
        "corpus_fragments", "corpus_import_runs",
    ):
        assert "project_id" not in _table_statement(table_name)
    styles = _table_statement("style_templates")
    assert "unique key uq_style_template_revision (stable_key, revision)" in styles
    assert "unique key uq_style_template_identity (stable_key, id)" in styles
    style_heads = _table_statement("style_template_heads")
    assert "foreign key (stable_key, style_template_id) references style_templates(stable_key, id) on delete restrict" in style_heads
    cards = _table_statement("experience_cards")
    assert "check (category in ('plot','ensemble','dialogue','emotion','interiority','information','rhythm','suspense'))" in cards
    corpus = _table_statement("corpus_sources")
    assert "unique key uq_corpus_source_revision (source_key, revision)" in corpus
    assert "unique key uq_corpus_source_import (source_hash, parser_version, normalizer_version, fragmenter_version, index_version)" in corpus
    assert "status = 'imported' and public_error_code is null and analyzed_at is null" in corpus
    assert "status = 'analyzed' and public_error_code is null and analyzed_at is not null and analyzed_at >= imported_at" in corpus
    assert "status = 'failed' and public_error_code is not null and analyzed_at is null" in corpus


def test_story_engine_drafts_and_contract_heads_are_revision_bound():
    batches = _table_statement("story_engine_batches")
    assert "unique key uq_engine_batch_idempotency (project_id, idempotency_key)" in batches
    assert "unique key uq_engine_batch_project_id (project_id, id)" in batches
    assert "check (source_type in ('provider','manual'))" in batches
    assert "check (status in ('reserved','running','succeeded','failed','outcome_unknown'))" in batches
    assert batches.count("lease_expires_at is not null") == 4
    assert (
        "status = 'failed' and public_error_code is not null "
        "and public_error_code = 'not_started' and attempt_id is null "
        "and attempt_started_at is null and lease_expires_at is null "
        "and raw_response_text is null and raw_response_hash is null "
        "and finished_at is not null"
    ) in batches
    assert (
        "status = 'failed' and attempt_id is not null "
        "and attempt_started_at is not null and lease_expires_at is not null "
        "and public_error_code is not null and public_error_code <> 'not_started' "
        "and finished_at is not null"
    ) in batches
    assert re.search(
        r"status = 'outcome_unknown' and attempt_id is not null "
        r"and attempt_started_at is not null and lease_expires_at is not null "
        r"and raw_response_text is null and raw_response_hash is null "
        r"and public_error_code = 'outcome_unknown' and finished_at is not null",
        batches,
    )
    options = _table_statement("story_engine_options")
    assert "project_id char(36) not null" in options
    assert "unique key uq_engine_option_order (batch_id, option_order)" in options
    assert "unique key uq_engine_option_project_id (project_id, id)" in options
    assert "foreign key (project_id, batch_id) references story_engine_batches(project_id, id) on delete restrict" in options
    assert "foreign key (batch_id)" not in options
    assert "check (option_order between 1 and 3)" in options
    drafts = _table_statement("project_contract_drafts")
    assert "project_id char(36) primary key" in drafts
    assert "unique key uq_contract_draft_id (id)" in drafts
    assert "foreign key (project_id, seed_revision_id) references creative_seed_revisions(project_id, id) on delete restrict" in drafts
    assert "foreign key (project_id, engine_option_id) references story_engine_options(project_id, id) on delete restrict" in drafts
    assert "foreign key (seed_revision_id)" not in drafts
    assert "foreign key (engine_option_id)" not in drafts
    heads = _table_statement("project_contract_heads")
    assert "check ((revision = 0" in heads
    assert "foreign key (project_id, creation_contract_id) references creation_contracts(project_id, id) on delete restrict" in heads
    requests = _table_statement("contract_confirmation_requests")
    assert "unique key uq_contract_confirmation_idempotency (project_id, idempotency_key)" in requests
    assert "foreign key (project_id, creation_contract_id, result_revision) references creation_contracts(project_id, id, revision) on delete restrict" in requests
    assert "foreign key (project_id, style_contract_id, result_revision) references style_contracts(project_id, id, revision) on delete restrict" in requests


def test_contracts_and_specialized_refs_use_real_revision_foreign_keys():
    creation = _table_statement("creation_contracts")
    for contract in (
        "unique key uq_creation_contract_revision (project_id, revision)",
        "unique key uq_creation_contract_id (project_id, id)",
        "foreign key (seed_id, seed_revision_id) references creative_seed_revisions(seed_id, id) on delete restrict",
        "foreign key (project_id, binding_revision_id) references project_model_binding_revisions(project_id, id) on delete restrict",
        "check (total_word_min > 0 and total_word_max >= total_word_min)",
        "check (chapter_char_min > 0 and chapter_char_target >= chapter_char_min and chapter_char_max >= chapter_char_target)",
    ):
        assert contract in creation
    style = _table_statement("style_contracts")
    assert "foreign key (project_id, creation_contract_id, revision) references creation_contracts(project_id, id, revision) on delete restrict" in style
    engine_refs = _table_statement("creation_contract_engine_refs")
    assert "project_id char(36) not null" in engine_refs
    assert "foreign key (project_id, creation_contract_id) references creation_contracts(project_id, id) on delete restrict" in engine_refs
    assert "foreign key (project_id, engine_option_id) references story_engine_options(project_id, id) on delete restrict" in engine_refs
    assert "foreign key (creation_contract_id)" not in engine_refs
    assert "foreign key (engine_option_id)" not in engine_refs
    assert "foreign key (style_template_id, asset_revision) references style_templates(id, revision) on delete restrict" in _table_statement("style_contract_template_refs")
    assert "foreign key (experience_card_id, asset_revision) references experience_cards(id, revision) on delete restrict" in _table_statement("creation_contract_experience_refs")
    assert "foreign key (corpus_source_id, source_revision) references corpus_sources(id, revision) on delete restrict" in _table_statement("creation_contract_corpus_refs")


def test_existing_planning_draft_canon_and_projection_tables_remain_present():
    unchanged = {
        "volume_plans", "story_blocks", "story_stages", "scene_tasks",
        "chapter_sessions", "working_drafts", "draft_candidates", "final_chapters",
        "finalization_change_sets", "finalization_records", "canon_entities",
        "entity_aliases", "canon_revisions", "canon_events",
        "current_state_projections", "memory_views", "arc_projections",
        "plot_thread_projections", "projection_heads", "reference_uses",
    }
    assert unchanged <= set(created_table_names())
