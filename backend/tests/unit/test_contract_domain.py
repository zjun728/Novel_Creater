from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.domain.contracts import (
    CONTRACT_TEXT_MAX_LENGTH,
    STYLE_CONTRACT_TEXT_MAX_LENGTH,
    CreationContractPayload,
    StyleContractPayload,
)
from backend.domain.seeds import SeedPayload
from backend.domain.story_engines import StoryEngineOption


EXPECTED_COLLECTION_MAX_ITEMS = 20


def seed() -> SeedPayload:
    return SeedPayload(
        title="典镇山河",
        genre="东方奇幻",
        logline="少年以县志镇压黑潮。",
        protagonist="沈码",
        desire="让被抹去的乡民重获姓名。",
        coreConflict="修史会同时唤醒镇物。",
        worldPressure="黑潮上涨，王朝封存旧志。",
        openingHook="县志预写了新县令的死期。",
        differentiation="以地方志书写为力量体系。",
    )


def engine() -> StoryEngineOption:
    return StoryEngineOption(
        name="县志镇潮",
        storyPromise="以修复地方志持续揭开被抹去的历史。",
        protagonistDesire="让无名乡民重新被世界记住。",
        sustainedPressure="黑潮上涨与朝廷封禁同时逼近。",
        growthDirection="从独自求真成长为承担共同记忆的人。",
        conflictLoop="寻得残页、重写旧事、唤醒镇物、承担代价。",
        ensembleRoles=({"role": "新县令", "purpose": "制造秩序压力。"},),
        advantageAndCost="修史可号令镇物，但会失去私人记忆。",
        satisfactionSources=("旧案翻转",),
        longFormVariation=("县、州、王朝三层旧志扩大冲突。",),
        endingAnchor="主角把自己的名字写入末页封住黑潮。",
        risks=("旧案结构重复",),
        differentiation="地方志修复是有代价的力量系统。",
    )


def creation_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "schemaVersion": "creation-contract-v1",
        "channelProfileKey": "web-fiction",
        "genreProfileKey": "eastern-fantasy",
        "qualityCharterVersion": "writer-core-quality-v1",
        "selectedSeed": seed(),
        "selectedEngine": engine(),
        "totalWordRange": (800_000, 1_200_000),
        "chapterCapacityPolicy": "每章推进一个不可逆选择",
        "modelBindingRevision": 1,
    }
    values.update(overrides)
    return values


def style_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "schemaVersion": "style-contract-v1",
        "readingExperience": "克制现实主义",
        "narrativeDistance": "近距离第三人称",
        "sentenceParagraphRhythm": "行动段短促，反思段舒展",
        "dictionDensity": "低修辞密度",
        "dialogueAndSubtext": "对白简短，冲突藏在回避中",
        "characterVoices": ("主角克制", "县令锋利"),
        "emotionAndInteriority": "以动作和选择承载情绪",
        "actionExplanationEnvironment": "先动作，后解释，环境参与阻碍",
        "primaryRules": ("克制现实主义", "避免空泛抒情"),
        "secondaryFlavor": None,
        "risks": ("节奏可能过冷",),
    }
    values.update(overrides)
    return values


def test_creation_contract_has_exact_approved_fields_and_quality_charter():
    payload = CreationContractPayload(**creation_values())

    assert tuple(type(payload).model_fields) == (
        "schemaVersion",
        "channelProfileKey",
        "genreProfileKey",
        "qualityCharterVersion",
        "selectedSeed",
        "selectedEngine",
        "totalWordRange",
        "chapterCapacityPolicy",
        "modelBindingRevision",
    )
    assert payload.qualityCharterVersion == "writer-core-quality-v1"
    assert "rubric" not in payload.model_dump()
    assert "checklist" not in payload.model_dump()

    with pytest.raises(ValidationError):
        CreationContractPayload(**creation_values(rubric=("完整",)))
    with pytest.raises(ValidationError):
        CreationContractPayload(**creation_values(checklist=("无 AI 味",)))


def test_creation_contract_rejects_unknown_fields_and_is_frozen():
    with pytest.raises(ValidationError):
        CreationContractPayload(**creation_values(legacyField="legacy"))

    payload = CreationContractPayload(**creation_values())
    with pytest.raises(ValidationError):
        payload.qualityCharterVersion = "v2"


def test_creation_contract_validates_word_range_and_binding_revision():
    with pytest.raises(ValidationError):
        CreationContractPayload(**creation_values(totalWordRange=(1_200_000, 800_000)))
    with pytest.raises(ValidationError):
        CreationContractPayload(**creation_values(totalWordRange=[800_000, 1_200_000]))
    with pytest.raises(ValidationError):
        CreationContractPayload(**creation_values(modelBindingRevision=0))


