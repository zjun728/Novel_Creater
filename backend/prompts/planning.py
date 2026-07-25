"""Closed, bounded prompt construction for Planning generation."""

from __future__ import annotations

from collections.abc import Mapping
import json
import math
import re
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from backend.domain.contracts import (
    MAX_CHAPTER_WORD_RANGE_VALUE,
    MAX_EXPECTED_CHAPTER_COUNT,
    MAX_EXPECTED_VOLUME_COUNT,
    MAX_TARGET_TOTAL_WORDS,
)
from backend.domain.json_contracts import canonical_json
from backend.domain.planning import DraftPlanningAggregate
from backend.security.provider_secrets import is_provider_secret_key


PLANNING_MAX_PROMPT_BYTES = 96 * 1024
PLANNING_STORY_CONTEXT_MAX_BYTES = 40 * 1024
PLANNING_STORY_TEXT_MAX_LENGTH = 1_600
PLANNING_STORY_ITEM_TEXT_MAX_LENGTH = 800
PLANNING_STORY_SEED_TEXT_MAX_LENGTH = 1_000
PLANNING_STORY_LIST_MAX_ITEMS = 6
_SAFE_ERROR = "Planning prompt input invalid"
_PRIVATE_TEXT = re.compile(
    r"(?:api[\s_-]*key|base[\s_-]*url|access[\s_-]*token"
    r"|bearer[\s_-]*token|token|password|dsn)\s*[:=]\s*\S+"
    r"|(?:source[\s_.-]*document[\s_.-]*text"
    r"|raw[\s_.-]*source(?:[\s_.-]*(?:text|content|payload))?"
    r"|corpus(?:[\s_.-]*(?:text|content|payload|fragment))?)"
    r"\s*[:=]\s*\S+"
    r"|\bauthorization\s*:\s*[A-Za-z][A-Za-z0-9_-]*\s+\S+"
    r"|\bauthorization\s*:?\s*bearer\s+\S+"
    r"|\bbearer\s+[A-Za-z0-9][A-Za-z0-9._~+/=-]{7,}"
    r"|\bgh[pousr]_[A-Za-z0-9_]{12,}"
    r"|\bgithub_pat_[A-Za-z0-9_]{12,}"
    r"|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
    r"|\bAIza[A-Za-z0-9_-]{20,}"
    r"|(?:mysql|postgres(?:ql)?|mariadb)://\S+",
    re.IGNORECASE,
)
_PERCENT_TOKEN_SEPARATOR = re.compile(r"%(?:2d|5f)", re.IGNORECASE)
_PROVIDER_TOKEN_CANDIDATE = re.compile(
    r"(?<![A-Za-z0-9])(?:sk|rk|pk)[_-]"
    r"(?P<body>[A-Za-z0-9][A-Za-z0-9._-]{31,})",
    re.IGNORECASE,
)
_STRICT_MANIFEST = ConfigDict(
    strict=True,
    frozen=True,
    extra="forbid",
    hide_input_in_errors=True,
)


class PlanningGenerationBasis(BaseModel):
    model_config = _STRICT_MANIFEST

    project_id: str = Field(alias="projectId", min_length=1)
    basis_hash: str = Field(
        alias="basisHash",
        pattern=r"^[0-9a-f]{64}$",
    )
    draft_revision: int = Field(alias="draftRevision", ge=1)
    draft_hash: str = Field(
        alias="draftHash",
        pattern=r"^[0-9a-f]{64}$",
    )


StoryText = Annotated[
    str,
    Field(min_length=1, max_length=PLANNING_STORY_TEXT_MAX_LENGTH),
]
StoryItemText = Annotated[
    str,
    Field(min_length=1, max_length=PLANNING_STORY_ITEM_TEXT_MAX_LENGTH),
]
StorySeedText = Annotated[
    str,
    Field(min_length=1, max_length=PLANNING_STORY_SEED_TEXT_MAX_LENGTH),
]


