"""Snapshot-bound authority reads for the project overview."""

from __future__ import annotations

from collections.abc import Mapping

from backend.repositories.chapter_outlines import ChapterOutlineRepository
from backend.repositories.chapter_sessions import (
    ChapterSessionRepository,
    authoritative_chapter,
)


class ProjectOverviewRepository:
    """Aggregate overview facts without crossing the caller's read snapshot."""

    def __init__(
        self,
        *,
        chapter_session_repository=None,
        chapter_outline_repository=None,
    ):
        self.chapter_session_repository = (
            chapter_session_repository or ChapterSessionRepository()
        )
        self.chapter_outline_repository = (
            chapter_outline_repository or ChapterOutlineRepository()
        )

    async def read_snapshot(self, session, project_id: str):
        project = await session.fetchone(
            """SELECT id,title,genre,description,target_words,target_chapters,
                      status,current_chapter,archived_at,lifecycle_revision,
                      created_at,updated_at
                 FROM projects
                WHERE id=%s""",
            (project_id,),
        )
        if project is None:
            return None

        selected_seed = await session.fetchone(
            """SELECT selected.selection_revision,selected.selected_at,
                      selected.updated_at,revision.payload_json
                 FROM project_selected_seeds selected
                 JOIN project_seed_selection_revisions selection
                   ON selection.project_id=selected.project_id
                  AND selection.selection_revision=selected.selection_revision
                  AND selection.seed_id=selected.seed_id
                  AND selection.seed_revision_id=selected.seed_revision_id
                  AND selection.seed_hash=selected.seed_hash
                 JOIN creative_seed_revisions revision
                   ON revision.project_id=selection.project_id
                  AND revision.seed_id=selection.seed_id
                  AND revision.id=selection.seed_revision_id
                  AND revision.content_hash=selection.seed_hash
                WHERE selected.project_id=%s""",
            (project_id,),
        )
        contract = await session.fetchone(
            """SELECT head.revision,head.updated_at,
                      EXISTS(
                        SELECT 1
                          FROM project_contract_drafts draft
                         WHERE draft.project_id=head.project_id
                      ) AS has_draft
                 FROM project_contract_heads head
                WHERE head.project_id=%s""",
            (project_id,),
        )
        bible = await session.fetchone(
            """SELECT head.revision,head.updated_at,
                      EXISTS(
                        SELECT 1
                          FROM project_bible_drafts draft
                         WHERE draft.project_id=head.project_id
                           AND draft.active_slot=1
                      ) AS has_draft
                 FROM project_bible_heads head
                WHERE head.project_id=%s""",
            (project_id,),
        )
        planning = await session.fetchone(
            """SELECT head.revision,head.updated_at,revision.content_json,
                      EXISTS(
                        SELECT 1
                          FROM planning_drafts draft
                         WHERE draft.project_id=head.project_id
                           AND draft.active_slot=1
                           AND draft.status='active'
                      ) AS has_draft
                 FROM project_planning_heads head
                 LEFT JOIN planning_revisions revision
                   ON revision.project_id=head.project_id
                  AND revision.id=head.planning_revision_id
                  AND revision.revision=head.revision
                  AND revision.content_hash=head.content_hash
                WHERE head.project_id=%s""",
            (project_id,),
        )

        active_session = (
            await self.chapter_session_repository.read_active_session(
                session,
                project_id,
            )
        )
        max_final_chapter = (
            await self.chapter_session_repository.read_max_final_chapter_number(
                session,
                project_id,
            )
        )
        authoritative_chapter_number = authoritative_chapter(
            active_session,
            max_final_chapter,
        )

        outline_head = await self.chapter_outline_repository.read_outline_head(
            session,
            project_id,
            authoritative_chapter_number,
        )
        outline_draft = await self.chapter_outline_repository.read_active_draft(
            session,
            project_id,
            authoritative_chapter_number,
        )
        outline = self._outline_fact(outline_head, outline_draft is not None)

        writer_core = await session.fetchone(
            """SELECT canon_revision_number AS canon_revision,
                      projection_revision_number AS projection_revision
                 FROM projection_heads
                WHERE project_id=%s""",
            (project_id,),
        )
        aggregate_row = await session.fetchone(
            """SELECT COUNT(*) AS chapter_count,
                      COALESCE(SUM(CHAR_LENGTH(content)),0) AS scalar_count,
                      MAX(chapter_num) AS latest_number
                 FROM final_chapters
                WHERE project_id=%s""",
            (project_id,),
        )
        final_aggregate = self._final_aggregate(aggregate_row)
        latest_number = final_aggregate["latest_number"]
        if latest_number is not None:
            latest = await session.fetchone(
                """SELECT chapter_num AS latest_number,
                          title AS latest_title,
                          finalized_at AS latest_finalized_at
                     FROM final_chapters
                    WHERE project_id=%s AND chapter_num=%s""",
                (project_id, latest_number),
            )
            if latest is not None:
                final_aggregate.update(dict(latest))

        return {
            "project": dict(project),
            "selected_seed": self._mapping_or_none(selected_seed),
            "contract": self._mapping_or_none(contract),
            "bible": self._mapping_or_none(bible),
            "planning": self._mapping_or_none(planning),
            "outline": outline,
            "session": self._mapping_or_none(active_session),
            "writer_core": self._mapping_or_none(writer_core),
            "final_aggregate": final_aggregate,
            "authoritative_chapter_number": authoritative_chapter_number,
        }

    @staticmethod
    def _mapping_or_none(row):
        return dict(row) if row is not None else None

    @staticmethod
    def _outline_fact(
        head: Mapping[str, object] | None,
        has_draft: bool,
    ) -> dict[str, object]:
        if head is None:
            return {
                "revision": None,
                "updated_at": None,
                "content_json": None,
                "has_draft": has_draft,
            }
        content = head.get("content_json", head.get("content"))
        return {
            "revision": head.get("revision"),
            "updated_at": head.get("updated_at"),
            "content_json": content,
            "has_draft": has_draft,
        }

    @staticmethod
    def _final_aggregate(row) -> dict[str, object]:
        aggregate = dict(row) if row is not None else {}
        latest_number = aggregate.get("latest_number")
        return {
            "chapter_count": int(aggregate.get("chapter_count") or 0),
            "scalar_count": int(aggregate.get("scalar_count") or 0),
            "latest_number": (
                int(latest_number) if latest_number is not None else None
            ),
            "latest_title": None,
            "latest_finalized_at": None,
        }


__all__ = ("ProjectOverviewRepository",)
