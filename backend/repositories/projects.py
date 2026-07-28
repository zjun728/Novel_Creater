"""Session-bound persistence for project foundation transactions."""

from __future__ import annotations

import time
from uuid import uuid4

from backend.domain.provider_policy import GENERATION_PROVIDER_TYPE
from backend.repositories.chapter_outlines import ChapterOutlineRepository
from backend.repositories.chapter_sessions import (
    ChapterSessionRepository,
    authoritative_chapter,
)
from backend.repositories.project_lifecycle import (
    lock_active_project,
    lock_project,
    read_project,
)


_PROJECT_OWNED_DELETE_ORDER = (
    "reference_uses",
    "final_chapters",
    "finalization_records",
    "finalization_change_sets",
    "draft_candidates",
    "working_drafts",
    "chapter_sessions",
    "chapter_outline_confirmation_requests",
    "project_chapter_outline_heads",
    "chapter_outline_generation_attempts",
    "chapter_outline_drafts",
    "chapter_outline_revisions",
    "planning_confirmation_requests",
    "project_planning_heads",
    "planning_generation_attempts",
    "planning_drafts",
    "planning_revisions",
    "project_bible_heads",
    "bible_confirmation_requests",
    "project_bible_drafts",
    "bible_generation_attempts",
    "creation_bible_revisions",
    "project_contract_heads",
    "contract_confirmation_requests",
    "style_contracts",
    "project_contract_drafts",
    "creation_contracts",
    "story_engine_options",
    "story_engine_batches",
    "seed_inspiration_requests",
    "asset_recommendation_requests",
    "style_trial_requests",
    "seed_inspiration_attempts",
    "asset_recommendation_attempts",
    "style_trial_attempts",
    "market_analyses",
    "project_selected_seeds",
    "project_seed_selection_revisions",
)


