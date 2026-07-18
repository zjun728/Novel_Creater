from __future__ import annotations

import json
from dataclasses import is_dataclass

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from backend.http_errors import PublicDomainError
from backend.routers import providers
from backend.security.redaction import install_error_handlers
from backend.serializers.provider import (
    ProviderConnectionPublicResult,
    provider_public_profile,
)


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


class RetryableProviderRouteError(PublicDomainError):
    status_code = 409
    code = "provider_mutation_retryable_conflict"
    message = "Provider mutation conflicted; retry the request"
    retryable = True


class FakeProviderProfileService:
    def __init__(self):
        self.calls = []
        self.error_method = None
        self.returned_public_values = []

    def _public(self, row):
        value = provider_public_profile(row)
        self.returned_public_values.append(value)
        return value

    def _fail_if_requested(self, method):
        if self.error_method == method:
            raise ProviderRouteError()

    async def list_profiles(self):
        self._fail_if_requested("list")
        self.calls.append(("list",))
        return [self._public(provider_row())]

    async def create(self, command):
        self._fail_if_requested("create")
        self.calls.append(("create", command))
        return self._public(
            provider_row(
                id="provider-created",
                name=command.name,
                provider_type=command.provider_type,
                model_name=command.model,
                base_url=command.base_url,
                api_key=command.api_key,
                notes=command.notes,
                thinking=command.thinking,
                revision=1,
            )
        )

    async def update(self, command):
        self._fail_if_requested("update")
        self.calls.append(("update", command))
        return self._public(
            provider_row(
                model_name=command.changes.get("model", "model-one"),
                revision=command.expected_revision + 1,
            )
        )

    async def delete(self, command):
        self._fail_if_requested("delete")
        self.calls.append(("delete", command))
        return self._public(
            provider_row(
                api_key="",
                base_url="",
                enabled=0,
                lifecycle_status="deleted",
                deleted_at=30,
                revision=command.expected_revision + 1,
                _redaction_values=(SECRET, PRIVATE_URL),
            )
        )

    async def clear_api_key(self, command):
        self._fail_if_requested("clear")
        self.calls.append(("clear", command))
        return self._public(
            provider_row(
                api_key="",
                enabled=0,
                lifecycle_status="unconfigured",
                revision=command.expected_revision + 1,
                _redaction_values=(SECRET, PRIVATE_URL),
            )
        )

    async def test_connection(self, provider_id):
        self._fail_if_requested("test")
        self.calls.append(("test", provider_id))
        result = ProviderConnectionPublicResult(
            ok=True,
            code="connected",
            latency_ms=12,
            public_message="连接成功",
        )
        self.returned_public_values.append(result)
        return result


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
        "notes": "public notes",
        "thinking": {"mode": "safe"},
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
    assert service.returned_public_values
    assert all(is_dataclass(value) for value in service.returned_public_values)
    for value in service.returned_public_values:
        assert_public_boundary(value.to_dict())

    update = next(call[1] for call in service.calls if call[0] == "update")
    assert update.expected_revision == 4
    assert update.idempotency_key == "mutate-provider-request-0001"
    assert "apiKey" not in update.changes
    assert "baseURL" not in update.changes


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "apiKey": "a",
            "name": "a",
        },
        {
            "apiKey": "a",
            "name": " a ",
        },
        {
            "apiKey": "a",
            "thinking": {"a": "ordinary"},
        },
        {
            "apiKey": "safe-short-key",
            "baseURL": "https://secret.internal.example/v1",
            "notes": "public https://secret.internal.example/v1 collision",
        },
    ],
)
def test_create_rejects_public_secret_collisions_with_fixed_safe_422(
    provider_api, overrides
):
    client, service = provider_api
    body = create_body()
    body["notes"] = "public notes"
    body["thinking"] = {"mode": "safe"}
    body.update(overrides)

    response = client.post("/api/providers", json=body)

    assert response.status_code == 422
    assert not any(call[0] == "create" for call in service.calls)
    assert "Provider public fields cannot contain private configuration" in (
        response.text
    )
    assert '"a"' not in response.text
    assert "secret.internal.example" not in response.text
    assert_public_boundary(response.json())


