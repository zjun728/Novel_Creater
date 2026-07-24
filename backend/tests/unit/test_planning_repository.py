from __future__ import annotations

import inspect

import pytest

from backend.repositories.planning import PlanningRepository


PUBLIC_METHODS = {
    "lock_active_project",
    "read_project_any",
    "read_current_basis",
    "lock_planning_head",
    "read_active_draft",
    "read_draft",
    "insert_draft",
    "update_draft_cas",
    "supersede_draft",
    "find_confirmation",
    "insert_confirmation_pending",
    "insert_revision",
    "advance_head_cas",
    "finish_confirmation",
    "list_revisions",
    "read_projection_head",
    "lock_projection_head",
}


class CapturingSession:
    def __init__(self):
        self.calls: list[tuple[str, str, object]] = []

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", sql, args))
        return None

    async def fetchall(self, sql, args=None):
        self.calls.append(("fetchall", sql, args))
        return ()

    async def execute(self, sql, args=None):
        self.calls.append(("execute", sql, args))
        return 1


def test_repository_exposes_only_the_session_bound_planning_contract():
    methods = {
        name
        for name, member in inspect.getmembers(
            PlanningRepository, predicate=inspect.iscoroutinefunction
        )
        if not name.startswith("_")
    }

    assert methods == PUBLIC_METHODS
    for retired in (
        "lock_project",
        "read_contract_head",
        "read_creation_contract",
        "read_bible_head",
        "read_selected_seed",
        "read_current_plan",
        "insert_initial_plan",
    ):
        assert not hasattr(PlanningRepository, retired)


@pytest.mark.asyncio
async def test_current_basis_is_one_exact_generation_join_without_provider_secret():
    session = CapturingSession()

    await PlanningRepository().read_current_basis(session, "p1")

    _, sql, args = session.calls[-1]
    compact = " ".join(sql.split())
    assert args == ("p1",)
    assert "project_selected_seeds selected" in compact
    assert "project_contract_heads contract_head" in compact
    assert "creation_contracts creation" in compact
    assert "style_contracts style" in compact
    assert "project_bible_heads bible_head" in compact
    assert "creation_bible_revisions bible" in compact
    assert "creation.selection_revision=selected.selection_revision" in compact
    assert "bible.selection_revision=selected.selection_revision" in compact
    assert "bible.creation_hash=contract_head.creation_hash" in compact
    assert "bible.style_hash=contract_head.style_hash" in compact
    forbidden = ("api_key", "base_url", "provider_profiles", "model_name")
    assert all(item not in compact.lower() for item in forbidden)


@pytest.mark.asyncio
async def test_mutation_sql_uses_cas_and_terminal_rows_clear_active_slot():
    session = CapturingSession()
    repository = PlanningRepository()
    row = {
        "project_id": "p1",
        "id": "draft-1",
        "draft_revision": 2,
        "content_json": "{}",
        "content_hash": "b" * 64,
        "status": "active",
        "updated_at": 2,
    }

    assert await repository.update_draft_cas(
        session,
        row,
        expected_revision=1,
        expected_hash="a" * 64,
    )
    _, sql, args = session.calls[-1]
    compact = " ".join(sql.split())
    assert "draft_revision=%s" in compact
    assert "content_hash=%s" in compact
    assert "status='active'" in compact
    assert "active_slot=1" in compact
    assert args[-2:] == (1, "a" * 64)

    terminal = {**row, "status": "confirmed"}
    assert await repository.update_draft_cas(
        session,
        terminal,
        expected_revision=2,
        expected_hash="b" * 64,
    )
    _, terminal_sql, _ = session.calls[-1]
    assert "active_slot=NULL" in " ".join(terminal_sql.split())


@pytest.mark.asyncio
async def test_projection_read_and_lock_are_read_only_head_queries():
    session = CapturingSession()
    repository = PlanningRepository()

    await repository.read_projection_head(session, "p1")
    await repository.lock_projection_head(session, "p1")

    first = " ".join(session.calls[-2][1].split())
    second = " ".join(session.calls[-1][1].split())
    assert "FROM projection_heads" in first
    assert "FOR UPDATE" not in first
    assert "FROM projection_heads" in second
    assert second.endswith("FOR UPDATE")
    assert all(call[0] == "fetchone" for call in session.calls)


def test_phase3a_planning_router_exposes_only_the_revisioned_task7_contract():
    import backend.routers.planning as planning_router

    assert planning_router.router.tags == ["planning"]
    routes = {
        (next(iter(route.methods)), route.path)
        for route in planning_router.router.routes
    }
    assert routes == {
        ("GET", "/projects/{pid}/planning"),
        ("GET", "/projects/{pid}/planning/history"),
        ("POST", "/projects/{pid}/planning/drafts"),
        ("PUT", "/projects/{pid}/planning/drafts/{draft_id}"),
        (
            "POST",
            "/projects/{pid}/planning/drafts/{draft_id}/confirm",
        ),
    }
    assert all("/planning/initial" not in path for _, path in routes)
    source = inspect.getsource(planning_router)
    for retired in (
        "CreateInitialPlan",
        "create_initial_plan",
        "/projects/{pid}/planning/initial",
    ):
        assert retired not in source
