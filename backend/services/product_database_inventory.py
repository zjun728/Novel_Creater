"""Read-only, secret-safe product database inventory collection."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.product_database_readiness import (
    DatabaseInventory,
    ProductDatabaseReadinessError,
)


_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]{1,64}$", re.ASCII)
_FAILED = "database inventory failed"
_ABSENT = "database inventory target is absent"
_INVALID_TARGET = "database inventory target is invalid"
_COMPARE_FAILED = "database inventory comparison failed"
_STORAGE_FAILED = "database table storage policy failed"

SCHEMA_EXISTS_SQL = (
    "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s"
)
SERVER_VERSION_SQL = "SELECT VERSION() AS version"
TABLE_STORAGE_SQL = (
    "SELECT TABLE_NAME, ENGINE, TABLE_COLLATION "
    "FROM information_schema.TABLES "
    "WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"
)
SCHEMA_METADATA_SQL = (
    "SELECT schema_version, manifest_hash FROM `{database}`.`schema_metadata` "
    "WHERE singleton_id=1"
)

STRUCTURE_QUERIES: tuple[str, ...] = (
    "SELECT TABLE_NAME, ENGINE, TABLE_COLLATION, ROW_FORMAT "
    "FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s "
    "AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME",
    "SELECT TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, COLUMN_DEFAULT, IS_NULLABLE, "
    "DATA_TYPE, COLUMN_TYPE, CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, "
    "NUMERIC_SCALE, CHARACTER_SET_NAME, COLLATION_NAME, EXTRA, GENERATION_EXPRESSION "
    "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s "
    "ORDER BY TABLE_NAME, ORDINAL_POSITION, COLUMN_NAME",
    "SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME, COLLATION, "
    "SUB_PART, INDEX_TYPE, NULLABLE, EXPRESSION FROM information_schema.STATISTICS "
    "WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX, COLUMN_NAME",
    "SELECT CONSTRAINT_NAME, TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, "
    "POSITION_IN_UNIQUE_CONSTRAINT, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME "
    "FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=%s "
    "ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION, COLUMN_NAME",
    "SELECT CONSTRAINT_NAME, TABLE_NAME, REFERENCED_TABLE_NAME, UNIQUE_CONSTRAINT_NAME, "
    "MATCH_OPTION, UPDATE_RULE, DELETE_RULE FROM information_schema.REFERENTIAL_CONSTRAINTS "
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
)


@dataclass(frozen=True)
class TableStorage:
    name: str
    engine: str
    collation: str


def _raise(message: str) -> None:
    raise ProductDatabaseReadinessError(message) from None


def _identifier(value: object) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        _raise(_INVALID_TARGET)
    return value


async def _fetchall(
    session: object,
    sql: str,
    params: tuple[object, ...] = (),
) -> list[Mapping[str, object]]:
    try:
        result = await session.fetchall(sql, params)  # type: ignore[attr-defined]
        if hasattr(result, "mappings"):
            result = result.mappings()
        if hasattr(result, "all"):
            result = result.all()
        if not isinstance(result, Sequence) or isinstance(
            result, (str, bytes, bytearray)
        ):
            _raise(_FAILED)
        rows = list(result)
        if any(not isinstance(row, Mapping) for row in rows):
            _raise(_FAILED)
        return [dict(row) for row in rows]
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        _raise(_FAILED)


def _one(rows: list[Mapping[str, object]]) -> Mapping[str, object]:
    if len(rows) != 1:
        _raise(_FAILED)
    return rows[0]


async def read_table_storage(session: object, database: str) -> tuple[TableStorage, ...]:
    database = _identifier(database)
    try:
        rows = await _fetchall(session, TABLE_STORAGE_SQL, (database,))
        storage: list[TableStorage] = []
        for row in rows:
            name = row.get("TABLE_NAME")
            engine = row.get("ENGINE")
            collation = row.get("TABLE_COLLATION")
            validated_name = _identifier(name)
            if (
                type(engine) is not str
                or not engine
                or type(collation) is not str
                or not collation
            ):
                _raise(_FAILED)
            storage.append(TableStorage(validated_name, engine, collation))
        result = tuple(storage)
        if tuple(item.name for item in result) != tuple(sorted({item.name for item in result})):
            _raise(_FAILED)
        return result
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except ProductDatabaseReadinessError:
        raise
    except Exception:
        _raise(_FAILED)


def assert_storage_policy(rows: tuple[TableStorage, ...]) -> None:
    if type(rows) is not tuple or any(
        type(row) is not TableStorage
        or row.engine != "InnoDB"
        or row.collation != "utf8mb4_0900_ai_ci"
        for row in rows
    ):
        _raise(_STORAGE_FAILED)


def _normalize(rows: list[Mapping[str, object]]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for row in rows:
        clean: dict[str, object] = {}
        for key in sorted(row):
            value = row[key]
            if type(key) is not str or value is not None and type(value) not in (str, int):
                _raise(_FAILED)
            clean[key] = value
        normalized.append(clean)
    return sorted(normalized, key=canonical_json)


async def inventory_database(session: object, database: str) -> DatabaseInventory:
    database = _identifier(database)
    try:
        existence = await _fetchall(session, SCHEMA_EXISTS_SQL, (database,))
        if not existence:
            _raise(_ABSENT)
        schema_name = _one(existence).get("SCHEMA_NAME")
        if schema_name != database or type(schema_name) is not str:
            _raise(_FAILED)

        version = _one(await _fetchall(session, SERVER_VERSION_SQL)).get("version")
        if type(version) is not str or not version:
            _raise(_FAILED)

        storage = await read_table_storage(session, database)
        table_names = tuple(row.name for row in storage)

        schema_version: str | None = None
        manifest_hash: str | None = None
        if "schema_metadata" in table_names:
            metadata = _one(
                await _fetchall(session, SCHEMA_METADATA_SQL.format(database=database))
            )
            schema_version = metadata.get("schema_version")  # type: ignore[assignment]
            manifest_hash = metadata.get("manifest_hash")  # type: ignore[assignment]
            if type(schema_version) is not str or type(manifest_hash) is not str:
                _raise(_FAILED)

        row_counts: list[tuple[str, int]] = []
        for table in table_names:
            validated_table = _identifier(table)
            count = _one(
                await _fetchall(
                    session,
                    f"SELECT COUNT(*) AS count FROM `{database}`.`{validated_table}`",
                )
            ).get("count")
            if type(count) is not int or count < 0:
                _raise(_FAILED)
            row_counts.append((validated_table, count))

        structure: list[dict[str, object]] = []
        for ordinal, sql in enumerate(STRUCTURE_QUERIES):
            structure.append(
                {
                    "query": ordinal,
                    "rows": _normalize(await _fetchall(session, sql, (database,))),
                }
            )
        fingerprint = canonical_hash({"structure": structure})
        counts = tuple(row_counts)
        return DatabaseInventory(
            database=database,
            server_version=version,
            schema_version=schema_version,
            manifest_hash=manifest_hash,
            structural_fingerprint=fingerprint,
            table_names=table_names,
            row_counts=counts,
            nonempty_table_count=sum(count > 0 for _, count in counts),
            total_row_count=sum(count for _, count in counts),
        )
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except ProductDatabaseReadinessError:
        raise
    except Exception:
        _raise(_FAILED)


def assert_inventory_equal(
    authority: DatabaseInventory,
    observed: DatabaseInventory,
) -> None:
    if type(authority) is not DatabaseInventory or type(observed) is not DatabaseInventory:
        _raise(_COMPARE_FAILED)
    comparable = (
        "table_names",
        "schema_version",
        "manifest_hash",
        "structural_fingerprint",
        "row_counts",
    )
    if any(getattr(authority, field) != getattr(observed, field) for field in comparable):
        _raise(_COMPARE_FAILED)
