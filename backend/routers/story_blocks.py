"""故事块：分卷规划和章节小纲之间的滚动剧情单元。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Any
from database import fetchone, fetchall, execute
from .helpers import convert_row, convert_rows, touch_project
import json
import time
import uuid

router = APIRouter(tags=["story-blocks"])

ALLOWED_STATUSES = {"active", "completed", "paused", "closed"}
ALLOWED_DECISIONS = {
    "continue_current_block",
    "adjust_remaining_stages",
    "split_unfinalized_content",
    "complete_current_block",
    "open_new_block",
}

ALLOWED_CLOSE_REASONS = {
    "user_manual_close",
    "block_goal_completed",
    "direction_changed",
    "stages_merged",
    "plan_abandoned",
    "ai_review_suggested",
    "unknown",
}

ALLOWED_CLOSED_BY = {"ai_review", "user_manual", "system_fallback"}
CLOSED_UNEXECUTED_STAGE_STATUS = "closed_unexecuted"
SKIPPED_BY_BLOCK_CLOSE_STATUS = "skipped_by_block_close"
INVALIDATED_STAGE_STATUS = "invalidated"


class StoryBlockCreate(BaseModel):
    volumeId: Optional[str] = None
    blockNum: Optional[int] = None
    status: str = "active"
    title: str = ""
    goal: str = ""
    storyFunction: str = ""
    entryState: str = ""
    exitTarget: str = ""
    mainPressure: str = ""
    keyCharacters: list[Any] = []
    stagePlan: list[dict] = []
    completedStages: list[dict] = []
    nextStageSuggestion: str = ""
    unresolvedQuestions: list[Any] = []
    dontAdvanceYet: list[Any] = []
    carryOverToNextChapter: list[Any] = []
    capacityAssessment: str = "normal"
    chapterRefs: list[Any] = []
    lockState: dict = {}


class RemainingStagesUpdate(BaseModel):
    stagePlan: list[dict] = []
    nextStageSuggestion: str = ""
    unresolvedQuestions: list[Any] = []
    dontAdvanceYet: list[Any] = []
    carryOverToNextChapter: list[Any] = []
    capacityAssessment: str = "normal"


class StatusPayload(BaseModel):
    reason: str = ""
    closeReason: str = "unknown"
    completionEvidence: str = ""
    singleChapterBlockReason: str = ""
    closedBy: str = "user_manual"
    chapterRefs: list[Any] = []
    blockCloseReasonType: str = ""
    earlyCloseAllowed: Optional[bool] = None
    earlyCloseEvidence: str = ""
    invalidatedStageIds: list[Any] = []
    closedUnexecutedStageIds: list[Any] = []


class StoryBlockReviewCreate(BaseModel):
    chapterNum: Optional[int] = None
    decision: str = "continue_current_block"
    review: dict = {}


class ConfirmReviewPayload(BaseModel):
    reason: str = ""


@router.get("/projects/{pid}/story-blocks")
async def list_story_blocks(pid: str):
    rows = await fetchall(
        "SELECT * FROM story_blocks WHERE project_id=%s ORDER BY block_num, created_at",
        (pid,),
    )
    return convert_rows(rows)


@router.get("/projects/{pid}/story-blocks/active")
async def get_active_story_block(pid: str):
    row = await _get_single_active_block(pid)
    return convert_row(row) if row else None


@router.post("/projects/{pid}/story-blocks")
async def create_story_block(pid: str, data: StoryBlockCreate):
    _validate_status(data.status)
    if data.status == "active":
        await _reject_existing_active_block(pid)
    now = int(time.time() * 1000)
    bid = str(uuid.uuid4())
    block_num = data.blockNum or await _next_block_num(pid)
    await execute(
        """
        INSERT INTO story_blocks (
          id, project_id, volume_id, block_num, status, title, goal,
          story_function, entry_state, exit_target, main_pressure,
          key_characters, stage_plan, completed_stages, next_stage_suggestion,
          unresolved_questions, dont_advance_yet, carry_over_to_next_chapter, capacity_assessment,
          chapter_refs, lock_state, review_history, created_at, updated_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            bid,
            pid,
            data.volumeId,
            block_num,
            data.status,
            data.title,
            data.goal,
            data.storyFunction,
            data.entryState,
            data.exitTarget,
            data.mainPressure,
            _json(data.keyCharacters),
            _json(data.stagePlan),
            _json(data.completedStages),
            data.nextStageSuggestion,
            _json(data.unresolvedQuestions),
            _json(data.dontAdvanceYet),
            _json(data.carryOverToNextChapter),
            data.capacityAssessment or "normal",
            _json(data.chapterRefs),
            _json(data.lockState),
            _json([]),
            now,
            now,
        ),
    )
    await touch_project(pid)
    return convert_row(await fetchone("SELECT * FROM story_blocks WHERE id=%s", (bid,)))


