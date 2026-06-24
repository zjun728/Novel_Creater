from pathlib import Path


SOURCE = Path("backend/routers/story_blocks.py").read_text(encoding="utf-8")


def test_status_payload_carries_semantic_close_evidence():
    assert "completionEvidence" in SOURCE
    assert "singleChapterBlockReason" in SOURCE
    assert "closedBy" in SOURCE
    assert "ALLOWED_CLOSED_BY" in SOURCE


def test_close_complete_validate_evidence_before_status_change():
    assert "def _validate_status_transition_evidence" in SOURCE
    assert "_validate_status_transition_evidence(status, data, chapter_refs)" in SOURCE
    assert "completionEvidence" in SOURCE
    assert "closeReason" in SOURCE
    assert "raise HTTPException(400" in SOURCE


def test_status_transition_persists_granularity_metadata():
    assert '"completionEvidence"' in SOURCE
    assert '"singleChapterBlockReason"' in SOURCE
    assert '"closedBy"' in SOURCE
