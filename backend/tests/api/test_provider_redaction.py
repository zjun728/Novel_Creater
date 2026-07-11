from __future__ import annotations

import json
from contextlib import asynccontextmanager

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
        "notes": f"nested {SECRET} {PRIVATE_URL}",
        "thinking": json.dumps(
            {"nested": [SECRET, {"url": PRIVATE_URL}]}, ensure_ascii=False
        ),
        "lifecycle_status": "active",
        "deleted_at": None,
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
    assert payload["hasKey"] is True
    assert payload["hasBaseURL"] is True
    assert payload["notes"] == "nested [REDACTED] [REDACTED]"
    assert payload["thinking"] == {
        "nested": ["[REDACTED]", {"url": "[REDACTED]"}]
    }


class FakeSession:
    def __init__(self, store, executions):
        self.store = store
        self.executions = executions

    async def fetchone(self, sql, args=None):
        self.executions.append(("fetchone", " ".join(sql.split()), tuple(args or ())))
        row = self.store.get(args[0]) if args else None
        if row is None or row["lifecycle_status"] != "active":
            return None
        return row

    async def execute(self, sql, args=None):
        self.executions.append(("execute", " ".join(sql.split()), tuple(args or ())))
        provider_id = args[-1]
        row = self.store.get(provider_id)
        if row is None or row["lifecycle_status"] != "active":
            return 0
        row.update(
            enabled=0,
            lifecycle_status="deleted",
            api_key="",
            base_url="",
            deleted_at=args[0],
            updated_at=args[1],
        )
        return 1


@pytest.fixture
def provider_api(monkeypatch):
    store = {"provider-1": provider_row()}
    executions = []
    transaction_counts = {"commit": 0, "rollback": 0}

    async def fetchall(sql, args=None):
        executions.append(("fetchall", " ".join(sql.split()), tuple(args or ())))
        return [row for row in store.values() if row["lifecycle_status"] == "active"]

    async def fetchone(sql, args=None):
        executions.append(("fetchone", " ".join(sql.split()), tuple(args or ())))
        row = store.get(args[0]) if args else None
        if row is None or row["lifecycle_status"] != "active":
            return None
        return row

    async def execute(sql, args=None):
        executions.append(("execute", " ".join(sql.split()), tuple(args or ())))
        if sql.lstrip().startswith("INSERT INTO provider_profiles"):
            provider_id = args[0]
            store[provider_id] = provider_row(
                id=provider_id,
                name=args[1], provider_type=args[2], model_name=args[3],
                base_url=args[4], api_key=args[5], enabled=args[6],
                sort_order=args[7], stream=args[8],
                max_context_tokens=args[9], max_output_tokens=args[10],
                temperature=args[11], top_p=args[12], supports_json=args[13],
                supports_streaming=args[14], notes=args[15], thinking=args[16],
                lifecycle_status=args[17], deleted_at=args[18],
                created_at=args[19], updated_at=args[20],
            )
        return 1

    @asynccontextmanager
    async def transaction():
        try:
            yield FakeSession(store, executions)
        except BaseException:
            transaction_counts["rollback"] += 1
            raise
        else:
            transaction_counts["commit"] += 1

    monkeypatch.setattr(providers, "fetchall", fetchall)
    monkeypatch.setattr(providers, "fetchone", fetchone)
    monkeypatch.setattr(providers, "execute", execute)
    monkeypatch.setattr(providers, "transaction", transaction)
    app = FastAPI()
    app.include_router(providers.router, prefix="/api")
    return TestClient(app), store, executions, transaction_counts


def valid_create():
    return {
        "name": "Provider One",
        "providerType": "openai-compatible",
        "model": "model-one",
        "apiKey": SECRET,
        "baseURL": PRIVATE_URL,
        "enabled": True,
        "sortOrder": 2,
        "notes": f"nested {SECRET} {PRIVATE_URL}",
        "thinking": {"nested": [SECRET, {"url": PRIVATE_URL}]},
    }


def test_provider_list_create_update_are_active_only_and_recursively_redacted(provider_api):
    client, store, executions, _ = provider_api
    assert_public_provider(client.get("/api/providers").json()[0])
    list_sql = executions[-1][1]
    assert "lifecycle_status='active'" in list_sql

    created = client.post("/api/providers", json=valid_create())
    assert created.status_code == 200
    assert_public_provider(created.json())
    inserted = next(call for call in executions if call[1].startswith("INSERT"))
    assert inserted[2][17:19] == ("active", None)

    provider_id = created.json()["id"]
    updated = client.put(
        f"/api/providers/{provider_id}",
        json={"apiKey": "   ", "baseURL": "\t"},
    )
    assert updated.status_code == 200
    assert store[provider_id]["api_key"] == SECRET
    assert store[provider_id]["base_url"] == PRIVATE_URL

    rejected = client.put(
        f"/api/providers/{provider_id}", json={"clearApiKey": True}
    )
    assert rejected.status_code == 422

    for field in ("name", "providerType", "model", "apiKey", "baseURL", "notes"):
        rejected = client.put(
            f"/api/providers/{provider_id}", json={field: None}
        )
        assert rejected.status_code == 422


def test_delete_soft_deletes_in_one_transaction_and_is_repeatable_404(provider_api):
    client, store, executions, counts = provider_api

    deleted = client.delete("/api/providers/provider-1")

    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}
    assert counts == {"commit": 1, "rollback": 0}
    row = store["provider-1"]
    assert row["enabled"] == 0
    assert row["lifecycle_status"] == "deleted"
    assert row["api_key"] == "" and row["base_url"] == ""
    lock_sql = next(call[1] for call in executions if call[0] == "fetchone")
    assert "FOR UPDATE" in lock_sql
    update_sql = next(call[1] for call in executions if call[0] == "execute")
    assert "lifecycle_status='deleted'" in update_sql

    assert client.get("/api/providers").json() == []
    repeated = client.delete("/api/providers/provider-1")
    assert repeated.status_code == 404
    assert counts == {"commit": 1, "rollback": 1}
