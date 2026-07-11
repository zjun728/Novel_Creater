from __future__ import annotations

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
    "project_selected_seeds",
    "provider_profiles",
    "task_model_bindings",
    "task_model_binding_items",
    "creation_contracts",
    "style_contracts",
    "contract_asset_refs",
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
    "corpus_sources",
    "corpus_chapters",
    "style_templates",
    "experience_cards",
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
    assert len(EXPECTED_TABLES) == 34
    assert set(created_table_names()) == EXPECTED_TABLES
    assert len(created_table_names()) == len(EXPECTED_TABLES)


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
-- another comment
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
    assert ";-- statement must not split anything" in statements[1]
    assert created_table_names() == ("delimiter_example", "second_example")


def test_fragments_are_create_only_and_have_no_legacy_schema():
    statements = read_statements()
    upper = "\n".join(statements).upper()
    for banned in ("ALTER TABLE", "CREATE DATABASE", "IF NOT EXISTS"):
        assert banned not in upper
    assert all(not statement.lstrip().upper().startswith("USE ") for statement in statements)
    assert "LEGACY" not in upper
    assert "COMPATIBILITY" not in upper

    legacy_tables = {
        "chapters",
        "chapter_versions",
        "temp_drafts",
        "canon_facts",
        "characters",
        "plot_threads",
        "rolling_outlines",
        "project_volumes",
        "setting_entities",
        "setting_relations",
        "setting_change_events",
    }
    assert set(created_table_names()).isdisjoint(legacy_tables)


def test_every_table_uses_mysql8_storage_contract():
    for table_name in EXPECTED_TABLES:
        statement = _table_statement(table_name)
        assert "engine=innodb" in statement
        assert "default charset=utf8mb4" in statement
        assert "collate=utf8mb4_0900_ai_ci" in statement


def test_project_owned_tables_have_project_and_owner_foreign_keys():
    globally_owned = {"schema_metadata", "projects", "provider_profiles"}
    for table_name in EXPECTED_TABLES - globally_owned:
        statement = _table_statement(table_name)
        assert (
            "project_id char(36) not null" in statement
            or "project_id char(36) primary key" in statement
        )
        assert (
            "foreign key (project_id) references projects(id) on delete cascade"
            in statement
        )

    nested_owners = {
        "project_selected_seeds": "foreign key (seed_id) references creative_seeds(id)",
        "task_model_binding_items": "foreign key (binding_id) references task_model_bindings(id)",
        "contract_asset_refs": "foreign key (creation_contract_id) references creation_contracts(id)",
        "story_stages": "foreign key (story_block_id) references story_blocks(id)",
        "scene_tasks": "foreign key (story_stage_id) references story_stages(id)",
        "working_drafts": "foreign key (chapter_session_id) references chapter_sessions(id)",
        "draft_candidates": "foreign key (chapter_session_id) references chapter_sessions(id)",
        "finalization_change_sets": "foreign key (draft_candidate_id) references draft_candidates(id)",
        "corpus_chapters": "foreign key (corpus_source_id) references corpus_sources(id)",
    }
    for table_name, owner_fk in nested_owners.items():
        assert owner_fk in _table_statement(table_name)


def test_core_contracts_and_provider_constraints_are_explicit():
    selected = _table_statement("project_selected_seeds")
    assert "project_id char(36) primary key" in selected
    assert "unique key uq_selected_seed (seed_id)" in selected
    assert "foreign key (project_id) references projects(id) on delete cascade" in selected
    assert "foreign key (seed_id) references creative_seeds(id) on delete cascade" in selected

    providers = _table_statement("provider_profiles")
    for column in (
        "base_url varchar(2048) not null",
        "api_key text not null",
        "enabled tinyint(1) not null default 1",
        "sort_order int not null default 0",
    ):
        assert column in providers
    bindings = _table_statement("task_model_bindings")
    assert "unique key uq_binding_project (project_id)" in bindings
    items = _table_statement("task_model_binding_items")
    assert "unique key uq_binding_task (binding_id, task_key)" in items
    assert "foreign key (provider_id) references provider_profiles(id) on delete restrict" in items

    for contract in ("creation_contracts", "style_contracts"):
        statement = _table_statement(contract)
        assert "unique key" in statement and "(project_id)" in statement
        assert "revision int not null" in statement
        assert "check (revision > 0)" in statement
        assert "content_hash char(64) not null" in statement
    refs = _table_statement("contract_asset_refs")
    assert (
        "unique key uq_contract_asset (creation_contract_id, asset_type, asset_id)"
        in refs
    )


