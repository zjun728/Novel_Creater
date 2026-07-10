"""Public provider projection and response sanitization."""

from .helpers import convert_row


PUBLIC_PROVIDER_COLUMNS = """
id, name, provider_type, base_url, model, stream,
max_context_tokens, max_output_tokens, temperature, top_p,
supports_json, supports_streaming, notes, thinking, created_at, updated_at,
CASE WHEN COALESCE(api_key, '') <> '' THEN 1 ELSE 0 END AS has_api_key
""".strip()


def _strip_secret_fields(value):
    if isinstance(value, dict):
        return {
            key: _strip_secret_fields(item)
            for key, item in value.items()
            if not (
                isinstance(key, str)
                and key.lower().replace("_", "").replace("-", "") == "apikey"
            )
        }
    if isinstance(value, list):
        return [_strip_secret_fields(item) for item in value]
    return value


def public_provider_query(suffix: str = "") -> str:
    suffix = suffix.strip()
    return f"SELECT {PUBLIC_PROVIDER_COLUMNS} FROM provider_profiles" + (
        f" {suffix}" if suffix else ""
    )


def to_public_provider(row):
    if not row:
        return None
    safe = dict(row)
    safe.pop("api_key", None)
    safe.pop("apiKey", None)
    metadata_values = [
        safe.pop("has_api_key", None),
        safe.pop("hasAPIKey", None),
        safe.pop("hasApiKey", None),
    ]
    has_api_key = next((value for value in metadata_values if value is not None), False)
    result = _strip_secret_fields(convert_row(safe))
    result["hasApiKey"] = bool(has_api_key)
    return result


def to_public_providers(rows):
    return [to_public_provider(row) for row in (rows or [])]
