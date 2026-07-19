"""Fixed SQL persistence for market sources and immutable snapshots."""

from __future__ import annotations

import json

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.market_sources import (
    MarketSourceConflict,
    MarketSourceFailure,
    MarketSourceNotFound,
    SourcePolicy,
)

_REFRESH_LEASE_MS = 30_000


def _json_value(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


class MarketRepository:
    async def lock_schema_guard(self, session) -> None:
        row = await session.fetchone(
            "SELECT singleton_id FROM schema_metadata "
            "WHERE singleton_id=1 FOR UPDATE"
        )
        if row is None:
            raise RuntimeError("market source seed schema guard is unavailable")

    async def list_seed_inventory(self, session):
        rows = await session.fetchall(
            """SELECT s.id,s.stable_key,s.adapter_key,s.display_name,
                      s.public_config_json,s.status,s.created_at,s.updated_at,
                      p.id AS policy_id,p.source_id,p.revision,
                      p.policy_status,p.policy_version,p.checked_at,
                      p.evidence_url,p.evidence_hash,p.allowed_origins_json,
                      p.path_prefixes_json,p.enabled,p.interval_minutes,
                      p.next_run_at,p.content_hash AS policy_content_hash,
                      p.created_at AS policy_created_at,
                      h.revision_id AS head_revision_id,
                      h.revision AS head_revision,
                      h.content_hash AS head_content_hash
               FROM market_sources s
               LEFT JOIN market_source_policy_heads h ON h.source_id=s.id
               LEFT JOIN market_source_policy_revisions p
                 ON p.source_id=h.source_id AND p.id=h.revision_id
                AND p.revision=h.revision AND p.content_hash=h.content_hash
               ORDER BY s.stable_key"""
        )
        inventory = []
        for row in rows:
            policy = None
            head = None
            if row["policy_id"] is not None:
                policy = {
                    "id": row["policy_id"],
                    "source_id": row["source_id"],
                    "revision": row["revision"],
                    "policy_status": row["policy_status"],
                    "policy_version": row["policy_version"],
                    "checked_at": row["checked_at"],
                    "evidence_url": row["evidence_url"],
                    "evidence_hash": row["evidence_hash"],
                    "allowed_origins_json": canonical_json(
                        _json_value(row["allowed_origins_json"])
                    ),
                    "path_prefixes_json": canonical_json(
                        _json_value(row["path_prefixes_json"])
                    ),
                    "enabled": row["enabled"],
                    "interval_minutes": row["interval_minutes"],
                    "next_run_at": row["next_run_at"],
                    "content_hash": row["policy_content_hash"],
                    "created_at": row["policy_created_at"],
                }
                head = {
                    "source_id": row["id"],
                    "revision_id": row["head_revision_id"],
                    "revision": row["head_revision"],
                    "content_hash": row["head_content_hash"],
                }
            inventory.append(
                {
                    "id": row["id"],
                    "stable_key": row["stable_key"],
                    "adapter_key": row["adapter_key"],
                    "display_name": row["display_name"],
                    "public_config_json": canonical_json(
                        _json_value(row["public_config_json"])
                    ),
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "policy": policy,
                    "head": head,
                }
            )
        return tuple(inventory)

    async def insert_source(self, session, row: dict) -> None:
        await session.execute(
            """INSERT INTO market_sources
               (id,stable_key,adapter_key,display_name,public_config_json,
                status,created_at,updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["id"],
                row["stable_key"],
                row["adapter_key"],
                row["display_name"],
                row["public_config_json"],
                row["status"],
                row["created_at"],
                row["updated_at"],
            ),
        )

    async def insert_policy_revision(self, session, row: dict) -> None:
        await session.execute(
            """INSERT INTO market_source_policy_revisions
               (id,source_id,revision,policy_status,policy_version,checked_at,
                evidence_url,evidence_hash,allowed_origins_json,
                path_prefixes_json,enabled,interval_minutes,next_run_at,
                content_hash,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["id"],
                row["source_id"],
                row["revision"],
                row["policy_status"],
                row["policy_version"],
                row["checked_at"],
                row["evidence_url"],
                row["evidence_hash"],
                row["allowed_origins_json"],
                row["path_prefixes_json"],
                row["enabled"],
                row["interval_minutes"],
                row["next_run_at"],
                row["content_hash"],
                row["created_at"],
            ),
        )

    async def insert_policy_head(self, session, row: dict) -> None:
        await session.execute(
            """INSERT INTO market_source_policy_heads
               (source_id,revision_id,revision,content_hash,updated_at)
               VALUES (%s,%s,%s,%s,%s)""",
            (
                row["source_id"],
                row["revision_id"],
                row["revision"],
                row["content_hash"],
                row["updated_at"],
            ),
        )

    async def insert_refresh_state(self, session, row: dict) -> None:
        await session.execute(
            """INSERT INTO market_source_refresh_states
               (source_id,last_snapshot_id,refresh_status,lease_owner,
                lease_expires_at,last_attempted_at,last_succeeded_at,
                next_run_at,public_error_code,updated_at)
               VALUES (%s,NULL,'idle',NULL,NULL,NULL,NULL,NULL,NULL,%s)""",
            (row["source_id"], row["updated_at"]),
        )

    @staticmethod
    def _policy_from_row(row) -> SourcePolicy | None:
        if row.get("policy_revision_id") is None:
            return None
        return SourcePolicy(
            status=row["policy_status"],
            checkedAt=row["checked_at"],
            evidenceURL=row["evidence_url"],
            evidenceHash=row["evidence_hash"],
            allowedOrigins=tuple(_json_value(row["allowed_origins_json"])),
            pathPrefixes=tuple(_json_value(row["path_prefixes_json"])),
            requestIntervalSeconds=int(row["interval_minutes"]) * 60,
            policyVersion=row["policy_version"],
            enabled=bool(row["enabled"]),
        )

    async def list_sources(self, session):
        rows = await session.fetchall(
            """SELECT s.id,s.stable_key,s.adapter_key,s.display_name,
                      s.public_config_json,s.status,
                      p.id AS policy_revision_id,p.revision AS policy_revision,
                      p.policy_status,p.policy_version,p.checked_at,
                      p.evidence_url,p.evidence_hash,p.allowed_origins_json,
                      p.path_prefixes_json,p.enabled,p.interval_minutes,
                      p.content_hash AS policy_hash,
                      rs.last_snapshot_id,rs.refresh_status,
                      rs.last_attempted_at,rs.last_succeeded_at,
                      rs.public_error_code
               FROM market_sources s
               LEFT JOIN market_source_policy_heads h ON h.source_id=s.id
               LEFT JOIN market_source_policy_revisions p
                 ON p.source_id=h.source_id AND p.id=h.revision_id
                AND p.revision=h.revision AND p.content_hash=h.content_hash
               LEFT JOIN market_source_refresh_states rs ON rs.source_id=s.id
               WHERE s.status='active'
               ORDER BY s.stable_key LIMIT 100"""
        )
        return tuple(self._decode_source_row(row) for row in rows)

    async def get_source(self, session, source_id: str):
        row = await session.fetchone(
            """SELECT s.id,s.stable_key,s.adapter_key,s.display_name,
                      s.public_config_json,s.status,
                      p.id AS policy_revision_id,p.revision AS policy_revision,
                      p.policy_status,p.policy_version,p.checked_at,
                      p.evidence_url,p.evidence_hash,p.allowed_origins_json,
                      p.path_prefixes_json,p.enabled,p.interval_minutes,
                      p.content_hash AS policy_hash,
                      rs.last_snapshot_id,rs.refresh_status,
                      rs.last_attempted_at,rs.last_succeeded_at,
                      rs.public_error_code
               FROM market_sources s
               LEFT JOIN market_source_policy_heads h ON h.source_id=s.id
               LEFT JOIN market_source_policy_revisions p
                 ON p.source_id=h.source_id AND p.id=h.revision_id
                AND p.revision=h.revision AND p.content_hash=h.content_hash
               LEFT JOIN market_source_refresh_states rs ON rs.source_id=s.id
               WHERE s.id=%s AND s.status='active'""",
            (source_id,),
        )
        return None if row is None else self._decode_source_row(row)

    def _decode_source_row(self, row):
        value = dict(row)
        value["public_config"] = _json_value(value.pop("public_config_json"))
        value["policy"] = self._policy_from_row(value)
        return value

    async def update_schedule(
        self,
        session,
        *,
        source_id: str,
        revision_id: str,
        expected_revision: int,
        enabled: bool,
        interval_minutes: int,
        now_ms: int,
    ):
        current = await session.fetchone(
            """SELECT s.id,s.status,p.id AS policy_revision_id,
                      p.revision AS policy_revision,p.policy_status,
                      p.policy_version,p.checked_at,p.evidence_url,
                      p.evidence_hash,p.allowed_origins_json,
                      p.path_prefixes_json,p.enabled,p.interval_minutes,
                      p.next_run_at,p.content_hash AS policy_hash,
                      rs.public_error_code
               FROM market_sources s
               LEFT JOIN market_source_policy_heads h ON h.source_id=s.id
               LEFT JOIN market_source_policy_revisions p
                 ON p.source_id=h.source_id AND p.id=h.revision_id
                AND p.revision=h.revision AND p.content_hash=h.content_hash
               LEFT JOIN market_source_refresh_states rs ON rs.source_id=s.id
               WHERE s.id=%s FOR UPDATE""",
            (source_id,),
        )
        if current is None or current["status"] != "active":
            raise MarketSourceNotFound()
        if current["policy_revision_id"] is None:
            raise MarketSourceFailure("MARKET_POLICY_MISSING")

        replay = await session.fetchone(
            """SELECT revision,policy_status,enabled,interval_minutes,
                      next_run_at
               FROM market_source_policy_revisions
               WHERE source_id=%s AND id=%s""",
            (source_id, revision_id),
        )
        if replay is not None:
            if (
                int(replay["revision"]) != expected_revision + 1
                or bool(replay["enabled"]) is not enabled
                or int(replay["interval_minutes"]) != interval_minutes
            ):
                raise MarketSourceConflict()
            return {
                "source_id": source_id,
                "revision": int(replay["revision"]),
                "enabled": bool(replay["enabled"]),
                "interval_minutes": int(replay["interval_minutes"]),
                "next_run_at": replay["next_run_at"],
                "policy_status": replay["policy_status"],
                "recovery_reason": None,
            }

        if enabled and current["policy_status"] != "verified_public":
            raise MarketSourceFailure("MARKET_POLICY_NOT_VERIFIED")
        if int(current["policy_revision"]) != expected_revision:
            raise MarketSourceConflict()

        current_policy = self._policy_from_row(current)
        if current_policy is None:
            raise MarketSourceFailure("MARKET_POLICY_MISSING")
        if enabled:
            if canonical_hash(current_policy) != current["policy_hash"]:
                raise MarketSourceFailure("MARKET_POLICY_HASH_INVALID")
            policy_age = now_ms - current_policy.checked_at
            if not -5 * 60 * 1000 <= policy_age <= 30 * 24 * 60 * 60 * 1000:
                raise MarketSourceFailure("MARKET_POLICY_EXPIRED")
        updated_policy = SourcePolicy(
            status=current_policy.status,
            checkedAt=current_policy.checked_at,
            evidenceURL=current_policy.evidence_url,
            evidenceHash=current_policy.evidence_hash,
            allowedOrigins=current_policy.allowed_origins,
            pathPrefixes=current_policy.path_prefixes,
            requestIntervalSeconds=interval_minutes * 60,
            policyVersion=current_policy.policy_version,
            enabled=enabled,
        )
        revision = expected_revision + 1
        next_run_at = now_ms if enabled else None
        content_hash = canonical_hash(updated_policy)
        await session.execute(
            """INSERT INTO market_source_policy_revisions
               (id,source_id,revision,policy_status,policy_version,checked_at,
                evidence_url,evidence_hash,allowed_origins_json,
                path_prefixes_json,enabled,interval_minutes,next_run_at,
                content_hash,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                revision_id,
                source_id,
                revision,
                updated_policy.status,
                updated_policy.policy_version,
                updated_policy.checked_at,
                updated_policy.evidence_url,
                updated_policy.evidence_hash,
                canonical_json(list(updated_policy.allowed_origins)),
                canonical_json(list(updated_policy.path_prefixes)),
                int(updated_policy.enabled),
                interval_minutes,
                next_run_at,
                content_hash,
                now_ms,
            ),
        )
        changed = await session.execute(
            """UPDATE market_source_policy_heads
               SET revision_id=%s,revision=%s,content_hash=%s,updated_at=%s
               WHERE source_id=%s AND revision=%s""",
            (
                revision_id,
                revision,
                content_hash,
                now_ms,
                source_id,
                expected_revision,
            ),
        )
        if changed != 1:
            raise MarketSourceConflict()
        changed = await session.execute(
            """UPDATE market_source_refresh_states
               SET next_run_at=%s,updated_at=%s WHERE source_id=%s""",
            (next_run_at, now_ms, source_id),
        )
        if changed != 1:
            raise MarketSourceConflict()
        return {
            "source_id": source_id,
            "revision": revision,
            "enabled": enabled,
            "interval_minutes": interval_minutes,
            "next_run_at": next_run_at,
            "policy_status": updated_policy.status,
            "recovery_reason": None,
        }

    async def list_due_schedules(
        self,
        session,
        *,
        now_ms: int,
        limit: int,
    ):
        rows = await session.fetchall(
            """SELECT s.id AS source_id,rs.next_run_at
               FROM market_sources s
               JOIN market_source_policy_heads h ON h.source_id=s.id
               JOIN market_source_policy_revisions p
                 ON p.source_id=h.source_id AND p.id=h.revision_id
                AND p.revision=h.revision AND p.content_hash=h.content_hash
               JOIN market_source_refresh_states rs ON rs.source_id=s.id
               WHERE s.status='active' AND p.policy_status='verified_public'
                 AND p.enabled=1 AND rs.next_run_at IS NOT NULL
                 AND rs.next_run_at<=%s
               ORDER BY rs.next_run_at,s.id LIMIT %s""",
            (now_ms, limit),
        )
        return tuple(dict(row) for row in rows)

    async def next_scheduled_run(self, session):
        row = await session.fetchone(
            """SELECT MIN(rs.next_run_at) AS next_run_at
               FROM market_sources s
               JOIN market_source_policy_heads h ON h.source_id=s.id
               JOIN market_source_policy_revisions p
                 ON p.source_id=h.source_id AND p.id=h.revision_id
                AND p.revision=h.revision AND p.content_hash=h.content_hash
               JOIN market_source_refresh_states rs ON rs.source_id=s.id
               WHERE s.status='active' AND p.policy_status='verified_public'
                 AND p.enabled=1 AND rs.next_run_at IS NOT NULL"""
        )
        return None if row is None else row["next_run_at"]

    async def reserve_refresh(
        self,
        session,
        *,
        source_id: str,
        idempotency_key: str,
        request_hash: str,
        input_manifest_hash: str,
        now_ms: int,
        enforce_cooldown: bool,
        scheduled: bool = False,
    ):
        source = await session.fetchone(
            """SELECT s.id,s.stable_key,s.adapter_key,s.display_name,
                      s.public_config_json,s.status,
                      p.id AS policy_revision_id,p.revision AS policy_revision,
                      p.policy_status,p.policy_version,p.checked_at,
                      p.evidence_url,p.evidence_hash,p.allowed_origins_json,
                      p.path_prefixes_json,p.enabled,p.interval_minutes,
                      p.content_hash AS policy_hash
               FROM market_sources s
               LEFT JOIN market_source_policy_heads h ON h.source_id=s.id
               LEFT JOIN market_source_policy_revisions p
                 ON p.source_id=h.source_id AND p.id=h.revision_id
                AND p.revision=h.revision AND p.content_hash=h.content_hash
               WHERE s.id=%s AND s.status='active' FOR UPDATE""",
            (source_id,),
        )
        if source is None:
            raise MarketSourceNotFound()
        if source["policy_revision_id"] is None:
            raise MarketSourceFailure("MARKET_POLICY_MISSING")
        input_manifest_hash = canonical_hash(
            {
                "sourceId": source_id,
                "adapterKey": source["adapter_key"],
                "publicConfig": _json_value(source["public_config_json"]),
                "policyRevision": source["policy_revision"],
                "policyHash": source["policy_hash"],
                "requestHash": request_hash,
            }
        )

        existing = await session.fetchone(
            """SELECT id,request_hash,status,snapshot_id,public_error_code
               FROM market_refresh_requests
               WHERE source_id=%s AND idempotency_key=%s FOR UPDATE""",
            (source_id, idempotency_key),
        )
        if existing is not None:
            if existing["request_hash"] != request_hash:
                raise MarketSourceConflict()
            if existing["status"] == "succeeded":
                snapshot = await self.get_snapshot(
                    session,
                    source_id,
                    existing["snapshot_id"],
                )
                return {"kind": "succeeded", "snapshot": snapshot}
            if existing["status"] in {"failed", "outcome_unknown"}:
                raise MarketSourceFailure(existing["public_error_code"])

        state = await session.fetchone(
            """SELECT refresh_status,lease_owner,lease_expires_at,
                      last_attempted_at,last_succeeded_at,last_snapshot_id,
                      next_run_at
               FROM market_source_refresh_states
               WHERE source_id=%s FOR UPDATE""",
            (source_id,),
        )
        if state is None:
            raise RuntimeError("market source refresh state is unavailable")

        if scheduled and (
            source["policy_status"] != "verified_public"
            or not bool(source["enabled"])
            or state["next_run_at"] is None
            or state["next_run_at"] > now_ms
        ):
            return {"kind": "skipped", "status": "not-due"}

        lease_is_live = bool(
            state["refresh_status"] == "leased"
            and state["lease_owner"] is not None
            and state["lease_expires_at"] is not None
            and state["lease_expires_at"] > now_ms
        )
        if lease_is_live:
            if scheduled:
                return {"kind": "skipped", "status": "lease-live"}
            raise MarketSourceFailure("MARKET_REFRESH_IN_PROGRESS")

        recovered_expired_lease = False
        if state["refresh_status"] == "leased":
            recovered_expired_lease = True
            expired_owner = state["lease_owner"]
            if expired_owner is not None:
                await session.execute(
                    """UPDATE market_refresh_requests
                       SET status='outcome_unknown',
                           public_error_code='MARKET_REFRESH_LEASE_EXPIRED',
                           completed_at=%s
                       WHERE id=%s AND source_id=%s AND status='running'""",
                    (now_ms, expired_owner, source_id),
                )
            await session.execute(
                """UPDATE market_source_refresh_states
                   SET refresh_status='idle',lease_owner=NULL,
                       lease_expires_at=NULL,
                       public_error_code='MARKET_REFRESH_LEASE_EXPIRED',
                       updated_at=%s
                   WHERE source_id=%s""",
                (now_ms, source_id),
            )
            if (
                existing is not None
                and existing["status"] == "running"
                and existing["id"] == expired_owner
            ):
                return {
                    "kind": "rejected",
                    "code": "MARKET_REFRESH_LEASE_EXPIRED",
                }

        if existing is not None:
            await session.execute(
                """UPDATE market_refresh_requests
                   SET status='outcome_unknown',
                       public_error_code='MARKET_REFRESH_LEASE_EXPIRED',
                       completed_at=%s
                   WHERE id=%s AND source_id=%s AND status='running'""",
                (now_ms, existing["id"], source_id),
            )
            await session.execute(
                """UPDATE market_source_refresh_states
                   SET public_error_code='MARKET_REFRESH_LEASE_EXPIRED',
                       updated_at=%s
                   WHERE source_id=%s""",
                (now_ms, source_id),
            )
            return {
                "kind": "rejected",
                "code": "MARKET_REFRESH_LEASE_EXPIRED",
            }

        cooldown_ms = int(source["interval_minutes"]) * 60 * 1000
        if (
            enforce_cooldown
            and not scheduled
            and state["last_attempted_at"] is not None
            and now_ms < state["last_attempted_at"] + cooldown_ms
        ):
            if recovered_expired_lease:
                return {
                    "kind": "rejected",
                    "code": "MARKET_REFRESH_COOLDOWN",
                }
            raise MarketSourceFailure("MARKET_REFRESH_COOLDOWN")

        request_id = canonical_hash(
            {
                "sourceId": source_id,
                "idempotencyKey": idempotency_key,
                "requestHash": request_hash,
            }
        )[:32]
        request_id = (
            f"{request_id[:8]}-{request_id[8:12]}-{request_id[12:16]}-"
            f"{request_id[16:20]}-{request_id[20:32]}"
        )
        await session.execute(
            """INSERT INTO market_refresh_requests
               (id,source_id,idempotency_key,request_hash,policy_revision,
                input_manifest_hash,status,snapshot_id,result_hash,
                public_error_code,created_at,completed_at)
               VALUES (%s,%s,%s,%s,%s,%s,'running',NULL,NULL,NULL,%s,NULL)""",
            (
                request_id,
                source_id,
                idempotency_key,
                request_hash,
                source["policy_revision"],
                input_manifest_hash,
                now_ms,
            ),
        )
        last_attempted_at = (
            now_ms if enforce_cooldown else state["last_attempted_at"]
        )
        changed = await session.execute(
            """UPDATE market_source_refresh_states
               SET refresh_status='leased',lease_owner=%s,lease_expires_at=%s,
                   last_attempted_at=%s,updated_at=%s
               WHERE source_id=%s AND refresh_status='idle'
                     AND lease_owner IS NULL""",
            (
                request_id,
                now_ms + _REFRESH_LEASE_MS,
                last_attempted_at,
                now_ms,
                source_id,
            ),
        )
        if changed != 1:
            raise MarketSourceConflict()
        decoded = self._decode_source_row(source)
        return {
            "kind": "reserved",
            "request_id": request_id,
            "source": decoded,
            "scheduled_interval_minutes": (
                int(source["interval_minutes"]) if scheduled else None
            ),
        }

    async def _snapshot_summary(self, session, source_id: str, snapshot_id: str):
        return await session.fetchone(
            """SELECT id,source_id,captured_at,platform,ranking_name,category,
                      source_url,content_hash,entry_count
               FROM market_snapshots WHERE source_id=%s AND id=%s""",
            (source_id, snapshot_id),
        )

    async def publish_snapshot(
        self,
        session,
        *,
        request_id: str,
        source_id: str,
        snapshot,
        snapshot_id: str,
        snapshot_hash: str,
        entry_ids: tuple[str, ...],
        entry_hashes: tuple[str, ...],
        manifest_id: str,
        manifest: dict,
        manifest_hash: str,
        adapter_version: str,
        policy_revision_id: str,
        policy_revision: int,
        policy_hash: str,
        completed_at: int,
        next_run_at: int | None = None,
    ):
        source = await session.fetchone(
            """SELECT id,status FROM market_sources
               WHERE id=%s FOR UPDATE""",
            (source_id,),
        )
        if source is None:
            raise MarketSourceConflict()
        current_head = await session.fetchone(
            """SELECT revision_id,revision,content_hash
               FROM market_source_policy_heads
               WHERE source_id=%s FOR UPDATE""",
            (source_id,),
        )
        request = await session.fetchone(
            """SELECT status,public_error_code FROM market_refresh_requests
               WHERE id=%s AND source_id=%s FOR UPDATE""",
            (request_id, source_id),
        )
        if request is None:
            raise MarketSourceConflict()
        state = await session.fetchone(
            """SELECT refresh_status,lease_owner,lease_expires_at
               FROM market_source_refresh_states
               WHERE source_id=%s FOR UPDATE""",
            (source_id,),
        )
        if state is None:
            raise MarketSourceConflict()
        if request["status"] != "running":
            if (
                request["status"] == "outcome_unknown"
                and request["public_error_code"]
                == "MARKET_REFRESH_LEASE_EXPIRED"
            ):
                return {
                    "kind": "rejected",
                    "code": "MARKET_REFRESH_LEASE_EXPIRED",
                }
            raise MarketSourceConflict()

        holder_owns_lease = bool(
            state["refresh_status"] == "leased"
            and state["lease_owner"] == request_id
        )
        holder_lease_is_live = bool(
            holder_owns_lease
            and state["lease_expires_at"] is not None
            and state["lease_expires_at"] > completed_at
        )
        if not holder_lease_is_live:
            changed = await session.execute(
                """UPDATE market_refresh_requests
                   SET status='outcome_unknown',snapshot_id=NULL,
                       result_hash=NULL,
                       public_error_code='MARKET_REFRESH_LEASE_EXPIRED',
                       completed_at=%s
                   WHERE id=%s AND source_id=%s AND status='running'""",
                (completed_at, request_id, source_id),
            )
            if changed != 1:
                raise MarketSourceConflict()
            if holder_owns_lease:
                await session.execute(
                    """UPDATE market_source_refresh_states
                       SET refresh_status='idle',lease_owner=NULL,
                           lease_expires_at=NULL,
                           public_error_code='MARKET_REFRESH_LEASE_EXPIRED',
                           updated_at=%s
                       WHERE source_id=%s AND refresh_status='leased'
                             AND lease_owner=%s""",
                    (completed_at, source_id, request_id),
                )
            return {
                "kind": "rejected",
                "code": "MARKET_REFRESH_LEASE_EXPIRED",
            }
        publication_inputs_match = bool(
            source["status"] == "active"
            and current_head is not None
            and current_head["revision_id"] == policy_revision_id
            and current_head["revision"] == policy_revision
            and current_head["content_hash"] == policy_hash
        )
        if not publication_inputs_match:
            changed = await session.execute(
                """UPDATE market_refresh_requests
                   SET status='failed',snapshot_id=NULL,result_hash=NULL,
                       public_error_code='MARKET_SOURCE_CONFLICT',
                       completed_at=%s
                   WHERE id=%s AND source_id=%s AND status='running'""",
                (completed_at, request_id, source_id),
            )
            if changed != 1:
                raise MarketSourceConflict()
            changed = await session.execute(
                """UPDATE market_source_refresh_states
                   SET refresh_status='idle',lease_owner=NULL,
                       lease_expires_at=NULL,
                       public_error_code='MARKET_SOURCE_CONFLICT',
                       updated_at=%s
                   WHERE source_id=%s AND refresh_status='leased'
                         AND lease_owner=%s""",
                (completed_at, source_id, request_id),
            )
            if changed != 1:
                raise MarketSourceConflict()
            return {
                "kind": "rejected",
                "code": "MARKET_SOURCE_CONFLICT",
            }
        existing = await session.fetchone(
            """SELECT id FROM market_snapshots
               WHERE source_id=%s AND content_hash=%s""",
            (source_id, snapshot_hash),
        )
        published_id = snapshot_id
        if existing is None:
            await session.execute(
                """INSERT INTO market_snapshots
                   (id,source_id,captured_at,platform,ranking_name,category,
                    source_url,content_hash,entry_count,created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    snapshot_id,
                    source_id,
                    snapshot.captured_at,
                    snapshot.platform,
                    snapshot.ranking_name,
                    snapshot.category,
                    snapshot.source_url,
                    snapshot_hash,
                    len(snapshot.entries),
                    completed_at,
                ),
            )
            for entry, entry_id, entry_hash in zip(
                snapshot.entries,
                entry_ids,
                entry_hashes,
                strict=True,
            ):
                await session.execute(
                    """INSERT INTO market_snapshot_entries
                       (id,source_id,snapshot_id,rank_number,title,author,
                        category,work_url,public_metrics_json,content_hash,
                        created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        entry_id,
                        source_id,
                        snapshot_id,
                        entry.rank,
                        entry.title,
                        entry.author,
                        entry.category,
                        entry.work_url,
                        canonical_json(dict(entry.public_metrics)),
                        entry_hash,
                        completed_at,
                    ),
                )
            await session.execute(
                """INSERT INTO market_snapshot_manifests
                   (id,source_id,snapshot_id,snapshot_hash,policy_revision_id,
                    policy_revision,policy_hash,adapter_version,manifest_json,
                    manifest_hash,created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    manifest_id,
                    source_id,
                    snapshot_id,
                    snapshot_hash,
                    policy_revision_id,
                    policy_revision,
                    policy_hash,
                    adapter_version,
                    canonical_json(manifest),
                    manifest_hash,
                    completed_at,
                ),
            )
        else:
            published_id = existing["id"]

        changed = await session.execute(
            """UPDATE market_refresh_requests
               SET status='succeeded',snapshot_id=%s,result_hash=%s,
                   public_error_code=NULL,completed_at=%s
               WHERE id=%s AND source_id=%s AND status='running'""",
            (
                published_id,
                snapshot_hash,
                completed_at,
                request_id,
                source_id,
            ),
        )
        if changed != 1:
            raise MarketSourceConflict()
        changed = await session.execute(
            """UPDATE market_source_refresh_states
               SET last_snapshot_id=%s,refresh_status='idle',lease_owner=NULL,
                   lease_expires_at=NULL,last_succeeded_at=%s,
                   next_run_at=COALESCE(%s,next_run_at),
                   public_error_code=NULL,updated_at=%s
               WHERE source_id=%s AND refresh_status='leased'
                     AND lease_owner=%s""",
            (
                published_id,
                completed_at,
                next_run_at,
                completed_at,
                source_id,
                request_id,
            ),
        )
        if changed != 1:
            raise MarketSourceConflict()
        return await self.get_snapshot(session, source_id, published_id)

    async def fail_refresh(
        self,
        session,
        *,
        request_id: str,
        source_id: str,
        public_error_code: str,
        completed_at: int,
        next_run_at: int | None = None,
    ) -> None:
        source = await session.fetchone(
            "SELECT id FROM market_sources WHERE id=%s FOR UPDATE",
            (source_id,),
        )
        if source is None:
            raise MarketSourceConflict()
        state = await session.fetchone(
            """SELECT refresh_status,lease_owner,lease_expires_at
               FROM market_source_refresh_states
               WHERE source_id=%s FOR UPDATE""",
            (source_id,),
        )
        if (
            state is None
            or state["refresh_status"] != "leased"
            or state["lease_owner"] != request_id
            or state["lease_expires_at"] is None
            or state["lease_expires_at"] <= completed_at
        ):
            raise MarketSourceConflict()
        changed = await session.execute(
            """UPDATE market_refresh_requests
               SET status='failed',public_error_code=%s,completed_at=%s
               WHERE id=%s AND source_id=%s AND status='running'""",
            (public_error_code, completed_at, request_id, source_id),
        )
        if changed != 1:
            raise MarketSourceConflict()
        changed = await session.execute(
            """UPDATE market_source_refresh_states
               SET refresh_status='idle',lease_owner=NULL,
                   lease_expires_at=NULL,
                   next_run_at=COALESCE(%s,next_run_at),
                   public_error_code=%s,updated_at=%s
               WHERE source_id=%s AND refresh_status='leased'
                     AND lease_owner=%s""",
            (
                next_run_at,
                public_error_code,
                completed_at,
                source_id,
                request_id,
            ),
        )
        if changed != 1:
            raise MarketSourceConflict()

    async def abandon_refresh(
        self,
        session,
        *,
        request_id: str,
        source_id: str,
        public_error_code: str,
        completed_at: int,
        next_run_at: int | None = None,
    ) -> None:
        source = await session.fetchone(
            "SELECT id FROM market_sources WHERE id=%s FOR UPDATE",
            (source_id,),
        )
        if source is None:
            raise MarketSourceConflict()
        request = await session.fetchone(
            """SELECT status FROM market_refresh_requests
               WHERE id=%s AND source_id=%s FOR UPDATE""",
            (request_id, source_id),
        )
        state = await session.fetchone(
            """SELECT refresh_status,lease_owner,lease_expires_at
               FROM market_source_refresh_states
               WHERE source_id=%s FOR UPDATE""",
            (source_id,),
        )
        if (
            request is None
            or request["status"] != "running"
            or state is None
            or state["refresh_status"] != "leased"
            or state["lease_owner"] != request_id
            or state["lease_expires_at"] is None
            or state["lease_expires_at"] <= completed_at
        ):
            raise MarketSourceConflict()
        changed = await session.execute(
            """UPDATE market_refresh_requests
               SET status='outcome_unknown',snapshot_id=NULL,
                   result_hash=NULL,public_error_code=%s,completed_at=%s
               WHERE id=%s AND source_id=%s AND status='running'""",
            (
                public_error_code,
                completed_at,
                request_id,
                source_id,
            ),
        )
        if changed != 1:
            raise MarketSourceConflict()
        changed = await session.execute(
            """UPDATE market_source_refresh_states
               SET refresh_status='idle',lease_owner=NULL,
                   lease_expires_at=NULL,
                   next_run_at=COALESCE(%s,next_run_at),
                   public_error_code=%s,updated_at=%s
               WHERE source_id=%s AND refresh_status='leased'
                     AND lease_owner=%s""",
            (
                next_run_at,
                public_error_code,
                completed_at,
                source_id,
                request_id,
            ),
        )
        if changed != 1:
            raise MarketSourceConflict()

    async def list_snapshots(self, session, source_id: str):
        return tuple(
            await session.fetchall(
                """SELECT id,source_id,captured_at,platform,ranking_name,
                          category,source_url,content_hash,entry_count
                   FROM market_snapshots WHERE source_id=%s
                   ORDER BY captured_at DESC,id DESC LIMIT 100""",
                (source_id,),
            )
        )

    async def get_snapshot(self, session, source_id: str, snapshot_id: str):
        snapshot = await self._snapshot_summary(session, source_id, snapshot_id)
        if snapshot is None:
            return None
        rows = await session.fetchall(
            """SELECT rank_number,title,author,category,work_url,
                      public_metrics_json
               FROM market_snapshot_entries
               WHERE source_id=%s AND snapshot_id=%s
               ORDER BY rank_number ASC LIMIT 100""",
            (source_id, snapshot_id),
        )
        value = dict(snapshot)
        value["entries"] = tuple(
            {
                "rank": row["rank_number"],
                "title": row["title"],
                "author": row["author"],
                "category": row["category"],
                "work_url": row["work_url"],
                "public_metrics": _json_value(row["public_metrics_json"]),
            }
            for row in rows
        )
        return value
