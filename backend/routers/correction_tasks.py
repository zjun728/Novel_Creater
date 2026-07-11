"""审稿纠偏任务。"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from backend.database import fetchone, fetchall, execute
from .helpers import convert_row, convert_rows, touch_project
import json
import time
import uuid

router = APIRouter(tags=["correction-tasks"])


class CorrectionTaskCreate(BaseModel):
    sourceType: str = "global_audit"
    sourceId: Optional[str] = None
    targetModule: str = "general"
    title: str = ""
    description: str = ""
    severity: str = "minor"
    issueType: str = "general"
    chapterRefs: list = []
    relatedItems: list = []
    suggestedAction: str = ""
    status: str = "pending"
    metadata: dict = {}


class CorrectionTaskUpdate(BaseModel):
    targetModule: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    issueType: Optional[str] = None
    chapterRefs: Optional[list] = None
    relatedItems: Optional[list] = None
    suggestedAction: Optional[str] = None
    status: Optional[str] = None
    metadata: Optional[dict] = None


@router.get("/projects/{pid}/correction-tasks")
async def list_correction_tasks(pid: str, status: str = Query("", alias="status")):
    if status:
        rows = await fetchall(
            """
            SELECT * FROM correction_tasks
            WHERE project_id=%s AND status=%s
            ORDER BY FIELD(severity, 'critical', 'major', 'minor', 'suggestion'), updated_at DESC
            """,
            (pid, status),
        )
    else:
        rows = await fetchall(
            """
            SELECT * FROM correction_tasks
            WHERE project_id=%s
            ORDER BY FIELD(status, 'pending', 'accepted', 'in_progress', 'done', 'ignored', 'rejected'),
                     FIELD(severity, 'critical', 'major', 'minor', 'suggestion'),
                     updated_at DESC
            """,
            (pid,),
        )
    return convert_rows(rows)


@router.post("/projects/{pid}/correction-tasks")
async def create_correction_task(pid: str, data: CorrectionTaskCreate):
    now = int(time.time() * 1000)
    task_id = str(uuid.uuid4())
    await execute(
        """
        INSERT INTO correction_tasks (
          id, project_id, source_type, source_id, target_module, title, description,
          severity, issue_type, chapter_refs, related_items, suggested_action,
          status, metadata, created_at, updated_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            task_id,
            pid,
            data.sourceType,
            data.sourceId,
            data.targetModule,
            data.title,
            data.description,
            data.severity,
            data.issueType,
            json.dumps(data.chapterRefs or [], ensure_ascii=False),
            json.dumps(data.relatedItems or [], ensure_ascii=False),
            data.suggestedAction,
            data.status,
            json.dumps(data.metadata or {}, ensure_ascii=False),
            now,
            now,
        ),
    )
    await touch_project(pid)
    return convert_row(await fetchone("SELECT * FROM correction_tasks WHERE id=%s", (task_id,)))


@router.post("/projects/{pid}/correction-tasks/bulk")
async def create_correction_tasks_bulk(pid: str, data: list[CorrectionTaskCreate]):
    created = []
    for item in data:
        created.append(await create_correction_task(pid, item))
    return created


@router.put("/projects/{pid}/correction-tasks/{task_id}")
async def update_correction_task(pid: str, task_id: str, data: CorrectionTaskUpdate):
    existing = await fetchone("SELECT * FROM correction_tasks WHERE project_id=%s AND id=%s", (pid, task_id))
    if not existing:
        raise HTTPException(404, "纠偏任务不存在")

    field_map = {
        "targetModule": "target_module",
        "title": "title",
        "description": "description",
        "severity": "severity",
        "issueType": "issue_type",
        "chapterRefs": "chapter_refs",
        "relatedItems": "related_items",
        "suggestedAction": "suggested_action",
        "status": "status",
        "metadata": "metadata",
    }
    incoming = data.dict(exclude_none=True)
    sets, args = [], []
    for key, value in incoming.items():
        col = field_map[key]
        sets.append(f"{col}=%s")
        if key in ("chapterRefs", "relatedItems", "metadata"):
            value = json.dumps(value or ([] if key != "metadata" else {}), ensure_ascii=False)
        args.append(value)

    if not sets:
        return convert_row(existing)

    sets.append("updated_at=%s")
    args.append(int(time.time() * 1000))
    args.extend([pid, task_id])
    await execute(
        f"UPDATE correction_tasks SET {', '.join(sets)} WHERE project_id=%s AND id=%s",
        args,
    )
    await touch_project(pid)
    return convert_row(await fetchone("SELECT * FROM correction_tasks WHERE id=%s", (task_id,)))


@router.delete("/projects/{pid}/correction-tasks/{task_id}")
async def delete_correction_task(pid: str, task_id: str):
    await execute("DELETE FROM correction_tasks WHERE project_id=%s AND id=%s", (pid, task_id))
    await touch_project(pid)
    return {"ok": True}
