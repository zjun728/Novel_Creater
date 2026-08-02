from __future__ import annotations

from copy import deepcopy
import hashlib

import pytest

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.repositories.chapter_sessions import ChapterSessionRepository


class CapturingSession:
    def __init__(
        self,
        rows=(),
        all_rows=(),
        execute_result=1,
        execute_results=(),
    ):
        self.calls = []
        self.rows = list(rows)
        self.all_rows = list(all_rows)
        self.execute_result = execute_result
        self.execute_results = list(execute_results)

    async def fetchone(self, sql, args=None):
        self.calls.append((sql, args))
        return self.rows.pop(0) if self.rows else None

    async def fetchall(self, sql, args=None):
        self.calls.append((sql, args))
        return list(self.all_rows)

    async def execute(self, sql, args=None):
        self.calls.append((sql, args))
        if self.execute_results:
            return self.execute_results.pop(0)
        return self.execute_result


@pytest.mark.asyncio
async def test_upsert_working_draft_uses_revision_and_hash_cas():
    row = {
        "id": "draft-1",
        "project_id": "p1",
        "chapter_session_id": "session-1",
        "revision": 3,
        "content": "新正文",
        "content_hash": "b" * 64,
        "source_payload": {"source": "manual"},
        "updated_at": 1,
    }
    session = CapturingSession(execute_result=1)

    assert await ChapterSessionRepository().upsert_working_draft(
        session,
        row,
        expected_revision=2,
        expected_content_hash="a" * 64,
    )

    sql, args = session.calls[-1]
    compact = " ".join(sql.split())
    assert "UPDATE working_drafts" in compact
    assert "AND revision=%s AND content_hash=%s" in compact
    assert args[-2:] == (2, "a" * 64)


def _candidate_row():
    basis = {
        "schemaVersion": "draft-candidate-basis-v1",
        "outlineRevisionId": "outline-revision-1",
        "outlineRevision": 1,
        "outlineHash": "a" * 64,
        "planningRevisionId": "planning-revision-1",
        "planningRevision": 1,
        "planningHash": "b" * 64,
        "canonRevision": 0,
        "projectionRevision": 0,
        "projectionHash": "c" * 64,
    }
    return {
        "id": "candidate-1",
        "project_id": "p1",
        "chapter_session_id": "session-1",
        "working_draft_revision": 2,
        "content": "正文",
        "content_hash": "d" * 64,
        "basis_hash": canonical_hash(basis),
        "provenance": {"source": "save", "workingDraftRevision": 2, **basis},
        "created_at": 1,
    }


def test_candidate_row_retains_internal_basis_hash_only_for_service_validation():
    row = {
        "id": "candidate-1",
        "project_id": "p1",
        "chapter_session_id": "session-1",
        "working_draft_revision": 2,
        "content": "正文",
        "content_hash": "a" * 64,
        "basis_hash": "b" * 64,
        "provenance_json": "{}",
        "created_at": 1,
    }

    candidate = ChapterSessionRepository()._candidate(row)

    assert candidate["basis_hash"] == "b" * 64


@pytest.mark.asyncio
async def test_insert_candidate_reports_new_insert_without_replay_lookup():
    session = CapturingSession(execute_result=1)

    assert await ChapterSessionRepository().insert_candidate(session, _candidate_row())

    assert len(session.calls) == 1
    compact = " ".join(session.calls[0][0].split())
    assert "ON DUPLICATE KEY UPDATE id=id" in compact


@pytest.mark.asyncio
async def test_insert_candidate_accepts_exact_identity_basis_replay():
    row = _candidate_row()
    stored = {
        **row["provenance"],
        "source": "replay",
        "workingDraftRevision": 99,
    }
    session = CapturingSession(
        rows=[
            {
                "basis_hash": row["basis_hash"],
                "provenance_json": canonical_json(stored),
            }
        ],
        execute_result=0,
    )

    assert await ChapterSessionRepository().insert_candidate(session, row)
    lookup_sql, lookup_args = session.calls[1]
    assert lookup_args == (
        row["chapter_session_id"],
        row["content_hash"],
        row["basis_hash"],
    )
    assert "WHERE chapter_session_id=%s AND content_hash=%s AND basis_hash=%s" in " ".join(
        lookup_sql.split()
    )


