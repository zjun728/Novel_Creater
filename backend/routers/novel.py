"""创作圣经、滚动大纲、角色、伏笔、Canon事实、可能性池"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List, Any
from database import fetchone, fetchall, execute
from .helpers import convert_row, convert_rows, to_snake, touch_project
from .provenance_support import persist_provenance_if_columns
from .guards import ensure_project_without_chapter_content
import uuid, time, json

router = APIRouter(tags=["novel"])

PROVENANCE_INPUT_KEYS = {
    "provenance",
    "sourceProvenance",
    "snapshotProvenance",
    "sourceChapterNum",
    "sourceVersionId",
    "runId",
    "finalizationId",
    "commitStatus",
}

# --- 创作圣经 ---
class BibleUpdate(BaseModel):
    premise: str = ""
    targetReader: str = ""
    styleBible: str = ""
    themeBible: str = ""
    worldRules: str = ""
    writingProfile: Optional[Any] = None
    forbiddenDirections: Optional[List[str]] = None


class ProjectAuditCreate(BaseModel):
    reportType: str = "global"
    title: str = ""
    report: dict

@router.get("/projects/{pid}/bible")
async def get_bible(pid: str):
    rows = await fetchall("SELECT * FROM creative_bible WHERE project_id=%s", (pid,))
    r = convert_rows(rows)
    return r[0] if r else None

@router.put("/projects/{pid}/bible")
async def save_bible(pid: str, data: BibleUpdate):
    now = int(time.time() * 1000)
    rows = await fetchall("SELECT * FROM creative_bible WHERE project_id=%s", (pid,))
    sets, args = [], []
    for k, v in data.dict().items():
        col = to_snake(k)
        if isinstance(v, (list, dict)):
            sets.append(f"{col}=%s"); args.append(json.dumps(v, ensure_ascii=False))
        else:
            sets.append(f"{col}=%s"); args.append(v)
    if rows:
        sets.append("updated_at=%s"); args.append(now); args.append(rows[0]['id'])
        await execute(f"UPDATE creative_bible SET {', '.join(sets)} WHERE id=%s", args)
    else:
        bid = str(uuid.uuid4())
        args = [bid, pid] + args
        await execute(f"INSERT INTO creative_bible (id, project_id, {','.join([to_snake(k) for k in data.dict()])}, updated_at) VALUES (%s,%s,{','.join(['%s']*len(data.dict()))},%s)", args + [now])
    await touch_project(pid)
    return await get_bible(pid)

@router.delete("/projects/{pid}/bible")
async def delete_bible(pid: str):
    await ensure_project_without_chapter_content(pid, "删除创作圣经")
    await execute("DELETE FROM creative_bible WHERE project_id=%s", (pid,))
    await touch_project(pid)
    return {"ok": True}


# --- 项目级审稿报告 ---
@router.get("/projects/{pid}/global-audits")
async def list_global_audits(pid: str):
    return convert_rows(await fetchall(
        """
        SELECT * FROM project_audit_reports
        WHERE project_id=%s AND report_type='global'
        ORDER BY created_at DESC
        LIMIT 10
        """,
        (pid,),
    ))


@router.post("/projects/{pid}/global-audits")
async def create_global_audit(pid: str, data: ProjectAuditCreate):
    now = int(time.time() * 1000)
    rid = str(uuid.uuid4())
    await execute(
        """
        INSERT INTO project_audit_reports (
          id, project_id, report_type, title, report_json, created_at
        ) VALUES (%s,%s,%s,%s,%s,%s)
        """,
        (
            rid,
            pid,
            data.reportType or "global",
            data.title or "全局审稿报告",
            json.dumps(data.report, ensure_ascii=False),
            now,
        ),
    )
    await touch_project(pid)
    return convert_row(await fetchone("SELECT * FROM project_audit_reports WHERE id=%s", (rid,)))


@router.delete("/projects/{pid}/global-audits/{rid}")
async def delete_global_audit(pid: str, rid: str):
    await execute("DELETE FROM project_audit_reports WHERE project_id=%s AND id=%s", (pid, rid))
    await touch_project(pid)
    return {"ok": True}

# --- 滚动大纲 ---
@router.get("/projects/{pid}/outline")
async def get_outline(pid: str):
    rows = await fetchall("SELECT * FROM rolling_outlines WHERE project_id=%s", (pid,))
    r = convert_rows(rows)
    return r[0] if r else None

@router.put("/projects/{pid}/outline")
async def save_outline(pid: str, data: dict):
    now = int(time.time() * 1000)
    rows = await fetchall("SELECT * FROM rolling_outlines WHERE project_id=%s", (pid,))
    far = json.dumps(data.get('farVision') or {}, ensure_ascii=False)
    vol = json.dumps(data.get('currentVolume') or {}, ensure_ascii=False)
    near = json.dumps(data.get('nearChapters') or [], ensure_ascii=False)
    if rows:
        await execute("UPDATE rolling_outlines SET far_vision=%s, current_volume=%s, near_chapters=%s, updated_at=%s WHERE id=%s",
                      (far, vol, near, now, rows[0]['id']))
    else:
        await execute("INSERT INTO rolling_outlines (id, project_id, far_vision, current_volume, near_chapters, updated_at) VALUES (%s,%s,%s,%s,%s,%s)",
                      (str(uuid.uuid4()), pid, far, vol, near, now))
    await touch_project(pid)
    return await get_outline(pid)

# --- 角色 ---
@router.get("/projects/{pid}/characters")
async def list_characters(pid: str):
    return convert_rows(await fetchall("SELECT * FROM characters WHERE project_id=%s ORDER BY created_at", (pid,)))

@router.post("/projects/{pid}/characters")
async def create_character(pid: str, data: dict):
    now = int(time.time() * 1000)
    cid = str(uuid.uuid4())
    await execute("""INSERT INTO characters (id, project_id, name, role, appearance, personality, desire,
             fear, misbelief, secret, relationship_notes, arc_stage, hard_state, soft_state, created_at, updated_at)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
             (cid, pid, data.get('name',''), data.get('role','supporting'), data.get('appearance',''),
              data.get('personality',''), data.get('desire',''), data.get('fear',''), data.get('misbelief',''),
              data.get('secret',''), data.get('relationshipNotes',''), data.get('arcStage',''),
              json.dumps(data.get('hardState') or {}), json.dumps(data.get('softState') or {}), now, now))
    await persist_provenance_if_columns("characters", cid, data)
    return convert_row(await fetchone("SELECT * FROM characters WHERE id=%s", (cid,)))

