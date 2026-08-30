from __future__ import annotations

import re

import pytest

from backend.repositories.chapter_sessions import ActiveChapterSessionConflict
from backend.repositories.project_overview import ProjectOverviewRepository


class ScriptedSession:
    def __init__(self, *rows, many=()):
        self.rows = list(rows)
        self.many = list(many)
        self.calls: list[tuple[str, tuple[object, ...] | None]] = []

    async def fetchone(self, sql, args=None):
        self.calls.append((sql, args))
        if not self.rows:
            raise AssertionError("unexpected fetchone call")
        return self.rows.pop(0)

    async def fetchall(self, sql, args=None):
        self.calls.append((sql, args))
        if not self.many:
            raise AssertionError("unexpected fetchall call")
        return self.many.pop(0)


class ScriptedChapterSessions:
    def __init__(self, *, active=None, max_final=None, error=None):
        self.active = active
        self.max_final = max_final
        self.error = error
        self.calls: list[tuple[str, object, str]] = []

    async def read_active_session(self, session, project_id):
        self.calls.append(("active", session, project_id))
        if self.error is not None:
            raise self.error
        return self.active

    async def read_max_final_chapter_number(self, session, project_id):
        self.calls.append(("max_final", session, project_id))
        return self.max_final


class ScriptedOutlines:
    def __init__(self, *, head=None, draft=None):
        self.head = head
        self.draft = draft
        self.calls: list[tuple[str, object, str, int]] = []

    async def read_outline_head(self, session, project_id, chapter_number):
        self.calls.append(("head", session, project_id, chapter_number))
        return self.head

    async def read_active_draft(self, session, project_id, chapter_number):
        self.calls.append(("draft", session, project_id, chapter_number))
        return self.draft


def _repository(chapter_sessions, outlines):
    return ProjectOverviewRepository(
        chapter_session_repository=chapter_sessions,
        chapter_outline_repository=outlines,
    )


def _authority_rows(project_id: str, *, aggregate=None, latest=None):
    rows = [
        {
            "id": project_id,
            "title": "夜航档案",
            "genre": "悬疑",
            "description": "失忆的摆渡人寻找被抹去的航线。",
            "target_words": 90_000,
            "target_chapters": 36,
            "status": "active",
            "archived_at": None,
            "created_at": 100,
            "updated_at": 900,
        },
        {
            "selection_revision": 2,
            "selected_at": 200,
            "updated_at": 210,
            "payload_json": '{"title":"夜航种子"}',
        },
        {"revision": 3, "updated_at": 300, "has_draft": 0},
        {"revision": 4, "updated_at": 400, "has_draft": 1},
        {
            "revision": 5,
            "updated_at": 500,
            "content_json": '{"volumes":[]}',
            "has_draft": 1,
        },
        {"canon_revision": 17, "projection_revision": 16},
        aggregate
        or {"chapter_count": 3, "scalar_count": 11_840, "latest_number": 3},
    ]
    if latest is not None:
        rows.append(latest)
    return rows


def _assert_final_chapter_queries_do_not_project_prose(sql_statements):
    for sql in sql_statements:
        compact = " ".join(sql.lower().split())
        if "from final_chapters" not in compact:
            continue
        projection = compact.split("select ", 1)[1].split(
            " from final_chapters",
            1,
        )[0]
        projection_without_scalar_aggregate = projection.replace(
            "char_length(content)",
            "",
        )
        assert not re.search(r"\bcontent\b", projection_without_scalar_aggregate)


