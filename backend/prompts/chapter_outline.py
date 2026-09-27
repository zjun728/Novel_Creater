"""Closed, bounded prompt construction for ChapterOutline generation."""

from __future__ import annotations

from collections.abc import Mapping
import json
import re
from hashlib import sha256
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
    model_serializer,
)

from backend.domain.chapter_outlines import (
    EditableChapterOutlineContent,
    OutlineCapacityPolicy,
)
from backend.domain.json_contracts import canonical_json
from backend.domain.planning import Plot, SceneTask, Stage, StoryBlock, Volume
from backend.prompts.planning import (
    validate_planning_story_context_candidate,
)


CHAPTER_OUTLINE_MAX_MANIFEST_BYTES = 64 * 1024
CHAPTER_OUTLINE_MAX_PROMPT_BYTES = 96 * 1024
_SAFE_ERROR = "Chapter outline prompt input invalid"
_HASH_PATTERN = r"^[0-9a-f]{64}$"
_RAW_CORPUS_PASSAGE = re.compile(
    r"(?:raw[\s_.-]*)?corpus[\s_.-]*passages?\s*[:=]\s*\S+",
    re.IGNORECASE,
)
_STRICT_MANIFEST = ConfigDict(
    strict=True,
    frozen=True,
    extra="forbid",
    hide_input_in_errors=True,
)


class PlanningAuthority(BaseModel):
    model_config = _STRICT_MANIFEST

    revision_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    content_hash: str = Field(pattern=_HASH_PATTERN)


class ProjectionAuthority(BaseModel):
    model_config = _STRICT_MANIFEST

    revision: int = Field(ge=0)
    content_hash: str = Field(pattern=_HASH_PATTERN)


class PublicBindingAuthority(BaseModel):
    model_config = _STRICT_MANIFEST

    revision_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    content_hash: str = Field(pattern=_HASH_PATTERN)
    provider_id: str = Field(min_length=1)
    model_name: str = Field(min_length=1)


class PreviousFinalChapter(BaseModel):
    model_config = _STRICT_MANIFEST

    id: str = Field(min_length=1)
    chapter_number: int = Field(ge=1)
    canon_revision: int = Field(ge=1)
    content: str = Field(min_length=1)
    content_hash: str = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def verify_text(self) -> Self:
        # Preserve the whole chapter, including its ending. Oversize context is
        # rejected by the manifest byte boundary, never silently truncated.
        if sha256(self.content.encode("utf-8")).hexdigest() != self.content_hash:
            raise ValueError(_SAFE_ERROR)
        return self


class ActualPlanningProgress(BaseModel):
    model_config = _STRICT_MANIFEST

    chapter_number: int = Field(alias="chapterNumber", ge=1)
    target_id: str = Field(alias="targetId", min_length=1, max_length=100)
    target_type: Literal["story_block", "stage", "scene_task"] = Field(alias="targetType")
    status: Literal["started", "advanced", "completed"]


class OutlineContinuity(BaseModel):
    model_config = _STRICT_MANIFEST

    previous_chapter: PreviousFinalChapter | None
    actual_progress: tuple[ActualPlanningProgress, ...]

    @field_validator("actual_progress", mode="before")
    @classmethod
    def accept_json_arrays(cls, value):
        return tuple(value) if isinstance(value, list) else value


