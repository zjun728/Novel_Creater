"""Canonical generation-capable Provider policy."""

from __future__ import annotations

from collections.abc import Mapping


GENERATION_PROVIDER_TYPE = "openai-compatible"
SUPPORTED_PROVIDER_TYPES = frozenset({GENERATION_PROVIDER_TYPE})


def provider_type_is_supported(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.strip().casefold() in SUPPORTED_PROVIDER_TYPES
    )


def provider_is_generation_ready(
    row: Mapping | None, *, prefix: str = ""
) -> bool:
    if row is None:
        return False

    def value(name: str):
        return row.get(f"{prefix}{name}")

    return (
        value("lifecycle_status") == "active"
        and int(value("enabled") or 0) == 1
        and provider_type_is_supported(value("provider_type"))
        and all(
            isinstance(value(field), str) and bool(value(field).strip())
            for field in ("model_name", "base_url", "api_key")
        )
    )
