from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.seeds import SeedPayload
from backend.routers import seeds
from backend.security.redaction import install_error_handlers
from backend.services.seeds import SeedResult, SelectedSeedResult


PAYLOAD = {
    "title": "雾城来信",
    "genre": "悬疑",
    "logline": "一封未来来信。",
    "protagonist": "林岚",
    "desire": "寻找姐姐",
    "coreConflict": "真相会改变时间",
    "worldPressure": "城市遗忘记忆",
    "openingHook": "明日邮戳",
    "differentiation": "档案缺页叙事",
}


def seed_result(revision=1, selection_revision=0):
    return SeedResult(
        id="seed-1", project_id="p1", status="candidate",
        revision=revision, revision_id=f"revision-{revision}",
        content_hash=str(revision) * 64, payload=SeedPayload(**PAYLOAD),
        is_selected=selection_revision > 0,
        selection_revision=selection_revision,
    )


class FakeSeedService:
    def __init__(self):
        self.calls = []

    async def list(self, project_id):
        self.calls.append(("list", project_id))
        return (seed_result(),)

    async def create(self, command):
        self.calls.append(("create", command))
        return seed_result()

    async def edit(self, command):
        self.calls.append(("edit", command))
        return seed_result(2, 2)

    async def delete(self, command):
        self.calls.append(("delete", command))

    async def get_selected(self, project_id):
        self.calls.append(("get-selected", project_id))
        return SelectedSeedResult(
            selected=seed_result(1, 1), seed_ready=True,
            contract_ready=False, reasons=("binding_not_verified",),
        )

    async def select(self, command):
        self.calls.append(("select", command))
        return seed_result(1, 1)


def make_client():
    service = FakeSeedService()
    app = FastAPI()
    app.include_router(seeds.router, prefix="/api")
    app.dependency_overrides[seeds.get_seed_service] = lambda: service
    install_error_handlers(app)
    return TestClient(app, raise_server_exceptions=False), service


def test_seed_routes_use_service_dependency_and_return_camel_case_public_dto():
    client, service = make_client()
    listed = client.get("/api/projects/p1/seeds")
    created = client.post("/api/projects/p1/seeds", json={"payload": PAYLOAD})
    edited = client.put(
        "/api/projects/p1/seeds/seed-1",
        json={
            "payload": {**PAYLOAD, "title": "第二封信"},
            "expectedSeedRevision": 1,
            "expectedSelectionRevision": 1,
        },
    )
    deleted = client.request(
        "DELETE", "/api/projects/p1/seeds/seed-1",
        json={"expectedSeedRevision": 2, "expectedSelectionRevision": 2},
    )
    selected = client.get("/api/projects/p1/selected-seed")
    changed = client.put(
        "/api/projects/p1/selected-seed",
        json={
            "seedId": "seed-1", "expectedSeedRevision": 1,
            "expectedSelectionRevision": 0,
        },
    )

    assert [r.status_code for r in (listed, created, edited, deleted, selected, changed)] == [200] * 6
    assert listed.json()[0] == {
        "id": "seed-1", "projectId": "p1", "status": "candidate",
        "revision": 1, "revisionId": "revision-1", "contentHash": "1" * 64,
        "payload": PAYLOAD, "isSelected": False, "selectionRevision": 0,
    }
    assert selected.json()["contractReady"] is False
    assert selected.json()["seedReady"] is True
    assert selected.json()["reasons"] == ["binding_not_verified"]
    assert service.calls[1][1].project_id == "p1"
    assert service.calls[2][1].expected_seed_revision == 1
    assert service.calls[3][1].expected_selection_revision == 2


def test_seed_write_requests_forbid_legacy_or_extra_fields():
    client, _ = make_client()
    response = client.post(
        "/api/projects/p1/seeds",
        json={"payload": {**PAYLOAD, "premise_json": "legacy"}},
    )
    assert response.status_code == 422
    response = client.put(
        "/api/projects/p1/selected-seed",
        json={
            "seedId": "seed-1", "expectedSeedRevision": 1,
            "expectedSelectionRevision": 0, "unexpected": True,
        },
    )
    assert response.status_code == 422
