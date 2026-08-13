"""Typed Provider HTTP commands over the transactional profile service."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.database import connection, transaction
from backend.domain.provider_policy import provider_type_is_supported
from backend.gateways.provider_connection import ProviderConnectionGateway
from backend.security.provider_secrets import (
    PUBLIC_SECRET_COLLISION_MESSAGE,
    normalize_provider_secrets,
    provider_public_fields_contain_secret,
)
from backend.services.provider_profiles import (
    ClearProviderApiKeyCommand,
    DeleteProviderCommand,
    ProviderCreateCommand,
    ProviderProfileService,
    ProviderUpdateCommand,
    SqlProviderProfileRepository,
)


router = APIRouter(tags=["providers"])
IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,63}$"


def build_provider_profile_service(
    *, connection_gateway=None
) -> ProviderProfileService:
    return ProviderProfileService(
        SqlProviderProfileRepository(),
        transaction_factory=transaction,
        connection_factory=connection,
        connection_gateway=connection_gateway or ProviderConnectionGateway(),
    )


def get_provider_profile_service(request: Request) -> ProviderProfileService:
    service = getattr(request.app.state, "provider_profile_service", None)
    return service or build_provider_profile_service()


class _StrictBody(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class ProviderCreate(_StrictBody):
    name: str = Field(min_length=1, max_length=120)
    providerType: str = Field(
        default="openai-compatible", min_length=1, max_length=64
    )
    model: str = Field(min_length=1, max_length=160)
    baseURL: str = Field(min_length=1, max_length=2048)
    apiKey: str = Field(min_length=1)
    enabled: bool = True
    sortOrder: int = 0
    stream: bool = True
    maxContextTokens: int = Field(default=200_000, gt=0)
    maxOutputTokens: int = Field(default=4096, gt=0)
    temperature: float = Field(default=0.8, ge=0, le=2)
    topP: float = Field(default=0.9, ge=0, le=1)
    supportsJSON: bool = True
    supportsStreaming: bool = True
    notes: str = ""
    thinking: Optional[dict] = None
    idempotencyKey: str = Field(pattern=IDEMPOTENCY_PATTERN)

    @field_validator("name", "providerType", "model", "baseURL", "apiKey")
    @classmethod
    def required_fields_are_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must not be blank")
        return value

    @field_validator("providerType")
    @classmethod
    def provider_type_is_supported(cls, value: str) -> str:
        if not provider_type_is_supported(value):
            raise ValueError("Unsupported Provider type")
        return value

    @model_validator(mode="after")
    def public_fields_cannot_contain_private_configuration(self):
        secrets = normalize_provider_secrets((self.apiKey, self.baseURL))
        if provider_public_fields_contain_secret(
            {
                "name": self.name.strip(),
                "providerType": self.providerType.strip(),
                "model": self.model.strip(),
                "notes": self.notes,
                "thinking": self.thinking,
            },
            secrets,
        ):
            raise ValueError(PUBLIC_SECRET_COLLISION_MESSAGE)
        return self


class ProviderUpdate(_StrictBody):
    expectedRevision: int = Field(ge=0)
    idempotencyKey: str = Field(pattern=IDEMPOTENCY_PATTERN)
    name: Optional[str] = Field(default=None, max_length=120)
    model: Optional[str] = Field(default=None, max_length=160)
    baseURL: Optional[str] = Field(default=None, max_length=2048)
    apiKey: Optional[str] = None
    enabled: Optional[bool] = None
    sortOrder: Optional[int] = None
    stream: Optional[bool] = None
    maxContextTokens: Optional[int] = Field(default=None, gt=0)
    maxOutputTokens: Optional[int] = Field(default=None, gt=0)
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    topP: Optional[float] = Field(default=None, ge=0, le=1)
    supportsJSON: Optional[bool] = None
    supportsStreaming: Optional[bool] = None
    notes: Optional[str] = None
    thinking: Optional[dict] = None

    @field_validator("name", "model")
    @classmethod
    def public_identity_is_not_blank(cls, value: str | None):
        if value is not None and not value.strip():
            raise ValueError("provider identity must not be blank")
        return value

    @model_validator(mode="after")
    def non_secret_fields_cannot_be_cleared(self):
        for field in ("name", "model", "notes"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError("provider public fields cannot be cleared")
        secrets = normalize_provider_secrets((self.apiKey, self.baseURL))
        if provider_public_fields_contain_secret(
            {
                field: getattr(self, field)
                for field in ("name", "model", "notes", "thinking")
                if field in self.model_fields_set
            },
            secrets,
        ):
            raise ValueError(PUBLIC_SECRET_COLLISION_MESSAGE)
        return self


class ProviderMutation(_StrictBody):
    expectedRevision: int = Field(ge=0)
    idempotencyKey: str = Field(pattern=IDEMPOTENCY_PATTERN)


@router.get("/providers")
async def list_providers(
    service: ProviderProfileService = Depends(get_provider_profile_service),
):
    return [
        profile.to_dict()
        for profile in await service.list_profiles()
    ]


@router.post("/providers")
async def create_provider(
    data: ProviderCreate,
    service: ProviderProfileService = Depends(get_provider_profile_service),
):
    row = await service.create(
        ProviderCreateCommand(
            name=data.name,
            provider_type=data.providerType,
            model=data.model,
            base_url=data.baseURL,
            api_key=data.apiKey,
            enabled=data.enabled,
            sort_order=data.sortOrder,
            stream=data.stream,
            max_context_tokens=data.maxContextTokens,
            max_output_tokens=data.maxOutputTokens,
            temperature=data.temperature,
            top_p=data.topP,
            supports_json=data.supportsJSON,
            supports_streaming=data.supportsStreaming,
            notes=data.notes,
            thinking=data.thinking,
            idempotency_key=data.idempotencyKey,
        )
    )
    return row.to_dict()


@router.put("/providers/{provider_id}")
async def update_provider(
    provider_id: str,
    data: ProviderUpdate,
    service: ProviderProfileService = Depends(get_provider_profile_service),
):
    changes = data.model_dump(
        exclude_unset=True,
        exclude={"expectedRevision", "idempotencyKey"},
    )
    for field in ("apiKey", "baseURL"):
        if not isinstance(changes.get(field), str) or not changes[field].strip():
            changes.pop(field, None)
    row = await service.update(
        ProviderUpdateCommand(
            provider_id=provider_id,
            expected_revision=data.expectedRevision,
            idempotency_key=data.idempotencyKey,
            changes=changes,
        )
    )
    return row.to_dict()


@router.delete("/providers/{provider_id}")
async def delete_provider(
    provider_id: str,
    data: ProviderMutation,
    service: ProviderProfileService = Depends(get_provider_profile_service),
):
    row = await service.delete(
        DeleteProviderCommand(
            provider_id=provider_id,
            expected_revision=data.expectedRevision,
            idempotency_key=data.idempotencyKey,
        )
    )
    return row.to_dict()


@router.post("/providers/{provider_id}/clear-api-key")
async def clear_provider_api_key(
    provider_id: str,
    data: ProviderMutation,
    service: ProviderProfileService = Depends(get_provider_profile_service),
):
    row = await service.clear_api_key(
        ClearProviderApiKeyCommand(
            provider_id=provider_id,
            expected_revision=data.expectedRevision,
            idempotency_key=data.idempotencyKey,
        )
    )
    return row.to_dict()


@router.post("/providers/{provider_id}/test-connection")
async def test_provider_connection(
    provider_id: str,
    service: ProviderProfileService = Depends(get_provider_profile_service),
):
    return (await service.test_connection(provider_id)).to_dict()
