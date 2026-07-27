"""Shared bounded OpenAI-compatible JSON transport with no error leakage."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import math

import httpx

from backend.domain.provider_policy import provider_type_is_supported
from backend.security.provider_secrets import (
    normalize_provider_secrets,
    provider_response_text_contains_secret,
    provider_response_value_contains_secret,
    validate_provider_response_text,
)


@dataclass(frozen=True, slots=True)
class OpenAIJSONTransportResult:
    """Success value or a content-free failure sentinel."""

    succeeded: bool
    cancelled: bool = False
    value: object | None = None


OPENAI_JSON_TRANSPORT_FAILURE = OpenAIJSONTransportResult(
    succeeded=False,
)
OPENAI_JSON_TRANSPORT_CANCELLED = OpenAIJSONTransportResult(
    succeeded=False,
    cancelled=True,
)


class _MemoryRawStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes):
        self._content = content

    async def __aiter__(self):
        yield self._content

    async def aclose(self) -> None:
        self._content = b""


class _BorrowedAsyncTransport(httpx.AsyncBaseTransport):
    """Delegate requests without taking ownership of transport lifecycle."""

    def __init__(self, transport: httpx.AsyncBaseTransport):
        self._transport = transport

    async def handle_async_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        response = await self._transport.handle_async_request(request)
        if not response.is_stream_consumed:
            return response
        content = response.content
        status_code = response.status_code
        headers = response.headers
        extensions = response.extensions
        await response.aclose()
        response = None
        return httpx.Response(
            status_code,
            headers=headers,
            stream=_MemoryRawStream(content),
            extensions=extensions,
            request=request,
        )

    async def aclose(self) -> None:
        return None


def openai_chat_completions_endpoint(base_url: str) -> str:
    """Validate and join an OpenAI-compatible chat-completions endpoint."""

    parsed = httpx.URL(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.host:
        raise ValueError("OpenAI-compatible endpoint is invalid")
    path = parsed.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path += "/chat/completions"
    return str(parsed.copy_with(path=path))


async def request_openai_json(
    *,
    provider: Mapping[str, object],
    model_name: str,
    messages: Sequence[Mapping[str, str]],
    transport: httpx.AsyncBaseTransport | None,
    timeout_seconds: int | float,
    max_response_bytes: int,
) -> OpenAIJSONTransportResult:
    """Make one bounded call and return decoded JSON or a safe failure."""

    result = OPENAI_JSON_TRANSPORT_FAILURE
    decoded_value: object | None = None
    base_url = None
    api_key = None
    temperature = None
    max_output_value = None
    max_output_tokens = None
    timeout_value = None
    endpoint = None
    authorization = None
    request_body = None
    rendered_request_body = None
    secrets = ()
    client_transport = None
    client = None
    response = None
    response_bytes = bytearray()
    content_encoding = None
    declared = None
    declared_size = None
    chunk = None
    remaining = None
    response_text = None
    envelope = None
    content = None
    try:
        if not provider_type_is_supported(provider.get("provider_type")):
            raise ValueError("invalid runtime")
        if not isinstance(model_name, str) or not model_name.strip():
            raise ValueError("invalid runtime")
        base_url = provider["base_url"]
        api_key = provider["api_key"]
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("invalid runtime")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("invalid runtime")
        temperature = float(provider["temperature"])
        max_output_value = provider.get("max_output_tokens")
        if max_output_value is None:
            max_output_value = provider["maxOutputTokens"]
        max_output_tokens = int(max_output_value)
        timeout_value = float(timeout_seconds)
        if (
            not math.isfinite(temperature)
            or temperature < 0
            or max_output_tokens <= 0
            or not math.isfinite(timeout_value)
            or timeout_value <= 0
            or type(max_response_bytes) is not int
            or max_response_bytes <= 0
        ):
            raise ValueError("invalid runtime")

        endpoint = openai_chat_completions_endpoint(base_url.strip())
        authorization = f"Bearer {api_key.strip()}"
        secrets = normalize_provider_secrets((api_key, base_url))
        request_body = {
            "model": model_name.strip(),
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_output_tokens,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        rendered_request_body = json.dumps(
            request_body,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        if (
            provider_response_text_contains_secret(
                rendered_request_body,
                secrets,
            )
            or provider_response_value_contains_secret(
                request_body,
                secrets,
            )
        ):
            raise ValueError("unsafe request")
        client_transport = (
            _BorrowedAsyncTransport(transport)
            if transport is not None
            else None
        )

        async with asyncio.timeout(timeout_value):
            async with httpx.AsyncClient(
                transport=client_transport,
                timeout=httpx.Timeout(
                    connect=15,
                    read=timeout_value,
                    write=30,
                    pool=15,
                ),
            ) as client:
                async with client.stream(
                    "POST",
                    endpoint,
                    headers={
                        "Authorization": authorization,
                        "Accept-Encoding": "identity",
                    },
                    json=request_body,
                ) as response:
                    if not response.is_success:
                        raise ValueError("remote failure")
                    content_encoding = response.headers.get(
                        "content-encoding",
                        "",
                    ).strip()
                    if (
                        content_encoding
                        and content_encoding.casefold() != "identity"
                    ):
                        raise ValueError("encoded response is forbidden")
                    declared = response.headers.get("content-length")
                    if declared is not None:
                        declared_size = int(declared)
                        if (
                            declared_size < 0
                            or declared_size > max_response_bytes
                        ):
                            raise ValueError("response too large")
                    async for chunk in response.aiter_raw():
                        remaining = (
                            max_response_bytes + 1 - len(response_bytes)
                        )
                        if remaining > 0:
                            response_bytes.extend(chunk[:remaining])
                        if (
                            len(response_bytes) > max_response_bytes
                            or len(chunk) > remaining
                        ):
                            raise ValueError("response too large")

        response_text = bytes(response_bytes).decode("utf-8")
        if provider_response_text_contains_secret(response_text, secrets):
            raise ValueError("unsafe response")
        envelope = json.loads(response_text)
        if provider_response_value_contains_secret(envelope, secrets):
            raise ValueError("unsafe response")
        content = validate_provider_response_text(
            envelope["choices"][0]["message"]["content"],
            strip=True,
        )
        if provider_response_text_contains_secret(content, secrets):
            raise ValueError("unsafe response")
        decoded_value = json.loads(content)
        if provider_response_value_contains_secret(
            decoded_value,
            secrets,
        ):
            raise ValueError("unsafe response")
        result = OpenAIJSONTransportResult(
            succeeded=True,
            value=decoded_value,
        )
    except asyncio.CancelledError:
        result = OPENAI_JSON_TRANSPORT_CANCELLED
    except Exception:
        result = OPENAI_JSON_TRANSPORT_FAILURE
    finally:
        response_bytes.clear()
        provider = None
        model_name = None
        messages = ()
        transport = None
        base_url = None
        api_key = None
        temperature = None
        max_output_value = None
        max_output_tokens = None
        timeout_value = None
        endpoint = None
        authorization = None
        request_body = None
        rendered_request_body = None
        secrets = ()
        client_transport = None
        client = None
        response = None
        response_bytes = None
        content_encoding = None
        declared = None
        declared_size = None
        chunk = None
        remaining = None
        response_text = None
        envelope = None
        content = None
        decoded_value = None

    return result


__all__ = (
    "OPENAI_JSON_TRANSPORT_CANCELLED",
    "OPENAI_JSON_TRANSPORT_FAILURE",
    "OpenAIJSONTransportResult",
    "openai_chat_completions_endpoint",
    "request_openai_json",
)
