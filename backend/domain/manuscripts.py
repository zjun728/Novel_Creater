"""Strict immutable domain values for finalized-manuscript reading."""

from __future__ import annotations

import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.domain.chapter_outlines import ChapterOutline


ManuscriptLifecycle = Literal["active", "archived"]


class ManuscriptDomainError(ValueError):
    """Base error for safe deterministic manuscript-read failures."""


class ManuscriptProjectMissing(ManuscriptDomainError):
    def __init__(self) -> None:
        super().__init__("manuscript project was not found")


class FinalChapterMissing(ManuscriptDomainError):
    def __init__(self) -> None:
        super().__init__("finalized chapter was not found")


class ManuscriptCorrupt(ManuscriptDomainError):
    def __init__(self) -> None:
        super().__init__("manuscript integrity validation failed")


class ManuscriptUnavailable(ManuscriptDomainError):
    def __init__(self) -> None:
        super().__init__("manuscript is temporarily unavailable")


class _StrictManuscriptValue(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


def _validate_safe_title(value: str) -> str:
    if not value.strip() or value != value.strip():
        raise ValueError("title must be trimmed non-empty text")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError("title must not contain control characters")
    return value


class ManuscriptChapterMeta(_StrictManuscriptValue):
    number: int = Field(ge=1)
    title: str = Field(min_length=1)
    scalar_count: int = Field(ge=0)
    finalized_at_ms: int = Field(ge=0)

    _title_is_safe = field_validator("title")(_validate_safe_title)


class ManuscriptVolume(_StrictManuscriptValue):
    id: str = Field(min_length=1)
    order: int = Field(ge=1)
    title: str = Field(min_length=1)
    lifecycle: ManuscriptLifecycle
    chapters: tuple[ManuscriptChapterMeta, ...]

    _title_is_safe = field_validator("title")(_validate_safe_title)


class FinalOutlineProjection(_StrictManuscriptValue):
    chapter_goal: str
    expected_characters: tuple[str, ...]
    continuation: tuple[str, ...]
    planned_tasks: tuple[str, ...]
    scenes: tuple[str, ...]
    forbidden_early_events: tuple[str, ...]


def canonicalize_manuscript_volumes(
    volumes: tuple[ManuscriptVolume, ...],
) -> tuple[ManuscriptVolume, ...]:
    """Return finalized chapters in global numeric order after link validation."""

    if type(volumes) is not tuple or any(
        type(volume) is not ManuscriptVolume for volume in volumes
    ):
        raise ManuscriptCorrupt()

    by_volume_id: dict[str, tuple[int, str]] = {}
    by_volume_order: dict[int, tuple[str, str]] = {}
    chapter_numbers: set[int] = set()
    linked_chapters: list[tuple[ManuscriptChapterMeta, ManuscriptVolume]] = []

    for volume in volumes:
        details = (volume.order, volume.title)
        if by_volume_id.setdefault(volume.id, details) != details:
            raise ManuscriptCorrupt()
        order_details = (volume.id, volume.title)
        if by_volume_order.setdefault(volume.order, order_details) != order_details:
            raise ManuscriptCorrupt()
        for chapter in volume.chapters:
            if chapter.number in chapter_numbers:
                raise ManuscriptCorrupt()
            chapter_numbers.add(chapter.number)
            linked_chapters.append((chapter, volume))

    linked_chapters.sort(key=lambda item: item[0].number)
    runs: list[tuple[ManuscriptVolume, list[ManuscriptChapterMeta]]] = []
    completed_volume_ids: set[str] = set()
    current_volume: ManuscriptVolume | None = None

    for chapter, volume in linked_chapters:
        if current_volume is None or volume.id != current_volume.id:
            if current_volume is not None:
                completed_volume_ids.add(current_volume.id)
                if volume.order < current_volume.order:
                    raise ManuscriptCorrupt()
            if volume.id in completed_volume_ids:
                raise ManuscriptCorrupt()
            current_volume = volume
            runs.append((volume, []))
        runs[-1][1].append(chapter)

    return tuple(
        volume.model_copy(update={"chapters": tuple(chapters)})
        for volume, chapters in runs
    )


def unicode_scalar_count(value: str) -> int:
    """Count Python Unicode code points after rejecting surrogate code units."""

    if type(value) is not str:
        raise TypeError("value must be str")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ValueError("value must contain only Unicode scalar values")
    return len(value)


def validate_database_scalar_count(value: object) -> int:
    """Validate a scalar count read from storage without numeric coercion."""

    if type(value) is not int or value < 0:
        raise ManuscriptCorrupt()
    return value


def project_final_outline(outline: ChapterOutline) -> FinalOutlineProjection:
    """Expose only the six author-facing fields pinned in a final outline."""

    if type(outline) is not ChapterOutline:
        raise TypeError("outline must be a ChapterOutline")
    return FinalOutlineProjection(
        chapter_goal=outline.chapter_goal,
        expected_characters=outline.expected_characters,
        continuation=outline.continuation,
        planned_tasks=outline.planned_tasks,
        scenes=outline.scenes,
        forbidden_early_events=outline.forbidden_early_events,
    )


__all__ = (
    "canonicalize_manuscript_volumes",
    "FinalChapterMissing",
    "FinalOutlineProjection",
    "ManuscriptChapterMeta",
    "ManuscriptCorrupt",
    "ManuscriptDomainError",
    "ManuscriptLifecycle",
    "ManuscriptProjectMissing",
    "ManuscriptUnavailable",
    "ManuscriptVolume",
    "project_final_outline",
    "unicode_scalar_count",
    "validate_database_scalar_count",
)
