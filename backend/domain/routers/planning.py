"""Public HTTP boundary for the revisioned Planning aggregate."""

from __future__ import annotations

import json
import re
from urllib.parse import unquote, unquote_plus, urlsplit

from fastapi import APIRouter, Depends, Request
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from backend.database import transaction
from backend.domain.planning import DraftPlanningAggregate
from backend.gateways.planning_provider import PlanningProviderGateway
from backend.http_errors import PublicDomainError
from backend.prompts.planning import _PRIVATE_TEXT as _PLANNING_PRIVATE_TEXT
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
from backend.services.planning_generation import (
    PLANNING_AUTHOR_INSTRUCTIONS_MAX_LENGTH,
    GeneratePlanningDraft,
    PlanningGenerationService,
    is_safe_planning_idempotency_key,
)


router = APIRouter(tags=["planning"])
_service = PlanningService(
    PlanningRepository(),
    transaction_factory=transaction,
)
planning_provider_gateway = PlanningProviderGateway()
_generation_service = PlanningGenerationService(
    PlanningRepository(),
    provider_gateway=planning_provider_gateway,
    transaction_factory=transaction,
)


def get_planning_service() -> PlanningService:
    return _service


def get_planning_generation_service() -> PlanningGenerationService:
    return _generation_service


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


class GenerateDraftBody(_StrictBody):
    draftRevision: int = Field(ge=1)
    draftHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotencyKey: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    authorInstructions: str = Field(
        max_length=PLANNING_AUTHOR_INSTRUCTIONS_MAX_LENGTH
    )

    @field_validator("idempotencyKey")
    @classmethod
    def validate_secret_safe_idempotency_key(cls, value):
        if not is_safe_planning_idempotency_key(value):
            raise ValueError("invalid Planning idempotency key")
        return value


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


def _public_revision(result, *, include_display_status: bool = False):
    value = {
        "projectId": result.project_id,
        "planningRevisionId": result.planning_revision_id,
        "revision": result.revision,
        "parentRevision": result.parent_revision,
        "contentHash": result.content_hash,
        "content": _public_content(result.content),
    }
    if include_display_status:
        value["displayStatus"] = result.display_status
        value["displayReason"] = result.display_reason
    return value


_SAFE_OPERATION_FAILURE_CODES = frozenset(
    {
        "PlanningGenerationCancelled",
        "PlanningProviderFailed",
        "PlanningProviderResultInvalid",
    }
)
_PUBLIC_OPERATION_STATUSES = frozenset(
    {"pending", "succeeded", "failed", "superseded"}
)
_PUBLIC_MODEL_UNAVAILABLE = "unavailable"
_API_KEY_SHAPED_TEXT = re.compile(
    r"(?:^|[^A-Za-z0-9])(?:"
    r"(?:sk|rk|pk)[-_][A-Za-z0-9._~+/=-]{8,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|AIza[A-Za-z0-9_-]{20,}"
    r"|(?:AKIA|ASIA)[A-Z0-9]{16}"
    r")(?:$|[^A-Za-z0-9])",
    re.IGNORECASE,
)
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_VALID_PERCENT_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")


def _public_model_summary(model):
    values = (model.provider_id, model.model_name)
    if any(not _public_model_value_is_safe(value) for value in values):
        return {
            "providerId": _PUBLIC_MODEL_UNAVAILABLE,
            "modelName": _PUBLIC_MODEL_UNAVAILABLE,
        }
    return {
        "providerId": model.provider_id,
        "modelName": model.model_name,
    }


def _public_model_value_is_safe(value) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 512
    ):
        return False
    try:
        value.encode("utf-8")
        variants = {value}
        frontier = {value}
        for _ in range(2):
            if any(_INVALID_PERCENT_ESCAPE.search(item) for item in frontier):
                return False
            decoded = {
                candidate
                for item in frontier
                for candidate in (
                    unquote(item, encoding="utf-8", errors="strict"),
                    unquote_plus(item, encoding="utf-8", errors="strict"),
                )
            }
            if any(len(candidate) > 512 for candidate in decoded):
                return False
            frontier = decoded - variants
            variants.update(decoded)
            if not frontier:
                break
        else:
            if any(_VALID_PERCENT_ESCAPE.search(item) for item in frontier):
                return False
        if any(_INVALID_PERCENT_ESCAPE.search(item) for item in variants):
            return False
    except (UnicodeError, ValueError):
        return False
    return all(_public_model_variant_is_safe(item) for item in variants)


