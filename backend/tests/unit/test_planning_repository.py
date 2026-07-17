from __future__ import annotations

import pytest


class CapturingSession:
    def __init__(self):
        self.sql = ""
        self.args = None

    async def fetchone(self, sql, args=None):
        self.sql = sql
        self.args = args
        return None


@pytest.mark.asyncio
async def test_selected_seed_read_uses_formal_project_selected_seeds_table():
    from backend.repositories.planning import PlanningRepository

    session = CapturingSession()
    await PlanningRepository().read_selected_seed(session, "p1")

    assert "project_selected_seeds" in session.sql
    assert "creative_seed_revisions" in session.sql
    assert "selected_seed_state" not in session.sql
    assert session.args == ("p1",)
