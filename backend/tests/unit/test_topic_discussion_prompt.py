from __future__ import annotations

import json

import pytest


def _snapshot(index: int = 1) -> dict:
    return {
        "id": f"snapshot-{index}",
        "source_id": f"source-{index}",
        "content_hash": f"{index:x}" * 64,
        "captured_at": 1_721_000_000_000 + index,
        "platform": "fanqie",
        "ranking_name": "reading",
        "category": "all",
        "source_url": "https://private.example/raw-url",
        "entries": (
            {
                "rank": 1,
                "title": f"公开作品{index}",
                "author": "公开作者",
                "category": "玄幻",
                "public_metrics": {"readers": 123},
                "work_url": "https://private.example/work-url",
                "raw_html": "PRIVATE_RAW_HTML",
            },
        ),
        "api_key": "PRIVATE_API_KEY",
    }


def test_prompt_accepts_blank_idea_without_market_evidence():
    from backend.prompts.topic_discussion import build_topic_discussion_messages

    messages = build_topic_discussion_messages(
        transcript=({"role": "user", "content": "我想写地方治理题材。"},),
        evidence=(),
        subject=None,
    )
    rendered = json.dumps(messages, ensure_ascii=False)

    assert [item["role"] for item in messages] == ["system", "user", "user"]
    assert "我想写地方治理题材" in rendered
    assert '"directionSuggestions"' in messages[0]["content"]
    assert '"candidateSuggestions"' in messages[0]["content"]
    assert "市场证据不是必填项" in rendered


def test_prompt_projects_only_bounded_public_snapshot_facts_and_exact_subject():
    from backend.prompts.topic_discussion import build_topic_discussion_messages

    messages = build_topic_discussion_messages(
        transcript=(
            {"role": "user", "content": "分析这个方向。"},
            {"role": "assistant", "content": "可以继续收束。"},
        ),
        evidence=(_snapshot(),),
        subject={
            "kind": "candidate",
            "id": "candidate-1",
            "version": 2,
            "content_hash": "a" * 64,
            "payload": {"title": "典镇山河", "genre": "东方奇幻"},
            "api_key": "PRIVATE_SUBJECT_KEY",
        },
    )
    rendered = json.dumps(messages, ensure_ascii=False)

    assert "snapshot-1" in rendered
    assert "公开作品1" in rendered
    assert "典镇山河" in rendered
    for forbidden in (
        "PRIVATE_RAW_HTML",
        "PRIVATE_API_KEY",
        "PRIVATE_SUBJECT_KEY",
        "private.example",
        "api_key",
        "raw_html",
    ):
        assert forbidden not in rendered


def test_prompt_rejects_unbounded_evidence_transcript_and_unpinned_subject():
    from backend.prompts.topic_discussion import build_topic_discussion_messages

    with pytest.raises(ValueError, match="evidence"):
        build_topic_discussion_messages(
            transcript=({"role": "user", "content": "想法"},),
            evidence=tuple(_snapshot(index) for index in range(1, 6)),
            subject=None,
        )
    with pytest.raises(ValueError, match="transcript"):
        build_topic_discussion_messages(
            transcript=tuple(
                {"role": "user", "content": str(index)}
                for index in range(25)
            ),
            evidence=(),
            subject=None,
        )
    with pytest.raises(ValueError, match="subject"):
        build_topic_discussion_messages(
            transcript=({"role": "user", "content": "想法"},),
            evidence=(),
            subject={"id": "candidate-1", "payload": {}},
        )
