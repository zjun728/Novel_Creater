from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.domain.routers import manuscripts
from backend.database import DatabaseUnavailable, read_only_transaction
from backend.security.redaction import install_error_handlers
from backend.services.manuscripts import (
    FinalChapterNotFound, ManuscriptChapterDetailResponse,
    ManuscriptChapterResponse, ManuscriptDirectoryResponse,
    ManuscriptIntegrityFailure, ManuscriptNavigationResponse,
    ManuscriptOutlineResponse, ManuscriptProjectNotFound,
    ManuscriptSummaryResponse, ManuscriptTemporarilyUnavailable,
    ManuscriptVolumeDetailResponse,
)


class Service:
    def __init__(self):
        self.error = None
        self.calls = []

    async def directory(self, project_id):
        self.calls.append(("directory", project_id))
        if self.error:
            raise self.error
        return ManuscriptDirectoryResponse(projectId=project_id, title="Book", lifecycle="active", summary=ManuscriptSummaryResponse(finalChapterCount=0, totalScalarCount=0), volumes=())

    async def chapter(self, project_id, chapter_number):
        self.calls.append(("chapter", project_id, chapter_number))
        if self.error:
            raise self.error
        if chapter_number == 9:
            return ManuscriptChapterDetailResponse(
                projectId=project_id, projectTitle="Book", lifecycle="archived",
                volume=ManuscriptVolumeDetailResponse(id="volume-safe", order=2, title="Two"),
                chapter=ManuscriptChapterResponse(number=9, title="Nine", content="target prose", scalarCount=12, finalizedAt="1970-01-01T00:00:01Z"),
                outline=ManuscriptOutlineResponse(chapterGoal="Goal", expectedCharacters=("A",), continuation=("Next",), plannedTasks=("Task",), scenes=("Scene",), forbiddenEarlyEvents=("Never",)),
                navigation=ManuscriptNavigationResponse(previousChapterNumber=2, nextChapterNumber=None),
            )
        raise FinalChapterNotFound()


def _client():
    app = FastAPI()
    install_error_handlers(app)
    service = Service()
    app.include_router(manuscripts.router, prefix="/api")
    app.dependency_overrides[manuscripts.get_manuscript_reading_service] = lambda: service
    return TestClient(app, raise_server_exceptions=False), service


def test_production_manuscript_router_uses_database_enforced_read_only_boundary():
    assert manuscripts._service._transaction_factory is read_only_transaction


class BoundaryFailure:
    def __init__(self, error, *, on_exit=False):
        self.error = error
        self.on_exit = on_exit

    def __call__(self):
        return self

    async def __aenter__(self):
        if not self.on_exit:
            raise self.error
        return object()

    async def __aexit__(self, exc_type, exc, traceback):
        if self.on_exit:
            raise self.error


class UnusedRepository:
    async def load_directory(self, session, project_id):
        pytest.fail("repository must not run when transaction boundary fails")

    async def load_chapter(self, session, project_id, chapter_number):
        pytest.fail("repository must not run when transaction boundary fails")


def _boundary_client(error, *, on_exit=False):
    from backend.services.manuscripts import ManuscriptReadingService

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(manuscripts.router, prefix="/api")
    app.dependency_overrides[manuscripts.get_manuscript_reading_service] = lambda: ManuscriptReadingService(
        BoundaryFailure(error, on_exit=on_exit), UnusedRepository(),
    )
    return TestClient(app, raise_server_exceptions=False)


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


def test_chapter_path_accepts_only_bounded_positive_ascii_decimal_numbers():
    client, service = _client()

    invalid_values = [
        "0", "-1", "1.0", "1e2", "+1", " 1", "1 ",
        "%C2%A01", "true", "9" * 4301,
    ]
    responses = [
        client.get(f"/api/projects/project-1/manuscript/chapters/{value}")
        for value in invalid_values
    ]

    assert all(response.status_code == 422 for response in responses)
    assert all(response.json()["code"] == "ManuscriptRequestInvalid" for response in responses)
    assert service.calls == []

    valid = client.get("/api/projects/project-1/manuscript/chapters/2147483647")
    too_large = client.get("/api/projects/project-1/manuscript/chapters/2147483648")
    assert valid.status_code == 404
    assert valid.json()["code"] == "FinalChapterNotFound"
    assert too_large.status_code == 422
    assert too_large.json()["code"] == "ManuscriptRequestInvalid"
    assert service.calls == [("chapter", "project-1", 2147483647)]


def test_chapter_success_is_exact_content_only_projection_with_headers():
    client, _ = _client()

    response = client.get("/api/projects/project-1/manuscript/chapters/9")

    assert response.status_code == 200
    assert response.json() == {
        "projectId": "project-1", "projectTitle": "Book", "lifecycle": "archived",
        "volume": {"id": "volume-safe", "order": 2, "title": "Two"},
        "chapter": {"number": 9, "title": "Nine", "content": "target prose", "scalarCount": 12, "finalizedAt": "1970-01-01T00:00:01Z"},
        "outline": {"chapterGoal": "Goal", "expectedCharacters": ["A"], "continuation": ["Next"], "plannedTasks": ["Task"], "scenes": ["Scene"], "forbiddenEarlyEvents": ["Never"]},
        "navigation": {"previousChapterNumber": 2, "nextChapterNumber": None},
    }
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert set(response.json()["outline"]) == {"chapterGoal", "expectedCharacters", "continuation", "plannedTasks", "scenes", "forbiddenEarlyEvents"}


