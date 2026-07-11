"""创作经验卡：样本来源、经验卡审核、候选标准和正式写作标准。"""
from pathlib import Path
from fastapi import APIRouter, Body, HTTPException, Query
from backend.database import fetchone, fetchall, execute
from .helpers import convert_row, convert_rows
import hashlib
import json
import re
import time
import uuid


router = APIRouter(tags=["experience-cards"])

CARD_STATUSES = {"candidate", "reviewed", "rejected", "merged", "archived"}
CANDIDATE_STATUSES = {"draft", "reviewing", "approved", "rejected", "promoted"}
FORBIDDEN_PROMPT_KEYS = {"rawExcerpt", "sourceText", "sourceCardIds", "source_card_ids"}
SOURCE_SPECIFIC_TOKENS = {
    "凡人修仙传",
    "四世同堂",
    "老舍：四世同堂",
    "一句顶一万句",
    "大奉打更人",
    "修真聊天群",
    "斗破苍穹",
    "全球高武",
    "韩立",
    "黄枫谷",
    "祁家",
}
SAFETY_FLAGS = [
    "no_raw_excerpt",
    "no_source_text",
    "no_long_source_quote",
    "no_source_names",
    "no_direct_imitation",
]
PROMPT_READY_LOW_DOSE = "prompt-ready-low-dose"
BACKEND_REFERENCE_ONLY = "backend-reference-only-until-reviewed"
PROMPT_MICRO_DEMO_FORBIDDEN_FIELDS = {
    "sourceWork",
    "sourceInfluence",
    "sourceCardId",
    "characterEmotionVariants",
    "emotionDialogueOptions",
}
PROMPT_MICRO_DEMO_FILES = [
    ("v2.1", "prompt_injectable_scene", "sampleMicroDemoCards.v2_1.json"),
    ("v2.2", "prompt_injectable_dialogue", "sampleMicroDemoCards.v2_2.json"),
]
PROMPT_MICRO_DEMO_DATA_DIR = Path(__file__).resolve().parents[2] / "frontend" / "src" / "data"

BUILTIN_WRITING_STANDARD_BLUEPRINTS = [
    {
        "id": "system-dialogue-realism",
        "name": "对话真实感增强",
        "category": "对话 / 关系",
        "applicableScenes": "嘴硬关心、旧识旧账、讨价还价、市井闲话、沉默岔开、失败埋怨、亲近废话、恐惧胡扯。",
        "principles": ["对话先服务人物当下的身份、顾虑和遮掩，再顺手露出信息。"],
        "originalMicroDemo": "他把药包推过去，说：“别误会，掌柜多收了我一份。”她没拆穿，只把药包往袖里一塞。",
        "antiAiReminder": "不要让角色像客服一样逐条解释设定，也不要每问必答。",
        "notApplicableScenes": "纯动作追逐、无人物互动的地图交代。",
        "callStrength": "low",
        "match": ("嘴硬", "旧识", "旧账", "讨价", "市井", "闲话", "沉默", "岔开", "埋怨", "废话", "恐惧", "胡扯", "对话"),
    },
    {
        "id": "system-character-humanity",
        "name": "人物血肉与情绪反应",
        "category": "人物 / 情绪",
        "applicableScenes": "人物受伤、隐瞒、误会、亏欠、害怕、嘴硬、关系松动或失衡。",
        "principles": ["人物先用动作、迟疑、误判和小选择反应压力，不急着替自己命名情绪。"],
        "originalMicroDemo": "她听见名字时先去扶倒了的凳子，扶了两次都没扶正，才问：“他什么时候走的？”",
        "antiAiReminder": "不要把情绪写成标签，也不要让配角只负责递线索。",
        "notApplicableScenes": "纯设定表、纯战斗数值结算。",
        "callStrength": "low",
        "match": ("人物", "情绪", "血肉", "反应", "害怕", "误会", "隐瞒", "亏欠", "伤口", "嘴硬", "关系", "配角"),
    },
    {
        "id": "system-scene-dwell-life-texture",
        "name": "场景停留与生活质感",
        "category": "场景 / 生活质感",
        "applicableScenes": "街巷、店铺、客栈、码头、衙门、饭铺等需要停留感和生活纹理的场景。",
        "principles": ["场景至少有秩序、摩擦和微变三拍，让人感觉角色真的站在这个地方。"],
        "originalMicroDemo": "面摊的汤锅还滚着，摊主先把火拨小，才抬眼看他们：“两位要吵，别挡着我收摊。”",
        "antiAiReminder": "不要用一串形容词堆氛围，场景细节必须有用力方向。",
        "notApplicableScenes": "高速打斗、信息密集的短过场。",
        "callStrength": "low",
        "match": ("场景", "停留", "生活", "市井", "街", "巷", "客栈", "码头", "饭铺", "茶馆", "秩序", "摩擦", "微变"),
    },
    {
        "id": "system-anti-ai-basic",
        "name": "反 AI 腔基础标准",
        "category": "语言 / 反模板",
        "applicableScenes": "任何容易变成剧情摘要、规则清单、功能对白或模板收束的章节。",
        "principles": ["先写具体动作和后果，再让读者自己感到意思；少用总结句替场景盖章。"],
        "originalMicroDemo": "他想说不疼，袖口却先湿了一圈。小九看见了，没问，只把灯往旁边挪了挪。",
        "antiAiReminder": "避免“这意味着”“他意识到”“两人的关系发生变化”等代替场景的总结。",
        "notApplicableScenes": "明确需要条目化说明的后台报告，不适用于正文。",
        "callStrength": "low",
        "match": ("反 AI", "AI", "模板", "清单", "摘要", "功能", "骨架", "打卡"),
    },
    {
        "id": "system-popular-story-progression",
        "name": "通俗故事推进",
        "category": "章节推进 / 通俗可读",
        "applicableScenes": "阶段答案、行动后果、线索转向、选择代价和下一章承接。",
        "principles": ["每章给读者一个小答案，同时让答案打开新的后果或选择压力。"],
        "originalMicroDemo": "钥匙是真的，门却不是这把钥匙开的。陆沉舟把钥匙收回去，先问：“谁让你告诉我这个？”",
        "antiAiReminder": "不要只换地点和追兵制造推进，必须有答案、代价或关系变化。",
        "notApplicableScenes": "纯氛围散文段、无章节承接压力的独白。",
        "callStrength": "low",
        "match": ("推进", "答案", "后果", "代价", "选择", "线索", "阶段", "通俗", "故事", "开门", "悬念"),
    },
    {
        "id": "system-natural-setting-exposition",
        "name": "设定自然呈现",
        "category": "设定 / 信息释放",
        "applicableScenes": "规则、组织、功法、制度、物件、地点和势力关系需要进入正文时。",
        "principles": ["设定先通过尝试、阻碍、旁人反应和后果呈现，再补一句小结。"],
        "originalMicroDemo": "令牌递过去后，门房没看字，先看铜边缺口。看完，他把茶碗往里挪了半寸。",
        "antiAiReminder": "不要让人物站在原地背世界观，也不要一次讲完整套规则。",
        "notApplicableScenes": "读者已经熟悉且无需变化的重复设定。",
        "callStrength": "low",
        "match": ("设定", "规则", "组织", "制度", "功法", "物件", "钥匙", "令牌", "信息", "呈现", "解释", "后果"),
    },
]


@router.get("/experience-cards/sources")
async def list_sample_sources(status: str = ""):
    args = []
    where = []
    if status:
        where.append("status=%s")
        args.append(status)
    sql = "SELECT * FROM sample_source"
    if where:
        sql += f" WHERE {' AND '.join(where)}"
    sql += " ORDER BY updated_at DESC, title ASC"
    return convert_rows(await fetchall(sql, args))