@pytest.mark.asyncio
async def test_insert_candidate_rejects_mismatched_stored_basis_payload():
    row = _candidate_row()
    stored = deepcopy(row["provenance"])
    stored["outlineRevision"] = True
    session = CapturingSession(
        rows=[
            {
                "basis_hash": row["basis_hash"],
                "provenance_json": canonical_json(stored),
            }
        ],
        execute_result=0,
    )

    assert not await ChapterSessionRepository().insert_candidate(session, row)


@pytest.mark.asyncio
async def test_insert_candidate_rejects_conflict_without_matching_identity():
    session = CapturingSession(rows=[None], execute_result=0)

    assert not await ChapterSessionRepository().insert_candidate(session, _candidate_row())


@pytest.mark.asyncio
async def test_candidate_freeze_request_repository_scopes_replay_to_session():
    session = CapturingSession(rows=[None])

    assert await ChapterSessionRepository().read_candidate_freeze_request(
        session,
        "session-1",
        "idempotency-1",
    ) is None

    sql, args = session.calls[-1]
    assert args == ("session-1", "idempotency-1")
    assert "candidate_freeze_requests" in " ".join(sql.split())


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
        all_rows=[
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
    assert "LIMIT 2" in compact


@pytest.mark.asyncio
async def test_active_session_authority_fails_closed_on_project_wide_split():
    session = CapturingSession(
        all_rows=[
            {
                "id": "session-4",
                "project_id": "p1",
                "chapter_num": 4,
                "status": "drafting",
            },
            {
                "id": "session-5",
                "project_id": "p1",
                "chapter_num": 5,
                "status": "drafting",
            },
        ]
    )

    with pytest.raises(RuntimeError, match="active ChapterSession"):
        await ChapterSessionRepository().read_active_session(session, "p1")


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


def _draft_operation_row():
    return {
        "id": "operation-1",
        "project_id": "project-1",
        "chapter_session_id": "chapter-session-1",
        "operation_type": "generate_new",
        "idempotency_key": "idempotency-1",
        "request_fingerprint": "a" * 64,
        "active_slot": 1,
        "fencing_token": 3,
        "lease_expires_at": 200,
        "base_working_draft_revision": 1,
        "base_working_draft_hash": "b" * 64,
        "input_manifest": {"operationType": "generate_new"},
        "input_manifest_hash": "c" * 64,
        "provider_id": "provider-1",
        "model_name_snapshot": "fake-writer",
        "last_event_sequence": 0,
        "status": "starting",
        "created_at": 100,
        "updated_at": 100,
        "completed_at": None,
        "result_working_draft_revision": None,
        "result_content_hash": None,
        "failure_code": None,
    }


def _stream_write_row(**overrides):
    row = {
        "id": "event-2",
        "project_id": "project-1",
        "chapter_session_id": "chapter-session-1",
        "draft_operation_id": "operation-1",
        "fencing_token": 3,
        "previous_partial_output_hash": "a" * 64,
        "previous_last_event_sequence": 1,
        "sequence_num": 2,
        "partial_output_text": "片段",
        "partial_output_hash": "b" * 64,
        "partial_output_scalars": 2,
        "heartbeat_at": 150,
        "lease_expires_at": 250,
        "updated_at": 150,
        "closed_payload": {
            "text": "片段",
            "partialOutputHash": "b" * 64,
            "partialOutputScalars": 2,
        },
        "created_at": 150,
    }
    row.update(overrides)
    return row


def _cancel_row(*, commit_partial=False, **overrides):
    row = {
        **_stream_write_row(
            id="cancel-event-2",
            closed_payload={"committedPartial": commit_partial},
        ),
        "cancelled_at": 150,
        "completed_at": 150,
        "result_working_draft_revision": None,
        "result_content_hash": None,
    }
    if commit_partial:
        row.update({
            "result_working_draft_revision": 2,
            "result_content_hash": "b" * 64,
            "expected_working_draft_revision": 1,
            "expected_working_draft_hash": "c" * 64,
            "working_draft": {
                "id": "draft-1",
                "project_id": "project-1",
                "chapter_session_id": "chapter-session-1",
                "revision": 2,
                "content": "片段",
                "content_hash": "b" * 64,
                "source_payload": {
                    "source": "draft-operation-cancel",
                    "operationId": "operation-1",
                },
                "updated_at": 150,
            },
            "before_revision": {
                "id": "before-1",
                "project_id": "project-1",
                "chapter_session_id": "chapter-session-1",
                "working_draft_id": "draft-1",
                "working_draft_revision": 1,
                "snapshot_role": "before",
                "replacement_reason": "generate_new",
                "source_operation_id": "operation-1",
                "content": "原文",
                "content_hash": "c" * 64,
                "created_at": 150,
            },
            "after_revision": {
                "id": "after-1",
                "project_id": "project-1",
                "chapter_session_id": "chapter-session-1",
                "working_draft_id": "draft-1",
                "working_draft_revision": 2,
                "snapshot_role": "after",
                "replacement_reason": "generate_new",
                "source_operation_id": "operation-1",
                "content": "片段",
                "content_hash": "b" * 64,
                "created_at": 150,
            },
        })
    row.update(overrides)
    return row


def _assert_exact_stream_guards(sql):
    compact = " ".join(sql.split())
    for predicate in (
        "operation.project_id=%s",
        "operation.chapter_session_id=%s",
        "operation.id=%s",
        "operation.fencing_token=%s",
        "operation.status='running'",
        "operation.active_slot=1",
        "chapter.active_draft_operation_id=operation.id",
        "operation.lease_expires_at>%s",
        "operation.partial_output_hash=%s",
        "operation.last_event_sequence=%s",
    ):
        assert predicate in compact
    return compact


@pytest.mark.asyncio
async def test_operation_owner_reads_lock_exact_session_and_operation_rows():
    session = CapturingSession(
        rows=[
            {"id": "chapter-session-1"},
            {"id": "operation-1"},
            {"id": "operation-1"},
            {"id": "operation-1"},
        ]
    )
    repository = ChapterSessionRepository()

    assert await repository.lock_session_for_operation(
        session, "project-1", "chapter-session-1"
    ) == {"id": "chapter-session-1"}
    assert await repository.read_draft_operation_by_key(
        session, "chapter-session-1", "idempotency-1"
    ) == {"id": "operation-1"}
    assert await repository.read_draft_operation(
        session, "project-1", "chapter-session-1", "operation-1"
    ) == {"id": "operation-1"}
    assert await repository.read_active_draft_operation(
        session, "chapter-session-1"
    ) == {"id": "operation-1"}

    sqls = [" ".join(sql.split()) for sql, _ in session.calls]
    assert all("FOR UPDATE" in sql for sql in sqls)
    assert "project_id=%s AND id=%s" in sqls[0]
    assert "chapter_session_id=%s AND idempotency_key=%s" in sqls[1]
    assert "project_id=%s AND chapter_session_id=%s AND id=%s" in sqls[2]
    assert "chapter_session_id=%s AND active_slot=1" in sqls[3]
    assert all("api_key" not in sql and "base_url" not in sql for sql in sqls)


@pytest.mark.asyncio
async def test_working_draft_operation_lock_uses_exact_owner_and_normalizes_status():
    session = CapturingSession(
        rows=[
            {
                "id": "draft-1",
                "project_id": "project-1",
                "chapter_session_id": "chapter-session-1",
                "revision": 2,
                "content": "正文",
                "content_hash": "a" * 64,
                "source_payload_json": '{"source":"manual"}',
                "updated_at": 120,
                "effective_status": "drafting",
            }
        ]
    )

    result = await ChapterSessionRepository().lock_working_draft_for_operation(
        session, "project-1", "chapter-session-1"
    )

    assert result == {
        "id": "draft-1",
        "project_id": "project-1",
        "chapter_session_id": "chapter-session-1",
        "revision": 2,
        "content": "正文",
        "content_hash": "a" * 64,
        "source_payload": {"source": "manual"},
        "updated_at": 120,
        "effective_status": "drafting",
    }
    sql, args = session.calls[-1]
    compact = " ".join(sql.split())
    assert "JOIN chapter_sessions chapter" in compact
    assert "chapter.status AS effective_status" in compact
    assert "draft.project_id=%s AND draft.chapter_session_id=%s" in compact
    assert "FOR UPDATE" in compact
    assert args == ("project-1", "chapter-session-1")


@pytest.mark.asyncio
async def test_next_operation_fence_locks_owned_session_before_incrementing():
    session = CapturingSession(rows=[{"draft_operation_fencing_token": 3}])

    assert await ChapterSessionRepository().next_draft_operation_fencing_token(
        session, "project-1", "chapter-session-1"
    ) == 4

    lock_sql, lock_args = session.calls[0]
    update_sql, update_args = session.calls[1]
    assert "FOR UPDATE" in " ".join(lock_sql.split())
    assert lock_args == ("project-1", "chapter-session-1")
    assert "draft_operation_fencing_token=%s" in " ".join(update_sql.split())
    assert update_args == (4, "project-1", "chapter-session-1", 3)


@pytest.mark.asyncio
async def test_insert_operation_uses_only_safe_parameterized_columns():
    session = CapturingSession()

    assert await ChapterSessionRepository().insert_draft_operation(
        session, _draft_operation_row()
    )

    sql, args = session.calls[-1]
    compact = " ".join(sql.split())
    assert "draft_operation_attempts" in compact
    assert "%s" in compact
    assert "api_key" not in compact and "base_url" not in compact
    assert args[0:3] == ("operation-1", "project-1", "chapter-session-1")


@pytest.mark.asyncio
async def test_insert_operation_initializes_exact_empty_streaming_state():
    session = CapturingSession()

    assert await ChapterSessionRepository().insert_draft_operation(
        session, _draft_operation_row()
    )

    sql, args = session.calls[-1]
    compact = " ".join(sql.split())
    assert (
        "partial_output_text,partial_output_hash,partial_output_scalars, "
        "heartbeat_at,status"
    ) in compact
    assert args[19:27] == (
        "",
        hashlib.sha256("".encode("utf-8")).hexdigest(),
        0,
        100,
        "starting",
        100,
        100,
        None,
    )


@pytest.mark.asyncio
async def test_delta_atomically_updates_exact_running_owner_and_appends_closed_event():
    row = _stream_write_row()
    session = CapturingSession(execute_results=[1, 1])

    assert await ChapterSessionRepository().append_draft_operation_delta(
        session, row
    )

    assert len(session.calls) == 2
    update_sql, update_args = session.calls[0]
    event_sql, event_args = session.calls[1]
    compact = _assert_exact_stream_guards(update_sql)
    for assignment in (
        "operation.partial_output_text=%s",
        "operation.partial_output_hash=%s",
        "operation.partial_output_scalars=%s",
        "operation.heartbeat_at=%s",
        "operation.lease_expires_at=%s",
        "operation.updated_at=%s",
        "operation.last_event_sequence=%s",
    ):
        assert assignment in compact
    assert update_args == (
        "片段", "b" * 64, 2, 150, 250, 150, 2,
        "project-1", "chapter-session-1", "operation-1", 3,
        150, "a" * 64, 1,
    )
    assert "INSERT INTO draft_operation_events" in " ".join(event_sql.split())
    assert event_args == (
        "event-2", "project-1", "operation-1", 2, "delta",
        canonical_json(row["closed_payload"]), 150,
    )
    assert "provider" not in canonical_json(row["closed_payload"]).lower()


@pytest.mark.asyncio
async def test_heartbeat_keeps_partial_unchanged_and_appends_null_payload_event():
    row = _stream_write_row(id="heartbeat-event-2")
    session = CapturingSession(execute_results=[1, 1])

    assert await ChapterSessionRepository().append_draft_operation_heartbeat(
        session, row
    )

    update_sql, update_args = session.calls[0]
    event_sql, event_args = session.calls[1]
    compact = _assert_exact_stream_guards(update_sql)
    assert "SET operation.heartbeat_at=%s" in compact
    assert "operation.lease_expires_at=%s" in compact
    assert "operation.updated_at=%s" in compact
    assert "operation.last_event_sequence=%s" in compact
    assert "operation.partial_output_text=%s" not in compact
    assert "operation.partial_output_scalars=%s" not in compact
    assert update_args == (
        150, 250, 150, 2, "project-1", "chapter-session-1",
        "operation-1", 3, 150, "a" * 64, 1,
    )
    assert "INSERT INTO draft_operation_events" in " ".join(event_sql.split())
    assert event_args == (
        "heartbeat-event-2", "project-1", "operation-1", 2,
        "heartbeat", None, 150,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "sequence_num", "previous_sequence"),
    (
        ("append_draft_operation_delta", 1, 0),
        ("append_draft_operation_delta", 2048, 2047),
        ("append_draft_operation_heartbeat", 1, 0),
        ("append_draft_operation_heartbeat", 2048, 2047),
        ("append_draft_operation_delta", 3, 1),
    ),
)
async def test_nonterminal_stream_writes_reject_reserved_or_nonconsecutive_sequences(
    method_name, sequence_num, previous_sequence,
):
    session = CapturingSession()
    row = _stream_write_row(
        sequence_num=sequence_num,
        previous_last_event_sequence=previous_sequence,
    )

    assert not await getattr(ChapterSessionRepository(), method_name)(session, row)
    assert session.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name",
    ("append_draft_operation_delta", "append_draft_operation_heartbeat"),
)
async def test_stale_nonterminal_guard_stops_event_insert(method_name):
    session = CapturingSession(execute_result=0)

    assert not await getattr(ChapterSessionRepository(), method_name)(
        session, _stream_write_row()
    )
    assert len(session.calls) == 1
    _assert_exact_stream_guards(session.calls[0][0])


