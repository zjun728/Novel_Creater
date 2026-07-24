from __future__ import annotations

import pytest

from backend.repositories.chapter_sessions import ChapterSessionRepository


class CapturingSession:
    def __init__(self):
        self.calls = []

    async def fetchone(self, sql, args=None):
        self.calls.append((sql, args))
        return None


@pytest.mark.asyncio
async def test_current_outline_reads_exact_planning_and_current_generation_pins():
    session = CapturingSession()

    assert (
        await ChapterSessionRepository().read_current_outline(session, "p1", 3)
        is None
    )

    sql, args = session.calls[-1]
    compact = " ".join(sql.split())
    assert args == ("p1", 3)
    assert (
        "current_head.planning_revision_id AS current_planning_revision_id"
        in compact
    )
    for field in (
        "selection_revision",
        "seed_id",
        "seed_revision_id",
        "seed_hash",
        "contract_revision",
        "creation_contract_id",
        "creation_hash",
        "style_contract_id",
        "style_hash",
        "bible_revision",
        "bible_revision_id",
        "bible_hash",
    ):
        assert f"planning_{field}" in compact
        assert f"current_{field}" in compact
    assert "planning.id=outline.planning_revision_id" in compact
    assert "planning.revision=outline.planning_revision" in compact
    assert "planning.content_hash=outline.planning_hash" in compact
    assert "creation.selection_revision=selected.selection_revision" in compact
    assert "bible.contract_revision=contract_head.revision" in compact
