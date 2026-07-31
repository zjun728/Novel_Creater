from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.seeds import SeedMutationCapabilities, SeedPayload
from backend.http_errors import SeedAlreadyConfirmed, SeedNotFound
from backend.routers import seeds
from backend.security.redaction import install_error_handlers
from backend.services.seeds import (
    ActiveSeedSelection,
    SeedResult,
    SelectedSeedResult,
)


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
        capabilities=SeedMutationCapabilities(
            referenced=selection_revision > 0,
            hasFinalChapters=False,
            canEdit=True,
            canSelect=True,
            canArchive=selection_revision == 0,
            canRestore=False,
            canPermanentlyDelete=selection_revision == 0,
        ),
    )


class FakeSeedService:
    def __init__(self):
        self.calls = []
        self.select_count = 0

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

    async def archive(self, command):
        self.calls.append(("archive", command))
        return seed_result()

    async def restore(self, command):
        self.calls.append(("restore", command))
        return seed_result()

    async def get_selected(self, project_id):
        self.calls.append(("get-selected", project_id))
        if project_id == "missing":
            raise SeedNotFound()
        selected = seed_result(1, 1)
        return SelectedSeedResult(
            active_selection=ActiveSeedSelection(
                project_id="p1", selection_revision=1,
                seed_id=selected.id, seed_revision_id=selected.revision_id,
                seed_hash=selected.content_hash, selected_at=1,
                updated_at=1, seed=selected,
            ),
            seed_ready=True,
            contract_ready=False, reasons=("binding_not_verified",),
        )

    async def select(self, command):
        self.calls.append(("select", command))
        self.select_count += 1
        if self.select_count > 1:
            raise SeedAlreadyConfirmed()
        return seed_result(1, 1)


class FakeInspirationService:
    def __init__(self):
        self.calls = []

    async def generate(self, command):
        self.calls.append(command)
        return {
            "attempt_id": "attempt-1",
            "status": "succeeded",
            "assistant_turn": {
                "role": "assistant",
                "content": "把知识优势拆成三次递进兑现。",
            },
            "result_hash": "a" * 64,
            "public_error_code": None,
            "created_at": 1,
            "completed_at": 2,
        }


def make_client():
    service = FakeSeedService()
    inspiration = FakeInspirationService()
    app = FastAPI()
    app.include_router(seeds.router, prefix="/api")
    app.dependency_overrides[seeds.get_seed_service] = lambda: service
    dependency = getattr(seeds, "get_seed_generation_service", None)
    if dependency is not None:
        app.dependency_overrides[dependency] = lambda: inspiration
    install_error_handlers(app)
    return (
        TestClient(app, raise_server_exceptions=False),
        service,
        inspiration,
    )


def test_seed_routes_use_service_dependency_and_return_camel_case_public_dto():
    client, service, _ = make_client()
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
        "capabilities": {
            "referenced": False, "hasFinalChapters": False,
            "canEdit": True, "canSelect": True, "canArchive": True,
            "canRestore": False, "canPermanentlyDelete": True,
        },
    }
    assert selected.json()["activeSelection"]["selectionRevision"] == 1
    assert selected.json()["activeSelection"]["seed"]["id"] == "seed-1"
    assert selected.json()["contractReady"] is False
    assert selected.json()["seedReady"] is True
    assert selected.json()["reasons"] == ["binding_not_verified"]
    assert service.calls[1][1].project_id == "p1"
    assert service.calls[2][1].expected_seed_revision == 1
    assert service.calls[3][1].expected_selection_revision == 2


def test_seed_archive_restore_routes_are_explicit_and_delete_never_archives():
    client, service, _ = make_client()
    archived = client.post(
        "/api/projects/p1/seeds/seed-1/archive",
        json={"expectedSeedRevision": 1, "expectedSelectionRevision": 2},
    )
    restored = client.post(
        "/api/projects/p1/seeds/seed-1/restore",
        json={"expectedSeedRevision": 1, "expectedSelectionRevision": 2},
    )

    assert archived.status_code == restored.status_code == 200
    assert [call[0] for call in service.calls] == ["archive", "restore"]
    assert service.calls[0][1].seed_id == "seed-1"
    assert service.calls[1][1].expected_selection_revision == 2


def test_seed_write_requests_forbid_legacy_or_extra_fields():
    client, _, _ = make_client()
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


def test_second_seed_selection_returns_stable_public_409_without_private_details():
    client, _, _ = make_client()
    request = {
        "seedId": "seed-1",
        "expectedSeedRevision": 1,
        "expectedSelectionRevision": 0,
    }

    assert client.put("/api/projects/p1/selected-seed", json=request).status_code == 200
    response = client.put(
        "/api/projects/p1/selected-seed",
        json={**request, "expectedSelectionRevision": 1},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "seed_already_confirmed"
    assert response.json()["message"] == SeedAlreadyConfirmed.message
    assert "private" not in response.text.lower()


def test_selected_seed_unknown_project_returns_exact_public_404():
    client, _, _ = make_client()

    response = client.get("/api/projects/missing/selected-seed")

    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"code", "message", "correlationId"}
    assert body["code"] == "SeedNotFound"
    assert body["message"] == SeedNotFound.message
    assert body["correlationId"]


