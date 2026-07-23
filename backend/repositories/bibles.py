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
        *,
        update_binding: bool = False,
    ) -> bool:
        binding_set = (
            "binding_revision_id=%s,binding_hash=%s,"
            if update_binding
            else ""
        )
        binding_values = (
            (row["binding_revision_id"], row["binding_hash"])
            if update_binding
            else ()
        )
        changed = await session.execute(
            f"""UPDATE project_bible_drafts
                  SET {binding_set}draft_json=%s,content_hash=%s,draft_version=%s,
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
                *binding_values,
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

    async def lock_generation_attempt_by_key(
        self,
        session,
        project_id: str,
        idempotency_key: str,
    ):
        return await session.fetchone(
            """SELECT * FROM bible_generation_attempts
                WHERE project_id=%s AND idempotency_key=%s FOR UPDATE""",
            (project_id, idempotency_key),
        )

    async def lock_generation_attempt(
        self,
        session,
        project_id: str,
        attempt_id: str,
    ):
        return await session.fetchone(
            """SELECT * FROM bible_generation_attempts
                WHERE project_id=%s AND id=%s FOR UPDATE""",
            (project_id, attempt_id),
        )

    async def read_generation_attempt(
        self,
        session,
        project_id: str,
        attempt_id: str,
    ):
        return await session.fetchone(
            """SELECT * FROM bible_generation_attempts
                WHERE project_id=%s AND id=%s""",
            (project_id, attempt_id),
        )

    async def insert_generation_attempt(self, session, row: dict) -> bool:
        changed = await session.execute(
            """INSERT INTO bible_generation_attempts
               (id,project_id,selection_revision,seed_id,seed_revision_id,
                seed_hash,contract_revision,creation_contract_id,creation_hash,
                style_contract_id,style_hash,binding_revision_id,binding_hash,
                provider_id,model_name_snapshot,policy_version,idempotency_key,
                request_hash,input_manifest_json,input_manifest_hash,status,
                owner_token,lease_expires_at,attempt_version,result_json,
                result_hash,public_error_code,created_at,completed_at)
               VALUES
               (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,NULL,NULL,NULL,%s,NULL)""",
            tuple(
                row[key]
                for key in (
                    "id",
                    "project_id",
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
                    "provider_id",
                    "model_name_snapshot",
                    "policy_version",
                    "idempotency_key",
                    "request_hash",
                    "input_manifest_json",
                    "input_manifest_hash",
                    "status",
                    "owner_token",
                    "lease_expires_at",
                    "attempt_version",
                    "created_at",
                )
            ),
        )
        return changed == 1

    async def finish_generation_attempt(
        self,
        session,
        *,
        project_id: str,
        attempt_id: str,
        owner_token: str,
        expected_attempt_version: int,
        status: str,
        public_error_code: str,
        completed_at: int,
    ) -> bool:
        changed = await session.execute(
            """UPDATE bible_generation_attempts
                  SET status=%s,owner_token=NULL,lease_expires_at=NULL,
                      attempt_version=attempt_version+1,result_json=NULL,
                      result_hash=NULL,public_error_code=%s,completed_at=%s
                WHERE project_id=%s AND id=%s AND owner_token=%s
                  AND attempt_version=%s
                  AND status IN ('reserved','running')""",
            (
                status,
                public_error_code,
                completed_at,
                project_id,
                attempt_id,
                owner_token,
                expected_attempt_version,
            ),
        )
        return changed == 1

    async def succeed_generation_attempt(
        self,
        session,
        *,
        project_id: str,
        attempt_id: str,
        owner_token: str,
        expected_attempt_version: int,
        result_json: str,
        result_hash: str,
        completed_at: int,
    ) -> bool:
        changed = await session.execute(
            """UPDATE bible_generation_attempts
                  SET status='succeeded',owner_token=NULL,
                      lease_expires_at=NULL,
                      attempt_version=attempt_version+1,result_json=%s,
                      result_hash=%s,public_error_code=NULL,completed_at=%s
                WHERE project_id=%s AND id=%s AND owner_token=%s
                  AND attempt_version=%s AND status='running'""",
            (
                result_json,
                result_hash,
                completed_at,
                project_id,
                attempt_id,
                owner_token,
                expected_attempt_version,
            ),
        )
        return changed == 1

    async def lock_planning_binding(self, session, project_id: str):
        return await session.fetchone(
            """SELECT head.binding_revision_id,
                      head.content_hash AS binding_hash,
                      item.resolution_status,item.provider_id,
                      item.model_name_snapshot,
                      provider.id,provider.provider_type,provider.model_name,
                      provider.base_url,provider.api_key,provider.enabled,
                      provider.lifecycle_status,provider.revision,
                      provider.temperature,provider.max_context_tokens,
                      provider.max_output_tokens
                 FROM project_model_binding_heads head
                 JOIN project_model_binding_items item
                   ON item.binding_revision_id=head.binding_revision_id
                  AND item.task_key='planning'
                 LEFT JOIN provider_profiles provider
                   ON provider.id=item.provider_id
                WHERE head.project_id=%s FOR UPDATE""",
            (project_id,),
        )

    async def read_seed_revision(
        self,
        session,
        project_id: str,
        revision_id: str,
        *,
        lock: bool = False,
    ):
        suffix = " FOR UPDATE" if lock else ""
        return await session.fetchone(
            f"""SELECT seed_id,id AS seed_revision_id,
                       content_hash AS seed_hash,payload_json
                  FROM creative_seed_revisions
                 WHERE project_id=%s AND id=%s{suffix}""",
            (project_id, revision_id),
        )

    async def read_experience_revision(
        self,
        session,
        asset_id: str,
        *,
        lock: bool = False,
    ):
        suffix = " FOR UPDATE" if lock else ""
        return await session.fetchone(
            f"""SELECT id,revision,content_hash,payload_json
                  FROM experience_cards WHERE id=%s{suffix}""",
            (asset_id,),
        )

    async def read_corpus_fragments(
        self,
        session,
        source_id: str,
        revision_id: str,
        fragment_ids: tuple[str, ...],
        *,
        lock: bool = False,
    ):
        if not fragment_ids:
            return ()
        suffix = " FOR UPDATE" if lock else ""
        return tuple(
            await session.fetchall(
                f"""SELECT source.id AS source_id,
                           revision.id AS source_revision_id,
                           revision.revision AS source_revision,
                           revision.content_hash AS source_hash,
                           chapter.id AS chapter_id,
                           fragment.id AS fragment_id,
                           fragment.content_hash AS fragment_hash,
                           fragment.chapter_char_start AS fragment_char_start,
                           fragment.chapter_char_end AS fragment_char_end,
                           fragment.normalized_text
                      FROM corpus_sources source
                      JOIN corpus_source_revisions revision
                        ON revision.source_id=source.id AND revision.id=%s
                      JOIN corpus_chapters chapter
                        ON chapter.corpus_source_id=source.id
                       AND chapter.source_revision_id=revision.id
                      JOIN corpus_fragments fragment
                        ON fragment.corpus_source_id=source.id
                       AND fragment.corpus_chapter_id=chapter.id
                     WHERE source.id=%s
                       AND fragment.id IN ({','.join(['%s'] * len(fragment_ids))})
                     ORDER BY fragment.id{suffix}""",
                (revision_id, source_id, *fragment_ids),
            )
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
