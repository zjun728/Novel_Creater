from __future__ import annotations

import json

import pytest

from backend.domain.finalization import FinalizationChangeSet, change_set_hash
from backend.domain.json_contracts import canonical_hash
from backend.repositories.finalization import (
    FinalizationDataCorruption,
    FinalizationRepository,
)


HASH_A = "a" * 64
HASH_B = "b" * 64


class CapturingSession:
    def __init__(self, *, rows=(), all_rows=(), execute_results=()):
        self.rows = list(rows)
        self.all_rows = list(all_rows)
        self.execute_results = list(execute_results)
        self.calls = []

    async def fetchone(self, sql, args=None):
        self.calls.append((sql, args))
        return self.rows.pop(0) if self.rows else None

    async def execute(self, sql, args=None):
        self.calls.append((sql, args))
        return self.execute_results.pop(0) if self.execute_results else 1

    async def fetchall(self, sql, args=None):
        self.calls.append((sql, args))
        return self.all_rows.pop(0) if self.all_rows else []


def _compact(sql):
    return " ".join(sql.split())


def _change_set():
    return FinalizationChangeSet.model_validate({
        "schemaVersion": "finalization-changeset-v1",
        "title": "第一章",
        "summary": "摘要",
        "existingEntityIds": [],
        "entities": [],
        "aliases": [],
        "canonEvents": [],
        "storyProgressEvents": [],
        "planningPatches": [],
        "planningSuggestions": [],
    })


@pytest.mark.asyncio
async def test_lock_session_uses_exact_project_owner_and_for_update():
    row = {"id": "session-1", "project_id": "project-1"}
    session = CapturingSession(rows=[row])

    result = await FinalizationRepository().lock_session(
        session, "project-1", "session-1",
    )

    sql, args = session.calls[0]
    assert "WHERE chapter.project_id=%s AND chapter.id=%s FOR UPDATE" in _compact(sql)
    assert args == ("project-1", "session-1")
    assert result == row and result is not row


@pytest.mark.asyncio
async def test_lock_session_includes_current_working_draft_hash():
    session = CapturingSession(rows=[{
        "id": "session-1", "working_draft_content_hash": HASH_A,
    }])

    result = await FinalizationRepository().lock_session(
        session, "project-1", "session-1",
    )

    sql, _ = session.calls[0]
    compact = _compact(sql)
    assert "JOIN working_drafts draft" in compact
    assert "draft.content_hash AS working_draft_content_hash" in compact
    assert result["working_draft_content_hash"] == HASH_A


@pytest.mark.asyncio
async def test_lock_candidate_uses_exact_session_owner_and_decodes_provenance():
    session = CapturingSession(rows=[{
        "id": "candidate-1",
        "project_id": "project-1",
        "chapter_session_id": "session-1",
        "provenance_json": '{"source":"save"}',
    }])

    result = await FinalizationRepository().lock_candidate(
        session, "project-1", "session-1", "candidate-1",
    )

    sql, args = session.calls[0]
    assert "WHERE project_id=%s AND chapter_session_id=%s AND id=%s" in _compact(sql)
    assert "FOR UPDATE" in _compact(sql)
    assert args == ("project-1", "session-1", "candidate-1")
    assert result["provenance"] == {"source": "save"}
    assert "provenance_json" not in result


@pytest.mark.asyncio
async def test_corrupt_candidate_json_fails_closed_without_raw_value():
    sentinel = "RAW_PROSE_SENTINEL"
    session = CapturingSession(rows=[{"provenance_json": sentinel}])

    with pytest.raises(FinalizationDataCorruption) as raised:
        await FinalizationRepository().lock_candidate(
            session, "project-1", "session-1", "candidate-1",
        )

    assert sentinel not in str(raised.value)


@pytest.mark.asyncio
async def test_lock_current_authority_locks_projection_planning_and_outline_heads():
    row = {
        "canon_revision": 1,
        "projection_revision": 1,
        "projection_hash": HASH_A,
        "planning_hash": HASH_B,
        "outline_hash": HASH_A,
    }
    session = CapturingSession(rows=[row])

    result = await FinalizationRepository().lock_current_authority(
        session, "project-1", 2,
    )

    sql, args = session.calls[0]
    compact = _compact(sql)
    assert "FROM projection_heads projection" in compact
    assert "JOIN project_planning_heads planning" in compact
    assert "JOIN project_chapter_outline_heads outline" in compact
    assert "FOR UPDATE" in compact
    assert args == ("project-1", 2)
    assert result == row


