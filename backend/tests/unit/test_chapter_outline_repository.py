from __future__ import annotations

import importlib
import inspect

import pytest

from backend.domain.json_contracts import canonical_json


PUBLIC_METHODS = {
    "lock_project",
    "read_project_any",
    "read_current_authorities",
    "lock_outline_head",
    "read_outline_head",
    "read_active_draft",
    "read_draft",
    "insert_draft",
    "update_draft_cas",
    "supersede_draft",
    "insert_revision",
    "advance_head_cas",
    "find_confirmation",
    "insert_confirmation_pending",
    "finish_confirmation",
    "list_revisions",
    "lock_attempt_by_key",
    "read_attempt_by_key",
    "lock_attempt",
    "read_attempt",
    "lock_active_attempt",
    "read_active_attempt",
    "next_fencing_token",
    "insert_attempt",
    "supersede_attempt",
    "fail_attempt",
    "load_result_into_draft",
}


def _repository_class():
    module = importlib.import_module("backend.repositories.chapter_outlines")
    return module.ChapterOutlineRepository


class CapturingSession:
    def __init__(self, *, rows=(), many=(), changed=1):
        self.calls: list[tuple[str, str, object]] = []
        self.rows = list(rows)
        self.many = list(many)
        self.changed = changed

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", sql, args))
        return self.rows.pop(0) if self.rows else None

    async def fetchall(self, sql, args=None):
        self.calls.append(("fetchall", sql, args))
        return self.many.pop(0) if self.many else ()

    async def execute(self, sql, args=None):
        self.calls.append(("execute", sql, args))
        if isinstance(self.changed, list):
            return self.changed.pop(0)
        return self.changed


def _compact(sql: str) -> str:
    return " ".join(sql.split())


def _draft_row(**overrides):
    row = {
        "id": "draft-1",
        "project_id": "p1",
        "chapter_num": 3,
        "base_head_revision": 0,
        "draft_revision": 1,
        "planning_revision_id": "planning-1",
        "planning_revision": 1,
        "planning_hash": "a" * 64,
        "canon_revision": 0,
        "projection_revision": 0,
        "projection_hash": "b" * 64,
        "content": {"z": 1, "a": "章"},
        "content_hash": "c" * 64,
        "status": "active",
        "created_at": 10,
        "updated_at": 10,
    }
    row.update(overrides)
    return row


def _attempt_row(**overrides):
    row = {
        "id": "attempt-1",
        "project_id": "p1",
        "outline_draft_id": "draft-1",
        "operation_id": "operation-1",
        "idempotency_key": "key-1",
        "request_fingerprint": "d" * 64,
        "binding_revision_id": "binding-1",
        "binding_revision": 1,
        "binding_hash": "e" * 64,
        "provider_id": "provider-1",
        "model_name_snapshot": "model-1",
        "fencing_token": 7,
        "lease_expires_at": 20,
        "input_manifest": {"z": 1, "a": "safe"},
        "input_manifest_hash": "f" * 64,
        "created_at": 10,
        "updated_at": 10,
    }
    row.update(overrides)
    return row


def test_repository_exposes_exact_outline_persistence_contract():
    repository_class = _repository_class()
    methods = {
        name
        for name, member in inspect.getmembers(
            repository_class,
            predicate=inspect.iscoroutinefunction,
        )
        if not name.startswith("_")
    }

    assert methods == PUBLIC_METHODS
    for forbidden in (
        "calculate_chapter_number",
        "mark_attempt_succeeded",
        "succeed_attempt",
        "read_active_session",
        "read_max_final_chapter_number",
    ):
        assert not hasattr(repository_class, forbidden)


