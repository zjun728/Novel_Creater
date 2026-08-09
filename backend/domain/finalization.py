"""Closed immutable values for quality review and atomic finalization."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum, StrEnum
from hashlib import sha256
import json
from typing import Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from backend.domain.canon import (
    AssertionOperator,
    CanonValidationError,
    EntityType,
    FactKind,
    ValueCardinality,
    freeze_json,
    thaw_json,
)


Hash = str
_HASH_PATTERN = r"^[0-9a-f]{64}$"


class FinalizationState(StrEnum):
    PREPARING = "preparing"
    AWAITING_AUTHOR = "awaiting_author"
    COMMITTING = "committing"
    COMMITTED = "committed"
    INVALIDATED = "invalidated"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ChangeSetSource(StrEnum):
    EXTRACTION = "extraction"
    AUTHOR_CORRECTION = "author_correction"


class QualityReportStatus(StrEnum):
    COMPLETED = "completed"
    QUALITY_NOT_COMPLETED = "quality_not_completed"


class QualityDimension(StrEnum):
    PLOT_EFFECTIVENESS = "plot_effectiveness"
    CONTENT_RICHNESS = "content_richness"
    CHARACTER_VITALITY = "character_vitality"
    DIALOGUE_CREDIBILITY = "dialogue_credibility"
    EMOTIONAL_NATURALNESS = "emotional_naturalness"
    CONTINUITY = "continuity"
    PACING = "pacing"
    STYLE_STABILITY = "style_stability"
    AI_FLAVOR = "ai_flavor"
    READING_MOTIVATION = "reading_motivation"


class HardBlockCode(StrEnum):
    CANON_CONFLICT = "canon_conflict"
    TIMELINE_CONFLICT = "timeline_conflict"
    STATE_CONFLICT = "state_conflict"
    EMPTY_CANDIDATE = "empty_candidate"
    TECHNICAL_TRUNCATION = "technical_truncation"
    CANDIDATE_HASH_DRIFT = "candidate_hash_drift"
    SESSION_DRIFT = "session_drift"
    PLANNING_DRIFT = "planning_drift"
    OUTLINE_DRIFT = "outline_drift"
    DETERMINISTIC_COPY = "deterministic_copy"
    PRECHECK_INCOMPLETE = "precheck_incomplete"


class ProgressTargetType(StrEnum):
    STORY_BLOCK = "story_block"
    STAGE = "stage"
    SCENE_TASK = "scene_task"


class ProgressStatus(StrEnum):
    STARTED = "started"
    ADVANCED = "advanced"
    COMPLETED = "completed"


class PlanningTargetType(StrEnum):
    VOLUME = "volume"
    PLOT = "plot"
    STORY_BLOCK = "story_block"
    STAGE = "stage"
    SCENE_TASK = "scene_task"


_PLANNING_FIELDS = {
    PlanningTargetType.VOLUME: frozenset({
        "title", "coreChange", "mainPressure", "ensembleFocus",
        "forbiddenEvents",
    }),
    PlanningTargetType.PLOT: frozenset({
        "title", "storyQuestion", "futureDirection", "expectedPayoff",
        "relatedCharacters",
    }),
    PlanningTargetType.STORY_BLOCK: frozenset({
        "title", "entrySituation", "blockGoal", "mainPressure",
        "expectedChange", "openQuestions", "involvedCharacters",
    }),
    PlanningTargetType.STAGE: frozenset({
        "title", "purpose", "dramaticQuestion",
    }),
    PlanningTargetType.SCENE_TASK: frozenset({
        "task", "completionEvidence",
    }),
}


class _StrictValue(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        populate_by_name=False,
    )

    @model_validator(mode="before")
    @classmethod
    def accept_json_arrays(cls, value):
        if isinstance(value, Mapping):
            for item in value.values():
                if isinstance(item, str) and not item.strip():
                    raise ValueError("string values must be trimmed non-empty text")
            return {
                key: tuple(item) if isinstance(item, list) else item
                for key, item in value.items()
            }
        return value


def _enum(enum_type, value):
    if isinstance(value, enum_type):
        return value
    return enum_type(value)


def _strict_json(value: object, field_name: str) -> object:
    if type(value) is tuple:
        value = list(value)
    try:
        return freeze_json(value, field_name=field_name)
    except CanonValidationError as exc:
        raise ValueError(f"{field_name} must contain strict JSON") from exc


def _public_json(value: object) -> object:
    if isinstance(value, BaseModel):
        return _public_json(value.model_dump(by_alias=True, mode="python"))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {key: _public_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_public_json(item) for item in value]
    if isinstance(value, list):
        return [_public_json(item) for item in value]
    return thaw_json(value)


class EvidenceLocation(_StrictValue):
    start_scalar: int = Field(alias="startScalar", ge=0)
    end_scalar: int = Field(alias="endScalar", ge=1)
    excerpt_hash: Hash = Field(alias="excerptHash", pattern=_HASH_PATTERN)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def range_is_half_open(self) -> Self:
        if self.end_scalar <= self.start_scalar:
            raise ValueError("evidence range must be non-empty and half-open")
        return self


class EntityChange(_StrictValue):
    id: str = Field(min_length=1, max_length=100)
    entity_type: EntityType = Field(alias="entityType")
    canonical_name: str = Field(alias="canonicalName", min_length=1, max_length=200)

    @field_validator("entity_type", mode="before")
    @classmethod
    def parse_entity_type(cls, value):
        return _enum(EntityType, value)


class AliasChange(_StrictValue):
    id: str = Field(min_length=1, max_length=100)
    entity_id: str = Field(alias="entityId", min_length=1, max_length=100)
    alias: str = Field(min_length=1, max_length=200)


class CanonEventChange(_StrictValue):
    id: str = Field(min_length=1, max_length=100)
    entity_id: str | None = Field(alias="entityId", max_length=100)
    fact_kind: FactKind = Field(alias="factKind")
    field_path: str = Field(alias="fieldPath", min_length=1, max_length=200)
    value: object
    evidence: EvidenceLocation
    effective_start_chapter: int | None = Field(
        alias="effectiveStartChapter", default=None, ge=1,
    )
    effective_end_chapter: int | None = Field(
        alias="effectiveEndChapter", default=None, ge=1,
    )
    assertion_operator: AssertionOperator = Field(alias="assertionOperator")
    value_cardinality: ValueCardinality = Field(alias="valueCardinality")

    @field_validator("fact_kind", mode="before")
    @classmethod
    def parse_fact_kind(cls, value):
        return _enum(FactKind, value)

    @field_validator("assertion_operator", mode="before")
    @classmethod
    def parse_operator(cls, value):
        return _enum(AssertionOperator, value)

    @field_validator("value_cardinality", mode="before")
    @classmethod
    def parse_cardinality(cls, value):
        return _enum(ValueCardinality, value)

    @field_validator("value", mode="before")
    @classmethod
    def freeze_value(cls, value):
        return _strict_json(value, "Canon event value")

    @model_validator(mode="after")
    def chapter_range_is_ordered(self) -> Self:
        if (
            self.effective_start_chapter is not None
            and self.effective_end_chapter is not None
            and self.effective_end_chapter < self.effective_start_chapter
        ):
            raise ValueError("effective chapter range is reversed")
        return self


class StoryProgressEvent(_StrictValue):
    id: str = Field(min_length=1, max_length=100)
    target_type: ProgressTargetType = Field(alias="targetType")
    target_id: str = Field(alias="targetId", min_length=1, max_length=100)
    status: ProgressStatus
    evidence: EvidenceLocation

    @field_validator("target_type", mode="before")
    @classmethod
    def parse_target_type(cls, value):
        return _enum(ProgressTargetType, value)

    @field_validator("status", mode="before")
    @classmethod
    def parse_status(cls, value):
        return _enum(ProgressStatus, value)


class PlanningPatch(_StrictValue):
    id: str = Field(min_length=1, max_length=100)
    target_type: PlanningTargetType = Field(alias="targetType")
    target_id: str = Field(alias="targetId", min_length=1, max_length=100)
    expected_revision: int = Field(alias="expectedRevision", ge=1)
    expected_hash: Hash = Field(alias="expectedHash", pattern=_HASH_PATTERN)
    field_path: str = Field(alias="fieldPath", min_length=1, max_length=64)
    replacement: object
    evidence: EvidenceLocation

    @field_validator("target_type", mode="before")
    @classmethod
    def parse_target_type(cls, value):
        return _enum(PlanningTargetType, value)

    @field_validator("replacement", mode="before")
    @classmethod
    def freeze_replacement(cls, value):
        return _strict_json(value, "Planning replacement")

    @model_validator(mode="after")
    def field_is_closed_for_target(self) -> Self:
        if self.field_path not in _PLANNING_FIELDS[self.target_type]:
            raise ValueError("planning fieldPath is not allowed for targetType")
        return self


class PlanningSuggestion(_StrictValue):
    id: str = Field(min_length=1, max_length=100)
    target_id: str | None = Field(alias="targetId", default=None, max_length=100)
    message: str = Field(min_length=1, max_length=2000)
    evidence: EvidenceLocation


class FinalizationChangeSet(_StrictValue):
    schema_version: Literal["finalization-changeset-v1"] = Field(
        alias="schemaVersion",
    )
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=4000)
    existing_entity_ids: tuple[str, ...] = Field(
        alias="existingEntityIds", max_length=2048,
    )
    entities: tuple[EntityChange, ...] = Field(max_length=256)
    aliases: tuple[AliasChange, ...] = Field(max_length=512)
    canon_events: tuple[CanonEventChange, ...] = Field(
        alias="canonEvents", max_length=2048,
    )
    story_progress_events: tuple[StoryProgressEvent, ...] = Field(
        alias="storyProgressEvents", max_length=1024,
    )
    planning_patches: tuple[PlanningPatch, ...] = Field(
        alias="planningPatches", max_length=256,
    )
    planning_suggestions: tuple[PlanningSuggestion, ...] = Field(
        alias="planningSuggestions", max_length=256,
    )

    @model_validator(mode="after")
    def identities_and_references_are_closed(self) -> Self:
        all_changes = (
            *self.entities,
            *self.aliases,
            *self.canon_events,
            *self.story_progress_events,
            *self.planning_patches,
            *self.planning_suggestions,
        )
        ids = [item.id for item in all_changes]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate change id")
        if len(self.existing_entity_ids) != len(set(self.existing_entity_ids)):
            raise ValueError("duplicate existing entity id")
        allowed_entities = set(self.existing_entity_ids)
        new_entity_ids = {item.id for item in self.entities}
        if allowed_entities & new_entity_ids:
            raise ValueError("existing and new entity ids must be disjoint")
        allowed_entities.update(new_entity_ids)
        for item in self.aliases:
            if item.entity_id not in allowed_entities:
                raise ValueError("alias entityId is outside the closed entity set")
        for item in self.canon_events:
            if item.entity_id is not None and item.entity_id not in allowed_entities:
                raise ValueError("Canon event entityId is outside the closed entity set")
        return self


class FinalizationAuthority(_StrictValue):
    project_id: str = Field(alias="projectId", min_length=1, max_length=100)
    chapter_session_id: str = Field(
        alias="chapterSessionId", min_length=1, max_length=100,
    )
    candidate_id: str = Field(alias="candidateId", min_length=1, max_length=100)
    candidate_hash: Hash = Field(alias="candidateHash", pattern=_HASH_PATTERN)
    expected_canon_revision: int = Field(alias="expectedCanonRevision", ge=0)
    expected_planning_hash: Hash = Field(
        alias="expectedPlanningHash", pattern=_HASH_PATTERN,
    )
    expected_outline_hash: Hash = Field(
        alias="expectedOutlineHash", pattern=_HASH_PATTERN,
    )
    context_manifest_hash: Hash = Field(
        alias="contextManifestHash", pattern=_HASH_PATTERN,
    )
    idempotency_key: Hash = Field(alias="idempotencyKey", pattern=_HASH_PATTERN)
    request_fingerprint: Hash = Field(
        alias="requestFingerprint", pattern=_HASH_PATTERN,
    )


class ConfirmationPin(_StrictValue):
    expected_change_set_revision: int = Field(
        alias="expectedChangeSetRevision", ge=1,
    )
    expected_change_set_hash: Hash = Field(
        alias="expectedChangeSetHash", pattern=_HASH_PATTERN,
    )


class DeterministicBlock(_StrictValue):
    code: HardBlockCode
    message: str = Field(min_length=1, max_length=500)
    evidence: EvidenceLocation | None

    @field_validator("code", mode="before")
    @classmethod
    def parse_code(cls, value):
        return _enum(HardBlockCode, value)


class QualityFinding(_StrictValue):
    id: str = Field(min_length=1, max_length=100)
    dimension: QualityDimension
    reason: str = Field(min_length=1, max_length=2000)
    suggested_action: str = Field(
        alias="suggestedAction", min_length=1, max_length=2000,
    )
    evidence: EvidenceLocation

    @field_validator("dimension", mode="before")
    @classmethod
    def parse_dimension(cls, value):
        return _enum(QualityDimension, value)


class QualityReportPayload(_StrictValue):
    status: QualityReportStatus
    deterministic_blocks: tuple[DeterministicBlock, ...] = Field(
        alias="deterministicBlocks", max_length=128,
    )
    findings: tuple[QualityFinding, ...] = Field(max_length=256)

    @field_validator("status", mode="before")
    @classmethod
    def parse_status(cls, value):
        return _enum(QualityReportStatus, value)

    @model_validator(mode="after")
    def finding_ids_are_unique(self) -> Self:
        ids = [item.id for item in self.findings]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate quality finding id")
        if (
            self.status is QualityReportStatus.QUALITY_NOT_COMPLETED
            and self.findings
        ):
            raise ValueError("quality_not_completed cannot contain model findings")
        return self


def change_set_payload(value: FinalizationChangeSet) -> dict[str, Any]:
    if type(value) is not FinalizationChangeSet:
        raise TypeError("value must be a FinalizationChangeSet")
    result = _public_json(value)
    if not isinstance(result, dict):
        raise TypeError("FinalizationChangeSet serialization must be an object")
    return result


def change_set_hash(value: FinalizationChangeSet) -> str:
    payload = json.dumps(
        change_set_payload(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "ChangeSetSource",
    "ConfirmationPin",
    "EvidenceLocation",
    "FinalizationAuthority",
    "FinalizationChangeSet",
    "FinalizationState",
    "QualityReportPayload",
    "QualityReportStatus",
    "change_set_hash",
    "change_set_payload",
]