@router.post("/experience-cards/seed-local-report")
async def seed_local_writing_sample_report():
    report = _load_local_report()
    cards = report.get("cards") or []
    now = _now()
    imported_sources = 0
    imported_chunks = 0
    imported_cards = 0

    for index, card in enumerate(cards, start=1):
        source_title = _clean_text(card.get("sourceTitle")) or f"本地样本 {index}"
        source_id = _stable_uuid(f"sample-source:{source_title}")
        card_id = _stable_uuid(f"experience-card:{card.get('id') or source_title}")
        chunk_id = _stable_uuid(f"sample-chunk:{card.get('id') or source_title}")
        source_hash = _hash_json({
            "sourceTitle": source_title,
            "metrics": card.get("metrics") or {},
            "generatedAt": report.get("generatedAt"),
        })

        if await _upsert_by_id("sample_source", {
            "id": source_id,
            "source_type": "local_report",
            "title": source_title,
            "author": "",
            "file_name": f"{source_title}.txt",
            "file_hash": source_hash,
            "source_note": "从 localWritingSampleReport.json 迁移；只保留抽象创作经验，不保存原文。",
            "status": "imported",
            "imported_at": now,
            "created_at": now,
            "updated_at": now,
        }):
            imported_sources += 1

        if await _upsert_by_id("sample_chunk", {
            "id": chunk_id,
            "source_id": source_id,
            "chunk_order": 1,
            "chapter_label": "local-report",
            "window_role": "report_card",
            "abstract_notes_json": _json(card.get("analysisNotes") or []),
            "metrics_json": _json(card.get("metrics") or {}),
            "raw_hash": _stable_hash(card.get("id") or source_title),
            "status": "imported",
            "created_at": now,
            "updated_at": now,
        }):
            imported_chunks += 1

        if await _upsert_experience_card_from_report(_card_values_from_report(card, source_id, chunk_id, card_id, now)):
            imported_cards += 1

    return {
        "ok": True,
        "sourceCount": imported_sources,
        "chunkCount": imported_chunks,
        "cardCount": imported_cards,
        "totalCards": len(cards),
    }


@router.post("/experience-cards/seed-prompt-injectable-cards")
async def seed_prompt_injectable_cards():
    cards = _load_prompt_micro_demo_cards()
    now = _now()
    imported_sources = 0
    imported_chunks = 0
    imported_cards = 0
    source_ids: dict[str, str] = {}

    for card in cards:
        source_key = f"prompt-micro-demo:{card['version']}:{card['card_type']}"
        source_id = source_ids.get(source_key) or _stable_uuid(f"sample-source:{source_key}")
        source_ids[source_key] = source_id
        chunk_id = _stable_uuid(f"sample-chunk:prompt-micro-demo:{card['version']}:{card['card_id']}")
        card_id = _stable_uuid(f"experience-card:prompt-micro-demo:{card['version']}:{card['card_id']}")
        source_title = f"原创微示范卡 {card['version']}"

        if await _upsert_by_id("sample_source", {
            "id": source_id,
            "source_type": "prompt_micro_demo_cards",
            "title": source_title,
            "author": "",
            "file_name": card["source_file"],
            "file_hash": _stable_hash(card["source_file"]),
            "source_note": "从 v2.1/v2.2 样本深读产物导入；仅保存脱敏原创微示范和后台诊断状态。",
            "status": "imported",
            "imported_at": now,
            "created_at": now,
            "updated_at": now,
        }):
            imported_sources += 1

        if await _upsert_by_id("sample_chunk", {
            "id": chunk_id,
            "source_id": source_id,
            "chunk_order": 1,
            "chapter_label": card["prompt_readiness"],
            "window_role": card["card_type"],
            "abstract_notes_json": _json({
                "promptReadiness": card["prompt_readiness"],
                "sourceFieldsStripped": True,
                "sampleLeakageDetected": False,
            }),
            "metrics_json": _json({"microDemoChars": card["micro_demo_chars"]}),
            "raw_hash": _stable_hash(f"{card['version']}:{card['card_id']}"),
            "status": "imported",
            "created_at": now,
            "updated_at": now,
        }):
            imported_chunks += 1

        status = "reviewed" if card["prompt_readiness"] == PROMPT_READY_LOW_DOSE else "candidate"
        if await _upsert_by_id("experience_card", {
            "id": card_id,
            "source_id": source_id,
            "source_card_ref": card["card_id"],
            "source_title": source_title,
            "title": card["card_title"],
            "status": status,
            "card_type": card["card_type"],
            "chapter_skeleton": card["prompt_injection_safe_version"],
            "story_block_span": "每章最多低量参考一张原创微示范；无明显匹配时不注入正文 prompt。",
            "protagonist_progression": "",
            "supporting_character_method": "",
            "emotional_dwell": "",
            "scene_dwell": card["original_micro_demo"],
            "dialogue_naturalness": card["dialogue_type"],
            "setting_exposure": "",
            "answers_and_suspense": "",
            "anti_ai_notes": card["anti_skeleton_effect"],
            "genre_tags": _json([card["version"], card["prompt_readiness"], card["card_type"]]),
            "avoid_patterns": _json(["不要复用人物、物件、句子，也不要按清单打卡。"]),
            "chunk_ids": _json([chunk_id]),
            "metrics_json": _json({
                "promptReadiness": card["prompt_readiness"],
                "microDemoChars": card["micro_demo_chars"],
                "sourceFieldsStripped": True,
                "sampleLeakageDetected": False,
            }),
            "safety_flags": _json([*SAFETY_FLAGS, "source_fields_stripped", card["prompt_readiness"]]),
            "review_note": f"{card['prompt_readiness']}；来源字段已剥离，只作低量手感参考或后台诊断。",
            "reviewed_at": now if status == "reviewed" else None,
            "created_at": now,
            "updated_at": now,
        }):
            imported_cards += 1

    return {
        "ok": True,
        "sourceCount": imported_sources,
        "chunkCount": imported_chunks,
        "cardCount": imported_cards,
        "totalCards": len(cards),
        "promptReadyCards": len([card for card in cards if card["prompt_readiness"] == PROMPT_READY_LOW_DOSE]),
        "backendReferenceOnlyCards": len([card for card in cards if card["prompt_readiness"] == BACKEND_REFERENCE_ONLY]),
    }


@router.get("/experience-cards/product/cards")
async def list_product_experience_cards(q: str = "", limit: int = Query(300, ge=1, le=500)):
    await _ensure_builtin_experience_cards()
    rows = await list_experience_cards(status="", q=q, limit=limit)
    return [_product_card(row) for row in rows]


@router.post("/experience-cards/cards")
async def create_experience_card(data: dict):
    now = _now()
    card_id = str(uuid.uuid4())
    values = {
        "id": card_id,
        "source_id": None,
        "source_card_ref": _clean_text(data.get("sourceCardRef")) or card_id,
        "source_title": "我的经验",
        "title": _clean_text(data.get("title")) or "未命名经验卡",
        "status": "reviewed",
        "card_type": "user_experience",
        "chapter_skeleton": _clean_text(data.get("writingMethod") or data.get("chapterSkeleton")),
        "story_block_span": _clean_text(data.get("applicableScenes")),
        "protagonist_progression": _clean_text(data.get("protagonistProgression")),
        "supporting_character_method": _clean_text(data.get("supportingCharacterMethod")),
        "emotional_dwell": _clean_text(data.get("emotionalDwell")),
        "scene_dwell": _clean_text(data.get("originalMicroDemo") or data.get("sceneDwell")),
        "dialogue_naturalness": _clean_text(data.get("dialogueNaturalness")),
        "setting_exposure": _clean_text(data.get("settingExposure")),
        "answers_and_suspense": _clean_text(data.get("answersAndSuspense")),
        "anti_ai_notes": _clean_text(data.get("antiAiReminder") or data.get("antiAiNotes")),
        "genre_tags": _json(_safe_list(data.get("genreTags"))),
        "avoid_patterns": _json(_safe_list(data.get("avoidPatterns"))),
        "chunk_ids": _json([]),
        "metrics_json": _json({"sourceKind": "user", "productStatus": "active"}),
        "safety_flags": _json(SAFETY_FLAGS),
        "review_note": "我的经验卡，可直接用于候选标准。",
        "reviewed_at": now,
        "created_at": now,
        "updated_at": now,
    }
    await _insert("experience_card", values)
    return _product_card(await _get_card(card_id))