@pytest.mark.asyncio
async def test_delta_event_failure_returns_false_for_caller_transaction_rollback():
    session = CapturingSession(execute_results=[1, 0])

    assert not await ChapterSessionRepository().append_draft_operation_delta(
        session, _stream_write_row()
    )
    assert len(session.calls) == 2
    _assert_exact_stream_guards(session.calls[0][0])
    assert "INSERT INTO draft_operation_events" in " ".join(
        session.calls[1][0].split()
    )


@pytest.mark.asyncio
async def test_cancel_empty_partial_closes_exact_owner_without_draft_writes():
    row = _cancel_row()
    session = CapturingSession(rows=[{"id": "operation-1"}], execute_results=[1, 1])

    assert await ChapterSessionRepository().cancel_draft_operation(session, row)

    assert len(session.calls) == 3
    guard_sql, guard_args = session.calls[0]
    update_sql, update_args = session.calls[1]
    event_sql, event_args = session.calls[2]
    assert "FOR UPDATE" in _assert_exact_stream_guards(guard_sql)
    assert "operation.partial_output_scalars=0" in " ".join(guard_sql.split())
    assert guard_args == (
        "project-1", "chapter-session-1", "operation-1", 3,
        150, "a" * 64, 1,
    )
    compact = _assert_exact_stream_guards(update_sql)
    for assignment in (
        "operation.status='cancelled'",
        "operation.active_slot=NULL",
        "operation.result_working_draft_revision=%s",
        "operation.result_content_hash=%s",
        "operation.failure_code=NULL",
        "operation.cancelled_at=%s",
        "operation.completed_at=%s",
        "chapter.active_draft_operation_id=NULL",
    ):
        assert assignment in compact
    assert update_args == (
        None, None, 150, 150, 150, 2,
        "project-1", "chapter-session-1", "operation-1", 3,
        150, "a" * 64, 1,
    )
    assert "working_drafts" not in compact
    assert "working_draft_revisions" not in compact
    assert "INSERT INTO draft_operation_events" in " ".join(event_sql.split())
    assert event_args == (
        "cancel-event-2", "project-1", "operation-1", 2, "cancelled",
        canonical_json(row["closed_payload"]), 150,
    )


