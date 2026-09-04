from __future__ import annotations

import re
from hashlib import sha256
from pathlib import Path

import pytest

from backend import schema_manifest
from backend.domain.assets import ASSET_CATEGORIES
from backend.schema_manifest import (
    FRAGMENTS,
    created_table_names,
    manifest_hash,
    read_fragment_statements,
    read_statements,
)


EXPECTED_FRAGMENTS = (
    "00_metadata.sql",
    "10_core.sql",
    "12_application.sql",
    "15_assets.sql",
    "18_market.sql",
    "19_topics.sql",
    "20_contracts.sql",
    "25_bible.sql",
    "30_planning.sql",
    "40_drafts.sql",
    "50_canon.sql",
    "60_projections.sql",
    "70_corpus.sql",
    "80_project_imports.sql",
)

EXPECTED_TABLES = {
    "schema_metadata",
    "projects",
    "creative_seeds",
    "creative_seed_revisions",
    "creative_seed_heads",
    "project_seed_selection_revisions",
    "project_selected_seeds",
    "provider_profiles",
    "provider_profile_mutation_requests",
    "application_settings",
    "project_model_binding_revisions",
    "project_model_binding_items",
    "project_model_binding_heads",
    "style_templates",
    "style_template_heads",
    "experience_cards",
    "experience_card_heads",
    "corpus_blobs",
    "corpus_sources",
    "corpus_source_revisions",
    "corpus_source_heads",
    "corpus_chapters",
    "corpus_fragments",
    "corpus_import_runs",
    "corpus_source_deletions",
    "market_sources",
    "market_source_refresh_states",
    "market_source_policy_revisions",
    "market_source_policy_heads",
    "market_refresh_requests",
    "market_snapshots",
    "market_snapshot_entries",
    "market_snapshot_manifests",
    "market_analyses",
    "seed_inspiration_attempts",
    "seed_inspiration_requests",
    "topic_discussions",
    "topic_discussion_messages",
    "topic_discussion_requests",
    "topic_directions",
    "topic_direction_versions",
    "topic_candidates",
    "topic_candidate_versions",
    "topic_project_handoffs",
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
    "creation_contract_corpus_fragment_refs",
    "project_bible_drafts",
    "bible_generation_attempts",
    "creation_bible_revisions",
    "project_bible_heads",
    "bible_confirmation_requests",
    "planning_drafts",
    "planning_generation_attempts",
    "planning_revisions",
    "project_planning_heads",
    "planning_confirmation_requests",
    "chapter_outline_drafts",
    "chapter_outline_generation_attempts",
    "chapter_outline_revisions",
    "project_chapter_outline_heads",
    "chapter_outline_confirmation_requests",
    "chapter_sessions",
    "working_drafts",
    "working_draft_revisions",
    "draft_operation_attempts",
    "draft_operation_events",
    "draft_candidates",
    "candidate_freeze_requests",
    "candidate_quality_reports",
    "final_chapters",
    "finalization_change_sets",
    "finalization_change_set_revisions",
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
    "project_package_import_commands",
    "project_import_provenance",
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


def _raw_table_statement(table_name: str) -> str:
    prefix = f"CREATE TABLE {table_name} "
    return next(
        statement
        for statement in read_statements()
        if statement.startswith(prefix)
    )


def test_manifest_has_exact_ordered_fragments_and_tables():
    assert FRAGMENTS == EXPECTED_FRAGMENTS
    assert set(created_table_names()) == EXPECTED_TABLES
    assert len(created_table_names()) == len(EXPECTED_TABLES) == 99
    assert set(created_table_names()).isdisjoint(
        {"task_model_bindings", "task_model_binding_items", "contract_asset_refs"}
    )


def test_fragment_reader_is_bounded_and_topic_fragment_has_exact_eight_tables():
    statements = read_fragment_statements("19_topics.sql")

    assert type(statements) is tuple
    assert len(statements) == 8
    assert all(_compact(statement).startswith("create table ") for statement in statements)
    with pytest.raises(ValueError, match="outside the schema manifest"):
        read_fragment_statements("../19_topics.sql")


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
    non_ddl = [
        _compact(statement)
        for statement in statements
        if not _compact(statement).startswith("create table ")
    ]
    assert non_ddl == [
        "insert into application_settings "
        "(singleton_id, fallback_provider_id, revision, updated_at) "
        "values (1, null, 0, 0)"
    ]


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
    history = _table_statement("project_seed_selection_revisions")
    assert "primary key (project_id, selection_revision)" in history
    assert "unique key uq_seed_selection_fact (project_id, selection_revision, seed_id, seed_revision_id, seed_hash)" in history
    assert "foreign key (project_id, seed_id, seed_revision_id, seed_hash) references creative_seed_revisions(project_id, seed_id, id, content_hash) on delete restrict" in history
    assert "foreign key (project_id, selection_revision, seed_id, seed_revision_id, seed_hash) references project_seed_selection_revisions(project_id, selection_revision, seed_id, seed_revision_id, seed_hash) on delete restrict" in selected


def test_provider_and_binding_revisions_encode_closed_state_spaces():
    project_statement = _table_statement("projects")
    raw_project_statement = _raw_table_statement("projects")
    assert "archived_at BIGINT NULL" in raw_project_statement
    assert "lifecycle_revision INT NOT NULL DEFAULT 0" in raw_project_statement
    assert "check (status in ('drafting','active','completed'))" in project_statement
    assert "check (lifecycle_revision >= 0)" in project_statement

    providers = _table_statement("provider_profiles")
    assert "lifecycle_status varchar(16) not null" in providers
    assert "deleted_at bigint null" in providers
    assert "revision int not null" in providers
    assert "check (lifecycle_status in ('active','unconfigured','deleted'))" in providers
    assert "lifecycle_status = 'unconfigured'" in providers
    assert "lifecycle_status = 'deleted'" in providers
    requests = _table_statement("provider_profile_mutation_requests")
    assert "unique key uq_provider_mutation_idempotency (provider_id, idempotency_key)" in requests
    assert "result_revision int null" in requests
    revisions = _table_statement("project_model_binding_revisions")
    binding_revision_statement = _raw_table_statement(
        "project_model_binding_revisions"
    )
    assert "unique key uq_binding_revision (project_id, revision)" in revisions
    assert "unique key uq_binding_revision_id (project_id, id)" in revisions
    assert (
        "FOREIGN KEY (source_project_id) REFERENCES projects(id) "
        "ON DELETE SET NULL"
    ) in binding_revision_statement
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
    assert (
        "foreign key (project_id, binding_revision_id, revision, content_hash) "
        "references project_model_binding_revisions(project_id, id, revision, "
        "content_hash) on delete cascade"
    ) in heads


def test_global_assets_have_revision_heads_and_no_project_ownership():
    for table_name in (
        "style_templates", "style_template_heads", "experience_cards",
        "experience_card_heads", "corpus_blobs", "corpus_sources",
        "corpus_source_revisions", "corpus_source_heads", "corpus_chapters",
        "corpus_fragments", "corpus_import_runs",
    ):
        assert "project_id" not in _table_statement(table_name)
    styles = _table_statement("style_templates")
    assert "unique key uq_style_template_revision (stable_key, revision)" in styles
    assert "unique key uq_style_template_head_ref (stable_key, id, revision, content_hash)" in styles
    assert "unique key uq_style_template_contract_ref (id, revision, content_hash)" in styles
    style_heads = _table_statement("style_template_heads")
    assert "foreign key (stable_key, style_template_id, revision, content_hash) references style_templates(stable_key, id, revision, content_hash) on delete restrict" in style_heads
    cards = _table_statement("experience_cards")
    expected_categories = ",".join(f"'{category}'" for category in ASSET_CATEGORIES)
    assert f"check (category in ({expected_categories}))" in cards
    assert "unique key uq_experience_card_head_ref (stable_key, id, revision, content_hash)" in cards
    assert "unique key uq_experience_card_contract_ref (id, revision, content_hash)" in cards
    card_heads = _table_statement("experience_card_heads")
    assert "foreign key (stable_key, experience_card_id, revision, content_hash) references experience_cards(stable_key, id, revision, content_hash) on delete restrict" in card_heads
    blobs = _table_statement("corpus_blobs")
    assert "content_hash char(64) primary key" in blobs
    corpus = _table_statement("corpus_source_revisions")
    assert "unique key uq_corpus_source_revision (source_id, revision)" in corpus
    assert "display_name varchar(300) not null" in corpus
    assert "reference_tags_json json not null" in corpus
    assert "notes text not null" in corpus
    assert "provenance_json json not null" in corpus
    assert "foreign key (content_hash) references corpus_blobs(content_hash) on delete restrict" in corpus
    heads = _table_statement("corpus_source_heads")
    assert "foreign key (source_id, revision_id, revision, content_hash) references corpus_source_revisions(source_id, id, revision, content_hash) on delete restrict" in heads


def test_application_settings_is_a_single_revision_zero_manifest_row():
    settings = _table_statement("application_settings")
    assert "singleton_id tinyint primary key" in settings
    assert "fallback_provider_id char(36) null" in settings
    assert "revision int not null" in settings
    assert "check (singleton_id = 1)" in settings
    assert "check (revision >= 0)" in settings

    statements = [_compact(statement) for statement in read_statements()]
    inserts = [statement for statement in statements if statement.startswith("insert into ")]
    assert inserts == [
        "insert into application_settings "
        "(singleton_id, fallback_provider_id, revision, updated_at) "
        "values (1, null, 0, 0)"
    ]


def test_topic_center_tables_keep_one_global_authority_and_atomic_handoff():
    topic_tables = {
        "topic_discussions",
        "topic_discussion_messages",
        "topic_discussion_requests",
        "topic_directions",
        "topic_direction_versions",
        "topic_candidates",
        "topic_candidate_versions",
        "topic_project_handoffs",
    }
    forbidden_owners = (
        "creation_contract",
        "bible",
        "planning",
        "chapter_session",
        "finalization",
        "canon_",
        "projection",
    )
    for table_name in topic_tables:
        statement = _table_statement(table_name)
        assert all(owner not in statement for owner in forbidden_owners)

    messages = _table_statement("topic_discussion_messages")
    assert "unique key uq_topic_message_sequence (discussion_id, sequence_number)" in messages
    assert "unique key uq_topic_message_owner (discussion_id, id)" in messages
    assert "check (role in ('user','assistant'))" in messages
    assert "foreign key (discussion_id) references topic_discussions(id) on delete restrict" in messages

    requests = _table_statement("topic_discussion_requests")
    assert "unique key uq_topic_request_idempotency (discussion_id, idempotency_key)" in requests
    assert "foreign key (provider_id) references provider_profiles(id) on delete restrict" in requests
    assert "check (status in ('reserved','running','succeeded','failed','outcome_unknown'))" in requests
    assert "provider_api_key" not in requests
    assert "base_url" not in requests

    directions = _table_statement("topic_directions")
    candidates = _table_statement("topic_candidates")
    assert "current_version int not null" in directions
    assert "current_version int not null" in candidates
    assert "check (status in ('active','archived'))" in candidates

    direction_versions = _table_statement("topic_direction_versions")
    candidate_versions = _table_statement("topic_candidate_versions")
    assert "unique key uq_topic_direction_version (direction_id, version)" in direction_versions
    assert "unique key uq_topic_candidate_version (candidate_id, version)" in candidate_versions
    assert "unique key uq_topic_candidate_version_fact (candidate_id, version, content_hash)" in candidate_versions
    assert "foreign key (discussion_id) references topic_discussions(id) on delete restrict" in direction_versions
    assert "foreign key (discussion_id) references topic_discussions(id) on delete restrict" in candidate_versions

    handoffs = _table_statement("topic_project_handoffs")
    assert "unique key uq_topic_handoff_idempotency (idempotency_key)" in handoffs
    assert "foreign key (candidate_id, candidate_version, candidate_hash) references topic_candidate_versions(candidate_id, version, content_hash) on delete restrict" in handoffs
    assert "foreign key (project_id, seed_id, seed_revision_id, seed_hash) references creative_seed_revisions(project_id, seed_id, id, content_hash) on delete restrict" in handoffs
    assert "check (seed_revision > 0)" in handoffs
    assert "project_selected_seeds" not in handoffs


def test_market_and_generation_ledgers_freeze_safe_identities():
    snapshots = _table_statement("market_snapshots")
    assert "unique key uq_market_snapshot_identity (source_id, id, captured_at, content_hash)" in snapshots
    assert "foreign key (source_id) references market_sources(id) on delete restrict" in snapshots
    entries = _table_statement("market_snapshot_entries")
    assert "foreign key (source_id, snapshot_id) references market_snapshots(source_id, id) on delete restrict" in entries
    manifests = _table_statement("market_snapshot_manifests")
    assert "foreign key (source_id, snapshot_id, snapshot_hash) references market_snapshots(source_id, id, content_hash) on delete restrict" in manifests
    for table_name in (
        "seed_inspiration_attempts",
        "asset_recommendation_attempts",
        "style_trial_attempts",
    ):
        attempt = _table_statement(table_name)
        assert "input_manifest_hash char(64) not null" in attempt
        assert "status varchar(24) not null" in attempt
        assert "result_hash char(64) null" in attempt
    for table_name in (
        "seed_inspiration_requests",
        "asset_recommendation_requests",
        "style_trial_requests",
    ):
        request = _table_statement(table_name)
        assert "idempotency_key char(64) not null" in request
        assert "request_hash char(64) not null" in request
        assert "status varchar(24) not null" in request

    recommendation_attempt = _table_statement("asset_recommendation_attempts")
    recommendation_request = _table_statement("asset_recommendation_requests")
    assert "status in ('running','succeeded','failed','outcome_unknown')" in (
        recommendation_attempt
    )
    assert "status in ('running','succeeded','failed','outcome_unknown')" in (
        recommendation_request
    )
    assert (
        "status = 'running' and attempt_id is not null and result_hash is null"
        in recommendation_request
    )
    assert "status = 'reserved' and attempt_id is null" not in (
        recommendation_request
    )

    style_trial_attempt = _table_statement("style_trial_attempts")
    style_trial_request = _table_statement("style_trial_requests")
    assert "status in ('running','succeeded','failed','outcome_unknown')" in (
        style_trial_attempt
    )
    assert "status in ('running','succeeded','failed','outcome_unknown')" in (
        style_trial_request
    )
    assert (
        "status = 'running' and attempt_id is not null and result_hash is null"
        in style_trial_request
    )
    assert "status = 'reserved'" not in style_trial_attempt
    assert "status = 'reserved'" not in style_trial_request


def test_planning_manifest_replaces_mutable_tables_with_ordered_aggregate_ledgers():
    created = created_table_names()
    planning_tables = (
        "planning_drafts",
        "planning_generation_attempts",
        "planning_revisions",
        "project_planning_heads",
        "planning_confirmation_requests",
        "chapter_outline_drafts",
        "chapter_outline_generation_attempts",
        "chapter_outline_revisions",
        "project_chapter_outline_heads",
        "chapter_outline_confirmation_requests",
    )
    assert tuple(name for name in created if name in planning_tables) == planning_tables
    assert set(created).isdisjoint(
        {"volume_plans", "story_blocks", "story_stages", "scene_tasks"}
    )
    for table_name in planning_tables:
        statement = _table_statement(table_name)
        assert (
            "project_id char(36) not null" in statement
            or "project_id char(36) primary key" in statement
        )


def test_planning_draft_pins_exact_basis_and_has_one_active_slot():
    draft = _table_statement("planning_drafts")
    for column in (
        "active_slot tinyint null",
        "base_head_revision int not null",
        "draft_revision int not null",
        "selection_revision int not null",
        "seed_id char(36) not null",
        "seed_revision_id char(36) not null",
        "seed_hash char(64) not null",
        "contract_revision int not null",
        "creation_contract_id char(36) not null",
        "creation_hash char(64) not null",
        "style_contract_id char(36) not null",
        "style_hash char(64) not null",
        "bible_revision int not null",
        "bible_revision_id char(36) not null",
        "bible_hash char(64) not null",
        "content_json json not null",
        "content_hash char(64) not null",
        "source_attempt_id char(36) null",
        "status varchar(24) not null",
    ):
        assert column in draft
    for contract in (
        "unique key uq_planning_draft_project_id (project_id, id)",
        "unique key uq_planning_draft_active_slot (project_id, active_slot)",
        "foreign key (project_id, selection_revision, seed_id, seed_revision_id, seed_hash) references project_seed_selection_revisions(project_id, selection_revision, seed_id, seed_revision_id, seed_hash) on delete restrict",
        "foreign key (project_id, creation_contract_id, contract_revision, creation_hash) references creation_contracts(project_id, id, revision, content_hash) on delete restrict",
        "foreign key (project_id, style_contract_id, contract_revision, style_hash) references style_contracts(project_id, id, revision, content_hash) on delete restrict",
        "foreign key (project_id, bible_revision_id, selection_revision, contract_revision, creation_hash, style_hash, bible_revision, bible_hash) references creation_bible_revisions(project_id, id, selection_revision, contract_revision, creation_hash, style_hash, revision, content_hash) on delete restrict",
        "check (active_slot is null or active_slot = 1)",
        "check (status in ('active','confirmed','superseded'))",
        "status = 'active' and active_slot is not null and active_slot = 1",
        "status in ('confirmed','superseded') and active_slot is null",
    ):
        assert contract in draft
    assert "foreign key (source_attempt_id)" not in draft


def test_planning_generation_attempts_freeze_model_lease_fence_and_closed_states():
    for table_name, draft_column, loaded_column, draft_table in (
        (
            "planning_generation_attempts",
            "draft_id",
            "loaded_draft_revision",
            "planning_drafts",
        ),
        (
            "chapter_outline_generation_attempts",
            "outline_draft_id",
            "loaded_outline_draft_revision",
            "chapter_outline_drafts",
        ),
    ):
        attempt = _table_statement(table_name)
        for column in (
            f"{draft_column} char(36) not null",
            "operation_id char(36) not null",
            "active_slot tinyint null",
            "idempotency_key varchar(64) not null",
            "request_fingerprint char(64) not null",
            "binding_revision_id char(36) not null",
            "binding_revision int not null",
            "binding_hash char(64) not null",
            "provider_id char(36) not null",
            "model_name_snapshot varchar(200) not null",
            "fencing_token bigint not null",
            "lease_expires_at bigint not null",
            "input_manifest_json json not null",
            "input_manifest_hash char(64) not null",
            "result_content_json json null",
            "result_content_hash char(64) null",
            f"{loaded_column} int null",
            "loaded_at bigint null",
            "failure_code varchar(64) null",
            "status varchar(24) not null",
            "created_at bigint not null",
            "updated_at bigint not null",
        ):
            assert column in attempt
        unique_contracts = (
            (
                "unique key uq_planning_operation (project_id, operation_id)",
                "unique key uq_planning_generation_idempotency (project_id, idempotency_key)",
                "unique key uq_active_planning_generation (draft_id, active_slot)",
                "unique key uq_planning_fencing (draft_id, fencing_token)",
            )
            if table_name == "planning_generation_attempts"
            else (
                "unique key uq_outline_operation (project_id, operation_id)",
                "unique key uq_outline_generation_idempotency (project_id, idempotency_key)",
                "unique key uq_active_outline_generation (outline_draft_id, active_slot)",
                "unique key uq_outline_fencing (outline_draft_id, fencing_token)",
            )
        )
        for contract in (
            *unique_contracts,
            f"foreign key (project_id, {draft_column}) references {draft_table}(project_id, id) on delete restrict",
            "foreign key (project_id, binding_revision_id, binding_revision, binding_hash) references project_model_binding_revisions(project_id, id, revision, content_hash) on delete restrict",
            "foreign key (provider_id) references provider_profiles(id) on delete restrict",
            "check (status in ('pending','succeeded','failed','superseded'))",
            "status = 'succeeded'",
            "status = 'failed'",
            "status = 'superseded'",
        ):
            assert contract in attempt
        assert (
            attempt.count(
                "status = 'pending' and active_slot is not null "
                "and active_slot = 1"
            )
            == 2
        )
        assert (
            f"{loaded_column} is not null and {loaded_column} > 0 "
            "and loaded_at is not null"
        ) in attempt
        assert "prompt" not in attempt
        assert "raw_output" not in attempt
        assert "api_key" not in attempt


def test_planning_revision_head_and_confirmation_are_exact_and_immutable():
    revision = _table_statement("planning_revisions")
    for contract in (
        "revision int not null",
        "parent_revision int not null",
        "content_json json not null",
        "content_hash char(64) not null",
        "created_at bigint not null",
        "unique key uq_planning_revision (project_id, revision)",
        "unique key uq_planning_revision_identity (project_id, id, revision, content_hash)",
        "foreign key (project_id, bible_revision_id, selection_revision, contract_revision, creation_hash, style_hash, bible_revision, bible_hash) references creation_bible_revisions(project_id, id, selection_revision, contract_revision, creation_hash, style_hash, revision, content_hash) on delete restrict",
    ):
        assert contract in revision
    head = _table_statement("project_planning_heads")
    assert (
        "foreign key (project_id, planning_revision_id, revision, content_hash) "
        "references planning_revisions(project_id, id, revision, content_hash) "
        "on delete restrict"
    ) in head
    assert "revision = 0 and planning_revision_id is null and content_hash is null" in head
    assert "revision > 0 and planning_revision_id is not null and content_hash is not null" in head
    request = _table_statement("planning_confirmation_requests")
    for contract in (
        "idempotency_key char(64) not null",
        "request_fingerprint char(64) not null",
        "status varchar(16) not null",
        "planning_revision_id char(36) null",
        "result_revision int null",
        "result_hash char(64) null",
        "created_at bigint not null",
        "completed_at bigint null",
        "unique key uq_planning_confirmation_idempotency (project_id, idempotency_key)",
        "check (status in ('pending','succeeded','failed'))",
        "status = 'pending' and planning_revision_id is null",
        "status = 'succeeded' and planning_revision_id is not null "
        "and result_revision is not null",
    ):
        assert contract in request
    assert "reserved" not in request


def test_outline_tables_pin_exact_planning_canon_projection_and_chapter():
    for table_name in (
        "chapter_outline_drafts",
        "chapter_outline_revisions",
        "chapter_outline_confirmation_requests",
    ):
        statement = _table_statement(table_name)
        for column in (
            "chapter_num int not null",
            "planning_revision_id char(36) not null",
            "planning_revision int not null",
            "planning_hash char(64) not null",
            "canon_revision int not null",
            "projection_revision int not null",
            "projection_hash char(64) not null",
        ):
            assert column in statement
        assert (
            "foreign key (project_id, planning_revision_id, planning_revision, "
            "planning_hash) references planning_revisions(project_id, id, revision, "
            "content_hash) on delete restrict"
        ) in statement
    draft = _table_statement("chapter_outline_drafts")
    assert "unique key uq_outline_draft_active_slot (project_id, chapter_num, active_slot)" in draft
    assert (
        "status = 'active' and active_slot is not null and active_slot = 1"
        in draft
    )
    assert "status in ('confirmed','superseded') and active_slot is null" in draft
    revision = _table_statement("chapter_outline_revisions")
    assert "unique key uq_outline_revision (project_id, chapter_num, revision)" in revision
    assert "unique key uq_outline_revision_identity (project_id, id, revision, content_hash)" in revision
    assert (
        "unique key uq_outline_revision_planning_identity "
        "(project_id, chapter_num, id, revision, content_hash, "
        "planning_revision_id, planning_revision, planning_hash)"
    ) in revision
    head = _table_statement("project_chapter_outline_heads")
    assert "primary key (project_id, chapter_num)" in head
    assert "revision = 0 and outline_revision_id is null and content_hash is null" in head
    assert "revision > 0 and outline_revision_id is not null and content_hash is not null" in head
    request = _table_statement("chapter_outline_confirmation_requests")
    assert "check (status in ('pending','succeeded','failed'))" in request
    assert "status = 'pending' and outline_revision_id is null" in request
    assert (
        "status = 'succeeded' and outline_revision_id is not null "
        "and result_revision is not null"
    ) in request
    assert "reserved" not in request


def test_chapter_session_and_phase_five_records_pin_planning_and_outline():
    session = _table_statement("chapter_sessions")
    for column in (
        "planning_revision_id char(36) not null",
        "planning_revision int not null",
        "planning_hash char(64) not null",
        "story_block_id char(36) not null",
        "story_block_revision int not null",
        "story_block_hash char(64) not null",
        "chapter_outline_revision_id char(36) not null",
        "chapter_outline_revision int not null",
        "chapter_outline_hash char(64) not null",
        "expected_canon_revision int not null",
    ):
        assert column in session
    for forbidden in (
        "volume_plan_id",
        "planning_manifest_hash",
        "planning_snapshot_json",
        "expected_story_block_revision",
        "selection_revision",
        "contract_revision",
        "bible_revision",
    ):
        assert forbidden not in session
    assert (
        "foreign key (project_id, planning_revision_id, planning_revision, "
        "planning_hash) references planning_revisions(project_id, id, revision, "
        "content_hash) on delete restrict"
    ) in session
    assert (
        "foreign key (project_id, chapter_num, chapter_outline_revision_id, "
        "chapter_outline_revision, chapter_outline_hash, planning_revision_id, "
        "planning_revision, planning_hash) references "
        "chapter_outline_revisions(project_id, chapter_num, id, revision, "
        "content_hash, planning_revision_id, planning_revision, planning_hash) "
        "on delete restrict"
    ) in session

    change_set = _table_statement("finalization_change_sets")
    assert "expected_planning_hash char(64) not null" in change_set
    assert "expected_outline_hash char(64) not null" in change_set
    assert "expected_story_block_revision" not in change_set

    final_chapter = _table_statement("final_chapters")
    for column in (
        "planning_revision_id char(36) not null",
        "planning_revision int not null",
        "planning_hash char(64) not null",
        "chapter_outline_revision_id char(36) not null",
        "chapter_outline_revision int not null",
        "chapter_outline_hash char(64) not null",
    ):
        assert column in final_chapter
    assert (
        "foreign key (project_id, chapter_num, chapter_outline_revision_id, "
        "chapter_outline_revision, chapter_outline_hash, planning_revision_id, "
        "planning_revision, planning_hash) references "
        "chapter_outline_revisions(project_id, chapter_num, id, revision, "
        "content_hash, planning_revision_id, planning_revision, planning_hash) "
        "on delete restrict"
    ) in final_chapter
    assert "story_block_revision" not in final_chapter
    assert "planning_snapshot_json" not in final_chapter


def test_phase_five_finalization_schema_is_lean_closed_and_immutable():
    names = created_table_names()
    assert names.index("draft_candidates") < names.index("candidate_quality_reports")
    assert names.index("candidate_quality_reports") < names.index("finalization_change_sets")
    assert names.index("finalization_change_sets") < names.index(
        "finalization_change_set_revisions"
    )
    assert names.index("finalization_change_set_revisions") < names.index(
        "finalization_records"
    )
    assert names.index("finalization_records") < names.index("final_chapters")

    report = _table_statement("candidate_quality_reports")
    for contract in (
        "chapter_session_id char(36) not null",
        "draft_candidate_id char(36) not null",
        "candidate_hash char(64) not null",
        "expected_canon_revision int not null",
        "expected_planning_hash char(64) not null",
        "expected_outline_hash char(64) not null",
        "policy_version varchar(32) not null",
        "context_manifest_hash char(64) not null",
        "deterministic_blocks_json json not null",
        "findings_json json not null",
        "content_hash char(64) not null",
        "unique key uq_quality_report_owner_id (project_id, chapter_session_id, draft_candidate_id, id)",
        "check (status in ('completed','quality_not_completed'))",
    ):
        assert contract in report
    assert "api_key" not in report
    assert "raw_response" not in report
    assert "content longtext" not in report

    change_set = _table_statement("finalization_change_sets")
    for contract in (
        "chapter_session_id char(36) not null",
        "quality_report_id char(36) null",
        "idempotency_key char(64) not null",
        "request_fingerprint char(64) not null",
        "active_slot tinyint null",
        "context_manifest_json json not null",
        "context_manifest_hash char(64) not null",
        "current_revision int null",
        "current_revision_hash char(64) null",
        "confirmed_revision int null",
        "confirmed_revision_hash char(64) null",
        "unique key uq_finalization_active_slot (chapter_session_id, active_slot)",
        "check (active_slot is null or active_slot = 1)",
        "confirmed_revision = current_revision",
        "status = 'preparing' and quality_report_id is null",
        "status = 'awaiting_author' and quality_report_id is not null",
        "status in ('committing','committed') and quality_report_id is not null",
        "check (status in ('preparing','awaiting_author','committing','committed','invalidated','cancelled','failed'))",
    ):
        assert contract in change_set
    assert "payload_json" not in change_set

    revision = _table_statement("finalization_change_set_revisions")
    for contract in (
        "change_set_id char(36) not null",
        "revision int not null",
        "payload_json json not null",
        "content_hash char(64) not null",
        "unique key uq_changeset_revision (change_set_id, revision)",
        "check (source in ('extraction','author_correction'))",
        "check (revision > 0)",
    ):
        assert contract in revision

    record = _table_statement("finalization_records")
    for contract in (
        "change_set_revision int not null",
        "request_fingerprint char(64) not null",
        "foreign key (project_id, change_set_id, change_set_revision, change_set_hash)",
    ):
        assert contract in record
    assert "unique key uq_finalization_idempotency (project_id, idempotency_key)" in record


def test_phase_4b_draft_operation_recovery_schema_is_exact_and_secret_free():
    names = created_table_names()
    assert names.index("working_drafts") < names.index("draft_operation_attempts")
    assert names.index("draft_operation_attempts") < names.index("draft_candidates")
    assert names.index("draft_candidates") < names.index("working_draft_revisions")
    assert names.index("working_draft_revisions") < names.index("draft_operation_events")

    sessions = _table_statement("chapter_sessions")
    for contract in (
        "draft_operation_fencing_token bigint not null default 0",
        "active_draft_operation_id char(36) null",
        "check (draft_operation_fencing_token >= 0)",
    ):
        assert contract in sessions

    revisions = _table_statement("working_draft_revisions")
    for contract in (
        "working_draft_id char(36) not null",
        "working_draft_revision int not null",
        "snapshot_role varchar(24) not null",
        "replacement_reason varchar(40) not null",
        "source_operation_id char(36) null",
        "source_candidate_id char(36) null",
        "unique key uq_working_draft_recovery "
        "(chapter_session_id, working_draft_revision, snapshot_role)",
        "foreign key (project_id, chapter_session_id, working_draft_id) "
        "references working_drafts(project_id, chapter_session_id, id) "
        "on delete cascade",
        "foreign key (project_id, chapter_session_id, source_operation_id) "
        "references draft_operation_attempts(project_id, chapter_session_id, id) "
        "on delete cascade",
        "foreign key (project_id, chapter_session_id, source_candidate_id) "
        "references draft_candidates(project_id, chapter_session_id, id) "
        "on delete cascade",
        "check (working_draft_revision > 0)",
        "check (snapshot_role in ('before','after'))",
        "check (replacement_reason in ('generate_new','rewrite_selection',"
        "'polish_selection','expand_selection','compress_selection','undo_local',"
        "'candidate_load'))",
        "check ( (replacement_reason = 'candidate_load' "
        "and source_operation_id is null and source_candidate_id is not null) "
        "or (replacement_reason <> 'candidate_load' "
        "and source_operation_id is not null and source_candidate_id is null) )",
    ):
        assert contract in revisions
    assert "uq_working_draft_revision_identity" not in revisions
    assert "uq_working_draft_revision_recovery" not in revisions
    assert revisions.count("unique key") == 1
    assert "foreign key (project_id) references projects(id)" not in revisions
    assert "foreign key (working_draft_id) references working_drafts(id)" not in revisions

    candidates = _table_statement("draft_candidates")
    assert (
        "unique key uq_candidate_owner_id "
        "(project_id, chapter_session_id, id)"
    ) in candidates
    assert all(
        not statement.lower().startswith("alter table")
        for statement in read_statements()
    )

    operations = _table_statement("draft_operation_attempts")
    for contract in (
        "operation_type varchar(40) not null",
        "idempotency_key varchar(64) not null",
        "request_fingerprint char(64) not null",
        "active_slot tinyint null",
        "fencing_token bigint not null",
        "lease_expires_at bigint not null",
        "base_working_draft_revision int not null",
        "base_working_draft_hash char(64) not null",
        "input_manifest_json json not null",
        "input_manifest_hash char(64) not null",
        "provider_id char(36) not null",
        "model_name_snapshot varchar(200) not null",
        "result_working_draft_revision int null",
        "result_content_hash char(64) null",
        "last_event_sequence int not null",
        "failure_code varchar(64) null",
        "completed_at bigint null",
        "unique key uq_draft_operation_idempotency "
        "(chapter_session_id, idempotency_key)",
        "unique key uq_draft_operation_active_slot "
        "(chapter_session_id, active_slot)",
        "unique key uq_draft_operation_fencing "
        "(chapter_session_id, fencing_token)",
        "unique key uq_draft_operation_project_id (project_id, id)",
        "unique key uq_draft_operation_owner "
        "(project_id, chapter_session_id, id)",
        "foreign key (project_id, chapter_session_id) references "
        "chapter_sessions(project_id, id) on delete cascade",
        "foreign key (provider_id) references provider_profiles(id) on delete restrict",
        "check (active_slot is null or active_slot = 1)",
        "check (fencing_token > 0)",
        "check (base_working_draft_revision > 0)",
        "check (last_event_sequence >= 0)",
        "check (operation_type in ('generate_new','rewrite_selection',"
        "'polish_selection','expand_selection','compress_selection'))",
        "status = 'completed' and active_slot is null "
        "and result_working_draft_revision is not null "
        "and result_content_hash is not null and failure_code is null "
        "and completed_at is not null",
        "status = 'failed' and active_slot is null "
        "and result_working_draft_revision is null "
        "and result_content_hash is null and failure_code is not null "
        "and completed_at is not null",
        "status = 'expired' and active_slot is null "
        "and result_working_draft_revision is null "
        "and result_content_hash is null and failure_code is null "
        "and completed_at is not null",
    ):
        assert contract in operations
    for forbidden in (
        "operation_id char(36)",
        "uq_draft_operation_identity",
        "result_working_draft_hash",
        "last_sequence_num",
    ):
        assert forbidden not in operations
    for forbidden in (
        "provider_body",
        "provider_key",
        "base_url",
        "prompt",
        "raw_response",
    ):
        assert forbidden not in operations
    for forbidden in (
        "selection_start",
        "selection_end",
        "selected_text_hash",
        "undo_operation_id",
    ):
        assert forbidden not in operations

    events = _table_statement("draft_operation_events")
    for contract in (
        "draft_operation_id char(36) not null",
        "sequence_num int not null",
        "event_type varchar(16) not null",
        "closed_payload_json json null",
        "unique key uq_draft_operation_event_sequence "
        "(draft_operation_id, sequence_num)",
        "foreign key (project_id, draft_operation_id) "
        "references draft_operation_attempts(project_id, id) "
        "on delete cascade",
    ):
        assert contract in events
    assert "foreign key (project_id) references projects(id)" not in events
    assert "foreign key (draft_operation_id) references draft_operation_attempts(id)" not in events

    drafts = _table_statement("working_drafts")
    assert (
        "unique key uq_working_draft_owner "
        "(project_id, chapter_session_id, id)"
    ) in drafts


def test_phase_4b2_streaming_schema_is_exact():
    operations = _table_statement("draft_operation_attempts")
    for contract in (
        "partial_output_text longtext not null",
        "partial_output_hash char(64) not null",
        "partial_output_scalars int not null",
        "heartbeat_at bigint not null",
        "cancelled_at bigint null",
        "check (partial_output_scalars between 0 and 100000)",
        "check (heartbeat_at >= created_at)",
        "check ( (status = 'cancelled' and cancelled_at is not null) or "
        "(status <> 'cancelled' and cancelled_at is null) )",
        "check (status in ('starting','running','completed','failed','cancelled','expired'))",
        "status in ('starting','running') and active_slot is not null "
        "and active_slot = 1 and result_working_draft_revision is null "
        "and result_content_hash is null and failure_code is null "
        "and completed_at is null and cancelled_at is null",
        "status = 'cancelled' and active_slot is null and failure_code is null "
        "and completed_at is not null and cancelled_at is not null",
    ):
        assert contract in operations

    events = _table_statement("draft_operation_events")
    for contract in (
        "check (sequence_num between 1 and 2048)",
        "check (event_type in ('started','delta','heartbeat','completed','failed','cancelled'))",
        "event_type in ('started','heartbeat') and closed_payload_json is null",
        "event_type in ('delta','completed','failed','cancelled') "
        "and closed_payload_json is not null",
    ):
        assert contract in events


def test_phase_4b2_governing_design_commits_only_safe_nonempty_cancelled_partial():
    design_path = (
        Path(schema_manifest.__file__).resolve().parents[1]
        / "docs/superpowers/specs/2026-08-01-phase-4-writer-loop-design.md"
    )
    design = design_path.read_text(encoding="utf-8")
    assert (
        "Cancellation commits the latest safe persisted non-empty partial to "
        "the WorkingDraft. Empty partial, failure, and expiry preserve the "
        "prior WorkingDraft."
    ) in design


def test_candidate_identity_is_content_and_immutable_basis_hash():
    candidate = _table_statement("draft_candidates")

    assert "basis_hash char(64) not null" in candidate
    assert (
        "unique key uq_candidate_identity "
        "(chapter_session_id, content_hash, basis_hash)"
    ) in candidate
    assert "uq_candidate_hash" not in candidate


def test_phase4a_draft_integrity_tables_are_in_exact_manifest():
    names = created_table_names()
    assert names.index("draft_candidates") < names.index("candidate_freeze_requests")
    assert names.index("candidate_freeze_requests") < names.index(
        "finalization_change_sets"
    )

    freeze_requests = _table_statement("candidate_freeze_requests")
    for contract in (
        "unique key uq_candidate_freeze_idempotency "
        "(chapter_session_id, idempotency_key)",
        "foreign key (project_id) references projects(id) on delete cascade",
        "foreign key (project_id, chapter_session_id) references "
        "chapter_sessions(project_id, id) on delete cascade",
        "foreign key (project_id, draft_candidate_id) references "
        "draft_candidates(project_id, id) on delete cascade",
    ):
        assert contract in freeze_requests


def test_corpus_revision_identity_allows_metadata_only_revisions_on_one_blob():
    revisions = _table_statement("corpus_source_revisions")
    assert "unique key uq_corpus_source_import" not in revisions
    assert (
        "unique key uq_corpus_source_revision (source_id, revision)"
    ) in revisions


def test_seed_inspiration_can_precede_selection_and_pins_market_inputs():
    attempt = _table_statement("seed_inspiration_attempts")
    assert "selection_revision int null" in attempt
    assert "market_source_id char(36) not null" in attempt
    assert "market_snapshot_id char(36) not null" in attempt
    assert "market_snapshot_hash char(64) not null" in attempt
    assert "market_analysis_id char(36) not null" in attempt
    assert "market_analysis_hash char(64) not null" in attempt
    assert (
        "foreign key (market_source_id, market_snapshot_id, "
        "market_snapshot_hash) references market_snapshots(source_id, id, "
        "content_hash) on delete restrict"
    ) in attempt
    assert (
        "foreign key (project_id, market_analysis_id, market_analysis_hash) "
        "references market_analyses(project_id, id, result_hash) "
        "on delete restrict"
    ) in attempt


def test_generation_request_ledgers_bind_owner_attempt_and_success_hash():
    pairs = (
        ("seed_inspiration_attempts", "seed_inspiration_requests"),
        ("asset_recommendation_attempts", "asset_recommendation_requests"),
        ("style_trial_attempts", "style_trial_requests"),
    )
    for attempt_name, request_name in pairs:
        attempt = _table_statement(attempt_name)
        request = _table_statement(request_name)
        assert (
            f"unique key uq_{attempt_name.removesuffix('_attempts')}_attempt_owner "
            "(project_id, id)"
        ) in attempt
        assert (
            f"foreign key (project_id, attempt_id) references {attempt_name}"
            "(project_id, id) on delete restrict"
        ) in request
        assert (
            f"foreign key (project_id, attempt_id, result_hash) references "
            f"{attempt_name}(project_id, id, result_hash) on delete restrict"
        ) in request
        assert (
            "status = 'succeeded' and attempt_id is not null "
            "and result_hash is not null"
        ) in request


def test_corpus_deletion_commands_are_persistent_and_not_source_fk_cascades():
    statement = _table_statement("corpus_source_deletions")

    assert "source_id char(36) primary key" in statement
    assert "expected_revision int not null" in statement
    assert "tombstones_json json not null" in statement
    assert "restore_pending" in statement
    assert "cleanup_pending" in statement
    assert "succeeded" in statement
    assert "foreign key" not in statement


def test_story_engine_drafts_and_contract_heads_are_revision_bound():
    batches = _table_statement("story_engine_batches")
    assert "selection_revision int not null" in batches
    assert "foreign key (project_id, selection_revision, seed_id, seed_revision_id, seed_hash) references project_seed_selection_revisions(project_id, selection_revision, seed_id, seed_revision_id, seed_hash) on delete restrict" in batches
    assert "provider_id is null and model_name_snapshot is null" in batches
    assert "provider_id is not null and model_name_snapshot is not null" in batches
    assert (
        "provider_id is null and model_name_snapshot is null "
        "and (status = 'reserved' or (status = 'failed' and attempt_id is null "
        "and public_error_code in ('not_started','provider_configuration')))"
    ) in batches
    assert "public_error_code = 'provider_configuration'" in batches
    assert "unique key uq_engine_batch_idempotency (project_id, idempotency_key)" in batches
    assert "unique key uq_engine_batch_project_id (project_id, id)" in batches
    assert "check (source_type in ('provider','manual'))" in batches
    assert "check (status in ('reserved','running','succeeded','failed','outcome_unknown'))" in batches
    assert "check (raw_response_text is null)" in batches
    assert (
        "status = 'succeeded' and attempt_id is not null "
        "and attempt_started_at is not null and lease_expires_at is not null "
        "and raw_response_text is null and raw_response_hash is not null"
    ) in batches
    assert (
        "public_error_code = 'invalid_response' and raw_response_hash is not null"
    ) in batches
    assert (
        "public_error_code = 'selection_superseded' "
        "and raw_response_hash is not null"
    ) in batches
    assert (
        "public_error_code in ('provider_failed','provider_timeout') "
        "and raw_response_hash is null"
    ) in batches
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
        "and ((public_error_code = 'invalid_response' and raw_response_hash is not null) "
        "or (public_error_code = 'selection_superseded' "
        "and raw_response_hash is not null) "
        "or (public_error_code in ('provider_failed','provider_timeout') "
        "and raw_response_hash is null)) "
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
    assert "selection_revision int not null" in options
    assert "project_id char(36) not null" in options
    assert "unique key uq_engine_option_order (batch_id, option_order)" in options
    assert "unique key uq_engine_option_project_id (project_id, id)" in options
    assert "foreign key (project_id, batch_id, selection_revision) references story_engine_batches(project_id, id, selection_revision) on delete restrict" in options
    assert "foreign key (batch_id)" not in options
    assert "check (option_order between 1 and 3)" in options
    drafts = _table_statement("project_contract_drafts")
    assert "selection_revision int not null" in drafts
    assert "project_id char(36) primary key" in drafts
    assert "unique key uq_contract_draft_id (id)" in drafts
    assert "foreign key (project_id, selection_revision, seed_revision_id, seed_hash) references project_seed_selection_revisions(project_id, selection_revision, seed_revision_id, seed_hash) on delete restrict" in drafts
    assert "foreign key (project_id, seed_revision_id) references creative_seed_revisions(project_id, id) on delete restrict" in drafts
    assert "foreign key (project_id, engine_option_id, selection_revision) references story_engine_options(project_id, id, selection_revision) on delete restrict" in drafts
    assert "foreign key (seed_revision_id)" not in drafts
    assert "foreign key (engine_option_id)" not in drafts
    heads = _table_statement("project_contract_heads")
    assert "check ((revision = 0" in heads
    assert (
        "foreign key (project_id, creation_contract_id, revision, creation_hash) "
        "references creation_contracts(project_id, id, revision, content_hash) "
        "on delete restrict"
    ) in heads
    requests = _table_statement("contract_confirmation_requests")
    assert "selection_revision int not null" in requests
    assert "unique key uq_contract_confirmation_idempotency (project_id, idempotency_key)" in requests
    assert (
        "foreign key (project_id, selection_revision, creation_contract_id, "
        "result_revision) references creation_contracts(project_id, "
        "selection_revision, id, revision) on delete restrict"
    ) in requests
    assert "foreign key (project_id, style_contract_id, result_revision) references style_contracts(project_id, id, revision) on delete restrict" in requests


def test_contracts_and_specialized_refs_use_real_revision_foreign_keys():
    creation = _table_statement("creation_contracts")
    for contract in (
        "unique key uq_creation_contract_revision (project_id, revision)",
        "unique key uq_creation_contract_id (project_id, id)",
        "foreign key (project_id, selection_revision, seed_id, seed_revision_id, seed_hash) references project_seed_selection_revisions(project_id, selection_revision, seed_id, seed_revision_id, seed_hash) on delete restrict",
        "foreign key (project_id, binding_revision_id, binding_hash) references project_model_binding_revisions(project_id, id, content_hash) on delete restrict",
        "check (total_word_min > 0 and total_word_max >= total_word_min)",
    ):
        assert contract in creation
    assert "quality_charter_version varchar(120) not null" in creation
    assert "binding_revision_id char(36) null" in creation
    assert "binding_hash char(64) null" in creation
    assert "check ((binding_revision_id is null and binding_hash is null) or (binding_revision_id is not null and binding_hash is not null))" in creation
    assert "chapter_capacity_policy text not null" in creation
    assert "reference_manifest_json json not null" in creation
    assert "reference_manifest_hash char(64) not null" in creation
    assert "chapter_char_min" not in creation
    assert "chapter_char_target" not in creation
    assert "chapter_char_max" not in creation
    assert "selection_revision int not null" in creation
    style = _table_statement("style_contracts")
    assert "foreign key (project_id, creation_contract_id, revision) references creation_contracts(project_id, id, revision) on delete restrict" in style
    engine_refs = _table_statement("creation_contract_engine_refs")
    assert "project_id char(36) not null" in engine_refs
    assert "foreign key (project_id, creation_contract_id) references creation_contracts(project_id, id) on delete cascade" in engine_refs
    assert "foreign key (project_id, engine_option_id) references story_engine_options(project_id, id) on delete restrict" in engine_refs
    assert "foreign key (creation_contract_id)" not in engine_refs
    assert "foreign key (engine_option_id)" not in engine_refs
    assert "foreign key (style_template_id, asset_revision, asset_hash) references style_templates(id, revision, content_hash) on delete restrict" in _table_statement("style_contract_template_refs")
    assert "foreign key (experience_card_id, asset_revision, asset_hash) references experience_cards(id, revision, content_hash) on delete restrict" in _table_statement("creation_contract_experience_refs")
    assert "foreign key (corpus_source_id, source_revision, source_hash) references corpus_source_revisions(source_id, revision, content_hash) on delete restrict" in _table_statement("creation_contract_corpus_refs")
    fragment_refs = _table_statement("creation_contract_corpus_fragment_refs")
    for column in (
        "source_revision int not null",
        "source_hash char(64) not null",
        "corpus_chapter_id char(36) not null",
        "corpus_fragment_id char(36) not null",
        "fragment_hash char(64) not null",
        "chapter_char_start bigint not null",
        "chapter_char_end bigint not null",
        "reference_use varchar(32) not null",
        "sort_order int not null",
    ):
        assert column in fragment_refs


def test_bible_history_is_bound_to_exact_creation_and_style_contracts():
    for table_name in (
        "project_bible_drafts",
        "bible_generation_attempts",
        "creation_bible_revisions",
        "bible_confirmation_requests",
    ):
        statement = _table_statement(table_name)
        assert "selection_revision int not null" in statement
        assert "contract_revision int not null" in statement
        assert "creation_contract_id char(36) not null" in statement
        assert "creation_hash char(64) not null" in statement
        assert "style_contract_id char(36) not null" in statement
        assert "style_hash char(64) not null" in statement
        assert "contract_hash" not in statement
        assert (
            "foreign key (project_id, creation_contract_id, contract_revision, "
            "creation_hash) references creation_contracts(project_id, id, "
            "revision, content_hash) on delete restrict"
        ) in statement
        assert (
            "foreign key (project_id, selection_revision, contract_revision, "
            "creation_hash) references creation_contracts(project_id, "
            "selection_revision, revision, content_hash) on delete restrict"
        ) in statement
        assert (
            "foreign key (project_id, style_contract_id, contract_revision, "
            "style_hash) references style_contracts(project_id, id, revision, "
            "content_hash) on delete restrict"
        ) in statement
    revisions = _table_statement("creation_bible_revisions")
    assert "unique key uq_bible_revision_identity (project_id, id, revision, content_hash)" in revisions
    heads = _table_statement("project_bible_heads")
    assert "check ((revision = 0" in heads
    assert "foreign key (project_id, bible_revision_id, revision, content_hash) references creation_bible_revisions(project_id, id, revision, content_hash) on delete restrict" in heads


def test_bible_drafts_retain_history_with_one_nullable_active_slot():
    drafts = _table_statement("project_bible_drafts")

    assert "id char(36) primary key" in drafts
    assert "project_id char(36) not null" in drafts
    assert "project_id char(36) primary key" not in drafts
    assert "active_slot tinyint null" in drafts
    assert "unique key uq_bible_draft_project_id (project_id, id)" in drafts
    assert "unique key uq_bible_draft_active_slot (project_id, active_slot)" in drafts
    assert "check (active_slot is null or active_slot = 1)" in drafts


def test_bible_confirmation_requests_reference_draft_identity_and_snapshot():
    requests = _table_statement("bible_confirmation_requests")

    assert "draft_version int not null" in requests
    assert "draft_hash char(64) not null" in requests
    assert (
        "foreign key (project_id, draft_id, selection_revision, contract_revision, "
        "creation_hash, style_hash) references project_bible_drafts(project_id, id, "
        "selection_revision, contract_revision, creation_hash, style_hash) "
        "on delete restrict"
    ) in requests
    assert (
        "foreign key (project_id, draft_id) references "
        "project_bible_drafts(project_id, id) on delete restrict"
    ) not in requests
    assert "draft_id char(36) primary key" not in requests
    assert "unique key uq_bible_confirmation_project" not in requests


def test_bible_generation_attempts_have_owned_leases_and_exact_terminal_states():
    attempts = _table_statement("bible_generation_attempts")

    assert "owner_token char(36) null" in attempts
    assert "lease_expires_at bigint null" in attempts
    assert "attempt_version int not null" in attempts
    assert "check (attempt_version > 0)" in attempts
    assert (
        "status in ('reserved','running') and owner_token is not null "
        "and lease_expires_at is not null and result_json is null "
        "and result_hash is null and public_error_code is null "
        "and completed_at is null"
    ) in attempts
    assert (
        "status = 'succeeded' and owner_token is null and lease_expires_at is null "
        "and result_json is not null and result_hash is not null "
        "and public_error_code is null and completed_at is not null"
    ) in attempts
    assert (
        "status in ('failed','outcome_unknown') and owner_token is null "
        "and lease_expires_at is null and result_json is null "
        "and result_hash is null and public_error_code is not null "
        "and completed_at is not null"
    ) in attempts


def test_planning_revisions_and_sessions_freeze_aggregate_generation():
    revision = _table_statement("planning_revisions")
    for contract in (
        "selection_revision int not null",
        "seed_id char(36) not null",
        "seed_revision_id char(36) not null",
        "seed_hash char(64) not null",
        "contract_revision int not null",
        "creation_contract_id char(36) not null",
        "creation_hash char(64) not null",
        "style_contract_id char(36) not null",
        "style_hash char(64) not null",
        "bible_revision int not null",
        "bible_revision_id char(36) not null",
        "bible_hash char(64) not null",
    ):
        assert contract in revision

    sessions = _table_statement("chapter_sessions")
    for contract in (
        "planning_revision_id char(36) not null",
        "planning_revision int not null",
        "planning_hash char(64) not null",
        "story_block_id char(36) not null",
        "story_block_revision int not null",
        "story_block_hash char(64) not null",
        "chapter_outline_revision_id char(36) not null",
        "chapter_outline_revision int not null",
        "chapter_outline_hash char(64) not null",
    ):
        assert contract in sessions


def test_planning_draft_canon_and_projection_tables_are_present():
    unchanged = {
        "planning_drafts", "planning_generation_attempts", "planning_revisions",
        "project_planning_heads", "planning_confirmation_requests",
        "chapter_outline_drafts", "chapter_outline_generation_attempts",
        "chapter_outline_revisions", "project_chapter_outline_heads",
        "chapter_outline_confirmation_requests",
        "chapter_sessions", "working_drafts", "draft_candidates", "final_chapters",
        "finalization_change_sets", "finalization_records", "canon_entities",
        "entity_aliases", "canon_revisions", "canon_events",
        "current_state_projections", "memory_views", "arc_projections",
        "plot_thread_projections", "projection_heads", "reference_uses",
    }
    assert unchanged <= set(created_table_names())


def test_project_private_parent_child_edges_are_project_scoped():
    expected_contracts = {
        "project_selected_seeds": (
            "foreign key (project_id, selection_revision, seed_id, "
            "seed_revision_id, seed_hash) references "
            "project_seed_selection_revisions(project_id, selection_revision, "
            "seed_id, seed_revision_id, seed_hash) on delete restrict",
        ),
        "story_engine_batches": (
            "foreign key (project_id, seed_id, seed_revision_id, seed_hash) "
            "references creative_seed_revisions(project_id, seed_id, id, "
            "content_hash) on delete restrict",
        ),
        "creation_contracts": (
            "foreign key (project_id, seed_id, seed_revision_id, seed_hash) "
            "references creative_seed_revisions(project_id, seed_id, id, "
            "content_hash) on delete restrict",
        ),
        "planning_generation_attempts": (
            "foreign key (project_id, draft_id) references "
            "planning_drafts(project_id, id) on delete restrict",
        ),
        "project_planning_heads": (
            "foreign key (project_id, planning_revision_id, revision, content_hash) "
            "references planning_revisions(project_id, id, revision, content_hash) "
            "on delete restrict",
        ),
        "planning_confirmation_requests": (
            "foreign key (project_id, planning_draft_id, draft_revision, "
            "draft_hash) references planning_drafts(project_id, id, "
            "draft_revision, content_hash) on delete restrict",
        ),
        "chapter_outline_drafts": (
            "foreign key (project_id, planning_revision_id, planning_revision, "
            "planning_hash) references planning_revisions(project_id, id, "
            "revision, content_hash) on delete restrict",
        ),
        "chapter_outline_generation_attempts": (
            "foreign key (project_id, outline_draft_id) references "
            "chapter_outline_drafts(project_id, id) on delete restrict",
        ),
        "project_chapter_outline_heads": (
            "foreign key (project_id, chapter_num, outline_revision_id, revision, "
            "content_hash) references chapter_outline_revisions(project_id, "
            "chapter_num, id, revision, content_hash) on delete restrict",
        ),
        "chapter_outline_confirmation_requests": (
            "foreign key (project_id, chapter_outline_draft_id, draft_revision, "
            "draft_hash) references chapter_outline_drafts(project_id, id, "
            "draft_revision, content_hash) on delete restrict",
            "foreign key (project_id, chapter_num, outline_revision_id, "
            "result_revision, result_hash, planning_revision_id, "
            "planning_revision, planning_hash) references "
            "chapter_outline_revisions(project_id, chapter_num, id, revision, "
            "content_hash, planning_revision_id, planning_revision, "
            "planning_hash) on delete restrict",
        ),
        "chapter_sessions": (
            "foreign key (project_id, planning_revision_id, planning_revision, "
            "planning_hash) references planning_revisions(project_id, id, "
            "revision, content_hash) on delete restrict",
            "foreign key (project_id, chapter_num, chapter_outline_revision_id, "
            "chapter_outline_revision, chapter_outline_hash, planning_revision_id, "
            "planning_revision, planning_hash) references "
            "chapter_outline_revisions(project_id, chapter_num, id, revision, "
            "content_hash, planning_revision_id, planning_revision, planning_hash) "
            "on delete restrict",
        ),
        "working_drafts": (
            "foreign key (project_id, chapter_session_id) references "
            "chapter_sessions(project_id, id) on delete cascade",
        ),
        "draft_candidates": (
            "foreign key (project_id, chapter_session_id) references "
            "chapter_sessions(project_id, id) on delete cascade",
        ),
        "candidate_quality_reports": (
            "foreign key (project_id, chapter_session_id, draft_candidate_id) "
            "references draft_candidates(project_id, chapter_session_id, id) "
            "on delete cascade",
        ),
        "finalization_change_sets": (
            "foreign key (project_id, chapter_session_id, draft_candidate_id) "
            "references draft_candidates(project_id, chapter_session_id, id) "
            "on delete cascade",
            "foreign key (project_id, chapter_session_id, draft_candidate_id, "
            "quality_report_id) references candidate_quality_reports(project_id, "
            "chapter_session_id, draft_candidate_id, id) on delete restrict",
        ),
        "finalization_change_set_revisions": (
            "foreign key (project_id, change_set_id) references "
            "finalization_change_sets(project_id, id) on delete cascade",
        ),
        "finalization_records": (
            "foreign key (project_id, chapter_session_id) references "
            "chapter_sessions(project_id, id) on delete cascade",
            "foreign key (project_id, chapter_session_id, draft_candidate_id) "
            "references draft_candidates(project_id, chapter_session_id, id) "
            "on delete cascade",
            "foreign key (project_id, change_set_id, change_set_revision, "
            "change_set_hash) references finalization_change_set_revisions("
            "project_id, change_set_id, revision, content_hash) on delete restrict",
        ),
        "final_chapters": (
            "foreign key (project_id, chapter_session_id) references "
            "chapter_sessions(project_id, id) on delete cascade",
            "foreign key (project_id, draft_candidate_id) references "
            "draft_candidates(project_id, id) on delete cascade",
            "foreign key (project_id, finalization_record_id) references "
            "finalization_records(project_id, id) on delete cascade",
        ),
        "entity_aliases": (
            "foreign key (project_id, entity_id) references "
            "canon_entities(project_id, id) on delete cascade",
        ),
        "canon_events": (
            "foreign key (project_id, revision_id) references "
            "canon_revisions(project_id, id) on delete cascade",
            "foreign key (project_id, entity_id) references "
            "canon_entities(project_id, id) on delete cascade",
        ),
        "current_state_projections": (
            "foreign key (project_id, entity_id) references "
            "canon_entities(project_id, id) on delete cascade",
        ),
        "memory_views": (
            "foreign key (project_id, entity_id) references "
            "canon_entities(project_id, id) on delete cascade",
        ),
        "arc_projections": (
            "foreign key (project_id, entity_id) references "
            "canon_entities(project_id, id) on delete cascade",
        ),
        "plot_thread_projections": (
            "foreign key (project_id, entity_id) references "
            "canon_entities(project_id, id) on delete cascade",
        ),
        "reference_uses": (
            "foreign key (project_id, chapter_session_id) references "
            "chapter_sessions(project_id, id) on delete cascade",
            "foreign key (project_id, draft_candidate_id) references "
            "draft_candidates(project_id, id) on delete cascade",
        ),
    }
    for table_name, contracts in expected_contracts.items():
        statement = _table_statement(table_name)
        for contract in contracts:
            assert contract in statement

    for parent in (
        "creative_seed_revisions",
        "planning_drafts",
        "planning_revisions",
        "chapter_outline_drafts",
        "chapter_outline_revisions",
        "chapter_sessions",
        "draft_candidates",
        "finalization_change_sets",
        "finalization_records",
        "canon_entities",
        "canon_revisions",
    ):
        assert "(project_id, id)" in _table_statement(parent)
