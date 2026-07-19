from __future__ import annotations

import importlib
import json

import httpx
import pytest


def _feature():
    try:
        return importlib.import_module(
            "backend.gateways.market_analysis_provider"
        )
    except ModuleNotFoundError:
        pytest.fail("market analysis provider gateway module is missing")


@pytest.mark.asyncio
async def test_gateway_makes_one_non_streaming_strict_json_request():
    module = _feature()
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "currentHeat": [],
                                    "growthDirections": [],
                                    "crowding": [],
                                    "opportunities": [],
                                    "uncertainties": [],
                                    "sourceCoverage": {
                                        "snapshotIds": [],
                                        "summary": "none",
                                    },
                                }
                            )
                        }
                    }
                ]
            },
        )

    gateway = module.MarketAnalysisProviderGateway(
        transport=httpx.MockTransport(handler)
    )
    result = await gateway.generate(
        provider={
            "model_name": "deepseek-v4-flash",
            "base_url": "https://provider.invalid/v1",
            "api_key": "PRIVATE_GATEWAY_KEY",
        },
        messages=(
            {"role": "system", "content": "system"},
            {"role": "user", "content": "facts"},
        ),
        generation_config={"temperature": 0.2, "maxOutputTokens": 2400},
    )

    assert '"currentHeat"' in result
    assert len(calls) == 1
    request = calls[0]
    assert str(request.url) == "https://provider.invalid/v1/chat/completions"
    body = json.loads(request.content)
    assert body["stream"] is False
    assert body["response_format"] == {"type": "json_object"}
    assert body["model"] == "deepseek-v4-flash"
    assert request.headers["authorization"] == "Bearer PRIVATE_GATEWAY_KEY"


@pytest.mark.asyncio
async def test_gateway_has_safe_single_attempt_failures_without_remote_echo():
    module = _feature()
    calls = 0

    def handler(_request: httpx.Request):
        nonlocal calls
        calls += 1
        return httpx.Response(500, text="PRIVATE_REMOTE_ERROR_SENTINEL")

    gateway = module.MarketAnalysisProviderGateway(
        transport=httpx.MockTransport(handler)
    )
    with pytest.raises(module.MarketAnalysisProviderHTTPError) as caught:
        await gateway.generate(
            provider={
                "model_name": "model",
                "base_url": "https://provider.invalid/v1",
                "api_key": "PRIVATE_GATEWAY_KEY",
            },
            messages=({"role": "user", "content": "facts"},),
            generation_config={"temperature": 0.2, "maxOutputTokens": 2400},
        )

    assert calls == 1
    rendered = repr(caught.value)
    assert "PRIVATE_REMOTE_ERROR_SENTINEL" not in rendered
    assert "PRIVATE_GATEWAY_KEY" not in rendered
    assert not hasattr(caught.value, "response")


@pytest.mark.asyncio
@pytest.mark.parametrize("declared_length", [True, False])
async def test_gateway_rejects_oversized_response_before_json_decode(
    declared_length,
):
    module = _feature()
    oversized = b"x" * (module.MAX_PROVIDER_RESPONSE_BYTES + 1)

    class ChunkedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            midpoint = len(oversized) // 2
            yield oversized[:midpoint]
            yield oversized[midpoint:]

    def handler(_request: httpx.Request):
        if declared_length:
            return httpx.Response(
                200,
                headers={"content-length": str(len(oversized))},
                content=b"{}",
            )
        return httpx.Response(200, stream=ChunkedStream())

    gateway = module.MarketAnalysisProviderGateway(
        transport=httpx.MockTransport(handler)
    )
    with pytest.raises(module.MarketAnalysisProviderResponseError):
        await gateway.generate(
            provider={
                "model_name": "model",
                "base_url": "https://provider.invalid/v1",
                "api_key": "PRIVATE_GATEWAY_KEY",
            },
            messages=({"role": "user", "content": "facts"},),
            generation_config={"temperature": 0.2, "maxOutputTokens": 1},
        )