@pytest.mark.asyncio
async def test_current_authorities_are_one_normalized_exact_generation_read():
    session = CapturingSession(
        rows=[
            {
                "planning_revision_id": "planning-1",
                "planning_revision": 2,
                "planning_hash": "a" * 64,
                "planning_content_json": b'{"storyBlocks":[],"volumes":[]}',
                "chapter_capacity_policy": (
                    b'{"softCeiling":5000,"targetMax":5000,"targetMin":3000}'
                ),
                "canon_revision": 4,
                "projection_revision": 5,
                "projection_hash": "b" * 64,
            }
        ]
    )

    result = await _repository_class()().read_current_authorities(session, "p1")

    assert result == {
        "planning_revision_id": "planning-1",
        "planning_revision": 2,
        "planning_hash": "a" * 64,
        "chapter_capacity_policy": {
            "softCeiling": 5000,
            "targetMax": 5000,
            "targetMin": 3000,
        },
        "canon_revision": 4,
        "projection_revision": 5,
        "projection_hash": "b" * 64,
        "planning_content": {"storyBlocks": [], "volumes": []},
    }
    _, sql, args = session.calls[-1]
    compact = _compact(sql)
    assert args == ("p1",)
    assert "FROM project_planning_heads planning_head" in compact
    assert "JOIN planning_revisions planning" in compact
    assert "JOIN creation_contracts creation" in compact
    assert "JOIN projection_heads projection" in compact
    assert "planning.id=planning_head.planning_revision_id" in compact
    assert "planning.content_hash=planning_head.content_hash" in compact
    assert "creation.id=planning.creation_contract_id" in compact
    assert "creation.content_hash=planning.creation_hash" in compact
    assert "provider_profiles" not in compact
    assert all(not key.endswith("_json") for key in result)


@pytest.mark.asyncio
async def test_head_and_draft_reads_normalize_json_and_lock_only_lock_methods():
    rows = [
        {
            "project_id": "p1",
            "chapter_num": 3,
            "revision": 1,
            "outline_revision_id": "outline-1",
            "content_hash": "a" * 64,
            "content_json": '{"chapterGoal":"locked"}',
        },
        {
            "project_id": "p1",
            "chapter_num": 3,
            "revision": 1,
            "outline_revision_id": "outline-1",
            "content_hash": "a" * 64,
            "content_json": '{"chapterGoal":"read"}',
        },
        {
            **_draft_row(),
            "content_json": '{"chapterGoal":"active"}',
        },
        {
            **_draft_row(),
            "content_json": b'{"chapterGoal":"exact"}',
        },
    ]
    session = CapturingSession(rows=rows)
    repository = _repository_class()()

    locked = await repository.lock_outline_head(session, "p1", 3)
    read = await repository.read_outline_head(session, "p1", 3)
    active = await repository.read_active_draft(session, "p1", 3)
    exact = await repository.read_draft(session, "p1", 3, "draft-1")

    assert locked["content"] == {"chapterGoal": "locked"}
    assert read["content"] == {"chapterGoal": "read"}
    assert active["content"] == {"chapterGoal": "active"}
    assert exact["content"] == {"chapterGoal": "exact"}
    assert all("content_json" not in row for row in (locked, read, active, exact))
    sql = [_compact(call[1]) for call in session.calls]
    assert sql[0].endswith("FOR UPDATE")
    assert "FOR UPDATE" not in sql[1]
    assert "status='active' AND active_slot=1" in sql[2]
    assert session.calls[2][2] == ("p1", 3)
    assert sql[3].endswith("FOR UPDATE")
    assert session.calls[3][2] == ("p1", 3, "draft-1")


@pytest.mark.asyncio
async def test_draft_writes_use_canonical_json_and_exact_revision_hash_cas():
    session = CapturingSession()
    repository = _repository_class()()
    row = _draft_row()

    assert await repository.insert_draft(session, row)
    _, insert_sql, insert_args = session.calls[-1]
    assert "INSERT INTO chapter_outline_drafts" in _compact(insert_sql)
    assert canonical_json(row["content"]) in insert_args
    assert "'active'" in _compact(insert_sql)
    assert "active_slot" in _compact(insert_sql)

    saved = {
        **row,
        "draft_revision": 2,
        "content": {"b": 2, "a": 1},
        "content_hash": "d" * 64,
        "updated_at": 20,
    }
    assert await repository.update_draft_cas(
        session,
        saved,
        expected_revision=1,
        expected_hash="c" * 64,
    )
    _, update_sql, update_args = session.calls[-1]
    compact = _compact(update_sql)
    assert "WHERE project_id=%s AND chapter_num=%s AND id=%s" in compact
    assert "status='active' AND active_slot=1" in compact
    assert "draft_revision=%s AND content_hash=%s" in compact
    assert canonical_json(saved["content"]) in update_args
    assert update_args[-2:] == (1, "c" * 64)

    terminal = {**saved, "status": "confirmed"}
    assert await repository.update_draft_cas(
        session,
        terminal,
        expected_revision=2,
        expected_hash="d" * 64,
    )
    assert "active_slot=NULL" in _compact(session.calls[-1][1])

    assert await repository.supersede_draft(session, "p1", 3, "draft-1")
    _, supersede_sql, supersede_args = session.calls[-1]
    compact = _compact(supersede_sql)
    assert "status='superseded'" in compact
    assert "active_slot=NULL" in compact
    assert "status='active' AND active_slot=1" in compact
    assert supersede_args == ("p1", 3, "draft-1")


