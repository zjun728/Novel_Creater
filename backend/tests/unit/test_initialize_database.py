from __future__ import annotations

import pytest

from backend.config import LocalMySQLConfigError
from backend import config as backend_config
from backend.schema_manifest import created_table_names, manifest_hash, read_statements
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from backend.scripts.initialize_database import (
    _AiomysqlAdminSession,
    _default_connection_factory,
    InitializationError,
    format_initialization_result,
    initialize_database,
    run_cli,
)


DATABASE_NAME = "writer_core_test"


@pytest.mark.asyncio
async def test_default_factory_ensures_connection_closed_when_cursor_creation_fails(monkeypatch):
    import aiomysql

    cursor_error = RuntimeError("cursor creation failed")

    class Connection:
        close_count = 0

        async def cursor(self, cursor_class):
            assert cursor_class is aiomysql.DictCursor
            raise cursor_error

        async def ensure_closed(self):
            self.close_count += 1

    connection = Connection()

    async def connect(**kwargs):
        return connection

    monkeypatch.setattr(aiomysql, "connect", connect)

    with pytest.raises(RuntimeError) as raised:
        await _default_connection_factory({"password": "test-only"})

    assert raised.value is cursor_error
    assert connection.close_count == 1


@pytest.mark.asyncio
async def test_default_factory_falls_back_to_sync_close_after_cursor_failure(monkeypatch):
    import aiomysql

    class Connection:
        close_count = 0

        async def cursor(self, cursor_class):
            raise RuntimeError("cursor creation failed")

        def close(self):
            self.close_count += 1

    connection = Connection()

    async def connect(**kwargs):
        return connection

    monkeypatch.setattr(aiomysql, "connect", connect)

    with pytest.raises(RuntimeError, match="cursor creation failed"):
        await _default_connection_factory({"password": "test-only"})

    assert connection.close_count == 1


@pytest.mark.asyncio
async def test_default_factory_preserves_cursor_and_connection_close_failures(monkeypatch):
    import aiomysql

    cursor_error = RuntimeError("cursor creation failed")
    close_error = RuntimeError("connection close failed")

    class Connection:
        async def cursor(self, cursor_class):
            raise cursor_error

        async def ensure_closed(self):
            raise close_error

    async def connect(**kwargs):
        return Connection()

    monkeypatch.setattr(aiomysql, "connect", connect)

    with pytest.raises(BaseExceptionGroup) as raised:
        await _default_connection_factory({"password": "test-only"})

    assert raised.value.exceptions == (cursor_error, close_error)


@pytest.mark.asyncio
async def test_cli_default_config_rejects_missing_password_before_connection(monkeypatch):
    called = False

    async def connection_factory(connection_config):
        nonlocal called
        called = True
        raise AssertionError("must not connect")

    monkeypatch.setattr(
        backend_config,
        "MYSQL_CONFIG",
        dict(backend_config.MYSQL_CONFIG, password=None),
    )

    with pytest.raises(LocalMySQLConfigError, match="MYSQL_PASSWORD"):
        await run_cli(
            ["--database", DATABASE_NAME, "--confirm-create", DATABASE_NAME],
            connection_factory=connection_factory,
        )

    assert called is False


@pytest.mark.asyncio
async def test_admin_session_close_is_idempotent_and_waits_for_disconnect():
    class Cursor:
        close_count = 0

        async def close(self):
            self.close_count += 1

    class Connection:
        close_count = 0

        async def ensure_closed(self):
            self.close_count += 1

    cursor = Cursor()
    connection = Connection()
    session = _AiomysqlAdminSession(connection, cursor)

    await session.close()
    await session.close()

    assert cursor.close_count == 1
    assert connection.close_count == 1


@pytest.mark.asyncio
async def test_admin_session_closes_connection_when_cursor_close_fails():
    class Cursor:
        async def close(self):
            raise RuntimeError("cursor close failed")

    class Connection:
        close_count = 0

        async def ensure_closed(self):
            self.close_count += 1

    connection = Connection()
    session = _AiomysqlAdminSession(connection, Cursor())

    with pytest.raises(RuntimeError, match="cursor close failed"):
        await session.close()
    await session.close()

    assert connection.close_count == 1


