from types import MappingProxyType
import asyncio
from concurrent.futures import CancelledError as ThreadCancelledError
from pathlib import Path
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect

from backend.domain.project_import_plans import ProjectImportSummary
from backend.domain.project_imports import (
    ProjectImportInvalid, ProjectImportSensitiveData, ProjectImportTooLarge,
)
from backend.repositories.project_imports import (
    ProjectImportCommandConflict, ProjectImportCommandStateConflict,
    ProjectImportCommandView, ProjectImportPersistenceError,
)
from backend.domain.routers import project_imports
from backend import config as backend_config


COMMAND = "11111111-1111-4111-8111-111111111111"
HASH = "a" * 64
PRIVATE = (
    r"C:\private\package.zip", "internal-row-id", "PRIVATE_PACKAGE_BODY",
    "mysql://root:password@product", "provider-output-secret",
)


@pytest.fixture(autouse=True)
def no_active_runtime_configuration(monkeypatch):
    monkeypatch.setattr(
        backend_config, "_active_runtime_configuration", None, raising=False
    )


def install_runtime_configuration(tmp_path):
    corpus_root = tmp_path / "corpus"
    managed_root = tmp_path / "managed"
    corpus_root.mkdir()
    managed_root.mkdir()
    snapshot = backend_config.RuntimeConfiguration(
        mysql_items=(("host", "runtime-host"), ("port", 3307),
                     ("user", "runtime-user"), ("password", "runtime-password"),
                     ("db", "runtime-db"), ("charset", "utf8mb4"),
                     ("autocommit", True), ("minsize", 1), ("maxsize", 10)),
        corpus_root=corpus_root,
        managed_corpus_root=managed_root,
        market_scheduler_enabled=False,
    )
    backend_config.install_runtime_configuration(snapshot)
    return snapshot


@pytest.mark.asyncio
async def test_production_service_uses_installed_snapshot_root(
    monkeypatch, tmp_path,
):
    snapshot = install_runtime_configuration(tmp_path)
    monkeypatch.setenv("MANAGED_CORPUS_ROOT", str(tmp_path / "later"))
    monkeypatch.setattr(
        backend_config,
        "load_managed_corpus_root",
        lambda *args, **kwargs: pytest.fail("service reread local configuration"),
    )

    service = await project_imports.get_project_import_service()

    assert service._managed_root == snapshot.managed_corpus_root.resolve(strict=True)


@pytest.mark.asyncio
async def test_production_service_requires_active_snapshot():
    with pytest.raises(
        backend_config.RuntimeConfigurationError,
        match="^runtime configuration is unavailable$",
    ) as caught:
        await project_imports.get_project_import_service()

    assert caught.value.args == ("runtime configuration is unavailable",)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


class FakeService:
    def __init__(self):
        self.calls = []
        self.error = None
        self.last_upload = None
        self.command = ProjectImportCommandView(
            COMMAND, "succeeded", "succeeded", False,
            "22222222-2222-4222-8222-222222222222", None,
        )

    async def preflight(self, upload):
        self.last_upload = upload
        self.calls.append(("preflight", await upload.read(7)))
        if self.error:
            raise self.error
        return ProjectImportSummary(
            HASH, "b" * 64, 1, "Source", "Source (Imported)",
            MappingProxyType({"project": 1}), True, 2,
        )

    async def import_project(self, upload, request):
        self.last_upload = upload
        self.calls.append(("import", request, await upload.read(7)))
        if self.error:
            raise self.error
        return self.command

    async def get_command(self, command_id):
        self.calls.append(("get", command_id))
        if self.error:
            raise self.error
        return self.command


def _client(*, raise_server_exceptions=False):
    service = FakeService()
    app = FastAPI()
    app.include_router(project_imports.router, prefix="/api")
    app.dependency_overrides[project_imports.get_project_import_service] = lambda: service
    return TestClient(app, raise_server_exceptions=raise_server_exceptions), service


def _import_data(**changes):
    value = {
        "commandId": COMMAND,
        "idempotencyKey": "same_import_key1",
        "expectedPackageHash": HASH,
        "newTitle": "Imported",
    }
    value.update(changes)
    return value