@pytest.mark.asyncio
async def test_idempotency_and_active_attempt_queries_are_session_scoped():
    session = CapturingSession(rows=[{"id": "attempt-1"}, {"id": "attempt-2"}])
    repository = FinalizationRepository()

    first = await repository.find_by_idempotency(
        session, "project-1", "session-1", HASH_A,
    )
    second = await repository.find_active(
        session, "project-1", "session-1",
    )

    first_sql, first_args = session.calls[0]
    second_sql, second_args = session.calls[1]
    assert "project_id=%s AND chapter_session_id=%s AND idempotency_key=%s" in _compact(first_sql)
    assert first_args == ("project-1", "session-1", HASH_A)
    assert "active_slot=1" in _compact(second_sql)
    assert "FOR UPDATE" in _compact(second_sql)
    assert second_args == ("project-1", "session-1")
    assert first["id"] == "attempt-1" and second["id"] == "attempt-2"


@pytest.mark.asyncio
async def test_insert_preparing_attempt_serializes_only_canonical_manifest():
    session = CapturingSession()
    row = {
        "id": "attempt-1", "project_id": "project-1",
        "chapter_session_id": "session-1", "draft_candidate_id": "candidate-1",
        "idempotency_key": HASH_A, "request_fingerprint": HASH_B,
        "candidate_hash": HASH_A, "expected_canon_revision": 0,
        "expected_planning_hash": HASH_A, "expected_outline_hash": HASH_B,
        "context_manifest": {"schemaVersion": "finalization-context-v1", "chapter": 1},
        "context_manifest_hash": HASH_A, "created_at": 1, "updated_at": 1,
    }

    await FinalizationRepository().insert_preparing_attempt(session, row)

    sql, args = session.calls[0]
    compact = _compact(sql)
    assert "INSERT INTO finalization_change_sets" in compact
    assert "'preparing'" in compact and "active_slot" in compact
    manifest = args[10]
    assert manifest == '{"chapter":1,"schemaVersion":"finalization-context-v1"}'
    assert "RAW" not in "".join(str(item) for item in args)


@pytest.mark.asyncio
async def test_insert_quality_report_and_revision_use_closed_canonical_json():
    session = CapturingSession()
    repository = FinalizationRepository()
    report = {
        "id": "report-1", "project_id": "project-1",
        "chapter_session_id": "session-1", "draft_candidate_id": "candidate-1",
        "candidate_hash": HASH_A, "expected_canon_revision": 0,
        "expected_planning_hash": HASH_A, "expected_outline_hash": HASH_B,
        "policy_version": "quality-v1", "context_manifest_hash": HASH_A,
        "provider_id": None, "provider_profile_revision": None,
        "model_name_snapshot": None, "status": "quality_not_completed",
        "deterministic_blocks": [{"code": "precheck_incomplete"}],
        "findings": [], "content_hash": HASH_B, "created_at": 1,
    }
    await repository.insert_quality_report(session, report)
    await repository.insert_change_set_revision(session, {
        "id": "revision-1", "project_id": "project-1",
        "change_set_id": "attempt-1", "revision": 1,
        "change_set": _change_set(), "content_hash": HASH_A,
        "source": "extraction", "created_at": 2,
    })

    report_args = session.calls[0][1]
    revision_args = session.calls[1][1]
    assert json.loads(report_args[14]) == [{"code": "precheck_incomplete"}]
    assert json.loads(report_args[15]) == []
    assert json.loads(revision_args[4])["schemaVersion"] == "finalization-changeset-v1"


@pytest.mark.asyncio
async def test_publish_awaiting_author_is_preparing_state_cas_and_checks_row_count():
    repository = FinalizationRepository()
    session = CapturingSession(execute_results=[1])

    assert await repository.publish_awaiting_author(
        session,
        project_id="project-1",
        session_id="session-1",
        change_set_id="attempt-1",
        report_id="report-1",
        extraction_id="extraction-1",
        revision=1,
        revision_hash=HASH_A,
        updated_at=2,
    )
    sql, args = session.calls[0]
    compact = _compact(sql)
    assert "status='awaiting_author'" in compact
    assert (
        "WHERE project_id=%s AND chapter_session_id=%s AND id=%s "
        "AND status='preparing' AND active_slot=1"
    ) in compact
    assert args[-3:] == ("project-1", "session-1", "attempt-1")

    failed = CapturingSession(execute_results=[0])
    assert not await repository.publish_awaiting_author(
        failed,
        project_id="project-1",
        session_id="session-1",
        change_set_id="attempt-1",
        report_id="report-1",
        extraction_id="extraction-1",
        revision=1,
        revision_hash=HASH_A,
        updated_at=2,
    )


