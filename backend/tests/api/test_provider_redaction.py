from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import providers


SECRET = "sk-plain-secret-must-never-leave-backend"
PRIVATE_URL = "https://private-provider.example/v1"


def provider_row(**overrides):
    row = {
        "id": "provider-1",
        "name": "Provider One",
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
        "notes": "note",
        "thinking": '{"mode":"enabled"}',
        "created_at": 10,
        "updated_at": 20,
    }
    row.update(overrides)
    return row


def assert_public_provider(payload):
    rendered = json.dumps(payload, ensure_ascii=False)
    assert SECRET not in rendered
    assert PRIVATE_URL not in rendered
    assert "apiKey" not in payload and "api_key" not in payload
    assert "baseURL" not in payload and "base_url" not in payload
    assert payload == {
        "id": "provider-1",
        "name": "Provider One",
        "providerType": "openai-compatible",
        "model": "model-one",
        "enabled": True,
        "sortOrder": 2,
        "stream": True,
        "maxContextTokens": 200_000,
        "maxOutputTokens": 4096,
        "temperature": 0.8,
        "topP": 0.9,
        "supportsJSON": True,
        "supportsStreaming": True,
        "notes": "note",
        "thinking": {"mode": "enabled"},
        "hasKey": True,
        "hasBaseURL": True,
        "createdAt": 10,
        "updatedAt": 20,
    }


@pytest.fixture
def provider_api(monkeypatch):
    store = {"provider-1": provider_row()}
    executions = []

    async def fetchall(sql, args=None):
        if "FROM task_model_binding_items" in sql:
            return [
                {
                    "task_key": "writing",
                    **store["provider-1"],
                }
            ]
        if "FROM provider_profiles" in sql:
            return list(store.values())
        if "FROM task_model_bindings" in sql:
            return [{"id": "binding-1", "project_id": "project-1"}]
        raise AssertionError(sql)

    async def fetchone(sql, args=None):
        if "FROM provider_profiles" in sql:
            return store.get(args[0]) if args else next(iter(store.values()), None)
        if "FROM projects" in sql:
            return {"id": "project-1"}
        if "FROM task_model_bindings" in sql:
            return {"id": "binding-1", "project_id": "project-1"}
        raise AssertionError(sql)

    async def execute(sql, args=None):
        executions.append((" ".join(sql.split()), tuple(args or ())))
        if sql.lstrip().startswith("INSERT INTO provider_profiles"):
            (
                provider_id,
                name,
                provider_type,
                model_name,
                base_url,
                api_key,
                enabled,
                sort_order,
                stream,
                max_context,
                max_output,
                temperature,
                top_p,
                supports_json,
                supports_streaming,
                notes,
                thinking,
                created_at,
                updated_at,
            ) = args
            store[provider_id] = provider_row(
                id=provider_id,
                name=name,
                provider_type=provider_type,
                model_name=model_name,
                base_url=base_url,
                api_key=api_key,
                enabled=enabled,
                sort_order=sort_order,
                stream=stream,
                max_context_tokens=max_context,
                max_output_tokens=max_output,
                temperature=temperature,
                top_p=top_p,
                supports_json=supports_json,
                supports_streaming=supports_streaming,
                notes=notes,
                thinking=thinking,
                created_at=created_at,
                updated_at=updated_at,
            )
        elif sql.lstrip().startswith("UPDATE provider_profiles"):
            assignments = sql.split("SET", 1)[1].split("WHERE", 1)[0].split(",")
            provider_id = args[-1]
            for assignment, value in zip(assignments, args[:-1]):
                store[provider_id][assignment.split("=")[0].strip()] = value
        return 1

    monkeypatch.setattr(providers, "fetchall", fetchall)
    monkeypatch.setattr(providers, "fetchone", fetchone)
    monkeypatch.setattr(providers, "execute", execute)
    app = FastAPI()
    app.include_router(providers.router, prefix="/api")
    return TestClient(app), store, executions


def test_provider_list_create_update_and_binding_status_are_public(provider_api):
    client, store, _ = provider_api
    assert_public_provider(client.get("/api/providers").json()[0])

    created = client.post(
        "/api/providers",
        json={
            "name": "Provider One",
            "providerType": "openai-compatible",
            "model": "model-one",
            "apiKey": SECRET,
            "baseURL": PRIVATE_URL,
            "enabled": True,
            "sortOrder": 2,
            "notes": "note",
            "thinking": {"mode": "enabled"},
        },
    )
    assert created.status_code == 200
    created_payload = created.json()
    created_payload["id"] = "provider-1"
    created_payload["createdAt"] = 10
    created_payload["updatedAt"] = 20
    assert_public_provider(created_payload)

    provider_id = next(reversed(store))
    updated = client.put(
        f"/api/providers/{provider_id}", json={"apiKey": SECRET}
    )
    assert updated.status_code == 200
    updated_payload = updated.json()
    updated_payload["id"] = "provider-1"
    updated_payload["createdAt"] = 10
    updated_payload["updatedAt"] = 20
    assert_public_provider(updated_payload)

    status = client.get("/api/projects/project-1/bindings/status")
    assert status.status_code == 200
    rendered = json.dumps(status.json(), ensure_ascii=False)
    assert SECRET not in rendered and PRIVATE_URL not in rendered
    assert_public_provider(status.json()["items"][0]["provider"])


def test_blank_secret_fields_preserve_and_clear_flags_explicitly_clear(provider_api):
    client, store, executions = provider_api
    before = len(executions)

    response = client.put(
        "/api/providers/provider-1",
        json={"apiKey": "   ", "baseURL": "\t"},
    )
    assert response.status_code == 200
    assert store["provider-1"]["api_key"] == SECRET
    assert store["provider-1"]["base_url"] == PRIVATE_URL
    assert len(executions) == before

    response = client.put(
        "/api/providers/provider-1",
        json={"clearApiKey": True, "clearBaseURL": True},
    )
    assert response.status_code == 200
    assert store["provider-1"]["api_key"] == ""
    assert store["provider-1"]["base_url"] == ""
    assert response.json()["hasKey"] is False
    assert response.json()["hasBaseURL"] is False
