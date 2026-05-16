"""章节与版本管理"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from database import fetchone, fetchall, execute
from .helpers import convert_row, convert_rows, to_snake
import uuid, time

router = APIRouter(tags=["chapters"])

class ChapterCreate(BaseModel):
    chapterNum: int
    title: str = ""

class ChapterUpdate(BaseModel):
    title: Optional[str] = None
    finalVersionId: Optional[str] = None
    status: Optional[str] = None
    summary: Optional[str] = None
    wordCount: Optional[int] = None

class VersionCreate(BaseModel):
    title: str = ""
    content: str = ""
    versionType: str = "ai_candidate"
    sourceModelId: Optional[str] = None
    promptBrief: str = ""

class VersionUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    versionType: Optional[str] = None
    sourceModelId: Optional[str] = None

# --- Chapters ---
@router.get("/projects/{pid}/chapters")
async def list_chapters(pid: str):
    rows = await fetchall("SELECT * FROM chapters WHERE project_id=%s ORDER BY chapter_num", (pid,))
    return convert_rows(rows)

@router.post("/projects/{pid}/chapters")
async def create_chapter(pid: str, data: ChapterCreate):
    now = int(time.time() * 1000)
    cid = str(uuid.uuid4())
    title = data.title or f"第 {data.chapterNum} 章"
    await execute("""INSERT INTO chapters (id, project_id, chapter_num, title, final_version_id,
             status, summary, word_count, created_at, updated_at)
             VALUES (%s,%s,%s,%s,NULL,'drafting','',0,%s,%s)""",
             (cid, pid, data.chapterNum, title, now, now))
    return convert_row(await fetchone("SELECT * FROM chapters WHERE id=%s", (cid,)))

@router.put("/projects/{pid}/chapters/{cid}")
async def update_chapter(pid: str, cid: str, data: ChapterUpdate):
    sets, args = [], []
    for k, v in data.dict(exclude_none=True).items():
        sets.append(f"{to_snake(k)}=%s")
        args.append(v)
    if not sets:
        return convert_row(await fetchone("SELECT * FROM chapters WHERE id=%s", (cid,)))
    sets.append("updated_at=%s")
    args.append(int(time.time() * 1000))
    args.append(cid)
    await execute(f"UPDATE chapters SET {', '.join(sets)} WHERE id=%s", args)
    return convert_row(await fetchone("SELECT * FROM chapters WHERE id=%s", (cid,)))

# --- Chapter Versions ---
@router.get("/projects/{pid}/chapters/{cid}/versions")
async def list_versions(pid: str, cid: str):
    rows = await fetchall("SELECT * FROM chapter_versions WHERE chapter_id=%s ORDER BY created_at DESC", (cid,))
    return convert_rows(rows)

@router.post("/projects/{pid}/chapters/{cid}/versions")
async def create_version(pid: str, cid: str, data: VersionCreate):
    now = int(time.time() * 1000)
    vid = str(uuid.uuid4())
    ch = await fetchone("SELECT chapter_num FROM chapters WHERE id=%s", (cid,))
    cnum = ch['chapter_num'] if ch else 0
    await execute("""INSERT INTO chapter_versions (id, project_id, chapter_id, chapter_num, title,
             content, version_type, source_model_id, prompt_brief, created_at, updated_at)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
             (vid, pid, cid, cnum, data.title, data.content, data.versionType,
              data.sourceModelId, data.promptBrief, now, now))
    return convert_row(await fetchone("SELECT * FROM chapter_versions WHERE id=%s", (vid,)))

@router.put("/projects/{pid}/chapters/{cid}/versions/{vid}")
async def update_version(pid: str, cid: str, vid: str, data: VersionUpdate):
    sets, args = [], []
    for k, v in data.dict(exclude_none=True).items():
        sets.append(f"{to_snake(k)}=%s")
        args.append(v)
    if not sets:
        return convert_row(await fetchone("SELECT * FROM chapter_versions WHERE id=%s", (vid,)))
    sets.append("updated_at=%s")
    args.append(int(time.time() * 1000))
    args.append(vid)
    await execute(f"UPDATE chapter_versions SET {', '.join(sets)} WHERE id=%s", args)
    return convert_row(await fetchone("SELECT * FROM chapter_versions WHERE id=%s", (vid,)))

@router.delete("/projects/{pid}/chapters/{cid}/versions/{vid}")
async def delete_version(pid: str, cid: str, vid: str):
    await execute("DELETE FROM chapter_versions WHERE id=%s", (vid,))
    return {"ok": True}

# --- Temp Drafts ---
@router.get("/projects/{pid}/temp-draft/{cnum}")
async def get_temp_draft(pid: str, cnum: int):
    draft_id = f"{pid}_{cnum}"
    row = await fetchone("SELECT * FROM temp_drafts WHERE id=%s", (draft_id,))
    return convert_row(row) if row else None

@router.put("/projects/{pid}/temp-draft/{cnum}")
async def save_temp_draft(pid: str, cnum: int, data: dict):
    draft_id = f"{pid}_{cnum}"
    now = int(time.time() * 1000)
    content = data.get("content", "")
    await execute("REPLACE INTO temp_drafts (id, project_id, chapter_num, content, saved_at) VALUES (%s,%s,%s,%s,%s)",
                  (draft_id, pid, cnum, content, now))
    return {"ok": True}

@router.delete("/projects/{pid}/temp-draft/{cnum}")
async def delete_temp_draft(pid: str, cnum: int):
    await execute("DELETE FROM temp_drafts WHERE id=%s", (f"{pid}_{cnum}",))
    return {"ok": True}