@pytest.mark.asyncio
async def test_load_preparation_context_decodes_closed_heads_canon_references_and_bindings():
    head = {
        "canon_revision": 2,
        "projection_hash": HASH_A,
        "planning_revision_id": "planning-2",
        "planning_revision": 2,
        "planning_hash": HASH_B,
        "planning_json": '{"volumes":[]}',
        "outline_revision_id": "outline-1",
        "outline_revision": 1,
        "outline_hash": HASH_A,
        "outline_json": '{"chapterGoal":"进入城中"}',
        "contract_revision": 1,
        "contract_hash": HASH_A,
        "contract_json": '{"genre":"悬疑"}',
        "style_json": '{"tone":"克制"}',
        "bible_revision": 1,
        "bible_hash": HASH_B,
        "bible_json": '{"characters":[]}',
        "policy_version": "quality-v1",
        "creation_contract_id": "contract-1",
    }
    entities = [{
        "id": "entity-1", "entity_type": "person",
        "canonical_name": "林舟",
    }]
    states = [{
        "entity_id": "entity-1", "field_path": "location",
        "payload_json": '{"value":"城门"}', "content_hash": HASH_A,
    }, {
        "entity_id": "entity-1", "field_path": "status",
        "payload_json": '"守城"', "content_hash": HASH_A,
    }]
    references = [{
        "id": "fragment-1", "content": "参考文本", "content_hash": HASH_B,
    }]
    bindings = [{
        "task_key": key, "id": f"provider-{key}",
        "provider_type": "openai-compatible", "model_name": "model",
        "base_url": "https://provider.invalid/v1", "api_key": "SECRET",
        "enabled": 1, "lifecycle_status": "active", "revision": 4,
    } for key in ("audit", "extraction")]
    session = CapturingSession(
        rows=[head], all_rows=[entities, states, references, bindings],
    )

    result = await FinalizationRepository().load_preparation_context(
        session, "project-1", 3,
    )

    assert result["policy_version"] == "quality-v1"
    assert result["canon_context"]["entities"] == entities
    assert result["canon_context"]["currentState"][0]["payload"] == {
        "value": "城门",
    }
    assert result["canon_context"]["currentState"][1]["payload"] == "守城"
    assert result["planning_context"]["content"] == {"volumes": []}
    assert result["outline_context"]["content"]["chapterGoal"] == "进入城中"
    assert result["contract_context"]["style"] == {"tone": "克制"}
    assert result["reference_sources"] == references
    assert result["audit_binding"]["id"] == "provider-audit"
    assert result["extraction_binding"]["id"] == "provider-extraction"
    compact_calls = [_compact(sql) for sql, _ in session.calls]
    assert "FOR UPDATE" in compact_calls[0]
    assert "task_key IN ('audit','extraction')" in compact_calls[4]


@pytest.mark.asyncio
async def test_load_preparation_context_rejects_corrupt_persisted_json_without_raw_value():
    sentinel = "RAW_CONTEXT_SENTINEL"
    session = CapturingSession(rows=[{
        "planning_json": sentinel,
        "outline_json": "{}",
        "contract_json": "{}",
        "style_json": "{}",
        "bible_json": "{}",
    }])

    with pytest.raises(FinalizationDataCorruption) as raised:
        await FinalizationRepository().load_preparation_context(
            session, "project-1", 1,
        )

    assert sentinel not in str(raised.value)


@pytest.mark.asyncio
async def test_advance_project_chapter_updates_public_progress_atomically():
    session = CapturingSession(execute_results=[1])

    assert await FinalizationRepository().advance_project_chapter(
        session,
        project_id="project-1",
        chapter_number=3,
        updated_at=9,
    )

    sql, args = session.calls[0]
    assert "current_chapter=GREATEST(current_chapter,%s)" in _compact(sql)
    assert "status='drafting'" in _compact(sql)
    assert args == (3, 9, "project-1")


