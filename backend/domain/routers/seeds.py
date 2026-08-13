"""Immutable seed CRUD, selection CAS, and readiness HTTP routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.database import connection, transaction
from backend.domain.seeds import (
    SeedChatTurn,
    SeedPayload,
    SeedProvenanceSelection,
)
from backend.gateways.seed_provider import SeedProviderGateway
from backend.repositories.seeds import SeedRepository
from backend.services.seed_generation import (
    GenerateSeedInspiration,
    SeedGenerationService,
)
from backend.services.seeds import (
    ArchiveSeed,
    CreateSeed,
    DeleteSeed,
    EditSeed,
    RestoreSeed,
    SeedResult,
    SeedService,
    SelectSeed,
    SelectedSeedResult,
)


router = APIRouter(tags=["seeds"])
_service = SeedService(
    SeedRepository(), transaction_factory=transaction,
    connection_factory=connection,
)
_generation_service = SeedGenerationService(
    SeedRepository(),
    transaction_factory=transaction,
    connection_factory=connection,
    provider_gateway=SeedProviderGateway(),
)


def get_seed_service() -> SeedService:
    return _service


def get_seed_generation_service() -> SeedGenerationService:
    return _generation_service


class _StrictBody(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class CreateSeedBody(_StrictBody):
    payload: SeedPayload
    provenance: SeedProvenanceSelection | None = None
    idempotencyKey: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]{64}$",
    )


class EditSeedBody(_StrictBody):
    payload: SeedPayload
    expectedSeedRevision: int = Field(gt=0)
    expectedSelectionRevision: int = Field(ge=0)


class DeleteSeedBody(_StrictBody):
    expectedSeedRevision: int = Field(gt=0)
    expectedSelectionRevision: int = Field(ge=0)


class SelectSeedBody(_StrictBody):
    seedId: str = Field(min_length=1)
    expectedSeedRevision: int = Field(gt=0)
    expectedSelectionRevision: int = Field(ge=0)


class SeedInspirationBody(_StrictBody):
    transcript: tuple[SeedChatTurn, ...] = Field(min_length=1, max_length=12)
    snapshotIds: tuple[str, ...] = Field(min_length=1, max_length=4)
    analysisId: str = Field(min_length=1, max_length=36)
    idempotencyKey: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]{64}$",
    )

    @field_validator("transcript", "snapshotIds", mode="before")
    @classmethod
    def freeze_sequences(cls, value):
        return tuple(value) if isinstance(value, list) else value

    @field_validator("snapshotIds")
    @classmethod
    def validate_snapshot_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("snapshot IDs must be unique")
        if any(not item or len(item) > 36 for item in value):
            raise ValueError("snapshot ID is invalid")
        return value


def _public_seed(result: SeedResult) -> dict:
    value = {
        "id": result.id,
        "projectId": result.project_id,
        "status": result.status,
        "revision": result.revision,
        "revisionId": result.revision_id,
        "contentHash": result.content_hash,
        "payload": result.payload.model_dump(mode="json"),
        "isSelected": result.is_selected,
        "selectionRevision": result.selection_revision,
        "capabilities": result.capabilities.model_dump(mode="json"),
    }
    if result.provenance is not None:
        value["provenance"] = result.provenance.model_dump(
            mode="json",
            by_alias=True,
        )
    return value


def _public_selected(result: SelectedSeedResult) -> dict:
    return {
        "activeSelection": (
            {
                "projectId": result.active_selection.project_id,
                "selectionRevision": result.active_selection.selection_revision,
                "seedId": result.active_selection.seed_id,
                "seedRevisionId": result.active_selection.seed_revision_id,
                "seedHash": result.active_selection.seed_hash,
                "selectedAt": result.active_selection.selected_at,
                "updatedAt": result.active_selection.updated_at,
                "seed": _public_seed(result.active_selection.seed),
            }
            if result.active_selection
            else None
        ),
        "seedReady": result.seed_ready,
        "contractReady": result.contract_ready,
        "reasons": list(result.reasons),
    }


@router.get("/projects/{pid}/seeds")
async def list_seeds(pid: str, service=Depends(get_seed_service)):
    return [_public_seed(item) for item in await service.list(pid)]


@router.post("/projects/{pid}/seeds")
async def create_seed(
    pid: str, body: CreateSeedBody, service=Depends(get_seed_service)
):
    return _public_seed(
        await service.create(
            CreateSeed(
                project_id=pid,
                payload=body.payload,
                provenance=body.provenance,
                idempotency_key=body.idempotencyKey,
            )
        )
    )


def _inspiration_value(result, name: str):
    return result.get(name) if isinstance(result, dict) else getattr(result, name)


@router.post("/projects/{pid}/seed-inspiration")
async def generate_seed_inspiration(
    pid: Annotated[str, Path(min_length=1, max_length=36)],
    body: SeedInspirationBody,
    service: SeedGenerationService = Depends(get_seed_generation_service),
):
    result = await service.generate(
        GenerateSeedInspiration(
            project_id=pid,
            transcript=body.transcript,
            snapshot_ids=body.snapshotIds,
            analysis_id=body.analysisId,
            idempotency_key=body.idempotencyKey,
        )
    )
    assistant = _inspiration_value(result, "assistant_turn")
    if assistant is not None and not isinstance(assistant, dict):
        assistant = assistant.model_dump(mode="json")
    return {
        "attemptId": _inspiration_value(result, "attempt_id"),
        "status": _inspiration_value(result, "status"),
        "assistantTurn": assistant,
        "resultHash": _inspiration_value(result, "result_hash"),
        "publicErrorCode": _inspiration_value(result, "public_error_code"),
        "createdAt": _inspiration_value(result, "created_at"),
        "completedAt": _inspiration_value(result, "completed_at"),
    }


@router.put("/projects/{pid}/seeds/{seed_id}")
async def edit_seed(
    pid: str, seed_id: str, body: EditSeedBody,
    service=Depends(get_seed_service),
):
    return _public_seed(
        await service.edit(
            EditSeed(
                project_id=pid, seed_id=seed_id, payload=body.payload,
                expected_seed_revision=body.expectedSeedRevision,
                expected_selection_revision=body.expectedSelectionRevision,
            )
        )
    )


@router.delete("/projects/{pid}/seeds/{seed_id}")
async def delete_seed(
    pid: str, seed_id: str, body: DeleteSeedBody,
    service=Depends(get_seed_service),
):
    await service.delete(
        DeleteSeed(
            project_id=pid, seed_id=seed_id,
            expected_seed_revision=body.expectedSeedRevision,
            expected_selection_revision=body.expectedSelectionRevision,
        )
    )
    return {"ok": True}


@router.post("/projects/{pid}/seeds/{seed_id}/archive")
async def archive_seed(
    pid: str, seed_id: str, body: DeleteSeedBody,
    service=Depends(get_seed_service),
):
    return _public_seed(
        await service.archive(
            ArchiveSeed(
                project_id=pid, seed_id=seed_id,
                expected_seed_revision=body.expectedSeedRevision,
                expected_selection_revision=body.expectedSelectionRevision,
            )
        )
    )


@router.post("/projects/{pid}/seeds/{seed_id}/restore")
async def restore_seed(
    pid: str, seed_id: str, body: DeleteSeedBody,
    service=Depends(get_seed_service),
):
    return _public_seed(
        await service.restore(
            RestoreSeed(
                project_id=pid, seed_id=seed_id,
                expected_seed_revision=body.expectedSeedRevision,
                expected_selection_revision=body.expectedSelectionRevision,
            )
        )
    )


@router.get("/projects/{pid}/selected-seed")
async def get_selected_seed(pid: str, service=Depends(get_seed_service)):
    return _public_selected(await service.get_selected(pid))


@router.put("/projects/{pid}/selected-seed")
async def select_seed(
    pid: str, body: SelectSeedBody, service=Depends(get_seed_service)
):
    return _public_seed(
        await service.select(
            SelectSeed(
                project_id=pid, seed_id=body.seedId,
                expected_seed_revision=body.expectedSeedRevision,
                expected_selection_revision=body.expectedSelectionRevision,
            )
        )
    )
