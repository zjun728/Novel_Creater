"""Verified read-only reconstruction of finalized manuscript records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping

import aiomysql
from pydantic import ValidationError

from backend.domain.chapter_outlines import ChapterOutline
from backend.domain.json_contracts import canonical_hash
from backend.domain.manuscripts import (
    FinalChapterRecord,
    ManuscriptChapterLookup,
    ManuscriptChapterMeta,
    ManuscriptCorrupt,
    ManuscriptDirectoryRecord,
    ManuscriptUnavailable,
    ManuscriptVolume,
    canonicalize_manuscript_volumes,
    project_final_outline,
    unicode_scalar_count,
    validate_database_scalar_count,
)
from backend.domain.planning import (
    PlanningAggregate,
    Plot,
    SceneTask,
    Stage,
    StoryBlock,
    Volume,
    planning_content_hash,
)


_AUTHORITY_COLUMNS = """
       final.id AS final_id, final.project_id AS final_project_id,
       final.chapter_session_id AS final_session_id,
       final.chapter_num AS final_chapter_num, final.title AS final_title,
       final.finalized_at AS final_finalized_at,
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
"""

_AUTHORITY_JOINS = """
  LEFT JOIN final_chapters final ON final.project_id=project.id
  LEFT JOIN chapter_sessions chapter
    ON chapter.project_id=final.project_id AND chapter.id=final.chapter_session_id
  LEFT JOIN chapter_outline_revisions outline
    ON outline.project_id=final.project_id AND outline.id=final.chapter_outline_revision_id
  LEFT JOIN planning_revisions planning
    ON planning.project_id=final.project_id AND planning.id=final.planning_revision_id
"""

_DIRECTORY_SELECT = f"""
SELECT project.id AS project_id, project.title AS book_title,
       project.archived_at AS project_archived_at,
       CHAR_LENGTH(final.content) AS final_scalar_count,
{_AUTHORITY_COLUMNS}
  FROM projects project
{_AUTHORITY_JOINS}
 WHERE project.id=%s
 ORDER BY final.chapter_num ASC, final.id ASC
"""

_TARGET_SELECT = f"""
SELECT project.id AS project_id, project.title AS book_title,
       project.archived_at AS project_archived_at,
       final.content AS final_content, final.content_hash AS final_content_hash,
{_AUTHORITY_COLUMNS}
  FROM projects project
{_AUTHORITY_JOINS}
 WHERE project.id=%s AND final.chapter_num=%s
 ORDER BY final.id ASC
"""

_NEIGHBOR_SELECT = """
SELECT project.id AS project_id, final.chapter_num AS final_chapter_num
  FROM projects project
  LEFT JOIN final_chapters final ON final.project_id=project.id
 WHERE project.id=%s
 ORDER BY final.chapter_num ASC, final.id ASC
