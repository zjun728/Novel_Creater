from __future__ import annotations

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.http_errors import (
    ProjectArchived,
    ProjectBusy,
    ProjectLifecycleConflict,
    ProjectNotFound,
    SeedConflict,
    SeedLocked,
    SeedNotFound,
)
from backend.security.redaction import install_error_handlers


SECRET = "sk-domain-error-sentinel"
PRIVATE_URL = "https://domain-private.example/v1"
PRIVATE_SQL = "SELECT api_key FROM providers WHERE id='private-provider'"


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ProjectNotFound(), 404, "ProjectNotFound"),
        (ProjectArchived(), 409, "ProjectArchived"),
        (
            ProjectLifecycleConflict(),
            409,
            "ProjectLifecycleConflict",
        ),
        (ProjectBusy(), 409, "ProjectBusy"),
        (SeedNotFound(), 404, "SeedNotFound"),
        (SeedConflict(), 409, "SeedConflict"),
        (SeedLocked(), 423, "SeedLocked"),
    ],
)
def test_public_domain_errors_have_exact_safe_shape(error, status, code, caplog):
    app = FastAPI()

    @app.get("/failure")
    async def failure():
        error.debug_context = f"{SECRET} {PRIVATE_URL} {PRIVATE_SQL}"
        logging.getLogger("untrusted").error(
            "%s %s %s", SECRET, PRIVATE_URL, PRIVATE_SQL
        )
        raise error

    install_error_handlers(app)
    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.WARNING, logger="backend"):
        response = client.get("/failure")

    assert response.status_code == status
    body = response.json()
    assert set(body) == {"code", "message", "correlationId"}
    assert body["code"] == code
    assert body["message"] == error.message
    assert body["correlationId"]
    rendered = json.dumps(body)
    assert SECRET not in rendered
    assert PRIVATE_URL not in rendered
    assert PRIVATE_SQL not in rendered
    assert repr(error) not in rendered
    assert type(error).__name__ in caplog.text
