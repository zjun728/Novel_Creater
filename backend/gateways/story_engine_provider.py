"""One OpenAI-compatible outbound boundary for story-engine generation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence

import httpx


PROVIDER_TIMEOUT_SECONDS = 180
STORY_ENGINE_TEMPERATURE = 0.7
STORY_ENGINE_MAX_TOKENS = 6_000


class StoryEngineProviderError(RuntimeError):
    """A safe provider-boundary failure that carries no remote details."""


class StoryEngineProviderHTTPError(StoryEngineProviderError):
    pass


class StoryEngineProviderResponseError(StoryEngineProviderError):
    pass


class StoryEngineProviderTransportError(httpx.TransportError):
    pass


class StoryEngineProviderGateway:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    @staticmethod
    def _endpoint(base_url: str) -> str:
        endpoint = base_url.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        return endpoint

    async def generate(
        self,
        *,
        provider: Mapping[str, object],
        messages: Sequence[Mapping[str, str]],
    ) -> str:
        timeout = httpx.Timeout(connect=15, read=180, write=30, pool=15)
        body = {
            "model": provider["model_name"],
            "messages": list(messages),
            "temperature": STORY_ENGINE_TEMPERATURE,
            "max_tokens": STORY_ENGINE_MAX_TOKENS,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {provider['api_key']}"}
        try:
            async with asyncio.timeout(PROVIDER_TIMEOUT_SECONDS):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=timeout,
                ) as client:
                    response = await client.post(
                        self._endpoint(str(provider["base_url"])),
                        headers=headers,
                        json=body,
                    )
        except httpx.TimeoutException:
            raise TimeoutError("provider request timed out") from None
        except (httpx.TransportError, httpx.InvalidURL):
            raise StoryEngineProviderTransportError(
                "provider transport failed"
            ) from None

        if response.is_error:
            raise StoryEngineProviderHTTPError("provider request failed")
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, TypeError, KeyError, IndexError):
            raise StoryEngineProviderResponseError(
                "provider response was invalid"
            ) from None
        if not isinstance(content, str) or not content.strip():
            raise StoryEngineProviderResponseError(
                "provider response was invalid"
            )
        return content
