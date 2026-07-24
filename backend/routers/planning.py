"""Public HTTP boundary for the revisioned Planning aggregate."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.database import connection, transaction
from backend.domain.planning import DraftPlanningAggregate
from backend.http_errors import PublicDomainError
from backend.repositories.planning import PlanningRepository
from backend.services.planning import (
    ConfirmPlanningDraft,
    CreatePlanningDraft,
    PlanningArchived as ServicePlanningArchived,
    PlanningConflict as ServicePlanningConflict,
    PlanningNotFound,
    PlanningPreconditionFailed as ServicePlanningPreconditionFailed,
    PlanningRequestInvalid as ServicePlanningRequestInvalid,
    PlanningService,
    SavePlanningDraft,
)


router = APIRouter(tags=["planning"])
_service = PlanningService(
    PlanningRepository(),
    transaction_factory=transaction,
    connection_factory=connection,
)


def get_planning_service() -> PlanningService:
    return _service


class PlanningRequestInvalid(PublicDomainError):
    status_code = 422
    code = "PlanningRequestInvalid"
    message = "Planning request is invalid"


class PlanningResourceNotFound(PublicDomainError):
    status_code = 404
    code = "PlanningResourceNotFound"
    message = "Planning resource was not found"


class PlanningPreconditionFailed(PublicDomainError):
    status_code = 412
    code = "PlanningPreconditionFailed"
    message = "Planning prerequisites changed; refresh and retry"


class PlanningConflict(PublicDomainError):
    status_code = 409
    code = "PlanningConflict"
    message = "Planning state changed; refresh and retry"


class PlanningArchived(PublicDomainError):
    status_code = 409
    code = "PlanningArchived"
    message = "Project is archived"


class _StrictBody(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        hide_input_in_errors=True,
    )


class CreateDraftBody(_StrictBody):
    idempotencyKey: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )


class SaveDraftBody(_StrictBody):
    expectedDraftRevision: int = Field(ge=1)
    expectedDraftHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: DraftPlanningAggregate
    idempotencyKey: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )


class ConfirmDraftBody(_StrictBody):
    expectedDraftRevision: int = Field(ge=1)
    expectedDraftHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotencyKey: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )


def _raise_public(error: Exception):
    if isinstance(error, ServicePlanningArchived):
        raise PlanningArchived() from None
    if isinstance(error, ServicePlanningRequestInvalid):
        raise PlanningRequestInvalid() from None
    if isinstance(error, PlanningNotFound):
        raise PlanningResourceNotFound() from None
    if isinstance(error, ServicePlanningPreconditionFailed):
        raise PlanningPreconditionFailed() from None
    if isinstance(error, ServicePlanningConflict):
        raise PlanningConflict() from None
    raise error


def _validate(model, raw_body):
    try:
        return model.model_validate(raw_body)
    except ValidationError:
        raise PlanningRequestInvalid() from None


async def _request_json(request: Request):
    try:
        value = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise PlanningRequestInvalid() from None
    if value is None:
        raise PlanningRequestInvalid()
    return value


def _public_content(content):
    if content is None:
        return None
    return content.model_dump(mode="json", by_alias=True)


def _public_draft(result):
    return {
        "projectId": result.project_id,
        "draftId": result.draft_id,
        "baseHeadRevision": result.base_head_revision,
        "draftRevision": result.draft_revision,
        "contentHash": result.content_hash,
        "content": _public_content(result.content),
        "status": result.status,
        "capacityPolicy": dict(result.capacity_policy),
    }


def _public_revision(result):
    return {
        "projectId": result.project_id,
        "planningRevisionId": result.planning_revision_id,
        "revision": result.revision,
        "parentRevision": result.parent_revision,
        "contentHash": result.content_hash,
        "content": _public_content(result.content),
    }


def _public_state(result):
    return {
        "projectId": result.project_id,
        "basisStatus": result.basis_status,
        "head": {
            "revision": result.head.revision,
            "planningRevisionId": result.head.planning_revision_id,
            "contentHash": result.head.content_hash,
        },
        "draft": (
            _public_draft(result.draft)
            if result.draft is not None
            else None
        ),
        "futurePlan": _public_content(result.future_plan),
        "actualProgress": list(result.actual_progress),
        "canonProjectionStatus": dict(result.canon_projection_status),
        "capacityPolicy": (
            dict(result.capacity_policy)
            if result.capacity_policy is not None
            else None
        ),
        "capabilities": {
            "view": result.capabilities.view,
            "edit": result.capabilities.edit,
            "confirm": result.capabilities.confirm,
            "generate": result.capabilities.generate,
        },
    }


@router.get("/projects/{pid}/planning")
async def get_planning(pid: str, service=Depends(get_planning_service)):
    try:
        result = await service.get_state(pid)
    except Exception as error:
        _raise_public(error)
    return _public_state(result)


@router.get("/projects/{pid}/planning/history")
async def get_planning_history(
    pid: str,
    service=Depends(get_planning_service),
):
    try:
        result = await service.history(pid)
    except Exception as error:
        _raise_public(error)
    return {"items": [_public_revision(item) for item in result]}


@router.post("/projects/{pid}/planning/drafts", status_code=201)
async def create_planning_draft(
    pid: str,
    request: Request,
    service=Depends(get_planning_service),
):
    raw_body = await _request_json(request)
    body = _validate(CreateDraftBody, raw_body)
    try:
        result = await service.create_draft(
            CreatePlanningDraft(
                project_id=pid,
                idempotency_key=body.idempotencyKey,
            )
        )
    except Exception as error:
        _raise_public(error)
    return _public_draft(result)


@router.put("/projects/{pid}/planning/drafts/{draft_id}")
async def save_planning_draft(
    pid: str,
    draft_id: str,
    request: Request,
    service=Depends(get_planning_service),
):
    raw_body = await _request_json(request)
    body = _validate(SaveDraftBody, raw_body)
    try:
        result = await service.save_draft(
            SavePlanningDraft(
                project_id=pid,
                draft_id=draft_id,
                expected_revision=body.expectedDraftRevision,
                expected_hash=body.expectedDraftHash,
                content=body.content.model_dump(mode="json", by_alias=True),
                idempotency_key=body.idempotencyKey,
            )
        )
    except Exception as error:
        _raise_public(error)
    return _public_draft(result)


@router.post(
    "/projects/{pid}/planning/drafts/{draft_id}/confirm",
    status_code=201,
)
async def confirm_planning_draft(
    pid: str,
    draft_id: str,
    request: Request,
    service=Depends(get_planning_service),
):
    raw_body = await _request_json(request)
    body = _validate(ConfirmDraftBody, raw_body)
    try:
        result = await service.confirm_draft(
            ConfirmPlanningDraft(
                project_id=pid,
                draft_id=draft_id,
                expected_draft_revision=body.expectedDraftRevision,
                expected_draft_hash=body.expectedDraftHash,
                idempotency_key=body.idempotencyKey,
            )
        )
    except Exception as error:
        _raise_public(error)
    return _public_revision(result)


__all__ = (
    "PlanningArchived",
    "PlanningConflict",
    "PlanningPreconditionFailed",
    "PlanningRequestInvalid",
    "PlanningResourceNotFound",
    "get_planning_service",
    "router",
)
