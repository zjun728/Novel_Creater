"""Session-bound persistence for the global Topic Center authority."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping

from backend.domain.json_contracts import canonical_hash
from backend.domain.topics import TopicEvidenceRef, TopicFailure


def _page(offset: int, limit: int) -> tuple[int, int]:
    return max(0, int(offset)), min(100, max(1, int(limit)))


def _json_object(value: object, field: str) -> dict:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"invalid {field}")
    return decoded


def _decode_json_fields(row: Mapping, *fields: str) -> dict:
    decoded = dict(row)
    for field in fields:
        value = decoded.pop(field, None)
        public_name = field.removesuffix("_json")
        decoded[public_name] = (
            None if value is None else _json_object(value, field)
        )
    return decoded


class TopicRepository:
    """Every method uses the connection or transaction supplied by its caller."""

    async def list_discussions(
        self,
        session,
        *,
        offset: int = 0,
        limit: int = 50,
    ):
        offset, limit = _page(offset, limit)
        rows = await session.fetchall(
            """SELECT id,title,status,created_at,updated_at
               FROM topic_discussions
               ORDER BY updated_at DESC,id DESC
               LIMIT %s OFFSET %s""",
            (limit, offset),
        )
        return tuple(dict(row) for row in rows)

    async def read_discussion(self, session, discussion_id: str):
        discussion = await session.fetchone(
            """SELECT id,title,status,created_at,updated_at
               FROM topic_discussions WHERE id=%s""",
            (discussion_id,),
        )
        if discussion is None:
            return None
        messages = await session.fetchall(
            """SELECT id,discussion_id,sequence_number,role,content_text,
                      content_hash,created_at
               FROM topic_discussion_messages
               WHERE discussion_id=%s
               ORDER BY sequence_number ASC""",
            (discussion_id,),
        )
        requests = await session.fetchall(
            """SELECT id,discussion_id,idempotency_key,request_hash,
                      input_manifest_json,input_manifest_hash,provider_id,
                      provider_name_snapshot,model_name_snapshot,
                      provider_config_hash,status,user_message_id,
                      assistant_message_id,result_json,result_hash,
                      public_error_code,created_at,completed_at
               FROM topic_discussion_requests
               WHERE discussion_id=%s
               ORDER BY created_at ASC,id ASC""",
            (discussion_id,),
        )
        return {
            "discussion": dict(discussion),
            "messages": tuple(dict(row) for row in messages),
            "requests": tuple(
                _decode_json_fields(row, "input_manifest_json", "result_json")
                for row in requests
            ),
        }

    async def list_directions(
        self,
        session,
        *,
        offset: int = 0,
        limit: int = 50,
    ):
        offset, limit = _page(offset, limit)
        rows = await session.fetchall(
            """SELECT d.id,d.current_version,d.created_at,d.updated_at,
                      v.id AS version_id,v.payload_json,v.content_hash,
                      v.discussion_id,v.basis_json,v.basis_hash,
                      v.created_at AS version_created_at
               FROM topic_directions d
               JOIN topic_direction_versions v
                 ON v.direction_id=d.id AND v.version=d.current_version
               ORDER BY d.updated_at DESC,d.id DESC
               LIMIT %s OFFSET %s""",
            (limit, offset),
        )
        return tuple(
            _decode_json_fields(row, "payload_json", "basis_json")
            for row in rows
        )
    async def read_direction(self, session, direction_id: str):
        direction = await session.fetchone(
            """SELECT id,current_version,created_at,updated_at
               FROM topic_directions WHERE id=%s""",
            (direction_id,),
        )
        if direction is None:
            return None
        versions = await session.fetchall(
            """SELECT id,direction_id,version,payload_json,content_hash,
                      discussion_id,basis_json,basis_hash,idempotency_key,
                      request_hash,created_at
               FROM topic_direction_versions
               WHERE direction_id=%s
               ORDER BY version DESC""",
            (direction_id,),
        )
        return {
            "direction": dict(direction),
            "versions": tuple(
                _decode_json_fields(row, "payload_json", "basis_json")
                for row in versions
            ),
        }

    async def list_candidates(
        self,
        session,
        *,
        status: str = "active",
        offset: int = 0,
        limit: int = 50,
    ):
        if status not in {"active", "archived"}:
            raise ValueError("invalid candidate status")
        offset, limit = _page(offset, limit)
        rows = await session.fetchall(
            """SELECT c.id,c.status,c.current_version,c.created_at,c.updated_at,
                      v.id AS version_id,v.payload_json,v.content_hash,
                      v.discussion_id,v.basis_json,v.basis_hash,
                      v.created_at AS version_created_at
               FROM topic_candidates c
               JOIN topic_candidate_versions v
                 ON v.candidate_id=c.id AND v.version=c.current_version
               WHERE c.status=%s
               ORDER BY c.updated_at DESC,c.id DESC
               LIMIT %s OFFSET %s""",
            (status, limit, offset),
        )
        return tuple(
            _decode_json_fields(row, "payload_json", "basis_json")
            for row in rows
        )

    async def read_candidate(self, session, candidate_id: str):
        candidate = await session.fetchone(
            """SELECT id,status,current_version,created_at,updated_at
               FROM topic_candidates WHERE id=%s""",
            (candidate_id,),
        )
        if candidate is None:
            return None
        versions = await session.fetchall(
            """SELECT id,candidate_id,version,payload_json,content_hash,
                      discussion_id,basis_json,basis_hash,idempotency_key,
                      request_hash,created_at
               FROM topic_candidate_versions
               WHERE candidate_id=%s
               ORDER BY version DESC""",
            (candidate_id,),
        )
        return {
            "candidate": dict(candidate),
            "versions": tuple(
                _decode_json_fields(row, "payload_json", "basis_json")
                for row in versions
            ),
        }

    async def lock_discussion(self, session, discussion_id: str):
        return await session.fetchone(
            """SELECT id,title,status,created_at,updated_at
               FROM topic_discussions WHERE id=%s FOR UPDATE""",
            (discussion_id,),
        )

    async def lock_message(
        self,
        session,
        *,
        discussion_id: str,
        message_id: str,
    ):
        return await session.fetchone(
            """SELECT id,discussion_id,sequence_number,role,content_text,
                      content_hash,created_at
               FROM topic_discussion_messages
               WHERE discussion_id=%s AND id=%s FOR UPDATE""",
            (discussion_id, message_id),
        )

    async def lock_direction(self, session, direction_id: str):
        return await session.fetchone(
            """SELECT id,current_version,created_at,updated_at
               FROM topic_directions WHERE id=%s FOR UPDATE""",
            (direction_id,),
        )

    async def lock_candidate(self, session, candidate_id: str):
        return await session.fetchone(
            """SELECT id,status,current_version,created_at,updated_at
               FROM topic_candidates WHERE id=%s FOR UPDATE""",
            (candidate_id,),
        )

    async def lock_direction_version(
        self,
        session,
        *,
        direction_id: str,
        version: int,
        content_hash: str,
    ):
        row = await session.fetchone(
            """SELECT id,direction_id,version,payload_json,content_hash,
                      discussion_id,basis_json,basis_hash,created_at
               FROM topic_direction_versions
               WHERE direction_id=%s AND version=%s AND content_hash=%s
               FOR UPDATE""",
            (direction_id, version, content_hash),
        )
        return (
            None
            if row is None
            else _decode_json_fields(row, "payload_json", "basis_json")
        )

    async def lock_candidate_version(
        self,
        session,
        *,
        candidate_id: str,
        version: int,
        content_hash: str,
    ):
        row = await session.fetchone(
            """SELECT id,candidate_id,version,payload_json,content_hash,
                      discussion_id,basis_json,basis_hash,created_at
               FROM topic_candidate_versions
               WHERE candidate_id=%s AND version=%s AND content_hash=%s
               FOR UPDATE""",
            (candidate_id, version, content_hash),
        )
        return (
            None
            if row is None
            else _decode_json_fields(row, "payload_json", "basis_json")
        )

    async def lock_snapshot_evidence(
        self,
        session,
        refs: Iterable[TopicEvidenceRef],
    ):
        refs = tuple(refs)
        if not refs:
            return ()
        ordered_ids = tuple(sorted({ref.snapshot_id for ref in refs}))
        placeholders = ",".join("%s" for _ in ordered_ids)
        rows = await session.fetchall(
            f"""SELECT id,source_id,captured_at,platform,ranking_name,
                       category,source_url,content_hash,entry_count,created_at
                FROM market_snapshots
                WHERE id IN ({placeholders})
                ORDER BY id ASC FOR UPDATE""",
            ordered_ids,
        )
        by_id = {row["id"]: dict(row) for row in rows}
        resolved = []
        for ref in refs:
            row = by_id.get(ref.snapshot_id)
            if row is None or row.get("content_hash") != ref.content_hash:
                raise TopicFailure("TOPIC_NOT_FOUND")
            resolved.append(row)
        return tuple(resolved)

    async def lock_generation_inputs(self, session):
        row = await session.fetchone(
            """SELECT a.revision AS settings_revision,
                      p.id AS provider_id,p.name AS provider_name,
                      p.provider_type,p.model_name,p.base_url,p.api_key,
                      p.enabled,p.lifecycle_status,p.max_context_tokens,
                      p.max_output_tokens,p.temperature,p.top_p,p.supports_json
               FROM application_settings a
               LEFT JOIN provider_profiles p ON p.id=a.fallback_provider_id
               WHERE a.singleton_id=1 FOR UPDATE"""
        )
        if row is None or row.get("provider_id") is None:
            return None
        runtime = dict(row)
        base_url_hash = hashlib.sha256(
            str(runtime.get("base_url") or "").encode("utf-8")
        ).hexdigest()
        generation = {
            "maxContextTokens": int(runtime["max_context_tokens"]),
            "maxOutputTokens": int(runtime["max_output_tokens"]),
            "temperature": str(runtime["temperature"]),
            "topP": str(runtime["top_p"]),
            "supportsJson": bool(runtime["supports_json"]),
        }
        public_config = {
            "providerType": runtime["provider_type"],
            "modelName": runtime["model_name"],
            "baseUrlHash": base_url_hash,
            "generation": generation,
        }
        manifest = {
            "settingsRevision": int(runtime["settings_revision"]),
            "providerId": runtime["provider_id"],
            "providerName": runtime["provider_name"],
            **public_config,
            "providerConfigHash": canonical_hash(public_config),
        }
        return {"runtime": runtime, "manifest": manifest}

    async def insert_discussion(self, session, row: Mapping) -> None:
        await session.execute(
            """INSERT INTO topic_discussions
               (id,title,status,created_at,updated_at)
               VALUES (%s,%s,%s,%s,%s)""",
            (
                row["id"], row["title"], row["status"],
                row["created_at"], row["updated_at"],
            ),
        )

    async def insert_message(self, session, row: Mapping) -> None:
        await session.execute(
            """INSERT INTO topic_discussion_messages
               (id,discussion_id,sequence_number,role,content_text,
                content_hash,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["id"], row["discussion_id"], row["sequence_number"],
                row["role"], row["content_text"], row["content_hash"],
                row["created_at"],
            ),
        )

    async def touch_discussion(
        self,
        session,
        *,
        discussion_id: str,
        updated_at: int,
    ) -> None:
        await session.execute(
            "UPDATE topic_discussions SET updated_at=%s WHERE id=%s",
            (updated_at, discussion_id),
        )

    async def lock_request_by_key(
        self,
        session,
        *,
        discussion_id: str,
        idempotency_key: str,
    ):
        row = await session.fetchone(
            """SELECT id,discussion_id,idempotency_key,request_hash,
                      input_manifest_json,input_manifest_hash,provider_id,
                      provider_name_snapshot,model_name_snapshot,
                      provider_config_hash,status,user_message_id,
                      assistant_message_id,result_json,result_hash,
                      public_error_code,created_at,completed_at
               FROM topic_discussion_requests
               WHERE discussion_id=%s AND idempotency_key=%s FOR UPDATE""",
            (discussion_id, idempotency_key),
        )
        return (
            None
            if row is None
            else _decode_json_fields(
                row,
                "input_manifest_json",
                "result_json",
            )
        )

    async def insert_request(self, session, row: Mapping) -> None:
        await session.execute(
            """INSERT INTO topic_discussion_requests
               (id,discussion_id,idempotency_key,request_hash,
                input_manifest_json,input_manifest_hash,provider_id,
                provider_name_snapshot,model_name_snapshot,
                provider_config_hash,status,user_message_id,
                assistant_message_id,result_json,result_hash,
                public_error_code,created_at,completed_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       NULL,NULL,NULL,NULL,%s,NULL)""",
            (
                row["id"], row["discussion_id"], row["idempotency_key"],
                row["request_hash"], row["input_manifest_json"],
                row["input_manifest_hash"], row.get("provider_id"),
                row.get("provider_name_snapshot"),
                row.get("model_name_snapshot"),
                row.get("provider_config_hash"), row["status"],
                row["user_message_id"], row["created_at"],
            ),
        )

    async def mark_request_running(self, session, request_id: str) -> bool:
        changed = await session.execute(
            """UPDATE topic_discussion_requests SET status='running'
               WHERE id=%s AND status='reserved'""",
            (request_id,),
        )
        return changed == 1

    async def complete_request(
        self,
        session,
        *,
        request_id: str,
        assistant_message_id: str,
        result_json: str,
        result_hash: str,
        completed_at: int,
    ) -> bool:
        changed = await session.execute(
            """UPDATE topic_discussion_requests
               SET status='succeeded',assistant_message_id=%s,
                   result_json=%s,result_hash=%s,completed_at=%s
               WHERE id=%s AND status='running'""",
            (
                assistant_message_id, result_json, result_hash,
                completed_at, request_id,
            ),
        )
        return changed == 1

    async def fail_request(
        self,
        session,
        *,
        request_id: str,
        status: str,
        public_error_code: str,
        completed_at: int,
    ) -> bool:
        if status not in {"failed", "outcome_unknown"}:
            raise ValueError("invalid terminal request status")
        changed = await session.execute(
            """UPDATE topic_discussion_requests
               SET status=%s,public_error_code=%s,completed_at=%s
               WHERE id=%s AND status IN ('reserved','running')""",
            (status, public_error_code, completed_at, request_id),
        )
        return changed == 1

    async def insert_direction_identity(self, session, row: Mapping) -> None:
        await session.execute(
            """INSERT INTO topic_directions
               (id,current_version,created_at,updated_at)
               VALUES (%s,%s,%s,%s)""",
            (
                row["id"], row["current_version"],
                row["created_at"], row["updated_at"],
            ),
        )

    async def insert_direction_version(self, session, row: Mapping) -> None:
        await session.execute(
            """INSERT INTO topic_direction_versions
               (id,direction_id,version,payload_json,content_hash,
                discussion_id,basis_json,basis_hash,idempotency_key,
                request_hash,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            tuple(
                row[key]
                for key in (
                    "id", "direction_id", "version", "payload_json",
                    "content_hash", "discussion_id", "basis_json",
                    "basis_hash", "idempotency_key", "request_hash",
                    "created_at",
                )
            ),
        )

    async def find_direction_version_by_key(
        self,
        session,
        idempotency_key: str,
    ):
        row = await session.fetchone(
            """SELECT id,direction_id,version,payload_json,content_hash,
                      discussion_id,basis_json,basis_hash,idempotency_key,
                      request_hash,created_at
               FROM topic_direction_versions
               WHERE idempotency_key=%s FOR UPDATE""",
            (idempotency_key,),
        )
        return (
            None
            if row is None
            else _decode_json_fields(row, "payload_json", "basis_json")
        )

    async def advance_direction(
        self,
        session,
        *,
        direction_id: str,
        expected_version: int,
        version: int,
        updated_at: int,
    ) -> bool:
        changed = await session.execute(
            """UPDATE topic_directions
               SET current_version=%s,updated_at=%s
               WHERE id=%s AND current_version=%s""",
            (version, updated_at, direction_id, expected_version),
        )
        return changed == 1

    async def insert_candidate_identity(self, session, row: Mapping) -> None:
        await session.execute(
            """INSERT INTO topic_candidates
               (id,status,current_version,created_at,updated_at)
               VALUES (%s,%s,%s,%s,%s)""",
            (
                row["id"], row["status"], row["current_version"],
                row["created_at"], row["updated_at"],
            ),
        )

    async def insert_candidate_version(self, session, row: Mapping) -> None:
        await session.execute(
            """INSERT INTO topic_candidate_versions
               (id,candidate_id,version,payload_json,content_hash,
                discussion_id,basis_json,basis_hash,idempotency_key,
                request_hash,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            tuple(
                row[key]
                for key in (
                    "id", "candidate_id", "version", "payload_json",
                    "content_hash", "discussion_id", "basis_json",
                    "basis_hash", "idempotency_key", "request_hash",
                    "created_at",
                )
            ),
        )

    async def find_candidate_version_by_key(
        self,
        session,
        idempotency_key: str,
    ):
        row = await session.fetchone(
            """SELECT id,candidate_id,version,payload_json,content_hash,
                      discussion_id,basis_json,basis_hash,idempotency_key,
                      request_hash,created_at
               FROM topic_candidate_versions
               WHERE idempotency_key=%s FOR UPDATE""",
            (idempotency_key,),
        )
        return (
            None
            if row is None
            else _decode_json_fields(row, "payload_json", "basis_json")
        )

    async def advance_candidate(
        self,
        session,
        *,
        candidate_id: str,
        expected_version: int,
        version: int,
        updated_at: int,
    ) -> bool:
        changed = await session.execute(
            """UPDATE topic_candidates
               SET current_version=%s,updated_at=%s
               WHERE id=%s AND current_version=%s AND status='active'""",
            (version, updated_at, candidate_id, expected_version),
        )
        return changed == 1

    async def archive_candidate(
        self,
        session,
        *,
        candidate_id: str,
        expected_version: int,
        updated_at: int,
    ) -> bool:
        changed = await session.execute(
            """UPDATE topic_candidates
               SET status='archived',updated_at=%s
               WHERE id=%s AND current_version=%s AND status='active'""",
            (updated_at, candidate_id, expected_version),
        )
        return changed == 1

    async def lock_handoff_by_key(self, session, idempotency_key: str):
        row = await session.fetchone(
            """SELECT id,candidate_id,candidate_version,candidate_hash,
                      idempotency_key,request_hash,project_id,seed_id,
                      seed_revision_id,seed_revision,seed_hash,created_at
               FROM topic_project_handoffs
               WHERE idempotency_key=%s FOR UPDATE""",
            (idempotency_key,),
        )
        return None if row is None else dict(row)

    async def insert_handoff(self, session, row: Mapping) -> None:
        await session.execute(
            """INSERT INTO topic_project_handoffs
               (id,candidate_id,candidate_version,candidate_hash,
                idempotency_key,request_hash,project_id,seed_id,
                seed_revision_id,seed_revision,seed_hash,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            tuple(
                row[key]
                for key in (
                    "id", "candidate_id", "candidate_version",
                    "candidate_hash", "idempotency_key", "request_hash",
                    "project_id", "seed_id", "seed_revision_id",
                    "seed_revision", "seed_hash", "created_at",
                )
            ),
        )
