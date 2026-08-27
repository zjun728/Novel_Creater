from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.routers import manuscripts
from backend.security.redaction import install_error_handlers
from backend.services.manuscripts import (
    FinalChapterNotFound, ManuscriptDirectoryResponse, ManuscriptIntegrityFailure,
    ManuscriptProjectNotFound, ManuscriptTemporarilyUnavailable,
)


class Service:
    def __init__(self):
        self.error = None
        self.calls = []

    async def directory(self, project_id):
        self.calls.append(("directory", project_id))
        if self.error:
            raise self.error
        return ManuscriptDirectoryResponse(projectId=project_id, title="Book", lifecycle="active", summary={"finalChapterCount": 0, "totalScalarCount": 0}, volumes=())

    async def chapter(self, project_id, chapter_number):
        self.calls.append(("chapter", project_id, chapter_number))
        if self.error:
            raise self.error
        raise FinalChapterNotFound()


def _client():
    app = FastAPI()
    install_error_handlers(app)
    service = Service()
    app.include_router(manuscripts.router, prefix="/api")
    app.dependency_overrides[manuscripts.get_manuscript_reading_service] = lambda: service
    return TestClient(app, raise_server_exceptions=False), service


def test_directory_shape_headers_and_closed_query_contract():
    client, service = _client()
    response = client.get("/api/projects/project-1/manuscript")
    invalid = client.get("/api/projects/project-1/manuscript?raw=RAW_PROSE_SENTINEL")

    assert response.status_code == 200
    assert response.json() == {"projectId": "project-1", "title": "Book", "lifecycle": "active", "summary": {"finalChapterCount": 0, "totalScalarCount": 0}, "volumes": []}
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "ManuscriptRequestInvalid"
    assert "RAW_PROSE_SENTINEL" not in invalid.text
    assert service.calls == [("directory", "project-1")]


def test_chapter_parses_path_locally_and_maps_public_error_matrix_without_leaks():
    client, service = _client()
    for error, status, code in [
        (ManuscriptProjectNotFound("RAW_PROSE_SENTINEL HASH_SENTINEL"), 404, "ManuscriptProjectNotFound"),
        (FinalChapterNotFound("RAW_PROSE_SENTINEL HASH_SENTINEL"), 404, "FinalChapterNotFound"),
        (ManuscriptIntegrityFailure("RAW_PROSE_SENTINEL HASH_SENTINEL"), 500, "ManuscriptIntegrityFailure"),
        (ManuscriptTemporarilyUnavailable("RAW_PROSE_SENTINEL HASH_SENTINEL"), 503, "ManuscriptTemporarilyUnavailable"),
    ]:
        service.error = error
        response = client.get("/api/projects/project-1/manuscript/chapters/9")
        assert response.status_code == status
        assert response.json()["code"] == code
        assert set(response.json()) == {"code", "message", "correlationId"}
        assert "RAW_PROSE_SENTINEL" not in response.text and "HASH_SENTINEL" not in response.text

    service.error = None
    invalid = [
        client.get("/api/projects/project-1/manuscript/chapters/0"),
        client.get("/api/projects/project-1/manuscript/chapters/nope"),
        client.get("/api/projects/project-1/manuscript/chapters/9?raw=RAW_PROSE_SENTINEL"),
    ]
    assert all(response.status_code == 422 and response.json()["code"] == "ManuscriptRequestInvalid" for response in invalid)
    assert all("RAW_PROSE_SENTINEL" not in response.text for response in invalid)
