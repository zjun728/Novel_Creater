"""Closed, bounded prompt construction for ChapterOutline generation."""

from __future__ import annotations

from collections.abc import Mapping
import json
import re
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
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
                "Copy volumeRef and storyBlockRef exactly from the manifest.",
                "Copy every allowed Stage and SceneTask reference exactly, "
                "in manifest order.",
                "Do not invent IDs, revisions, hashes, nodes, or references.",
                "Use only the supplied StoryBlock, Stage, SceneTask, Volume, "
                "Plot, capacity, and author-instruction evidence.",
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
