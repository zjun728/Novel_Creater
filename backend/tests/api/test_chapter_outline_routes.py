from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import chapter_outlines
from backend.repositories.chapter_sessions import ActiveChapterSessionConflict
from backend.security.redaction import install_error_handlers
from backend.domain.chapter_outlines import EditableChapterOutlineContent
from backend.services.chapter_outlines import (
    CanonProjectionAuthorityResult,
    ChapterOutlineBasisResult,
    ChapterOutlineCapabilities,
    ChapterOutlineDraftResult,
    ChapterOutlineRevisionResult,
    ChapterOutlineService,
    ChapterOutlineState,
    PlanningAuthorityResult,
)
from backend.services.chapter_outline_generation import (
    ChapterOutlineOperationResult,
    ChapterOutlineGenerationService,
    PublicModelSummary,
)


HASH = "a" * 64
OPERATION_ID = "11111111-1111-4111-8111-111111111111"


def _basis():
    return ChapterOutlineBasisResult(
        planning=PlanningAuthorityResult(
            planning_revision_id="planning-1",
            revision=2,
            content_hash=HASH,
            content=None,
        ),
        canon_projection=CanonProjectionAuthorityResult(
            canon_revision=3,
            projection_revision=3,
            content_hash=HASH,
            synchronized=True,
        ),
    )


def _draft():
    return ChapterOutlineDraftResult(
        project_id="p1",
        chapter_number=1,
        draft_id="draft-1",
        base_head_revision=0,
        draft_revision=1,
        content_hash=HASH,
        content=EditableChapterOutlineContent(),
        basis=_basis(),
        status="active",
    )


class _FakeService:
    def __init__(self):
        self.commands = []

    async def get_current(self, project_id):
        assert project_id == "p1"
        return ChapterOutlineState(
            project_id=project_id,
            lifecycle="active",
            authoritative_chapter_number=1,
            target_path="/projects/p1/planning/story-blocks",
            planning_authority=None,
            canon_projection_authority=None,
            confirmed_outline=None,
            draft=None,
            active_session=None,
            capabilities=ChapterOutlineCapabilities(
                view=True,
                create_draft=False,
                edit_draft=False,
                generate=False,
                confirm=False,
                start_session=False,
            ),
            reasons=("planningUnavailable",),
        )

    async def create_draft(self, command):
        self.commands.append(command)
        return _draft()

    async def save_draft(self, command):
        self.commands.append(command)
        return _draft()

    async def confirm_draft(self, command):
        self.commands.append(command)
        return ChapterOutlineRevisionResult(
            project_id="p1",
            chapter_number=1,
            outline_revision_id="outline-1",
            revision=1,
            parent_revision=0,
            content_hash=HASH,
            content=EditableChapterOutlineContent(),
            basis=_basis(),
        )

    async def get_operation_by_key(self, project_id, key):
        assert (project_id, key) == ("p1", "safe-key")
        return ChapterOutlineOperationResult(
            operation_id=OPERATION_ID,
            status="pending",
            failure_code=None,
            model=PublicModelSummary(
                provider_id="provider-1",
                model_name="test-model",
            ),
            loaded=False,
            loaded_draft_revision=None,
        )

    async def get_operation(self, project_id, operation_id):
        assert (project_id, operation_id) == ("p1", OPERATION_ID)
        return await self.get_operation_by_key(project_id, "safe-key")


class _FakeGenerationService(_FakeService):
    async def generate(self, command):
        self.commands.append(command)
        return await self.get_operation_by_key(
            command.project_id,
            command.idempotency_key,
        )


def _client(generation_service=None, service=None):
    service = service or _FakeService()
    generation_service = generation_service or _FakeGenerationService()
    app = FastAPI()
    app.include_router(chapter_outlines.router, prefix="/api")
    app.dependency_overrides[chapter_outlines.get_chapter_outline_service] = (
        lambda: service
    )
    app.dependency_overrides[
        chapter_outlines.get_chapter_outline_generation_service
    ] = lambda: generation_service
    install_error_handlers(app)
    return (
        TestClient(app, raise_server_exceptions=False),
        service,
        generation_service,
    )


class _Transaction:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _AuthorityOutlineRepository:
    async def read_project_any(self, session, project_id):
        return {"id": project_id, "archived_at": None}

    async def lock_project(self, session, project_id):
        return {"id": project_id, "archived_at": None}


class _SplitActiveSessionRepository:
    async def read_active_session(self, session, project_id):
        raise ActiveChapterSessionConflict(
            "raw SQL row AUTHORITY-SPLIT-SENTINEL"
        )


def _split_authority_service():
    return ChapterOutlineService(
        _AuthorityOutlineRepository(),
        _SplitActiveSessionRepository(),
        transaction_factory=_Transaction,
    )


def _assert_safe_authority_conflict(response):
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "ChapterOutlineConflict"
    assert body["message"] == (
        "Chapter outline state changed; refresh and retry"
    )
    assert isinstance(body["correlationId"], str)
    for forbidden in ("AUTHORITY-SPLIT-SENTINEL", "raw", "SQL", "row"):
        assert forbidden not in response.text


