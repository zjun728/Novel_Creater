from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.finalization import FinalizationChangeSet
from backend.routers import finalization
from backend.security.redaction import install_error_handlers
from backend.services.finalization import (
    FinalizationConflict,
    PreparedFinalization,
    ReviewedFinalization,
)
from backend.services.finalization_commit import CommittedFinalization


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _change_set():
    return {
        "schemaVersion": "finalization-changeset-v1",
        "title": "第一章",
        "summary": "主角进入城中。",
        "existingEntityIds": [],
        "entities": [],
        "aliases": [],
        "canonEvents": [],
        "storyProgressEvents": [],
        "planningPatches": [],
        "planningSuggestions": [],
    }


class FakeFinalizationService:
    def __init__(self):
        self.prepared = []
        self.corrected = []
        self.confirmed = []
        self.error = None
        self.review = {
            "attemptId": "attempt-1", "status": "awaiting_author",
            "candidateId": "candidate-1", "candidateHash": HASH_A,
            "qualityReport": {
                "status": "completed", "deterministicBlocks": [],
                "findings": [], "contentHash": HASH_B,
            },
            "changeSet": {
                "revision": 1, "contentHash": HASH_A,
                "source": "extraction", "payload": _change_set(),
            },
            "confirmation": None,
        }

    async def prepare(self, command):
        if self.error:
            raise self.error
        self.prepared.append(command)
        return PreparedFinalization(
            attempt_id="attempt-1", status="awaiting_author",
            quality_status="completed", current_revision=1,
            current_revision_hash=HASH_A,
        )

    async def get_review(self, project_id, session_id):
        if self.error:
            raise self.error
        return self.review

    async def correct(self, command):
        if self.error:
            raise self.error
        self.corrected.append(command)
        return ReviewedFinalization(
            attempt_id="attempt-1", status="awaiting_author",
            current_revision=2, current_revision_hash=HASH_B,
        )

    async def confirm(self, command):
        if self.error:
            raise self.error
        self.confirmed.append(command)
        return ReviewedFinalization(
            attempt_id="attempt-1", status="awaiting_author",
            current_revision=1, current_revision_hash=HASH_A,
            confirmed_revision=1, confirmed_revision_hash=HASH_A,
        )


class FakeAtomicFinalizationService:
    def __init__(self):
        self.committed = []

    async def commit(self, command):
        self.committed.append(command)
        return CommittedFinalization(
            record_id="record-1", final_chapter_id="chapter-1",
            canon_revision=2, projection_hash=HASH_C,
            planning_revision_id="planning-2", planning_revision=2,
            planning_hash=HASH_B,
        )

def _client():
    service = FakeFinalizationService()
    atomic = FakeAtomicFinalizationService()
    app = FastAPI()
    app.include_router(finalization.router, prefix="/api")
    app.dependency_overrides[finalization.get_finalization_service] = lambda: service
    app.dependency_overrides[finalization.get_atomic_finalization_service] = lambda: atomic
    install_error_handlers(app)
    return TestClient(app, raise_server_exceptions=False), service, atomic


def test_prepare_get_correct_and_confirm_use_narrow_closed_contracts():
    client, service, atomic = _client()
    base = "/api/projects/p1/chapter-sessions/session-1"

    prepared = client.post(
        f"{base}/candidates/candidate-1/finalization/prepare",
        json={
            "candidateHash": HASH_A,
            "expectedCanonRevision": 0,
            "expectedPlanningHash": HASH_B,
            "expectedOutlineHash": HASH_C,
            "idempotencyKey": HASH_A,
        },
    )
    viewed = client.get(f"{base}/finalization")
    corrected = client.post(f"{base}/finalization/revisions", json={
        "expectedRevision": 1,
        "expectedRevisionHash": HASH_A,
        "changeSet": _change_set(),
    })
    confirmed = client.post(f"{base}/finalization/confirm", json={
        "expectedRevision": 1,
        "expectedRevisionHash": HASH_A,
    })
    committed = client.post(f"{base}/finalization/commit", json={
        "idempotencyKey": HASH_C,
        "expectedRevision": 1,
        "expectedRevisionHash": HASH_A,
    })

    assert [
        prepared.status_code, viewed.status_code,
        corrected.status_code, confirmed.status_code, committed.status_code,
    ] == [201, 200, 201, 200, 200]
    assert prepared.json()["currentRevision"] == 1
    assert viewed.json()["changeSet"]["payload"] == _change_set()
    assert corrected.json()["currentRevision"] == 2
    assert confirmed.json()["confirmedRevision"] == 1
    assert service.prepared[0].candidate_id == "candidate-1"
    assert isinstance(service.corrected[0].change_set, FinalizationChangeSet)
    assert service.confirmed[0].expected_revision_hash == HASH_A
    assert committed.json()["finalChapterId"] == "chapter-1"
    assert atomic.committed[0].idempotency_key == HASH_C


def test_strict_bodies_reject_unknown_keys_and_malformed_full_payload():
    client, service, _ = _client()
    base = "/api/projects/p1/chapter-sessions/session-1"

    unknown = client.post(f"{base}/finalization/confirm", json={
        "expectedRevision": 1,
        "expectedRevisionHash": HASH_A,
        "partialApproval": True,
    })
    malformed = client.post(f"{base}/finalization/revisions", json={
        "expectedRevision": 1,
        "expectedRevisionHash": HASH_A,
        "changeSet": {"schemaVersion": "finalization-changeset-v1"},
    })

    assert unknown.status_code == malformed.status_code == 422
    assert service.corrected == service.confirmed == []


def test_get_finalization_returns_200_empty_projection_for_existing_session():
    client, service, _ = _client()
    service.review = {"state": "empty"}

    response = client.get(
        "/api/projects/project-1/chapter-sessions/session-1/finalization"
    )

    assert response.status_code == 200
    assert response.json() == {"state": "empty"}


def test_get_finalization_keeps_true_not_found_fixed():
    client, service, _ = _client()
    service.error = FinalizationConflict("FINALIZATION_NOT_FOUND")

    response = client.get(
        "/api/projects/project-1/chapter-sessions/missing/finalization"
    )

    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"code", "message", "correlationId"}
    assert body["code"] == "FinalizationNotFound"
    assert body["message"] == "Finalization or chapter session was not found"
    assert body["correlationId"]


def test_service_errors_are_stable_and_do_not_return_internal_text():
    client, service, _ = _client()
    service.error = FinalizationConflict(
        "FINALIZATION_STATE_CONFLICT RAW_PROSE_SENTINEL SECRET_KEY"
    )

    response = client.get(
        "/api/projects/p1/chapter-sessions/session-1/finalization"
    )

    assert response.status_code == 409
    assert response.json()["code"] == "FinalizationConflict"
    assert response.json()["message"] == (
        "Finalization state changed; refresh and retry"
    )
    assert "RAW_PROSE_SENTINEL" not in response.text
    assert "SECRET_KEY" not in response.text
