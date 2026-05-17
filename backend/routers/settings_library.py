"""设定库：人物、势力、地点、体系、物品、关系和状态变更。"""
from fastapi import APIRouter, Query
from database import fetchone, fetchall, execute
from .helpers import convert_row, convert_rows
import json
import time
import uuid

router = APIRouter(tags=["settings-library"])

ENTITY_FIELDS = {
    "entityType": ("entity_type", "text"),
    "name": ("name", "text"),
    "category": ("category", "text"),
    "summary": ("summary", "text"),
    "status": ("status", "text"),
    "importance": ("importance", "number"),
    "aliases": ("aliases", "json"),
    "tags": ("tags", "json"),
    "profile": ("profile", "json"),
    "firstChapter": ("first_chapter", "number"),
    "lastChapter": ("last_chapter", "number"),
}

RELATION_FIELDS = {
    "sourceEntityId": ("source_entity_id", "text"),
    "targetEntityId": ("target_entity_id", "text"),
    "relationType": ("relation_type", "text"),
    "stance": ("stance", "text"),
    "summary": ("summary", "text"),
    "isHidden": ("is_hidden", "bool"),
    "evidence": ("evidence", "text"),
    "chapterNum": ("chapter_num", "number"),
    "status": ("status", "text"),
}

CHANGE_FIELDS = {
    "entityType": ("entity_type", "text"),
    "entityId": ("entity_id", "text"),
    "entityName": ("entity_name", "text"),
    "changeType": ("change_type", "text"),
    "fieldPath": ("field_path", "text"),
    "oldValue": ("old_value", "text"),
    "newValue": ("new_value", "text"),
    "chapterNum": ("chapter_num", "number"),
    "evidence": ("evidence", "text"),
    "confidence": ("confidence", "number"),
    "status": ("status", "text"),
}


@router.get("/projects/{pid}/settings/entities")
async def list_setting_entities(
    pid: str,
    entityType: str = Query("", alias="type"),
    q: str = "",
):
    args = [pid]
    where = ["project_id=%s"]
    if entityType:
        where.append("entity_type=%s")
        args.append(entityType)
    if q:
        where.append("(name LIKE %s OR summary LIKE %s OR category LIKE %s)")
        like = f"%{q}%"
        args.extend([like, like, like])
    sql = f"""
        SELECT * FROM setting_entities
        WHERE {' AND '.join(where)}
        ORDER BY importance DESC, updated_at DESC
    """
    return convert_rows(await fetchall(sql, args))


@router.get("/projects/{pid}/settings/entities/{eid}")
async def get_setting_entity(pid: str, eid: str):
    return convert_row(await fetchone(
        "SELECT * FROM setting_entities WHERE project_id=%s AND id=%s",
        (pid, eid),
    ))


@router.post("/projects/{pid}/settings/entities")
async def create_setting_entity(pid: str, data: dict):
    now = int(time.time() * 1000)
    eid = str(uuid.uuid4())
    values = {
        "id": eid,
        "project_id": pid,
        "entity_type": data.get("entityType") or "character",
        "name": data.get("name") or "",
        "category": data.get("category") or "",
        "summary": data.get("summary") or "",
        "status": data.get("status") or "active",
        "importance": data.get("importance") or 3,
        "aliases": _json(data.get("aliases") or []),
        "tags": _json(data.get("tags") or []),
        "profile": _json(data.get("profile") or {}),
        "first_chapter": data.get("firstChapter"),
        "last_chapter": data.get("lastChapter"),
        "created_at": now,
        "updated_at": now,
    }
    await _insert("setting_entities", values)
    return await get_setting_entity(pid, eid)


@router.put("/projects/{pid}/settings/entities/{eid}")
async def update_setting_entity(pid: str, eid: str, data: dict):
    await _update("setting_entities", ENTITY_FIELDS, data, "project_id=%s AND id=%s", (pid, eid))
    return await get_setting_entity(pid, eid)


@router.delete("/projects/{pid}/settings/entities/{eid}")
async def delete_setting_entity(pid: str, eid: str):
    await execute("DELETE FROM setting_relations WHERE project_id=%s AND (source_entity_id=%s OR target_entity_id=%s)", (pid, eid, eid))
    await execute("DELETE FROM setting_entities WHERE project_id=%s AND id=%s", (pid, eid))
    return {"ok": True}


