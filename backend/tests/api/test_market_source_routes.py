from __future__ import annotations

from inspect import signature
import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.requests import Request


SOURCE_ID = "00000000-0000-0000-0000-000000000101"
SNAPSHOT_ID = "00000000-0000-0000-0000-000000000201"
PROJECT_ID = "00000000-0000-0000-0000-000000000001"
ANALYSIS_ID = "00000000-0000-0000-0000-000000000301"
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
                "public_config": {"private": "CONFIG_SENTINEL"},
                "source_url": "https://private.example/URL_SENTINEL",
                "error_detail": "ERROR_SENTINEL",
                "raw": "RAW_SENTINEL",
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

class FakeAnalysisService:
    def __init__(self):
        self.calls = []

    async def analyze(self, command):
        self.calls.append(("analyze", command))
        return {
            "id": ANALYSIS_ID,
            "project_id": PROJECT_ID,
            "input_manifest_hash": "b" * 64,
            "policy_version": "market-analysis-policy-v1",
            "status": "succeeded",
            "analysis": {
                "currentHeat": [
                    {
                        "text": "穿越题材当前有公开榜单热度。",
                        "snapshotIds": [SNAPSHOT_ID],
                        "inference": False,
                    }
                ],
                "growthDirections": [],
                "crowding": [],
                "opportunities": [],
                "uncertainties": [],
                "sourceCoverage": {
                    "snapshotIds": [SNAPSHOT_ID],
                    "summary": "覆盖一份冻结快照。",
                },
            },
            "result_hash": "c" * 64,
            "public_error_code": "PRIVATE_ERROR_DETAIL_SENTINEL",
            "created_at": NOW,
            "completed_at": NOW + 1,
            "provider": "PRIVATE_PROVIDER_SENTINEL",
            "base_url": "PRIVATE_BASE_URL_SENTINEL",
            "api_key": "PRIVATE_API_KEY_SENTINEL",
            "raw": "PRIVATE_RAW_RESPONSE_SENTINEL",
            "error_detail": "PRIVATE_ERROR_DETAIL_SENTINEL",
        }

    async def get(self, project_id, analysis_id):
        self.calls.append(("get", project_id, analysis_id))
        return await self.analyze(None)


def _client():
    from backend.domain.routers import market_sources
    from backend.security.redaction import install_error_handlers

    service = FakeService()
    analysis_service = FakeAnalysisService()
    app = FastAPI()
    app.include_router(market_sources.router, prefix="/api")
    app.dependency_overrides[market_sources.get_market_source_service] = lambda: service
    dependency = getattr(market_sources, "get_market_analysis_service", None)
    if dependency is not None:
        app.dependency_overrides[dependency] = lambda: analysis_service
    install_error_handlers(app)
    return (
        TestClient(app, raise_server_exceptions=False),
        service,
        analysis_service,
        market_sources,
    )


def test_market_service_builds_candidate_adapters_from_the_central_registry(monkeypatch):
    from backend.domain.routers import market_sources

    called = []
    adapters = {"qimao_public_rank": object()}

    def build(transport):
        called.append(transport)
        return adapters

    monkeypatch.setattr(market_sources, "build_market_adapters", build)

    service = market_sources.get_market_source_service()

    assert called
    assert service.snapshot_service.adapters == adapters
    assert "qidian_public_rank" not in service.snapshot_service.adapters


def test_market_source_routes_expose_only_inventory_status_history_detail_and_commands():
    client, service, _, market_sources = _client()
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
        "canManualImport",
        "canRefresh",
        "canSchedule",
        "refreshStatus",
        "lastAttemptedAt",
        "lastSucceededAt",
        "lastSnapshotId",
        "publicErrorCode",
    }
    assert source["canManualImport"] is True
    assert source["canRefresh"] is False
    assert source["canSchedule"] is False
    assert responses[1].json() == source
    rendered_sources = json.dumps(
        [responses[0].json(), responses[1].json()],
        ensure_ascii=False,
    )
    for sentinel in (
        "CONFIG_SENTINEL",
        "URL_SENTINEL",
        "ERROR_SENTINEL",
        "RAW_SENTINEL",
    ):
        assert sentinel not in rendered_sources
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
    client, _, _, _ = _client()

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
    client, service, _, _ = _client()
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


