from __future__ import annotations

import pytest

from backend.repositories import model_bindings, projects, seeds
from backend.repositories import project_lifecycle


def compact(sql: str) -> str:
    return " ".join(sql.split())


class RecordingSession:
    _UNSET = object()

    def __init__(
        self,
        *,
        row=_UNSET,
        rows=None,
        execute_result: int = 1,
    ):
        self.row = (
            {"id": "p1", "status": "drafting", "archived_at": None}
            if row is self._UNSET
            else row
        )
        self.rows = [] if rows is None else rows
        self.execute_result = execute_result
        self.calls = []

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", compact(sql), args))
        return self.row

    async def fetchall(self, sql, args=None):
        self.calls.append(("fetchall", compact(sql), args))
        return self.rows

    async def execute(self, sql, args=None):
        self.calls.append(("execute", compact(sql), args))
        return self.execute_result


@pytest.mark.asyncio
async def test_shared_project_lifecycle_exposes_active_and_any_status_reads_and_locks():
    session = RecordingSession()

    assert await project_lifecycle.read_active_project(session, "p1") == session.row
    assert await project_lifecycle.lock_active_project(session, "p1") == session.row
    assert await project_lifecycle.read_project(session, "p1") == session.row
    assert await project_lifecycle.lock_project(session, "p1") == session.row

    assert session.calls == [
        (
            "fetchone",
            "SELECT * FROM projects WHERE id=%s AND archived_at IS NULL",
            ("p1",),
        ),
        (
            "fetchone",
            "SELECT * FROM projects WHERE id=%s FOR UPDATE",
            ("p1",),
        ),
        ("fetchone", "SELECT * FROM projects WHERE id=%s", ("p1",)),
        ("fetchone", "SELECT * FROM projects WHERE id=%s FOR UPDATE", ("p1",)),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "repository", "method", "guard_name"),
    [
        (
            projects,
            projects.ProjectRepository(),
            "lock_active_project",
            "lock_active_project",
        ),
        (seeds, seeds.SeedRepository(), "lock_project", "lock_active_project"),
        (
            model_bindings,
            model_bindings.ModelBindingRepository(),
            "read_project",
            "read_project",
        ),
        (
            model_bindings,
            model_bindings.ModelBindingRepository(),
            "lock_project",
            "lock_active_project",
        ),
    ],
)
async def test_ordinary_project_mutations_keep_using_active_boundary(
    monkeypatch, module, repository, method, guard_name
):
    calls = []

    async def guard(session, project_id):
        calls.append((session, project_id))
        return {"id": project_id}

    monkeypatch.setattr(module, guard_name, guard)
    session = object()

    assert await getattr(repository, method)(session, "p1") == {"id": "p1"}
    assert calls == [(session, "p1")]


@pytest.mark.asyncio
async def test_seed_read_project_delegates_to_shared_any_status_read(
    monkeypatch,
):
    calls = []

    async def read(session, project_id):
        calls.append((session, project_id))
        return {"id": project_id, "archived_at": 123}

    monkeypatch.setattr(seeds, "read_any_project", read)
    repository = seeds.SeedRepository()
    session = object()

    assert (await repository.read_project(session, "p1"))["archived_at"] == 123
    assert calls == [(session, "p1")]


@pytest.mark.asyncio
async def test_binding_inheritance_candidates_exclude_archived_projects():
    session = RecordingSession()

    await model_bindings.ModelBindingRepository().lock_inheritance_candidates(
        session, "p1"
    )

    call = session.calls[0]
    assert call[0] == "fetchall"
    assert "p.id<>%s AND p.archived_at IS NULL" in call[1]
    assert "ORDER BY p.created_at DESC, p.id DESC" in call[1]
    assert call[2] == ("p1",)


@pytest.mark.asyncio
async def test_active_and_archived_lists_are_disjoint_and_stably_ordered():
    session = RecordingSession(rows=[])
    repository = projects.ProjectRepository()

    assert await repository.list_active(session) == []
    assert await repository.list_archived(session) == []

    assert session.calls == [
        (
            "fetchall",
            "SELECT * FROM projects WHERE archived_at IS NULL "
            "ORDER BY updated_at DESC, id DESC",
            None,
        ),
        (
            "fetchall",
            "SELECT * FROM projects WHERE archived_at IS NOT NULL "
            "ORDER BY archived_at DESC, id DESC",
            None,
        ),
    ]


@pytest.mark.asyncio
async def test_any_status_reads_and_locks_delegate_to_shared_helpers(
    monkeypatch,
):
    calls = []

    async def read(session, project_id):
        calls.append(("read", session, project_id))
        return {"id": project_id, "archived_at": 123}

    async def lock(session, project_id):
        calls.append(("lock", session, project_id))
        return {"id": project_id, "archived_at": 123}

    monkeypatch.setattr(projects, "read_project", read)
    monkeypatch.setattr(projects, "lock_project", lock)
    repository = projects.ProjectRepository()
    session = object()

    assert (await repository.get_any(session, "p1"))["archived_at"] == 123
    assert (await repository.lock_any(session, "p1"))["archived_at"] == 123
    assert calls == [
        ("read", session, "p1"),
        ("lock", session, "p1"),
    ]


