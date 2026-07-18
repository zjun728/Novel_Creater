"""Bounded, single-attempt Provider connection checks."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping

import httpx


PROVIDER_CONNECTION_TIMEOUT_SECONDS = 10
MAX_PUBLIC_LATENCY_MS = 30_000


class ProviderConnectionGateway:
    """Call an OpenAI-compatible public capability endpoint exactly once."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        monotonic=None,
        timeout_seconds: float = PROVIDER_CONNECTION_TIMEOUT_SECONDS,
    ):
        self._transport = transport
        self._monotonic = monotonic or time.monotonic
        self._timeout_seconds = min(
            max(float(timeout_seconds), 0.1),
            PROVIDER_CONNECTION_TIMEOUT_SECONDS,
        )

    @staticmethod
    def _endpoint(base_url: str) -> str:
        parsed = httpx.URL(base_url)
        path = f"{parsed.path.rstrip('/')}/models"
        return str(parsed.copy_with(path=path))

    def _latency_ms(self, started_at: float) -> int:
        elapsed = round((self._monotonic() - started_at) * 1000)
        return min(MAX_PUBLIC_LATENCY_MS, max(0, int(elapsed)))

    @staticmethod
    def _result(
        *,
        ok: bool,
        code: str,
        latency_ms: int,
        public_message: str,
    ) -> dict:
        return {
            "ok": ok,
            "code": code,
            "latencyMs": latency_ms,
            "publicMessage": public_message,
        }

    async def test_connection(self, provider: Mapping[str, object]) -> dict:
        started_at = self._monotonic()
        timeout = httpx.Timeout(self._timeout_seconds)
        try:
            endpoint = self._endpoint(str(provider["base_url"]))
            headers = {"Authorization": f"Bearer {provider['api_key']}"}
            async with asyncio.timeout(self._timeout_seconds):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=timeout,
                ) as client:
                    response = await client.get(endpoint, headers=headers)
        except (httpx.TimeoutException, TimeoutError):
            return self._result(
                ok=False,
                code="provider_timeout",
                latency_ms=self._latency_ms(started_at),
                public_message="连接超时",
            )
        except (httpx.TransportError, httpx.InvalidURL, ValueError):
            return self._result(
                ok=False,
                code="provider_unreachable",
                latency_ms=self._latency_ms(started_at),
                public_message="无法连接 Provider",
            )

        latency_ms = self._latency_ms(started_at)
        if response.is_error:
            return self._result(
                ok=False,
                code="provider_rejected",
                latency_ms=latency_ms,
                public_message="Provider 拒绝连接",
            )
        return self._result(
            ok=True,
            code="connected",
            latency_ms=latency_ms,
            public_message="连接成功",
        )
