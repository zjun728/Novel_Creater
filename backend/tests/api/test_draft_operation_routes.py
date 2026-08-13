from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
import pytest

from backend.domain.routers import chapter_sessions
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
OUTPUT = "正文"
OUTPUT_HASH = hashlib.sha256(OUTPUT.encode("utf-8")).hexdigest()
EMPTY_HASH = hashlib.sha256(b"").hexdigest()


def stored_operation(**overrides):
    row = {
        "id": OPERATION_ID,
        "project_id": PROJECT_ID,
        "chapter_session_id": SESSION_ID,
        "operation_type": "generate_new",
        "idempotency_key": IDEMPOTENCY_KEY,
        "request_fingerprint": "b" * 64,
        "status": "completed",
        "active_slot": None,
        "fencing_token": 1,
        "lease_expires_at": 200,
        "last_event_sequence": 2,
        "base_working_draft_revision": 1,
        "base_working_draft_hash": HASH,
        "input_manifest_json": "{}",
        "input_manifest_hash": hashlib.sha256(b"{}").hexdigest(),
        "result_working_draft_revision": 2,
        "result_content_hash": HASH,
        "failure_code": None,
        "created_at": 100,
        "updated_at": 101,
        "completed_at": 101,
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
                "resultContentHash": OUTPUT_HASH,
            }),
            "created_at": 101,
        },
    ]
    return events


class FakeDraftOperationService:
    def __init__(self):
        self.commands = []
        self.reads = []
        self.cancels = []
        self.undos = []
        self.error = None
        self.result = DraftOperationResult(
            operation_id=OPERATION_ID,
            project_id=PROJECT_ID,
            chapter_session_id=SESSION_ID,
            operation_type="generate_new",
            status="completed",
            last_event_sequence=2,
            result_working_draft_revision=2,
            result_content_hash=OUTPUT_HASH,
            failure_code=None,
            provider_id="provider-1",
            model_name="fake-model",
            partial_output=OUTPUT,
            partial_output_hash=OUTPUT_HASH,
            partial_output_scalars=len(OUTPUT),
        )

    async def start(self, command):
        self.commands.append(command)
        if self.error is not None:
            raise self.error
        return self.result

    async def read(self, project_id, session_id, operation_id):
        self.reads.append((project_id, session_id, operation_id))
        if self.error is not None:
            raise self.error
        if operation_id != OPERATION_ID:
            raise chapter_sessions.DraftOperationNotFound()
        return self.result

    async def cancel(self, project_id, session_id, operation_id):
        self.cancels.append((project_id, session_id, operation_id))
        if self.error is not None:
            raise self.error
        if operation_id != OPERATION_ID:
            raise chapter_sessions.DraftOperationNotFound()
        return self.result

    async def undo_local(self, command):
        self.undos.append(command)
        if self.error is not None:
            raise self.error
        return 7


class FakeChapterSessionService:
    def __init__(self):
        self.reads = []
        self.workspace = SimpleNamespace(
            project_id=PROJECT_ID,
            active_draft_operation_id=None,
            session=SimpleNamespace(
                id=SESSION_ID,
                project_id=PROJECT_ID,
                planning_revision_id="planning-1",
                planning_revision=1,
                planning_hash="1" * 64,
                story_block_id="block-1",
                story_block_revision=1,
                story_block_hash="2" * 64,
                chapter_outline_revision_id="outline-1",
                chapter_outline_revision=1,
                chapter_outline_hash="3" * 64,
                chapter_num=7,
                expected_canon_revision=0,
                status="drafting",
            ),
            working_draft=SimpleNamespace(
                id="draft-1",
                project_id=PROJECT_ID,
                chapter_session_id=SESSION_ID,
                revision=3,
                content="撤销后的正文",
                content_hash="4" * 64,
            ),
            candidates=[],
        )

    async def get(self, project_id, chapter_number):
        self.reads.append((project_id, chapter_number))
        return self.workspace