@router.put("/experience-cards/cards/{card_id}")
async def update_experience_card(card_id: str, data: dict):
    card = await _get_card(card_id)
    if _card_source_kind(card) == "system":
        raise HTTPException(status_code=409, detail="系统内置经验卡不可编辑，可复制为我的经验卡后再编辑。")
    updates = {
        "title": _clean_text(data.get("title")) or card.get("title") or "",
        "story_block_span": _clean_text(data.get("applicableScenes")) or card.get("story_block_span") or "",
        "chapter_skeleton": _clean_text(data.get("writingMethod") or data.get("chapterSkeleton")) or card.get("chapter_skeleton") or "",
        "scene_dwell": _clean_text(data.get("originalMicroDemo") or data.get("sceneDwell")) or card.get("scene_dwell") or "",
        "anti_ai_notes": _clean_text(data.get("antiAiReminder") or data.get("antiAiNotes")) or card.get("anti_ai_notes") or "",
        "updated_at": _now(),
    }
    await _update_by_columns("experience_card", updates, "id=%s", (card_id,))
    return _product_card(await _get_card(card_id))


@router.post("/experience-cards/cards/{card_id}/toggle-active")
async def toggle_experience_card_active(card_id: str, data: dict | None = Body(default=None)):
    card = await _get_card(card_id)
    active = (data or {}).get("active")
    current_active = _product_active(card)
    next_active = (not current_active) if active is None else bool(active)
    metrics = _decode_json(card.get("metrics_json")) or {}
    metrics["productStatus"] = "active" if next_active else "inactive"
    metrics["sourceKind"] = _card_source_kind(card)
    await _update_by_columns("experience_card", {
        "metrics_json": _json(metrics),
        "updated_at": _now(),
    }, "id=%s", (card_id,))
    return _product_card(await _get_card(card_id))


@router.post("/experience-cards/cards/{card_id}/copy")
async def copy_experience_card(card_id: str, data: dict | None = Body(default=None)):
    card = await _get_card(card_id)
    now = _now()
    new_id = str(uuid.uuid4())
    values = dict(card)
    values.update({
        "id": new_id,
        "source_id": None,
        "source_card_ref": new_id,
        "source_title": "我的经验",
        "title": _clean_text((data or {}).get("title")) or f"{card.get('title') or '经验卡'}（我的）",
        "status": "reviewed",
        "card_type": "user_experience",
        "metrics_json": _json({"sourceKind": "user", "productStatus": "active", "copiedFrom": card_id}),
        "review_note": "从系统内置或我的经验卡复制。",
        "reviewed_at": now,
        "created_at": now,
        "updated_at": now,
    })
    await _insert("experience_card", _filter_table_values(values, "experience_card"))
    return _product_card(await _get_card(new_id))


@router.delete("/experience-cards/cards/{card_id}")
async def delete_experience_card(card_id: str):
    card = await _get_card(card_id)
    if _card_source_kind(card) == "system":
        raise HTTPException(status_code=409, detail="系统内置经验卡禁止删除，只能取消激活。")
    references = await _experience_card_reference_counts(card_id)
    if references["candidateCount"] or references["standardCount"]:
        raise HTTPException(
            status_code=409,
            detail=f"该经验卡已被 {references['candidateCount']} 个候选标准、{references['standardCount']} 个正式写作标准引用，请先移除引用后再删除。",
        )
    await execute("DELETE FROM experience_card WHERE id=%s", (card_id,))
    return {"ok": True, "deletedId": card_id}


@router.get("/experience-cards/cards")
async def list_experience_cards(status: str = "", q: str = "", limit: int = Query(200, ge=1, le=500)):
    args = []
    where = []
    if status:
        _ensure_status(status, CARD_STATUSES, "经验卡状态")
        where.append("status=%s")
        args.append(status)
    if q:
        like = f"%{q}%"
        where.append("(title LIKE %s OR source_title LIKE %s OR chapter_skeleton LIKE %s)")
        args.extend([like, like, like])
    sql = "SELECT * FROM experience_card"
    if where:
        sql += f" WHERE {' AND '.join(where)}"
    sql += " ORDER BY updated_at DESC, title ASC LIMIT %s"
    args.append(limit)
    return convert_rows(await fetchall(sql, args))


@router.post("/experience-cards/cards/{card_id}/review")
async def review_experience_card(card_id: str, data: dict | None = Body(default=None)):
    card = await _get_card(card_id)
    _ensure_transition(card.get("status"), {"candidate", "reviewed"}, "审核通过经验卡")
    now = _now()
    await _update_by_columns("experience_card", {
        "status": "reviewed",
        "review_note": (data or {}).get("reviewNote") or card.get("review_note") or "",
        "reviewed_at": now,
        "updated_at": now,
    }, "id=%s", (card_id,))
    return convert_row(await _get_card(card_id))


@router.post("/experience-cards/cards/{card_id}/reject")
async def reject_experience_card(card_id: str, data: dict | None = Body(default=None)):
    card = await _get_card(card_id)
    _ensure_transition(card.get("status"), {"candidate", "reviewed", "rejected"}, "拒绝经验卡")
    now = _now()
    await _update_by_columns("experience_card", {
        "status": "rejected",
        "review_note": (data or {}).get("reviewNote") or card.get("review_note") or "",
        "reviewed_at": now,
        "updated_at": now,
    }, "id=%s", (card_id,))
    return convert_row(await _get_card(card_id))


@router.post("/experience-cards/cards/{card_id}/archive")
async def archive_experience_card(card_id: str, data: dict | None = Body(default=None)):
    card = await _get_card(card_id)
    _ensure_transition(card.get("status"), {"candidate", "reviewed", "rejected", "archived"}, "归档经验卡")
    now = _now()
    await _update_by_columns("experience_card", {
        "status": "archived",
        "review_note": (data or {}).get("reviewNote") or card.get("review_note") or "",
        "updated_at": now,
    }, "id=%s", (card_id,))
    return convert_row(await _get_card(card_id))


@router.get("/experience-cards/candidates")
async def list_writing_standard_candidates(status: str = ""):
    args = []
    where = []
    if status:
        _ensure_status(status, CANDIDATE_STATUSES, "候选标准状态")
        where.append("status=%s")
        args.append(status)
    sql = "SELECT * FROM writing_standard_candidate"
    if where:
        sql += f" WHERE {' AND '.join(where)}"
    sql += " ORDER BY updated_at DESC"
    return convert_rows(await fetchall(sql, args))


@router.post("/experience-cards/candidates")
async def create_writing_standard_candidate(data: dict):
    card_ids = _safe_list(data.get("cardIds") or data.get("sourceCardIds"))
    if not card_ids:
        raise HTTPException(status_code=400, detail="至少选择一张已审核经验卡")
    cards = await _fetch_cards_by_ids(card_ids)
    found_ids = {row.get("id") for row in cards}
    missing = [card_id for card_id in card_ids if card_id not in found_ids]
    if missing:
        raise HTTPException(status_code=404, detail={"message": "经验卡不存在", "missingCardIds": missing})
    not_reviewed = [row.get("id") for row in cards if row.get("status") != "reviewed"]
    if not_reviewed:
        raise HTTPException(status_code=409, detail={"message": "只有 reviewed 经验卡可合并为候选标准", "cardIds": not_reviewed})

    status = data.get("status") or "draft"
    if status not in {"draft", "reviewing"}:
        raise HTTPException(status_code=400, detail="新候选标准状态只能是 draft 或 reviewing")

    now = _now()
    candidate_id = str(uuid.uuid4())
    merged_guidance = _build_candidate_guidance(cards)
    values = {
        "id": candidate_id,
        "name": _clean_text(data.get("name")) or "未命名写作标准候选",
        "category": _clean_text(data.get("category")) or "样本库 / 人工审核",
        "status": status,
        "source_card_ids": _json(card_ids),
        "merged_guidance": _json(merged_guidance),
        "audit_focus": _json(_audit_focus_from_guidance(merged_guidance)),
        "safety_policy": _json(_default_safety_policy(cards)),
        "review_note": _clean_text(data.get("reviewNote")),
        "promoted_standard_id": None,
        "created_at": now,
        "updated_at": now,
    }
    await _insert("writing_standard_candidate", values)
    return convert_row(await _get_candidate(candidate_id))


