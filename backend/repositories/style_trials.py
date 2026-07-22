"""Session-bound persistence for temporary style-trial attempts."""

from __future__ import annotations

from backend.domain.json_contracts import canonical_hash
from backend.repositories.project_lifecycle import lock_project


def _input_facts(inputs: dict) -> dict:
    """Return only immutable/public identities used for publication fencing."""

    selection = inputs.get("selection") or {}
    engine = inputs.get("engine") or {}
    provider = inputs.get("provider") or {}
    return {
        "projectActive": bool(
            inputs.get("project")
            and inputs["project"].get("archived_at") is None
        ),
        "selection": {
            "revision": selection.get("selection_revision"),
            "seedId": selection.get("seed_id"),
            "seedRevisionId": selection.get("seed_revision_id"),
            "seedHash": selection.get("seed_hash"),
        },
        "engine": {
            "optionId": engine.get("id"),
            "hash": engine.get("content_hash"),
            "batchId": engine.get("batch_id"),
            "status": engine.get("status"),
            "selectionRevision": engine.get("selection_revision"),
            "seedRevisionId": engine.get("seed_revision_id"),
            "seedHash": engine.get("seed_hash"),
        },
        "styles": [
            {
                "role": row.get("role"),
                "id": row.get("id"),
                "revision": row.get("revision"),
                "hash": row.get("content_hash"),
                "status": row.get("status"),
                "headId": row.get("head_id"),
                "headRevision": row.get("head_revision"),
                "headHash": row.get("head_hash"),
            }
            for row in inputs.get("styles") or ()
        ],
        "binding": {
            "revisionId": inputs.get("binding_revision_id"),
            "hash": inputs.get("binding_hash"),
            "resolutionStatus": inputs.get("resolution_status"),
            "providerId": inputs.get("provider_id"),
            "modelNameSnapshot": inputs.get("model_name_snapshot"),
        },
        "provider": {
            "providerId": provider.get("id"),
            "providerType": provider.get("provider_type"),
            "modelName": provider.get("model_name"),
            "profileRevision": provider.get("revision"),
            "enabled": provider.get("enabled"),
            "lifecycleStatus": provider.get("lifecycle_status"),
        },
    }


def input_facts_hash(inputs: dict) -> str:
    return canonical_hash(_input_facts(inputs))


