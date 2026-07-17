"""Session-bound persistence for project foundation transactions."""

from __future__ import annotations

import time
from uuid import uuid4

from backend.repositories.project_lifecycle import (
    lock_active_project,
    lock_project,
    read_project,
)


class ProjectRepository:
    """All methods require the caller's explicit database session."""

    def __init__(self, *, id_factory=None, clock=None):
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: int(time.time() * 1000))

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

    async def lock_any(self, session, project_id: str):
        return await lock_project(session, project_id)

    async def lock_active_project(self, session, project_id: str):
        return await lock_active_project(session, project_id)

    async def has_unfinished_operation(self, session, project_id: str) -> bool:
        row = await session.fetchone(
            """SELECT 1 AS present
               FROM story_engine_batches
               WHERE project_id=%s
                 AND status IN ('reserved','running','outcome_unknown')
               LIMIT 1""",
            (project_id,),
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
        changed = await session.execute(
            """DELETE FROM projects
               WHERE id=%s
                 AND archived_at IS NOT NULL
                 AND lifecycle_revision=%s""",
            (project_id, expected_revision),
        )
        return changed == 1

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
