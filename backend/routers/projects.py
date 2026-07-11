"""项目 CRUD"""
from typing import Optional
import time
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.database import fetchone, fetchall, execute
from .helpers import convert_row, convert_rows, to_snake
from .providers import inherit_latest_task_model_bindings

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
        """
        INSERT INTO projects
          (id, title, genre, description, target_words, target_chapters, current_chapter_num, status, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,0,'drafting',%s,%s)
        """,
        (pid, data.title, data.genre, data.description, data.targetWords, data.targetChapters, now, now),
    )
    await inherit_latest_task_model_bindings(pid)
    return convert_row(await fetchone("SELECT * FROM projects WHERE id=%s", (pid,)))


@router.get("/projects/{pid}")
async def get_project(pid: str):
    row = await fetchone("SELECT * FROM projects WHERE id=%s", (pid,))
    if not row:
        raise HTTPException(404, "项目不存在")
    return convert_row(row)


@router.get("/projects/{pid}/content-state")
async def get_project_content_state(pid: str):
    chapter_count = await _count("SELECT COUNT(*) AS c FROM chapters WHERE project_id=%s", (pid,))
    written_chapters = await _count(
        """
        SELECT COUNT(*) AS c FROM chapters
        WHERE project_id=%s
          AND (COALESCE(word_count, 0) > 0 OR final_version_id IS NOT NULL OR COALESCE(summary, '') <> '' OR status IN ('final', 'reviewing'))
        """,
        (pid,),
    )
    chapter_versions = await _count(
        "SELECT COUNT(*) AS c FROM chapter_versions WHERE project_id=%s AND COALESCE(content, '') <> ''",
        (pid,),
    )
    temp_drafts = await _count(
        "SELECT COUNT(*) AS c FROM temp_drafts WHERE project_id=%s AND COALESCE(content, '') <> ''",
        (pid,),
    )
    seed_count = await _count("SELECT COUNT(*) AS c FROM creative_seeds WHERE project_id=%s", (pid,))
    bible_count = await _count("SELECT COUNT(*) AS c FROM creative_bible WHERE project_id=%s", (pid,))
    setting_entities = await _count("SELECT COUNT(*) AS c FROM setting_entities WHERE project_id=%s", (pid,))
    setting_relations = await _count("SELECT COUNT(*) AS c FROM setting_relations WHERE project_id=%s", (pid,))
    setting_events = await _count("SELECT COUNT(*) AS c FROM setting_change_events WHERE project_id=%s", (pid,))
    return {
        "chaptersCount": chapter_count,
        "writtenChapters": written_chapters,
        "chapterVersions": chapter_versions,
        "tempDrafts": temp_drafts,
        "hasChapterContent": written_chapters > 0 or chapter_versions > 0 or temp_drafts > 0,
        "seedsCount": seed_count,
        "hasBible": bible_count > 0,
        "settingEntitiesCount": setting_entities,
        "settingRelationsCount": setting_relations,
        "settingChangeEventsCount": setting_events,
        "settingsCount": setting_entities + setting_relations + setting_events,
    }


@router.put("/projects/{pid}")
async def update_project(pid: str, data: ProjectUpdate):
    current = await fetchone("SELECT * FROM projects WHERE id=%s", (pid,))
    if not current:
        raise HTTPException(404, "项目不存在")

    incoming = data.dict(exclude_none=True)
    target_words_changed = (
        "targetWords" in incoming
        and int(incoming["targetWords"] or 0) != int(current.get("target_words") or 0)
    )
    target_chapters_changed = (
        "targetChapters" in incoming
        and int(incoming["targetChapters"] or 0) != int(current.get("target_chapters") or 0)
    )
    if target_words_changed or target_chapters_changed:
        if await _has_project_chapter_content(pid):
            raise HTTPException(
                400,
                "项目已有正文、候选版本或临时草稿，不能修改目标字数或目标章节数；如需重新规划，请先清空章节内容后再调整。",
            )

    sets, args = [], []
    for key, value in incoming.items():
        sets.append(f"{to_snake(key)}=%s")
        args.append(value)
    if not sets:
        return await get_project(pid)
    sets.append("updated_at=%s")
    args.append(int(time.time() * 1000))
    args.append(pid)
    await execute(f"UPDATE projects SET {', '.join(sets)} WHERE id=%s", args)
    return await get_project(pid)


@router.delete("/projects/{pid}")
async def delete_project(pid: str):
    tables = [
        "chapters",
        "chapter_versions",
        "creative_seeds",
        "creative_bible",
        "characters",
        "plot_threads",
        "rolling_outlines",
        "canon_facts",
        "possibility_cards",
        "chapter_beat_plans",
        "temp_drafts",
        "task_model_bindings",
        "market_items",
        "market_chat_messages",
        "market_direction_reports",
        "project_audit_reports",
        "correction_tasks",
        "project_volumes",
        "setting_relations",
        "setting_change_events",
        "setting_entities",
    ]
    for table in tables:
        await execute(f"DELETE FROM {table} WHERE project_id=%s", (pid,))
    await execute("DELETE FROM projects WHERE id=%s", (pid,))
    return {"ok": True}


async def _count(sql: str, args: tuple):
    row = await fetchone(sql, args)
    return int((row or {}).get("c") or 0)


async def _has_project_chapter_content(pid: str) -> bool:
    written_chapters = await _count(
        """
        SELECT COUNT(*) AS c FROM chapters
        WHERE project_id=%s
          AND (COALESCE(word_count, 0) > 0 OR final_version_id IS NOT NULL OR COALESCE(summary, '') <> '' OR status IN ('final', 'reviewing'))
        """,
        (pid,),
    )
    chapter_versions = await _count(
        "SELECT COUNT(*) AS c FROM chapter_versions WHERE project_id=%s AND COALESCE(content, '') <> ''",
        (pid,),
    )
    temp_drafts = await _count(
        "SELECT COUNT(*) AS c FROM temp_drafts WHERE project_id=%s AND COALESCE(content, '') <> ''",
        (pid,),
    )
    return written_chapters > 0 or chapter_versions > 0 or temp_drafts > 0