@router.put("/projects/{pid}/characters/{cid}")
async def update_character(pid: str, cid: str, data: dict):
    now = int(time.time() * 1000)
    sets, args = [], []
    field_map = {'name':'name','role':'role','appearance':'appearance','personality':'personality',
                 'desire':'desire','fear':'fear','misbelief':'misbelief','secret':'secret',
                 'relationshipNotes':'relationship_notes','arcStage':'arc_stage'}
    for js_key, col in field_map.items():
        if js_key in data and data[js_key] is not None:
            sets.append(f"{col}=%s"); args.append(data[js_key])
    if 'hardState' in data and data['hardState'] is not None:
        sets.append("hard_state=%s"); args.append(json.dumps(data['hardState']))
    if 'softState' in data and data['softState'] is not None:
        sets.append("soft_state=%s"); args.append(json.dumps(data['softState']))
    if not sets:
        return convert_row(await fetchone("SELECT * FROM characters WHERE id=%s", (cid,)))
    sets.append("updated_at=%s"); args.append(now); args.append(cid)
    await execute(f"UPDATE characters SET {', '.join(sets)} WHERE id=%s", args)
    await persist_provenance_if_columns("characters", cid, data)
    return convert_row(await fetchone("SELECT * FROM characters WHERE id=%s", (cid,)))

@router.delete("/projects/{pid}/characters/{cid}")
async def delete_character(pid: str, cid: str):
    await execute("DELETE FROM characters WHERE id=%s", (cid,))
    return {"ok": True}

# --- 伏笔 ---
@router.get("/projects/{pid}/plot-threads")
async def list_plot_threads(pid: str):
    return _augment_plot_threads(await fetchall("SELECT * FROM plot_threads WHERE project_id=%s ORDER BY created_at", (pid,)))

