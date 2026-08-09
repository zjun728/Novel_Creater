from __future__ import annotations

from pathlib import Path
import re

import pytest

from backend.domain.project_packages import PackageRecord, RECORD_FIELD_ALLOWLISTS
from backend.domain.project_packages import ProjectPackageInvalid
from backend.repositories.project_packages import (
    INTERNAL_NON_PACKAGE_TABLES,
    PROJECT_OWNED_TABLES,
    PROJECT_TABLE_RECORD_TYPES,
    PROJECT_TABLE_COLUMN_POLICIES,
    SHARED_EXCLUDED_TABLES,
    NORMALIZED_SHARED_RECORD_TYPES,
    FROZEN_CORPUS_BLOB_TABLES,
    LOGICAL_REFERENCE_TARGETS,
    NESTED_LOGICAL_REFERENCE_TARGETS,
    POLYMORPHIC_LOGICAL_REFERENCE_TARGETS,
    FrozenCorpusBlob,
    ProjectPackageSnapshot,
)
from backend.security.project_package_paths import reject_sensitive_keys


def _schema_tables() -> set[str]:
    schema_dir = Path(__file__).parents[2] / "schema"
    return {
        match.group(1)
        for path in schema_dir.glob("*.sql")
        for match in re.finditer(r"(?im)^CREATE TABLE\s+([a-z_]+)", path.read_text(encoding="utf-8"))
    }


def _schema_columns() -> dict[str, set[str]]:
    schema_dir = Path(__file__).parents[2] / "schema"
    schema_text = "\n".join(path.read_text(encoding="utf-8") for path in schema_dir.glob("*.sql"))
    columns: dict[str, set[str]] = {}
    for table, body in re.findall(r"CREATE TABLE\s+([a-z_]+)\s*\((.*?)\)\s*ENGINE=", schema_text, re.DOTALL):
        columns[table] = {
            match.group(1)
            for line in body.splitlines()
            if (match := re.match(r"\s{2}([a-z][a-z0-9_]*)\s+", line))
            and match.group(1) not in {"primary", "unique", "foreign", "check", "key", "constraint"}
        }
    return columns


def _schema_foreign_key_targets() -> dict[tuple[str, str], str]:
    schema_dir = Path(__file__).parents[2] / "schema"
    schema_text = "\n".join(path.read_text(encoding="utf-8") for path in schema_dir.glob("*.sql"))
    targets: dict[tuple[str, str], str] = {}
    for table, body in re.findall(r"CREATE TABLE\s+([a-z_]+)\s*\((.*?)\)\s*ENGINE=", schema_text, re.DOTALL):
        for local, target in re.findall(r"FOREIGN KEY\s*\(([^)]+)\)\s*REFERENCES\s+([a-z_]+)\s*\(", body):
            for column in re.findall(r"[a-z_]+", local):
                targets[(table, column)] = target
    return targets


def test_explicit_ownership_inventory_closes_over_every_create_only_schema_table() -> None:
    schema_tables = _schema_tables()

    assert len(schema_tables) == 89
    assert PROJECT_OWNED_TABLES | SHARED_EXCLUDED_TABLES | INTERNAL_NON_PACKAGE_TABLES == schema_tables
    assert PROJECT_OWNED_TABLES.isdisjoint(SHARED_EXCLUDED_TABLES)
    assert PROJECT_OWNED_TABLES.isdisjoint(INTERNAL_NON_PACKAGE_TABLES)
    assert SHARED_EXCLUDED_TABLES.isdisjoint(INTERNAL_NON_PACKAGE_TABLES)


def test_key_tables_are_classified_by_authority_not_by_name() -> None:
    assert {"projects", "draft_operation_events", "final_chapters", "canon_events", "reference_uses"} <= PROJECT_OWNED_TABLES
    assert {
        "provider_profiles", "provider_profile_mutation_requests", "application_settings",
        "style_template_heads", "experience_card_heads", "market_sources", "market_refresh_requests",
        "corpus_source_heads", "corpus_import_runs", "corpus_source_deletions",
    } <= SHARED_EXCLUDED_TABLES
    assert {
        "schema_metadata", "current_state_projections", "memory_views", "arc_projections",
        "plot_thread_projections", "projection_heads",
    } == INTERNAL_NON_PACKAGE_TABLES


