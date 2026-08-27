"""Read-only reconstruction of finalized novel snapshots from pinned revisions."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping

from pydantic import ValidationError

from backend.domain.manuscripts import ManuscriptCorrupt
from backend.domain.novel_downloads import (
    DownloadScope,
    FinalizedChapterMetadata,
    FinalizedChapterSnapshot,
    NovelDownloadIntegrityError,
    NovelDownloadMetadata,
    NovelDownloadScopeNotFoundError,
    NovelDownloadSelector,
    NovelDownloadSnapshot,
)
from backend.repositories.manuscripts import decode_finalized_authority


class NovelDownloadDataCorruption(NovelDownloadIntegrityError):
    """The immutable finalized chain cannot be reconstructed safely."""


_FINALIZED_METADATA_SELECT = """
SELECT project.title AS book_title,
       final.id AS final_id, final.project_id AS final_project_id,
       final.chapter_session_id AS final_session_id,
       final.chapter_num AS final_chapter_num, final.title AS final_title,
       final.planning_revision_id AS final_planning_id,
       final.planning_revision AS final_planning_revision,
       final.planning_hash AS final_planning_hash,
       final.chapter_outline_revision_id AS final_outline_id,
       final.chapter_outline_revision AS final_outline_revision,
       final.chapter_outline_hash AS final_outline_hash,
       chapter.id AS session_id, chapter.project_id AS session_project_id,
       chapter.chapter_num AS session_chapter_num,
       chapter.planning_revision_id AS session_planning_id,
       chapter.planning_revision AS session_planning_revision,
       chapter.planning_hash AS session_planning_hash,
       chapter.story_block_id AS session_story_block_id,
       chapter.story_block_revision AS session_story_block_revision,
       chapter.story_block_hash AS session_story_block_hash,
       chapter.chapter_outline_revision_id AS session_outline_id,
       chapter.chapter_outline_revision AS session_outline_revision,
       chapter.chapter_outline_hash AS session_outline_hash,
       outline.id AS outline_id, outline.project_id AS outline_project_id,
       outline.chapter_num AS outline_chapter_num,
       outline.revision AS outline_revision,
       outline.planning_revision_id AS outline_planning_id,
       outline.planning_revision AS outline_planning_revision,
       outline.planning_hash AS outline_planning_hash,
       outline.content_hash AS outline_content_hash,
       outline.content_json AS outline_content_json,
       planning.id AS planning_id, planning.project_id AS planning_project_id,
       planning.revision AS planning_revision,
       planning.content_hash AS planning_content_hash,
       planning.content_json AS planning_content_json
  FROM projects project
  LEFT JOIN final_chapters final
    ON final.project_id=project.id
  LEFT JOIN chapter_sessions chapter
    ON chapter.project_id=final.project_id
   AND chapter.id=final.chapter_session_id
  LEFT JOIN chapter_outline_revisions outline
    ON outline.project_id=final.project_id
   AND outline.id=final.chapter_outline_revision_id
  LEFT JOIN planning_revisions planning
    ON planning.project_id=final.project_id
   AND planning.id=final.planning_revision_id
 WHERE project.id=%s
 ORDER BY final.chapter_num ASC, final.id ASC
"""

_SELECTED_PROSE_SELECT = """
SELECT final.id AS final_id,
       final.chapter_num AS final_chapter_num,
       final.content AS final_content,
       final.content_hash AS final_content_hash
  FROM final_chapters final
 WHERE final.project_id=%s
   AND final.id IN ({placeholders})
 ORDER BY final.chapter_num ASC, final.id ASC
