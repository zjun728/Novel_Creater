from __future__ import annotations

import pytest

from backend.domain.model_bindings import TASK_KEYS
from backend.services.model_bindings import (
    ModelBindingService,
    provider_is_available,
)


def provider(provider_id, *, status="active", enabled=1, sort_order=0):
    return {
        "id": provider_id,
        "name": f"Provider {provider_id}",
        "provider_type": "openai-compatible",
        "model_name": f"model-{provider_id}",
        "base_url": f"https://{provider_id}.test/v1",
        "api_key": f"key-{provider_id}",
        "enabled": enabled,
        "lifecycle_status": status,
        "sort_order": sort_order,
        "created_at": sort_order,
    }


def test_only_generation_capable_provider_types_are_available():
    openai_compatible = provider("deepseek")
    anthropic = {
        **provider("anthropic"),
        "provider_type": "anthropic",
    }

    assert provider_is_available(openai_compatible) is True
    assert provider_is_available(anthropic) is False


def test_binding_snapshots_use_longest_first_shared_secret_sanitizer():
    private_url = "https://secret.internal.example/v1"
    row = {
        **provider("overlap"),
        "name": f"private endpoint {private_url}",
        "model_name": private_url,
        "api_key": "https",
        "base_url": private_url,
    }

    item = ModelBindingService._bound_item("seed", row)

    assert item.provider_name_snapshot == "private endpoint [REDACTED]"
    assert item.model_name_snapshot == "[REDACTED]"
    assert "secret.internal.example" not in str(item)


class InitializeRepository:
    def __init__(self):
        self.events = []
        self.item_rows = None
        self.id_factory = lambda: "revision-1"
        self.clock = lambda: 100

    async def lock_previous_project(self, session, project_id):
        self.events.append("previous_lock")
        return {"id": "previous-project"}

    async def find_previous_project(self, session, project_id):
        self.events.append("previous_unlocked")
        return {"id": "previous-project"}

    async def lock_current_rows(self, session, project_id):
        self.events.append("binding_lock")
        return [{"task_key": key, "provider_id": "provider-b"} for key in TASK_KEYS]

    async def read_current_rows(self, session, project_id):
        self.events.append("binding_unlocked")
        return [{"task_key": key, "provider_id": "provider-b"} for key in TASK_KEYS]

    async def list_available_providers(self, session):
        self.events.append("candidate_ids")
        return [
            provider("provider-b", sort_order=0),
            provider("provider-a", sort_order=1),
        ]

    async def lock_providers(self, session, provider_ids):
        self.events.append(("provider_locks", tuple(sorted(provider_ids))))
        return [
            provider("provider-a", sort_order=1),
            provider("provider-b", status="deleted", enabled=0, sort_order=0),
        ]

    async def insert_revision(self, session, row):
        self.events.append("revision")

    async def insert_items(self, session, revision_id, rows):
        self.events.append("items")
        self.item_rows = rows

    async def insert_head(self, session, row):
        self.events.append("head")

    async def lock_project_creation_guard(self, session):
        self.events.append(("creation_guard", session))


@pytest.mark.asyncio
async def test_project_creation_lock_delegates_on_the_caller_session():
    repository = InitializeRepository()
    service = ModelBindingService(repository, transaction_factory=None)
    session = object()

    await service.lock_project_creation(session)

    assert repository.events == [("creation_guard", session)]


@pytest.mark.asyncio
async def test_initialize_locks_and_revalidates_before_writing_revision():
    repository = InitializeRepository()
    service = ModelBindingService(repository, transaction_factory=None)
    session = object()

    await service.initialize_project(session, "new-project")

    assert repository.events == [
        "previous_lock",
        "binding_lock",
        "candidate_ids",
        ("provider_locks", ("provider-a", "provider-b")),
        "revision",
        "items",
        "head",
    ]
    assert len(repository.item_rows) == len(TASK_KEYS)
    assert all(row["provider_id"] == "provider-a" for row in repository.item_rows)
