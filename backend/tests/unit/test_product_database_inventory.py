import asyncio
from dataclasses import FrozenInstanceError, replace
import traceback

import pytest

from backend.domain.product_database_readiness import LEGACY_DATABASE, ProductDatabaseReadinessError
from backend.services.product_database_inventory import (
    TableStorage,
    assert_inventory_equal,
    assert_storage_policy,
    inventory_database,
    read_table_storage,
)


RESTORE_DATABASE = "novel_creator_phase7b_restore_0123456789abcdef0123456789abcdef"
SCHEMA_EXISTS_SQL = "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s"
SERVER_VERSION_SQL = "SELECT VERSION() AS version"
TABLE_STORAGE_SQL = (
    "SELECT TABLE_NAME, ENGINE, TABLE_COLLATION FROM information_schema.TABLES "
    "WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"
)
SCHEMA_METADATA_SQL = (
    "SELECT schema_version, manifest_hash FROM `{database}`.`schema_metadata` "
    "WHERE singleton_id=1"
)
SCHEMA_METADATA_COUNT_SQL = (
    "SELECT COUNT(*) AS count FROM `{database}`.`schema_metadata` WHERE singleton_id=1"
)
STRUCTURE_QUERIES = (
    "SELECT TABLE_NAME, TABLE_TYPE, ENGINE, TABLE_COLLATION, ROW_FORMAT, CREATE_OPTIONS "
    "FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s "
    "AND TABLE_TYPE IN ('BASE TABLE','VIEW') ORDER BY TABLE_NAME, TABLE_TYPE",
    "SELECT TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, COLUMN_DEFAULT, IS_NULLABLE, "
    "DATA_TYPE, COLUMN_TYPE, CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE, "
    "CHARACTER_SET_NAME, COLLATION_NAME, EXTRA, GENERATION_EXPRESSION, SRS_ID "
    "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s "
    "ORDER BY TABLE_NAME, ORDINAL_POSITION, COLUMN_NAME",
    "SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME, COLLATION, "
    "SUB_PART, INDEX_TYPE, NULLABLE, EXPRESSION, IS_VISIBLE FROM information_schema.STATISTICS "
    "WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX, COLUMN_NAME",
    "SELECT CONSTRAINT_NAME, TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, "
    "POSITION_IN_UNIQUE_CONSTRAINT, REFERENCED_TABLE_SCHEMA, REFERENCED_TABLE_NAME, "
    "REFERENCED_COLUMN_NAME "
    "FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=%s "
    "ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION, COLUMN_NAME",
    "SELECT CONSTRAINT_NAME, TABLE_NAME, REFERENCED_TABLE_NAME, UNIQUE_CONSTRAINT_SCHEMA, "
    "UNIQUE_CONSTRAINT_NAME, MATCH_OPTION, UPDATE_RULE, DELETE_RULE "
    "FROM information_schema.REFERENTIAL_CONSTRAINTS "
    "WHERE CONSTRAINT_SCHEMA=%s ORDER BY TABLE_NAME, CONSTRAINT_NAME",
    "SELECT CONSTRAINT_NAME, TABLE_NAME, CONSTRAINT_TYPE, ENFORCED "
    "FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA=%s "
    "ORDER BY TABLE_NAME, CONSTRAINT_NAME, CONSTRAINT_TYPE",
    "SELECT tc.TABLE_NAME, cc.CONSTRAINT_NAME, cc.CHECK_CLAUSE "
    "FROM information_schema.CHECK_CONSTRAINTS AS cc "
    "JOIN information_schema.TABLE_CONSTRAINTS AS tc "
    "ON tc.CONSTRAINT_SCHEMA=cc.CONSTRAINT_SCHEMA "
    "AND tc.CONSTRAINT_NAME=cc.CONSTRAINT_NAME "
    "WHERE tc.TABLE_SCHEMA=%s AND tc.CONSTRAINT_TYPE='CHECK' "
    "ORDER BY tc.TABLE_NAME, cc.CONSTRAINT_NAME",
    "SELECT TABLE_NAME, VIEW_DEFINITION, CHECK_OPTION, IS_UPDATABLE, DEFINER, SECURITY_TYPE, "
    "CHARACTER_SET_CLIENT, COLLATION_CONNECTION FROM information_schema.VIEWS "
    "WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME",
    "SELECT TABLE_NAME, PARTITION_NAME, SUBPARTITION_NAME, PARTITION_ORDINAL_POSITION, "
    "SUBPARTITION_ORDINAL_POSITION, PARTITION_METHOD, SUBPARTITION_METHOD, "
    "PARTITION_EXPRESSION, SUBPARTITION_EXPRESSION, PARTITION_DESCRIPTION "
    "FROM information_schema.PARTITIONS WHERE TABLE_SCHEMA=%s AND PARTITION_NAME IS NOT NULL "
    "ORDER BY TABLE_NAME, PARTITION_ORDINAL_POSITION, SUBPARTITION_ORDINAL_POSITION, "
    "PARTITION_NAME, SUBPARTITION_NAME",
)