def _decode_json_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [item for item in value if item is not None]
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [item for item in parsed if item is not None]
            if isinstance(parsed, str):
                return [parsed]
            return []
        except (TypeError, ValueError):
            return [part.strip() for part in text.replace("；", ",").replace("，", ",").split(",") if part.strip()]
    return []

def _plot_thread_title(value):
    text = str(value or "").strip()
    text = text.lstrip("#＃").strip()
    text = text.strip("「」《》【】[]（）()：:、，,。；; \t\r\n")
    text = " ".join(text.split())
    return text[:80]

def _plot_thread_key(value):
    return _plot_thread_title(value).lower()

PLOT_THREAD_SYSTEM_TAG_TITLES = {
    "主线推进",
    "世界观",
    "身体状态",
    "时间线",
    "时间紧迫线",
    "关键道具清单",
    "线索判断",
    "章节锚点",
    "硬状态账本",
    "关键地点线",
    "势力斗争线",
    "追捕线",
    "感情关系线",
}

PLOT_THREAD_REAL_TITLES = {
    "星账代价线",
    "父亲线索线",
    "第三密栈行动",
    "庚字号门后的真相",
    "天池裂隙",
    "徐正清身份疑点",
    "小九身世线",
    "反派阴谋线",
    "主角身世线",
    "关键道具线",
}

PLOT_THREAD_BROAD_UNRESOLVABLE_TITLES = {
    "主角身世线",
    "关键道具线",
    "反派阴谋线",
    "星账代价线",
    "主线推进",
}

PLOT_THREAD_RESOLVE_PHRASES = (
    "真相揭开",
    "谜底是",
    "证实为",
    "已确认答案",
    "找到真正原因",
    "完成回收",
    "正式揭示",
)

def _plot_thread_text(thread):
    return " ".join(str(thread.get(key) or "") for key in ("title", "content", "notes", "evidence"))

def _plot_thread_class(thread):
    title = _plot_thread_title(thread.get("title"))
    text = _plot_thread_text(thread)
    if (thread.get("status") or "") == "candidate" and any(
        marker in text for marker in ("候选来源", "foreshadowingPlan", "分卷规划", "未来候选", "尚未由 Canon facts 证明")
    ):
        return "future_candidate"
    if title in PLOT_THREAD_SYSTEM_TAG_TITLES:
        return "system_tag"
    if title in PLOT_THREAD_REAL_TITLES:
        return "real_thread"
    if any(marker in title for marker in ("状态", "清单", "时间线", "位置", "持有物", "下一步行动", "地形信息", "身体", "伤势", "世界观", "章节锚点", "硬状态账本")):
        return "system_tag"
    if any(marker in title for marker in ("真相", "之谜", "秘密", "疑点", "阴谋", "黑幕", "密栈", "裂隙", "门后", "代价", "旧案", "身世")) or title.endswith("线"):
        return "real_thread"
    return "system_tag"

def _plot_thread_type(thread):
    title = _plot_thread_title(thread.get("title"))
    if any(marker in title for marker in ("主线", "父亲", "身世", "旧案")):
        return "mainline"
    if any(marker in title for marker in ("小九", "徐正清", "陆沉舟", "陆长庚", "身份")):
        return "character"
    if any(marker in title for marker in ("钥匙", "账", "星账", "道具", "玉佩", "印", "门")):
        return "prop"
    if any(marker in title for marker in ("巡天司", "商盟", "星债会", "密栈", "势力", "反派")):
        return "faction"
    if any(marker in title for marker in ("灵脉", "规则", "天池", "裂隙", "代价", "世界观")):
        return "setting"
    return "other"

def _thread_latest_chapter(thread):
    values = [
        thread.get("latest_chapter"),
        thread.get("latestChapter"),
        thread.get("resolved_chapter"),
        thread.get("resolvedChapter"),
        thread.get("planted_chapter"),
        thread.get("plantedChapter"),
    ]
    notes = str(thread.get("notes") or "")
    import re
    note_chapters = [int(match.group(1)) for match in re.finditer(r"第\s*(\d+)\s*章", notes)]
    values.extend(note_chapters)
    numeric = []
    for value in values:
        try:
            if value:
                numeric.append(int(value))
        except (TypeError, ValueError):
            continue
    return max(numeric) if numeric else 0