class FakeDraftOperationRepository:
    def __init__(self):
        self.operation_reads = []
        self.event_reads = []
        self.error = None
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
        if self.error is not None:
            raise self.error
        return [
            dict(event)
            for event in self.events
            if event["sequence_num"] > after_sequence
        ][:limit]


def make_client():
    service = FakeDraftOperationService()
    chapter_service = FakeChapterSessionService()
    repository = FakeDraftOperationRepository()
    app = FastAPI()
    app.include_router(chapter_sessions.router, prefix="/api")
    if hasattr(chapter_sessions, "get_draft_operation_service"):
        app.dependency_overrides[
            chapter_sessions.get_draft_operation_service
        ] = lambda: service
    app.dependency_overrides[
        chapter_sessions.get_chapter_session_service
    ] = lambda: chapter_service
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
    service.chapter_service = chapter_service
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


def local_create_body(**overrides):
    body = create_body(
        operationType="rewrite_selection",
        startOffset=2,
        endOffset=4,
        selectedTextHash="b" * 64,
        authorInstruction="保持克制",
    )
    body.update(overrides)
    return body


def operation_path(operation_id=OPERATION_ID):
    return (
        f"/api/projects/{PROJECT_ID}/chapter-sessions/{SESSION_ID}/"
        f"draft-operations/{operation_id}"
    )


def test_router_exports_the_exact_registry_injected_into_the_global_service():
    assert (
        chapter_sessions._draft_operation_service._registry
        is chapter_sessions.draft_operation_task_registry
    )
    assert chapter_sessions._draft_operation_service._owns_registry is False


