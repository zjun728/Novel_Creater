"""Strict immutable read contracts for the unified author workbench."""

from __future__ import annotations

import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


WorkbenchMode = Literal["historical", "current", "future"]
WorkbenchAction = Literal[
    "view_chapter", "view_outline", "create_session", "edit_draft",
    "run_ai_operation", "save_candidate", "compare_candidates",
    "audit_candidate", "finalize_candidate",
]
WorkbenchBlockCode = Literal[
    "project_archived", "future_chapter", "outline_required",
    "session_not_created", "canon_projection_unsynchronized",
    "finalization_in_progress",
]
ChapterIndexMode = Literal["historical", "current"]


class _StrictValue(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


def _safe_text(value: str) -> str:
    if not value.strip() or value != value.strip():
        raise ValueError("text must be trimmed and non-empty")
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError("text must not contain control characters")
    return value


class WorkbenchVolumeReference(_StrictValue):
    id: str = Field(min_length=1)
    order: int = Field(ge=1)
    title: str = Field(min_length=1)

    _id_safe = field_validator("id")(_safe_text)
    _title_safe = field_validator("title")(_safe_text)


class WorkbenchOutlineReference(_StrictValue):
    id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    _id_safe = field_validator("id")(_safe_text)


class WorkbenchSessionReference(_StrictValue):
    id: str = Field(min_length=1)
    chapter_number: int = Field(ge=1)
    status: Literal["drafting"] = "drafting"

    _id_safe = field_validator("id")(_safe_text)


class WorkbenchFinalChapterReference(_StrictValue):
    id: str = Field(min_length=1)
    chapter_number: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    _id_safe = field_validator("id")(_safe_text)


class WorkbenchBlockedReason(_StrictValue):
    code: WorkbenchBlockCode
    message: str = Field(min_length=1, max_length=240)

    _message_safe = field_validator("message")(_safe_text)


class WorkbenchBootstrap(_StrictValue):
    project_id: str = Field(min_length=1)
    requested_chapter: int = Field(ge=1)
    authoritative_chapter: int = Field(ge=1)
    mode: WorkbenchMode
    volume: WorkbenchVolumeReference | None
    session: WorkbenchSessionReference | None
    final_chapter: WorkbenchFinalChapterReference | None
    outline: WorkbenchOutlineReference | None
    available_actions: tuple[WorkbenchAction, ...]
    blocked_reasons: tuple[WorkbenchBlockedReason, ...]
    canon_revision: int | None = Field(default=None, ge=0)
    projection_revision: int | None = Field(default=None, ge=0)
    canon_projection_synchronized: bool

    _project_id_safe = field_validator("project_id")(_safe_text)

    @model_validator(mode="after")
    def validate_authority_shape(self):
        expected_mode = (
            "historical" if self.requested_chapter < self.authoritative_chapter
            else "current" if self.requested_chapter == self.authoritative_chapter
            else "future"
        )
        if self.mode != expected_mode:
            raise ValueError("mode differs from server authoritative chapter")
        if len(set(self.available_actions)) != len(self.available_actions):
            raise ValueError("available actions must be unique")
        reason_codes = tuple(reason.code for reason in self.blocked_reasons)
        if len(set(reason_codes)) != len(reason_codes):
            raise ValueError("blocked reason codes must be unique")
        synchronized = (
            self.canon_revision is not None
            and self.projection_revision is not None
            and self.canon_revision == self.projection_revision
        )
        if self.canon_projection_synchronized != synchronized:
            raise ValueError("Canon/Projection synchronization flag is invalid")
        if self.mode == "historical":
            if self.final_chapter is None or self.outline is None or self.volume is None:
                raise ValueError("historical mode requires pinned final authorities")
            if self.session is not None:
                raise ValueError("historical mode cannot expose a drafting session")
            if set(self.available_actions) - {"view_chapter", "view_outline"}:
                raise ValueError("historical mode is read-only")
            if self.final_chapter.chapter_number != self.requested_chapter:
                raise ValueError("final chapter differs from request")
        elif self.mode == "current":
            if self.final_chapter is not None:
                raise ValueError("current mode cannot expose a final chapter")
            if self.session is not None:
                if self.session.chapter_number != self.requested_chapter:
                    raise ValueError("session differs from request")
                if "create_session" in self.available_actions:
                    raise ValueError("create_session is invalid when a session exists")
            elif set(self.available_actions) - {"view_outline", "create_session"}:
                raise ValueError("draft actions require a current session")
        else:
            if any((self.volume, self.session, self.final_chapter, self.outline)):
                raise ValueError("future mode cannot expose chapter authorities")
            if self.available_actions:
                raise ValueError("future mode has no actions")
            if "future_chapter" not in reason_codes:
                raise ValueError("future mode requires a stable blocked reason")
        return self


class WorkbenchVolumeSummary(_StrictValue):
    volume: WorkbenchVolumeReference
    finalized_chapter_count: int = Field(ge=0)
    first_finalized_chapter: int | None = Field(default=None, ge=1)
    last_finalized_chapter: int | None = Field(default=None, ge=1)
    contains_authoritative_chapter: bool

    @model_validator(mode="after")
    def validate_finalized_range(self):
        values = (self.first_finalized_chapter, self.last_finalized_chapter)
        if self.finalized_chapter_count == 0 and any(value is not None for value in values):
            raise ValueError("empty volume cannot expose a finalized range")
        if self.finalized_chapter_count > 0:
            if any(value is None for value in values):
                raise ValueError("non-empty volume requires a finalized range")
            if self.first_finalized_chapter > self.last_finalized_chapter:
                raise ValueError("finalized range is reversed")
        return self


class WorkbenchVolumeSummaryList(_StrictValue):
    project_id: str = Field(min_length=1)
    volumes: tuple[WorkbenchVolumeSummary, ...]
    authoritative_chapter: int | None = Field(default=None, ge=1)
    unassigned_authoritative_chapter: int | None = Field(default=None, ge=1)

    _project_id_safe = field_validator("project_id")(_safe_text)

    @model_validator(mode="after")
    def validate_authority_location(self):
        identities = tuple(item.volume.id for item in self.volumes)
        orders = tuple(item.volume.order for item in self.volumes)
        if len(set(identities)) != len(identities) or len(set(orders)) != len(orders):
            raise ValueError("volume identities and orders must be unique")
        if tuple(sorted(orders)) != orders:
            raise ValueError("volumes must be ordered")
        located = sum(item.contains_authoritative_chapter for item in self.volumes)
        if located > 1:
            raise ValueError("authoritative chapter can belong to one volume only")
        if self.unassigned_authoritative_chapter is not None:
            if self.unassigned_authoritative_chapter != self.authoritative_chapter or located:
                raise ValueError("unassigned authority must not also belong to a volume")
        return self


class WorkbenchChapterIndexItem(_StrictValue):
    chapter_number: int = Field(ge=1)
    title: str = Field(min_length=1)
    mode: ChapterIndexMode
    scalar_count: int | None = Field(default=None, ge=0)
    finalized_at_ms: int | None = Field(default=None, ge=0)
    final_chapter_id: str | None = Field(default=None, min_length=1)
    session_id: str | None = Field(default=None, min_length=1)

    _title_safe = field_validator("title")(_safe_text)

    @field_validator("final_chapter_id", "session_id")
    @classmethod
    def optional_id_safe(cls, value: str | None) -> str | None:
        return None if value is None else _safe_text(value)

    @model_validator(mode="after")
    def validate_mode_shape(self):
        if self.mode == "historical":
            if None in (self.scalar_count, self.finalized_at_ms, self.final_chapter_id):
                raise ValueError("historical item requires final metadata")
            if self.session_id is not None:
                raise ValueError("historical item cannot expose a session")
        elif any(value is not None for value in (
            self.scalar_count, self.finalized_at_ms, self.final_chapter_id,
        )):
            raise ValueError("current item cannot expose final metadata")
        return self


class WorkbenchChapterIndexPage(_StrictValue):
    project_id: str = Field(min_length=1)
    volume: WorkbenchVolumeReference
    chapters: tuple[WorkbenchChapterIndexItem, ...]
    next_cursor: str | None = Field(default=None, min_length=1, max_length=512)
    limit: int = Field(ge=1, le=100)

    _project_id_safe = field_validator("project_id")(_safe_text)

    @field_validator("next_cursor")
    @classmethod
    def cursor_safe(cls, value: str | None) -> str | None:
        return None if value is None else _safe_text(value)

    @model_validator(mode="after")
    def validate_page(self):
        numbers = tuple(item.chapter_number for item in self.chapters)
        if tuple(sorted(numbers)) != numbers or len(set(numbers)) != len(numbers):
            raise ValueError("chapters must be unique and ordered")
        if sum(item.mode == "current" for item in self.chapters) > 1:
            raise ValueError("page can expose at most one current chapter")
        if len(self.chapters) > self.limit:
            raise ValueError("page exceeds its declared limit")
        return self


__all__ = (
    "ChapterIndexMode", "WorkbenchAction", "WorkbenchBlockedReason",
    "WorkbenchBlockCode", "WorkbenchBootstrap", "WorkbenchChapterIndexItem",
    "WorkbenchChapterIndexPage", "WorkbenchFinalChapterReference",
    "WorkbenchMode", "WorkbenchOutlineReference", "WorkbenchSessionReference",
    "WorkbenchVolumeReference", "WorkbenchVolumeSummary",
    "WorkbenchVolumeSummaryList",
)
