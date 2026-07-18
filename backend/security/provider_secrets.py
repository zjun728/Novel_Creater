"""Shared Provider secret normalization and public-value sanitization."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from urllib.parse import quote, quote_plus


REDACTED = "[REDACTED]"
MIN_SUBSTRING_SECRET_LENGTH = 8
_PERCENT_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")
PUBLIC_SECRET_COLLISION_MESSAGE = (
    "Provider public fields cannot contain private configuration"
)
FORBIDDEN_PROVIDER_PUBLIC_KEYS = frozenset(
    {"apikey", "baseurl", "authorization", "token", "password"}
)


def normalize_provider_secrets(values: Iterable[object]) -> tuple[str, ...]:
    normalized = []
    for value in values:
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8")
        if not isinstance(value, str):
            continue
        value = value.strip()
        if value:
            normalized.append(value)
    return tuple(
        sorted(dict.fromkeys(normalized), key=len, reverse=True)
    )


def _normalized_public_key(value: object) -> str:
    return str(value).casefold().replace("_", "").replace("-", "")


def _matches_secret(value: str, secret: str) -> bool:
    if len(secret) < MIN_SUBSTRING_SECRET_LENGTH:
        return value == secret
    return secret in value


def provider_public_value_contains_secret(
    value: object,
    secrets: Iterable[object],
) -> bool:
    normalized = normalize_provider_secrets(secrets)

    def contains(item: object) -> bool:
        if isinstance(item, Mapping):
            return any(
                (
                    isinstance(key, str)
                    and any(_matches_secret(key, secret) for secret in normalized)
                )
                or contains(nested)
                for key, nested in item.items()
            )
        if isinstance(item, (list, tuple, set)):
            return any(contains(nested) for nested in item)
        return isinstance(item, str) and any(
            _matches_secret(item, secret) for secret in normalized
        )

    return contains(value)


def provider_public_fields_contain_secret(
    fields: Mapping[object, object],
    secrets: Iterable[object],
) -> bool:
    """Inspect trusted field values while preserving their schema keys."""

    normalized = normalize_provider_secrets(secrets)
    return any(
        provider_public_value_contains_secret(value, normalized)
        for value in fields.values()
    )


def provider_response_text_contains_secret(
    value: str,
    secrets: Iterable[object],
) -> bool:
    """Scan raw response text for encoded variants of long secrets."""

    normalized_value = _PERCENT_ESCAPE.sub(
        lambda match: match.group(0).upper(),
        value,
    )
    variants: set[str] = set()
    for secret in normalize_provider_secrets(secrets):
        if len(secret) < MIN_SUBSTRING_SECRET_LENGTH:
            continue
        secret_variants = {
            secret,
            quote(secret, safe=""),
            quote_plus(secret, safe=""),
            secret.replace("/", r"\/"),
        }
        variants.update(
            _PERCENT_ESCAPE.sub(
                lambda match: match.group(0).upper(),
                variant,
            )
            for variant in secret_variants
        )
    return any(variant in normalized_value for variant in variants)


def provider_response_value_contains_secret(
    value: object,
    secrets: Iterable[object],
    *,
    max_depth: int = 32,
    max_nodes: int = 10_000,
) -> bool:
    """Scan decoded response values with bounded, short-exact matching."""

    normalized = normalize_provider_secrets(secrets)
    stack: list[tuple[object, int]] = [(value, 0)]
    scanned_nodes = 0
    while stack:
        item, depth = stack.pop()
        scanned_nodes += 1
        if scanned_nodes > max_nodes or depth > max_depth:
            raise ValueError("response structure exceeds scan limits")
        if isinstance(item, str):
            if any(_matches_secret(item, secret) for secret in normalized):
                return True
            continue
        if isinstance(item, Mapping):
            stack.extend((key, depth + 1) for key in item.keys())
            stack.extend((nested, depth + 1) for nested in item.values())
        elif isinstance(item, (list, tuple, set)):
            stack.extend((nested, depth + 1) for nested in item)
    return False


def _fail_closed_text(
    original: str,
    *,
    max_chars: int | None,
    max_utf8_bytes: int | None,
) -> str:
    candidate = REDACTED if len(REDACTED) <= len(original) else ""
    if max_chars is not None and len(candidate) > max_chars:
        return ""
    if (
        max_utf8_bytes is not None
        and len(candidate.encode("utf-8")) > max_utf8_bytes
    ):
        return ""
    return candidate


def sanitize_provider_secret_text(
    value: str,
    secrets: Iterable[object],
    *,
    max_chars: int | None = None,
    max_utf8_bytes: int | None = None,
) -> str:
    normalized = normalize_provider_secrets(secrets)
    original = value
    for secret in normalized:
        if not _matches_secret(value, secret):
            continue
        if len(secret) < MIN_SUBSTRING_SECRET_LENGTH:
            return _fail_closed_text(
                original,
                max_chars=max_chars,
                max_utf8_bytes=max_utf8_bytes,
            )
        replaced = value.replace(secret, REDACTED)
        if len(replaced) > len(value):
            return _fail_closed_text(
                original,
                max_chars=max_chars,
                max_utf8_bytes=max_utf8_bytes,
            )
        value = replaced
    if max_chars is not None and len(value) > max_chars:
        return _fail_closed_text(
            original,
            max_chars=max_chars,
            max_utf8_bytes=max_utf8_bytes,
        )
    if (
        max_utf8_bytes is not None
        and len(value.encode("utf-8")) > max_utf8_bytes
    ):
        return _fail_closed_text(
            original,
            max_chars=max_chars,
            max_utf8_bytes=max_utf8_bytes,
        )
    return value


def sanitize_provider_public_value(
    value: object,
    secrets: Iterable[object],
    *,
    max_chars: int | None = None,
    max_utf8_bytes: int | None = None,
):
    normalized = normalize_provider_secrets(secrets)

    def sanitize(item):
        if isinstance(item, Mapping):
            sanitized = {}
            for key, nested in item.items():
                if _normalized_public_key(key) in FORBIDDEN_PROVIDER_PUBLIC_KEYS:
                    continue
                safe_key = (
                    sanitize_provider_secret_text(key, normalized)
                    if isinstance(key, str)
                    else key
                )
                if safe_key in sanitized:
                    return {}
                sanitized[safe_key] = sanitize(nested)
            return sanitized
        if isinstance(item, list):
            return [sanitize(nested) for nested in item]
        if isinstance(item, tuple):
            return tuple(sanitize(nested) for nested in item)
        if isinstance(item, str):
            return sanitize_provider_secret_text(
                item,
                normalized,
                max_chars=max_chars,
                max_utf8_bytes=max_utf8_bytes,
            )
        return item

    return sanitize(value)
