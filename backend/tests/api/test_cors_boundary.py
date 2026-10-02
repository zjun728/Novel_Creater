"""Browser read permission; these checks deliberately do not imply authentication."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from backend import config, main
from backend.domain.routers import projects


@pytest.fixture(autouse=True)
def project_list_without_database(monkeypatch):
    async def list_active():
        return []

    monkeypatch.setattr(projects, "_service", SimpleNamespace(list_active=list_active))


def assert_allowed(client, origin):
    response = client.get("/api/projects", headers={"Origin": origin})
    assert response.status_code == 200
    assert response.json() == []
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "Origin" in response.headers["vary"]
    response = client.options("/api/projects", headers={
        "Origin": origin, "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "content-type",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def assert_disallowed(client, origin):
    response = client.get("/api/projects", headers={"Origin": origin})
    assert response.status_code == 200  # CORS must not be presented as authentication.
    assert "access-control-allow-origin" not in response.headers
    response = client.options("/api/projects", headers={
        "Origin": origin, "Access-Control-Request-Method": "GET",
    })
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("origin", [
    "http://localhost:5173", "http://127.0.0.1:5173",
])
def test_default_frontend_get_and_preflight(origin):
    assert_allowed(TestClient(main.app), origin)


@pytest.mark.parametrize("origin", [
    "http://localhost:49199", "http://127.0.0.1:49199",
    "https://example.com", "http://localhost.evil.example:5173",
    "http://127.0.0.1.evil.example:5173", "http://localhost:5173@evil.example",
    "https://localhost:5173", "null",
])
def test_unconfigured_origins_cannot_read_across_origins(origin):
    assert_disallowed(TestClient(main.app), origin)


def test_same_origin_and_non_browser_requests_keep_working():
    client = TestClient(main.app)
    response = client.get("/api/projects")
    assert response.status_code == 200
    assert response.json() == []
    assert "access-control-allow-origin" not in response.headers
    # A same-origin browser response needs no CORS read permission.
    assert client.get("/api/projects", headers={"Origin": "http://testserver"}).status_code == 200


def test_explicit_isolated_frontend_replaces_defaults():
    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    app.add_middleware(CORSMiddleware,
        allow_origins=config.load_cors_allowed_origins(environment={
            "CORS_ALLOWED_ORIGINS": "http://127.0.0.1:15273,http://localhost:15273",
        }), allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
    )
    client = TestClient(app)
    assert_allowed(client, "http://127.0.0.1:15273")
    assert_allowed(client, "http://localhost:15273")
    assert_disallowed(client, "http://127.0.0.1:5173")
    assert_disallowed(client, "http://localhost:49199")


def test_cors_empty_configuration_allows_same_origin_only():
    assert config.load_cors_allowed_origins(environment={"CORS_ALLOWED_ORIGINS": ""}) == ()


def test_cors_defaults_and_explicit_deduplication():
    assert config.load_cors_allowed_origins(environment={}) == (
        "http://localhost:5173", "http://127.0.0.1:5173",
    )
    assert config.load_cors_allowed_origins(environment={
        "CORS_ALLOWED_ORIGINS": " https://localhost:5173 , https://localhost:5173 ",
    }) == ("https://localhost:5173",)


@pytest.mark.parametrize("value", [
    "*", "null", "http://localhost:*", "http://localhost:0", "http://localhost:65536",
    "ftp://localhost:5173", "http://localhost:5173/", "http://localhost:5173/path",
    "http://localhost:5173?", "http://localhost:5173#", "http://user@localhost:5173",
    "http://localhost:5173,", "http://local host:5173", "http://localhost\n:5173",
    "https://frontend.example", "http://localhost.evil.example:5173",
    "http://127.0.0.1.evil.example:5173", "http://localhost:",
])
def test_invalid_cors_configuration_fails_closed(value):
    with pytest.raises(config.LocalCorsConfigError, match="CORS_ALLOWED_ORIGINS"):
        config.load_cors_allowed_origins(environment={"CORS_ALLOWED_ORIGINS": value})