@pytest.mark.asyncio
async def test_missing_project_short_circuits_without_later_reads():
    session = ScriptedSession(None)
    chapter_sessions = ScriptedChapterSessions()
    outlines = ScriptedOutlines()

    result = await _repository(chapter_sessions, outlines).read_snapshot(
        session,
        "missing / 项目",
    )

    assert result is None
    assert len(session.calls) == 1
    assert session.calls[0][1] == ("missing / 项目",)
    assert chapter_sessions.calls == []
    assert outlines.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("active", "max_final", "expected_chapter"),
    (
        ({"id": "session-7", "chapter_num": 7, "status": "drafting"}, 3, 7),
        (None, 3, 4),
    ),
)
async def test_full_snapshot_uses_existing_authoritative_chapter_behavior(
    active,
    max_final,
    expected_chapter,
):
    project_id = "project / 一 % _ ' \""
    latest = {
        "latest_number": 3,
        "latest_title": "夜渡",
        "latest_finalized_at": 1_788_067_100_000,
    }
    rows = _authority_rows(project_id, latest=latest)
    rows.insert(5, {"content_json": '{"volumes":[]}'})
    session = ScriptedSession(*rows)
    chapter_sessions = ScriptedChapterSessions(
        active=active,
        max_final=max_final,
    )
    outlines = ScriptedOutlines(
        head={
            "revision": 6,
            "updated_at": 600,
            "content": {"chapterGoal": "越过暗河"},
            "planning_revision_id": "planning-5",
            "planning_revision": 5,
            "planning_hash": "5" * 64,
        },
        draft={"id": "outline-draft-1", "status": "active"},
    )

    snapshot = await _repository(chapter_sessions, outlines).read_snapshot(
        session,
        project_id,
    )

    assert set(snapshot) == {
        "project",
        "selected_seed",
        "contract",
        "bible",
        "planning",
        "outline",
        "session",
        "writer_core",
        "final_aggregate",
        "authoritative_chapter_number",
    }
    assert snapshot["project"]["id"] == project_id
    assert snapshot["session"] == active
    assert snapshot["authoritative_chapter_number"] == expected_chapter
    assert snapshot["outline"] == {
        "revision": 6,
        "updated_at": 600,
        "content_json": {"chapterGoal": "越过暗河"},
        "planning_revision_id": "planning-5",
        "planning_revision": 5,
        "planning_hash": "5" * 64,
        "pinned_planning_content_json": '{"volumes":[]}',
        "has_draft": True,
    }
    assert snapshot["final_aggregate"] == {
        "chapter_count": 3,
        "scalar_count": 11_840,
        "latest_number": 3,
        "latest_title": "夜渡",
        "latest_finalized_at": 1_788_067_100_000,
    }
    assert [call[0] for call in chapter_sessions.calls] == [
        "active",
        "max_final",
    ]
    assert all(call[1] is session for call in chapter_sessions.calls)
    assert all(call[2] == project_id for call in chapter_sessions.calls)
    assert outlines.calls == [
        ("head", session, project_id, expected_chapter),
        ("draft", session, project_id, expected_chapter),
    ]
    assert all(
        args is not None and args[0] == project_id
        for _, args in session.calls
    )


@pytest.mark.asyncio
async def test_multiple_active_session_conflict_propagates_fail_closed():
    project_id = "project-conflict"
    conflict = ActiveChapterSessionConflict("multiple drafting sessions")
    session = ScriptedSession(*_authority_rows(project_id)[:5])
    chapter_sessions = ScriptedChapterSessions(error=conflict)
    outlines = ScriptedOutlines()

    with pytest.raises(ActiveChapterSessionConflict) as raised:
        await _repository(chapter_sessions, outlines).read_snapshot(
            session,
            project_id,
        )

    assert raised.value is conflict
    assert [call[0] for call in chapter_sessions.calls] == ["active"]
    assert outlines.calls == []


@pytest.mark.asyncio
async def test_outline_resolves_its_exact_pinned_planning_not_current_head():
    project_id = "planning-advanced"
    planning_r1_id = "planning-r1"
    planning_r1_hash = "1" * 64
    current_planning = {
        "revision": 2,
        "updated_at": 500,
        "content_json": '{"volumes":[{"id":"volume-r2"}]}',
        "has_draft": 0,
    }
    rows = _authority_rows(
        project_id,
        aggregate={
            "chapter_count": 0,
            "scalar_count": 0,
            "latest_number": None,
        },
    )
    rows[4] = current_planning
    rows.insert(
        5,
        {"content_json": '{"volumes":[{"id":"volume-r1"}]}'},
    )
    session = ScriptedSession(*rows)
    chapter_sessions = ScriptedChapterSessions(max_final=None)
    outlines = ScriptedOutlines(
        head={
            "revision": 1,
            "updated_at": 600,
            "content": {"chapterGoal": "R1 pin"},
            "planning_revision_id": planning_r1_id,
            "planning_revision": 1,
            "planning_hash": planning_r1_hash,
        },
    )

    snapshot = await _repository(chapter_sessions, outlines).read_snapshot(
        session,
        project_id,
    )

    assert snapshot["planning"] == current_planning
    assert snapshot["outline"] == {
        "revision": 1,
        "updated_at": 600,
        "content_json": {"chapterGoal": "R1 pin"},
        "planning_revision_id": planning_r1_id,
        "planning_revision": 1,
        "planning_hash": planning_r1_hash,
        "pinned_planning_content_json": '{"volumes":[{"id":"volume-r1"}]}',
        "has_draft": False,
    }
    pinned_sql, pinned_args = next(
        (sql, args)
        for sql, args in session.calls
        if "FROM planning_revisions pinned" in sql
    )
    compact = " ".join(pinned_sql.split())
    assert "pinned.project_id=%s" in compact
    assert "pinned.id=%s" in compact
    assert "pinned.revision=%s" in compact
    assert "pinned.content_hash=%s" in compact
    assert pinned_args == (
        project_id,
        planning_r1_id,
        1,
        planning_r1_hash,
    )


