from backend.prompts.chapter_draft import build_chapter_draft_messages


LOCAL_CASES = {
    "rewrite_selection": "rewrite",
    "polish_selection": "polish",
    "expand_selection": "expand",
    "compress_selection": "compress",
}


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
