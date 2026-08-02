from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence

import httpx


MAX_CHAPTER_DRAFT_PROVIDER_RESPONSE_BYTES = 1024 * 1024


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
        headers = {
            "Authorization": f"Bearer {provider['api_key']}",
            "Accept-Encoding": "identity",
        }
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(connect=30, read=1200, write=30, pool=30),
            ) as client:
                async with client.stream(
                    "POST",
                    self._endpoint(str(provider["base_url"])),
                    headers=headers,
                    json=body,
                ) as response:
                    if response.is_error:
                        raise ChapterDraftProviderHTTPError("provider request failed")
                    content_encodings = response.headers.get_list(
                        "content-encoding"
                    )
                    if content_encodings:
                        if (
                            len(content_encodings) != 1
                            or "," in content_encodings[0]
                            or content_encodings[0].strip().lower() != "identity"
                        ):
                            raise ChapterDraftProviderResponseError(
                                "provider response was invalid"
                            )
                    declared_length = response.headers.get("content-length")
                    if declared_length is not None:
                        try:
                            declared_bytes = int(declared_length)
                        except ValueError:
                            raise ChapterDraftProviderResponseError(
                                "provider response was invalid"
                            ) from None
                        if not 0 <= declared_bytes <= MAX_CHAPTER_DRAFT_PROVIDER_RESPONSE_BYTES:
                            raise ChapterDraftProviderResponseError(
                                "provider response was invalid"
                            )
                    raw = bytearray()
                    async for chunk in response.aiter_raw():
                        remaining = (
                            MAX_CHAPTER_DRAFT_PROVIDER_RESPONSE_BYTES
                            + 1
                            - len(raw)
                        )
                        raw.extend(chunk[:remaining])
                        if len(raw) > MAX_CHAPTER_DRAFT_PROVIDER_RESPONSE_BYTES:
                            raise ChapterDraftProviderResponseError(
                                "provider response was invalid"
                            )
        except ChapterDraftProviderError:
            raise
        except (httpx.TransportError, httpx.InvalidURL):
            raise ChapterDraftProviderTransportError(
                "provider transport failed"
            ) from None
        try:
            data = json.loads(bytes(raw))
            content = data["choices"][0]["message"]["content"]
        except (
            UnicodeError,
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            RecursionError,
        ):
            raise ChapterDraftProviderResponseError(
                "provider response was invalid"
            ) from None
        if not isinstance(content, str) or not content.strip():
            raise ChapterDraftProviderResponseError("provider response was empty")
        return content

    async def stream(
        self,
        *,
        provider: Mapping[str, object],
        messages: Sequence[Mapping[str, str]],
        generation_config: Mapping[str, object],
    ) -> AsyncIterator[str]:
        """Yield validated text chunks from one bounded, uncompressed SSE stream."""
        body = {
            "model": provider["model_name"],
            "messages": list(messages),
            "temperature": generation_config["temperature"],
            "max_tokens": generation_config["maxOutputTokens"],
            "stream": True,
        }
        headers = {
            "Authorization": f"Bearer {provider['api_key']}",
            "Accept": "text/event-stream",
            "Accept-Encoding": "identity",
        }
        deadline = asyncio.get_running_loop().time() + 1200
        from backend.gateways.openai_sse import OpenAITextSSEParser

        parser = OpenAITextSSEParser()
        raw_bytes = 0
        try:
            async with asyncio.timeout_at(deadline):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=httpx.Timeout(connect=30, read=1200, write=30, pool=30),
                ) as client:
                    async with client.stream(
                        "POST",
                        self._endpoint(str(provider["base_url"])),
                        headers=headers,
                        json=body,
                    ) as response:
                        if response.is_error:
                            raise ChapterDraftProviderHTTPError("provider request failed")
                        self._validate_stream_headers(response)
                        async for chunk in response.aiter_raw():
                            raw_bytes += len(chunk)
                            if raw_bytes > MAX_CHAPTER_DRAFT_PROVIDER_RESPONSE_BYTES:
                                raise ChapterDraftProviderResponseError(
                                    "provider response was invalid"
                                )
                            for text in parser.feed(chunk):
                                yield text
                        parser.finish()
        except asyncio.CancelledError:
            raise
        except ChapterDraftProviderError:
            raise
        except (httpx.TransportError, httpx.InvalidURL, TimeoutError):
            raise ChapterDraftProviderTransportError(
                "provider transport failed"
            ) from None
        except Exception:
            raise ChapterDraftProviderResponseError(
                "provider response was invalid"
            ) from None

    @staticmethod
    def _validate_stream_headers(response: httpx.Response) -> None:
        media_types = response.headers.get_list("content-type")
        if (
            len(media_types) != 1
            or media_types[0].strip().lower() != "text/event-stream"
            or "," in media_types[0]
        ):
            raise ChapterDraftProviderResponseError("provider response was invalid")
        content_encodings = response.headers.get_list("content-encoding")
        if content_encodings and (
            len(content_encodings) != 1
            or "," in content_encodings[0]
            or content_encodings[0].strip().lower() != "identity"
        ):
            raise ChapterDraftProviderResponseError("provider response was invalid")
        declared_lengths = response.headers.get_list("content-length")
        if len(declared_lengths) > 1:
            raise ChapterDraftProviderResponseError("provider response was invalid")
        if declared_lengths:
            try:
                declared_bytes = int(declared_lengths[0])
            except ValueError:
                raise ChapterDraftProviderResponseError(
                    "provider response was invalid"
                ) from None
            if not 0 <= declared_bytes <= MAX_CHAPTER_DRAFT_PROVIDER_RESPONSE_BYTES:
                raise ChapterDraftProviderResponseError("provider response was invalid")
