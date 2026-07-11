"""Provider configuration with a strict public-response boundary."""

from __future__ import annotations

import json
import time
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.database import fetchall, transaction
from backend.serializers.provider import provider_public, providers_public


router = APIRouter(tags=["providers"])

_PROVIDER_UPDATE_COLUMNS = {
    "name": "name",
    "providerType": "provider_type",
    "model": "model_name",
    "baseURL": "base_url",
    "apiKey": "api_key",
    "enabled": "enabled",
    "sortOrder": "sort_order",
    "stream": "stream",
    "maxContextTokens": "max_context_tokens",
    "maxOutputTokens": "max_output_tokens",
    "temperature": "temperature",
    "topP": "top_p",
    "supportsJSON": "supports_json",
    "supportsStreaming": "supports_streaming",
    "notes": "notes",
    "thinking": "thinking",
}


def _is_blank(value) -> bool:
    return isinstance(value, str) and not value.strip()


class ProviderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    providerType: str = Field(default="openai-compatible", min_length=1)
    model: str = Field(min_length=1)
    baseURL: str = Field(min_length=1)
    apiKey: str = Field(min_length=1)
    enabled: bool = True
    sortOrder: int = 0
    stream: bool = True
    maxContextTokens: int = Field(default=200_000, gt=0)
    maxOutputTokens: int = Field(default=4096, gt=0)
    temperature: float = 0.8
    topP: float = 0.9
    supportsJSON: bool = True
    supportsStreaming: bool = True
    notes: str = ""
    thinking: Optional[dict] = None

    @field_validator("name", "providerType", "model", "baseURL", "apiKey")
    @classmethod
    def required_fields_are_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must not be blank")
        return value


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    providerType: Optional[str] = None
    model: Optional[str] = None
    baseURL: Optional[str] = None
    apiKey: Optional[str] = None
    enabled: Optional[bool] = None
    sortOrder: Optional[int] = None
    stream: Optional[bool] = None
    maxContextTokens: Optional[int] = Field(default=None, gt=0)
    maxOutputTokens: Optional[int] = Field(default=None, gt=0)
    temperature: Optional[float] = None
    topP: Optional[float] = None
    supportsJSON: Optional[bool] = None
    supportsStreaming: Optional[bool] = None
    notes: Optional[str] = None
    thinking: Optional[dict] = None

    @field_validator("name", "providerType", "model")
    @classmethod
    def active_fields_are_not_blank(cls, value: str | None):
        if value is not None and not value.strip():
            raise ValueError("active provider fields must not be blank")
        return value

    @model_validator(mode="after")
    def active_required_fields_cannot_be_cleared(self):
        required = {"name", "providerType", "model", "baseURL", "apiKey", "notes"}
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in required
        ):
            raise ValueError("active provider fields cannot be cleared")
        return self


@router.get("/providers")
async def list_providers():
    rows = await fetchall(
        """SELECT * FROM provider_profiles WHERE lifecycle_status='active'
           ORDER BY sort_order, created_at, id"""
    )
    return providers_public(rows)


@router.post("/providers")
async def create_provider(data: ProviderCreate):
    now = int(time.time() * 1000)
    provider_id = str(uuid4())
    async with transaction() as session:
        await session.execute(
            """INSERT INTO provider_profiles
               (id, name, provider_type, model_name, base_url, api_key, enabled,
                sort_order, stream, max_context_tokens, max_output_tokens,
                temperature, top_p, supports_json, supports_streaming, notes,
                thinking, lifecycle_status, deleted_at, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                provider_id, data.name, data.providerType, data.model,
                data.baseURL, data.apiKey, int(data.enabled), data.sortOrder,
                int(data.stream), data.maxContextTokens, data.maxOutputTokens,
                data.temperature, data.topP, int(data.supportsJSON),
                int(data.supportsStreaming), data.notes,
                json.dumps(data.thinking, ensure_ascii=False)
                if data.thinking else None,
                "active", None, now, now,
            ),
        )
        created = await session.fetchone(
            """SELECT * FROM provider_profiles
               WHERE id=%s AND lifecycle_status='active'""",
            (provider_id,),
        )
    return provider_public(created)


@router.put("/providers/{provider_id}")
async def update_provider(provider_id: str, data: ProviderUpdate):
    async with transaction() as session:
        current = await session.fetchone(
            """SELECT * FROM provider_profiles
               WHERE id=%s AND lifecycle_status='active' FOR UPDATE""",
            (provider_id,),
        )
        if current is None:
            raise HTTPException(status_code=404, detail="Provider not found")
        incoming = data.model_dump(exclude_unset=True)
        if "apiKey" not in incoming or _is_blank(incoming["apiKey"]):
            incoming.pop("apiKey", None)
        if "baseURL" not in incoming or _is_blank(incoming["baseURL"]):
            incoming.pop("baseURL", None)

        sets = []
        args = []
        for key, value in incoming.items():
            sets.append(f"{_PROVIDER_UPDATE_COLUMNS[key]}=%s")
            if key == "thinking":
                value = (
                    json.dumps(value, ensure_ascii=False)
                    if value is not None else None
                )
            elif isinstance(value, bool):
                value = int(value)
            args.append(value)
        if sets:
            sets.append("updated_at=%s")
            args.extend((int(time.time() * 1000), provider_id))
            await session.execute(
                f"""UPDATE provider_profiles SET {', '.join(sets)}
                    WHERE id=%s AND lifecycle_status='active'""",
                args,
            )
        updated = await session.fetchone(
            """SELECT * FROM provider_profiles
               WHERE id=%s AND lifecycle_status='active'""",
            (provider_id,),
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="Provider not found")
    return provider_public(updated)


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: str):
    async with transaction() as session:
        current = await session.fetchone(
            """SELECT id FROM provider_profiles
               WHERE id=%s AND lifecycle_status='active' FOR UPDATE""",
            (provider_id,),
        )
        if current is None:
            raise HTTPException(status_code=404, detail="Provider not found")
        now = int(time.time() * 1000)
        changed = await session.execute(
            """UPDATE provider_profiles
               SET enabled=0,lifecycle_status='deleted',api_key='',base_url='',
                   deleted_at=%s,updated_at=%s
               WHERE id=%s AND lifecycle_status='active'""",
            (now, now, provider_id),
        )
        if changed != 1:
            raise HTTPException(status_code=404, detail="Provider not found")
    return {"ok": True}
