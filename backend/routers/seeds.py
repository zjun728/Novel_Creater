"""Immutable seed CRUD, selection CAS, and readiness HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from backend.database import connection, transaction
from backend.domain.seeds import SeedPayload
from backend.repositories.seeds import SeedRepository
from backend.services.seeds import (
    CreateSeed,
    DeleteSeed,
    EditSeed,
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


def get_seed_service() -> SeedService:
    return _service


class _StrictBody(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class CreateSeedBody(_StrictBody):
    payload: SeedPayload


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


def _public_seed(result: SeedResult) -> dict:
    return {
        "id": result.id,
        "projectId": result.project_id,
        "status": result.status,
        "revision": result.revision,
        "revisionId": result.revision_id,
        "contentHash": result.content_hash,
        "payload": result.payload.model_dump(mode="json"),
        "isSelected": result.is_selected,
        "selectionRevision": result.selection_revision,
    }


def _public_selected(result: SelectedSeedResult) -> dict:
    return {
        "selected": _public_seed(result.selected) if result.selected else None,
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
        await service.create(CreateSeed(project_id=pid, payload=body.payload))
    )


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
