"""项目分卷 / 阶段规划。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from database import fetchone, fetchall, execute
from .helpers import convert_row, convert_rows, to_snake, touch_project
import json
import time
import uuid

router = APIRouter(tags=["volumes"])


class VolumeBase(BaseModel):
    volumeNum: int = 1
    title: str = ""
    startChapter: int = 1
    endChapter: int = 1
    targetWords: int = 0
    coreGoal: str = ""
    mainConflict: str = ""
    keyCharacters: list[str] = []
    summary: str = ""
    foreshadowingPlan: list[str] = []
    unresolvedItems: list[str] = []
    handoffPoint: str = ""
    status: str = "planned"


class VolumeUpdate(BaseModel):
    volumeNum: Optional[int] = None
    title: Optional[str] = None
    startChapter: Optional[int] = None
    endChapter: Optional[int] = None
    targetWords: Optional[int] = None
    coreGoal: Optional[str] = None
    mainConflict: Optional[str] = None
    keyCharacters: Optional[list[str]] = None
    summary: Optional[str] = None
    foreshadowingPlan: Optional[list[str]] = None
    unresolvedItems: Optional[list[str]] = None
    handoffPoint: Optional[str] = None
    status: Optional[str] = None


class VolumeAuditSave(BaseModel):
    report: dict


class VolumeSummarySave(BaseModel):
    report: dict


@router.get("/projects/{pid}/volumes")
async def list_volumes(pid: str):
    rows = await fetchall(
        "SELECT * FROM project_volumes WHERE project_id=%s ORDER BY volume_num, start_chapter",
        (pid,),
    )
    return convert_rows(rows)


@router.get("/projects/{pid}/volumes/{vid}/context")
async def get_volume_context(pid: str, vid: str):
    volume = await fetchone("SELECT * FROM project_volumes WHERE project_id=%s AND id=%s", (pid, vid))
    if not volume:
        raise HTTPException(404, "分卷不存在")

    chapter_rows = await fetchall(
        """
        SELECT
          c.*,
          v.title AS final_title,
          v.content AS final_content,
          v.updated_at AS final_updated_at
        FROM chapters c
        LEFT JOIN chapter_versions v ON c.final_version_id = v.id
        WHERE c.project_id=%s AND c.chapter_num BETWEEN %s AND %s
        ORDER BY c.chapter_num
        """,
        (pid, volume["start_chapter"], volume["end_chapter"]),
    )
    chapters = convert_rows(chapter_rows)
    return {
        "volume": convert_row(volume),
        "chapters": chapters,
        "stats": {
            "chapterCount": len(chapters),
            "finalizedCount": len([c for c in chapters if c.get("finalVersionId")]),
            "totalWords": sum(int(c.get("wordCount") or 0) for c in chapters),
        },
    }


@router.post("/projects/{pid}/volumes")
async def create_volume(pid: str, data: VolumeBase):
    _validate_range(data.startChapter, data.endChapter)
    now = int(time.time() * 1000)
    vid = str(uuid.uuid4())
    await execute(
        """
        INSERT INTO project_volumes (
          id, project_id, volume_num, title, start_chapter, end_chapter,
          target_words, core_goal, main_conflict, key_characters, summary,
          foreshadowing_plan, unresolved_items, handoff_point,
          status, created_at, updated_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            vid,
            pid,
            data.volumeNum,
            data.title,
            data.startChapter,
            data.endChapter,
            data.targetWords,
            data.coreGoal,
            data.mainConflict,
            json.dumps(data.keyCharacters or [], ensure_ascii=False),
            data.summary,
            json.dumps(data.foreshadowingPlan or [], ensure_ascii=False),
            json.dumps(data.unresolvedItems or [], ensure_ascii=False),
            data.handoffPoint,
            data.status,
            now,
            now,
        ),
    )
    await touch_project(pid)
    return convert_row(await fetchone("SELECT * FROM project_volumes WHERE id=%s", (vid,)))