STRUCTURE_KEYS = (
    frozenset({"TABLE_NAME", "TABLE_TYPE", "ENGINE", "TABLE_COLLATION", "ROW_FORMAT", "CREATE_OPTIONS"}),
    frozenset({"TABLE_NAME", "COLUMN_NAME", "ORDINAL_POSITION", "COLUMN_DEFAULT", "IS_NULLABLE", "DATA_TYPE", "COLUMN_TYPE", "CHARACTER_MAXIMUM_LENGTH", "NUMERIC_PRECISION", "NUMERIC_SCALE", "CHARACTER_SET_NAME", "COLLATION_NAME", "EXTRA", "GENERATION_EXPRESSION", "SRS_ID"}),
    frozenset({"TABLE_NAME", "INDEX_NAME", "NON_UNIQUE", "SEQ_IN_INDEX", "COLUMN_NAME", "COLLATION", "SUB_PART", "INDEX_TYPE", "NULLABLE", "EXPRESSION", "IS_VISIBLE"}),
    frozenset({"CONSTRAINT_NAME", "TABLE_NAME", "COLUMN_NAME", "ORDINAL_POSITION", "POSITION_IN_UNIQUE_CONSTRAINT", "REFERENCED_TABLE_SCHEMA", "REFERENCED_TABLE_NAME", "REFERENCED_COLUMN_NAME"}),
    frozenset({"CONSTRAINT_NAME", "TABLE_NAME", "REFERENCED_TABLE_NAME", "UNIQUE_CONSTRAINT_SCHEMA", "UNIQUE_CONSTRAINT_NAME", "MATCH_OPTION", "UPDATE_RULE", "DELETE_RULE"}),
    frozenset({"CONSTRAINT_NAME", "TABLE_NAME", "CONSTRAINT_TYPE", "ENFORCED"}),
    frozenset({"TABLE_NAME", "CONSTRAINT_NAME", "CHECK_CLAUSE"}),
    frozenset({"TABLE_NAME", "VIEW_DEFINITION", "CHECK_OPTION", "IS_UPDATABLE", "DEFINER", "SECURITY_TYPE", "CHARACTER_SET_CLIENT", "COLLATION_CONNECTION"}),
    frozenset({"TABLE_NAME", "PARTITION_NAME", "SUBPARTITION_NAME", "PARTITION_ORDINAL_POSITION", "SUBPARTITION_ORDINAL_POSITION", "PARTITION_METHOD", "SUBPARTITION_METHOD", "PARTITION_EXPRESSION", "SUBPARTITION_EXPRESSION", "PARTITION_DESCRIPTION"}),
)


def structure_rows(database: str = LEGACY_DATABASE) -> list[list[dict[str, object]]]:
    return [
        [
            {"TABLE_NAME": "metadata_view", "TABLE_TYPE": "VIEW", "ENGINE": None, "TABLE_COLLATION": None, "ROW_FORMAT": None, "CREATE_OPTIONS": None},
            {"TABLE_NAME": "schema_metadata", "TABLE_TYPE": "BASE TABLE", "ENGINE": "InnoDB", "TABLE_COLLATION": "utf8mb4_0900_ai_ci", "ROW_FORMAT": "Dynamic", "CREATE_OPTIONS": ""},
        ],
        [{"TABLE_NAME": "schema_metadata", "COLUMN_NAME": "singleton_id", "ORDINAL_POSITION": 1, "COLUMN_DEFAULT": None, "IS_NULLABLE": "NO", "DATA_TYPE": "bigint", "COLUMN_TYPE": "bigint", "CHARACTER_MAXIMUM_LENGTH": None, "NUMERIC_PRECISION": 20, "NUMERIC_SCALE": 0, "CHARACTER_SET_NAME": None, "COLLATION_NAME": None, "EXTRA": "", "GENERATION_EXPRESSION": "", "SRS_ID": None}],
        [{"TABLE_NAME": "schema_metadata", "INDEX_NAME": "PRIMARY", "NON_UNIQUE": 0, "SEQ_IN_INDEX": 1, "COLUMN_NAME": "singleton_id", "COLLATION": "A", "SUB_PART": None, "INDEX_TYPE": "BTREE", "NULLABLE": "", "EXPRESSION": None, "IS_VISIBLE": "YES"}],
        [{"CONSTRAINT_NAME": "child_fk", "TABLE_NAME": "child", "COLUMN_NAME": "parent_id", "ORDINAL_POSITION": 1, "POSITION_IN_UNIQUE_CONSTRAINT": 1, "REFERENCED_TABLE_SCHEMA": database, "REFERENCED_TABLE_NAME": "parent", "REFERENCED_COLUMN_NAME": "id"}],
        [{"CONSTRAINT_NAME": "child_fk", "TABLE_NAME": "child", "REFERENCED_TABLE_NAME": "parent", "UNIQUE_CONSTRAINT_SCHEMA": database, "UNIQUE_CONSTRAINT_NAME": "PRIMARY", "MATCH_OPTION": "NONE", "UPDATE_RULE": "RESTRICT", "DELETE_RULE": "CASCADE"}],
        [{"CONSTRAINT_NAME": "PRIMARY", "TABLE_NAME": "schema_metadata", "CONSTRAINT_TYPE": "PRIMARY KEY", "ENFORCED": "YES"}],
        [{"TABLE_NAME": "schema_metadata", "CONSTRAINT_NAME": "singleton_check", "CHECK_CLAUSE": "(`singleton_id` = 1)"}],
        [{"TABLE_NAME": "metadata_view", "VIEW_DEFINITION": "select `schema_metadata`.`schema_version` AS `schema_version` from `schema_metadata`", "CHECK_OPTION": "NONE", "IS_UPDATABLE": "YES", "DEFINER": "app@%", "SECURITY_TYPE": "DEFINER", "CHARACTER_SET_CLIENT": "utf8mb4", "COLLATION_CONNECTION": "utf8mb4_0900_ai_ci"}],
        [{"TABLE_NAME": "events", "PARTITION_NAME": "p0", "SUBPARTITION_NAME": None, "PARTITION_ORDINAL_POSITION": 1, "SUBPARTITION_ORDINAL_POSITION": None, "PARTITION_METHOD": "RANGE", "SUBPARTITION_METHOD": None, "PARTITION_EXPRESSION": "year(`created_at`)", "SUBPARTITION_EXPRESSION": None, "PARTITION_DESCRIPTION": "2026"}],
    ]


