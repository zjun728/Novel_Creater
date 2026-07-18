"""Secret-free Provider response serialization."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from backend.domain.provider_policy import provider_is_generation_ready
from backend.security.provider_secrets import (
    REDACTED,
    normalize_provider_secrets,
    sanitize_provider_public_value,
)


@dataclass(frozen=True, slots=True)
class ProviderPublicProfile:
    id: str
    name: str
    provider_type: str
    model: str
    enabled: bool
    sort_order: int
    stream: bool
    max_context_tokens: int
    max_output_tokens: int
    temperature: float
    top_p: float
    supports_json: bool
    supports_streaming: bool
    notes: str
    thinking: Any
    has_key: bool
    has_base_url: bool
    lifecycle_status: str
    revision: int
    ready: bool
    created_at: int
    updated_at: int

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "providerType": self.provider_type,
            "model": self.model,
            "enabled": self.enabled,
            "sortOrder": self.sort_order,
            "stream": self.stream,
            "maxContextTokens": self.max_context_tokens,
            "maxOutputTokens": self.max_output_tokens,
            "temperature": self.temperature,
            "topP": self.top_p,
            "supportsJSON": self.supports_json,
            "supportsStreaming": self.supports_streaming,
            "notes": self.notes,
            "thinking": self.thinking,
            "hasKey": self.has_key,
            "hasBaseURL": self.has_base_url,
            "lifecycleStatus": self.lifecycle_status,
            "revision": self.revision,
            "ready": self.ready,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class ProviderConnectionPublicResult:
    ok: bool
    code: str
    latency_ms: int
    public_message: str

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "code": self.code,
            "latencyMs": self.latency_ms,
            "publicMessage": self.public_message,
        }


def _thinking(value):
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def _secret_values(row: Mapping) -> tuple[str, ...]:
    values = []
    for key in ("api_key", "base_url"):
        value = row.get(key)
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8")
        if isinstance(value, str) and value:
            values.append(value)
    for value in row.get("_redaction_values", ()):
        values.append(value)
    return normalize_provider_secrets(values)


def provider_public_profile(
    row: Mapping | None,
) -> ProviderPublicProfile | None:
    if not row:
        return None
    public = {
        "id": row["id"],
        "name": row["name"],
        "providerType": row["provider_type"],
        "model": row["model_name"],
        "enabled": bool(row["enabled"]),
        "sortOrder": row["sort_order"],
        "stream": bool(row["stream"]),
        "maxContextTokens": row["max_context_tokens"],
        "maxOutputTokens": row["max_output_tokens"],
        "temperature": float(row["temperature"]),
        "topP": float(row["top_p"]),
        "supportsJSON": bool(row["supports_json"]),
        "supportsStreaming": bool(row["supports_streaming"]),
        "notes": row.get("notes") or "",
        "thinking": _thinking(row.get("thinking")),
        "hasKey": bool(row.get("api_key")),
        "hasBaseURL": bool(row.get("base_url")),
        "lifecycleStatus": row["lifecycle_status"],
        "revision": int(row["revision"]),
        "ready": provider_is_generation_ready(row),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
    secrets = _secret_values(row)
    safe = {
        key: sanitize_provider_public_value(value, secrets)
        for key, value in public.items()
    }
    return ProviderPublicProfile(
        id=safe["id"],
        name=safe["name"],
        provider_type=safe["providerType"],
        model=safe["model"],
        enabled=safe["enabled"],
        sort_order=safe["sortOrder"],
        stream=safe["stream"],
        max_context_tokens=safe["maxContextTokens"],
        max_output_tokens=safe["maxOutputTokens"],
        temperature=safe["temperature"],
        top_p=safe["topP"],
        supports_json=safe["supportsJSON"],
        supports_streaming=safe["supportsStreaming"],
        notes=safe["notes"],
        thinking=safe["thinking"],
        has_key=safe["hasKey"],
        has_base_url=safe["hasBaseURL"],
        lifecycle_status=safe["lifecycleStatus"],
        revision=safe["revision"],
        ready=safe["ready"],
        created_at=safe["createdAt"],
        updated_at=safe["updatedAt"],
    )


def provider_public(row: Mapping | None) -> dict | None:
    profile = provider_public_profile(row)
    return profile.to_dict() if profile else None


def providers_public(rows) -> list[dict]:
    return [provider_public(row) for row in rows]
