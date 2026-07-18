from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import is_dataclass
import json

import pytest

from backend.services.provider_profiles import (
    ClearProviderApiKeyCommand,
    DeleteProviderCommand,
    ProviderCreateCommand,
    ProviderIdempotencyConflict,
    ProviderProfileConflict,
    ProviderProfileService,
    ProviderUpdateCommand,
)


SECRET = "saved-provider-secret"
PRIVATE_URL = "https://saved-provider.example/v1"
FORBIDDEN_KEYS = {
    "apikey",
    "baseurl",
    "authorization",
    "token",
    "password",
}


def assert_public_profile(value):
    assert is_dataclass(value)
    assert not hasattr(value, "api_key")
    assert not hasattr(value, "base_url")
    payload = value.to_dict()

    def visit(item):
        if isinstance(item, dict):
            for key, nested in item.items():
                normalized = str(key).casefold().replace("_", "").replace("-", "")
                assert normalized not in FORBIDDEN_KEYS
                visit(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested)

    visit(payload)
    rendered = json.dumps(payload, ensure_ascii=False)
    assert SECRET not in rendered
    assert PRIVATE_URL not in rendered
    return payload


def provider_row(**overrides):
    row = {
        "id": "provider-1",
        "name": "Provider One",
        "provider_type": "openai-compatible",
        "model_name": "model-one",
        "base_url": PRIVATE_URL,
        "api_key": SECRET,
        "enabled": 1,
        "sort_order": 0,
        "stream": 1,
        "max_context_tokens": 200_000,
        "max_output_tokens": 4096,
        "temperature": 0.8,
        "top_p": 0.9,
        "supports_json": 1,
        "supports_streaming": 1,
        "notes": "",
        "thinking": None,
        "lifecycle_status": "active",
        "revision": 4,
        "deleted_at": None,
        "created_at": 10,
        "updated_at": 20,
    }
    row.update(overrides)
    return row


class MemoryProviderRepository:
    def __init__(self, rows=None):
        self.profiles = {
            row["id"]: dict(row)
            for row in ([provider_row()] if rows is None else rows)
        }
        self.requests = {}
        self.events = []

    async def list_profiles(self, session):
        self.events.append("list_profiles")
        return [
            dict(row)
            for row in self.profiles.values()
            if row["lifecycle_status"] != "deleted"
        ]

    async def lock_create_request(self, session, idempotency_key):
        self.events.append("lock_create_request")
        for request in self.requests.values():
            if (
                request["mutation_kind"] == "create"
                and request["idempotency_key"] == idempotency_key
            ):
                return dict(request)
        return None

    async def lock_mutation_request(self, session, provider_id, idempotency_key):
        self.events.append("lock_mutation_request")
        request = self.requests.get((provider_id, idempotency_key))
        return dict(request) if request else None

    async def lock_profile(self, session, provider_id):
        self.events.append("lock_profile")
        row = self.profiles.get(provider_id)
        return dict(row) if row else None

    async def read_profile(self, session, provider_id):
        self.events.append("read_profile")
        row = self.profiles.get(provider_id)
        return dict(row) if row else None

    async def read_connection_profile(self, session, provider_id):
        self.events.append("read_connection_profile")
        row = self.profiles.get(provider_id)
        return dict(row) if row else None

    async def insert_profile(self, session, row):
        self.events.append("insert_profile")
        self.profiles[row["id"]] = dict(row)

    async def compare_and_swap_profile(
        self, session, provider_id, expected_revision, changes
    ):
        self.events.append("compare_and_swap_profile")
        row = self.profiles.get(provider_id)
        if row is None or row["revision"] != expected_revision:
            return False
        row.update(changes)
        return True

    async def insert_mutation_request(self, session, request):
        self.events.append("insert_mutation_request")
        key = (request["provider_id"], request["idempotency_key"])
        self.requests[key] = dict(request)


class FakeGateway:
    def __init__(self, result=None):
        self.result = result or {
            "ok": True,
            "code": "connected",
            "latencyMs": 12,
            "publicMessage": "连接成功",
        }
        self.providers = []

    async def test_connection(self, provider):
        self.providers.append(dict(provider))
        return dict(self.result)


