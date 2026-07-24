"""Guarded helpers for MySQL integration tests.

This module intentionally reads only ``TEST_MYSQL_*`` variables.  It must never
inherit the application's product database configuration.
"""

from __future__ import annotations

import os
import re
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
import time

import aiomysql

from backend.scripts.initialize_database import (
    _AiomysqlAdminSession,
    initialize_database,
)
from backend.services.projections import build_projection_bundle


TEST_PREFIX = "novel_creator_test_"
_DISPOSABLE_NAME = re.compile(r"novel_creator_test_[a-f0-9]{32}")
_REQUIRED_TEST_VARIABLES = (
    "TEST_MYSQL_HOST",
    "TEST_MYSQL_PORT",
    "TEST_MYSQL_USER",
    "TEST_MYSQL_PASSWORD",
)


class _TestDatabaseSession:
    """Minimal explicit session that has no application-config import path."""

    def __init__(self, raw):
        self.raw = raw

    async def execute(self, sql, args=None):
        async with self.raw.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, args)
            return cursor.rowcount

    async def fetchone(self, sql, args=None):
        async with self.raw.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, args)
            return await cursor.fetchone()

    async def fetchall(self, sql, args=None):
        async with self.raw.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, args)
            return await cursor.fetchall()


def test_server_config() -> dict[str, object]:
    """Return an admin connection config only when all test vars are explicit."""
    missing = [name for name in _REQUIRED_TEST_VARIABLES if name not in os.environ]
    if missing:
        raise RuntimeError(
            "Disposable MySQL requires explicit variables: " + ", ".join(missing)
        )
    try:
        port = int(os.environ["TEST_MYSQL_PORT"])
    except ValueError as exc:
        raise RuntimeError("TEST_MYSQL_PORT must be an integer") from exc
    return {
        "host": os.environ["TEST_MYSQL_HOST"],
        "port": port,
        "user": os.environ["TEST_MYSQL_USER"],
        "password": os.environ["TEST_MYSQL_PASSWORD"],
        "charset": "utf8mb4",
        "autocommit": True,
    }


def new_database_name() -> str:
    """Create a fresh name in the only namespace tests may mutate."""
    name = f"{TEST_PREFIX}{uuid.uuid4().hex}"
    assert_disposable_name(name)
    return name


def assert_disposable_name(name: str) -> None:
    """Reject product and non-test database names before any database DDL."""
    if not isinstance(name, str) or _DISPOSABLE_NAME.fullmatch(name) is None:
        raise RuntimeError(f"Refusing non-disposable database: {name}")


@dataclass(frozen=True)
class DisposableMySQL:
    """Handles exposed to one initialized disposable database."""

    database_name: str
    connection_config: dict[str, object]
    admin_session: _AiomysqlAdminSession
    session: _TestDatabaseSession


async def _database_exists(admin_session, database_name: str) -> bool:
    row = await admin_session.fetchone(
        "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s",
        (database_name,),
    )
    return row is not None


async def _open_admin_session(config: dict[str, object]):
    assert "db" not in config
    connection = await aiomysql.connect(**config)
    cursor = await connection.cursor(aiomysql.DictCursor)
    return _AiomysqlAdminSession(connection, cursor)


async def _close_raw_connection(connection) -> None:
    ensure_closed = getattr(connection, "ensure_closed", None)
    if ensure_closed is not None:
        await ensure_closed()
    else:
        connection.close()


