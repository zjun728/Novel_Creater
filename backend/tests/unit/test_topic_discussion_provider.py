from __future__ import annotations

import json

import httpx
import pytest


def _provider() -> dict[str, object]:
    return {
        "provider_type": "openai-compatible",
        "base_url": "https://provider.example/v1",
        "api_key": "PRIVATE_TOPIC_KEY",
        "temperature": 0.6,
        "max_output_tokens": 16_384,
    }


def _result() -> dict:
    return {
        "reply": "这个方向可以用地方治理承载长期升级。",
        "directionSuggestions": [],
        "candidateSuggestions": [],
    }


def _response(value: object, request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(value, ensure_ascii=False),
                    }
                }
            ]
        },
        request=request,
    )


@pytest.mark.asyncio
async def test_gateway_uses_one_lifespan_owned_bounded_json_call():
    from backend.gateways.topic_discussion_provider import (
        MAX_PROVIDER_RESPONSE_BYTES,
        PROVIDER_TIMEOUT_SECONDS,
        TopicDiscussionProviderGateway,
    )

    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        return _response(_result(), request)

    gateway = TopicDiscussionProviderGateway(
        transport=httpx.MockTransport(handler)
    )
    await gateway.start()
    try:
        result = await gateway.generate(
            provider=_provider(),
            model_name="topic-model",
            messages=({"role": "user", "content": "讨论想法"},),
        )
    finally:
        await gateway.aclose()
    assert PROVIDER_TIMEOUT_SECONDS == 180
    assert MAX_PROVIDER_RESPONSE_BYTES == 256 * 1024
    assert result.reply.startswith("这个方向")
    assert len(calls) == 1
    body = json.loads(calls[0].content)
    assert body["model"] == "topic-model"
    assert body["stream"] is False
    assert body["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    (
        {**_result(), "provider": "private"},
        {"reply": "只有回复"},
        [],
    ),
)
async def test_gateway_rejects_invalid_or_extra_provider_output(payload):
    from backend.gateways.topic_discussion_provider import (
        TopicDiscussionInvalidResponse,
        TopicDiscussionProviderGateway,
    )

    gateway = TopicDiscussionProviderGateway(
        transport=httpx.MockTransport(lambda request: _response(payload, request))
    )
    await gateway.start()
    try:
        with pytest.raises(TopicDiscussionInvalidResponse):
            await gateway.generate(
                provider=_provider(),
                model_name="topic-model",
                messages=({"role": "user", "content": "讨论想法"},),
            )
    finally:
        await gateway.aclose()


@pytest.mark.asyncio
async def test_gateway_rejects_private_request_material_and_oversized_response():
    from backend.gateways.topic_discussion_provider import (
        MAX_PROVIDER_RESPONSE_BYTES,
        TopicDiscussionProviderError,
        TopicDiscussionProviderGateway,
    )

    calls = 0

    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        content = b"x" * (MAX_PROVIDER_RESPONSE_BYTES + 1)
        return httpx.Response(200, content=content, request=request)

    gateway = TopicDiscussionProviderGateway(
        transport=httpx.MockTransport(handler)
    )
    await gateway.start()
    try:
        with pytest.raises(TopicDiscussionProviderError):
            await gateway.generate(
                provider=_provider(),
                model_name="topic-model",
                messages=(
                    {
                        "role": "user",
                        "content": '{"apiKey":"must-not-leave"}',
                    },
                ),
            )
        assert calls == 0

        with pytest.raises(TopicDiscussionProviderError):
            await gateway.generate(
                provider=_provider(),
                model_name="topic-model",
                messages=({"role": "user", "content": "普通想法"},),
            )
        assert calls == 1
    finally:
        await gateway.aclose()