def raw_create_body(**overrides):
    return json.dumps(
        create_body(**overrides),
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def event_id(sequence):
    return f"50000000-0000-0000-0000-{sequence:012x}"


def stored_event(sequence, event_type, payload=None):
    return {
        "id": event_id(sequence),
        "project_id": PROJECT_ID,
        "draft_operation_id": OPERATION_ID,
        "sequence_num": sequence,
        "event_type": event_type,
        "closed_payload_json": (
            None if payload is None else json.dumps(payload, ensure_ascii=False)
        ),
        "created_at": 99 + sequence,
    }


def test_create_formal_draft_operation_returns_only_closed_result_fields():
    client, service, _ = make_client()

    response = client.post(operation_path().rsplit("/", 1)[0], json=create_body())

    assert response.status_code == 200
    assert response.json() == {
        "id": OPERATION_ID,
        "projectId": PROJECT_ID,
        "chapterSessionId": SESSION_ID,
        "operationType": "generate_new",
        "status": "completed",
        "lastEventSequence": 2,
        "partialOutput": OUTPUT,
        "partialOutputHash": OUTPUT_HASH,
        "partialOutputScalars": len(OUTPUT),
        "resultWorkingDraftRevision": 2,
        "resultContentHash": OUTPUT_HASH,
        "resultSelectionStart": None,
        "resultSelectionEnd": None,
        "failureCode": None,
        "model": {
            "providerId": "provider-1",
            "modelName": "fake-model",
        },
    }
    assert len(service.commands) == 1
    command = service.commands[0]
    assert command.project_id == PROJECT_ID
    assert command.chapter_session_id == SESSION_ID
    assert command.operation_type == "generate_new"
    assert command.expected_content_hash == HASH


def test_create_local_operation_accepts_only_exact_selection_contract_and_projects_range():
    client, service, _ = make_client()
    service.result = replace(
        service.result,
        operation_type="rewrite_selection",
        result_content_hash="c" * 64,
        result_selection_start=2,
        result_selection_end=2 + len(OUTPUT),
    )

    response = client.post(
        operation_path().rsplit("/", 1)[0], json=local_create_body(),
    )

    assert response.status_code == 200
    assert response.json()["resultSelectionStart"] == 2
    assert response.json()["resultSelectionEnd"] == 2 + len(OUTPUT)
    command = service.commands[0]
    assert command.operation_type == "rewrite_selection"
    assert command.start_offset == 2
    assert command.end_offset == 4
    assert command.selected_text_hash == "b" * 64

    for body in (
        local_create_body(startOffset=None),
        local_create_body(endOffset=2),
        local_create_body(selectedTextHash="B" * 64),
        local_create_body(authorInstruction="字" * 1001),
        create_body(startOffset=0, endOffset=1, selectedTextHash="b" * 64),
    ):
        rejected = client.post(operation_path().rsplit("/", 1)[0], json=body)
        assert rejected.status_code == 422
        assert rejected.json()["code"] == "DraftOperationRequestInvalid"
    assert len(service.commands) == 1


def test_create_local_operation_rejects_mismatched_service_type_or_range():
    client, service, _ = make_client()
    path = operation_path().rsplit("/", 1)[0]
    baseline = replace(
        service.result,
        operation_type="rewrite_selection",
        result_content_hash="c" * 64,
        result_selection_start=2,
        result_selection_end=2 + len(OUTPUT),
    )
    for result in (
        replace(baseline, operation_type="polish_selection"),
        replace(
            baseline,
            result_selection_start=3,
            result_selection_end=3 + len(OUTPUT),
        ),
    ):
        service.result = result
        response = client.post(path, json=local_create_body())
        assert response.status_code == 502
        assert response.json()["code"] == "DraftOperationUnavailable"


def test_undo_local_requires_exact_body_and_returns_authoritative_workspace():
    client, service, _ = make_client()
    path = (
        f"/api/projects/{PROJECT_ID}/chapter-sessions/{SESSION_ID}/"
        "working-draft/undo"
    )
    body = {
        "expectedWorkingDraftRevision": 2,
        "expectedContentHash": OUTPUT_HASH,
        "sourceOperationId": OPERATION_ID,
    }

    response = client.post(path, json=body)

    assert response.status_code == 200
    assert response.json()["workingDraft"] == {
        "id": "draft-1",
        "projectId": PROJECT_ID,
        "chapterSessionId": SESSION_ID,
        "revision": 3,
        "content": "撤销后的正文",
        "contentHash": "4" * 64,
    }
    command = service.undos[0]
    assert command.expected_working_draft_revision == 2
    assert command.expected_content_hash == OUTPUT_HASH
    assert command.source_operation_id == OPERATION_ID
    assert service.chapter_service.reads == [(PROJECT_ID, 7)]

    for invalid in (
        {**body, "sourceOperationId": "not-a-uuid"},
        {**body, "unexpected": "LEAK-SENTINEL"},
        {key: value for key, value in body.items() if key != "expectedContentHash"},
    ):
        rejected = client.post(path, json=invalid)
        assert rejected.status_code == 422
        assert rejected.json()["code"] == "DraftOperationRequestInvalid"
        assert "LEAK-SENTINEL" not in rejected.text
    duplicate = client.post(
        path,
        content=(
            b'{"expectedWorkingDraftRevision":2,'
            + f'"expectedContentHash":"{OUTPUT_HASH}",'.encode()
            + f'"sourceOperationId":"{OPERATION_ID}",'.encode()
            + f'"sourceOperationId":"{OPERATION_ID}"}}'.encode()
        ),
        headers={"content-type": "application/json"},
    )
    wrong_content_type = client.post(
        path, content=json.dumps(body), headers={"content-type": "text/plain"},
    )
    assert duplicate.status_code == 422
    assert wrong_content_type.status_code == 422
    assert len(service.undos) == 1


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


def test_create_formal_draft_operation_counts_unicode_scalars_and_rejects_lone_surrogates():
    client, service, _ = make_client()
    path = operation_path().rsplit("/", 1)[0]

    for size in (1001, 2000):
        response = client.post(path, json=create_body(authorInstruction="😀" * size))
        assert response.status_code == 200
    too_long = client.post(path, json=create_body(authorInstruction="😀" * 2001))
    assert too_long.status_code == 422
    raw = json.dumps(
        create_body(authorInstruction="\ud800"),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    malformed = client.post(
        path,
        content=raw,
        headers={"content-type": "application/json"},
    )
    assert malformed.status_code == 422
    assert len(service.commands) == 2


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


def test_formal_operation_projection_rejects_terminal_sequence_one_and_invalid_unicode():
    client, service, _ = make_client()

    for result in (
        replace(service.result, last_event_sequence=1),
        replace(
            service.result,
            status="running",
            last_event_sequence=1,
            result_working_draft_revision=None,
            result_content_hash=None,
        ),
        replace(
            service.result,
            partial_output="\ud800",
            partial_output_hash=EMPTY_HASH,
            partial_output_scalars=1,
        ),
    ):
        service.result = result
        response = client.get(operation_path())
        assert response.status_code == 404
        assert response.json()["code"] == "DraftOperationNotFound"


def test_create_formal_draft_operation_requires_completed_result_to_advance_the_submitted_base_once():
    client, service, _ = make_client()
    service.result = replace(
        service.result,
        result_working_draft_revision=999,
    )

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


@pytest.mark.asyncio
async def test_create_draft_operation_reader_stops_streaming_after_the_size_limit():
    reads = 0
    chunks = [b"x" * (12 * 1024 + 1), b"must-not-be-buffered"]

    async def receive():
        nonlocal reads
        reads += 1
        return {
            "type": "http.request",
            "body": chunks.pop(0),
            "more_body": bool(chunks),
        }

    request = Request({
        "type": "http",
        "method": "POST",
        "headers": [(b"content-type", b"application/json")],
    }, receive)

    with pytest.raises(chapter_sessions.DraftOperationRequestInvalid):
        await chapter_sessions._read_draft_operation_create_body(request)

    assert reads == 1


def test_create_formal_draft_operation_bounds_nesting_without_rejecting_literal_brackets():
    client, service, _ = make_client()
    command_prefix = json.dumps({
        key: value
        for key, value in create_body().items()
        if key != "authorInstruction"
    }, separators=(",", ":"))[:-1].encode("utf-8")
    deeply_nested = (
        command_prefix + b',"authorInstruction":' + b"[" * 4000
        + b"0" + b"]" * 4000 + b"}"
    )

    too_deep = client.post(
        operation_path().rsplit("/", 1)[0],
        content=deeply_nested,
        headers={"content-type": "application/json"},
    )
    literal_brackets = client.post(
        operation_path().rsplit("/", 1)[0],
        content=raw_create_body(
            authorInstruction='文字中的 { [ ] } 和转义引号 " 都不是结构。',
        ),
        headers={"content-type": "application/json"},
    )

    assert len(deeply_nested) < 12 * 1024
    assert too_deep.status_code == 422
    assert too_deep.json()["code"] == "DraftOperationRequestInvalid"
    assert literal_brackets.status_code == 200
    assert len(service.commands) == 1


def test_create_formal_draft_operation_rejects_oversized_body_without_starting_service():
    client, service, _ = make_client()

    response = client.post(
        operation_path().rsplit("/", 1)[0],
        content=raw_create_body(authorInstruction="x" * (12 * 1024)),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "DraftOperationRequestInvalid"
    assert service.commands == []


def test_create_formal_draft_operation_requires_exact_json_content_type():
    client, service, _ = make_client()
    path = operation_path().rsplit("/", 1)[0]
    raw = raw_create_body()

    for content_type in (
        None,
        "text/plain",
        "application/octet-stream",
        "application/problem+json",
        "application/json; charset=latin-1",
        "application/json; boundary=unexpected",
    ):
        kwargs = {}
        if content_type is not None:
            kwargs["headers"] = {"content-type": content_type}
        response = client.post(path, content=raw, **kwargs)

        assert response.status_code == 422
        assert response.json()["code"] == "DraftOperationRequestInvalid"

    for content_type in (
        "application/json",
        'Application/JSON ; CHARSET = "UTF-8"',
    ):
        response = client.post(
            path,
            content=raw,
            headers={"content-type": content_type},
        )

        assert response.status_code == 200
    assert len(service.commands) == 2


@pytest.mark.asyncio
async def test_create_draft_operation_reader_rejects_duplicate_content_type_before_reading():
    reads = 0

    async def receive():
        nonlocal reads
        reads += 1
        return {"type": "http.request", "body": b"{}", "more_body": False}

    request = Request({
        "type": "http",
        "method": "POST",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-type", b"application/json"),
        ],
    }, receive)

    with pytest.raises(chapter_sessions.DraftOperationRequestInvalid):
        await chapter_sessions._read_draft_operation_create_body(request)

    assert reads == 0


def test_draft_operation_content_type_uses_only_http_ows_and_exact_quoted_utf8():
    def request_with_content_type(value):
        return Request({
            "type": "http",
            "method": "POST",
            "headers": [(b"content-type", value)],
        })

    for value in (
        b'application/json; charset=" utf-8 "',
        b"application/json\r\n",
        b"application/json\v",
        b"application/json\f",
        b"application/json;\r\ncharset=utf-8",
    ):
        assert not chapter_sessions._has_draft_operation_json_content_type(
            request_with_content_type(value)
        )

    assert chapter_sessions._has_draft_operation_json_content_type(
        request_with_content_type(
            b'Application/JSON\t;\tcharset\t=\t"UTF-8"\t'
        )
    )


def test_formal_operation_reads_are_owner_scoped_and_never_start_provider_work():
    client, service, repository = make_client()

    status = client.get(operation_path())
    events = client.get(f"{operation_path()}/events?after=0")
    missing = client.get(operation_path("30000000-0000-0000-0000-000000000099"))

    assert status.status_code == 200
    assert status.json()["id"] == OPERATION_ID
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
                "resultContentHash": OUTPUT_HASH,
            },
        ],
        "lastEventSequence": 2,
        "nextAfter": 2,
        "hasMore": False,
    }
    assert missing.status_code == 404
    assert missing.json()["code"] == "DraftOperationNotFound"
    assert service.commands == []
    assert service.reads == [
        (PROJECT_ID, SESSION_ID, OPERATION_ID),
        (PROJECT_ID, SESSION_ID, OPERATION_ID),
        (PROJECT_ID, SESSION_ID, "30000000-0000-0000-0000-000000000099"),
    ]
    assert repository.operation_reads == []
    assert repository.event_reads == [(OPERATION_ID, 0, 100)]