def test_current_route_maps_split_active_session_to_safe_conflict():
    client, _, _ = _client(service=_split_authority_service())

    response = client.get("/api/projects/p1/chapter-outlines/current")

    _assert_safe_authority_conflict(response)


def test_create_route_maps_split_active_session_to_safe_conflict():
    client, _, _ = _client(service=_split_authority_service())

    response = client.post(
        "/api/projects/p1/chapter-outlines/1/drafts",
        json={},
    )

    _assert_safe_authority_conflict(response)


def test_static_current_route_is_registered_before_dynamic_chapter_route():
    client, _, _ = _client()
    response = client.get("/api/projects/p1/chapter-outlines/current")

    assert response.status_code == 200
    assert set(response.json()) == {
        "projectId",
        "lifecycle",
        "authoritativeChapterNumber",
        "targetPath",
        "planningAuthority",
        "canonProjectionAuthority",
        "confirmedOutline",
        "draft",
        "activeSession",
        "capabilities",
        "reasons",
    }


def test_current_projector_does_not_accept_arbitrary_mapping_bypass():
    with pytest.raises(AttributeError):
        chapter_outlines._public_state(
            {"content_json": {"internal": True}}
        )


def test_create_body_is_closed():
    client, _, _ = _client()
    response = client.post(
        "/api/projects/p1/chapter-outlines/1/drafts",
        json={"chapterNumber": 99},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "ChapterOutlineRequestInvalid"


def test_create_has_no_client_authority_or_idempotency_body():
    client, service, _ = _client()

    response = client.post(
        "/api/projects/p1/chapter-outlines/1/drafts",
        json={},
    )

    assert response.status_code == 201
    assert service.commands[0].project_id == "p1"
    assert service.commands[0].chapter_number == 1
    assert response.json()["status"] == "current"
    assert set(response.json()) == {
        "projectId",
        "chapterNumber",
        "draftId",
        "baseHeadRevision",
        "draftRevision",
        "contentHash",
        "content",
        "basis",
        "status",
    }


def test_save_rejects_server_owned_fields_inside_editable_content():
    client, _, _ = _client()

    response = client.put(
        "/api/projects/p1/chapter-outlines/1/drafts/draft-1",
        json={
            "expectedDraftRevision": 1,
            "expectedDraftHash": HASH,
            "content": {
                "schemaVersion": "chapter-outline-draft-v1",
                "chapterNumber": 1,
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "ChapterOutlineRequestInvalid"


def test_save_projects_internal_active_draft_as_current():
    client, service, _ = _client()

    response = client.put(
        "/api/projects/p1/chapter-outlines/1/drafts/draft-1",
        json={
            "expectedDraftRevision": 1,
            "expectedDraftHash": HASH,
            "content": EditableChapterOutlineContent().model_dump(
                mode="json",
                by_alias=True,
            ),
        },
    )

    assert response.status_code == 200
    assert service.commands[0].draft_id == "draft-1"
    assert response.json()["status"] == "current"


def test_confirm_projects_closed_command_and_response():
    client, service, _ = _client()

    response = client.post(
        "/api/projects/p1/chapter-outlines/1/drafts/draft-1/confirm",
        json={
            "expectedDraftRevision": 1,
            "expectedDraftHash": HASH,
            "expectedHeadRevision": 0,
            "idempotencyKey": "confirm-outline-1",
        },
    )

    assert response.status_code == 201
    assert service.commands[0].expected_head_revision == 0
    assert service.commands[0].idempotency_key == "confirm-outline-1"
    assert "content_json" not in response.text
    assert "manifest" not in response.text
    assert "attempt" not in response.text


def test_static_operation_routes_do_not_bind_as_chapter_numbers():
    client, _, _ = _client()

    by_key = client.get(
        "/api/projects/p1/chapter-outlines/operations/by-key/safe-key"
    )
    by_id = client.get(
        f"/api/projects/p1/chapter-outlines/operations/{OPERATION_ID}"
    )

    assert by_key.status_code == 200
    assert by_id.status_code == 200
    assert by_key.json() == {
        "operationId": OPERATION_ID,
        "status": "pending",
        "failureCode": None,
        "model": {
            "providerId": "provider-1",
            "modelName": "test-model",
        },
        "loaded": False,
        "loadedDraftRevision": None,
    }


def test_generate_route_has_closed_body_and_projects_only_public_summary():
    client, _, generation = _client()

    response = client.post(
        "/api/projects/p1/chapter-outlines/1/drafts/draft-1/generate",
        json={
            "draftRevision": 1,
            "draftHash": HASH,
            "idempotencyKey": "safe-key",
            "authorInstructions": "强化人物选择。",
        },
    )

    assert response.status_code == 200
    assert generation.commands[0].chapter_number == 1
    assert generation.commands[0].draft_id == "draft-1"
    assert response.json() == {
        "operationId": OPERATION_ID,
        "status": "pending",
        "failureCode": None,
        "model": {
            "providerId": "provider-1",
            "modelName": "test-model",
        },
        "loaded": False,
        "loadedDraftRevision": None,
    }
    assert all(
        marker not in response.text.casefold()
        for marker in (
            "manifest",
            "prompt",
            "raw",
            "api_key",
            "authorization",
            "password",
            "dsn",
        )
    )

    closed = client.post(
        "/api/projects/p1/chapter-outlines/1/drafts/draft-1/generate",
        json={
            "draftRevision": 1,
            "draftHash": HASH,
            "idempotencyKey": "safe-key",
            "authorInstructions": "",
            "planningRevision": 99,
        },
    )
    assert closed.status_code == 422
    assert closed.json()["code"] == "ChapterOutlineRequestInvalid"


class _CorruptGenerationService:
    def __init__(self, result):
        self.result = result

    async def generate(self, _command):
        return self.result

    async def get_operation(self, _project_id, _operation_id):
        return self.result

    async def get_operation_by_key(self, _project_id, _key):
        return self.result


def _corrupt_result(**overrides):
    values = {
        "operation_id": OPERATION_ID,
        "status": "pending",
        "failure_code": None,
        "model": PublicModelSummary("provider-1", "test-model"),
        "loaded": False,
        "loaded_draft_revision": None,
    }
    values.update(overrides)
    return ChapterOutlineOperationResult(**values)


@pytest.mark.parametrize(
    ("method", "path", "json_body", "result", "sentinel"),
    (
        (
            "post",
            "/api/projects/p1/chapter-outlines/1/drafts/draft-1/generate",
            {
                "draftRevision": 1,
                "draftHash": HASH,
                "idempotencyKey": "safe-key",
                "authorInstructions": "",
            },
            _corrupt_result(
                operation_id="api_key=PUBLIC_OPERATION_SENTINEL"
            ),
            "PUBLIC_OPERATION_SENTINEL",
        ),
        (
            "get",
            f"/api/projects/p1/chapter-outlines/operations/{OPERATION_ID}",
            None,
            _corrupt_result(
                status="succeeded",
                loaded=True,
                loaded_draft_revision="MALICIOUS_PRIVATE_VALUE",
            ),
            "MALICIOUS_PRIVATE_VALUE",
        ),
        (
            "get",
            "/api/projects/p1/chapter-outlines/operations/by-key/safe-key",
            None,
            _corrupt_result(
                status="succeeded",
                loaded=True,
                loaded_draft_revision=0,
            ),
            "MALICIOUS_PRIVATE_VALUE",
        ),
    ),
)
def test_all_operation_routes_fail_closed_on_corrupt_direct_results(
    method,
    path,
    json_body,
    result,
    sentinel,
):
    client, _, _ = _client(_CorruptGenerationService(result))

    response = client.request(method, path, json=json_body)

    assert response.status_code == 409
    assert response.json()["code"] == "ChapterOutlineConflict"
    assert sentinel not in response.text


class _PersistedOperationService:
    def __init__(self, row):
        self.row = row

    async def generate(self, _command):
        return ChapterOutlineGenerationService._operation_result(self.row)

    async def get_operation(self, _project_id, _operation_id):
        return ChapterOutlineGenerationService._operation_result(self.row)

    async def get_operation_by_key(self, _project_id, _key):
        return ChapterOutlineGenerationService._operation_result(self.row)


def _persisted_operation_row(status, active_slot):
    row = {
        "operation_id": OPERATION_ID,
        "active_slot": active_slot,
        "status": status,
        "failure_code": None,
        "provider_id": "provider-1",
        "model_name_snapshot": "ACTIVE_SLOT_ROUTE_SENTINEL",
        "result_content": None,
        "result_content_hash": None,
        "loaded_outline_draft_revision": None,
        "loaded_at": None,
    }
    if status == "succeeded":
        row.update(
            result_content={"schemaVersion": "chapter-outline-draft-v1"},
            result_content_hash=HASH,
            loaded_outline_draft_revision=2,
            loaded_at=2_100_000_000_000,
        )
    elif status == "failed":
        row["failure_code"] = "ChapterOutlineProviderFailed"
    return row


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    (
        (
            "post",
            "/api/projects/p1/chapter-outlines/1/drafts/draft-1/generate",
            {
                "draftRevision": 1,
                "draftHash": HASH,
                "idempotencyKey": "safe-key",
                "authorInstructions": "",
            },
        ),
        (
            "get",
            f"/api/projects/p1/chapter-outlines/operations/{OPERATION_ID}",
            None,
        ),
        (
            "get",
            "/api/projects/p1/chapter-outlines/operations/by-key/safe-key",
            None,
        ),
    ),
)
@pytest.mark.parametrize(
    ("status", "active_slot"),
    (
        ("pending", None),
        ("succeeded", 1),
        ("failed", 1),
        ("superseded", 1),
    ),
)
def test_all_operation_routes_reject_corrupt_persisted_active_slots(
    method,
    path,
    json_body,
    status,
    active_slot,
):
    row = _persisted_operation_row(status, active_slot)
    client, _, _ = _client(_PersistedOperationService(row))

    response = client.request(method, path, json=json_body)

    assert response.status_code == 409
    assert response.json()["code"] == "ChapterOutlineConflict"
    assert "ACTIVE_SLOT_ROUTE_SENTINEL" not in response.text
