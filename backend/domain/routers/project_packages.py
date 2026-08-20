"""Secret-free project package streaming boundary."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import tempfile
from threading import Lock
from typing import Annotated, AsyncIterator, Callable
from urllib.parse import quote

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from backend.config import (
    current_runtime_configuration,
    require_managed_corpus_root,
)
from backend.database import get_pool
from backend.domain.project_packages import (
    ProjectPackageBusy,
    ProjectPackageConflict,
    ProjectPackageIntegrity,
    ProjectPackageInvalid,
    ProjectPackageNotFound,
    ProjectPackageSensitiveData,
    ProjectPackageTooLarge,
)
from backend.http_errors import PublicDomainError
from backend.repositories.project_packages import ProjectPackageRepository
from backend.services.project_packages import (
    ProjectPackageFile,
    ProjectPackageService,
    cleanup_stale_project_package_roots,
)


STREAM_CHUNK_BYTES = 64 * 1024
PROJECT_PACKAGE_TEMP_PARENT = Path(tempfile.gettempdir())
_logger = logging.getLogger("backend.project_packages")

router = APIRouter(tags=["project-packages"])


class BackupProjectBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expectedLifecycleRevision: int = Field(ge=0)


class ProjectPackageNotFoundPublic(PublicDomainError):
    status_code = 404
    code = "ProjectPackageNotFound"
    message = "Project backup is unavailable"


class ProjectPackageConflictPublic(PublicDomainError):
    status_code = 409
    code = "ProjectPackageConflict"
    message = "Project state changed; refresh and retry"


class ProjectPackageBusyPublic(PublicDomainError):
    status_code = 409
    code = "ProjectPackageBusy"
    message = "Project has an unfinished operation"


class ProjectPackageTooLargePublic(PublicDomainError):
    status_code = 413
    code = "ProjectPackageTooLarge"
    message = "Project backup exceeds the supported size"


class ProjectPackageInvalidPublic(PublicDomainError):
    status_code = 422
    code = "ProjectPackageInvalid"
    message = "Project backup could not be created"


class ProjectPackageFailure(PublicDomainError):
    status_code = 500
    code = "ProjectPackageFailure"
    message = "Project backup could not be generated"


async def get_project_package_service() -> ProjectPackageService:
    snapshot = current_runtime_configuration()
    managed_corpus_root = require_managed_corpus_root(
        snapshot.managed_corpus_root
    )
    pool = await get_pool()
    return ProjectPackageService(
        repository=ProjectPackageRepository(pool=pool),
        managed_corpus_root=managed_corpus_root,
        temp_parent=PROJECT_PACKAGE_TEMP_PARENT,
    )


class IdempotentPackageCleanup:
    """Complete one response-owned cleanup effect across worker threads."""

    def __init__(self, cleanup: Callable[[], None]) -> None:
        if not callable(cleanup):
            raise ProjectPackageInvalid("invalid project package cleanup")
        self._cleanup = cleanup
        self._lock = Lock()
        self._completed = False

    def __call__(self) -> None:
        with self._lock:
            if self._completed:
                return
            try:
                self._cleanup()
            except Exception:
                _logger.warning("project_package_response_cleanup_failed")
                return
            self._completed = True


async def stream_project_package(
    path: Path,
    cleanup: IdempotentPackageCleanup,
) -> AsyncIterator[bytes]:
    try:
        with path.open("rb") as source:
            while True:
                chunk = source.read(STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                yield chunk
    finally:
        cleanup()


def project_package_response(
    package: ProjectPackageFile,
    *,
    cleanup: IdempotentPackageCleanup | None = None,
) -> StreamingResponse:
    if type(package) is not ProjectPackageFile:
        raise ProjectPackageInvalid("invalid project package file")
    owned_cleanup = cleanup or IdempotentPackageCleanup(package.cleanup)
    encoded_name = quote(package.download_name, safe="")
    return StreamingResponse(
        stream_project_package(package.path, owned_cleanup),
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{package.download_name}"; '
                f"filename*=UTF-8''{encoded_name}"
            ),
            "X-Package-SHA256": package.package_sha256,
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
        background=BackgroundTask(owned_cleanup),
    )


def _raise_public(error: Exception) -> None:
    if isinstance(error, ProjectPackageNotFound):
        raise ProjectPackageNotFoundPublic() from None
    if isinstance(error, ProjectPackageBusy):
        raise ProjectPackageBusyPublic() from None
    if isinstance(error, ProjectPackageConflict):
        raise ProjectPackageConflictPublic() from None
    if isinstance(error, ProjectPackageTooLarge):
        raise ProjectPackageTooLargePublic() from None
    if isinstance(
        error,
        (
            ProjectPackageIntegrity,
            ProjectPackageSensitiveData,
            ProjectPackageInvalid,
        ),
    ):
        raise ProjectPackageInvalidPublic() from None
    raise ProjectPackageFailure() from None


@router.post("/projects/{project_id}/backup")
async def backup_project(
    project_id: str,
    body: BackupProjectBody,
    service: Annotated[ProjectPackageService, Depends(get_project_package_service)],
) -> StreamingResponse:
    try:
        package = await service.create_backup(
            project_id,
            body.expectedLifecycleRevision,
        )
        return project_package_response(package)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        _raise_public(error)


__all__ = (
    "BackupProjectBody",
    "IdempotentPackageCleanup",
    "PROJECT_PACKAGE_TEMP_PARENT",
    "STREAM_CHUNK_BYTES",
    "get_project_package_service",
    "cleanup_stale_project_package_roots",
    "project_package_response",
    "router",
    "stream_project_package",
)