class RecordingSession:
    def __init__(self, *, database: str = LEGACY_DATABASE, tables=None, structures=None):
        self.database = database
        self.tables = tables if tables is not None else [
            {"TABLE_NAME": "schema_metadata", "ENGINE": "InnoDB", "TABLE_COLLATION": "utf8mb4_0900_ai_ci"}
        ]
        self.structures = structures if structures is not None else structure_rows(database)
        self.calls: list[tuple[str, str, tuple[object, ...]]] = []
        self.exists = True
        self.metadata: list[dict[str, object]] = [
            {"schema_version": "writer-core-v1.13.0", "manifest_hash": "a" * 64}
        ]
        self.metadata_match_count: object = 1
        self.counts: dict[str, object] = {row["TABLE_NAME"]: 1 for row in self.tables}
        self.failure: BaseException | None = None

    async def execute(self, sql: str, params: tuple[object, ...] = ()):
        raise AssertionError("read-only inventory must use the session fetch API")

    def _record(self, method: str, sql: str, params: tuple[object, ...]) -> None:
        self.calls.append((method, sql, params))
        upper = sql.upper()
        forbidden = ("SELECT *", "API_KEY", "PAYLOAD_JSON", "CONTENT_JSON", "RAW_BODY", "RAW_PROMPT", "PROVIDER")
        if any(token in upper for token in forbidden):
            raise AssertionError("business values must never be selected")
        if self.failure is not None:
            raise self.failure

    async def fetchone(self, sql: str, params: tuple[object, ...] = ()):
        self._record("fetchone", sql, params)
        if sql == SCHEMA_EXISTS_SQL:
            return {"SCHEMA_NAME": self.database} if self.exists else None
        if sql == SERVER_VERSION_SQL:
            return {"version": "8.4.10"}
        if sql == SCHEMA_METADATA_COUNT_SQL.format(database=self.database):
            return {"count": self.metadata_match_count}
        if sql == SCHEMA_METADATA_SQL.format(database=self.database):
            return self.metadata[0] if self.metadata else None
        if sql.startswith("SELECT COUNT(*) AS count FROM"):
            table = sql.rsplit("`", 2)[1]
            return {"count": self.counts[table]}
        raise AssertionError("unexpected singleton inventory query")

    async def fetchall(self, sql: str, params: tuple[object, ...] = ()):
        self._record("fetchall", sql, params)
        if sql == TABLE_STORAGE_SQL:
            return self.tables
        if sql in STRUCTURE_QUERIES:
            return self.structures[STRUCTURE_QUERIES.index(sql)]
        raise AssertionError("unexpected collection inventory query")


