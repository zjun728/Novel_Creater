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
