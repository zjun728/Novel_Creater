"""Exactly one bounded OpenAI-compatible call for a creation Bible."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
import json

import httpx
from pydantic import ValidationError

from backend.domain.bibles import BiblePayload
from backend.security.provider_secrets import (
    normalize_provider_secrets,
    provider_response_text_contains_secret,
    provider_response_value_contains_secret,
    validate_provider_response_text,
)


PROVIDER_TIMEOUT_SECONDS = 180
MAX_PROVIDER_RESPONSE_BYTES = 128 * 1024
_LIST_FIELDS = (
    "worldRules",
    "coreCast",
    "factions",
    "longTermConflicts",
    "relationshipDynamics",
    "continuityGuardrails",
    "openDesignQuestions",
)


class BibleProviderError(RuntimeError):
    """Fixed gateway exception; upstream diagnostics never cross this boundary."""


class BibleProviderHTTPError(BibleProviderError):
    pass


class BibleProviderTransportError(BibleProviderError):
    pass


class BibleProviderTimeoutError(BibleProviderError):
    pass


class BibleProviderParseError(BibleProviderError):
    pass


class BibleProviderGateway:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    @staticmethod
    def _endpoint(base_url: str) -> str:
        parsed = httpx.URL(base_url)
        path = parsed.path.rstrip("/")
        if not path.endswith("/chat/completions"):
            path += "/chat/completions"
        return str(parsed.copy_with(path=path))

    async def generate(
        self,
        *,
        provider: Mapping[str, object],
        messages: Sequence[Mapping[str, str]],
        generation_config: Mapping[str, object],
    ) -> BiblePayload:
        try:
            body = {
                "model": provider["model_name"],
                "messages": list(messages),
                "temperature": generation_config["temperature"],
                "max_tokens": generation_config["maxOutputTokens"],
                "response_format": {"type": "json_object"},
                "thinking": {"type": "disabled"},
                "stream": False,
            }
            endpoint = self._endpoint(str(provider["base_url"]))
            authorization = f"Bearer {provider['api_key']}"
        except (KeyError, TypeError, ValueError):
            raise BibleProviderTransportError("Bible provider unavailable") from None

        try:
            async with asyncio.timeout(PROVIDER_TIMEOUT_SECONDS):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=httpx.Timeout(
                        connect=15,
                        read=180,
                        write=30,
                        pool=15,
                    ),
                ) as client:
                    async with client.stream(
                        "POST",
                        endpoint,
                        headers={"Authorization": authorization},
                        json=body,
                    ) as response:
                        if not response.is_success:
                            raise BibleProviderHTTPError(
                                "Bible provider request failed"
                            )
                        declared = response.headers.get("content-length")
                        if declared is not None:
                            try:
                                if int(declared) > MAX_PROVIDER_RESPONSE_BYTES:
                                    raise BibleProviderParseError(
                                        "Bible provider response invalid"
                                    )
                            except ValueError:
                                raise BibleProviderParseError(
                                    "Bible provider response invalid"
                                ) from None
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > MAX_PROVIDER_RESPONSE_BYTES:
                                raise BibleProviderParseError(
                                    "Bible provider response invalid"
                                )
        except BibleProviderError:
            raise
        except TimeoutError:
            raise BibleProviderTimeoutError(
                "Bible provider request timed out"
            ) from None
        except httpx.HTTPError:
            raise BibleProviderTransportError(
                "Bible provider transport failed"
            ) from None

        secrets = normalize_provider_secrets(
            (provider.get("api_key"), provider.get("base_url"))
        )
        try:
            raw_text = bytes(raw).decode("utf-8")
            if provider_response_text_contains_secret(raw_text, secrets):
                raise ValueError("private provider data")
            envelope = json.loads(raw_text)
            if provider_response_value_contains_secret(envelope, secrets):
                raise ValueError("private provider data")
            content = validate_provider_response_text(
                envelope["choices"][0]["message"]["content"],
                strip=True,
            )
            if provider_response_text_contains_secret(content, secrets):
                raise ValueError("private provider data")
            value = json.loads(content)
            if provider_response_value_contains_secret(value, secrets):
                raise ValueError("private provider data")
            if not isinstance(value, dict):
                raise TypeError("Bible output must be an object")
            normalized = dict(value)
            for field in _LIST_FIELDS:
                if isinstance(normalized.get(field), list):
                    normalized[field] = tuple(normalized[field])
            return BiblePayload.model_validate(normalized, strict=True)
        except (
            UnicodeError,
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            ValidationError,
            RecursionError,
        ):
            raise BibleProviderParseError(
                "Bible provider response invalid"
            ) from None


__all__ = (
    "MAX_PROVIDER_RESPONSE_BYTES",
    "PROVIDER_TIMEOUT_SECONDS",
    "BibleProviderError",
    "BibleProviderGateway",
    "BibleProviderHTTPError",
    "BibleProviderParseError",
    "BibleProviderTimeoutError",
    "BibleProviderTransportError",
)
