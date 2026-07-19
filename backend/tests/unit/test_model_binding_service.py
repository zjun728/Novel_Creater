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
        self.revision_row = None
        self.id_factory = lambda: "revision-1"
        self.clock = lambda: 100
        self.fallback_provider_id = None
        self.candidate_rows = [
            {
                "source_project_id": "previous-project",
                "source_revision": 3,
                "task_key": key,
                "resolution_status": "bound",
                "provider_id": "provider-b",
                "provider_name_snapshot": "Provider provider-b",
                "model_name_snapshot": "model-provider-b",
            }
            for key in TASK_KEYS
        ]

    async def lock_inheritance_candidates(self, session, project_id):
        self.events.append("candidate_snapshots")
        return self.candidate_rows

    async def lock_application_settings(self, session):
        self.events.append("application_settings")
        return {
            "singleton_id": 1,
            "fallback_provider_id": self.fallback_provider_id,
            "revision": 0,
        }

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
        self.revision_row = row

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
        "candidate_snapshots",
        "application_settings",
        "candidate_ids",
        ("provider_locks", ("provider-a", "provider-b")),
        "revision",
        "items",
        "head",
    ]
    assert len(repository.item_rows) == len(TASK_KEYS)
    assert all(row["provider_id"] == "provider-a" for row in repository.item_rows)


def snapshot(project_id, provider_id, *, task_keys=TASK_KEYS, model=None):
    return [
        {
            "source_project_id": project_id,
            "source_revision": 4,
            "task_key": task_key,
            "resolution_status": "bound",
            "provider_id": provider_id,
            "provider_name_snapshot": f"Provider {provider_id}",
            "model_name_snapshot": model or f"model-{provider_id}",
        }
        for task_key in task_keys
    ]


@pytest.mark.asyncio
async def test_inheritance_skips_partial_latest_and_copies_older_ready_snapshot_whole():
    repository = InitializeRepository()
    repository.candidate_rows = [
        *snapshot("latest-partial", "provider-b", task_keys=TASK_KEYS[:-1]),
        *snapshot("older-ready", "provider-a"),
    ]
    service = ModelBindingService(repository, transaction_factory=None)

    await service.initialize_project(object(), "new-project")

    assert all(row["provider_id"] == "provider-a" for row in repository.item_rows)
    assert repository.revision_row["source_project_id"] == "older-ready"


@pytest.mark.asyncio
async def test_inheritance_skips_stale_latest_without_task_by_task_repair():
    repository = InitializeRepository()
    repository.candidate_rows = [
        *snapshot("latest-stale", "provider-b"),
        *snapshot("older-ready", "provider-a"),
    ]
    service = ModelBindingService(repository, transaction_factory=None)

    await service.initialize_project(object(), "new-project")

    assert all(row["provider_id"] == "provider-a" for row in repository.item_rows)
    assert repository.revision_row["source_project_id"] == "older-ready"


@pytest.mark.asyncio
async def test_ready_explicit_fallback_applies_to_all_tasks_when_no_snapshot_ready():
    repository = InitializeRepository()
    repository.fallback_provider_id = "provider-a"
    repository.candidate_rows = snapshot(
        "latest-stale",
        "provider-b",
        model="stale-model",
    )
    service = ModelBindingService(repository, transaction_factory=None)

    await service.initialize_project(object(), "new-project")

    assert len(repository.item_rows) == len(TASK_KEYS)
    assert all(row["provider_id"] == "provider-a" for row in repository.item_rows)
    assert repository.revision_row["source_project_id"] is None


@pytest.mark.asyncio
async def test_first_ready_provider_applies_to_all_tasks_without_ready_fallback():
    repository = InitializeRepository()
    repository.fallback_provider_id = "provider-b"
    repository.candidate_rows = []
    service = ModelBindingService(repository, transaction_factory=None)

    await service.initialize_project(object(), "new-project")

    assert all(row["provider_id"] == "provider-a" for row in repository.item_rows)


@pytest.mark.asyncio
async def test_no_ready_source_creates_all_eight_unbound_without_failing_creation():
    repository = InitializeRepository()
    repository.candidate_rows = []
    repository.fallback_provider_id = None

    async def no_candidates(session):
        repository.events.append("candidate_ids")
        return []

    repository.list_available_providers = no_candidates
    service = ModelBindingService(repository, transaction_factory=None)

    await service.initialize_project(object(), "new-project")

    assert len(repository.item_rows) == len(TASK_KEYS)
    assert all(row["resolution_status"] == "unbound" for row in repository.item_rows)
    assert all(row["provider_id"] is None for row in repository.item_rows)