def _thread_latest_summary(thread):
    notes = str(thread.get("notes") or "")
    import re
    match = re.search(r"最近推进：第\s*\d+\s*章[，,]\s*(.+)$", notes)
    if match:
        return match.group(1).strip()
    return notes or str(thread.get("content") or "")

def _thread_node_summary(thread):
    def _num(*keys):
        for key in keys:
            try:
                value = thread.get(key)
                if value:
                    return int(value)
            except (TypeError, ValueError):
                continue
        return 0
    planted = _num("planted_chapter", "plantedChapter")
    latest = _thread_latest_chapter(thread)
    resolved = _num("resolved_chapter", "resolvedChapter")
    nodes = []
    if planted:
        nodes.append(f"第 {planted} 章埋设")
    if latest and latest != planted and latest != resolved:
        nodes.append(f"第 {latest} 章推进")
    if resolved:
        nodes.append(f"第 {resolved} 章回收")
    return " -> ".join(nodes)

def _augment_plot_thread(row):
    item = convert_row(row)
    if not item:
        return item
    raw = dict(row)
    item["threadClass"] = _plot_thread_class(raw)
    item["threadType"] = _plot_thread_type(raw)
    item["latestChapter"] = _thread_latest_chapter(raw)
    item["latestSummary"] = _thread_latest_summary(raw)
    item["nodeSummary"] = _thread_node_summary(raw)
    return item

def _augment_plot_threads(rows):
    return [_augment_plot_thread(row) for row in (rows or [])]

def _fact_chapter_num(fact):
    return int(fact.get("chapter_num") or fact.get("chapterNum") or 0)

def _fact_content(fact):
    return str(fact.get("content") or "").strip()

def _fact_evidence(fact):
    return str(fact.get("evidence") or "").strip()

def _fact_threads(fact):
    values = []
    for key in ("related_plot_threads", "relatedPlotThreads", "threadTags", "tags"):
        values.extend(_decode_json_list(fact.get(key)))
    seen = set()
    result = []
    for value in values:
        title = _plot_thread_title(value)
        key = _plot_thread_key(title)
        if title and key not in seen:
            seen.add(key)
            result.append(title)
    return result

def _fact_characters(fact):
    seen = set()
    result = []
    for value in _decode_json_list(fact.get("related_characters") or fact.get("relatedCharacters")):
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result

def _is_resolved_fact(fact):
    text = f"{_fact_content(fact)} {_fact_evidence(fact)}"
    return any(phrase in text for phrase in PLOT_THREAD_RESOLVE_PHRASES)

def _should_resolve_thread(title, facts):
    normalized = _plot_thread_title(title)
    if normalized in PLOT_THREAD_BROAD_UNRESOLVABLE_TITLES:
        return False
    return any(_is_resolved_fact(fact) for fact in facts)

def _thread_recent_notes(title, facts):
    ordered = sorted(facts, key=lambda fact: (_fact_chapter_num(fact), int(fact.get("updated_at") or fact.get("created_at") or 0)))
    if not ordered:
        return ""
    first_chapter = _fact_chapter_num(ordered[0])
    latest = ordered[-1]
    latest_chapter = _fact_chapter_num(latest)
    latest_content = _fact_content(latest)
    if len(latest_content) > 120:
        latest_content = latest_content[:117] + "..."
    return f"首次出现：第 {first_chapter} 章；最近推进：第 {latest_chapter} 章，{latest_content}"

def _merge_characters(existing, facts):
    merged = []
    seen = set()
    for value in _decode_json_list(existing):
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            merged.append(text)
    for fact in facts:
        for text in _fact_characters(fact):
            if text not in seen:
                seen.add(text)
                merged.append(text)
    return merged