class StyleTrialRepository:
    """Use fixed SQL only; Provider calls remain outside this repository."""

    async def lock_project(self, session, project_id: str):
        return await lock_project(session, project_id)

    async def lock_request(self, session, project_id: str, idempotency_key: str):
        return await session.fetchone(
            """SELECT * FROM style_trial_requests
               WHERE project_id=%s AND idempotency_key=%s FOR UPDATE""",
            (project_id, idempotency_key),
        )

    async def lock_inputs(self, session, command) -> dict:
        project = await self.lock_project(session, command.project_id)
        selection = await session.fetchone(
            """SELECT selected.seed_id,selected.selection_revision,
                      selected.seed_revision_id,selected.seed_hash,
                      revision.payload_json
                 FROM project_selected_seeds selected
                 JOIN creative_seed_revisions revision
                   ON revision.project_id=selected.project_id
                  AND revision.seed_id=selected.seed_id
                  AND revision.id=selected.seed_revision_id
                WHERE selected.project_id=%s FOR UPDATE""",
            (command.project_id,),
        )
        engine = await session.fetchone(
            """SELECT engine_option.id,engine_option.batch_id,
                      engine_option.content_hash,engine_option.payload_json,
                      batch.status,batch.selection_revision,
                      batch.seed_revision_id,batch.seed_hash
                 FROM story_engine_options engine_option
                 JOIN story_engine_batches batch
                   ON batch.project_id=engine_option.project_id
                  AND batch.id=engine_option.batch_id
                  AND batch.selection_revision=engine_option.selection_revision
                WHERE engine_option.project_id=%s AND engine_option.id=%s
                FOR UPDATE""",
            (command.project_id, command.engine_option_id),
        )
        requested = [
            ("primary", command.primary_style_revision_id),
            *((
                ("secondary", command.secondary_style_revision_id),
            ) if command.secondary_style_revision_id is not None else ()),
        ]
        ids = tuple(sorted(item[1] for item in requested))
        rows = await session.fetchall(
            f"""SELECT revision.id,revision.stable_key,revision.revision,
                       revision.payload_json,revision.content_hash,revision.status,
                       head.style_template_id AS head_id,
                       head.revision AS head_revision,
                       head.content_hash AS head_hash
                  FROM style_templates revision
                  LEFT JOIN style_template_heads head
                    ON head.stable_key=revision.stable_key
                 WHERE revision.id IN ({','.join(['%s'] * len(ids))})
                 ORDER BY revision.id FOR UPDATE""",
            ids,
        )
        by_id = {row["id"]: dict(row) for row in rows}
        styles = tuple(
            ({"role": role} | by_id[revision_id])
            for role, revision_id in requested
            if revision_id in by_id
        )
        binding = await session.fetchone(
            """SELECT head.binding_revision_id,
                      head.content_hash AS binding_hash,
                      item.resolution_status,item.provider_id,
                      item.model_name_snapshot,
                      provider.id AS current_provider_id,
                      provider.provider_type,provider.model_name,
                      provider.base_url,provider.api_key,provider.enabled,
                      provider.lifecycle_status,provider.revision,
                      provider.temperature,provider.max_output_tokens
                 FROM project_model_binding_heads head
                 JOIN project_model_binding_items item
                   ON item.binding_revision_id=head.binding_revision_id
                  AND item.task_key='seed'
                 LEFT JOIN provider_profiles provider
                   ON provider.id=item.provider_id
                WHERE head.project_id=%s FOR UPDATE""",
            (command.project_id,),
        )
        provider = None
        if binding is not None:
            provider = {
                "id": binding.get("current_provider_id"),
                "provider_type": binding.get("provider_type"),
                "model_name": binding.get("model_name"),
                "base_url": binding.get("base_url"),
                "api_key": binding.get("api_key"),
                "enabled": binding.get("enabled"),
                "lifecycle_status": binding.get("lifecycle_status"),
                "revision": binding.get("revision"),
                "temperature": binding.get("temperature"),
                "max_output_tokens": binding.get("max_output_tokens"),
            }
        return {
            "project": project,
            "selection": selection,
            "engine": engine,
            "styles": styles,
            "binding_revision_id": (
                binding.get("binding_revision_id") if binding else None
            ),
            "binding_hash": binding.get("binding_hash") if binding else None,
            "resolution_status": (
                binding.get("resolution_status") if binding else None
            ),
            "provider_id": binding.get("provider_id") if binding else None,
            "model_name_snapshot": (
                binding.get("model_name_snapshot") if binding else None
            ),
            "provider": provider,
        }

    async def insert_request(self, session, row: dict) -> None:
        await session.execute(
            """INSERT INTO style_trial_requests
               (id,project_id,idempotency_key,request_hash,status,attempt_id,
                result_hash,public_error_code,created_at,completed_at)
               VALUES (%s,%s,%s,%s,'running',%s,NULL,NULL,%s,NULL)""",
            (
                row["id"], row["project_id"], row["idempotency_key"],
                row["request_hash"], row["attempt_id"], row["created_at"],
            ),
        )

    async def insert_attempt(self, session, row: dict) -> None:
        await session.execute(
            """INSERT INTO style_trial_attempts
               (id,project_id,selection_revision,binding_revision_id,
                binding_hash,input_manifest_json,input_manifest_hash,status,
                result_json,result_hash,public_error_code,created_at,completed_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'running',NULL,NULL,NULL,%s,NULL)""",
            (
                row["id"], row["project_id"], row["selection_revision"],
                row["binding_revision_id"], row["binding_hash"],
                row["input_manifest_json"], row["input_manifest_hash"],
                row["created_at"],
            ),
        )

    async def read_attempt(self, session, project_id: str, attempt_id: str):
        return await session.fetchone(
            """SELECT * FROM style_trial_attempts
               WHERE project_id=%s AND id=%s""",
            (project_id, attempt_id),
        )

    async def _terminalize_failure(self, session, **values) -> None:
        attempt_changed = await session.execute(
            """UPDATE style_trial_attempts
                  SET status=%s,result_json=NULL,result_hash=NULL,
                      public_error_code=%s,completed_at=%s
                WHERE project_id=%s AND id=%s AND status='running'""",
            (
                values["attempt_status"], values["public_error_code"],
                values["completed_at"], values["project_id"],
                values["attempt_id"],
            ),
        )
        request_changed = await session.execute(
            """UPDATE style_trial_requests
                  SET status=%s,result_hash=NULL,
                      public_error_code=%s,completed_at=%s
                WHERE project_id=%s AND idempotency_key=%s
                  AND status='running' AND attempt_id=%s""",
            (
                values["request_status"],
                values["public_error_code"], values["completed_at"],
                values["project_id"], values["idempotency_key"],
                values["attempt_id"],
            ),
        )
        if attempt_changed != 1 or request_changed != 1:
            raise RuntimeError("style trial terminal write must remain atomic")

    async def fail(self, session, **values) -> bool:
        await self._terminalize_failure(session, **values)
        return True

    async def cleanup_interrupted(self, session, **values) -> bool:
        request = await session.fetchone(
            """SELECT status,attempt_id FROM style_trial_requests
                WHERE project_id=%s AND idempotency_key=%s
                  AND request_hash=%s AND id=%s AND attempt_id=%s FOR UPDATE""",
            (
                values["project_id"], values["idempotency_key"],
                values["request_hash"], values["request_id"],
                values["attempt_id"],
            ),
        )
        if request is None:
            return False
        if not request.get("attempt_id"):
            raise RuntimeError("style trial interruption request lost its attempt")
        attempt = await session.fetchone(
            """SELECT status FROM style_trial_attempts
                WHERE project_id=%s AND id=%s FOR UPDATE""",
            (values["project_id"], values["attempt_id"]),
        )
        if attempt is None:
            raise RuntimeError("style trial interruption attempt is missing")
        request_status = request["status"]
        attempt_status = attempt["status"]
        if request_status == "running" and attempt_status == "running":
            attempt_changed = await session.execute(
                """UPDATE style_trial_attempts
                      SET status='outcome_unknown',result_json=NULL,result_hash=NULL,
                          public_error_code=%s,completed_at=%s
                    WHERE project_id=%s AND id=%s AND status='running'""",
                (
                    values["public_error_code"], values["completed_at"],
                    values["project_id"], values["attempt_id"],
                ),
            )
            request_changed = await session.execute(
                """UPDATE style_trial_requests
                      SET status='outcome_unknown',result_hash=NULL,
                          public_error_code=%s,completed_at=%s
                    WHERE project_id=%s AND idempotency_key=%s AND id=%s
                      AND request_hash=%s AND status='running' AND attempt_id=%s""",
                (
                    values["public_error_code"], values["completed_at"],
                    values["project_id"], values["idempotency_key"],
                    values["request_id"], values["request_hash"],
                    values["attempt_id"],
                ),
            )
            if attempt_changed != 1 or request_changed != 1:
                raise RuntimeError("style trial cleanup write must remain atomic")
            return True
        if (
            request_status in {"succeeded", "failed", "outcome_unknown"}
            and attempt_status == request_status
        ):
            return False
        raise RuntimeError("style trial interruption state diverged")

    async def publish(self, session, **values) -> bool:
        current = await self.lock_inputs(session, values["command"])
        if input_facts_hash(current) != values["expected_input_facts_hash"]:
            await self._terminalize_failure(
                session,
                project_id=values["project_id"],
                idempotency_key=values["idempotency_key"],
                attempt_id=values["attempt_id"],
                attempt_status="failed",
                request_status="failed",
                public_error_code="STYLE_TRIAL_INPUT_CHANGED",
                completed_at=values["completed_at"],
            )
            return False
        attempt_changed = await session.execute(
            """UPDATE style_trial_attempts
                  SET status='succeeded',result_json=%s,result_hash=%s,
                      public_error_code=NULL,completed_at=%s
                WHERE project_id=%s AND id=%s AND status='running'""",
            (
                values["result_json"], values["result_hash"],
                values["completed_at"], values["project_id"],
                values["attempt_id"],
            ),
        )
        request_changed = await session.execute(
            """UPDATE style_trial_requests
                  SET status='succeeded',result_hash=%s,
                      public_error_code=NULL,completed_at=%s
                WHERE project_id=%s AND idempotency_key=%s
                  AND status='running' AND attempt_id=%s AND request_hash=%s""",
            (
                values["result_hash"],
                values["completed_at"], values["project_id"],
                values["idempotency_key"], values["attempt_id"],
                values["request_hash"],
            ),
        )
        if attempt_changed != 1 or request_changed != 1:
            raise RuntimeError("style trial publication must remain atomic")
        return True


__all__ = ("StyleTrialRepository", "input_facts_hash")
