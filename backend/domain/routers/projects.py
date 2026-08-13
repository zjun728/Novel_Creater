"""Explicit project lifecycle routes."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict, Field

from backend.database import connection, transaction
from backend.repositories.model_bindings import ModelBindingRepository
from backend.repositories.chapter_outlines import ChapterOutlineRepository
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.repositories.projects import ProjectRepository
from backend.domain.routers.contracts import get_contract_service
from backend.services.model_bindings import ModelBindingService
from backend.services.project_lifecycle import (
    CreateProject,
    ProjectLifecycleService,
)
from .helpers import convert_row, convert_rows


router = APIRouter(tags=["projects"])
_binding_service = ModelBindingService(
    ModelBindingRepository(),
    transaction_factory=transaction,
    connection_factory=connection,
)
_service = ProjectLifecycleService(
    ProjectRepository(
        chapter_session_repository=ChapterSessionRepository(),
        chapter_outline_repository=ChapterOutlineRepository(),
    ),
    transaction,
    connection,
    model_binding_service=_binding_service,
    contract_service=get_contract_service(),
)


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)


class ProjectRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)


class ProjectLifecycleCommand(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    expectedLifecycleRevision: int = Field(ge=0)


def _convert_result(result):
    return convert_row(result.model_dump())


def _convert_results(results):
    return convert_rows([result.model_dump() for result in results])


@router.get("/projects")
async def list_projects():
    return _convert_results(await _service.list_active())


@router.get("/projects/archived")
async def list_archived_projects():
    return _convert_results(await _service.list_archived())


@router.post("/projects")
async def create_project(data: ProjectCreate):
    result = await _service.create(
        CreateProject(
            id=str(uuid4()),
            title=data.title,
        )
    )
    return _convert_result(result)


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    return _convert_result(
        await _service.get(project_id, include_archived=True)
    )


@router.get("/projects/{project_id}/preparation")
async def get_project_preparation(project_id: str):
    return (
        await _service.preparation(project_id)
    ).model_dump(mode="json", by_alias=True)


@router.put("/projects/{project_id}")
async def rename_project(project_id: str, data: ProjectRename):
    return _convert_result(await _service.rename(project_id, data.title))


@router.post("/projects/{project_id}/archive")
async def archive_project(
    project_id: str,
    command: ProjectLifecycleCommand,
):
    return _convert_result(
        await _service.archive(
            project_id,
            command.expectedLifecycleRevision,
        )
    )


@router.post("/projects/{project_id}/restore")
async def restore_project(
    project_id: str,
    command: ProjectLifecycleCommand,
):
    return _convert_result(
        await _service.restore(
            project_id,
            command.expectedLifecycleRevision,
        )
    )


@router.delete(
    "/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def permanently_delete_project(
    project_id: str,
    command: ProjectLifecycleCommand,
):
    await _service.permanently_delete(
        project_id,
        command.expectedLifecycleRevision,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