class PlanningSeedContext(BaseModel):
    model_config = _STRICT_MANIFEST

    title: StorySeedText
    genre: StorySeedText
    logline: StorySeedText
    protagonist: StorySeedText
    desire: StorySeedText
    core_conflict: StorySeedText = Field(alias="coreConflict")
    world_pressure: StorySeedText = Field(alias="worldPressure")
    opening_hook: StorySeedText = Field(alias="openingHook")
    differentiation: StorySeedText


class PlanningStoryItem(BaseModel):
    model_config = _STRICT_MANIFEST

    id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    text: StoryItemText


class PlanningEngineRole(BaseModel):
    model_config = _STRICT_MANIFEST

    role: StoryItemText
    purpose: StoryItemText


class PlanningEngineContext(BaseModel):
    model_config = _STRICT_MANIFEST

    name: StoryText
    story_promise: StoryText = Field(alias="storyPromise")
    protagonist_desire: StoryText = Field(alias="protagonistDesire")
    sustained_pressure: StoryText = Field(alias="sustainedPressure")
    growth_direction: StoryText = Field(alias="growthDirection")
    conflict_loop: StoryText = Field(alias="conflictLoop")
    ensemble_roles: tuple[PlanningEngineRole, ...] = Field(
        alias="ensembleRoles",
        min_length=1,
        max_length=PLANNING_STORY_LIST_MAX_ITEMS,
    )
    advantage_and_cost: StoryText = Field(alias="advantageAndCost")
    satisfaction_sources: tuple[StoryItemText, ...] = Field(
        alias="satisfactionSources",
        min_length=1,
        max_length=PLANNING_STORY_LIST_MAX_ITEMS,
    )
    long_form_variation: tuple[StoryItemText, ...] = Field(
        alias="longFormVariation",
        min_length=1,
        max_length=PLANNING_STORY_LIST_MAX_ITEMS,
    )
    ending_anchor: StoryText = Field(alias="endingAnchor")
    risks: tuple[StoryItemText, ...] = Field(
        min_length=1,
        max_length=PLANNING_STORY_LIST_MAX_ITEMS,
    )
    differentiation: StoryText

    @field_validator(
        "ensemble_roles",
        "satisfaction_sources",
        "long_form_variation",
        "risks",
        mode="before",
    )
    @classmethod
    def accept_json_array(cls, value):
        return tuple(value) if isinstance(value, list) else value


class PlanningLongFormCapacity(BaseModel):
    model_config = _STRICT_MANIFEST

    target_total_words: int = Field(
        alias="targetTotalWords",
        strict=True,
        gt=0,
        le=MAX_TARGET_TOTAL_WORDS,
    )
    expected_volume_count: int = Field(
        alias="expectedVolumeCount",
        strict=True,
        gt=0,
        le=MAX_EXPECTED_VOLUME_COUNT,
    )
    expected_chapter_count: int = Field(
        alias="expectedChapterCount",
        strict=True,
        gt=0,
        le=MAX_EXPECTED_CHAPTER_COUNT,
    )
    chapter_word_range_preference: tuple[int, int] = Field(
        alias="chapterWordRangePreference",
    )

    @field_validator("chapter_word_range_preference", mode="before")
    @classmethod
    def accept_json_array(cls, value):
        return tuple(value) if isinstance(value, list) else value

    @field_validator("chapter_word_range_preference")
    @classmethod
    def validate_chapter_range(cls, value):
        if (
            any(
                type(item) is not int
                or item <= 0
                or item > MAX_CHAPTER_WORD_RANGE_VALUE
                for item in value
            )
            or value[0] > value[1]
        ):
            raise ValueError("chapter word range is invalid")
        return value