def test_manual_import_rejects_oversized_malformed_and_deep_raw_json_stably():
    from backend.gateways.market_sources.manual_snapshot import (
        MAX_MANUAL_SNAPSHOT_BYTES,
    )

    client, service, _, _ = _client()
    sentinel = "PRIVATE_MANUAL_BODY_SENTINEL"
    oversized = (
        b'{"idempotencyKey":"'
        + b"m" * 64
        + b'","snapshot":{"padding":"'
        + b"x" * MAX_MANUAL_SNAPSHOT_BYTES
        + b'"}}'
    )
    malformed = (
        '{"idempotencyKey":"'
        + "m" * 64
        + '","snapshot":{"private":"'
        + sentinel
    ).encode()
    deep = (
        '{"idempotencyKey":"'
        + "m" * 64
        + '","snapshot":'
        + "[" * 300
        + "0"
        + "]" * 300
        + "}"
    ).encode()

    responses = (
        client.post(
            f"/api/market-sources/{SOURCE_ID}/manual-import",
            content=oversized,
            headers={
                "content-type": "application/json",
                "content-length": str(len(oversized)),
            },
        ),
        client.post(
            f"/api/market-sources/{SOURCE_ID}/manual-import",
            content=malformed,
            headers={"content-type": "application/json"},
        ),
        client.post(
            f"/api/market-sources/{SOURCE_ID}/manual-import",
            content=deep,
            headers={"content-type": "application/json"},
        ),
    )

    assert [response.status_code for response in responses] == [422, 422, 422]
    assert [response.json()["code"] for response in responses] == [
        "MARKET_MANUAL_BODY_TOO_LARGE",
        "MARKET_MANUAL_SNAPSHOT_INVALID",
        "MARKET_MANUAL_SNAPSHOT_INVALID",
    ]
    assert sentinel not in json.dumps(
        [response.json() for response in responses]
    )
    assert service.calls == []


@pytest.mark.asyncio
async def test_manual_body_reader_checks_length_before_receive_and_stops_at_limit():
    from backend.gateways.market_sources.manual_snapshot import (
        MAX_MANUAL_SNAPSHOT_BYTES,
    )
    from backend.domain.routers.market_sources import _read_manual_body
    from backend.domain.market_sources import MarketSourceFailure

    calls = {"count": 0}

    async def forbidden_receive():
        calls["count"] += 1
        raise AssertionError("declared oversized body must not be read")

    declared = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [
                (
                    b"content-length",
                    str(MAX_MANUAL_SNAPSHOT_BYTES + 1).encode(),
                )
            ],
        },
        forbidden_receive,
    )
    with pytest.raises(MarketSourceFailure) as oversized:
        await _read_manual_body(declared)
    assert oversized.value.code == "MARKET_MANUAL_BODY_TOO_LARGE"
    assert calls["count"] == 0

    messages = iter(
        (
            {
                "type": "http.request",
                "body": b"x" * MAX_MANUAL_SNAPSHOT_BYTES,
                "more_body": True,
            },
            {
                "type": "http.request",
                "body": b"yz",
                "more_body": True,
            },
            {
                "type": "http.request",
                "body": b"PRIVATE_UNREAD_SENTINEL",
                "more_body": False,
            },
        )
    )
    stream_calls = {"count": 0}

    async def receive():
        stream_calls["count"] += 1
        return next(messages)

    streamed = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [],
        },
        receive,
    )
    with pytest.raises(MarketSourceFailure) as streamed_oversized:
        await _read_manual_body(streamed)
    assert streamed_oversized.value.code == "MARKET_MANUAL_BODY_TOO_LARGE"
    assert stream_calls["count"] == 2


