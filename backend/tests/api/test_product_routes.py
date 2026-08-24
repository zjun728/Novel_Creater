from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import main
from backend.http_errors import ProjectArchived
from backend.domain.routers import assets, contracts, corpus, projects, seeds, story_engines
from backend.domain.seeds import SeedMutationCapabilities, SeedPayload
from backend.security.redaction import install_error_handlers
from backend.services.project_lifecycle import (
    CreateProject,
    ProjectPreparationCapabilities,
    ProjectPreparationModelTask,
    ProjectPreparationOperation,
    ProjectPreparationResult,
    ProjectResult,
)
from backend.services.seeds import SeedResult


def test_joined_m2_routes_expose_public_behavior_through_dependencies():
    class FakeStoryEngineService:
        async def get(self, project_id, batch_id):
            assert (project_id, batch_id) == ("p1", "batch-1")
            return SimpleNamespace(
                    id="batch-1",
                    project_id="p1",
                    source_type="manual",
                    selection_revision=1,
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
        async def list_styles(self, **_filters):
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
                    capabilities=SeedMutationCapabilities(
                        referenced=True, hasFinalChapters=False,
                        canEdit=True, canSelect=True, canArchive=False,
                        canRestore=False, canPermanentlyDelete=False,
                    ),
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


def project_result(
    *,
    project_id="p1",
    title="Project",
    archived_at=None,
    lifecycle_revision=0,
):
    return ProjectResult(
        id=project_id,
        title=title,
        genre="",
        description="",
        target_words=100_000,
        target_chapters=100,
        current_chapter=0,
        status="drafting",
        archived_at=archived_at,
        lifecycle_revision=lifecycle_revision,
    )


def test_project_routes_delegate_explicit_lifecycle_contract(monkeypatch):
    class FakeService:
        def __init__(self):
            self.calls = []

        async def list_active(self):
            self.calls.append(("list_active",))
            return [project_result()]

        async def list_archived(self):
            self.calls.append(("list_archived",))
            return [
                project_result(
                    project_id="archived",
                    archived_at=123,
                    lifecycle_revision=2,
                )
            ]

        async def create(self, command: CreateProject):
            self.calls.append(("create", command))
            return ProjectResult.from_command(command)

        async def get(self, project_id, include_archived=False):
            self.calls.append(("get", project_id, include_archived))
            return project_result(
                project_id=project_id,
                archived_at=123 if project_id == "archived" else None,
                lifecycle_revision=2 if project_id == "archived" else 0,
            )

        async def preparation(self, project_id):
            self.calls.append(("preparation", project_id))
            return ProjectPreparationResult(
                lifecycle="active",
                active_selection="current",
                contract="current",
                bible="draft",
                planning="draft",
                planning_operation=ProjectPreparationOperation(
                    operation_id="operation-1",
                    status="pending",
                ),
                outline="draft",
                outline_operation=None,
                authoritative_chapter_number=8,
                model_tasks=tuple(
                    ProjectPreparationModelTask(
                        task_key=task_key,
                        readiness="ready",
                        reasons=(),
                    )
                    for task_key in (
                        "seed", "planning", "writing", "audit",
                        "summary", "extraction", "polish", "market",
                    )
                ),
                capabilities=ProjectPreparationCapabilities(
                    view_preparation=True,
                    edit_contract=True,
                    edit_bible=True,
                    generate_bible=True,
                ),
                next_action="recover_planning_operation",
                target_path="/projects/p1/planning/volumes",
                reasons=("planning_operation_pending",),
            )

        async def rename(self, project_id, title):
            self.calls.append(("rename", project_id, title))
            return project_result(project_id=project_id, title=title)

        async def archive(self, project_id, expected_lifecycle_revision):
            self.calls.append(
                ("archive", project_id, expected_lifecycle_revision)
            )
            return project_result(
                project_id=project_id,
                archived_at=123,
                lifecycle_revision=expected_lifecycle_revision + 1,
            )

        async def restore(self, project_id, expected_lifecycle_revision):
            self.calls.append(
                ("restore", project_id, expected_lifecycle_revision)
            )
            return project_result(
                project_id=project_id,
                lifecycle_revision=expected_lifecycle_revision + 1,
            )

        async def permanently_delete(
            self, project_id, expected_lifecycle_revision
        ):
            self.calls.append(
                ("permanently_delete", project_id, expected_lifecycle_revision)
            )

    service = FakeService()
    monkeypatch.setattr(projects, "_service", service)
    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    client = TestClient(app)

    active = client.get("/api/projects")
    archived = client.get("/api/projects/archived")
    created = client.post("/api/projects", json={"title": "New"})
    direct_archived = client.get("/api/projects/archived-id")
    preparation = client.get("/api/projects/p1/preparation")
    renamed = client.put("/api/projects/p1", json={"title": "Changed"})
    archived_command = client.post(
        "/api/projects/p1/archive",
        json={"expectedLifecycleRevision": 4},
    )
    restored_command = client.post(
        "/api/projects/p1/restore",
        json={"expectedLifecycleRevision": 5},
    )
    deleted = client.request(
        "DELETE",
        "/api/projects/p1",
        json={"expectedLifecycleRevision": 6},
    )

    assert active.status_code == 200
    assert [row["id"] for row in active.json()] == ["p1"]
    assert archived.status_code == 200
    assert archived.json()[0]["archivedAt"] == 123
    assert created.status_code == 200
    assert created.json()["title"] == "New"
    assert created.json()["targetWords"] == 2_400_000
    assert created.json()["targetChapters"] == 720
    assert direct_archived.status_code == 200
    assert preparation.status_code == 200
    assert preparation.json() == {
        "lifecycle": "active",
        "activeSelection": "current",
        "contract": "current",
        "bible": "draft",
        "planning": "draft",
        "planningOperation": {
            "operationId": "operation-1",
            "status": "pending",
        },
        "outline": "draft",
        "outlineOperation": None,
        "authoritativeChapterNumber": 8,
        "modelTasks": [
            {"taskKey": task_key, "readiness": "ready", "reasons": []}
            for task_key in (
                "seed", "planning", "writing", "audit",
                "summary", "extraction", "polish", "market",
            )
        ],
        "capabilities": {
            "viewPreparation": True,
            "editContract": True,
            "editBible": True,
            "generateBible": True,
        },
        "nextAction": "recover_planning_operation",
        "targetPath": "/projects/p1/planning/volumes",
        "reasons": ["planning_operation_pending"],
    }
    serialized = str(preparation.json()).lower()
    for forbidden in (
        "providerid", "providername", "modelname", "baseurl", "apikey",
        "password", "dsn", "prompt", "rawresponse", "corpustext",
    ):
        assert forbidden not in serialized
    assert renamed.json()["title"] == "Changed"
    assert archived_command.json()["lifecycleRevision"] == 5
    assert restored_command.json()["lifecycleRevision"] == 6
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert service.calls == [
        ("list_active",),
        ("list_archived",),
        ("create", service.calls[2][1]),
        ("get", "archived-id", True),
        ("preparation", "p1"),
        ("rename", "p1", "Changed"),
        ("archive", "p1", 4),
        ("restore", "p1", 5),
        ("permanently_delete", "p1", 6),
    ]
    assert service.calls[2][1].model_dump() == {
        "id": service.calls[2][1].id,
        "title": "New",
        "genre": "",
        "description": "",
        "target_words": 2_400_000,
        "target_chapters": 720,
    }


def test_archived_project_get_has_exact_safe_domain_error(monkeypatch):
    class FakeService:
        async def get(self, project_id, include_archived=False):
            assert project_id == "archived-project"
            assert include_archived is True
            raise ProjectArchived()

    monkeypatch.setattr(projects, "_service", FakeService())
    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    install_error_handlers(app)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/projects/archived-project")

    assert response.status_code == 409
    assert set(response.json()) == {"code", "message", "correlationId"}
    assert response.json()["code"] == "ProjectArchived"
    assert response.json()["message"] == ProjectArchived.message
    assert response.json()["correlationId"]


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "Project", "genre": "历史"},
        {"title": "Project", "description": "Description"},
        {"title": "Project", "targetWords": 1000},
        {"title": "Project", "targetChapters": 10},
    ],
)
def test_project_create_rejects_old_public_fields(monkeypatch, payload):
    class FakeService:
        async def create(self, command):
            raise AssertionError("extra payload must be rejected before service")

    monkeypatch.setattr(projects, "_service", FakeService())
    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/api/projects", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(item["loc"][-1] != "title" for item in detail)


