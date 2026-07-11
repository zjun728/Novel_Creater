"""Explicit one-time initializer for a new, empty Writer Core database."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import re
import sys
import time
from typing import Awaitable, Callable, Mapping, Sequence

from backend.schema_manifest import created_table_names, manifest_hash, read_statements
from backend.schema_version import EXPECTED_SCHEMA_VERSION


_DATABASE_NAME = re.compile(r"^[A-Za-z0-9_]+$")
_DATABASE_EXISTS_QUERY = (
    "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s"
)
_DATABASE_TABLES_QUERY = (
    "SELECT TABLE_NAME FROM information_schema.TABLES "
    "WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME"
)
_METADATA_INSERT = (
    "INSERT INTO schema_metadata "
    "(singleton_id, schema_version, manifest_hash, initialized_at) "
    "VALUES (1, %s, %s, %s)"
)


class InitializationError(RuntimeError):
    """The explicit bootstrap preconditions were not satisfied."""


@dataclass(frozen=True)
class InitializationResult:
    database_name: str
    schema_version: str
    manifest_hash: str
    table_count: int


def _validated_database_name(database_name: str, confirm_name: str) -> str:
    if not _DATABASE_NAME.fullmatch(database_name):
        raise InitializationError(
            "Invalid database name; use only ASCII letters, digits, and underscore."
        )
    if database_name != confirm_name:
        raise InitializationError("Database confirmation does not match database name.")
    return database_name


async def initialize_database(
    admin_session,
    database_name: str,
    confirm_name: str,
    now_ms: int,
) -> InitializationResult:
    """Create or select an empty database and apply the whole manifest once."""
    name = _validated_database_name(database_name, confirm_name)
    existing = await admin_session.fetchone(_DATABASE_EXISTS_QUERY, (name,))
    created_database = existing is None

    if created_database:
        await admin_session.execute(
            f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_0900_ai_ci"
        )

    try:
        tables = await admin_session.fetchall(_DATABASE_TABLES_QUERY, (name,))
        if tables:
            raise InitializationError(
                f"Database {name!r} is not empty; explicit reinitialization is required."
            )

        await admin_session.execute(f"USE `{name}`")
        for statement in read_statements():
            await admin_session.execute(statement)

        expected_hash = manifest_hash()
        await admin_session.execute(
            _METADATA_INSERT,
            (EXPECTED_SCHEMA_VERSION, expected_hash, now_ms),
        )
    except Exception as bootstrap_error:
        if created_database:
            try:
                await admin_session.execute(f"DROP DATABASE `{name}`")
            except Exception as cleanup_error:
                raise ExceptionGroup(
                    f"Writer Core bootstrap and cleanup both failed; database "
                    f"{name!r} may remain partially initialized",
                    [bootstrap_error, cleanup_error],
                ) from None
        raise

    return InitializationResult(
        database_name=name,
        schema_version=EXPECTED_SCHEMA_VERSION,
        manifest_hash=expected_hash,
        table_count=len(created_table_names()),
    )


def format_initialization_result(result: InitializationResult) -> str:
    """Render only the public bootstrap receipt fields."""
    return "\n".join(
        (
            f"database={result.database_name}",
            f"schema_version={result.schema_version}",
            f"manifest_hash={result.manifest_hash}",
            f"table_count={result.table_count}",
        )
    )


class _AiomysqlAdminSession:
    def __init__(self, connection, cursor):
        self._connection = connection
        self._cursor = cursor
        self._closed = False

    async def fetchone(self, sql, parameters=None):
        await self._cursor.execute(sql, parameters)
        return await self._cursor.fetchone()

    async def fetchall(self, sql, parameters=None):
        await self._cursor.execute(sql, parameters)
        return await self._cursor.fetchall()

    async def execute(self, sql, parameters=None):
        await self._cursor.execute(sql, parameters)

    async def close(self):
        if self._closed:
            return
        failures = []
        try:
            await self._cursor.close()
        except BaseException as exc:
            failures.append(exc)
        try:
            ensure_closed = getattr(self._connection, "ensure_closed", None)
            if ensure_closed is not None:
                await ensure_closed()
            else:
                self._connection.close()
        except BaseException as exc:
            failures.append(exc)
        else:
            self._closed = True
        if len(failures) == 1:
            raise failures[0]
        if failures:
            raise BaseExceptionGroup("admin session close failed", failures)


async def _default_connection_factory(connection_config: Mapping[str, object]):
    import aiomysql

    allowed = {"host", "port", "user", "password", "charset", "autocommit"}
    kwargs = {key: value for key, value in connection_config.items() if key in allowed}
    kwargs["autocommit"] = True
    connection = await aiomysql.connect(**kwargs)
    cursor = await connection.cursor(aiomysql.DictCursor)
    return _AiomysqlAdminSession(connection, cursor)


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Initialize an empty Writer Core database")
    parser.add_argument("--database", required=True)
    parser.add_argument("--confirm-create", required=True)
    return parser


async def run_cli(
    argv: Sequence[str] | None = None,
    *,
    connection_factory: Callable[[Mapping[str, object]], Awaitable[object]] | None = None,
    connection_config: Mapping[str, object] | None = None,
    now_ms: Callable[[], int] | None = None,
    output: Callable[[str], None] = print,
) -> int:
    """Run the CLI with injectable connection configuration for unit tests."""
    args = _argument_parser().parse_args(argv)
    _validated_database_name(args.database, args.confirm_create)

    if connection_config is None:
        from backend.config import require_mysql_config

        connection_config = require_mysql_config()
    factory = connection_factory or _default_connection_factory
    timestamp = now_ms or (lambda: int(time.time() * 1000))
    session = await factory(connection_config)
    try:
        result = await initialize_database(
            session,
            args.database,
            args.confirm_create,
            timestamp(),
        )
    finally:
        await session.close()
    output(format_initialization_result(result))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(run_cli(argv))
    except Exception:
        print("Writer Core database initialization failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