class PlanningStoryContext(BaseModel):
    model_config = _STRICT_MANIFEST

    premise: StoryText
    seed: PlanningSeedContext
    engine: PlanningEngineContext
    long_form_capacity: PlanningLongFormCapacity = Field(
        alias="longFormCapacity",
    )
    protagonist: StoryText
    core_characters: tuple[PlanningStoryItem, ...] = Field(
        alias="coreCharacters",
        min_length=1,
        max_length=PLANNING_STORY_LIST_MAX_ITEMS,
    )
    relationship_dynamics: tuple[PlanningStoryItem, ...] = Field(
        alias="relationshipDynamics",
        min_length=1,
        max_length=PLANNING_STORY_LIST_MAX_ITEMS,
    )
    world_rules: tuple[PlanningStoryItem, ...] = Field(
        alias="worldRules",
        min_length=1,
        max_length=PLANNING_STORY_LIST_MAX_ITEMS,
    )
    power_or_progression_system: StoryText = Field(
        alias="powerOrProgressionSystem",
    )
    long_term_conflicts: tuple[PlanningStoryItem, ...] = Field(
        alias="longTermConflicts",
        min_length=1,
        max_length=PLANNING_STORY_LIST_MAX_ITEMS,
    )
    tone_and_narrative_boundaries: StoryText = Field(
        alias="toneAndNarrativeBoundaries",
    )
    prohibited_directions: tuple[StoryItemText, ...] = Field(
        alias="prohibitedDirections",
        max_length=PLANNING_STORY_LIST_MAX_ITEMS,
    )
    continuity_guardrails: tuple[PlanningStoryItem, ...] = Field(
        alias="continuityGuardrails",
        min_length=1,
        max_length=PLANNING_STORY_LIST_MAX_ITEMS,
    )
    author_notes: StoryText | None = Field(default=None, alias="authorNotes")

    @field_validator(
        "core_characters",
        "relationship_dynamics",
        "world_rules",
        "long_term_conflicts",
        "prohibited_directions",
        "continuity_guardrails",
        mode="before",
    )
    @classmethod
    def accept_json_array(cls, value):
        return tuple(value) if isinstance(value, list) else value


class PlanningGenerationManifest(BaseModel):
    model_config = _STRICT_MANIFEST

    basis: PlanningGenerationBasis
    draft: DraftPlanningAggregate
    story_context: PlanningStoryContext = Field(alias="storyContext")

    @model_validator(mode="after")
    def reject_private_material(self) -> Self:
        snapshot = self.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        )
        if (
            len(
                canonical_json(snapshot["storyContext"]).encode("utf-8")
            )
            > PLANNING_STORY_CONTEXT_MAX_BYTES
        ):
            raise ValueError(_SAFE_ERROR)
        _validate_safe_manifest(snapshot)
        return self


def _is_private_manifest_key(value: object) -> bool:
    if not isinstance(value, str):
        return True
    normalized = "".join(
        character
        for character in value.casefold()
        if character.isalnum()
    )
    return (
        is_provider_secret_key(normalized)
        or normalized in {"accesstoken", "bearertoken"}
        or "corpus" in normalized
        or "rawsource" in normalized
        or (
            "sourcedocument" in normalized
            and any(
                marker in normalized
                for marker in ("text", "content", "payload")
            )
        )
        or normalized in {
            "rawtext",
            "sourcetext",
            "documenttext",
            "sourcedocument",
        }
    )


def _validate_safe_manifest(value: Mapping[str, object]) -> None:
    pending: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 10_000 or depth > 32:
            raise ValueError(_SAFE_ERROR)
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if _is_private_manifest_key(key):
                    raise ValueError(_SAFE_ERROR)
                pending.append((nested, depth + 1))
        elif isinstance(item, (list, tuple)):
            pending.extend((nested, depth + 1) for nested in item)
        elif isinstance(item, str):
            if planning_text_contains_private_material(item):
                raise ValueError(_SAFE_ERROR)
        elif item is not None and not isinstance(
            item, (int, float, bool)
        ):
            raise ValueError(_SAFE_ERROR)


def _normalized_token_separators(value: str) -> str:
    return _PERCENT_TOKEN_SEPARATOR.sub(
        lambda match: (
            "-" if match.group(0).casefold() == "%2d" else "_"
        ),
        value,
    )


