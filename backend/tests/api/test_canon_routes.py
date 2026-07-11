from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import canon
from backend.schema_version import EXPECTED_SCHEMA_VERSION


@pytest.fixture
def canon_api(monkeypatch):
    state = {
        "head": {
            "canon_revision_number": 2,
            "projection_revision_number": 2,
            "content_hash": "a" * 64,
        },
        "json_mode": "encoded",
    }

    async def fetchone(sql, args=None):
        if "FROM projection_heads" in sql:
            return dict(state["head"])
        if "FROM canon_entities" in sql:
            return {
                "id": args[1],
                "project_id": args[0],
                "entity_type": "person",
                "canonical_name": "甲",
            }
        raise AssertionError(sql)

    async def fetchall(sql, args=None):
        if "FROM canon_revisions" in sql:
            return [{"revision_number": 2, "content_hash": "a" * 64}]
        if "FROM canon_entities" in sql:
            return [{"id": "entity-1", "canonical_name": "甲"}]
        if "FROM canon_events" in sql:
            if state["json_mode"] == "native":
                value_json = {"alive": True}
                evidence_json = [{"chapter": 1}]
            elif state["json_mode"] == "invalid":
                value_json = "{not-json"
                evidence_json = "[not-json"
            else:
                value_json = '{"alive":true}'
                evidence_json = '[{"chapter":1}]'
            return [
                {
                    "id": "event-1",
                    "value_json": value_json,
                    "evidence_json": evidence_json,
                }
            ]
        if "FROM entity_aliases" in sql:
            normalized = args[1]
            if normalized == "missing":
                return []
            if normalized == "ambiguous":
                return [
                    {"entity_id": "entity-2", "normalized_alias": normalized},
                    {"entity_id": "entity-1", "normalized_alias": normalized},
                ]
            return [
                {"entity_id": "entity-1", "normalized_alias": normalized}
            ]
        projection_tables = {
            "current_state_projections",
            "memory_views",
            "arc_projections",
            "plot_thread_projections",
        }
        if any(f"FROM {table}" in sql for table in projection_tables):
            if state["json_mode"] == "native":
                payload_json = {"value": 1}
            elif state["json_mode"] == "invalid":
                payload_json = "{not-json"
            else:
                payload_json = '{"value":1}'
            return [{"payload_json": payload_json, "revision_number": 2}]
        raise AssertionError(sql)

    monkeypatch.setattr(canon, "fetchone", fetchone)
    monkeypatch.setattr(canon, "fetchall", fetchall)
    app = FastAPI()
    app.include_router(canon.router, prefix="/api")
    return TestClient(app), app, state


def test_writer_core_state_reports_revision_sync(canon_api):
    client, _, _ = canon_api
    response = client.get("/api/projects/p1/writer-core/state")
    assert response.status_code == 200
    assert response.json() == {
        "projectId": "p1",
        "schemaVersion": EXPECTED_SCHEMA_VERSION,
        "canonHeadRevision": 2,
        "projectionHeadRevision": 2,
        "projectionInSync": True,
    }


def test_canon_and_projection_read_routes_return_current_rows(canon_api):
    client, app, _ = canon_api
    paths = (
        "/api/projects/p1/canon/head",
        "/api/projects/p1/canon/revisions",
        "/api/projects/p1/canon/entities",
        "/api/projects/p1/canon/entities/entity-1",
        "/api/projects/p1/canon/events",
        "/api/projects/p1/projections/head",
        "/api/projects/p1/projections/current-state",
        "/api/projects/p1/projections/memories",
        "/api/projects/p1/projections/arcs",
        "/api/projects/p1/projections/plot-threads",
    )
    assert all(client.get(path).status_code == 200 for path in paths)
    canon_routes = [
        route
        for route in app.routes
        if "/canon/" in route.path or "/projections/" in route.path
    ]
    assert canon_routes
    assert all(route.methods <= {"GET", "HEAD"} for route in canon_routes)


def test_canon_events_and_every_projection_endpoint_decode_json(canon_api):
    client, _, _ = canon_api
    event = client.get("/api/projects/p1/canon/events").json()[0]
    assert event["valueJSON"] == {"alive": True}
    assert event["evidenceJSON"] == [{"chapter": 1}]

    for suffix in ("current-state", "memories", "arcs", "plot-threads"):
        row = client.get(f"/api/projects/p1/projections/{suffix}").json()[0]
        assert row["payloadJSON"] == {"value": 1}


def test_native_and_invalid_json_values_follow_explicit_non_throwing_policy(
    canon_api,
):
    client, _, state = canon_api
    state["json_mode"] = "native"
    native_event = client.get("/api/projects/p1/canon/events")
    native_projection = client.get(
        "/api/projects/p1/projections/current-state"
    )
    assert native_event.status_code == 200
    assert native_event.json()[0]["valueJSON"] == {"alive": True}
    assert native_event.json()[0]["evidenceJSON"] == [{"chapter": 1}]
    assert native_projection.json()[0]["payloadJSON"] == {"value": 1}

    state["json_mode"] = "invalid"
    invalid_event = client.get("/api/projects/p1/canon/events")
    invalid_projection = client.get(
        "/api/projects/p1/projections/current-state"
    )
    assert invalid_event.status_code == 200
    assert invalid_projection.status_code == 200
    assert invalid_event.json()[0]["valueJSON"] == "{not-json"
    assert invalid_event.json()[0]["evidenceJSON"] == "[not-json"
    assert invalid_projection.json()[0]["payloadJSON"] == "{not-json"


def test_projection_data_routes_reject_out_of_sync_heads(canon_api):
    client, _, state = canon_api
    state["head"]["projection_revision_number"] = 1
    for suffix in ("current-state", "memories", "arcs", "plot-threads"):
        response = client.get(f"/api/projects/p1/projections/{suffix}")
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "projection_out_of_sync"
    assert client.get("/api/projects/p1/projections/head").status_code == 200


@pytest.mark.parametrize(
    ("name", "expected"),
    (
        ("missing", {"status": "missing", "entityIds": []}),
        ("resolved", {"status": "resolved", "entityIds": ["entity-1"]}),
        (
            "ambiguous",
            {"status": "ambiguous", "entityIds": ["entity-1", "entity-2"]},
        ),
    ),
)
def test_alias_resolution_returns_product_state_with_http_200(
    canon_api, name, expected
):
    client, _, _ = canon_api
    response = client.get(
        "/api/projects/p1/canon/aliases/resolve", params={"name": name}
    )
    assert response.status_code == 200
    assert response.json() == expected
