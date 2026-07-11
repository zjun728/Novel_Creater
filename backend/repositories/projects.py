"""Session-bound persistence for project foundation transactions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import time
from uuid import uuid4


@dataclass(frozen=True)
class PreviousBindingSnapshot:
    source_project_id: str
    provider_ids: Mapping[str, str]


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
            "SELECT * FROM projects ORDER BY updated_at DESC, id DESC"
        )

    async def get(self, session, project_id: str):
        return await session.fetchone(
            "SELECT * FROM projects WHERE id=%s", (project_id,)
        )

    async def update(self, session, project_id: str, changes: Mapping) -> None:
        if not changes:
            return
        allowed = {
            "title",
            "genre",
            "description",
            "target_words",
            "target_chapters",
            "current_chapter",
            "status",
        }
        if not set(changes) <= allowed:
            raise ValueError("project update contains unsupported fields")
        sets = [f"{field}=%s" for field in changes]
        args = [changes[field] for field in changes]
        sets.append("updated_at=%s")
        args.extend((self._clock(), project_id))
        await session.execute(
            f"UPDATE projects SET {', '.join(sets)} WHERE id=%s", tuple(args)
        )

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

    async def list_enabled_providers(self, session):
        return await session.fetchall(
            """SELECT id, model_name FROM provider_profiles
               WHERE enabled=1
               ORDER BY sort_order ASC, created_at ASC, id ASC"""
        )

    async def find_previous_binding_snapshot(
        self, session, project_id: str
    ) -> PreviousBindingSnapshot | None:
        rows = await session.fetchall(
            """SELECT p.id AS source_project_id, i.task_key, i.provider_id
               FROM projects p
               LEFT JOIN task_model_bindings b ON b.project_id=p.id
               LEFT JOIN task_model_binding_items i ON i.binding_id=b.id
               WHERE p.id<>%s
               ORDER BY p.created_at DESC, p.id DESC, i.task_key ASC""",
            (project_id,),
        )
        if not rows:
            return None
        source_project_id = rows[0]["source_project_id"]
        provider_ids = {
            row["task_key"]: row["provider_id"]
            for row in rows
            if row["source_project_id"] == source_project_id
            and row.get("task_key")
            and row.get("provider_id")
        }
        return PreviousBindingSnapshot(source_project_id, provider_ids)

    async def insert_binding_snapshot(
        self, session, project_id: str, *, source_project_id: str | None
    ) -> str:
        binding_id = self._id_factory()
        now = self._clock()
        await session.execute(
            """INSERT INTO task_model_bindings
               (id, project_id, source_project_id, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s)""",
            (binding_id, project_id, source_project_id, now, now),
        )
        return binding_id

    async def insert_binding_items(
        self,
        session,
        project_id: str,
        binding_id: str,
        items: Mapping[str, Mapping[str, str]],
    ) -> None:
        now = self._clock()
        for task_key, item in items.items():
            await session.execute(
                """INSERT INTO task_model_binding_items
                   (id, project_id, binding_id, task_key, provider_id,
                    model_name, created_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    self._id_factory(),
                    project_id,
                    binding_id,
                    task_key,
                    item["provider_id"],
                    item["model_name"],
                    now,
                    now,
                ),
            )

    async def delete(self, session, project_id: str) -> None:
        await session.execute("DELETE FROM projects WHERE id=%s", (project_id,))