@pytest.mark.asyncio
async def test_unfinished_operation_checks_story_batches_and_active_planning_lease():
    session = RecordingSession(row={"present": 1})

    assert (
        await projects.ProjectRepository(clock=lambda: 123).has_unfinished_operation(
            session, "p1"
        )
        is True
    )

    assert session.calls == [
        (
            "fetchone",
            "SELECT 1 AS present WHERE EXISTS "
            "( SELECT 1 FROM story_engine_batches WHERE project_id=%s "
            "AND status IN ('reserved','running','outcome_unknown') ) "
            "OR EXISTS ( SELECT 1 FROM planning_generation_attempts "
            "WHERE project_id=%s AND status='pending' AND active_slot=1 "
            "AND lease_expires_at>%s ) LIMIT 1",
            ("p1", "p1", 123),
        )
    ]


@pytest.mark.asyncio
async def test_unfinished_operation_returns_false_without_matching_batch():
    session = RecordingSession(row=None)

    assert (
        await projects.ProjectRepository().has_unfinished_operation(
            session, "p1"
        )
        is False
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("affected, expected", [(1, True), (0, False), (2, False)])
async def test_archive_is_revision_guarded_compare_and_swap(affected, expected):
    session = RecordingSession(execute_result=affected)

    changed = await projects.ProjectRepository(clock=lambda: 123).archive(
        session, "p1", 4
    )

    assert changed is expected
    assert session.calls == [
        (
            "execute",
            "UPDATE projects SET archived_at=%s, "
            "lifecycle_revision=lifecycle_revision+1, updated_at=%s "
            "WHERE id=%s AND archived_at IS NULL AND lifecycle_revision=%s",
            (123, 123, "p1", 4),
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("affected, expected", [(1, True), (0, False), (2, False)])
async def test_restore_clears_archive_marker_with_revision_compare_and_swap(
    affected, expected
):
    session = RecordingSession(execute_result=affected)

    changed = await projects.ProjectRepository(clock=lambda: 456).restore(
        session, "p1", 7
    )

    assert changed is expected
    assert session.calls == [
        (
            "execute",
            "UPDATE projects SET archived_at=NULL, "
            "lifecycle_revision=lifecycle_revision+1, updated_at=%s "
            "WHERE id=%s AND archived_at IS NOT NULL AND lifecycle_revision=%s",
            (456, "p1", 7),
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("affected, expected", [(1, True), (0, False), (2, False)])
async def test_permanent_delete_guards_then_deletes_owned_graph_in_order(
    affected, expected
):
    session = RecordingSession(execute_result=affected)

    changed = await projects.ProjectRepository().permanently_delete(
        session, "p1", 9
    )

    assert changed is expected
    assert session.calls[0] == (
        "fetchone",
        "SELECT id FROM projects WHERE id=%s AND archived_at IS NOT NULL "
        "AND lifecycle_revision=%s AND NOT EXISTS ( SELECT 1 FROM "
        "topic_project_handoffs WHERE project_id=%s ) FOR UPDATE",
        ("p1", 9, "p1"),
    )
    assert "topic_project_handoffs" not in projects._PROJECT_OWNED_DELETE_ORDER
    direct_deletes = session.calls[1:1 + len(projects._PROJECT_OWNED_DELETE_ORDER)]
    assert direct_deletes == [
        (
            "execute",
            f"DELETE FROM {table_name} WHERE project_id=%s",
            ("p1",),
        )
        for table_name in projects._PROJECT_OWNED_DELETE_ORDER
    ]
    assert session.calls[-6:] == [
        (
            "execute",
            "DELETE heads FROM creative_seed_heads heads "
            "JOIN creative_seeds seeds ON seeds.id=heads.seed_id "
            "WHERE seeds.project_id=%s",
            ("p1",),
        ),
        (
            "execute",
            "DELETE FROM creative_seed_revisions WHERE project_id=%s",
            ("p1",),
        ),
        (
            "execute",
            "DELETE FROM creative_seeds WHERE project_id=%s",
            ("p1",),
        ),
        (
            "execute",
            "DELETE FROM project_model_binding_heads WHERE project_id=%s",
            ("p1",),
        ),
        (
            "execute",
            "DELETE FROM project_model_binding_revisions WHERE project_id=%s",
            ("p1",),
        ),
        (
            "execute",
            "DELETE FROM projects WHERE id=%s AND archived_at IS NOT NULL "
            "AND lifecycle_revision=%s",
            ("p1", 9),
        )
    ]


@pytest.mark.asyncio
async def test_permanent_delete_guard_failure_does_not_touch_owned_rows():
    session = RecordingSession(row=None)

    assert await projects.ProjectRepository().permanently_delete(
        session, "p1", 9
    ) is False
    assert session.calls == [(
        "fetchone",
        "SELECT id FROM projects WHERE id=%s AND archived_at IS NOT NULL "
        "AND lifecycle_revision=%s AND NOT EXISTS ( SELECT 1 FROM "
        "topic_project_handoffs WHERE project_id=%s ) FOR UPDATE",
        ("p1", 9, "p1"),
    )]


@pytest.mark.asyncio
@pytest.mark.parametrize("affected, expected", [(1, True), (0, False), (2, False)])
async def test_rename_changes_only_title_on_an_active_project(affected, expected):
    session = RecordingSession(execute_result=affected)

    changed = await projects.ProjectRepository(clock=lambda: 789).rename(
        session, "p1", "Changed"
    )

    assert changed is expected
    assert session.calls == [
        (
            "execute",
            "UPDATE projects SET title=%s, updated_at=%s "
            "WHERE id=%s AND archived_at IS NULL",
            ("Changed", 789, "p1"),
        )
    ]
