"""Secret-free Provider response serialization."""

from __future__ import annotations

import json
from collections.abc import Mapping


REDACTED = "[REDACTED]"
_FORBIDDEN_PUBLIC_KEYS = frozenset(
    {
        "apikey",
        "baseurl",
        "authorization",
        "token",
        "password",
    }
)


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
        if isinstance(value, str) and value:
            values.append(value)
    return tuple(dict.fromkeys(values))


def _sanitize(value, secrets: tuple[str, ...]):
    if isinstance(value, Mapping):
        return {
            _sanitize(key, secrets): _sanitize(item, secrets)
            for key, item in value.items()
            if not (
                isinstance(key, str)
                and key.casefold().replace("_", "").replace("-", "")
                in _FORBIDDEN_PUBLIC_KEYS
            )
        }
    if isinstance(value, list):
        return [_sanitize(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize(item, secrets) for item in value)
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, REDACTED)
    return value


def provider_public(row: Mapping | None) -> dict | None:
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
        "ready": (
            row["lifecycle_status"] == "active"
            and bool(row["enabled"])
            and bool(row.get("api_key"))
            and bool(row.get("base_url"))
        ),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
    return _sanitize(public, _secret_values(row))


def providers_public(rows) -> list[dict]:
    return [provider_public(row) for row in rows]