@pytest.mark.asyncio
async def test_missing_exact_pinned_planning_never_falls_back_to_current_head():
    project_id = "missing-planning-pin"
    planning_r1_hash = "1" * 64
    rows = _authority_rows(
        project_id,
        aggregate={
            "chapter_count": 0,
            "scalar_count": 0,
            "latest_number": None,
        },
    )
    rows.insert(5, None)
    session = ScriptedSession(*rows)
    outlines = ScriptedOutlines(
        head={
            "revision": 1,
            "updated_at": 600,
            "content": {"chapterGoal": "orphaned pin"},
            "planning_revision_id": "planning-r1",
            "planning_revision": 1,
            "planning_hash": planning_r1_hash,
        },
    )

    snapshot = await _repository(
        ScriptedChapterSessions(max_final=None),
        outlines,
    ).read_snapshot(session, project_id)

    assert snapshot["outline"]["planning_revision_id"] == "planning-r1"
    assert snapshot["outline"]["planning_revision"] == 1
    assert snapshot["outline"]["planning_hash"] == planning_r1_hash
    assert snapshot["outline"]["pinned_planning_content_json"] is None


@pytest.mark.asyncio
async def test_default_composition_reuses_scoped_read_only_authority_queries():
    project_id = "default / 组合"
    rows = _authority_rows(
        project_id,
        aggregate={
            "chapter_count": 0,
            "scalar_count": 0,
            "latest_number": None,
        },
    )
    session = ScriptedSession(
        *rows[:5],
        {"chapter_num": None},
        None,
        None,
        *rows[5:],
        many=[()],
    )

    snapshot = await ProjectOverviewRepository().read_snapshot(
        session,
        project_id,
    )

    assert snapshot["authoritative_chapter_number"] == 1
    compact_calls = [(" ".join(sql.split()), args) for sql, args in session.calls]
    active_session_sql, active_session_args = next(
        (sql, args)
        for sql, args in compact_calls
        if "FROM chapter_sessions" in sql
    )
    assert "WHERE project_id=%s AND status='drafting'" in active_session_sql
    assert "LIMIT 2" in active_session_sql
    assert active_session_args == (project_id,)
    max_final_sql, max_final_args = next(
        (sql, args)
        for sql, args in compact_calls
        if "SELECT MAX(chapter_num) AS chapter_num" in sql
    )
    assert "WHERE project_id=%s" in max_final_sql
    assert max_final_args == (project_id,)
    outline_head_sql, outline_head_args = next(
        (sql, args)
        for sql, args in compact_calls
        if "FROM project_chapter_outline_heads head" in sql
    )
    assert (
        "WHERE head.project_id=%s AND head.chapter_num=%s"
        in outline_head_sql
    )
    assert outline_head_args == (project_id, 1)
    outline_draft_sql, outline_draft_args = next(
        (sql, args)
        for sql, args in compact_calls
        if "FROM chapter_outline_drafts" in sql
    )
    assert "status='active' AND active_slot=1" in outline_draft_sql
    assert outline_draft_args == (project_id, 1)
    forbidden = re.compile(
        r"\b(?:insert|update|delete|replace|merge)\b|\bfor\s+update\b|continuity",
        re.IGNORECASE,
    )
    assert all(not forbidden.search(sql) for sql, _ in compact_calls)


@pytest.mark.asyncio
async def test_default_composition_propagates_multiple_active_session_conflict():
    project_id = "default-conflict"
    rows = _authority_rows(project_id)
    session = ScriptedSession(
        *rows[:5],
        many=[
            (
                {
                    "id": "session-1",
                    "project_id": project_id,
                    "chapter_num": 1,
                    "status": "drafting",
                },
                {
                    "id": "session-2",
                    "project_id": project_id,
                    "chapter_num": 2,
                    "status": "drafting",
                },
            )
        ],
    )

    with pytest.raises(ActiveChapterSessionConflict):
        await ProjectOverviewRepository().read_snapshot(session, project_id)

    assert len(session.calls) == 6
    active_sql, active_args = session.calls[-1]
    assert "FROM chapter_sessions" in active_sql
    assert active_args == (project_id,)


