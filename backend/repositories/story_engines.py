"""Session-bound persistence for auditable story-engine batches."""

from __future__ import annotations

from backend.repositories.project_lifecycle import (
    lock_active_project,
    read_active_project,
)


class StoryEngineRepository:
    """Persist story-engine state using only the caller's explicit session."""

    async def lock_project(self, session, project_id: str):
        return await lock_active_project(session, project_id)

    async def read_project(self, session, project_id: str):
        return await read_active_project(session, project_id)

    async def lock_selected_seed(self, session, project_id: str):
        return await session.fetchone(
            """SELECT selected.seed_id,
                      selected.seed_revision_id,
                      selected.seed_hash,
                      revision.payload_json,
                      project.genre AS project_genre
               FROM project_selected_seeds selected
               JOIN creative_seeds seed
                 ON seed.project_id=selected.project_id
                AND seed.id=selected.seed_id
               JOIN creative_seed_revisions revision
                 ON revision.seed_id=selected.seed_id
                AND revision.id=selected.seed_revision_id
               JOIN projects project ON project.id=selected.project_id
               WHERE selected.project_id=%s AND seed.status='candidate'
               FOR UPDATE""",
            (project_id,),
        )

    async def lock_seed_binding(self, session, project_id: str):
        return await session.fetchone(
            """SELECT head.binding_revision_id,
                      head.content_hash AS binding_hash,
                      item.resolution_status,
                      item.provider_id,
                      item.model_name_snapshot,
                      provider.temperature,
                      provider.max_output_tokens
               FROM project_model_binding_heads head
               JOIN project_model_binding_items item
                 ON item.binding_revision_id=head.binding_revision_id
                AND item.task_key='seed'
               LEFT JOIN provider_profiles provider
                 ON provider.id=item.provider_id
               WHERE head.project_id=%s
               FOR UPDATE""",
            (project_id,),
        )

    async def lock_provider_connection(self, session, provider_id: str):
        return await session.fetchone(
            """SELECT id,provider_type,model_name,base_url,api_key,enabled,
                      lifecycle_status
               FROM provider_profiles WHERE id=%s FOR UPDATE""",
            (provider_id,),
        )

    async def lock_batch_by_key(
        self, session, project_id: str, idempotency_key: str
    ):
        return await session.fetchone(
            """SELECT * FROM story_engine_batches
               WHERE project_id=%s AND idempotency_key=%s FOR UPDATE""",
            (project_id, idempotency_key),
        )

    async def insert_batch(self, session, row: dict) -> None:
        await session.execute(
            """INSERT INTO story_engine_batches
               (id,project_id,source_type,seed_id,seed_revision_id,seed_hash,
                binding_revision_id,binding_hash,provider_id,model_name_snapshot,
                idempotency_key,request_json,request_hash,status,attempt_id,
                attempt_started_at,lease_expires_at,raw_response_text,
                raw_response_hash,public_error_code,created_at,finished_at)
               VALUES
               (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s)""",
            (
                row["id"], row["project_id"], row["source_type"],
                row["seed_id"], row["seed_revision_id"], row["seed_hash"],
                row["binding_revision_id"], row["binding_hash"],
                row["provider_id"], row["model_name_snapshot"],
                row["idempotency_key"], row["request_json"],
                row["request_hash"], row["status"], row["attempt_id"],
                row["attempt_started_at"], row["lease_expires_at"],
                row["raw_response_text"], row["raw_response_hash"],
                row["public_error_code"], row["created_at"],
                row["finished_at"],
            ),
        )

    async def insert_options(self, session, rows: tuple[dict, ...]) -> None:
        for row in rows:
            await session.execute(
                """INSERT INTO story_engine_options
                   (id,project_id,batch_id,option_order,payload_json,
                    content_hash,created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (
                    row["id"], row["project_id"], row["batch_id"],
                    row["option_order"], row["payload_json"],
                    row["content_hash"], row["created_at"],
                ),
            )

    async def read_batch(self, session, project_id: str, batch_id: str):
        return await session.fetchone(
            "SELECT * FROM story_engine_batches WHERE project_id=%s AND id=%s",
            (project_id, batch_id),
        )

    async def list_options(self, session, project_id: str, batch_id: str):
        return await session.fetchall(
            """SELECT id,project_id,batch_id,option_order,payload_json,
                      content_hash,created_at
               FROM story_engine_options
               WHERE project_id=%s AND batch_id=%s
               ORDER BY option_order ASC""",
            (project_id, batch_id),
        )

    async def cas_start_attempt(
        self, session, project_id: str, batch_id: str, row: dict
    ) -> bool:
        changed = await session.execute(
            """UPDATE story_engine_batches
               SET status='running',attempt_id=%s,attempt_started_at=%s,
                   lease_expires_at=%s
               WHERE project_id=%s AND id=%s AND source_type='provider'
                 AND status='reserved' AND attempt_id IS NULL
                 AND provider_id IS NOT NULL
                 AND model_name_snapshot IS NOT NULL""",
            (
                row["attempt_id"], row["attempt_started_at"],
                row["lease_expires_at"], project_id, batch_id,
            ),
        )
        return changed == 1

    async def cas_succeed_attempt(
        self,
        session,
        project_id: str,
        batch_id: str,
        attempt_id: str,
        row: dict,
    ) -> bool:
        changed = await session.execute(
            """UPDATE story_engine_batches
               SET status='succeeded',raw_response_text=NULL,
                   raw_response_hash=%s,finished_at=%s
               WHERE project_id=%s AND id=%s AND status='running'
                 AND attempt_id=%s""",
            (
                row["raw_response_hash"], row["finished_at"],
                project_id, batch_id, attempt_id,
            ),
        )
        return changed == 1

    async def cas_fail_attempt(
        self,
        session,
        project_id: str,
        batch_id: str,
        attempt_id: str,
        row: dict,
    ) -> bool:
        changed = await session.execute(
            """UPDATE story_engine_batches
               SET status='failed',raw_response_text=NULL,raw_response_hash=%s,
                   public_error_code=%s,finished_at=%s
               WHERE project_id=%s AND id=%s AND status='running'
                 AND attempt_id=%s""",
            (
                row.get("raw_response_hash"),
                row["public_error_code"],
                row["finished_at"],
                project_id, batch_id, attempt_id,
            ),
        )
        return changed == 1

    async def cas_fail_configuration(
        self, session, project_id: str, batch_id: str, row: dict
    ) -> bool:
        changed = await session.execute(
            """UPDATE story_engine_batches
               SET status='failed',public_error_code='provider_configuration',
                   finished_at=%s
               WHERE project_id=%s AND id=%s AND source_type='provider'
                 AND status='reserved' AND attempt_id IS NULL""",
            (row["finished_at"], project_id, batch_id),
        )
        return changed == 1

    async def cas_unknown_attempt(
        self,
        session,
        project_id: str,
        batch_id: str,
        attempt_id: str,
        row: dict,
    ) -> bool:
        changed = await session.execute(
            """UPDATE story_engine_batches
               SET status='outcome_unknown',public_error_code='outcome_unknown',
                   finished_at=%s
               WHERE project_id=%s AND id=%s AND status='running'
                 AND attempt_id=%s""",
            (row["finished_at"], project_id, batch_id, attempt_id),
        )
        return changed == 1

    async def cas_reconcile_reserved(
        self,
        session,
        project_id: str,
        batch_id: str,
        row: dict,
        stale_before: int,
    ) -> bool:
        changed = await session.execute(
            """UPDATE story_engine_batches
               SET status='failed',public_error_code='not_started',finished_at=%s
               WHERE project_id=%s AND id=%s AND status='reserved'
                 AND attempt_id IS NULL AND created_at<=%s""",
            (
                row["finished_at"], project_id, batch_id, stale_before,
            ),
        )
        return changed == 1

    async def cas_reconcile_running(
        self,
        session,
        project_id: str,
        batch_id: str,
        row: dict,
        now: int,
    ) -> bool:
        changed = await session.execute(
            """UPDATE story_engine_batches
               SET status='outcome_unknown',public_error_code='outcome_unknown',
                   finished_at=%s
               WHERE project_id=%s AND id=%s AND status='running'
                 AND attempt_id=%s AND lease_expires_at<=%s""",
            (
                row["finished_at"], project_id, batch_id,
                row["attempt_id"], now,
            ),
        )
        return changed == 1
