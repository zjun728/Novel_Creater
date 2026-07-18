"""Story-engine batch routes registered independently from the global app."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.database import connection, transaction
from backend.domain.story_engines import StoryEngineOption, validate_three_options
from backend.gateways.story_engine_provider import StoryEngineProviderGateway
from backend.repositories.story_engines import StoryEngineRepository
from backend.services.story_engines import (
    CreateManualStoryEngineBatch,
    ReserveStoryEngineBatch,
    StoryEngineService,
)


router = APIRouter(tags=["story-engines"])
_service = StoryEngineService(
    StoryEngineRepository(),
    transaction_factory=transaction,
    connection_factory=connection,
    provider_gateway=StoryEngineProviderGateway(),
)


def get_story_engine_service() -> StoryEngineService:
    return _service


class _StrictBody(BaseModel):
    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", str_strip_whitespace=True
    )


class ReserveBatchBody(_StrictBody):
    idempotencyKey: str = Field(min_length=1, max_length=64)


class ManualBatchBody(_StrictBody):
    idempotencyKey: str = Field(min_length=1, max_length=64)
    options: tuple[StoryEngineOption, ...] = Field(min_length=3, max_length=3)

    @field_validator("options", mode="before")
    @classmethod
    def normalize_json_collections(cls, value):
        if not isinstance(value, list):
            return value
        normalized = []
        tuple_fields = {
            "ensembleRoles", "satisfactionSources", "longFormVariation", "risks"
        }
        for item in value:
            if not isinstance(item, dict):
                normalized.append(item)
                continue
            normalized.append(
                {
                    key: tuple(field_value)
                    if key in tuple_fields and isinstance(field_value, list)
                    else field_value
                    for key, field_value in item.items()
                }
            )
        return tuple(normalized)

    @model_validator(mode="after")
    def validate_distinct_options(self):
        validate_three_options(self.options)
        return self


def _public_option(option) -> dict:
    return {
        "id": option.id,
        "optionOrder": option.option_order,
        "contentHash": option.content_hash,
        "payload": option.payload.model_dump(mode="json"),
    }


def _public_batch(result) -> dict:
    return {
        "id": result.id,
        "projectId": result.project_id,
        "sourceType": result.source_type,
        "selectionRevision": result.selection_revision,
        "seedId": result.seed_id,
        "seedRevisionId": result.seed_revision_id,
        "seedHash": result.seed_hash,
        "bindingRevisionId": result.binding_revision_id,
        "bindingHash": result.binding_hash,
        "providerId": result.provider_id,
        "modelNameSnapshot": result.model_name_snapshot,
        "idempotencyKey": result.idempotency_key,
        "requestHash": result.request_hash,
        "status": result.status,
        "publicErrorCode": result.public_error_code,
        "createdAt": result.created_at,
        "finishedAt": result.finished_at,
        "options": [_public_option(option) for option in result.options],
    }


def _public_recoverable_batch(result) -> dict:
    return {
        "id": result.id,
        "status": result.status,
        "publicErrorCode": result.public_error_code,
        "createdAt": result.created_at,
        "finishedAt": result.finished_at,
    }


@router.post("/projects/{pid}/story-engine-batches", status_code=201)
async def reserve_batch(
    pid: str,
    body: ReserveBatchBody,
    service=Depends(get_story_engine_service),
):
    return _public_batch(
        await service.generate_provider(
            ReserveStoryEngineBatch(pid, body.idempotencyKey)
        )
    )


@router.post("/projects/{pid}/story-engine-batches/manual", status_code=201)
async def create_manual_batch(
    pid: str,
    body: ManualBatchBody,
    service=Depends(get_story_engine_service),
):
    return _public_batch(
        await service.create_manual(
            CreateManualStoryEngineBatch(pid, body.idempotencyKey, body.options)
        )
    )


@router.get("/projects/{pid}/story-engine-batches/recoverable")
async def list_recoverable_batches(
    pid: str,
    service=Depends(get_story_engine_service),
):
    return {
        "items": [
            _public_recoverable_batch(item)
            for item in await service.list_recoverable(pid)
        ]
    }


@router.get("/projects/{pid}/story-engine-batches/{batch_id}")
async def get_batch(
    pid: str,
    batch_id: str,
    service=Depends(get_story_engine_service),
):
    return _public_batch(await service.get(pid, batch_id))


@router.post("/projects/{pid}/story-engine-batches/{batch_id}/reconcile")
async def reconcile_batch(
    pid: str,
    batch_id: str,
    service=Depends(get_story_engine_service),
):
    return _public_batch(await service.reconcile(pid, batch_id))
