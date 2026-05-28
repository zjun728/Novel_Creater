"""章节与版本管理"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from database import fetchone, fetchall, execute
from .helpers import convert_row, convert_rows, to_snake, touch_project
import uuid, time

router = APIRouter(tags=["chapters"])

FINALIZED_CHAPTER_MESSAGE = "本章已经定稿，正文、小纲和版本已锁定，不能再修改。"

class ChapterCreate(BaseModel):
    chapterNum: int
    title: str = ""

class ChapterUpdate(BaseModel):
    title: Optional[str] = None
    finalVersionId: Optional[str] = None
    status: Optional[str] = None
    summary: Optional[str] = None
    wordCount: Optional[int] = None

class ChapterSummaryUpdate(BaseModel):
    summary: str = ""

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

class VersionFinalize(BaseModel):
    summary: str = ""
    wordCount: Optional[int] = None

class BeatPlanSave(BaseModel):
    content: str = ""


async def _chapter_by_id(pid: str, cid: str):
    return await fetchone("SELECT * FROM chapters WHERE project_id=%s AND id=%s", (pid, cid))


async def _chapter_by_num(pid: str, cnum: int):
    return await fetchone("SELECT * FROM chapters WHERE project_id=%s AND chapter_num=%s", (pid, cnum))


def _is_finalized_chapter(chapter) -> bool:
    return bool(
        chapter
        and (
            chapter.get("final_version_id")
            or chapter.get("status") == "final"
        )
    )


def _raise_if_finalized(chapter):
    if _is_finalized_chapter(chapter):
        raise HTTPException(status_code=409, detail=FINALIZED_CHAPTER_MESSAGE)

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
    current = await _chapter_by_id(pid, cid)
    _raise_if_finalized(current)
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

@router.put("/projects/{pid}/chapters/{cid}/summary")
async def update_chapter_summary(pid: str, cid: str, data: ChapterSummaryUpdate):
    current = await _chapter_by_id(pid, cid)
    if not current:
        raise HTTPException(404, "章节不存在")
    now = int(time.time() * 1000)
    await execute(
        "UPDATE chapters SET summary=%s, updated_at=%s WHERE id=%s",
        (data.summary or "", now, cid),
    )
    await touch_project(pid)
    return convert_row(await fetchone("SELECT * FROM chapters WHERE id=%s", (cid,)))

@router.delete("/projects/{pid}/chapters/{cid}")
async def delete_chapter(pid: str, cid: str):
    chapter = await fetchone(
        "SELECT * FROM chapters WHERE project_id=%s AND id=%s",
        (pid, cid),
    )
    if not chapter:
        raise HTTPException(404, "章节不存在")

    chapter_num = chapter["chapter_num"]
    version_count = await _count(
        "SELECT COUNT(*) AS c FROM chapter_versions WHERE project_id=%s AND chapter_id=%s",
        (pid, cid),
    )
    temp_draft_count = await _count(
        "SELECT COUNT(*) AS c FROM temp_drafts WHERE project_id=%s AND chapter_num=%s AND COALESCE(content, '') <> ''",
        (pid, chapter_num),
    )
    canon_count = await _count(
        "SELECT COUNT(*) AS c FROM canon_facts WHERE project_id=%s AND chapter_num=%s",
        (pid, chapter_num),
    )
    setting_change_count = await _count(
        "SELECT COUNT(*) AS c FROM setting_change_events WHERE project_id=%s AND chapter_num=%s",
        (pid, chapter_num),
    )
    has_written_asset = (
        bool(chapter.get("final_version_id"))
        or int(chapter.get("word_count") or 0) > 0
        or chapter.get("status") == "final"
        or version_count > 0
        or temp_draft_count > 0
        or canon_count > 0
        or setting_change_count > 0
    )
    if has_written_asset:
        raise HTTPException(
            409,
            "当前章节已有正文、候选版本、定稿、临时草稿、记忆事实或设定变更记录，不能物理删除。请后续使用归档/废弃章节流程。",
        )

    await execute(
        "DELETE FROM chapter_beat_plans WHERE project_id=%s AND chapter_num=%s",
        (pid, chapter_num),
    )
    await execute("DELETE FROM chapters WHERE project_id=%s AND id=%s", (pid, cid))
    await touch_project(pid)
    return {"ok": True}

# --- Chapter Versions ---
@router.get("/projects/{pid}/chapters/{cid}/versions")
async def list_versions(pid: str, cid: str):
    rows = await fetchall("SELECT * FROM chapter_versions WHERE chapter_id=%s ORDER BY created_at DESC", (cid,))
    return convert_rows(rows)

@router.post("/projects/{pid}/chapters/{cid}/versions")
async def create_version(pid: str, cid: str, data: VersionCreate):
    now = int(time.time() * 1000)
    vid = str(uuid.uuid4())
    ch = await _chapter_by_id(pid, cid)
    _raise_if_finalized(ch)
    cnum = ch['chapter_num'] if ch else 0
    await execute("""INSERT INTO chapter_versions (id, project_id, chapter_id, chapter_num, title,
             content, version_type, source_model_id, prompt_brief, created_at, updated_at)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
             (vid, pid, cid, cnum, data.title, data.content, data.versionType,
              data.sourceModelId, data.promptBrief, now, now))
    return convert_row(await fetchone("SELECT * FROM chapter_versions WHERE id=%s", (vid,)))