@pytest.mark.asyncio
async def test_inventory_database_executes_only_explicit_read_queries_in_order():
    session = RecordingSession()
    result = await inventory_database(session, LEGACY_DATABASE)
    assert (result.database, result.server_version) == (LEGACY_DATABASE, "8.4.10")
    assert result.schema_version == "writer-core-v1.13.0"
    assert result.manifest_hash == "a" * 64
    assert result.table_names == ("schema_metadata",)
    assert result.row_counts == (("schema_metadata", 1),)
    assert (result.nonempty_table_count, result.total_row_count) == (1, 1)
    assert len(result.structural_fingerprint) == 64
    expected = [
        ("fetchone", SCHEMA_EXISTS_SQL, (LEGACY_DATABASE,)),
        ("fetchone", SERVER_VERSION_SQL, ()),
        ("fetchall", TABLE_STORAGE_SQL, (LEGACY_DATABASE,)),
        ("fetchone", SCHEMA_METADATA_COUNT_SQL.format(database=LEGACY_DATABASE), ()),
        ("fetchone", SCHEMA_METADATA_SQL.format(database=LEGACY_DATABASE), ()),
        ("fetchone", f"SELECT COUNT(*) AS count FROM `{LEGACY_DATABASE}`.`schema_metadata`", ()),
        *(("fetchall", query, (LEGACY_DATABASE,)) for query in STRUCTURE_QUERIES),
    ]
    assert session.calls == expected
    assert len(STRUCTURE_QUERIES) == 9
    assert all("SELECT *" not in sql.upper() for _, sql, _ in session.calls)


def test_independent_structure_query_contract_is_explicit_and_ordered():
    required_sources = (
        "information_schema.TABLES",
        "information_schema.COLUMNS",
        "information_schema.STATISTICS",
        "information_schema.KEY_COLUMN_USAGE",
        "information_schema.REFERENTIAL_CONSTRAINTS",
        "information_schema.TABLE_CONSTRAINTS",
        "information_schema.CHECK_CONSTRAINTS",
        "information_schema.VIEWS",
        "information_schema.PARTITIONS",
    )
    for query, source, expected_keys in zip(
        STRUCTURE_QUERIES, required_sources, STRUCTURE_KEYS, strict=True
    ):
        assert source in query
        assert "SELECT *" not in query.upper()
        assert "ORDER BY" in query
        assert "%s" in query
        selected = query.partition("SELECT ")[2].partition(" FROM ")[0]
        selected_keys = frozenset(
            field.strip().split(".")[-1] for field in selected.split(",")
        )
        assert selected_keys == expected_keys
    assert "TABLE_TYPE IN ('BASE TABLE','VIEW')" in STRUCTURE_QUERIES[0]
    assert "TABLE_NAME, ORDINAL_POSITION, COLUMN_NAME" in STRUCTURE_QUERIES[1]
    assert "TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX, COLUMN_NAME" in STRUCTURE_QUERIES[2]
    assert "TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION, COLUMN_NAME" in STRUCTURE_QUERIES[3]
    assert "CONSTRAINT_SCHEMA=%s" in STRUCTURE_QUERIES[4]
    assert "CONSTRAINT_TYPE, ENFORCED" in STRUCTURE_QUERIES[5]
    assert "tc.TABLE_SCHEMA=%s" in STRUCTURE_QUERIES[6]
    assert "SECURITY_TYPE" in STRUCTURE_QUERIES[7]
    assert "DEFINER" in STRUCTURE_QUERIES[7]
    assert "TABLE_ROWS" not in STRUCTURE_QUERIES[8]
    assert "DATA_LENGTH" not in STRUCTURE_QUERIES[8]


@pytest.mark.asyncio
async def test_database_name_does_not_enter_structural_fingerprint():
    source = await inventory_database(RecordingSession(), LEGACY_DATABASE)
    restored = await inventory_database(RecordingSession(database=RESTORE_DATABASE), RESTORE_DATABASE)
    assert source.structural_fingerprint == restored.structural_fingerprint


@pytest.mark.asyncio
@pytest.mark.parametrize("section", range(9))
async def test_structural_category_mutation_changes_fingerprint(section: int):
    baseline = await inventory_database(RecordingSession(), LEGACY_DATABASE)
    changed = structure_rows()
    mutation_keys = (
        "CREATE_OPTIONS",
        "COLUMN_NAME",
        "INDEX_NAME",
        "CONSTRAINT_NAME",
        "CONSTRAINT_NAME",
        "CONSTRAINT_NAME",
        "CHECK_CLAUSE",
        "CHECK_OPTION",
        "PARTITION_DESCRIPTION",
    )
    changed[section][0][mutation_keys[section]] = "changed"
    observed = await inventory_database(RecordingSession(structures=changed), LEGACY_DATABASE)
    assert observed.structural_fingerprint != baseline.structural_fingerprint


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("section", "key", "changed_value"),
    (
        (0, "TABLE_TYPE", "BASE TABLE"),
        (0, "CREATE_OPTIONS", "partitioned"),
        (1, "SRS_ID", 4326),
        (2, "IS_VISIBLE", "NO"),
        (3, "REFERENCED_TABLE_SCHEMA", "external_schema"),
        (4, "UNIQUE_CONSTRAINT_SCHEMA", "external_schema"),
        (7, "VIEW_DEFINITION", "select 2 AS `schema_version`"),
        (7, "DEFINER", "other_app@%"),
        (8, "PARTITION_EXPRESSION", "to_days(`created_at`)"),
        (8, "PARTITION_DESCRIPTION", "2027"),
    ),
)
async def test_new_structural_attributes_change_fingerprint(
    section: int,
    key: str,
    changed_value: object,
):
    baseline = await inventory_database(RecordingSession(), LEGACY_DATABASE)
    changed = structure_rows()
    changed[section][0][key] = changed_value
    if key == "TABLE_TYPE":
        changed[7] = []
    observed = await inventory_database(
        RecordingSession(structures=changed), LEGACY_DATABASE
    )
    assert observed.structural_fingerprint != baseline.structural_fingerprint


