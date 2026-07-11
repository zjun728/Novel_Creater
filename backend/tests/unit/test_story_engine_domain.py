from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.domain.story_engines import (
    STORY_ENGINE_TEXT_MAX_LENGTH,
    EnsembleRole,
    StoryEngineOption,
    validate_three_options,
)


EXPECTED_COLLECTION_MAX_ITEMS = 20


def engine_values(name: str = "县志镇潮", **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "name": name,
        "storyPromise": "以修复地方志的行动持续揭开被抹去的历史。",
        "protagonistDesire": "让无名乡民重新被世界记住。",
        "sustainedPressure": "黑潮上涨与朝廷封禁同时逼近。",
        "growthDirection": "从独自求真成长为愿意承担共同记忆的人。",
        "conflictLoop": "寻得残页、重写旧事、唤醒镇物、承担代价。",
        "ensembleRoles": (
            {"role": "新县令", "purpose": "迫使主角在真相与秩序间选择。"},
        ),
        "advantageAndCost": "修史可号令镇物，但每次都会失去一段私人记忆。",
        "satisfactionSources": ("旧案翻转", "镇物奇观"),
        "longFormVariation": ("县、州、王朝三层旧志逐步扩大冲突。",),
        "endingAnchor": "主角将自己的名字写入最后一页以封住黑潮。",
        "risks": ("单元旧案可能重复",),
        "differentiation": "把地方志修复变成有明确代价的力量系统。",
    }
    values.update(overrides)
    return values


def make_engine(name: str = "县志镇潮", **overrides: object) -> StoryEngineOption:
    return StoryEngineOption(**engine_values(name, **overrides))


def test_story_engine_models_have_exact_fields_and_reject_unknown_fields():
    option = make_engine()

    assert tuple(EnsembleRole.model_fields) == ("role", "purpose")
    assert tuple(type(option).model_fields) == (
        "name",
        "storyPromise",
        "protagonistDesire",
        "sustainedPressure",
        "growthDirection",
        "conflictLoop",
        "ensembleRoles",
        "advantageAndCost",
        "satisfactionSources",
        "longFormVariation",
        "endingAnchor",
        "risks",
        "differentiation",
    )
    with pytest.raises(ValidationError):
        StoryEngineOption(**engine_values(), legacyField="legacy")
    with pytest.raises(ValidationError):
        EnsembleRole(role="盟友", purpose="制造选择", legacyField="legacy")


def test_story_engine_strings_are_non_empty_bounded_and_strict():
    assert make_engine(name="  县志镇潮\n").name == "县志镇潮"
    assert len(make_engine(name="x" * STORY_ENGINE_TEXT_MAX_LENGTH).name) == (
        STORY_ENGINE_TEXT_MAX_LENGTH
    )

    for invalid in ("", " \t\n", "x" * (STORY_ENGINE_TEXT_MAX_LENGTH + 1), 1):
        with pytest.raises(ValidationError):
            make_engine(name=invalid)

    for invalid in ("", " \n", "x" * (STORY_ENGINE_TEXT_MAX_LENGTH + 1), 1):
        with pytest.raises(ValidationError):
            EnsembleRole(role=invalid, purpose="制造选择")


@pytest.mark.parametrize(
    "field_name",
    ("ensembleRoles", "satisfactionSources", "longFormVariation", "risks"),
)
def test_story_engine_collections_are_non_empty_strict_tuples(field_name: str):
    with pytest.raises(ValidationError):
        make_engine(**{field_name: ()})

    list_value = {
        "ensembleRoles": [{"role": "盟友", "purpose": "制造选择"}],
        "satisfactionSources": ["反转"],
        "longFormVariation": ["扩大舞台"],
        "risks": ["重复"],
    }[field_name]
    with pytest.raises(ValidationError):
        make_engine(**{field_name: list_value})


@pytest.mark.parametrize(
    "field_name",
    ("satisfactionSources", "longFormVariation", "risks"),
)
@pytest.mark.parametrize(
    "invalid_item",
    ("", " \t\n", "x" * (STORY_ENGINE_TEXT_MAX_LENGTH + 1), 1),
)
def test_story_engine_string_collection_items_are_bounded_and_strict(
    field_name: str,
    invalid_item: object,
):
    with pytest.raises(ValidationError):
        make_engine(**{field_name: (invalid_item,)})


@pytest.mark.parametrize(
    ("field_name", "item"),
    (
        ("ensembleRoles", {"role": "盟友", "purpose": "制造选择"}),
        ("satisfactionSources", "反转"),
        ("longFormVariation", "扩大舞台"),
        ("risks", "重复"),
    ),
)
def test_story_engine_collections_have_an_explicit_item_count_limit(
    field_name: str,
    item: object,
):
    assert len(
        make_engine(
            **{field_name: (item,) * EXPECTED_COLLECTION_MAX_ITEMS}
        ).model_dump()[field_name]
    ) == EXPECTED_COLLECTION_MAX_ITEMS

    with pytest.raises(ValidationError):
        make_engine(**{field_name: (item,) * (EXPECTED_COLLECTION_MAX_ITEMS + 1)})


def test_long_form_variation_requires_a_tuple_even_for_one_item():
    assert make_engine(longFormVariation=("扩大舞台",)).longFormVariation == (
        "扩大舞台",
    )

    with pytest.raises(ValidationError):
        make_engine(longFormVariation="扩大舞台")


def test_story_engine_and_nested_roles_are_frozen():
    option = make_engine()

    with pytest.raises(ValidationError):
        option.name = "新名称"
    with pytest.raises(ValidationError):
        option.ensembleRoles[0].role = "新角色"


def test_validate_three_options_accepts_three_structurally_distinct_options():
    options = (
        make_engine(),
        make_engine(
            "血脉镇物",
            storyPromise="以家族秘密推动镇物争夺。",
            conflictLoop="夺取信物、唤醒血脉、结盟背叛、支付寿命。",
            advantageAndCost="血脉越强，寿命越短。",
            endingAnchor="主角烧毁族谱终止血脉循环。",
        ),
        make_engine(
            "流亡修史",
            storyPromise="一支流亡队伍沿途修复被删去的城镇。",
            conflictLoop="抵达废城、寻找证人、公开真相、躲避追杀。",
            advantageAndCost="公开旧史能召回城魂，也会暴露队伍位置。",
            endingAnchor="所有幸存者共同口述一部无法再被焚毁的史书。",
        ),
    )

    assert validate_three_options(options) == options


@pytest.mark.parametrize("options", [(), (None,), (None, None), (None,) * 4])
def test_validate_three_options_rejects_any_count_other_than_three(options: tuple):
    with pytest.raises(ValueError, match="exactly three"):
        validate_three_options(options)


def test_validate_three_options_rejects_name_only_differences():
    options = (
        make_engine("名称一"),
        make_engine("名称二", differentiation="不同宣传语"),
        make_engine("名称三", differentiation="另一宣传语"),
    )

    with pytest.raises(ValueError, match="structurally distinct"):
        validate_three_options(options)


def test_validate_three_options_rejects_mutable_or_non_option_inputs():
    with pytest.raises(TypeError, match="tuple"):
        validate_three_options([make_engine(), make_engine(), make_engine()])

    with pytest.raises(TypeError, match="StoryEngineOption"):
        validate_three_options((make_engine(), make_engine(), object()))
