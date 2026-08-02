from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ChapterSessionView:
    id: str
    project_id: str
    planning_revision_id: str
    planning_revision: int
    planning_hash: str
    story_block_id: str
    story_block_revision: int
    story_block_hash: str
    chapter_outline_revision_id: str
    chapter_outline_revision: int
    chapter_outline_hash: str
    chapter_num: int
    expected_canon_revision: int
    status: str


@dataclass(frozen=True)
class WorkingDraftView:
    id: str
    project_id: str
    chapter_session_id: str
    revision: int
    content: str
    content_hash: str
    source_payload: Mapping[str, Any]
    status: str


@dataclass(frozen=True)
class DraftCandidateView:
    id: str
    project_id: str
    chapter_session_id: str
    working_draft_revision: int
    content: str
    content_hash: str
    outline_revision_id: str | None
    outline_revision: int | None
    outline_hash: str | None
    planning_revision_id: str | None
    planning_revision: int | None
    planning_hash: str | None
    canon_revision: int | None
    projection_revision: int | None
    projection_hash: str | None
    basis_status: str
    status: str


@dataclass(frozen=True)
class ChapterWorkspace:
    project_id: str
    session: ChapterSessionView
    working_draft: WorkingDraftView
    candidates: tuple[DraftCandidateView, ...]
    active_draft_operation_id: str | None = None