def test_short_key_substrings_remain_legal_and_uncorrupted(provider_api):
    client, service = provider_api
    body = create_body()
    body.update(
        {
            "name": "a" * 120,
            "providerType": "openai-compatible",
            "model": "claude",
            "baseURL": "https://provider.example/v1",
            "apiKey": "a",
            "notes": "aaaa remains ordinary public text",
            "thinking": {"a-key": "a value"},
        }
    )

    response = client.post("/api/providers", json=body)

    assert response.status_code == 200, response.text
    assert response.json()["name"] == body["name"]
    assert response.json()["providerType"] == body["providerType"]
    assert response.json()["model"] == body["model"]
    assert response.json()["notes"] == body["notes"]
    assert response.json()["thinking"] == body["thinking"]
    command = next(call[1] for call in service.calls if call[0] == "create")
    assert command.api_key == "a"


@pytest.mark.parametrize("secret_field", ["apiKey", "baseURL"])
@pytest.mark.parametrize(
    "structural_secret", ["enabled", "revision", "provider"]
)
def test_create_structural_secret_values_never_rewrite_public_schema(
    provider_api, secret_field, structural_secret
):
    client, _ = provider_api
    body = create_body()
    body[secret_field] = structural_secret

    response = client.post("/api/providers", json=body)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {
        "id",
        "name",
        "providerType",
        "model",
        "enabled",
        "sortOrder",
        "stream",
        "maxContextTokens",
        "maxOutputTokens",
        "temperature",
        "topP",
        "supportsJSON",
        "supportsStreaming",
        "notes",
        "thinking",
        "hasKey",
        "hasBaseURL",
        "lifecycleStatus",
        "revision",
        "ready",
        "createdAt",
        "updatedAt",
    }
    rendered_values = json.dumps(list(payload.values()), ensure_ascii=False)
    assert structural_secret not in rendered_values


@pytest.mark.parametrize(
    "unsupported_type", ["anthropic", "unsupported-native"]
)
def test_create_rejects_unsupported_provider_type_before_service(
    provider_api, unsupported_type
):
    client, service = provider_api
    body = create_body()
    body.update(
        {
            "providerType": unsupported_type,
            "notes": "public notes",
            "thinking": {"mode": "safe"},
        }
    )

    response = client.post("/api/providers", json=body)

    assert response.status_code == 422
    assert not any(call[0] == "create" for call in service.calls)
    assert "Unsupported Provider type" in response.text
    assert_public_boundary(response.json())


def test_update_rejects_submitted_public_secret_collision(provider_api):
    client, service = provider_api

    response = client.put(
        "/api/providers/provider-1",
        json={
            **mutation_body(),
            "apiKey": "a",
            "notes": "a",
        },
    )

    assert response.status_code == 422
    assert not any(call[0] == "update" for call in service.calls)
    assert "Provider public fields cannot contain private configuration" in (
        response.text
    )
    assert '"a"' not in response.text
    assert_public_boundary(response.json())


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