@router.get("/projects/{pid}/settings/relations")
async def list_setting_relations(pid: str, entityId: str = ""):
    if entityId:
        rows = await fetchall(
            """
            SELECT * FROM setting_relations
            WHERE project_id=%s AND (source_entity_id=%s OR target_entity_id=%s)
            ORDER BY updated_at DESC
            """,
            (pid, entityId, entityId),
        )
    else:
        rows = await fetchall(
            "SELECT * FROM setting_relations WHERE project_id=%s ORDER BY updated_at DESC",
            (pid,),
        )
    return convert_rows(rows)


@router.post("/projects/{pid}/settings/relations")
async def create_setting_relation(pid: str, data: dict):
    now = int(time.time() * 1000)
    rid = str(uuid.uuid4())
    values = {
        "id": rid,
        "project_id": pid,
        "source_entity_id": data.get("sourceEntityId") or "",
        "target_entity_id": data.get("targetEntityId") or "",
        "relation_type": data.get("relationType") or "",
        "stance": data.get("stance") or "",
        "summary": data.get("summary") or "",
        "is_hidden": 1 if data.get("isHidden") else 0,
        "evidence": data.get("evidence") or "",
        "chapter_num": data.get("chapterNum"),
        "status": data.get("status") or "active",
        "created_at": now,
        "updated_at": now,
    }
    await _insert("setting_relations", values)
    return convert_row(await fetchone(
        "SELECT * FROM setting_relations WHERE project_id=%s AND id=%s",
        (pid, rid),
    ))


@router.put("/projects/{pid}/settings/relations/{rid}")
async def update_setting_relation(pid: str, rid: str, data: dict):
    await _update("setting_relations", RELATION_FIELDS, data, "project_id=%s AND id=%s", (pid, rid))
    return convert_row(await fetchone(
        "SELECT * FROM setting_relations WHERE project_id=%s AND id=%s",
        (pid, rid),
    ))


@router.delete("/projects/{pid}/settings/relations/{rid}")
async def delete_setting_relation(pid: str, rid: str):
    await execute("DELETE FROM setting_relations WHERE project_id=%s AND id=%s", (pid, rid))
    return {"ok": True}


@router.get("/projects/{pid}/settings/change-events")
async def list_setting_change_events(pid: str, status: str = "", chapterNum: int | None = None):
    args = [pid]
    where = ["project_id=%s"]
    if status:
        where.append("status=%s")
        args.append(status)
    if chapterNum is not None:
        where.append("chapter_num=%s")
        args.append(chapterNum)
    sql = f"""
        SELECT * FROM setting_change_events
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC
    """
    return convert_rows(await fetchall(sql, args))


@router.post("/projects/{pid}/settings/change-events")
async def create_setting_change_event(pid: str, data: dict):
    now = int(time.time() * 1000)
    cid = str(uuid.uuid4())
    values = {
        "id": cid,
        "project_id": pid,
        "entity_type": data.get("entityType") or "",
        "entity_id": data.get("entityId"),
        "entity_name": data.get("entityName") or "",
        "change_type": data.get("changeType") or "update",
        "field_path": data.get("fieldPath") or "",
        "old_value": data.get("oldValue") or "",
        "new_value": data.get("newValue") or "",
        "chapter_num": data.get("chapterNum"),
        "evidence": data.get("evidence") or "",
        "confidence": data.get("confidence") or 0.8,
        "status": data.get("status") or "pending_review",
        "created_at": now,
        "updated_at": now,
    }
    await _insert("setting_change_events", values)
    return convert_row(await fetchone(
        "SELECT * FROM setting_change_events WHERE project_id=%s AND id=%s",
        (pid, cid),
    ))


@router.put("/projects/{pid}/settings/change-events/{cid}")
async def update_setting_change_event(pid: str, cid: str, data: dict):
    await _update("setting_change_events", CHANGE_FIELDS, data, "project_id=%s AND id=%s", (pid, cid))
    return convert_row(await fetchone(
        "SELECT * FROM setting_change_events WHERE project_id=%s AND id=%s",
        (pid, cid),
    ))


@router.post("/projects/{pid}/settings/change-events/{cid}/accept")
async def accept_setting_change_event(pid: str, cid: str):
    event = await fetchone(
        "SELECT * FROM setting_change_events WHERE project_id=%s AND id=%s",
        (pid, cid),
    )
    if not event:
        return {"ok": False, "error": "change event not found"}

    entity = None
    relation = None
    if event.get("change_type") == "relationship":
        relation = await _apply_relationship_event(pid, event)
    else:
        entity = await _apply_entity_event(pid, event)

    await execute(
        "UPDATE setting_change_events SET status=%s, entity_id=%s, updated_at=%s WHERE project_id=%s AND id=%s",
        ("accepted", entity.get("id") if entity else event.get("entity_id"), int(time.time() * 1000), pid, cid),
    )
    updated_event = convert_row(await fetchone(
        "SELECT * FROM setting_change_events WHERE project_id=%s AND id=%s",
        (pid, cid),
    ))
    return {
        "ok": True,
        "event": updated_event,
        "entity": convert_row(entity) if entity else None,
        "relation": convert_row(relation) if relation else None,
    }


