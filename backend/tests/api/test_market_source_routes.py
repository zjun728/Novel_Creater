from __future__ import annotations

from inspect import signature
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient


SOURCE_ID = "00000000-0000-0000-0000-000000000101"
SNAPSHOT_ID = "00000000-0000-0000-0000-000000000201"
NOW = 1_721_000_000_000


def _snapshot():
    return {
        "id": SNAPSHOT_ID,
        "source_id": SOURCE_ID,
        "captured_at": NOW,
        "platform": "qidian",
        "ranking_name": "newsign",
        "category": "male",
        "source_url": "https://www.qidian.com/rank/newsign/",
        "content_hash": "a" * 64,
        "entry_count": 1,
        "entries": (
            {
                "rank": 1,
                "title": "雾港天文钟",
                "author": "合成作者甲",
                "category": "奇幻",
                "work_url": "https://www.qidian.com/book/900000001/",
                "public_metrics": {"weeklyRecommendations": 321},
            },
        ),
    }


class FakeService:
    def __init__(self):
        self.calls = []

    async def list_sources(self):
        self.calls.append(("list_sources",))
        return (
            {
                "id": SOURCE_ID,
                "stable_key": "qidian.newsign",
                "display_name": "起点新签榜",
                "adapter_key": "qidian_public_rank",
                "platform": "qidian",
                "ranking_name": "newsign",
                "category": "male",
                "policy_status": "manual_only",
                "policy_version": "public-rank-policy-v1",
                "checked_at": NOW,
                "evidence_url": "https://evidence.example/qidian",
                "automatic_refresh_allowed": False,
                "refresh_status": "idle",
                "last_attempted_at": None,
                "last_succeeded_at": None,
                "last_snapshot_id": None,
                "public_error_code": None,
            },
        )

    async def get_source(self, source_id):
        self.calls.append(("get_source", source_id))
        return (await self.list_sources())[0]

    async def list_snapshots(self, source_id):
        self.calls.append(("list_snapshots", source_id))
        value = _snapshot()
        value.pop("entries")
        return (value,)

    async def get_snapshot(self, source_id, snapshot_id):
        self.calls.append(("get_snapshot", source_id, snapshot_id))
        return _snapshot()

    async def import_manual(self, source_id, snapshot, idempotency_key):
        self.calls.append(("import_manual", source_id, idempotency_key, snapshot))
        return _snapshot()

    async def refresh(self, source_id, idempotency_key):
        self.calls.append(("refresh", source_id, idempotency_key))
        return _snapshot()


def _client():
    from backend.routers import market_sources
    from backend.security.redaction import install_error_handlers

    service = FakeService()
    app = FastAPI()
    app.include_router(market_sources.router, prefix="/api")
    app.dependency_overrides[market_sources.get_market_source_service] = lambda: service
    install_error_handlers(app)
    return TestClient(app, raise_server_exceptions=False), service, market_sources


def test_market_source_routes_expose_only_inventory_status_history_detail_and_commands():
    client, service, market_sources = _client()
    manual_payload = {
        "idempotencyKey": "m" * 64,
        "snapshot": {
            "platform": "qidian",
            "rankingName": "newsign",
            "category": "male",
            "capturedAt": NOW,
            "sourceURL": "https://www.qidian.com/rank/newsign/",
            "entries": [
                {
                    "rank": 1,
                    "title": "雾港天文钟",
                    "author": "合成作者甲",
                    "category": "奇幻",
                    "workURL": "https://www.qidian.com/book/900000001/",
                    "publicMetrics": {},
                }
            ],
        },
    }

    responses = (
        client.get("/api/market-sources"),
        client.get(f"/api/market-sources/{SOURCE_ID}"),
        client.get(f"/api/market-sources/{SOURCE_ID}/snapshots"),
        client.get(f"/api/market-sources/{SOURCE_ID}/snapshots/{SNAPSHOT_ID}"),
        client.post(f"/api/market-sources/{SOURCE_ID}/manual-import", json=manual_payload),
        client.post(
            f"/api/market-sources/{SOURCE_ID}/refresh",
            json={"idempotencyKey": "r" * 64},
        ),
    )

    assert [response.status_code for response in responses] == [200] * 6
    source = responses[0].json()[0]
    assert set(source) == {
        "id",
        "stableKey",
        "displayName",
        "adapterKey",
        "platform",
        "rankingName",
        "category",
        "policyStatus",
        "policyVersion",
        "checkedAt",
        "evidenceURL",
        "automaticRefreshAllowed",
        "refreshStatus",
        "lastAttemptedAt",
        "lastSucceededAt",
        "lastSnapshotId",
        "publicErrorCode",
    }
    detail = responses[3].json()
    assert set(detail) == {
        "id",
        "sourceId",
        "capturedAt",
        "platform",
        "rankingName",
        "category",
        "sourceURL",
        "contentHash",
        "entryCount",
        "entries",
    }
    assert set(detail["entries"][0]) == {
        "rank",
        "title",
        "author",
        "category",
        "workURL",
        "publicMetrics",
    }
    methods = {route.path: route.methods for route in market_sources.router.routes}
    assert methods == {
        "/market-sources": {"GET"},
        "/market-sources/{source_id}": {"GET"},
        "/market-sources/{source_id}/snapshots": {"GET"},
        "/market-sources/{source_id}/snapshots/{snapshot_id}": {"GET"},
        "/market-sources/{source_id}/manual-import": {"POST"},
        "/market-sources/{source_id}/refresh": {"POST"},
    }
    assert "url" not in signature(market_sources.refresh_market_source).parameters
    assert "policy" not in signature(market_sources.refresh_market_source).parameters
    assert len(service.calls) == 7


