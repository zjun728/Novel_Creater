"""Application fallback model and safe diagnostic use cases."""

from __future__ import annotations

import time

from backend.domain.application_settings import (
    ApplicationDiagnostics,
    ApplicationProviderIdentity,
    ApplicationSettings,
    UpdateDefaultModel,
)
from backend.domain.provider_policy import provider_is_generation_ready
from backend.http_errors import (
    ApplicationFallbackUnavailable,
    ApplicationSettingsConflict,
    ApplicationSettingsUnavailable,
)
from backend.schema_manifest import manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from backend.security.provider_secrets import (
    normalize_provider_secrets,
    sanitize_provider_secret_text,
)


class ApplicationSettingsService:
    def __init__(
        self,
        repository,
        *,
        transaction_factory,
        connection_factory,
        clock=None,
        corpus_store_ready,
        scheduler_enabled: bool,
        scheduler_state: str,
        application_version: str,
    ):
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.connection_factory = connection_factory
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.corpus_store_ready = corpus_store_ready
        self.scheduler_enabled = scheduler_enabled
        self.scheduler_state = scheduler_state
        self.application_version = application_version

    @staticmethod
    def _from_row(row) -> ApplicationSettings:
        if row is None:
            raise ApplicationSettingsUnavailable()
        redaction_values = normalize_provider_secrets(
            (
                row.get("provider_api_key"),
                row.get("provider_base_url"),
            )
        )
        fallback = None
        if row.get("fallback_provider_id") is not None:
            if row.get("provider_id") is None:
                raise ApplicationSettingsUnavailable()
            fallback = ApplicationProviderIdentity(
                id=sanitize_provider_secret_text(
                    row["provider_id"], redaction_values
                ),
                name=sanitize_provider_secret_text(
                    row["provider_name"], redaction_values
                ),
                provider_type=sanitize_provider_secret_text(
                    row["provider_provider_type"], redaction_values
                ),
                model=sanitize_provider_secret_text(
                    row["provider_model_name"], redaction_values
                ),
                ready=provider_is_generation_ready(row, prefix="provider_"),
            )
        return ApplicationSettings(
            revision=int(row["revision"]),
            fallback_provider=fallback,
            redaction_values=redaction_values,
        )

    async def get(self) -> ApplicationSettings:
        async with self.connection_factory() as session:
            row = await self.repository.read_settings(session)
        return self._from_row(row)

    async def update_default_model(
        self, command: UpdateDefaultModel
    ) -> ApplicationSettings:
        async with self.transaction_factory() as session:
            current = await self.repository.lock_settings(session)
            if current is None:
                raise ApplicationSettingsUnavailable()
            if int(current["revision"]) != command.expected_revision:
                raise ApplicationSettingsConflict()
            if command.fallback_provider_id is not None:
                selected = await self.repository.lock_provider(
                    session, command.fallback_provider_id
                )
                if not provider_is_generation_ready(selected):
                    raise ApplicationFallbackUnavailable()
            changed = await self.repository.compare_and_swap(
                session,
                expected_revision=command.expected_revision,
                fallback_provider_id=command.fallback_provider_id,
                updated_at=self.clock(),
            )
            if not changed:
                raise ApplicationSettingsConflict()
            row = await self.repository.read_settings(session)
            return self._from_row(row)

    async def get_diagnostics(self) -> ApplicationDiagnostics:
        reachable = False
        metadata = None
        try:
            async with self.connection_factory() as session:
                metadata = await self.repository.read_schema_metadata(session)
                reachable = True
        except Exception:
            metadata = None
        try:
            corpus_ready = self.corpus_store_ready() is True
        except Exception:
            corpus_ready = False
        exact_manifest = bool(
            metadata
            and metadata.get("schema_version") == EXPECTED_SCHEMA_VERSION
            and metadata.get("manifest_hash") == manifest_hash()
        )
        return ApplicationDiagnostics(
            schema_version=EXPECTED_SCHEMA_VERSION,
            schema_manifest_match=exact_manifest,
            database_reachable=reachable,
            managed_corpus_store_ready=corpus_ready,
            scheduler_enabled=self.scheduler_enabled,
            scheduler_state=self.scheduler_state,
            application_version=self.application_version,
        )
