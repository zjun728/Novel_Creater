from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import traceback
import unicodedata

import pytest
from pydantic import ValidationError

from backend.domain.assets import (
    ASSET_CATEGORIES,
    AssetPackage,
    AssetPackageError,
    ExperienceCardRevision,
    StyleTemplateRevision,
    load_asset_package,
    validate_asset_package,
)
from backend.domain.json_contracts import canonical_hash


PRODUCTION_ASSET_MANIFEST = (
    Path(__file__).resolve().parents[3]
    / "backend"
    / "assets"
    / "writer-core-v1.1.0"
    / "manifest.json"
)
PRODUCTION_STYLE_KEYS = {
    "direct-propulsive",
    "light-humorous",
    "immersive-ensemble",
    "restrained-suspense",
    "high-energy-growth",
    "emotion-relationship",
    "epic-civilization-building",
    "marketplace-wit-and-life",
    "cautious-survival-accumulation",
    "austere-tragic-defiance",
}
CANDIDATE_STYLE_NAMES = {
    "cautious-survival-accumulation": "稳健求生积累型",
    "austere-tragic-defiance": "冷峻悲情逆命型",
}
CANDIDATE_CARD_SPECS = {
    "arc-block-chapter-delta": (
        "long_arc_continuity",
        "故事块跨章，每章改变一项状态",
    ),
    "arc-setup-serves-now-payoff-changes-choice": (
        "long_arc_continuity",
        "伏笔先服务当前戏，回收时改变选择",
    ),
    "arc-pressure-waves": (
        "long_arc_continuity",
        "长线压力要换来源并保留低谷",
    ),
    "arc-aftermath-new-normal": (
        "long_arc_continuity",
        "高潮后建立带代价的新常态",
    ),
    "progression-breakthrough-earned-options": (
        "progression_economy",
        "突破来自反馈、准备与旧能力组合",
    ),
    "progression-resource-loop-cost": (
        "progression_economy",
        "资源形成获取、转化、消耗、补给闭环",
    ),
    "progression-rank-changes-permission-risk": (
        "progression_economy",
        "境界与身份同时改变权限和风险",
    ),
    "progression-new-tier-new-problem": (
        "progression_economy",
        "新层级带来新类型问题",
    ),
}
TASK4_CANDIDATE_CARD_SPECS = {
    "character-antagonist-adapts-clock": (
        "character_arcs",
        "反派按自己的时钟行动并在受挫后改策",
    ),
    "character-supporting-arc-changes-main": (
        "character_arcs",
        "配角的阶段选择反过来改变主线",
    ),
    "character-growth-proved-under-old-trigger": (
        "character_arcs",
        "成长要在旧诱因重现时由新选择证明",
    ),
    "character-antagonist-offers-valid-alternative": (
        "character_arcs",
        "反派提出有诱惑力的有效替代方案",
    ),
    "action-competing-objectives": (
        "action_conflict",
        "胜负之外同时争夺另一项目标",
    ),
    "action-exchange-changes-state": (
        "action_conflict",
        "每轮交锋改变位置、信息或资源",
    ),
    "action-finish-established-combination": (
        "action_conflict",
        "终结手段来自前文建立的能力组合",
    ),
    "action-injury-cost-changes-tactics": (
        "action_conflict",
        "伤势与损耗持续改变后续战术",
    ),
}
CANDIDATE_CARD_PAYLOAD_FIELDS = {
    "schemaVersion",
    "category",
    "method",
    "applicability",
    "non_applicability",
    "risks",
    "original_micro_demo",
}
STYLE_PROMPT_PAYLOAD_FIELDS = {
    "schemaVersion",
    "reading_experience",
    "applicability",
    "non_applicability",
    "standard_scene_example",
    "complete_application_example",
    "narrative_distance",
    "rhythm",
    "diction_density",
    "dialogue",
    "subtext",
    "character_voices",
    "emotion",
    "interiority",
    "action",
    "explanation",
    "environment",
    "body_response",
    "preferred_techniques",
    "risks",
    "original_anchor",
}
EXPECTED_CATEGORY_COUNTS = {
    "plot_organization": 6,
    "ensemble": 6,
    "dialogue": 6,
    "emotion": 6,
    "interiority": 6,
    "information_release": 6,
    "pacing": 6,
    "suspense": 6,
    "long_arc_continuity": 4,
    "progression_economy": 4,
    "character_arcs": 4,
    "action_conflict": 4,
}
AUTHOR_APPROVAL_TIME = "2026-07-12T14:38:09+08:00"


def test_production_approval_does_not_change_reviewed_content():
    raw_styles = json.loads(
        (PRODUCTION_ASSET_MANIFEST.parent / "style_templates.json").read_text(
            encoding="utf-8"
        )
    )
    raw_cards = json.loads(
        (PRODUCTION_ASSET_MANIFEST.parent / "experience_cards.json").read_text(
            encoding="utf-8"
        )
    )
    def without_provenance(rows):
        return [
            {key: value for key, value in row.items() if key != "provenance"}
            for row in rows
        ]

    baseline = {
        "styles": without_provenance(raw_styles[:8]),
        "experience_cards": without_provenance(raw_cards[:48]),
    }

    # Double-review round 2 explicitly approved rewrites in four legacy styles,
    # six legacy cards, and the required style boundary field. Record the new
    # complete legacy prefix instead of silently retaining the pre-review hash.
    assert canonical_hash(baseline) == (
        "57936d057000d7662b63623db96d34ab74b15d05475677124d8008f42822557b"
    )
    assert canonical_hash(
        {
            "styles": without_provenance(raw_styles),
            "experience_cards": without_provenance(raw_cards),
        }
    ) == "589023a23c5b9d8a3f2702dcc9a97898d8a7880d9a39804c8705d3e7d4da1eb7"

    changed = deepcopy(baseline)
    changed["styles"][0]["name"] = "Changed only in the in-memory regression probe"
    assert canonical_hash(changed) != canonical_hash(baseline)


