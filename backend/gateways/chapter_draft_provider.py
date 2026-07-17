from __future__ import annotations

from collections.abc import Mapping, Sequence

import httpx


class ChapterDraftProviderError(RuntimeError):
    """Safe provider-boundary failure that must not include remote secrets."""


class ChapterDraftProviderHTTPError(ChapterDraftProviderError):
    pass


class ChapterDraftProviderResponseError(ChapterDraftProviderError):
    pass


class ChapterDraftProviderTransportError(ChapterDraftProviderError):
    pass


class ChapterDraftProviderGateway:
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
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {provider['api_key']}"}
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(connect=30, read=1200, write=30, pool=30),
            ) as client:
                response = await client.post(
                    self._endpoint(str(provider["base_url"])),
                    headers=headers,
                    json=body,
                )
        except (httpx.TransportError, httpx.InvalidURL) as exc:
            raise ChapterDraftProviderTransportError("provider transport failed") from exc
        if response.is_error:
            raise ChapterDraftProviderHTTPError("provider request failed")
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise ChapterDraftProviderResponseError("provider response was invalid") from exc
        if not isinstance(content, str) or not content.strip():
            raise ChapterDraftProviderResponseError("provider response was empty")
        return content