@pytest.mark.asyncio
async def test_revision_confirmation_and_history_use_only_final_outline_tables():
    revision = {
        "id": "outline-1",
        "project_id": "p1",
        "chapter_num": 3,
        "revision": 1,
        "parent_revision": 0,
        "planning_revision_id": "planning-1",
        "planning_revision": 2,
        "planning_hash": "a" * 64,
        "canon_revision": 4,
        "projection_revision": 5,
        "projection_hash": "b" * 64,
        "content": {"z": 1, "a": "outline"},
        "content_hash": "c" * 64,
        "created_at": 30,
    }
    confirmation = {
        "id": "confirmation-1",
        "project_id": "p1",
        "chapter_num": 3,
        "chapter_outline_draft_id": "draft-1",
        "draft_revision": 2,
        "draft_hash": "d" * 64,
        "expected_head_revision": 0,
        "planning_revision_id": "planning-1",
        "planning_revision": 2,
        "planning_hash": "a" * 64,
        "canon_revision": 4,
        "projection_revision": 5,
        "projection_hash": "b" * 64,
        "idempotency_key": "confirm-key",
        "request_fingerprint": "e" * 64,
        "created_at": 30,
    }
    session = CapturingSession(
        rows=[{"id": "confirmation-1"}],
        many=[
            (
                {
                    **revision,
                    "content_json": '{"chapterGoal":"history"}',
                },
            )
        ],
    )
    repository = _repository_class()()

    assert await repository.insert_revision(session, revision)
    assert canonical_json(revision["content"]) in session.calls[-1][2]
    found = await repository.find_confirmation(
        session, "p1", 3, "confirm-key"
    )
    assert found == {"id": "confirmation-1"}
    assert _compact(session.calls[-1][1]).endswith("FOR UPDATE")
    assert session.calls[-1][2] == ("p1", 3, "confirm-key")
    assert await repository.insert_confirmation_pending(session, confirmation)

    finished = {
        **confirmation,
        "status": "succeeded",
        "outline_revision_id": "outline-1",
        "result_revision": 1,
        "result_hash": "c" * 64,
        "public_error_code": None,
        "completed_at": 40,
    }
    assert await repository.finish_confirmation(session, finished)
    finish = _compact(session.calls[-1][1])
    assert "status=%s" in finish
    assert "status='pending'" in finish
    assert "request_fingerprint=%s" in finish

    history = await repository.list_revisions(session, "p1", 3)
    assert history[0]["content"] == {"chapterGoal": "history"}
    assert "content_json" not in history[0]
    assert "ORDER BY revision DESC" in _compact(session.calls[-1][1])


@pytest.mark.asyncio
async def test_head_advance_is_revision_cas_and_can_insert_first_head():
    repository = _repository_class()()
    row = {
        "project_id": "p1",
        "chapter_num": 3,
        "revision": 1,
        "outline_revision_id": "outline-1",
        "content_hash": "a" * 64,
        "updated_at": 30,
    }
    existing = CapturingSession(changed=1)
    assert await repository.advance_head_cas(existing, row, 0)
    assert "revision=%s" in _compact(existing.calls[-1][1])
    assert existing.calls[-1][2][-3:] == ("p1", 3, 0)

    missing = CapturingSession(changed=[0, 1])
    assert await repository.advance_head_cas(missing, row, 0)
    assert len(missing.calls) == 2
    assert "INSERT INTO project_chapter_outline_heads" in _compact(
        missing.calls[-1][1]
    )

    stale = CapturingSession(changed=0)
    assert not await repository.advance_head_cas(stale, row, 2)
    assert len(stale.calls) == 1