def test_each_project_owned_table_maps_to_an_explicit_public_or_normalized_record_type() -> None:
    assert set(PROJECT_TABLE_RECORD_TYPES) == PROJECT_OWNED_TABLES
    assert all(record_type in RECORD_FIELD_ALLOWLISTS for record_type in PROJECT_TABLE_RECORD_TYPES.values())


def test_every_project_owned_schema_column_has_an_explicit_export_policy() -> None:
    schema_columns = _schema_columns()

    assert set(PROJECT_TABLE_COLUMN_POLICIES) == PROJECT_OWNED_TABLES
    assert {table: set(policy) for table, policy in PROJECT_TABLE_COLUMN_POLICIES.items()} == {
        table: schema_columns[table] for table in PROJECT_OWNED_TABLES
    }
    assert {
        policy for table_policy in PROJECT_TABLE_COLUMN_POLICIES.values() for policy in table_policy.values()
    } <= {"public_field", "logical_reference", "nested_logical_reference", "polymorphic_logical_reference", "normalized_inert_evidence", "derived", "excluded_sensitive_operational"}
    future_schema_columns = dict(schema_columns)
    future_schema_columns["projects"] = schema_columns["projects"] | {"future_secret"}
    assert {table: set(policy) for table, policy in PROJECT_TABLE_COLUMN_POLICIES.items()} != {
        table: future_schema_columns[table] for table in PROJECT_OWNED_TABLES
    }


def test_column_policy_is_static_and_never_exports_operation_event_payloads() -> None:
    repository_source = (Path(__file__).parents[2] / "repositories" / "project_packages.py").read_text(encoding="utf-8")

    assert "_schema_owned_column_policies" not in repository_source
    assert "read_text(" not in repository_source
    assert PROJECT_TABLE_COLUMN_POLICIES["draft_operation_events"]["closed_payload_json"] == "excluded_sensitive_operational"


def test_shared_market_and_corpus_foreign_keys_are_not_package_logical_references() -> None:
    for table, column in {
        ("seed_inspiration_attempts", "market_source_id"),
        ("seed_inspiration_attempts", "market_snapshot_id"),
        ("creation_contract_corpus_refs", "corpus_source_id"),
        ("creation_contract_corpus_fragment_refs", "corpus_source_id"),
        ("creation_contract_corpus_fragment_refs", "corpus_chapter_id"),
        ("creation_contract_corpus_fragment_refs", "corpus_fragment_id"),
        ("reference_uses", "corpus_source_id"),
        ("reference_uses", "corpus_chapter_id"),
    }:
        assert PROJECT_TABLE_COLUMN_POLICIES[table][column] != "logical_reference"
    assert PROJECT_TABLE_COLUMN_POLICIES["finalization_change_sets"]["extraction_id"] == "excluded_sensitive_operational"


def test_every_logical_reference_has_a_project_or_normalized_fk_target() -> None:
    foreign_keys = _schema_foreign_key_targets()
    permitted = PROJECT_OWNED_TABLES | set(NORMALIZED_SHARED_RECORD_TYPES)
    logical_references = {
        (table, column)
        for table, policy in PROJECT_TABLE_COLUMN_POLICIES.items()
        for column, category in policy.items()
        if category == "logical_reference"
    }

    assert set(LOGICAL_REFERENCE_TARGETS) <= logical_references
    unresolved = {
        pair for pair in logical_references
        if foreign_keys.get(pair, LOGICAL_REFERENCE_TARGETS.get(pair)) not in permitted
    }
    assert not unresolved