@pytest.mark.asyncio
async def test_self_fk_schema_is_name_independent_but_external_schema_identity_is_not():
    source = await inventory_database(RecordingSession(), LEGACY_DATABASE)
    restored = await inventory_database(
        RecordingSession(database=RESTORE_DATABASE), RESTORE_DATABASE
    )
    assert source.structural_fingerprint == restored.structural_fingerprint

    external_source_rows = structure_rows()
    external_restore_rows = structure_rows(RESTORE_DATABASE)
    for rows in (external_source_rows, external_restore_rows):
        rows[3][0]["REFERENCED_TABLE_SCHEMA"] = "shared_external"
        rows[4][0]["UNIQUE_CONSTRAINT_SCHEMA"] = "shared_external"
    external_source = await inventory_database(
        RecordingSession(structures=external_source_rows), LEGACY_DATABASE
    )
    external_restore = await inventory_database(
        RecordingSession(database=RESTORE_DATABASE, structures=external_restore_rows),
        RESTORE_DATABASE,
    )
    assert external_source.structural_fingerprint == external_restore.structural_fingerprint
    assert external_source.structural_fingerprint != source.structural_fingerprint

    other_external = structure_rows()
    other_external[3][0]["REFERENCED_TABLE_SCHEMA"] = "other_external"
    other_external[4][0]["UNIQUE_CONSTRAINT_SCHEMA"] = "other_external"
    other = await inventory_database(
        RecordingSession(structures=other_external), LEGACY_DATABASE
    )
    assert other.structural_fingerprint != external_source.structural_fingerprint


@pytest.mark.asyncio
async def test_view_differences_change_structure_without_affecting_base_counts():
    baseline = await inventory_database(RecordingSession(), LEGACY_DATABASE)
    without_view = structure_rows()
    without_view[0] = [row for row in without_view[0] if row["TABLE_TYPE"] != "VIEW"]
    without_view[7] = []
    removed = await inventory_database(
        RecordingSession(structures=without_view), LEGACY_DATABASE
    )
    changed_view = structure_rows()
    changed_view[7][0]["VIEW_DEFINITION"] = "select 2 AS `schema_version`"
    changed = await inventory_database(
        RecordingSession(structures=changed_view), LEGACY_DATABASE
    )
    assert removed.structural_fingerprint != baseline.structural_fingerprint
    assert changed.structural_fingerprint != baseline.structural_fingerprint
    assert baseline.table_names == removed.table_names == changed.table_names
    assert baseline.row_counts == removed.row_counts == changed.row_counts


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("VIEW_DEFINITION", None),
        ("VIEW_DEFINITION", ""),
        ("VIEW_DEFINITION", "   "),
        ("DEFINER", None),
        ("DEFINER", ""),
        ("DEFINER", "   "),
        ("SECURITY_TYPE", ""),
        ("SECURITY_TYPE", "OWNER"),
    ),
)
async def test_view_authority_fields_are_closed_and_nonempty(
    field: str,
    value: object,
):
    sensitive = "password=view-authority-secret"
    changed = structure_rows()
    changed[7][0][field] = sensitive if value == "OWNER" else value
    if field == "SECURITY_TYPE" and value == "OWNER":
        changed[7][0][field] = value
    with pytest.raises(ProductDatabaseReadinessError) as captured:
        await inventory_database(
            RecordingSession(structures=changed), LEGACY_DATABASE
        )
    assert str(captured.value) == "database inventory failed"
    assert sensitive not in "".join(traceback.format_exception(captured.value))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "inconsistency",
    ("missing", "duplicate", "extra", "base_table", "duplicate_table_view"),
)
async def test_tables_and_views_must_have_an_exact_one_to_one_mapping(
    inconsistency: str,
):
    changed = structure_rows()
    if inconsistency == "missing":
        changed[7] = []
    elif inconsistency == "duplicate":
        changed[7].append(dict(changed[7][0]))
    elif inconsistency == "extra":
        changed[7].append(dict(changed[7][0]) | {"TABLE_NAME": "extra_view"})
    elif inconsistency == "base_table":
        changed[7][0]["TABLE_NAME"] = "schema_metadata"
    else:
        changed[0].append(dict(changed[0][0]))
    with pytest.raises(ProductDatabaseReadinessError) as captured:
        await inventory_database(
            RecordingSession(structures=changed), LEGACY_DATABASE
        )
    assert str(captured.value) == "database inventory failed"


