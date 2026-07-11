from __future__ import annotations

import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import providers
from backend.security.redaction import SecretRedactionFilter, install_error_handlers


SECRET = "sk-validation-and-error-sentinel"
PRIVATE_URL = "https://error-private.example/v1"


def test_request_validation_error_sanitizes_pydantic_input(caplog):
    app = FastAPI()
    app.include_router(providers.router, prefix="/api")
    install_error_handlers(app)
    client = TestClient(app, raise_server_exceptions=False)

    with caplog.at_level(logging.ERROR):
        response = client.post(
            "/api/providers",
            json={
                "name": "invalid",
                "apiKey": {"token": SECRET},
                "baseURL": {"value": PRIVATE_URL},
            },
        )

    assert response.status_code == 422
    rendered = json.dumps(response.json(), ensure_ascii=False)
    assert SECRET not in rendered and PRIVATE_URL not in rendered
    assert SECRET not in caplog.text and PRIVATE_URL not in caplog.text


def test_unexpected_error_returns_only_generic_message_and_correlation_id(
    monkeypatch, caplog
):
    async def fail(*args, **kwargs):
        raise RuntimeError(f"upstream failed {SECRET} {PRIVATE_URL}")

    monkeypatch.setattr(providers, "fetchall", fail)
    app = FastAPI()
    app.include_router(providers.router, prefix="/api")
    install_error_handlers(app)
    client = TestClient(app, raise_server_exceptions=False)

    with caplog.at_level(logging.ERROR, logger="backend"):
        response = client.get("/api/providers")

    assert response.status_code == 500
    assert response.json()["message"] == "Internal server error"
    assert response.json()["correlationId"]
    rendered = json.dumps(response.json(), ensure_ascii=False)
    assert SECRET not in rendered and PRIVATE_URL not in rendered
    assert SECRET not in caplog.text and PRIVATE_URL not in caplog.text
    assert "RuntimeError" in caplog.text


def test_logging_filter_recursively_redacts_structured_arguments():
    record = logging.LogRecord(
        "backend",
        logging.ERROR,
        __file__,
        1,
        "failed payload=%s",
        ({"nested": {"Authorization": SECRET}, "base_url": PRIVATE_URL},),
        None,
    )
    assert SecretRedactionFilter().filter(record)
    rendered = record.getMessage()
    assert SECRET not in rendered and PRIVATE_URL not in rendered
    assert rendered.count("[REDACTED]") == 2