@router.put("/experience-cards/candidates/{candidate_id}")
async def update_writing_standard_candidate(candidate_id: str, data: dict):
    candidate = await _get_candidate(candidate_id)
    updates = {
        "name": _clean_text(data.get("name")) or candidate.get("name") or "",
        "category": _clean_text(data.get("applicableScenes") or data.get("category")) or candidate.get("category") or "",
        "review_note": _clean_text(data.get("description") or data.get("reviewNote")) or candidate.get("review_note") or "",
        "updated_at": _now(),
    }
    await _update_by_columns("writing_standard_candidate", updates, "id=%s", (candidate_id,))
    return _product_candidate(await _get_candidate(candidate_id))


@router.post("/experience-cards/candidates/{candidate_id}/cards")
async def add_cards_to_writing_standard_candidate(candidate_id: str, data: dict):
    candidate = await _get_candidate(candidate_id)
    existing_ids = _safe_list(_decode_json(candidate.get("source_card_ids")))
    incoming_ids = _safe_list(data.get("cardIds") or data.get("sourceCardIds"))
    if not incoming_ids:
        raise HTTPException(status_code=400, detail="请选择要加入的经验卡。")
    card_ids = _dedupe([*existing_ids, *incoming_ids])
    cards = await _fetch_cards_by_ids(card_ids)
    await _update_by_columns("writing_standard_candidate", {
        "source_card_ids": _json(card_ids),
        "merged_guidance": _json(_build_candidate_guidance(cards)),
        "audit_focus": _json(_audit_focus_from_guidance(_build_candidate_guidance(cards))),
        "updated_at": _now(),
    }, "id=%s", (candidate_id,))
    return _product_candidate(await _get_candidate(candidate_id))


@router.delete("/experience-cards/candidates/{candidate_id}/cards/{card_id}")
async def remove_card_from_writing_standard_candidate(candidate_id: str, card_id: str):
    candidate = await _get_candidate(candidate_id)
    current_ids = _safe_list(_decode_json(candidate.get("source_card_ids")))
    next_ids = [item for item in current_ids if item != card_id]
    if not next_ids:
        raise HTTPException(status_code=409, detail="候选标准移除经验卡时不能产生空候选标准。")
    cards = await _fetch_cards_by_ids(next_ids)
    await _update_by_columns("writing_standard_candidate", {
        "source_card_ids": _json(next_ids),
        "merged_guidance": _json(_build_candidate_guidance(cards)),
        "audit_focus": _json(_audit_focus_from_guidance(_build_candidate_guidance(cards))),
        "updated_at": _now(),
    }, "id=%s", (candidate_id,))
    return _product_candidate(await _get_candidate(candidate_id))


@router.delete("/experience-cards/candidates/{candidate_id}")
async def delete_writing_standard_candidate(candidate_id: str):
    await _get_candidate(candidate_id)
    await execute("DELETE FROM writing_standard_candidate WHERE id=%s", (candidate_id,))
    return {"ok": True, "deletedId": candidate_id}


@router.post("/experience-cards/candidates/{candidate_id}/generate-standard")
async def generate_formal_standard_from_candidate(candidate_id: str, data: dict | None = Body(default=None)):
    payload = data if isinstance(data, dict) else {}
    candidate = await fetchone("SELECT * FROM writing_standard_candidate WHERE id=%s", (candidate_id,))
    card_ids = _safe_list(payload.get("cardIds") or payload.get("sourceCardIds"))
    if candidate:
        card_ids = card_ids or _safe_list(_decode_json(candidate.get("source_card_ids")))
    if not card_ids:
        raise HTTPException(status_code=400, detail="至少选择一张经验卡生成正式写作标准。")
    cards = await _fetch_cards_by_ids(card_ids)
    if not cards:
        raise HTTPException(status_code=404, detail="经验卡不存在")
    standard = await _create_formal_standard_from_cards({
        "name": payload.get("name") or (candidate or {}).get("name") or "我的写作标准",
        "category": payload.get("applicableScenes") or payload.get("category") or (candidate or {}).get("category") or "我的写作标准",
        "description": payload.get("description") or (candidate or {}).get("review_note") or "",
        "sourceCandidateId": candidate_id if candidate else "",
    }, cards)
    if candidate:
        await _update_by_columns("writing_standard_candidate", {
            "status": "promoted",
            "promoted_standard_id": standard["id"],
            "updated_at": _now(),
        }, "id=%s", (candidate_id,))
    return {
        "ok": True,
        "candidate": _product_candidate(await _get_candidate(candidate_id)) if candidate else None,
        "standard": convert_row(standard),
    }


@router.post("/experience-cards/candidates/{candidate_id}/approve")
async def approve_writing_standard_candidate(candidate_id: str, data: dict | None = Body(default=None)):
    candidate = await _get_candidate(candidate_id)
    _ensure_transition(candidate.get("status"), {"draft", "reviewing", "approved"}, "批准候选标准")
    now = _now()
    await _update_by_columns("writing_standard_candidate", {
        "status": "approved",
        "review_note": (data or {}).get("reviewNote") or candidate.get("review_note") or "",
        "updated_at": now,
    }, "id=%s", (candidate_id,))
    return convert_row(await _get_candidate(candidate_id))


@router.post("/experience-cards/candidates/{candidate_id}/reject")
async def reject_writing_standard_candidate(candidate_id: str, data: dict | None = Body(default=None)):
    candidate = await _get_candidate(candidate_id)
    _ensure_transition(candidate.get("status"), {"draft", "reviewing", "approved", "rejected"}, "拒绝候选标准")
    now = _now()
    await _update_by_columns("writing_standard_candidate", {
        "status": "rejected",
        "review_note": (data or {}).get("reviewNote") or candidate.get("review_note") or "",
        "updated_at": now,
    }, "id=%s", (candidate_id,))
    return convert_row(await _get_candidate(candidate_id))