def test_formal_operation_status_fails_closed_for_cross_owner_or_malformed_result():
    client, service, _ = make_client()

    for result in (
        replace(service.result, project_id=OTHER_PROJECT_ID),
        replace(service.result, partial_output_hash=HASH),
        object(),
    ):
        service.result = result
        response = client.get(operation_path())

        assert response.status_code == 404
        assert response.json()["code"] == "DraftOperationNotFound"


def test_cancelled_projection_requires_a_positive_integer_result_revision():
    client, service, _ = make_client()

    for revision in (True, "2", 0, -1):
        service.result = replace(
            service.result,
            status="cancelled",
            result_working_draft_revision=revision,
        )
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


@pytest.mark.parametrize(
    ("event_type", "payload"),
    (
        (
            "delta",
            {
                "text": OUTPUT,
                "partialOutputHash": OUTPUT_HASH,
                "partialOutputScalars": len(OUTPUT),
            },
        ),
        ("heartbeat", None),
    ),
)
def test_terminal_operation_requires_its_terminal_event_at_the_last_sequence(
    event_type,
    payload,
):
    client, _, repository = make_client()
    repository.events = [
        stored_event(1, "started"),
        stored_event(2, event_type, payload),
    ]

    response = client.get(f"{operation_path()}/events?after=0")

    assert response.status_code == 404
    assert response.json()["code"] == "DraftOperationNotFound"


