"""Versioned project model-binding HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.database import connection, transaction
from backend.domain.model_bindings import TASK_KEYS, TaskKey
from backend.repositories.model_bindings import ModelBindingRepository
from backend.security.provider_secrets import (
    normalize_provider_secrets,
    sanitize_provider_secret_text,
)
from backend.services.model_bindings import ModelBindingService


router = APIRouter(tags=["model-bindings"])
_service = ModelBindingService(
    ModelBindingRepository(),
    transaction_factory=transaction,
    connection_factory=connection,
)


def get_model_binding_service() -> ModelBindingService:
    return _service


class _StrictBody(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class BindingEntryBody(_StrictBody):
    taskKey: TaskKey
    providerId: str | None = Field(default=None, min_length=1)


class ReplaceBindingsBody(_StrictBody):
    expectedRevision: int = Field(gt=0)
    entries: list[BindingEntryBody]

    @model_validator(mode="after")
    def validate_exact_map(self):
        keys = tuple(entry.taskKey for entry in self.entries)
        if len(keys) != len(TASK_KEYS) or set(keys) != set(TASK_KEYS):
            raise ValueError("entries must contain each task key exactly once")
        return self


def _public_item(item) -> dict:
    return {
        "taskKey": item.task_key,
        "resolutionStatus": item.resolution_status,
        "providerId": item.provider_id,
        "providerNameSnapshot": item.provider_name_snapshot,
        "modelNameSnapshot": item.model_name_snapshot,
    }


def _public_binding(result) -> dict:
    public = {
        "projectId": result.project_id,
        "revision": result.revision,
        "contentHash": result.content_hash,
        "sourceProjectId": result.source_project_id,
        "items": [_public_item(item) for item in result.items],
    }
    secrets = normalize_provider_secrets(
        getattr(result, "redaction_values", ())
    )
    for item in public["items"]:
        for field in (
            "providerId", "providerNameSnapshot", "modelNameSnapshot"
        ):
            if isinstance(item[field], str):
                item[field] = sanitize_provider_secret_text(
                    item[field], secrets
                )
    return public


@router.get("/projects/{pid}/bindings")
async def get_bindings(pid: str, service=Depends(get_model_binding_service)):
    return _public_binding(await service.get_current(pid))


@router.get("/projects/{pid}/bindings/status")
async def get_bindings_status(pid: str, service=Depends(get_model_binding_service)):
    result = await service.get_status(pid)
    return {
        **_public_binding(result),
        "bindingComplete": result.binding_complete,
        "bindingReady": result.binding_ready,
        "reasons": list(result.reasons),
    }


@router.put("/projects/{pid}/bindings")
async def replace_bindings(
    pid: str,
    body: ReplaceBindingsBody,
    service=Depends(get_model_binding_service),
):
    mapping = {entry.taskKey: entry.providerId for entry in body.entries}
    return _public_binding(
        await service.replace_all(pid, body.expectedRevision, mapping)
    )
