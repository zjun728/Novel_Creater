"""Bounded allowlisted prompt for asset and corpus ranking."""

from __future__ import annotations

import json

from backend.domain.json_contracts import canonical_json


MAX_ASSET_RECOMMENDATION_PROMPT_BYTES = 128 * 1024
_SEED_FIELDS = (
    "title", "genre", "logline", "protagonist", "desire",
    "coreConflict", "worldPressure", "openingHook", "differentiation",
)
_ENGINE_FIELDS = (
    "name", "storyPromise", "protagonistDesire", "sustainedPressure",
    "growthDirection", "conflictLoop", "ensembleRoles",
    "advantageAndCost", "satisfactionSources", "longFormVariation",
    "endingAnchor", "risks", "differentiation",
)


def _text(value: object, limit: int) -> str:
    return str(value or "")[:limit]


def _bounded_value(value: object):
    if isinstance(value, str):
        return _text(value, 500)
    if isinstance(value, dict):
        return {
            _text(key, 64): _bounded_value(item)
            for key, item in tuple(value.items())[:20]
            if isinstance(key, str)
        }
    if isinstance(value, (list, tuple)):
        return [_bounded_value(item) for item in value[:20]]
    return value


def _asset(value) -> dict:
    return {
        "assetRevisionId": value.asset_revision_id,
        "assetType": value.asset_type,
        "stableKey": value.stable_key,
        "revision": value.revision,
        "contentHash": value.content_hash,
        "label": value.label,
        "category": value.category,
        "facts": value.facts,
    }


def _selected_style(value) -> dict:
    result = _asset(value)
    role = getattr(value, "role", None)
    if role is not None:
        result["role"] = role
    return result


def _corpus(value) -> dict:
    return {
        "sourceId": value.source_id,
        "sourceRevision": value.source_revision,
        "sourceHash": value.source_hash,
        "chapterId": value.chapter_id,
        "fragmentId": value.fragment_id,
        "fragmentHash": value.fragment_hash,
        "windowStart": value.window_start,
        "windowEnd": value.window_end,
        "excerpt": value.excerpt,
    }


def build_asset_recommendation_messages(
    *,
    selection: dict,
    engine: dict,
    selected_styles: tuple,
    asset_candidates: tuple,
    corpus_candidates: tuple,
) -> tuple[dict[str, str], ...]:
    evidence = {
        "selection": {
            "selectionRevision": selection["selectionRevision"],
            "seedRevisionId": selection["seedRevisionId"],
            "seedHash": selection["seedHash"],
            "seed": {
                key: _text(selection.get("seed", {}).get(key), 800)
                for key in _SEED_FIELDS
                if key in selection.get("seed", {})
            },
        },
        "engine": {
            "id": engine["id"],
            "hash": engine["hash"],
            "payload": {
                key: _bounded_value(engine.get("payload", {}).get(key))
                for key in _ENGINE_FIELDS
                if key in engine.get("payload", {})
            },
        },
        "selectedStyles": [_selected_style(item) for item in selected_styles],
        "assetCandidates": [_asset(item) for item in asset_candidates],
        "corpusCandidates": [_corpus(item) for item in corpus_candidates],
    }
    instruction = {
        "task": "Rank only the supplied eligible asset and corpus candidates.",
        "rules": [
            "Return one JSON object and no other text.",
            "Never select or apply anything; recommendations remain optional.",
            "Use only candidate assetRevisionId and fragmentId values.",
            "Do not invent candidates, quote long excerpts, or emit configuration.",
            "Return any number of recommendations, including zero; never pad a count.",
        ],
        "outputSchema": {
            "assetRecommendations": [{
                "assetRevisionId": "candidate ID",
                "reason": "short reason",
                "confidence": "number from 0 to 1",
            }],
            "corpusRecommendations": [{
                "fragmentId": "candidate ID",
                "rangeStart": "exact chapter character start within candidate window",
                "rangeEnd": "exact chapter character end within candidate window",
                "use": "short suggested use",
                "reason": "short reason",
                "confidence": "number from 0 to 1",
            }],
        },
    }
    messages = (
        {"role": "system", "content": canonical_json(instruction)},
        {"role": "user", "content": canonical_json(evidence)},
    )
    rendered = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    if len(rendered.encode("utf-8")) > MAX_ASSET_RECOMMENDATION_PROMPT_BYTES:
        raise ValueError("asset recommendation prompt exceeds bounded size")
    return messages


__all__ = (
    "MAX_ASSET_RECOMMENDATION_PROMPT_BYTES",
    "build_asset_recommendation_messages",
)