@pytest.mark.asyncio
async def test_cancel_nonempty_partial_recovers_cas_commits_and_then_closes_owner():
    row = _cancel_row(commit_partial=True)
    session = CapturingSession(
        rows=[{"id": "operation-1"}],
        execute_results=[1, 1, 1, 1, 1],
    )

    assert await ChapterSessionRepository().cancel_draft_operation(session, row)

    assert len(session.calls) == 6
    guard_sql, _ = session.calls[0]
    before_sql, before_args = session.calls[1]
    draft_sql, draft_args = session.calls[2]
    after_sql, after_args = session.calls[3]
    update_sql, update_args = session.calls[4]
    event_sql, event_args = session.calls[5]
    assert "FOR UPDATE" in _assert_exact_stream_guards(guard_sql)
    assert "operation.partial_output_scalars>0" in " ".join(guard_sql.split())
    assert "INSERT INTO working_draft_revisions" in " ".join(before_sql.split())
    assert before_args[0] == "before-1"
    assert "UPDATE working_drafts" in " ".join(draft_sql.split())
    assert draft_args[-2:] == (1, "c" * 64)
    assert "INSERT INTO working_draft_revisions" in " ".join(after_sql.split())
    assert after_args[0] == "after-1"
    _assert_exact_stream_guards(update_sql)
    assert update_args == (
        2, "b" * 64, 150, 150, 150, 2,
        "project-1", "chapter-session-1", "operation-1", 3,
        150, "a" * 64, 1,
    )
    assert "INSERT INTO draft_operation_events" in " ".join(event_sql.split())
    assert event_args[4] == "cancelled"
    assert event_args[5] == canonical_json(row["closed_payload"])