def _public_model_variant_is_safe(value: str) -> bool:
    if (
        any(
            ord(character) < 32 or ord(character) == 127
            for character in value
        )
        or _PLANNING_PRIVATE_TEXT.search(value)
        or _API_KEY_SHAPED_TEXT.search(value)
    ):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.username is None and parsed.password is None


def _public_operation_state(result):
    status = result.status
    failure_code = result.failure_code
    loaded = result.loaded
    loaded_revision = result.loaded_draft_revision
    revision_is_positive = (
        type(loaded_revision) is int and loaded_revision > 0
    )
    status_is_public = (
        isinstance(status, str) and status in _PUBLIC_OPERATION_STATUSES
    )
    failure_is_safe = (
        failure_code is None
        or (
            isinstance(failure_code, str)
            and failure_code in _SAFE_OPERATION_FAILURE_CODES
        )
    )
    common_valid = (
        status_is_public
        and type(loaded) is bool
        and failure_is_safe
        and (
            loaded_revision is None
            or revision_is_positive
        )
    )
    valid = common_valid and (
        (
            status == "pending"
            and failure_code is None
            and loaded is False
            and loaded_revision is None
        )
        or (
            status == "succeeded"
            and failure_code is None
            and (
                (loaded is False and loaded_revision is None)
                or (loaded is True and revision_is_positive)
            )
        )
        or (
            status == "failed"
            and isinstance(failure_code, str)
            and failure_code in _SAFE_OPERATION_FAILURE_CODES
            and loaded is False
            and loaded_revision is None
        )
        or (
            status == "superseded"
            and failure_code is None
            and loaded is False
            and loaded_revision is None
        )
    )
    if not valid:
        return (
            "failed",
            "PlanningGenerationFailed",
            False,
            None,
        )
    return status, failure_code, loaded, loaded_revision


def _public_operation(result):
    status, failure_code, loaded, loaded_revision = (
        _public_operation_state(result)
    )
    return {
        "operationId": result.operation_id,
        "status": status,
        "failureCode": failure_code,
        "model": _public_model_summary(result.model),
        "loaded": loaded,
        "loadedDraftRevision": loaded_revision,
    }


def _public_state(result):
    return {
        "projectId": result.project_id,
        "basisStatus": result.basis_status,
        "projectLifecycle": result.project_lifecycle,
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
        "actualProgress": [
            {
                "revisionNumber": item.revision_number,
                "subjectKey": item.subject_key,
                "entityId": item.entity_id,
                "fieldPath": item.field_path,
                "value": item.value,
                "contentHash": item.content_hash,
            }
            for item in result.actual_progress
        ],
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
    return {
        "items": [
            _public_revision(item, include_display_status=True)
            for item in result
        ]
    }


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


@router.post("/projects/{pid}/planning/drafts/{draft_id}/generate")
async def generate_planning_draft(
    pid: str,
    draft_id: str,
    request: Request,
    service=Depends(get_planning_generation_service),
):
    raw_body = await _request_json(request)
    body = _validate(GenerateDraftBody, raw_body)
    result = await service.generate(
        GeneratePlanningDraft(
            project_id=pid,
            draft_id=draft_id,
            draft_revision=body.draftRevision,
            draft_hash=body.draftHash,
            idempotency_key=body.idempotencyKey,
            author_instructions=body.authorInstructions,
        )
    )
    return _public_operation(result)


@router.get(
    "/projects/{pid}/planning/operations/by-idempotency-key/"
    "{idempotency_key}"
)
async def get_planning_operation_by_idempotency_key(
    pid: str,
    idempotency_key: str,
    service=Depends(get_planning_generation_service),
):
    if not is_safe_planning_idempotency_key(idempotency_key):
        raise PlanningRequestInvalid()
    return _public_operation(
        await service.get_operation_by_key(pid, idempotency_key)
    )


@router.get("/projects/{pid}/planning/operations/{operation_id}")
async def get_planning_operation(
    pid: str,
    operation_id: str,
    service=Depends(get_planning_generation_service),
):
    return _public_operation(
        await service.get_operation(pid, operation_id)
    )


__all__ = (
    "PlanningArchived",
    "PlanningConflict",
    "PlanningPreconditionFailed",
    "PlanningRequestInvalid",
    "PlanningResourceNotFound",
    "get_planning_generation_service",
    "get_planning_service",
    "router",
)
