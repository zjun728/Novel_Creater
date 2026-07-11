from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import canon


@pytest.fixture
def canon_api(monkeypatch):
    state = {
        "head": {
            "canon_revision_number": 2,
            "projection_revision_number": 2,
            "content_hash": "a" * 64,
        }
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
            return [{"id": "event-1", "value_json": '{"alive":true}'}]
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
            return [{"payload_json": '{"value":1}', "revision_number": 2}]
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
        "schemaVersion": "writer-core-v1.0.0",
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