@pytest.mark.asyncio
async def test_cancel_stale_guard_stops_all_writes():
    session = CapturingSession(rows=[])

    assert not await ChapterSessionRepository().cancel_draft_operation(
        session, _cancel_row()
    )
    assert len(session.calls) == 1
    assert "FOR UPDATE" in _assert_exact_stream_guards(session.calls[0][0])


@pytest.mark.asyncio
async def test_cancel_nonempty_draft_cas_failure_stops_recovery_and_terminal_writes():
    session = CapturingSession(
        rows=[{"id": "operation-1"}],
        execute_results=[1, 0],
    )

    assert not await ChapterSessionRepository().cancel_draft_operation(
        session, _cancel_row(commit_partial=True)
    )
    assert len(session.calls) == 3
    assert "INSERT INTO working_draft_revisions" in " ".join(
        session.calls[1][0].split()
    )
    assert "UPDATE working_drafts" in " ".join(session.calls[2][0].split())


@pytest.mark.asyncio
async def test_cancel_terminal_guard_failure_stops_event_for_caller_rollback():
    session = CapturingSession(
        rows=[{"id": "operation-1"}],
        execute_results=[1, 1, 1, 0],
    )

    assert not await ChapterSessionRepository().cancel_draft_operation(
        session, _cancel_row(commit_partial=True)
    )
    assert len(session.calls) == 5
    _assert_exact_stream_guards(session.calls[4][0])
    assert all(
        "INSERT INTO draft_operation_events" not in " ".join(sql.split())
        for sql, _ in session.calls
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sequence_num", "previous_sequence"),
    ((1, 0), (2049, 2048), (3, 1)),
)
async def test_cancel_rejects_reserved_or_nonconsecutive_terminal_sequence(
    sequence_num, previous_sequence,
):
    session = CapturingSession()

    assert not await ChapterSessionRepository().cancel_draft_operation(
        session,
        _cancel_row(
            sequence_num=sequence_num,
            previous_last_event_sequence=previous_sequence,
        ),
    )
    assert session.calls == []


