from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.http_errors import PublicDomainError
from backend.routers import providers
from backend.security.redaction import install_error_handlers


SECRET = "sk-plain-secret-must-never-leave-backend"
PRIVATE_URL = "https://private-provider.example/v1"
FORBIDDEN_KEYS = {
    "apiKey",
    "api_key",
    "baseURL",
    "base_url",
    "authorization",
    "token",
    "password",
}


def provider_row(**overrides):
    row = {
        "id": "provider-1",
        "name": f"Provider {SECRET} {PRIVATE_URL}",
        "provider_type": "openai-compatible",
        "model_name": "model-one",
        "base_url": PRIVATE_URL,
        "api_key": SECRET,
        "enabled": 1,
        "sort_order": 2,
        "stream": 1,
        "max_context_tokens": 200_000,
        "max_output_tokens": 4096,
        "temperature": 0.8,
        "top_p": 0.9,
        "supports_json": 1,
        "supports_streaming": 1,
        "notes": f"nested {SECRET} {PRIVATE_URL}",
        "thinking": json.dumps(
            {
                "nested": [SECRET, {"url": PRIVATE_URL}],
                "authorization": SECRET,
                "token": SECRET,
                "password": SECRET,
                "api_key": SECRET,
                "baseURL": PRIVATE_URL,
            },
            ensure_ascii=False,
        ),
        "lifecycle_status": "active",
        "revision": 4,
        "deleted_at": None,
        "created_at": 10,
        "updated_at": 20,
    }
    row.update(overrides)
    return row


def assert_public_boundary(value):
    def visit(item):
        if isinstance(item, dict):
            assert not (set(item) & FORBIDDEN_KEYS), item
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)
        elif isinstance(item, str):
            assert item not in FORBIDDEN_KEYS

    visit(value)
    rendered = json.dumps(value, ensure_ascii=False)
    assert SECRET not in rendered
    assert PRIVATE_URL not in rendered


class ProviderRouteError(PublicDomainError):
    status_code = 409
    code = "provider_conflict"
    message = "Provider 配置已变化，请刷新后重试"


class FakeProviderProfileService:
    def __init__(self):
        self.calls = []
        self.error_method = None

    def _fail_if_requested(self, method):
        if self.error_method == method:
            raise ProviderRouteError()

    async def list_profiles(self):
        self._fail_if_requested("list")
        self.calls.append(("list",))
        return [provider_row()]

    async def create(self, command):
        self._fail_if_requested("create")
        self.calls.append(("create", command))
        return provider_row(
            id="provider-created",
            name=command.name,
            model_name=command.model,
            base_url=command.base_url,
            api_key=command.api_key,
            revision=1,
        )

    async def update(self, command):
        self._fail_if_requested("update")
        self.calls.append(("update", command))
        return provider_row(
            model_name=command.changes.get("model", "model-one"),
            revision=command.expected_revision + 1,
        )

    async def delete(self, command):
        self._fail_if_requested("delete")
        self.calls.append(("delete", command))
        return provider_row(
            api_key="",
            base_url="",
            enabled=0,
            lifecycle_status="deleted",
            deleted_at=30,
            revision=command.expected_revision + 1,
            _redaction_values=(SECRET, PRIVATE_URL),
        )

    async def clear_api_key(self, command):
        self._fail_if_requested("clear")
        self.calls.append(("clear", command))
        return provider_row(
            api_key="",
            enabled=0,
            lifecycle_status="unconfigured",
            revision=command.expected_revision + 1,
            _redaction_values=(SECRET, PRIVATE_URL),
        )

    async def test_connection(self, provider_id):
        self._fail_if_requested("test")
        self.calls.append(("test", provider_id))
        return {
            "ok": True,
            "code": "connected",
            "latencyMs": 12,
            "publicMessage": "连接成功",
        }


