"""One strict OpenAI-compatible outbound call for market analysis."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
import json

import httpx


PROVIDER_TIMEOUT_SECONDS = 180
MAX_PROVIDER_RESPONSE_BYTES = 256 * 1024


class MarketAnalysisProviderError(RuntimeError):
    pass


class MarketAnalysisProviderHTTPError(MarketAnalysisProviderError):
    pass


class MarketAnalysisProviderResponseError(MarketAnalysisProviderError):
    pass


class MarketAnalysisProviderTransportError(MarketAnalysisProviderError):
    pass


class MarketAnalysisProviderGateway:
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
    ) -> str:
        body = {
            "model": provider["model_name"],
            "messages": list(messages),
            "temperature": generation_config["temperature"],
            "max_tokens": generation_config["maxOutputTokens"],
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {provider['api_key']}"}
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
                        headers=headers,
                        json=body,
                    ) as response:
                        if response.is_error:
                            raise MarketAnalysisProviderHTTPError(
                                "provider request failed"
                            )
                        declared = response.headers.get("content-length")
                        if declared is not None:
                            try:
                                declared_size = int(declared)
                            except ValueError:
                                raise MarketAnalysisProviderResponseError(
                                    "provider response was invalid"
                                ) from None
                            if (
                                declared_size < 0
                                or declared_size > MAX_PROVIDER_RESPONSE_BYTES
                            ):
                                raise MarketAnalysisProviderResponseError(
                                    "provider response was invalid"
                                )
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            remaining = (
                                MAX_PROVIDER_RESPONSE_BYTES + 1 - len(raw)
                            )
                            if remaining > 0:
                                raw.extend(chunk[:remaining])
                            if (
                                len(raw) > MAX_PROVIDER_RESPONSE_BYTES
                                or len(chunk) > remaining
                            ):
                                raise MarketAnalysisProviderResponseError(
                                    "provider response was invalid"
                                )
        except (TimeoutError, httpx.TimeoutException):
            raise TimeoutError("market analysis provider timed out") from None
        except MarketAnalysisProviderError:
            raise
        except (httpx.TransportError, httpx.InvalidURL):
            raise MarketAnalysisProviderTransportError(
                "provider transport failed"
            ) from None
        try:
            payload = json.loads(bytes(raw))
            content = payload["choices"][0]["message"]["content"]
        except (UnicodeError, ValueError, TypeError, KeyError, IndexError):
            raise MarketAnalysisProviderResponseError(
                "provider response was invalid"
            ) from None
        if not isinstance(content, str) or not content.strip():
            raise MarketAnalysisProviderResponseError(
                "provider response was invalid"
            )
        return content
