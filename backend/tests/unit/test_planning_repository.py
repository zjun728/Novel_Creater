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
    "lock_generation_attempt_by_key",
    "read_generation_attempt_by_key",
    "lock_generation_attempt",
    "read_generation_attempt",
    "lock_active_generation_attempt",
    "insert_generation_attempt",
    "next_fencing_token",
    "supersede_generation_attempt",
    "fail_generation_attempt",
    "succeed_generation_attempt",
    "load_generation_result_into_draft",
    "lock_planning_binding",
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
async def test_planning_head_read_carries_the_complete_immutable_generation():
    session = CapturingSession()

    await PlanningRepository().lock_planning_head(session, "p1")

    _, sql, args = session.calls[-1]
    compact = " ".join(sql.split())
    assert args == ("p1",)
    for column in (
        "revision.selection_revision",
        "revision.seed_id",
        "revision.seed_revision_id",
        "revision.seed_hash",
        "revision.contract_revision",
        "revision.creation_contract_id",
        "revision.creation_hash",
        "revision.style_contract_id",
        "revision.style_hash",
        "revision.bible_revision",
        "revision.bible_revision_id",
        "revision.bible_hash",
    ):
        assert column in compact
    assert "revision.id=head.planning_revision_id" in compact
    assert "revision.content_hash=head.content_hash" in compact


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
async def test_planning_head_advance_compares_the_complete_previous_head():
    session = CapturingSession()
    new_head = {
        "project_id": "p1",
        "revision": 2,
        "planning_revision_id": "planning-2",
        "content_hash": "b" * 64,
        "updated_at": 2,
    }
    previous_head = {
        "revision": 1,
        "planning_revision_id": "planning-1",
        "content_hash": "a" * 64,
    }

    assert await PlanningRepository().advance_head_cas(
        session,
        new_head,
        previous_head,
    )

    _, sql, args = session.calls[-1]
    compact = " ".join(sql.split())
    assert "revision=%s" in compact
    assert "planning_revision_id <=> %s" in compact
    assert "content_hash <=> %s" in compact
    assert args[-4:] == (
        "p1",
        1,
        "planning-1",
        "a" * 64,
    )


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


@pytest.mark.asyncio
async def test_generation_attempt_locks_use_exact_key_operation_and_active_draft():
    session = CapturingSession()
    repository = PlanningRepository()

    await repository.lock_generation_attempt_by_key(session, "p1", "key-1")
    await repository.lock_generation_attempt(session, "p1", "operation-1")
    await repository.lock_active_generation_attempt(session, "draft-1")

    key_sql = " ".join(session.calls[-3][1].split())
    operation_sql = " ".join(session.calls[-2][1].split())
    active_sql = " ".join(session.calls[-1][1].split())
    assert session.calls[-3][2] == ("p1", "key-1")
    assert "project_id=%s AND idempotency_key=%s" in key_sql
    assert key_sql.endswith("FOR UPDATE")
    assert session.calls[-2][2] == ("p1", "operation-1")
    assert "project_id=%s AND operation_id=%s" in operation_sql
    assert operation_sql.endswith("FOR UPDATE")
    assert session.calls[-1][2] == ("draft-1",)
    assert "draft_id=%s" in active_sql
    assert "status='pending'" in active_sql
    assert "active_slot=1" in active_sql
    assert active_sql.endswith("FOR UPDATE")


@pytest.mark.asyncio
async def test_generation_attempt_reads_are_exact_and_never_lock():
    session = CapturingSession()
    repository = PlanningRepository()

    await repository.read_generation_attempt_by_key(
        session, "p1", "key-1"
    )
    await repository.read_generation_attempt(
        session, "p1", "operation-1"
    )

    key_sql = " ".join(session.calls[-2][1].split())
    operation_sql = " ".join(session.calls[-1][1].split())
    assert session.calls[-2][2] == ("p1", "key-1")
    assert "project_id=%s AND idempotency_key=%s" in key_sql
    assert "FOR UPDATE" not in key_sql
    assert session.calls[-1][2] == ("p1", "operation-1")
    assert "project_id=%s AND operation_id=%s" in operation_sql
    assert "FOR UPDATE" not in operation_sql
    assert all(call[0] == "fetchone" for call in session.calls[-2:])


@pytest.mark.asyncio
async def test_planning_binding_lock_reads_exact_task_head_and_provider_runtime():
    session = CapturingSession()

    await PlanningRepository().lock_planning_binding(session, "p1")

    _, sql, args = session.calls[-1]
    compact = " ".join(sql.split())
    assert args == ("p1",)
    assert "FROM project_model_binding_heads head" in compact
    assert "JOIN project_model_binding_items item" in compact
    assert "item.binding_revision_id=head.binding_revision_id" in compact
    assert "item.task_key='planning'" in compact
    assert "LEFT JOIN provider_profiles provider" in compact
    for column in (
        "head.binding_revision_id",
        "head.revision AS binding_revision",
        "head.content_hash AS binding_hash",
        "item.task_key AS binding_task_key",
        "item.resolution_status",
        "item.provider_id",
        "item.model_name_snapshot",
        "provider.id",
        "provider.provider_type",
        "provider.model_name",
        "provider.base_url",
        "provider.api_key",
        "provider.enabled",
        "provider.lifecycle_status",
        "provider.revision",
        "provider.temperature",
        "provider.max_context_tokens",
        "provider.max_output_tokens",
    ):
        assert column in compact
    assert "WHERE head.project_id=%s" in compact
    assert compact.endswith("FOR UPDATE")


