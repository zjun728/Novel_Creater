from backend.prompts.chapter_draft import build_chapter_draft_messages


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