def test_nested_and_polymorphic_references_have_explicit_real_semantics() -> None:
    assert PROJECT_TABLE_COLUMN_POLICIES["planning_generation_attempts"]["operation_id"] == "excluded_sensitive_operational"
    assert PROJECT_TABLE_COLUMN_POLICIES["chapter_outline_generation_attempts"]["operation_id"] == "excluded_sensitive_operational"
    assert PROJECT_TABLE_COLUMN_POLICIES["story_engine_batches"]["attempt_id"] == "excluded_sensitive_operational"
    assert NESTED_LOGICAL_REFERENCE_TARGETS == {("chapter_sessions", "story_block_id"): "story-block"}
    assert POLYMORPHIC_LOGICAL_REFERENCE_TARGETS[("canon_revisions", "source_id")] == {
        "bootstrap": None, "finalization": "finalization_records", "manual_test": None,
    }


def test_shared_normalization_never_claims_a_blob_is_a_package_record() -> None:
    assert set(NORMALIZED_SHARED_RECORD_TYPES) <= SHARED_EXCLUDED_TABLES
    assert all(record_type in RECORD_FIELD_ALLOWLISTS for record_type in NORMALIZED_SHARED_RECORD_TYPES.values())
    assert "corpus_blobs" not in NORMALIZED_SHARED_RECORD_TYPES
    assert FROZEN_CORPUS_BLOB_TABLES == frozenset({"corpus_blobs"})


def test_public_record_allowlists_have_no_provider_or_execution_sensitive_fields() -> None:
    forbidden = {
        "id", "projectId", "providerId", "providerUuid", "baseUrl", "apiKey", "hasApiKey", "enabled",
        "ownerToken", "lease", "prompt", "requestJson", "rawOutput", "delta", "absolutePath",
        "localPath", "filesystemPath", "idempotencyKey",
    }
    public_fields = {field for fields in RECORD_FIELD_ALLOWLISTS.values() for field in fields}

    assert not forbidden & public_fields
    for field in public_fields:
        reject_sensitive_keys({field: None})


def test_snapshot_and_frozen_blob_are_immutable_package_boundary_dtos() -> None:
    source_projection = {"hashes": [{"nested": ["x"]}], "count": 0}
    snapshot = ProjectPackageSnapshot(
        source_project_logical_id="project:1",
        lifecycle_revision=0,
        graph_records=(PackageRecord("project", "project:1", data={"label": "project"}),),
        operation_records=(),
        provider_history_records=(),
        frozen_asset_records=(),
        corpus_revision_records=(),
        corpus_blobs=(FrozenCorpusBlob("corpus-blob:1", "a" * 64, 0, "sha256/aa/" + "a" * 64),),
        projection_validation=source_projection,
        referenced_secret_values=(b"private",),
        counts={"project": 1},
    )

    assert snapshot.source_project_logical_id == "project:1"
    assert snapshot.corpus_blobs[0].content_hash == "a" * 64
    source_projection["hashes"][0]["nested"].append("source-only")
    assert snapshot.projection_validation["hashes"][0]["nested"] == ("x",)
    with pytest.raises(TypeError):
        snapshot.projection_validation["hashes"][0]["nested"] += ("y",)


@pytest.mark.parametrize("storage_key", ["C:/corpus/blob", "/corpus/blob", "sha256/aa/not-the-hash", "sha256/aa/%2e%2e/blob"])
def test_frozen_blob_requires_its_exact_managed_storage_key(storage_key: str) -> None:
    with pytest.raises(ProjectPackageInvalid, match="invalid package value"):
        FrozenCorpusBlob("corpus-blob:1", "a" * 64, 0, storage_key)


def test_snapshot_rejects_non_tuple_record_collections_with_a_fixed_error() -> None:
    with pytest.raises(ProjectPackageInvalid, match="invalid package value"):
        ProjectPackageSnapshot(
            source_project_logical_id="project:1", lifecycle_revision=0,
            graph_records=[], operation_records=(), provider_history_records=(), frozen_asset_records=(),
            corpus_revision_records=(), corpus_blobs=(), projection_validation={}, referenced_secret_values=(),
        )
