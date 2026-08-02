from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence

import httpx


MAX_CHAPTER_DRAFT_PROVIDER_RESPONSE_BYTES = 1024 * 1024
_CHAPTER_DRAFT_STREAM_TIMEOUT_SECONDS = 1200


class ChapterDraftProviderError(RuntimeError):
    """Safe provider-boundary failure that must not include remote secrets."""


class ChapterDraftProviderHTTPError(ChapterDraftProviderError):
    pass


class ChapterDraftProviderResponseError(ChapterDraftProviderError):
    pass


class ChapterDraftProviderTransportError(ChapterDraftProviderError):
    pass


async def _close_stream_resources(
    response: httpx.Response | None,
    client: httpx.AsyncClient | None,
) -> tuple[bool, asyncio.CancelledError | None]:
    failed = False
    cancellation = None
    for resource in (response, client):
        if resource is None:
            continue
        try:
            await resource.aclose()
        except asyncio.CancelledError as caught:
            failed = True
            if cancellation is None:
                cancellation = caught
        except BaseException:
            failed = True
    return failed, cancellation


def _raise_if_stream_deadline_elapsed(
    loop: asyncio.AbstractEventLoop,
    deadline: float,
) -> None:
    if loop.time() >= deadline:
        raise TimeoutError


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
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _CHAPTER_DRAFT_STREAM_TIMEOUT_SECONDS
        from backend.gateways.openai_sse import OpenAITextSSEParser

        parser = OpenAITextSSEParser()
        raw_bytes = 0
        client = None
        response = None
        failure: BaseException | None = None
        try:
            client = httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(connect=30, read=1200, write=30, pool=30),
            )
            request = client.build_request(
                "POST",
                self._endpoint(str(provider["base_url"])),
                headers=headers,
                json=body,
            )
            _raise_if_stream_deadline_elapsed(loop, deadline)
            async with asyncio.timeout_at(deadline):
                response = await client.send(request, stream=True)
            _raise_if_stream_deadline_elapsed(loop, deadline)
            if response.is_error:
                raise ChapterDraftProviderHTTPError("provider request failed")
            self._validate_stream_headers(response)
            _raise_if_stream_deadline_elapsed(loop, deadline)
            raw_iterator = response.aiter_raw().__aiter__()
            while True:
                try:
                    _raise_if_stream_deadline_elapsed(loop, deadline)
                    async with asyncio.timeout_at(deadline):
                        chunk = await anext(raw_iterator)
                    _raise_if_stream_deadline_elapsed(loop, deadline)
                except StopAsyncIteration:
                    break
                raw_bytes += len(chunk)
                if raw_bytes > MAX_CHAPTER_DRAFT_PROVIDER_RESPONSE_BYTES:
                    raise ChapterDraftProviderResponseError(
                        "provider response was invalid"
                    )
                texts = parser.feed(chunk)
                _raise_if_stream_deadline_elapsed(loop, deadline)
                for text in texts:
                    _raise_if_stream_deadline_elapsed(loop, deadline)
                    yield text
            _raise_if_stream_deadline_elapsed(loop, deadline)
            parser.finish()
            _raise_if_stream_deadline_elapsed(loop, deadline)
        except BaseException as caught:
            failure = caught

        cleanup_failed, cleanup_cancellation = await _close_stream_resources(
            response,
            client,
        )
        if isinstance(failure, asyncio.CancelledError):
            raise failure
        if failure is None and cleanup_cancellation is not None:
            raise cleanup_cancellation
        if isinstance(failure, (GeneratorExit, KeyboardInterrupt, SystemExit)):
            raise failure
        if isinstance(failure, ChapterDraftProviderError):
            raise failure from None
        if isinstance(failure, (httpx.TransportError, httpx.InvalidURL, TimeoutError)):
            raise ChapterDraftProviderTransportError(
                "provider transport failed"
            ) from None
        if failure is not None:
            raise ChapterDraftProviderResponseError(
                "provider response was invalid"
            ) from None
        if cleanup_failed:
            raise ChapterDraftProviderTransportError(
                "provider transport failed"
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