def test_route_identifiers_and_payloads_are_strictly_bounded():
    client, _, _ = _client()

    responses = (
        client.get("/api/market-sources/" + "s" * 37),
        client.get(
            f"/api/market-sources/{SOURCE_ID}/snapshots/" + "x" * 37
        ),
        client.post(
            f"/api/market-sources/{SOURCE_ID}/refresh",
            json={"idempotencyKey": "short", "url": "https://evil.example"},
        ),
        client.post(
            f"/api/market-sources/{SOURCE_ID}/manual-import",
            json={"idempotencyKey": "m" * 64, "snapshot": {}, "rawHTML": "secret"},
        ),
    )

    assert [response.status_code for response in responses] == [422] * 4
    assert "secret" not in str(responses[-1].json()).casefold()


def test_manual_import_nested_raw_content_fails_with_no_echo_before_service():
    client, service, _ = _client()
    raw_sentinel = "PRIVATE_RAW_MARKET_RESPONSE_SENTINEL"
    snapshot = {
        "platform": "qidian",
        "rankingName": "newsign",
        "category": "male",
        "capturedAt": NOW,
        "sourceURL": "https://www.qidian.com/rank/newsign/",
        "entries": [
            {
                "rank": 1,
                "title": "雾港天文钟",
                "author": "合成作者甲",
                "category": "奇幻",
                "workURL": "https://www.qidian.com/book/900000001/",
                "publicMetrics": {},
            }
        ],
        "rawHTML": raw_sentinel,
    }

    response = client.post(
        f"/api/market-sources/{SOURCE_ID}/manual-import",
        json={"idempotencyKey": "m" * 64, "snapshot": snapshot},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "MARKET_MANUAL_SNAPSHOT_INVALID"
    assert raw_sentinel not in str(response.json())
    assert service.calls == []


def test_refresh_rejects_raw_url_and_policy_overrides_without_echo(
    caplog,
):
    client, service, _ = _client()
    raw_sentinel = "PRIVATE_REFRESH_RAW_HTML_SENTINEL"
    caplog.set_level(logging.WARNING, logger="backend")

    response = client.post(
        f"/api/market-sources/{SOURCE_ID}/refresh",
        json={
            "idempotencyKey": "r" * 64,
            "rawHTML": raw_sentinel,
            "url": "https://evil.example/rank",
            "policy": {"status": "verified_public"},
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "MARKET_REFRESH_COMMAND_INVALID"
    assert raw_sentinel not in str(response.json())
    assert raw_sentinel not in caplog.text
    assert service.calls == []


def test_command_response_never_masks_missing_persisted_entries_as_empty_detail():
    client, service, _ = _client()

    async def summary_only(source_id, idempotency_key):
        value = _snapshot()
        value.pop("entries")
        return value

    service.refresh = summary_only

    response = client.post(
        f"/api/market-sources/{SOURCE_ID}/refresh",
        json={"idempotencyKey": "r" * 64},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "MARKET_REFRESH_FAILED"
    assert "entries" not in response.json()


def test_main_registers_new_routes_and_has_no_old_market_scrape_route():
    from backend import main

    paths = {route.path for route in main.app.routes}
    assert "/api/market-sources" in paths
    assert "/api/market-sources/{source_id}/manual-import" in paths
    assert "/api/market/scrape" not in paths
