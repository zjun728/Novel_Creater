from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import projects, seeds
from backend.services.projects import ProjectResult


def test_seed_list_joins_selection_and_serializes_selected_status(monkeypatch):
    calls = []

    async def fetchall(sql, args=None):
        calls.append((" ".join(sql.split()), args))
        return [
            {
                "id": "seed-1",
                "project_id": "p1",
                "title": "Seed",
                "premise_json": '{"hook":"x"}',
                "content_hash": "a" * 64,
                "status": "selected",
                "created_at": 1,
            }
        ]

    monkeypatch.setattr(seeds, "fetchall", fetchall, raising=False)
    app = FastAPI()
    app.include_router(seeds.router, prefix="/api")
    client = TestClient(app)

    response = client.get("/api/projects/p1/seeds")

    assert response.status_code == 200
    assert response.json()[0]["status"] == "selected"
    assert response.json()[0]["premiseJSON"] == {"hook": "x"}
    assert "LEFT JOIN project_selected_seeds" in calls[0][0]


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