def test_double_review_rewrites_do_not_spread_to_unauthorized_assets():
    raw_styles = json.loads(
        (PRODUCTION_ASSET_MANIFEST.parent / "style_templates.json").read_text(
            encoding="utf-8"
        )
    )
    raw_cards = json.loads(
        (PRODUCTION_ASSET_MANIFEST.parent / "experience_cards.json").read_text(
            encoding="utf-8"
        )
    )
    authorized_style_keys = {
        "direct-propulsive",
        "epic-civilization-building",
        "cautious-survival-accumulation",
        "austere-tragic-defiance",
    }
    authorized_card_keys = {
        "emotion-relief-has-aftershock",
        "interiority-thought-leads-choice",
        "info-rule-small-failure",
        "pacing-cut-on-consequence",
        "pacing-fast-with-clear-landmarks",
        "suspense-answer-opens-choice",
        "arc-setup-serves-now-payoff-changes-choice",
    }

    untouched_style_content = []
    for raw_row in raw_styles:
        if raw_row["stable_key"] in authorized_style_keys:
            continue
        row = deepcopy(raw_row)
        row["payload"].pop("non_applicability")
        row["content_hash"] = canonical_hash(row["payload"])
        row.pop("provenance")
        untouched_style_content.append(row)
    # A1 adds the new required boundary field to all styles. Removing only that
    # field and rebuilding each content hash must recover the six untouched
    # pre-review style objects exactly.
    assert canonical_hash({"styles": untouched_style_content}) == (
        "30a069d7b9439e96572f5ee7755751cd41df8a0102f5fcf1c57055f393c8d10f"
    )

    def without_provenance(rows):
        return [
            {key: value for key, value in row.items() if key != "provenance"}
            for row in rows
            if row["stable_key"] not in authorized_card_keys
        ]

    assert canonical_hash(
        {"experience_cards": without_provenance(raw_cards)}
    ) == "35a3def37fd5ebfa8580e12a7c36e63f54f361686cf05918dd66117631e7124a"
    assert canonical_hash(
        {"experience_cards": without_provenance(raw_cards[:48])}
    ) == "1b703ebdb7648100dd761af067f1d0d9d5932edc71cdb124a7b4c89fac1d2f76"


def test_double_review_style_boundaries_and_shared_standard_scene_are_explicit():
    raw_styles = json.loads(
        (PRODUCTION_ASSET_MANIFEST.parent / "style_templates.json").read_text(
            encoding="utf-8"
        )
    )
    styles = {row["stable_key"]: row["payload"] for row in raw_styles}

    assert all(1 <= len(payload["non_applicability"]) <= 3 for payload in styles.values())

    cautious = styles["cautious-survival-accumulation"]
    austere = styles["austere-tragic-defiance"]
    for payload in (cautious, austere):
        assert all(
            anchor in payload["standard_scene_example"]
            for anchor in ("许川", "灰垣城", "铜环", "水闸")
        )
        assert "不要求每场或每章" in payload["rhythm"]
    assert "退路" in cautious["standard_scene_example"]
    for editorial_label in ("验证到这里已经够用", "能验证的有限收益"):
        assert editorial_label not in cautious["standard_scene_example"]
    assert all(
        concrete_beat in cautious["standard_scene_example"]
        for concrete_beat in ("水线", "半阶", "裂纹", "旧匠巷")
    )
    assert "冷压" not in austere["standard_scene_example"]
    assert all(
        pressure_beat in austere["standard_scene_example"]
        for pressure_beat in ("压低声音", "公簿", "封闸令", "日落", "无籍者")
    )
    assert "仍" in austere["standard_scene_example"]
    assert "可跨章" in austere["rhythm"]

    direct = styles["direct-propulsive"]
    assert "每句对白都带筹码" not in direct["dialogue"]
    assert "主角说方案" not in direct["character_voices"]
    assert all(
        allowance in direct["dialogue"]
        for allowance in ("闲话", "误解", "未奏效")
    )
    assert all(
        distinction in direct["character_voices"]
        for distinction in ("欲望", "关系", "经历")
    )

    epic_complete = styles["epic-civilization-building"][
        "complete_application_example"
    ]
    assert all(
        scene_detail in epic_complete
        for scene_detail in ("霜", "试行", "失败", "改", "炭", "口粮")
    )
    assert "这不是主角一句话建成的盛世" not in epic_complete


def test_double_review_card_methods_preserve_conditional_storytelling():
    raw_cards = json.loads(
        (PRODUCTION_ASSET_MANIFEST.parent / "experience_cards.json").read_text(
            encoding="utf-8"
        )
    )
    cards = {row["stable_key"]: row["payload"] for row in raw_cards}
    titles = {row["stable_key"]: row["title"] for row in raw_cards}
    assert {
        "emotion-relief-has-aftershock": "松口气后让消耗留下后效",
        "info-rule-small-failure": "规则先从局部后果显形",
        "pacing-fast-with-clear-landmarks": "快场景保留清晰空间锚点",
        "suspense-answer-opens-choice": "揭晓后把真相转成选择",
    }.items() <= titles.items()

    relief = cards["emotion-relief-has-aftershock"]
    assert all(word in relief["method"] for word in ("具体消耗", "注意力", "行为", "需求", "无明显反应"))
    assert "让读者感到压力真实经过身体" not in relief["method"]

    thought = cards["interiority-thought-leads-choice"]
    assert all(word in thought["method"] for word in ("目标导向", "至少", "行动"))
    assert all(word in " ".join(thought["non_applicability"]) for word in ("联想", "情绪", "驻留", "即时产出"))
    assert "每段思考至少" not in thought["method"]

    rule = cards["info-rule-small-failure"]
    assert all(word in rule["method"] for word in ("旁观", "试探", "误解", "他人后果", "当前所需"))
    assert "每条规则" in " ".join(rule["non_applicability"])
    assert all(
        observed_beat in rule["original_micro_demo"]
        for observed_beat in ("前面", "守门人", "标记")
    )
    assert all(
        tutorial_beat not in rule["original_micro_demo"]
        for tutorial_beat in (
            "孟秋照做",
            "它认持票者的掌温",
            "摘下手套，用掌心按住三息，别松",
        )
    )

    cut = cards["pacing-cut-on-consequence"]
    assert all(word in cut["method"] for word in ("可预料", "移动", "重复操作"))
    assert all(word in " ".join(cut["non_applicability"]) for word in ("首次突破", "核心交锋", "阶段爽点"))
    assert "夜闯税仓" in cut["original_micro_demo"]
    assert "内库印" in cut["original_micro_demo"]
    assert "天亮时" in cut["original_micro_demo"]
    assert all(
        editorial_aside not in cut["original_micro_demo"]
        for editorial_aside in ("没有跳过关键行动", "省去的是", "下一场")
    )

    landmarks = cards["pacing-fast-with-clear-landmarks"]
    assert "三个" not in landmarks["method"]
    assert all(word in landmarks["method"] for word in ("足够", "稳定", "路线选择"))

    suspense = cards["suspense-answer-opens-choice"]
    assert "立刻" not in suspense["method"]
    assert all(word in suspense["method"] for word in ("当前或后续场景", "危险", "承受"))

    setup = cards["arc-setup-serves-now-payoff-changes-choice"]
    assert all(word in setup["method"] for word in ("当前动作", "关系", "氛围", "理解", "选择", "可选", "Canon"))


