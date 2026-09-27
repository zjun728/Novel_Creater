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
    story_context: Mapping | None = None,
    review_context: Mapping | None = None,
) -> list[dict[str, str]]:
    chapter_outline = chapter_session.get("chapter_outline") or {}
    system = (
        "你是长篇男频小说写作助手。任务是写出让读者愿意继续读的章节正文，"
        "不要写分析、不要列规则、不要输出 JSON。正文要有具体场景、人物反应、"
        "对话和推进，避免干巴巴复述设定。作者临时要求是本次生成的硬约束；"
        "其中包含目标字数时必须在范围内结束。只输出纯文本正文，不要输出 Markdown 标题、"
        "创作说明或总结。严格停在已确认小纲的章节边界，不得扩写到小纲未选择的后续阶段。"
        "种子、创作合同、风格合同、创作圣经、当前 Canon 和上一章定稿均是权威依据，"
        "不得擅自改写其中的既定事实；发生冲突时以创作圣经和当前 Canon 为准。"
        "权威背景中的秘密、后续设计和世界规则不等于本章人物已经知道或本章可以揭露。"
        "本章的信息披露范围以已确认小纲为限：小纲要求未知、只答不知、不得揭露或禁止提前发生的内容，"
        "即使背景已经给出答案，也不得通过人物台词、传闻、推测或旁白提前解释；临时要求留空也必须遵守。"
        "只兑现小纲选定的调查方向和交付，不自行增加新的关键知情人、逃亡者、抄本持有人或远期目的地来扩展任务。"
        "人物证言、传闻和推测必须保留来源及不确定性，叙述者不得随后把它们写成已证实事实。"
        "时间、伤势和物品归属承接既定事实；没有依据时不补写具体年份、失踪月份、额外伤势或确切康复期限。"
        "小纲指定由谁观察、判断、提出办法或完成记录时，必须保留该人物的贡献归属；"
        "小纲中的可见损失、记录物和场景交付不得遗漏，也不能只用一句结论代替正文证据。"
        "合并没有新变化的同类操作—解释循环，每一次重复必须带来新的代价、关系变化或判断。"
        "正文不得出现‘第几章’‘本章’‘小纲’等面向作者的元叙事字样；"
        "结尾应落在已发生的状态变化或具体悬念上，不能只写角色准备下一次行动。"
    )
    user_parts = [
        f"章节：第 {int(chapter_session.get('chapter_num') or 1)} 章",
    ]
    if story_context:
        user_parts.extend([
            "以下为本次写作的权威长篇上下文：",
            f"创意种子：{_safe_json(story_context.get('seed') or {})}",
            f"创作合同：{_safe_json(story_context.get('creationContract') or {})}",
            f"风格合同：{_safe_json(story_context.get('styleContract') or {})}",
            f"创作圣经：{_safe_json(story_context.get('creationBible') or {})}",
            f"当前 Canon：{_safe_json(story_context.get('canon') or {})}",
        ])
        previous = story_context.get("previousFinalChapter")
        if previous:
            user_parts.append(
                "上一章已定稿正文是本章开篇的直接连续性依据："
                f"{_safe_json(previous)}"
            )
    user_parts.append(f"本章已确认小纲：{_safe_json(chapter_outline)}")
    contract = (story_context or {}).get("creationContract") or {}
    word_range = contract.get("chapterWordRangePreference") if isinstance(contract, Mapping) else None
    capacity = chapter_outline.get("capacityPolicy") or {}
    length_plan = None
    if isinstance(capacity, Mapping) and all(
        type(capacity.get(key)) is int for key in ("targetMin", "targetMax")
    ) and 0 < capacity["targetMin"] <= capacity["targetMax"]:
        word_range = [capacity["targetMin"], capacity["targetMax"]]
    if (
        operation_type not in LOCAL_DRAFT_OPERATION_INTENTS
        and isinstance(word_range, (list, tuple))
        and len(word_range) == 2
        and all(type(value) is int for value in word_range)
        and 0 < word_range[0] <= word_range[1]
    ):
        user_parts.append(
            f"本次完整章节目标字数：{word_range[0]}–{word_range[1]} 字，按已确认小纲容量、创作合同的顺序读取。"
            "除非作者临时要求明确调整字数，否则必须按此范围分配场景篇幅并收束；"
            "不要为凑字数增加小纲外的事件，也不要用概述替代场景。"
        )
        target = (word_range[0] + word_range[1]) // 2
        scenes = chapter_outline.get("scenes")
        scene_count = sum(isinstance(scene, str) and bool(scene.strip()) for scene in scenes) if isinstance(scenes, list) else 0
        length_plan = (
            f"篇幅执行预算：整章以约 {target} 字为中心，必须留出结尾空间，不能把每场都扩成独立长章。"
            + (f"当前 {scene_count} 场，主体每场平均约 {int(target * 0.9) // scene_count} 字，余量用于过渡与收束；可按重要性调配，但总量仍服从目标范围。" if scene_count else "按场景重要性分配有限篇幅。")
            + "输出前在内部检查完整章节的篇幅和关键交付：超长时压缩重复动作、解释和对白，不删除必要事实与结尾，不截断句子，也不新增剧情凑数。审稿重写同样遵守此预算，不能只追加段落。"
            + "作者临时要求明确改了字数时，以作者本次字数要求重算预算；以上默认预算不覆盖该要求。不要输出预算或自检说明。"
        )
    user_parts.append(
        "执行本章前先在内部核对小纲的场景交付、禁止提前发生事项和仍未知的信息，"
        "据此约束正文中的叙述与台词；不要输出这份核对过程。"
    )
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
    elif operation_type != "generate_new" or review_context is not None:
        user_parts.append(
            f"当前工作稿：{working_draft.get('content') or '（空）'}"
        )
    instruction = str(author_instruction or "").strip()
    if instruction:
        user_parts.append(f"作者临时要求：{instruction}")
    if review_context is not None:
        if operation_type != "generate_new":
            raise ValueError("review adjustment requires full chapter generation")
        user_parts.extend([
            f"本稿完整审稿意见（由服务端读取）：{_safe_json(review_context)}",
            "请在当前工作稿基础上，依据以上审稿意见调整并输出完整章节正文。"
            "逐项处理有效问题，保留未受影响的剧情与人物意图。审稿意见是修订建议，"
            "不能作为新增事实或越过小纲边界的依据；与权威背景冲突时以权威背景为准。"
            "只输出调整后的完整正文，不输出意见清单或修改说明。",
        ])
    elif operation_type == "generate_new":
        user_parts.append(
            "请根据本章小纲直接生成一版完整章节正文。保持白话、画面感和人物区分度。"
        )
    elif operation_type in LOCAL_DRAFT_OPERATION_INTENTS:
        if operation_type == "polish_selection":
            user_parts.append(
                "去 AI 味/润色只调整选区的表达：保留剧情、既定事实、人物意图和信息量，"
                "不得新增事件或改变人物贡献归属。减少解释腔、套路反差、抽象判断、"
                "同义反复和机械节奏；保留原有叙述视角与人物声音，勿为润色堆砌辞藻。"
            )
        user_parts.append("只输出用于替换精确选中内容的新文本，不要解释、标注或输出全文。")
    else:
        user_parts.append(
            "请直接输出章节正文。保持白话、画面感和人物区分度；"
            "如果当前工作稿为空，从当前故事块自然开篇；如果不为空，"
            "在保留作者意图的基础上重写成完整正文。"
        )
    if operation_type not in LOCAL_DRAFT_OPERATION_INTENTS:
        user_parts.append("本章最终执行边界（自动从已确认小纲读取，不依赖作者临时补充）：")
        for key, label in (
            ("chapterGoal", "必须达成的目标与保留的未知"),
            ("scenes", "逐场交付与人物知情范围"),
            ("forbiddenEarlyEvents", "禁止提前发生"),
            ("continuation", "结束时的状态与后续边界"),
        ):
            value = chapter_outline.get(key)
            if isinstance(value, str) and value.strip():
                user_parts.append(f"{label}：{value}")
            elif isinstance(value, list):
                user_parts.append(label + "：\n" + "\n".join(
                    f"- {item}" for item in value if isinstance(item, str) and item.strip()
                ))
    if length_plan is not None:
        user_parts.append(length_plan)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ]
