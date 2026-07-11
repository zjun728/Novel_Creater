"""Secret-free Provider response serialization."""

from __future__ import annotations

import json
from collections.abc import Mapping


def _thinking(value):
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def provider_public(row: Mapping | None) -> dict | None:
    if not row:
        return None
    return {
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
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def providers_public(rows) -> list[dict]:
    return [provider_public(row) for row in rows]