def test_production_approved_styles_are_complete_distinct_original_payloads():
    manifest_bytes = PRODUCTION_ASSET_MANIFEST.read_bytes()
    raw_manifest = json.loads(manifest_bytes)
    style_bytes = (
        PRODUCTION_ASSET_MANIFEST.parent / raw_manifest["styles_file"]["path"]
    ).read_bytes()
    card_bytes = (
        PRODUCTION_ASSET_MANIFEST.parent
        / raw_manifest["experience_cards_file"]["path"]
    ).read_bytes()

    assert sha256(style_bytes).hexdigest() == raw_manifest["styles_file"]["sha256"]
    assert sha256(card_bytes).hexdigest() == raw_manifest["experience_cards_file"][
        "sha256"
    ]
    assert sha256(card_bytes).hexdigest() == (
        "60f7c6a713167a26d737b91a62c43012e5f77c8a9bb89e7b877099bf8f6e995b"
    )

    raw_styles = json.loads(style_bytes)

    assert len(raw_styles) == 10
    validated_styles = [
        StyleTemplateRevision.model_validate(style) for style in raw_styles
    ]
    assert {style.stable_key for style in validated_styles} == PRODUCTION_STYLE_KEYS
    for style in validated_styles:
        assert style.content_hash == canonical_hash(style.payload)
        assert style.provenance.decision == "approved"
        assert style.provenance.reviewer == "author"
        assert style.provenance.review_time == AUTHOR_APPROVAL_TIME

    styles_by_key = {style["stable_key"]: style for style in raw_styles}
    assert CANDIDATE_STYLE_NAMES.items() <= {
        key: style["name"] for key, style in styles_by_key.items()
    }.items()

    candidate_styles = [styles_by_key[key] for key in CANDIDATE_STYLE_NAMES]
    for style in candidate_styles:
        assert set(style["payload"]) == STYLE_PROMPT_PAYLOAD_FIELDS
        assert style["payload"]["schemaVersion"] == "style-template-v1"
        assert style["provenance"] == {
            "reviewer": "author",
            "review_time": AUTHOR_APPROVAL_TIME,
            "decision": "approved",
        }
        assert style["content_hash"] == canonical_hash(style["payload"])
        for example_field in (
            "standard_scene_example",
            "complete_application_example",
        ):
            example = style["payload"][example_field]
            assert len(example) >= 220
            assert "“" in example and "”" in example

    for field in ("reading_experience", "rhythm", "original_anchor"):
        values = [
            _normalized_text_identity(style["payload"][field])
            for style in raw_styles
        ]
        assert len(values) == len(set(values))


def test_new_style_examples_keep_costs_focused_and_quantities_selective():
    raw_styles = json.loads(
        (PRODUCTION_ASSET_MANIFEST.parent / "style_templates.json").read_text(
            encoding="utf-8"
        )
    )
    styles_by_key = {style["stable_key"]: style for style in raw_styles}

    cautious_complete = styles_by_key["cautious-survival-accumulation"]["payload"][
        "complete_application_example"
    ]
    explicit_quantities = re.findall(
        r"[一二两三四五六七八九十百千万半]+小?"
        r"(?:盏|日|坛|只|壶|刻|成|枚|天|夜|张|包|季|次)",
        cautious_complete,
    )
    assert 2 <= len(explicit_quantities) <= 3

    austere_payload = styles_by_key["austere-tragic-defiance"]["payload"]
    austere_standard = austere_payload["standard_scene_example"]
    for stacked_cost in ("已经没有呼吸", "震聋", "什么称呼也没留下"):
        assert stacked_cost not in austere_standard
    assert all(
        checkpoint in austere_standard
        for checkpoint in ("许川", "灰垣城", "铜环", "水闸", "无籍", "低坊")
    )

    austere_complete = austere_payload["complete_application_example"]
    for stacked_cost in ("再不能", "纸债", "从此没有回来", "脱臼"):
        assert stacked_cost not in austere_complete
    assert all(
        checkpoint in austere_complete
        for checkpoint in ("长子", "宋师傅", "被拖出门", "印坊")
    )


def test_production_approved_cards_append_exact_valid_distinct_payloads():
    raw_manifest = json.loads(PRODUCTION_ASSET_MANIFEST.read_bytes())
    style_bytes = (
        PRODUCTION_ASSET_MANIFEST.parent / raw_manifest["styles_file"]["path"]
    ).read_bytes()
    card_bytes = (
        PRODUCTION_ASSET_MANIFEST.parent
        / raw_manifest["experience_cards_file"]["path"]
    ).read_bytes()

    assert raw_manifest["styles_file"]["sha256"] == (
        "7c2e6fb458774282b11a08b726b6c9c10bc61e32e212736e02e9c060879a9333"
    )
    assert sha256(style_bytes).hexdigest() == raw_manifest["styles_file"]["sha256"]
    assert sha256(card_bytes).hexdigest() == raw_manifest["experience_cards_file"][
        "sha256"
    ]

    raw_cards = json.loads(card_bytes)
    appended_cards = raw_cards[48:56]
    cards_by_key = {card["stable_key"]: card for card in appended_cards}

    assert set(cards_by_key) == set(CANDIDATE_CARD_SPECS)
    assert len(appended_cards) == 8
    assert {
        category: sum(card["category"] == category for card in appended_cards)
        for category in ("long_arc_continuity", "progression_economy")
    } == {"long_arc_continuity": 4, "progression_economy": 4}

    for stable_key, (expected_category, expected_title) in CANDIDATE_CARD_SPECS.items():
        raw_card = cards_by_key[stable_key]
        card = ExperienceCardRevision.model_validate(raw_card)

        assert raw_card["title"] == expected_title
        assert raw_card["category"] == expected_category
        assert set(raw_card["payload"]) == CANDIDATE_CARD_PAYLOAD_FIELDS
        assert card.payload.schemaVersion == "experience-card-v1"
        assert card.payload.category == expected_category
        assert raw_card["provenance"] == {
            "reviewer": "author",
            "review_time": AUTHOR_APPROVAL_TIME,
            "decision": "approved",
        }
        assert card.content_hash == canonical_hash(card.payload)
        assert card.payload.applicability
        assert card.payload.non_applicability
        assert card.payload.risks

    methods = [
        _normalized_text_identity(card["payload"]["method"]) for card in raw_cards
    ]
    micro_demos = [
        _normalized_text_identity(card["payload"]["original_micro_demo"])
        for card in raw_cards
    ]
    assert len(methods) == len(set(methods))
    assert len(micro_demos) == len(set(micro_demos))


