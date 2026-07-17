"""Shared active-project reads for repository session boundaries."""

from __future__ import annotations

from backend.http_errors import ProjectArchived


async def read_active_project(session, project_id: str):
    return await session.fetchone(
        "SELECT * FROM projects WHERE id=%s AND archived_at IS NULL",
        (project_id,),
    )


async def lock_active_project(session, project_id: str):
    row = await session.fetchone(
        "SELECT * FROM projects WHERE id=%s FOR UPDATE",
        (project_id,),
    )
    if row is not None and row["archived_at"] is not None:
        raise ProjectArchived()
    return row


async def read_project(session, project_id: str):
    return await session.fetchone(
        "SELECT * FROM projects WHERE id=%s",
        (project_id,),
    )


async def lock_project(session, project_id: str):
    return await session.fetchone(
        "SELECT * FROM projects WHERE id=%s FOR UPDATE",
        (project_id,),
    )