@router.put("/projects/{pid}/story-blocks/{bid}/remaining-stages")
async def update_remaining_stages(pid: str, bid: str, data: RemainingStagesUpdate):
    block = await _get_block(pid, bid)
    if block.get("status") != "active":
        raise HTTPException(409, "只有 active 故事块允许更新后续阶段")
    locked_stage_ids = await _locked_stage_ids(pid, bid)
    existing_stages = _stage_list(block.get("stage_plan"))
    incoming_stages = _stage_list(data.stagePlan)
    completed_ids = _completed_stage_ids(block)
    closed_ids = _closed_stage_ids(block)

    existing_by_id = {str(stage.get("id") or ""): stage for stage in existing_stages if stage.get("id")}
    merged = []
    for incoming in incoming_stages:
        stage_id = str(incoming.get("id") or "")
        existing = existing_by_id.get(stage_id)
        if stage_id and (stage_id in locked_stage_ids or stage_id in completed_ids or stage_id in closed_ids):
            if existing is None:
                raise HTTPException(409, "已锁定阶段不能被删除或替换")
            if _compact_json(existing) != _compact_json(incoming):
                raise HTTPException(409, "已被小纲或定稿章节引用的阶段不能回改")
            merged.append(existing)
        else:
            merged.append(incoming)

    incoming_ids = {str(stage.get("id") or "") for stage in incoming_stages if stage.get("id")}
    for existing in existing_stages:
        stage_id = str(existing.get("id") or "")
        if stage_id and (stage_id in locked_stage_ids or stage_id in completed_ids or stage_id in closed_ids) and stage_id not in incoming_ids:
            merged.append(existing)

    now = int(time.time() * 1000)
    await execute(
        """
        UPDATE story_blocks
        SET stage_plan=%s, next_stage_suggestion=%s, unresolved_questions=%s,
            dont_advance_yet=%s, carry_over_to_next_chapter=%s,
            capacity_assessment=%s, updated_at=%s
        WHERE project_id=%s AND id=%s
        """,
        (
            _json(merged),
            data.nextStageSuggestion,
            _json(data.unresolvedQuestions),
            _json(data.dontAdvanceYet),
            _json(data.carryOverToNextChapter),
            data.capacityAssessment or block.get("capacity_assessment") or "normal",
            now,
            pid,
            bid,
        ),
    )
    await touch_project(pid)
    return convert_row(await fetchone("SELECT * FROM story_blocks WHERE project_id=%s AND id=%s", (pid, bid)))


@router.post("/projects/{pid}/story-blocks/{bid}/close")
async def close_story_block(pid: str, bid: str, data: StatusPayload):
    return await _set_status(pid, bid, "closed", data)


@router.post("/projects/{pid}/story-blocks/{bid}/complete")
async def complete_story_block(pid: str, bid: str, data: StatusPayload):
    return await _set_status(pid, bid, "completed", data)


