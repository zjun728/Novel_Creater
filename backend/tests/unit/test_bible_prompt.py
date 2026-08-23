from __future__ import annotations

import json

import pytest

from backend.prompts.bible import (
    BIBLE_MAX_PROMPT_BYTES,
    build_bible_messages,
)


def _inputs(**changes):
    values = {
        "seed": {
            "title": "典镇山河",
            "genre": "历史穿越",
            "logline": "守住失散的典籍",
            "protagonist": "沈砚",
            "desire": "让同伴活着离开",
            "coreConflict": "知识会招来争夺",
            "worldPressure": "战乱逼近",
            "openingHook": "残页显字",
            "differentiation": "每次使用知识都有代价",
        },
        "creation_contract": {
            "schemaVersion": "creation-contract-v1",
            "storyPromise": "知识解决现实难题，也制造新的关系债。",
            "protagonistDrive": "保护同伴并让知识可以传承。",
        },
        "style_contract": {
            "schemaVersion": "style-contract-v1",
            "readingExperience": "人物先做选择，规则从后果中显现。",
            "narrativeDistance": "贴近人物有限视角。",
        },
        "experience_cards": (
            {
                "id": "experience-1",
                "revision": 1,
                "contentHash": "3" * 64,
                "payload": {
                    "schemaVersion": "experience-card-v1",
                    "category": "long_arc_continuity",
                    "method": "每次兑现都留下新的长期代价。",
                },
            },
        ),
        "corpus_fragments": (
            {
                "sourceId": "corpus-1",
                "sourceRevisionId": "corpus-revision-1",
                "fragmentId": "fragment-1",
                "fragmentHash": "4" * 64,
                "referenceUse": "structure",
                "text": "困境先迫使人物结盟，结盟随后改变资源分配。",
            },
        ),
        "author_instructions": "强调群像分工与长期关系代价。",
    }
    values.update(changes)
    return values


def test_prompt_is_one_bounded_json_request_for_future_design_only():
    first = build_bible_messages(**_inputs())
    second = build_bible_messages(**_inputs())

    assert first == second
    assert len(first) == 2
    assert tuple(message["role"] for message in first) == ("system", "user")
    assert len(
        json.dumps(
            first,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ) <= BIBLE_MAX_PROMPT_BYTES

    system = json.loads(first[0]["content"])
    evidence = json.loads(first[1]["content"])
    rendered = json.dumps(first, ensure_ascii=False)
    assert system["task"] == "Generate one complete creation Bible"
    assert "未来设计" in rendered
    assert "Canon" in rendered
    assert "不得虚构已经发生" in rendered
    assert evidence["confirmedSeed"]["title"] == "典镇山河"
    assert evidence["creationContract"]["storyPromise"].startswith("知识")
    assert evidence["styleContract"]["readingExperience"].startswith("人物")
    assert evidence["experienceCards"][0]["payload"]["method"].startswith("每次")
    assert evidence["corpusFragments"][0]["text"].startswith("困境")
    assert evidence["authorInstructions"] == "强调群像分工与长期关系代价。"
    assert any("整个 JSON 不超过 5000 个汉字" in rule for rule in system["rules"])
    scalar_schema = evidence["outputSchema"]["properties"]["premiseAndPromise"]
    assert scalar_schema == {"type": "string", "minLength": 120, "maxLength": 300}
    list_schema = evidence["outputSchema"]["properties"]["worldRules"]
    assert list_schema["type"] == "array"
    assert list_schema["minItems"] == 3
    assert list_schema["maxItems"] == 6
    assert list_schema["items"]["required"] == ["id", "text"]
    assert list_schema["items"]["properties"]["text"] == {
        "type": "string",
        "minLength": 40,
        "maxLength": 160,
    }
    assert set(evidence["outputSchema"]["required"]) == {
        "premiseAndPromise",
        "worldRules",
        "powerOrProgressionSystem",
        "protagonist",
        "coreCast",
        "factions",
        "longTermConflicts",
        "relationshipDynamics",
        "toneAndNarrativeBoundaries",
        "continuityGuardrails",
        "openDesignQuestions",
    }


def test_prompt_fails_closed_when_semantic_inputs_exceed_one_context_budget():
    with pytest.raises(ValueError, match="bounded size"):
        build_bible_messages(
            **_inputs(
                author_instructions="写" * (BIBLE_MAX_PROMPT_BYTES + 1),
            )
        )
