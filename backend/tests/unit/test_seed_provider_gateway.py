from __future__ import annotations

import importlib
import json

import httpx
import pytest


def _feature():
    try:
        return importlib.import_module("backend.gateways.seed_provider")
    except ModuleNotFoundError:
        pytest.fail("seed provider gateway is missing")


@pytest.mark.asyncio
async def test_seed_gateway_makes_one_bounded_non_streaming_request():
    module = _feature()
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "把知识优势拆成三次递进兑现。"}}
                ]
            },
        )

    result = await module.SeedProviderGateway(
        transport=httpx.MockTransport(handler)
    ).generate(
        provider={
            "model_name": "deepseek-v4-flash",
            "base_url": "https://provider.invalid/v1",
            "api_key": "PRIVATE_KEY",
        },
        messages=({"role": "user", "content": "facts"},),
        generation_config={"temperature": 0.7, "maxOutputTokens": 1600},
    )

    assert result == "把知识优势拆成三次递进兑现。"
    assert len(calls) == 1
    body = json.loads(calls[0].content)
    assert body["stream"] is False
    assert body["model"] == "deepseek-v4-flash"
    assert calls[0].headers["authorization"] == "Bearer PRIVATE_KEY"


@pytest.mark.asyncio
async def test_seed_gateway_rejects_remote_errors_and_oversized_body_without_echo():
    module = _feature()

    def failed(_request):
        return httpx.Response(500, text="PRIVATE_REMOTE_SENTINEL")

    with pytest.raises(module.SeedProviderHTTPError) as caught:
        await module.SeedProviderGateway(
            transport=httpx.MockTransport(failed)
        ).generate(
            provider={
                "model_name": "model",
                "base_url": "https://provider.invalid/v1",
                "api_key": "PRIVATE_KEY",
            },
            messages=({"role": "user", "content": "facts"},),
            generation_config={"temperature": 0.7, "maxOutputTokens": 1600},
        )
    assert "PRIVATE_REMOTE_SENTINEL" not in repr(caught.value)
    assert "PRIVATE_KEY" not in repr(caught.value)

    oversized = b"x" * (module.MAX_PROVIDER_RESPONSE_BYTES + 1)

    def too_large(_request):
        return httpx.Response(
            200,
            headers={"content-length": str(len(oversized))},
            content=b"{}",
        )

    with pytest.raises(module.SeedProviderResponseError):
        await module.SeedProviderGateway(
            transport=httpx.MockTransport(too_large)
        ).generate(
            provider={
                "model_name": "model",
                "base_url": "https://provider.invalid/v1",
                "api_key": "PRIVATE_KEY",
            },
            messages=({"role": "user", "content": "facts"},),
            generation_config={"temperature": 0.7, "maxOutputTokens": 1600},
        )