def test_new_cards_keep_long_arc_and_progression_guidance_conditional():
    raw_cards = json.loads(
        (PRODUCTION_ASSET_MANIFEST.parent / "experience_cards.json").read_text(
            encoding="utf-8"
        )
    )
    cards_by_key = {card["stable_key"]: card for card in raw_cards[48:]}

    block = cards_by_key["arc-block-chapter-delta"]["payload"]
    assert "本章实际承载该故事块推进时" in block["method"]
    assert "优先" in block["method"]
    assert all(
        boundary in block["method"]
        for boundary in ("铺垫", "驻留", "纯余波", "不要求钩子、转折或闭环")
    )
    assert all(
        boundary in " ".join(block["non_applicability"])
        for boundary in ("仅提及", "纯余波", "刻意驻留", "不承担推进")
    )

    setup = cards_by_key["arc-setup-serves-now-payoff-changes-choice"]["payload"]
    assert all(
        focus in setup["method"]
        for focus in (
            "能力",
            "关系承诺",
            "习惯",
            "物件",
            "当前动作",
            "氛围",
            "理解",
            "实际选择",
            "可选路径",
            "Canon",
        )
    )
    assert all(
        hidden_truth_marker not in setup["original_micro_demo"]
        for hidden_truth_marker in ("伪造", "官印", "认出命令", "真相")
    )
    assert all(
        scene_beat in setup["original_micro_demo"]
        for scene_beat in ("快解结", "修船", "割", "救人", "信任", "改道")
    )

    pressure = cards_by_key["arc-pressure-waves"]["payload"]
    assert all(
        causal_focus in pressure["method"]
        for causal_focus in ("应对选择", "产生或暴露", "下一种压力", "一项", "不复制固定")
    )
    assert all(
        handoff in pressure["original_micro_demo"]
        for handoff in ("骑哨", "河谷", "因此", "涨水")
    )
    assert "收了向导的钱" not in pressure["original_micro_demo"]
    assert "鼓" not in pressure["original_micro_demo"]

    resource = cards_by_key["progression-resource-loop-cost"]["payload"]
    assert all(
        condition in resource["method"]
        for condition in ("资源稀缺", "确实影响路线", "重大消耗", "真实备选", "不要求每次出现")
    )
    assert all(
        full_loop_marker not in resource["original_micro_demo"]
        for full_loop_marker in ("退潮滩", "刮取", "烘成", "转舵来接")
    )
    assert all(
        outcome in resource["original_micro_demo"]
        for outcome in ("旧储备", "矿道", "回闪", "求援仍未完成", "补给")
    )

    reviewed_methods = (
        block["method"],
        setup["method"],
        pressure["method"],
        resource["method"],
    )
    assert all(
        hard_rule not in method
        for method in reviewed_methods
        for hard_rule in ("必须", "每章只需")
    )

    breakthrough_demo = cards_by_key[
        "progression-breakthrough-earned-options"
    ]["payload"]["original_micro_demo"]
    assert "刚练成" not in breakthrough_demo
    assert "数日" in breakthrough_demo
    assert "灼痕" in breakthrough_demo


def _production_raw_cards() -> tuple[dict[str, object], list[dict[str, object]], bytes]:
    raw_manifest = json.loads(PRODUCTION_ASSET_MANIFEST.read_bytes())
    card_bytes = (
        PRODUCTION_ASSET_MANIFEST.parent
        / raw_manifest["experience_cards_file"]["path"]
    ).read_bytes()
    return raw_manifest, json.loads(card_bytes), card_bytes


def test_task4_candidate_cards_append_exact_keys_to_raw_asset():
    _, raw_cards, _ = _production_raw_cards()
    task4_cards_by_key = {card["stable_key"]: card for card in raw_cards[56:]}

    assert set(task4_cards_by_key) == set(TASK4_CANDIDATE_CARD_SPECS)


@pytest.mark.parametrize(
    ("stable_key", "expected_category", "expected_title"),
    [
        (stable_key, expected_category, expected_title)
        for stable_key, (expected_category, expected_title) in TASK4_CANDIDATE_CARD_SPECS.items()
    ],
)
def test_task4_approved_card_is_individually_complete_and_valid(
    stable_key: str,
    expected_category: str,
    expected_title: str,
):
    _, raw_cards, _ = _production_raw_cards()
    cards_by_key = {card["stable_key"]: card for card in raw_cards}

    assert stable_key in cards_by_key
    raw_card = cards_by_key[stable_key]
    card = ExperienceCardRevision.model_validate(raw_card)

    assert set(raw_card) == {
        "stable_key",
        "revision",
        "title",
        "category",
        "payload",
        "provenance",
        "content_hash",
    }
    assert raw_card["revision"] == 1
    assert raw_card["title"] == expected_title
    assert raw_card["category"] == expected_category
    assert set(raw_card["payload"]) == CANDIDATE_CARD_PAYLOAD_FIELDS
    assert card.payload.schemaVersion == "experience-card-v1"
    assert card.payload.category == expected_category
    assert raw_card["provenance"] == {
        "reviewer": "author",
        "review_time": AUTHOR_APPROVAL_TIME,
        "decision": "approved",
    }
    assert raw_card["content_hash"] == canonical_hash(raw_card["payload"])
    assert card.payload.applicability
    assert card.payload.non_applicability
    assert card.payload.risks


def test_task4_cards_complete_the_raw_inventory_and_manifest_hash():
    raw_manifest, raw_cards, card_bytes = _production_raw_cards()

    assert len(raw_cards) == 64
    assert {
        category: sum(card["category"] == category for card in raw_cards[56:])
        for category in ("character_arcs", "action_conflict")
    } == {"character_arcs": 4, "action_conflict": 4}
    assert sha256(card_bytes).hexdigest() == raw_manifest["experience_cards_file"][
        "sha256"
    ]