def test_refresh_rejects_raw_url_and_policy_overrides_without_echo(
    caplog,
):
    client, service, _, _ = _client()
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
    client, service, _, _ = _client()

    async def summary_only(source_id, idempotency_key):
        value = _snapshot()
        value.pop("entries")
        return value

    service.refresh = summary_only

    response = client.post(
        f"/api/market-sources/{SOURCE_ID}/refresh",
        json={"idempotencyKey": "r" * 64},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "MARKET_REFRESH_FAILED"
    assert "entries" not in response.json()


def test_schedule_route_is_retired():
    client, _, _, _ = _client()
    response = client.put(
        f"/api/market-sources/{SOURCE_ID}/schedule",
        json={
            "expectedRevision": 3,
            "enabled": True,
            "intervalMinutes": 360,
            "idempotencyKey": "s" * 64,
        },
    )

    assert response.status_code == 404


def test_project_bound_market_analysis_routes_are_retired():
    client, _, analysis_service, _ = _client()

    created = client.post(
        f"/api/projects/{PROJECT_ID}/market-analyses",
        json={
            "snapshotIds": [SNAPSHOT_ID],
            "idempotencyKey": "a" * 64,
        },
    )
    loaded = client.get(
        f"/api/projects/{PROJECT_ID}/market-analyses/{ANALYSIS_ID}"
    )

    assert created.status_code == loaded.status_code == 404
    assert analysis_service.calls == []


def test_market_analysis_request_rejects_duplicates_bounds_and_extra_fields():
    client, _, analysis_service, _ = _client()
    responses = (
        client.post(
            f"/api/projects/{PROJECT_ID}/market-analyses",
            json={
                "snapshotIds": [SNAPSHOT_ID, SNAPSHOT_ID],
                "idempotencyKey": "a" * 64,
            },
        ),
        client.post(
            f"/api/projects/{PROJECT_ID}/market-analyses",
            json={
                "snapshotIds": [
                    f"00000000-0000-0000-0000-{index:012d}"
                    for index in range(1, 6)
                ],
                "idempotencyKey": "a" * 64,
            },
        ),
        client.post(
            f"/api/projects/{PROJECT_ID}/market-analyses",
            json={
                "snapshotIds": [SNAPSHOT_ID],
                "idempotencyKey": "a" * 64,
                "providerId": "PRIVATE_BROWSER_PROVIDER",
            },
        ),
    )
    assert [response.status_code for response in responses] == [404, 404, 404]
    assert "PRIVATE_BROWSER_PROVIDER" not in json.dumps(
        [response.json() for response in responses]
    )
    assert analysis_service.calls == []


@pytest.mark.parametrize(
    ("code", "status"),
    (
        ("MARKET_MANUAL_SNAPSHOT_INVALID", 422),
        ("MARKET_SOURCE_NOT_FOUND", 404),
        ("MARKET_SOURCE_CONFLICT", 409),
        ("MARKET_REFRESH_IN_PROGRESS", 409),
        ("MARKET_REFRESH_COOLDOWN", 429),
        ("MARKET_HTML_UNKNOWN", 502),
        ("MARKET_TRANSPORT_FAILED", 503),
        ("MARKET_TRANSPORT_TIMEOUT", 503),
    ),
)
def test_market_failures_have_stable_semantic_http_status_without_exception_text(
    code,
    status,
):
    from backend.domain.market_sources import MarketSourceFailure
    from backend.security.redaction import install_error_handlers

    failure = MarketSourceFailure(code)
    app = FastAPI()

    @app.get("/failure")
    async def fail():
        raise failure

    install_error_handlers(app)
    response = TestClient(app, raise_server_exceptions=False).get("/failure")

    assert response.status_code == status
    assert set(response.json()) == {"code", "message", "correlationId"}
    assert response.json()["code"] == code
    assert response.json()["message"] == failure.message
    assert repr(failure) not in json.dumps(response.json())


def test_main_registers_new_routes_and_has_no_old_market_scrape_route():
    from backend import main

    paths = {route.path for route in main.app.routes}
    assert "/api/market-sources" in paths
    assert "/api/market-sources/{source_id}/manual-import" in paths
    assert "/api/market/scrape" not in paths
