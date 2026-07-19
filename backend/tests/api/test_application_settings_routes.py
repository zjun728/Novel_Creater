from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.security.redaction import install_error_handlers


SECRET = "application-route-secret"
PRIVATE_URL = "https://application-route-private.example/v1"


def router_module():
    try:
        return importlib.import_module("backend.routers.application_settings")
    except ModuleNotFoundError as exc:
        pytest.fail(f"application settings router is missing: {exc}")


def result(revision=3):
    return SimpleNamespace(
        revision=revision,
        fallback_provider=SimpleNamespace(
            id="provider-1",
            name=f"Provider {SECRET}",
            provider_type="openai-compatible",
            model=f"model {PRIVATE_URL}",
            ready=True,
        ),
        redaction_values=(SECRET, PRIVATE_URL),
    )


class FakeService:
    def __init__(self):
        self.updated = None

    async def get(self):
        return result()

    async def update_default_model(self, command):
        self.updated = command
        return result(command.expected_revision + 1)

    async def get_diagnostics(self):
        return SimpleNamespace(
            schema_version="writer-core-v1.3.0",
            schema_manifest_match=True,
            database_reachable=True,
            managed_corpus_store_ready=False,
            scheduler_enabled=False,
            scheduler_state="disabled",
            scheduler_next_run_at=None,
            application_version="1.0.0",
        )


def client_for(service):
    module = router_module()
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(module.router, prefix="/api")
    app.dependency_overrides[module.get_application_settings_service] = (
        lambda: service
    )
    return TestClient(app, raise_server_exceptions=False)


def assert_safe(payload):
    rendered = json.dumps(payload, ensure_ascii=False)
    assert SECRET not in rendered
    assert PRIVATE_URL not in rendered
    for forbidden in (
        "apiKey",
        "api_key",
        "baseURL",
        "base_url",
        "authorization",
        "token",
        "password",
    ):
        assert forbidden.casefold() not in rendered.casefold()


def test_get_and_nullable_put_expose_only_public_model_identity():
    service = FakeService()
    client = client_for(service)

    current = client.get("/api/settings/application")
    updated = client.put(
        "/api/settings/application/default-model",
        json={"expectedRevision": 3, "fallbackProviderId": None},
    )

    assert current.status_code == 200
    assert set(current.json()) == {"revision", "fallbackProvider"}
    assert set(current.json()["fallbackProvider"]) == {
        "id",
        "name",
        "providerType",
        "model",
        "ready",
    }
    assert updated.status_code == 200
    assert service.updated.expected_revision == 3
    assert service.updated.fallback_provider_id is None
    assert_safe(current.json())
    assert_safe(updated.json())


def test_diagnostics_response_has_exact_safe_allowlist():
    response = client_for(FakeService()).get(
        "/api/settings/application/diagnostics"
    )

    assert response.status_code == 200
    assert response.json() == {
        "schemaVersion": "writer-core-v1.3.0",
        "schemaManifestMatch": True,
        "databaseReachable": True,
        "managedCorpusStoreReady": False,
        "schedulerEnabled": False,
        "schedulerState": "disabled",
        "schedulerNextRunAt": None,
        "applicationVersion": "1.0.0",
    }
    assert_safe(response.json())
