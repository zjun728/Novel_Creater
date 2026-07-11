"""Session-bound persistence for project foundation transactions."""

from __future__ import annotations

from collections.abc import Mapping
import time
from uuid import uuid4

from backend.repositories.project_lifecycle import (
    lock_active_project,
    read_active_project,
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

    async def list(self, session):
        return await session.fetchall(
            """SELECT * FROM projects WHERE status<>'archived'
               ORDER BY updated_at DESC, id DESC"""
        )

    async def get(self, session, project_id: str):
        return await read_active_project(session, project_id)

    async def lock_active_project(self, session, project_id: str):
        return await lock_active_project(session, project_id)

    async def archive(self, session, project_id: str) -> bool:
        changed = await session.execute(
            """UPDATE projects SET status='archived',updated_at=%s
               WHERE id=%s AND status<>'archived'""",
            (self._clock(), project_id),
        )
        return changed == 1

    async def update(self, session, project_id: str, changes: Mapping) -> bool:
        if not changes:
            return True
        allowed = {
            "title",
            "genre",
            "description",
            "target_words",
            "target_chapters",
            "current_chapter",
        }
        if not set(changes) <= allowed:
            raise ValueError("project update contains unsupported fields")
        sets = [f"{field}=%s" for field in changes]
        args = [changes[field] for field in changes]
        sets.append("updated_at=%s")
        args.extend((self._clock(), project_id))
        changed = await session.execute(
            f"UPDATE projects SET {', '.join(sets)} "
            "WHERE id=%s AND status<>'archived'",
            tuple(args),
        )
        return changed == 1

    async def content_state(self, session, project_id: str) -> dict:
        row = await session.fetchone(
            """SELECT
                 (SELECT COUNT(*) FROM creative_seeds WHERE project_id=%s)
                   AS seeds_count,
                 COALESCE((SELECT canon_revision_number FROM projection_heads
                           WHERE project_id=%s), 0) AS canon_head_revision,
                 (SELECT COUNT(*) FROM final_chapters WHERE project_id=%s)
                   AS final_chapters_count""",
            (project_id, project_id, project_id),
        )
        return {
            "seeds_count": int((row or {}).get("seeds_count") or 0),
            "canon_head_revision": int(
                (row or {}).get("canon_head_revision") or 0
            ),
            "has_final_chapters": bool(
                (row or {}).get("final_chapters_count")
            ),
        }

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
