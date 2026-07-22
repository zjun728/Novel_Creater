"""Exactly one bounded OpenAI-compatible asset-ranking call."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
import json

import httpx
from pydantic import ValidationError

from backend.domain.asset_recommendations import ProviderRankingOutput
from backend.security.provider_secrets import (
    normalize_provider_secrets,
    provider_response_text_contains_secret,
    provider_response_value_contains_secret,
    validate_provider_response_text,
)


PROVIDER_TIMEOUT_SECONDS = 180
MAX_PROVIDER_RESPONSE_BYTES = 128 * 1024


class AssetRecommendationProviderError(RuntimeError):
    """Fixed exception boundary; provider and parse details are never public."""


class AssetRecommendationProviderGateway:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    @staticmethod
    def _endpoint(base_url: str) -> str:
        parsed = httpx.URL(base_url)
        path = parsed.path.rstrip("/")
        if not path.endswith("/chat/completions"):
            path += "/chat/completions"
        return str(parsed.copy_with(path=path))

    async def rank(
        self,
        *,
        provider: Mapping[str, object],
        messages: Sequence[Mapping[str, str]],
        generation_config: Mapping[str, object],
    ) -> ProviderRankingOutput:
        body = {
            "model": provider["model_name"],
            "messages": list(messages),
            "temperature": generation_config["temperature"],
            "max_tokens": generation_config["maxOutputTokens"],
            "stream": False,
        }
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
                        self._endpoint(str(provider["base_url"])),
                        headers={
                            "Authorization": f"Bearer {provider['api_key']}"
                        },
                        json=body,
                    ) as response:
                        if response.is_error:
                            raise AssetRecommendationProviderError(
                                "asset ranking provider failed"
                            )
                        declared = response.headers.get("content-length")
                        if declared is not None and int(declared) > MAX_PROVIDER_RESPONSE_BYTES:
                            raise AssetRecommendationProviderError(
                                "asset ranking provider failed"
                            )
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > MAX_PROVIDER_RESPONSE_BYTES:
                                raise AssetRecommendationProviderError(
                                    "asset ranking provider failed"
                                )
        except AssetRecommendationProviderError:
            raise
        except (TimeoutError, httpx.HTTPError, ValueError, KeyError, TypeError):
            raise AssetRecommendationProviderError(
                "asset ranking provider failed"
            ) from None

        secrets = normalize_provider_secrets(
            (provider.get("api_key"), provider.get("base_url"))
        )
        try:
            envelope = json.loads(bytes(raw))
            content = validate_provider_response_text(
                envelope["choices"][0]["message"]["content"],
                strip=True,
            )
            if provider_response_text_contains_secret(content, secrets):
                raise ValueError("provider response contains private data")
            value = json.loads(content)
            if provider_response_value_contains_secret(value, secrets):
                raise ValueError("provider response contains private data")
            return ProviderRankingOutput.model_validate(value, strict=True)
        except (
            UnicodeError,
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            ValidationError,
            RecursionError,
        ):
            raise AssetRecommendationProviderError(
                "asset ranking provider failed"
            ) from None


__all__ = (
    "AssetRecommendationProviderError",
    "AssetRecommendationProviderGateway",
)
