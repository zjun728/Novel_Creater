"""Bounded seed-inspiration prompt from working chat and frozen public facts."""

from __future__ import annotations

import json

from backend.domain.json_contracts import canonical_json
from backend.domain.seeds import (
    MAX_SEED_CHAT_TURNS,
    SeedChatTurn,
)


MAX_SEED_PROMPT_BYTES = 96 * 1024
MAX_PROMPT_ENTRIES_PER_SNAPSHOT = 20
MAX_PROMPT_METRICS_PER_ENTRY = 8


def _text(value: object, limit: int) -> str:
    return str(value)[:limit]


def _entry(value: dict) -> dict:
    metrics = value.get("public_metrics")
    if not isinstance(metrics, dict):
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
            for key, item in tuple(sorted(metrics.items()))[
                :MAX_PROMPT_METRICS_PER_ENTRY
            ]
        },
    }


def _snapshot(value: dict) -> dict:
    return {
        "id": value["id"],
        "contentHash": value["content_hash"],
        "manifestHash": value["manifest_hash"],
        "capturedAt": int(value["captured_at"]),
        "platform": _text(value["platform"], 120),
        "rankingName": _text(value["ranking_name"], 160),
        "category": _text(value["category"], 160),
        "entries": [
            _entry(item)
            for item in tuple(value["entries"])[
                :MAX_PROMPT_ENTRIES_PER_SNAPSHOT
            ]
        ],
    }


def _analysis(value: dict, snapshot_ids: tuple[str, ...]) -> dict:
    document = value.get("analysis_json")
    if isinstance(document, str):
        document = json.loads(document)
    if not isinstance(document, dict):
        raise ValueError("analysis is invalid")
    coverage = document.get("sourceCoverage")
    if (
        not isinstance(coverage, dict)
        or tuple(coverage.get("snapshotIds") or ()) != snapshot_ids
    ):
        raise ValueError("analysis does not match frozen snapshots")
    return {
        "id": value["id"],
        "resultHash": value["result_hash"],
        "result": document,
    }


def build_seed_inspiration_messages(
    *,
    transcript: tuple[SeedChatTurn, ...],
    inputs: dict,
) -> tuple[dict[str, str], ...]:
    if not 1 <= len(transcript) <= MAX_SEED_CHAT_TURNS:
        raise ValueError("seed transcript must be bounded")
    snapshots = tuple(inputs.get("snapshots") or ())
    if not 1 <= len(snapshots) <= 4:
        raise ValueError("seed snapshots must be bounded")
    snapshot_ids = tuple(item.get("id") for item in snapshots)
    if (
        any(not isinstance(item, str) or not item for item in snapshot_ids)
        or len(snapshot_ids) != len(set(snapshot_ids))
    ):
        raise ValueError("frozen snapshot identities are invalid")
    evidence = {
        "snapshots": [_snapshot(item) for item in snapshots],
        "analysis": _analysis(inputs["analysis"], snapshot_ids),
        "currentTranscript": [
            turn.model_dump(mode="json") for turn in transcript
        ],
    }
    instruction = {
        "task": (
            "Continue the author's seed-inspiration conversation using only "
            "the supplied working transcript and frozen public evidence."
        ),
        "rules": [
            "Return one useful assistant turn as plain text, without a wrapper.",
            "Do not claim unsupported market facts or invent rankings.",
            "Offer concrete story conflict, character, and long-form variation.",
            "Do not output credentials, Provider configuration, URLs, or raw data.",
            "Do not present the idea as saved, selected, canonical, or final.",
        ],
    }
    messages = (
        {"role": "system", "content": canonical_json(instruction)},
        {"role": "user", "content": canonical_json(evidence)},
    )
    rendered = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    if len(rendered.encode("utf-8")) > MAX_SEED_PROMPT_BYTES:
        raise ValueError("seed prompt exceeds bounded size")
    return messages
