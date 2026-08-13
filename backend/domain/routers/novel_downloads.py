"""Public, read-only finalized novel download endpoints."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.database import transaction
from backend.domain.novel_downloads import (
    DownloadFormat,
    DownloadScope,
    NovelDownloadIntegrityError,
    NovelDownloadScopeNotFoundError,
    NovelDownloadSelector,
    NovelDownloadTooLargeError,
)
from backend.http_errors import PublicDomainError
from backend.repositories.novel_downloads import NovelDownloadRepository
from backend.services.novel_downloads import (
    NovelDownloadProjectNotFound,
    NovelDownloadService,
    NovelDownloadUnavailable,
)


router = APIRouter(tags=["novel-downloads"])
_service = NovelDownloadService(transaction, NovelDownloadRepository())


def get_novel_download_service() -> NovelDownloadService:
    return _service


class NovelDownloadNotFound(PublicDomainError):
    status_code = 404
    code = "NovelDownloadNotFound"
    message = "Finalized novel download not found"


class NovelDownloadUnavailablePublic(PublicDomainError):
    status_code = 409
    code = "NovelDownloadUnavailable"
    message = "No finalized chapters are available for download"


class NovelDownloadIntegrityFailure(PublicDomainError):
    status_code = 500
    code = "NovelDownloadIntegrityFailure"
    message = "Finalized novel download could not be generated"


class NovelDownloadQuery(BaseModel):
    """Closed URL query contract; coercion is intentionally enabled for URLs."""

    model_config = ConfigDict(extra="forbid")

    scope: DownloadScope
    format: DownloadFormat
    volumeId: str | None = Field(default=None, min_length=1)
    chapterNumber: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def selector_fields_match_scope(self):
        NovelDownloadSelector(
            scope=self.scope,
            format=self.format,
            volume_id=self.volumeId,
            chapter_number=self.chapterNumber,
        )
        return self

    def selector(self) -> NovelDownloadSelector:
        return NovelDownloadSelector(
            scope=self.scope,
            format=self.format,
            volume_id=self.volumeId,
            chapter_number=self.chapterNumber,
        )


def _raise_public(error: Exception) -> None:
    if isinstance(error, (NovelDownloadProjectNotFound, NovelDownloadScopeNotFoundError)):
        raise NovelDownloadNotFound() from None
    if isinstance(error, NovelDownloadUnavailable):
        raise NovelDownloadUnavailablePublic() from None
    if isinstance(error, (NovelDownloadIntegrityError, NovelDownloadTooLargeError)):
        raise NovelDownloadIntegrityFailure() from None
    raise error


def _attachment_disposition(result) -> str:
    names = result.attachment_names
    return (
        f'attachment; filename="{names.ascii_filename}"; '
        f"filename*=UTF-8''{quote(names.unicode_filename, safe='')}"
    )


@router.get("/projects/{project_id}/novel-download/options")
async def get_novel_download_options(
    project_id: str,
    service: Annotated[NovelDownloadService, Depends(get_novel_download_service)],
):
    try:
        options = await service.options(project_id)
    except Exception as error:
        _raise_public(error)
    return options.model_dump(by_alias=True, mode="json")


@router.get("/projects/{project_id}/novel-download")
async def download_novel(
    project_id: str,
    query: Annotated[NovelDownloadQuery, Query()],
    service: Annotated[NovelDownloadService, Depends(get_novel_download_service)],
) -> Response:
    try:
        result = await service.download(project_id, query.selector())
    except Exception as error:
        _raise_public(error)
    return Response(
        content=result.content,
        media_type=result.media_type,
        headers={
            "Content-Disposition": _attachment_disposition(result),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


__all__ = (
    "NovelDownloadIntegrityFailure",
    "NovelDownloadNotFound",
    "NovelDownloadQuery",
    "NovelDownloadUnavailablePublic",
    "get_novel_download_service",
    "router",
)
