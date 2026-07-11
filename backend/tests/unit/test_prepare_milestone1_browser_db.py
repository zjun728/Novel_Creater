from pathlib import Path
import subprocess
import sys

import pytest

from backend.scripts.prepare_milestone1_browser_db import (
    BrowserDatabaseSafetyError,
    assert_browser_database_name,
    browser_mysql_config,
    run_cli,
)


DATABASE = "novel_creator_test_0123456789abcdef0123456789abcdef"
TEST_ENVIRONMENT = {
    "TEST_MYSQL_HOST": "127.0.0.1",
    "TEST_MYSQL_PORT": "33060",
    "TEST_MYSQL_USER": "root",
    "TEST_MYSQL_PASSWORD": "test-only",
    "MYSQL_DB": "novel_creator",
    "MYSQL_PASSWORD": "product-must-not-be-used",
}
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "database_name",
    (
        "novel_creator",
        "novel_creator_test_0123456789abcdef0123456789abcde",
        "novel_creator_test_0123456789abcdef0123456789abcdef_suffix",
        "novel_creator_test_0123456789ABCDEF0123456789ABCDEF",
    ),
)
def test_browser_database_guard_rejects_every_non_disposable_name(database_name):
    with pytest.raises(BrowserDatabaseSafetyError, match="disposable"):
        assert_browser_database_name(database_name)


def test_browser_mysql_config_reads_only_explicit_test_variables():
    config = browser_mysql_config(TEST_ENVIRONMENT)

    assert config == {
        "host": "127.0.0.1",
        "port": 33060,
        "user": "root",
        "password": "test-only",
        "charset": "utf8mb4",
        "autocommit": True,
    }
    assert "db" not in config


def test_browser_mysql_config_fails_closed_when_a_test_variable_is_missing():
    environment = dict(TEST_ENVIRONMENT)
    environment.pop("TEST_MYSQL_PASSWORD")

    with pytest.raises(BrowserDatabaseSafetyError, match="TEST_MYSQL_PASSWORD"):
        browser_mysql_config(environment)


def test_cli_help_exits_zero_without_printing_the_failure_banner():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.scripts.prepare_milestone1_browser_db",
            "--help",
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert "M1 browser database operation failed" not in result.stderr


@pytest.mark.asyncio
async def test_cli_rejects_an_unsafe_name_before_opening_a_connection():
    connected = False

    async def connection_factory(config):
        nonlocal connected
        connected = True
        raise AssertionError("must not connect")

    with pytest.raises(BrowserDatabaseSafetyError, match="disposable"):
        await run_cli(
            ["--database", "novel_creator"],
            environment=TEST_ENVIRONMENT,
            connection_factory=connection_factory,
        )

    assert connected is False


class DropSession:
    def __init__(self, *, database_remains=False, close_error=None):
        self.database_remains = database_remains
        self.close_error = close_error
        self.calls = []

    async def execute(self, sql, parameters=None):
        self.calls.append(("execute", sql, parameters))

    async def fetchone(self, sql, parameters=None):
        self.calls.append(("fetchone", sql, parameters))
        if self.database_remains:
            return {"SCHEMA_NAME": DATABASE}
        return None

    async def close(self):
        self.calls.append(("close", None, None))
        if self.close_error is not None:
            raise self.close_error


async def run_drop(session):
    async def connection_factory(config):
        return session

    return await run_cli(
        ["--database", DATABASE, "--drop"],
        environment=TEST_ENVIRONMENT,
        connection_factory=connection_factory,
        output=lambda message: None,
    )


@pytest.mark.asyncio
async def test_drop_verifies_with_a_parameterized_schema_absence_query():
    session = DropSession()

    assert await run_drop(session) == 0

    assert session.calls == [
        ("execute", f"DROP DATABASE IF EXISTS `{DATABASE}`", None),
        (
            "fetchone",
            "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s",
            (DATABASE,),
        ),
        ("close", None, None),
    ]


@pytest.mark.asyncio
async def test_drop_fails_closed_when_the_disposable_schema_remains():
    session = DropSession(database_remains=True)

    with pytest.raises(BrowserDatabaseSafetyError, match="still exists"):
        await run_drop(session)

    assert session.calls[-1] == ("close", None, None)


@pytest.mark.asyncio
async def test_drop_verification_and_close_failures_are_preserved_together():
    close_error = RuntimeError("injected close failure")
    session = DropSession(database_remains=True, close_error=close_error)

    with pytest.raises(BaseExceptionGroup) as raised:
        await run_drop(session)

    assert len(raised.value.exceptions) == 2
    assert isinstance(raised.value.exceptions[0], BrowserDatabaseSafetyError)
    assert "still exists" in str(raised.value.exceptions[0])
    assert raised.value.exceptions[1] is close_error