def test_retryable_provider_conflict_has_fixed_public_http_contract(
    provider_api,
):
    client, service = provider_api

    async def fail_clear(command):
        raise RetryableProviderRouteError()

    service.clear_api_key = fail_clear
    response = client.post(
        "/api/providers/provider-1/clear-api-key",
        json=mutation_body(),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "provider_mutation_retryable_conflict"
    assert response.json()["message"] == (
        "Provider mutation conflicted; retry the request"
    )
    assert response.json()["retryable"] is True
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


@pytest.mark.parametrize(
    "alias",
    ("api-key", "base-url", "Api_Key", "Base-URL"),
)
def test_provider_validation_error_redacts_secret_aliases_at_any_depth(
    provider_api, alias
):
    client, _ = provider_api
    root_secret = f"root-alias-secret-{alias}-must-not-escape"
    nested_secret = f"nested-alias-secret-{alias}-must-not-escape"
    body = create_body()
    body[alias] = root_secret
    body["extraContainer"] = {alias: nested_secret}

    response = client.post("/api/providers", json=body)

    assert response.status_code == 422
    rendered = json.dumps(response.json(), ensure_ascii=False)
    assert alias not in rendered
    assert root_secret not in rendered
    assert nested_secret not in rendered


def test_provider_validation_error_preserves_ordinary_near_match_fields(
    provider_api,
):
    client, _ = provider_api
    body = create_body()
    ordinary = {
        "api-key-hint": "ordinary-api-hint-visible",
        "base-url-status": "ordinary-base-status-visible",
    }
    body.update(ordinary)

    response = client.post("/api/providers", json=body)

    assert response.status_code == 422
    rendered = json.dumps(response.json(), ensure_ascii=False)
    for key, value in ordinary.items():
        assert key in rendered
        assert value in rendered


def test_provider_secret_key_predicate_canonicalizes_only_exact_aliases():
    from backend.security.provider_secrets import is_provider_secret_key

    for alias in (
        "apiKey",
        "api_key",
        "api-key",
        "Api_Key",
        "baseURL",
        "base_url",
        "base-url",
        "Base-URL",
        "Authorization",
        "token",
        "password",
    ):
        assert is_provider_secret_key(alias) is True
    for ordinary in (
        "api-key-hint",
        "base-url-status",
        "authorizationMode",
        "tokenCount",
        "passwordPolicy",
    ):
        assert is_provider_secret_key(ordinary) is False


@pytest.mark.parametrize(
    "structural_secret", ["type", "loc", "msg", "input", "ctx"]
)
def test_validation_redaction_preserves_trusted_error_schema_keys(
    provider_api, structural_secret
):
    client, _ = provider_api
    body = create_body()
    body["apiKey"] = structural_secret
    body["name"] = " "

    response = client.post("/api/providers", json=body)

    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert set(error) == {"type", "loc", "msg", "input", "ctx"}
    assert "" not in error
    assert_public_boundary(response.json())


@pytest.mark.parametrize(
    ("secret_field", "secret_value"),
    [
        ("apiKey", "sk-" + ("cross-field-secret-" * 9)),
        (
            "baseURL",
            "https://private-provider.example/" + ("cross-field-url-" * 9),
        ),
        (
            "apiKey",
            {"nested": ["sk-" + ("nested-list-secret-" * 8)]},
        ),
        (
            "baseURL",
            ["https://private-provider.example/" + ("nested-list-url-" * 8)],
        ),
        (
            "thinking",
            {
                "nested": [
                    {"authorization": "Bearer " + ("nested-token-" * 10)}
                ]
            },
        ),
    ],
)
def test_validation_error_redacts_secret_values_from_unrelated_fields(
    provider_api, secret_field, secret_value
):
    client, _ = provider_api

    def first_string(value):
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for item in value.values():
                found = first_string(item)
                if found:
                    return found
        if isinstance(value, list):
            for item in value:
                found = first_string(item)
                if found:
                    return found
        return ""

    secret = first_string(secret_value)
    body = create_body()
    body[secret_field] = secret_value
    body["name"] = secret

    response = client.post("/api/providers", json=body)

    assert response.status_code == 422
    assert_public_boundary(response.json())
    assert secret not in response.text


def test_validation_error_redacts_secret_values_used_as_mapping_keys(
    provider_api,
):
    client, _ = provider_api
    secret = "sk-" + ("cross-field-mapping-key-" * 8)
    body = create_body()
    body["apiKey"] = secret
    body["name"] = {secret: True}

    response = client.post("/api/providers", json=body)

    assert response.status_code == 422
    assert_public_boundary(response.json())
    assert secret not in response.text


@pytest.mark.parametrize(
    ("secret_field", "secret"),
    [
        ("apiKey", "sk-" + ("nested-mapping-key-" * 8)),
        (
            "baseURL",
            "https://private.example/" + ("nested-url-key-" * 8),
        ),
    ],
)
def test_validation_error_collects_secrets_from_sensitive_mapping_keys(
    secret_field, secret
):
    body = {
        secret_field: {"nested": {secret: True}},
        "ordinary": {"ordinary-key": "ordinary-value"},
    }
    app = FastAPI()

    @app.post("/validation")
    async def fail_validation(payload: dict):
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("body", f"loc:{secret}"),
                    "msg": f"msg:ordinary-key:{secret}",
                    "input": {
                        f"input-key:{secret}": f"input-value:{secret}",
                    },
                    "ctx": {
                        f"ctx-key:{secret}": f"ctx-value:{secret}",
                        "token": secret,
                    },
                }
            ],
            body=payload,
        )

    install_error_handlers(app)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/validation", json=body)

    assert response.status_code == 422
    payload = response.json()
    assert_public_boundary(payload)
    assert secret not in response.text
    error = payload["detail"][0]
    assert error["loc"] == ["body", "loc:[REDACTED]"]
    assert error["msg"] == "msg:ordinary-key:[REDACTED]"
    assert error["input"] == {
        "input-key:[REDACTED]": "input-value:[REDACTED]",
    }
    assert error["ctx"] == {
        "ctx-key:[REDACTED]": "ctx-value:[REDACTED]",
    }
