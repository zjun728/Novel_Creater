"""项目 CRUD"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from database import fetchone, fetchall, execute
from .helpers import convert_row, convert_rows, to_snake
import uuid, time

router = APIRouter(tags=["projects"])

class ProjectCreate(BaseModel):
    title: str
    genre: str = ""
    description: str = ""
    targetWords: int = 100000
    targetChapters: int = 100

class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    genre: Optional[str] = None
    description: Optional[str] = None
    targetWords: Optional[int] = None
    targetChapters: Optional[int] = None
    currentChapterNum: Optional[int] = None
    status: Optional[str] = None

@router.get("/projects")
async def list_projects():
    rows = await fetchall("SELECT * FROM projects ORDER BY updated_at DESC")
    return convert_rows(rows)

@router.post("/projects")
async def create_project(data: ProjectCreate):
    now = int(time.time() * 1000)
    pid = str(uuid.uuid4())
    await execute(
        "INSERT INTO projects (id, title, genre, description, target_words, target_chapters, current_chapter_num, status, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,0,'drafting',%s,%s)",
        (pid, data.title, data.genre, data.description, data.targetWords, data.targetChapters, now, now))
    return convert_row(await fetchone("SELECT * FROM projects WHERE id=%s", (pid,)))

@router.get("/projects/{pid}")
async def get_project(pid: str):
    row = await fetchone("SELECT * FROM projects WHERE id=%s", (pid,))
    if not row: raise HTTPException(404, "项目不存在")
    return convert_row(row)

@router.put("/projects/{pid}")
async def update_project(pid: str, data: ProjectUpdate):
    sets, args = [], []
    for k, v in data.dict(exclude_none=True).items():
        sets.append(f"{to_snake(k)}=%s")
        args.append(v)
    if not sets: return await get_project(pid)
    sets.append("updated_at=%s")
    args.append(int(time.time() * 1000))
    args.append(pid)
    await execute(f"UPDATE projects SET {', '.join(sets)} WHERE id=%s", args)
    return await get_project(pid)

@router.delete("/projects/{pid}")
async def delete_project(pid: str):
    tables = ["chapters", "chapter_versions", "creative_seeds", "creative_bible",
              "characters", "plot_threads", "rolling_outlines", "canon_facts",
              "possibility_cards", "temp_drafts", "task_model_bindings"]
    for t in tables:
        await execute(f"DELETE FROM {t} WHERE project_id=%s", (pid,))
    await execute("DELETE FROM projects WHERE id=%s", (pid,))
    return {"ok": True}