async def _create_plot_thread(pid, *, title, content="", status="candidate", planted_chapter=None,
                              related_characters=None, resolved_chapter=None, notes=""):
    now = int(time.time() * 1000)
    tid = str(uuid.uuid4())
    await execute("""INSERT INTO plot_threads (id, project_id, title, content, status, planted_chapter,
             related_characters, possible_resolve_window, resolve_options, resolved_chapter, notes, created_at, updated_at)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
             (tid, pid, title, content, status, planted_chapter,
              json.dumps(related_characters or [], ensure_ascii=False),
              json.dumps([None, None], ensure_ascii=False),
              json.dumps([], ensure_ascii=False), resolved_chapter,
              notes, now, now))
    return tid

async def _update_plot_thread_from_sync(thread, *, title, content, status, planted_chapter,
                                        related_characters, resolved_chapter, notes):
    now = int(time.time() * 1000)
    await execute("""UPDATE plot_threads
             SET title=%s, content=%s, status=%s, planted_chapter=%s,
                 related_characters=%s, resolved_chapter=%s, notes=%s, updated_at=%s
             WHERE id=%s""",
             (title, content, status, planted_chapter,
              json.dumps(related_characters or [], ensure_ascii=False),
              resolved_chapter, notes, now, thread.get("id")))

def _candidate_content(volume):
    volume_num = volume.get("volume_num") or volume.get("volumeNum") or "?"
    return f"来自第 {volume_num} 卷 foreshadowingPlan 的候选伏笔，等待正文事实埋设。"

def _candidate_notes(volume):
    volume_num = volume.get("volume_num") or volume.get("volumeNum") or "?"
    return f"候选来源：第 {volume_num} 卷分卷规划；尚未由 Canon facts 证明已埋设。"

async def syncPlotThreadsFromCanonFacts(projectId: str):
    """Backfill/update plot_threads from accepted Canon facts and volume candidates."""
    pid = projectId
    existing_threads = await fetchall("SELECT * FROM plot_threads WHERE project_id=%s ORDER BY created_at", (pid,))
    threads_by_key = {
        _plot_thread_key(thread.get("title")): thread
        for thread in existing_threads
        if _plot_thread_key(thread.get("title"))
    }
    created = 0
    updated = 0
    candidates_created = 0

    volumes = await fetchall("SELECT * FROM project_volumes WHERE project_id=%s ORDER BY volume_num", (pid,))
    for volume in volumes:
        for item in _decode_json_list(volume.get("foreshadowing_plan") or volume.get("foreshadowingPlan")):
            title = _plot_thread_title(item)
            key = _plot_thread_key(title)
            if not title or key in threads_by_key:
                continue
            tid = await _create_plot_thread(
                pid,
                title=title,
                content=_candidate_content(volume),
                status="candidate",
                planted_chapter=None,
                related_characters=_decode_json_list(volume.get("key_characters") or volume.get("keyCharacters")),
                resolved_chapter=None,
                notes=_candidate_notes(volume),
            )
            thread = {
                "id": tid,
                "project_id": pid,
                "title": title,
                "content": _candidate_content(volume),
                "status": "candidate",
                "planted_chapter": None,
                "related_characters": json.dumps(_decode_json_list(volume.get("key_characters") or volume.get("keyCharacters")), ensure_ascii=False),
                "resolved_chapter": None,
                "notes": _candidate_notes(volume),
            }
            threads_by_key[key] = thread
            created += 1
            candidates_created += 1

    facts = await fetchall("""
        SELECT * FROM canon_facts
        WHERE project_id=%s AND status='accepted'
        ORDER BY chapter_num, created_at
    """, (pid,))
    grouped = {}
    for fact in facts:
        for title in _fact_threads(fact):
            grouped.setdefault(_plot_thread_key(title), {"title": title, "facts": []})["facts"].append(fact)

    for key, group in grouped.items():
        facts_for_thread = sorted(group["facts"], key=lambda fact: (_fact_chapter_num(fact), int(fact.get("updated_at") or fact.get("created_at") or 0)))
        if not facts_for_thread:
            continue
        chapters = sorted({_fact_chapter_num(fact) for fact in facts_for_thread if _fact_chapter_num(fact)})
        planted_chapter = chapters[0] if chapters else None
        resolved_facts = [fact for fact in facts_for_thread if _is_resolved_fact(fact)] if _should_resolve_thread(group["title"], facts_for_thread) else []
        resolved_chapter = _fact_chapter_num(resolved_facts[0]) if resolved_facts else None
        status = "resolved" if resolved_chapter else ("developing" if len(chapters) > 1 else "planted")
        notes = _thread_recent_notes(group["title"], facts_for_thread)
        thread = threads_by_key.get(key)
        related_characters = _merge_characters(thread.get("related_characters") if thread else [], facts_for_thread)
        existing_content = thread.get("content") if thread and thread.get("content") else ""
        if existing_content and not any(marker in existing_content for marker in ("foreshadowingPlan", "分卷规划", "候选伏笔")):
            content = existing_content
        else:
            content = f"由 Canon facts 自动同步：{group['title']}"
        if thread:
            existing_planted = thread.get("planted_chapter")
            if existing_planted:
                planted_chapter = min(int(existing_planted), planted_chapter or int(existing_planted))
            await _update_plot_thread_from_sync(
                thread,
                title=thread.get("title") or group["title"],
                content=content,
                status=status,
                planted_chapter=planted_chapter,
                related_characters=related_characters,
                resolved_chapter=resolved_chapter,
                notes=notes,
            )
            updated += 1
        else:
            tid = await _create_plot_thread(
                pid,
                title=group["title"],
                content=content,
                status=status,
                planted_chapter=planted_chapter,
                related_characters=related_characters,
                resolved_chapter=resolved_chapter,
                notes=notes,
            )
            threads_by_key[key] = {
                "id": tid,
                "project_id": pid,
                "title": group["title"],
                "content": content,
                "status": status,
                "planted_chapter": planted_chapter,
                "related_characters": json.dumps(related_characters, ensure_ascii=False),
                "resolved_chapter": resolved_chapter,
                "notes": notes,
            }
            created += 1

    rows = await fetchall("SELECT * FROM plot_threads WHERE project_id=%s ORDER BY created_at", (pid,))
    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "candidateCreated": candidates_created,
        "plotThreads": _augment_plot_threads(rows),
    }

@router.post("/projects/{pid}/plot-threads/sync-canon-facts")
async def sync_plot_threads_from_canon_facts(pid: str):
    return await syncPlotThreadsFromCanonFacts(pid)

@router.post("/projects/{pid}/plot-threads")
async def create_plot_thread(pid: str, data: dict):
    now = int(time.time() * 1000)
    tid = str(uuid.uuid4())
    await execute("""INSERT INTO plot_threads (id, project_id, title, content, status, planted_chapter,
             related_characters, possible_resolve_window, resolve_options, resolved_chapter, notes, created_at, updated_at)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
             (tid, pid, data.get('title',''), data.get('content',''), data.get('status','candidate'),
              data.get('plantedChapter'), json.dumps(data.get('relatedCharacters') or []),
              json.dumps(data.get('possibleResolveWindow') or [None, None]),
              json.dumps(data.get('resolveOptions') or []), data.get('resolvedChapter'),
              data.get('notes',''), now, now))
    return _augment_plot_thread(await fetchone("SELECT * FROM plot_threads WHERE id=%s", (tid,)))