@asynccontextmanager
async def disposable_mysql_database(
    *, on_created=None, on_cleaned=None, initialize_schema: bool = True,
):
    """Create, initialize, yield and unconditionally remove one guarded database."""
    admin_config = test_server_config()
    database_name = new_database_name()
    admin_session = await _open_admin_session(admin_config)
    database_connection = None
    create_attempted = False
    body_error = None
    try:
        assert_disposable_name(database_name)
        create_attempted = True
        await admin_session.execute(
            f"CREATE DATABASE `{database_name}` CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_0900_ai_ci"
        )
        assert_disposable_name(database_name)
        if on_created is not None:
            on_created(database_name)

        if initialize_schema:
            await initialize_database(
                admin_session,
                database_name,
                database_name,
                int(time.time() * 1000),
            )
        database_config = {**admin_config, "db": database_name}
        database_connection = await aiomysql.connect(**database_config)
        test_session = _TestDatabaseSession(database_connection)
        yield DisposableMySQL(
            database_name=database_name,
            connection_config=database_config,
            admin_session=admin_session,
            session=test_session,
        )
    except BaseException as exc:
        body_error = exc
    finally:
        cleanup_failures = []
        if database_connection is not None:
            try:
                await _close_raw_connection(database_connection)
            except BaseException as exc:
                cleanup_failures.append(exc)
        if create_attempted:
            try:
                assert_disposable_name(database_name)
                exists = await _database_exists(admin_session, database_name)
                assert_disposable_name(database_name)
                if exists:
                    assert_disposable_name(database_name)
                    await admin_session.execute(f"DROP DATABASE `{database_name}`")
                    assert_disposable_name(database_name)
                assert_disposable_name(database_name)
                still_exists = await _database_exists(admin_session, database_name)
                assert_disposable_name(database_name)
                if still_exists:
                    raise RuntimeError(
                        f"Disposable database cleanup did not remove {database_name}"
                    )
                if exists and on_cleaned is not None:
                    on_cleaned(database_name)
            except BaseException as exc:
                cleanup_failures.append(exc)
        try:
            await admin_session.close()
        except BaseException as exc:
            cleanup_failures.append(exc)

        cleanup_error = None
        if cleanup_failures:
            cause = (
                cleanup_failures[0]
                if len(cleanup_failures) == 1
                else BaseExceptionGroup(
                    "multiple disposable MySQL cleanup failures",
                    cleanup_failures,
                )
            )
            cleanup_error = RuntimeError(
                f"Disposable MySQL cleanup failed; partial state may remain for "
                f"{database_name}"
            )
            cleanup_error.__cause__ = cause
        if body_error is not None and cleanup_error is not None:
            raise BaseExceptionGroup(
                "Disposable MySQL body and cleanup both failed",
                [body_error, cleanup_error],
            ) from body_error
        if cleanup_error is not None:
            raise cleanup_error
        if body_error is not None:
            raise body_error


def empty_disposable_mysql_database(*, on_created=None, on_cleaned=None):
    """Create a guarded empty database for legacy-reset integration tests."""
    return disposable_mysql_database(
        on_created=on_created,
        on_cleaned=on_cleaned,
        initialize_schema=False,
    )


def transaction_factory_for(connection_config: dict[str, object]):
    """Return an explicit transaction factory bound only to a disposable DB."""
    database_name = connection_config.get("db")
    assert_disposable_name(database_name)
    config = {**connection_config, "autocommit": False}

    @asynccontextmanager
    async def transaction_factory():
        assert_disposable_name(config["db"])
        raw = await aiomysql.connect(**config)
        await raw.begin()
        try:
            yield _TestDatabaseSession(raw)
        except BaseException as body_error:
            try:
                await raw.rollback()
            except BaseException as rollback_error:
                raise BaseExceptionGroup(
                    "transaction body failed and rollback also failed",
                    [body_error, rollback_error],
                ) from body_error
            raise
        else:
            await raw.commit()
        finally:
            raw.close()

    return transaction_factory


async def bootstrap_canon_project(session, project_id: str) -> str:
    """Insert one project with deterministic empty revision/head zero state."""
    bundle = build_projection_bundle(0, ())
    now_ms = 1_720_000_000_000
    await session.execute(
        """INSERT INTO projects
           (id, title, genre, description, target_words, target_chapters,
            status, current_chapter, created_at, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            project_id, "Integration Project", "history", "test only",
            100_000, 100, "drafting", 0, now_ms, now_ms,
        ),
    )
    await session.execute(
        """INSERT INTO canon_revisions
           (id, project_id, revision_number, parent_revision_number,
            idempotency_key, source_type, source_id, content_hash, created_at)
           VALUES (%s,%s,0,0,%s,'bootstrap',NULL,%s,%s)""",
        (
            "00000000-0000-0000-0000-000000000000",
            project_id,
            "0" * 64,
            bundle.content_hash,
            now_ms,
        ),
    )
    await session.execute(
        """INSERT INTO projection_heads
           (project_id, canon_revision_number, projection_revision_number,
            content_hash, updated_at) VALUES (%s,0,0,%s,%s)""",
        (project_id, bundle.content_hash, now_ms),
    )
    await session.execute(
        """INSERT INTO project_planning_heads
           (project_id, revision, planning_revision_id, content_hash, updated_at)
           VALUES (%s,0,NULL,NULL,%s)""",
        (project_id, now_ms),
    )
    return bundle.content_hash
