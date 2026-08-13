"""Read-only Canon and projection product routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.database import fetchall, fetchone
from backend.domain.canon import normalize_name, resolve_alias
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from .helpers import convert_row, convert_rows


router = APIRouter(tags=["canon"])


async def _head(project_id: str):
    row = await fetchone(
        """SELECT canon_revision_number, projection_revision_number, content_hash
           FROM projection_heads WHERE project_id=%s""",
        (project_id,),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Project head not found")
    return row


def _public_head(project_id: str, row) -> dict:
    return {
        "projectId": project_id,
        "canonRevisionNumber": row["canon_revision_number"],
        "projectionRevisionNumber": row["projection_revision_number"],
        "contentHash": row["content_hash"],
    }


async def _synced_head(project_id: str):
    row = await _head(project_id)
    if row["canon_revision_number"] != row["projection_revision_number"]:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "projection_out_of_sync",
                "canonHeadRevision": row["canon_revision_number"],
                "projectionHeadRevision": row["projection_revision_number"],
            },
        )
    return row


@router.get("/projects/{project_id}/writer-core/state")
async def writer_core_state(project_id: str):
    row = await _head(project_id)
    canon_revision = row["canon_revision_number"]
    projection_revision = row["projection_revision_number"]
    return {
        "projectId": project_id,
        "schemaVersion": EXPECTED_SCHEMA_VERSION,
        "canonHeadRevision": canon_revision,
        "projectionHeadRevision": projection_revision,
        "projectionInSync": canon_revision == projection_revision,
    }


@router.get("/projects/{project_id}/canon/head")
async def canon_head(project_id: str):
    row = await _head(project_id)
    return {
        "projectId": project_id,
        "revisionNumber": row["canon_revision_number"],
        "contentHash": row["content_hash"],
    }


@router.get("/projects/{project_id}/canon/revisions")
async def canon_revisions(project_id: str):
    return convert_rows(
        await fetchall(
            """SELECT * FROM canon_revisions WHERE project_id=%s
               ORDER BY revision_number DESC""",
            (project_id,),
        )
    )


@router.get("/projects/{project_id}/canon/entities")
async def canon_entities(project_id: str):
    return convert_rows(
        await fetchall(
            """SELECT * FROM canon_entities WHERE project_id=%s
               ORDER BY entity_type, normalized_name, id""",
            (project_id,),
        )
    )


@router.get("/projects/{project_id}/canon/entities/{entity_id}")
async def canon_entity(project_id: str, entity_id: str):
    row = await fetchone(
        "SELECT * FROM canon_entities WHERE project_id=%s AND id=%s",
        (project_id, entity_id),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Canon entity not found")
    return convert_row(row)


@router.get("/projects/{project_id}/canon/events")
async def canon_events(project_id: str):
    return convert_rows(
        await fetchall(
            """SELECT * FROM canon_events WHERE project_id=%s
               ORDER BY revision_number, event_order, id""",
            (project_id,),
        )
    )


@router.get("/projects/{project_id}/canon/aliases/resolve")
async def alias_resolve(project_id: str, name: str = Query(min_length=1)):
    normalized = normalize_name(name)
    rows = await fetchall(
        """SELECT entity_id, normalized_alias FROM entity_aliases
           WHERE project_id=%s AND normalized_alias=%s ORDER BY entity_id""",
        (project_id, normalized),
    )
    result = resolve_alias(normalized, rows)
    return {"status": result.status, "entityIds": list(result.entity_ids)}


@router.get("/projects/{project_id}/projections/head")
async def projection_head(project_id: str):
    return _public_head(project_id, await _head(project_id))


async def _projection_rows(project_id: str, table: str):
    head = await _synced_head(project_id)
    return convert_rows(
        await fetchall(
            f"""SELECT * FROM {table}
                 WHERE project_id=%s AND revision_number=%s ORDER BY id""",
            (project_id, head["projection_revision_number"]),
        )
    )


@router.get("/projects/{project_id}/projections/current-state")
async def current_state(project_id: str):
    return await _projection_rows(project_id, "current_state_projections")


@router.get("/projects/{project_id}/projections/memories")
async def memories(project_id: str):
    return await _projection_rows(project_id, "memory_views")


@router.get("/projects/{project_id}/projections/arcs")
async def arcs(project_id: str):
    return await _projection_rows(project_id, "arc_projections")


@router.get("/projects/{project_id}/projections/plot-threads")
async def plot_threads(project_id: str):
    return await _projection_rows(project_id, "plot_thread_projections")