"""


def _corruption() -> NovelDownloadDataCorruption:
    # This must be stable and deliberately contain no stored content or identifiers.
    return NovelDownloadDataCorruption("finalized download authority is corrupt")


@dataclass(frozen=True, slots=True)
class _FinalizedAuthority:
    final_id: str
    chapter: FinalizedChapterMetadata


def _authority_from_row(row: Mapping[str, object]) -> _FinalizedAuthority:
    try:
        authority = decode_finalized_authority(row, require_finalized_at=False)
        return _FinalizedAuthority(
            final_id=authority.final_id,
            chapter=FinalizedChapterMetadata(
                chapter_number=authority.chapter_number,
                chapter_title=authority.chapter_title,
                volume_id=authority.volume.id,
                volume_order=authority.volume.order,
                volume_title=authority.volume.title,
            ),
        )
    except (ManuscriptCorrupt, ValidationError):
        raise _corruption() from None


def _metadata_from_rows(
    rows: list[Mapping[str, object]],
) -> tuple[NovelDownloadMetadata, tuple[_FinalizedAuthority, ...]] | None:
    if not rows:
        return None
    book_title = rows[0].get("book_title")
    if not isinstance(book_title, str) or not book_title:
        raise _corruption()
    authorities = tuple(
        _authority_from_row(row)
        for row in rows
        if row.get("final_id") is not None
    )
    try:
        metadata = NovelDownloadMetadata(
            book_title=book_title,
            chapters=tuple(authority.chapter for authority in authorities),
        )
    except (ValidationError, ValueError) as error:
        raise _corruption() from None
    return metadata, authorities


def _matches_selector(
    authority: _FinalizedAuthority,
    selector: NovelDownloadSelector,
) -> bool:
    if selector.scope is DownloadScope.BOOK:
        return True
    if selector.scope is DownloadScope.VOLUME:
        return authority.chapter.volume_id == selector.volume_id
    return authority.chapter.chapter_number == selector.chapter_number


def _selected_authorities(
    authorities: tuple[_FinalizedAuthority, ...],
    selector: NovelDownloadSelector,
) -> tuple[_FinalizedAuthority, ...]:
    selected = tuple(
        authority for authority in authorities
        if _matches_selector(authority, selector)
    )
    if not selected:
        raise NovelDownloadScopeNotFoundError(
            "requested download scope has no finalized chapters"
        )
    return selected


def _snapshot_from_prose_rows(
    metadata: NovelDownloadMetadata,
    selected: tuple[_FinalizedAuthority, ...],
    prose_rows: list[Mapping[str, object]],
) -> NovelDownloadSnapshot:
    selected_by_id = {authority.final_id: authority for authority in selected}
    prose_by_id: dict[str, tuple[str, str]] = {}
    for row in prose_rows:
        final_id = row.get("final_id")
        authority = selected_by_id.get(final_id) if isinstance(final_id, str) else None
        prose = row.get("final_content")
        prose_hash = row.get("final_content_hash")
        if (
            authority is None
            or final_id in prose_by_id
            or row.get("final_chapter_num") != authority.chapter.chapter_number
            or not isinstance(prose, str)
            or not isinstance(prose_hash, str)
            or sha256(prose.encode("utf-8")).hexdigest() != prose_hash
        ):
            raise _corruption()
        prose_by_id[final_id] = (prose, prose_hash)
    if set(prose_by_id) != set(selected_by_id):
        raise _corruption()
    try:
        chapters = tuple(
            FinalizedChapterSnapshot(
                **authority.chapter.model_dump(),
                content=prose_by_id[authority.final_id][0],
                content_hash=prose_by_id[authority.final_id][1],
            )
            for authority in selected
        )
        return NovelDownloadSnapshot(book_title=metadata.book_title, chapters=chapters)
    except (ValidationError, ValueError) as error:
        raise _corruption() from None


class NovelDownloadRepository:
    """Load a finalized snapshot using only the rows pinned by final chapters."""

    async def _load_metadata_and_authorities(self, session, project_id: str):
        rows = await session.fetchall(_FINALIZED_METADATA_SELECT, (project_id,))
        return _metadata_from_rows(rows)

    async def load_finalized_metadata(
        self,
        session,
        project_id: str,
    ) -> NovelDownloadMetadata | None:
        loaded = await self._load_metadata_and_authorities(session, project_id)
        return None if loaded is None else loaded[0]

    async def load_finalized_snapshot(
        self,
        session,
        project_id: str,
        selector: NovelDownloadSelector,
    ) -> NovelDownloadSnapshot | None:
        if not isinstance(selector, NovelDownloadSelector):
            raise TypeError("selector must be a NovelDownloadSelector")
        selector = NovelDownloadSelector.model_validate(
            selector.model_dump(mode="python"),
        )
        loaded = await self._load_metadata_and_authorities(session, project_id)
        if loaded is None:
            return None
        metadata, authorities = loaded
        if not authorities:
            return NovelDownloadSnapshot(book_title=metadata.book_title, chapters=())
        selected = _selected_authorities(authorities, selector)
        placeholders = ", ".join("%s" for _ in selected)
        prose_rows = await session.fetchall(
            _SELECTED_PROSE_SELECT.format(placeholders=placeholders),
            (project_id, *(authority.final_id for authority in selected)),
        )
        return _snapshot_from_prose_rows(metadata, selected, prose_rows)


__all__ = ["NovelDownloadDataCorruption", "NovelDownloadRepository"]