def test_formal_operation_events_require_failure_payload_to_match_stored_result():
    client, service, repository = make_client()
    service.result = replace(
        service.result,
        status="failed",
        partial_output="",
        partial_output_hash=EMPTY_HASH,
        partial_output_scalars=0,
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


@pytest.mark.parametrize(
    ("status", "payload", "expected_terminal"),
    (
        (
            "failed",
            {"failureCode": "DraftProviderFailed"},
            {"failureCode": "DraftProviderFailed"},
        ),
        (
            "cancelled",
            {
                "resultWorkingDraftRevision": 2,
                "resultContentHash": OUTPUT_HASH,
            },
            {
                "resultWorkingDraftRevision": 2,
                "resultContentHash": OUTPUT_HASH,
            },
        ),
    ),
)
def test_formal_operation_events_project_closed_failure_and_cancel(
    status,
    payload,
    expected_terminal,
):
    client, service, repository = make_client()
    if status == "failed":
        service.result = replace(
            service.result,
            status=status,
            partial_output="",
            partial_output_hash=EMPTY_HASH,
            partial_output_scalars=0,
            result_working_draft_revision=None,
            result_content_hash=None,
            failure_code="DraftProviderFailed",
        )
    else:
        service.result = replace(service.result, status=status)
    repository.events = [
        stored_event(1, "started"),
        stored_event(2, status, payload),
    ]

    response = client.get(f"{operation_path()}/events?after=0")

    assert response.status_code == 200
    terminal = response.json()["events"][-1]
    assert terminal == {
        "sequence": 2,
        "type": status,
        "createdAt": 101,
        **expected_terminal,
    }


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
        "resultContentHash": OUTPUT_HASH,
    }]
    assert terminal_only.json()["lastEventSequence"] == 2
    assert terminal_only.json()["nextAfter"] == 2
    assert terminal_only.json()["hasMore"] is False
    assert exhausted.status_code == 200
    assert exhausted.json() == {
        "operationId": OPERATION_ID,
        "events": [],
        "lastEventSequence": 2,
        "nextAfter": 2,
        "hasMore": False,
    }
    assert repository.event_reads == [(OPERATION_ID, 1, 100), (OPERATION_ID, 2, 100)]


