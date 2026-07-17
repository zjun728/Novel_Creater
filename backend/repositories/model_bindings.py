"""Session-bound persistence for immutable project model bindings."""

from __future__ import annotations

import time
from uuid import uuid4

from backend.repositories.project_lifecycle import (
    lock_active_project,
    read_active_project,
)


AVAILABLE_PROVIDER_PREDICATE = """lifecycle_status='active'
  AND enabled=1
  AND provider_type IS NOT NULL AND TRIM(provider_type)<>''
  AND model_name IS NOT NULL AND TRIM(model_name)<>''
  AND base_url IS NOT NULL AND TRIM(base_url)<>''
  AND api_key IS NOT NULL AND TRIM(api_key)<>''"""


class ModelBindingRepository:
    """Every method uses the explicit session supplied by its caller."""

    def __init__(self, *, id_factory=None, clock=None):
        self.id_factory = id_factory or (lambda: str(uuid4()))
        self.clock = clock or (lambda: int(time.time() * 1000))

    async def lock_project_creation_guard(self, session) -> None:
        row = await session.fetchone(
            """SELECT singleton_id FROM schema_metadata
               WHERE singleton_id=1 FOR UPDATE"""
        )
        if row is None:
            raise RuntimeError("project creation guard is unavailable")

    async def lock_previous_project(self, session, project_id: str):
        return await session.fetchone(
            """SELECT id FROM projects
               WHERE id<>%s AND archived_at IS NULL
               ORDER BY created_at DESC, id DESC LIMIT 1 FOR UPDATE""",
            (project_id,),
        )

    async def list_available_providers(self, session):
        return await session.fetchall(
            f"""SELECT id,name,provider_type,model_name,base_url,api_key,
                       enabled,lifecycle_status,sort_order,created_at
                FROM provider_profiles
                WHERE {AVAILABLE_PROVIDER_PREDICATE}
                ORDER BY sort_order ASC, created_at ASC, id ASC"""
        )

    async def read_project(self, session, project_id: str):
        return await read_active_project(session, project_id)

    async def lock_project(self, session, project_id: str):
        return await lock_active_project(session, project_id)

    @staticmethod
    def _read_current_sql() -> str:
        return """SELECT h.project_id,h.revision,h.binding_revision_id,
                           h.content_hash,r.source_project_id,r.created_at,
                           i.task_key,i.resolution_status,i.provider_id,
                           i.provider_name_snapshot,i.model_name_snapshot,
                           i.item_hash,
                           p.name AS current_provider_name,
                           p.model_name AS current_model_name,
                           p.provider_type AS current_provider_type,
                           p.base_url AS current_base_url,
                           p.api_key AS current_api_key,
                           p.enabled AS current_enabled,
                           p.lifecycle_status AS current_lifecycle_status
                    FROM project_model_binding_heads h
                    JOIN project_model_binding_revisions r
                      ON r.project_id=h.project_id
                     AND r.id=h.binding_revision_id
                    JOIN project_model_binding_items i
                      ON i.binding_revision_id=r.id
                    LEFT JOIN provider_profiles p ON p.id=i.provider_id
                    WHERE h.project_id=%s
                    ORDER BY CASE i.task_key
                      WHEN 'seed' THEN 1 WHEN 'planning' THEN 2
                      WHEN 'writing' THEN 3 WHEN 'audit' THEN 4
                      WHEN 'summary' THEN 5 WHEN 'extraction' THEN 6
                      WHEN 'polish' THEN 7 WHEN 'market' THEN 8 ELSE 9 END"""

    @staticmethod
    def _lock_current_sql() -> str:
        return """SELECT h.project_id,h.revision,h.binding_revision_id,
                          h.content_hash,r.source_project_id,r.created_at,
                          i.task_key,i.resolution_status,i.provider_id,
                          i.provider_name_snapshot,i.model_name_snapshot,
                          i.item_hash
                   FROM project_model_binding_heads h
                   JOIN project_model_binding_revisions r
                     ON r.project_id=h.project_id
                    AND r.id=h.binding_revision_id
                   JOIN project_model_binding_items i
                     ON i.binding_revision_id=r.id
                   WHERE h.project_id=%s
                   ORDER BY CASE i.task_key
                     WHEN 'seed' THEN 1 WHEN 'planning' THEN 2
                     WHEN 'writing' THEN 3 WHEN 'audit' THEN 4
                     WHEN 'summary' THEN 5 WHEN 'extraction' THEN 6
                     WHEN 'polish' THEN 7 WHEN 'market' THEN 8 ELSE 9 END
                   FOR UPDATE"""

    async def read_current_rows(self, session, project_id: str):
        return await session.fetchall(
            self._read_current_sql(), (project_id,)
        )

    async def lock_current_rows(self, session, project_id: str):
        return await session.fetchall(
            self._lock_current_sql(), (project_id,)
        )

    async def lock_providers(self, session, provider_ids: set[str]):
        if not provider_ids:
            return []
        ordered = tuple(sorted(provider_ids))
        placeholders = ",".join("%s" for _ in ordered)
        return await session.fetchall(
            f"""SELECT id,name,provider_type,model_name,base_url,api_key,
                       enabled,lifecycle_status,sort_order,created_at
                FROM provider_profiles WHERE id IN ({placeholders})
                ORDER BY id ASC FOR UPDATE""",
            ordered,
        )

    async def insert_revision(self, session, row: dict) -> None:
        await session.execute(
            """INSERT INTO project_model_binding_revisions
               (id,project_id,revision,content_hash,source_project_id,created_at)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (
                row["id"], row["project_id"], row["revision"],
                row["content_hash"], row["source_project_id"], row["created_at"],
            ),
        )

    async def insert_items(self, session, revision_id: str, rows: tuple[dict, ...]):
        for row in rows:
            await session.execute(
                """INSERT INTO project_model_binding_items
                   (binding_revision_id,task_key,resolution_status,provider_id,
                    provider_name_snapshot,model_name_snapshot,item_hash)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (
                    revision_id, row["task_key"], row["resolution_status"],
                    row["provider_id"], row["provider_name_snapshot"],
                    row["model_name_snapshot"], row["item_hash"],
                ),
            )

    async def insert_head(self, session, row: dict) -> None:
        await session.execute(
            """INSERT INTO project_model_binding_heads
               (project_id,revision,binding_revision_id,content_hash,updated_at)
               VALUES (%s,%s,%s,%s,%s)""",
            (
                row["project_id"], row["revision"], row["binding_revision_id"],
                row["content_hash"], row["updated_at"],
            ),
        )

    async def compare_and_swap_head(
        self, session, row: dict, *, expected_revision: int
    ) -> bool:
        changed = await session.execute(
            """UPDATE project_model_binding_heads
               SET revision=%s,binding_revision_id=%s,content_hash=%s,updated_at=%s
               WHERE project_id=%s AND revision=%s""",
            (
                row["revision"], row["binding_revision_id"], row["content_hash"],
                row["updated_at"], row["project_id"], expected_revision,
            ),
        )
        return changed == 1