@router.post("/projects/{pid}/settings/change-events/{cid}/reject")
async def reject_setting_change_event(pid: str, cid: str):
    await execute(
        "UPDATE setting_change_events SET status=%s, updated_at=%s WHERE project_id=%s AND id=%s",
        ("rejected", int(time.time() * 1000), pid, cid),
    )
    return {
        "ok": True,
        "event": convert_row(await fetchone(
            "SELECT * FROM setting_change_events WHERE project_id=%s AND id=%s",
            (pid, cid),
        ))
    }


@router.delete("/projects/{pid}/settings/change-events/{cid}")
async def delete_setting_change_event(pid: str, cid: str):
    await execute("DELETE FROM setting_change_events WHERE project_id=%s AND id=%s", (pid, cid))
    return {"ok": True}


def _json(value):
    return json.dumps(value, ensure_ascii=False)


async def _insert(table: str, values: dict):
    cols = list(values.keys())
    args = list(values.values())
    placeholders = ",".join(["%s"] * len(cols))
    await execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})", args)


async def _update(table: str, field_map: dict, data: dict, where_sql: str, where_args: tuple):
    sets, args = [], []
    for js_key, (col, value_type) in field_map.items():
        if js_key not in data:
            continue
        value = data[js_key]
        if value_type == "json":
            value = _json(value or ([] if js_key in ("aliases", "tags") else {}))
        elif value_type == "bool":
            value = 1 if value else 0
        sets.append(f"{col}=%s")
        args.append(value)
    if not sets:
        return
    sets.append("updated_at=%s")
    args.append(int(time.time() * 1000))
    args.extend(where_args)
    await execute(f"UPDATE {table} SET {', '.join(sets)} WHERE {where_sql}", args)


async def _apply_entity_event(pid: str, event: dict):
    entity_type = event.get("entity_type") or "character"
    entity_name = event.get("entity_name") or ""
    entity = await _find_or_create_entity(pid, entity_type, entity_name, event)
    profile = _decode_json(entity.get("profile")) or {}
    now = int(time.time() * 1000)
    updates = {"last_chapter": event.get("chapter_num"), "updated_at": now}

    payload = _decode_json(event.get("new_value"))
    field_path = _normalize_field_path(event.get("field_path") or "")

    if event.get("change_type") == "new_entity":
        if isinstance(payload, dict):
            if payload.get("summary"):
                updates["summary"] = payload.get("summary")
            if payload.get("category"):
                updates["category"] = payload.get("category")
            if payload.get("importance"):
                updates["importance"] = payload.get("importance")
            if isinstance(payload.get("profile"), dict):
                profile.update(_clean_empty(payload["profile"]))
            if isinstance(payload.get("tags"), list):
                updates["tags"] = _json(payload["tags"])
        elif event.get("new_value"):
            updates["summary"] = event.get("new_value")
        if not entity.get("first_chapter") and event.get("chapter_num"):
            updates["first_chapter"] = event.get("chapter_num")
    elif field_path.startswith("profile."):
        key = field_path.split(".", 1)[1]
        if key:
            profile[key] = _stringify_value(event.get("new_value"))
    elif field_path in ENTITY_COLUMN_PATHS:
        updates[ENTITY_COLUMN_PATHS[field_path]] = _stringify_value(event.get("new_value"))
    elif event.get("new_value"):
        profile[field_path or "notes"] = _stringify_value(event.get("new_value"))

    updates["profile"] = _json(profile)
    await _update_by_columns("setting_entities", updates, "project_id=%s AND id=%s", (pid, entity["id"]))
    return await fetchone("SELECT * FROM setting_entities WHERE project_id=%s AND id=%s", (pid, entity["id"]))


