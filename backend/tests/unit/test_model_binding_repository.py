from __future__ import annotations

import pytest

from backend.repositories.model_bindings import ModelBindingRepository


class RecordingSession:
    def __init__(self):
        self.calls = []

    async def fetchall(self, sql, args=None):
        self.calls.append((" ".join(sql.split()), args))
        return []


@pytest.mark.asyncio
async def test_lock_current_rows_does_not_lock_provider_rows_early():
    session = RecordingSession()

    await ModelBindingRepository().lock_current_rows(session, "project-1")

    sql, args = session.calls[0]
    assert "FOR UPDATE" in sql
    assert "provider_profiles" not in sql
    assert args == ("project-1",)


@pytest.mark.asyncio
async def test_lock_providers_uses_sorted_ids_and_one_stable_lock_order():
    session = RecordingSession()

    await ModelBindingRepository().lock_providers(
        session, {"provider-z", "provider-a"}
    )

    sql, args = session.calls[0]
    assert "ORDER BY id ASC FOR UPDATE" in sql
    assert args == ("provider-a", "provider-z")
