from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.model_bindings import TASK_KEYS
from backend.http_errors import BindingConflict
from backend.domain.routers import model_bindings
from backend.security.redaction import install_error_handlers


SECRET = "sk-binding-secret-never-public"
PRIVATE_URL = "https://binding-private.example/v1"
OVERLAPPING_URL = "https://secret.internal.example/v1"


def binding_result(*, revision=1, ready=True):
    items = list(
        SimpleNamespace(
            task_key=key,
            resolution_status="bound" if ready else "unbound",
            provider_id=f"provider-{key}" if ready else None,
            provider_name_snapshot=f"Provider {key}" if ready else None,
            model_name_snapshot=f"model-{key}" if ready else None,
        )
        for key in TASK_KEYS
    )
    items[0] = SimpleNamespace(
        task_key="seed",
        resolution_status="bound" if ready else "unbound",
        provider_id="provider-seed" if ready else None,
        provider_name_snapshot=f"Provider {SECRET}" if ready else None,
        model_name_snapshot=f"model {PRIVATE_URL}" if ready else None,
    )
    return SimpleNamespace(
        project_id="p1",
        revision=revision,
        content_hash="a" * 64,
        source_project_id="p0",
        items=tuple(items),
        binding_complete=True,
        binding_ready=ready,
        reasons=() if ready else tuple(f"task_unbound:{key}" for key in TASK_KEYS),
        redaction_values=(SECRET, PRIVATE_URL),
    )


class FakeService:
    def __init__(self):
        self.replaced = None

    async def get_current(self, project_id):
        assert project_id == "p1"
        return binding_result()

    async def get_status(self, project_id):
        assert project_id == "p1"
        return binding_result(ready=False)

    async def replace_all(self, project_id, expected_revision, mapping):
        self.replaced = (project_id, expected_revision, mapping)
        return binding_result(revision=expected_revision + 1)


def client_for(service):
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(model_bindings.router, prefix="/api")
    app.dependency_overrides[model_bindings.get_model_binding_service] = lambda: service
    return TestClient(app, raise_server_exceptions=False)


def full_entries(provider_id="provider-1"):
    return [{"taskKey": key, "providerId": provider_id} for key in TASK_KEYS]


def assert_secret_free(payload):
    rendered = json.dumps(payload, ensure_ascii=False)
    assert SECRET not in rendered
    assert PRIVATE_URL not in rendered
    assert "apiKey" not in rendered and "baseURL" not in rendered


def test_get_bindings_and_status_expose_only_snapshot_metadata():
    client = client_for(FakeService())

    current = client.get("/api/projects/p1/bindings")
    status = client.get("/api/projects/p1/bindings/status")

    assert current.status_code == 200
    assert current.json()["revision"] == 1
    assert [item["taskKey"] for item in current.json()["items"]] == list(TASK_KEYS)
    assert set(current.json()["items"][0]) == {
        "taskKey", "resolutionStatus", "providerId",
        "providerNameSnapshot", "modelNameSnapshot",
    }
    assert status.json()["bindingComplete"] is True
    assert status.json()["bindingReady"] is False
    assert len(status.json()["reasons"]) == 8
    assert_secret_free(current.json())
    assert_secret_free(status.json())


def test_binding_route_uses_longest_first_shared_secret_sanitizer():
    class OverlappingService(FakeService):
        async def get_current(self, project_id):
            result = binding_result()
            first = result.items[0]
            first.provider_id = OVERLAPPING_URL
            first.provider_name_snapshot = OVERLAPPING_URL
            first.model_name_snapshot = f"model {OVERLAPPING_URL}"
            result.redaction_values = ("https", OVERLAPPING_URL)
            return result

    response = client_for(OverlappingService()).get(
        "/api/projects/p1/bindings"
    )

    assert response.status_code == 200
    rendered = response.text
    assert OVERLAPPING_URL not in rendered
    assert "secret.internal.example" not in rendered
    assert "[REDACTED]://secret" not in rendered


def test_put_requires_exact_unique_task_map_and_delegates_nullable_provider_ids():
    service = FakeService()
    client = client_for(service)
    entries = full_entries()
    entries[-1]["providerId"] = None

    response = client.put(
        "/api/projects/p1/bindings",
        json={"expectedRevision": 1, "entries": entries},
    )

    assert response.status_code == 200
    assert service.replaced == (
        "p1", 1, {entry["taskKey"]: entry["providerId"] for entry in entries}
    )
    assert response.json()["revision"] == 2

    for invalid in (entries[:-1], entries[:-1] + [entries[0]]):
        rejected = client.put(
            "/api/projects/p1/bindings",
            json={"expectedRevision": 1, "entries": invalid},
        )
        assert rejected.status_code == 422


def test_binding_conflict_uses_stable_secret_free_public_domain_envelope():
    class ConflictService(FakeService):
        async def replace_all(self, project_id, expected_revision, mapping):
            raise BindingConflict()

    response = client_for(ConflictService()).put(
        "/api/projects/p1/bindings",
        json={"expectedRevision": 1, "entries": full_entries()},
    )

    assert response.status_code == 409
    assert set(response.json()) == {"code", "message", "correlationId"}
    assert response.json()["code"] == "BindingConflict"
    assert response.json()["message"] == "Binding state changed; refresh and retry"
    assert_secret_free(response.json())