@router.put("/projects/{pid}/chapters/{cid}/versions/{vid}")
async def update_version(pid: str, cid: str, vid: str, data: VersionUpdate):
    chapter = await _chapter_by_id(pid, cid)
    _raise_if_finalized(chapter)
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

@router.post("/projects/{pid}/chapters/{cid}/versions/{vid}/finalize")
async def finalize_version(pid: str, cid: str, vid: str, data: VersionFinalize):
    chapter = await _chapter_by_id(pid, cid)
    if not chapter:
        raise HTTPException(404, "章节不存在")
    version = await fetchone(
        "SELECT * FROM chapter_versions WHERE project_id=%s AND chapter_id=%s AND id=%s",
        (pid, cid, vid),
    )
    if not version:
        raise HTTPException(404, "版本不存在")

    existing_final_id = chapter.get("final_version_id")
    if _is_finalized_chapter(chapter) and existing_final_id != vid:
        raise HTTPException(status_code=409, detail=FINALIZED_CHAPTER_MESSAGE)

    now = int(time.time() * 1000)
    word_count = data.wordCount if data.wordCount is not None else len(version.get("content") or "")
    await execute(
        "UPDATE chapter_versions SET version_type='final', updated_at=%s WHERE id=%s",
        (now, vid),
    )
    await execute(
        """UPDATE chapters SET final_version_id=%s, status='final', summary=%s,
           word_count=%s, updated_at=%s WHERE id=%s""",
        (vid, data.summary or chapter.get("summary") or "", word_count, now, cid),
    )
    await touch_project(pid)
    return {
        "version": convert_row(await fetchone("SELECT * FROM chapter_versions WHERE id=%s", (vid,))),
        "chapter": convert_row(await fetchone("SELECT * FROM chapters WHERE id=%s", (cid,))),
    }

@router.delete("/projects/{pid}/chapters/{cid}/versions/{vid}")
async def delete_version(pid: str, cid: str, vid: str):
    chapter = await _chapter_by_id(pid, cid)
    _raise_if_finalized(chapter)
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
    _raise_if_finalized(await _chapter_by_num(pid, cnum))
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

# --- Chapter Beat Plans ---
@router.get("/projects/{pid}/chapter-beat-plan/{cnum}")
async def get_chapter_beat_plan(pid: str, cnum: int):
    row = await fetchone(
        "SELECT * FROM chapter_beat_plans WHERE project_id=%s AND chapter_num=%s",
        (pid, cnum),
    )
    return convert_row(row) if row else None

@router.put("/projects/{pid}/chapter-beat-plan/{cnum}")
async def save_chapter_beat_plan(pid: str, cnum: int, data: BeatPlanSave):
    _raise_if_finalized(await _chapter_by_num(pid, cnum))
    plan_id = f"{pid}_{cnum}"
    now = int(time.time() * 1000)
    existing = await fetchone("SELECT id FROM chapter_beat_plans WHERE id=%s", (plan_id,))
    if existing:
        await execute(
            "UPDATE chapter_beat_plans SET content=%s, updated_at=%s WHERE id=%s",
            (data.content, now, plan_id),
        )
    else:
        await execute(
            """INSERT INTO chapter_beat_plans
               (id, project_id, chapter_num, content, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (plan_id, pid, cnum, data.content, now, now),
        )
    row = await fetchone("SELECT * FROM chapter_beat_plans WHERE id=%s", (plan_id,))
    return convert_row(row)

@router.delete("/projects/{pid}/chapter-beat-plan/{cnum}")
async def delete_chapter_beat_plan(pid: str, cnum: int):
    _raise_if_finalized(await _chapter_by_num(pid, cnum))
    await execute(
        "DELETE FROM chapter_beat_plans WHERE project_id=%s AND chapter_num=%s",
        (pid, cnum),
    )
    return {"ok": True}

async def _count(sql: str, args: tuple) -> int:
    row = await fetchone(sql, args)
    return int((row or {}).get("c") or 0)