@router.post("/experience-cards/candidates/{candidate_id}/promote")
async def promote_writing_standard_candidate(candidate_id: str, data: dict | None = Body(default=None)):
    payload = data if isinstance(data, dict) else {}
    candidate = await _get_candidate(candidate_id)
    if candidate.get("status") == "promoted":
        standard_id = candidate.get("promoted_standard_id")
        return {
            "ok": True,
            "candidate": convert_row(candidate),
            "standard": convert_row(await fetchone("SELECT * FROM writing_standard WHERE id=%s", (standard_id,))) if standard_id else None,
        }
    _ensure_transition(candidate.get("status"), {"approved"}, "入库候选标准")

    source_card_ids = _decode_json(candidate.get("source_card_ids")) or []
    cards = await _fetch_cards_by_ids(source_card_ids)
    guidance = _sanitize_guidance_for_standard(_decode_json(candidate.get("merged_guidance")) or {}, cards)
    snapshots = [_experience_card_snapshot(card) for card in cards]
    guidance.update({
        "linkedExperienceCardIds": [item["id"] for item in snapshots if item.get("id")],
        "experienceCardSnapshots": snapshots,
        "sourceKind": "user",
        "principles": [guidance.get("characterMethod") or guidance.get("chapterEngine") or "从经验卡抽象出低量写法原则。"],
        "originalMicroDemo": snapshots[0].get("originalMicroDemo") if snapshots else "",
        "antiAiReminder": snapshots[0].get("antiAiReminder") if snapshots else guidance.get("avoid") or "",
        "callStrength": "low",
    })
    standard_id = str(uuid.uuid4())
    now = _now()
    standard_values = {
        "id": standard_id,
        "name": _sanitize_standard_name(candidate.get("name") or "经验卡写作标准"),
        "category": candidate.get("category") or "样本库 / 人工审核",
        "version": payload.get("version") or "v1",
        "short_rule": guidance.get("chapterEngine") or "从人工审核经验卡合并出的抽象写作标准。",
        "guidance_json": _json(guidance),
        "audit_focus": _json(_decode_json(candidate.get("audit_focus")) or _audit_focus_from_guidance(guidance)),
        "source_candidate_id": candidate_id,
        "source_type": "experience_card",
        "status": "active",
        "no_direct_imitation": 1,
        "safety_flags": _json(SAFETY_FLAGS),
        "created_at": now,
        "updated_at": now,
    }
    await _insert("writing_standard", standard_values)
    await _update_by_columns("writing_standard_candidate", {
        "status": "promoted",
        "promoted_standard_id": standard_id,
        "updated_at": now,
    }, "id=%s", (candidate_id,))
    await _mark_cards_merged(source_card_ids, candidate_id)
    return {
        "ok": True,
        "candidate": convert_row(await _get_candidate(candidate_id)),
        "standard": convert_row(await fetchone("SELECT * FROM writing_standard WHERE id=%s", (standard_id,))),
    }


@router.get("/experience-cards/standards")
async def list_writing_standards(status: str = "active"):
    await _ensure_builtin_experience_cards()
    await _ensure_builtin_writing_standards()
    args = []
    where = []
    if status:
        where.append("status=%s")
        args.append(status)
    sql = "SELECT * FROM writing_standard"
    if where:
        sql += f" WHERE {' AND '.join(where)}"
    sql += " ORDER BY updated_at DESC, name ASC"
    return convert_rows(await fetchall(sql, args))


@router.put("/experience-cards/standards/{standard_id}")
async def update_writing_standard(standard_id: str, data: dict):
    standard = await _get_standard(standard_id)
    if _standard_source_kind(standard) == "system":
        raise HTTPException(status_code=409, detail="系统内置正式标准不可编辑，可复制为我的写作标准后再编辑。")
    guidance = _decode_json(standard.get("guidance_json")) or {}
    guidance.update({
        "applicableScenes": _clean_text(data.get("applicableScenes")) or guidance.get("applicableScenes") or "",
        "principles": _safe_list(data.get("principles") or guidance.get("principles")),
        "originalMicroDemo": _clean_text(data.get("originalMicroDemo")) or guidance.get("originalMicroDemo") or "",
        "antiAiReminder": _clean_text(data.get("antiAiReminder")) or guidance.get("antiAiReminder") or "",
        "notApplicableScenes": _clean_text(data.get("notApplicableScenes")) or guidance.get("notApplicableScenes") or "",
        "callStrength": _clean_text(data.get("callStrength")) or guidance.get("callStrength") or "low",
    })
    await _update_by_columns("writing_standard", {
        "name": _sanitize_standard_name(data.get("name") or standard.get("name")),
        "category": _clean_text(data.get("category") or data.get("applicableScenes")) or standard.get("category") or "",
        "short_rule": _safe_list(guidance.get("principles"))[0] if _safe_list(guidance.get("principles")) else standard.get("short_rule") or "",
        "guidance_json": _json(guidance),
        "updated_at": _now(),
    }, "id=%s", (standard_id,))
    return convert_row(await _get_standard(standard_id))


@router.post("/experience-cards/standards/{standard_id}/toggle-active")
async def toggle_writing_standard_active(standard_id: str, data: dict | None = Body(default=None)):
    standard = await _get_standard(standard_id)
    active = (data or {}).get("active")
    current_active = (standard.get("status") or "active") == "active"
    next_active = (not current_active) if active is None else bool(active)
    await _update_by_columns("writing_standard", {
        "status": "active" if next_active else "inactive",
        "updated_at": _now(),
    }, "id=%s", (standard_id,))
    return convert_row(await _get_standard(standard_id))


@router.post("/experience-cards/standards/{standard_id}/copy")
async def copy_writing_standard(standard_id: str, data: dict | None = Body(default=None)):
    standard = await _get_standard(standard_id)
    now = _now()
    new_id = str(uuid.uuid4())
    values = dict(standard)
    guidance = _decode_json(standard.get("guidance_json")) or {}
    guidance["sourceKind"] = "user"
    values.update({
        "id": new_id,
        "name": _sanitize_standard_name((data or {}).get("name") or f"{standard.get('name') or '写作标准'}（我的）"),
        "source_candidate_id": None,
        "source_type": "user_formal_standard",
        "status": "active",
        "guidance_json": _json(guidance),
        "created_at": now,
        "updated_at": now,
    })
    await _insert("writing_standard", _filter_table_values(values, "writing_standard"))
    return convert_row(await _get_standard(new_id))


@router.delete("/experience-cards/standards/{standard_id}")
async def delete_writing_standard(standard_id: str):
    standard = await _get_standard(standard_id)
    if _standard_source_kind(standard) == "system":
        raise HTTPException(status_code=409, detail="系统内置正式标准禁止删除，只能取消激活。")
    await execute("DELETE FROM writing_standard WHERE id=%s", (standard_id,))
    return {"ok": True, "deletedId": standard_id}


async def _ensure_builtin_experience_cards():
    cards = _load_prompt_micro_demo_cards()
    now = _now()
    for card in cards:
        card_id = _builtin_experience_card_id(card["card_id"])
        existing = await fetchone("SELECT * FROM experience_card WHERE id=%s", (card_id,))
        metrics = _decode_json(existing.get("metrics_json")) if existing else {}
        product_status = (metrics or {}).get("productStatus") or "active"
        values = {
            "id": card_id,
            "source_id": None,
            "source_card_ref": card["card_id"],
            "source_title": f"原创微示范卡 {card['version']}",
            "title": card["card_title"],
            "status": "reviewed",
            "card_type": card["card_type"],
            "chapter_skeleton": card["prompt_injection_safe_version"],
            "story_block_span": card.get("dialogue_type") or card["card_title"],
            "protagonist_progression": "",
            "supporting_character_method": "",
            "emotional_dwell": "",
            "scene_dwell": card["original_micro_demo"],
            "dialogue_naturalness": card["dialogue_type"],
            "setting_exposure": "",
            "answers_and_suspense": "",
            "anti_ai_notes": card["anti_skeleton_effect"],
            "genre_tags": _json([card["version"], card["prompt_readiness"], card["card_type"]]),
            "avoid_patterns": _json(["不要复用人物、物件、句子，也不要按清单打卡。"]),
            "chunk_ids": _json([]),
            "metrics_json": _json({
                "sourceKind": "system",
                "productStatus": product_status,
                "promptReadiness": card["prompt_readiness"],
                "microDemoChars": card["micro_demo_chars"],
                "sourceFieldsStripped": True,
            }),
            "safety_flags": _json([*SAFETY_FLAGS, "source_fields_stripped", card["prompt_readiness"]]),
            "review_note": "系统内置经验卡；用于制作候选标准和正式写作标准，不直接进入正文 prompt。",
            "reviewed_at": now,
            "created_at": existing.get("created_at") if existing else now,
            "updated_at": now,
        }
        await _upsert_by_id("experience_card", values)


def _builtin_experience_card_id(source_card_ref: str):
    return _stable_uuid(f"system-card:{source_card_ref}")