@pytest.mark.asyncio
async def test_mark_terminal_releases_active_slot_with_owner_and_state_cas():
    session = CapturingSession(execute_results=[1])

    assert await FinalizationRepository().mark_terminal(
        session,
        project_id="project-1",
        session_id="session-1",
        change_set_id="attempt-1",
        status="failed",
        report_id="report-1",
        updated_at=3,
    )
    sql, args = session.calls[0]
    compact = _compact(sql)
    assert "active_slot=NULL" in compact
    assert "status='preparing' AND active_slot=1" in compact
    assert args[-3:] == ("project-1", "session-1", "attempt-1")

    with pytest.raises(ValueError):
        await FinalizationRepository().mark_terminal(
            CapturingSession(),
            project_id="project-1",
            session_id="session-1",
            change_set_id="attempt-1",
            status="committed",
            report_id=None,
            updated_at=3,
        )


@pytest.mark.asyncio
async def test_review_mutations_are_owner_scoped_revision_hash_cas():
    repository = FinalizationRepository()
    revision_hash = change_set_hash(_change_set())
    session = CapturingSession(
        rows=[{"id": "attempt-1"}, {
            "revision": 1,
            "content_hash": revision_hash,
            "payload_json": json.dumps(
                _change_set().model_dump(by_alias=True, mode="json")
            ),
        }],
        execute_results=[1, 1],
    )

    attempt = await repository.lock_current_attempt(
        session, "project-1", "session-1",
    )
    revision = await repository.lock_change_set_revision(
        session, "project-1", "attempt-1", 1, revision_hash,
    )
    assert await repository.advance_current_revision(
        session,
        project_id="project-1", session_id="session-1",
        change_set_id="attempt-1", expected_revision=1,
        expected_revision_hash=HASH_A, next_revision=2,
        next_revision_hash=HASH_B, updated_at=4,
    )
    assert await repository.confirm_current_revision(
        session,
        project_id="project-1", session_id="session-1",
        change_set_id="attempt-1", revision=2,
        revision_hash=HASH_B, confirmed_at=5,
    )

    assert attempt["id"] == "attempt-1"
    assert revision["change_set"] == _change_set()
    calls = [(_compact(sql), args) for sql, args in session.calls]
    assert "active_slot=1 FOR UPDATE" in calls[0][0]
    assert "revision=%s AND content_hash=%s FOR UPDATE" in calls[1][0]
    assert "confirmed_revision IS NULL" in calls[2][0]
    assert "current_revision=%s AND current_revision_hash=%s" in calls[3][0]
    assert calls[2][1][3:6] == ("project-1", "session-1", "attempt-1")


@pytest.mark.asyncio
async def test_read_current_view_decodes_only_public_report_and_change_set():
    payload = _change_set().model_dump(by_alias=True, mode="json")
    revision_hash = change_set_hash(_change_set())
    report_payload = {
        "status": "completed", "deterministicBlocks": [], "findings": [],
    }
    report_hash = canonical_hash(report_payload)
    session = CapturingSession(rows=[{
        "attempt_id": "attempt-1", "status": "awaiting_author",
        "draft_candidate_id": "candidate-1", "candidate_hash": HASH_A,
        "quality_status": "completed",
        "deterministic_blocks_json": "[]",
        "findings_json": "[]",
        "quality_content_hash": report_hash,
        "current_revision": 1, "current_revision_hash": revision_hash,
        "payload_json": json.dumps(payload), "revision_source": "extraction",
        "confirmed_revision": None, "confirmed_revision_hash": None,
    }])

    result = await FinalizationRepository().read_current_view(
        session, "project-1", "session-1",
    )

    sql, args = session.calls[0]
    compact = _compact(sql)
    assert "ORDER BY attempt.created_at DESC,attempt.id DESC LIMIT 1" in compact
    assert args == ("project-1", "session-1")
    assert result == {
        "attemptId": "attempt-1",
        "status": "awaiting_author",
        "candidateId": "candidate-1",
        "candidateHash": HASH_A,
        "qualityReport": {
            "status": "completed", "deterministicBlocks": [],
            "findings": [], "contentHash": report_hash,
        },
        "changeSet": {
            "revision": 1, "contentHash": revision_hash,
            "source": "extraction", "payload": payload,
        },
        "confirmation": None,
    }