def test_planning_and_draft_invariants_are_explicit():
    planning = " ".join(
        _table_statement(name)
        for name in ("volume_plans", "story_blocks", "story_stages", "scene_tasks")
    )
    for key in (
        "unique key uq_volume_num (project_id, volume_num)",
        "unique key uq_block_num (project_id, block_num)",
        "unique key uq_stage_order (story_block_id, stage_order)",
        "unique key uq_scene_order (story_stage_id, task_order)",
    ):
        assert key in planning
    assert "check (status in ('planned','active','completed','failed','redirected'))" in planning
    assert planning.count("check (status in ('pending','in_progress','completed','cancelled'))") == 2
    for banned in ("target_chapter", "continuation_count", "forced_hook"):
        assert banned not in planning

    sessions = _table_statement("chapter_sessions")
    assert "check (status in ('drafting','final'))" in sessions
    assert "unique key uq_working_draft_session (chapter_session_id)" in _table_statement("working_drafts")
    candidates = _table_statement("draft_candidates")
    assert "unique key uq_candidate_hash (chapter_session_id, content_hash)" in candidates
    assert "updated_at" not in candidates
    final_chapters = _table_statement("final_chapters")
    assert "unique key uq_final_chapter_num (project_id, chapter_num)" in final_chapters
    assert "updated_at" not in final_chapters
    assert "finalization_record_id char(36) not null" in final_chapters
    changesets = _table_statement("finalization_change_sets")
    assert "unique key uq_changeset_candidate (draft_candidate_id, candidate_hash, expected_canon_revision)" in changesets
    assert "unique key uq_finalization_idempotency (idempotency_key)" in _table_statement("finalization_records")
    for required in ("payload_json json not null", "content_hash char(64) not null"):
        assert required in changesets


def test_canon_and_projection_invariants_are_explicit():
    entities = _table_statement("canon_entities")
    assert "check (entity_type in ('person','organization','place','item'))" in entities
    assert "key ix_entity_name (project_id, entity_type, normalized_name)" in entities
    assert "unique" not in entities.split("key ix_entity_name", 1)[0][-8:]

    aliases = _table_statement("entity_aliases")
    assert "unique key uq_entity_alias (project_id, entity_id, normalized_alias)" in aliases
    assert "key ix_alias_lookup (project_id, normalized_alias)" in aliases
    revisions = _table_statement("canon_revisions")
    assert "unique key uq_revision_number (project_id, revision_number)" in revisions
    assert "unique key uq_revision_idempotency (project_id, idempotency_key)" in revisions
    assert "check (source_type in ('bootstrap','finalization','manual_test'))" in revisions

    events = _table_statement("canon_events")
    for contract in (
        "entity_id char(36) null",
        "value_json json not null",
        "evidence_json json not null",
        "check (fact_kind in ('stable_definition','dynamic_event','claim'))",
        "check (assertion_operator in ('equals','not_equals'))",
        "check (value_cardinality in ('single','multi'))",
        "check (confirmation_status in ('confirmed','rejected'))",
        "check (effective_end_chapter is null or effective_start_chapter is null or effective_end_chapter >= effective_start_chapter)",
    ):
        assert contract in events

    for projection in (
        "current_state_projections",
        "memory_views",
        "arc_projections",
        "plot_thread_projections",
    ):
        statement = _table_statement(projection)
        assert "revision_number int not null" in statement
        assert "payload_json json not null" in statement
        assert "content_hash char(64) not null" in statement
        assert "unique key" in statement
    heads = _table_statement("projection_heads")
    assert "project_id char(36) primary key" in heads
    assert "content_hash char(64) not null" in heads
    assert "check (canon_revision_number >= 0)" in heads
    assert "check (projection_revision_number >= 0)" in heads

    memories = _table_statement("memory_views")
    assert "entity_id char(36) null" in memories
    assert "subject_key varchar(200) not null" in memories
    assert "unique key uq_memory_key (project_id, revision_number, subject_key)" in memories

    threads = _table_statement("plot_thread_projections")
    assert "entity_id char(36) null" in threads
    assert "subject_key varchar(200) not null" in threads
    assert "field_path varchar(200) not null" in threads
    assert "unique key uq_plot_thread_key (project_id, revision_number, subject_key, field_path)" in threads


def test_corpus_records_sources_content_analysis_and_reference_locations():
    sources = _table_statement("corpus_sources")
    for column in ("source_path", "source_hash", "status"):
        assert column in sources
    chapters = _table_statement("corpus_chapters")
    assert "normalized_text longtext not null" in chapters
    assert "content_hash char(64) not null" in chapters
    assert "payload_json json not null" in _table_statement("style_templates")
    assert "payload_json json not null" in _table_statement("experience_cards")
    uses = _table_statement("reference_uses")
    for column in (
        "chapter_session_id",
        "draft_candidate_id",
        "corpus_source_id",
        "corpus_chapter_id",
        "location_start",
        "location_end",
    ):
        assert column in uses
    corpus = " ".join(
        _table_statement(name)
        for name in ("corpus_sources", "corpus_chapters", "style_templates", "experience_cards", "reference_uses")
    )
    for secret in ("api_key", "base_url", "password"):
        assert secret not in corpus
