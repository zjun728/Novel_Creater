"""Session-bound persistence for immutable seed revisions and selection CAS."""

from __future__ import annotations

from backend.repositories.project_lifecycle import (
    lock_active_project,
    read_active_project,
)


class SeedRepository:
    """Every method uses the explicit session supplied by its caller."""

    async def lock_project(self, session, project_id: str):
        return await lock_active_project(session, project_id)

    async def read_project(self, session, project_id: str):
        return await read_active_project(session, project_id)

    async def count_final_chapters(self, session, project_id: str) -> int:
        row = await session.fetchone(
            "SELECT COUNT(*) AS count FROM final_chapters WHERE project_id=%s",
            (project_id,),
        )
        return int((row or {}).get("count") or 0)

    async def list_heads(self, session, project_id: str):
        return await session.fetchall(
            """SELECT s.id, s.project_id, s.status, s.created_at, s.updated_at,
                      r.id AS revision_id, r.revision, r.payload_json,
                      r.content_hash,
                      CASE WHEN selected.seed_id=s.id THEN 1 ELSE 0 END
                        AS is_selected,
                      COALESCE(selected.selection_revision, 0)
                        AS selection_revision
               FROM creative_seeds s
               JOIN creative_seed_heads h ON h.seed_id=s.id
               JOIN creative_seed_revisions r
                 ON r.seed_id=h.seed_id AND r.id=h.revision_id
               LEFT JOIN project_selected_seeds selected
                 ON selected.project_id=s.project_id
               WHERE s.project_id=%s
               ORDER BY s.created_at DESC, s.id DESC""",
            (project_id,),
        )

    async def lock_seed_head(self, session, project_id: str, seed_id: str):
        return await session.fetchone(
            """SELECT s.id, s.project_id, s.status, s.created_at, s.updated_at,
                      r.id AS revision_id, r.revision, r.payload_json,
                      r.content_hash
               FROM creative_seeds s
               JOIN creative_seed_heads h ON h.seed_id=s.id
               JOIN creative_seed_revisions r
                 ON r.seed_id=h.seed_id AND r.id=h.revision_id
               WHERE s.project_id=%s AND s.id=%s
               FOR UPDATE""",
            (project_id, seed_id),
        )

    async def lock_selection(self, session, project_id: str):
        return await session.fetchone(
            """SELECT project_id, seed_id, seed_revision_id, seed_hash,
                      selection_revision, selected_at, updated_at
               FROM project_selected_seeds WHERE project_id=%s FOR UPDATE""",
            (project_id,),
        )

    async def insert_identity(self, session, row: dict) -> None:
        await session.execute(
            """INSERT INTO creative_seeds
               (id, project_id, status, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s)""",
            (
                row["id"], row["project_id"], row["status"],
                row["created_at"], row["updated_at"],
            ),
        )

    async def insert_revision(self, session, row: dict) -> None:
        await session.execute(
            """INSERT INTO creative_seed_revisions
               (id, project_id, seed_id, revision, payload_json,
                content_hash, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["id"], row["project_id"], row["seed_id"],
                row["revision"], row["payload_json"], row["content_hash"],
                row["created_at"],
            ),
        )

    async def insert_head(self, session, row: dict) -> None:
        await session.execute(
            """INSERT INTO creative_seed_heads
               (seed_id, revision_id, revision, content_hash, updated_at)
               VALUES (%s,%s,%s,%s,%s)""",
            (
                row["seed_id"], row["revision_id"], row["revision"],
                row["content_hash"], row["updated_at"],
            ),
        )

    async def update_head(self, session, row: dict) -> None:
        await session.execute(
            """UPDATE creative_seed_heads
               SET revision_id=%s, revision=%s, content_hash=%s, updated_at=%s
               WHERE seed_id=%s""",
            (
                row["revision_id"], row["revision"], row["content_hash"],
                row["updated_at"], row["seed_id"],
            ),
        )
        await session.execute(
            "UPDATE creative_seeds SET updated_at=%s WHERE id=%s",
            (row["updated_at"], row["seed_id"]),
        )

    async def insert_selection(self, session, row: dict) -> None:
        await session.execute(
            """INSERT INTO project_selected_seeds
               (project_id, seed_id, seed_revision_id, seed_hash,
                selection_revision, selected_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["project_id"], row["seed_id"], row["seed_revision_id"],
                row["seed_hash"], row["selection_revision"],
                row["selected_at"], row["updated_at"],
            ),
        )

    async def advance_selected_revision(self, session, row: dict) -> None:
        await session.execute(
            """UPDATE project_selected_seeds
               SET seed_revision_id=%s, seed_hash=%s,
                   selection_revision=%s, updated_at=%s
               WHERE project_id=%s""",
            (
                row["seed_revision_id"], row["seed_hash"],
                row["selection_revision"], row["updated_at"],
                row["project_id"],
            ),
        )

    async def replace_selection(self, session, row: dict) -> None:
        await session.execute(
            """UPDATE project_selected_seeds
               SET seed_id=%s, seed_revision_id=%s, seed_hash=%s,
                   selection_revision=%s, selected_at=%s, updated_at=%s
               WHERE project_id=%s""",
            (
                row["seed_id"], row["seed_revision_id"], row["seed_hash"],
                row["selection_revision"], row["selected_at"],
                row["updated_at"],
                row["project_id"],
            ),
        )

    async def dependency_count(
        self, session, project_id: str, seed_id: str
    ) -> int:
        row = await session.fetchone(
            """SELECT
                 (SELECT COUNT(*) FROM story_engine_batches
                   WHERE project_id=%s AND seed_id=%s)
                 +
                 (SELECT COUNT(*) FROM project_contract_drafts d
                   JOIN creative_seed_revisions r ON r.id=d.seed_revision_id
                   WHERE d.project_id=%s AND r.seed_id=%s)
                 +
                 (SELECT COUNT(*) FROM creation_contracts
                   WHERE project_id=%s AND seed_id=%s) AS count""",
            (project_id, seed_id, project_id, seed_id, project_id, seed_id),
        )
        return int((row or {}).get("count") or 0)

    async def archive(
        self, session, project_id: str, seed_id: str, updated_at: int
    ) -> None:
        await session.execute(
            """UPDATE creative_seeds SET status='archived', updated_at=%s
               WHERE project_id=%s AND id=%s""",
            (updated_at, project_id, seed_id),
        )

    async def physical_delete(
        self, session, project_id: str, seed_id: str
    ) -> None:
        await session.execute(
            "DELETE FROM creative_seed_heads WHERE seed_id=%s", (seed_id,)
        )
        await session.execute(
            """DELETE FROM creative_seed_revisions
               WHERE project_id=%s AND seed_id=%s""",
            (project_id, seed_id),
        )
        await session.execute(
            "DELETE FROM creative_seeds WHERE project_id=%s AND id=%s",
            (project_id, seed_id),
        )

    async def read_selection(self, session, project_id: str):
        return await session.fetchone(
            """SELECT s.id, s.project_id, s.status, s.created_at, s.updated_at,
                      r.id AS revision_id, r.revision, r.payload_json,
                      r.content_hash, selected.selection_revision,
                      1 AS is_selected
               FROM project_selected_seeds selected
               JOIN creative_seeds s
                 ON s.project_id=selected.project_id AND s.id=selected.seed_id
               JOIN creative_seed_revisions r
                 ON r.seed_id=selected.seed_id
                AND r.id=selected.seed_revision_id
               WHERE selected.project_id=%s""",
            (project_id,),
        )

    async def read_contract_facts(self, session, project_id: str):
        return await session.fetchone(
            """SELECT h.revision, c.seed_id, c.seed_revision_id, c.seed_hash
               FROM project_contract_heads h
               LEFT JOIN creation_contracts c
                 ON c.project_id=h.project_id
                AND c.id=h.creation_contract_id
               WHERE h.project_id=%s""",
            (project_id,),
        )