@pytest.mark.asyncio
async def test_mark_running_requires_matching_operation_fence_and_session_owner():
    session = CapturingSession()

    assert await ChapterSessionRepository().mark_draft_operation_running(
        session, "operation-1", 3, 120
    )

    sql, args = session.calls[-1]
    compact = " ".join(sql.split())
    assert "UPDATE draft_operation_attempts operation" in compact
    assert "JOIN chapter_sessions chapter" in compact
    assert "operation.id=%s" in compact
    assert "operation.fencing_token=%s" in compact
    assert "chapter.active_draft_operation_id IS NULL" in compact
    assert args == (120, "operation-1", 3)


@pytest.mark.asyncio
async def test_terminal_operation_updates_require_matching_fence_and_clear_same_owner():
    repository = ChapterSessionRepository()
    complete = {
        **_draft_operation_row(),
        "result_working_draft_revision": 2,
        "result_content_hash": "d" * 64,
        "updated_at": 160,
        "completed_at": 160,
    }
    failed = {**_draft_operation_row(), "failure_code": "DraftProviderFailed", "updated_at": 170, "completed_at": 170}
    session = CapturingSession()

    assert await repository.complete_draft_operation(session, complete)
    assert await repository.fail_draft_operation(session, failed)
    assert await repository.expire_draft_operation(session, "operation-1", 3, 180)

    for sql, _ in session.calls:
        compact = " ".join(sql.split())
        assert "JOIN chapter_sessions chapter" in compact
        assert "operation.id=%s" in compact
        assert "operation.fencing_token=%s" in compact
        assert "chapter.active_draft_operation_id=operation.id" in compact
        assert "operation.active_slot=NULL" in compact
    assert session.calls[0][1][-2:] == ("operation-1", 3)
    assert session.calls[1][1][-2:] == ("operation-1", 3)
    assert session.calls[2][1] == (180, 180, "operation-1", 3, 180)