@router.post("/projects/{pid}/story-blocks/{bid}/reviews")
async def create_story_block_review(pid: str, bid: str, data: StoryBlockReviewCreate):
    block = await _get_block(pid, bid)
    if data.decision not in ALLOWED_DECISIONS:
        raise HTTPException(400, "故事块回看决策不合法")
    now = int(time.time() * 1000)
    rid = str(uuid.uuid4())
    review = {**(data.review or {}), "decision": data.decision, "chapterNum": data.chapterNum}
    _validate_stage_continuation_reason(review)
    completed_stage_ids = _filter_executed_completed_stage_ids(
        block,
        review,
        _default_completed_stage_ids_for_review(data.decision, review),
    )
    if completed_stage_ids:
        review["completedStageIds"] = completed_stage_ids
    await execute(
        """
        INSERT INTO story_block_reviews
          (id, project_id, story_block_id, chapter_num, decision, review_json, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        """,
        (rid, pid, bid, data.chapterNum, data.decision, _json(review), now),
    )

    history = _list(block.get("review_history"))
    history_item = {"id": rid, "decision": data.decision, "chapterNum": data.chapterNum, "createdAt": now}
    if review.get("aiReviewFallback") is True:
        history_item["aiReviewFallback"] = True
    if review.get("stageContinues") is True:
        history_item["stageContinues"] = True
        history_item["stageContinueReason"] = _stage_continue_reason(review)
        history_item["reason"] = _stage_continue_reason(review)
    if review.get("aiReviewError"):
        history_item["aiReviewError"] = str(review.get("aiReviewError"))[:240]
    if review.get("completionEvidence"):
        history_item["completionEvidence"] = str(review.get("completionEvidence"))[:500]
    if review.get("singleChapterBlockReason"):
        history_item["singleChapterBlockReason"] = str(review.get("singleChapterBlockReason"))[:300]
    if review.get("closedBy"):
        history_item["closedBy"] = str(review.get("closedBy"))[:40]
    if review.get("blockCloseReasonType"):
        history_item["blockCloseReasonType"] = str(review.get("blockCloseReasonType"))[:80]
    if review.get("earlyCloseAllowed") is not None:
        history_item["earlyCloseAllowed"] = bool(review.get("earlyCloseAllowed"))
    if review.get("closedUnexecutedStageIds"):
        history_item["closedUnexecutedStageIds"] = _string_list(review.get("closedUnexecutedStageIds"))
    if review.get("invalidatedStageIds"):
        history_item["invalidatedStageIds"] = _string_list(review.get("invalidatedStageIds"))
    history.append(history_item)
    chapter_refs = _list(block.get("chapter_refs"))
    if data.chapterNum and data.chapterNum not in chapter_refs:
        chapter_refs.append(data.chapterNum)
    completed_stages = _list(block.get("completed_stages"))
    completed_ids = {
        str(stage.get("id"))
        for stage in completed_stages
        if isinstance(stage, dict) and stage.get("id")
    }
    completed_by_id = {
        str(stage.get("id")): stage
        for stage in completed_stages
        if isinstance(stage, dict) and stage.get("id")
    }
    for stage_id in completed_stage_ids:
        sid = str(stage_id or "")
        if sid and sid not in completed_ids:
            item = {"id": sid, "chapterNum": data.chapterNum, "reviewId": rid}
            completed_stages.append(item)
            completed_ids.add(sid)
            completed_by_id[sid] = item
    stage_plan = _apply_completed_stage_ids_to_plan(block.get("stage_plan"), completed_by_id)

    await execute(
        """
        UPDATE story_blocks
        SET review_history=%s, chapter_refs=%s, stage_plan=%s, completed_stages=%s, updated_at=%s
        WHERE project_id=%s AND id=%s
        """,
        (_json(history), _json(chapter_refs), _json(stage_plan), _json(completed_stages), now, pid, bid),
    )
    await touch_project(pid)
    return convert_row(await fetchone("SELECT * FROM story_block_reviews WHERE id=%s", (rid,)))


