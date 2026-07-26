"""Session-bound persistence for authoritative ChapterOutline state."""

from __future__ import annotations

import json

from backend.domain.json_contracts import canonical_json
from backend.repositories.project_lifecycle import (
    lock_active_project,
    read_project,
)


_OUTLINE_HEAD_SELECT = """
SELECT head.project_id,head.chapter_num,head.revision,
       head.outline_revision_id,head.content_hash,head.updated_at,
       revision.parent_revision,revision.planning_revision_id,
       revision.planning_revision,revision.planning_hash,
       revision.canon_revision,revision.projection_revision,
       revision.projection_hash,revision.content_json,
       revision.created_at
  FROM project_chapter_outline_heads head
  LEFT JOIN chapter_outline_revisions revision
    ON revision.project_id=head.project_id
   AND revision.chapter_num=head.chapter_num
   AND revision.id=head.outline_revision_id
   AND revision.revision=head.revision
   AND revision.content_hash=head.content_hash
"""


class ChapterOutlineRepository:
    async def lock_project(self, session, project_id: str):
        return await lock_active_project(session, project_id)

    async def read_project_any(self, session, project_id: str):
        return await read_project(session, project_id)

    async def read_current_authorities(self, session, project_id: str):
        row = await session.fetchone(
            """SELECT planning.id AS planning_revision_id,
                      planning.revision AS planning_revision,
                      planning.content_hash AS planning_hash,
                      planning.content_json AS planning_content_json,
                      creation.chapter_capacity_policy,
                      projection.canon_revision_number AS canon_revision,
                      projection.projection_revision_number
                        AS projection_revision,
                      projection.content_hash AS projection_hash
                 FROM project_planning_heads planning_head
                 JOIN planning_revisions planning
                   ON planning.project_id=planning_head.project_id
                  AND planning.id=planning_head.planning_revision_id
                  AND planning.revision=planning_head.revision
                  AND planning.content_hash=planning_head.content_hash
                 JOIN creation_contracts creation
                   ON creation.project_id=planning.project_id
                  AND creation.id=planning.creation_contract_id
                  AND creation.revision=planning.contract_revision
                  AND creation.content_hash=planning.creation_hash
                 JOIN projection_heads projection
                   ON projection.project_id=planning_head.project_id
                WHERE planning_head.project_id=%s
                  AND planning_head.revision>0""",
            (project_id,),
        )
        if row is None:
            return None
        result = dict(row)
        result["planning_content"] = self._json(
            result.pop("planning_content_json"),
        )
        result["chapter_capacity_policy"] = self._json(
            result["chapter_capacity_policy"],
        )
        return result

    async def lock_outline_head(
        self,
        session,
        project_id: str,
        chapter_number: int,
    ):
        row = await session.fetchone(
            f"""{_OUTLINE_HEAD_SELECT}
                 WHERE head.project_id=%s AND head.chapter_num=%s
                 FOR UPDATE""",
            (project_id, chapter_number),
        )
        return self._content_row(row) if row else None

    async def read_outline_head(
        self,
        session,
        project_id: str,
        chapter_number: int,
    ):
        row = await session.fetchone(
            f"""{_OUTLINE_HEAD_SELECT}
                 WHERE head.project_id=%s AND head.chapter_num=%s""",
            (project_id, chapter_number),
        )
        return self._content_row(row) if row else None

    async def read_active_draft(
        self,
        session,
        project_id: str,
        chapter_number: int,
    ):
        row = await session.fetchone(
            """SELECT * FROM chapter_outline_drafts
                WHERE project_id=%s AND chapter_num=%s
                  AND status='active' AND active_slot=1""",
            (project_id, chapter_number),
        )
        return self._content_row(row) if row else None

    async def read_draft(
        self,
        session,
        project_id: str,
        chapter_number: int,
        draft_id: str,
    ):
        row = await session.fetchone(
            """SELECT * FROM chapter_outline_drafts
                WHERE project_id=%s AND chapter_num=%s AND id=%s
                FOR UPDATE""",
            (project_id, chapter_number, draft_id),
        )
        return self._content_row(row) if row else None

    async def insert_draft(self, session, row: dict) -> bool:
        changed = await session.execute(
            """INSERT INTO chapter_outline_drafts
               (id,project_id,chapter_num,active_slot,base_head_revision,
                draft_revision,planning_revision_id,planning_revision,
                planning_hash,canon_revision,projection_revision,
                projection_hash,content_json,content_hash,source_attempt_id,
                status,created_at,updated_at)
               VALUES (%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,
                       'active',%s,%s)""",
            (
                row["id"],
                row["project_id"],
                row["chapter_num"],
                row["base_head_revision"],
                row["draft_revision"],
                row["planning_revision_id"],
                row["planning_revision"],
                row["planning_hash"],
                row["canon_revision"],
                row["projection_revision"],
                row["projection_hash"],
                canonical_json(row["content"]),
                row["content_hash"],
                row["created_at"],
                row["updated_at"],
            ),
        )
        return changed == 1

    async def update_draft_cas(
        self,
        session,
        row: dict,
        expected_revision: int,
        expected_hash: str,
    ) -> bool:
        terminal = row["status"] in {"confirmed", "superseded"}
        active_slot = "NULL" if terminal else "1"
        changed = await session.execute(
            f"""UPDATE chapter_outline_drafts
                   SET draft_revision=%s,content_json=%s,content_hash=%s,
                       status=%s,active_slot={active_slot},updated_at=%s
                 WHERE project_id=%s AND chapter_num=%s AND id=%s
                   AND status='active' AND active_slot=1
                   AND draft_revision=%s AND content_hash=%s""",
            (
                row["draft_revision"],
                canonical_json(row["content"]),
                row["content_hash"],
                row["status"],
                row["updated_at"],
                row["project_id"],
                row["chapter_num"],
                row["id"],
                expected_revision,
                expected_hash,
            ),
        )
        return changed == 1

    async def supersede_draft(
        self,
        session,
        project_id: str,
        chapter_number: int,
        draft_id: str,
    ) -> bool:
        changed = await session.execute(
            """UPDATE chapter_outline_drafts
                  SET status='superseded',active_slot=NULL
                WHERE project_id=%s AND chapter_num=%s AND id=%s
                  AND status='active' AND active_slot=1""",
            (project_id, chapter_number, draft_id),
        )
        return changed == 1

    async def insert_revision(self, session, row: dict) -> bool:
        changed = await session.execute(
            """INSERT INTO chapter_outline_revisions
               (id,project_id,chapter_num,revision,parent_revision,
                planning_revision_id,planning_revision,planning_hash,
                canon_revision,projection_revision,projection_hash,
                content_json,content_hash,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["id"],
                row["project_id"],
                row["chapter_num"],
                row["revision"],
                row["parent_revision"],
                row["planning_revision_id"],
                row["planning_revision"],
                row["planning_hash"],
                row["canon_revision"],
                row["projection_revision"],
                row["projection_hash"],
                canonical_json(row["content"]),
                row["content_hash"],
                row["created_at"],
            ),
        )
        return changed == 1

    async def advance_head_cas(
        self,
        session,
        row: dict,
        expected_revision: int,
    ) -> bool:
        changed = await session.execute(
            """UPDATE project_chapter_outline_heads
                  SET revision=%s,outline_revision_id=%s,content_hash=%s,
                      updated_at=%s
                WHERE project_id=%s AND chapter_num=%s AND revision=%s""",
            (
                row["revision"],
                row["outline_revision_id"],
                row["content_hash"],
                row["updated_at"],
                row["project_id"],
                row["chapter_num"],
                expected_revision,
            ),
        )
        if changed == 1:
            return True
        if expected_revision != 0:
            return False
        changed = await session.execute(
            """INSERT INTO project_chapter_outline_heads
               (project_id,chapter_num,revision,outline_revision_id,
                content_hash,updated_at)
               SELECT %s,%s,%s,%s,%s,%s
                WHERE NOT EXISTS (
                  SELECT 1 FROM project_chapter_outline_heads
                   WHERE project_id=%s AND chapter_num=%s
                )""",
            (
                row["project_id"],
                row["chapter_num"],
                row["revision"],
                row["outline_revision_id"],
                row["content_hash"],
                row["updated_at"],
                row["project_id"],
                row["chapter_num"],
            ),
        )
        return changed == 1

    async def find_confirmation(
        self,
        session,
        project_id: str,
        chapter_number: int,
        idempotency_key: str,
    ):
        row = await session.fetchone(
            """SELECT * FROM chapter_outline_confirmation_requests
                WHERE project_id=%s AND chapter_num=%s
                  AND idempotency_key=%s
                FOR UPDATE""",
            (project_id, chapter_number, idempotency_key),
        )
        return dict(row) if row else None

    async def insert_confirmation_pending(self, session, row: dict) -> bool:
        changed = await session.execute(
            """INSERT INTO chapter_outline_confirmation_requests
               (id,project_id,chapter_num,chapter_outline_draft_id,
                draft_revision,draft_hash,expected_head_revision,
                planning_revision_id,planning_revision,planning_hash,
                canon_revision,projection_revision,projection_hash,
                idempotency_key,request_fingerprint,status,
                outline_revision_id,result_revision,result_hash,
                public_error_code,created_at,completed_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       'pending',NULL,NULL,NULL,NULL,%s,NULL)""",
            (
                row["id"],
                row["project_id"],
                row["chapter_num"],
                row["chapter_outline_draft_id"],
                row["draft_revision"],
                row["draft_hash"],
                row["expected_head_revision"],
                row["planning_revision_id"],
                row["planning_revision"],
                row["planning_hash"],
                row["canon_revision"],
                row["projection_revision"],
                row["projection_hash"],
                row["idempotency_key"],
                row["request_fingerprint"],
                row["created_at"],
            ),
        )
        return changed == 1

    async def finish_confirmation(self, session, row: dict) -> bool:
        changed = await session.execute(
            """UPDATE chapter_outline_confirmation_requests
                  SET status=%s,outline_revision_id=%s,result_revision=%s,
                      result_hash=%s,public_error_code=%s,completed_at=%s
                WHERE project_id=%s AND chapter_num=%s
                  AND idempotency_key=%s AND status='pending'
                  AND request_fingerprint=%s""",
            (
                row["status"],
                row.get("outline_revision_id"),
                row.get("result_revision"),
                row.get("result_hash"),
                row.get("public_error_code"),
                row["completed_at"],
                row["project_id"],
                row["chapter_num"],
                row["idempotency_key"],
                row["request_fingerprint"],
            ),
        )
        return changed == 1

    async def list_revisions(
        self,
        session,
        project_id: str,
        chapter_number: int,
    ):
        rows = await session.fetchall(
            """SELECT * FROM chapter_outline_revisions
                WHERE project_id=%s AND chapter_num=%s
                ORDER BY revision DESC""",
            (project_id, chapter_number),
        )
        return tuple(self._content_row(row) for row in rows)

    async def lock_attempt_by_key(
        self,
        session,
        project_id: str,
        idempotency_key: str,
    ):
        row = await session.fetchone(
            """SELECT * FROM chapter_outline_generation_attempts
                WHERE project_id=%s AND idempotency_key=%s
                FOR UPDATE""",
            (project_id, idempotency_key),
        )
        return self._attempt(row) if row else None

    async def read_attempt_by_key(
        self,
        session,
        project_id: str,
        idempotency_key: str,
    ):
        row = await session.fetchone(
            """SELECT * FROM chapter_outline_generation_attempts
                WHERE project_id=%s AND idempotency_key=%s""",
            (project_id, idempotency_key),
        )
        return self._attempt(row) if row else None

    async def lock_attempt(
        self,
        session,
        project_id: str,
        operation_id: str,
    ):
        row = await session.fetchone(
            """SELECT * FROM chapter_outline_generation_attempts
                WHERE project_id=%s AND operation_id=%s
                FOR UPDATE""",
            (project_id, operation_id),
        )
        return self._attempt(row) if row else None

    async def read_attempt(
        self,
        session,
        project_id: str,
        operation_id: str,
    ):
        row = await session.fetchone(
            """SELECT * FROM chapter_outline_generation_attempts
                WHERE project_id=%s AND operation_id=%s""",
            (project_id, operation_id),
        )
        return self._attempt(row) if row else None

    async def lock_active_attempt(self, session, draft_id: str):
        row = await session.fetchone(
            """SELECT * FROM chapter_outline_generation_attempts
                WHERE outline_draft_id=%s
                  AND status='pending' AND active_slot=1
                FOR UPDATE""",
            (draft_id,),
        )
        return self._attempt(row) if row else None

    async def next_fencing_token(self, session, draft_id: str) -> int:
        latest = await session.fetchone(
            """SELECT fencing_token
                 FROM chapter_outline_generation_attempts
                WHERE outline_draft_id=%s
                ORDER BY fencing_token DESC
                LIMIT 1 FOR UPDATE""",
            (draft_id,),
        )
        return 1 if latest is None else int(latest["fencing_token"]) + 1

    async def insert_attempt(self, session, row: dict) -> bool:
        changed = await session.execute(
            """INSERT INTO chapter_outline_generation_attempts
               (id,project_id,outline_draft_id,operation_id,active_slot,
                idempotency_key,request_fingerprint,binding_revision_id,
                binding_revision,binding_hash,provider_id,model_name_snapshot,
                fencing_token,lease_expires_at,input_manifest_json,
                input_manifest_hash,status,created_at,updated_at)
               VALUES (%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       'pending',%s,%s)""",
            (
                row["id"],
                row["project_id"],
                row["outline_draft_id"],
                row["operation_id"],
                row["idempotency_key"],
                row["request_fingerprint"],
                row["binding_revision_id"],
                row["binding_revision"],
                row["binding_hash"],
                row["provider_id"],
                row["model_name_snapshot"],
                row["fencing_token"],
                row["lease_expires_at"],
                canonical_json(row["input_manifest"]),
                row["input_manifest_hash"],
                row["created_at"],
                row["updated_at"],
            ),
        )
        return changed == 1

    async def supersede_attempt(
        self,
        session,
        project_id: str,
        operation_id: str,
        fencing_token: int,
    ) -> bool:
        changed = await session.execute(
            """UPDATE chapter_outline_generation_attempts
                  SET status='superseded',active_slot=NULL
                WHERE project_id=%s AND operation_id=%s
                  AND status='pending' AND active_slot=1
                  AND fencing_token=%s""",
            (project_id, operation_id, fencing_token),
        )
        return changed == 1

    async def fail_attempt(
        self,
        session,
        project_id: str,
        operation_id: str,
        fencing_token: int,
        failure_code: str,
    ) -> bool:
        changed = await session.execute(
            """UPDATE chapter_outline_generation_attempts
                  SET status='failed',active_slot=NULL,failure_code=%s
                WHERE project_id=%s AND operation_id=%s
                  AND status='pending' AND active_slot=1
                  AND fencing_token=%s""",
            (failure_code, project_id, operation_id, fencing_token),
        )
        return changed == 1

    async def load_result_into_draft(
        self,
        session,
        draft_id: str,
        expected_revision: int,
        expected_hash: str,
        operation_id: str,
        fencing_token: int,
        content: dict,
        content_hash: str,
        loaded_at: int,
    ) -> bool:
        loaded_revision = expected_revision + 1
        content_json = canonical_json(content)
        changed = await session.execute(
            """UPDATE chapter_outline_drafts draft
                 JOIN chapter_outline_generation_attempts attempt
                   ON attempt.project_id=draft.project_id
                  AND attempt.outline_draft_id=draft.id
                  SET draft.draft_revision=%s,
                      draft.content_json=%s,draft.content_hash=%s,
                      draft.source_attempt_id=attempt.id,
                      draft.updated_at=%s,
                      attempt.status='succeeded',
                      attempt.active_slot=NULL,
                      attempt.result_content_json=%s,
                      attempt.result_content_hash=%s,
                      attempt.loaded_outline_draft_revision=%s,
                      attempt.loaded_at=%s,
                      attempt.updated_at=%s
                WHERE draft.id=%s
                  AND draft.status='active' AND draft.active_slot=1
                  AND draft.draft_revision=%s AND draft.content_hash=%s
                  AND attempt.operation_id=%s
                  AND attempt.status='pending'
                  AND attempt.active_slot=1
                  AND attempt.fencing_token=%s
                  AND attempt.loaded_outline_draft_revision IS NULL
                  AND attempt.loaded_at IS NULL""",
            (
                loaded_revision,
                content_json,
                content_hash,
                loaded_at,
                content_json,
                content_hash,
                loaded_revision,
                loaded_at,
                loaded_at,
                draft_id,
                expected_revision,
                expected_hash,
                operation_id,
                fencing_token,
            ),
        )
        return changed == 2

    @staticmethod
    def _json(value):
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("utf-8")
        if isinstance(value, str):
            loaded = json.loads(value)
            return loaded if isinstance(loaded, dict) else {}
        return {}

    def _content_row(self, row):
        result = dict(row)
        raw = result.pop("content_json", None)
        result["content"] = self._json(raw)
        return result

    def _attempt(self, row):
        result = dict(row)
        input_manifest = result.pop("input_manifest_json", None)
        result_content = result.pop("result_content_json", None)
        result["input_manifest"] = self._json(input_manifest)
        result["result_content"] = (
            None if result_content is None else self._json(result_content)
        )
        return result