def test_both_routes_reject_blank_and_duplicate_unknown_query_parameters():
    client, service = _client()

    responses = [
        client.get("/api/projects/project-1/manuscript?unknown="),
        client.get("/api/projects/project-1/manuscript?unknown=a&unknown=b"),
        client.get("/api/projects/project-1/manuscript/chapters/9?unknown="),
        client.get("/api/projects/project-1/manuscript/chapters/9?unknown=a&unknown=b"),
    ]

    assert all(response.status_code == 422 for response in responses)
    assert all(response.json()["code"] == "ManuscriptRequestInvalid" for response in responses)
    assert service.calls == []


@pytest.mark.parametrize(
    "url,error,status,code,message",
    [
        ("/api/projects/project-1/manuscript", ManuscriptProjectNotFound, 404, "ManuscriptProjectNotFound", "Manuscript project not found"),
        ("/api/projects/project-1/manuscript", ManuscriptIntegrityFailure, 500, "ManuscriptIntegrityFailure", "Finalized manuscript could not be read"),
        ("/api/projects/project-1/manuscript", ManuscriptTemporarilyUnavailable, 503, "ManuscriptTemporarilyUnavailable", "Finalized manuscript is temporarily unavailable"),
        ("/api/projects/project-1/manuscript/chapters/9", ManuscriptProjectNotFound, 404, "ManuscriptProjectNotFound", "Manuscript project not found"),
        ("/api/projects/project-1/manuscript/chapters/9", FinalChapterNotFound, 404, "FinalChapterNotFound", "Finalized chapter not found"),
        ("/api/projects/project-1/manuscript/chapters/9", ManuscriptIntegrityFailure, 500, "ManuscriptIntegrityFailure", "Finalized manuscript could not be read"),
        ("/api/projects/project-1/manuscript/chapters/9", ManuscriptTemporarilyUnavailable, 503, "ManuscriptTemporarilyUnavailable", "Finalized manuscript is temporarily unavailable"),
    ],
)
def test_applicable_error_matrix_has_exact_safe_public_body(
    url, error, status, code, message,
):
    client, service = _client()
    tokens = (
        "project-internal-7", "stored-record-9", "sha256:deadbeef",
        "chapter.content", "SELECT final_content FROM final_chapters",
        "private prose fragment", '{"raw":"json"}', "RuntimeError: raw exception",
    )
    service.error = error(" | ".join(tokens))

    response = client.get(url)

    assert response.status_code == status
    assert response.json()["code"] == code
    assert response.json()["message"] == message
    assert set(response.json()) == {"code", "message", "correlationId"}
    assert all(token not in response.text for token in tokens)
    assert all(token not in response.text for token in ("projectId", "volumes", '"content"', '"outline"'))


@pytest.mark.parametrize(
    "url",
    [
        "/api/projects/project-1/manuscript?invalid=",
        "/api/projects/project-1/manuscript/chapters/9?invalid=",
    ],
)
def test_request_invalid_has_fixed_safe_public_body_without_partial_data(url):
    client, _ = _client()

    response = client.get(url)

    assert response.status_code == 422
    assert response.json()["code"] == "ManuscriptRequestInvalid"
    assert response.json()["message"] == "Manuscript request is invalid"
    assert set(response.json()) == {"code", "message", "correlationId"}
    assert all(token not in response.text for token in ("projectId", "volumes", '"content"', '"outline"'))


@pytest.mark.parametrize("url", [
    "/api/projects/project-1/manuscript",
    "/api/projects/project-1/manuscript/chapters/9",
])
@pytest.mark.parametrize("on_exit", [False, True])
def test_database_read_only_boundary_unavailability_is_public_503_without_partial_data(
    url, on_exit,
):
    response = _boundary_client(DatabaseUnavailable(), on_exit=on_exit).get(url)

    assert response.status_code == 503
    assert response.json()["code"] == "ManuscriptTemporarilyUnavailable"
    assert response.json()["message"] == "Finalized manuscript is temporarily unavailable"
    assert set(response.json()) == {"code", "message", "correlationId"}
    assert all(token not in response.text for token in ("projectId", "volumes", '"content"', '"outline"'))


def test_programmer_transaction_error_is_not_mapped_to_manuscript_503():
    response = _boundary_client(RuntimeError("programmer failure")).get(
        "/api/projects/project-1/manuscript",
    )

    assert response.status_code == 500
    assert response.json()["message"] == "Internal server error"
    assert response.json().get("code") != "ManuscriptTemporarilyUnavailable"
