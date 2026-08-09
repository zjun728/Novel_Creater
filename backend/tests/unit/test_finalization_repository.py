from __future__ import annotations

import json

import pytest

from backend.domain.finalization import FinalizationChangeSet
from backend.repositories.finalization import (
    FinalizationDataCorruption,
    FinalizationRepository,
)


HASH_A = "a" * 64
HASH_B = "b" * 64


class CapturingSession:
    def __init__(self, *, rows=(), execute_results=()):
        self.rows = list(rows)
        self.execute_results = list(execute_results)
        self.calls = []

    async def fetchone(self, sql, args=None):
        self.calls.append((sql, args))
        return self.rows.pop(0) if self.rows else None

    async def execute(self, sql, args=None):
        self.calls.append((sql, args))
        return self.execute_results.pop(0) if self.execute_results else 1


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
    assert "WHERE project_id=%s AND id=%s FOR UPDATE" in _compact(sql)
    assert args == ("project-1", "session-1")
    assert result == row and result is not row


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
