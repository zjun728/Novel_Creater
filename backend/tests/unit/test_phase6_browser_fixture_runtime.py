"""Standalone fixture CLIs own one runtime lifespan; reused prepare functions do not."""

import importlib
import sys
from pathlib import Path

import pytest

from backend.config import (
    RuntimeConfigurationError, current_runtime_configuration, load_runtime_configuration,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["6a", "6b", "6c"])
@pytest.mark.parametrize("verify", [False, True])
@pytest.mark.parametrize("failure", [None, "fixture", "close"])
async def test_fixture_cli_installs_runtime_before_work_and_clears_after_pool_close(
    monkeypatch, phase, verify, failure,
):
    fixture = importlib.import_module(f"backend.scripts.prepare_phase{phase}_browser_db")
    database = "novel_creator_test_" + "a" * 32
    snapshot = load_runtime_configuration(environment={
        "MYSQL_HOST": "127.0.0.1", "MYSQL_PORT": "3306",
        "MYSQL_USER": "fixture-test", "MYSQL_PASSWORD": "fixture-only",
        "MYSQL_DB": database, "MARKET_SCHEDULER_ENABLED": "false",
    }, config_path=Path(__file__).with_suffix(".absent.json"))
    events = []
    monkeypatch.setattr(fixture, "load_runtime_configuration", lambda: snapshot)
    monkeypatch.setattr(sys, "argv", ["fixture", "--database", database] + (
        ["--verify-postconditions"] if verify else []
    ))
    monkeypatch.delenv("BROWSER_RESULT_PATH", raising=False)

    async def work(selected_database):
        assert selected_database == database
        assert current_runtime_configuration() is snapshot
        events.append("verify" if verify else "prepare")
        if failure == "fixture":
            raise RuntimeError("fixture failure")

    async def unexpected(_database):
        pytest.fail("CLI dispatched the wrong fixture action")

    async def close():
        assert current_runtime_configuration() is snapshot
        events.append("close")
        if failure == "close":
            raise RuntimeError("close failure")

    monkeypatch.setattr(fixture, "verify_postconditions", work if verify else unexpected)
    monkeypatch.setattr(fixture, "prepare", unexpected if verify else work)
    monkeypatch.setattr(fixture, "close_pool", close)
    if failure:
        with pytest.raises(RuntimeError, match=f"{failure} failure"):
            await fixture.main()
    else:
        await fixture.main()
    assert events == ["verify" if verify else "prepare", "close"]
    with pytest.raises(RuntimeConfigurationError):
        current_runtime_configuration()
