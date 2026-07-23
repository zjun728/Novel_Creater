from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.domain.bibles import (
    BIBLE_LIST_MAX_ITEMS,
    BIBLE_TEXT_MAX_LENGTH,
    BibleDesignItem,
    BiblePayload,
    canonical_bible_hash,
)


def bible_values(**overrides):
    values = {
        "premiseAndPromise": "主角将在陌生秩序中寻找可持续的立足方式。",
        "worldRules": (
            {"id": "world-rule-1", "text": "力量使用将付出可追踪的代价。"},
        ),
        "powerOrProgressionSystem": "成长将依靠选择、训练和有限资源逐层推进。",
        "protagonist": "主角被设计为谨慎、能承担选择后果的人。",
        "coreCast": (
            {"id": "cast-1", "text": "同伴将以独立目标参与未来冲突。"},
        ),
        "factions": (
            {"id": "faction-1", "text": "地方势力将围绕秩序与利益形成竞争。"},
        ),
        "longTermConflicts": (
            {"id": "conflict-1", "text": "长期矛盾将围绕自由与稳定逐步升级。"},
        ),
        "relationshipDynamics": (
            {"id": "relationship-1", "text": "信任将通过共同选择缓慢建立。"},
        ),
        "toneAndNarrativeBoundaries": "叙事将克制直接说教，并保留行动余波。",
        "continuityGuardrails": (
            {"id": "guardrail-1", "text": "能力提升必须保留资源与训练依据。"},
        ),
        "openDesignQuestions": (
            {"id": "question-1", "text": "后续需要决定第一阶段的关键代价。"},
        ),
    }
    values.update(overrides)
    return values


def payload(**overrides) -> BiblePayload:
    return BiblePayload(**bible_values(**overrides))


def test_payload_accepts_only_the_frozen_future_design_shape():
    value = payload()

    assert set(value.model_dump(mode="json")) == {
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
    assert value.worldRules[0] == BibleDesignItem(
        id="world-rule-1",
        text="力量使用将付出可追踪的代价。",
    )


@pytest.mark.parametrize(
    "values",
    (
        bible_values(debug=True),
        bible_values(
            worldRules=(
                {"id": "world-rule-1", "text": "规则。", "score": 99},
            )
        ),
        bible_values(premiseAndPromise="   "),
        bible_values(worldRules=()),
        bible_values(
            coreCast=(
                {"id": "cast-1", "text": "角色一。"},
                {"id": "cast-1", "text": "角色二。"},
            )
        ),
        bible_values(
            factions=tuple(
                {"id": f"faction-{index}", "text": "未来势力设计。"}
                for index in range(BIBLE_LIST_MAX_ITEMS + 1)
            )
        ),
        bible_values(
            protagonist="x" * (BIBLE_TEXT_MAX_LENGTH + 1),
        ),
    ),
)
def test_payload_rejects_unknown_blank_duplicate_and_unbounded_values(values):
    with pytest.raises(ValidationError):
        BiblePayload(**values)


@pytest.mark.parametrize(
    "fact_shape",
    (
        {"occurredEvents": ()},
        {"chapterFacts": ()},
        {"canonChanges": ()},
    ),
)
def test_payload_has_no_channel_for_claiming_events_as_occurred_facts(fact_shape):
    with pytest.raises(ValidationError):
        BiblePayload(**(bible_values() | fact_shape))


def test_author_design_text_is_not_subject_to_unreliable_tense_keyword_scoring():
    value = payload(
        protagonist="主角曾经失去故乡；这段背景将约束未来的风险选择。"
    )

    assert "曾经" in value.protagonist


def test_duplicate_item_ids_are_scoped_to_each_list_not_unrelated_categories():
    value = payload(
        worldRules=({"id": "shared-1", "text": "世界规则设计。"},),
        continuityGuardrails=(
            {"id": "shared-1", "text": "连续性护栏设计。"},
        ),
    )

    assert value.worldRules[0].id == value.continuityGuardrails[0].id


def test_hash_uses_only_canonical_validated_payload_data():
    first = payload()
    second = BiblePayload.model_validate(first.model_dump(mode="python"))

    assert canonical_bible_hash(first) == canonical_bible_hash(second)
    assert canonical_bible_hash(first) != canonical_bible_hash(
        payload(protagonist="主角将以更强硬的方式承担选择后果。")
    )
