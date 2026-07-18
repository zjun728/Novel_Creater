from __future__ import annotations

import json
from hashlib import sha256
import logging
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from backend.gateways.story_engine_provider import StoryEngineProviderGateway
from backend.routers import providers, story_engines
from backend.security.redaction import SecretRedactionFilter, install_error_handlers
from backend.tests.support.story_engine_fakes import StoryEngineHarness, three_options


SECRET = "sk-validation-and-error-sentinel"
PRIVATE_URL = "https://error-private.example/v1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


uvicorn_test_app = FastAPI()
install_error_handlers(uvicorn_test_app)


@uvicorn_test_app.get("/health")
async def _uvicorn_test_health():
    return {"status": "ok"}


@uvicorn_test_app.get("/failure")
async def _uvicorn_test_failure():
    raise RuntimeError(f"upstream failed {SECRET} {PRIVATE_URL}")


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
    class FailingProviderService:
        async def list_profiles(self):
            raise RuntimeError(f"upstream failed {SECRET} {PRIVATE_URL}")

    app = FastAPI()
    app.include_router(providers.router, prefix="/api")
    app.dependency_overrides[
        providers.get_provider_profile_service
    ] = FailingProviderService
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


def test_error_handler_installation_filters_uvicorn_error_once():
    uvicorn_logger = logging.getLogger("uvicorn.error")
    original_filters = list(uvicorn_logger.filters)
    for item in original_filters:
        if isinstance(item, SecretRedactionFilter):
            uvicorn_logger.removeFilter(item)

    try:
        install_error_handlers(FastAPI())
        install_error_handlers(FastAPI())

        installed = [
            item
            for item in uvicorn_logger.filters
            if isinstance(item, SecretRedactionFilter)
        ]
        assert len(installed) == 1
    finally:
        for item in list(uvicorn_logger.filters):
            if isinstance(item, SecretRedactionFilter):
                uvicorn_logger.removeFilter(item)
        for item in original_filters:
            if isinstance(item, SecretRedactionFilter):
                uvicorn_logger.addFilter(item)


def test_story_engine_provider_failure_redacts_connection_and_raw_response(caplog):
    harness = StoryEngineHarness()
    harness.repository.providers["provider-seed"].update(
        api_key=SECRET,
        base_url=PRIVATE_URL,
    )
    harness.service.provider_gateway = StoryEngineProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                503,
                text=f"RAW_RESPONSE_SENTINEL {SECRET} {PRIVATE_URL}",
                request=request,
            )
        )
    )
    app = FastAPI()
    app.include_router(story_engines.router, prefix="/api")
    app.dependency_overrides[
        story_engines.get_story_engine_service
    ] = lambda: harness.service
    install_error_handlers(app)
    client = TestClient(app, raise_server_exceptions=False)

    with caplog.at_level(logging.ERROR):
        response = client.post(
            "/api/projects/p1/story-engine-batches",
            json={"idempotencyKey": "safe-failure"},
        )

    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["publicErrorCode"] == "provider_failed"
    rendered = response.text + caplog.text
    assert all(
        sentinel not in rendered
        for sentinel in (SECRET, PRIVATE_URL, "RAW_RESPONSE_SENTINEL")
    )


def test_story_engine_success_envelope_echoing_secret_is_rejected_before_api_output(
    caplog,
):
    harness = StoryEngineHarness()
    harness.repository.providers["provider-seed"].update(
        api_key=SECRET,
        base_url=PRIVATE_URL,
    )
    options = [item.model_dump(mode="json") for item in three_options()]
    options[1]["ensembleRoles"][0]["purpose"] = f"嵌套回显 {SECRET}"
    raw_content = json.dumps({"options": options}, ensure_ascii=False)
    harness.service.provider_gateway = StoryEngineProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"content": raw_content}}]},
                request=request,
            )
        )
    )
    app = FastAPI()
    app.include_router(story_engines.router, prefix="/api")
    app.dependency_overrides[
        story_engines.get_story_engine_service
    ] = lambda: harness.service
    install_error_handlers(app)
    client = TestClient(app, raise_server_exceptions=False)

    with caplog.at_level(logging.ERROR):
        response = client.post(
            "/api/projects/p1/story-engine-batches",
            json={"idempotencyKey": "safe-success-echo"},
        )

    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["publicErrorCode"] == "invalid_response"
    assert response.json()["options"] == []
    stored = next(iter(harness.repository.batches.values()))
    assert stored["raw_response_text"] is None
    assert stored["raw_response_hash"] is not None
    rendered = response.text + caplog.text + json.dumps(stored, default=str)
    assert SECRET not in rendered
    assert PRIVATE_URL not in rendered