def test_formal_operation_events_project_delta_and_heartbeat_closed_payloads():
    client, service, repository = make_client()
    service.result = replace(
        service.result,
        status="running",
        last_event_sequence=3,
        result_working_draft_revision=None,
        result_content_hash=None,
    )
    repository.events = [
        stored_event(1, "started"),
        stored_event(2, "delta", {
            "text": OUTPUT,
            "partialOutputHash": OUTPUT_HASH,
            "partialOutputScalars": len(OUTPUT),
        }),
        stored_event(3, "heartbeat"),
    ]

    response = client.get(f"{operation_path()}/events?after=0")

    assert response.status_code == 200
    assert response.json() == {
        "operationId": OPERATION_ID,
        "events": [
            {"sequence": 1, "type": "started", "createdAt": 100},
            {
                "sequence": 2,
                "type": "delta",
                "createdAt": 101,
                "text": OUTPUT,
                "partialOutputHash": OUTPUT_HASH,
                "partialOutputScalars": len(OUTPUT),
            },
            {"sequence": 3, "type": "heartbeat", "createdAt": 102},
        ],
        "lastEventSequence": 3,
        "nextAfter": 3,
        "hasMore": False,
    }


def test_formal_operation_delta_after_cursor_exposes_only_the_new_suffix():
    client, service, repository = make_client()
    cumulative = "甲乙"
    cumulative_hash = hashlib.sha256(cumulative.encode("utf-8")).hexdigest()
    service.result = replace(
        service.result,
        status="running",
        last_event_sequence=9,
        partial_output=cumulative,
        partial_output_hash=cumulative_hash,
        partial_output_scalars=len(cumulative),
        result_working_draft_revision=None,
        result_content_hash=None,
    )
    repository.events = [stored_event(9, "delta", {
        "text": "乙",
        "partialOutputHash": cumulative_hash,
        "partialOutputScalars": len(cumulative),
    })]

    response = client.get(f"{operation_path()}/events?after=8")

    assert response.status_code == 200
    assert response.json()["events"] == [{
        "sequence": 9,
        "type": "delta",
        "createdAt": 108,
        "text": "乙",
        "partialOutputHash": cumulative_hash,
        "partialOutputScalars": len(cumulative),
    }]


