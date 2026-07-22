"""Exactly one bounded OpenAI-compatible style-trial call."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
import json

import httpx
from pydantic import ValidationError

from backend.domain.style_trials import (
    StyleTrialProviderOutput,
    style_trial_value_contains_secret,
)
from backend.security.provider_secrets import (
    normalize_provider_secrets,
    provider_response_text_contains_secret,
    provider_response_value_contains_secret,
    validate_provider_response_text,
)


PROVIDER_TIMEOUT_SECONDS = 180
MAX_PROVIDER_RESPONSE_BYTES = 128 * 1024


class StyleTrialProviderError(RuntimeError):
    """Fixed gateway exception; raw Provider details never cross the boundary."""


class StyleTrialProviderGateway:
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
    ) -> StyleTrialProviderOutput:
        body = {
            "model": provider["model_name"],
            "messages": list(messages),
            "temperature": generation_config["temperature"],
            "max_tokens": generation_config["maxOutputTokens"],
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        try:
            async with asyncio.timeout(PROVIDER_TIMEOUT_SECONDS):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=httpx.Timeout(connect=15, read=180, write=30, pool=15),
                ) as client:
                    async with client.stream(
                        "POST",
                        self._endpoint(str(provider["base_url"])),
                        headers={"Authorization": f"Bearer {provider['api_key']}"},
                        json=body,
                    ) as response:
                        if not response.is_success:
                            raise StyleTrialProviderError("style trial provider failed")
                        declared = response.headers.get("content-length")
                        if declared is not None and int(declared) > MAX_PROVIDER_RESPONSE_BYTES:
                            raise StyleTrialProviderError("style trial provider failed")
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > MAX_PROVIDER_RESPONSE_BYTES:
                                raise StyleTrialProviderError("style trial provider failed")
        except StyleTrialProviderError:
            raise
        except (TimeoutError, httpx.HTTPError, ValueError, KeyError, TypeError):
            raise StyleTrialProviderError("style trial provider failed") from None

        secrets = normalize_provider_secrets(
            (provider.get("api_key"), provider.get("base_url"))
        )
        try:
            raw_text = bytes(raw).decode("utf-8")
            if style_trial_value_contains_secret(raw_text, secrets):
                raise ValueError("provider response contains private data")
            envelope = json.loads(raw_text)
            if style_trial_value_contains_secret(envelope, secrets):
                raise ValueError("provider response contains private data")
            content = validate_provider_response_text(
                envelope["choices"][0]["message"]["content"], strip=True
            )
            if (
                style_trial_value_contains_secret(content, secrets)
                or provider_response_text_contains_secret(content, secrets)
            ):
                raise ValueError("provider response contains private data")
            value = json.loads(content)
            if (
                style_trial_value_contains_secret(value, secrets)
                or provider_response_value_contains_secret(value, secrets)
            ):
                raise ValueError("provider response contains private data")
            return StyleTrialProviderOutput.model_validate(value, strict=True)
        except (
            UnicodeError,
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            ValidationError,
            RecursionError,
        ):
            raise StyleTrialProviderError("style trial provider failed") from None


__all__ = ("StyleTrialProviderError", "StyleTrialProviderGateway")
