"""Shared active-project reads for repository session boundaries."""

from __future__ import annotations


async def read_active_project(session, project_id: str):
    return await session.fetchone(
        "SELECT * FROM projects WHERE id=%s AND status<>'archived'",
        (project_id,),
    )


async def lock_active_project(session, project_id: str):
    return await session.fetchone(
        """SELECT * FROM projects
           WHERE id=%s AND status<>'archived' FOR UPDATE""",
        (project_id,),
    )