class Harness:
    def __init__(self, rows=None):
        self.repository = MemoryProviderRepository(rows)
        self.gateway = FakeGateway()
        self.events = []
        self.ids = iter(("generated-provider-id", "request-id-1", "request-id-2"))
        self.times = iter((100, 101, 102, 103, 104, 105))

        @asynccontextmanager
        async def transaction():
            self.events.append("transaction_enter")
            try:
                yield object()
            except BaseException:
                self.events.append("transaction_rollback")
                raise
            else:
                self.events.append("transaction_commit")

        @asynccontextmanager
        async def connection():
            self.events.append("connection_enter")
            try:
                yield object()
            finally:
                self.events.append("connection_exit")

        self.service = ProviderProfileService(
            self.repository,
            transaction_factory=transaction,
            connection_factory=connection,
            connection_gateway=self.gateway,
            id_factory=lambda: next(self.ids),
            clock=lambda: next(self.times),
        )


def create_command(**overrides):
    values = {
        "name": "Created",
        "provider_type": "openai-compatible",
        "model": "model-created",
        "base_url": PRIVATE_URL,
        "api_key": SECRET,
        "enabled": True,
        "sort_order": 0,
        "stream": True,
        "max_context_tokens": 200_000,
        "max_output_tokens": 4096,
        "temperature": 0.8,
        "top_p": 0.9,
        "supports_json": True,
        "supports_streaming": True,
        "notes": "",
        "thinking": None,
        "idempotency_key": "create-request-key-0001",
    }
    values.update(overrides)
    return ProviderCreateCommand(**values)


@pytest.mark.asyncio
async def test_create_is_revisioned_and_idempotent_in_one_transaction():
    harness = Harness(rows=[])

    created = await harness.service.create(create_command())
    replay = await harness.service.create(create_command())

    assert created == replay
    assert_public_profile(created)
    assert created.revision == 1
    assert created.lifecycle_status == "active"
    assert len(harness.repository.profiles) == 1
    request = next(iter(harness.repository.requests.values()))
    assert request["mutation_kind"] == "create"
    assert request["expected_revision"] == 0
    assert request["result_revision"] == 1
    assert harness.repository.events.count("insert_profile") == 1
    assert harness.events == [
        "transaction_enter",
        "transaction_commit",
        "transaction_enter",
        "transaction_commit",
    ]


@pytest.mark.asyncio
async def test_update_blank_secrets_preserves_them_and_increments_revision():
    harness = Harness()

    result = await harness.service.update(
        ProviderUpdateCommand(
            provider_id="provider-1",
            expected_revision=4,
            idempotency_key="update-request-key-0001",
            changes={"apiKey": "   ", "baseURL": "", "model": "model-two"},
        )
    )

    assert_public_profile(result)
    stored = harness.repository.profiles["provider-1"]
    assert stored["api_key"] == SECRET
    assert stored["base_url"] == PRIVATE_URL
    assert stored["model_name"] == "model-two"
    assert result.revision == 5
    assert result.lifecycle_status == "active"


@pytest.mark.asyncio
async def test_clear_key_is_atomic_idempotent_and_preserves_private_base_url():
    harness = Harness()
    command = ClearProviderApiKeyCommand(
        provider_id="provider-1",
        expected_revision=4,
        idempotency_key="clear-request-key-0001",
    )

    cleared = await harness.service.clear_api_key(command)
    replay = await harness.service.clear_api_key(command)

    assert cleared == replay
    assert_public_profile(cleared)
    stored = harness.repository.profiles["provider-1"]
    assert stored["api_key"] == ""
    assert stored["base_url"] == PRIVATE_URL
    assert cleared.enabled is False
    assert cleared.has_key is False
    assert cleared.has_base_url is True
    assert cleared.lifecycle_status == "unconfigured"
    assert cleared.revision == 5
    assert harness.repository.events.count("compare_and_swap_profile") == 1
    request = harness.repository.requests[
        ("provider-1", "clear-request-key-0001")
    ]
    assert request["mutation_kind"] == "clear_key"
    assert request["result_revision"] == 5


