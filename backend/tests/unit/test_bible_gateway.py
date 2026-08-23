from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from backend.domain.bibles import BiblePayload
from backend.gateways.bible_provider import (
    MAX_PROVIDER_RESPONSE_BYTES,
    BibleProviderGateway,
    BibleProviderHTTPError,
    BibleProviderParseError,
    BibleProviderTimeoutError,
    BibleProviderTransportError,
)


def _payload(**changes):
    item = lambda identity: [{"id": identity, "text": f"{identity} design"}]
    values = {
        "premiseAndPromise": "知识能解决困境，也会制造新的关系债。",
        "worldRules": item("world"),
        "powerOrProgressionSystem": "成长来自组织知识与承担公开知识的代价。",
        "protagonist": "沈砚谨慎、固执，必须学会让同伴参与判断。",
        "coreCast": item("cast"),
        "factions": item("faction"),
        "longTermConflicts": item("conflict"),
        "relationshipDynamics": item("relationship"),
        "toneAndNarrativeBoundaries": "克制、具体，不把知识写成万能答案。",
        "continuityGuardrails": item("guardrail"),
        "openDesignQuestions": item("question"),
    }
    values.update(changes)
    return values


def _envelope(content):
    return {
        "choices": [
            {
                "message": {
                    "content": (
                        content
                        if isinstance(content, str)
                        else json.dumps(content, ensure_ascii=False)
                    )
                }
            }
        ]
    }


def _provider():
    return {
        "model_name": "novel-model",
        "base_url": "https://provider.invalid/v1",
        "api_key": "PRIVATE_PROVIDER_KEY_123456",
    }


@pytest.mark.asyncio
async def test_gateway_makes_exactly_one_json_mode_non_streaming_call():
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json=_envelope(_payload()))

    result = await BibleProviderGateway(
        transport=httpx.MockTransport(handler)
    ).generate(
        provider=_provider(),
        messages=({"role": "user", "content": "{}"},),
        generation_config={"temperature": 0.5, "maxOutputTokens": 8192},
    )

    assert isinstance(result, BiblePayload)
    assert len(requests) == 1
    request = requests[0]
    assert request.url.path == "/v1/chat/completions"
    body = json.loads(request.content)
    assert body == {
        "model": "novel-model",
        "messages": [{"role": "user", "content": "{}"}],
        "temperature": 0.5,
        "max_tokens": 8192,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "stream": False,
    }


@pytest.mark.parametrize(
    "response_body",
    (
        _envelope({**_payload(), "rawProviderBody": "forbidden"}),
        _envelope({"premiseAndPromise": "incomplete"}),
        {"choices": []},
        {"choices": [{"message": {"content": "{not-json"}}]},
    ),
)
@pytest.mark.asyncio
async def test_gateway_strictly_rejects_envelope_json_and_payload_drift(
    response_body,
):
    gateway = BibleProviderGateway(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=response_body)
        )
    )
    with pytest.raises(BibleProviderParseError):
        await gateway.generate(
            provider=_provider(),
            messages=({"role": "user", "content": "{}"},),
            generation_config={"temperature": 0.5, "maxOutputTokens": 8192},
        )

@pytest.mark.parametrize(
    "secret_value",
    (
        "PRIVATE_PROVIDER_KEY_123456",
        "https://provider.invalid/v1",
        "https%3A%2F%2Fprovider.invalid%2Fv1",
    ),
)
@pytest.mark.asyncio
async def test_gateway_rejects_secrets_anywhere_in_provider_output(secret_value):
    value = _payload(protagonist=f"人物描述 {secret_value}")
    gateway = BibleProviderGateway(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=_envelope(value))
        )
    )
    with pytest.raises(BibleProviderParseError):
        await gateway.generate(
            provider=_provider(),
            messages=({"role": "user", "content": "{}"},),
            generation_config={"temperature": 0.5, "maxOutputTokens": 8192},
        )


@pytest.mark.asyncio
async def test_gateway_bounds_response_before_decoding():
    gateway = BibleProviderGateway(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                content=b"x" * (MAX_PROVIDER_RESPONSE_BYTES + 1),
            )
        )
    )
    with pytest.raises(BibleProviderParseError):
        await gateway.generate(
            provider=_provider(),
            messages=({"role": "user", "content": "{}"},),
            generation_config={"temperature": 0.5, "maxOutputTokens": 8192},
        )


@pytest.mark.asyncio
async def test_gateway_keeps_http_transport_and_outer_timeout_failures_distinct(
    monkeypatch,
):
    http_gateway = BibleProviderGateway(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(429, json={"private": "detail"})
        )
    )
    with pytest.raises(BibleProviderHTTPError):
        await http_gateway.generate(
            provider=_provider(),
            messages=({"role": "user", "content": "{}"},),
            generation_config={"temperature": 0.5, "maxOutputTokens": 8192},
        )

    def transport_failure(_request):
        raise httpx.ConnectError("PRIVATE_TRANSPORT_DETAIL")

    with pytest.raises(BibleProviderTransportError):
        await BibleProviderGateway(
            transport=httpx.MockTransport(transport_failure)
        ).generate(
            provider=_provider(),
            messages=({"role": "user", "content": "{}"},),
            generation_config={"temperature": 0.5, "maxOutputTokens": 8192},
        )

    async def slow(_request):
        await asyncio.sleep(1)
        return httpx.Response(200, json=_envelope(_payload()))

    monkeypatch.setattr(
        "backend.gateways.bible_provider.PROVIDER_TIMEOUT_SECONDS",
        0.001,
    )
    with pytest.raises(BibleProviderTimeoutError):
        await BibleProviderGateway(
            transport=httpx.MockTransport(slow)
        ).generate(
            provider=_provider(),
            messages=({"role": "user", "content": "{}"},),
            generation_config={"temperature": 0.5, "maxOutputTokens": 8192},
        )