@pytest.mark.asyncio
async def test_read_current_view_rejects_non_closed_change_set_payload():
    session = CapturingSession(rows=[{
        "attempt_id": "attempt-1", "status": "awaiting_author",
        "draft_candidate_id": "candidate-1", "candidate_hash": HASH_A,
        "quality_status": None,
        "current_revision": 1, "current_revision_hash": HASH_A,
        "payload_json": '{"schemaVersion":"finalization-changeset-v1"}',
        "revision_source": "extraction",
        "confirmed_revision": None, "confirmed_revision_hash": None,
    }])

    with pytest.raises(FinalizationDataCorruption):
        await FinalizationRepository().read_current_view(
            session, "project-1", "session-1",
        )


@pytest.mark.asyncio
async def test_read_current_view_rejects_quality_report_hash_mismatch():
    session = CapturingSession(rows=[{
        "attempt_id": "attempt-1", "status": "failed",
        "draft_candidate_id": "candidate-1", "candidate_hash": HASH_A,
        "quality_status": "completed",
        "deterministic_blocks_json": "[]", "findings_json": "[]",
        "quality_content_hash": HASH_A,
        "current_revision": None, "current_revision_hash": None,
        "payload_json": None, "revision_source": None,
        "confirmed_revision": None, "confirmed_revision_hash": None,
    }])

    with pytest.raises(FinalizationDataCorruption):
        await FinalizationRepository().read_current_view(
            session, "project-1", "session-1",
        )


@pytest.mark.asyncio
async def test_commit_receipt_queries_are_locked_and_decode_only_result_json():
    row = {
        "id": "record-1", "chapter_session_id": "session-1",
        "result_payload_json": '{"canonRevision":2}',
    }
    session = CapturingSession(rows=[row, row])
    repository = FinalizationRepository()

    by_key = await repository.lock_commit_by_key(
        session, "project-1", HASH_A,
    )
    by_session = await repository.lock_commit_by_session(
        session, "project-1", "session-1",
    )

    assert by_key["result"] == by_session["result"] == {"canonRevision": 2}
    assert all("FOR UPDATE" in _compact(sql) for sql, _ in session.calls)
    assert session.calls[0][1] == ("project-1", HASH_A)
    assert session.calls[1][1] == ("project-1", "session-1")


@pytest.mark.asyncio
async def test_commit_writes_and_state_transitions_are_exact_owner_scoped():
    session = CapturingSession(execute_results=[1, 1, 1, 1, 1])
    repository = FinalizationRepository()
    record = {
        "id": "record-1", "project_id": "project-1",
        "chapter_session_id": "session-1", "draft_candidate_id": "candidate-1",
        "change_set_id": "attempt-1", "change_set_revision": 2,
        "idempotency_key": HASH_A, "request_fingerprint": HASH_B,
        "candidate_hash": HASH_A, "change_set_hash": HASH_B,
        "expected_canon_revision": 1, "committed_canon_revision": 2,
        "result": {"canonRevision": 2}, "finalized_at": 9,
    }
    chapter = {
        "id": "chapter-1", "project_id": "project-1",
        "chapter_session_id": "session-1", "draft_candidate_id": "candidate-1",
        "finalization_record_id": "record-1", "chapter_num": 1,
        "title": "第一章", "content": "正文", "content_hash": HASH_A,
        "canon_revision": 2, "planning_revision_id": "planning-1",
        "planning_revision": 1, "planning_hash": HASH_A,
        "chapter_outline_revision_id": "outline-1",
        "chapter_outline_revision": 1, "chapter_outline_hash": HASH_B,
        "finalized_at": 9,
    }

    assert await repository.mark_committing(
        session, project_id="project-1", session_id="session-1",
        change_set_id="attempt-1", updated_at=9,
    )
    await repository.insert_finalization_record(session, record)
    await repository.insert_final_chapter(session, chapter)
    assert await repository.finalize_session(
        session, project_id="project-1", session_id="session-1", finalized_at=9,
    )
    assert await repository.mark_committed(
        session, project_id="project-1", session_id="session-1",
        change_set_id="attempt-1", updated_at=9,
    )

    sql = [_compact(item[0]) for item in session.calls]
    assert "status='awaiting_author'" in sql[0]
    assert "INSERT INTO finalization_records" in sql[1]
    assert json.loads(session.calls[1][1][12]) == {"canonRevision": 2}
    assert "INSERT INTO final_chapters" in sql[2]
    assert "status='final'" in sql[3]
    assert "status='committed',active_slot=NULL" in sql[4]
