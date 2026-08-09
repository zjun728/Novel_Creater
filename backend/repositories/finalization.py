"""Session-bound persistence for finalization preparation and review."""

from __future__ import annotations

from collections.abc import Mapping
import json

from backend.domain.finalization import change_set_payload
from backend.domain.json_contracts import canonical_json
from backend.repositories.project_lifecycle import lock_active_project


class FinalizationDataCorruption(RuntimeError):
    """Persisted finalization authority violates the closed contract."""


def _decoded_object(value: object, field_name: str) -> dict[str, object]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        raise FinalizationDataCorruption(
            f"persisted {field_name} is invalid"
        ) from None
    if not isinstance(decoded, dict):
        raise FinalizationDataCorruption(f"persisted {field_name} is invalid")
    return dict(decoded)


def _canonical_json_value(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class FinalizationRepository:
    async def lock_project(self, session, project_id: str):
        return await lock_active_project(session, project_id)

    async def lock_session(self, session, project_id: str, session_id: str):
        row = await session.fetchone(
            """SELECT id,project_id,planning_revision_id,planning_revision,
                      planning_hash,story_block_id,story_block_revision,
                      story_block_hash,chapter_outline_revision_id,
                      chapter_outline_revision,chapter_outline_hash,chapter_num,
                      expected_canon_revision,status,active_draft_operation_id,
                      finalized_at
                 FROM chapter_sessions
                WHERE project_id=%s AND id=%s FOR UPDATE""",
            (project_id, session_id),
        )
        return None if row is None else dict(row)

    async def lock_candidate(
        self,
        session,
        project_id: str,
        session_id: str,
        candidate_id: str,
    ):
        row = await session.fetchone(
            """SELECT id,project_id,chapter_session_id,working_draft_revision,
                      content,content_hash,basis_hash,provenance_json,created_at
                 FROM draft_candidates
                WHERE project_id=%s AND chapter_session_id=%s AND id=%s
                FOR UPDATE""",
            (project_id, session_id, candidate_id),
        )
        if row is None:
            return None
        result = dict(row)
        result["provenance"] = _decoded_object(
            result.pop("provenance_json", None), "Candidate provenance",
        )
        return result

    async def lock_current_authority(
        self,
        session,
        project_id: str,
        chapter_number: int,
    ):
        row = await session.fetchone(
            """SELECT projection.canon_revision_number AS canon_revision,
                      projection.projection_revision_number AS projection_revision,
                      projection.content_hash AS projection_hash,
                      planning.content_hash AS planning_hash,
                      outline.content_hash AS outline_hash,
                      planning.planning_revision_id,
                      planning.revision AS planning_revision,
                      outline.outline_revision_id,
                      outline.revision AS outline_revision
                 FROM projection_heads projection
                 JOIN project_planning_heads planning
                   ON planning.project_id=projection.project_id
                 JOIN project_chapter_outline_heads outline
                   ON outline.project_id=projection.project_id
                WHERE projection.project_id=%s AND outline.chapter_num=%s
                FOR UPDATE""",
            (project_id, chapter_number),
        )
        return None if row is None else dict(row)

    async def find_by_idempotency(
        self,
        session,
        project_id: str,
        session_id: str,
        idempotency_key: str,
    ):
        row = await session.fetchone(
            """SELECT * FROM finalization_change_sets
                WHERE project_id=%s AND chapter_session_id=%s
                  AND idempotency_key=%s""",
            (project_id, session_id, idempotency_key),
        )
        return None if row is None else dict(row)

    async def find_active(self, session, project_id: str, session_id: str):
        row = await session.fetchone(
            """SELECT * FROM finalization_change_sets
                WHERE project_id=%s AND chapter_session_id=%s
                  AND active_slot=1 FOR UPDATE""",
            (project_id, session_id),
        )
        return None if row is None else dict(row)

    async def insert_preparing_attempt(
        self,
        session,
        row: Mapping[str, object],
    ) -> None:
        await session.execute(
            """INSERT INTO finalization_change_sets
               (id,project_id,chapter_session_id,draft_candidate_id,
                quality_report_id,extraction_id,idempotency_key,
                request_fingerprint,active_slot,candidate_hash,
                expected_canon_revision,expected_planning_hash,
                expected_outline_hash,context_manifest_json,
                context_manifest_hash,status,current_revision,
                current_revision_hash,confirmed_revision,
                confirmed_revision_hash,created_at,updated_at,confirmed_at)
               VALUES (%s,%s,%s,%s,NULL,NULL,%s,%s,1,%s,%s,%s,%s,%s,%s,
                       'preparing',NULL,NULL,NULL,NULL,%s,%s,NULL)""",
            (
                row["id"], row["project_id"], row["chapter_session_id"],
                row["draft_candidate_id"], row["idempotency_key"],
                row["request_fingerprint"], row["candidate_hash"],
                row["expected_canon_revision"], row["expected_planning_hash"],
                row["expected_outline_hash"],
                canonical_json(dict(row["context_manifest"])),
                row["context_manifest_hash"], row["created_at"],
                row["updated_at"],
            ),
        )

    async def insert_quality_report(
        self,
        session,
        row: Mapping[str, object],
    ) -> None:
        await session.execute(
            """INSERT INTO candidate_quality_reports
               (id,project_id,chapter_session_id,draft_candidate_id,
                candidate_hash,expected_canon_revision,expected_planning_hash,
                expected_outline_hash,policy_version,context_manifest_hash,
                provider_id,provider_profile_revision,model_name_snapshot,status,
                deterministic_blocks_json,findings_json,content_hash,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["id"], row["project_id"], row["chapter_session_id"],
                row["draft_candidate_id"], row["candidate_hash"],
                row["expected_canon_revision"], row["expected_planning_hash"],
                row["expected_outline_hash"], row["policy_version"],
                row["context_manifest_hash"], row["provider_id"],
                row["provider_profile_revision"], row["model_name_snapshot"],
                row["status"], _canonical_json_value(row["deterministic_blocks"]),
                _canonical_json_value(row["findings"]),
                row["content_hash"], row["created_at"],
            ),
        )

    async def insert_change_set_revision(
        self,
        session,
        row: Mapping[str, object],
    ) -> None:
        await session.execute(
            """INSERT INTO finalization_change_set_revisions
               (id,project_id,change_set_id,revision,payload_json,content_hash,
                source,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["id"], row["project_id"], row["change_set_id"],
                row["revision"], canonical_json(change_set_payload(row["change_set"])),
                row["content_hash"], row["source"], row["created_at"],
            ),
        )

    async def publish_awaiting_author(
        self,
        session,
        *,
        project_id: str,
        session_id: str,
        change_set_id: str,
        report_id: str,
        extraction_id: str,
        revision: int,
        revision_hash: str,
        updated_at: int,
    ) -> bool:
        affected = await session.execute(
            """UPDATE finalization_change_sets
                  SET quality_report_id=%s,extraction_id=%s,
                      current_revision=%s,current_revision_hash=%s,
                      status='awaiting_author',updated_at=%s
                WHERE project_id=%s AND chapter_session_id=%s AND id=%s
                  AND status='preparing' AND active_slot=1""",
            (
                report_id, extraction_id, revision, revision_hash,
                updated_at, project_id, session_id, change_set_id,
            ),
        )
        return affected == 1


__all__ = ["FinalizationDataCorruption", "FinalizationRepository"]
