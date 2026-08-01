from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import chapter_sessions
from backend.security.redaction import install_error_handlers
from backend.services.draft_operations import (
    DraftOperationResult,
    DraftOperationStorageError,
    DraftOperationUnexpectedProviderError,
)


PROJECT_ID = "10000000-0000-0000-0000-000000000001"
SESSION_ID = "20000000-0000-0000-0000-000000000001"
OPERATION_ID = "30000000-0000-0000-0000-000000000001"
IDEMPOTENCY_KEY = "40000000-0000-0000-0000-000000000001"
HASH = "a" * 64


class FakeDraftOperationService:
    def __init__(self):
        self.commands = []
        self.error = None

    async def start(self, command):
        self.commands.append(command)
        if self.error is not None:
            raise self.error
        return DraftOperationResult(
            operation_id=OPERATION_ID,
            project_id=PROJECT_ID,
            chapter_session_id=SESSION_ID,
            operation_type="generate_new",
            status="completed",
            last_event_sequence=2,
            result_working_draft_revision=2,
            result_content_hash=HASH,
            failure_code=None,
            provider_id="provider-1",
            model_name="fake-model",
        )


class FakeDraftOperationRepository:
    def __init__(self):
        self.operation_reads = []
        self.event_reads = []

    async def read_draft_operation(self, session, project_id, session_id, operation_id):
        self.operation_reads.append((project_id, session_id, operation_id))
        if (project_id, session_id, operation_id) != (
            PROJECT_ID, SESSION_ID, OPERATION_ID,
        ):
            return None
        return {
            "id": OPERATION_ID,
            "project_id": PROJECT_ID,
            "chapter_session_id": SESSION_ID,
            "operation_type": "generate_new",
            "status": "completed",
            "last_event_sequence": 2,
            "result_working_draft_revision": 2,
            "result_content_hash": HASH,
            "failure_code": None,
            "provider_id": "provider-1",
            "model_name_snapshot": "fake-model",
        }

    async def list_draft_operation_events(
        self, session, operation_id, after_sequence, limit,
    ):
        self.event_reads.append((operation_id, after_sequence, limit))
        return [
            {
                "sequence_num": 1,
                "event_type": "started",
                "closed_payload_json": None,
                "created_at": 100,
                "project_id": PROJECT_ID,
            },
            {
                "sequence_num": 2,
                "event_type": "completed",
                "closed_payload_json": (
                    '{"resultWorkingDraftRevision":2,'
                    f'"resultContentHash":"{HASH}"}}'
                ),
                "created_at": 101,
                "project_id": PROJECT_ID,
            },
        ]


def make_client():
    service = FakeDraftOperationService()
    repository = FakeDraftOperationRepository()
    app = FastAPI()
    app.include_router(chapter_sessions.router, prefix="/api")
    if hasattr(chapter_sessions, "get_draft_operation_service"):
        app.dependency_overrides[
            chapter_sessions.get_draft_operation_service
        ] = lambda: service
    if hasattr(chapter_sessions, "get_draft_operation_repository"):
        app.dependency_overrides[
            chapter_sessions.get_draft_operation_repository
        ] = lambda: repository
    if hasattr(chapter_sessions, "get_draft_operation_transaction_factory"):
        @asynccontextmanager
        async def transaction_factory():
            yield object()

        app.dependency_overrides[
            chapter_sessions.get_draft_operation_transaction_factory
        ] = lambda: transaction_factory
    install_error_handlers(app)
    return TestClient(app, raise_server_exceptions=False), service, repository


def create_body(**overrides):
    body = {
        "operationType": "generate_new",
        "expectedWorkingDraftRevision": 1,
        "expectedContentHash": HASH,
        "idempotencyKey": IDEMPOTENCY_KEY,
        "authorInstruction": "增加人物之间的试探",
    }
    body.update(overrides)
    return body


def operation_path(operation_id=OPERATION_ID):
    return (
        f"/api/projects/{PROJECT_ID}/chapter-sessions/{SESSION_ID}/"
        f"draft-operations/{operation_id}"
    )