@pytest.mark.asyncio
async def test_soft_delete_is_the_only_command_that_wipes_key_and_base_url():
    harness = Harness()

    deleted = await harness.service.delete(
        DeleteProviderCommand(
            provider_id="provider-1",
            expected_revision=4,
            idempotency_key="delete-request-key-0001",
        )
    )

    assert_public_profile(deleted)
    stored = harness.repository.profiles["provider-1"]
    assert stored["api_key"] == ""
    assert stored["base_url"] == ""
    assert stored["deleted_at"] is not None
    assert deleted.enabled is False
    assert deleted.lifecycle_status == "deleted"
    assert deleted.revision == 5


@pytest.mark.asyncio
async def test_revision_and_idempotency_conflicts_do_not_write():
    harness = Harness()
    with pytest.raises(ProviderProfileConflict):
        await harness.service.clear_api_key(
            ClearProviderApiKeyCommand(
                provider_id="provider-1",
                expected_revision=3,
                idempotency_key="clear-request-key-0001",
            )
        )
    assert "compare_and_swap_profile" not in harness.repository.events

    first = ClearProviderApiKeyCommand(
        provider_id="provider-1",
        expected_revision=4,
        idempotency_key="clear-request-key-0002",
    )
    await harness.service.clear_api_key(first)
    with pytest.raises(ProviderIdempotencyConflict):
        await harness.service.clear_api_key(
            ClearProviderApiKeyCommand(
                provider_id="provider-1",
                expected_revision=5,
                idempotency_key="clear-request-key-0002",
            )
        )


@pytest.mark.asyncio
async def test_connection_uses_saved_private_projection_after_read_scope_closes():
    harness = Harness()

    result = await harness.service.test_connection("provider-1")

    assert is_dataclass(result)
    assert result.to_dict() == {
        "ok": True,
        "code": "connected",
        "latencyMs": 12,
        "publicMessage": "连接成功",
    }
    assert harness.events == ["connection_enter", "connection_exit"]
    assert harness.gateway.providers == [
        {
            "provider_type": "openai-compatible",
            "model_name": "model-one",
            "base_url": PRIVATE_URL,
            "api_key": SECRET,
        }
    ]


@pytest.mark.asyncio
async def test_all_profile_reads_and_mutations_return_typed_public_projections():
    contaminated = provider_row(
        name=f"Provider {SECRET}",
        notes=f"Notes {PRIVATE_URL}",
        thinking={"authorization": SECRET, "safe": "visible"},
    )

    listed_harness = Harness(rows=[contaminated])
    listed = await listed_harness.service.list_profiles()

    create_harness = Harness(rows=[])
    created = await create_harness.service.create(
        create_command(
            name=f"Created {SECRET}",
            notes=f"Notes {PRIVATE_URL}",
            thinking={"password": SECRET, "safe": "visible"},
        )
    )

    update_harness = Harness(rows=[contaminated])
    updated = await update_harness.service.update(
        ProviderUpdateCommand(
            provider_id="provider-1",
            expected_revision=4,
            idempotency_key="update-public-request-0001",
            changes={"notes": f"Updated {SECRET} {PRIVATE_URL}"},
        )
    )

    clear_harness = Harness(rows=[contaminated])
    clear_command = ClearProviderApiKeyCommand(
        provider_id="provider-1",
        expected_revision=4,
        idempotency_key="clear-public-request-0001",
    )
    cleared = await clear_harness.service.clear_api_key(clear_command)
    replayed = await clear_harness.service.clear_api_key(clear_command)

    delete_harness = Harness(rows=[contaminated])
    deleted = await delete_harness.service.delete(
        DeleteProviderCommand(
            provider_id="provider-1",
            expected_revision=4,
            idempotency_key="delete-public-request-0001",
        )
    )

    for profile in [*listed, created, updated, cleared, replayed, deleted]:
        assert_public_profile(profile)
