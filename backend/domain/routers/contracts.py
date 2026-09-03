"""Recoverable contract-draft, preview, and clone HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from backend.database import connection, transaction
from backend.repositories.contracts import ContractRepository
from backend.http_errors import PublicDomainError
from backend.services.contracts import (
    ContractDraftInput,
    ContractService,
    ConfirmContracts,
    SaveContractDraft,
)


router = APIRouter(tags=["contracts"])
_service = ContractService(
    ContractRepository(), transaction_factory=transaction,
    connection_factory=connection,
)


def get_contract_service() -> ContractService:
    return _service


class ContractRequestInvalid(PublicDomainError):
    status_code = 422
    code = "ContractRequestInvalid"
    message = "Contract request is invalid"


class _StrictBody(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class SaveDraftBody(_StrictBody):
    expectedDraftVersion: int = Field(ge=0)
    draft: ContractDraftInput

    @field_validator("draft", mode="before")
    @classmethod
    def normalize_json_arrays(cls, value):
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        for key in (
            "chapterWordRangePreference", "prohibitedDirections",
            "experienceCardRefs", "corpusSourceRefs", "likes", "dislikes",
        ):
            if isinstance(normalized.get(key), list):
                normalized[key] = tuple(normalized[key])
        if isinstance(normalized.get("corpusSourceRefs"), tuple):
            normalized["corpusSourceRefs"] = tuple(
                {
                    **source,
                    "fragments": tuple(source.get("fragments") or ()),
                }
                if isinstance(source, dict) else source
                for source in normalized["corpusSourceRefs"]
            )
        return normalized


class EmptyBody(_StrictBody):
    pass


class ConfirmBody(_StrictBody):
    idempotencyKey: str = Field(
        min_length=1, max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    expectedDraftVersion: int = Field(gt=0)
    expectedDraftHash: str = Field(pattern=r"^[0-9a-f]{64}$")


def _public_draft(result):
    public = {
        "id": result.id,
        "projectId": result.project_id,
        "selectionRevision": result.selection_revision,
        "baseHeadRevision": result.base_head_revision,
        "draftVersion": result.draft_version,
        "contentHash": result.content_hash,
        "draftStage": result.draft.draftStage,
        "isComplete": result.draft.is_complete,
        "draft": result.draft.model_dump(mode="json"),
        "createdAt": result.created_at,
        "updatedAt": result.updated_at,
    }
    projection = result.document_projection
    if projection is not None:
        def public_style(style):
            return ({
                "id": style.id,
                "revision": style.revision,
                "contentHash": style.content_hash,
                "name": style.name,
                "readingExperience": style.reading_experience,
                "narrativeDistance": style.narrative_distance,
                "sentenceParagraphRhythm": style.sentence_paragraph_rhythm,
            } if style else None)
        public["documentProjection"] = {
            "selectedEngine": (
                projection.selected_engine.model_dump(mode="json")
                if projection.selected_engine else None
            ),
            "primaryStyle": public_style(projection.primary_style),
            "secondaryStyle": public_style(projection.secondary_style),
            "unavailableReasons": list(projection.unavailable_reasons),
        }
    return public


def _public_binding_item(item):
    return {
        "taskKey": item.task_key,
        "resolutionStatus": item.resolution_status,
        "providerId": item.provider_id,
        "providerNameSnapshot": item.provider_name_snapshot,
        "modelNameSnapshot": item.model_name_snapshot,
    }


def _public_preview(result):
    return {
        "projectId": result.project_id,
        "selectionRevision": result.selection_revision,
        "draftVersion": result.draft_version,
        "baseHeadRevision": result.base_head_revision,
        "expectedRevision": result.expected_revision,
        "contractReady": result.contract_ready,
        "reasons": list(result.reasons),
        "seedRef": {
            "id": result.seed_ref.id,
            "revisionId": result.seed_ref.revision_id,
            "contentHash": result.seed_ref.content_hash,
        },
        "engineRef": {
            "id": result.engine_ref.id,
            "batchId": result.engine_ref.batch_id,
            "contentHash": result.engine_ref.content_hash,
        },
        "bindingRef": ({
            "id": result.binding_ref.id,
            "revision": result.binding_ref.revision,
            "contentHash": result.binding_ref.content_hash,
            "items": [_public_binding_item(item) for item in result.binding_ref.items],
        } if result.binding_ref else None),
        "styleRefs": [ref.model_dump(mode="json") for ref in result.style_refs],
        "experienceCardRefs": [
            ref.model_dump(mode="json") for ref in result.experience_card_refs
        ],
        "corpusSourceRefs": [
            ref.model_dump(mode="json") for ref in result.corpus_source_refs
        ],
        "creationContract": (
            result.creation_contract.model_dump(mode="json")
            if result.creation_contract is not None else None
        ),
        "styleContract": (
            result.style_contract.model_dump(mode="json")
            if result.style_contract is not None else None
        ),
        "likes": list(result.likes),
        "dislikes": list(result.dislikes),
        "creationHash": result.creation_hash,
        "styleHash": result.style_hash,
    }


def _public_confirmed(result):
    return {
        "projectId": result.project_id,
        "revision": result.revision,
        "selectionRevision": result.selection_revision,
        "hasContract": True,
        "creationContractId": result.creation_contract_id,
        "styleContractId": result.style_contract_id,
        "contractReady": result.contract_ready,
        "reasons": list(result.reasons),
        "supersededReasons": list(result.superseded_reasons),
        "seedRef": {
            "id": result.seed_ref.id,
            "revisionId": result.seed_ref.revision_id,
            "contentHash": result.seed_ref.content_hash,
        },
        "engineRef": {
            "id": result.engine_ref.id,
            "batchId": result.engine_ref.batch_id,
            "contentHash": result.engine_ref.content_hash,
        },
        "bindingRef": ({
            "id": result.binding_ref.id,
            "revision": result.binding_ref.revision,
            "contentHash": result.binding_ref.content_hash,
            "items": [_public_binding_item(item) for item in result.binding_ref.items],
        } if result.binding_ref else None),
        "styleRefs": [ref.model_dump(mode="json") for ref in result.style_refs],
        "experienceCardRefs": [
            ref.model_dump(mode="json") for ref in result.experience_card_refs
        ],
        "corpusSourceRefs": [
            ref.model_dump(mode="json") for ref in result.corpus_source_refs
        ],
        "creationContract": result.creation_contract.model_dump(mode="json"),
        "styleContract": result.style_contract.model_dump(mode="json"),
        "likes": list(result.likes),
        "dislikes": list(result.dislikes),
        "creationHash": result.creation_hash,
        "styleHash": result.style_hash,
    }


@router.get("/projects/{pid}/contract-draft")
async def get_contract_draft(pid: str, service=Depends(get_contract_service)):
    return _public_draft(await service.get_draft(pid))


@router.put("/projects/{pid}/contract-draft")
async def save_contract_draft(
    pid: str,
    raw_body: object = Body(...),
    service=Depends(get_contract_service),
):
    try:
        body = SaveDraftBody.model_validate(raw_body)
    except ValidationError:
        raise ContractRequestInvalid() from None
    return _public_draft(await service.save_draft(SaveContractDraft(
        project_id=pid,
        expected_draft_version=body.expectedDraftVersion,
        draft=body.draft,
    )))


@router.post("/projects/{pid}/contracts/preview")
async def preview_contracts(
    pid: str,
    raw_body: object = Body(default=None),
    service=Depends(get_contract_service),
):
    try:
        EmptyBody.model_validate({} if raw_body is None else raw_body)
    except ValidationError:
        raise ContractRequestInvalid() from None
    return _public_preview(await service.preview(pid))


@router.post("/projects/{pid}/contracts/{source_revision}/clone")
async def clone_contracts(
    pid: str,
    source_revision: int = Path(gt=0),
    raw_body: object = Body(default=None),
    service=Depends(get_contract_service),
):
    try:
        EmptyBody.model_validate({} if raw_body is None else raw_body)
    except ValidationError:
        raise ContractRequestInvalid() from None
    return _public_draft(await service.clone_revision(pid, source_revision))


@router.post("/projects/{pid}/contracts/confirm", status_code=201)
async def confirm_contracts(
    pid: str,
    raw_body: object = Body(...),
    service=Depends(get_contract_service),
):
    try:
        body = ConfirmBody.model_validate(raw_body)
    except ValidationError:
        raise ContractRequestInvalid() from None
    return _public_confirmed(await service.confirm(ConfirmContracts(
        project_id=pid,
        idempotency_key=body.idempotencyKey,
        expected_draft_version=body.expectedDraftVersion,
        expected_draft_hash=body.expectedDraftHash,
    )))


@router.get("/projects/{pid}/contracts/head")
async def get_contract_head(pid: str, service=Depends(get_contract_service)):
    result = await service.get_head(pid)
    if isinstance(result, dict):
        return {
            "projectId": result["project_id"],
            "revision": result["revision"],
            "hasContract": result["has_contract"],
            "contractReady": result["contract_ready"],
            "reasons": list(result["reasons"]),
        }
    return _public_confirmed(result)


@router.get("/projects/{pid}/contracts/history")
async def get_contract_history(
    pid: str,
    limit: int = Query(default=20, ge=1, le=100),
    before_revision: int | None = Query(
        default=None, alias="beforeRevision", ge=1
    ),
    service=Depends(get_contract_service),
):
    page = await service.history(
        pid, limit=limit, before_revision=before_revision
    )
    return {
        "items": [_public_confirmed(item) for item in page.items],
        "nextBeforeRevision": page.next_before_revision,
    }