async def _apply_relationship_event(pid: str, event: dict):
    payload = _decode_json(event.get("new_value")) or {}
    if not isinstance(payload, dict):
        payload = {"summary": event.get("new_value") or ""}

    source = await _find_or_create_entity(
        pid,
        event.get("entity_type") or "character",
        event.get("entity_name") or "未命名主体",
        event,
    )
    target = await _find_or_create_entity(
        pid,
        payload.get("targetEntityType") or payload.get("targetType") or "character",
        payload.get("targetEntityName") or payload.get("targetName") or payload.get("target") or "未命名客体",
        event,
    )

    relation_type = payload.get("relationType") or event.get("field_path") or "关系"
    existing = await fetchone(
        """
        SELECT * FROM setting_relations
        WHERE project_id=%s AND source_entity_id=%s AND target_entity_id=%s AND relation_type=%s
        """,
        (pid, source["id"], target["id"], relation_type),
    )
    now = int(time.time() * 1000)
    values = {
        "stance": payload.get("stance") or "",
        "summary": payload.get("summary") or event.get("evidence") or "",
        "evidence": event.get("evidence") or "",
        "chapter_num": event.get("chapter_num"),
        "status": "active",
        "updated_at": now,
    }
    if existing:
        await _update_by_columns("setting_relations", values, "project_id=%s AND id=%s", (pid, existing["id"]))
        return await fetchone("SELECT * FROM setting_relations WHERE project_id=%s AND id=%s", (pid, existing["id"]))

    rid = str(uuid.uuid4())
    values.update({
        "id": rid,
        "project_id": pid,
        "source_entity_id": source["id"],
        "target_entity_id": target["id"],
        "relation_type": relation_type,
        "is_hidden": 0,
        "created_at": now,
    })
    await _insert("setting_relations", values)
    return await fetchone("SELECT * FROM setting_relations WHERE project_id=%s AND id=%s", (pid, rid))


async def _find_or_create_entity(pid: str, entity_type: str, name: str, event: dict):
    entity_id = event.get("entity_id")
    if entity_id:
        existing = await fetchone(
            "SELECT * FROM setting_entities WHERE project_id=%s AND id=%s",
            (pid, entity_id),
        )
        if existing:
            return existing

    existing = await fetchone(
        "SELECT * FROM setting_entities WHERE project_id=%s AND entity_type=%s AND name=%s LIMIT 1",
        (pid, entity_type, name),
    )
    if existing:
        return existing

    now = int(time.time() * 1000)
    eid = str(uuid.uuid4())
    await _insert("setting_entities", {
        "id": eid,
        "project_id": pid,
        "entity_type": entity_type,
        "name": name,
        "category": "",
        "summary": f"第 {event.get('chapter_num') or '?'} 章自动识别的设定",
        "status": "active",
        "importance": 3,
        "aliases": _json([]),
        "tags": _json(["AI识别"]),
        "profile": _json({}),
        "first_chapter": event.get("chapter_num"),
        "last_chapter": event.get("chapter_num"),
        "created_at": now,
        "updated_at": now,
    })
    return await fetchone("SELECT * FROM setting_entities WHERE project_id=%s AND id=%s", (pid, eid))


async def _update_by_columns(table: str, values: dict, where_sql: str, where_args: tuple):
    clean = {k: v for k, v in values.items() if v is not None}
    if not clean:
        return
    sets = [f"{key}=%s" for key in clean.keys()]
    args = list(clean.values()) + list(where_args)
    await execute(f"UPDATE {table} SET {', '.join(sets)} WHERE {where_sql}", args)


def _decode_json(value):
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except ValueError:
        return None


def _stringify_value(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else str(value)


def _clean_empty(data: dict):
    return {k: v for k, v in data.items() if v not in (None, "", [])}


ENTITY_COLUMN_PATHS = {
    "summary": "summary",
    "category": "category",
    "status": "status",
    "importance": "importance",
    "firstChapter": "first_chapter",
    "lastChapter": "last_chapter",
}


FIELD_ALIASES = {
    "新增人物": "summary",
    "状态变化": "profile.currentState",
    "家族": "profile.family",
    "宗门": "profile.sect",
    "门派": "profile.sect",
    "阵营": "profile.faction",
    "国家": "profile.nation",
    "身份": "profile.rankTitle",
    "境界": "profile.realm",
    "境界层级": "profile.realmLevel",
    "功法": "profile.techniques",
    "武器": "profile.weapons",
    "法宝": "profile.weapons",
    "位置": "profile.location",
    "地点": "profile.location",
    "身体状态": "profile.physicalStatus",
    "心理状态": "profile.mentalState",
    "当前目标": "profile.currentGoal",
    "持有者": "profile.owner",
    "品阶": "profile.grade",
    "能力": "profile.ability",
}


def _normalize_field_path(field_path: str):
    return FIELD_ALIASES.get(field_path, field_path)
