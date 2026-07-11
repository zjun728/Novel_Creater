"""Provider configuration with a strict public-response boundary."""

from __future__ import annotations

import json
import time
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.database import execute, fetchall, fetchone
from backend.serializers.provider import provider_public, providers_public
from .helpers import to_snake


router = APIRouter(tags=["providers"])


def _is_blank(value) -> bool:
    return isinstance(value, str) and not value.strip()


class ProviderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    providerType: str = "openai-compatible"
    model: str = ""
    baseURL: str = ""
    apiKey: str = ""
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


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    providerType: Optional[str] = None
    model: Optional[str] = None
    baseURL: Optional[str] = None
    apiKey: Optional[str] = None
    clearBaseURL: bool = False
    clearApiKey: bool = False
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


@router.get("/providers")
async def list_providers():
    rows = await fetchall(
        "SELECT * FROM provider_profiles ORDER BY sort_order, created_at, id"
    )
    return providers_public(rows)


@router.post("/providers")
async def create_provider(data: ProviderCreate):
    now = int(time.time() * 1000)
    provider_id = str(uuid4())
    await execute(
        """INSERT INTO provider_profiles
           (id, name, provider_type, model_name, base_url, api_key, enabled,
            sort_order, stream, max_context_tokens, max_output_tokens,
            temperature, top_p, supports_json, supports_streaming, notes,
            thinking, created_at, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            provider_id,
            data.name,
            data.providerType,
            data.model,
            data.baseURL,
            data.apiKey,
            int(data.enabled),
            data.sortOrder,
            int(data.stream),
            data.maxContextTokens,
            data.maxOutputTokens,
            data.temperature,
            data.topP,
            int(data.supportsJSON),
            int(data.supportsStreaming),
            data.notes,
            json.dumps(data.thinking, ensure_ascii=False) if data.thinking else None,
            now,
            now,
        ),
    )
    return provider_public(
        await fetchone(
            "SELECT * FROM provider_profiles WHERE id=%s", (provider_id,)
        )
    )


@router.put("/providers/{provider_id}")
async def update_provider(provider_id: str, data: ProviderUpdate):
    current = await fetchone(
        "SELECT * FROM provider_profiles WHERE id=%s", (provider_id,)
    )
    if current is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    incoming = data.model_dump(exclude_unset=True)
    clear_api_key = incoming.pop("clearApiKey", False)
    clear_base_url = incoming.pop("clearBaseURL", False)
    if clear_api_key:
        incoming["apiKey"] = ""
    elif "apiKey" not in incoming or _is_blank(incoming["apiKey"]):
        incoming.pop("apiKey", None)
    if clear_base_url:
        incoming["baseURL"] = ""
    elif "baseURL" not in incoming or _is_blank(incoming["baseURL"]):
        incoming.pop("baseURL", None)

    sets = []
    args = []
    field_columns = {"model": "model_name"}
    for key, value in incoming.items():
        column = field_columns.get(key, to_snake(key))
        sets.append(f"{column}=%s")
        if key == "thinking":
            value = (
                json.dumps(value, ensure_ascii=False)
                if value is not None
                else None
            )
        elif isinstance(value, bool):
            value = int(value)
        args.append(value)
    if sets:
        sets.append("updated_at=%s")
        args.extend((int(time.time() * 1000), provider_id))
        await execute(
            f"UPDATE provider_profiles SET {', '.join(sets)} WHERE id=%s",
            args,
        )
    return provider_public(
        await fetchone(
            "SELECT * FROM provider_profiles WHERE id=%s", (provider_id,)
        )
    )


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: str):
    await execute("DELETE FROM provider_profiles WHERE id=%s", (provider_id,))
    return {"ok": True}


async def _binding_items(project_id: str):
    rows = await fetchall(
        """SELECT i.task_key, p.*
           FROM task_model_binding_items i
           JOIN provider_profiles p ON p.id=i.provider_id
           WHERE i.project_id=%s ORDER BY i.task_key""",
        (project_id,),
    )
    return [
        {"taskKey": row["task_key"], "provider": provider_public(row)}
        for row in rows
    ]


@router.get("/projects/{project_id}/bindings")
async def get_bindings(project_id: str):
    binding = await fetchone(
        "SELECT * FROM task_model_bindings WHERE project_id=%s", (project_id,)
    )
    if binding is None:
        return None
    return {
        "id": binding["id"],
        "projectId": project_id,
        "items": await _binding_items(project_id),
    }


@router.get("/projects/{project_id}/bindings/status")
async def get_bindings_status(project_id: str):
    project = await fetchone(
        "SELECT id FROM projects WHERE id=%s", (project_id,)
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    binding = await get_bindings(project_id)
    items = binding["items"] if binding else []
    return {
        "projectId": project_id,
        "hasBinding": bool(items),
        "items": items,
        "message": (
            "Provider bindings configured"
            if items
            else "No enabled Provider is bound"
        ),
    }
