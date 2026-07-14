from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.http_errors import StoryEngineBatchConflict, StoryEngineBatchNotFound
from backend.routers import story_engines
from backend.security.redaction import install_error_handlers
from backend.tests.support.story_engine_fakes import three_options


def _json_options():
    return [item.model_dump(mode="json") for item in three_options()]


class FakeService:
    def __init__(self):
        self.calls = []

    async def generate_provider(self, command):
        self.calls.append(("generate", command))
        if command.idempotency_key == "conflict":
            raise StoryEngineBatchConflict()
        return _result("reserved")

    async def create_manual(self, command):
        self.calls.append(("manual", command))
        return _result("succeeded", options=command.options)

    async def get(self, project_id, batch_id):
        self.calls.append(("get", project_id, batch_id))
        if batch_id == "missing":
            raise StoryEngineBatchNotFound()
        return _result("reserved")

    async def reconcile(self, project_id, batch_id):
        self.calls.append(("reconcile", project_id, batch_id))
        return _result("failed", public_error_code="not_started")


def _result(status, *, options=(), public_error_code=None):
    from backend.services.story_engines import StoryEngineBatchResult

    return StoryEngineBatchResult(
        id="batch-1", project_id="p1", source_type="manual" if options else "provider",
        seed_id="seed-1", seed_revision_id="revision-1", seed_hash="a" * 64,
        binding_revision_id=None if options else "binding-1",
        binding_hash=None if options else "b" * 64,
        provider_id=None if options else "provider-1",
        model_name_snapshot=None if options else "model",
        idempotency_key="key", request_hash="c" * 64, status=status,
        attempt_id="attempt-secret-sentinel",
        attempt_started_at=123456789, lease_expires_at=987654321,
        raw_response_text="https://secret.invalid/api\nraw-secret-sentinel",
        raw_response_hash="d" * 64,
        public_error_code=public_error_code, created_at=100, finished_at=200 if status in {"succeeded", "failed"} else None,
        options=tuple(
            {"id": f"option-{index}", "option_order": index, "content_hash": canonical,
             "payload": option}
            for index, (option, canonical) in enumerate(
                ((item, str(index) * 64) for index, item in enumerate(options, 1)), 1
            )
        ),
    )


def make_client():
    app = FastAPI()
    service = FakeService()
    app.include_router(story_engines.router, prefix="/api")
    app.dependency_overrides[story_engines.get_story_engine_service] = lambda: service
    install_error_handlers(app)
    return TestClient(app, raise_server_exceptions=False), service


def test_fixed_routes_delegate_and_return_camel_case_dto():
    client, service = make_client()
    provider = client.post("/api/projects/p1/story-engine-batches", json={"idempotencyKey": "key"})
    manual = client.post(
        "/api/projects/p1/story-engine-batches/manual",
        json={"idempotencyKey": "key", "options": _json_options()},
    )
    read = client.get("/api/projects/p1/story-engine-batches/batch-1")
    reconcile = client.post("/api/projects/p1/story-engine-batches/batch-1/reconcile")

    assert [response.status_code for response in (provider, manual)] == [201, 201]
    assert [response.status_code for response in (read, reconcile)] == [200, 200]
    assert provider.json()["projectId"] == "p1"
    assert provider.json()["bindingRevisionId"] == "binding-1"
    assert manual.json()["bindingRevisionId"] is None
    assert len(manual.json()["options"]) == 3
    assert reconcile.json()["publicErrorCode"] == "not_started"
    assert service.calls[0][0] == "generate"
    assert service.calls[0][1].project_id == "p1"


def test_all_public_batch_responses_redact_raw_audit_and_attempt_markers():
    client, _ = make_client()
    responses = (
        client.post(
            "/api/projects/p1/story-engine-batches",
            json={"idempotencyKey": "key"},
        ),
        client.post(
            "/api/projects/p1/story-engine-batches",
            json={"idempotencyKey": "key"},
        ),
        client.get("/api/projects/p1/story-engine-batches/batch-1"),
        client.post("/api/projects/p1/story-engine-batches/batch-1/reconcile"),
    )
    forbidden = (
        "attemptId", "attemptStartedAt", "leaseExpiresAt",
        "rawResponseText", "rawResponseHash",
        "attempt-secret-sentinel", "123456789", "987654321",
        "https://secret.invalid/api", "raw-secret-sentinel", "d" * 64,
    )
    assert [response.status_code for response in responses] == [201, 201, 200, 200]
    for response in responses:
        serialized = response.text
        assert all(item not in serialized for item in forbidden)


def test_create_route_idempotency_replays_keep_static_201_and_same_resource():
    client, _ = make_client()
    requests = (
        (
            "/api/projects/p1/story-engine-batches",
            {"idempotencyKey": "key"},
        ),
        (
            "/api/projects/p1/story-engine-batches/manual",
            {"idempotencyKey": "key", "options": _json_options()},
        ),
    )
    for path, payload in requests:
        created = client.post(path, json=payload)
        replayed = client.post(path, json=payload)
        assert (created.status_code, replayed.status_code) == (201, 201)
        assert replayed.json() == created.json()
        assert replayed.json()["id"] == "batch-1"


def test_manual_requires_exactly_three_strict_options_and_forbids_extra_fields():
    client, service = make_client()
    for options in (_json_options()[:2], _json_options() + [_json_options()[0]]):
        response = client.post(
            "/api/projects/p1/story-engine-batches/manual",
            json={"idempotencyKey": "key", "options": options},
        )
        assert response.status_code == 422
    response = client.post(
        "/api/projects/p1/story-engine-batches",
        json={"idempotencyKey": "key", "baseURL": "https://secret.invalid"},
    )
    assert response.status_code == 422
    duplicate = _json_options()[0]
    response = client.post(
        "/api/projects/p1/story-engine-batches/manual",
        json={"idempotencyKey": "key", "options": [duplicate] * 3},
    )
    assert response.status_code == 422
    assert service.calls == []


def test_public_404_and_409_are_stable_and_do_not_echo_sensitive_input():
    client, _ = make_client()
    missing = client.get("/api/projects/p1/story-engine-batches/missing")
    conflict = client.post(
        "/api/projects/p1/story-engine-batches", json={"idempotencyKey": "conflict"}
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "StoryEngineBatchNotFound"
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "StoryEngineBatchConflict"
    assert "secret" not in str(missing.json()).lower()
    assert "base_url" not in str(conflict.json()).lower()
