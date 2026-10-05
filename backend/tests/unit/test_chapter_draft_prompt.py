from copy import deepcopy
import json

import pytest

from backend.prompts.chapter_draft import build_chapter_draft_messages


LOCAL_CASES = {
    "rewrite_selection": "rewrite",
    "polish_selection": "polish",
    "expand_selection": "expand",
    "compress_selection": "compress",
}


def test_blank_instruction_promotes_contract_chapter_length_without_old_draft():
    messages = build_chapter_draft_messages(
        operation_type="generate_new",
        chapter_session={"chapter_num": 3, "chapter_outline": {"chapterGoal": "只核查旧船记录"}},
        working_draft={"content": "旧的有补充要求的正文"},
        story_context={"creationContract": {"chapterWordRangePreference": [2800, 3800]}},
    )
    prompt = messages[1]["content"]
    assert "本次完整章节目标字数：2800–3800 字" in prompt
    assert "只核查旧船记录" in prompt
    assert "作者临时要求：" not in prompt
    assert "旧的有补充要求的正文" not in prompt


def test_local_edit_does_not_receive_full_chapter_word_budget():
    messages = build_chapter_draft_messages(
        operation_type="polish_selection",
        chapter_session={"chapter_num": 3, "chapter_outline": {}},
        working_draft={"content": "旧正文"},
        selection_context={"left": "", "selected": "一句话", "right": ""},
        story_context={"creationContract": {"chapterWordRangePreference": [2800, 3800]}},
    )
    assert "本次完整章节目标字数：" not in messages[1]["content"]


def test_confirmed_outline_capacity_and_disclosure_boundary_are_explicit():
    messages = build_chapter_draft_messages(
        operation_type="generate_new",
        chapter_session={"chapter_num": 3, "chapter_outline": {
            "capacityPolicy": {"targetMin": 1800, "targetMax": 2400},
            "chapterGoal": "证人只说见过记录，牌子用途仍未知",
            "scenes": ["询问牌子用途时，证人只答不知"],
            "forbiddenEarlyEvents": ["提前解释牌子用途"],
            "continuation": ["人物尚未查到完整记录"],
        }},
        working_draft={"content": ""},
        story_context={"creationContract": {"chapterWordRangePreference": [2800, 3800]}},
    )
    prompt = messages[1]["content"]
    assert "本次完整章节目标字数：1800–2400 字" in prompt
    boundary = prompt.split("本章最终执行边界", 1)[1]
    assert "询问牌子用途时，证人只答不知" in boundary
    assert "禁止提前发生：\n- 提前解释牌子用途" in boundary
    assert "人物尚未查到完整记录" in boundary


def test_polish_preserves_story_information_and_only_replaces_selection():
    messages = build_chapter_draft_messages(
        operation_type="polish_selection",
        chapter_session={"chapter_num": 2, "chapter_outline": {}},
        working_draft={"content": "不应发送的完整正文"},
        selection_context={"left": "左侧", "selected": "待润色片段", "right": "右侧"},
    )
    prompt = messages[1]["content"]
    assert "保留剧情、既定事实、人物意图和信息量" in prompt
    assert "不得新增事件或改变人物贡献归属" in prompt
    assert "只输出用于替换精确选中内容的新文本" in prompt
    assert "不应发送的完整正文" not in prompt


def test_generate_new_prompt_uses_outline_but_not_existing_prose_as_rewrite_input():
    messages = build_chapter_draft_messages(
        operation_type="generate_new",
        chapter_session={
            "chapter_num": 7,
            "chapter_outline": {"chapterGoal": "逼主角公开选择阵营"},
        },
        working_draft={"content": "这段旧正文绝不能成为重写输入"},
        author_instruction="多一点人物试探",
    )

    rendered = "\n".join(item["content"] for item in messages)
    assert "逼主角公开选择阵营" in rendered
    assert "多一点人物试探" in rendered
    assert "这段旧正文绝不能成为重写输入" not in rendered
    assert "从当前工作稿" not in rendered
    assert "作者临时要求是本次生成的硬约束" in messages[0]["content"]
    assert "不要输出 Markdown 标题" in messages[0]["content"]
    assert "不得扩写到小纲未选择的后续阶段" in messages[0]["content"]


