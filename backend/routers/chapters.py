"""章节与版本管理"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from database import fetchone, fetchall, execute
from .helpers import convert_row, convert_rows, to_snake, touch_project
import json
import re
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

class ChapterTitleUpdate(BaseModel):
    title: str = ""


CHAPTER_TITLE_PRONOUN_FRAGMENT_RE = re.compile(r"^(你|我|他|她|它|谁|这|那|嗯|啊|哦|呀|喂|哈|嘿)[—\-…~，。！？!?,]*$")


def _is_semantic_title_char(ch: str) -> bool:
    return ch.isalnum() or ("\u4e00" <= ch <= "\u9fff")


def _chapter_title_invalid_reason(title: str) -> str:
    text = (title or "").strip()
    if not text:
        return "empty"
    if len(text) > 30 or "\n" in text or "\r" in text:
        return "too_long_or_multiline"
    chars = [ch for ch in text if not ch.isspace()]
    semantic_count = sum(1 for ch in chars if _is_semantic_title_char(ch))
    symbol_count = sum(1 for ch in chars if not _is_semantic_title_char(ch))
    if semantic_count == 0:
        return "symbol_fragment"
    if symbol_count >= semantic_count and symbol_count > 0:
        return "punctuation_dominant"
    if CHAPTER_TITLE_PRONOUN_FRAGMENT_RE.match(text):
        return "dialogue_fragment"
    if re.fullmatch(r"[{}\[\]()`#>*_+=|\\/\"'“”‘’《》「」『』【】（）()]+", text):
        return "markup_or_json_fragment"
    return ""

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
    storyBlockId: Optional[str] = None
    blockStageId: Optional[str] = None
    blockStageSnapshot: Optional[dict] = None
    beatPlanSource: Optional[str] = None
    derivedFromStoryBlock: Optional[bool] = False
    derivedReason: Optional[str] = None


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

@router.put("/projects/{pid}/chapters/{cid}/title")
async def update_chapter_title(pid: str, cid: str, data: ChapterTitleUpdate):
    current = await _chapter_by_id(pid, cid)
    if not current:
        raise HTTPException(404, "章节不存在")
    title = (data.title or "").strip()
    if not title:
        raise HTTPException(400, "章节标题不能为空")
    invalid_reason = _chapter_title_invalid_reason(title)
    if invalid_reason:
        raise HTTPException(400, f"章节标题不合法：{invalid_reason}")
    now = int(time.time() * 1000)
    await execute(
        "UPDATE chapters SET title=%s, updated_at=%s WHERE project_id=%s AND id=%s",
        (title, now, pid, cid),
    )
    await touch_project(pid)
    return convert_row(await fetchone("SELECT * FROM chapters WHERE project_id=%s AND id=%s", (pid, cid)))

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
    await _validate_story_block_reference(pid, data, cnum)
    plan_id = f"{pid}_{cnum}"
    now = int(time.time() * 1000)
    snapshot = json.dumps(data.blockStageSnapshot or None, ensure_ascii=False)
    beat_plan_source = (data.beatPlanSource or "").strip() or None
    derived_from_story_block = 1 if data.derivedFromStoryBlock else 0
    derived_reason = data.derivedReason or None
    existing = await fetchone("SELECT id FROM chapter_beat_plans WHERE id=%s", (plan_id,))
    if existing:
        await execute(
            """
            UPDATE chapter_beat_plans
            SET content=%s, story_block_id=%s, block_stage_id=%s,
                block_stage_snapshot=%s, beat_plan_source=%s,
                derived_from_story_block=%s, derived_reason=%s, updated_at=%s
            WHERE id=%s
            """,
            (
                data.content,
                data.storyBlockId,
                data.blockStageId,
                snapshot,
                beat_plan_source,
                derived_from_story_block,
                derived_reason,
                now,
                plan_id,
            ),
        )
    else:
        await execute(
            """INSERT INTO chapter_beat_plans
               (id, project_id, chapter_num, story_block_id, block_stage_id,
                block_stage_snapshot, beat_plan_source, derived_from_story_block,
                derived_reason, content, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                plan_id,
                pid,
                cnum,
                data.storyBlockId,
                data.blockStageId,
                snapshot,
                beat_plan_source,
                derived_from_story_block,
                derived_reason,
                data.content,
                now,
                now,
            ),
        )
    if data.storyBlockId:
        await execute(
            "UPDATE chapters SET story_block_id=%s, updated_at=%s WHERE project_id=%s AND chapter_num=%s",
            (data.storyBlockId, now, pid, cnum),
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


async def _validate_story_block_reference(pid: str, data: BeatPlanSave, cnum: int | None = None):
    if not data.storyBlockId or not data.blockStageId or not data.blockStageSnapshot:
        raise HTTPException(400, "小纲必须绑定 storyBlockId、blockStageId 和 blockStageSnapshot")

    block = await fetchone(
        "SELECT * FROM story_blocks WHERE project_id=%s AND id=%s",
        (pid, data.storyBlockId),
    )
    if not block:
        raise HTTPException(404, "故事块不存在或不属于当前项目")
    if block.get("status") != "active":
        raise HTTPException(409, "只能引用 active 故事块生成当前章小纲")

    stage = _find_stage_by_id(block.get("stage_plan"), data.blockStageId)
    stage_ids = {
        str(stage.get("id"))
        for stage in _stage_list(block.get("stage_plan"))
        if stage.get("id")
    }
    if data.blockStageId not in stage_ids:
        raise HTTPException(400, "blockStageId 不属于该故事块的 stagePlan")
    if await _is_story_block_stage_unusable_for_beat_plan(pid, block, stage, data.blockStageId, cnum):
        raise HTTPException(
            409,
            {
                "code": "story_block_stage_reuse_detected",
                "message": "该故事块阶段已完成、锁定或已绑定章节，不能用于新章节小纲。",
                "storyBlockId": data.storyBlockId,
                "blockStageId": data.blockStageId,
                "chapterNum": cnum,
            },
        )

    snapshot = data.blockStageSnapshot or {}
    if snapshot.get("storyBlockId") != data.storyBlockId:
        raise HTTPException(400, "blockStageSnapshot.storyBlockId 与 storyBlockId 不一致")
    if snapshot.get("stageId") != data.blockStageId:
        raise HTTPException(400, "blockStageSnapshot.stageId 与 blockStageId 不一致")
    await _validate_story_block_snapshot_fields(block, stage, snapshot)


async def _validate_story_block_snapshot_fields(block, stage, snapshot: dict):
    checks = [
        ("blockGoal", block.get("goal")),
        ("entryState", block.get("entry_state")),
        ("storyFunction", block.get("story_function")),
        ("mainPressure", block.get("main_pressure")),
        ("stagePurpose", _pick_stage_value(stage, "purpose", "stagePurpose", "goal")),
        ("stageAction", _pick_stage_value(stage, "sceneOrAction", "action", "description")),
        ("stageChoice", _pick_stage_value(stage, "choice")),
        ("stageCostOrConsequence", _pick_stage_value(stage, "costOrConsequence", "consequence", "cost")),
    ]
    for field, expected in checks:
        actual = _normalize_snapshot_value(snapshot.get(field))
        if not actual:
            continue
        if actual != _normalize_snapshot_value(expected):
            raise HTTPException(400, f"blockStageSnapshot.{field} 与故事块当前阶段不一致")


async def _is_story_block_stage_unusable_for_beat_plan(pid: str, block: dict, stage: dict, stage_id: str, cnum: int | None):
    sid = str(stage_id or "").strip()
    if not sid:
        return True
    if cnum and await _has_stage_continuation_basis(pid, block.get("id"), sid, cnum):
        return False
    if sid in _completed_stage_ids(block):
        return True
    if sid in await _locked_stage_ids(pid, block.get("id"), cnum):
        return True
    if str(stage.get("status") or "") in {"completed", "closed", "skipped", "closed_unexecuted", "skipped_by_block_close", "invalidated"}:
        return True
    if stage.get("locked") or stage.get("lockedByBeatPlan") or stage.get("lockedByFinalChapter"):
        return True
    if _list(stage.get("chapterRefs")):
        return True
    return False


async def _has_stage_continuation_basis(pid: str, story_block_id: str, stage_id: str, cnum: int):
    if not story_block_id or not stage_id or not cnum or cnum <= 1:
        return False
    row = await fetchone(
        """
        SELECT review_json
        FROM story_block_reviews
        WHERE project_id=%s AND story_block_id=%s AND chapter_num=%s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (pid, story_block_id, cnum - 1),
    )
    review = _dict((row or {}).get("review_json"))
    snapshot = _dict(review.get("blockStageSnapshot"))
    return bool(
        review.get("stageContinues") is True
        and str(snapshot.get("stageId") or review.get("blockStageId") or "") == str(stage_id)
        and _stage_continue_reason(review)
    )


def _stage_continue_reason(review: dict) -> str:
    return str(
        review.get("stageContinueReason")
        or review.get("stage_continue_reason")
        or review.get("reason")
        or ""
    ).strip()


def _find_stage_by_id(stage_plan, stage_id: str):
    for stage in _stage_list(stage_plan):
        if str(stage.get("id") or "") == str(stage_id or ""):
            return stage
    return {}


def _pick_stage_value(stage: dict, *keys):
    for key in keys:
        value = stage.get(key)
        if value is not None and str(value).strip():
            return value
    return ""


def _normalize_snapshot_value(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value).strip()


def _completed_stage_ids(block) -> set[str]:
    ids = set()
    for stage in _stage_list(block.get("stage_plan")):
        if stage.get("status") == "completed" and stage.get("id"):
            ids.add(str(stage["id"]))
    for stage in _list(block.get("completed_stages")):
        if isinstance(stage, dict) and stage.get("id"):
            ids.add(str(stage["id"]))
        elif stage:
            ids.add(str(stage))
    return ids


async def _locked_stage_ids(pid: str, bid: str, exclude_chapter_num: int | None = None) -> set[str]:
    params = [pid, bid]
    exclude_clause = ""
    if exclude_chapter_num is not None:
        exclude_clause = " AND chapter_num<>%s"
        params.append(exclude_chapter_num)
    rows = await fetchall(
        f"""
        SELECT DISTINCT block_stage_id
        FROM chapter_beat_plans
        WHERE project_id=%s AND story_block_id=%s AND block_stage_id IS NOT NULL
        {exclude_clause}
        """,
        tuple(params),
    )
    return {str(row.get("block_stage_id")) for row in rows if row.get("block_stage_id")}


def _stage_list(value) -> list[dict]:
    return [item for item in _list(value) if isinstance(item, dict)]


def _list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except ValueError:
            return []
    return []


def _dict(value):
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}
