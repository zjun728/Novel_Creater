from __future__ import annotations

from pathlib import Path

from backend.schema_manifest import FRAGMENTS, created_table_names, read_statements
from backend.schema_version import EXPECTED_SCHEMA_VERSION


SCHEMA_PATH = Path(__file__).parents[2] / "schema" / "80_project_imports.sql"


def _compact(statement: str) -> str:
    return " ".join(statement.lower().split())


def _statement(table_name: str) -> str:
    prefix = f"create table {table_name} "
    return next(
        _compact(statement)
        for statement in read_statements()
        if _compact(statement).startswith(prefix)
    )


def test_import_schema_is_registered_and_advances_one_version():
    assert FRAGMENTS[-1] == "80_project_imports.sql"
    assert EXPECTED_SCHEMA_VERSION == "writer-core-v1.14.0"
    assert created_table_names()[-2:] == (
        "project_package_import_commands",
        "project_import_provenance",
    )


def test_command_table_has_closed_identity_state_json_and_lease_contracts():
    command = _statement("project_package_import_commands")
    for contract in (
        "id char(36) primary key",
        "idempotency_key char(64) not null",
        "request_fingerprint char(64) not null",
        "package_hash char(64) not null",
        "manifest_hash char(64) not null",
        "package_version int not null",
        "target_project_id char(36) not null",
        "normalized_title varchar(300) not null",
        "status varchar(16) not null",
        "phase varchar(16) not null",
        "owner_token char(36) null",
        "lease_expires_at bigint null",
        "staging_manifest_json json null",
        "public_error_code varchar(64) null",
        "unique key uq_project_import_idempotency (idempotency_key)",
        "unique key uq_project_import_target (target_project_id)",
        "check (status in ('reserved','running','succeeded','failed'))",
        "check (phase in ('uploaded','preflighted','staged','publishing','succeeded','failed'))",
        "check (staging_manifest_json is null or json_valid(staging_manifest_json))",
    ):
        assert contract in command
    assert "foreign key" not in command


def test_provenance_has_exact_ownership_order_category_and_json_contracts():
    provenance = _statement("project_import_provenance")
    for contract in (
        "project_id char(36) not null",
        "command_id char(36) not null",
        "record_order int not null",
        "category varchar(32) not null",
        "source_entity_type varchar(120) not null",
        "source_logical_id varchar(200) not null",
        "payload_json json not null",
        "content_hash char(64) not null",
        "primary key (project_id, record_order)",
        "unique key uq_project_import_provenance_command_order (command_id, record_order)",
        "foreign key (project_id) references projects(id) on delete cascade",
        "foreign key (command_id, project_id) references project_package_import_commands(id, target_project_id) on delete restrict",
        "check (record_order > 0)",
        "check (category in ('provider-history','market-history','operation-history','unsupported-history'))",
        "check (json_valid(payload_json))",
    ):
        assert contract in provenance
    for forbidden in ("provider_id", "market_source_id", "operation_id"):
        assert forbidden not in provenance


def test_import_schema_adds_no_generic_or_visibility_persistence():
    source = SCHEMA_PATH.read_text(encoding="utf-8").lower()
    assert "alter table" not in source
    assert "projects.visibility" not in source
    for forbidden in (
        "project_import_jobs", "project_import_tasks", "project_import_preflights",
        "project_import_ledgers", "provider_profiles",
    ):
        assert forbidden not in source
