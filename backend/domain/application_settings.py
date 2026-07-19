"""Application-wide default model and safe diagnostic contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _FrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class ApplicationProviderIdentity(_FrozenModel):
    """The only Provider fields allowed through application settings."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    provider_type: str = Field(min_length=1)
    model: str = Field(min_length=1)
    ready: bool


class ApplicationSettings(_FrozenModel):
    revision: int = Field(ge=0)
    fallback_provider: ApplicationProviderIdentity | None
    redaction_values: tuple[str, ...] = Field(default=(), exclude=True)


class UpdateDefaultModel(_FrozenModel):
    expected_revision: int = Field(ge=0)
    fallback_provider_id: str | None = Field(default=None, min_length=1)


class ApplicationDiagnostics(_FrozenModel):
    schema_version: str = Field(min_length=1)
    schema_manifest_match: bool
    database_reachable: bool
    managed_corpus_store_ready: bool
    scheduler_enabled: bool
    scheduler_state: str = Field(min_length=1)
    application_version: str = Field(min_length=1)