@pytest.mark.parametrize(
    ("secret_field", "escape_mode"),
    (("api_key", "full"), ("base_url", "mixed")),
)
def test_story_engine_unicode_escaped_connection_secret_never_reaches_api_or_options(
    caplog,
    secret_field,
    escape_mode,
):
    harness = StoryEngineHarness()
    harness.repository.providers["provider-seed"].update(
        api_key=SECRET,
        base_url=PRIVATE_URL,
    )
    secret = harness.repository.providers["provider-seed"][secret_field]
    options = [item.model_dump(mode="json") for item in three_options()]
    options[1]["ensembleRoles"][0]["purpose"] = f"嵌套回显 {secret}"
    raw_content = json.dumps({"options": options}, ensure_ascii=False)
    if escape_mode == "full":
        escaped = "".join(f"\\u{ord(character):04x}" for character in secret)
    else:
        escaped = "".join(
            f"\\u{ord(character):04x}" if index % 2 == 0 else character
            for index, character in enumerate(secret)
        )
    raw_content = raw_content.replace(secret, escaped)
    assert secret not in raw_content
    harness.service.provider_gateway = StoryEngineProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"content": raw_content}}]},
                request=request,
            )
        )
    )
    app = FastAPI()
    app.include_router(story_engines.router, prefix="/api")
    app.dependency_overrides[
        story_engines.get_story_engine_service
    ] = lambda: harness.service
    install_error_handlers(app)
    client = TestClient(app, raise_server_exceptions=False)

    with caplog.at_level(logging.ERROR):
        response = client.post(
            "/api/projects/p1/story-engine-batches",
            json={"idempotencyKey": f"unicode-{secret_field}-{escape_mode}"},
        )

    stored = next(iter(harness.repository.batches.values()))
    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["publicErrorCode"] == "invalid_response"
    assert response.json()["options"] == []
    assert stored["raw_response_text"] is None
    assert stored["raw_response_hash"] == sha256(
        raw_content.encode("utf-8")
    ).hexdigest()
    assert harness.repository.options[stored["id"]] == []
    rendered = response.text + caplog.text + json.dumps(stored, default=str)
    assert SECRET not in rendered
    assert PRIVATE_URL not in rendered


def test_story_engine_decoding_failure_finishes_batch_without_secret_leak(caplog):
    harness = StoryEngineHarness()
    harness.repository.providers["provider-seed"].update(
        api_key=SECRET,
        base_url=PRIVATE_URL,
    )
    harness.service.provider_gateway = StoryEngineProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"Content-Encoding": "gzip"},
                content=f"RAW_RESPONSE_SENTINEL {SECRET}".encode(),
                request=request,
            )
        )
    )
    app = FastAPI()
    app.include_router(story_engines.router, prefix="/api")
    app.dependency_overrides[
        story_engines.get_story_engine_service
    ] = lambda: harness.service
    install_error_handlers(app)
    client = TestClient(app, raise_server_exceptions=False)

    with caplog.at_level(logging.ERROR):
        response = client.post(
            "/api/projects/p1/story-engine-batches",
            json={"idempotencyKey": "safe-decoding-failure"},
        )

    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["publicErrorCode"] == "provider_failed"
    stored = next(iter(harness.repository.batches.values()))
    assert stored["status"] == "failed"
    assert stored["raw_response_text"] is None
    assert stored["raw_response_hash"] is None
    rendered = response.text + caplog.text
    assert all(
        sentinel not in rendered
        for sentinel in (SECRET, PRIVATE_URL, "RAW_RESPONSE_SENTINEL")
    )


def test_real_uvicorn_logs_never_render_unexpected_error_secrets():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.tests.api.test_secret_error_redaction:uvicorn_test_app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "error",
            "--no-access-log",
        ],
        cwd=REPOSITORY_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stdout = ""
    stderr = ""
    try:
        deadline = time.monotonic() + 10
        while True:
            if process.poll() is not None:
                raise AssertionError("Uvicorn exited before the health route was ready")
            try:
                with urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=0.25
                ) as response:
                    if response.status == 200:
                        break
            except (OSError, URLError):
                pass
            if time.monotonic() >= deadline:
                raise AssertionError("Uvicorn health route did not become ready")
            time.sleep(0.05)

        try:
            urlopen(f"http://127.0.0.1:{port}/failure", timeout=2)
            raise AssertionError("Failure route unexpectedly returned success")
        except HTTPError as exc:
            status = exc.code
            body = json.loads(exc.read().decode("utf-8"))
    finally:
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)

    assert status == 500
    assert body["message"] == "Internal server error"
    assert body["correlationId"]
    rendered_body = json.dumps(body, ensure_ascii=False)
    captured_logs = stdout + stderr
    assert SECRET not in rendered_body and PRIVATE_URL not in rendered_body
    assert SECRET not in captured_logs and PRIVATE_URL not in captured_logs