async def _ensure_builtin_writing_standards():
    cards = await fetchall("SELECT * FROM experience_card", [])
    now = _now()
    for blueprint in BUILTIN_WRITING_STANDARD_BLUEPRINTS:
        existing = await fetchone("SELECT * FROM writing_standard WHERE id=%s", (blueprint["id"],))
        status = (existing or {}).get("status") or "active"
        snapshots = _snapshots_for_blueprint(cards, blueprint)
        guidance = {
            "applicableScenes": blueprint["applicableScenes"],
            "principles": blueprint["principles"],
            "originalMicroDemo": snapshots[0]["originalMicroDemo"] if snapshots and snapshots[0].get("originalMicroDemo") else blueprint["originalMicroDemo"],
            "antiAiReminder": snapshots[0]["antiAiReminder"] if snapshots and snapshots[0].get("antiAiReminder") else blueprint["antiAiReminder"],
            "notApplicableScenes": blueprint["notApplicableScenes"],
            "callStrength": blueprint["callStrength"],
            "linkedExperienceCardIds": [item["id"] for item in snapshots],
            "experienceCardSnapshots": snapshots,
            "sourceKind": "system",
        }
        values = {
            "id": blueprint["id"],
            "name": blueprint["name"],
            "category": blueprint["category"],
            "version": "v1",
            "short_rule": blueprint["principles"][0],
            "guidance_json": _json(guidance),
            "audit_focus": _json(["是否低量调用正式标准", "是否避免经验卡直连正文", "是否减少模板化口味"]),
            "source_candidate_id": None,
            "source_type": "system_builtin_standard",
            "status": status,
            "no_direct_imitation": 1,
            "safety_flags": _json(SAFETY_FLAGS),
            "created_at": existing.get("created_at") if existing else now,
            "updated_at": now,
        }
        await _upsert_by_id("writing_standard", values)


def _product_card(card: dict):
    source_kind = _card_source_kind(card)
    active = _product_active(card)
    return {
        **convert_row(card),
        "sourceKind": source_kind,
        "sourceLabel": "系统内置" if source_kind == "system" else "我的经验",
        "active": active,
        "statusLabel": "激活" if active else "未激活",
        "locked": source_kind == "system",
        "applicableScenes": card.get("story_block_span") or "",
        "writingMethod": card.get("chapter_skeleton") or "",
        "originalMicroDemo": card.get("scene_dwell") or "",
        "antiAiReminder": card.get("anti_ai_notes") or "",
    }


def _product_candidate(candidate: dict):
    promoted_id = candidate.get("promoted_standard_id") or ""
    return {
        **convert_row(candidate),
        "statusLabel": "已生成正式标准" if promoted_id else "草稿",
        "description": candidate.get("review_note") or "",
        "applicableScenes": candidate.get("category") or "",
    }


def _product_active(row: dict):
    metrics = _decode_json(row.get("metrics_json")) or {}
    return metrics.get("productStatus") != "inactive" and row.get("status") != "archived"


def _card_source_kind(card: dict):
    metrics = _decode_json(card.get("metrics_json")) or {}
    if metrics.get("sourceKind") in {"system", "user"}:
        return metrics["sourceKind"]
    if str(card.get("card_type") or "").startswith("prompt_injectable") or str(card.get("source_title") or "").startswith("原创微示范卡"):
        return "system"
    return "user"


def _standard_source_kind(standard: dict):
    guidance = _decode_json(standard.get("guidance_json")) or {}
    if guidance.get("sourceKind") in {"system", "user"}:
        return guidance["sourceKind"]
    return "system" if standard.get("source_type") == "system_builtin_standard" or str(standard.get("id") or "").startswith("system-") else "user"


async def _experience_card_reference_counts(card_id: str):
    candidates = await fetchall("SELECT * FROM writing_standard_candidate", [])
    standards = await fetchall("SELECT * FROM writing_standard", [])
    candidate_count = 0
    for candidate in candidates:
        if card_id in _safe_list(_decode_json(candidate.get("source_card_ids"))):
            candidate_count += 1
    standard_count = 0
    for standard in standards:
        guidance = _decode_json(standard.get("guidance_json")) or {}
        linked_ids = _safe_list(guidance.get("linkedExperienceCardIds") or guidance.get("sourceCardIds"))
        snapshot_ids = [item.get("id") for item in _safe_list(guidance.get("experienceCardSnapshots")) if isinstance(item, dict)]
        if card_id in {*linked_ids, *snapshot_ids}:
            standard_count += 1
    return {"candidateCount": candidate_count, "standardCount": standard_count}


def _experience_card_snapshot(card: dict):
    return {
        "id": card.get("id") or "",
        "title": _sanitize_text(card.get("title"), SOURCE_SPECIFIC_TOKENS),
        "sourceKind": _card_source_kind(card),
        "applicableScenes": _sanitize_text(card.get("story_block_span"), SOURCE_SPECIFIC_TOKENS),
        "writingMethod": _sanitize_text(card.get("chapter_skeleton"), SOURCE_SPECIFIC_TOKENS),
        "originalMicroDemo": _sanitize_text(card.get("scene_dwell"), SOURCE_SPECIFIC_TOKENS),
        "antiAiReminder": _sanitize_text(card.get("anti_ai_notes"), SOURCE_SPECIFIC_TOKENS),
    }


def _snapshots_for_blueprint(cards: list[dict], blueprint: dict):
    matched = []
    for card in cards:
        text = "\n".join([
            str(card.get("title") or ""),
            str(card.get("story_block_span") or ""),
            str(card.get("chapter_skeleton") or ""),
            str(card.get("scene_dwell") or ""),
            str(card.get("anti_ai_notes") or ""),
        ])
        if any(token in text for token in blueprint.get("match") or []):
            matched.append(_experience_card_snapshot(card))
    if not matched:
        matched = [_experience_card_snapshot(card) for card in cards[:4]]
    return matched[:4]


async def _create_formal_standard_from_cards(metadata: dict, cards: list[dict]):
    now = _now()
    standard_id = str(uuid.uuid4())
    snapshots = [_experience_card_snapshot(card) for card in cards]
    first = snapshots[0] if snapshots else {}
    principles = [
        _sanitize_text(metadata.get("principle"), SOURCE_SPECIFIC_TOKENS),
        first.get("writingMethod") or "",
        _build_candidate_guidance(cards).get("characterMethod") or "",
        _build_candidate_guidance(cards).get("chapterEngine") or "",
    ]
    principle = next((item for item in principles if item), "从经验卡抽象出当前章节可低量调用的写法原则。")
    guidance = {
        "description": _clean_text(metadata.get("description")),
        "applicableScenes": _clean_text(metadata.get("category")),
        "principles": [principle],
        "originalMicroDemo": first.get("originalMicroDemo") or "",
        "antiAiReminder": first.get("antiAiReminder") or "不要复用经验卡人物、物件、句子，也不要按清单打卡。",
        "notApplicableScenes": _clean_text(metadata.get("notApplicableScenes")),
        "callStrength": _clean_text(metadata.get("callStrength")) or "low",
        "linkedExperienceCardIds": [item["id"] for item in snapshots if item.get("id")],
        "experienceCardSnapshots": snapshots,
        "sourceKind": "user",
    }
    values = {
        "id": standard_id,
        "name": _sanitize_standard_name(metadata.get("name") or "我的写作标准"),
        "category": _clean_text(metadata.get("category")) or "我的写作标准",
        "version": "v1",
        "short_rule": principle,
        "guidance_json": _json(guidance),
        "audit_focus": _json(_audit_focus_from_guidance(_build_candidate_guidance(cards))),
        "source_candidate_id": metadata.get("sourceCandidateId") or None,
        "source_type": "user_formal_standard",
        "status": "active",
        "no_direct_imitation": 1,
        "safety_flags": _json(SAFETY_FLAGS),
        "created_at": now,
        "updated_at": now,
    }
    await _insert("writing_standard", values)
    return await _get_standard(standard_id)