@router.post("/projects/{pid}/story-blocks/{bid}/confirm-review")
async def confirm_story_block_review(pid: str, bid: str, data: ConfirmReviewPayload):
    block = await _get_block(pid, bid)
    lock_state = _dict(block.get("lock_state"))
    lock_state["requiresReview"] = False
    lock_state["reviewConfirmedAt"] = int(time.time() * 1000)
    if data.reason:
        lock_state["reviewConfirmReason"] = data.reason
    now = int(time.time() * 1000)
    await execute(
        """
        UPDATE story_blocks
        SET lock_state=%s, updated_at=%s
        WHERE project_id=%s AND id=%s
        """,
        (_json(lock_state), now, pid, bid),
    )
    await touch_project(pid)
    return convert_row(await fetchone("SELECT * FROM story_blocks WHERE project_id=%s AND id=%s", (pid, bid)))


async def _set_status(pid: str, bid: str, status: str, data: StatusPayload):
    _validate_status(status)
    block = await _get_block(pid, bid)
    chapter_refs = _list(block.get("chapter_refs"))
    for ref in data.chapterRefs or []:
        if ref not in chapter_refs:
            chapter_refs.append(ref)
    if status in {"completed", "closed"}:
        _validate_status_transition_evidence(status, data, chapter_refs)
    lock_state = _dict(block.get("lock_state"))
    close_reason = data.closeReason if data.closeReason in ALLOWED_CLOSE_REASONS else "unknown"
    closed_by = data.closedBy if data.closedBy in ALLOWED_CLOSED_BY else "user_manual"
    if data.reason:
        lock_state = {**lock_state, f"{status}Reason": data.reason}
    if status in {"completed", "closed"}:
        lock_state = {
            **lock_state,
            "closedBy": closed_by,
            "completionEvidence": data.completionEvidence or data.reason or "",
            "singleChapterBlockReason": data.singleChapterBlockReason or "",
            "blockCloseReasonType": data.blockCloseReasonType or "",
            "earlyCloseAllowed": data.earlyCloseAllowed,
            "earlyCloseEvidence": data.earlyCloseEvidence or data.completionEvidence or data.reason or "",
            "closedUnexecutedStageIds": _string_list(data.closedUnexecutedStageIds),
            "invalidatedStageIds": _string_list(data.invalidatedStageIds),
        }
    if status == "closed":
        lock_state = {**lock_state, "closeReason": close_reason}
        if close_reason == "unknown":
            lock_state["closeReasonWarning"] = "关闭原因未知，请产品复核。"
    if status == "completed":
        lock_state = {**lock_state, "closeReason": close_reason if close_reason != "unknown" else "block_goal_completed"}
    stage_plan = _stage_list(block.get("stage_plan"))
    if status in {"completed", "closed"}:
        locked_stage_ids = await _locked_stage_ids(pid, bid)
        stage_plan = _archive_unfinished_stages_for_closed_block(
            stage_plan,
            locked_stage_ids,
            invalidated_stage_ids=set(_string_list(data.invalidatedStageIds)),
            closed_unexecuted_stage_ids=set(_string_list(data.closedUnexecutedStageIds)),
        )
    now = int(time.time() * 1000)
    await execute(
        """
        UPDATE story_blocks
        SET status=%s, chapter_refs=%s, stage_plan=%s, lock_state=%s, updated_at=%s
        WHERE project_id=%s AND id=%s
        """,
        (status, _json(chapter_refs), _json(stage_plan), _json(lock_state), now, pid, bid),
    )
    await touch_project(pid)
    return convert_row(await fetchone("SELECT * FROM story_blocks WHERE project_id=%s AND id=%s", (pid, bid)))