@pytest.mark.asyncio
async def test_admin_session_combines_close_failures_and_can_retry():
    class Cursor:
        attempts = 0

        async def close(self):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("cursor close failed")

    class Connection:
        attempts = 0

        async def ensure_closed(self):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("connection close failed")

    cursor = Cursor()
    connection = Connection()
    session = _AiomysqlAdminSession(connection, cursor)

    with pytest.raises(BaseExceptionGroup) as raised:
        await session.close()
    assert [str(error) for error in raised.value.exceptions] == [
        "cursor close failed", "connection close failed",
    ]

    await session.close()
    assert cursor.attempts == 2
    assert connection.attempts == 2


class FakeAdminSession:
    def __init__(
        self,
        *,
        database_exists=False,
        tables=(),
        fail_on_sql=None,
        cleanup_error=None,
    ):
        self.database_exists = database_exists
        self.tables = tuple(tables)
        self.fail_on_sql = fail_on_sql
        self.cleanup_error = cleanup_error
        self.calls = []
        self.closed = False

    async def fetchone(self, sql, parameters=None):
        self.calls.append(("fetchone", sql, parameters))
        if "information_schema.SCHEMATA" in sql:
            return {"SCHEMA_NAME": DATABASE_NAME} if self.database_exists else None
        raise AssertionError(f"unexpected fetchone: {sql}")

    async def fetchall(self, sql, parameters=None):
        self.calls.append(("fetchall", sql, parameters))
        if "information_schema.TABLES" in sql:
            return [{"TABLE_NAME": table} for table in self.tables]
        raise AssertionError(f"unexpected fetchall: {sql}")

    async def execute(self, sql, parameters=None):
        self.calls.append(("execute", sql, parameters))
        if sql.startswith("DROP DATABASE") and self.cleanup_error is not None:
            raise self.cleanup_error
        if sql == self.fail_on_sql:
            raise RuntimeError("injected bootstrap failure")

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize("database_name", ["", "with-hyphen", "has space", "quoted`name"])
async def test_invalid_database_name_is_rejected_before_admin_queries(database_name):
    session = FakeAdminSession()
    with pytest.raises(InitializationError, match="database name"):
        await initialize_database(session, database_name, database_name, 123)
    assert session.calls == []


@pytest.mark.asyncio
async def test_mismatched_confirmation_is_rejected_before_admin_queries():
    session = FakeAdminSession()
    with pytest.raises(InitializationError, match="confirmation"):
        await initialize_database(session, DATABASE_NAME, "different", 123)
    assert session.calls == []


@pytest.mark.asyncio
async def test_non_empty_database_is_rejected_without_schema_statements():
    session = FakeAdminSession(database_exists=True, tables=("already_here",))

    with pytest.raises(InitializationError, match="not empty"):
        await initialize_database(session, DATABASE_NAME, DATABASE_NAME, 123)

    executed_sql = [sql for kind, sql, _ in session.calls if kind == "execute"]
    assert executed_sql == []


@pytest.mark.asyncio
async def test_fresh_database_executes_manifest_in_order_and_writes_metadata():
    session = FakeAdminSession(database_exists=False)
    result = await initialize_database(session, DATABASE_NAME, DATABASE_NAME, 1_720_000_000_123)

    executed = [(sql, params) for kind, sql, params in session.calls if kind == "execute"]
    create_database = (
        f"CREATE DATABASE `{DATABASE_NAME}` CHARACTER SET utf8mb4 "
        "COLLATE utf8mb4_0900_ai_ci"
    )
    metadata_insert = (
        "INSERT INTO schema_metadata "
        "(singleton_id, schema_version, manifest_hash, initialized_at) VALUES (1, %s, %s, %s)"
    )
    assert executed == [
        (create_database, None),
        (f"USE `{DATABASE_NAME}`", None),
        *((statement, None) for statement in read_statements()),
        (
            metadata_insert,
            (EXPECTED_SCHEMA_VERSION, manifest_hash(), 1_720_000_000_123),
        ),
    ]
    assert result.database_name == DATABASE_NAME
    assert result.schema_version == EXPECTED_SCHEMA_VERSION
    assert result.manifest_hash == manifest_hash()
    assert result.table_count == len(created_table_names()) == 77


