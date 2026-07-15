from hashlib import sha256
import json
import re

import pytest

import backend.scripts.prepare_milestone2_browser_db as browser_db


DATABASE = "novel_creator_test_0123456789abcdef0123456789abcdef"
TEST_ENVIRONMENT = {
    "TEST_MYSQL_HOST": "127.0.0.1",
    "TEST_MYSQL_PORT": "33060",
    "TEST_MYSQL_USER": "root",
    "TEST_MYSQL_PASSWORD": "test-only",
    "MYSQL_HOST": "product-host",
    "MYSQL_DB": "novel_creator",
    "MYSQL_PASSWORD": "product-secret",
}


@pytest.mark.parametrize(
    "database_name",
    (
        "novel_creator",
        "novel_creator_test_0123456789abcdef0123456789abcde",
        "novel_creator_test_0123456789ABCDEF0123456789ABCDEF",
        "novel_creator_test_0123456789abcdef0123456789abcdef_suffix",
    ),
)
def test_database_guard_rejects_every_non_disposable_name(database_name):
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


@pytest.mark.parametrize("scenario", ("foundation", "manual", "recovery", "settings"))
def test_cli_scenario_is_a_closed_set(scenario):
    parser = browser_db._argument_parser()
    assert parser.parse_args(
        ["--database", DATABASE, "--scenario", scenario]
    ).scenario == scenario

    with pytest.raises(SystemExit):
        parser.parse_args(
            ["--database", DATABASE, "--scenario", f"{scenario}-extra"]
        )


class RecordingSession:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, parameters=None):
        self.calls.append(("execute", " ".join(sql.split()), parameters))

    async def fetchone(self, sql, parameters=None):
        self.calls.append(("fetchone", " ".join(sql.split()), parameters))
        return None

    async def close(self):
        self.calls.append(("close", "", None))


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ("foundation", "manual", "recovery", "settings"))
async def test_prepare_initializes_v11_and_seeds_only_scenario_preconditions(
    monkeypatch, scenario
):
    session = RecordingSession()
    initialized = []

    async def fake_initialize(active_session, database, confirmation, now_ms):
        initialized.append((active_session, database, confirmation, now_ms))

    monkeypatch.setattr(browser_db, "initialize_database", fake_initialize)

    async def connection_factory(config):
        assert config["host"] == TEST_ENVIRONMENT["TEST_MYSQL_HOST"]
        assert "db" not in config
        return session

    assert await browser_db.run_cli(
        ["--database", DATABASE, "--scenario", scenario],
        environment=TEST_ENVIRONMENT,
        connection_factory=connection_factory,
        now_ms=lambda: 1_720_000_000_000,
        output=lambda _message: None,
    ) == 0

    assert initialized == [(session, DATABASE, DATABASE, 1_720_000_000_000)]
    sql = "\n".join(call[1] for call in session.calls)
    assert "INSERT INTO projects" in sql
    assert "INSERT INTO project_contract_heads" in sql
    assert "INSERT INTO creation_contracts" not in sql
    assert "INSERT INTO style_contracts" not in sql
    assert "INSERT INTO contract_confirmation_requests" not in sql
    batch_calls = [call for call in session.calls if "INSERT INTO story_engine_batches" in call[1]]
    assert len(batch_calls) == (2 if scenario == "recovery" else 0)

    if scenario == "recovery":
        flattened = [value for call in batch_calls for value in (call[2] or ())]
        assert "running" in flattened
        assert "reserved" in flattened
        assert browser_db.RECOVERY_ATTEMPT_ID in flattened
        assert browser_db.RECOVERY_LEASE_EXPIRES_AT < 1_720_000_000_000
        assert browser_db.RECOVERY_LEASE_EXPIRES_AT in flattened
        assert all("succeeded" not in (call[2] or ()) for call in batch_calls)
        for _, _, parameters in batch_calls:
            assert re.fullmatch(r"[a-f0-9]{64}", parameters[10])
            request = json.loads(parameters[11])
            assert request["fixture"] == "synthetic-recovery-precondition"
            assert parameters[12] == sha256(parameters[11].encode("utf-8")).hexdigest()


@pytest.mark.asyncio
async def test_drop_verifies_database_absence_and_always_closes():
    session = RecordingSession()

    async def connection_factory(_config):
        return session

    await browser_db.run_cli(
        ["--database", DATABASE, "--scenario", "manual", "--drop"],
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
