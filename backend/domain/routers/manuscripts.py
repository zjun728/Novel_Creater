"""Closed public HTTP endpoints for finalized manuscript reading."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from backend.database import transaction
from backend.http_errors import PublicDomainError
from backend.services.manuscripts import (
    FinalChapterNotFound,
    ManuscriptIntegrityFailure,
    ManuscriptProjectNotFound,
    ManuscriptReadingService,
    ManuscriptTemporarilyUnavailable,
)


router = APIRouter(tags=["manuscripts"])
_service = ManuscriptReadingService(transaction)


def get_manuscript_reading_service() -> ManuscriptReadingService:
    return _service


class ManuscriptRequestInvalid(PublicDomainError):
    status_code = 422
    code = "ManuscriptRequestInvalid"
    message = "Manuscript request is invalid"


class ManuscriptProjectNotFoundPublic(PublicDomainError):
    status_code = 404
    code = "ManuscriptProjectNotFound"
    message = "Manuscript project not found"


class FinalChapterNotFoundPublic(PublicDomainError):
    status_code = 404
    code = "FinalChapterNotFound"
    message = "Finalized chapter not found"


class ManuscriptIntegrityFailurePublic(PublicDomainError):
    status_code = 500
    code = "ManuscriptIntegrityFailure"
    message = "Finalized manuscript could not be read"


class ManuscriptTemporarilyUnavailablePublic(PublicDomainError):
    status_code = 503
    code = "ManuscriptTemporarilyUnavailable"
    message = "Finalized manuscript is temporarily unavailable"


def _require_no_query_parameters(request: Request) -> None:
    if request.query_params:
        raise ManuscriptRequestInvalid()


def _chapter_number(value: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise ManuscriptRequestInvalid()
    number = int(value)
    if number < 1:
        raise ManuscriptRequestInvalid()
    return number


def _raise_public(error: Exception) -> None:
    if isinstance(error, ManuscriptProjectNotFound):
        raise ManuscriptProjectNotFoundPublic() from None
    if isinstance(error, FinalChapterNotFound):
        raise FinalChapterNotFoundPublic() from None
    if isinstance(error, ManuscriptIntegrityFailure):
        raise ManuscriptIntegrityFailurePublic() from None
    if isinstance(error, ManuscriptTemporarilyUnavailable):
        raise ManuscriptTemporarilyUnavailablePublic() from None
    raise error


def _success(value) -> JSONResponse:
    return JSONResponse(
        content=value.model_dump(by_alias=True, mode="json"),
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/projects/{project_id}/manuscript")
async def get_manuscript_directory(
    project_id: str,
    request: Request,
    service: Annotated[ManuscriptReadingService, Depends(get_manuscript_reading_service)],
) -> JSONResponse:
    _require_no_query_parameters(request)
    try:
        result = await service.directory(project_id)
    except Exception as error:
        _raise_public(error)
    return _success(result)


@router.get("/projects/{project_id}/manuscript/chapters/{chapter_number}")
async def get_manuscript_chapter(
    project_id: str,
    chapter_number: str,
    request: Request,
    service: Annotated[ManuscriptReadingService, Depends(get_manuscript_reading_service)],
) -> JSONResponse:
    _require_no_query_parameters(request)
    number = _chapter_number(chapter_number)
    try:
        result = await service.chapter(project_id, number)
    except Exception as error:
        _raise_public(error)
    return _success(result)


__all__ = (
    "FinalChapterNotFoundPublic", "ManuscriptIntegrityFailurePublic",
    "ManuscriptProjectNotFoundPublic", "ManuscriptRequestInvalid",
    "ManuscriptTemporarilyUnavailablePublic", "get_manuscript_reading_service", "router",
)