@pytest.mark.asyncio
async def test_sql_is_bounded_read_only_and_preserves_immutable_authorities():
    project_id = "project / 一"
    latest = {
        "latest_number": 3,
        "latest_title": "夜渡",
        "latest_finalized_at": 1_788_067_100_000,
    }
    session = ScriptedSession(*_authority_rows(project_id, latest=latest))
    chapter_sessions = ScriptedChapterSessions(max_final=3)
    outlines = ScriptedOutlines()

    snapshot = await _repository(chapter_sessions, outlines).read_snapshot(
        session,
        project_id,
    )

    compact_sql = [" ".join(sql.split()) for sql, _ in session.calls]
    selected_seed_sql = next(
        sql for sql in compact_sql if "FROM project_selected_seeds" in sql
    )
    for identity in (
        "selection.project_id=selected.project_id",
        "selection.selection_revision=selected.selection_revision",
        "selection.seed_id=selected.seed_id",
        "selection.seed_revision_id=selected.seed_revision_id",
        "selection.seed_hash=selected.seed_hash",
        "revision.project_id=selection.project_id",
        "revision.seed_id=selection.seed_id",
        "revision.id=selection.seed_revision_id",
        "revision.content_hash=selection.seed_hash",
    ):
        assert identity in selected_seed_sql
    assert re.search(
        r"SELECT selected\.selection_revision,\s*selected\.selected_at,"
        r"\s*selected\.updated_at,\s*revision\.payload_json",
        selected_seed_sql,
    )

    aggregate_sql = next(
        sql
        for sql in compact_sql
        if "FROM final_chapters" in sql and "COUNT(*)" in sql
    )
    assert (
        "COALESCE(SUM(CHAR_LENGTH(content)),0) AS scalar_count"
        in aggregate_sql
    )
    assert "MAX(chapter_num) AS latest_number" in aggregate_sql
    latest_sql, latest_args = next(
        (sql, args)
        for sql, args in session.calls
        if "FROM final_chapters" in sql and "title AS latest_title" in sql
    )
    assert "WHERE project_id=%s AND chapter_num=%s" in " ".join(
        latest_sql.split()
    )
    assert latest_args == (project_id, 3)
    compact_latest = " ".join(latest_sql.lower().split())
    assert compact_latest.startswith(
        "select chapter_num as latest_number, title as latest_title, "
        "finalized_at as latest_finalized_at from final_chapters"
    )
    _assert_final_chapter_queries_do_not_project_prose(
        sql for sql, _ in session.calls
    )

    forbidden_sql = re.compile(
        r"\b(?:insert|update|delete|replace|merge)\b|\bfor\s+update\b|continuity",
        re.IGNORECASE,
    )
    assert all(not forbidden_sql.search(sql) for sql in compact_sql)
    assert "final_chapters.content" not in " ".join(compact_sql).lower()
    assert not any(
        key in snapshot
        for key in ("next_action", "target_path", "status_label", "continuity")
    )
    assert "payload_json" not in snapshot["project"]
    assert "content" not in snapshot["final_aggregate"]


def test_final_chapter_prose_guard_rejects_unqualified_content_projection():
    with pytest.raises(AssertionError):
        _assert_final_chapter_queries_do_not_project_prose(
            ["SELECT content FROM final_chapters WHERE project_id=%s"]
        )


@pytest.mark.asyncio
async def test_empty_final_aggregate_normalizes_scalars_and_skips_latest_read():
    project_id = "empty-project"
    aggregate = {"chapter_count": 0, "scalar_count": None, "latest_number": None}
    session = ScriptedSession(
        *_authority_rows(project_id, aggregate=aggregate),
    )
    chapter_sessions = ScriptedChapterSessions(max_final=None)
    outlines = ScriptedOutlines()

    snapshot = await _repository(chapter_sessions, outlines).read_snapshot(
        session,
        project_id,
    )

    assert snapshot["final_aggregate"] == {
        "chapter_count": 0,
        "scalar_count": 0,
        "latest_number": None,
        "latest_title": None,
        "latest_finalized_at": None,
    }
    assert snapshot["authoritative_chapter_number"] == 1
    final_sql = [sql for sql, _ in session.calls if "final_chapters" in sql]
    assert len(final_sql) == 1