@pytest.mark.asyncio
async def test_attempt_reads_are_exact_normalized_and_lock_only_lock_methods():
    raw = {
        **_attempt_row(),
        "input_manifest_json": '{"safe":true}',
        "result_content_json": '{"chapterGoal":"generated"}',
    }
    session = CapturingSession(rows=[dict(raw) for _ in range(6)])
    repository = _repository_class()()

    results = (
        await repository.lock_attempt_by_key(session, "p1", "key-1"),
        await repository.read_attempt_by_key(session, "p1", "key-1"),
        await repository.lock_attempt(session, "p1", "operation-1"),
        await repository.read_attempt(session, "p1", "operation-1"),
        await repository.lock_active_attempt(session, "draft-1"),
        await repository.read_active_attempt(session, "draft-1"),
    )

    for result in results:
        assert result["input_manifest"] == {"safe": True}
        assert result["result_content"] == {"chapterGoal": "generated"}
        assert "input_manifest_json" not in result
        assert "result_content_json" not in result
    sql = [_compact(call[1]) for call in session.calls]
    assert sql[0].endswith("FOR UPDATE")
    assert "FOR UPDATE" not in sql[1]
    assert sql[2].endswith("FOR UPDATE")
    assert "FOR UPDATE" not in sql[3]
    assert "outline_draft_id=%s" in sql[4]
    assert "status='pending' AND active_slot=1" in sql[4]
    assert sql[4].endswith("FOR UPDATE")
    assert "outline_draft_id=%s" in sql[5]
    assert "status='pending' AND active_slot=1" in sql[5]
    assert "FOR UPDATE" not in sql[5]


@pytest.mark.asyncio
async def test_attempt_insert_canonicalizes_manifest_and_token_is_monotonic():
    session = CapturingSession(rows=[{"fencing_token": 41}])
    repository = _repository_class()()
    row = _attempt_row()

    assert await repository.insert_attempt(session, row)
    _, sql, args = session.calls[-1]
    compact = _compact(sql)
    assert "INSERT INTO chapter_outline_generation_attempts" in compact
    assert "'pending'" in compact
    assert canonical_json(row["input_manifest"]) in args
    assert "result_content_json" not in compact

    assert await repository.next_fencing_token(session, "draft-1") == 42
    _, token_sql, token_args = session.calls[-1]
    compact = _compact(token_sql)
    assert token_args == ("draft-1",)
    assert "WHERE outline_draft_id=%s" in compact
    assert "ORDER BY fencing_token DESC" in compact
    assert "LIMIT 1 FOR UPDATE" in compact


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "extra_args", "set_fragments"),
    (
        (
            "supersede_attempt",
            (),
            ("status='superseded'", "active_slot=NULL"),
        ),
        (
            "fail_attempt",
            ("ProviderFailed",),
            ("status='failed'", "failure_code=%s", "active_slot=NULL"),
        ),
    ),
)
async def test_terminal_attempt_updates_are_exact_fenced_pending_cas(
    method,
    extra_args,
    set_fragments,
):
    session = CapturingSession()

    changed = await getattr(_repository_class()(), method)(
        session,
        "p1",
        "operation-1",
        7,
        *extra_args,
    )

    assert changed
    _, sql, args = session.calls[-1]
    compact = _compact(sql)
    assert all(fragment in compact for fragment in set_fragments)
    assert "WHERE project_id=%s AND operation_id=%s" in compact
    assert "status='pending'" in compact
    assert "active_slot=1" in compact
    assert "fencing_token=%s" in compact
    assert args[-3:] == ("p1", "operation-1", 7)


@pytest.mark.asyncio
async def test_load_result_is_one_joined_exact_draft_and_attempt_cas():
    session = CapturingSession(changed=2)
    content = {"z": 2, "chapterGoal": "generated"}

    changed = await _repository_class()().load_result_into_draft(
        session,
        "draft-1",
        2,
        "a" * 64,
        "operation-1",
        7,
        content,
        "b" * 64,
        40,
    )

    assert changed
    _, sql, args = session.calls[-1]
    compact = _compact(sql)
    assert "UPDATE chapter_outline_drafts draft" in compact
    assert "JOIN chapter_outline_generation_attempts attempt" in compact
    assert "attempt.project_id=draft.project_id" in compact
    assert "attempt.outline_draft_id=draft.id" in compact
    assert "draft.source_attempt_id=attempt.id" in compact
    assert "attempt.status='succeeded'" in compact
    assert "attempt.active_slot=NULL" in compact
    assert "attempt.result_content_json=%s" in compact
    assert "attempt.result_content_hash=%s" in compact
    assert "attempt.loaded_outline_draft_revision=%s" in compact
    assert "attempt.loaded_at=%s" in compact
    assert "draft.id=%s" in compact
    assert "draft.status='active' AND draft.active_slot=1" in compact
    assert "draft.draft_revision=%s AND draft.content_hash=%s" in compact
    assert "attempt.operation_id=%s" in compact
    assert "attempt.status='pending'" in compact
    assert "attempt.active_slot=1" in compact
    assert "attempt.fencing_token=%s" in compact
    assert canonical_json(content) in args
    assert args[-5:] == (
        "draft-1",
        2,
        "a" * 64,
        "operation-1",
        7,
    )
