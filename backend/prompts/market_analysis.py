"""Bounded prompt construction from normalized immutable snapshots only."""

from __future__ import annotations

import json

from backend.domain.json_contracts import canonical_json
from backend.domain.market_analysis import MAX_ANALYSIS_SNAPSHOTS


MAX_MARKET_ANALYSIS_PROMPT_BYTES = 128 * 1024
MAX_PROMPT_ENTRIES_PER_SNAPSHOT = 20
MAX_PROMPT_METRICS_PER_ENTRY = 8


def _bounded_text(value: object, limit: int) -> str:
    text = str(value)
    return text[:limit]


def _project_entry(entry: dict) -> dict:
    metrics = entry.get("public_metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    bounded_metrics = {}
    for key in sorted(metrics)[:MAX_PROMPT_METRICS_PER_ENTRY]:
        item = metrics[key]
        bounded_metrics[_bounded_text(key, 64)] = (
            _bounded_text(item, 100) if isinstance(item, str) else item
        )
    return {
        "rank": int(entry["rank"]),
        "title": _bounded_text(entry["title"], 300),
        "author": _bounded_text(entry["author"], 200),
        "category": _bounded_text(entry["category"], 160),
        "publicMetrics": bounded_metrics,
    }


def _project_snapshot(snapshot: dict) -> dict:
    return {
        "id": snapshot["id"],
        "contentHash": snapshot["content_hash"],
        "manifestHash": snapshot["manifest_hash"],
        "capturedAt": int(snapshot["captured_at"]),
        "platform": _bounded_text(snapshot["platform"], 120),
        "rankingName": _bounded_text(snapshot["ranking_name"], 160),
        "category": _bounded_text(snapshot["category"], 160),
        "entries": [
            _project_entry(entry)
            for entry in tuple(snapshot["entries"])[
                :MAX_PROMPT_ENTRIES_PER_SNAPSHOT
            ]
        ],
    }


def build_market_analysis_messages(
    snapshots: tuple[dict, ...],
) -> tuple[dict[str, str], ...]:
    if not 1 <= len(snapshots) <= MAX_ANALYSIS_SNAPSHOTS:
        raise ValueError("market analysis snapshots must be bounded")
    ids = tuple(snapshot.get("id") for snapshot in snapshots)
    if any(not isinstance(item, str) or not item for item in ids):
        raise ValueError("snapshot identity is invalid")
    if len(ids) != len(set(ids)):
        raise ValueError("snapshot IDs must be unique")
    facts = {"snapshots": [_project_snapshot(snapshot) for snapshot in snapshots]}
    instruction = {
        "task": "Analyze only the normalized public ranking facts below.",
        "rules": [
            "Do not invent rankings, books, metrics, causes, or trends.",
            "Every statement must cite one or more supplied snapshot IDs.",
            "Mark predictions and opportunities with inference=true.",
            "Return exactly the requested JSON object and no prose wrapper.",
        ],
        "outputSchema": {
            "currentHeat": "statement[]",
            "growthDirections": "statement[]",
            "crowding": "statement[]",
            "opportunities": "statement[]",
            "uncertainties": "statement[]",
            "sourceCoverage": {
                "snapshotIds": "all supplied IDs in order",
                "summary": "bounded text",
            },
            "statement": {
                "text": "bounded text",
                "snapshotIds": "one or more supplied IDs",
                "inference": "boolean",
            },
        },
    }
    messages = (
        {
            "role": "system",
            "content": canonical_json(instruction),
        },
        {
            "role": "user",
            "content": canonical_json(facts),
        },
    )
    rendered = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    if len(rendered.encode("utf-8")) > MAX_MARKET_ANALYSIS_PROMPT_BYTES:
        raise ValueError("market analysis prompt exceeds bounded size")
    return messages