def test_create_formal_draft_operation_returns_only_closed_result_fields():
    client, service, _ = make_client()

    response = client.post(operation_path().rsplit("/", 1)[0], json=create_body())

    assert response.status_code == 200
    assert response.json() == {
        "operationId": OPERATION_ID,
        "projectId": PROJECT_ID,
        "chapterSessionId": SESSION_ID,
        "operationType": "generate_new",
        "status": "completed",
        "lastEventSequence": 2,
        "resultWorkingDraftRevision": 2,
        "resultContentHash": HASH,
        "failureCode": None,
        "providerId": "provider-1",
        "modelName": "fake-model",
    }
    assert len(service.commands) == 1
    command = service.commands[0]
    assert command.project_id == PROJECT_ID
    assert command.chapter_session_id == SESSION_ID
    assert command.operation_type == "generate_new"
    assert command.expected_content_hash == HASH


def test_create_formal_draft_operation_rejects_unknown_sensitive_shaped_fields():
    client, service, _ = make_client()

    for field in (
        "prompt", "messages", "provider", "model", "apiKey", "baseUrl",
        "debug", "responseBody",
    ):
        response = client.post(
            operation_path().rsplit("/", 1)[0],
            json=create_body(**{field: "LEAK-SENTINEL"}),
        )

        assert response.status_code == 422
        assert response.json()["code"] == "DraftOperationRequestInvalid"
        assert "LEAK-SENTINEL" not in response.text
    assert service.commands == []


def test_create_formal_draft_operation_requires_canonical_command_fields():
    client, service, _ = make_client()

    for body in (
        create_body(operationType="rewrite"),
        create_body(expectedWorkingDraftRevision=True),
        create_body(expectedContentHash="A" * 64),
        create_body(idempotencyKey="40000000-0000-0000-0000-00000000000A"),
        create_body(authorInstruction="字" * 2001),
    ):
        response = client.post(operation_path().rsplit("/", 1)[0], json=body)

        assert response.status_code == 422
        assert response.json()["code"] == "DraftOperationRequestInvalid"
    assert service.commands == []


def test_create_formal_draft_operation_hides_internal_provider_and_storage_errors():
    client, service, _ = make_client()

    for error in (
        DraftOperationUnexpectedProviderError(),
        DraftOperationStorageError("LEAK-SENTINEL"),
    ):
        service.error = error
        response = client.post(
            operation_path().rsplit("/", 1)[0], json=create_body(),
        )

        assert response.status_code == 502
        assert response.json()["code"] == "DraftOperationUnavailable"
        assert "LEAK-SENTINEL" not in response.text


def test_formal_operation_reads_are_owner_scoped_and_never_start_provider_work():
    client, service, repository = make_client()

    status = client.get(operation_path())
    events = client.get(f"{operation_path()}/events?after=0")
    missing = client.get(operation_path("30000000-0000-0000-0000-000000000099"))

    assert status.status_code == 200
    assert status.json()["operationId"] == OPERATION_ID
    assert events.status_code == 200
    assert events.json() == {
        "operationId": OPERATION_ID,
        "events": [
            {"sequence": 1, "type": "started", "createdAt": 100},
            {
                "sequence": 2,
                "type": "completed",
                "createdAt": 101,
                "resultWorkingDraftRevision": 2,
                "resultContentHash": HASH,
            },
        ],
    }
    assert missing.status_code == 404
    assert missing.json()["code"] == "DraftOperationNotFound"
    assert service.commands == []
    assert repository.operation_reads == [
        (PROJECT_ID, SESSION_ID, OPERATION_ID),
        (PROJECT_ID, SESSION_ID, OPERATION_ID),
        (PROJECT_ID, SESSION_ID, "30000000-0000-0000-0000-000000000099"),
    ]
    assert repository.event_reads == [(OPERATION_ID, 0, 100)]


def test_formal_operation_read_rejects_noncanonical_owner_before_repository_access():
    client, service, repository = make_client()

    response = client.get(
        "/api/projects/not-a-uuid/chapter-sessions/"
        f"{SESSION_ID}/draft-operations/{OPERATION_ID}"
    )

    assert response.status_code == 404
    assert response.json()["code"] == "DraftOperationNotFound"
    assert service.commands == []
    assert repository.operation_reads == []


def test_formal_operation_event_cursor_rejects_invalid_values_and_old_post_is_gone():
    client, _, repository = make_client()

    for after in ("-1", "1.0", "secret-shaped-token"):
        response = client.get(f"{operation_path()}/events?after={after}")
        assert response.status_code == 422
        assert response.json()["code"] == "DraftOperationRequestInvalid"
    retired = client.post(
        f"/api/projects/{PROJECT_ID}/chapter-sessions/{SESSION_ID}/"
        "generate-working-draft",
        json={"expectedWorkingDraftRevision": 1},
    )

    assert retired.status_code == 404
    assert repository.event_reads == []
