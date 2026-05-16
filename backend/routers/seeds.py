"""创作种子管理"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from database import fetchone, fetchall, execute
from .helpers import convert_row, convert_rows, to_snake
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
    status: Optional[str] = None

@router.get("/projects/{pid}/seeds")
async def list_seeds(pid: str):
    rows = await fetchall("SELECT * FROM creative_seeds WHERE project_id=%s ORDER BY created_at DESC", (pid,))
    return convert_rows(rows)

@router.post("/projects/{pid}/seeds")
async def create_seed(pid: str, data: SeedCreate):
    now = int(time.time() * 1000)
    sid = str(uuid.uuid4())
    await execute("""INSERT INTO creative_seeds (id, project_id, title, genre, logline, protagonist,
             desire, core_conflict, world_pressure, opening_hook, emotional_promise,
             differentiation, style_target, source, risk_notes, status, created_at)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'candidate',%s)""",
             (sid, pid, data.title, data.genre, data.logline, data.protagonist,
              data.desire, data.coreConflict, data.worldPressure, data.openingHook,
              data.emotionalPromise, data.differentiation, data.styleTarget,
              data.source, data.riskNotes, now))
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
    return convert_row(await fetchone("SELECT * FROM creative_seeds WHERE id=%s", (sid,)))

@router.delete("/projects/{pid}/seeds/{sid}")
async def delete_seed(pid: str, sid: str):
    await execute("DELETE FROM creative_seeds WHERE id=%s", (sid,))
    return {"ok": True}
