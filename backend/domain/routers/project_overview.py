"""Read-only author-facing project overview route."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.database import connection
from backend.repositories.project_overview import ProjectOverviewRepository
from backend.services.project_overview import ProjectOverviewService


router = APIRouter(tags=["project-overview"])
_service = ProjectOverviewService(
    ProjectOverviewRepository(),
    connection_factory=connection,
)


def get_project_overview_service() -> ProjectOverviewService:
    return _service


@router.get("/projects/{project_id:path}/overview")
async def get_project_overview(
    project_id: str,
    service: Annotated[
        ProjectOverviewService,
        Depends(get_project_overview_service),
    ],
):
    return (await service.get(project_id)).model_dump(
        mode="json",
        by_alias=True,
    )


__all__ = ("get_project_overview_service", "router")