@pytest.mark.asyncio
async def test_expire_operation_requires_elapsed_lease_and_only_its_starting_or_running_owner():
    session = CapturingSession()

    assert await ChapterSessionRepository().expire_draft_operation(
        session, "operation-1", 3, 180
    )

    sql, args = session.calls[-1]
    compact = " ".join(sql.split())
    assert "operation.lease_expires_at<=%s" in compact
    assert (
        "operation.status='starting' AND ( "
        "chapter.active_draft_operation_id IS NULL OR "
        "chapter.active_draft_operation_id=operation.id )"
    ) in compact
    assert (
        "operation.status='running' AND "
        "chapter.active_draft_operation_id=operation.id"
    ) in compact
    assert args == (180, 180, "operation-1", 3, 180)


@pytest.mark.asyncio
async def test_drift_expiry_only_closes_live_running_operation_owned_by_session():
    session = CapturingSession()

    assert await ChapterSessionRepository().expire_draft_operation_for_drift(
        session,
        "project-1",
        "chapter-session-1",
        "operation-1",
        3,
        180,
    )

    sql, args = session.calls[-1]
    compact = " ".join(sql.split())
    assert "UPDATE draft_operation_attempts operation" in compact
    assert "JOIN chapter_sessions chapter" in compact
    assert "operation.project_id=%s" in compact
    assert "operation.chapter_session_id=%s" in compact
    assert "operation.id=%s" in compact
    assert "operation.fencing_token=%s" in compact
    assert "operation.status='running'" in compact
    assert "operation.active_slot=1" in compact
    assert "operation.lease_expires_at>%s" in compact
    assert "chapter.active_draft_operation_id=operation.id" in compact
    assert "operation.active_slot=NULL" in compact
    assert "chapter.active_draft_operation_id=NULL" in compact
    assert args == (
        180,
        180,
        "project-1",
        "chapter-session-1",
        "operation-1",
        3,
        180,
    )


