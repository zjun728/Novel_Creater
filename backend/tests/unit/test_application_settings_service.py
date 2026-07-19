from __future__ import annotations

from contextlib import asynccontextmanager
import importlib

import pytest

from backend.schema_manifest import manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION


def _application_settings_symbols():
    try:
        domain = importlib.import_module("backend.domain.application_settings")
        service_module = importlib.import_module(
            "backend.services.application_settings"
        )
    except ModuleNotFoundError as exc:
        pytest.fail(f"application settings boundary is missing: {exc}")
    return domain, service_module


def provider(
    provider_id: str,
    *,
    enabled: int = 1,
    lifecycle_status: str = "active",
    provider_type: str = "openai-compatible",
):
    return {
        "id": provider_id,
        "name": f"Provider {provider_id}",
        "provider_type": provider_type,
        "model_name": f"model-{provider_id}",
        "base_url": f"https://{provider_id}.private.test/v1",
        "api_key": f"secret-{provider_id}",
        "enabled": enabled,
        "lifecycle_status": lifecycle_status,
    }


class MemoryApplicationSettingsRepository:
    def __init__(self):
        self.settings = {
            "singleton_id": 1,
            "fallback_provider_id": None,
            "revision": 0,
            "updated_at": 10,
        }
        self.providers = {
            "ready": provider("ready"),
            "disabled": provider("disabled", enabled=0),
            "unsupported": provider(
                "unsupported", provider_type="anthropic"
            ),
        }
        self.events = []
        self.metadata = {
            "schema_version": EXPECTED_SCHEMA_VERSION,
            "manifest_hash": manifest_hash(),
        }

    def _joined(self):
        row = dict(self.settings)
        selected = self.providers.get(self.settings["fallback_provider_id"])
        if selected:
            row.update({f"provider_{key}": value for key, value in selected.items()})
        return row

    async def read_settings(self, session):
        self.events.append(("read", session))
        return self._joined()

    async def lock_settings(self, session):
        self.events.append(("settings-lock", session))
        return dict(self.settings)

    async def lock_provider(self, session, provider_id):
        self.events.append(("provider-lock", session, provider_id))
        row = self.providers.get(provider_id)
        return dict(row) if row else None

    async def compare_and_swap(
        self,
        session,
        *,
        expected_revision,
        fallback_provider_id,
        updated_at,
    ):
        self.events.append(
            (
                "cas",
                session,
                expected_revision,
                fallback_provider_id,
                updated_at,
            )
        )
        if self.settings["revision"] != expected_revision:
            return False
        self.settings.update(
            fallback_provider_id=fallback_provider_id,
            revision=expected_revision + 1,
            updated_at=updated_at,
        )
        return True

    async def read_schema_metadata(self, session):
        self.events.append(("metadata", session))
        return dict(self.metadata)


def factories():
    sessions = []

    @asynccontextmanager
    async def transaction():
        session = object()
        sessions.append(("transaction", session))
        yield session

    @asynccontextmanager
    async def connection():
        session = object()
        sessions.append(("connection", session))
        yield session

    return transaction, connection, sessions


def build_service(repository, *, corpus_ready=lambda: True):
    _, service_module = _application_settings_symbols()
    transaction, connection, sessions = factories()
    service = service_module.ApplicationSettingsService(
        repository,
        transaction_factory=transaction,
        connection_factory=connection,
        clock=lambda: 99,
        corpus_store_ready=corpus_ready,
        scheduler_enabled=False,
        scheduler_state="disabled",
        application_version="1.0.0",
    )
    return service, service_module, sessions


@pytest.mark.asyncio
async def test_get_returns_only_public_fallback_display_and_model_identity():
    repository = MemoryApplicationSettingsRepository()
    repository.settings["fallback_provider_id"] = "ready"
    service, _, _ = build_service(repository)

    result = await service.get()

    assert result.revision == 0
    assert result.fallback_provider.model_dump() == {
        "id": "ready",
        "name": "Provider ready",
        "provider_type": "openai-compatible",
        "model": "model-ready",
        "ready": True,
    }
    rendered = str(result.model_dump())
    assert "secret-ready" not in rendered
    assert "private.test" not in rendered


