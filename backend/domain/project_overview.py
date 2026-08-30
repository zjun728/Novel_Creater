"""Strict immutable read contracts for the project overview."""

from __future__ import annotations

import unicodedata
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel


OverviewArtifactStatus = Literal[
    "missing",
    "working_draft",
    "pending_confirmation",
    "current",
    "needs_review",
]


class _StrictOverviewValue(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
    )


def _safe_text(value: str) -> str:
    if not value.strip() or value != value.strip():
        raise ValueError("text must be trimmed and non-empty")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError("text must not contain Unicode control characters")
    return value


class OverviewProject(_StrictOverviewValue):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    genre: str = Field(min_length=1)
    logline: str = Field(min_length=1)
    target_words: int = Field(gt=0)
    target_chapters: int = Field(gt=0)
    updated_at_ms: int = Field(ge=0)
    lifecycle: Literal["active", "archived"]

    _id_safe = field_validator("id")(_safe_text)
    _title_safe = field_validator("title")(_safe_text)
    _genre_safe = field_validator("genre")(_safe_text)
    _logline_safe = field_validator("logline")(_safe_text)


class OverviewVolume(_StrictOverviewValue):
    id: str = Field(min_length=1)
    order: int = Field(gt=0)
    title: str = Field(min_length=1)

    _id_safe = field_validator("id")(_safe_text)
    _title_safe = field_validator("title")(_safe_text)


class OverviewFinalChapter(_StrictOverviewValue):
    number: int = Field(gt=0)
    title: str = Field(min_length=1)
    finalized_at_ms: int = Field(ge=0)

    _title_safe = field_validator("title")(_safe_text)


class OverviewProgress(_StrictOverviewValue):
    authoritative_chapter_number: int = Field(gt=0)
    current_volume: OverviewVolume | None = None
    latest_final_chapter: OverviewFinalChapter | None = None
    finalized_chapter_count: int = Field(ge=0)
    finalized_scalar_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_final_chapter_shape(self) -> Self:
        has_final_chapter = self.latest_final_chapter is not None
        if (self.finalized_chapter_count > 0) != has_final_chapter:
            raise ValueError("finalized chapter count and latest chapter disagree")
        if self.finalized_chapter_count == 0 and self.finalized_scalar_count != 0:
            raise ValueError("zero finalized chapters require zero finalized scalars")
        if self.latest_final_chapter is not None:
            if self.latest_final_chapter.number >= self.authoritative_chapter_number:
                raise ValueError("latest final chapter must precede authoritative chapter")
            if self.finalized_chapter_count > self.latest_final_chapter.number:
                raise ValueError("finalized chapter count exceeds latest chapter number")
        return self


class OverviewModuleStates(_StrictOverviewValue):
    seed: OverviewArtifactStatus
    contract: OverviewArtifactStatus
    bible: OverviewArtifactStatus
    planning: OverviewArtifactStatus
    outline: OverviewArtifactStatus
    writing: OverviewArtifactStatus


class OverviewWriterCore(_StrictOverviewValue):
    canon_revision: int = Field(ge=0)
    projection_revision: int = Field(ge=0)
    synchronized: bool

    @model_validator(mode="after")
    def validate_synchronization(self) -> Self:
        if self.synchronized != (self.canon_revision == self.projection_revision):
            raise ValueError("synchronized must equal the revision comparison")
        return self


class OverviewContinuity(_StrictOverviewValue):
    availability: Literal["pending_module", "available"]
    pending_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_availability_shape(self) -> Self:
        if self.availability == "pending_module" and self.pending_count is not None:
            raise ValueError("pending continuity module cannot expose a count")
        if self.availability == "available" and self.pending_count is None:
            raise ValueError("available continuity requires a pending count")
        return self


class OverviewAchievement(_StrictOverviewValue):
    kind: Literal["seed", "contract", "bible", "planning", "final_chapter"]
    label: str = Field(min_length=1)
    occurred_at_ms: int = Field(ge=0)

    _label_safe = field_validator("label")(_safe_text)


class ProjectOverview(_StrictOverviewValue):
    project: OverviewProject
    progress: OverviewProgress
    modules: OverviewModuleStates
    writer_core: OverviewWriterCore
    continuity: OverviewContinuity
    recent_achievements: tuple[OverviewAchievement, ...] = Field(max_length=5)

    @model_validator(mode="after")
    def validate_achievement_uniqueness(self) -> Self:
        identities = tuple(
            (achievement.kind, achievement.occurred_at_ms, achievement.label)
            for achievement in self.recent_achievements
        )
        if len(set(identities)) != len(identities):
            raise ValueError("recent achievements must be unique")
        return self


__all__ = (
    "OverviewAchievement",
    "OverviewArtifactStatus",
    "OverviewContinuity",
    "OverviewFinalChapter",
    "OverviewModuleStates",
    "OverviewProgress",
    "OverviewProject",
    "OverviewVolume",
    "OverviewWriterCore",
    "ProjectOverview",
)
