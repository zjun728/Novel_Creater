"""Session-bound persistence for the single revisioned Planning aggregate."""

from __future__ import annotations

from backend.repositories.project_lifecycle import (
    lock_active_project,
    read_project,
)


class PlanningRepository:
    async def lock_active_project(self, session, project_id: str):
        return await lock_active_project(session, project_id)

    async def read_project_any(self, session, project_id: str):
        return await read_project(session, project_id)

    async def read_current_basis(self, session, project_id: str):
        return await session.fetchone(
            """SELECT selected.selection_revision,selected.seed_id,
                      selected.seed_revision_id,selected.seed_hash,
                      contract_head.revision AS contract_revision,
                      contract_head.creation_contract_id,
                      contract_head.creation_hash,
                      contract_head.style_contract_id,contract_head.style_hash,
                      creation.chapter_capacity_policy,
                      bible_head.revision AS bible_revision,
                      bible_head.bible_revision_id,
                      bible_head.content_hash AS bible_hash
                 FROM project_selected_seeds selected
                 JOIN project_contract_heads contract_head
                   ON contract_head.project_id=selected.project_id
                  AND contract_head.revision>0
                 JOIN creation_contracts creation
                   ON creation.project_id=contract_head.project_id
                  AND creation.id=contract_head.creation_contract_id
                  AND creation.revision=contract_head.revision
                  AND creation.content_hash=contract_head.creation_hash
                  AND creation.selection_revision=selected.selection_revision
                  AND creation.seed_id=selected.seed_id
                  AND creation.seed_revision_id=selected.seed_revision_id
                  AND creation.seed_hash=selected.seed_hash
                 JOIN style_contracts style
                   ON style.project_id=contract_head.project_id
                  AND style.id=contract_head.style_contract_id
                  AND style.creation_contract_id=creation.id
                  AND style.revision=contract_head.revision
                  AND style.content_hash=contract_head.style_hash
                 JOIN project_bible_heads bible_head
                   ON bible_head.project_id=selected.project_id
                  AND bible_head.revision>0
                 JOIN creation_bible_revisions bible
                   ON bible.project_id=bible_head.project_id
                  AND bible.id=bible_head.bible_revision_id
                  AND bible.revision=bible_head.revision
                  AND bible.content_hash=bible_head.content_hash
                  AND bible.selection_revision=selected.selection_revision
                  AND bible.seed_id=selected.seed_id
                  AND bible.seed_revision_id=selected.seed_revision_id
                  AND bible.seed_hash=selected.seed_hash
                  AND bible.contract_revision=contract_head.revision
                  AND bible.creation_contract_id=contract_head.creation_contract_id
                  AND bible.creation_hash=contract_head.creation_hash
                  AND bible.style_contract_id=contract_head.style_contract_id
                  AND bible.style_hash=contract_head.style_hash
                WHERE selected.project_id=%s
                FOR UPDATE""",
            (project_id,),
        )

    async def lock_planning_head(self, session, project_id: str):
        return await session.fetchone(
            """SELECT head.project_id,head.revision,head.planning_revision_id,
                      head.content_hash,head.updated_at,
                      revision.content_json
                 FROM project_planning_heads head
                 LEFT JOIN planning_revisions revision
                   ON revision.project_id=head.project_id
                  AND revision.id=head.planning_revision_id
                  AND revision.revision=head.revision
                  AND revision.content_hash=head.content_hash
                WHERE head.project_id=%s
                FOR UPDATE""",
            (project_id,),
        )

    async def read_active_draft(self, session, project_id: str):
        return await session.fetchone(
            """SELECT * FROM planning_drafts
                WHERE project_id=%s AND active_slot=1 AND status='active'""",
            (project_id,),
        )

    async def read_draft(self, session, project_id: str, draft_id: str):
        return await session.fetchone(
            """SELECT * FROM planning_drafts
                WHERE project_id=%s AND id=%s
                FOR UPDATE""",
            (project_id, draft_id),
        )

    async def insert_draft(self, session, row: dict) -> bool:
        changed = await session.execute(
            """INSERT INTO planning_drafts
               (id,project_id,active_slot,base_head_revision,draft_revision,
                selection_revision,seed_id,seed_revision_id,seed_hash,
                contract_revision,creation_contract_id,creation_hash,
                style_contract_id,style_hash,bible_revision,bible_revision_id,
                bible_hash,content_json,content_hash,source_attempt_id,status,
                created_at,updated_at)
               VALUES (%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       %s,%s,%s,NULL,'active',%s,%s)""",
            tuple(
                row[key]
                for key in (
                    "id",
                    "project_id",
                    "base_head_revision",
                    "draft_revision",
                    "selection_revision",
                    "seed_id",
                    "seed_revision_id",
                    "seed_hash",
                    "contract_revision",
                    "creation_contract_id",
                    "creation_hash",
                    "style_contract_id",
                    "style_hash",
                    "bible_revision",
                    "bible_revision_id",
                    "bible_hash",
                    "content_json",
                    "content_hash",
                    "created_at",
                    "updated_at",
                )
            ),
        )
        return changed == 1

    async def update_draft_cas(
        self,
        session,
        row: dict,
        *,
        expected_revision: int,
        expected_hash: str,
    ) -> bool:
        terminal = row["status"] in {"confirmed", "superseded"}
        active_slot = "NULL" if terminal else "1"
        changed = await session.execute(
            f"""UPDATE planning_drafts
                   SET draft_revision=%s,content_json=%s,content_hash=%s,
                       status=%s,active_slot={active_slot},updated_at=%s
                 WHERE project_id=%s AND id=%s
                   AND status='active' AND active_slot=1
                   AND draft_revision=%s AND content_hash=%s""",
            (
                row["draft_revision"],
                row["content_json"],
                row["content_hash"],
                row["status"],
                row["updated_at"],
                row["project_id"],
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
        draft_id: str,
        updated_at: int,
    ) -> bool:
        changed = await session.execute(
            """UPDATE planning_drafts
                  SET status='superseded',active_slot=NULL,updated_at=%s
                WHERE project_id=%s AND id=%s
                  AND status='active' AND active_slot=1""",
            (updated_at, project_id, draft_id),
        )
        return changed == 1

    async def find_confirmation(
        self,
        session,
        project_id: str,
        idempotency_key: str,
    ):
        return await session.fetchone(
            """SELECT * FROM planning_confirmation_requests
                WHERE project_id=%s AND idempotency_key=%s
                FOR UPDATE""",
            (project_id, idempotency_key),
        )

    async def insert_confirmation_pending(self, session, row: dict) -> bool:
        changed = await session.execute(
            """INSERT INTO planning_confirmation_requests
               (id,project_id,planning_draft_id,draft_revision,draft_hash,
                expected_head_revision,idempotency_key,request_fingerprint,
                status,planning_revision_id,result_revision,result_hash,
                public_error_code,created_at,completed_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending',
                       NULL,NULL,NULL,NULL,%s,NULL)""",
            tuple(
                row[key]
                for key in (
                    "id",
                    "project_id",
                    "planning_draft_id",
                    "draft_revision",
                    "draft_hash",
                    "expected_head_revision",
                    "idempotency_key",
                    "request_fingerprint",
                    "created_at",
                )
            ),
        )
        return changed == 1

    async def insert_revision(self, session, row: dict) -> bool:
        changed = await session.execute(
            """INSERT INTO planning_revisions
               (id,project_id,revision,parent_revision,selection_revision,
                seed_id,seed_revision_id,seed_hash,contract_revision,
                creation_contract_id,creation_hash,style_contract_id,
                style_hash,bible_revision,bible_revision_id,bible_hash,
                content_json,content_hash,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       %s,%s,%s)""",
            tuple(
                row[key]
                for key in (
                    "id",
                    "project_id",
                    "revision",
                    "parent_revision",
                    "selection_revision",
                    "seed_id",
                    "seed_revision_id",
                    "seed_hash",
                    "contract_revision",
                    "creation_contract_id",
                    "creation_hash",
                    "style_contract_id",
                    "style_hash",
                    "bible_revision",
                    "bible_revision_id",
                    "bible_hash",
                    "content_json",
                    "content_hash",
                    "created_at",
                )
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
            """UPDATE project_planning_heads
                  SET revision=%s,planning_revision_id=%s,content_hash=%s,
                      updated_at=%s
                WHERE project_id=%s AND revision=%s""",
            (
                row["revision"],
                row["planning_revision_id"],
                row["content_hash"],
                row["updated_at"],
                row["project_id"],
                expected_revision,
            ),
        )
        return changed == 1

    async def finish_confirmation(self, session, row: dict) -> bool:
        changed = await session.execute(
            """UPDATE planning_confirmation_requests
                  SET status='succeeded',planning_revision_id=%s,
                      result_revision=%s,result_hash=%s,completed_at=%s
                WHERE project_id=%s AND idempotency_key=%s
                  AND status='pending'
                  AND request_fingerprint=%s""",
            (
                row["planning_revision_id"],
                row["result_revision"],
                row["result_hash"],
                row["completed_at"],
                row["project_id"],
                row["idempotency_key"],
                row["request_fingerprint"],
            ),
        )
        return changed == 1

    async def list_revisions(self, session, project_id: str):
        return tuple(
            await session.fetchall(
                """SELECT * FROM planning_revisions
                    WHERE project_id=%s ORDER BY revision DESC""",
                (project_id,),
            )
        )

    async def read_projection_head(self, session, project_id: str):
        return await session.fetchone(
            """SELECT * FROM projection_heads
                WHERE project_id=%s""",
            (project_id,),
        )

    async def lock_projection_head(self, session, project_id: str):
        return await session.fetchone(
            """SELECT * FROM projection_heads
                WHERE project_id=%s FOR UPDATE""",
            (project_id,),
        )