def test_generate_new_receives_authoritative_long_form_story_context():
    messages = build_chapter_draft_messages(
        operation_type="generate_new",
        chapter_session={
            "chapter_num": 2,
            "chapter_outline": {"chapterGoal": "完成第一次织机试验"},
        },
        working_draft={"content": ""},
        story_context={
            "seed": {"openingHook": "压胜钱是系统宿主，只提供有限提示"},
            "creationContract": {"targetLength": "至少二百万字"},
            "styleContract": {"prose": "白话、克制、具体"},
            "creationBible": {"hardRules": ["残页必须由主角主动收集"]},
            "canon": {"currentState": [{"name": "阿芸", "status": "仍被扣押"}]},
            "previousFinalChapter": {
                "chapterNumber": 1,
                "title": "泔水醒来，三日织机赌局",
                "content": "王老大摔门而去，阿芸仍在门外等候。",
            },
        },
    )

    rendered = "\n".join(item["content"] for item in messages)
    assert "压胜钱是系统宿主" in rendered
    assert "残页必须由主角主动收集" in rendered
    assert "阿芸" in rendered
    assert "王老大摔门而去" in rendered
    assert "上一章已定稿正文是本章开篇的直接连续性依据" in rendered
    assert "不得擅自改写" in messages[0]["content"]
    assert "贡献归属" in messages[0]["content"]
    assert "不得遗漏" in messages[0]["content"]
    assert "同类操作—解释循环" in messages[0]["content"]
    assert "第几章" in messages[0]["content"]


def test_rewrite_prompt_keeps_existing_prose_available_for_later_operation_types():
    messages = build_chapter_draft_messages(
        operation_type="rewrite_full",
        chapter_session={"chapter_num": 7, "chapter_outline": {}},
        working_draft={"content": "需要保留的作者正文"},
    )

    rendered = "\n".join(item["content"] for item in messages)
    assert "需要保留的作者正文" in rendered


def test_local_selection_prompts_use_only_exact_selection_and_bounded_context():
    for operation_type, intent in LOCAL_CASES.items():
        messages = build_chapter_draft_messages(
            operation_type=operation_type,
            chapter_session={
                "chapter_num": 7,
                "chapter_outline": {"chapterGoal": "逼主角选择阵营"},
            },
            working_draft={"content": "完整工作稿绝不能进入局部提示词"},
            selection_context={
                "left": "左侧边界",
                "selected": "精确选中文本",
                "right": "右侧边界",
            },
            author_instruction="保持克制",
        )

        rendered = "\n".join(item["content"] for item in messages)
        assert intent in rendered
        assert "精确选中文本" in rendered
        assert "左侧边界" in rendered
        assert "右侧边界" in rendered
        assert "逼主角选择阵营" in rendered
        assert "保持克制" in rendered
        assert "完整工作稿绝不能进入局部提示词" not in rendered


def test_local_selection_prompt_requires_a_closed_context_shape():
    for context in (None, {}, {"left": "左", "selected": "中"}, {"left": "左", "selected": "中", "right": "右", "extra": "x"}):
        try:
            build_chapter_draft_messages(
                operation_type="rewrite_selection",
                chapter_session={"chapter_num": 1, "chapter_outline": {}},
                working_draft={"content": "不得回退到全文"},
                selection_context=context,
            )
        except ValueError as error:
            assert str(error) == "invalid local draft selection context"
        else:
            raise AssertionError("invalid local context must fail closed")