@pytest.mark.asyncio
async def test_null_view_definitions_cannot_create_false_equal_fingerprints():
    for definer in ("app@%", "other_app@%"):
        changed = structure_rows()
        changed[7][0]["VIEW_DEFINITION"] = None
        changed[7][0]["DEFINER"] = definer
        with pytest.raises(ProductDatabaseReadinessError, match="^database inventory failed$"):
            await inventory_database(
                RecordingSession(structures=changed), LEGACY_DATABASE
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("section", range(9))
@pytest.mark.parametrize("malformation", ("missing", "extra"))
async def test_every_structure_category_requires_exact_keys(
    section: int,
    malformation: str,
):
    changed = structure_rows()
    if malformation == "missing":
        changed[section][0].pop(next(iter(STRUCTURE_KEYS[section])))
    else:
        changed[section][0]["UNEXPECTED"] = "value"
    with pytest.raises(ProductDatabaseReadinessError) as captured:
        await inventory_database(
            RecordingSession(structures=changed), LEGACY_DATABASE
        )
    assert str(captured.value) == "database inventory failed"


@pytest.mark.asyncio
async def test_structural_fingerprint_normalizes_equivalent_row_order():
    ordered = structure_rows()
    ordered[1].append(dict(ordered[1][0]) | {"COLUMN_NAME": "schema_version", "ORDINAL_POSITION": 2})
    reversed_rows = structure_rows()
    reversed_rows[1] = list(reversed(ordered[1]))
    first = await inventory_database(RecordingSession(structures=ordered), LEGACY_DATABASE)
    second = await inventory_database(RecordingSession(structures=reversed_rows), LEGACY_DATABASE)
    assert first.structural_fingerprint == second.structural_fingerprint


@pytest.mark.asyncio
async def test_inventory_requires_sorted_unique_tables_and_derives_totals():
    tables = [
        {"TABLE_NAME": "a_table", "ENGINE": "InnoDB", "TABLE_COLLATION": "utf8mb4_0900_ai_ci"},
        {"TABLE_NAME": "z_table", "ENGINE": "InnoDB", "TABLE_COLLATION": "utf8mb4_0900_ai_ci"},
    ]
    session = RecordingSession(tables=tables)
    session.counts = {"a_table": 0, "z_table": 3}
    result = await inventory_database(session, LEGACY_DATABASE)
    assert result.table_names == ("a_table", "z_table")
    assert result.row_counts == (("a_table", 0), ("z_table", 3))
    assert (result.nonempty_table_count, result.total_row_count) == (1, 3)
    assert result.schema_version is None and result.manifest_hash is None


@pytest.mark.asyncio
@pytest.mark.parametrize("database", ("", "bad-name", "x` UNION SELECT 1", "a" * 65, "数据库", 1))
async def test_invalid_database_identifier_is_rejected_before_session(database: object):
    session = RecordingSession()
    with pytest.raises(ProductDatabaseReadinessError) as captured:
        await inventory_database(session, database)  # type: ignore[arg-type]
    assert str(captured.value) == "database inventory target is invalid"
    assert session.calls == []


@pytest.mark.asyncio
async def test_invalid_table_identifier_is_never_interpolated_into_count_sql():
    session = RecordingSession(tables=[{"TABLE_NAME": "bad`table", "ENGINE": "InnoDB", "TABLE_COLLATION": "utf8mb4_0900_ai_ci"}])
    with pytest.raises(ProductDatabaseReadinessError) as captured:
        await inventory_database(session, LEGACY_DATABASE)
    assert str(captured.value) == "database inventory failed"
    assert not any("COUNT(*)" in sql for _, sql, _ in session.calls)


@pytest.mark.asyncio
async def test_storage_helper_and_policy_are_narrow_and_frozen():
    rows = await read_table_storage(RecordingSession(), LEGACY_DATABASE)
    assert rows == (TableStorage("schema_metadata", "InnoDB", "utf8mb4_0900_ai_ci"),)
    assert_storage_policy(rows)
    with pytest.raises(FrozenInstanceError):
        rows[0].engine = "MyISAM"  # type: ignore[misc]
    for invalid in (
        (TableStorage("schema_metadata", "MyISAM", "utf8mb4_0900_ai_ci"),),
        (TableStorage("schema_metadata", "InnoDB", "utf8mb4_general_ci"),),
    ):
        with pytest.raises(ProductDatabaseReadinessError, match="^database table storage policy failed$"):
            assert_storage_policy(invalid)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row",
    (
        {"TABLE_NAME": "bad-table", "ENGINE": "InnoDB", "TABLE_COLLATION": "utf8mb4_0900_ai_ci"},
        {"TABLE_NAME": "schema_metadata", "ENGINE": None, "TABLE_COLLATION": "utf8mb4_0900_ai_ci"},
        {"TABLE_NAME": "schema_metadata", "ENGINE": "InnoDB", "TABLE_COLLATION": True},
    ),
)
async def test_storage_helper_remaps_invalid_returned_rows(row: dict[str, object]):
    with pytest.raises(ProductDatabaseReadinessError) as captured:
        await read_table_storage(RecordingSession(tables=[row]), LEGACY_DATABASE)
    assert str(captured.value) == "database inventory failed"
    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__


