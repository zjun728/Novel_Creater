"""Writer Core project CRUD backed by explicit repository sessions."""

from __future__ import annotations

from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.database import connection, transaction
from backend.repositories.projects import ProjectRepository
from backend.services.projects import (
    CreateProject,
    ProjectService,
    UpdateProject,
)
from .helpers import convert_row, convert_rows


router = APIRouter(tags=["projects"])
_service = ProjectService(ProjectRepository(), transaction, connection)


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    genre: str = ""
    description: str = ""
    targetWords: int = Field(default=100_000, gt=0)
    targetChapters: int = Field(default=100, gt=0)


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    genre: Optional[str] = None
    description: Optional[str] = None
    targetWords: Optional[int] = Field(default=None, gt=0)
    targetChapters: Optional[int] = Field(default=None, gt=0)
    currentChapter: Optional[int] = Field(default=None, ge=0)
    status: Optional[str] = None


@router.get("/projects")
async def list_projects():
    return convert_rows(await _service.list())


@router.post("/projects")
async def create_project(data: ProjectCreate):
    result = await _service.create(
        CreateProject(
            id=str(uuid4()),
            title=data.title,
            genre=data.genre,
            description=data.description,
            target_words=data.targetWords,
            target_chapters=data.targetChapters,
        )
    )
    return convert_row(result.model_dump())


@router.get("/projects/{pid}")
async def get_project(pid: str):
    row = await _service.get(pid)
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return convert_row(row)


@router.get("/projects/{pid}/content-state")
async def get_project_content_state(pid: str):
    state = await _service.content_state(pid)
    return {
        "seedsCount": state["seeds_count"],
        "canonHeadRevision": state["canon_head_revision"],
        "hasFinalChapters": state["has_final_chapters"],
        "writerEnabled": False,
    }


@router.put("/projects/{pid}")
async def update_project(pid: str, data: ProjectUpdate):
    incoming = data.model_dump(exclude_none=True)
    mapping = {
        "targetWords": "target_words",
        "targetChapters": "target_chapters",
        "currentChapter": "current_chapter",
    }
    command = UpdateProject(
        **{mapping.get(key, key): value for key, value in incoming.items()}
    )
    row = await _service.update(pid, command)
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return convert_row(row)


@router.delete("/projects/{pid}")
async def delete_project(pid: str):
    await _service.delete(pid)
    return {"ok": True}
