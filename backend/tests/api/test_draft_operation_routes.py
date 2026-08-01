from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
import json

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
OTHER_PROJECT_ID = "10000000-0000-0000-0000-000000000002"
SESSION_ID = "20000000-0000-0000-0000-000000000001"
OPERATION_ID = "30000000-0000-0000-0000-000000000001"
IDEMPOTENCY_KEY = "40000000-0000-0000-0000-000000000001"
START_EVENT_ID = "50000000-0000-0000-0000-000000000001"
TERMINAL_EVENT_ID = "50000000-0000-0000-0000-000000000002"
HASH = "a" * 64


def stored_operation(**overrides):
    row = {
        "id": OPERATION_ID,
        "project_id": PROJECT_ID,
        "chapter_session_id": SESSION_ID,
        "operation_type": "generate_new",
        "status": "completed",
        "active_slot": None,
        "last_event_sequence": 2,
        "base_working_draft_revision": 1,
        "base_working_draft_hash": HASH,
        "result_working_draft_revision": 2,
        "result_content_hash": HASH,
        "failure_code": None,
        "provider_id": "provider-1",
        "model_name_snapshot": "fake-model",
    }
    row.update(overrides)
    return row


def stored_events():
    events = [
        {
            "id": START_EVENT_ID,
            "project_id": PROJECT_ID,
            "draft_operation_id": OPERATION_ID,
            "sequence_num": 1,
            "event_type": "started",
            "closed_payload_json": None,
            "created_at": 100,
        },
        {
            "id": TERMINAL_EVENT_ID,
            "project_id": PROJECT_ID,
            "draft_operation_id": OPERATION_ID,
            "sequence_num": 2,
            "event_type": "completed",
            "closed_payload_json": json.dumps({
                "resultWorkingDraftRevision": 2,
                "resultContentHash": HASH,
            }),
            "created_at": 101,
        },
    ]
    return events


