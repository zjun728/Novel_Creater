from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import chapter_outlines
from backend.security.redaction import install_error_handlers
from backend.domain.chapter_outlines import EditableChapterOutlineContent
from backend.services.chapter_outlines import (
    CanonProjectionAuthorityResult,
    ChapterOutlineBasisResult,
    ChapterOutlineCapabilities,
    ChapterOutlineDraftResult,
    ChapterOutlineOperationResult,
    ChapterOutlineRevisionResult,
    ChapterOutlineState,
    PlanningAuthorityResult,
)


HASH = "a" * 64


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
            operation_id="operation-1",
            status="pending",
            failure_code=None,
            loaded=False,
            loaded_draft_revision=None,
        )

    async def get_operation(self, project_id, operation_id):
        assert (project_id, operation_id) == ("p1", "operation-1")
        return await self.get_operation_by_key(project_id, "safe-key")


def _client():
    service = _FakeService()
    app = FastAPI()
    app.include_router(chapter_outlines.router, prefix="/api")
    app.dependency_overrides[chapter_outlines.get_chapter_outline_service] = (
        lambda: service
    )
    install_error_handlers(app)
    return TestClient(app, raise_server_exceptions=False), service


def test_static_current_route_is_registered_before_dynamic_chapter_route():
    client, _ = _client()
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
    client, _ = _client()
    response = client.post(
        "/api/projects/p1/chapter-outlines/1/drafts",
        json={"chapterNumber": 99},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "ChapterOutlineRequestInvalid"


def test_create_has_no_client_authority_or_idempotency_body():
    client, service = _client()

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
    client, _ = _client()

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
    client, service = _client()

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
    client, service = _client()

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
    client, _ = _client()

    by_key = client.get(
        "/api/projects/p1/chapter-outlines/operations/by-key/safe-key"
    )
    by_id = client.get(
        "/api/projects/p1/chapter-outlines/operations/operation-1"
    )

    assert by_key.status_code == 200
    assert by_id.status_code == 200
    assert by_key.json() == {
        "operationId": "operation-1",
        "status": "pending",
        "failureCode": None,
        "loaded": False,
        "loadedDraftRevision": None,
    }
