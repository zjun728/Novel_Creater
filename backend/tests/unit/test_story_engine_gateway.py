from __future__ import annotations

import asyncio
from hashlib import sha256
import json

import httpx
import pytest

from backend.gateways import story_engine_provider as gateway_module
from backend.gateways.story_engine_provider import (
    StoryEngineProviderGateway,
    StoryEngineProviderHTTPError,
    StoryEngineProviderResponseError,
    StoryEngineProviderTransportError,
)


MESSAGES = (
    {"role": "system", "content": "system"},
    {"role": "user", "content": "user"},
)
GENERATION_CONFIG = {"temperature": 0.321, "maxOutputTokens": 1_234}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("base_url", "expected_url"),
    (
        ("https://provider.example/v1/", "https://provider.example/v1/chat/completions"),
        (
            "https://provider.example/v1/chat/completions",
            "https://provider.example/v1/chat/completions",
        ),
        (
            "https://provider.example/v1/chat/completions?api-version=2026-01",
            "https://provider.example/v1/chat/completions?api-version=2026-01",
        ),
    ),
)
async def test_gateway_posts_one_fixed_json_mode_request(base_url, expected_url):
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"options": []}'}}]},
        )

    gateway = StoryEngineProviderGateway(
        transport=httpx.MockTransport(handler)
    )
    content = await gateway.generate(
        provider={
            "base_url": base_url,
            "api_key": "KEY_SENTINEL",
            "model_name": "frozen-model",
        },
        messages=MESSAGES,
        generation_config=GENERATION_CONFIG,
    )

    assert content == '{"options": []}'
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == expected_url
    assert request.headers["Authorization"] == "Bearer KEY_SENTINEL"
    assert request.extensions["timeout"] == {
        "connect": 15,
        "read": 180,
        "write": 30,
        "pool": 15,
    }
    assert json.loads(request.content) == {
        "model": "frozen-model",
        "messages": list(MESSAGES),
        "temperature": 0.321,
        "max_tokens": 1_234,
        "response_format": {"type": "json_object"},
        "stream": False,
    }


@pytest.mark.asyncio
async def test_gateway_invalid_envelope_error_carries_only_exact_body_hash():
    raw_body = b'{"bad":"SECRET_SENTINEL"}'

    def handler(request: httpx.Request):
        return httpx.Response(200, content=raw_body, request=request)

    gateway = StoryEngineProviderGateway(transport=httpx.MockTransport(handler))

    with pytest.raises(StoryEngineProviderResponseError) as captured:
        await gateway.generate(
            provider={
                "base_url": "https://provider.example/v1",
                "api_key": "KEY_SENTINEL",
                "model_name": "frozen-model",
            },
            messages=MESSAGES,
            generation_config=GENERATION_CONFIG,
        )

    assert captured.value.response_hash == sha256(raw_body).hexdigest()
    assert "SECRET_SENTINEL" not in str(captured.value)
    assert "SECRET_SENTINEL" not in repr(captured.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"choices": []},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": ""}}]},
        {"choices": [{"message": {"content": 42}}]},
    ),
)
async def test_gateway_strictly_requires_non_empty_first_message_content(payload):
    gateway = StoryEngineProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload)
        )
    )
    with pytest.raises(StoryEngineProviderResponseError) as caught:
        await gateway.generate(
            provider={
                "base_url": "https://PRIVATE_URL_SENTINEL/v1",
                "api_key": "KEY_SENTINEL",
                "model_name": "model",
            },
            messages=MESSAGES,
            generation_config=GENERATION_CONFIG,
        )
    rendered = str(caught.value)
    assert "KEY_SENTINEL" not in rendered
    assert "PRIVATE_URL_SENTINEL" not in rendered
    assert repr(payload) not in rendered


@pytest.mark.asyncio
async def test_gateway_converts_http_failure_to_secret_free_public_exception():
    gateway = StoryEngineProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                503, text="RAW_RESPONSE_SENTINEL", request=request
            )
        )
    )
    with pytest.raises(StoryEngineProviderHTTPError) as caught:
        await gateway.generate(
            provider={
                "base_url": "https://PRIVATE_URL_SENTINEL/v1",
                "api_key": "KEY_SENTINEL",
                "model_name": "model",
            },
            messages=MESSAGES,
            generation_config=GENERATION_CONFIG,
        )
    rendered = str(caught.value)
    assert all(
        item not in rendered
        for item in ("KEY_SENTINEL", "PRIVATE_URL_SENTINEL", "RAW_RESPONSE_SENTINEL")
    )


@pytest.mark.asyncio
async def test_gateway_applies_outer_total_deadline(monkeypatch):
    async def handler(request: httpx.Request):
        await asyncio.sleep(0.05)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}}]},
        )

    monkeypatch.setattr(gateway_module, "PROVIDER_TIMEOUT_SECONDS", 0.001)
    gateway = StoryEngineProviderGateway(
        transport=httpx.MockTransport(handler)
    )
    with pytest.raises(TimeoutError):
        await gateway.generate(
            provider={
                "base_url": "https://provider.example/v1",
                "api_key": "key",
                "model_name": "model",
            },
            messages=MESSAGES,
            generation_config=GENERATION_CONFIG,
        )


@pytest.mark.asyncio
async def test_gateway_redacts_invalid_url_failures():
    gateway = StoryEngineProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={})
        )
    )
    with pytest.raises(StoryEngineProviderTransportError) as caught:
        await gateway.generate(
            provider={
                "base_url": "https://provider.example:PRIVATE_URL_SENTINEL/v1",
                "api_key": "KEY_SENTINEL",
                "model_name": "model",
            },
            messages=MESSAGES,
            generation_config=GENERATION_CONFIG,
        )
    rendered = str(caught.value)
    assert "KEY_SENTINEL" not in rendered
    assert "PRIVATE_URL_SENTINEL" not in rendered


@pytest.mark.asyncio
async def test_gateway_converts_content_decoding_failure_to_safe_response_error():
    gateway = StoryEngineProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"Content-Encoding": "gzip"},
                content=b"RAW_SECRET_SENTINEL not-gzip",
                request=request,
            )
        )
    )
    with pytest.raises(StoryEngineProviderResponseError) as caught:
        await gateway.generate(
            provider={
                "base_url": "https://PRIVATE_URL_SENTINEL/v1",
                "api_key": "KEY_SENTINEL",
                "model_name": "model",
            },
            messages=MESSAGES,
            generation_config=GENERATION_CONFIG,
        )
    rendered = str(caught.value)
    assert all(
        value not in rendered
        for value in (
            "KEY_SENTINEL",
            "PRIVATE_URL_SENTINEL",
            "RAW_SECRET_SENTINEL",
        )
    )
