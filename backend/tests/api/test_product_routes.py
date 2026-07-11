from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import projects, seeds
from backend.domain.seeds import SeedPayload
from backend.services.projects import ProjectResult
from backend.services.seeds import SeedResult


def test_seed_list_uses_service_dependency_and_revision_payload_contract():
    class FakeService:
        async def list(self, project_id):
            assert project_id == "p1"
            return (
                SeedResult(
                    id="seed-1", project_id="p1", status="candidate",
                    revision=1, revision_id="revision-1",
                    content_hash="a" * 64,
                    payload=SeedPayload(
                        title="Seed", genre="悬疑", logline="Logline",
                        protagonist="Protagonist", desire="Desire",
                        coreConflict="Conflict", worldPressure="Pressure",
                        openingHook="Hook", differentiation="Different",
                    ),
                    is_selected=True, selection_revision=1,
                ),
            )

    app = FastAPI()
    app.include_router(seeds.router, prefix="/api")
    app.dependency_overrides[seeds.get_seed_service] = FakeService
    client = TestClient(app)

    response = client.get("/api/projects/p1/seeds")

    assert response.status_code == 200
    body = response.json()[0]
    assert body["isSelected"] is True
    assert body["selectionRevision"] == 1
    assert body["payload"]["title"] == "Seed"
    assert "premiseJSON" not in body and "title" not in body
    assert not hasattr(seeds, "fetchall")


def test_project_routes_delegate_create_delete_and_public_content_state(monkeypatch):
    class FakeService:
        def __init__(self):
            self.created = None
            self.deleted = None

        async def create(self, command):
            self.created = command
            return ProjectResult.from_command(command)

        async def delete(self, project_id):
            self.deleted = project_id

        async def content_state(self, project_id):
            return {
                "seeds_count": 3,
                "canon_head_revision": 2,
                "has_final_chapters": True,
            }

    service = FakeService()
    monkeypatch.setattr(projects, "_service", service)
    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    client = TestClient(app)

    created = client.post(
        "/api/projects",
        json={
            "title": "Project",
            "genre": "历史",
            "description": "Description",
            "targetWords": 1000,
            "targetChapters": 10,
        },
    )
    assert created.status_code == 200
    assert service.created.title == "Project"
    assert service.created.target_words == 1000
    state = client.get(f"/api/projects/{service.created.id}/content-state")
    assert state.json() == {
        "seedsCount": 3,
        "canonHeadRevision": 2,
        "hasFinalChapters": True,
        "writerEnabled": False,
    }
    deleted = client.delete(f"/api/projects/{service.created.id}")
    assert deleted.json() == {"ok": True}
    assert service.deleted == service.created.id