def test_project_rename_and_lifecycle_commands_forbid_extra_or_missing_fields(
    monkeypatch,
):
    class FakeService:
        async def rename(self, project_id, title):
            raise AssertionError("invalid rename must not reach service")

        async def archive(self, project_id, expected_lifecycle_revision):
            raise AssertionError("invalid archive must not reach service")

    monkeypatch.setattr(projects, "_service", FakeService())
    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    client = TestClient(app, raise_server_exceptions=False)

    rename = client.put(
        "/api/projects/p1",
        json={"title": "Changed", "status": "drafting"},
    )
    missing_revision = client.post("/api/projects/p1/archive", json={})
    extra_revision = client.post(
        "/api/projects/p1/archive",
        json={"expectedLifecycleRevision": 0, "force": True},
    )

    assert rename.status_code == 422
    assert missing_revision.status_code == 422
    assert extra_revision.status_code == 422


@pytest.mark.parametrize(
    "invalid_revision",
    [True, 1.0, "1"],
)
def test_project_lifecycle_revision_requires_an_exact_json_integer(
    monkeypatch, invalid_revision
):
    class FakeService:
        async def archive(self, project_id, expected_lifecycle_revision):
            raise AssertionError("coerced revision must not reach service")

    monkeypatch.setattr(projects, "_service", FakeService())
    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/projects/p1/archive",
        json={"expectedLifecycleRevision": invalid_revision},
    )

    assert response.status_code == 422