@pytest.mark.parametrize("continuation", [
    ["上一章留下的账料复核仍待验官公布，甲员尚未核对结论"],
    "上一章留下的账料复核仍待验官公布，甲员尚未核对结论",
])
@pytest.mark.parametrize(("operation_type", "review_context"), [
    ("generate_new", None),
    ("rewrite_full", None),
    ("generate_new", {
        "findings": [{"reason": "核对动作过于概括", "suggestedAction": "写清本章实际核对过程"}],
    }),
])
def test_full_chapter_continuation_is_carried_in_work_that_can_finish_in_this_chapter(
    continuation, operation_type, review_context,
):
    outline = {
        "chapterGoal": "验官实际公布复核结论，甲员当场核对完成；具体责任人仍未知",
        "scenes": ["验官当众公布复核结论", "甲员逐条核对并记下实际结论与来源"],
        "forbiddenEarlyEvents": ["不得提前揭露具体责任人"],
        "continuation": continuation,
        "capacityPolicy": {"targetMin": 1800, "targetMax": 2400},
    }
    original = deepcopy(outline)
    messages = build_chapter_draft_messages(
        operation_type=operation_type,
        chapter_session={"chapter_num": 3, "chapter_outline": outline},
        working_draft={"content": "需要保留意图的作者原稿"},
        story_context={"creationContract": {"chapterWordRangePreference": [2800, 3800]}},
        review_context=review_context,
    )
    prompt = messages[1]["content"]
    outline_line = next(line for line in prompt.splitlines() if line.startswith("本章已确认小纲："))
    assert json.loads(outline_line.split("：", 1)[1]) == original
    assert outline == original
    boundary = prompt.split("本章最终执行边界", 1)[1]
    assert "必须达成的目标与保留的未知：" + original["chapterGoal"] in boundary
    assert "逐场交付与人物知情范围：\n- " + "\n- ".join(original["scenes"]) in boundary
    assert "禁止提前发生：\n- 不得提前揭露具体责任人" in boundary
    carried_in = continuation[0] if isinstance(continuation, list) else continuation
    expected = "承接的未完成情节：" + ("\n- " if isinstance(continuation, list) else "") + carried_in
    assert expected in boundary
    assert "结束时的状态与后续边界" not in prompt
    assert "本次完整章节目标字数：1800–2400 字" in prompt
    assert "篇幅执行预算：整章以约 2100 字为中心" in prompt
    assert "当前 2 场，主体每场平均约 945 字" in prompt
    if operation_type == "rewrite_full" or review_context is not None:
        assert "当前工作稿：需要保留意图的作者原稿" in prompt
    else:
        assert "需要保留意图的作者原稿" not in prompt
    if review_context is not None:
        review_line = next(line for line in prompt.splitlines() if line.startswith("本稿完整审稿意见（由服务端读取）："))
        assert json.loads(review_line.split("：", 1)[1]) == review_context
        assert "依据以上审稿意见调整并输出完整章节正文" in prompt


@pytest.mark.parametrize("operation_type", LOCAL_CASES)
def test_continuation_label_fix_keeps_local_selection_scope(operation_type):
    outline = {
        "chapterGoal": "本章完成对照核验",
        "scenes": ["现场核对后记下结论"],
        "forbiddenEarlyEvents": ["不得启程前往别处"],
        "continuation": ["上一章的对照尚未核完"],
        "capacityPolicy": {"targetMin": 1800, "targetMax": 2400},
    }
    messages = build_chapter_draft_messages(
        operation_type=operation_type,
        chapter_session={"chapter_num": 3, "chapter_outline": outline},
        working_draft={"content": "不得发送的完整工作稿"},
        selection_context={"left": "左侧上下文", "selected": "精确选区", "right": "右侧上下文"},
    )
    prompt = messages[1]["content"]
    outline_line = next(line for line in prompt.splitlines() if line.startswith("本章已确认小纲："))
    assert json.loads(outline_line.split("：", 1)[1]) == outline
    assert "需要处理的精确选中内容：精确选区" in prompt
    assert "选中内容左侧上下文：左侧上下文" in prompt
    assert "选中内容右侧上下文：右侧上下文" in prompt
    assert "只输出用于替换精确选中内容的新文本" in prompt
    assert "不得发送的完整工作稿" not in prompt
    assert "本章最终执行边界" not in prompt
    assert "承接的未完成情节：" not in prompt
    assert "结束时的状态与后续边界：" not in prompt
    assert "本次完整章节目标字数：" not in prompt
    assert "篇幅执行预算：" not in prompt