def test_formal_operation_delta_after_cursor_rejects_invalid_unicode_text():
    client, service, repository = make_client()
    service.result = replace(
        service.result,
        status="running",
        last_event_sequence=9,
        result_working_draft_revision=None,
        result_content_hash=None,
    )
    repository.events = [stored_event(9, "delta", {
        "text": "\ud800",
        "partialOutputHash": OUTPUT_HASH,
        "partialOutputScalars": 99,
    })]

    response = client.get(f"{operation_path()}/events?after=8")

    assert response.status_code == 404
    assert response.json()["code"] == "DraftOperationNotFound"


def test_formal_operation_events_page_at_one_hundred_with_truthful_envelope():
    client, service, repository = make_client()
    service.result = replace(service.result, last_event_sequence=137)
    repository.events = [stored_event(1, "started")]
    repository.events.extend(
        stored_event(sequence, "heartbeat") for sequence in range(2, 137)
    )
    repository.events.append(stored_event(137, "completed", {
        "resultWorkingDraftRevision": 2,
        "resultContentHash": OUTPUT_HASH,
    }))

    first = client.get(f"{operation_path()}/events?after=0")
    second = client.get(f"{operation_path()}/events?after=100")

    assert first.status_code == 200
    assert len(first.json()["events"]) == 100
    assert first.json()["events"][-1]["sequence"] == 100
    assert first.json() | {"events": []} == {
        "operationId": OPERATION_ID,
        "events": [],
        "lastEventSequence": 137,
        "nextAfter": 100,
        "hasMore": True,
    }
    assert second.status_code == 200
    assert len(second.json()["events"]) == 37
    assert second.json()["events"][-1]["type"] == "completed"
    assert second.json()["nextAfter"] == 137
    assert second.json()["hasMore"] is False


def test_formal_operation_events_fail_closed_for_an_incomplete_page():
    client, service, repository = make_client()
    service.result = replace(service.result, last_event_sequence=3)
    repository.events = [stored_event(1, "started")]

    response = client.get(f"{operation_path()}/events?after=0")

    assert response.status_code == 404
    assert response.json()["code"] == "DraftOperationNotFound"


def test_active_event_page_uses_the_service_snapshot_when_a_new_tail_arrives():
    client, service, repository = make_client()
    service.result = replace(
        service.result,
        status="running",
        result_working_draft_revision=None,
        result_content_hash=None,
    )
    repository.events = [
        stored_event(1, "started"),
        stored_event(2, "delta", {
            "text": OUTPUT,
            "partialOutputHash": OUTPUT_HASH,
            "partialOutputScalars": len(OUTPUT),
        }),
        stored_event(3, "heartbeat"),
    ]

    response = client.get(f"{operation_path()}/events?after=0")

    assert response.status_code == 200
    assert [event["sequence"] for event in response.json()["events"]] == [1, 2]
    assert response.json()["lastEventSequence"] == 2
    assert response.json()["nextAfter"] == 2
    assert response.json()["hasMore"] is False