def _validate_status_transition_evidence(status: str, data: StatusPayload, chapter_refs: list[Any]):
    close_reason = data.closeReason if data.closeReason in ALLOWED_CLOSE_REASONS else "unknown"
    closed_by = data.closedBy if data.closedBy in ALLOWED_CLOSED_BY else "user_manual"
    evidence = (data.completionEvidence or data.reason or "").strip()
    has_semantic_close_reason = close_reason != "unknown"
    if not evidence and not has_semantic_close_reason:
        raise HTTPException(400, f"故事块{status}需要 completionEvidence 或 closeReason")
    meaningful_refs = [ref for ref in chapter_refs if ref not in (None, "")]
    if closed_by == "ai_review" and len(set(map(str, meaningful_refs))) <= 1 and not (data.singleChapterBlockReason or "").strip():
        raise HTTPException(400, "AI 自动结束单章故事块必须提供 singleChapterBlockReason")


async def _get_block(pid: str, bid: str):
    block = await fetchone("SELECT * FROM story_blocks WHERE project_id=%s AND id=%s", (pid, bid))
    if not block:
        raise HTTPException(404, "故事块不存在")
    return block


async def _get_single_active_block(pid: str):
    rows = await fetchall(
        """
        SELECT * FROM story_blocks
        WHERE project_id=%s AND status='active'
        ORDER BY block_num DESC, created_at DESC
        """,
        (pid,),
    )
    if len(rows) > 1:
        raise HTTPException(409, "故事块数据异常：项目存在多个 active 故事块，请先关闭多余故事块")
    return rows[0] if rows else None


async def _reject_existing_active_block(pid: str):
    active = await _get_single_active_block(pid)
    if active:
        raise HTTPException(409, "项目已有 active 故事块，请先显式关闭或完成当前块")


async def _next_block_num(pid: str) -> int:
    row = await fetchone("SELECT COALESCE(MAX(block_num), 0) AS n FROM story_blocks WHERE project_id=%s", (pid,))
    return int((row or {}).get("n") or 0) + 1


async def _locked_stage_ids(pid: str, bid: str) -> set[str]:
    rows = await fetchall(
        """
        SELECT DISTINCT block_stage_id
        FROM chapter_beat_plans
        WHERE project_id=%s AND story_block_id=%s AND block_stage_id IS NOT NULL
        """,
        (pid, bid),
    )
    return {str(row.get("block_stage_id")) for row in rows if row.get("block_stage_id")}


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


def _closed_stage_ids(block) -> set[str]:
    ids = set()
    for stage in _stage_list(block.get("stage_plan")):
        if stage.get("status") in {"closed", "skipped", CLOSED_UNEXECUTED_STAGE_STATUS, SKIPPED_BY_BLOCK_CLOSE_STATUS, INVALIDATED_STAGE_STATUS} and stage.get("id"):
            ids.add(str(stage["id"]))
    return ids


def _review_stage_continues(review: dict) -> bool:
    return review.get("stageContinues") is True


def _stage_continue_reason(review: dict) -> str:
    return str(
        review.get("stageContinueReason")
        or review.get("stage_continue_reason")
        or review.get("reason")
        or ""
    ).strip()


def _validate_stage_continuation_reason(review: dict):
    if review.get("stageContinues") is not True:
        return
    reason = _stage_continue_reason(review)
    if not reason:
        raise HTTPException(
            400,
            {
                "code": "story_block_review_invalid",
                "message": "stageContinues=true 时必须提供 stageContinueReason，说明本阶段未完成原因和下一章承接动作。",
                "field": "stageContinueReason",
            },
        )
    review["stageContinueReason"] = reason
    if not str(review.get("reason") or "").strip():
        review["reason"] = reason


def _default_completed_stage_ids_for_review(decision: str, review: dict) -> list[str]:
    completed = []
    seen = set()
    for stage_id in review.get("completedStageIds") or []:
        sid = str(stage_id or "").strip()
        if sid and sid not in seen:
            completed.append(sid)
            seen.add(sid)

    if decision not in {"continue_current_block", "adjust_remaining_stages", "complete_current_block", "open_new_block"}:
        return completed
    if _review_stage_continues(review):
        return completed

    snapshot = _dict(review.get("blockStageSnapshot"))
    sid = str(snapshot.get("stageId") or review.get("blockStageId") or "").strip()
    if sid and sid not in seen:
        completed.append(sid)
    return completed


