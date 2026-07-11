"""M1 read-only creative seed pool."""

from fastapi import APIRouter

from backend.database import fetchall
from .helpers import convert_rows


router = APIRouter(tags=["seeds"])


@router.get("/projects/{pid}/seeds")
async def list_seeds(pid: str):
    rows = await fetchall(
        """SELECT s.id, s.project_id, s.title, s.premise_json,
                  s.content_hash,
                  CASE WHEN selected.seed_id IS NOT NULL
                       THEN 'selected' ELSE s.status END AS status,
                  s.created_at
           FROM creative_seeds s
           LEFT JOIN project_selected_seeds selected
             ON selected.project_id=s.project_id AND selected.seed_id=s.id
           WHERE s.project_id=%s
           ORDER BY s.created_at DESC, s.id DESC""",
        (pid,),
    )
    return convert_rows(rows)
