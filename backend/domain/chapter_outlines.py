"""Strict immutable ChapterOutline values pinned to one Planning revision."""

from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.domain.json_contracts import canonical_hash
from backend.domain.planning import PlanningAggregate, PersistedNode


class ChapterOutlineDomainError(ValueError):
    """Raised when an Outline is not a closed slice of locked authorities."""


class _StrictOutlineValue(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
    )

    @model_validator(mode="before")
    @classmethod
    def accept_json_arrays(cls, value):
        if isinstance(value, dict):
            return {
                key: tuple(item) if isinstance(item, list) else item
                for key, item in value.items()
            }
        return value


class PlanningNodeRef(_StrictOutlineValue):
    id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    content_hash: str = Field(
        alias="contentHash",
        pattern=r"^[0-9a-f]{64}$",
    )


class OutlineCapacityPolicy(_StrictOutlineValue):
    target_min: int = Field(alias="targetMin", ge=1)
    target_max: int = Field(alias="targetMax", ge=1)
    soft_ceiling: int = Field(alias="softCeiling", ge=1)

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if not self.target_min <= self.target_max <= self.soft_ceiling:
            raise ValueError("invalid capacity order")
        return self


class EditableChapterOutlineContent(_StrictOutlineValue):
    schema_version: Literal["chapter-outline-draft-v1"] = Field(
        default="chapter-outline-draft-v1",
        alias="schemaVersion",
    )
    volume_ref: PlanningNodeRef | None = Field(
        default=None,
        alias="volumeRef",
    )
    story_block_ref: PlanningNodeRef | None = Field(
        default=None,
        alias="storyBlockRef",
    )
    stage_refs: tuple[PlanningNodeRef, ...] = Field(
        default=(),
        alias="stageRefs",
    )
    scene_task_refs: tuple[PlanningNodeRef, ...] = Field(
        default=(),
        alias="sceneTaskRefs",
    )
    chapter_goal: str = Field(
        default="",
        alias="chapterGoal",
        max_length=4000,
    )
    expected_characters: tuple[str, ...] = Field(
        default=(),
        alias="expectedCharacters",
    )
    continuation: tuple[str, ...] = ()
    planned_tasks: tuple[str, ...] = Field(
        default=(),
        alias="plannedTasks",
    )
    scenes: tuple[str, ...] = ()
    forbidden_early_events: tuple[str, ...] = Field(
        default=(),
        alias="forbiddenEarlyEvents",
    )


class DraftChapterOutline(_StrictOutlineValue):
    schema_version: Literal["chapter-outline-v1"] = Field(alias="schemaVersion")
    chapter_number: int = Field(alias="chapterNumber", ge=1)
    planning_revision_id: str = Field(alias="planningRevisionId", min_length=1)
    planning_revision: int = Field(alias="planningRevision", ge=1)
    planning_hash: str = Field(
        alias="planningHash",
        pattern=r"^[0-9a-f]{64}$",
    )
    volume_ref: PlanningNodeRef = Field(alias="volumeRef")
    story_block_ref: PlanningNodeRef = Field(alias="storyBlockRef")
    stage_refs: tuple[PlanningNodeRef, ...] = Field(
        alias="stageRefs",
        min_length=1,
    )
    scene_task_refs: tuple[PlanningNodeRef, ...] = Field(
        alias="sceneTaskRefs",
        min_length=1,
    )
    chapter_goal: str = Field(
        alias="chapterGoal",
        min_length=1,
        max_length=4000,
    )
    expected_characters: tuple[str, ...] = Field(alias="expectedCharacters")
    continuation: tuple[str, ...]
    planned_tasks: tuple[str, ...] = Field(alias="plannedTasks")
    scenes: tuple[str, ...] = Field(min_length=1)
    forbidden_early_events: tuple[str, ...] = Field(alias="forbiddenEarlyEvents")
    capacity_policy: OutlineCapacityPolicy = Field(alias="capacityPolicy")


class ChapterOutline(DraftChapterOutline):
    canon_revision: int = Field(alias="canonRevision", ge=0)
    projection_revision: int = Field(alias="projectionRevision", ge=0)
    projection_hash: str = Field(
        alias="projectionHash",
        pattern=r"^[0-9a-f]{64}$",
    )
    content_hash: str = Field(
        alias="contentHash",
        pattern=r"^[0-9a-f]{64}$",
    )