def test_cancel_formal_operation_accepts_only_absent_body_or_exact_empty_object():
    client, service, _ = make_client()
    service.result = replace(service.result, status="cancelled")
    cancel_path = f"{operation_path()}/cancel"

    absent = client.post(cancel_path)
    empty_object = client.post(
        cancel_path,
        content=b"{}",
        headers={"content-type": "application/json"},
    )

    assert absent.status_code == 200
    assert empty_object.status_code == 200
    assert absent.json()["status"] == "cancelled"
    assert absent.json()["partialOutput"] == OUTPUT
    assert service.cancels == [
        (PROJECT_ID, SESSION_ID, OPERATION_ID),
        (PROJECT_ID, SESSION_ID, OPERATION_ID),
    ]


def test_cancel_formal_operation_rejects_nonempty_or_noncanonical_requests():
    client, service, _ = make_client()
    cancel_path = f"{operation_path()}/cancel"
    requests = (
        ({
            "content": b'{"reason":"stop"}',
            "headers": {"content-type": "application/json"},
        }),
        ({
            "content": b'{"x":1,"x":1}',
            "headers": {"content-type": "application/json"},
        }),
        ({"content": b"[]", "headers": {"content-type": "application/json"}}),
        ({"content": b"{}", "headers": {"content-type": "text/plain"}}),
        ({"content": b"", "headers": {"content-type": "application/json"}}),
        ({"content": b" " * 1025, "headers": {"content-type": "application/json"}}),
    )

    for request in requests:
        response = client.post(cancel_path, **request)
        assert response.status_code == 422
        assert response.json()["code"] == "DraftOperationRequestInvalid"

    wrong_owner = client.post(
        f"/api/projects/not-a-uuid/chapter-sessions/{SESSION_ID}/"
        f"draft-operations/{OPERATION_ID}/cancel"
    )
    assert wrong_owner.status_code == 404
    assert wrong_owner.json()["code"] == "DraftOperationNotFound"
    assert service.cancels == []


def test_status_events_and_cancel_hide_storage_failures():
    client, service, _ = make_client()
    service.error = DraftOperationStorageError("LEAK-SENTINEL")

    responses = (
        client.get(operation_path()),
        client.get(f"{operation_path()}/events?after=0"),
        client.post(f"{operation_path()}/cancel"),
    )

    for response in responses:
        assert response.status_code == 502
        assert response.json()["code"] == "DraftOperationUnavailable"
        assert "LEAK-SENTINEL" not in response.text


def test_events_hide_native_repository_failures():
    client, _, repository = make_client()
    repository.error = RuntimeError("LEAK-SENTINEL")

    response = client.get(f"{operation_path()}/events?after=0")

    assert response.status_code == 502
    assert response.json()["code"] == "DraftOperationUnavailable"
    assert "LEAK-SENTINEL" not in response.text


@pytest.mark.asyncio
async def test_cancel_reader_rejects_duplicate_content_type_without_reading_body():
    reads = 0

    async def receive():
        nonlocal reads
        reads += 1
        return {"type": "http.request", "body": b"{}", "more_body": False}

    request = Request({
        "type": "http",
        "method": "POST",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-type", b"application/json"),
        ],
    }, receive)

    with pytest.raises(chapter_sessions.DraftOperationRequestInvalid):
        await chapter_sessions._read_empty_cancel_body(request)

    assert reads == 0


def test_formal_operation_read_rejects_noncanonical_owner_before_repository_access():
    client, service, repository = make_client()

    response = client.get(
        "/api/projects/not-a-uuid/chapter-sessions/"
        f"{SESSION_ID}/draft-operations/{OPERATION_ID}"
    )

    assert response.status_code == 404
    assert response.json()["code"] == "DraftOperationNotFound"
    assert service.commands == []
    assert service.reads == []
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
