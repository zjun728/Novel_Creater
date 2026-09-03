from __future__ import annotations

import json

import pytest

from backend.prompts.bible import (
    BIBLE_MAX_PROMPT_BYTES,
    BIBLE_PROPOSAL_SCOPE_FIELDS,
    build_bible_messages,
)
from backend.domain.bibles import BibleDesignItem, BiblePayload


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
    assert scalar_schema == {"type": "string", "minLength": 1, "maxLength": 4_000}
    list_schema = evidence["outputSchema"]["properties"]["worldRules"]
    assert list_schema["type"] == "array"
    assert list_schema["minItems"] == 1
    assert list_schema["maxItems"] == 20
    assert list_schema["items"]["required"] == ["id", "text"]
    assert list_schema["items"]["properties"]["text"] == {
        "type": "string",
        "minLength": 1,
        "maxLength": 4_000,
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


def test_whole_proposal_needs_no_saved_bible_and_requests_one_complete_payload():
    messages = build_bible_messages(
        **_inputs(proposal_scope="whole", current_bible=None)
    )

    system = json.loads(messages[0]["content"])
    evidence = json.loads(messages[1]["content"])
    assert system["task"] == "Propose one complete creation Bible"
    assert evidence["proposalScope"] == "whole"
    assert "currentBible" not in evidence
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


def test_section_proposal_carries_complete_saved_bible_and_retains_non_targets():
    current_bible = {
        "premiseAndPromise": "已保存的前提承诺。",
        "worldRules": [{"id": "world", "text": "已保存的世界规则。"}],
        "powerOrProgressionSystem": "已保存的成长体系。",
        "protagonist": "已保存的主角设计。",
        "coreCast": [{"id": "cast", "text": "已保存的群像设计。"}],
        "factions": [{"id": "faction", "text": "已保存的势力设计。"}],
        "longTermConflicts": [{"id": "conflict", "text": "已保存的冲突设计。"}],
        "relationshipDynamics": [{"id": "relationship", "text": "已保存的关系设计。"}],
        "toneAndNarrativeBoundaries": "已保存的叙事边界。",
        "continuityGuardrails": [{"id": "guardrail", "text": "已保存的连续性护栏。"}],
        "openDesignQuestions": [{"id": "question", "text": "已保存的开放问题。"}],
    }
    messages = build_bible_messages(
        **_inputs(
            proposal_scope="core_characters",
            current_bible=current_bible,
        )
    )

    system = json.loads(messages[0]["content"])
    evidence = json.loads(messages[1]["content"])
    assert evidence["proposalScope"] == "core_characters"
    assert evidence["currentBible"] == current_bible
    assert system["targetFields"] == ["protagonist", "coreCast"]
    assert any("非目标字段" in rule and "保留" in rule for rule in system["rules"])


@pytest.mark.parametrize("scope", ([], {}, None, 7, "not-a-bible-scope"))
def test_prompt_rejects_non_string_or_unknown_proposal_scopes(scope):
    with pytest.raises(ValueError, match="Bible proposal scope is invalid"):
        build_bible_messages(
            **_inputs(proposal_scope=scope, current_bible=None)
        )


def test_section_prompt_exempts_pinned_non_targets_from_authoring_guidance():
    item = BibleDesignItem(id="item", text="短")
    current = BiblePayload(
        premiseAndPromise="短",
        worldRules=(item,),
        powerOrProgressionSystem="短",
        protagonist="短",
        coreCast=(item,),
        factions=(item,),
        longTermConflicts=(item,),
        relationshipDynamics=(item,),
        toneAndNarrativeBoundaries="短",
        continuityGuardrails=(item,),
        openDesignQuestions=(item,),
    )
    messages = build_bible_messages(
        **_inputs(
            proposal_scope="world_rules",
            current_bible=current.model_dump(mode="json"),
        )
    )

    system = json.loads(messages[0]["content"])
    evidence = json.loads(messages[1]["content"])
    assert system["targetFields"] == ["worldRules"]
    assert system["nonTargetFieldsMustEqualCurrentBible"] is True
    assert evidence["currentBible"] == current.model_dump(mode="json")
    assert evidence["outputSchema"]["properties"]["premiseAndPromise"] == {
        "type": "string",
        "minLength": 1,
        "maxLength": 4_000,
    }
    assert evidence["outputSchema"]["properties"]["coreCast"]["minItems"] == 1
    assert all("每个列表 3 至 6" not in rule for rule in system["rules"])
    assert all("每个标量字段 120 至 300" not in rule for rule in system["rules"])
    assert any("仅对 targetFields" in rule for rule in system["rules"])


def test_proposal_scope_registry_is_immutable():
    with pytest.raises(TypeError):
        BIBLE_PROPOSAL_SCOPE_FIELDS["unexpected"] = ("protagonist",)