def test_task4_preserves_all_card_method_and_demo_nfkc_uniqueness():
    _, raw_cards, _ = _production_raw_cards()
    methods = [
        _normalized_text_identity(card["payload"]["method"]) for card in raw_cards
    ]
    micro_demos = [
        _normalized_text_identity(card["payload"]["original_micro_demo"])
        for card in raw_cards
    ]

    assert len(raw_cards) == 64
    assert len(methods) == len(set(methods))
    assert len(micro_demos) == len(set(micro_demos))


def test_task4_finish_combination_differs_from_ensemble_division_of_labor():
    _, raw_cards, _ = _production_raw_cards()
    card = next(
        card
        for card in raw_cards
        if card["stable_key"] == "action-finish-established-combination"
    )
    method = card["payload"]["method"]
    demo = card["payload"]["original_micro_demo"]

    assert "同一人物" in method
    assert "预期方案失效" in method
    assert "每个参与者" not in method
    assert "矿井" not in demo


def test_task4_supporting_arc_choice_has_direct_authority_over_main_contract():
    _, raw_cards, _ = _production_raw_cards()
    demo = next(
        card["payload"]["original_micro_demo"]
        for card in raw_cards
        if card["stable_key"] == "character-supporting-arc-changes-main"
    )

    assert "共同继承人" in demo
    assert "责任医师" in demo
    assert "签字" in demo
    assert "投资失效" in demo


def test_task4_competing_objectives_uses_natural_on_scene_judgment():
    _, raw_cards, _ = _production_raw_cards()
    demo = next(
        card["payload"]["original_micro_demo"]
        for card in raw_cards
        if card["stable_key"] == "action-competing-objectives"
    )

    assert "先让他跑得有名字" not in demo
    assert "牌子在手，才知道往哪追。你去盯船。" in demo


def test_task4_exchange_demo_uses_natural_causality_and_earned_broadcast_access():
    _, raw_cards, _ = _production_raw_cards()
    demo = next(
        card["payload"]["original_micro_demo"]
        for card in raw_cards
        if card["stable_key"] == "action-exchange-changes-state"
    )

    assert "记者证" in demo
    assert "站务员" in demo
    for checklist_link in ("她先", "随即", "只能", "因此"):
        assert checklist_link not in demo