class FakeDraftOperationService:
    def __init__(self):
        self.commands = []
        self.error = None
        self.result = DraftOperationResult(
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

    async def start(self, command):
        self.commands.append(command)
        if self.error is not None:
            raise self.error
        return self.result


class FakeDraftOperationRepository:
    def __init__(self):
        self.operation_reads = []
        self.event_reads = []
        self.operation = stored_operation()
        self.events = stored_events()

    async def read_draft_operation(self, session, project_id, session_id, operation_id):
        self.operation_reads.append((project_id, session_id, operation_id))
        if (project_id, session_id, operation_id) != (
            PROJECT_ID, SESSION_ID, OPERATION_ID,
        ):
            return None
        return dict(self.operation)

    async def list_draft_operation_events(
        self, session, operation_id, after_sequence, limit,
    ):
        self.event_reads.append((operation_id, after_sequence, limit))
        return [
            dict(event)
            for event in self.events
            if event["sequence_num"] > after_sequence
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


def test_create_formal_draft_operation_rejects_wrong_owner_or_malformed_service_result():
    client, service, _ = make_client()

    for result in (
        replace(service.result, project_id=OTHER_PROJECT_ID),
        object(),
    ):
        service.result = result
        response = client.post(
            operation_path().rsplit("/", 1)[0], json=create_body(),
        )

        assert response.status_code == 502
        assert response.json()["code"] == "DraftOperationUnavailable"


def test_create_formal_draft_operation_rejects_duplicate_raw_json_members():
    client, service, _ = make_client()
    body = json.dumps(
        create_body(), separators=(",", ":"), ensure_ascii=False,
    )
    duplicate_top_level = body.replace(
        '"operationType":"generate_new"',
        '"operationType":"generate_new","operationType":"generate_new"',
    )
    duplicate_nested = body.replace(
        '"authorInstruction":"增加人物之间的试探"',
        '"authorInstruction":{"hint":1,"hint":2}',
    )
    nonfinite_number = body.replace(
        '"expectedWorkingDraftRevision":1',
        '"expectedWorkingDraftRevision":NaN',
    )

    for raw_json in (duplicate_top_level, duplicate_nested, nonfinite_number):
        response = client.post(
            operation_path().rsplit("/", 1)[0],
            content=raw_json.encode("utf-8"),
            headers={"content-type": "application/json"},
        )

        assert response.status_code == 422
        assert response.json()["code"] == "DraftOperationRequestInvalid"
    invalid_utf8 = client.post(
        operation_path().rsplit("/", 1)[0],
        content=b"\xff",
        headers={"content-type": "application/json"},
    )
    assert invalid_utf8.status_code == 422
    assert invalid_utf8.json()["code"] == "DraftOperationRequestInvalid"
    assert service.commands == []


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


def test_formal_operation_status_fails_closed_for_cross_owner_or_incomplete_stored_row():
    client, _, repository = make_client()

    for mutation in (
        lambda: repository.operation.update(project_id=OTHER_PROJECT_ID),
        lambda: repository.operation.pop("base_working_draft_hash"),
        lambda: repository.operation.pop("active_slot"),
    ):
        repository.operation = stored_operation()
        mutation()
        response = client.get(operation_path())

        assert response.status_code == 404
        assert response.json()["code"] == "DraftOperationNotFound"


def test_formal_operation_events_reject_cross_owner_or_invalid_b1_terminal_history():
    client, _, repository = make_client()

    invalid_events = []
    cross_owner = stored_events()
    cross_owner[1]["project_id"] = OTHER_PROJECT_ID
    invalid_events.append(cross_owner)
    cross_operation = stored_events()
    cross_operation[1]["draft_operation_id"] = (
        "30000000-0000-0000-0000-000000000099"
    )
    invalid_events.append(cross_operation)
    malformed_event_id = stored_events()
    malformed_event_id[1]["id"] = "not-a-uuid"
    invalid_events.append(malformed_event_id)
    invalid_events.append(list(reversed(stored_events())))
    wrong_terminal = stored_events()
    wrong_terminal[1].update(
        event_type="failed",
        closed_payload_json=json.dumps({"failureCode": "DraftProviderFailed"}),
    )
    invalid_events.append(wrong_terminal)
    wrong_result = stored_events()
    wrong_result[1]["closed_payload_json"] = json.dumps({
        "resultWorkingDraftRevision": 2,
        "resultContentHash": "b" * 64,
    })
    invalid_events.append(wrong_result)
    invalid_events.append(stored_events() * 51)

    for events in invalid_events:
        repository.events = events
        response = client.get(f"{operation_path()}/events?after=0")

        assert response.status_code == 404
        assert response.json()["code"] == "DraftOperationNotFound"


def test_formal_operation_events_require_failure_payload_to_match_stored_result():
    client, _, repository = make_client()
    repository.operation = stored_operation(
        status="failed",
        result_working_draft_revision=None,
        result_content_hash=None,
        failure_code="DraftProviderFailed",
    )
    repository.events = stored_events()
    repository.events[1].update(
        event_type="failed",
        closed_payload_json=json.dumps({
            "failureCode": "DraftProviderResultInvalid",
        }),
    )

    response = client.get(f"{operation_path()}/events?after=0")

    assert response.status_code == 404
    assert response.json()["code"] == "DraftOperationNotFound"


def test_formal_operation_events_return_only_the_strict_cursor_suffix():
    client, _, repository = make_client()

    terminal_only = client.get(f"{operation_path()}/events?after=1")
    exhausted = client.get(f"{operation_path()}/events?after=2")

    assert terminal_only.status_code == 200
    assert terminal_only.json()["events"] == [{
        "sequence": 2,
        "type": "completed",
        "createdAt": 101,
        "resultWorkingDraftRevision": 2,
        "resultContentHash": HASH,
    }]
    assert exhausted.status_code == 200
    assert exhausted.json()["events"] == []
    assert repository.event_reads == [(OPERATION_ID, 1, 100), (OPERATION_ID, 2, 100)]


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

    for after in (
        "-1", "1.0", "secret-shaped-token", "2147483648", "9" * 5000,
    ):
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
