"""设定库：人物、势力、地点、体系、物品、关系和状态变更。"""
from fastapi import APIRouter, Body, HTTPException, Query
from database import fetchone, fetchall, execute
from .helpers import convert_row, convert_rows, touch_project
from .guards import ensure_project_without_chapter_content
import json
import re
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
    await ensure_project_without_chapter_content(pid, "删除设定实体")
    await execute("DELETE FROM setting_relations WHERE project_id=%s AND (source_entity_id=%s OR target_entity_id=%s)", (pid, eid, eid))
    await execute("DELETE FROM setting_entities WHERE project_id=%s AND id=%s", (pid, eid))
    await touch_project(pid)
    return {"ok": True}


@router.delete("/projects/{pid}/settings")
async def clear_setting_library(pid: str):
    await ensure_project_without_chapter_content(pid, "清空设定库")
    await execute("DELETE FROM setting_relations WHERE project_id=%s", (pid,))
    await execute("DELETE FROM setting_change_events WHERE project_id=%s", (pid,))
    await execute("DELETE FROM setting_entities WHERE project_id=%s", (pid,))
    await touch_project(pid)
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
    await ensure_project_without_chapter_content(pid, "删除设定关系")
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
    event_status = data.get("status") or "pending_review"
    if event_status == "pending_review" and _is_invalid_placeholder_entity_event(data):
        event_status = "rejected"
    values = {
        "id": cid,
        "project_id": pid,
        "entity_type": data.get("entityType") or "",
        "entity_id": data.get("entityId"),
        "entity_name": data.get("entityName") or "",
        "change_type": data.get("changeType") or "update",
        "field_path": data.get("fieldPath") or "",
        "old_value": _stringify_value(data.get("oldValue")),
        "new_value": _stringify_value(data.get("newValue")),
        "chapter_num": data.get("chapterNum"),
        "evidence": data.get("evidence") or "",
        "confidence": data.get("confidence") or 0.8,
        "status": event_status,
        "created_at": now,
        "updated_at": now,
    }
    duplicate = await fetchone(
        """
        SELECT * FROM setting_change_events
        WHERE project_id=%s
          AND entity_type=%s
          AND entity_name=%s
          AND change_type=%s
          AND field_path=%s
          AND (chapter_num <=> %s)
          AND evidence=%s
          AND new_value=%s
          AND status='pending_review'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (
            values["project_id"],
            values["entity_type"],
            values["entity_name"],
            values["change_type"],
            values["field_path"],
            values["chapter_num"],
            values["evidence"],
            values["new_value"],
        ),
    )
    if duplicate:
        return convert_row(duplicate)

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
async def accept_setting_change_event(pid: str, cid: str, data: dict | None = Body(default=None)):
    event = await fetchone(
        "SELECT * FROM setting_change_events WHERE project_id=%s AND id=%s",
        (pid, cid),
    )
    if not event:
        return {"ok": False, "error": "change event not found"}

    hard_conflicts = await _collect_hard_setting_conflicts(pid, event)
    force_hard_conflict = bool((data or {}).get("forceHardConflict"))
    if hard_conflicts and not force_hard_conflict:
        field_path = _normalize_hard_field_path(_normalize_field_path(event.get("field_path") or ""))
        raise HTTPException(
            status_code=409,
            detail={
                "code": "hard_conflict_setting_review_required",
                "conflictWarnings": hard_conflicts,
                "fieldPath": field_path,
                "fieldTier": _field_tier(field_path),
                "whyBlocked": "；".join(hard_conflicts),
            },
        )

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


HARD_SETTING_FIELDS = {
    "summary",
    "category",
    "status",
    "profile.identity",
    "profile.affiliation",
    "profile.family",
    "profile.sect",
    "profile.faction",
    "profile.nation",
    "profile.rankTitle",
    "profile.realm",
    "profile.realmLevel",
    "profile.powerLevel",
    "profile.abilityLevel",
    "profile.techniques",
    "profile.weapons",
    "profile.fixedRelationship",
    "profile.leader",
    "profile.territory",
    "profile.resources",
    "profile.controller",
    "profile.realms",
    "profile.breakthroughRules",
    "profile.grade",
    "profile.owner",
    "profile.coreLimitations",
    "profile.worldRules",
    "profile.powerRules",
    "profile.itemCoreLimitations",
    "profile.bloodline",
    "profile.lineage",
    "profile.camp",
    "profile.alignment",
    "profile.country",
}

DYNAMIC_STATE_FIELDS = {
    "profile.location",
    "profile.currentGoal",
    "profile.temporaryGoal",
    "profile.physicalStatus",
    "profile.itemStatus",
    "profile.mentalState",
    "profile.behaviorState",
    "profile.currentState",
    "profile.situation",
    "profile.currentSituation",
    "profile.clueProgress",
    "profile.progress",
    "profile.lastKnownLocation",
    "profile.observedCosts",
    "profile.costHistory",
    "profile.ruleExamples",
    "profile.observedFacts",
    "profile.revealedClues",
    "profile.currentActions",
    "profile.internalMechanisms",
    "profile.chapterEvidence",
    "profile.hiddenStance",
    "profile.currentAction",
    "profile.currentHolder",
    "profile.possessionStatus",
    "profile.custodyState",
    "profile.contactStatus",
    "profile.accessState",
}

OBSERVED_CAPABILITY_FIELDS = {
    "profile.ability",
    "profile.capability",
    "profile.observedAbility",
}

RULE_INSTANCE_REHOME_FIELD = "profile.observedCosts"
SUMMARY_CHAPTER_FACT_REHOME_FIELD = "profile.observedFacts"
HARD_FIELD_BEHAVIOR_REHOME_FIELD = "profile.hiddenStance"
OWNER_POSSESSION_REHOME_FIELD = "profile.possessionStatus"

HARD_FIELD_ALIASES = {
    "identity": "profile.identity",
    "affiliation": "profile.affiliation",
    "family": "profile.family",
    "sect": "profile.sect",
    "faction": "profile.faction",
    "nation": "profile.nation",
    "rankTitle": "profile.rankTitle",
    "realm": "profile.realm",
    "realmLevel": "profile.realmLevel",
    "powerLevel": "profile.powerLevel",
    "abilityLevel": "profile.abilityLevel",
    "fixedRelationship": "profile.fixedRelationship",
    "owner": "profile.owner",
    "itemOwner": "profile.owner",
    "holder": "profile.currentHolder",
    "currentHolder": "profile.currentHolder",
    "possessor": "profile.currentHolder",
    "currentPossessor": "profile.currentHolder",
    "custody": "profile.custodyState",
    "possessionStatus": "profile.possessionStatus",
    "contactStatus": "profile.contactStatus",
    "accessState": "profile.accessState",
    "ability": "profile.ability",
    "capability": "profile.capability",
    "observedAbility": "profile.observedAbility",
    "observedFacts": "profile.observedFacts",
    "revealedClues": "profile.revealedClues",
    "currentActions": "profile.currentActions",
    "internalMechanisms": "profile.internalMechanisms",
    "chapterEvidence": "profile.chapterEvidence",
    "hiddenStance": "profile.hiddenStance",
    "currentAction": "profile.currentAction",
    "physicalStatus": "profile.physicalStatus",
    "itemStatus": "profile.itemStatus",
    "mentalState": "profile.mentalState",
    "behaviorState": "profile.behaviorState",
    "currentGoal": "profile.currentGoal",
    "currentState": "profile.currentState",
    "location": "profile.location",
}

HARD_FIELD_LABELS = {
    "summary": "概要",
    "category": "分类",
    "status": "状态",
    "profile.identity": "身份",
    "profile.affiliation": "势力归属",
    "profile.family": "家族",
    "profile.sect": "宗门/门派",
    "profile.faction": "阵营",
    "profile.nation": "国家",
    "profile.rankTitle": "身份/职位",
    "profile.realm": "境界",
    "profile.realmLevel": "境界层级",
    "profile.powerLevel": "能力等级",
    "profile.abilityLevel": "能力等级",
    "profile.location": "当前位置",
    "profile.physicalStatus": "身体状态",
    "profile.currentGoal": "当前目标",
    "profile.mentalState": "心理状态",
    "profile.behaviorState": "行动状态",
    "profile.currentState": "当前状态",
    "profile.fixedRelationship": "固定关系",
    "profile.owner": "归属/持有人",
    "profile.currentHolder": "当前持有者",
    "profile.possessionStatus": "持有状态",
    "profile.custodyState": "保管状态",
    "profile.contactStatus": "接触状态",
    "profile.accessState": "访问/取用状态",
    "profile.ability": "能力",
    "profile.capability": "能力表现",
    "profile.observedAbility": "已观察能力表现",
    "profile.itemStatus": "物品状态",
    "profile.observedCosts": "已发生代价",
    "profile.costHistory": "代价历史",
    "profile.ruleExamples": "规则实例",
    "profile.observedFacts": "已观察事实",
    "profile.revealedClues": "已揭示线索",
    "profile.currentActions": "当前行动",
    "profile.internalMechanisms": "内部机制",
    "profile.chapterEvidence": "章节证据",
    "profile.hiddenStance": "隐藏立场",
    "profile.currentAction": "当前行为",
}

RESERVATION_RE = re.compile(
    r"(官方结论|表面(?:信息|说法|记录)?|传闻|传言|据说|可能|疑似|疑点|暗示|线索|未确认|不明|下落不明|"
    r"名籍.*封存|封存.*名籍|封存于.*旧档|档案异常|名字异常|星账.*名字|名字出现在|表面死亡|假死)"
)
OBSERVED_CAPABILITY_RE = re.compile(r"(新增|已展现|展现|已观察|观察到|表现|使用效果|触发|现象|浮现|显示|感应|震动|发热|发光|主动|能(?:够)?|可以|会|使用后|发动后|触发后|表现为)")
CORE_RULE_RE = re.compile(r"(不能|只能|必须|不得|不可|限制|核心规则|规则|代价|随机|不可逆|只记录|不能伪造|不能销毁)")
CORE_RULE_NEGATION_RE = re.compile(r"(不再|无需|不必|无须|没有代价|免代价|可以伪造|可以销毁|可以复制|可被复制|不再需要|取消|删除|推翻|改写|改为|变成|不受限制|记录死人|记录死者|死人代价|死者代价|代价可逆|可以逆转|可逆转)")
RULE_INSTANCE_RE = re.compile(r"(第[一二三四五六七八九十百千万\d]+次|首次|初次|再(?:次|度)|本章|第\s*\d+\s*章|已发生|发生过|代价[:：]|欠债[一二三四五六七八九十\d]*次|左眼|右眼|视力|记忆|寿元|灵脉|失去|损失|扣除)")
DIRECT_NEGATION_RE = re.compile(r"(并非|不是|不再是|没有|从未|未曾|不曾|不存在|不属于|并未|否认|推翻)")
PLACEHOLDER_SUMMARY_RE = re.compile(r"^(?:第\s*(?:\?|[一二三四五六七八九十百千万\d]+)\s*章自动识别的设定|自动识别的设定|待补全|待完善|未知|暂无|无|占位|占位设定|暂无明确设定|无有效摘要)$")
SUMMARY_CHAPTER_FACT_RE = re.compile(
    r"(第\s*[一二三四五六七八九十百千万\d]+\s*章|本章|章节|新增|揭示|发现|线索|证据|暗号|铜牌|追捕|帮助|调查|处决|内部|机制|当前|正在|已发生|行动|态势|动向|外围|暗中|"
    r"派人|追踪|尾随|盯上|接触|拉拢|收购|交换|交易|威胁|封锁|设伏|搜查|试图|索要|逼迫|交换条件)"
)
SUMMARY_CURRENT_ACTION_RE = re.compile(
    r"(已派人|派人|尾随|盯上|拉拢|收购|交换|交易|威胁|封锁|设伏|搜查|试图|索要|逼迫|交换条件|暗中.{0,8}拉拢|"
    r"已.{0,8}追踪|正在.{0,8}(追踪|尾随|盯上|拉拢|交换|交易|威胁|封锁|设伏|搜查|索要|逼迫)|"
    r"试图.{0,8}(交换|交易|索要|逼迫|收购|拉拢))"
)
UNCERTAIN_SUMMARY_FRAGMENT_RE = re.compile(r"(可能|疑似|或许|也许|未确认|不明|下落不明|传闻|据说|暗示|线索|疑点)")
DESCRIPTIVE_PLACEHOLDER_NAME_RE = re.compile(r"(老人|老头|老者|男子|女人|女子|少年|少女|孩童|灰袍|黑袍|白衣|黑斗笠|斗笠|面具|蒙面|木门后|门后|卖.+的|守门|账房|追踪者|陌生人|来客|掌柜|伙计)$")
UNCERTAIN_IDENTITY_RE = re.compile(r"(可能|疑似|像是|看起来|身份不明|身份未明|未确认|不明|关键情报源|旧识|父亲旧识|线索人物|知情人|神秘|陌生)")
FORMAL_IDENTITY_RE = re.compile(r"(?:^|[，,。；;\s])(?:[一-龥]{2,4})(?:[，,。；;\s]|$)|(?:名叫|叫作|叫做|本名|真名|姓名|自称|承认自己叫).{0,8}[一-龥]{2,4}|(?:前|曾任|现任|原为|任).{0,16}(账房|星吏|官|吏|司主|掌柜|管事|弟子|长老|供奉|执事)")
SUMMARY_IDENTITY_REWRITE_RE = re.compile(r"(其实|并非|不是|不再是|变成|改为|本质上|根本上|真实身份|实际是).{0,24}(非官方|不是官方|商盟|分部|公开官署|官署|秘密组织|公开机构|官方机构|民间组织|商业联盟|商会|伪装|伪造)")
OFFICIAL_ORG_RE = re.compile(r"(官方机构|朝廷|官署|巡查|缉拿|执法|官府|公门)")
SECRET_ORG_RE = re.compile(r"(秘密组织|隐秘组织|暗中|地下|外围|暗号|秘密结社)")
PUBLIC_ORG_RE = re.compile(r"(公开官署|公开机构|官方机构|正式登记|朝廷设立)")
HIDDEN_BEHAVIOR_RE = re.compile(r"(暗中|秘密|私下|表面|伪装|但|却|当前|正在|帮助|追捕|调查|保护|掩护|背离|隐藏|短期|暂时|见习|卧底|内应)")
OWNER_UNSTABLE_OR_DYNAMIC_RE = re.compile(r"(未知|不明|疑似|可能|未确认|已接触|接触|未取出|取出|暂时|临时|当前|拿到|拿走|带走|携带|保管|藏在|收起|夺走|抢走|被夺|归还|交还|触碰|持有)")
OWNER_POSSESSION_ACTION_RE = re.compile(r"(已接触|接触|触碰|未取出|取出|暂时|临时|当前|拿到|拿走|带走|携带|保管|藏在|收起|夺走|抢走|被夺|归还|交还|持有|怀里|身上|掌中|手中)")
OWNER_POSSESSION_NEGATION_RE = re.compile(r"(无|没有|未|并未|并无|缺少|不具备|不能证明|未证明|没有证明).{0,18}(接触|取出|拿到|拿走|带走|携带|持有|保管|夺走|抢走|被夺|归还|交还|触碰)")
OWNER_TRANSFER_RE = re.compile(
    r"(正式|法理|长期|永久|真正|确认|明确|所有权|归属|拥有权|转让|移交|交割|继承|赠与|交给|交还|归还).{0,18}"
    r"(归属|所有|拥有|主人|持有人|所有权|拥有权|移交|转让|继承|赠与|交割|交给|交还|归还)|"
    r"(?:归属|所有权|拥有权).{0,18}(转移|移交|确认|改归|属于|归于)|"
    r"(?:正式|法理|长期|永久|真正).{0,18}(属于|拥有|持有|归属)|"
    r"(?:当众|明确).{0,12}(转让|移交|赠与|交割)"
)
OWNER_TRANSFER_NEGATION_RE = re.compile(r"(无|没有|未|并未|并无|缺少|不具备|不能证明|未证明|没有证明).{0,18}(转让|移交|交割|继承|赠与|归还|交还|所有权|归属|拥有权|法理|永久|长期)")
INVALID_ENTITY_NAME_RE = re.compile(r"(^第\s*(?:\?|[一二三四五六七八九十百千万\d]+)\s*章|死去\s*[一二三四五六七八九十百千万\d]+年|现死去|^\d+$)")
HARD_PROFILE_STABLE_FIELDS = {
    "profile.identity",
    "profile.affiliation",
    "profile.family",
    "profile.sect",
    "profile.faction",
    "profile.nation",
    "profile.rankTitle",
    "profile.realm",
    "profile.realmLevel",
    "profile.powerLevel",
    "profile.abilityLevel",
    "profile.fixedRelationship",
    "profile.leader",
    "profile.territory",
    "profile.controller",
    "profile.owner",
    "profile.camp",
    "profile.alignment",
    "profile.country",
}


async def _collect_hard_setting_conflicts(pid: str, event: dict):
    if event.get("change_type") == "relationship":
        return await _collect_relationship_conflicts(pid, event)

    entity = await _find_existing_entity_for_event(pid, event)
    if not entity:
        return []

    if event.get("change_type") == "new_entity":
        return _collect_duplicate_entity_hard_conflicts(event, entity)

    field_path = _normalize_hard_field_path(_normalize_field_path(event.get("field_path") or ""))
    existing_value = _clean_text(_read_entity_field(entity, field_path))
    incoming_value = _clean_text(_resolve_event_incoming_value(event, field_path))
    if not existing_value or not incoming_value or existing_value == incoming_value:
        return []
    if _is_dynamic_state_field(field_path):
        return []
    if _is_observed_capability_field(field_path):
        if _is_ability_core_conflict(existing_value, incoming_value, event.get("evidence")):
            return [_format_ability_core_warning(field_path, existing_value, incoming_value)]
        return []
    if not _is_hard_setting_field(field_path):
        return []
    if field_path == "summary" and _is_rule_instance_summary_supplement(existing_value, incoming_value, event.get("evidence")):
        return []
    if field_path == "summary" and _is_placeholder_summary(existing_value):
        return []
    if field_path == "summary" and _is_descriptive_placeholder_identity_reveal(entity.get("name") or event.get("entity_name"), existing_value, incoming_value, event.get("evidence")):
        return []
    if field_path == "summary" and _is_summary_chapter_fact_supplement(existing_value, incoming_value, event.get("evidence")):
        return []
    if field_path == "profile.owner" and _is_owner_possession_rehome_change(field_path, existing_value, incoming_value, event.get("evidence")):
        return []
    if field_path == "profile.owner" and _has_stable_owner_transfer_evidence(existing_value, incoming_value, event.get("evidence")):
        return []
    if _is_hard_field_behavior_supplement(field_path, existing_value, incoming_value, event.get("evidence")):
        return []
    if _allows_layered_hard_field_reveal(existing_value, incoming_value, event.get("evidence")):
        return []
    return [_format_hard_field_warning(field_path, existing_value, incoming_value)]


async def _find_existing_entity_for_event(pid: str, event: dict):
    entity_id = event.get("entity_id")
    if entity_id:
        existing = await fetchone(
            "SELECT * FROM setting_entities WHERE project_id=%s AND id=%s",
            (pid, entity_id),
        )
        if existing:
            return existing
    entity_name = event.get("entity_name") or ""
    entity_type = event.get("entity_type") or ""
    if not entity_name:
        return None
    if entity_type:
        return await fetchone(
            "SELECT * FROM setting_entities WHERE project_id=%s AND entity_type=%s AND name=%s LIMIT 1",
            (pid, entity_type, entity_name),
        )
    return await fetchone(
        "SELECT * FROM setting_entities WHERE project_id=%s AND name=%s LIMIT 1",
        (pid, entity_name),
    )


def _collect_duplicate_entity_hard_conflicts(event: dict, entity: dict):
    if _is_placeholder_entity(entity):
        return []

    payload = _decode_json(event.get("new_value"))
    if not isinstance(payload, dict):
        return []

    warnings = []
    for field_path in ("summary", "category", "status"):
        if field_path not in payload or not _is_hard_setting_field(field_path):
            continue
        existing_value = _clean_text(_read_entity_field(entity, field_path))
        incoming_value = _clean_text(payload.get(field_path))
        if existing_value and incoming_value and existing_value != incoming_value:
            if field_path == "summary" and _is_rule_instance_summary_supplement(existing_value, incoming_value, event.get("evidence")):
                continue
            if field_path == "summary" and _is_placeholder_summary(existing_value):
                continue
            if field_path == "summary" and _is_descriptive_placeholder_identity_reveal(entity.get("name") or event.get("entity_name"), existing_value, incoming_value, event.get("evidence")):
                continue
            if field_path == "summary" and _is_summary_chapter_fact_supplement(existing_value, incoming_value, event.get("evidence")):
                continue
            if field_path == "profile.owner" and _is_owner_possession_rehome_change(field_path, existing_value, incoming_value, event.get("evidence")):
                continue
            if field_path == "profile.owner" and _has_stable_owner_transfer_evidence(existing_value, incoming_value, event.get("evidence")):
                continue
            warnings.append(_format_hard_field_warning(field_path, existing_value, incoming_value))

    profile = {}
    if isinstance(payload.get("profile"), dict):
        profile.update(payload["profile"])
    if isinstance(payload.get("profilePatch"), dict):
        profile.update(payload["profilePatch"])
    for key, value in profile.items():
        field_path = _normalize_hard_field_path(key)
        existing_value = _clean_text(_read_entity_field(entity, field_path))
        incoming_value = _clean_text(value)
        if existing_value and incoming_value and existing_value != incoming_value:
            if _is_dynamic_state_field(field_path):
                continue
            if _is_observed_capability_field(field_path):
                if _is_ability_core_conflict(existing_value, incoming_value, event.get("evidence")):
                    warnings.append(_format_ability_core_warning(field_path, existing_value, incoming_value))
                continue
            if not _is_hard_setting_field(field_path):
                continue
            if field_path == "profile.owner" and _is_owner_possession_rehome_change(field_path, existing_value, incoming_value, event.get("evidence")):
                continue
            if field_path == "profile.owner" and _has_stable_owner_transfer_evidence(existing_value, incoming_value, event.get("evidence")):
                continue
            if _is_hard_field_behavior_supplement(field_path, existing_value, incoming_value, event.get("evidence")):
                continue
            warnings.append(_format_hard_field_warning(field_path, existing_value, incoming_value))
    return warnings


def _is_placeholder_entity(entity: dict):
    if not entity:
        return False
    summary = _clean_text(entity.get("summary"))
    if summary and _is_placeholder_summary(summary):
        return True
    if _entity_has_chapter_dependency(entity):
        return False
    category = _clean_text(entity.get("category"))
    tags = _decode_json(entity.get("tags")) or []
    profile = _decode_json(entity.get("profile")) or {}
    if not isinstance(tags, list):
        tags = []
    profile_empty = isinstance(profile, dict) and not profile
    has_meaningful_profile = isinstance(profile, dict) and any(_clean_text(value) for value in profile.values())
    return (
        summary == "第 ? 章自动识别的设定"
        or "AI识别" in [str(item).strip() for item in tags]
        or (profile_empty and not summary and not category)
        or (not has_meaningful_profile and not summary and not category)
    )


def _entity_has_chapter_dependency(entity: dict):
    return bool(
        entity.get("first_chapter")
        or entity.get("last_chapter")
        or entity.get("firstChapter")
        or entity.get("lastChapter")
    )


async def _collect_relationship_conflicts(pid: str, event: dict):
    payload = _decode_json(event.get("new_value")) or {}
    if not isinstance(payload, dict):
        return []
    source = await _find_existing_entity_for_event(pid, event)
    target_name = payload.get("targetEntityName") or payload.get("targetName") or payload.get("target") or ""
    target_type = payload.get("targetEntityType") or payload.get("targetType") or "character"
    if not source or not target_name:
        return []
    target = await fetchone(
        "SELECT * FROM setting_entities WHERE project_id=%s AND entity_type=%s AND name=%s LIMIT 1",
        (pid, target_type, target_name),
    )
    if not target:
        return []
    relation_type = payload.get("relationType") or event.get("field_path") or "关系"
    existing = await fetchone(
        """
        SELECT * FROM setting_relations
        WHERE project_id=%s AND source_entity_id=%s AND target_entity_id=%s AND relation_type=%s
        """,
        (pid, source["id"], target["id"], relation_type),
    )
    if not existing:
        return []
    warnings = [f"关系「{source.get('name')} -> {relation_type} -> {target.get('name')}」已存在，确认后会覆盖该关系记录。"]
    if existing.get("stance") and payload.get("stance") and existing.get("stance") != payload.get("stance"):
        warnings.append(f"关系立场将从「{existing.get('stance')}」变为「{payload.get('stance')}」。")
    if existing.get("summary") and payload.get("summary") and existing.get("summary") != payload.get("summary"):
        warnings.append("关系说明与现有记录不同，建议逐条确认。")
    return warnings


def _normalize_hard_field_path(field_path: str):
    value = str(field_path or "").strip()
    return HARD_FIELD_ALIASES.get(value, value)


def _is_hard_setting_field(field_path: str):
    normalized = _normalize_hard_field_path(field_path)
    candidates = [normalized]
    if normalized and not normalized.startswith("profile.") and normalized not in {"summary", "category", "status"}:
        candidates.append(f"profile.{normalized}")
    return any(candidate in HARD_SETTING_FIELDS for candidate in candidates)


def _is_dynamic_state_field(field_path: str):
    normalized = _normalize_hard_field_path(field_path)
    candidates = [normalized]
    if normalized and not normalized.startswith("profile.") and normalized not in {"summary", "category", "status"}:
        candidates.append(f"profile.{normalized}")
    return any(candidate in DYNAMIC_STATE_FIELDS for candidate in candidates)


def _is_observed_capability_field(field_path: str):
    normalized = _normalize_hard_field_path(field_path)
    candidates = [normalized]
    if normalized and not normalized.startswith("profile.") and normalized not in {"summary", "category", "status"}:
        candidates.append(f"profile.{normalized}")
    return any(candidate in OBSERVED_CAPABILITY_FIELDS for candidate in candidates)


def _field_tier(field_path: str):
    if _is_dynamic_state_field(field_path):
        return "dynamicState"
    if _is_observed_capability_field(field_path):
        return "observedCapability"
    if _is_hard_setting_field(field_path):
        return "hardSetting"
    return "general"


def _read_entity_field(entity: dict, field_path: str):
    if not entity or not field_path:
        return ""
    normalized = _normalize_hard_field_path(field_path)
    if normalized.startswith("profile."):
        profile = _decode_json(entity.get("profile")) or {}
        key = normalized.split(".", 1)[1]
        return profile.get(key, "")
    column = ENTITY_COLUMN_PATHS.get(normalized, normalized)
    return entity.get(column, "")


def _resolve_event_incoming_value(event: dict, field_path: str):
    if event.get("change_type") != "new_entity":
        return event.get("new_value")
    payload = _decode_json(event.get("new_value"))
    if not isinstance(payload, dict):
        return event.get("new_value")
    normalized = _normalize_hard_field_path(field_path)
    if normalized.startswith("profile."):
        key = normalized.split(".", 1)[1]
        return (payload.get("profile") or {}).get(key) or (payload.get("profilePatch") or {}).get(key)
    return payload.get(normalized) or payload.get("summary") or event.get("new_value")


def _allows_layered_hard_field_reveal(existing_value, incoming_value, evidence):
    old_text = _clean_text(existing_value)
    new_text = _clean_text(incoming_value)
    evidence_text = _clean_text(evidence)
    return bool(old_text and new_text and old_text in new_text and RESERVATION_RE.search(f"{new_text} {evidence_text}"))


def _is_ability_core_conflict(existing_value, incoming_value, evidence):
    old_text = _clean_text(existing_value)
    new_text = _clean_text(incoming_value)
    evidence_text = _clean_text(evidence)
    combined = f"{new_text} {evidence_text}"
    if not old_text or not new_text or old_text == new_text:
        return False
    if RESERVATION_RE.search(combined):
        return False
    if old_text in new_text and OBSERVED_CAPABILITY_RE.search(combined):
        return False
    if CORE_RULE_RE.search(old_text) and CORE_RULE_NEGATION_RE.search(new_text):
        return True
    if re.search(r"只记录活人", old_text) and re.search(r"(记录死人|记录死者)", new_text):
        return True
    if re.search(r"不能伪造|不能销毁", old_text) and re.search(r"(可以伪造|可以销毁)", new_text):
        return True
    if re.search(r"必须.*代价|付出.*代价|代价.*不可逆", old_text) and re.search(r"无需.*代价|没有代价|免代价|不再需要.*代价", new_text):
        return True
    return bool(DIRECT_NEGATION_RE.search(new_text) and not OBSERVED_CAPABILITY_RE.search(combined))


def _is_rule_instance_summary_supplement(existing_value, incoming_value, evidence):
    old_text = _clean_text(existing_value)
    new_text = _clean_text(incoming_value)
    evidence_text = _clean_text(evidence)
    combined = f"{new_text} {evidence_text}"
    if not old_text or not new_text or old_text == new_text:
        return False
    if not CORE_RULE_RE.search(old_text):
        return False
    if not RULE_INSTANCE_RE.search(combined):
        return False
    if _is_core_rule_rewrite(old_text, new_text):
        return False
    return new_text.find(old_text) >= 0 or _strip_parenthetical_segments(new_text) == old_text


def _is_placeholder_summary(value):
    text = _clean_text(value)
    if not text:
        return True
    return bool(PLACEHOLDER_SUMMARY_RE.search(text))


def _is_summary_chapter_fact_supplement(existing_value, incoming_value, evidence):
    old_text = _clean_text(existing_value)
    new_text = _clean_text(incoming_value)
    combined = f"{new_text} {_clean_text(evidence)}"
    if not old_text or not new_text or old_text == new_text:
        return False
    if _is_placeholder_summary(old_text):
        return False
    if _is_hard_summary_rewrite(old_text, new_text):
        return False
    if not SUMMARY_CHAPTER_FACT_RE.search(combined):
        return False
    return old_text in new_text or _old_summary_anchor_preserved(old_text, new_text)


def _is_descriptive_placeholder_identity_reveal(entity_name, existing_value, incoming_value, evidence):
    name = _clean_text(entity_name)
    old_text = _clean_text(existing_value)
    new_text = _clean_text(incoming_value)
    combined = f"{new_text} {_clean_text(evidence)}"
    if not name or not old_text or not new_text or old_text == new_text:
        return False
    if not DESCRIPTIVE_PLACEHOLDER_NAME_RE.search(name):
        return False
    if not UNCERTAIN_IDENTITY_RE.search(old_text):
        return False
    if not FORMAL_IDENTITY_RE.search(combined):
        return False
    if _is_hard_summary_rewrite(old_text, new_text):
        return False
    return True


def _is_hard_summary_rewrite(existing_value, incoming_value):
    old_text = _clean_text(existing_value)
    new_text = _clean_text(incoming_value)
    if not old_text or not new_text:
        return False
    if SUMMARY_IDENTITY_REWRITE_RE.search(new_text):
        return True
    if re.search(r"(其实|并非|不是|不再是).{0,12}(商业联盟|商会|组织|机构|势力)", new_text):
        return True
    if re.search(r"(星债会).{0,12}(伪装|分部)|(?:伪装|分部).{0,12}(星债会)", new_text):
        return True
    if OFFICIAL_ORG_RE.search(old_text) and re.search(r"(不是|并非|不再是).{0,12}(官方|朝廷|官署)|商盟.{0,8}分部|伪造.{0,8}(机构|官署)", new_text):
        return True
    if SECRET_ORG_RE.search(old_text) and re.search(r"(不再是|不是|并非).{0,8}秘密|公开官署|公开机构|正式登记", new_text):
        return True
    if PUBLIC_ORG_RE.search(old_text) and re.search(r"(秘密组织|隐秘组织|地下组织)", new_text) and DIRECT_NEGATION_RE.search(new_text):
        return True
    return False


def _is_hard_field_behavior_supplement(field_path, existing_value, incoming_value, evidence):
    normalized = _normalize_hard_field_path(field_path)
    old_text = _clean_text(existing_value)
    new_text = _clean_text(incoming_value)
    combined = f"{new_text} {_clean_text(evidence)}"
    if normalized not in HARD_PROFILE_STABLE_FIELDS:
        return False
    if not old_text or not new_text or old_text == new_text:
        return False
    if not HIDDEN_BEHAVIOR_RE.search(combined):
        return False
    return old_text in new_text or _strip_parenthetical_segments(new_text) == old_text


def _is_owner_possession_rehome_change(field_path, existing_value, incoming_value, evidence):
    normalized = _normalize_hard_field_path(field_path)
    if normalized != "profile.owner":
        return False
    old_text = _clean_text(existing_value)
    new_text = _clean_text(incoming_value)
    evidence_text = _clean_text(evidence)
    if not old_text or not new_text or old_text == new_text:
        return False
    if _has_stable_owner_transfer_evidence(old_text, new_text, evidence_text):
        return False
    old_is_unstable = bool(OWNER_UNSTABLE_OR_DYNAMIC_RE.search(old_text))
    new_is_dynamic = bool(OWNER_POSSESSION_ACTION_RE.search(new_text))
    evidence_is_dynamic = bool(OWNER_POSSESSION_ACTION_RE.search(evidence_text)) and not OWNER_POSSESSION_NEGATION_RE.search(evidence_text)
    return old_is_unstable or new_is_dynamic or evidence_is_dynamic


def _has_stable_owner_transfer_evidence(existing_value, incoming_value, evidence):
    combined = f"{_clean_text(existing_value)} {_clean_text(incoming_value)} {_clean_text(evidence)}"
    if OWNER_TRANSFER_NEGATION_RE.search(combined):
        return False
    return bool(OWNER_TRANSFER_RE.search(combined))


def _stable_owner_value_from_mixed(value):
    text = _clean_text(value)
    if not text:
        return ""
    stripped = re.sub(
        r"已接触|接触|未取出|取出|暂时|临时|当前|拿到|拿走|带走|携带|保管|藏在|收起|触碰|持有",
        "",
        _strip_parenthetical_segments(text),
    )
    stripped = re.sub(r"[，,；;、/]+$", "", stripped).strip()
    if not stripped or re.search(r"^(未知|不明|疑似|可能|未确认)$", stripped):
        return "未知"
    if re.search(r"^(未知|不明)", stripped):
        return "未知"
    return stripped


def _build_owner_possession_rehome_value(existing_value, incoming_value, evidence):
    old_text = _clean_text(existing_value)
    new_text = _clean_text(incoming_value)
    evidence_text = _clean_text(evidence)
    parts = []
    if new_text:
        parts.append(f"当前持有/接触线索：{new_text}")
    if old_text and OWNER_UNSTABLE_OR_DYNAMIC_RE.search(old_text):
        parts.append(f"旧 owner 动态状态：{old_text}")
    if evidence_text:
        parts.append(f"证据：{evidence_text}")
    return "；".join(parts)


def _choose_hard_field_behavior_rehome_field(incoming_value, evidence):
    combined = f"{_clean_text(incoming_value)} {_clean_text(evidence)}"
    if re.search(r"(暗中|秘密|私下|表面|伪装|隐藏|卧底|内应)", combined):
        return HARD_FIELD_BEHAVIOR_REHOME_FIELD
    return "profile.currentAction"


def _choose_summary_chapter_fact_rehome_field(incoming_value, evidence):
    combined = f"{_clean_text(incoming_value)} {_clean_text(evidence)}"
    if SUMMARY_CURRENT_ACTION_RE.search(combined):
        return "profile.currentActions"
    return SUMMARY_CHAPTER_FACT_REHOME_FIELD


def _old_summary_anchor_preserved(old_text, new_text):
    incoming = _clean_text(new_text)
    for part in re.split(r"[。；;，,]", _clean_text(old_text)):
        anchor = _clean_text(part)
        if len(anchor) >= 8 and not UNCERTAIN_SUMMARY_FRAGMENT_RE.search(anchor) and anchor in incoming:
            return True
    return False


def _extract_formal_name_from_identity_text(value):
    text = _clean_text(value)
    if not text:
        return ""
    first = re.split(r"[，,。；;\s]", text, maxsplit=1)[0].strip()
    if re.fullmatch(r"[一-龥]{2,4}", first) and not DESCRIPTIVE_PLACEHOLDER_NAME_RE.search(first):
        return first
    match = re.search(r"(?:名叫|叫作|叫做|本名|真名|姓名|自称|承认自己叫)\s*([一-龥]{2,4})", text)
    if match and not DESCRIPTIVE_PLACEHOLDER_NAME_RE.search(match.group(1)):
        return match.group(1)
    return ""


def _merge_aliases(existing_aliases, *values):
    aliases = _decode_json(existing_aliases) if isinstance(existing_aliases, str) else existing_aliases
    if not isinstance(aliases, list):
        aliases = []
    normalized = []
    seen = set()
    for value in [*aliases, *values]:
        text = _clean_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _is_core_rule_rewrite(existing_value, incoming_value):
    old_text = _clean_text(existing_value)
    new_text = _clean_text(incoming_value)
    if not old_text or not new_text:
        return False
    if CORE_RULE_RE.search(old_text) and CORE_RULE_NEGATION_RE.search(new_text):
        return True
    if re.search(r"只记录活人", old_text) and re.search(r"(记录死人|记录死者|死人代价|死者代价)", new_text):
        return True
    if re.search(r"(不可复制|不能复制|不可被复制)", old_text) and re.search(r"(可以复制|可被复制|能够复制)", new_text):
        return True
    if re.search(r"(必须.*代价|付出.*代价|每次使用.*代价)", old_text) and re.search(r"(无需.*代价|无须.*代价|不必.*代价|没有代价|免代价|不再需要.*代价)", new_text):
        return True
    if re.search(r"不可逆", old_text) and re.search(r"(代价可逆|可以逆转|可逆转|可以恢复|可恢复)", new_text):
        return True
    return False


def _strip_parenthetical_segments(text):
    return re.sub(r"\s+", " ", re.sub(r"[（(][^（）()]*[）)]", "", _clean_text(text))).strip()


def _append_profile_dynamic_entry(profile: dict, field_name: str, entry: dict, event: dict):
    existing = profile.get(field_name)
    if not isinstance(existing, list):
        existing = []
    duplicate = any(
        isinstance(item, dict)
        and item.get("value") == entry.get("value")
        and item.get("evidence") == entry.get("evidence")
        and item.get("chapterNum") == entry.get("chapterNum")
        for item in existing
    )
    if not duplicate:
        existing.append(entry)
    profile[field_name] = existing
    meta = profile.get("_dynamicStateMeta")
    if not isinstance(meta, dict):
        meta = {}
    meta[field_name] = _change_event_meta(event)
    profile["_dynamicStateMeta"] = meta


def _rehome_summary_chapter_fact_update(profile: dict, updates: dict, event: dict, existing_summary, incoming_summary):
    entry = {
        "value": _stringify_value(incoming_summary),
        "evidence": event.get("evidence") or "",
        "chapterNum": event.get("chapter_num") or event.get("chapterNum"),
        "confidence": event.get("confidence"),
        "sourceField": "summary",
        "preservedSummary": _stringify_value(existing_summary),
    }
    target_field = _choose_summary_chapter_fact_rehome_field(incoming_summary, event.get("evidence"))
    field_name = target_field.split(".", 1)[1]
    _append_profile_dynamic_entry(profile, field_name, entry, event)
    updates.pop("summary", None)


def _apply_descriptive_identity_reveal_update(entity: dict, profile: dict, updates: dict, event: dict, existing_summary, incoming_summary):
    old_name = _clean_text(entity.get("name") or event.get("entity_name"))
    formal_name = _extract_formal_name_from_identity_text(incoming_summary)
    if formal_name and formal_name != old_name:
        updates["name"] = formal_name
        updates["aliases"] = _json(_merge_aliases(entity.get("aliases"), old_name))

    updates["summary"] = _stringify_value(incoming_summary)
    reveal = {
        "value": _stringify_value(incoming_summary),
        "evidence": event.get("evidence") or "",
        "chapterNum": event.get("chapter_num") or event.get("chapterNum"),
        "confidence": event.get("confidence"),
        "sourceField": "summary",
        "previousName": old_name,
        "previousSummary": _stringify_value(existing_summary),
    }
    existing = profile.get("identityReveal")
    if isinstance(existing, list):
        if not any(isinstance(item, dict) and item.get("value") == reveal["value"] for item in existing):
            existing.append(reveal)
        profile["identityReveal"] = existing
    elif existing:
        profile["identityReveal"] = f"{existing}；旧描述「{old_name}」揭示为：{_stringify_value(incoming_summary)}"
    else:
        profile["identityReveal"] = f"旧描述「{old_name}」揭示为：{_stringify_value(incoming_summary)}"

    observed = {
        "value": f"身份揭示：旧描述「{old_name}」对应「{_stringify_value(incoming_summary)}」",
        "evidence": event.get("evidence") or "",
        "chapterNum": event.get("chapter_num") or event.get("chapterNum"),
        "confidence": event.get("confidence"),
        "sourceField": "summary",
        "preservedSummary": _stringify_value(existing_summary),
    }
    _append_profile_dynamic_entry(profile, "observedFacts", observed, event)


def _rehome_hard_field_behavior_update(profile: dict, updates: dict, event: dict, field_path, existing_value, incoming_value):
    target_field = _choose_hard_field_behavior_rehome_field(incoming_value, event.get("evidence"))
    field_name = target_field.split(".", 1)[1]
    entry = {
        "value": _stringify_value(incoming_value),
        "evidence": event.get("evidence") or "",
        "chapterNum": event.get("chapter_num") or event.get("chapterNum"),
        "confidence": event.get("confidence"),
        "sourceField": _normalize_hard_field_path(field_path),
        "preservedValue": _stringify_value(existing_value),
    }
    _append_profile_dynamic_entry(profile, field_name, entry, event)
    updates.pop("profile", None)


def _rehome_owner_possession_update(profile: dict, updates: dict, event: dict, field_path, existing_value, incoming_value):
    old_text = _stringify_value(existing_value)
    new_text = _stringify_value(incoming_value)
    stable_owner = _stable_owner_value_from_mixed(old_text)
    if OWNER_UNSTABLE_OR_DYNAMIC_RE.search(_clean_text(old_text)) and stable_owner:
        profile["owner"] = stable_owner

    entry = {
        "value": _build_owner_possession_rehome_value(old_text, new_text, event.get("evidence")),
        "evidence": event.get("evidence") or "",
        "chapterNum": event.get("chapter_num") or event.get("chapterNum"),
        "confidence": event.get("confidence"),
        "sourceField": _normalize_hard_field_path(field_path),
        "preservedOwnerState": old_text,
        "incomingOwnerValue": new_text,
        "stableOwnerValue": stable_owner,
    }
    field_name = OWNER_POSSESSION_REHOME_FIELD.split(".", 1)[1]
    _append_profile_dynamic_entry(profile, field_name, entry, event)

    if new_text and not OWNER_POSSESSION_ACTION_RE.search(_clean_text(new_text)) and len(_clean_text(new_text)) <= 24:
        profile["currentHolder"] = new_text
        meta = profile.get("_dynamicStateMeta")
        if not isinstance(meta, dict):
            meta = {}
        meta["currentHolder"] = _change_event_meta(event)
        profile["_dynamicStateMeta"] = meta
    updates.pop("profile", None)


def _apply_profile_payload_update(profile: dict, payload: dict, event: dict):
    for key, value in _clean_empty(payload).items():
        field_path = _normalize_hard_field_path(key)
        profile_key = field_path.split(".", 1)[1] if field_path.startswith("profile.") else key
        incoming_value = _stringify_value(value)
        existing_value = profile.get(profile_key)
        if _is_owner_possession_rehome_change(field_path, existing_value, incoming_value, event.get("evidence")):
            _rehome_owner_possession_update(profile, {}, event, field_path, existing_value, incoming_value)
            continue
        if _is_hard_field_behavior_supplement(field_path, existing_value, incoming_value, event.get("evidence")):
            _rehome_hard_field_behavior_update(profile, {}, event, field_path, existing_value, incoming_value)
            continue
        profile[profile_key] = value
        if _is_dynamic_state_field(field_path):
            meta = profile.get("_dynamicStateMeta")
            if not isinstance(meta, dict):
                meta = {}
            meta[profile_key] = _change_event_meta(event)
            profile["_dynamicStateMeta"] = meta
        elif _is_observed_capability_field(field_path):
            meta = profile.get("_observedCapabilityMeta")
            if not isinstance(meta, dict):
                meta = {}
            meta[profile_key] = _change_event_meta(event)
            profile["_observedCapabilityMeta"] = meta


def _apply_placeholder_summary_completion(entity: dict, updates: dict, incoming_summary):
    updates["summary"] = _stringify_value(incoming_summary)
    tags = _decode_json(entity.get("tags")) or []
    if isinstance(tags, list):
        cleaned_tags = [item for item in tags if str(item).strip() not in {"AI识别", "占位"}]
        updates["tags"] = _json(cleaned_tags)


def _is_invalid_entity_name(name):
    text = _clean_text(name)
    if not text:
        return True
    if len(text) <= 12 and re.search(r"[\-—–－~～/／→]", text):
        return True
    if INVALID_ENTITY_NAME_RE.search(text):
        return True
    if len(text) <= 8 and re.search(r"(死去|已死|三年|两年|一年|多年|当天|当夜|之前|之后)", text):
        return True
    if len(text) > 24 and re.search(r"(关系|帮助|追捕|调查|处决|发现|揭示)", text):
        return True
    return False


def _is_invalid_placeholder_entity_event(data: dict):
    if (data.get("changeType") or data.get("change_type")) != "new_entity":
        return False
    entity_name = data.get("entityName") or data.get("entity_name") or ""
    if not _is_invalid_entity_name(entity_name):
        return False
    payload = data.get("newValue") if "newValue" in data else data.get("new_value")
    if isinstance(payload, str):
        decoded = _decode_json(payload)
    else:
        decoded = payload
    if not isinstance(decoded, dict):
        return _is_placeholder_summary(payload)
    summary = decoded.get("summary") or ""
    profile = decoded.get("profile") or decoded.get("profilePatch") or {}
    tags = decoded.get("tags") or []
    profile_empty = isinstance(profile, dict) and not profile
    tags_text = " ".join(str(item) for item in tags) if isinstance(tags, list) else str(tags)
    return _is_placeholder_summary(summary) or profile_empty or "AI识别" in tags_text


def _rehome_rule_instance_summary_update(profile: dict, updates: dict, event: dict, existing_summary, incoming_summary):
    observed = profile.get("observedCosts")
    if not isinstance(observed, list):
        observed = []

    entry = {
        "value": _stringify_value(incoming_summary),
        "evidence": event.get("evidence") or "",
        "chapterNum": event.get("chapter_num") or event.get("chapterNum"),
        "confidence": event.get("confidence"),
        "sourceField": "summary",
        "preservedSummary": _stringify_value(existing_summary),
    }
    duplicate = any(
        isinstance(item, dict)
        and item.get("value") == entry["value"]
        and item.get("evidence") == entry["evidence"]
        and item.get("chapterNum") == entry["chapterNum"]
        for item in observed
    )
    if not duplicate:
        observed.append(entry)

    profile["observedCosts"] = observed
    meta = profile.get("_dynamicStateMeta")
    if not isinstance(meta, dict):
        meta = {}
    meta["observedCosts"] = _change_event_meta(event)
    profile["_dynamicStateMeta"] = meta
    updates.pop("summary", None)


def _format_hard_field_warning(field_path: str, existing_value: str, incoming_value: str):
    normalized = _normalize_hard_field_path(field_path)
    label = HARD_FIELD_LABELS.get(normalized, HARD_FIELD_LABELS.get(field_path, field_path))
    return f"硬设定字段「{label}」将从「{existing_value}」变为「{incoming_value}」。"


def _format_ability_core_warning(field_path: str, existing_value: str, incoming_value: str):
    normalized = _normalize_hard_field_path(field_path)
    label = HARD_FIELD_LABELS.get(normalized, HARD_FIELD_LABELS.get(field_path, field_path))
    return f"能力核心规则「{label}」将从「{existing_value}」变为「{incoming_value}」。"


def _clean_text(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return re.sub(r"\s+", " ", str(value)).strip()


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
        elif table == "setting_change_events" and js_key in ("oldValue", "newValue"):
            value = _stringify_value(value)
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
                existing_summary = entity.get("summary")
                incoming_summary = payload.get("summary")
                if existing_summary and _is_placeholder_summary(existing_summary):
                    _apply_placeholder_summary_completion(entity, updates, incoming_summary)
                elif existing_summary and _is_rule_instance_summary_supplement(existing_summary, incoming_summary, event.get("evidence")):
                    _rehome_rule_instance_summary_update(profile, updates, event, entity.get("summary"), payload.get("summary"))
                elif existing_summary and _is_descriptive_placeholder_identity_reveal(entity.get("name") or entity_name, existing_summary, incoming_summary, event.get("evidence")):
                    _apply_descriptive_identity_reveal_update(entity, profile, updates, event, existing_summary, incoming_summary)
                elif existing_summary and _is_summary_chapter_fact_supplement(existing_summary, incoming_summary, event.get("evidence")):
                    _rehome_summary_chapter_fact_update(profile, updates, event, existing_summary, incoming_summary)
                else:
                    updates["summary"] = incoming_summary
            if payload.get("category"):
                updates["category"] = payload.get("category")
            if payload.get("importance"):
                updates["importance"] = payload.get("importance")
            if isinstance(payload.get("profile"), dict):
                _apply_profile_payload_update(profile, payload["profile"], event)
            if isinstance(payload.get("profilePatch"), dict):
                _apply_profile_payload_update(profile, payload["profilePatch"], event)
            if isinstance(payload.get("tags"), list):
                tags = payload["tags"]
                if _is_placeholder_summary(entity.get("summary")):
                    tags = [item for item in tags if str(item).strip() not in {"AI识别", "占位"}]
                updates["tags"] = _json(tags)
        elif event.get("new_value"):
            updates["summary"] = event.get("new_value")
        if not entity.get("first_chapter") and event.get("chapter_num"):
            updates["first_chapter"] = event.get("chapter_num")
    elif field_path.startswith("profile."):
        key = field_path.split(".", 1)[1]
        if key:
            normalized = _normalize_hard_field_path(field_path)
            existing_value = profile.get(key)
            incoming_value = _stringify_value(event.get("new_value"))
            if _is_owner_possession_rehome_change(normalized, existing_value, incoming_value, event.get("evidence")):
                _rehome_owner_possession_update(profile, updates, event, normalized, existing_value, incoming_value)
            elif _is_hard_field_behavior_supplement(normalized, existing_value, incoming_value, event.get("evidence")):
                _rehome_hard_field_behavior_update(profile, updates, event, normalized, existing_value, incoming_value)
            else:
                profile[key] = incoming_value
            if _is_dynamic_state_field(field_path):
                meta = profile.get("_dynamicStateMeta")
                if not isinstance(meta, dict):
                    meta = {}
                meta[key] = _change_event_meta(event)
                profile["_dynamicStateMeta"] = meta
            elif _is_observed_capability_field(field_path):
                meta = profile.get("_observedCapabilityMeta")
                if not isinstance(meta, dict):
                    meta = {}
                meta[key] = _change_event_meta(event)
                profile["_observedCapabilityMeta"] = meta
    elif field_path == "summary" and _is_placeholder_summary(entity.get("summary")):
        _apply_placeholder_summary_completion(entity, updates, event.get("new_value"))
    elif field_path == "summary" and _is_rule_instance_summary_supplement(entity.get("summary"), event.get("new_value"), event.get("evidence")):
        _rehome_rule_instance_summary_update(profile, updates, event, entity.get("summary"), event.get("new_value"))
    elif field_path == "summary" and _is_descriptive_placeholder_identity_reveal(entity.get("name") or entity_name, entity.get("summary"), event.get("new_value"), event.get("evidence")):
        _apply_descriptive_identity_reveal_update(entity, profile, updates, event, entity.get("summary"), event.get("new_value"))
    elif field_path == "summary" and _is_summary_chapter_fact_supplement(entity.get("summary"), event.get("new_value"), event.get("evidence")):
        _rehome_summary_chapter_fact_update(profile, updates, event, entity.get("summary"), event.get("new_value"))
    elif field_path == "status":
        status_value = _stringify_value(event.get("new_value")).strip()
        if status_value in SYSTEM_ENTITY_STATUSES:
            updates["status"] = status_value
        elif status_value:
            profile[STORY_STATE_PROFILE_PATH] = status_value
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

    if event.get("change_type") == "relationship":
        pending_entity = await _apply_pending_new_entity_event(pid, entity_type, name)
        if pending_entity:
            return pending_entity

    now = int(time.time() * 1000)
    eid = str(uuid.uuid4())
    placeholder_reason = f"relationship_event_missing_entity:{event.get('id') or ''}"
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


async def _apply_pending_new_entity_event(pid: str, entity_type: str, name: str):
    pending_event = await _find_pending_new_entity_event(pid, entity_type, name)
    if not pending_event:
        return None
    conflicts = await _collect_hard_setting_conflicts(pid, pending_event)
    if conflicts:
        field_path = _normalize_hard_field_path(_normalize_field_path(pending_event.get("field_path") or ""))
        raise HTTPException(
            status_code=409,
            detail={
                "code": "hard_conflict_setting_review_required",
                "conflictWarnings": conflicts,
                "pendingEntityEventId": pending_event.get("id"),
                "fieldPath": field_path,
                "fieldTier": _field_tier(field_path),
                "whyBlocked": "；".join(conflicts),
            },
        )
    entity = await _apply_entity_event(pid, pending_event)
    await execute(
        "UPDATE setting_change_events SET status=%s, entity_id=%s, updated_at=%s WHERE project_id=%s AND id=%s",
        ("accepted", entity.get("id"), int(time.time() * 1000), pid, pending_event.get("id")),
    )
    return entity


async def _find_pending_new_entity_event(pid: str, entity_type: str, name: str):
    if not name:
        return None
    return await fetchone(
        """
        SELECT * FROM setting_change_events
        WHERE project_id=%s
          AND change_type='new_entity'
          AND status='pending_review'
          AND entity_type=%s
          AND entity_name=%s
        ORDER BY created_at ASC
        LIMIT 1
        """,
        (pid, entity_type, name),
    )


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


def _change_event_meta(event: dict):
    chapter_num = event.get("chapter_num") or event.get("chapterNum")
    return {
        "chapterNum": chapter_num,
        "lastUpdatedChapter": chapter_num,
        "evidence": event.get("evidence") or "",
        "confidence": event.get("confidence"),
    }


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

SYSTEM_ENTITY_STATUSES = {"active", "inactive", "hidden", "archived"}
STORY_STATE_PROFILE_PATH = "currentState"


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
    "持有者": "profile.currentHolder",
    "品阶": "profile.grade",
    "能力": "profile.ability",
}


def _normalize_field_path(field_path: str):
    return FIELD_ALIASES.get(field_path, field_path)