@router.put("/projects/{pid}/volumes/{vid}/audit")
async def save_volume_audit(pid: str, vid: str, data: VolumeAuditSave):
    existing = await fetchone("SELECT id FROM project_volumes WHERE project_id=%s AND id=%s", (pid, vid))
    if not existing:
        raise HTTPException(404, "分卷不存在")

    now = int(time.time() * 1000)
    await execute(
        """
        UPDATE project_volumes
        SET audit_report=%s, audit_updated_at=%s, updated_at=%s
        WHERE project_id=%s AND id=%s
        """,
        (json.dumps(data.report, ensure_ascii=False), now, now, pid, vid),
    )
    await touch_project(pid)
    return convert_row(await fetchone("SELECT * FROM project_volumes WHERE id=%s", (vid,)))


@router.put("/projects/{pid}/volumes/{vid}/summary-report")
async def save_volume_summary(pid: str, vid: str, data: VolumeSummarySave):
    existing = await fetchone("SELECT * FROM project_volumes WHERE project_id=%s AND id=%s", (pid, vid))
    if not existing:
        raise HTTPException(404, "分卷不存在")

    now = int(time.time() * 1000)
    summary_text = _pick_summary_text(data.report) or existing.get("summary") or ""
    await execute(
        """
        UPDATE project_volumes
        SET stage_summary_report=%s, summary=%s, summary_updated_at=%s, updated_at=%s
        WHERE project_id=%s AND id=%s
        """,
        (json.dumps(data.report, ensure_ascii=False), summary_text, now, now, pid, vid),
    )
    await touch_project(pid)
    return convert_row(await fetchone("SELECT * FROM project_volumes WHERE id=%s", (vid,)))


@router.put("/projects/{pid}/volumes/{vid}")
async def update_volume(pid: str, vid: str, data: VolumeUpdate):
    existing = await fetchone("SELECT * FROM project_volumes WHERE project_id=%s AND id=%s", (pid, vid))
    if not existing:
        raise HTTPException(404, "分卷不存在")

    incoming = data.dict(exclude_none=True)
    if "startChapter" in incoming or "endChapter" in incoming:
        start = incoming.get("startChapter", existing.get("start_chapter"))
        end = incoming.get("endChapter", existing.get("end_chapter"))
        _validate_range(start, end)

    sets, args = [], []
    for key, value in incoming.items():
        sets.append(f"{to_snake(key)}=%s")
        if key in ("keyCharacters", "foreshadowingPlan", "unresolvedItems"):
            value = json.dumps(value or [], ensure_ascii=False)
        args.append(value)

    if not sets:
        return convert_row(existing)

    sets.append("updated_at=%s")
    args.append(int(time.time() * 1000))
    args.extend([pid, vid])
    await execute(
        f"UPDATE project_volumes SET {', '.join(sets)} WHERE project_id=%s AND id=%s",
        args,
    )
    await touch_project(pid)
    return convert_row(await fetchone("SELECT * FROM project_volumes WHERE id=%s", (vid,)))


@router.delete("/projects/{pid}/volumes/{vid}")
async def delete_volume(pid: str, vid: str):
    volume = await fetchone("SELECT * FROM project_volumes WHERE project_id=%s AND id=%s", (pid, vid))
    if not volume:
        raise HTTPException(404, "分卷不存在")
    chapter_count = await _count(
        "SELECT COUNT(*) AS c FROM chapters WHERE project_id=%s AND chapter_num BETWEEN %s AND %s",
        (pid, volume["start_chapter"], volume["end_chapter"]),
    )
    if chapter_count > 0:
        raise HTTPException(
            409,
            f"当前分卷范围内已有 {chapter_count} 个章节，不能直接删除分卷。请先移动或删除这些章节，再删除分卷。",
        )
    await execute("DELETE FROM project_volumes WHERE project_id=%s AND id=%s", (pid, vid))
    await touch_project(pid)
    return {"ok": True}


def _pick_summary_text(report: dict):
    for key in ("compactSummary", "stageSummary", "handoffSummary"):
        value = report.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


async def _count(sql: str, args: tuple) -> int:
    row = await fetchone(sql, args)
    return int((row or {}).get("c") or 0)


def _validate_range(start: int, end: int):
    if start < 1 or end < 1 or end < start:
        raise HTTPException(400, "分卷章节范围不合法")