@pytest.mark.asyncio
async def test_failure_after_creating_database_attempts_cleanup_and_reraises():
    failing_statement = read_statements()[2]
    session = FakeAdminSession(database_exists=False, fail_on_sql=failing_statement)

    with pytest.raises(RuntimeError, match="injected bootstrap failure"):
        await initialize_database(session, DATABASE_NAME, DATABASE_NAME, 123)

    executed_sql = [sql for kind, sql, _ in session.calls if kind == "execute"]
    assert executed_sql[-1] == f"DROP DATABASE `{DATABASE_NAME}`"


@pytest.mark.asyncio
async def test_bootstrap_and_cleanup_failures_are_both_reported_as_partial_database():
    failing_statement = read_statements()[2]
    cleanup_error = RuntimeError("injected cleanup failure")
    session = FakeAdminSession(
        database_exists=False,
        fail_on_sql=failing_statement,
        cleanup_error=cleanup_error,
    )

    with pytest.raises(ExceptionGroup) as raised:
        await initialize_database(session, DATABASE_NAME, DATABASE_NAME, 123)

    group = raised.value
    assert DATABASE_NAME in str(group)
    assert "may remain partially initialized" in str(group)
    assert len(group.exceptions) == 2
    assert str(group.exceptions[0]) == "injected bootstrap failure"
    assert group.exceptions[1] is cleanup_error
    executed_sql = [sql for kind, sql, _ in session.calls if kind == "execute"]
    assert executed_sql[-1] == f"DROP DATABASE `{DATABASE_NAME}`"


@pytest.mark.asyncio
async def test_failure_in_existing_empty_database_does_not_drop_it():
    failing_statement = read_statements()[2]
    session = FakeAdminSession(database_exists=True, fail_on_sql=failing_statement)

    with pytest.raises(RuntimeError, match="injected bootstrap failure"):
        await initialize_database(session, DATABASE_NAME, DATABASE_NAME, 123)

    executed_sql = [sql for kind, sql, _ in session.calls if kind == "execute"]
    assert all(not sql.startswith("DROP DATABASE") for sql in executed_sql)


def test_result_output_contains_only_public_bootstrap_fields():
    sentinel_secrets = ("PASSWORD_SENTINEL", "DSN_SENTINEL", "API_KEY_SENTINEL", "BASE_URL_SENTINEL")
    session = FakeAdminSession()
    result = type(
        "Result",
        (),
        {
            "database_name": DATABASE_NAME,
            "schema_version": EXPECTED_SCHEMA_VERSION,
            "manifest_hash": manifest_hash(),
            "table_count": 49,
        },
    )()
    output = format_initialization_result(result)
    assert set(output.splitlines()) == {
        f"database={DATABASE_NAME}",
        f"schema_version={EXPECTED_SCHEMA_VERSION}",
        f"manifest_hash={manifest_hash()}",
        "table_count=49",
    }
    assert all(secret not in output for secret in sentinel_secrets)
    assert session.calls == []


@pytest.mark.asyncio
async def test_cli_uses_injected_connection_config_without_printing_secrets():
    session = FakeAdminSession(database_exists=False)
    captured_config = []
    output = []
    config = {
        "host": "DSN_SENTINEL",
        "password": "PASSWORD_SENTINEL",
        "api_key": "API_KEY_SENTINEL",
        "base_url": "BASE_URL_SENTINEL",
    }

    async def connection_factory(connection_config):
        captured_config.append(connection_config)
        return session

    exit_code = await run_cli(
        ["--database", DATABASE_NAME, "--confirm-create", DATABASE_NAME],
        connection_factory=connection_factory,
        connection_config=config,
        now_ms=lambda: 123,
        output=output.append,
    )

    assert exit_code == 0
    assert captured_config == [config]
    assert session.closed
    rendered = "\n".join(output)
    for secret in config.values():
        assert secret not in rendered
