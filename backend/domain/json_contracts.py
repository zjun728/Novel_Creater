"""Canonical JSON serialization and hashing for immutable domain values."""

from __future__ import annotations

from hashlib import sha256
import json

from pydantic import BaseModel


def canonical_json(value: BaseModel | dict[str, object]) -> str:
    """Serialize a model or dictionary into stable compact Unicode JSON."""

    serializable = (
        value.model_dump(mode="json")
        if isinstance(value, BaseModel)
        else value
    )
    return json.dumps(
        serializable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_hash(value: BaseModel | dict[str, object]) -> str:
    """Return the SHA-256 hex digest of canonical UTF-8 JSON."""

    return sha256(canonical_json(value).encode("utf-8")).hexdigest()
