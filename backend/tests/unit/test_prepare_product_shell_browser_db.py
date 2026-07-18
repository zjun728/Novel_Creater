import re

import pytest

import backend.scripts.prepare_product_shell_browser_db as browser_db


DATABASE = "novel_creator_test_0123456789abcdef0123456789abcdef"
TEST_ENVIRONMENT = {
    "TEST_MYSQL_HOST": "127.0.0.1",
    "TEST_MYSQL_PORT": "33060",
    "TEST_MYSQL_USER": "root",
    "TEST_MYSQL_PASSWORD": "test-only",
    "MYSQL_HOST": "product-host",
    "MYSQL_PORT": "3306",
    "MYSQL_USER": "product-user",
    "MYSQL_PASSWORD": "product-secret",
    "MYSQL_DB": "novel_creator",
}


@pytest.mark.parametrize(
    "database_name",
    (
        "novel_creator",
        "novel_creater",
        "novel_creator_test_0123456789abcdef0123456789abcde",
        "novel_creator_test_0123456789ABCDEF0123456789ABCDEF",
        "novel_creator_test_0123456789abcdef0123456789abcdef_suffix",
        "../novel_creator_test_0123456789abcdef0123456789abcdef",
    ),
)
def test_database_guard_rejects_product_and_non_disposable_names(database_name):
    with pytest.raises(browser_db.BrowserDatabaseSafetyError, match="disposable"):
        browser_db.assert_browser_database_name(database_name)


def test_mysql_config_uses_only_explicit_test_authority():
    assert browser_db.browser_mysql_config(TEST_ENVIRONMENT) == {
        "host": "127.0.0.1",
        "port": 33060,
        "user": "root",
        "password": "test-only",
        "charset": "utf8mb4",
        "autocommit": True,
    }


@pytest.mark.parametrize(
    "missing_name",
    (
        "TEST_MYSQL_HOST",
        "TEST_MYSQL_PORT",
        "TEST_MYSQL_USER",
        "TEST_MYSQL_PASSWORD",
    ),
)
def test_mysql_config_fails_closed_when_test_authority_is_incomplete(missing_name):
    environment = dict(TEST_ENVIRONMENT)
    environment.pop(missing_name)

    with pytest.raises(browser_db.BrowserDatabaseSafetyError, match=missing_name):
        browser_db.browser_mysql_config(environment)


class RecordingSession:
    def __init__(self, remaining_database=None):
        self.calls = []
        self.remaining_database = remaining_database

    async def execute(self, sql, parameters=None):
        self.calls.append(("execute", " ".join(sql.split()), parameters))

    async def fetchone(self, sql, parameters=None):
        self.calls.append(("fetchone", " ".join(sql.split()), parameters))
        return self.remaining_database

    async def close(self):
        self.calls.append(("close", "", None))


@pytest.mark.asyncio
async def test_prepare_initializes_only_the_current_schema_without_seeding(monkeypatch):
    session = RecordingSession()
    initialized = []

    async def fake_initialize(active_session, database, confirmation, now_ms):
        initialized.append((active_session, database, confirmation, now_ms))

    monkeypatch.setattr(browser_db, "initialize_database", fake_initialize)
    outputs = []

    async def connection_factory(config):
        assert config == {
            "host": "127.0.0.1",
            "port": 33060,
            "user": "root",
            "password": "test-only",
            "charset": "utf8mb4",
            "autocommit": True,
        }
        assert "db" not in config
        return session

    result = await browser_db.run_cli(
        ["--database", DATABASE],
        environment=TEST_ENVIRONMENT,
        connection_factory=connection_factory,
        now_ms=lambda: 1_720_000_000_000,
        output=outputs.append,
    )

    assert result == 0
    assert initialized == [(session, DATABASE, DATABASE, 1_720_000_000_000)]
    assert outputs == ["action=prepared"]
    assert session.calls == [("close", "", None)]
    source = browser_db.__file__
    assert re.search(r"prepare_product_shell_browser_db\.py$", source)


@pytest.mark.asyncio
async def test_invalid_name_is_rejected_before_opening_an_admin_connection():
    connection_calls = 0

    async def connection_factory(_config):
        nonlocal connection_calls
        connection_calls += 1
        return RecordingSession()

    with pytest.raises(browser_db.BrowserDatabaseSafetyError, match="disposable"):
        await browser_db.run_cli(
            ["--database", "novel_creator"],
            environment=TEST_ENVIRONMENT,
            connection_factory=connection_factory,
        )

    assert connection_calls == 0


@pytest.mark.asyncio
async def test_drop_removes_only_the_named_database_and_verifies_absence():
    session = RecordingSession()

    async def connection_factory(_config):
        return session

    await browser_db.run_cli(
        ["--database", DATABASE, "--drop"],
        environment=TEST_ENVIRONMENT,
        connection_factory=connection_factory,
        output=lambda _message: None,
    )

    assert session.calls == [
        ("execute", f"DROP DATABASE IF EXISTS `{DATABASE}`", None),
        (
            "fetchone",
            "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s",
            (DATABASE,),
        ),
        ("close", "", None),
    ]


@pytest.mark.asyncio
async def test_drop_fails_if_the_named_database_still_exists_and_closes():
    session = RecordingSession(remaining_database={"SCHEMA_NAME": DATABASE})

    async def connection_factory(_config):
        return session

    with pytest.raises(browser_db.BrowserDatabaseSafetyError, match="still exists"):
        await browser_db.run_cli(
            ["--database", DATABASE, "--drop"],
            environment=TEST_ENVIRONMENT,
            connection_factory=connection_factory,
            output=lambda _message: None,
        )

    assert session.calls[-1] == ("close", "", None)


@pytest.mark.asyncio
async def test_prepare_failure_attempts_only_owned_database_cleanup(monkeypatch):
    session = RecordingSession()

    async def fail_initialize(_session, _database, _confirmation, _now_ms):
        raise RuntimeError("synthetic schema failure")

    monkeypatch.setattr(browser_db, "initialize_database", fail_initialize)

    async def connection_factory(_config):
        return session

    with pytest.raises(RuntimeError, match="synthetic schema failure"):
        await browser_db.run_cli(
            ["--database", DATABASE],
            environment=TEST_ENVIRONMENT,
            connection_factory=connection_factory,
            output=lambda _message: None,
        )

    sql = [call[1] for call in session.calls if call[0] == "execute"]
    assert sql == [f"DROP DATABASE IF EXISTS `{DATABASE}`"]
    assert session.calls[-1] == ("close", "", None)