def _normalized_text_identity(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _all_mapping_keys(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _all_mapping_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _all_mapping_keys(child)


def _style(index: int, *, approved: bool = False) -> dict[str, object]:
    payload = {
        "schemaVersion": "style-template-v1",
        "reading_experience": f"Synthetic reading experience {index}.",
        "applicability": [f"Synthetic application {index}"],
        "non_applicability": [f"Synthetic non-application {index}"],
        "standard_scene_example": f"Standard scene rendered in style {index}.",
        "complete_application_example": f"Complete original application {index}.",
        "narrative_distance": f"Narrative distance {index}.",
        "rhythm": f"Rhythm {index}.",
        "diction_density": f"Diction density {index}.",
        "dialogue": f"Dialogue strategy {index}.",
        "subtext": f"Subtext strategy {index}.",
        "character_voices": f"Voice strategy {index}.",
        "emotion": f"Emotion strategy {index}.",
        "interiority": f"Interiority strategy {index}.",
        "action": f"Action strategy {index}.",
        "explanation": f"Explanation strategy {index}.",
        "environment": f"Environment strategy {index}.",
        "body_response": f"Body response strategy {index}.",
        "preferred_techniques": [f"Preferred technique {index}"],
        "risks": [f"Risk {index}"],
        "original_anchor": f"Original synthetic anchor {index}.",
    }
    return {
        "stable_key": f"style.synthetic-{index}",
        "revision": 1,
        "name": f"Synthetic Style {index}",
        "payload": payload,
        "provenance": {
            "reviewer": "Synthetic Reviewer" if approved else None,
            "review_time": "2026-07-12T00:00:00+00:00" if approved else None,
            "decision": "approved" if approved else ("candidate", "rewrite", "rejected")[index % 3],
        },
        "content_hash": canonical_hash(payload),
    }


def synthetic_categories() -> tuple[str, ...]:
    return tuple(
        category
        for category, count in EXPECTED_CATEGORY_COUNTS.items()
        for _ in range(count)
    )


def _card(
    index: int,
    *,
    category: str | None = None,
    approved: bool = False,
) -> dict[str, object]:
    category = category or synthetic_categories()[index % 64]
    payload = {
        "schemaVersion": "experience-card-v1",
        "category": category,
        "method": f"Synthetic method {index}",
        "applicability": [f"Applicable situation {index}"],
        "non_applicability": [f"Non-applicable situation {index}"],
        "risks": [f"Synthetic risk {index}"],
        "original_micro_demo": f"Original synthetic micro-demo {index}.",
    }
    return {
        "stable_key": f"card.synthetic-{index}",
        "revision": 1,
        "title": f"Synthetic Card {index}",
        "category": category,
        "payload": payload,
        "provenance": {
            "reviewer": "Synthetic Reviewer" if approved else None,
            "review_time": "2026-07-12T00:00:00+00:00" if approved else None,
            "decision": "approved" if approved else ("candidate", "rewrite", "rejected")[index % 3],
        },
        "content_hash": canonical_hash(payload),
    }


def valid_values(*, approved: bool = False) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    styles = [_style(index, approved=approved) for index in range(10)]
    cards = [
        _card(index, category=category, approved=approved)
        for index, category in enumerate(synthetic_categories())
    ]
    manifest = {
        "package_version": "writer-core-v1.1.0",
        "styles_file": {"path": "style_templates.json", "sha256": "a" * 64},
        "experience_cards_file": {"path": "experience_cards.json", "sha256": "b" * 64},
    }
    return manifest, styles, cards


def package_from_values(*, approved: bool = False) -> AssetPackage:
    manifest, styles, cards = valid_values(approved=approved)
    return AssetPackage.model_validate(
        {"manifest": manifest, "styles": styles, "experience_cards": cards}
    )


def package_dict(*, approved: bool = False) -> dict[str, object]:
    manifest, styles, cards = valid_values(approved=approved)
    return {"manifest": manifest, "styles": styles, "experience_cards": cards}


def _write_package(root: Path, *, approved: bool = False) -> Path:
    manifest, styles, cards = valid_values(approved=approved)
    style_bytes = json.dumps(styles, ensure_ascii=False, indent=2).encode("utf-8")
    card_bytes = json.dumps(cards, ensure_ascii=False, indent=2).encode("utf-8")
    (root / "style_templates.json").write_bytes(style_bytes)
    (root / "experience_cards.json").write_bytes(card_bytes)
    manifest["styles_file"]["sha256"] = sha256(style_bytes).hexdigest()
    manifest["experience_cards_file"]["sha256"] = sha256(card_bytes).hexdigest()
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def _assert_safe_error(
    error: BaseException,
    *,
    expected: str,
    secrets: tuple[str, ...],
) -> None:
    assert str(error) == expected
    assert error.__context__ is None
    assert error.__cause__ is None
    rendered = "".join(traceback.format_exception(error))
    for secret in secrets:
        assert secret not in str(error)
        assert secret not in rendered


def test_structural_package_accepts_exact_synthetic_inventory_and_decisions():
    package = package_from_values()

    result = validate_asset_package(package, mode="structural")

    assert result is package
    assert len(result.styles) == 10
    assert len(result.experience_cards) == 64
    assert {
        category: sum(card.category == category for card in result.experience_cards)
        for category in ASSET_CATEGORIES
    } == EXPECTED_CATEGORY_COUNTS
    assert len({item.content_hash for item in (*result.styles, *result.experience_cards)}) == 74
    assert {item.provenance.decision for item in (*result.styles, *result.experience_cards)} <= {
        "approved", "candidate", "rewrite", "rejected"
    }


def test_validator_accepts_a_raw_synthetic_package_dict():
    result = validate_asset_package(package_dict(), mode="structural")

    assert isinstance(result, AssetPackage)
    assert result.package_version == "writer-core-v1.1.0"


def test_validator_wraps_raw_dict_validation_errors_as_stable_package_errors():
    values = package_dict()
    secret_key = "rawExcerpt_SECRET_KEY"
    secret_value = "SECRET_VALUE\nSECRET_NEWLINE_SENTINEL"
    values["experience_cards"][0]["payload"][secret_key] = secret_value

    with pytest.raises(ValidationError) as original:
        AssetPackage.model_validate(values)
    original_error = original.value.errors(include_url=False)[0]
    assert secret_key in original_error["loc"]
    assert original_error["input"] == secret_value

    with pytest.raises(AssetPackageError) as captured:
        validate_asset_package(values, mode="structural")

    _assert_safe_error(
        captured.value,
        expected="ASSET_PACKAGE_INVALID: asset package is invalid",
        secrets=(secret_key, secret_value, "SECRET_NEWLINE_SENTINEL"),
    )


@pytest.mark.parametrize("style_count", [9, 11])
def test_structural_package_requires_exactly_ten_styles(style_count: int):
    package = package_from_values()
    changed = package.model_copy(update={"styles": package.styles[:style_count]})
    if style_count == 11:
        extra = deepcopy(package.styles[-1].model_dump(mode="json"))
        extra["stable_key"] = "style.synthetic-extra"
        extra["payload"]["original_anchor"] = "Unique extra anchor."
        extra["content_hash"] = canonical_hash(extra["payload"])
        changed = package.model_copy(
            update={"styles": (*package.styles, type(package.styles[0]).model_validate(extra))}
        )

    with pytest.raises(AssetPackageError, match="exactly 10 styles"):
        validate_asset_package(changed, mode="structural")


@pytest.mark.parametrize("card_count", [63, 65])
def test_structural_package_requires_exactly_sixty_four_cards(card_count: int):
    package = package_from_values()
    cards = package.experience_cards[:card_count]
    if card_count == 65:
        extra_values = _card(64, category="plot_organization")
        extra = type(package.experience_cards[0]).model_validate(extra_values)
        cards = (*package.experience_cards, extra)
    changed = package.model_copy(update={"experience_cards": cards})

    with pytest.raises(AssetPackageError, match="exactly 64 experience cards"):
        validate_asset_package(changed, mode="structural")


def test_structural_package_requires_all_approved_category_counts():
    package = package_from_values()
    cards = list(package.experience_cards)
    for index, card in enumerate(cards):
        if card.category != "action_conflict":
            continue
        replacement_values = card.model_dump(mode="json")
        replacement_values["category"] = "plot_organization"
        replacement_values["payload"]["category"] = "plot_organization"
        replacement_values["content_hash"] = canonical_hash(
            replacement_values["payload"]
        )
        cards[index] = type(package.experience_cards[0]).model_validate(
            replacement_values
        )
    changed = package.model_copy(update={"experience_cards": tuple(cards)})

    assert len(changed.experience_cards) == 64
    assert "action_conflict" not in {card.category for card in changed.experience_cards}
    with pytest.raises(AssetPackageError, match="approved category counts"):
        validate_asset_package(changed, mode="structural")


def test_structural_package_rejects_new_category_five_three_split_at_total_64():
    package = package_from_values()
    cards = list(package.experience_cards)
    replacement_index = next(
        index
        for index, card in enumerate(cards)
        if card.category == "progression_economy"
    )
    replacement_values = cards[replacement_index].model_dump(mode="json")
    replacement_values["category"] = "long_arc_continuity"
    replacement_values["payload"]["category"] = "long_arc_continuity"
    replacement_values["content_hash"] = canonical_hash(replacement_values["payload"])
    cards[replacement_index] = type(package.experience_cards[0]).model_validate(
        replacement_values
    )
    changed = package.model_copy(update={"experience_cards": tuple(cards)})

    assert len(changed.experience_cards) == 64
    with pytest.raises(AssetPackageError, match="approved category counts"):
        validate_asset_package(changed, mode="structural")


@pytest.mark.parametrize("collection_name", ["styles", "experience_cards"])
def test_structural_package_rejects_duplicate_stable_keys(collection_name: str):
    package = package_from_values()
    values = list(getattr(package, collection_name))
    values[1] = values[1].model_copy(update={"stable_key": values[0].stable_key})
    changed = package.model_copy(update={collection_name: tuple(values)})

    with pytest.raises(AssetPackageError, match="duplicate stable_key"):
        validate_asset_package(changed, mode="structural")


@pytest.mark.parametrize("field", ["method", "original_micro_demo"])
def test_structural_package_rejects_normalized_method_or_demo_duplicates(field: str):
    package = package_from_values()
    values = list(package.experience_cards)
    payload = values[1].payload.model_dump(mode="json")
    payload[field] = "  " + getattr(values[0].payload, field).upper() + "  "
    values[1] = values[1].model_copy(
        update={"payload": type(values[1].payload).model_validate(payload)}
    )
    changed = package.model_copy(update={"experience_cards": tuple(values)})

    with pytest.raises(AssetPackageError, match=f"duplicate normalized {field}"):
        validate_asset_package(changed, mode="structural")


def test_structural_package_rejects_content_hash_mismatch_and_duplicates():
    package = package_from_values()
    styles = list(package.styles)
    styles[0] = styles[0].model_copy(update={"content_hash": "0" * 64})
    mismatch = package.model_copy(update={"styles": tuple(styles)})
    with pytest.raises(AssetPackageError, match="content_hash mismatch"):
        validate_asset_package(mismatch, mode="structural")

    styles = list(package.styles)
    styles[1] = styles[1].model_copy(update={"content_hash": styles[0].content_hash})
    duplicate = package.model_copy(update={"styles": tuple(styles)})
    with pytest.raises(AssetPackageError, match="duplicate content_hash"):
        validate_asset_package(duplicate, mode="structural")


def test_release_requires_approved_decision_reviewer_and_review_time():
    with pytest.raises(AssetPackageError, match="release review metadata"):
        validate_asset_package(package_from_values(), mode="release")

    approved = package_from_values(approved=True)
    assert validate_asset_package(approved, mode="release") is approved


def test_release_rejects_invalid_or_timezone_naive_review_time():
    for review_time in ("not-a-time", "2026-07-12T00:00:00"):
        values = package_dict(approved=True)
        values["styles"][0]["provenance"]["review_time"] = review_time

        with pytest.raises(AssetPackageError) as captured:
            validate_asset_package(values, mode="release")

        _assert_safe_error(
            captured.value,
            expected="ASSET_PACKAGE_INVALID: asset package is invalid",
            secrets=(review_time,),
        )


def test_unknown_validation_mode_is_rejected():
    secret_mode = "preview_SECRET_MODE\nSECRET_NEWLINE_SENTINEL"
    with pytest.raises(AssetPackageError) as captured:
        validate_asset_package(package_from_values(), mode=secret_mode)

    _assert_safe_error(
        captured.value,
        expected=(
            "ASSET_VALIDATION_MODE_UNSUPPORTED: "
            "asset package validation mode is unsupported"
        ),
        secrets=(secret_mode, "SECRET_MODE", "SECRET_NEWLINE_SENTINEL"),
    )


def test_loader_wraps_manifest_validation_without_secret_echo(tmp_path: Path):
    secret_key = "unknown_SECRET_MANIFEST_KEY"
    secret_value = "SECRET_MANIFEST_VALUE\nSECRET_NEWLINE_SENTINEL"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "package_version": "writer-core-v1.1.0",
                "styles_file": {"path": "styles.json", "sha256": "a" * 64},
                "experience_cards_file": {"path": "cards.json", "sha256": "b" * 64},
                secret_key: secret_value,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(AssetPackageError) as captured:
        load_asset_package(manifest_path)

    _assert_safe_error(
        captured.value,
        expected="ASSET_MANIFEST_INVALID: asset manifest is invalid",
        secrets=(secret_key, secret_value, "SECRET_NEWLINE_SENTINEL"),
    )


def test_loader_wraps_manifest_io_without_absolute_path_echo(tmp_path: Path):
    secret_path = tmp_path / "SECRET_ABSOLUTE_PATH\nSECRET_NEWLINE_SENTINEL.json"

    with pytest.raises(OSError) as original:
        secret_path.stat()
    assert original.value.filename == str(secret_path)

    with pytest.raises(AssetPackageError) as captured:
        load_asset_package(secret_path)

    _assert_safe_error(
        captured.value,
        expected="ASSET_MANIFEST_IO: asset manifest could not be read",
        secrets=(str(secret_path), "SECRET_ABSOLUTE_PATH", "SECRET_NEWLINE_SENTINEL"),
    )


def test_loader_wraps_child_io_without_absolute_path_echo(tmp_path: Path):
    manifest, _, _ = valid_values()
    secret_child = "SECRET_CHILD_PATH_SECRET_NEWLINE_SENTINEL.json"
    manifest["styles_file"]["path"] = secret_child
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(AssetPackageError) as captured:
        load_asset_package(manifest_path)

    absolute_secret_path = str(tmp_path / secret_child)
    _assert_safe_error(
        captured.value,
        expected="ASSET_STYLES_IO: styles asset file could not be read",
        secrets=(secret_child, absolute_secret_path, "SECRET_NEWLINE_SENTINEL"),
    )


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("manifest", "ASSET_MANIFEST_JSON_INVALID: asset manifest JSON is invalid"),
        ("styles", "ASSET_STYLES_JSON_INVALID: styles asset JSON is invalid"),
    ],
)
def test_loader_wraps_invalid_json_without_content_or_path_echo(
    tmp_path: Path,
    target: str,
    expected: str,
):
    secret_json = b'{"SECRET_JSON_KEY":"SECRET_JSON_VALUE\\nSECRET_NEWLINE_SENTINEL"'
    secret_document = secret_json.decode("utf-8")
    with pytest.raises(json.JSONDecodeError) as original:
        json.loads(secret_document)
    assert original.value.doc == secret_document

    if target == "manifest":
        target_path = tmp_path / "manifest_SECRET_ABSOLUTE_PATH.json"
        target_path.write_bytes(secret_json)
        manifest_path = target_path
    else:
        manifest_path = _write_package(tmp_path)
        target_path = tmp_path / "style_templates.json"
        target_path.write_bytes(secret_json)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["styles_file"]["sha256"] = sha256(secret_json).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(AssetPackageError) as captured:
        load_asset_package(manifest_path)

    _assert_safe_error(
        captured.value,
        expected=expected,
        secrets=(
            "SECRET_JSON_KEY",
            "SECRET_JSON_VALUE",
            "SECRET_NEWLINE_SENTINEL",
            str(target_path),
        ),
    )


