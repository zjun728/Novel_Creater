"""Browser read permission; these checks deliberately do not imply authentication."""

import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from backend import config
# Default-origin checks must not inherit a caller's isolated runner environment.
with patch.dict(os.environ):
    os.environ.pop("CORS_ALLOWED_ORIGINS", None)
    from backend import main
from backend.domain.routers import projects


@pytest.fixture(autouse=True)
def project_list_without_database(monkeypatch):
    async def list_active():
        return []

    monkeypatch.setattr(projects, "_service", SimpleNamespace(list_active=list_active))


@pytest.fixture
def default_client(monkeypatch):
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    # Copy registered production routes, without mutating a possibly cached app
    # or running its database/model lifespan.
    app = FastAPI()
    app.router.routes = main.app.router.routes.copy()
    for middleware in reversed(main.app.user_middleware):
        options = dict(middleware.kwargs)
        if middleware.cls is CORSMiddleware:
            options["allow_origins"] = config.load_cors_allowed_origins()
        app.add_middleware(middleware.cls, **options)
    return TestClient(app)


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
def test_default_frontend_get_and_preflight(origin, default_client):
    assert_allowed(default_client, origin)


@pytest.mark.parametrize("origin", [
    "http://localhost:49199", "http://127.0.0.1:49199",
    "https://example.com", "http://localhost.evil.example:5173",
    "http://127.0.0.1.evil.example:5173", "http://localhost:5173@evil.example",
    "https://localhost:5173", "null",
])
def test_unconfigured_origins_cannot_read_across_origins(origin, default_client):
    assert_disallowed(default_client, origin)


def test_same_origin_and_non_browser_requests_keep_working(default_client):
    client = default_client
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


@pytest.mark.parametrize("configured,canonical", [
    ("http://LOCALHOST:5173", "http://localhost:5173"),
    ("http://localhost:80", "http://localhost"),
    ("https://localhost:443", "https://localhost"),
    ("http://127.0.0.1:05173", "http://127.0.0.1:5173"),
    ("http://[::1]:80", "http://[::1]"),
    ("https://[::1]:00443", "https://[::1]"),
    ("http://[::1]:05173", "http://[::1]:5173"),
    ("https://LOCALHOST:00080", "https://localhost:80"),
    ("http://127.0.0.1", "http://127.0.0.1"),
    ("https://127.0.0.1:65535", "https://127.0.0.1:65535"),
])
def test_browser_serialized_origin_get_and_authorized_json_preflight(configured, canonical):
    origins = config.load_cors_allowed_origins(environment={"CORS_ALLOWED_ORIGINS": configured})
    assert origins == (canonical,)
    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    app.add_middleware(CORSMiddleware, allow_origins=origins,
        allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    client = TestClient(app)
    assert_allowed(client, canonical)
    response = client.options("/api/projects", headers={
        "Origin": canonical, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == canonical
    assert "POST" in response.headers["access-control-allow-methods"]
    assert response.headers["access-control-allow-headers"] == "authorization,content-type"
    assert_disallowed(client, "http://localhost:49199")


def test_deduplicate_after_browser_origin_normalization():
    assert config.load_cors_allowed_origins(environment={"CORS_ALLOWED_ORIGINS":
        "http://LOCALHOST:00080,http://localhost,http://localhost:80,"
        "https://[::1]:443,https://[::1],http://127.0.0.1:05173,http://127.0.0.1:5173"
    }) == ("http://localhost", "https://[::1]", "http://127.0.0.1:5173")


def test_invalid_origin_prevents_application_creation():
    result = subprocess.run([sys.executable, "-c", "import backend.main"],
        env={**os.environ, "CORS_ALLOWED_ORIGINS": "http://localhost.evil.example:5173"},
        capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode != 0
    assert "LocalCorsConfigError" in result.stderr
    assert "localhost.evil.example" not in result.stderr


@pytest.mark.parametrize("value", [
    "*", "null", "http://localhost:*", "http://localhost:0", "http://localhost:65536",
    "ftp://localhost:5173", "http://localhost:5173/", "http://localhost:5173/path",
    "http://localhost:5173?", "http://localhost:5173#", "http://user@localhost:5173",
    "http://localhost:5173,", "http://local host:5173", "http://localhost\n:5173",
    "https://frontend.example", "http://localhost.evil.example:5173",
    "http://127.0.0.1.evil.example:5173", "http://localhost:",
    "http://[::1]evil", "http://[::1]:80.evil", "http://[::1]\\evil",
    "http://localhost\\evil", "http://localhost:５１７３", "http://[::1]:",
    "http://[::ffff:127.0.0.1]:5173", "http://[0:0:0:0:0:0:0:1]:5173",
    "http://127.1:5173", "http://2130706433:5173", "http://localhost.:5173",
    "http://%6cocalhost:5173", "http://127.0.0.1:0", "http://[::1]:65536",
])
def test_invalid_cors_configuration_fails_closed(value):
    with pytest.raises(config.LocalCorsConfigError, match="CORS_ALLOWED_ORIGINS"):
        config.load_cors_allowed_origins(environment={"CORS_ALLOWED_ORIGINS": value})
