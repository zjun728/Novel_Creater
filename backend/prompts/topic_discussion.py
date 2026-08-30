"""Bounded Topic Center discussion prompt from pinned public facts only."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from backend.domain.json_contracts import canonical_json
from backend.domain.topics import TopicMessage


MAX_TOPIC_DISCUSSION_PROMPT_BYTES = 128 * 1024
MAX_TOPIC_TRANSCRIPT_MESSAGES = 24
MAX_TOPIC_EVIDENCE = 4
MAX_TOPIC_ENTRIES_PER_SNAPSHOT = 20
MAX_TOPIC_METRICS_PER_ENTRY = 8


def _text(value: object, limit: int) -> str:
    return str(value)[:limit]


def _entry(value: Mapping) -> dict:
    metrics = value.get("public_metrics")
    if not isinstance(metrics, Mapping):
        metrics = {}
    return {
        "rank": int(value["rank"]),
        "title": _text(value["title"], 300),
        "author": _text(value["author"], 200),
        "category": _text(value["category"], 160),
        "publicMetrics": {
            _text(key, 64): (
                _text(item, 100) if isinstance(item, str) else item
            )
            for key, item in sorted(metrics.items(), key=lambda pair: str(pair[0]))[
                :MAX_TOPIC_METRICS_PER_ENTRY
            ]
        },
    }


def _snapshot(value: Mapping) -> dict:
    entries = value.get("entries")
    if not isinstance(entries, (tuple, list)):
        entries = ()
    return {
        "id": value["id"],
        "sourceId": value["source_id"],
        "contentHash": value["content_hash"],
        "capturedAt": int(value["captured_at"]),
        "platform": _text(value["platform"], 120),
        "rankingName": _text(value["ranking_name"], 160),
        "category": _text(value["category"], 160),
        "entries": [
            _entry(item)
            for item in entries[:MAX_TOPIC_ENTRIES_PER_SNAPSHOT]
            if isinstance(item, Mapping)
        ],
    }


def _subject(value: Mapping | None) -> dict | None:
    if value is None:
        return None
    required = {"kind", "id", "version", "content_hash", "payload"}
    if (
        not isinstance(value, Mapping)
        or not required <= set(value)
        or value.get("kind") not in {"direction", "candidate"}
        or not isinstance(value.get("id"), str)
        or not isinstance(value.get("version"), int)
        or value["version"] <= 0
        or not isinstance(value.get("content_hash"), str)
        or len(value["content_hash"]) != 64
        or not isinstance(value.get("payload"), Mapping)
    ):
        raise ValueError("topic subject is invalid")
    return {
        "kind": value["kind"],
        "id": value["id"],
        "version": value["version"],
        "contentHash": value["content_hash"],
        "payload": dict(value["payload"]),
    }


def build_topic_discussion_messages(
    *,
    transcript: Sequence[Mapping[str, object]],
    evidence: Sequence[Mapping],
    subject: Mapping | None,
) -> tuple[dict[str, str], ...]:
    if not 1 <= len(transcript) <= MAX_TOPIC_TRANSCRIPT_MESSAGES:
        raise ValueError("topic transcript must be bounded")
    if len(evidence) > MAX_TOPIC_EVIDENCE:
        raise ValueError("topic evidence must be bounded")
    evidence_ids = tuple(item.get("id") for item in evidence)
    if any(not isinstance(item, str) or not item for item in evidence_ids):
        raise ValueError("topic evidence identity is invalid")
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("topic evidence IDs must be unique")

    frozen_transcript = tuple(
        TopicMessage.model_validate(item, strict=True) for item in transcript
    )
    context = {
        "marketEvidence": [_snapshot(item) for item in evidence],
        "pinnedSubject": _subject(subject),
    }
    instruction = {
        "task": "与作者讨论长篇小说选题，并只返回严格 JSON。",
        "rules": [
            "市场证据不是必填项；没有证据时只讨论作者明确提供的想法。",
            "市场判断只能依据已提供的冻结公开快照，不得编造榜单或作品事实。",
            "建议只是讨论输出，不能声称已经保存方向、候选种子或项目。",
            "避免照抄来源文本，不输出链接、Provider 配置或任何密钥。",
            "只返回请求的 JSON 对象，不添加 Markdown 包装。",
        ],
        "outputSchema": {
            "reply": "面向作者的讨论回复",
            "directionSuggestions": "零到四个完整方向对象",
            "candidateSuggestions": "零到四个完整候选种子对象",
        },
    }
    messages = [
        {"role": "system", "content": canonical_json(instruction)},
        {"role": "user", "content": canonical_json(context)},
    ]
    messages.extend(
        {"role": item.role, "content": item.content}
        for item in frozen_transcript
    )
    rendered = json.dumps(
        messages,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(rendered.encode("utf-8")) > MAX_TOPIC_DISCUSSION_PROMPT_BYTES:
        raise ValueError("topic prompt exceeds bounded size")
    return tuple(messages)