@pytest.mark.parametrize(
    "field_name",
    ("channelProfileKey", "genreProfileKey", "qualityCharterVersion"),
)
def test_creation_contract_profile_and_version_keys_are_bounded_to_schema(field_name):
    with pytest.raises(ValidationError):
        CreationContractPayload(**creation_values(**{field_name: "x" * 121}))


def test_style_contract_has_exact_approved_fields_and_requires_primary_style():
    payload = StyleContractPayload(**style_values())

    assert tuple(type(payload).model_fields) == (
        "schemaVersion",
        "readingExperience",
        "narrativeDistance",
        "sentenceParagraphRhythm",
        "dictionDensity",
        "dialogueAndSubtext",
        "characterVoices",
        "emotionAndInteriority",
        "actionExplanationEnvironment",
        "primaryRules",
        "secondaryFlavor",
        "risks",
    )
    with pytest.raises(ValidationError):
        StyleContractPayload(**style_values(primaryRules=()))
    values = style_values()
    del values["primaryRules"]
    with pytest.raises(ValidationError):
        StyleContractPayload(**values)


def test_style_contract_allows_zero_or_one_distinct_secondary_flavor():
    assert StyleContractPayload(**style_values()).secondaryFlavor is None
    assert (
        StyleContractPayload(
            **style_values(secondaryFlavor="章回体悬念")
        ).secondaryFlavor
        == "章回体悬念"
    )

    with pytest.raises(ValidationError, match="different"):
        StyleContractPayload(**style_values(secondaryFlavor="克制现实主义"))
    with pytest.raises(ValidationError):
        StyleContractPayload(**style_values(secondaryFlavor=("章回体", "冷幽默")))


def test_style_contract_rejects_unknown_fields_and_is_frozen():
    with pytest.raises(ValidationError):
        StyleContractPayload(**style_values(likes=("克制",)))

    payload = StyleContractPayload(**style_values())
    with pytest.raises(ValidationError):
        payload.readingExperience = "热血"


@pytest.mark.parametrize("field_name", ("characterVoices", "primaryRules", "risks"))
def test_style_contract_collections_are_non_empty_strict_tuples(field_name: str):
    with pytest.raises(ValidationError):
        StyleContractPayload(**style_values(**{field_name: ()}))
    with pytest.raises(ValidationError):
        StyleContractPayload(**style_values(**{field_name: ["规则"]}))


@pytest.mark.parametrize("field_name", ("characterVoices", "primaryRules", "risks"))
@pytest.mark.parametrize(
    "invalid_item",
    ("", " \t\n", "x" * (STYLE_CONTRACT_TEXT_MAX_LENGTH + 1), 1),
)
def test_style_contract_collection_items_are_bounded_and_strict(
    field_name: str,
    invalid_item: object,
):
    with pytest.raises(ValidationError):
        StyleContractPayload(**style_values(**{field_name: (invalid_item,)}))


@pytest.mark.parametrize("field_name", ("characterVoices", "primaryRules", "risks"))
def test_style_contract_collections_have_an_explicit_item_count_limit(
    field_name: str,
):
    assert len(
        StyleContractPayload(
            **style_values(
                **{field_name: ("规则",) * EXPECTED_COLLECTION_MAX_ITEMS}
            )
        ).model_dump()[field_name]
    ) == EXPECTED_COLLECTION_MAX_ITEMS

    with pytest.raises(ValidationError):
        StyleContractPayload(
            **style_values(
                **{
                    field_name: ("规则",)
                    * (EXPECTED_COLLECTION_MAX_ITEMS + 1)
                }
            )
        )


def test_style_contract_text_supports_m2c_prompt_and_composed_field_lengths():
    prompt_text = "风" * 4_000
    composed_text = "合" * STYLE_CONTRACT_TEXT_MAX_LENGTH

    payload = StyleContractPayload(**style_values(
        readingExperience=prompt_text,
        dialogueAndSubtext=composed_text,
        characterVoices=(prompt_text,),
        primaryRules=(prompt_text,),
    ))

    assert len(payload.readingExperience) == 4_000
    assert len(payload.dialogueAndSubtext) == STYLE_CONTRACT_TEXT_MAX_LENGTH
    with pytest.raises(ValidationError):
        StyleContractPayload(**style_values(
            actionExplanationEnvironment="超" * (STYLE_CONTRACT_TEXT_MAX_LENGTH + 1)
        ))


def test_creation_contract_text_remains_bounded_at_2000():
    with pytest.raises(ValidationError):
        CreationContractPayload(**creation_values(
            chapterCapacityPolicy="章" * (CONTRACT_TEXT_MAX_LENGTH + 1)
        ))
