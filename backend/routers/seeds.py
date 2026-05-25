"""创作种子管理"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from database import fetchone, fetchall, execute
from .helpers import convert_row, convert_rows, to_snake, touch_project
import uuid, time

router = APIRouter(tags=["seeds"])

class SeedCreate(BaseModel):
    title: str = ""
    genre: str = ""
    logline: str = ""
    protagonist: str = ""
    desire: str = ""
    coreConflict: str = ""
    worldPressure: str = ""
    openingHook: str = ""
    emotionalPromise: str = ""
    differentiation: str = ""
    styleTarget: str = ""
    source: str = "user"
    riskNotes: str = ""
    endingAnchor: str = ""

class SeedUpdate(BaseModel):
    title: Optional[str] = None
    genre: Optional[str] = None
    logline: Optional[str] = None
    protagonist: Optional[str] = None
    desire: Optional[str] = None
    coreConflict: Optional[str] = None
    worldPressure: Optional[str] = None
    openingHook: Optional[str] = None
    emotionalPromise: Optional[str] = None
    differentiation: Optional[str] = None
    styleTarget: Optional[str] = None
    riskNotes: Optional[str] = None
    endingAnchor: Optional[str] = None
    status: Optional[str] = None

def _has_text(value):
    return value is not None and str(value).strip() != ""

def _validate_seed_completeness(data: SeedCreate):
    core_fields = [
        data.logline,
        data.protagonist,
        data.desire,
        data.coreConflict,
        data.openingHook,
        data.emotionalPromise,
    ]
    core_count = sum(1 for value in core_fields if _has_text(value))
    if not (_has_text(data.title) or _has_text(data.logline)) or not _has_text(data.genre) or core_count < 3:
        raise HTTPException(
            400,
            "种子内容不完整：至少需要题材，并包含一句话、主角、欲望、核心矛盾、开局钩子或情绪价值中的 3 项",
        )

@router.get("/projects/{pid}/seeds")
async def list_seeds(pid: str):
    rows = await fetchall("SELECT * FROM creative_seeds WHERE project_id=%s ORDER BY created_at DESC", (pid,))
    return convert_rows(rows)

@router.post("/projects/{pid}/seeds")
async def create_seed(pid: str, data: SeedCreate):
    _validate_seed_completeness(data)
    now = int(time.time() * 1000)
    sid = str(uuid.uuid4())
    await execute("""INSERT INTO creative_seeds (id, project_id, title, genre, logline, protagonist,
             desire, core_conflict, world_pressure, opening_hook, emotional_promise,
             differentiation, style_target, source, risk_notes, ending_anchor, status, created_at)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'candidate',%s)""",
             (sid, pid, data.title, data.genre, data.logline, data.protagonist,
              data.desire, data.coreConflict, data.worldPressure, data.openingHook,
              data.emotionalPromise, data.differentiation, data.styleTarget,
              data.source, data.riskNotes, data.endingAnchor, now))
    await touch_project(pid)
    return convert_row(await fetchone("SELECT * FROM creative_seeds WHERE id=%s", (sid,)))

@router.put("/projects/{pid}/seeds/{sid}")
async def update_seed(pid: str, sid: str, data: SeedUpdate):
    sets, args = [], []
    for k, v in data.dict(exclude_none=True).items():
        sets.append(f"{to_snake(k)}=%s")
        args.append(v)
    if not sets:
        return convert_row(await fetchone("SELECT * FROM creative_seeds WHERE id=%s", (sid,)))
    args.append(sid)
    await execute(f"UPDATE creative_seeds SET {', '.join(sets)} WHERE id=%s", args)
    await touch_project(pid)
    return convert_row(await fetchone("SELECT * FROM creative_seeds WHERE id=%s", (sid,)))

@router.delete("/projects/{pid}/seeds/{sid}")
async def delete_seed(pid: str, sid: str):
    await execute("DELETE FROM creative_seeds WHERE id=%s", (sid,))
    await touch_project(pid)
    return {"ok": True}

@router.delete("/projects/{pid}/seeds")
async def clear_seeds(pid: str):
    await execute("DELETE FROM creative_seeds WHERE project_id=%s", (pid,))
    await touch_project(pid)
    return {"ok": True}
