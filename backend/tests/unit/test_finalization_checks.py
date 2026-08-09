from __future__ import annotations

from hashlib import sha256

import pytest

from backend.domain.finalization import FinalizationAuthority
from backend.services.finalization_checks import run_finalization_prechecks


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
PROJECT_ID = "project-1"
SESSION_ID = "session-1"
CANDIDATE_ID = "candidate-1"


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _fixture(content="这是一个完整候选正文，主角走进山门并作出选择。"):
    candidate_hash = _hash_text(content)
    basis = {
        "schemaVersion": "draft-candidate-basis-v1",
        "outlineRevisionId": "outline-revision-1",
        "outlineRevision": 1,
        "outlineHash": HASH_C,
        "planningRevisionId": "planning-revision-1",
        "planningRevision": 1,
        "planningHash": HASH_B,
        "canonRevision": 0,
        "projectionRevision": 0,
        "projectionHash": HASH_A,
    }
    from backend.domain.json_contracts import canonical_hash

    authority = FinalizationAuthority.model_validate({
        "projectId": PROJECT_ID,
        "chapterSessionId": SESSION_ID,
        "candidateId": CANDIDATE_ID,
        "candidateHash": candidate_hash,
        "expectedCanonRevision": 0,
        "expectedPlanningHash": HASH_B,
        "expectedOutlineHash": HASH_C,
        "contextManifestHash": HASH_A,
        "idempotencyKey": HASH_B,
        "requestFingerprint": HASH_C,
    })
    session = {
        "id": SESSION_ID,
        "project_id": PROJECT_ID,
        "status": "drafting",
        "active_draft_operation_id": None,
        "expected_canon_revision": 0,
        "planning_hash": HASH_B,
        "chapter_outline_hash": HASH_C,
    }
    candidate = {
        "id": CANDIDATE_ID,
        "project_id": PROJECT_ID,
        "chapter_session_id": SESSION_ID,
        "content": content,
        "content_hash": candidate_hash,
        "basis_hash": canonical_hash(basis),
        "provenance": {"source": "explicit-save-candidate", **basis},
    }
    current = {
        "canon_revision": 0,
        "projection_revision": 0,
        "projection_hash": HASH_A,
        "planning_hash": HASH_B,
        "outline_hash": HASH_C,
    }
    return authority, session, candidate, current


def _codes(result):
    return tuple(item.code.value for item in result)


def test_current_complete_candidate_with_completed_empty_copy_set_passes():
    authority, session, candidate, current = _fixture()

    assert run_finalization_prechecks(
        authority,
        session=session,
        candidate=candidate,
        current_authority=current,
        reference_sources=(),
        copy_check_completed=True,
    ) == ()


@pytest.mark.parametrize(
    ("target", "field", "value", "code"),
    [
        ("session", "project_id", "other", "session_drift"),
        ("session", "status", "final", "session_drift"),
        ("session", "active_draft_operation_id", "operation-1", "session_drift"),
        ("candidate", "chapter_session_id", "other", "session_drift"),
        ("candidate", "content_hash", HASH_A, "candidate_hash_drift"),
        ("current", "canon_revision", 1, "canon_conflict"),
        ("current", "planning_hash", HASH_A, "planning_drift"),
        ("current", "outline_hash", HASH_A, "outline_drift"),
        ("current", "projection_revision", 1, "canon_conflict"),
    ],
)
def test_authority_and_owner_drift_is_hard_blocked(target, field, value, code):
    authority, session, candidate, current = _fixture()
    {"session": session, "candidate": candidate, "current": current}[target][field] = value

    assert code in _codes(run_finalization_prechecks(
        authority,
        session=session,
        candidate=candidate,
        current_authority=current,
        reference_sources=(),
        copy_check_completed=True,
    ))


@pytest.mark.parametrize("content", ["", "  \n\t  "])
def test_empty_candidate_is_hard_blocked(content):
    authority, session, candidate, current = _fixture(content)

    assert "empty_candidate" in _codes(run_finalization_prechecks(
        authority,
        session=session,
        candidate=candidate,
        current_authority=current,
        reference_sources=(),
        copy_check_completed=True,
    ))


def test_candidate_basis_hash_or_projection_drift_is_blocked():
    authority, session, candidate, current = _fixture()
    candidate["basis_hash"] = HASH_C

    result = run_finalization_prechecks(
        authority,
        session=session,
        candidate=candidate,
        current_authority=current,
        reference_sources=(),
        copy_check_completed=True,
    )

    assert "candidate_hash_drift" in _codes(result)


def test_explicit_technical_truncation_marker_is_blocked_but_narrative_abruptness_is_not():
    authority, session, candidate, current = _fixture("他推开门。")
    assert run_finalization_prechecks(
        authority,
        session=session,
        candidate=candidate,
        current_authority=current,
        reference_sources=(),
        copy_check_completed=True,
    ) == ()

    candidate["provenance"]["technicalTruncation"] = True
    assert "technical_truncation" in _codes(run_finalization_prechecks(
        authority,
        session=session,
        candidate=candidate,
        current_authority=current,
        reference_sources=(),
        copy_check_completed=True,
    ))


def test_uncompleted_or_corrupt_reference_check_is_hard_blocked():
    authority, session, candidate, current = _fixture()
    invalid_source = {"id": "source-1", "content": "参考", "content_hash": HASH_A}

    for completed, sources in ((False, ()), (True, (invalid_source,))):
        assert "precheck_incomplete" in _codes(run_finalization_prechecks(
            authority,
            session=session,
            candidate=candidate,
            current_authority=current,
            reference_sources=sources,
            copy_check_completed=completed,
        ))


def test_long_normalized_verbatim_local_copy_is_blocked_without_returning_source_text():
    copied = "山河故人" * 40
    content = f"开头。{copied}结尾。"
    authority, session, candidate, current = _fixture(content)
    source_text = f"前言 {copied[:100]}，{copied[100:]} 后记"
    source = {
        "id": "source-1",
        "content": source_text,
        "content_hash": _hash_text(source_text),
    }

    result = run_finalization_prechecks(
        authority,
        session=session,
        candidate=candidate,
        current_authority=current,
        reference_sources=(source,),
        copy_check_completed=True,
    )

    assert _codes(result) == ("deterministic_copy",)
    assert result[0].evidence is not None
    assert result[0].evidence.end_scalar > result[0].evidence.start_scalar
    assert copied not in result[0].message


def test_short_common_phrase_is_not_a_copy_block():
    content = "他抬头看向天空，然后继续赶路。"
    authority, session, candidate, current = _fixture(content)
    source_text = "他抬头看向天空。"

    assert run_finalization_prechecks(
        authority,
        session=session,
        candidate=candidate,
        current_authority=current,
        reference_sources=({
            "id": "source-1",
            "content": source_text,
            "content_hash": _hash_text(source_text),
        },),
        copy_check_completed=True,
    ) == ()