@pytest.fixture
def provider_api():
    service = FakeProviderProfileService()
    app = FastAPI()
    app.include_router(providers.router, prefix="/api")
    app.dependency_overrides[
        providers.get_provider_profile_service
    ] = lambda: service
    install_error_handlers(app)
    return TestClient(app, raise_server_exceptions=False), service


def create_body():
    return {
        "name": "Provider One",
        "providerType": "openai-compatible",
        "model": "model-one",
        "apiKey": SECRET,
        "baseURL": PRIVATE_URL,
        "enabled": True,
        "sortOrder": 2,
        "notes": f"nested {SECRET} {PRIVATE_URL}",
        "thinking": {
            "authorization": SECRET,
            "token": SECRET,
            "password": SECRET,
        },
        "idempotencyKey": "create-provider-request-0001",
    }


def mutation_body():
    return {
        "expectedRevision": 4,
        "idempotencyKey": "mutate-provider-request-0001",
    }


def test_list_create_update_delete_clear_and_test_successes_are_public_only(
    provider_api,
):
    client, service = provider_api

    responses = [
        client.get("/api/providers"),
        client.post("/api/providers", json=create_body()),
        client.put(
            "/api/providers/provider-1",
            json={
                **mutation_body(),
                "apiKey": "   ",
                "baseURL": "\t",
                "model": "model-two",
            },
        ),
        client.request(
            "DELETE", "/api/providers/provider-1", json=mutation_body()
        ),
        client.post(
            "/api/providers/provider-1/clear-api-key",
            json=mutation_body(),
        ),
        client.post("/api/providers/provider-1/test-connection"),
    ]

    for response in responses:
        assert response.status_code == 200, response.text
        assert_public_boundary(response.json())

    assert responses[-1].json() == {
        "ok": True,
        "code": "connected",
        "latencyMs": 12,
        "publicMessage": "连接成功",
    }
    assert responses[0].json()[0]["revision"] == 4
    assert responses[0].json()[0]["lifecycleStatus"] == "active"
    assert responses[3].json()["lifecycleStatus"] == "deleted"
    assert responses[4].json() == {
        **responses[4].json(),
        "enabled": False,
        "hasKey": False,
        "hasBaseURL": True,
        "lifecycleStatus": "unconfigured",
        "revision": 5,
    }

    update = next(call[1] for call in service.calls if call[0] == "update")
    assert update.expected_revision == 4
    assert update.idempotency_key == "mutate-provider-request-0001"
    assert "apiKey" not in update.changes
    assert "baseURL" not in update.changes


@pytest.mark.parametrize(
    ("method", "request_call"),
    [
        ("list", lambda client: client.get("/api/providers")),
        ("create", lambda client: client.post("/api/providers", json=create_body())),
        (
            "update",
            lambda client: client.put(
                "/api/providers/provider-1",
                json={**mutation_body(), "model": "model-two"},
            ),
        ),
        (
            "delete",
            lambda client: client.request(
                "DELETE", "/api/providers/provider-1", json=mutation_body()
            ),
        ),
        (
            "clear",
            lambda client: client.post(
                "/api/providers/provider-1/clear-api-key",
                json=mutation_body(),
            ),
        ),
        (
            "test",
            lambda client: client.post(
                "/api/providers/provider-1/test-connection"
            ),
        ),
    ],
)
def test_every_handled_provider_error_is_recursively_public_only(
    provider_api, method, request_call
):
    client, service = provider_api
    service.error_method = method

    response = request_call(client)

    assert response.status_code == 409
    assert response.json()["code"] == "provider_conflict"
    assert_public_boundary(response.json())


def test_provider_validation_error_drops_forbidden_keys_recursively(provider_api):
    client, _ = provider_api
    body = create_body()
    body["name"] = {"invalid": True}
    body["apiKey"] = {"token": SECRET}
    body["thinking"] = {
        "authorization": SECRET,
        "nested": {"password": SECRET, "base_url": PRIVATE_URL},
    }

    response = client.post("/api/providers", json=body)

    assert response.status_code == 422
    assert_public_boundary(response.json())