class ChapterOutlineGenerationManifest(BaseModel):
    model_config = _STRICT_MANIFEST

    schema_version: Literal["chapter-outline-generation-v1"] = (
        "chapter-outline-generation-v1"
    )
    chapter_number: int = Field(ge=1)
    planning: PlanningAuthority
    canon_revision: int = Field(ge=0)
    projection: ProjectionAuthority
    story_block: StoryBlock
    allowed_stages: tuple[Stage, ...] = Field(min_length=1)
    allowed_scene_tasks: tuple[SceneTask, ...] = Field(min_length=1)
    volume: Volume
    plots: tuple[Plot, ...] = Field(min_length=1)
    capacity_policy: OutlineCapacityPolicy
    draft_revision: int = Field(ge=1)
    draft_hash: str = Field(pattern=_HASH_PATTERN)
    author_instructions: str = Field(max_length=4_000)
    binding: PublicBindingAuthority
    continuity: OutlineContinuity | None = None

    @model_serializer(mode="wrap")
    def preserve_legacy_snapshot(self, handler):
        payload = handler(self)
        if self.continuity is None:
            payload.pop("continuity", None)
        return payload

    @field_validator(
        "allowed_stages",
        "allowed_scene_tasks",
        "plots",
        mode="before",
    )
    @classmethod
    def accept_json_arrays(cls, value):
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_closed_public_manifest(self) -> Self:
        if self.canon_revision != self.projection.revision:
            raise ValueError(_SAFE_ERROR)
        if self.continuity is not None:
            previous = self.continuity.previous_chapter
            if (
                (self.chapter_number == 1 and previous is not None)
                or (self.chapter_number > 1 and previous is None)
                or previous is not None and (
                    previous.chapter_number != self.chapter_number - 1
                    or previous.canon_revision > self.canon_revision
                )
                or any(item.chapter_number >= self.chapter_number
                       for item in self.continuity.actual_progress)
                or len({(item.target_type, item.target_id)
                        for item in self.continuity.actual_progress})
                   != len(self.continuity.actual_progress)
            ):
                raise ValueError(_SAFE_ERROR)
        if (
            self.volume.lifecycle != "active"
            or self.story_block.lifecycle != "active"
            or any(plot.lifecycle != "active" for plot in self.plots)
            or any(stage.lifecycle != "active" for stage in self.allowed_stages)
            or any(
                task.lifecycle != "active"
                for task in self.allowed_scene_tasks
            )
        ):
            raise ValueError(_SAFE_ERROR)
        if self.story_block.volume_id != self.volume.id:
            raise ValueError(_SAFE_ERROR)
        if self.story_block.plot_ids != tuple(plot.id for plot in self.plots):
            raise ValueError(_SAFE_ERROR)

        stages = {stage.id: stage for stage in self.story_block.stages}
        if (
            len(stages) != len(self.story_block.stages)
            or len({stage.id for stage in self.allowed_stages})
            != len(self.allowed_stages)
            or any(
                stages.get(stage.id) != stage
                for stage in self.allowed_stages
            )
        ):
            raise ValueError(_SAFE_ERROR)

        allowed_stage_ids = {stage.id for stage in self.allowed_stages}
        tasks = {
            task.id: task
            for stage in self.story_block.stages
            for task in stage.scene_tasks
        }
        if (
            len(tasks)
            != sum(
                len(stage.scene_tasks)
                for stage in self.story_block.stages
            )
            or len({task.id for task in self.allowed_scene_tasks})
            != len(self.allowed_scene_tasks)
            or any(
                tasks.get(task.id) != task
                or task.stage_id not in allowed_stage_ids
                for task in self.allowed_scene_tasks
            )
        ):
            raise ValueError(_SAFE_ERROR)
        if self.continuity is not None:
            completed = {(item.target_type, item.target_id)
                         for item in self.continuity.actual_progress
                         if item.status == "completed"}
            if (("story_block", self.story_block.id) in completed
                or any(("stage", stage.id) in completed for stage in self.allowed_stages)
                or any(("scene_task", task.id) in completed for task in self.allowed_scene_tasks)):
                raise ValueError(_SAFE_ERROR)

        snapshot = self.model_dump(mode="json", by_alias=True)
        try:
            validate_planning_story_context_candidate(snapshot)
            if _RAW_CORPUS_PASSAGE.search(self.author_instructions):
                raise ValueError(_SAFE_ERROR)
            rendered = canonical_json(snapshot).encode("utf-8")
        except (UnicodeError, TypeError, ValueError, RecursionError):
            raise ValueError(_SAFE_ERROR) from None
        if len(rendered) > CHAPTER_OUTLINE_MAX_MANIFEST_BYTES:
            raise ValueError(_SAFE_ERROR)
        return self


def build_chapter_outline_messages(
    *,
    manifest: ChapterOutlineGenerationManifest | Mapping[str, object],
) -> tuple[dict[str, str], ...]:
    """Build one JSON-only request from a frozen, secret-free manifest."""

    try:
        manifest_value = ChapterOutlineGenerationManifest.model_validate(
            manifest,
            strict=True,
        )
        manifest_snapshot = manifest_value.model_dump(
            mode="json",
            by_alias=True,
        )
        validate_planning_story_context_candidate(manifest_snapshot)
        instruction = {
            "task": "Generate one complete EditableChapterOutlineContent",
            "rules": [
                "Return exactly one JSON object matching outputContract.",
                "Return every outputContract field even when an array is empty; "
                "scenes must contain at least one concrete chapter scene.",
                "Copy volumeRef and storyBlockRef exactly from the manifest.",
                "Copy every allowed Stage and SceneTask reference exactly, "
                "in manifest order.",
                "Do not invent IDs, revisions, hashes, nodes, or references.",
                "Use only the supplied StoryBlock, Stage, SceneTask, Volume, "
                "Plot, capacity, continuity, and author-instruction evidence.",
                "Continuity contains actual events: continue from the previous "
                "finalized chapter's ending, preserving location, time, custody "
                "of evidence, knowledge limits and unfinished actions. Planning "
                "describes future intentions, not facts already established.",
                "Completed stages and tasks are historical context, not scenes "
                "to perform again. For started or advanced tasks, use the previous "
                "chapter to distinguish work already done from the remaining "
                "completion condition; advance only the unfinished part.",
                "A StoryBlock's entrySituation may have already happened. Do not "
                "restart it or repeat the previous chapter's discovery, meeting "
                "or agreement. References authorize scope, not reenactment.",
                "Do not return commentary, markdown, prompt text, or evidence.",
            ],
        }
        evidence = {
            "manifest": manifest_snapshot,
            "outputContract": (
                EditableChapterOutlineContent.model_json_schema(
                    by_alias=True
                )
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
        if len(rendered) > CHAPTER_OUTLINE_MAX_PROMPT_BYTES:
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
    "CHAPTER_OUTLINE_MAX_MANIFEST_BYTES",
    "CHAPTER_OUTLINE_MAX_PROMPT_BYTES",
    "ChapterOutlineGenerationManifest",
    "PlanningAuthority",
    "ProjectionAuthority",
    "PublicBindingAuthority",
    "build_chapter_outline_messages",
)