@pytest.mark.asyncio
async def test_default_model_update_locks_validates_and_cas_updates_one_row():
    domain, _ = _application_settings_symbols()
    repository = MemoryApplicationSettingsRepository()
    service, _, sessions = build_service(repository)

    result = await service.update_default_model(
        domain.UpdateDefaultModel(
            expected_revision=0,
            fallback_provider_id="ready",
        )
    )

    transaction_session = sessions[0][1]
    assert result.revision == 1
    assert result.fallback_provider.id == "ready"
    assert repository.events == [
        ("settings-lock", transaction_session),
        ("provider-lock", transaction_session, "ready"),
        ("cas", transaction_session, 0, "ready", 99),
        ("read", transaction_session),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_id", ["disabled", "unsupported", "missing"])
async def test_default_model_rejects_every_not_ready_provider_before_cas(
    provider_id,
):
    domain, _ = _application_settings_symbols()
    repository = MemoryApplicationSettingsRepository()
    service, service_module, _ = build_service(repository)

    with pytest.raises(service_module.ApplicationFallbackUnavailable):
        await service.update_default_model(
            domain.UpdateDefaultModel(
                expected_revision=0,
                fallback_provider_id=provider_id,
            )
        )

    assert not [event for event in repository.events if event[0] == "cas"]
    assert repository.settings["revision"] == 0


@pytest.mark.asyncio
async def test_default_model_clear_is_nullable_and_still_revision_cas():
    domain, _ = _application_settings_symbols()
    repository = MemoryApplicationSettingsRepository()
    repository.settings.update(fallback_provider_id="ready", revision=4)
    service, _, _ = build_service(repository)

    result = await service.update_default_model(
        domain.UpdateDefaultModel(
            expected_revision=4,
            fallback_provider_id=None,
        )
    )

    assert result.revision == 5
    assert result.fallback_provider is None
    assert not [event for event in repository.events if event[0] == "provider-lock"]


@pytest.mark.asyncio
async def test_default_model_conflict_never_repairs_or_inserts_singleton():
    domain, _ = _application_settings_symbols()
    repository = MemoryApplicationSettingsRepository()
    repository.settings["revision"] = 2
    service, service_module, _ = build_service(repository)

    with pytest.raises(service_module.ApplicationSettingsConflict):
        await service.update_default_model(
            domain.UpdateDefaultModel(
                expected_revision=1,
                fallback_provider_id=None,
            )
        )

    assert not hasattr(repository, "ensure_settings")
    assert not [event for event in repository.events if event[0] == "cas"]


@pytest.mark.asyncio
async def test_diagnostics_is_an_exact_safe_allowlist_and_swallows_probe_details():
    repository = MemoryApplicationSettingsRepository()
    repository.metadata["manifest_hash"] = "0" * 64
    sentinel = "db-host-secret provider-secret C:\\private\\corpus"

    def corpus_probe():
        raise RuntimeError(sentinel)

    service, _, _ = build_service(repository, corpus_ready=corpus_probe)
    result = await service.get_diagnostics()
    payload = result.model_dump()

    assert payload == {
        "schema_version": EXPECTED_SCHEMA_VERSION,
        "schema_manifest_match": False,
        "database_reachable": True,
        "managed_corpus_store_ready": False,
        "scheduler_enabled": False,
        "scheduler_state": "disabled",
        "application_version": "1.0.0",
    }
    assert sentinel not in str(payload)
    forbidden = {
        "host",
        "port",
        "database",
        "user",
        "dsn",
        "path",
        "provider",
        "environment",
        "exception",
    }
    assert forbidden.isdisjoint(payload)
