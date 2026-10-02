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
    model_serializer,
)
from backend.domain.planning_expansion import PlanningExpansion, PlanningContinuationOutput, PlanningBlockAdjustmentOutput

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
    expansion: PlanningExpansion | None = None

    @model_serializer(mode="wrap")
    def omit_legacy_expansion(self, handler):
        result = handler(self)
        if self.expansion is None:
            result.pop("expansion", None)
        return result

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
                "For every new Volume or Plot, set one non-empty clientNodeKey "
                "and omit id, revision, and contentHash.",
                "Copy supplied StoryBlock, Stage, and SceneTask identities, "
                "order, references, and content unchanged.",
                "Copy activeStoryBlockRef and storyBlocks as an exact deep copy. "
                "When they are null and empty, return null and [] exactly.",
                "Never create a StoryBlock, Stage, or SceneTask in this call.",
                "Do not add, remove, summarize, or rewrite supplied preserved content.",
                "Keep every relation inside the returned Planning draft.",
                "Do not return commentary, markdown, prompt text, or evidence.",
            ],
        }
        if manifest_value.expansion is not None:
            manifest_snapshot["expansion"] = manifest_value.expansion.model_dump(mode="json", by_alias=True)
            instruction = {
                "task": "Prepare author-reviewed future planning: " + manifest_value.expansion.mode,
                "rules": [
                    "Return exactly one JSON object matching outputContract, without commentary.",
                    "Use confirmed storyContext, the previous final chapter and actual progress. Future plans are not accomplished facts.",
                    "Every new node at every depth needs a unique clientNodeKey; omit id/revision/contentHash for new nodes.",
                    "initial: generate volumes, plot lines and exactly the first story block in the first volume, with meaningful stages and scene tasks and completionEvidence. Set activeStoryBlockRef to it.",
                    "next_block/next_volume: copy all existing volumes, plots and storyBlocks including nested identities and content unchanged. Never remove or rewrite them.",
                    "Reuse targetVolumeRef and targetBlockRef when supplied. If targetBlockRef is null, append exactly one complete block; if targetVolumeRef is null, append exactly one next volume. Order new nodes after existing nodes.",
                    "Set activeStoryBlockRef to the selected next block; every stage requires actionable sceneTasks. Keep all relations within this draft and reuse existing plot lines for continuation.",
                    "The output remains an unconfirmed draft. Do not claim any planned events already happened.",
                ],
            }
            if manifest_value.expansion.mode != "initial":
                instruction = {
                    "task": ("当前卷已结束。必须准备下一卷的第一个故事块。" if manifest_value.expansion.mode == "next_volume"
                             else "当前故事块已完成。准备同一卷中的下一个故事块。"),
                    "mode": manifest_value.expansion.mode,
                    "rules": [
                        "Return exactly one JSON object with only nextVolume and nextStoryBlock according to outputContract. Do not return or copy the existing draft.",
                        "The current active story block has finished. Prepare the NEXT block, never return the current block.",
                        "If targetBlockRef is null, nextStoryBlock MUST be a new complete block with stages and sceneTasks, linked to existing plot IDs. Otherwise return nextStoryBlock:null to reuse that target.",
                        "If targetVolumeRef is null, nextVolume MUST be a new volume and nextStoryBlock.volumeRef must equal its clientNodeKey. Otherwise return nextVolume:null and use targetVolumeRef exactly.",
                        "Every new node at every depth needs a unique clientNodeKey. Omit id/revision/contentHash. Order the new volume/block after all existing volumes/blocks respectively.",
                        "Use confirmed storyContext, previous final chapter and actual progress. Preserve unresolved story questions; planned events are not completed facts.",
                        "Each stage needs concrete sceneTasks and completionEvidence. Output is future planning awaiting author review.",
                    ],
                }
                expansion = manifest_value.expansion
                instruction["requiredOutput"] = {
                    "nextVolume": ("MUST be a NEW volume object, NOT null" if expansion.target_volume_ref is None
                                   else "MUST be null; reuse existing volume " + expansion.target_volume_ref),
                    "nextStoryBlock": ("MUST be a NEW complete story block object, NOT null" if expansion.target_block_ref is None
                                       else "MUST be null; reuse existing block " + expansion.target_block_ref),
                    "newVolumeOrder": max((v.order for v in manifest_value.draft.volumes), default=0) + 1,
                    "newStoryBlockOrder": max((b.order for b in manifest_value.draft.story_blocks), default=0) + 1,
                }
            if manifest_value.expansion.mode == "revise_block":
                instruction = {
                    "task": "按作者要求调整当前故事块尚未实施的未来安排，供作者对比确认。",
                    "rules": [
                        "Return exactly one JSON object with storyBlock matching outputContract.",
                        "Return the full adjusted current story block identified by targetBlockRef. Preserve its id/revision/contentHash, volumeRef, order and active lifecycle.",
                        "Change only future content requested in authorInstructions. Keep references to existing plots. Other volumes, plots and blocks are outside your output.",
                        "Keep every node listed in protectedNodeRefs as an EXACT deep copy, including content and identities. These stages or tasks already have actual progress and may not be changed or removed.",
                        "Keep existing node IDs, revision and contentHash; the server computes new revisions. New stages/tasks need unique clientNodeKey without id/revision/contentHash.",
                        "Retain existing child nodes. Unimplemented children can be edited or retired; never retire protected nodes. Include actionable active stages and sceneTasks with completionEvidence.",
                        "Actual progress and final chapter are facts; future planned events are not already completed.",
                    ],
                }
        evidence = {
            "manifest": manifest_snapshot,
            "authorInstructions": author_instructions,
            "outputContract": DraftPlanningAggregate.model_json_schema(
                by_alias=True
            ),
        }
        if manifest_value.expansion is not None and manifest_value.expansion.mode != "initial":
            evidence["outputContract"] = PlanningContinuationOutput.model_json_schema(by_alias=True)
            for field, target, node in (
                ("nextVolume", manifest_value.expansion.target_volume_ref, "DraftVolume"),
                ("nextStoryBlock", manifest_value.expansion.target_block_ref, "DraftStoryBlock"),
            ):
                evidence["outputContract"]["properties"][field] = (
                    {"$ref": "#/$defs/" + node} if target is None else {"type": "null"}
                )
        if manifest_value.expansion is not None and manifest_value.expansion.mode == "revise_block":
            evidence["outputContract"] = PlanningBlockAdjustmentOutput.model_json_schema(by_alias=True)
        if manifest_value.expansion is not None and manifest_value.expansion.mode.startswith('fill_'):
            from backend.domain.planning_completion import missing_block_fields, missing_volume_fields, completion_patch_schema
            from backend.domain.planning_expansion import node_ref
            expansion = manifest_value.expansion
            volume = next(v for v in manifest_value.draft.volumes if node_ref(v) == expansion.target_volume_ref)
            block = next((b for b in manifest_value.draft.story_blocks if node_ref(b) == expansion.target_block_ref), None)
            fill_volume = expansion.mode == 'fill_next_volume' and bool(missing_volume_fields(volume))
            fill_block = block is None or bool(missing_block_fields(block))
            instruction = {
                'task': '只补齐已有后续安排的缺失内容，保留作者已填写的每个字段，供作者核对后采用。',
                'mode': expansion.mode,
                'rules': [
                    'Return exactly one JSON object with nextVolume and nextStoryBlock according to outputContract, without commentary or markdown.',
                    'For an EXISTING target return ONLY its missing fields listed in outputContract, otherwise null. The server keeps all existing content and identity. Never copy or invent id, clientNodeKey, revision, contentHash, order, lifecycle or relations for an existing node.',
                    'Only fill blank text or empty arrays. Existing nonempty arrays must retain their exact order and length; their nodes may only have blank fields filled.',
                    'Never change or remove any implemented node listed in protectedNodeRefs. Do not rewrite other volumes, plots or blocks.',
                    'For missing stages/tasks add meaningful tasks and completionEvidence. New nodes need unique clientNodeKey without id/revision/contentHash.',
                    'When no target block exists, create exactly one complete first block in targetVolumeRef, ordered after existing blocks. Use existing plot IDs.',
                    'Use the previous final chapter and actual progress as facts; proposed future events have not happened. Output remains an unconfirmed draft.',
                ],
            }
            evidence['outputContract'] = PlanningContinuationOutput.model_json_schema(by_alias=True)
            for field, required, node in [('nextVolume', fill_volume, 'DraftVolume'), ('nextStoryBlock', fill_block, 'DraftStoryBlock')]:
                existing=volume if field=='nextVolume' else block
                evidence['outputContract']['properties'][field] = (
                    completion_patch_schema(existing,evidence['outputContract']['$defs'][node],evidence['outputContract']['$defs'])
                    if required and existing else {'$ref': '#/$defs/' + node} if required else {'type': 'null'})
            evidence['completionTargets']={
                'volume': volume.model_dump(mode='json',by_alias=True) if fill_volume else None,
                'storyBlock': block.model_dump(mode='json',by_alias=True) if block and fill_block else None,
                'missing': (missing_volume_fields(volume) if fill_volume else []) +
                           (missing_block_fields(block) if block and fill_block else ['首个故事块'] if fill_block else []),
            }
        if manifest_value.expansion is not None and manifest_value.expansion.mode in {"next_block", "next_volume"}:
            # Continuation returns only new nodes. Keep the full frozen draft for
            # server-side merging, but do not resend unrelated nested task history.
            detailed_refs = {
                manifest_value.draft.active_story_block_ref,
                manifest_value.expansion.target_block_ref,
            } - {None}
            for block in manifest_snapshot["draft"]["storyBlocks"]:
                if (block.get("id") or block.get("clientNodeKey")) not in detailed_refs:
                    block.pop("stages", None)
            evidence["planningContextScope"] = (
                "Only current and target blocks include full stages/tasks. Other "
                "blocks retain their narrative fields and unresolved questions; "
                "omitted task details remain unchanged on the server. This is "
                "planning context, not a complete draft or proof of completion."
            )
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
