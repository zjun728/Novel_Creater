"""Closed public HTTP boundary for manual ChapterOutline workflow."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.database import transaction
from backend.domain.chapter_outlines import EditableChapterOutlineContent
from backend.gateways.chapter_outline_provider import (
    ChapterOutlineProviderGateway,
)
from backend.http_errors import PublicDomainError
from backend.repositories.chapter_outlines import ChapterOutlineRepository
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.repositories.planning import PlanningRepository
from backend.services.chapter_outlines import (
    ChapterOutlineArchived as ServiceChapterOutlineArchived,
    ChapterOutlineConflict as ServiceChapterOutlineConflict,
    ChapterOutlineNotFound,
    ChapterOutlinePreconditionFailed as ServiceChapterOutlinePreconditionFailed,
    ChapterOutlineRequestInvalid as ServiceChapterOutlineRequestInvalid,
    ChapterOutlineService,
    ConfirmChapterOutlineDraft,
    CreateChapterOutlineDraft,
    SaveChapterOutlineDraft,
)
from backend.services.chapter_outline_generation import (
    CHAPTER_OUTLINE_AUTHOR_INSTRUCTIONS_MAX_LENGTH,
    ChapterOutlineGenerationService,
    GenerateChapterOutline,
)


router = APIRouter(tags=["chapter-outlines"])
_service = ChapterOutlineService(
    ChapterOutlineRepository(),
    ChapterSessionRepository(),
    transaction_factory=transaction,
    planning_repository=PlanningRepository(),
)
chapter_outline_provider_gateway = ChapterOutlineProviderGateway()
_generation_service = ChapterOutlineGenerationService(
    ChapterOutlineRepository(),
    ChapterSessionRepository(),
    planning_repository=PlanningRepository(),
    provider_gateway=chapter_outline_provider_gateway,
    transaction_factory=transaction,
)


def get_chapter_outline_service() -> ChapterOutlineService:
    return _service


def get_chapter_outline_generation_service():
    return _generation_service


class ChapterOutlineRequestInvalid(PublicDomainError):
    status_code = 422
    code = "ChapterOutlineRequestInvalid"
    message = "Chapter outline request is invalid"


class ChapterOutlineResourceNotFound(PublicDomainError):
    status_code = 404
    code = "ChapterOutlineResourceNotFound"
    message = "Chapter outline resource was not found"


class ChapterOutlinePreconditionFailed(PublicDomainError):
    status_code = 412
    code = "ChapterOutlinePreconditionFailed"
    message = "Chapter outline prerequisites changed; refresh and retry"


class ChapterOutlineConflict(PublicDomainError):
    status_code = 409
    code = "ChapterOutlineConflict"
    message = "Chapter outline state changed; refresh and retry"


class ChapterOutlineArchived(PublicDomainError):
    status_code = 409
    code = "ChapterOutlineArchived"
    message = "Project is archived"


class _StrictBody(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        hide_input_in_errors=True,
    )


class CreateDraftBody(_StrictBody):
    pass


class SaveDraftBody(_StrictBody):
    expectedDraftRevision: int = Field(ge=1)
    expectedDraftHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: EditableChapterOutlineContent


class ConfirmDraftBody(_StrictBody):
    expectedDraftRevision: int = Field(ge=1)
    expectedDraftHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expectedHeadRevision: int = Field(ge=0)
    idempotencyKey: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )


class GenerateDraftBody(_StrictBody):
    draftRevision: int = Field(ge=1)
    draftHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotencyKey: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    authorInstructions: str = Field(
        max_length=CHAPTER_OUTLINE_AUTHOR_INSTRUCTIONS_MAX_LENGTH
    )


def _raise_public(error: Exception):
    if isinstance(error, ServiceChapterOutlineArchived):
        raise ChapterOutlineArchived() from None
    if isinstance(error, ServiceChapterOutlineRequestInvalid):
        raise ChapterOutlineRequestInvalid() from None
    if isinstance(error, ChapterOutlineNotFound):
        raise ChapterOutlineResourceNotFound() from None
    if isinstance(error, ServiceChapterOutlinePreconditionFailed):
        raise ChapterOutlinePreconditionFailed() from None
    if isinstance(error, ServiceChapterOutlineConflict):
        raise ChapterOutlineConflict() from None
    raise error


async def _request_json(request: Request):
    try:
        value = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ChapterOutlineRequestInvalid() from None
    if value is None:
        raise ChapterOutlineRequestInvalid()
    return value


def _validate(model, value):
    try:
        return model.model_validate(value)
    except ValidationError:
        raise ChapterOutlineRequestInvalid() from None


def _public_content(content):
    return content.model_dump(mode="json", by_alias=True)


def _public_planning(authority):
    if authority is None:
        return None
    return {
        "planningRevisionId": authority.planning_revision_id,
        "revision": authority.revision,
        "contentHash": authority.content_hash,
        "content": (
            authority.content.model_dump(mode="json", by_alias=True)
            if authority.content is not None
            else None
        ),
    }


def _public_projection(authority):
    if authority is None:
        return None
    return {
        "canonRevision": authority.canon_revision,
        "projectionRevision": authority.projection_revision,
        "contentHash": authority.content_hash,
        "synchronized": authority.synchronized,
    }


def _public_basis(basis):
    return {
        "planningAuthority": _public_planning(basis.planning),
        "canonProjectionAuthority": _public_projection(
            basis.canon_projection
        ),
    }


def _public_draft(result):
    if result is None:
        return None
    status = "current" if result.status == "active" else result.status
    if status not in {"current", "superseded"}:
        raise ValueError("invalid public ChapterOutline Draft status")
    return {
        "projectId": result.project_id,
        "chapterNumber": result.chapter_number,
        "draftId": result.draft_id,
        "baseHeadRevision": result.base_head_revision,
        "draftRevision": result.draft_revision,
        "contentHash": result.content_hash,
        "content": _public_content(result.content),
        "basis": _public_basis(result.basis),
        "status": status,
    }


def _public_revision(result, *, include_display: bool = True):
    if result is None:
        return None
    value = {
        "projectId": result.project_id,
        "chapterNumber": result.chapter_number,
        "outlineRevisionId": result.outline_revision_id,
        "revision": result.revision,
        "parentRevision": result.parent_revision,
        "contentHash": result.content_hash,
        "content": _public_content(result.content),
        "basis": _public_basis(result.basis),
    }
    if include_display:
        value["status"] = result.display_status
        value["reason"] = result.display_reason
    return value


def _public_session(result):
    if result is None:
        return None
    return {
        "chapterSessionId": result.chapter_session_id,
        "chapterNumber": result.chapter_number,
        "status": result.status,
        "planningRevisionId": result.planning_revision_id,
        "planningRevision": result.planning_revision,
        "planningHash": result.planning_hash,
        "outlineRevisionId": result.outline_revision_id,
        "outlineRevision": result.outline_revision,
        "outlineHash": result.outline_hash,
    }


def _public_state(result):
    return {
        "projectId": result.project_id,
        "lifecycle": result.lifecycle,
        "authoritativeChapterNumber": (
            result.authoritative_chapter_number
        ),
        "targetPath": result.target_path,
        "planningAuthority": _public_planning(
            result.planning_authority
        ),
        "canonProjectionAuthority": _public_projection(
            result.canon_projection_authority
        ),
        "confirmedOutline": _public_revision(
            result.confirmed_outline
        ),
        "draft": _public_draft(result.draft),
        "activeSession": _public_session(result.active_session),
        "pendingOperation": (
            {
                "operationId": result.pending_operation.operation_id,
                "status": result.pending_operation.status,
            }
            if result.pending_operation is not None
            else None
        ),
        "capabilities": {
            "view": result.capabilities.view,
            "createDraft": result.capabilities.create_draft,
            "editDraft": result.capabilities.edit_draft,
            "generate": result.capabilities.generate,
            "confirm": result.capabilities.confirm,
            "startSession": result.capabilities.start_session,
        },
        "reasons": list(result.reasons),
    }


def _public_operation(result):
    value = None
    try:
        if ChapterOutlineGenerationService.public_operation_is_valid(result):
            value = {
                "operationId": result.operation_id,
                "status": result.status,
                "failureCode": result.failure_code,
                "model": {
                    "providerId": result.model.provider_id,
                    "modelName": result.model.model_name,
                },
                "loaded": result.loaded,
                "loadedDraftRevision": result.loaded_draft_revision,
            }
    except (
        AttributeError,
        TypeError,
        ValueError,
        OverflowError,
        UnicodeError,
    ):
        value = None
    result = None
    return value


def _raise_public_operation_conflict():
    raise ChapterOutlineConflict()


# Static routes must precede the dynamic /{chapter_number} route.
@router.get("/projects/{pid}/chapter-outlines/current")
async def get_current_chapter_outline(
    pid: str,
    service=Depends(get_chapter_outline_service),
):
    try:
        return _public_state(await service.get_current(pid))
    except Exception as error:
        _raise_public(error)


@router.get(
    "/projects/{pid}/chapter-outlines/operations/by-key/"
    "{idempotency_key}"
)
async def get_chapter_outline_operation_by_key(
    pid: str,
    idempotency_key: str,
    service=Depends(get_chapter_outline_generation_service),
):
    try:
        result = await service.get_operation_by_key(pid, idempotency_key)
    except Exception as error:
        _raise_public(error)
    value = _public_operation(result)
    result = None
    if value is None:
        _raise_public_operation_conflict()
    return value


@router.get(
    "/projects/{pid}/chapter-outlines/operations/{operation_id}"
)
async def get_chapter_outline_operation(
    pid: str,
    operation_id: str,
    service=Depends(get_chapter_outline_generation_service),
):
    try:
        result = await service.get_operation(pid, operation_id)
    except Exception as error:
        _raise_public(error)
    value = _public_operation(result)
    result = None
    if value is None:
        _raise_public_operation_conflict()
    return value


@router.get("/projects/{pid}/chapter-outlines/{chapter_number}")
async def get_chapter_outline(
    pid: str,
    chapter_number: int,
    service=Depends(get_chapter_outline_service),
):
    try:
        return _public_state(await service.get(pid, chapter_number))
    except Exception as error:
        _raise_public(error)


@router.get(
    "/projects/{pid}/chapter-outlines/{chapter_number}/history"
)
async def get_chapter_outline_history(
    pid: str,
    chapter_number: int,
    service=Depends(get_chapter_outline_service),
):
    try:
        items = await service.history(pid, chapter_number)
    except Exception as error:
        _raise_public(error)
    return {
        "items": [
            _public_revision(item, include_display=True)
            for item in items
        ]
    }


@router.post(
    "/projects/{pid}/chapter-outlines/{chapter_number}/drafts",
    status_code=201,
)
async def create_chapter_outline_draft(
    pid: str,
    chapter_number: int,
    request: Request,
    service=Depends(get_chapter_outline_service),
):
    body = _validate(CreateDraftBody, await _request_json(request))
    del body
    try:
        result = await service.create_draft(
            CreateChapterOutlineDraft(pid, chapter_number)
        )
    except Exception as error:
        _raise_public(error)
    return _public_draft(result)


@router.put(
    "/projects/{pid}/chapter-outlines/{chapter_number}/drafts/"
    "{draft_id}"
)
async def save_chapter_outline_draft(
    pid: str,
    chapter_number: int,
    draft_id: str,
    request: Request,
    service=Depends(get_chapter_outline_service),
):
    body = _validate(SaveDraftBody, await _request_json(request))
    try:
        result = await service.save_draft(
            SaveChapterOutlineDraft(
                project_id=pid,
                chapter_number=chapter_number,
                draft_id=draft_id,
                expected_draft_revision=body.expectedDraftRevision,
                expected_draft_hash=body.expectedDraftHash,
                content=body.content,
            )
        )
    except Exception as error:
        _raise_public(error)
    return _public_draft(result)


@router.post(
    "/projects/{pid}/chapter-outlines/{chapter_number}/drafts/"
    "{draft_id}/generate"
)
async def generate_chapter_outline_draft(
    pid: str,
    chapter_number: int,
    draft_id: str,
    request: Request,
    service=Depends(get_chapter_outline_generation_service),
):
    body = _validate(GenerateDraftBody, await _request_json(request))
    try:
        result = await service.generate(
            GenerateChapterOutline(
                project_id=pid,
                chapter_number=chapter_number,
                draft_id=draft_id,
                draft_revision=body.draftRevision,
                draft_hash=body.draftHash,
                idempotency_key=body.idempotencyKey,
                author_instructions=body.authorInstructions,
            )
        )
    except Exception as error:
        _raise_public(error)
    value = _public_operation(result)
    result = None
    body = None
    service = None
    if value is None:
        _raise_public_operation_conflict()
    return value


@router.post(
    "/projects/{pid}/chapter-outlines/{chapter_number}/drafts/"
    "{draft_id}/confirm",
    status_code=201,
)
async def confirm_chapter_outline_draft(
    pid: str,
    chapter_number: int,
    draft_id: str,
    request: Request,
    service=Depends(get_chapter_outline_service),
):
    body = _validate(ConfirmDraftBody, await _request_json(request))
    try:
        result = await service.confirm_draft(
            ConfirmChapterOutlineDraft(
                project_id=pid,
                chapter_number=chapter_number,
                draft_id=draft_id,
                expected_draft_revision=body.expectedDraftRevision,
                expected_draft_hash=body.expectedDraftHash,
                expected_head_revision=body.expectedHeadRevision,
                idempotency_key=body.idempotencyKey,
            )
        )
    except Exception as error:
        _raise_public(error)
    return _public_revision(result, include_display=False)


__all__ = (
    "ChapterOutlineArchived",
    "ChapterOutlineConflict",
    "ChapterOutlinePreconditionFailed",
    "ChapterOutlineRequestInvalid",
    "ChapterOutlineResourceNotFound",
    "get_chapter_outline_service",
    "get_chapter_outline_generation_service",
    "router",
)