def _filter_executed_completed_stage_ids(block, review: dict, completed_stage_ids: list[Any]) -> list[str]:
    stage_plan = _stage_list(block.get("stage_plan"))
    current_snapshot = _dict(review.get("blockStageSnapshot"))
    current_stage_id = str(current_snapshot.get("stageId") or review.get("blockStageId") or "").strip()
    already_completed = _completed_stage_ids(block)
    stage_by_id = {
        str(stage.get("id") or ""): stage
        for stage in stage_plan
        if stage.get("id")
    }
    filtered = []
    seen = set()
    for stage_id in completed_stage_ids or []:
        sid = str(stage_id or "").strip()
        if not sid or sid in seen:
            continue
        stage = stage_by_id.get(sid) or {}
        if (
            sid == current_stage_id
            or sid in already_completed
            or stage.get("status") == "completed"
            or _stage_has_outline_or_chapter_refs(stage)
        ):
            filtered.append(sid)
            seen.add(sid)
    return filtered


def _apply_completed_stage_ids_to_plan(stage_plan, completed_by_id: dict[str, dict]) -> list[dict]:
    stages = _stage_list(stage_plan)
    if not completed_by_id:
        return stages
    updated = []
    for stage in stages:
        item = {**stage}
        stage_id = str(item.get("id") or "")
        if stage_id and stage_id in completed_by_id:
            completion = completed_by_id.get(stage_id) or {}
            item["status"] = "completed"
            if completion.get("chapterNum") is not None:
                item["completedChapterNum"] = completion.get("chapterNum")
                chapter_refs = _list(item.get("chapterRefs"))
                if completion.get("chapterNum") not in chapter_refs:
                    chapter_refs.append(completion.get("chapterNum"))
                item["chapterRefs"] = chapter_refs
        updated.append(item)
    return updated


def _archive_unfinished_stages_for_closed_block(
    stage_plan,
    locked_stage_ids: set[str] | None = None,
    invalidated_stage_ids: set[str] | None = None,
    closed_unexecuted_stage_ids: set[str] | None = None,
) -> list[dict]:
    locked_stage_ids = locked_stage_ids or set()
    invalidated_stage_ids = invalidated_stage_ids or set()
    closed_unexecuted_stage_ids = closed_unexecuted_stage_ids or set()
    updated = []
    for stage in _stage_list(stage_plan):
        item = {**stage}
        if item.get("status") == "completed":
            updated.append(item)
            continue
        stage_id = str(item.get("id") or "")
        if stage_id in locked_stage_ids or _stage_has_outline_or_chapter_refs(item):
            item["status"] = "locked"
            updated.append(item)
            continue
        if stage_id in invalidated_stage_ids:
            item["status"] = INVALIDATED_STAGE_STATUS
            item["closeStatus"] = SKIPPED_BY_BLOCK_CLOSE_STATUS
        else:
            item["status"] = CLOSED_UNEXECUTED_STAGE_STATUS
            item["closeStatus"] = SKIPPED_BY_BLOCK_CLOSE_STATUS
        updated.append(item)
    return updated


def _stage_has_outline_or_chapter_refs(stage: dict) -> bool:
    return bool(stage.get("lockedByBeatPlan")) or bool(stage.get("lockedByFinalChapter")) or bool(_list(stage.get("chapterRefs")))


def _string_list(values) -> list[str]:
    result = []
    seen = set()
    for value in _list(values):
        text = str(value or "").strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _validate_status(status: str):
    if status not in ALLOWED_STATUSES:
        raise HTTPException(400, "故事块状态不合法")


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


def _json(value):
    return json.dumps(value if value is not None else None, ensure_ascii=False)


def _compact_json(value) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
