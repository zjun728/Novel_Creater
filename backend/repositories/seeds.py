"""Session-bound persistence for immutable seed revisions and selection CAS."""

from __future__ import annotations

from backend.repositories.project_lifecycle import (
    lock_active_project as _lock_active_project,
    read_project as read_any_project,
)
import json


async def lock_active_project(session, project_id: str):
    """Use the shared active-project boundary without waiting behind a writer."""

    return await _lock_active_project(session, project_id, nowait=True)


class SeedRepository:
    """Every method uses the explicit session supplied by its caller."""

    async def lock_project(self, session, project_id: str):
        return await lock_active_project(session, project_id)

    async def read_project(self, session, project_id: str):
        return await read_any_project(session, project_id)

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

    async def insert_selection_revision(self, session, row: dict) -> None:
        await session.execute(
            """INSERT INTO project_seed_selection_revisions
               (project_id, selection_revision, seed_id, seed_revision_id,
                seed_hash, selected_at)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (
                row["project_id"], row["selection_revision"], row["seed_id"],
                row["seed_revision_id"], row["seed_hash"], row["selected_at"],
            ),
        )

    async def advance_selected_revision(self, session, row: dict) -> bool:
        changed = await session.execute(
            """UPDATE project_selected_seeds
               SET seed_revision_id=%s, seed_hash=%s,
                   selection_revision=%s, updated_at=%s
               WHERE project_id=%s AND selection_revision=%s""",
            (
                row["seed_revision_id"], row["seed_hash"],
                row["selection_revision"], row["updated_at"],
                row["project_id"], row["expected_selection_revision"],
            ),
        )
        return changed == 1

    async def replace_selection(self, session, row: dict) -> bool:
        changed = await session.execute(
            """UPDATE project_selected_seeds
               SET seed_id=%s, seed_revision_id=%s, seed_hash=%s,
                   selection_revision=%s, selected_at=%s, updated_at=%s
               WHERE project_id=%s AND selection_revision=%s""",
            (
                row["seed_id"], row["seed_revision_id"], row["seed_hash"],
                row["selection_revision"], row["selected_at"],
                row["updated_at"], row["project_id"],
                row["expected_selection_revision"],
            ),
        )
        return changed == 1

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
                   WHERE project_id=%s AND seed_id=%s)
                 +
                 (SELECT COUNT(*) FROM project_seed_selection_revisions
                   WHERE project_id=%s AND seed_id=%s) AS count""",
            (
                project_id, seed_id, project_id, seed_id,
                project_id, seed_id, project_id, seed_id,
            ),
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

    async def restore(
        self, session, project_id: str, seed_id: str, updated_at: int
    ) -> None:
        await session.execute(
            """UPDATE creative_seeds SET status='candidate', updated_at=%s
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
                      selected.seed_id, selected.seed_revision_id,
                      selected.seed_hash, selected.selected_at,
                      selected.updated_at AS selection_updated_at,
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
            """SELECT h.revision, c.selection_revision, c.seed_id,
                      c.seed_revision_id, c.seed_hash
               FROM project_contract_heads h
               LEFT JOIN creation_contracts c
                 ON c.project_id=h.project_id
                AND c.id=h.creation_contract_id
               WHERE h.project_id=%s""",
            (project_id,),
        )

    async def lock_seed_provenance_inputs(
        self,
        session,
        project_id: str,
        selection,
    ) -> dict:
        attempt = None
        if selection.inspiration_attempt_id is not None:
            attempt = await session.fetchone(
                """SELECT id,status,result_hash,market_snapshot_id,
                          market_snapshot_hash,market_analysis_id,
                          market_analysis_hash,input_manifest_json
                     FROM seed_inspiration_attempts
                    WHERE project_id=%s AND id=%s
                    FOR UPDATE""",
                (project_id, selection.inspiration_attempt_id),
            )
        snapshot_ids = tuple(selection.snapshot_ids)
        placeholders = ",".join("%s" for _ in snapshot_ids)
        rows = await session.fetchall(
            f"""SELECT snapshot.id,snapshot.source_id,snapshot.source_url,
                       snapshot.captured_at,snapshot.content_hash,
                       manifest.manifest_hash
                  FROM market_snapshots snapshot
                  JOIN market_snapshot_manifests manifest
                    ON manifest.source_id=snapshot.source_id
                   AND manifest.snapshot_id=snapshot.id
                   AND manifest.snapshot_hash=snapshot.content_hash
                 WHERE snapshot.id IN ({placeholders})
                 FOR UPDATE""",
            snapshot_ids,
        )
        by_id = {row["id"]: dict(row) for row in rows}
        snapshots = tuple(
            by_id[item] for item in snapshot_ids if item in by_id
        )
        analysis = None
        if selection.analysis_id is not None:
            analysis = await session.fetchone(
                """SELECT id,status,result_hash,input_manifest_json
                     FROM market_analyses
                    WHERE project_id=%s AND id=%s
                    FOR UPDATE""",
                (project_id, selection.analysis_id),
            )
        return {
            "snapshots": snapshots,
            "analysis": analysis,
            "attempt": attempt,
        }

    async def lock_inspiration_project(self, session, project_id: str):
        return await _lock_active_project(session, project_id, nowait=True)

    async def lock_inspiration_request(
        self,
        session,
        project_id: str,
        idempotency_key: str,
    ):
        return await session.fetchone(
            """SELECT request.*,attempt.status AS attempt_status,
                      attempt.result_json,attempt.created_at AS attempt_created_at,
                      attempt.completed_at AS attempt_completed_at
                 FROM seed_inspiration_requests request
                 LEFT JOIN seed_inspiration_attempts attempt
                   ON attempt.project_id=request.project_id
                  AND attempt.id=request.attempt_id
                WHERE request.project_id=%s AND request.idempotency_key=%s
                FOR UPDATE""",
            (project_id, idempotency_key),
        )

    async def lock_inspiration_inputs(
        self,
        session,
        project_id: str,
        snapshot_ids: tuple[str, ...],
        analysis_id: str,
    ) -> dict:
        binding = await session.fetchone(
            """SELECT head.binding_revision_id,
                      head.content_hash AS binding_hash,
                      item.resolution_status,item.provider_id,
                      item.model_name_snapshot,
                      provider.id AS current_provider_id,
                      provider.provider_type,provider.model_name,
                      provider.base_url,provider.api_key,provider.enabled,
                      provider.lifecycle_status,provider.temperature,
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
        if binding is None:
            return {"snapshots": (), "analysis": None, "provider": None}
        selection = await session.fetchone(
            """SELECT selection_revision
                 FROM project_selected_seeds
                WHERE project_id=%s
                FOR UPDATE""",
            (project_id,),
        )
        placeholders = ",".join("%s" for _ in snapshot_ids)
        rows = await session.fetchall(
            f"""SELECT snapshot.id,snapshot.source_id,snapshot.captured_at,
                       snapshot.platform,snapshot.ranking_name,
                       snapshot.category,snapshot.source_url,
                       snapshot.content_hash,snapshot.entry_count,
                       manifest.manifest_hash
                  FROM market_snapshots snapshot
                  JOIN market_snapshot_manifests manifest
                    ON manifest.source_id=snapshot.source_id
                   AND manifest.snapshot_id=snapshot.id
                   AND manifest.snapshot_hash=snapshot.content_hash
                 WHERE snapshot.id IN ({placeholders})
                 FOR UPDATE""",
            snapshot_ids,
        )
        by_id = {row["id"]: dict(row) for row in rows}
        snapshots = tuple(
            by_id[item] for item in snapshot_ids if item in by_id
        )
        if len(snapshots) == len(snapshot_ids):
            entries = await session.fetchall(
                f"""SELECT snapshot_id,rank_number,title,author,category,
                           public_metrics_json
                      FROM market_snapshot_entries
                     WHERE snapshot_id IN ({placeholders})
                     ORDER BY snapshot_id,rank_number""",
                snapshot_ids,
            )
            grouped = {item: [] for item in snapshot_ids}
            for row in entries:
                metrics = row["public_metrics_json"]
                if isinstance(metrics, str):
                    metrics = json.loads(metrics)
                grouped[row["snapshot_id"]].append(
                    {
                        "rank": int(row["rank_number"]),
                        "title": row["title"],
                        "author": row["author"],
                        "category": row["category"],
                        "public_metrics": metrics,
                    }
                )
            complete = []
            for snapshot in snapshots:
                snapshot_entries = tuple(grouped[snapshot["id"]])
                if len(snapshot_entries) != int(snapshot["entry_count"]):
                    complete = []
                    break
                snapshot["entries"] = snapshot_entries
                complete.append(snapshot)
            snapshots = tuple(complete)
        analysis = await session.fetchone(
            """SELECT id,status,result_hash,input_manifest_json,
                      input_manifest_hash,analysis_json
                 FROM market_analyses
                WHERE project_id=%s AND id=%s
                FOR UPDATE""",
            (project_id, analysis_id),
        )
        provider = {
            "id": binding.get("current_provider_id"),
            "provider_type": binding.get("provider_type"),
            "model_name": binding.get("model_name"),
            "base_url": binding.get("base_url"),
            "api_key": binding.get("api_key"),
            "enabled": binding.get("enabled"),
            "lifecycle_status": binding.get("lifecycle_status"),
            "temperature": binding.get("temperature"),
            "max_output_tokens": binding.get("max_output_tokens"),
        }
        return {
            "selection_revision": (
                int(selection["selection_revision"])
                if selection is not None
                else None
            ),
            "binding_revision_id": binding["binding_revision_id"],
            "binding_hash": binding["binding_hash"],
            "resolution_status": binding["resolution_status"],
            "provider_id": binding["provider_id"],
            "model_name_snapshot": binding["model_name_snapshot"],
            "provider": provider,
            "snapshots": snapshots,
            "analysis": analysis,
        }

    async def insert_inspiration_request(self, session, row: dict) -> None:
        await session.execute(
            """INSERT INTO seed_inspiration_requests
               (id,project_id,idempotency_key,request_hash,status,attempt_id,
                result_hash,public_error_code,created_at,completed_at)
               VALUES (%s,%s,%s,%s,'reserved',NULL,NULL,NULL,%s,NULL)""",
            (
                row["id"],
                row["project_id"],
                row["idempotency_key"],
                row["request_hash"],
                row["created_at"],
            ),
        )

    async def insert_inspiration_attempt(self, session, row: dict) -> None:
        await session.execute(
            """INSERT INTO seed_inspiration_attempts
               (id,project_id,selection_revision,market_source_id,
                market_snapshot_id,market_snapshot_hash,market_analysis_id,
                market_analysis_hash,binding_revision_id,binding_hash,
                input_manifest_json,input_manifest_hash,status,result_json,
                result_hash,public_error_code,created_at,completed_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'running',
                       NULL,NULL,NULL,%s,NULL)""",
            (
                row["id"],
                row["project_id"],
                row["selection_revision"],
                row["market_source_id"],
                row["market_snapshot_id"],
                row["market_snapshot_hash"],
                row["market_analysis_id"],
                row["market_analysis_hash"],
                row["binding_revision_id"],
                row["binding_hash"],
                row["input_manifest_json"],
                row["input_manifest_hash"],
                row["created_at"],
            ),
        )

    async def read_inspiration_attempt(
        self,
        session,
        project_id: str,
        attempt_id: str,
    ):
        return await session.fetchone(
            """SELECT * FROM seed_inspiration_attempts
                WHERE project_id=%s AND id=%s""",
            (project_id, attempt_id),
        )

    async def publish_inspiration(self, session, **values) -> bool:
        attempt = await session.fetchone(
            """SELECT status FROM seed_inspiration_attempts
                WHERE project_id=%s AND id=%s FOR UPDATE""",
            (values["project_id"], values["attempt_id"]),
        )
        binding = await session.fetchone(
            """SELECT binding_revision_id,content_hash
                 FROM project_model_binding_heads
                WHERE project_id=%s FOR UPDATE""",
            (values["project_id"],),
        )
        snapshots = tuple(values["snapshots"])
        snapshot_ids = tuple(item["id"] for item in snapshots)
        placeholders = ",".join("%s" for _ in snapshot_ids)
        rows = await session.fetchall(
            f"""SELECT snapshot.id,snapshot.content_hash,
                       manifest.manifest_hash
                  FROM market_snapshots snapshot
                  JOIN market_snapshot_manifests manifest
                    ON manifest.source_id=snapshot.source_id
                   AND manifest.snapshot_id=snapshot.id
                   AND manifest.snapshot_hash=snapshot.content_hash
                 WHERE snapshot.id IN ({placeholders})
                 FOR UPDATE""",
            snapshot_ids,
        )
        facts = {
            row["id"]: (row["content_hash"], row["manifest_hash"])
            for row in rows
        }
        analysis = await session.fetchone(
            """SELECT status,result_hash,input_manifest_hash
                 FROM market_analyses
                WHERE project_id=%s AND id=%s FOR UPDATE""",
            (values["project_id"], values["analysis_id"]),
        )
        matches = bool(
            attempt is not None
            and attempt["status"] == "running"
            and binding is not None
            and binding["binding_revision_id"] == values["binding_revision_id"]
            and binding["content_hash"] == values["binding_hash"]
            and len(facts) == len(snapshots)
            and all(
                facts.get(item["id"])
                == (item["content_hash"], item["manifest_hash"])
                for item in snapshots
            )
            and analysis is not None
            and analysis["status"] == "succeeded"
            and analysis["result_hash"] == values["analysis_hash"]
            and analysis["input_manifest_hash"]
            == values["analysis_manifest_hash"]
        )
        if not matches:
            await self._terminalize_inspiration(
                session,
                project_id=values["project_id"],
                idempotency_key=values["idempotency_key"],
                attempt_id=values["attempt_id"],
                attempt_status="failed",
                request_status="failed",
                public_error_code="SEED_INSPIRATION_INPUT_CHANGED",
                completed_at=values["completed_at"],
            )
            return False
        changed = await session.execute(
            """UPDATE seed_inspiration_attempts
                  SET status='succeeded',result_json=%s,result_hash=%s,
                      public_error_code=NULL,completed_at=%s
                WHERE project_id=%s AND id=%s AND status='running'""",
            (
                values["result_json"],
                values["result_hash"],
                values["completed_at"],
                values["project_id"],
                values["attempt_id"],
            ),
        )
        if changed != 1:
            return False
        changed = await session.execute(
            """UPDATE seed_inspiration_requests
                  SET status='succeeded',attempt_id=%s,result_hash=%s,
                      public_error_code=NULL,completed_at=%s
                WHERE project_id=%s AND idempotency_key=%s
                  AND status='reserved' AND request_hash=%s""",
            (
                values["attempt_id"],
                values["result_hash"],
                values["completed_at"],
                values["project_id"],
                values["idempotency_key"],
                values["request_hash"],
            ),
        )
        if changed != 1:
            raise RuntimeError(
                "seed inspiration publication must remain atomic"
            )
        return True

    async def _terminalize_inspiration(self, session, **values) -> bool:
        attempt_changed = await session.execute(
            """UPDATE seed_inspiration_attempts
                  SET status=%s,result_json=NULL,result_hash=NULL,
                      public_error_code=%s,completed_at=%s
                WHERE project_id=%s AND id=%s AND status='running'""",
            (
                values["attempt_status"],
                values["public_error_code"],
                values["completed_at"],
                values["project_id"],
                values["attempt_id"],
            ),
        )
        request_attempt = (
            values["attempt_id"]
            if values["request_status"] == "outcome_unknown"
            else None
        )
        request_changed = await session.execute(
            """UPDATE seed_inspiration_requests
                  SET status=%s,attempt_id=%s,result_hash=NULL,
                      public_error_code=%s,completed_at=%s
                WHERE project_id=%s AND idempotency_key=%s
                  AND status='reserved'""",
            (
                values["request_status"],
                request_attempt,
                values["public_error_code"],
                values["completed_at"],
                values["project_id"],
                values["idempotency_key"],
            ),
        )
        if attempt_changed != 1 or request_changed != 1:
            raise RuntimeError(
                "seed inspiration terminal write must remain atomic"
            )
        return True

    async def fail_inspiration(self, session, **values) -> bool:
        return await self._terminalize_inspiration(session, **values)
