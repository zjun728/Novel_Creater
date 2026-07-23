"""Session-bound persistence for creation-Bible drafts and revisions."""

from __future__ import annotations

from backend.repositories.project_lifecycle import (
    lock_active_project,
    read_project,
)


class BibleRepository:
    async def read_project(self, session, project_id: str):
        return await read_project(session, project_id)

    async def lock_project(self, session, project_id: str):
        return await lock_active_project(session, project_id)

    async def lock_selected_seed(self, session, project_id: str):
        return await session.fetchone(
            """SELECT selection_revision,seed_id,seed_revision_id,seed_hash
                 FROM project_selected_seeds
                WHERE project_id=%s FOR UPDATE""",
            (project_id,),
        )

    async def lock_contract_head(self, session, project_id: str):
        return await session.fetchone(
            """SELECT revision,creation_contract_id,creation_hash,
                      style_contract_id,style_hash
                 FROM project_contract_heads
                WHERE project_id=%s FOR UPDATE""",
            (project_id,),
        )

    async def read_active_draft(self, session, project_id: str):
        return await session.fetchone(
            """SELECT * FROM project_bible_drafts
                WHERE project_id=%s AND active_slot=1""",
            (project_id,),
        )

    async def lock_active_draft(self, session, project_id: str):
        return await session.fetchone(
            """SELECT * FROM project_bible_drafts
                WHERE project_id=%s AND active_slot=1 FOR UPDATE""",
            (project_id,),
        )

    async def read_draft(self, session, project_id: str, draft_id: str):
        return await session.fetchone(
            """SELECT * FROM project_bible_drafts
                WHERE project_id=%s AND id=%s""",
            (project_id, draft_id),
        )

    async def insert_draft(self, session, row: dict) -> bool:
        changed = await session.execute(
            """INSERT INTO project_bible_drafts
               (id,project_id,active_slot,base_head_revision,
                selection_revision,seed_id,seed_revision_id,seed_hash,
                contract_revision,creation_contract_id,creation_hash,
                style_contract_id,style_hash,binding_revision_id,binding_hash,
                policy_version,draft_json,content_hash,draft_version,
                created_at,updated_at)
               VALUES (%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       %s,%s,%s,%s,%s,%s)""",
            tuple(
                row[key]
                for key in (
                    "id",
                    "project_id",
                    "base_head_revision",
                    "selection_revision",
                    "seed_id",
                    "seed_revision_id",
                    "seed_hash",
                    "contract_revision",
                    "creation_contract_id",
                    "creation_hash",
                    "style_contract_id",
                    "style_hash",
                    "binding_revision_id",
                    "binding_hash",
                    "policy_version",
                    "draft_json",
                    "content_hash",
                    "draft_version",
                    "created_at",
                    "updated_at",
                )
            ),
        )
        return changed == 1

    async def deactivate_active_draft(
        self,
        session,
        project_id: str,
        draft_id: str,
        expected_version: int,
        content_hash: str,
    ) -> bool:
        changed = await session.execute(
            """UPDATE project_bible_drafts
                  SET active_slot=NULL
                WHERE project_id=%s AND id=%s AND active_slot=1
                  AND draft_version=%s AND content_hash=%s""",
            (project_id, draft_id, expected_version, content_hash),
        )
        return changed == 1

    async def cas_update_draft(
        self,
        session,
        row: dict,
        expected_version: int,
    ) -> bool:
        changed = await session.execute(
            """UPDATE project_bible_drafts
                  SET draft_json=%s,content_hash=%s,draft_version=%s,
                      updated_at=%s
                WHERE project_id=%s AND id=%s AND active_slot=1
                  AND draft_version=%s
                  AND base_head_revision=%s
                  AND selection_revision=%s
                  AND seed_id=%s AND seed_revision_id=%s AND seed_hash=%s
                  AND contract_revision=%s
                  AND creation_contract_id=%s AND creation_hash=%s
                  AND style_contract_id=%s AND style_hash=%s""",
            (
                row["draft_json"],
                row["content_hash"],
                row["draft_version"],
                row["updated_at"],
                row["project_id"],
                row["id"],
                expected_version,
                row["base_head_revision"],
                row["selection_revision"],
                row["seed_id"],
                row["seed_revision_id"],
                row["seed_hash"],
                row["contract_revision"],
                row["creation_contract_id"],
                row["creation_hash"],
                row["style_contract_id"],
                row["style_hash"],
            ),
        )
        return changed == 1

    async def read_bible_head(self, session, project_id: str):
        return await session.fetchone(
            "SELECT * FROM project_bible_heads WHERE project_id=%s",
            (project_id,),
        )

    async def lock_bible_head(self, session, project_id: str):
        return await session.fetchone(
            """SELECT * FROM project_bible_heads
                WHERE project_id=%s FOR UPDATE""",
            (project_id,),
        )

    async def read_confirmation_request(
        self,
        session,
        project_id: str,
        idempotency_key: str,
    ):
        return await session.fetchone(
            """SELECT * FROM bible_confirmation_requests
                WHERE project_id=%s AND idempotency_key=%s FOR UPDATE""",
            (project_id, idempotency_key),
        )

    async def insert_confirmation_request(self, session, row: dict) -> bool:
        changed = await session.execute(
            """INSERT INTO bible_confirmation_requests
               (id,project_id,selection_revision,contract_revision,
                creation_contract_id,creation_hash,style_contract_id,
                style_hash,draft_id,draft_version,draft_hash,idempotency_key,
                request_hash,status,bible_revision_id,result_revision,
                result_hash,public_error_code,created_at,completed_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'reserved',
                       NULL,NULL,NULL,NULL,%s,NULL)""",
            tuple(
                row[key]
                for key in (
                    "id",
                    "project_id",
                    "selection_revision",
                    "contract_revision",
                    "creation_contract_id",
                    "creation_hash",
                    "style_contract_id",
                    "style_hash",
                    "draft_id",
                    "draft_version",
                    "draft_hash",
                    "idempotency_key",
                    "request_hash",
                    "created_at",
                )
            ),
        )
        return changed == 1

    async def insert_failed_confirmation_request(
        self,
        session,
        row: dict,
    ) -> bool:
        changed = await session.execute(
            """INSERT INTO bible_confirmation_requests
               (id,project_id,selection_revision,contract_revision,
                creation_contract_id,creation_hash,style_contract_id,
                style_hash,draft_id,draft_version,draft_hash,idempotency_key,
                request_hash,status,bible_revision_id,result_revision,
                result_hash,public_error_code,created_at,completed_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'failed',
                       NULL,NULL,NULL,'BibleConfirmationFailed',%s,%s)""",
            tuple(
                row[key]
                for key in (
                    "id",
                    "project_id",
                    "selection_revision",
                    "contract_revision",
                    "creation_contract_id",
                    "creation_hash",
                    "style_contract_id",
                    "style_hash",
                    "draft_id",
                    "draft_version",
                    "draft_hash",
                    "idempotency_key",
                    "request_hash",
                    "created_at",
                    "completed_at",
                )
            ),
        )
        return changed == 1

    async def insert_revision(self, session, row: dict) -> bool:
        changed = await session.execute(
            """INSERT INTO creation_bible_revisions
               (id,project_id,revision,selection_revision,seed_id,
                seed_revision_id,seed_hash,contract_revision,
                creation_contract_id,creation_hash,style_contract_id,
                style_hash,binding_revision_id,binding_hash,policy_version,
                content_json,content_hash,confirmed_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       %s,%s,%s,%s)""",
            tuple(
                row[key]
                for key in (
                    "id",
                    "project_id",
                    "revision",
                    "selection_revision",
                    "seed_id",
                    "seed_revision_id",
                    "seed_hash",
                    "contract_revision",
                    "creation_contract_id",
                    "creation_hash",
                    "style_contract_id",
                    "style_hash",
                    "binding_revision_id",
                    "binding_hash",
                    "policy_version",
                    "content_json",
                    "content_hash",
                    "confirmed_at",
                )
            ),
        )
        return changed == 1

    async def cas_bible_head(self, session, row: dict) -> bool:
        changed = await session.execute(
            """UPDATE project_bible_heads
                  SET revision=%s,bible_revision_id=%s,content_hash=%s,
                      updated_at=%s
                WHERE project_id=%s AND revision=%s""",
            (
                row["revision"],
                row["bible_revision_id"],
                row["content_hash"],
                row["updated_at"],
                row["project_id"],
                row["base_revision"],
            ),
        )
        return changed == 1

    async def succeed_confirmation_request(
        self,
        session,
        row: dict,
    ) -> bool:
        changed = await session.execute(
            """UPDATE bible_confirmation_requests
                  SET status='succeeded',bible_revision_id=%s,
                      result_revision=%s,result_hash=%s,
                      public_error_code=NULL,completed_at=%s
                WHERE project_id=%s AND idempotency_key=%s
                  AND request_hash=%s AND status='reserved'""",
            (
                row["bible_revision_id"],
                row["result_revision"],
                row["result_hash"],
                row["completed_at"],
                row["project_id"],
                row["idempotency_key"],
                row["request_hash"],
            ),
        )
        return changed == 1

    async def read_revision(
        self,
        session,
        project_id: str,
        revision: int,
    ):
        return await session.fetchone(
            """SELECT * FROM creation_bible_revisions
                WHERE project_id=%s AND revision=%s""",
            (project_id, revision),
        )

    async def list_revisions(
        self,
        session,
        project_id: str,
        *,
        before_revision: int | None,
        limit: int,
    ):
        cursor_clause = ""
        args: list[object] = [project_id]
        if before_revision is not None:
            cursor_clause = " AND revision<%s"
            args.append(before_revision)
        args.append(limit + 1)
        return await session.fetchall(
            f"""SELECT revision FROM creation_bible_revisions
                 WHERE project_id=%s{cursor_clause}
                 ORDER BY revision DESC LIMIT %s""",
            tuple(args),
        )


__all__ = ("BibleRepository",)