async def _get_standard(standard_id: str):
    standard = await fetchone("SELECT * FROM writing_standard WHERE id=%s", (standard_id,))
    if not standard:
        raise HTTPException(status_code=404, detail="正式写作标准不存在")
    return standard


def _filter_table_values(values: dict, table: str):
    allowed = {
        "experience_card": {
            "id", "source_id", "source_card_ref", "source_title", "title", "status", "card_type",
            "chapter_skeleton", "story_block_span", "protagonist_progression", "supporting_character_method",
            "emotional_dwell", "scene_dwell", "dialogue_naturalness", "setting_exposure",
            "answers_and_suspense", "anti_ai_notes", "genre_tags", "avoid_patterns", "chunk_ids",
            "metrics_json", "safety_flags", "review_note", "reviewed_at", "created_at", "updated_at",
        },
        "writing_standard": {
            "id", "name", "category", "version", "short_rule", "guidance_json", "audit_focus",
            "source_candidate_id", "source_type", "status", "no_direct_imitation", "safety_flags",
            "created_at", "updated_at",
        },
    }[table]
    return {key: values.get(key) for key in allowed if key in values}


def _dedupe(values: list[str]):
    seen = set()
    result = []
    for value in values:
        text = _clean_text(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _card_values_from_report(card: dict, source_id: str, chunk_id: str, card_id: str, now: int):
    source_title = _clean_text(card.get("sourceTitle"))
    avoid_patterns = _safe_list(card.get("avoidPatterns")) + _safe_list(card.get("forbiddenImitation"))
    chapter_entry = _clean_text(card.get("chapterEntry"))
    chapter_exit = _clean_text(card.get("chapterExit"))
    return {
        "id": card_id,
        "source_id": source_id,
        "source_card_ref": _clean_text(card.get("id")),
        "source_title": source_title,
        "title": f"{source_title}：抽象创作经验",
        "status": "candidate",
        "card_type": "imported_sample",
        "chapter_skeleton": _join_sentences([f"入章：{chapter_entry}", f"出章：{chapter_exit}"]),
        "story_block_span": "适合沉淀为 1-3 章的故事块经验：让目标、阻力、信息缺口和余波递进，而不是每章重启任务。",
        "protagonist_progression": _clean_text(card.get("characterMethod")),
        "supporting_character_method": _clean_text(card.get("ensembleMethod")),
        "emotional_dwell": _clean_text(card.get("emotionMethod")),
        "scene_dwell": _join_sentences([chapter_entry, _clean_text(card.get("proseRhythm"))]),
        "dialogue_naturalness": _clean_text(card.get("dialogueMethod")),
        "setting_exposure": _clean_text(card.get("informationMethod")),
        "answers_and_suspense": _join_sentences([_clean_text(card.get("challengeMethod")), chapter_exit]),
        "anti_ai_notes": _join_sentences(avoid_patterns),
        "genre_tags": _json(_safe_list(card.get("genreTags"))),
        "avoid_patterns": _json(avoid_patterns),
        "chunk_ids": _json([chunk_id]),
        "metrics_json": _json(card.get("metrics") or {}),
        "safety_flags": _json(SAFETY_FLAGS),
        "review_note": "本地报告迁移卡，待人工审核。",
        "reviewed_at": None,
        "created_at": now,
        "updated_at": now,
    }


def _build_candidate_guidance(cards: list[dict]):
    return {
        "chapterEngine": _join_card_field(cards, "chapter_skeleton"),
        "dialogueMethod": _join_card_field(cards, "dialogue_naturalness"),
        "characterMethod": _join_card_field(cards, "protagonist_progression"),
        "ensembleMethod": _join_card_field(cards, "supporting_character_method"),
        "challengeMethod": _join_card_field(cards, "answers_and_suspense"),
        "emotionMethod": _join_card_field(cards, "emotional_dwell"),
        "informationMethod": _join_card_field(cards, "setting_exposure"),
        "proseRhythm": _join_card_field(cards, "scene_dwell"),
        "endingPreference": "结尾落在可承接的关系变化、阶段答案、新缺口或行动代价上，避免模板化总结。",
        "avoid": _join_card_field(cards, "anti_ai_notes"),
    }


def _sanitize_guidance_for_standard(guidance: dict, cards: list[dict]):
    forbidden_tokens = set(SOURCE_SPECIFIC_TOKENS)
    for card in cards:
        source_title = _clean_text(card.get("source_title"))
        if source_title:
            forbidden_tokens.add(source_title)
            forbidden_tokens.update(_title_token_parts(source_title))

    sanitized = {}
    for key, value in guidance.items():
        if key in FORBIDDEN_PROMPT_KEYS:
            continue
        if isinstance(value, (dict, list)):
            continue
        safe_key = _to_prompt_guidance_key(key)
        sanitized[safe_key] = _sanitize_text(value, forbidden_tokens)

    defaults = _build_candidate_guidance(cards) if cards else {}
    for key in [
        "chapterEngine",
        "dialogueMethod",
        "characterMethod",
        "ensembleMethod",
        "challengeMethod",
        "emotionMethod",
        "informationMethod",
        "proseRhythm",
        "endingPreference",
        "avoid",
    ]:
        if not sanitized.get(key):
            sanitized[key] = _sanitize_text(defaults.get(key) or "保留抽象方法，不复刻样本原文和专名。", forbidden_tokens)
    return sanitized


def _default_safety_policy(cards: list[dict]):
    source_titles = [_clean_text(card.get("source_title")) for card in cards if _clean_text(card.get("source_title"))]
    return {
        "noDirectImitation": True,
        "forbiddenPromptKeys": sorted(FORBIDDEN_PROMPT_KEYS),
        "forbiddenSourceTitles": source_titles,
        "forbiddenSourceTokens": sorted(SOURCE_SPECIFIC_TOKENS),
        "rule": "正式标准只保留抽象方法，不把样本人物名、地名、专有设定或原文片段注入生成上下文。",
    }


def _audit_focus_from_guidance(guidance: dict):
    focus = [
        "是否把经验当成抽象方法，而不是句子级仿写",
        "是否避免样本人物名、地名和专有设定进入新项目",
        "是否服务当前故事块、设定库和卷目标，而不是压过项目设定",
    ]
    if guidance.get("avoid"):
        focus.append("是否落实反 AI 味注意事项")
    return focus


def _to_prompt_guidance_key(key: str):
    aliases = {
        "chapter_engine": "chapterEngine",
        "dialogue_method": "dialogueMethod",
        "character_method": "characterMethod",
        "ensemble_method": "ensembleMethod",
        "challenge_method": "challengeMethod",
        "emotion_method": "emotionMethod",
        "information_method": "informationMethod",
        "prose_rhythm": "proseRhythm",
        "ending_preference": "endingPreference",
    }
    return aliases.get(str(key or "").strip(), str(key or "").strip())


def _sanitize_standard_name(value):
    text = _sanitize_text(value, SOURCE_SPECIFIC_TOKENS)
    return text if text else "抽象写作标准"


def _sanitize_text(value, forbidden_tokens=()):
    text = _clean_text(value)
    if not text:
        return ""
    for key in FORBIDDEN_PROMPT_KEYS:
        text = text.replace(key, "")
    for token in sorted({str(item).strip() for item in forbidden_tokens if str(item).strip()}, key=len, reverse=True):
        text = text.replace(token, "样本原作")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 520:
        text = text[:500].rstrip("，。；;,. ") + "。"
    return text


def _load_prompt_micro_demo_cards():
    cards = []
    for version, default_type, filename in PROMPT_MICRO_DEMO_FILES:
        path = PROMPT_MICRO_DEMO_DATA_DIR / filename
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if version == "v2.1":
            raw_cards = [
                *(payload.get("promptInjectableCards") or []),
                *(payload.get("dialoguePromptInjectableCards") or []),
            ]
        else:
            raw_cards = payload.get("dialoguePromptInjectableCards") or []
        for raw_card in raw_cards:
            normalized = _normalize_prompt_micro_demo_card(raw_card, payload, version, default_type, filename)
            if normalized:
                cards.append(normalized)
    return cards


def _normalize_prompt_micro_demo_card(raw_card: dict, payload: dict, version: str, card_type: str, filename: str):
    _ = [raw_card.get(field) for field in PROMPT_MICRO_DEMO_FORBIDDEN_FIELDS]
    card_id = _clean_text(raw_card.get("cardId"))
    card_title = _sanitize_text(raw_card.get("cardTitle"), SOURCE_SPECIFIC_TOKENS)
    safe_version = _sanitize_text(raw_card.get("promptInjectionSafeVersion"), SOURCE_SPECIFIC_TOKENS)
    micro_demo = _sanitize_text(raw_card.get("originalMicroDemo"), SOURCE_SPECIFIC_TOKENS)
    anti_skeleton = _sanitize_text(raw_card.get("antiSkeletonEffect"), SOURCE_SPECIFIC_TOKENS)
    if not all([card_id, card_title, safe_version, micro_demo, anti_skeleton]):
        return None
    prompt_readiness = _prompt_micro_demo_readiness(raw_card, payload, version)
    return {
        "version": version,
        "source_file": filename,
        "card_id": card_id,
        "card_title": card_title,
        "card_type": card_type,
        "dialogue_type": _sanitize_text(raw_card.get("dialogueType"), SOURCE_SPECIFIC_TOKENS),
        "prompt_readiness": prompt_readiness,
        "prompt_injection_safe_version": safe_version,
        "original_micro_demo": micro_demo,
        "anti_skeleton_effect": anti_skeleton,
        "micro_demo_chars": int(raw_card.get("originalMicroDemoCharCount") or len(micro_demo)),
        "source_fields_stripped": True,
    }


def _prompt_micro_demo_readiness(raw_card: dict, payload: dict, version: str):
    explicit = _clean_text(raw_card.get("promptReadiness"))
    if explicit:
        return explicit
    card_id = _clean_text(raw_card.get("cardId"))
    if card_id in (payload.get("promptReadyCardIds") or []):
        return PROMPT_READY_LOW_DOSE
    if card_id in (payload.get("backendReferenceOnlyCardIds") or []):
        return BACKEND_REFERENCE_ONLY
    safety = raw_card.get("safetyCheck") or {}
    low_risk = (
        safety.get("directImitationRisk") == "low"
        and safety.get("containsSourceNameInPromptText") is not True
        and safety.get("containsSourceCharacters") is not True
        and safety.get("containsLongQuote") is not True
    )
    return PROMPT_READY_LOW_DOSE if version == "v2.1" and low_risk else BACKEND_REFERENCE_ONLY


def _title_token_parts(source_title: str):
    cleaned = re.sub(r"[《》【】\[\]（）()：:·,，.。!！?？\s]+", " ", source_title)
    return [part for part in cleaned.split() if len(part) >= 2]


async def _mark_cards_merged(card_ids: list[str], candidate_id: str):
    if not card_ids:
        return
    placeholders = ",".join(["%s"] * len(card_ids))
    await execute(
        f"UPDATE experience_card SET status=%s, updated_at=%s WHERE id IN ({placeholders})",
        ["merged", _now(), *card_ids],
    )


async def _fetch_cards_by_ids(card_ids: list[str]):
    if not card_ids:
        return []
    placeholders = ",".join(["%s"] * len(card_ids))
    return await fetchall(f"SELECT * FROM experience_card WHERE id IN ({placeholders})", card_ids)


async def _get_card(card_id: str):
    card = await fetchone("SELECT * FROM experience_card WHERE id=%s", (card_id,))
    if not card:
        raise HTTPException(status_code=404, detail="经验卡不存在")
    return card


async def _get_candidate(candidate_id: str):
    candidate = await fetchone("SELECT * FROM writing_standard_candidate WHERE id=%s", (candidate_id,))
    if not candidate:
        raise HTTPException(status_code=404, detail="候选标准不存在")
    return candidate


def _ensure_status(status: str, allowed: set[str], label: str):
    if status not in allowed:
        raise HTTPException(status_code=400, detail=f"{label}不合法：{status}")


def _ensure_transition(current: str, allowed: set[str], action: str):
    if current not in allowed:
        raise HTTPException(status_code=409, detail=f"{action}不允许从 {current} 状态执行")


async def _upsert_by_id(table: str, values: dict):
    existing = await fetchone(f"SELECT id FROM {table} WHERE id=%s", (values["id"],))
    if existing:
        update_values = {k: v for k, v in values.items() if k not in {"id", "created_at"}}
        await _update_by_columns(table, update_values, "id=%s", (values["id"],))
        return False
    await _insert(table, values)
    return True


async def _upsert_experience_card_from_report(values: dict):
    existing = await fetchone("SELECT * FROM experience_card WHERE id=%s", (values["id"],))
    if not existing:
        await _insert("experience_card", values)
        return True

    safe_updates = {}
    for key in ("genre_tags", "avoid_patterns", "chunk_ids", "safety_flags"):
        merged = _merge_json_arrays(existing.get(key), values.get(key))
        if merged is not None:
            safe_updates[key] = _json(merged)
    if _is_blank_stored_value(existing.get("metrics_json")) and values.get("metrics_json"):
        safe_updates["metrics_json"] = values["metrics_json"]
    if safe_updates:
        safe_updates["updated_at"] = values["updated_at"]
        await _update_by_columns("experience_card", safe_updates, "id=%s", (values["id"],))
    return False


async def _insert(table: str, values: dict):
    cols = list(values.keys())
    placeholders = ",".join(["%s"] * len(cols))
    await execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})", list(values.values()))


