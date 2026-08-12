from __future__ import annotations

from collections.abc import Mapping
import json

from backend.services.draft_selection import LOCAL_DRAFT_OPERATION_INTENTS


def _safe_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def build_chapter_draft_messages(
    *,
    operation_type: str = "rewrite_full",
    chapter_session: Mapping,
    working_draft: Mapping,
    author_instruction: str = "",
    selection_context: Mapping | None = None,
) -> list[dict[str, str]]:
    chapter_outline = chapter_session.get("chapter_outline") or {}
    system = (
        "你是长篇男频小说写作助手。任务是写出让读者愿意继续读的章节正文，"
        "不要写分析、不要列规则、不要输出 JSON。正文要有具体场景、人物反应、"
        "对话和推进，避免干巴巴复述设定。"
    )
    user_parts = [
        f"章节：第 {int(chapter_session.get('chapter_num') or 1)} 章",
        f"本章已确认小纲：{_safe_json(chapter_outline)}",
    ]
    if operation_type in LOCAL_DRAFT_OPERATION_INTENTS:
        if (
            not isinstance(selection_context, Mapping)
            or set(selection_context) != {"left", "selected", "right"}
            or any(not isinstance(selection_context[key], str) for key in selection_context)
        ):
            raise ValueError("invalid local draft selection context")
        try:
            for value in selection_context.values():
                value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("invalid local draft selection context") from None
        user_parts.extend([
            f"Local intent: {LOCAL_DRAFT_OPERATION_INTENTS[operation_type]}",
            f"选中内容左侧上下文：{selection_context['left']}",
            f"需要处理的精确选中内容：{selection_context['selected']}",
            f"选中内容右侧上下文：{selection_context['right']}",
        ])
    elif operation_type != "generate_new":
        user_parts.append(
            f"当前工作稿：{working_draft.get('content') or '（空）'}"
        )
    instruction = str(author_instruction or "").strip()
    if instruction:
        user_parts.append(f"作者临时要求：{instruction}")
    if operation_type == "generate_new":
        user_parts.append(
            "请根据本章小纲直接生成一版完整章节正文。保持白话、画面感和人物区分度。"
        )
    elif operation_type in LOCAL_DRAFT_OPERATION_INTENTS:
        user_parts.append("只输出用于替换精确选中内容的新文本，不要解释、标注或输出全文。")
    else:
        user_parts.append(
            "请直接输出章节正文。保持白话、画面感和人物区分度；"
            "如果当前工作稿为空，从当前故事块自然开篇；如果不为空，"
            "在保留作者意图的基础上重写成完整正文。"
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ]