@pytest.mark.parametrize(
    ("target", "limit", "expected"),
    [
        (
            "manifest",
            64 * 1024,
            "ASSET_MANIFEST_TOO_LARGE: asset manifest exceeds maximum size",
        ),
        (
            "styles",
            4 * 1024 * 1024,
            "ASSET_STYLES_TOO_LARGE: styles asset file exceeds maximum size",
        ),
    ],
)
def test_loader_rejects_oversized_invalid_json_before_parsing(
    tmp_path: Path,
    target: str,
    limit: int,
    expected: str,
):
    invalid_oversized_json = b"{" + (b"x" * limit)
    if target == "manifest":
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_bytes(invalid_oversized_json)
    else:
        manifest_path = _write_package(tmp_path)
        styles_path = tmp_path / "style_templates.json"
        styles_path.write_bytes(invalid_oversized_json)

    with pytest.raises(AssetPackageError) as captured:
        load_asset_package(manifest_path)

    assert str(captured.value) == expected


def test_loader_rejects_resolved_child_escape(tmp_path: Path):
    manifest, _, _ = valid_values()
    manifest["styles_file"]["path"] = "nested/../../outside.json"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(AssetPackageError) as captured:
        load_asset_package(manifest_path)

    assert str(captured.value) == "ASSET_MANIFEST_INVALID: asset manifest is invalid"


