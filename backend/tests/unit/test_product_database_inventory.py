import asyncio
from dataclasses import FrozenInstanceError, replace
import traceback

import pytest

from backend.domain.product_database_readiness import LEGACY_DATABASE, ProductDatabaseReadinessError
from backend.services.product_database_inventory import (
    SCHEMA_EXISTS_SQL, SCHEMA_METADATA_SQL, SERVER_VERSION_SQL, STRUCTURE_QUERIES,
    TABLE_STORAGE_SQL, TableStorage, assert_inventory_equal, assert_storage_policy,
    inventory_database, read_table_storage,
)


RESTORE_DATABASE = "novel_creator_phase7b_restore_0123456789abcdef0123456789abcdef"


def structure_rows() -> list[list[dict[str, object]]]:
    return [
        [{"TABLE_NAME": "schema_metadata", "ENGINE": "InnoDB", "TABLE_COLLATION": "utf8mb4_0900_ai_ci", "ROW_FORMAT": "Dynamic"}],
        [{"TABLE_NAME": "schema_metadata", "COLUMN_NAME": "singleton_id", "ORDINAL_POSITION": 1, "COLUMN_DEFAULT": None, "IS_NULLABLE": "NO", "DATA_TYPE": "bigint", "COLUMN_TYPE": "bigint", "CHARACTER_MAXIMUM_LENGTH": None, "NUMERIC_PRECISION": 20, "NUMERIC_SCALE": 0, "CHARACTER_SET_NAME": None, "COLLATION_NAME": None, "EXTRA": "", "GENERATION_EXPRESSION": ""}],
        [{"TABLE_NAME": "schema_metadata", "INDEX_NAME": "PRIMARY", "NON_UNIQUE": 0, "SEQ_IN_INDEX": 1, "COLUMN_NAME": "singleton_id", "COLLATION": "A", "SUB_PART": None, "INDEX_TYPE": "BTREE", "NULLABLE": "", "EXPRESSION": None}],
        [{"CONSTRAINT_NAME": "PRIMARY", "TABLE_NAME": "schema_metadata", "COLUMN_NAME": "singleton_id", "ORDINAL_POSITION": 1, "POSITION_IN_UNIQUE_CONSTRAINT": None, "REFERENCED_TABLE_NAME": None, "REFERENCED_COLUMN_NAME": None}],
        [],
        [{"CONSTRAINT_NAME": "PRIMARY", "TABLE_NAME": "schema_metadata", "CONSTRAINT_TYPE": "PRIMARY KEY", "ENFORCED": "YES"}],
        [],
    ]


class RecordingSession:
    def __init__(self, *, database: str = LEGACY_DATABASE, tables=None, structures=None):
        self.database = database
        self.tables = tables if tables is not None else [
            {"TABLE_NAME": "schema_metadata", "ENGINE": "InnoDB", "TABLE_COLLATION": "utf8mb4_0900_ai_ci"}
        ]
        self.structures = structures if structures is not None else structure_rows()
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.exists = True
        self.metadata: list[dict[str, object]] = [
            {"schema_version": "writer-core-v1.13.0", "manifest_hash": "a" * 64}
        ]
        self.counts: dict[str, object] = {row["TABLE_NAME"]: 1 for row in self.tables}
        self.failure: BaseException | None = None

    async def execute(self, sql: str, params: tuple[object, ...] = ()):
        raise AssertionError("read-only inventory must use the session fetch API")

    async def fetchall(self, sql: str, params: tuple[object, ...] = ()):
        self.calls.append((sql, params))
        upper = sql.upper()
        forbidden = ("SELECT *", "API_KEY", "PAYLOAD_JSON", "CONTENT_JSON", "RAW_BODY", "RAW_PROMPT", "PROVIDER")
        if any(token in upper for token in forbidden):
            raise AssertionError("business values must never be selected")
        if self.failure is not None:
            raise self.failure
        if sql == SCHEMA_EXISTS_SQL:
            return [{"SCHEMA_NAME": self.database}] if self.exists else []
        if sql == SERVER_VERSION_SQL:
            return [{"version": "8.4.10"}]
        if sql == TABLE_STORAGE_SQL:
            return self.tables
        if sql == SCHEMA_METADATA_SQL.format(database=self.database):
            return self.metadata
        if sql.startswith("SELECT COUNT(*) AS count FROM"):
            table = sql.rsplit("`", 2)[1]
            return [{"count": self.counts[table]}]
        if sql in STRUCTURE_QUERIES:
            return self.structures[STRUCTURE_QUERIES.index(sql)]
        raise AssertionError("unexpected inventory query")


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
        (SCHEMA_EXISTS_SQL, (LEGACY_DATABASE,)), (SERVER_VERSION_SQL, ()),
        (TABLE_STORAGE_SQL, (LEGACY_DATABASE,)),
        (SCHEMA_METADATA_SQL.format(database=LEGACY_DATABASE), ()),
        (f"SELECT COUNT(*) AS count FROM `{LEGACY_DATABASE}`.`schema_metadata`", ()),
        *((query, (LEGACY_DATABASE,)) for query in STRUCTURE_QUERIES),
    ]
    assert session.calls == expected
    assert len(STRUCTURE_QUERIES) == 7
    assert all("SELECT *" not in sql.upper() for sql, _ in session.calls)


@pytest.mark.asyncio
async def test_database_name_does_not_enter_structural_fingerprint():
    source = await inventory_database(RecordingSession(), LEGACY_DATABASE)
    restored = await inventory_database(RecordingSession(database=RESTORE_DATABASE), RESTORE_DATABASE)
    assert source.structural_fingerprint == restored.structural_fingerprint


@pytest.mark.asyncio
@pytest.mark.parametrize("section", range(7))
async def test_structural_category_mutation_changes_fingerprint(section: int):
    baseline = await inventory_database(RecordingSession(), LEGACY_DATABASE)
    changed = structure_rows()
    if not changed[section]:
        changed[section].append({"TABLE_NAME": "child", "CONSTRAINT_NAME": "new", "CHECK_CLAUSE": "singleton_id > 0"})
    else:
        first_key = next(iter(changed[section][0]))
        changed[section][0][first_key] = "changed"
    observed = await inventory_database(RecordingSession(structures=changed), LEGACY_DATABASE)
    assert observed.structural_fingerprint != baseline.structural_fingerprint


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
    assert str(captured.value) == "database inventory target is invalid"
    assert not any("COUNT(*)" in sql for sql, _ in session.calls)


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


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ("absent", "metadata", "count", "structure"))
async def test_inventory_data_failures_use_fixed_errors(failure: str):
    session = RecordingSession()
    expected = "database inventory failed"
    if failure == "absent":
        session.exists = False
        expected = "database inventory target is absent"
    elif failure == "metadata":
        session.metadata = []
    elif failure == "count":
        session.counts["schema_metadata"] = True
    else:
        session.structures[1][0]["COLUMN_DEFAULT"] = b"secret bytes"
    with pytest.raises(ProductDatabaseReadinessError) as captured:
        await inventory_database(session, LEGACY_DATABASE)
    assert str(captured.value) == expected
    assert captured.value.__cause__ is None and captured.value.__suppress_context__


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
        async def fetchall(self, sql: str, params: tuple[object, ...] = ()):
            if sql == SERVER_VERSION_SQL:
                return [{"version": ""}]
            return await super().fetchall(sql, params)
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