@router.put("/projects/{pid}/plot-threads/{tid}")
async def update_plot_thread(pid: str, tid: str, data: dict):
    now = int(time.time() * 1000)
    sets, args = [], []
    field_map = {'title':'title','content':'content','status':'status','plantedChapter':'planted_chapter',
                 'resolvedChapter':'resolved_chapter','notes':'notes'}
    for js_key, col in field_map.items():
        if js_key in data and data[js_key] is not None:
            sets.append(f"{col}=%s"); args.append(data[js_key])
    for js_key, col in [('relatedCharacters','related_characters'),('possibleResolveWindow','possible_resolve_window'),('resolveOptions','resolve_options')]:
        if js_key in data and data[js_key] is not None:
            sets.append(f"{col}=%s"); args.append(json.dumps(data[js_key]))
    if not sets:
        return _augment_plot_thread(await fetchone("SELECT * FROM plot_threads WHERE id=%s", (tid,)))
    sets.append("updated_at=%s"); args.append(now); args.append(tid)
    await execute(f"UPDATE plot_threads SET {', '.join(sets)} WHERE id=%s", args)
    return _augment_plot_thread(await fetchone("SELECT * FROM plot_threads WHERE id=%s", (tid,)))

@router.delete("/projects/{pid}/plot-threads/{tid}")
async def delete_plot_thread(pid: str, tid: str):
    await execute("DELETE FROM plot_threads WHERE id=%s", (tid,))
    return {"ok": True}

