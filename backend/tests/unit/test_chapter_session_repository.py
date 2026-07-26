from __future__ import annotations

import pytest

from backend.repositories.chapter_sessions import ChapterSessionRepository


class CapturingSession:
    def __init__(self, rows=()):
        self.calls = []
        self.rows = list(rows)

    async def fetchone(self, sql, args=None):
        self.calls.append((sql, args))
        return self.rows.pop(0) if self.rows else None


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


@pytest.mark.asyncio
async def test_active_session_authority_reads_across_all_project_chapters():
    session = CapturingSession(
        rows=[
            {
                "id": "session-4",
                "project_id": "p1",
                "chapter_num": 4,
                "status": "drafting",
            }
        ]
    )

    result = await ChapterSessionRepository().read_active_session(session, "p1")

    assert result == {
        "id": "session-4",
        "project_id": "p1",
        "chapter_num": 4,
        "status": "drafting",
    }
    sql, args = session.calls[-1]
    compact = " ".join(sql.split())
    assert args == ("p1",)
    assert "FROM chapter_sessions" in compact
    assert "project_id=%s" in compact
    assert "status='drafting'" in compact
    assert "chapter_num=%s" not in compact
    assert "LIMIT 1" in compact


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row", "expected"),
    (({"chapter_num": 7}, 7), ({"chapter_num": None}, None), (None, None)),
)
async def test_max_final_chapter_authority_returns_normalized_scalar(row, expected):
    session = CapturingSession(rows=[row])

    result = await ChapterSessionRepository().read_max_final_chapter_number(
        session,
        "p1",
    )

    assert result == expected
    sql, args = session.calls[-1]
    compact = " ".join(sql.split())
    assert args == ("p1",)
    assert "SELECT MAX(chapter_num) AS chapter_num" in compact
    assert "FROM final_chapters" in compact
    assert "project_id=%s" in compact
