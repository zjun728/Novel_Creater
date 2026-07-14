from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import main
from backend.http_errors import ProjectNotFound
from backend.routers import assets, contracts, corpus, projects, seeds, story_engines
from backend.domain.seeds import SeedPayload
from backend.security.redaction import install_error_handlers
from backend.services.projects import ProjectResult
from backend.services.seeds import SeedResult


def test_joined_m2_routes_expose_public_behavior_through_dependencies():
    class FakeStoryEngineService:
        async def get(self, project_id, batch_id):
            assert (project_id, batch_id) == ("p1", "batch-1")
            return SimpleNamespace(
                id="batch-1",
                project_id="p1",
                source_type="manual",
                seed_id="seed-1",
                seed_revision_id="seed-revision-1",
                seed_hash="a" * 64,
                binding_revision_id="binding-revision-1",
                binding_hash="b" * 64,
                provider_id=None,
                model_name_snapshot=None,
                idempotency_key="joined-route-test",
                request_hash="c" * 64,
                status="succeeded",
                public_error_code=None,
                created_at="2026-07-14T00:00:00Z",
                finished_at="2026-07-14T00:00:01Z",
                options=(),
            )

    class FakeContractService:
        async def get_head(self, project_id):
            assert project_id == "p1"
            return {
                "project_id": "p1",
                "revision": 0,
                "has_contract": False,
                "contract_ready": False,
                "reasons": ("contractMissing",),
            }

    class FakeAssetService:
        async def list_styles(self):
            return ()

    class FakeCorpusService:
        async def discovery(self, cursor, limit):
            assert cursor is None and limit == 50
            return {
                "items": (),
                "nextCursor": None,
                "reasonCounts": {},
                "scanStrategy": "allowlist",
            }

    overrides = {
        story_engines.get_story_engine_service: lambda: FakeStoryEngineService(),
        contracts.get_contract_service: lambda: FakeContractService(),
        assets.get_asset_service: lambda: FakeAssetService(),
        corpus.get_corpus_service: lambda: FakeCorpusService(),
    }
    main.app.dependency_overrides.update(overrides)
    client = TestClient(main.app)
    try:
        batch = client.get("/api/projects/p1/story-engine-batches/batch-1")
        contract = client.get("/api/projects/p1/contracts/head")
        styles = client.get("/api/assets/style-templates")
        discovery = client.get("/api/corpus/discovery")
    finally:
        for dependency in overrides:
            main.app.dependency_overrides.pop(dependency, None)

    assert batch.status_code == 200
    assert batch.json()["id"] == "batch-1"
    assert contract.json() == {
        "projectId": "p1",
        "revision": 0,
        "hasContract": False,
        "contractReady": False,
        "reasons": ["contractMissing"],
    }
    assert styles.json() == []
    assert discovery.json() == {
        "items": [],
        "nextCursor": None,
        "reasonCounts": {},
        "scanStrategy": "allowlist",
    }


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


def test_archived_project_content_state_has_exact_domain_404(monkeypatch):
    class FakeService:
        async def content_state(self, project_id):
            assert project_id == "archived-project"
            raise ProjectNotFound()

    monkeypatch.setattr(projects, "_service", FakeService())
    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    install_error_handlers(app)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/projects/archived-project/content-state")

    assert response.status_code == 404
    assert set(response.json()) == {"code", "message", "correlationId"}
    assert response.json()["code"] == "ProjectNotFound"
    assert response.json()["message"] == ProjectNotFound.message
    assert response.json()["correlationId"]


def test_project_update_rejects_status_as_an_extra_field(monkeypatch):
    class FakeService:
        async def update(self, project_id, command):
            raise AssertionError("status payload must be rejected before service")

    monkeypatch.setattr(projects, "_service", FakeService())
    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    client = TestClient(app, raise_server_exceptions=False)

    response = client.put(
        "/api/projects/p1", json={"title": "Changed", "status": "drafting"}
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(item["loc"][-1] == "status" for item in detail)