async def _update_by_columns(table: str, values: dict, where_sql: str, where_args: tuple):
    if not values:
        return
    sets = [f"{key}=%s" for key in values.keys()]
    args = list(values.values()) + list(where_args)
    await execute(f"UPDATE {table} SET {', '.join(sets)} WHERE {where_sql}", args)


def _load_local_report():
    path = Path(__file__).resolve().parents[2] / "frontend" / "src" / "data" / "localWritingSampleReport.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _stable_uuid(seed: str):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"novel_creator:{seed}"))


def _stable_hash(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:32]


def _hash_json(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:32]


def _json(value):
    return json.dumps(value, ensure_ascii=False)


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


def _is_blank_stored_value(value):
    decoded = _decode_json(value)
    if decoded in (None, "", [], {}):
        return True
    if isinstance(value, str) and value.strip() in {"", "[]", "{}"}:
        return True
    return False


def _merge_json_arrays(existing, incoming):
    existing_list = _safe_list(_decode_json(existing) if isinstance(existing, str) else existing)
    incoming_list = _safe_list(_decode_json(incoming) if isinstance(incoming, str) else incoming)
    if not incoming_list:
        return None
    seen = set()
    merged = []
    for item in [*existing_list, *incoming_list]:
        key = _clean_text(item)
        if key and key not in seen:
            seen.add(key)
            merged.append(item)
    if merged != existing_list:
        return merged
    return None


def _safe_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "")]
    return [value]


def _join_card_field(cards: list[dict], field: str, limit: int = 4):
    values = []
    seen = set()
    for card in cards:
        text = _clean_text(card.get(field))
        key = text[:80]
        if text and key not in seen:
            seen.add(key)
            values.append(text)
        if len(values) >= limit:
            break
    return _join_sentences(values)


def _join_sentences(values):
    parts = [_clean_text(item) for item in values if _clean_text(item)]
    return "；".join(parts)


def _clean_text(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return re.sub(r"\s+", " ", str(value)).strip()


def _now():
    return int(time.time() * 1000)
