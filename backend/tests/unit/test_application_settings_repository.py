from __future__ import annotations

import importlib

import pytest


def repository_type():
    try:
        module = importlib.import_module(
            "backend.repositories.application_settings"
        )
    except ModuleNotFoundError as exc:
        pytest.fail(f"application settings repository is missing: {exc}")
    return module.ApplicationSettingsRepository


class RecordingSession:
    def __init__(self):
        self.calls = []
        self.fetchone_result = None
        self.rowcount = 1

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", " ".join(sql.split()), args))
        return self.fetchone_result

    async def execute(self, sql, args=None):
        self.calls.append(("execute", " ".join(sql.split()), args))
        return self.rowcount


@pytest.mark.asyncio
async def test_lock_settings_targets_only_manifest_singleton_without_ensure():
    session = RecordingSession()
    session.fetchone_result = {
        "singleton_id": 1,
        "fallback_provider_id": None,
        "revision": 0,
    }

    await repository_type()().lock_settings(session)

    kind, sql, args = session.calls[0]
    assert kind == "fetchone"
    assert "FROM application_settings" in sql
    assert "singleton_id=1" in sql
    assert sql.endswith("FOR UPDATE")
    assert args is None
    assert "INSERT" not in sql and "CREATE" not in sql


@pytest.mark.asyncio
async def test_fallback_cas_increments_revision_only_from_expected_head():
    session = RecordingSession()

    changed = await repository_type()().compare_and_swap(
        session,
        expected_revision=3,
        fallback_provider_id="provider-1",
        updated_at=99,
    )

    assert changed is True
    kind, sql, args = session.calls[0]
    assert kind == "execute"
    assert "revision=revision+1" in sql
    assert "WHERE singleton_id=1 AND revision=%s" in sql
    assert args == ("provider-1", 99, 3)