def test_loader_rejects_symlink_child_escape_when_supported(tmp_path: Path):
    package_root = tmp_path / "package"
    package_root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("[]", encoding="utf-8")
    link = package_root / "linked.json"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlink creation is unavailable: {exc.__class__.__name__}")

    manifest, _, _ = valid_values()
    manifest["styles_file"] = {
        "path": "linked.json",
        "sha256": sha256(b"[]").hexdigest(),
    }
    manifest_path = package_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(AssetPackageError) as captured:
        load_asset_package(manifest_path)

    assert str(captured.value) == (
        "ASSET_STYLES_PATH_ESCAPE: styles asset path escapes package directory"
    )


def test_loader_checks_child_sha256_before_json_parsing(tmp_path: Path):
    manifest_path = _write_package(tmp_path)
    (tmp_path / "style_templates.json").write_text("not-json", encoding="utf-8")

    with pytest.raises(AssetPackageError, match="styles_file sha256 mismatch"):
        load_asset_package(manifest_path, mode="structural")


def test_loader_checks_canonical_content_hash_after_parsing(tmp_path: Path):
    manifest_path = _write_package(tmp_path)
    styles_path = tmp_path / "style_templates.json"
    styles = json.loads(styles_path.read_text(encoding="utf-8"))
    styles[0]["content_hash"] = "0" * 64
    style_bytes = json.dumps(styles, ensure_ascii=False).encode("utf-8")
    styles_path.write_bytes(style_bytes)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["styles_file"]["sha256"] = sha256(style_bytes).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(AssetPackageError, match="content_hash mismatch"):
        load_asset_package(manifest_path, mode="structural")


def test_loader_returns_same_deterministic_package_for_repeated_reads(tmp_path: Path):
    manifest_path = _write_package(tmp_path, approved=True)

    first = load_asset_package(manifest_path, mode="release")
    second = load_asset_package(manifest_path, mode="release")

    assert first == second


def test_loader_wraps_forbidden_raw_excerpt_as_stable_package_error(tmp_path: Path):
    manifest_path = _write_package(tmp_path)
    cards_path = tmp_path / "experience_cards.json"
    cards = json.loads(cards_path.read_text(encoding="utf-8"))
    cards[0]["payload"]["rawExcerpt"] = "forbidden source text"
    card_bytes = json.dumps(cards, ensure_ascii=False).encode("utf-8")
    cards_path.write_bytes(card_bytes)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["experience_cards_file"]["sha256"] = sha256(card_bytes).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(AssetPackageError) as captured:
        load_asset_package(manifest_path, mode="structural")

    assert str(captured.value) == "ASSET_PACKAGE_INVALID: asset package is invalid"


def test_production_approved_manifest_is_structurally_complete_and_releasable():
    raw_manifest = json.loads(PRODUCTION_ASSET_MANIFEST.read_text(encoding="utf-8"))
    raw_styles = json.loads(
        (PRODUCTION_ASSET_MANIFEST.parent / raw_manifest["styles_file"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    raw_cards = json.loads(
        (
            PRODUCTION_ASSET_MANIFEST.parent
            / raw_manifest["experience_cards_file"]["path"]
        ).read_text(encoding="utf-8")
    )

    assert (len(raw_styles), len(raw_cards)) == (10, 64)

    package = load_asset_package(PRODUCTION_ASSET_MANIFEST, mode="structural")

    assert {style.stable_key for style in package.styles} == PRODUCTION_STYLE_KEYS
    assert len(package.experience_cards) == 64
    assert {
        category: sum(card.category == category for card in package.experience_cards)
        for category in ASSET_CATEGORIES
    } == EXPECTED_CATEGORY_COUNTS

    for style in package.styles:
        assert style.payload.schemaVersion == "style-template-v1"
        for example in (
            style.payload.standard_scene_example,
            style.payload.complete_application_example,
        ):
            assert len(example) >= 220
            assert "“" in example and "”" in example

    methods = [
        _normalized_text_identity(card.payload.method)
        for card in package.experience_cards
    ]
    micro_demos = [
        _normalized_text_identity(card.payload.original_micro_demo)
        for card in package.experience_cards
    ]
    assert len(methods) == len(set(methods))
    assert len(micro_demos) == len(set(micro_demos))

    all_assets = (*package.styles, *package.experience_cards)
    assert all(asset.content_hash == canonical_hash(asset.payload) for asset in all_assets)
    assert all(
        asset.provenance.decision == "approved"
        and asset.provenance.reviewer == "author"
        and asset.provenance.review_time == AUTHOR_APPROVAL_TIME
        for asset in all_assets
    )

    raw_values = json.loads(PRODUCTION_ASSET_MANIFEST.read_text(encoding="utf-8"))
    for descriptor in (raw_values["styles_file"], raw_values["experience_cards_file"]):
        child_values = json.loads(
            (PRODUCTION_ASSET_MANIFEST.parent / descriptor["path"]).read_text(
                encoding="utf-8"
            )
        )
        forbidden_keys = {
            key.casefold()
            for key in _all_mapping_keys(child_values)
            if key.casefold() == "source" or key.casefold().startswith("source_")
        }
        assert forbidden_keys == set()

    release_package = load_asset_package(PRODUCTION_ASSET_MANIFEST, mode="release")
    assert release_package == package
