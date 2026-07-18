from __future__ import annotations

import httpx
import pytest

from backend.gateways.provider_connection import (
    MAX_PUBLIC_LATENCY_MS,
    PROVIDER_CONNECTION_TIMEOUT_SECONDS,
    ProviderConnectionGateway,
)


SECRET = "gateway-secret"
PRIVATE_URL = "https://private-provider.example/v1"


def private_provider():
    return {
        "provider_type": "openai-compatible",
        "model_name": "model-one",
        "api_key": SECRET,
        "base_url": PRIVATE_URL,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [200, 204, 299])
async def test_every_2xx_is_exact_bounded_success_and_one_attempt(status_code):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status_code, request=request)

    gateway = ProviderConnectionGateway(
        transport=httpx.MockTransport(respond),
        monotonic=iter((10.000, 10.012)).__next__,
    )

    result = await gateway.test_connection(private_provider())

    assert result == {
        "ok": True,
        "code": "connected",
        "latencyMs": 12,
        "publicMessage": "连接成功",
    }
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == f"Bearer {SECRET}"
    assert requests[0].url == f"{PRIVATE_URL}/models"
    timeout = requests[0].extensions["timeout"]
    assert all(
        0 < timeout[phase] <= PROVIDER_CONNECTION_TIMEOUT_SECONDS
        for phase in ("connect", "read", "write", "pool")
    )


@pytest.mark.asyncio
async def test_anthropic_is_fixed_unsupported_without_request():
    attempts = 0

    def respond(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(200, request=request)

    gateway = ProviderConnectionGateway(
        transport=httpx.MockTransport(respond),
        monotonic=iter((10.0, 10.001)).__next__,
    )
    provider = {
        **private_provider(),
        "provider_type": "anthropic",
        "base_url": "https://api.anthropic.com",
    }

    result = await gateway.test_connection(provider)

    assert result == {
        "ok": False,
        "code": "provider_unsupported",
        "latencyMs": 1,
        "publicMessage": "不支持的 Provider 类型",
    }
    assert attempts == 0
    assert SECRET not in str(result)
    assert PRIVATE_URL not in str(result)


@pytest.mark.asyncio
async def test_unsupported_provider_type_is_fixed_failure_without_request():
    attempts = 0

    def respond(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(200, request=request)

    gateway = ProviderConnectionGateway(
        transport=httpx.MockTransport(respond),
        monotonic=iter((10.0, 10.001)).__next__,
    )

    result = await gateway.test_connection(
        {**private_provider(), "provider_type": "unsupported-native"}
    )

    assert result == {
        "ok": False,
        "code": "provider_unsupported",
        "latencyMs": 1,
        "publicMessage": "不支持的 Provider 类型",
    }
    assert attempts == 0
    assert SECRET not in str(result)
    assert PRIVATE_URL not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "code", "message"),
    [
        (
            lambda request: httpx.Response(
                401,
                text=f"raw body {SECRET} {PRIVATE_URL}",
                headers={"authorization": SECRET},
                request=request,
            ),
            "provider_rejected",
            "Provider 拒绝连接",
        ),
        (
            lambda request: httpx.Response(
                302,
                text=f"redirect {SECRET} {PRIVATE_URL}",
                headers={"location": f"{PRIVATE_URL}/redirect?token={SECRET}"},
                request=request,
            ),
            "provider_rejected",
            "Provider 拒绝连接",
        ),
        (
            lambda request: httpx.Response(
                500,
                text=f"server {SECRET} {PRIVATE_URL}",
                request=request,
            ),
            "provider_rejected",
            "Provider 拒绝连接",
        ),
        (
            lambda request: (_ for _ in ()).throw(
                httpx.ConnectError(
                    f"transport {SECRET} {PRIVATE_URL}", request=request
                )
            ),
            "provider_unreachable",
            "无法连接 Provider",
        ),
        (
            lambda request: (_ for _ in ()).throw(
                httpx.ReadTimeout(
                    f"timeout {SECRET} {PRIVATE_URL}", request=request
                )
            ),
            "provider_timeout",
            "连接超时",
        ),
    ],
)
async def test_upstream_failures_use_fixed_codes_without_raw_details(
    response, code, message
):
    attempts = 0

    def transport(request):
        nonlocal attempts
        attempts += 1
        return response(request)

    gateway = ProviderConnectionGateway(
        transport=httpx.MockTransport(transport),
        monotonic=iter((0.0, 99_999.0)).__next__,
    )

    result = await gateway.test_connection(private_provider())

    assert result == {
        "ok": False,
        "code": code,
        "latencyMs": MAX_PUBLIC_LATENCY_MS,
        "publicMessage": message,
    }
    assert attempts == 1
    rendered = str(result)
    assert SECRET not in rendered
    assert PRIVATE_URL not in rendered
    assert "raw body" not in rendered
    assert "headers" not in rendered
