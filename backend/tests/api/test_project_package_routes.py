from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.project_packages import (
    ProjectPackageBusy,
    ProjectPackageConflict,
    ProjectPackageIntegrity,
    ProjectPackageInvalid,
    ProjectPackageNotFound,
    ProjectPackageSensitiveData,
    ProjectPackageTooLarge,
)
from backend.routers import project_packages
from backend.security.redaction import install_error_handlers
from backend.services.project_packages import ProjectPackageFile


_HASH = "a" * 64
_PRIVATE_SENTINELS = (
    r"C:\private\novel-creator-phase6b-secret\project-backup.zip",
    "internal-row-id-987",
    "sk-private-provider-sentinel",
    "mysql://root:private-password@127.0.0.1/product",
    "PRIVATE_CORPUS_BYTES_SENTINEL",
    "PRIVATE_CAUSE_SENTINEL",
)


class FakeProjectPackageService:
    def __init__(self, package: ProjectPackageFile):
        self.package = package
        self.error: BaseException | None = None
        self.calls: list[tuple[str, int]] = []

    async def create_backup(self, project_id, expected_lifecycle_revision):
        self.calls.append((project_id, expected_lifecycle_revision))
        if self.error is not None:
            raise self.error
        return self.package


def _package(tmp_path, *, content=b"PK\x03\x04bounded package bytes"):
    archive = tmp_path / "project-backup.zip"
    archive.write_bytes(content)
    cleanup_calls: list[str] = []

    def cleanup():
        cleanup_calls.append("cleanup")

    return (
        ProjectPackageFile(
            path=archive,
            package_sha256=_HASH,
            download_name="project-backup.zip",
            cleanup=cleanup,
        ),
        cleanup_calls,
    )


def _client(tmp_path):
    package, cleanup_calls = _package(tmp_path)
    service = FakeProjectPackageService(package)
    app = FastAPI()
    app.include_router(project_packages.router, prefix="/api")
    app.dependency_overrides[
        project_packages.get_project_package_service
    ] = lambda: service
    install_error_handlers(app)
    return (
        TestClient(app, raise_server_exceptions=False),
        service,
        cleanup_calls,
    )


def test_backup_streams_exact_zip_with_private_attachment_headers_and_one_cleanup(tmp_path):
    client, service, cleanup_calls = _client(tmp_path)

    response = client.post(
        "/api/projects/public-project/backup",
        json={"expectedLifecycleRevision": 7},
    )

    assert response.status_code == 200
    assert response.content == b"PK\x03\x04bounded package bytes"
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == (
        "attachment; filename=\"project-backup.zip\"; "
        "filename*=UTF-8''project-backup.zip"
    )
    assert response.headers["x-package-sha256"] == _HASH
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert service.calls == [("public-project", 7)]
    assert cleanup_calls == ["cleanup"]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"expectedLifecycleRevision": -1},
        {"expectedLifecycleRevision": "7"},
        {"expected_lifecycle_revision": 7},
        {"expectedLifecycleRevision": 7, "extra": "PRIVATE_CAUSE_SENTINEL"},
    ],
)
def test_backup_rejects_missing_invalid_or_unknown_body_fields_without_service_call(
    tmp_path, body
):
    client, service, cleanup_calls = _client(tmp_path)

    response = client.post("/api/projects/public-project/backup", json=body)

    assert response.status_code == 422
    assert service.calls == []
    assert cleanup_calls == []
    assert "PRIVATE_CAUSE_SENTINEL" not in response.text


@pytest.mark.parametrize(
    ("error_type", "status", "code"),
    [
        (ProjectPackageNotFound, 404, "ProjectPackageNotFound"),
        (ProjectPackageConflict, 409, "ProjectPackageConflict"),
        (ProjectPackageBusy, 409, "ProjectPackageBusy"),
        (ProjectPackageTooLarge, 413, "ProjectPackageTooLarge"),
        (ProjectPackageIntegrity, 422, "ProjectPackageInvalid"),
        (ProjectPackageSensitiveData, 422, "ProjectPackageInvalid"),
        (ProjectPackageInvalid, 422, "ProjectPackageInvalid"),
        (RuntimeError, 500, "ProjectPackageFailure"),
    ],
)
def test_backup_maps_failures_to_fixed_public_responses_without_private_evidence(
    tmp_path, error_type, status, code
):
    client, service, cleanup_calls = _client(tmp_path)
    service.error = error_type(" ".join(_PRIVATE_SENTINELS))

    response = client.post(
        "/api/projects/public-project/backup",
        json={"expectedLifecycleRevision": 7},
    )

    assert response.status_code == status
    assert set(response.json()) == {"code", "message", "correlationId"}
    assert response.json()["code"] == code
    rendered = response.text + json.dumps(dict(response.headers))
    assert all(sentinel not in rendered for sentinel in _PRIVATE_SENTINELS)
    assert cleanup_calls == []


@pytest.mark.asyncio
async def test_backup_preserves_request_cancellation(tmp_path):
    package, _ = _package(tmp_path)
    service = FakeProjectPackageService(package)
    service.error = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await project_packages.backup_project(
            "public-project",
            project_packages.BackupProjectBody(
                expectedLifecycleRevision=7
            ),
            service,
        )


@pytest.mark.asyncio
async def test_stream_cancellation_and_background_cleanup_share_one_idempotent_effect(
    tmp_path,
):
    content = b"x" * (project_packages.STREAM_CHUNK_BYTES + 17)
    package, cleanup_calls = _package(tmp_path, content=content)
    cleanup = project_packages.IdempotentPackageCleanup(package.cleanup)
    stream = project_packages.stream_project_package(package.path, cleanup)

    first = await anext(stream)
    assert 0 < len(first) <= project_packages.STREAM_CHUNK_BYTES
    with pytest.raises(asyncio.CancelledError):
        await stream.athrow(asyncio.CancelledError())

    response = project_packages.project_package_response(package, cleanup=cleanup)
    assert response.background is not None
    await response.background()
    await response.background()
    cleanup()

    assert cleanup_calls == ["cleanup"]


@pytest.mark.asyncio
async def test_failed_generator_cleanup_is_retried_by_background_until_file_is_removed(
    tmp_path,
):
    package, _ = _package(tmp_path)
    attempts: list[str] = []

    def fail_once_then_remove():
        attempts.append("attempt")
        if len(attempts) == 1:
            raise OSError("PRIVATE_CLEANUP_PATH_SENTINEL")
        package.path.unlink()

    cleanup = project_packages.IdempotentPackageCleanup(fail_once_then_remove)
    stream = project_packages.stream_project_package(package.path, cleanup)
    await anext(stream)

    with pytest.raises(asyncio.CancelledError):
        await stream.athrow(asyncio.CancelledError())

    assert attempts == ["attempt"]
    assert package.path.exists()

    response = project_packages.project_package_response(package, cleanup=cleanup)
    assert response.background is not None
    await response.background()
    await response.background()
    cleanup()

    assert attempts == ["attempt", "attempt"]
    assert not package.path.exists()


def test_concurrent_cleanup_calls_execute_one_successful_effect(tmp_path):
    package, _ = _package(tmp_path)
    started = Event()
    release = Event()
    effects: list[str] = []

    def remove_once():
        effects.append("effect")
        started.set()
        assert release.wait(timeout=1)
        package.path.unlink()

    cleanup = project_packages.IdempotentPackageCleanup(remove_once)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(cleanup)
        assert started.wait(timeout=1)
        second = executor.submit(cleanup)
        release.set()
        first.result(timeout=1)
        second.result(timeout=1)

    assert effects == ["effect"]
    assert not package.path.exists()
