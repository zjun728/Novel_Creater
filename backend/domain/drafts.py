from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ChapterSessionView:
    id: str
    project_id: str
    story_block_id: str
    chapter_num: int
    expected_canon_revision: int
    expected_story_block_revision: int
    planning_snapshot: Mapping[str, Any]
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


@dataclass(frozen=True)
class DraftCandidateView:
    id: str
    project_id: str
    chapter_session_id: str
    working_draft_revision: int
    content: str
    content_hash: str
    provenance: Mapping[str, Any]


@dataclass(frozen=True)
class ChapterWorkspace:
    project_id: str
    session: ChapterSessionView
    working_draft: WorkingDraftView
    candidates: tuple[DraftCandidateView, ...]
