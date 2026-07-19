"""Global fallback-model and safe application diagnostic routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from backend.config import MANAGED_CORPUS_ROOT
from backend.database import connection, transaction
from backend.domain.application_settings import UpdateDefaultModel
from backend.repositories.application_settings import (
    ApplicationSettingsRepository,
)
from backend.security.provider_secrets import (
    normalize_provider_secrets,
    sanitize_provider_secret_text,
)
from backend.services.application_settings import ApplicationSettingsService


APPLICATION_VERSION = "1.0.0"
router = APIRouter(tags=["application-settings"])


def _corpus_store_ready() -> bool:
    return (
        isinstance(MANAGED_CORPUS_ROOT, Path)
        and MANAGED_CORPUS_ROOT.exists()
        and MANAGED_CORPUS_ROOT.is_dir()
    )


_service = ApplicationSettingsService(
    ApplicationSettingsRepository(),
    transaction_factory=transaction,
    connection_factory=connection,
    corpus_store_ready=_corpus_store_ready,
    scheduler_enabled=False,
    scheduler_state="disabled",
    application_version=APPLICATION_VERSION,
)


def get_application_settings_service() -> ApplicationSettingsService:
    return _service


class DefaultModelBody(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    expectedRevision: int = Field(ge=0)
    fallbackProviderId: str | None = Field(default=None, min_length=1)


def _public_settings(result) -> dict:
    provider = result.fallback_provider
    redaction_values = normalize_provider_secrets(
        getattr(result, "redaction_values", ())
    )
    fallback = None
    if provider is not None:
        fallback = {
            "id": sanitize_provider_secret_text(
                provider.id, redaction_values
            ),
            "name": sanitize_provider_secret_text(
                provider.name, redaction_values
            ),
            "providerType": sanitize_provider_secret_text(
                provider.provider_type, redaction_values
            ),
            "model": sanitize_provider_secret_text(
                provider.model, redaction_values
            ),
            "ready": provider.ready is True,
        }
    return {
        "revision": result.revision,
        "fallbackProvider": fallback,
    }


@router.get("/settings/application")
async def get_application_settings(
    service=Depends(get_application_settings_service),
):
    return _public_settings(await service.get())


@router.put("/settings/application/default-model")
async def update_default_model(
    body: DefaultModelBody,
    service=Depends(get_application_settings_service),
):
    result = await service.update_default_model(
        UpdateDefaultModel(
            expected_revision=body.expectedRevision,
            fallback_provider_id=body.fallbackProviderId,
        )
    )
    return _public_settings(result)


@router.get("/settings/application/diagnostics")
async def get_application_diagnostics(
    service=Depends(get_application_settings_service),
):
    result = await service.get_diagnostics()
    return {
        "schemaVersion": result.schema_version,
        "schemaManifestMatch": result.schema_manifest_match,
        "databaseReachable": result.database_reachable,
        "managedCorpusStoreReady": result.managed_corpus_store_ready,
        "schedulerEnabled": result.scheduler_enabled,
        "schedulerState": result.scheduler_state,
        "applicationVersion": result.application_version,
    }
