"""创作圣经、滚动大纲、角色、伏笔、Canon事实、可能性池"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List
from database import fetchone, fetchall, execute
from .helpers import convert_row, convert_rows, to_snake
import uuid, time, json

router = APIRouter(tags=["novel"])

# --- 创作圣经 ---
class BibleUpdate(BaseModel):
    premise: str = ""
    targetReader: str = ""
    styleBible: str = ""
    themeBible: str = ""
    worldRules: str = ""
    confirmedSettings: Optional[List[str]] = None
    forbiddenDirections: Optional[List[str]] = None

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
        if isinstance(v, list):
            sets.append(f"{col}=%s"); args.append(json.dumps(v))
        else:
            sets.append(f"{col}=%s"); args.append(v)
    if rows:
        sets.append("updated_at=%s"); args.append(now); args.append(rows[0]['id'])
        await execute(f"UPDATE creative_bible SET {', '.join(sets)} WHERE id=%s", args)
    else:
        bid = str(uuid.uuid4())
        args = [bid, pid] + args
        await execute(f"INSERT INTO creative_bible (id, project_id, {','.join([to_snake(k) for k in data.dict()])}, updated_at) VALUES (%s,%s,{','.join(['%s']*len(data.dict()))},%s)", args + [now])
    return await get_bible(pid)

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
    far = json.dumps(data.get('farVision') or {})
    vol = json.dumps(data.get('currentVolume') or {})
    near = json.dumps(data.get('nearChapters') or [])
    if rows:
        await execute("UPDATE rolling_outlines SET far_vision=%s, current_volume=%s, near_chapters=%s, updated_at=%s WHERE id=%s",
                      (far, vol, near, now, rows[0]['id']))
    else:
        await execute("INSERT INTO rolling_outlines (id, project_id, far_vision, current_volume, near_chapters, updated_at) VALUES (%s,%s,%s,%s,%s,%s)",
                      (str(uuid.uuid4()), pid, far, vol, near, now))
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
    return convert_row(await fetchone("SELECT * FROM characters WHERE id=%s", (cid,)))

@router.delete("/projects/{pid}/characters/{cid}")
async def delete_character(pid: str, cid: str):
    await execute("DELETE FROM characters WHERE id=%s", (cid,))
    return {"ok": True}

# --- 伏笔 ---
@router.get("/projects/{pid}/plot-threads")
async def list_plot_threads(pid: str):
    return convert_rows(await fetchall("SELECT * FROM plot_threads WHERE project_id=%s ORDER BY created_at", (pid,)))

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
    return convert_row(await fetchone("SELECT * FROM plot_threads WHERE id=%s", (tid,)))

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
        return convert_row(await fetchone("SELECT * FROM plot_threads WHERE id=%s", (tid,)))
    sets.append("updated_at=%s"); args.append(now); args.append(tid)
    await execute(f"UPDATE plot_threads SET {', '.join(sets)} WHERE id=%s", args)
    return convert_row(await fetchone("SELECT * FROM plot_threads WHERE id=%s", (tid,)))

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
    await execute("""INSERT INTO canon_facts (id, project_id, chapter_num, fact_type, content,
             related_characters, related_plot_threads, evidence, confidence, status, created_at, updated_at)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
             (fid, pid, data.get('chapterNum',0), data.get('factType','plot'), data.get('content',''),
              json.dumps(data.get('relatedCharacters') or []), json.dumps(data.get('relatedPlotThreads') or []),
              data.get('evidence',''), data.get('confidence',0.8), data.get('status','pending_review'), now, now))
    return convert_row(await fetchone("SELECT * FROM canon_facts WHERE id=%s", (fid,)))

@router.put("/projects/{pid}/canon-facts/{fid}")
async def update_canon_fact(pid: str, fid: str, data: dict):
    now = int(time.time() * 1000)
    sets, args = [], []
    for k, v in data.items():
        if v is None: continue
        col = to_snake(k)
        if k in ('relatedCharacters', 'relatedPlotThreads'):
            sets.append(f"{col}=%s"); args.append(json.dumps(v))
        else:
            sets.append(f"{col}=%s"); args.append(v)
    if not sets:
        return convert_row(await fetchone("SELECT * FROM canon_facts WHERE id=%s", (fid,)))
    sets.append("updated_at=%s"); args.append(now); args.append(fid)
    await execute(f"UPDATE canon_facts SET {', '.join(sets)} WHERE id=%s", args)
    return convert_row(await fetchone("SELECT * FROM canon_facts WHERE id=%s", (fid,)))

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