class ProjectRepository:
    """All methods require the caller's explicit database session."""

    def __init__(
        self,
        *,
        id_factory=None,
        clock=None,
        chapter_session_repository=None,
        chapter_outline_repository=None,
    ):
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: int(time.time() * 1000))
        self.chapter_session_repository = (
            chapter_session_repository or ChapterSessionRepository()
        )
        self.chapter_outline_repository = (
            chapter_outline_repository or ChapterOutlineRepository()
        )

    async def insert_project(self, session, command) -> None:
        now = self._clock()
        await session.execute(
            """INSERT INTO projects
               (id, title, genre, description, target_words, target_chapters,
                status, current_chapter, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,'drafting',0,%s,%s)""",
            (
                command.id,
                command.title,
                command.genre,
                command.description,
                command.target_words,
                command.target_chapters,
                now,
                now,
            ),
        )

    async def list_active(self, session):
        return await session.fetchall(
            """SELECT * FROM projects WHERE archived_at IS NULL
               ORDER BY updated_at DESC, id DESC"""
        )

    async def list_archived(self, session):
        return await session.fetchall(
            """SELECT * FROM projects WHERE archived_at IS NOT NULL
               ORDER BY archived_at DESC, id DESC"""
        )

    async def get_any(self, session, project_id: str):
        return await read_project(session, project_id)

    async def read_preparation_snapshot(self, session, project_id: str):
        """Read authoritative preparation facts in the caller's snapshot."""

        project = await self.get_any(session, project_id)
        if project is None:
            return None
        selection = await session.fetchone(
            """SELECT selection_revision,seed_id,seed_revision_id,seed_hash
               FROM project_selected_seeds
               WHERE project_id=%s""",
            (project_id,),
        )
        contract_draft = await session.fetchone(
            """SELECT draft.selection_revision,revision.seed_id,
                      draft.seed_revision_id,draft.seed_hash,
                      draft.base_head_revision
               FROM project_contract_drafts draft
               LEFT JOIN creative_seed_revisions revision
                 ON revision.id=draft.seed_revision_id
                AND revision.content_hash=draft.seed_hash
               WHERE draft.project_id=%s""",
            (project_id,),
        )
        bible_head = await session.fetchone(
            """SELECT head.revision AS head_revision,
                      head.bible_revision_id AS head_bible_revision_id,
                      head.content_hash AS head_content_hash,
                      revision.id AS revision_id,
                      revision.revision,
                      revision.content_hash,
                      revision.selection_revision,
                      revision.seed_id,
                      revision.seed_revision_id,
                      revision.seed_hash,
                      revision.contract_revision,
                      revision.creation_contract_id,
                      revision.creation_hash,
                      revision.style_contract_id,
                      revision.style_hash,
                      revision.policy_version
               FROM project_bible_heads head
               LEFT JOIN creation_bible_revisions revision
                 ON revision.project_id=head.project_id
                AND revision.id=head.bible_revision_id
                AND revision.revision=head.revision
                AND revision.content_hash=head.content_hash
               WHERE head.project_id=%s""",
            (project_id,),
        )
        bible_draft = await session.fetchone(
            """SELECT id AS draft_id,base_head_revision,selection_revision,
                      seed_id,seed_revision_id,seed_hash,contract_revision,
                      creation_contract_id,creation_hash,style_contract_id,
                      style_hash,policy_version
               FROM project_bible_drafts
               WHERE project_id=%s AND active_slot=1""",
            (project_id,),
        )
        planning_head = await session.fetchone(
            """SELECT head.revision AS head_revision,
                      head.planning_revision_id,
                      head.content_hash AS head_content_hash,
                      revision.id AS revision_id,
                      revision.revision,
                      revision.content_hash,
                      revision.selection_revision,
                      revision.seed_id,
                      revision.seed_revision_id,
                      revision.seed_hash,
                      revision.contract_revision,
                      revision.creation_contract_id,
                      revision.creation_hash,
                      revision.style_contract_id,
                      revision.style_hash,
                      revision.bible_revision,
                      revision.bible_revision_id,
                      revision.bible_hash
               FROM project_planning_heads head
               LEFT JOIN planning_revisions revision
                 ON revision.project_id=head.project_id
                AND revision.id=head.planning_revision_id
                AND revision.revision=head.revision
                AND revision.content_hash=head.content_hash
               WHERE head.project_id=%s""",
            (project_id,),
        )
        planning_draft = await session.fetchone(
            """SELECT id AS draft_id,base_head_revision,draft_revision,
                      content_hash,status,selection_revision,seed_id,
                      seed_revision_id,seed_hash,contract_revision,
                      creation_contract_id,creation_hash,style_contract_id,
                      style_hash,bible_revision,bible_revision_id,bible_hash
               FROM planning_drafts
               WHERE project_id=%s AND active_slot=1 AND status='active'""",
            (project_id,),
        )
        planning_operation = await session.fetchone(
            """SELECT attempt.operation_id,attempt.status
               FROM planning_drafts draft
               JOIN planning_generation_attempts attempt
                 ON attempt.project_id=draft.project_id
                AND attempt.draft_id=draft.id
               WHERE draft.project_id=%s
                 AND draft.active_slot=1 AND draft.status='active'
                 AND attempt.active_slot=1 AND attempt.status='pending'
               ORDER BY attempt.created_at DESC,attempt.operation_id DESC
               LIMIT 1""",
            (project_id,),
        )
        active_session = (
            await self.chapter_session_repository.read_active_session(
                session,
                project_id,
            )
        )
        max_final_chapter_number = (
            await self.chapter_session_repository
            .read_max_final_chapter_number(session, project_id)
        )
        authoritative_chapter_number = authoritative_chapter(
            active_session,
            max_final_chapter_number,
        )
        outline_head = await self.chapter_outline_repository.read_outline_head(
            session,
            project_id,
            authoritative_chapter_number,
        )
        outline_draft = (
            await self.chapter_outline_repository.read_active_draft(
                session,
                project_id,
                authoritative_chapter_number,
            )
        )
        outline_operation = (
            await self.chapter_outline_repository.read_active_attempt(
                session,
                str(outline_draft["id"]),
            )
            if outline_draft is not None
            else None
        )
        canon_projection = await session.fetchone(
            """SELECT canon_revision_number AS canon_revision,
                      projection_revision_number AS projection_revision,
                      content_hash AS projection_hash
               FROM projection_heads
               WHERE project_id=%s""",
            (project_id,),
        )
        model_tasks = await session.fetchall(
            f"""SELECT item.task_key,item.resolution_status,
                       CASE WHEN
                         provider.id IS NOT NULL
                         AND provider.lifecycle_status='active'
                         AND provider.enabled=1
                         AND LOWER(TRIM(provider.provider_type))=
                           '{GENERATION_PROVIDER_TYPE}'
                         AND provider.model_name IS NOT NULL
                         AND TRIM(provider.model_name)<>''
                         AND provider.base_url IS NOT NULL
                         AND TRIM(provider.base_url)<>''
                         AND provider.api_key IS NOT NULL
                         AND TRIM(provider.api_key)<>''
                       THEN 1 ELSE 0 END AS provider_ready,
                       CASE WHEN provider.model_name=item.model_name_snapshot
                       THEN 1 ELSE 0 END AS model_snapshot_matches
                FROM project_model_binding_heads head
                JOIN project_model_binding_revisions revision
                  ON revision.project_id=head.project_id
                 AND revision.id=head.binding_revision_id
                 AND revision.revision=head.revision
                 AND revision.content_hash=head.content_hash
                JOIN project_model_binding_items item
                  ON item.binding_revision_id=revision.id
                LEFT JOIN provider_profiles provider
                  ON provider.id=item.provider_id
                WHERE head.project_id=%s
                ORDER BY CASE item.task_key
                  WHEN 'seed' THEN 1 WHEN 'planning' THEN 2
                  WHEN 'writing' THEN 3 WHEN 'audit' THEN 4
                  WHEN 'summary' THEN 5 WHEN 'extraction' THEN 6
                  WHEN 'polish' THEN 7 WHEN 'market' THEN 8 ELSE 9 END""",
            (project_id,),
        )
        return {
            "project": project,
            "selection": selection,
            "contract_draft": contract_draft,
            "bible_head": bible_head,
            "bible_draft": bible_draft,
            "planning_head": planning_head,
            "planning_draft": planning_draft,
            "planning_operation": planning_operation,
            "active_session": active_session,
            "max_final_chapter_number": max_final_chapter_number,
            "authoritative_chapter_number": authoritative_chapter_number,
            "canon_projection": canon_projection,
            "outline_head": outline_head,
            "outline_draft": outline_draft,
            "outline_operation": outline_operation,
            "model_tasks": tuple(model_tasks),
        }

    async def lock_any(self, session, project_id: str):
        return await lock_project(session, project_id)

    async def lock_active_project(self, session, project_id: str):
        return await lock_active_project(session, project_id)

    async def has_unfinished_operation(self, session, project_id: str) -> bool:
        row = await session.fetchone(
            """SELECT 1 AS present
               WHERE EXISTS (
                 SELECT 1 FROM story_engine_batches
                  WHERE project_id=%s
                    AND status IN ('reserved','running','outcome_unknown')
               )
               OR EXISTS (
                 SELECT 1 FROM planning_generation_attempts
                  WHERE project_id=%s
                    AND status='pending'
                    AND active_slot=1
                    AND lease_expires_at>%s
               )
               LIMIT 1""",
            (project_id, project_id, self._clock()),
        )
        return row is not None

    async def archive(
        self, session, project_id: str, expected_revision: int
    ) -> bool:
        now = self._clock()
        changed = await session.execute(
            """UPDATE projects
               SET archived_at=%s,
                   lifecycle_revision=lifecycle_revision+1,
                   updated_at=%s
               WHERE id=%s
                 AND archived_at IS NULL
                 AND lifecycle_revision=%s""",
            (now, now, project_id, expected_revision),
        )
        return changed == 1

    async def restore(
        self, session, project_id: str, expected_revision: int
    ) -> bool:
        changed = await session.execute(
            """UPDATE projects
               SET archived_at=NULL,
                   lifecycle_revision=lifecycle_revision+1,
                   updated_at=%s
               WHERE id=%s
                 AND archived_at IS NOT NULL
                 AND lifecycle_revision=%s""",
            (self._clock(), project_id, expected_revision),
        )
        return changed == 1

    async def permanently_delete(
        self, session, project_id: str, expected_revision: int
    ) -> bool:
        eligible = await session.fetchone(
            """SELECT id FROM projects
               WHERE id=%s
                 AND archived_at IS NOT NULL
                 AND lifecycle_revision=%s
               FOR UPDATE""",
            (project_id, expected_revision),
        )
        if eligible is None:
            return False
        await self._delete_owned_graph(session, project_id)
        changed = await session.execute(
            """DELETE FROM projects
               WHERE id=%s
                 AND archived_at IS NOT NULL
                 AND lifecycle_revision=%s""",
            (project_id, expected_revision),
        )
        return changed == 1

    async def _delete_owned_graph(self, session, project_id: str) -> None:
        """Delete only project-owned rows before the guarded project delete.

        Immutable lineage foreign keys remain restrictive for every ordinary
        delete. This method is reachable only from the archived-project
        permanent-delete entry point and runs in that entry point's transaction.
        Shared providers, assets, and corpus identities are deliberately absent.
        """

        for table_name in _PROJECT_OWNED_DELETE_ORDER:
            await session.execute(
                f"DELETE FROM {table_name} WHERE project_id=%s",
                (project_id,),
            )
        await session.execute(
            """DELETE heads FROM creative_seed_heads heads
               JOIN creative_seeds seeds ON seeds.id=heads.seed_id
               WHERE seeds.project_id=%s""",
            (project_id,),
        )
        await session.execute(
            "DELETE FROM creative_seed_revisions WHERE project_id=%s",
            (project_id,),
        )
        await session.execute(
            "DELETE FROM creative_seeds WHERE project_id=%s",
            (project_id,),
        )
        await session.execute(
            "DELETE FROM project_model_binding_heads WHERE project_id=%s",
            (project_id,),
        )
        await session.execute(
            "DELETE FROM project_model_binding_revisions WHERE project_id=%s",
            (project_id,),
        )

    async def rename(self, session, project_id: str, title: str) -> bool:
        changed = await session.execute(
            """UPDATE projects
               SET title=%s, updated_at=%s
               WHERE id=%s AND archived_at IS NULL""",
            (title, self._clock(), project_id),
        )
        return changed == 1

    async def insert_bootstrap_revision(
        self, session, project_id: str, *, content_hash: str, idempotency_key: str
    ) -> None:
        await session.execute(
            """INSERT INTO canon_revisions
               (id, project_id, revision_number, parent_revision_number,
                idempotency_key, source_type, source_id, content_hash, created_at)
               VALUES (%s,%s,0,0,%s,'bootstrap',NULL,%s,%s)""",
            (
                self._id_factory(),
                project_id,
                idempotency_key,
                content_hash,
                self._clock(),
            ),
        )

    async def insert_projection_head(
        self, session, project_id: str, *, content_hash: str
    ) -> None:
        await session.execute(
            """INSERT INTO projection_heads
               (project_id, canon_revision_number, projection_revision_number,
                content_hash, updated_at) VALUES (%s,0,0,%s,%s)""",
            (project_id, content_hash, self._clock()),
        )

    async def insert_contract_head0(self, session, project_id: str) -> None:
        await session.execute(
            """INSERT INTO project_contract_heads
               (project_id, revision, creation_contract_id, style_contract_id,
                creation_hash, style_hash, updated_at)
               VALUES (%s,0,NULL,NULL,NULL,NULL,%s)""",
            (project_id, self._clock()),
        )

    async def insert_bible_head0(self, session, project_id: str) -> None:
        await session.execute(
            """INSERT INTO project_bible_heads
               (project_id, revision, bible_revision_id, content_hash, updated_at)
               VALUES (%s,0,NULL,NULL,%s)""",
            (project_id, self._clock()),
        )

    async def insert_planning_head0(self, session, project_id: str) -> None:
        await session.execute(
            """INSERT INTO project_planning_heads
               (project_id, revision, planning_revision_id, content_hash, updated_at)
               VALUES (%s,0,NULL,NULL,%s)""",
            (project_id, self._clock()),
        )
