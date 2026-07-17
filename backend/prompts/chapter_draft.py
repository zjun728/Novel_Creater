from __future__ import annotations

from collections.abc import Mapping
import json


def _safe_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def build_chapter_draft_messages(
    *,
    chapter_session: Mapping,
    working_draft: Mapping,
    author_instruction: str = "",
) -> list[dict[str, str]]:
    planning = chapter_session.get("planning_snapshot") or {}
    system = (
        "你是长篇男频小说写作助手。任务是写出让读者愿意继续读的章节正文，"
        "不要写分析、不要列规则、不要输出 JSON。正文要有具体场景、人物反应、"
        "对话和推进，避免干巴巴复述设定。"
    )
    user_parts = [
        f"章节：第 {int(chapter_session.get('chapter_num') or 1)} 章",
        f"当前故事块与规划：{_safe_json(planning)}",
        f"当前工作稿：{working_draft.get('content') or '（空）'}",
    ]
    instruction = str(author_instruction or "").strip()
    if instruction:
        user_parts.append(f"作者临时要求：{instruction}")
    user_parts.append(
        "请直接输出章节正文。保持白话、画面感和人物区分度；"
        "如果当前工作稿为空，从当前故事块自然开篇；如果不为空，在保留作者意图的基础上重写成完整正文。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ]
