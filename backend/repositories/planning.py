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
                      seed_revision.payload_json AS seed_content_json,
                      contract_head.revision AS contract_revision,
                      contract_head.creation_contract_id,
                      contract_head.creation_hash,
                      contract_head.style_contract_id,contract_head.style_hash,
                      creation.chapter_capacity_policy,
                      creation.content_json AS creation_content_json,
                      bible_head.revision AS bible_revision,
                      bible_head.bible_revision_id,
                      bible_head.content_hash AS bible_hash,
                      bible.content_json AS bible_content_json
                 FROM project_selected_seeds selected
                 JOIN creative_seed_revisions seed_revision
                   ON seed_revision.project_id=selected.project_id
                  AND seed_revision.seed_id=selected.seed_id
                  AND seed_revision.id=selected.seed_revision_id
                  AND seed_revision.content_hash=selected.seed_hash
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
                      revision.content_json,
                      revision.selection_revision,revision.seed_id,
                      revision.seed_revision_id,revision.seed_hash,
                      revision.contract_revision,
                      revision.creation_contract_id,revision.creation_hash,
                      revision.style_contract_id,revision.style_hash,
                      revision.bible_revision,revision.bible_revision_id,
                      revision.bible_hash
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
        expected_head,
    ) -> bool:
        changed = await session.execute(
            """UPDATE project_planning_heads
                  SET revision=%s,planning_revision_id=%s,content_hash=%s,
                      updated_at=%s
                WHERE project_id=%s AND revision=%s
                  AND planning_revision_id <=> %s
                  AND content_hash <=> %s""",
            (
                row["revision"],
                row["planning_revision_id"],
                row["content_hash"],
                row["updated_at"],
                row["project_id"],
                expected_head["revision"],
                expected_head.get("planning_revision_id"),
                expected_head.get("content_hash"),
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

    async def read_actual_plot_progress(
        self,
        session,
        project_id: str,
        revision_number: int,
    ):
        return await session.fetchall(
            """SELECT revision_number,subject_key,entity_id,field_path,payload_json,content_hash
                 FROM plot_thread_projections
                WHERE project_id=%s AND revision_number=%s
                ORDER BY subject_key,field_path,id""",
            (project_id, revision_number),
        )

    async def lock_projection_head(self, session, project_id: str):
        return await session.fetchone(
            """SELECT * FROM projection_heads
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
            """SELECT * FROM planning_generation_attempts
                WHERE project_id=%s AND idempotency_key=%s
                FOR UPDATE""",
            (project_id, idempotency_key),
        )

    async def read_generation_attempt_by_key(
        self,
        session,
        project_id: str,
        idempotency_key: str,
    ):
        return await session.fetchone(
            """SELECT * FROM planning_generation_attempts
                WHERE project_id=%s AND idempotency_key=%s""",
            (project_id, idempotency_key),
        )

    async def lock_generation_attempt(
        self,
        session,
        project_id: str,
        operation_id: str,
    ):
        return await session.fetchone(
            """SELECT * FROM planning_generation_attempts
                WHERE project_id=%s AND operation_id=%s
                FOR UPDATE""",
            (project_id, operation_id),
        )

    async def read_generation_attempt(
        self,
        session,
        project_id: str,
        operation_id: str,
    ):
        return await session.fetchone(
            """SELECT * FROM planning_generation_attempts
                WHERE project_id=%s AND operation_id=%s""",
            (project_id, operation_id),
        )

    async def lock_active_generation_attempt(self, session, draft_id: str):
        return await session.fetchone(
            """SELECT * FROM planning_generation_attempts
                WHERE draft_id=%s AND status='pending' AND active_slot=1
                FOR UPDATE""",
            (draft_id,),
        )

    async def read_active_generation_attempt(self, session, draft_id: str):
        return await session.fetchone(
            """SELECT * FROM planning_generation_attempts
                WHERE draft_id=%s AND status='pending' AND active_slot=1""",
            (draft_id,),
        )

    async def lock_planning_binding(self, session, project_id: str):
        return await session.fetchone(
            """SELECT head.binding_revision_id,
                      head.revision AS binding_revision,
                      head.content_hash AS binding_hash,
                      item.task_key AS binding_task_key,
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

    async def insert_generation_attempt(self, session, row: dict) -> bool:
        changed = await session.execute(
            """INSERT INTO planning_generation_attempts
               (id,project_id,draft_id,operation_id,active_slot,
                idempotency_key,request_fingerprint,binding_revision_id,
                binding_revision,binding_hash,provider_id,model_name_snapshot,
                fencing_token,lease_expires_at,input_manifest_json,
                input_manifest_hash,status,created_at,updated_at)
               VALUES (%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       'pending',%s,%s)""",
            tuple(
                row[key]
                for key in (
                    "id",
                    "project_id",
                    "draft_id",
                    "operation_id",
                    "idempotency_key",
                    "request_fingerprint",
                    "binding_revision_id",
                    "binding_revision",
                    "binding_hash",
                    "provider_id",
                    "model_name_snapshot",
                    "fencing_token",
                    "lease_expires_at",
                    "input_manifest_json",
                    "input_manifest_hash",
                    "created_at",
                    "updated_at",
                )
            ),
        )
        return changed == 1

    async def next_fencing_token(self, session, draft_id: str) -> int:
        latest = await session.fetchone(
            """SELECT fencing_token FROM planning_generation_attempts
                WHERE draft_id=%s
                ORDER BY fencing_token DESC
                LIMIT 1 FOR UPDATE""",
            (draft_id,),
        )
        return 1 if latest is None else int(latest["fencing_token"]) + 1

    async def supersede_generation_attempt(
        self,
        session,
        *,
        project_id: str,
        operation_id: str,
        fencing_token: int,
        updated_at: int,
    ) -> bool:
        changed = await session.execute(
            """UPDATE planning_generation_attempts
                  SET status='superseded',active_slot=NULL,updated_at=%s
                WHERE project_id=%s AND operation_id=%s
                  AND status='pending' AND active_slot=1
                  AND fencing_token=%s""",
            (updated_at, project_id, operation_id, fencing_token),
        )
        return changed == 1

    async def fail_generation_attempt(
        self,
        session,
        *,
        project_id: str,
        operation_id: str,
        fencing_token: int,
        failure_code: str,
        updated_at: int,
    ) -> bool:
        changed = await session.execute(
            """UPDATE planning_generation_attempts
                  SET status='failed',active_slot=NULL,failure_code=%s,
                      updated_at=%s
                WHERE project_id=%s AND operation_id=%s
                  AND status='pending' AND active_slot=1
                  AND fencing_token=%s""",
            (
                failure_code,
                updated_at,
                project_id,
                operation_id,
                fencing_token,
            ),
        )
        return changed == 1

    async def load_generation_result_into_draft(
        self,
        session,
        *,
        project_id: str,
        draft_id: str,
        expected_revision: int,
        expected_hash: str,
        operation_id: str,
        fencing_token: int,
        content_json: str,
        content_hash: str,
        loaded_at: int,
    ) -> bool:
        loaded_revision = expected_revision + 1
        changed = await session.execute(
            """UPDATE planning_drafts draft
                 JOIN planning_generation_attempts attempt
                   ON attempt.project_id=draft.project_id
                  AND attempt.draft_id=draft.id
                  SET draft.draft_revision=%s,
                      draft.content_json=%s,draft.content_hash=%s,
                      draft.source_attempt_id=attempt.id,
                      draft.updated_at=%s,
                      attempt.status='succeeded',
                      attempt.active_slot=NULL,
                      attempt.result_content_json=%s,
                      attempt.result_content_hash=%s,
                      attempt.loaded_draft_revision=%s,
                      attempt.loaded_at=%s,
                      attempt.updated_at=%s
                WHERE draft.project_id=%s AND draft.id=%s
                  AND draft.status='active' AND draft.active_slot=1
                  AND draft.draft_revision=%s AND draft.content_hash=%s
                  AND attempt.operation_id=%s
                  AND attempt.status='pending'
                  AND attempt.active_slot=1
                  AND attempt.fencing_token=%s
                  AND attempt.loaded_draft_revision IS NULL
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
                project_id,
                draft_id,
                expected_revision,
                expected_hash,
                operation_id,
                fencing_token,
            ),
        )
        return changed == 2