def test_seed_inspiration_accepts_only_bounded_server_resolved_contract_and_never_creates_seed():
    client, seed_service, inspiration = make_client()

    response = client.post(
        "/api/projects/p1/seed-inspiration",
        json={
            "transcript": [
                {"role": "user", "content": "我想写明代穿越群像。"}
            ],
            "snapshotIds": ["snapshot-1", "snapshot-2"],
            "analysisId": "analysis-1",
            "idempotencyKey": "i" * 64,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "attemptId": "attempt-1",
        "status": "succeeded",
        "assistantTurn": {
            "role": "assistant",
            "content": "把知识优势拆成三次递进兑现。",
        },
        "resultHash": "a" * 64,
        "publicErrorCode": None,
        "createdAt": 1,
        "completedAt": 2,
    }
    assert len(inspiration.calls) == 1
    assert inspiration.calls[0].project_id == "p1"
    assert inspiration.calls[0].snapshot_ids == ("snapshot-1", "snapshot-2")
    assert not [
        call for call in seed_service.calls if call[0] == "create"
    ]

    forged = client.post(
        "/api/projects/p1/seed-inspiration",
        json={
            "transcript": [{"role": "user", "content": "测试"}],
            "snapshotIds": ["snapshot-1"],
            "analysisId": "analysis-1",
            "idempotencyKey": "x" * 64,
            "providerId": "forged-provider",
            "model": "forged-model",
        },
    )
    assert forged.status_code == 422
    rendered = forged.text
    assert "forged-provider" not in rendered
    assert "forged-model" not in rendered
    assert '"input"' not in rendered


@pytest.mark.parametrize(
    "snapshot_ids",
    (
        [],
        ["same", "same"],
        [""],
        ["x" * 37],
    ),
)
def test_seed_inspiration_rejects_invalid_snapshot_ids_at_the_http_boundary(
    snapshot_ids,
):
    client, _, inspiration = make_client()

    response = client.post(
        "/api/projects/p1/seed-inspiration",
        json={
            "transcript": [{"role": "user", "content": "测试"}],
            "snapshotIds": snapshot_ids,
            "analysisId": "analysis-1",
            "idempotencyKey": "i" * 64,
        },
    )

    assert response.status_code == 422
    assert inspiration.calls == []


def test_seed_inspiration_rejects_invalid_project_id_at_the_http_boundary():
    client, _, inspiration = make_client()

    response = client.post(
        f"/api/projects/{'p' * 37}/seed-inspiration",
        json={
            "transcript": [{"role": "user", "content": "测试"}],
            "snapshotIds": ["snapshot-1"],
            "analysisId": "analysis-1",
            "idempotencyKey": "i" * 64,
        },
    )

    assert response.status_code == 422
    assert inspiration.calls == []


def test_explicit_save_as_seed_accepts_selection_not_frozen_hashes_or_urls():
    client, service, _ = make_client()
    response = client.post(
        "/api/projects/p1/seeds",
        json={
            "payload": PAYLOAD,
            "idempotencyKey": "s" * 64,
            "provenance": {
                "kind": "ai_chat",
                "snapshotIds": ["snapshot-1"],
                "analysisId": "analysis-1",
                "inspirationAttemptId": "attempt-1",
                "publicNotes": ["作者已编辑最终九字段。"],
            },
        },
    )
    assert response.status_code == 200
    command = service.calls[-1][1]
    assert command.idempotency_key == "s" * 64
    assert command.provenance.kind == "ai_chat"

    for forbidden in (
        {"snapshotHash": "a" * 64},
        {"sourceURL": "https://private.invalid"},
        {"apiKey": "PRIVATE"},
        {"baseURL": "https://private.invalid"},
    ):
        body = {
            "payload": PAYLOAD,
            "idempotencyKey": "z" * 64,
            "provenance": {"kind": "manual", **forbidden},
        }
        rejected = client.post("/api/projects/p1/seeds", json=body)
        assert rejected.status_code == 422
        assert not any(
            value in rejected.text
            for value in (
                "PRIVATE",
                "https://private.invalid",
                '"input"',
            )
        )


def test_seed_validation_never_echoes_oversized_transcript_or_source_url():
    client, _, _ = make_client()
    oversized = "TRANSCRIPT_SENTINEL_" + "x" * 2_001
    response = client.post(
        "/api/projects/p1/seed-inspiration",
        json={
            "transcript": [{"role": "user", "content": oversized}],
            "snapshotIds": ["snapshot-1"],
            "analysisId": "analysis-1",
            "idempotencyKey": "i" * 64,
        },
    )
    assert response.status_code == 422
    assert "TRANSCRIPT_SENTINEL_" not in response.text
    assert '"input"' not in response.text

    source_url = "https://source-url-sentinel.invalid/private"
    response = client.post(
        "/api/projects/p1/seeds",
        json={
            "payload": PAYLOAD,
            "provenance": {
                "kind": "manual",
                "sourceURL": source_url,
            },
        },
    )
    assert response.status_code == 422
    assert source_url not in response.text
    assert '"input"' not in response.text