@pytest.mark.asyncio
async def test_storage_helper_maps_operational_failure_without_secret_context():
    sensitive = "password=storage-secret dsn=mysql://private"
    session = RecordingSession()
    session.failure = RuntimeError(sensitive)
    with pytest.raises(ProductDatabaseReadinessError) as captured:
        await read_table_storage(session, LEGACY_DATABASE)
    assert str(captured.value) == "database inventory failed"
    assert sensitive not in "".join(traceback.format_exception(captured.value))


@pytest.mark.asyncio
async def test_collaborator_domain_error_is_remapped_without_secret_context():
    sensitive = "password=collaborator-secret dsn=mysql://private"
    session = RecordingSession()
    session.failure = ProductDatabaseReadinessError(sensitive)
    with pytest.raises(ProductDatabaseReadinessError) as captured:
        await inventory_database(session, LEGACY_DATABASE)
    assert str(captured.value) == "database inventory failed"
    assert sensitive not in "".join(traceback.format_exception(captured.value))

    storage_session = RecordingSession()
    storage_session.failure = ProductDatabaseReadinessError(sensitive)
    with pytest.raises(ProductDatabaseReadinessError) as storage_captured:
        await read_table_storage(storage_session, LEGACY_DATABASE)
    assert str(storage_captured.value) == "database inventory failed"
    assert sensitive not in "".join(traceback.format_exception(storage_captured.value))


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ("absent", "metadata", "manifest_hash", "count", "structure"))
async def test_inventory_data_failures_use_fixed_errors(failure: str):
    session = RecordingSession()
    expected = "database inventory failed"
    if failure == "absent":
        session.exists = False
        expected = "database inventory target is absent"
    elif failure == "metadata":
        session.metadata = []
    elif failure == "manifest_hash":
        session.metadata[0]["manifest_hash"] = "invalid"
    elif failure == "count":
        session.counts["schema_metadata"] = True
    else:
        session.structures[1][0]["COLUMN_DEFAULT"] = b"secret bytes"
    with pytest.raises(ProductDatabaseReadinessError) as captured:
        await inventory_database(session, LEGACY_DATABASE)
    assert str(captured.value) == expected
    assert captured.value.__cause__ is None and captured.value.__suppress_context__


@pytest.mark.asyncio
@pytest.mark.parametrize("match_count", (0, 2, True, None, "1"))
async def test_schema_metadata_requires_exactly_one_singleton_match(
    match_count: object,
):
    session = RecordingSession()
    session.metadata_match_count = match_count
    with pytest.raises(ProductDatabaseReadinessError) as captured:
        await inventory_database(session, LEGACY_DATABASE)
    assert str(captured.value) == "database inventory failed"
    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__


@pytest.mark.asyncio
async def test_conflicting_duplicate_schema_metadata_is_rejected():
    session = RecordingSession()
    session.metadata = [
        {"schema_version": "writer-core-v1.13.0", "manifest_hash": "a" * 64},
        {"schema_version": "writer-core-v1.13.1", "manifest_hash": "b" * 64},
    ]
    session.metadata_match_count = 2
    with pytest.raises(ProductDatabaseReadinessError, match="^database inventory failed$"):
        await inventory_database(session, LEGACY_DATABASE)


@pytest.mark.asyncio
async def test_malformed_schema_metadata_count_row_is_rejected():
    class MalformedCountSession(RecordingSession):
        async def fetchone(self, sql: str, params: tuple[object, ...] = ()):
            if sql == SCHEMA_METADATA_COUNT_SQL.format(database=self.database):
                return {"wrong_key": 1}
            return await super().fetchone(sql, params)

    with pytest.raises(ProductDatabaseReadinessError, match="^database inventory failed$"):
        await inventory_database(MalformedCountSession(), LEGACY_DATABASE)


@pytest.mark.asyncio
async def test_unsorted_or_duplicate_table_rows_are_rejected():
    for names in (("z", "a"), ("a", "a")):
        tables = [{"TABLE_NAME": name, "ENGINE": "InnoDB", "TABLE_COLLATION": "utf8mb4_0900_ai_ci"} for name in names]
        with pytest.raises(ProductDatabaseReadinessError, match="^database inventory failed$"):
            await inventory_database(RecordingSession(tables=tables), LEGACY_DATABASE)


