from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.database import connection, transaction
from backend.http_errors import PublicDomainError
from backend.repositories.planning import PlanningRepository
from backend.services.planning import (
    CreateInitialPlan,
    PlanningConflict,
    PlanningNotFound,
    PlanningPreconditionFailed,
    PlanningRequestInvalid as ServicePlanningRequestInvalid,
    PlanningService,
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
    message = "Planning project was not found"


class PlanningStateConflict(PublicDomainError):
    status_code = 409
    code = "PlanningConflict"
    message = "Planning state changed; refresh and retry"


class PlanningPreconditionUnavailable(PublicDomainError):
    status_code = 422
    code = "PlanningPreconditionFailed"
    message = "A confirmed creation contract is required before planning"


class _StrictBody(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class CreateInitialPlanBody(_StrictBody):
    expectedContractRevision: int = Field(ge=1)
    idempotencyKey: str = Field(
        min_length=1, max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )


def _raise_public(error: Exception):
    if isinstance(error, PlanningNotFound):
        raise PlanningResourceNotFound() from None
    if isinstance(error, ServicePlanningRequestInvalid):
        raise PlanningRequestInvalid() from None
    if isinstance(error, PlanningConflict):
        raise PlanningStateConflict() from None
    if isinstance(error, PlanningPreconditionFailed):
        raise PlanningPreconditionUnavailable() from None
    raise error


def _volume(volume):
    if volume is None:
        return None
    return {
        "id": volume.id,
        "projectId": volume.project_id,
        "volumeNum": volume.volume_num,
        "title": volume.title,
        "direction": dict(volume.direction),
        "revision": volume.revision,
        "status": volume.status,
    }


def _block(block):
    if block is None:
        return None
    return {
        "id": block.id,
        "projectId": block.project_id,
        "volumePlanId": block.volume_plan_id,
        "blockNum": block.block_num,
        "title": block.title,
        "goal": dict(block.goal),
        "revision": block.revision,
        "status": block.status,
    }


def _stage(stage):
    return {
        "id": stage.id,
        "projectId": stage.project_id,
        "storyBlockId": stage.story_block_id,
        "stageOrder": stage.stage_order,
        "title": stage.title,
        "plan": dict(stage.plan),
        "revision": stage.revision,
        "status": stage.status,
    }


def _task(task):
    return {
        "id": task.id,
        "projectId": task.project_id,
        "storyStageId": task.story_stage_id,
        "taskOrder": task.task_order,
        "task": dict(task.task),
        "revision": task.revision,
        "status": task.status,
    }


def _public_state(state):
    return {
        "projectId": state.project_id,
        "hasPlanning": state.has_planning,
        "planningReady": state.planning_ready,
        "contractRevision": state.contract_revision,
        "activeVolume": _volume(state.active_volume),
        "activeBlock": _block(state.active_block),
        "stages": [_stage(stage) for stage in state.stages],
        "sceneTasks": [_task(task) for task in state.scene_tasks],
        "manifestHash": state.manifest_hash,
    }


@router.get("/projects/{pid}/planning")
async def get_planning(pid: str, service=Depends(get_planning_service)):
    try:
        return _public_state(await service.get_state(pid))
    except Exception as error:
        _raise_public(error)


@router.post("/projects/{pid}/planning/initial", status_code=201)
async def create_initial_planning(
    pid: str,
    raw_body: object = Body(...),
    service=Depends(get_planning_service),
):
    try:
        body = CreateInitialPlanBody.model_validate(raw_body)
        state = await service.create_initial_plan(CreateInitialPlan(
            project_id=pid,
            expected_contract_revision=body.expectedContractRevision,
            idempotency_key=body.idempotencyKey,
        ))
    except ValidationError:
        raise PlanningRequestInvalid() from None
    except Exception as error:
        _raise_public(error)
    return _public_state(state)