def _assert_private(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_preflight_and_import_use_exact_multipart_contract_and_private_responses():
    client, service = _client()
    preflight = client.post(
        "/api/project-imports/preflight", files={"file": ("ignored.zip", b"package")},
    )
    imported = client.post(
        "/api/project-imports", data=_import_data(),
        files={"file": ("ignored.zip", b"package")},
    )
    assert preflight.status_code == imported.status_code == 200
    assert set(preflight.json()) == {
        "packageHash", "manifestHash", "packageVersion", "sourceTitle",
        "proposedTitle", "counts", "hasFinalizedChapters", "providerHistoryCount",
    }
    assert imported.json()["targetProjectId"] == "22222222-2222-4222-8222-222222222222"
    assert [call[0] for call in service.calls] == ["preflight", "import"]
    assert service.calls[0][1] == service.calls[1][2] == b"package"
    _assert_private(preflight)
    _assert_private(imported)


@pytest.mark.parametrize("data", [
    {},
    _import_data(commandId="{11111111-1111-4111-8111-111111111111}"),
    _import_data(idempotencyKey="UPPER_NOT_ALLOWED1"),
    _import_data(expectedPackageHash="A" * 64),
    _import_data(newTitle=" Imported"),
    _import_data(extra="PRIVATE_PACKAGE_BODY"),
])
def test_import_rejects_missing_invalid_or_extra_fields_without_service_call(data):
    client, service = _client()
    response = client.post(
        "/api/project-imports", data=data,
        files={"file": ("ignored.zip", b"PRIVATE_PACKAGE_BODY")},
    )
    assert response.status_code == 422
    assert service.calls == []
    assert "PRIVATE_PACKAGE_BODY" not in response.text
    _assert_private(response)


def test_preflight_rejects_duplicate_or_extra_parts_without_service_call():
    client, service = _client()
    response = client.post("/api/project-imports/preflight", files=[
        ("file", ("one.zip", b"one")),
        ("file", ("two.zip", b"two")),
    ])
    extra = client.post(
        "/api/project-imports/preflight", data={"extra": "secret"},
        files={"file": ("one.zip", b"one")},
    )
    assert response.status_code == extra.status_code == 422
    assert service.calls == []
    _assert_private(response)


@pytest.mark.parametrize(("error", "status", "code"), [
    (ProjectImportInvalid("secret"), 422, "ProjectImportInvalid"),
    (ProjectImportTooLarge("secret"), 413, "ProjectImportTooLarge"),
    (ProjectImportSensitiveData("secret"), 422, "ProjectImportSensitiveData"),
    (ProjectImportCommandConflict(), 409, "ProjectImportConflict"),
    (ProjectImportCommandStateConflict(), 409, "ProjectImportConflict"),
    (ProjectImportPersistenceError(), 500, "ProjectImportIntegrity"),
    (RuntimeError("secret"), 500, "ProjectImportIntegrity"),
])
def test_import_errors_are_fixed_and_never_echo_private_evidence(error, status, code):
    client, service = _client()
    service.error = error
    response = client.post(
        "/api/project-imports", data=_import_data(),
        files={"file": (PRIVATE[0], PRIVATE[2].encode())},
    )
    assert response.status_code == status
    assert set(response.json()) == {"code", "message", "correlationId"}
    assert response.json()["code"] == code
    rendered = response.text + json.dumps(dict(response.headers))
    assert all(value not in rendered for value in PRIVATE)
    _assert_private(response)


@pytest.mark.parametrize(("view", "expected"), [
    (ProjectImportCommandView(COMMAND, "running", "staged", False, None, None),
     ("running", False, None, None)),
    (ProjectImportCommandView(COMMAND, "running", "staged", True, None, None),
     ("running", True, None, None)),
    (ProjectImportCommandView(COMMAND, "failed", "failed", False, None, "PROJECT_IMPORT_FAILED"),
     ("failed", False, None, "PROJECT_IMPORT_FAILED")),
])
def test_get_exposes_only_closed_running_retry_and_failed_views(view, expected):
    client, service = _client()
    service.command = view
    response = client.get(f"/api/project-imports/{COMMAND}")
    body = response.json()
    assert (body["status"], body["retryRequired"], body["targetProjectId"], body["publicErrorCode"]) == expected
    assert set(body) == {
        "commandId", "status", "phase", "retryRequired", "targetProjectId", "publicErrorCode",
    }
    _assert_private(response)


def test_get_strict_uuid_is_zero_service_and_unknown_is_fixed_not_found():
    client, service = _client()
    malformed = client.get("/api/project-imports/not-a-uuid")
    assert malformed.status_code == 422 and service.calls == []
    service.error = ProjectImportCommandStateConflict()
    missing = client.get(f"/api/project-imports/{COMMAND}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "ProjectImportNotFound"
    _assert_private(malformed)
    _assert_private(missing)


def test_cancelled_error_remains_primary_and_multipart_upload_is_closed():
    client, service = _client(raise_server_exceptions=True)
    service.error = asyncio.CancelledError()
    with pytest.raises((asyncio.CancelledError, ThreadCancelledError)):
        client.post(
            "/api/project-imports", data=_import_data(),
            files={"file": ("ignored.zip", b"package")},
        )
    assert service.last_upload is not None
    assert service.last_upload.file.closed


def test_router_never_reads_upload_body_itself_without_service_chunk_policy():
    source = Path(project_imports.__file__).read_text(encoding="utf-8")
    assert "await upload.read(" not in source
    assert "await request.body(" not in source


def _multipart(parts, boundary="task7-boundary"):
    body = bytearray()
    for name, value, filename in parts:
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"".encode())
        if filename is not None:
            body.extend(f"; filename=\"{filename}\"".encode())
        body.extend(b"\r\n\r\n")
        body.extend(value)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return bytes(body), f"multipart/form-data; boundary={boundary}"


class _StreamingRequest:
    def __init__(self, body, content_type, *, disconnect_after=None):
        self.body = body
        self.headers = {"content-type": content_type}
        self.disconnect_after = disconnect_after

    async def stream(self):
        for index in range(0, len(self.body), 3):
            if self.disconnect_after is not None and index >= self.disconnect_after:
                raise ClientDisconnect()
            yield self.body[index:index + 3]


@pytest.mark.asyncio
async def test_chunked_oversize_file_is_413_before_service_and_closes_temp(monkeypatch, tmp_path):
    body, content_type = _multipart((("file", b"123456", "ignored.zip"),))
    service = FakeService()
    monkeypatch.setattr(project_imports, "MAX_IMPORT_FILE_BYTES", 5)
    monkeypatch.setattr(project_imports, "PROJECT_IMPORT_TEMP_PARENT", tmp_path)
    response = await project_imports.preflight_project_import(
        _StreamingRequest(body, content_type), service,
    )
    assert response.status_code == 413
    assert service.calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_partial_file_disconnect_remains_primary_closes_handle_and_calls_no_service(monkeypatch, tmp_path):
    body, content_type = _multipart((("file", b"partial-file", "ignored.zip"),))
    service = FakeService()
    monkeypatch.setattr(project_imports, "PROJECT_IMPORT_TEMP_PARENT", tmp_path)
    header_end = body.index(b"\r\n\r\n") + 6
    with pytest.raises(ClientDisconnect):
        await project_imports.preflight_project_import(
            _StreamingRequest(body, content_type, disconnect_after=header_end), service,
        )
    assert service.calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_huge_text_field_is_413_before_service(monkeypatch):
    parts = (
        ("file", b"zip", "ignored.zip"),
        ("commandId", COMMAND.encode(), None),
        ("idempotencyKey", b"same_import_key1", None),
        ("expectedPackageHash", HASH.encode(), None),
        ("newTitle", b"oversized", None),
    )
    body, content_type = _multipart(parts)
    service = FakeService()
    monkeypatch.setattr(project_imports, "MAX_IMPORT_FIELD_BYTES", 4)
    response = await project_imports.import_project(
        _StreamingRequest(body, content_type), service,
    )
    assert response.status_code == 413
    assert service.calls == []
