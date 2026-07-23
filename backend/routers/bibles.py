"""Canonical manual creation-Bible HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path, Query
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from backend.database import transaction
from backend.domain.bibles import BiblePayload
from backend.http_errors import PublicDomainError
from backend.repositories.bibles import BibleRepository
from backend.routers.contracts import get_contract_service
from backend.services.bibles import (
    BibleService,
    CloneBibleDraft,
    ConfirmBible,
    SaveBibleDraft,
)


router = APIRouter(tags=["bibles"])
_service = BibleService(
    BibleRepository(),
    contract_service=get_contract_service(),
    transaction_factory=transaction,
)


def get_bible_service() -> BibleService:
    return _service


class BibleRequestInvalid(PublicDomainError):
    status_code = 422
    code = "BibleRequestInvalid"
    message = "Creation Bible request is invalid"


class _StrictBody(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class SaveBibleDraftBody(_StrictBody):
    expectedDraftVersion: int = Field(ge=0)
    draft: BiblePayload

    @field_validator("draft", mode="before")
    @classmethod
    def normalize_json_arrays(cls, value):
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        for field_name in (
            "worldRules",
            "coreCast",
            "factions",
            "longTermConflicts",
            "relationshipDynamics",
            "continuityGuardrails",
            "openDesignQuestions",
        ):
            if isinstance(normalized.get(field_name), list):
                normalized[field_name] = tuple(normalized[field_name])
        return normalized


class CloneBibleDraftBody(_StrictBody):
    sourceDraftId: str | None = Field(
        default=None,
        min_length=1,
        max_length=36,
    )
    sourceRevision: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def require_exactly_one_source(self):
        if (self.sourceDraftId is None) == (self.sourceRevision is None):
            raise ValueError("exactly one clone source is required")
        return self


class ConfirmBibleBody(_StrictBody):
    idempotencyKey: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    expectedDraftVersion: int = Field(gt=0)
    expectedHeadRevision: int = Field(ge=0)


def _public_basis(basis):
    if basis is None:
        return None
    return {
        "selectionRevision": basis.selection_revision,
        "seedId": basis.seed_id,
        "seedRevisionId": basis.seed_revision_id,
        "seedHash": basis.seed_hash,
        "contractRevision": basis.contract_revision,
        "creationContractId": basis.creation_contract_id,
        "creationHash": basis.creation_hash,
        "styleContractId": basis.style_contract_id,
        "styleHash": basis.style_hash,
        "bindingRevisionId": basis.binding_revision_id,
        "bindingHash": basis.binding_hash,
        "policyVersion": basis.policy_version,
    }


def _public_draft(result):
    return {
        "projectId": result.project_id,
        "lifecycle": result.lifecycle,
        "status": result.status,
        "draftId": result.draft_id,
        "draftVersion": result.draft_version,
        "baseHeadRevision": result.base_head_revision,
        "contentHash": result.content_hash,
        "draft": (
            result.payload.model_dump(mode="json")
            if result.payload is not None
            else None
        ),
        "basis": _public_basis(result.basis),
        "canEdit": result.can_edit,
        "canConfirm": result.can_confirm,
        "canClone": result.can_clone,
        "reasons": list(result.reasons),
        "createdAt": result.created_at,
        "updatedAt": result.updated_at,
    }


def _public_revision(result):
    return {
        "projectId": result.project_id,
        "lifecycle": result.lifecycle,
        "status": result.status,
        "bibleRevisionId": result.bible_revision_id,
        "revision": result.revision,
        "contentHash": result.content_hash,
        "bible": result.payload.model_dump(mode="json"),
        "basis": _public_basis(result.basis),
        "canEdit": result.can_edit,
        "canClone": result.can_clone,
        "reasons": list(result.reasons),
        "confirmedAt": result.confirmed_at,
    }


def _public_head(result):
    return {
        "projectId": result.project_id,
        "lifecycle": result.lifecycle,
        "status": result.status,
        "bibleRevisionId": result.bible_revision_id,
        "revision": result.revision,
        "contentHash": result.content_hash,
        "bible": (
            result.payload.model_dump(mode="json")
            if result.payload is not None
            else None
        ),
        "basis": _public_basis(result.basis),
        "canEdit": result.can_edit,
        "canClone": result.can_clone,
        "reasons": list(result.reasons),
        "confirmedAt": result.confirmed_at,
    }


@router.get("/projects/{pid}/bible/head")
async def get_bible_head(
    pid: str,
    service=Depends(get_bible_service),
):
    return _public_head(await service.get_head(pid))


@router.get("/projects/{pid}/bible/draft")
async def get_bible_draft(
    pid: str,
    service=Depends(get_bible_service),
):
    return _public_draft(await service.get_draft(pid))


@router.put("/projects/{pid}/bible/draft")
async def save_bible_draft(
    pid: str,
    raw_body: object = Body(...),
    service=Depends(get_bible_service),
):
    try:
        body = SaveBibleDraftBody.model_validate(raw_body)
    except ValidationError:
        raise BibleRequestInvalid() from None
    return _public_draft(
        await service.save_draft(
            SaveBibleDraft(
                project_id=pid,
                expected_draft_version=body.expectedDraftVersion,
                payload=body.draft,
            )
        )
    )


@router.post("/projects/{pid}/bible/draft/clone")
async def clone_bible_draft(
    pid: str,
    raw_body: object = Body(...),
    service=Depends(get_bible_service),
):
    try:
        body = CloneBibleDraftBody.model_validate(raw_body)
    except ValidationError:
        raise BibleRequestInvalid() from None
    return _public_draft(
        await service.clone_draft(
            CloneBibleDraft(
                project_id=pid,
                source_draft_id=body.sourceDraftId,
                source_revision=body.sourceRevision,
            )
        )
    )


@router.post("/projects/{pid}/bible/confirm", status_code=201)
async def confirm_bible(
    pid: str,
    raw_body: object = Body(...),
    service=Depends(get_bible_service),
):
    try:
        body = ConfirmBibleBody.model_validate(raw_body)
    except ValidationError:
        raise BibleRequestInvalid() from None
    return _public_revision(
        await service.confirm(
            ConfirmBible(
                project_id=pid,
                idempotency_key=body.idempotencyKey,
                expected_draft_version=body.expectedDraftVersion,
                expected_head_revision=body.expectedHeadRevision,
            )
        )
    )


@router.get("/projects/{pid}/bible/history")
async def get_bible_history(
    pid: str,
    limit: int = Query(default=20, ge=1, le=100),
    before_revision: int | None = Query(
        default=None,
        alias="beforeRevision",
        ge=1,
    ),
    service=Depends(get_bible_service),
):
    page = await service.history(
        pid,
        limit=limit,
        before_revision=before_revision,
    )
    return {
        "items": [_public_revision(item) for item in page.items],
        "nextBeforeRevision": page.next_before_revision,
    }


@router.get("/projects/{pid}/bible/history/{revision}")
async def get_bible_history_revision(
    pid: str,
    revision: int = Path(gt=0),
    service=Depends(get_bible_service),
):
    return _public_revision(
        await service.get_history_revision(pid, revision)
    )


__all__ = (
    "BibleRequestInvalid",
    "get_bible_service",
    "router",
)