def _resolve_ref(
    ref: PlanningNodeRef,
    nodes: dict[str, PersistedNode],
    label: str,
) -> PersistedNode:
    node = nodes.get(ref.id)
    if node is None:
        raise ChapterOutlineDomainError(f"{label} reference is unknown")
    if node.revision != ref.revision or node.content_hash != ref.content_hash:
        raise ChapterOutlineDomainError(f"{label} reference identity is stale")
    return node


def normalize_chapter_outline(
    draft: DraftChapterOutline,
    *,
    planning: PlanningAggregate,
    authoritative_chapter_number: int,
    planning_revision_id: str,
    planning_revision: int,
    capacity_policy: OutlineCapacityPolicy,
    canon_revision: int,
    projection_revision: int,
    projection_hash: str,
) -> ChapterOutline:
    """Validate a closed active Planning slice and derive its immutable hash."""

    if authoritative_chapter_number < 1:
        raise ChapterOutlineDomainError("authoritative chapter number is invalid")
    if draft.chapter_number != authoritative_chapter_number:
        raise ChapterOutlineDomainError("chapter number differs from server authority")

    if (
        draft.planning_revision_id != planning_revision_id
        or draft.planning_revision != planning_revision
        or draft.planning_hash != planning.content_hash
    ):
        raise ChapterOutlineDomainError("Planning authority does not match")
    if draft.capacity_policy != capacity_policy:
        raise ChapterOutlineDomainError("capacity policy does not match contract")
    if canon_revision < 0 or projection_revision < 0:
        raise ChapterOutlineDomainError("Canon/Projection revision is invalid")
    if canon_revision != projection_revision:
        raise ChapterOutlineDomainError("Canon and Projection must be synchronized")
    if re.fullmatch(r"[0-9a-f]{64}", projection_hash) is None:
        raise ChapterOutlineDomainError("projection hash is invalid")

    volumes = {node.id: node for node in planning.volumes}
    blocks = {node.id: node for node in planning.story_blocks}
    stages = {
        stage.id: stage
        for block in planning.story_blocks
        for stage in block.stages
    }
    tasks = {
        task.id: task
        for block in planning.story_blocks
        for stage in block.stages
        for task in stage.scene_tasks
    }

    volume = _resolve_ref(draft.volume_ref, volumes, "Volume")
    block = _resolve_ref(draft.story_block_ref, blocks, "StoryBlock")
    selected_stages = tuple(
        _resolve_ref(ref, stages, "Stage") for ref in draft.stage_refs
    )
    selected_tasks = tuple(
        _resolve_ref(ref, tasks, "SceneTask") for ref in draft.scene_task_refs
    )

    if len({ref.id for ref in draft.stage_refs}) != len(draft.stage_refs):
        raise ChapterOutlineDomainError("duplicate Stage reference")
    if len({ref.id for ref in draft.scene_task_refs}) != len(draft.scene_task_refs):
        raise ChapterOutlineDomainError("duplicate SceneTask reference")
    if any(node.lifecycle != "active" for node in (volume, block)):
        raise ChapterOutlineDomainError("Outline nodes must be active")
    if any(stage.lifecycle != "active" for stage in selected_stages):
        raise ChapterOutlineDomainError("Outline Stage nodes must be active")
    if any(task.lifecycle != "active" for task in selected_tasks):
        raise ChapterOutlineDomainError("Outline SceneTask nodes must be active")
    if block.id != planning.active_story_block_id:
        raise ChapterOutlineDomainError(
            "StoryBlock reference must be the current active StoryBlock"
        )
    if volume.id != block.volume_id:
        raise ChapterOutlineDomainError("Volume must belong to the StoryBlock")
    if any(stage.story_block_id != block.id for stage in selected_stages):
        raise ChapterOutlineDomainError("Stage must belong to the StoryBlock")
    selected_stage_ids = {stage.id for stage in selected_stages}
    if any(task.stage_id not in selected_stage_ids for task in selected_tasks):
        raise ChapterOutlineDomainError(
            "SceneTask must belong to a selected Stage"
        )

    payload = {
        **draft.model_dump(mode="json", by_alias=True),
        "canonRevision": canon_revision,
        "projectionRevision": projection_revision,
        "projectionHash": projection_hash,
    }
    content_hash = canonical_hash(payload)
    return ChapterOutline.model_validate(
        {**payload, "contentHash": content_hash}
    )


__all__ = (
    "ChapterOutline",
    "ChapterOutlineDomainError",
    "DraftChapterOutline",
    "EditableChapterOutlineContent",
    "OutlineCapacityPolicy",
    "PlanningNodeRef",
    "normalize_chapter_outline",
)