@pytest.mark.asyncio
async def test_operational_failure_is_fixed_and_cancellation_is_preserved():
    sensitive = "password=hidden dsn=mysql://private"
    failed = RecordingSession(); failed.failure = RuntimeError(sensitive)
    with pytest.raises(ProductDatabaseReadinessError) as captured:
        await inventory_database(failed, LEGACY_DATABASE)
    assert str(captured.value) == "database inventory failed"
    assert sensitive not in "".join(traceback.format_exception(captured.value))
    cancelled = RecordingSession(); cancelled.failure = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await inventory_database(cancelled, LEGACY_DATABASE)


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupt", (KeyboardInterrupt, SystemExit))
async def test_inventory_preserves_process_interrupts(interrupt: type[BaseException]):
    session = RecordingSession()
    session.failure = interrupt()
    with pytest.raises(interrupt):
        await inventory_database(session, LEGACY_DATABASE)


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupt", (asyncio.CancelledError, KeyboardInterrupt, SystemExit))
async def test_storage_preserves_cancellation_and_process_interrupts(
    interrupt: type[BaseException],
):
    session = RecordingSession()
    session.failure = interrupt()
    with pytest.raises(interrupt):
        await read_table_storage(session, LEGACY_DATABASE)


@pytest.mark.asyncio
async def test_canonical_hash_domain_error_is_remapped(monkeypatch: pytest.MonkeyPatch):
    sensitive = "password=canonical-secret dsn=mysql://private"

    def fail_hash(value: object) -> str:
        raise ProductDatabaseReadinessError(sensitive)

    monkeypatch.setattr(
        "backend.services.product_database_inventory.canonical_hash",
        fail_hash,
    )
    with pytest.raises(ProductDatabaseReadinessError) as captured:
        await inventory_database(RecordingSession(), LEGACY_DATABASE)
    assert str(captured.value) == "database inventory failed"
    assert sensitive not in "".join(traceback.format_exception(captured.value))


@pytest.mark.asyncio
async def test_public_error_suppresses_ambient_sensitive_context():
    sentinel = "password=ambient dsn=mysql://private"
    session = RecordingSession(); session.exists = False
    try:
        raise RuntimeError(sentinel)
    except RuntimeError:
        with pytest.raises(ProductDatabaseReadinessError) as captured:
            await inventory_database(session, LEGACY_DATABASE)
    assert sentinel not in "".join(traceback.format_exception(captured.value))


@pytest.mark.asyncio
async def test_empty_server_version_is_rejected():
    class BadSession(RecordingSession):
        async def fetchone(self, sql: str, params: tuple[object, ...] = ()):
            if sql == SERVER_VERSION_SQL:
                return {"version": ""}
            return await super().fetchone(sql, params)
    with pytest.raises(ProductDatabaseReadinessError, match="^database inventory failed$"):
        await inventory_database(BadSession(), LEGACY_DATABASE)


def test_assert_inventory_equal_ignores_database_and_server_only():
    baseline = asyncio.run(inventory_database(RecordingSession(), LEGACY_DATABASE))
    assert_inventory_equal(baseline, replace(baseline, database=RESTORE_DATABASE, server_version="8.4.11"))
    cases = (
        {"table_names": (), "row_counts": (), "nonempty_table_count": 0, "total_row_count": 0},
        {"schema_version": "changed"}, {"manifest_hash": "b" * 64},
        {"structural_fingerprint": "c" * 64},
        {"row_counts": (), "table_names": (), "nonempty_table_count": 0, "total_row_count": 0},
    )
    for changes in cases:
        with pytest.raises(ProductDatabaseReadinessError, match="^database inventory comparison failed$"):
            assert_inventory_equal(baseline, replace(baseline, **changes))


def test_public_assertion_errors_suppress_ambient_sensitive_context():
    baseline = asyncio.run(inventory_database(RecordingSession(), LEGACY_DATABASE))
    sentinel = "password=ambient dsn=mysql://private"
    comparison_changes = (
        {"table_names": (), "row_counts": (), "nonempty_table_count": 0, "total_row_count": 0},
        {"schema_version": "changed"},
        {"manifest_hash": "b" * 64},
        {"structural_fingerprint": "c" * 64},
        {"row_counts": (), "table_names": (), "nonempty_table_count": 0, "total_row_count": 0},
    )
    for changes in comparison_changes:
        try:
            raise RuntimeError(sentinel)
        except RuntimeError:
            with pytest.raises(ProductDatabaseReadinessError) as captured:
                assert_inventory_equal(baseline, replace(baseline, **changes))
        assert str(captured.value) == "database inventory comparison failed"
        assert captured.value.__cause__ is None
        assert captured.value.__suppress_context__
        assert sentinel not in "".join(traceback.format_exception(captured.value))

    try:
        raise RuntimeError(sentinel)
    except RuntimeError:
        with pytest.raises(ProductDatabaseReadinessError) as storage:
            assert_storage_policy((TableStorage("x", "MyISAM", "utf8mb4_0900_ai_ci"),))
    assert str(storage.value) == "database table storage policy failed"
    assert storage.value.__cause__ is None
    assert storage.value.__suppress_context__
    assert sentinel not in "".join(traceback.format_exception(storage.value))