@pytest.mark.asyncio
async def test_generation_insert_is_pending_and_uses_only_final_schema_columns():
    session = CapturingSession()
    row = {
        "id": "attempt-1",
        "project_id": "p1",
        "draft_id": "draft-1",
        "operation_id": "operation-1",
        "idempotency_key": "key-1",
        "request_fingerprint": "a" * 64,
        "binding_revision_id": "binding-1",
        "binding_revision": 1,
        "binding_hash": "b" * 64,
        "provider_id": "provider-1",
        "model_name_snapshot": "model-1",
        "fencing_token": 1,
        "lease_expires_at": 20,
        "input_manifest_json": "{}",
        "input_manifest_hash": "c" * 64,
        "created_at": 10,
        "updated_at": 10,
    }

    assert await PlanningRepository().insert_generation_attempt(session, row)

    _, sql, args = session.calls[-1]
    compact = " ".join(sql.split())
    assert "INSERT INTO planning_generation_attempts" in compact
    assert "active_slot" in compact
    assert "'pending'" in compact
    assert "result_content_json" not in compact
    assert "failure_code" not in compact
    assert args == tuple(row.values())


@pytest.mark.asyncio
async def test_next_fencing_token_locks_latest_attempt_and_increments_monotonically():
    class LatestTokenSession(CapturingSession):
        async def fetchone(self, sql, args=None):
            self.calls.append(("fetchone", sql, args))
            return {"fencing_token": 41}

    session = LatestTokenSession()

    token = await PlanningRepository().next_fencing_token(session, "draft-1")

    assert token == 42
    _, sql, args = session.calls[-1]
    compact = " ".join(sql.split())
    assert args == ("draft-1",)
    assert "WHERE draft_id=%s" in compact
    assert "ORDER BY fencing_token DESC" in compact
    assert "LIMIT 1 FOR UPDATE" in compact


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "extra_kwargs", "set_fragments"),
    (
        (
            "supersede_generation_attempt",
            {},
            ("status='superseded'", "active_slot=NULL"),
        ),
        (
            "fail_generation_attempt",
            {"failure_code": "ProviderFailed"},
            ("status='failed'", "failure_code=%s", "active_slot=NULL"),
        ),
        (
            "succeed_generation_attempt",
            {
                "result_content_json": '{"ok":true}',
                "result_content_hash": "d" * 64,
            },
            (
                "status='succeeded'",
                "result_content_json=%s",
                "result_content_hash=%s",
                "active_slot=NULL",
            ),
        ),
    ),
)
async def test_terminal_generation_updates_are_exact_fenced_pending_cas(
    method,
    extra_kwargs,
    set_fragments,
):
    session = CapturingSession()

    changed = await getattr(PlanningRepository(), method)(
        session,
        project_id="p1",
        operation_id="operation-1",
        fencing_token=7,
        updated_at=30,
        **extra_kwargs,
    )

    assert changed
    _, sql, args = session.calls[-1]
    compact = " ".join(sql.split())
    assert all(fragment in compact for fragment in set_fragments)
    assert "WHERE project_id=%s AND operation_id=%s" in compact
    assert "status='pending'" in compact
    assert "active_slot=1" in compact
    assert "fencing_token=%s" in compact
    assert args[-3:] == ("p1", "operation-1", 7)


@pytest.mark.asyncio
async def test_load_generation_result_is_one_exact_attempt_owned_draft_cas():
    class MultiTableSession(CapturingSession):
        async def execute(self, sql, args=None):
            self.calls.append(("execute", sql, args))
            return 2

    session = MultiTableSession()

    changed = await PlanningRepository().load_generation_result_into_draft(
        session,
        project_id="p1",
        draft_id="draft-1",
        expected_revision=2,
        expected_hash="a" * 64,
        operation_id="operation-1",
        fencing_token=7,
        content_json='{"generated":true}',
        content_hash="b" * 64,
        loaded_at=40,
    )

    assert changed
    _, sql, args = session.calls[-1]
    compact = " ".join(sql.split())
    assert "UPDATE planning_drafts draft" in compact
    assert "JOIN planning_generation_attempts attempt" in compact
    assert "attempt.project_id=draft.project_id" in compact
    assert "attempt.draft_id=draft.id" in compact
    assert "draft.source_attempt_id=attempt.id" in compact
    assert "attempt.status='succeeded'" in compact
    assert "attempt.active_slot=NULL" in compact
    assert "attempt.result_content_json=%s" in compact
    assert "attempt.result_content_hash=%s" in compact
    assert "attempt.loaded_draft_revision=%s" in compact
    assert "attempt.loaded_at=%s" in compact
    assert "attempt.updated_at=%s" in compact
    assert "draft.project_id=%s AND draft.id=%s" in compact
    assert "draft.status='active' AND draft.active_slot=1" in compact
    assert "draft.draft_revision=%s AND draft.content_hash=%s" in compact
    assert "attempt.operation_id=%s" in compact
    assert "attempt.status='pending'" in compact
    assert "attempt.active_slot=1" in compact
    assert "attempt.fencing_token=%s" in compact
    assert "attempt.loaded_draft_revision IS NULL" in compact
    assert args[-6:] == (
        "p1",
        "draft-1",
        2,
        "a" * 64,
        "operation-1",
        7,
    )


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