"""


def manuscript_corruption() -> ManuscriptCorrupt:
    return ManuscriptCorrupt()


def decode_json_object(value: object) -> dict[str, object]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError, json.JSONDecodeError):
        raise manuscript_corruption() from None
    if not isinstance(decoded, dict):
        raise manuscript_corruption() from None
    return decoded


def require_equal_pin(row: Mapping[str, object], *names: str) -> object:
    values = [row.get(name) for name in names]
    if any(value is None for value in values) or any(
        value != values[0] for value in values[1:]
    ):
        raise manuscript_corruption() from None
    return values[0]


def _planning_nodes(planning: PlanningAggregate):
    yield from planning.volumes
    yield from planning.plots
    for block in planning.story_blocks:
        yield block
        for stage in block.stages:
            yield stage
            yield from stage.scene_tasks


def _node_payload(node: Volume | Plot | StoryBlock | Stage | SceneTask) -> dict[str, object]:
    payload: dict[str, object] = {"id": node.id, "lifecycle": node.lifecycle}
    if isinstance(node, Volume):
        payload.update(order=node.order, title=node.title, coreChange=node.core_change,
                       mainPressure=node.main_pressure, ensembleFocus=node.ensemble_focus,
                       forbiddenEvents=node.forbidden_events)
    elif isinstance(node, Plot):
        payload.update(order=node.order, title=node.title, plotType=node.plot_type,
                       storyQuestion=node.story_question, futureDirection=node.future_direction,
                       expectedPayoff=node.expected_payoff,
                       relatedCharacters=node.related_characters)
    elif isinstance(node, StoryBlock):
        payload.update(volumeId=node.volume_id, plotIds=node.plot_ids, order=node.order,
                       title=node.title, entrySituation=node.entry_situation,
                       blockGoal=node.block_goal, mainPressure=node.main_pressure,
                       expectedChange=node.expected_change, openQuestions=node.open_questions,
                       involvedCharacters=node.involved_characters)
    elif isinstance(node, Stage):
        payload.update(storyBlockId=node.story_block_id, order=node.order,
                       title=node.title, purpose=node.purpose,
                       dramaticQuestion=node.dramatic_question)
    else:
        payload.update(stageId=node.stage_id, order=node.order, task=node.task,
                       completionEvidence=node.completion_evidence)
    return payload


@dataclass(frozen=True, slots=True)
class PinnedFinalAuthority:
    final_id: str
    chapter_number: int
    chapter_title: str
    finalized_at_ms: int
    planning: PlanningAggregate
    outline: ChapterOutline
    volume: Volume
    story_block: StoryBlock


def decode_finalized_authority(
    row: Mapping[str, object], *, require_finalized_at: bool = True,
    expected_project_id: str | None = None,
) -> PinnedFinalAuthority:
    authority_project_id = require_equal_pin(
        row, "final_project_id", "session_project_id", "outline_project_id",
        "planning_project_id",
    )
    if expected_project_id is not None and authority_project_id != expected_project_id:
        raise manuscript_corruption() from None
    chapter_number = require_equal_pin(
        row, "final_chapter_num", "session_chapter_num", "outline_chapter_num",
    )
    planning_id = require_equal_pin(
        row, "final_planning_id", "session_planning_id", "outline_planning_id",
        "planning_id",
    )
    planning_revision = require_equal_pin(
        row, "final_planning_revision", "session_planning_revision",
        "outline_planning_revision", "planning_revision",
    )
    planning_hash = require_equal_pin(
        row, "final_planning_hash", "session_planning_hash",
        "outline_planning_hash", "planning_content_hash",
    )
    outline_id = require_equal_pin(
        row, "final_outline_id", "session_outline_id", "outline_id",
    )
    outline_revision = require_equal_pin(
        row, "final_outline_revision", "session_outline_revision", "outline_revision",
    )
    outline_hash = require_equal_pin(
        row, "final_outline_hash", "session_outline_hash", "outline_content_hash",
    )
    if row.get("final_session_id") != row.get("session_id") or not all(
        isinstance(value, str)
        for value in (planning_id, planning_hash, outline_id, outline_hash)
    ):
        raise manuscript_corruption() from None
    try:
        planning = PlanningAggregate.model_validate(
            decode_json_object(row.get("planning_content_json")),
        )
        outline = ChapterOutline.model_validate(
            decode_json_object(row.get("outline_content_json")),
        )
    except (ManuscriptCorrupt, ValidationError):
        raise manuscript_corruption() from None
    if (
        planning_content_hash(
            planning.model_dump(by_alias=True, mode="json", exclude={"content_hash"}),
        ) != planning.content_hash
        or planning.content_hash != row.get("planning_content_hash")
        or any(canonical_hash(_node_payload(node)) != node.content_hash
               for node in _planning_nodes(planning))
        or canonical_hash(
            outline.model_dump(by_alias=True, mode="json", exclude={"content_hash"}),
        ) != outline.content_hash
        or outline.content_hash != row.get("outline_content_hash")
        or outline.chapter_number != chapter_number
        or outline.planning_revision_id != planning_id
        or outline.planning_revision != planning_revision
        or outline.planning_hash != planning_hash
    ):
        raise manuscript_corruption() from None
    volume = next((item for item in planning.volumes if item.id == outline.volume_ref.id), None)
    block = next((item for item in planning.story_blocks if item.id == outline.story_block_ref.id), None)
    session_block_pin = (
        row.get("session_story_block_id"), row.get("session_story_block_revision"),
        row.get("session_story_block_hash"),
    )
    if (
        volume is None or volume.lifecycle != "active" or block is None
        or block.volume_id != volume.id
        or (volume.revision, volume.content_hash)
        != (outline.volume_ref.revision, outline.volume_ref.content_hash)
        or (block.revision, block.content_hash)
        != (outline.story_block_ref.revision, outline.story_block_ref.content_hash)
        or session_block_pin
        != (outline.story_block_ref.id, outline.story_block_ref.revision,
            outline.story_block_ref.content_hash)
        or session_block_pin != (block.id, block.revision, block.content_hash)
    ):
        raise manuscript_corruption() from None
    final_id = row.get("final_id")
    title = row.get("final_title")
    finalized_at = row.get("final_finalized_at", 0)
    if (
        not isinstance(final_id, str) or not final_id
        or type(chapter_number) is not int or chapter_number < 1
        or not isinstance(title, str)
        or type(finalized_at) is not int or finalized_at < 0
        or (require_finalized_at and "final_finalized_at" not in row)
    ):
        raise manuscript_corruption() from None
    return PinnedFinalAuthority(
        final_id=final_id,
        chapter_number=chapter_number,
        chapter_title=title,
        finalized_at_ms=finalized_at,
        planning=planning,
        outline=outline,
        volume=volume,
        story_block=block,
    )


def _project_values(row: Mapping[str, object]) -> tuple[str, str, str]:
    project_id = row.get("project_id")
    title = row.get("book_title")
    if not isinstance(project_id, str) or not isinstance(title, str):
        raise manuscript_corruption() from None
    lifecycle = "archived" if row.get("project_archived_at") is not None else "active"
    return project_id, title, lifecycle


def _directory_from_rows(rows: list[Mapping[str, object]]) -> ManuscriptDirectoryRecord | None:
    if not rows:
        return None
    project_id, title, lifecycle = _project_values(rows[0])
    if any(_project_values(row) != (project_id, title, lifecycle) for row in rows):
        raise manuscript_corruption() from None
    chapter_rows = [row for row in rows if row.get("final_id") is not None]
    authorities = [
        decode_finalized_authority(row, expected_project_id=project_id)
        for row in chapter_rows
    ]
    try:
        chapter_pairs = [
            (
                authority,
                ManuscriptChapterMeta(
                    number=authority.chapter_number,
                    title=authority.chapter_title,
                    scalar_count=validate_database_scalar_count(row.get("final_scalar_count")),
                    finalized_at_ms=authority.finalized_at_ms,
                ),
            )
            for authority, row in zip(authorities, chapter_rows, strict=True)
        ]
        chapter_pairs.sort(key=lambda pair: pair[0].chapter_number)
        volume_groups: dict[str, tuple[Volume, list[ManuscriptChapterMeta]]] = {}
        for authority, chapter in chapter_pairs:
            stored = volume_groups.setdefault(authority.volume.id, (authority.volume, []))
            if stored[0] != authority.volume:
                raise manuscript_corruption() from None
            stored[1].append(chapter)
        volumes = canonicalize_manuscript_volumes(tuple(
            ManuscriptVolume(
                id=volume.id, order=volume.order, title=volume.title,
                chapters=tuple(chapters),
            )
            for volume, chapters in volume_groups.values()
        ))
        return ManuscriptDirectoryRecord(
            project_id=project_id, title=title, lifecycle=lifecycle,
            volumes=volumes,
            total_scalar_count=sum(
                chapter.scalar_count for volume in volumes for chapter in volume.chapters
            ),
        )
    except (ValidationError, ValueError):
        raise manuscript_corruption() from None


def _lookup_from_rows(
    target_rows: list[Mapping[str, object]],
    neighbor_rows: list[Mapping[str, object]],
    chapter_number: int,
) -> ManuscriptChapterLookup:
    if not neighbor_rows:
        return ManuscriptChapterLookup(project_exists=False, chapter=None)
    project_ids = {row.get("project_id") for row in neighbor_rows}
    if len(project_ids) != 1 or not isinstance(next(iter(project_ids)), str):
        raise manuscript_corruption() from None
    if not target_rows:
        return ManuscriptChapterLookup(project_exists=True, chapter=None)
    if len(target_rows) != 1:
        raise manuscript_corruption() from None
    row = target_rows[0]
    project_id, title, lifecycle = _project_values(row)
    authority = decode_finalized_authority(row, expected_project_id=project_id)
    prose = row.get("final_content")
    prose_hash = row.get("final_content_hash")
    if (
        authority.chapter_number != chapter_number
        or not isinstance(prose, str) or not isinstance(prose_hash, str)
        or sha256(prose.encode("utf-8")).hexdigest() != prose_hash
    ):
        raise manuscript_corruption() from None
    numbers = []
    for neighbor in neighbor_rows:
        value = neighbor.get("final_chapter_num")
        if value is not None:
            if type(value) is not int or value < 1 or value in numbers:
                raise manuscript_corruption() from None
            numbers.append(value)
    numbers.sort()
    if chapter_number not in numbers:
        raise manuscript_corruption() from None
    index = numbers.index(chapter_number)
    try:
        chapter = FinalChapterRecord(
            project_id=project_id, book_title=title, lifecycle=lifecycle,
            number=authority.chapter_number, title=authority.chapter_title,
            content=prose, scalar_count=unicode_scalar_count(prose),
            finalized_at_ms=authority.finalized_at_ms,
            volume_id=authority.volume.id, volume_order=authority.volume.order,
            volume_title=authority.volume.title,
            previous_number=numbers[index - 1] if index else None,
            next_number=numbers[index + 1] if index + 1 < len(numbers) else None,
            outline=project_final_outline(authority.outline),
        )
        return ManuscriptChapterLookup(project_exists=True, chapter=chapter)
    except (ValidationError, ValueError):
        raise manuscript_corruption() from None


class ManuscriptRepository:
    async def load_directory(self, session, project_id: str) -> ManuscriptDirectoryRecord | None:
        try:
            rows = await session.fetchall(_DIRECTORY_SELECT, (project_id,))
        except (aiomysql.OperationalError, aiomysql.InterfaceError):
            raise ManuscriptUnavailable() from None
        return _directory_from_rows(rows)

    async def load_chapter(
        self, session, project_id: str, chapter_number: int,
    ) -> ManuscriptChapterLookup:
        try:
            target_rows = await session.fetchall(
                _TARGET_SELECT, (project_id, chapter_number),
            )
            neighbor_rows = await session.fetchall(_NEIGHBOR_SELECT, (project_id,))
        except (aiomysql.OperationalError, aiomysql.InterfaceError):
            raise ManuscriptUnavailable() from None
        return _lookup_from_rows(target_rows, neighbor_rows, chapter_number)


__all__ = (
    "decode_finalized_authority",
    "decode_json_object",
    "manuscript_corruption",
    "ManuscriptRepository",
    "PinnedFinalAuthority",
    "require_equal_pin",
)
