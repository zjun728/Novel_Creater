"""Pure, deterministic recommendation of reviewed Writer Core assets."""

from __future__ import annotations

from collections.abc import Mapping
import re
from types import MappingProxyType
from typing import Literal
import unicodedata

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.assets import (
    ASSET_CATEGORIES,
    AssetInventory,
    AssetPackage,
    ExperienceCardRevision,
    StyleTemplateRevision,
    validate_asset_package,
    validate_asset_inventory,
)
from backend.domain.json_contracts import canonical_hash
from backend.domain.seeds import SeedPayload


RECOMMENDATION_VERSION = "asset-recommendation-v1"
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ENGINE_TEXT_MAX_LENGTH = 2_000
_ENGINE_COLLECTION_MAX_ITEMS = 20
_ENGINE_MAX_ITEMS = 100
_ENGINE_TOTAL_TEXT_MAX_LENGTH = 64_000
_CATEGORY_SIGNAL_THRESHOLD = 3

ReasonCode = Literal[
    "semantic-profile",
    "seed-context",
    "engine-context",
    "category-profile",
    "asset-text-overlap",
    "default-rank",
]


class RecommendationInputError(ValueError):
    """A fixed, non-sensitive failure at the recommendation boundary."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )


class AssetRecommendationRef(_FrozenModel):
    stable_key: str = Field(min_length=1, max_length=160)
    revision: int = Field(gt=0)
    content_hash: str = Field(pattern=_HASH_PATTERN.pattern)
    reason_codes: tuple[ReasonCode, ...] = Field(min_length=1, max_length=4)


class AssetRecommendationResult(_FrozenModel):
    recommendation_version: Literal["asset-recommendation-v1"]
    seed_hash: str = Field(pattern=_HASH_PATTERN.pattern)
    engine_hash: str = Field(pattern=_HASH_PATTERN.pattern)
    styles: tuple[AssetRecommendationRef, ...] = Field(min_length=3, max_length=3)
    experience_cards: tuple[AssetRecommendationRef, ...] = Field(
        min_length=2,
        max_length=4,
    )
    recommendation_hash: str = Field(pattern=_HASH_PATTERN.pattern)


_SEED_FIELD_WEIGHTS = MappingProxyType(
    {
        "title": 1,
        "genre": 5,
        "logline": 4,
        "protagonist": 2,
        "desire": 4,
        "coreConflict": 3,
        "worldPressure": 2,
        "openingHook": 2,
        "differentiation": 4,
    }
)

_ENGINE_SCALAR_FIELDS = (
    "name",
    "storyPromise",
    "protagonistDesire",
    "sustainedPressure",
    "growthDirection",
    "conflictLoop",
    "advantageAndCost",
    "endingAnchor",
    "differentiation",
)
_ENGINE_SEQUENCE_FIELDS = (
    "satisfactionSources",
    "longFormVariation",
    "risks",
)
_ENGINE_FIELDS = frozenset(
    (*_ENGINE_SCALAR_FIELDS, *_ENGINE_SEQUENCE_FIELDS, "ensembleRoles")
)
_ENGINE_FIELD_WEIGHTS = MappingProxyType(
    {
        "name": 1,
        "storyPromise": 5,
        "protagonistDesire": 4,
        "sustainedPressure": 3,
        "growthDirection": 4,
        "conflictLoop": 4,
        "ensembleRoles": 3,
        "advantageAndCost": 3,
        "satisfactionSources": 3,
        "longFormVariation": 3,
        "endingAnchor": 1,
        "risks": 1,
        "differentiation": 4,
    }
)

_STYLE_DEFAULT_ORDER = (
    "direct-propulsive",
    "immersive-ensemble",
    "high-energy-growth",
    "light-humorous",
    "cautious-survival-accumulation",
    "restrained-suspense",
    "epic-civilization-building",
    "marketplace-wit-and-life",
    "emotion-relationship",
    "austere-tragic-defiance",
)
_STYLE_PROFILES = MappingProxyType(
    {
        "direct-propulsive": (
            "直接推进", "任务目标", "立即行动", "限期", "追逐", "fast paced",
        ),
        "light-humorous": (
            "轻松", "幽默", "吐槽", "笑点", "反差喜剧", "comedy", "humor",
        ),
        "immersive-ensemble": (
            "群像", "配角", "伙伴", "团队", "多方", "众人", "协作", "ensemble",
        ),
        "restrained-suspense": (
            "悬疑", "诡异", "谜团", "线索", "嫌疑", "查案", "mystery", "suspense",
        ),
        "high-energy-growth": (
            "玄幻", "仙侠", "高武", "修炼突破", "境界突破", "能力成长", "角色成长", "伙伴成长", "升级流", "cultivation", "xianxia",
        ),
        "emotion-relationship": (
            "情感关系", "爱情", "亲情", "关系变化", "关系修复", "信任", "亏欠", "和解", "romance",
        ),
        "epic-civilization-building": (
            "历史穿越", "架空历史", "文明建设", "制度建设", "建设制度", "知识建设", "建设问题", "建设成果", "建设者", "改变乱世", "跨章修正制度", "技术变革", "长期秩序", "可持续秩序", "领地建设", "kingdom building",
        ),
        "marketplace-wit-and-life": (
            "市井", "经商", "商贸", "买卖", "价格", "人情", "商路", "marketplace",
        ),
        "cautious-survival-accumulation": (
            "求生", "生存", "谨慎", "稳健", "积累", "准备", "验证", "凡人", "survival",
        ),
        "austere-tragic-defiance": (
            "冷峻", "悲剧", "逆命", "宿命", "牺牲", "不可逆", "反抗", "复仇", "tragic",
        ),
    }
)

_CATEGORY_DEFAULT_ORDER = (
    "plot_organization",
    "character_arcs",
    "ensemble",
    "dialogue",
    "emotion",
    "interiority",
    "information_release",
    "pacing",
    "suspense",
    "long_arc_continuity",
    "progression_economy",
    "action_conflict",
)
_CATEGORY_PROFILES = MappingProxyType(
    {
        "plot_organization": (
            "主线转折", "因果链", "任务代价", "建设问题", "方案改写", "不可逆选择", "跨章修正",
        ),
        "ensemble": ("群像", "配角", "伙伴", "团队", "多方", "协作", "众人"),
        "dialogue": ("对话", "交谈", "谈判", "话术", "口吻", "争辩", "称呼"),
        "emotion": ("情绪变化", "情绪爆发", "悲伤", "愤怒", "喜悦", "不可逆失去", "关系修复"),
        "interiority": ("内心", "心理", "念头", "犹豫", "自省", "欲望", "动摇"),
        "information_release": ("规则显形", "公平线索", "旧证据", "历史争议", "知识验证", "证据含义"),
        "pacing": ("节奏", "快慢", "喘息", "追逐", "连战", "停顿", "压迫"),
        "suspense": ("悬疑", "诡异", "谜团", "线索", "真相", "嫌疑", "查案"),
        "long_arc_continuity": (
            "长篇", "长线", "跨章", "分卷", "伏笔", "回收", "长期因果", "余波",
        ),
        "progression_economy": (
            "修炼突破", "修炼资源", "境界突破", "能力组合", "能力成长", "成长反馈", "实践反馈", "资源闭环", "稳健积累", "升级流",
        ),
        "character_arcs": (
            "人物弧光", "反派改策", "配角选择", "性格改变", "人物选择", "角色成长",
        ),
        "action_conflict": (
            "动作冲突", "战斗", "斗法", "追杀", "交锋", "战术", "伤势", "高武",
        ),
    }
)

_CJK_BIGRAM_STOPWORDS = frozenset(
    {
        "一个",
        "人物",
        "角色",
        "主角",
        "选择",
        "改变",
        "目标",
        "信息",
        "故事",
        "场景",
        "需要",
        "自己",
        "关系",
        "能力",
        "行动",
        "问题",
        "结果",
        "压力",
        "通过",
        "不断",
        "同时",
        "相关",
        "推进",
        "留下",
        "后续",
        "当前",
        "可以",
        "不能",
        "必须",
        "如何",
        "不是",
        "开始",
        "完成",
        "具体",
        "对方",
        "知道",
    }
)


def validate_recommendation_inventory(
    inventory: AssetInventory,
) -> AssetInventory:
    """Require the approved fixed style-key set used by recommendation v1."""

    inventory = validate_asset_inventory(inventory, mode="release")
    if {style.stable_key for style in inventory.styles} != set(_STYLE_PROFILES):
        raise RecommendationInputError("asset recommendation profile is invalid")
    return inventory


def _normalize_text(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value).casefold()
    cleaned = "".join(
        " " if unicodedata.category(character)[0] in {"P", "Z", "C"} else character
        for character in folded
    )
    return " ".join(cleaned.split())


def _validate_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _ENGINE_TEXT_MAX_LENGTH:
        raise RecommendationInputError("engine payload is invalid")
    return value


def _engine_text_fields(payload: Mapping[str, object]) -> dict[str, str]:
    if not isinstance(payload, Mapping) or set(payload) != _ENGINE_FIELDS:
        raise RecommendationInputError("engine payload is invalid")
    fields: dict[str, str] = {}
    item_count = 0
    total_characters = 0
    for field in _ENGINE_SCALAR_FIELDS:
        text = _validate_text(payload[field])
        fields[field] = text
        item_count += 1
        total_characters += len(text)
    for field in _ENGINE_SEQUENCE_FIELDS:
        values = payload[field]
        if not isinstance(values, (tuple, list)) or not 1 <= len(values) <= _ENGINE_COLLECTION_MAX_ITEMS:
            raise RecommendationInputError("engine payload is invalid")
        texts = tuple(_validate_text(value) for value in values)
        fields[field] = " ".join(texts)
        item_count += len(texts)
        total_characters += sum(map(len, texts))
    roles = payload["ensembleRoles"]
    if not isinstance(roles, (tuple, list)) or not 1 <= len(roles) <= _ENGINE_COLLECTION_MAX_ITEMS:
        raise RecommendationInputError("engine payload is invalid")
    role_texts: list[str] = []
    for role in roles:
        if not isinstance(role, Mapping) or set(role) != {"role", "purpose"}:
            raise RecommendationInputError("engine payload is invalid")
        role_name = _validate_text(role["role"])
        purpose = _validate_text(role["purpose"])
        role_texts.extend((role_name, purpose))
        total_characters += len(role_name) + len(purpose)
    item_count += len(role_texts)
    fields["ensembleRoles"] = " ".join(role_texts)
    if item_count > _ENGINE_MAX_ITEMS or total_characters > _ENGINE_TOTAL_TEXT_MAX_LENGTH:
        raise RecommendationInputError("engine payload is invalid")
    return fields


def _profile_score(
    profile: tuple[str, ...],
    fields: Mapping[str, str],
    weights: Mapping[str, int],
) -> int:
    normalized_keywords = tuple(_normalize_text(keyword) for keyword in profile)
    return sum(
        weights[field]
        for field, raw_text in fields.items()
        for keyword in normalized_keywords
        if keyword and _signal_in_text(keyword, _normalize_text(raw_text))
    )


def _signal_in_text(signal: str, text: str) -> bool:
    if re.fullmatch(r"[a-z0-9 ]+", signal):
        return f" {signal} " in f" {text} "
    return signal in text


def _text_tokens(value: str) -> frozenset[str]:
    normalized = _normalize_text(value)
    ascii_tokens = set(re.findall(r"[a-z0-9]+", normalized))
    chinese_runs = re.findall(r"[\u3400-\u9fff]+", normalized)
    chinese_tokens: set[str] = set()
    for run in chinese_runs:
        if len(run) == 1:
            chinese_tokens.add(run)
        else:
            chinese_tokens.update(
                token
                for index in range(len(run) - 1)
                if (token := run[index : index + 2]) not in _CJK_BIGRAM_STOPWORDS
            )
    return frozenset((*ascii_tokens, *chinese_tokens))


def _style_ref(
    style: StyleTemplateRevision,
    *,
    seed_score: int,
    engine_score: int,
) -> AssetRecommendationRef:
    reasons: list[ReasonCode] = []
    if seed_score + engine_score:
        reasons.append("semantic-profile")
        if seed_score:
            reasons.append("seed-context")
        if engine_score:
            reasons.append("engine-context")
    else:
        reasons.append("default-rank")
    return AssetRecommendationRef(
        stable_key=style.stable_key,
        revision=style.revision,
        content_hash=style.content_hash,
        reason_codes=tuple(reasons),
    )


def _card_text(card: ExperienceCardRevision) -> str:
    return " ".join((card.title, card.payload.method))


def _card_ref(
    card: ExperienceCardRevision,
    *,
    category_score: int,
    overlap_score: int,
) -> AssetRecommendationRef:
    reasons: list[ReasonCode] = []
    if category_score:
        reasons.append("category-profile")
    if overlap_score:
        reasons.append("asset-text-overlap")
    if not reasons:
        reasons.append("default-rank")
    return AssetRecommendationRef(
        stable_key=card.stable_key,
        revision=card.revision,
        content_hash=card.content_hash,
        reason_codes=tuple(reasons),
    )


def recommend_assets(
    seed: SeedPayload,
    engine_payload: Mapping[str, object],
    package: AssetPackage | AssetInventory,
    *,
    seed_hash: str,
    engine_hash: str,
    allowed_style_identities: frozenset[tuple[str, str]] | None = None,
    allowed_card_identities: frozenset[tuple[str, str]] | None = None,
) -> AssetRecommendationResult:
    """Return a small stable recommendation without external state or providers."""

    if not isinstance(seed, SeedPayload):
        raise RecommendationInputError("seed payload is invalid")
    if not _HASH_PATTERN.fullmatch(seed_hash) or not _HASH_PATTERN.fullmatch(engine_hash):
        raise RecommendationInputError("recommendation hash input is invalid")
    if isinstance(package, AssetInventory):
        inventory = package
    else:
        package = validate_asset_package(package, mode="release")
        inventory = AssetInventory(
            styles=package.styles,
            experience_cards=package.experience_cards,
        )
    inventory = validate_recommendation_inventory(inventory)
    eligible_styles = tuple(
        style
        for style in inventory.styles
        if (
            allowed_style_identities is None
            or (style.stable_key, style.content_hash)
            in allowed_style_identities
        )
    )
    eligible_cards = tuple(
        card
        for card in inventory.experience_cards
        if (
            allowed_card_identities is None
            or (card.stable_key, card.content_hash)
            in allowed_card_identities
        )
    )
    if len(eligible_styles) < 3 or len(eligible_cards) < 2:
        raise RecommendationInputError(
            "typed asset eligibility leaves too few approved assets"
        )
    engine_fields = _engine_text_fields(engine_payload)
    seed_fields = {
        field: getattr(seed, field)
        for field in _SEED_FIELD_WEIGHTS
    }

    style_ranks = {key: rank for rank, key in enumerate(_STYLE_DEFAULT_ORDER)}
    styles_by_key = {style.stable_key: style for style in eligible_styles}
    style_scores: dict[str, tuple[int, int]] = {}
    for key, profile in _STYLE_PROFILES.items():
        style_scores[key] = (
            _profile_score(profile, seed_fields, _SEED_FIELD_WEIGHTS),
            _profile_score(profile, engine_fields, _ENGINE_FIELD_WEIGHTS),
        )
    selected_style_keys = sorted(
        styles_by_key,
        key=lambda key: (
            -sum(style_scores[key]),
            style_ranks[key],
            key,
        ),
    )[:3]
    style_refs = tuple(
        _style_ref(
            styles_by_key[key],
            seed_score=style_scores[key][0],
            engine_score=style_scores[key][1],
        )
        for key in selected_style_keys
    )

    category_ranks = {
        category: rank for rank, category in enumerate(_CATEGORY_DEFAULT_ORDER)
    }
    raw_category_scores = {
        category: (
            _profile_score(profile, seed_fields, _SEED_FIELD_WEIGHTS)
            + _profile_score(profile, engine_fields, _ENGINE_FIELD_WEIGHTS)
        )
        for category, profile in _CATEGORY_PROFILES.items()
    }
    category_scores = {
        category: score if score >= _CATEGORY_SIGNAL_THRESHOLD else 0
        for category, score in raw_category_scores.items()
    }
    positive_categories = sum(score > 0 for score in category_scores.values())
    card_target = max(2, min(4, positive_categories))
    category_order = sorted(
        ASSET_CATEGORIES,
        key=lambda category: (
            -category_scores[category],
            category_ranks[category],
            category,
        ),
    )
    context_tokens = _text_tokens(" ".join((*seed_fields.values(), *engine_fields.values())))
    ranked_by_category: dict[
        str, list[tuple[ExperienceCardRevision, int]]
    ] = {}
    for category in category_order:
        cards = [
            card
            for card in eligible_cards
            if card.category == category
        ]
        ranked_by_category[category] = sorted(
            (
                (
                    card,
                    (
                        overlap_count
                        if (overlap_count := len(context_tokens & _text_tokens(_card_text(card)))) >= 2
                        else 0
                    ),
                )
                for card in cards
            ),
            key=lambda item: (-item[1], item[0].stable_key),
        )
    selected_cards: list[tuple[ExperienceCardRevision, int]] = []
    for category in category_order:
        ranked_cards = ranked_by_category[category]
        if not ranked_cards:
            continue
        selected_cards.append(ranked_cards[0])
        if len(selected_cards) == card_target:
            break
    if len(selected_cards) < card_target:
        selected_keys = {
            card.stable_key for card, _ in selected_cards
        }
        remaining = sorted(
            (
                (card, overlap)
                for category in category_order
                for card, overlap in ranked_by_category[category]
                if card.stable_key not in selected_keys
            ),
            key=lambda item: (
                -category_scores[item[0].category],
                category_ranks[item[0].category],
                -item[1],
                item[0].stable_key,
            ),
        )
        selected_cards.extend(
            remaining[: card_target - len(selected_cards)]
        )
    card_refs = tuple(
        _card_ref(
            card,
            category_score=category_scores[card.category],
            overlap_score=overlap,
        )
        for card, overlap in selected_cards
    )

    hash_payload = {
        "version": RECOMMENDATION_VERSION,
        "seedHash": seed_hash,
        "engineHash": engine_hash,
        "styles": [item.model_dump(mode="json") for item in style_refs],
        "experienceCards": [item.model_dump(mode="json") for item in card_refs],
    }
    return AssetRecommendationResult(
        recommendation_version=RECOMMENDATION_VERSION,
        seed_hash=seed_hash,
        engine_hash=engine_hash,
        styles=style_refs,
        experience_cards=card_refs,
        recommendation_hash=canonical_hash(hash_payload),
    )