@pytest.mark.asyncio
async def test_event_append_advances_only_expected_sequence_and_lists_bounded_rows():
    row = {
        "id": "event-2",
        "project_id": "project-1",
        "draft_operation_id": "operation-1",
        "sequence_num": 2,
        "event_type": "completed",
        "closed_payload": {"workingDraftRevision": 2, "contentHash": "d" * 64},
        "created_at": 160,
    }
    session = CapturingSession(all_rows=[{"id": "event-2"}], execute_results=[1, 1])
    repository = ChapterSessionRepository()

    assert await repository.insert_draft_operation_event(session, row)
    assert await repository.list_draft_operation_events(session, "operation-1", 1, 20) == [
        {"id": "event-2"}
    ]

    advance_sql, advance_args = session.calls[0]
    insert_sql, insert_args = session.calls[1]
    list_sql, list_args = session.calls[2]
    assert "last_event_sequence=%s" in " ".join(advance_sql.split())
    assert advance_args == (2, "operation-1", "project-1", 1)
    assert "closed_payload_json" in " ".join(insert_sql.split())
    assert "provider" not in " ".join(insert_sql.split())
    assert insert_args[-1] == 160
    compact = " ".join(list_sql.split())
    assert "sequence_num>%s" in compact and "LIMIT %s" in compact
    assert list_args == ("operation-1", 1, 20)


@pytest.mark.asyncio
async def test_event_list_rejects_limits_outside_hard_safe_range():
    session = CapturingSession()
    repository = ChapterSessionRepository()

    with pytest.raises(ValueError, match="1..100"):
        await repository.list_draft_operation_events(session, "operation-1", 0, 0)
    with pytest.raises(ValueError, match="1..100"):
        await repository.list_draft_operation_events(session, "operation-1", 0, 101)

    assert session.calls == []


@pytest.mark.asyncio
async def test_writing_provider_resolution_freezes_streaming_capabilities_privately():
    session = CapturingSession(rows=[{
        "id": "provider-1",
        "stream": 1,
        "supports_streaming": 1,
        "api_key": "private-key",
    }])

    result = await ChapterSessionRepository().resolve_writing_provider(
        session, "project-1"
    )

    sql, args = session.calls[0]
    compact = " ".join(sql.split())
    assert "p.stream" in compact
    assert "p.supports_streaming" in compact
    assert args == ("project-1",)
    assert result["stream"] == 1
    assert result["supports_streaming"] == 1
    assert result["api_key"] == "private-key"


@pytest.mark.asyncio
async def test_recovery_insert_is_append_only_and_accepts_only_exact_content_replay():
    row = {
        "id": "recovery-1",
        "project_id": "project-1",
        "chapter_session_id": "chapter-session-1",
        "working_draft_id": "draft-1",
        "working_draft_revision": 1,
        "snapshot_role": "before",
        "replacement_reason": "generate_new",
        "source_operation_id": "operation-1",
        "content": "before prose",
        "content_hash": "e" * 64,
        "created_at": 160,
    }
    repository = ChapterSessionRepository()
    exact = CapturingSession(rows=[dict(row)], execute_result=0)
    conflicts = [
        {**row, "id": "recovery-other"},
        {**row, "working_draft_id": "draft-other"},
        {**row, "replacement_reason": "other"},
        {**row, "source_operation_id": "operation-other"},
        {**row, "content": "changed prose"},
        {**row, "content_hash": "f" * 64},
        {**row, "created_at": 161},
    ]

    assert await repository.insert_working_draft_revision(exact, row)
    for existing in conflicts:
        conflict = CapturingSession(rows=[existing], execute_result=0)
        assert not await repository.insert_working_draft_revision(conflict, row)
    insert_sql = " ".join(exact.calls[0][0].split())
    assert "ON DUPLICATE KEY UPDATE id=id" in insert_sql
    lookup_sql, lookup_args = exact.calls[1]
    compact = " ".join(lookup_sql.split())
    assert "project_id=%s AND chapter_session_id=%s" in compact
    assert "FOR UPDATE" in compact
    assert lookup_args == ("project-1", "chapter-session-1", 1, "before")
    for field in (
        "id",
        "working_draft_id",
        "replacement_reason",
        "source_operation_id",
        "content",
        "content_hash",
        "created_at",
    ):
        assert field in compact