# --- Canon 事实 ---
@router.get("/projects/{pid}/canon-facts")
async def list_canon_facts(pid: str):
    return convert_rows(await fetchall("SELECT * FROM canon_facts WHERE project_id=%s ORDER BY created_at DESC", (pid,)))

@router.post("/projects/{pid}/canon-facts")
async def create_canon_fact(pid: str, data: dict):
    now = int(time.time() * 1000)
    fid = str(uuid.uuid4())
    status = data.get('status','pending_review')
    await execute("""INSERT INTO canon_facts (id, project_id, chapter_num, fact_type, content,
             related_characters, related_plot_threads, evidence, confidence, status, created_at, updated_at)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
             (fid, pid, data.get('chapterNum',0), data.get('factType','plot'), data.get('content',''),
              json.dumps(data.get('relatedCharacters') or []), json.dumps(data.get('relatedPlotThreads') or []),
              data.get('evidence',''), data.get('confidence',0.8), status, now, now))
    if status == 'accepted' and not data.get('skipPlotThreadSync'):
        await syncPlotThreadsFromCanonFacts(pid)
    await persist_provenance_if_columns(
        "canon_facts",
        fid,
        data,
        {"sourceChapterNum": data.get("chapterNum"), "commitStatus": "final" if status == "accepted" else "pending_review"},
    )
    return convert_row(await fetchone("SELECT * FROM canon_facts WHERE id=%s", (fid,)))

@router.put("/projects/{pid}/canon-facts/{fid}")
async def update_canon_fact(pid: str, fid: str, data: dict):
    now = int(time.time() * 1000)
    sets, args = [], []
    for k, v in data.items():
        if v is None: continue
        if k == "skipPlotThreadSync": continue
        if k in PROVENANCE_INPUT_KEYS: continue
        col = to_snake(k)
        if k in ('relatedCharacters', 'relatedPlotThreads'):
            sets.append(f"{col}=%s"); args.append(json.dumps(v))
        else:
            sets.append(f"{col}=%s"); args.append(v)
    if not sets:
        await persist_provenance_if_columns("canon_facts", fid, data)
        return convert_row(await fetchone("SELECT * FROM canon_facts WHERE id=%s", (fid,)))
    sets.append("updated_at=%s"); args.append(now); args.append(fid)
    await execute(f"UPDATE canon_facts SET {', '.join(sets)} WHERE id=%s", args)
    await persist_provenance_if_columns("canon_facts", fid, data)
    row = await fetchone("SELECT * FROM canon_facts WHERE id=%s", (fid,))
    if row and row.get("status") == "accepted":
        await syncPlotThreadsFromCanonFacts(pid)
    return convert_row(row)

# --- 可能性池 ---
@router.get("/projects/{pid}/possibility-cards")
async def list_possibility_cards(pid: str):
    return convert_rows(await fetchall("SELECT * FROM possibility_cards WHERE project_id=%s ORDER BY created_at DESC", (pid,)))

@router.post("/projects/{pid}/possibility-cards")
async def create_possibility_card(pid: str, data: dict):
    now = int(time.time() * 1000)
    cid = str(uuid.uuid4())
    await execute("""INSERT INTO possibility_cards (id, project_id, type, title, content, source, status,
             related_chapter, related_characters, created_at)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
             (cid, pid, data.get('type','plot_twist'), data.get('title',''), data.get('content',''),
              data.get('source','ai'), data.get('status','candidate'), data.get('relatedChapter'),
              json.dumps(data.get('relatedCharacters') or []), now))
    return convert_row(await fetchone("SELECT * FROM possibility_cards WHERE id=%s", (cid,)))

@router.delete("/projects/{pid}/possibility-cards/{cid}")
async def delete_possibility_card(pid: str, cid: str):
    await execute("DELETE FROM possibility_cards WHERE id=%s", (cid,))
    return {"ok": True}