def _looks_like_random_provider_token(body: str) -> bool:
    alphanumeric = tuple(
        character for character in body if character.isalnum()
    )
    if len(alphanumeric) < 32:
        return False
    digit_count = sum(character.isdigit() for character in alphanumeric)
    lowered = tuple(character.casefold() for character in alphanumeric)
    frequencies = {
        character: lowered.count(character)
        for character in set(lowered)
    }
    unique_count = len(frequencies)
    entropy = -sum(
        (count / len(lowered)) * math.log2(count / len(lowered))
        for count in frequencies.values()
    )
    has_mixed_case = (
        any(character.islower() for character in alphanumeric)
        and any(character.isupper() for character in alphanumeric)
    )
    return (
        unique_count >= 16
        and unique_count / len(lowered) >= 0.45
        and entropy >= 3.8
        and (
            has_mixed_case
            or (digit_count >= 8 and unique_count >= 20)
        )
    )


def planning_text_contains_private_material(value: str) -> bool:
    if _PRIVATE_TEXT.search(value):
        return True
    normalized = _normalized_token_separators(value)
    for candidate in _PROVIDER_TOKEN_CANDIDATE.finditer(normalized):
        body = candidate.group("body")
        if _looks_like_random_provider_token(body):
            return True
    return False


def validate_planning_story_context_candidate(
    value: Mapping[str, object],
) -> None:
    _validate_safe_manifest(value)


def build_planning_messages(
    *,
    manifest: PlanningGenerationManifest | Mapping[str, object],
    author_instructions: str,
) -> tuple[dict[str, str], ...]:
    """Build one JSON-only Planning request from a frozen, secret-free manifest."""

    try:
        if not isinstance(author_instructions, str):
            raise ValueError(_SAFE_ERROR)
        author_instructions.encode("utf-8")
        if planning_text_contains_private_material(author_instructions):
            raise ValueError(_SAFE_ERROR)
        manifest_value = PlanningGenerationManifest.model_validate(
            manifest,
            strict=True,
        )
        manifest_snapshot = manifest_value.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        )
        manifest_snapshot["draft"]["activeStoryBlockRef"] = (
            manifest_value.draft.active_story_block_ref
        )
        _validate_safe_manifest(manifest_snapshot)
        instruction = {
            "task": "Generate one complete Planning draft",
            "editableScope": ["volumes", "plots"],
            "preserveScope": [
                "activeStoryBlockRef",
                "storyBlocks",
                "storyBlocks[].stages",
                "storyBlocks[].stages[].sceneTasks",
            ],
            "rules": [
                "Return exactly one JSON object matching outputContract.",
                "Create or revise Volume narrative direction and continuing "
                "Plot lines.",
                "Copy supplied StoryBlock, Stage, and SceneTask identities, "
                "order, references, and content unchanged.",
                "Do not add, remove, summarize, or rewrite supplied preserved content.",
                "Keep every relation inside the returned Planning draft.",
                "Do not return commentary, markdown, prompt text, or evidence.",
            ],
        }
        evidence = {
            "manifest": manifest_snapshot,
            "authorInstructions": author_instructions,
            "outputContract": DraftPlanningAggregate.model_json_schema(
                by_alias=True
            ),
        }
        messages = (
            {"role": "system", "content": canonical_json(instruction)},
            {"role": "user", "content": canonical_json(evidence)},
        )
        rendered = json.dumps(
            messages,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(rendered) > PLANNING_MAX_PROMPT_BYTES:
            raise ValueError(_SAFE_ERROR)
        return messages
    except (
        UnicodeError,
        TypeError,
        ValueError,
        OverflowError,
        RecursionError,
    ):
        raise ValueError(_SAFE_ERROR) from None


__all__ = (
    "PLANNING_MAX_PROMPT_BYTES",
    "PLANNING_STORY_ITEM_TEXT_MAX_LENGTH",
    "PLANNING_STORY_CONTEXT_MAX_BYTES",
    "PLANNING_STORY_LIST_MAX_ITEMS",
    "PLANNING_STORY_SEED_TEXT_MAX_LENGTH",
    "PLANNING_STORY_TEXT_MAX_LENGTH",
    "PlanningGenerationBasis",
    "PlanningGenerationManifest",
    "PlanningEngineContext",
    "PlanningEngineRole",
    "PlanningLongFormCapacity",
    "PlanningSeedContext",
    "PlanningStoryContext",
    "PlanningStoryItem",
    "build_planning_messages",
    "planning_text_contains_private_material",
    "validate_planning_story_context_candidate",
)
