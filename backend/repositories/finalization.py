"""Session-bound persistence for finalization preparation and review."""

from __future__ import annotations

from collections.abc import Mapping
import json

from backend.domain.finalization import change_set_payload
from backend.domain.json_contracts import canonical_json
from backend.domain.provider_policy import provider_is_generation_ready
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
            """SELECT chapter.id,chapter.project_id,
                      chapter.planning_revision_id,chapter.planning_revision,
                      chapter.planning_hash,chapter.story_block_id,
                      chapter.story_block_revision,chapter.story_block_hash,
                      chapter.chapter_outline_revision_id,
                      chapter.chapter_outline_revision,
                      chapter.chapter_outline_hash,chapter.chapter_num,
                      chapter.expected_canon_revision,chapter.status,
                      chapter.active_draft_operation_id,chapter.finalized_at,
                      draft.content_hash AS working_draft_content_hash
                 FROM chapter_sessions chapter
                 JOIN working_drafts draft
                   ON draft.project_id=chapter.project_id
                  AND draft.chapter_session_id=chapter.id
                WHERE chapter.project_id=%s AND chapter.id=%s FOR UPDATE""",
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

    async def load_preparation_context(
        self,
        session,
        project_id: str,
        chapter_number: int,
    ):
        head = await session.fetchone(
            """SELECT projection.canon_revision_number AS canon_revision,
                      projection.content_hash AS projection_hash,
                      planning_revision.id AS planning_revision_id,
                      planning_revision.revision AS planning_revision,
                      planning_revision.content_hash AS planning_hash,
                      planning_revision.content_json AS planning_json,
                      outline_revision.id AS outline_revision_id,
                      outline_revision.revision AS outline_revision,
                      outline_revision.content_hash AS outline_hash,
                      outline_revision.content_json AS outline_json,
                      contract.revision AS contract_revision,
                      contract.content_hash AS contract_hash,
                      contract.content_json AS contract_json,
                      contract.id AS creation_contract_id,
                      style.merged_style_json AS style_json,
                      bible.revision AS bible_revision,
                      bible.content_hash AS bible_hash,
                      bible.content_json AS bible_json,
                      bible.policy_version
                 FROM projection_heads projection
                 JOIN project_planning_heads planning
                   ON planning.project_id=projection.project_id
                 JOIN planning_revisions planning_revision
                   ON planning_revision.project_id=planning.project_id
                  AND planning_revision.id=planning.planning_revision_id
                  AND planning_revision.revision=planning.revision
                  AND planning_revision.content_hash=planning.content_hash
                 JOIN project_chapter_outline_heads outline
                   ON outline.project_id=projection.project_id
                  AND outline.chapter_num=%s
                 JOIN chapter_outline_revisions outline_revision
                   ON outline_revision.project_id=outline.project_id
                  AND outline_revision.chapter_num=outline.chapter_num
                  AND outline_revision.id=outline.outline_revision_id
                  AND outline_revision.revision=outline.revision
                  AND outline_revision.content_hash=outline.content_hash
                 JOIN project_contract_heads contract_head
                   ON contract_head.project_id=projection.project_id
                 JOIN creation_contracts contract
                   ON contract.project_id=contract_head.project_id
                  AND contract.id=contract_head.creation_contract_id
                  AND contract.revision=contract_head.revision
                  AND contract.content_hash=contract_head.creation_hash
                 JOIN style_contracts style
                   ON style.project_id=contract_head.project_id
                  AND style.id=contract_head.style_contract_id
                  AND style.revision=contract_head.revision
                  AND style.content_hash=contract_head.style_hash
                 JOIN project_bible_heads bible_head
                   ON bible_head.project_id=projection.project_id
                 JOIN creation_bible_revisions bible
                   ON bible.project_id=bible_head.project_id
                  AND bible.id=bible_head.bible_revision_id
                  AND bible.revision=bible_head.revision
                  AND bible.content_hash=bible_head.content_hash
                WHERE projection.project_id=%s FOR UPDATE""",
            (chapter_number, project_id),
        )
        if head is None:
            return None
        value = dict(head)
        planning = _decoded_object(value.get("planning_json"), "Planning context")
        outline = _decoded_object(value.get("outline_json"), "Outline context")
        contract = _decoded_object(value.get("contract_json"), "Contract context")
        style = _decoded_object(value.get("style_json"), "Style context")
        bible = _decoded_object(value.get("bible_json"), "Bible context")

        entities = tuple(dict(row) for row in await session.fetchall(
            """SELECT id,entity_type,canonical_name
                 FROM canon_entities
                WHERE project_id=%s AND created_revision<=%s
                ORDER BY id""",
            (project_id, value.get("canon_revision")),
        ))
        state_rows = await session.fetchall(
            """SELECT entity_id,field_path,payload_json,content_hash
                 FROM current_state_projections
                WHERE project_id=%s AND revision_number=%s
                ORDER BY entity_id,field_path""",
            (project_id, value.get("canon_revision")),
        )
        current_state = []
        for row in state_rows:
            item = dict(row)
            item["payload"] = _decoded_object(
                item.pop("payload_json", None), "Canon projection payload",
            )
            current_state.append(item)

        references = tuple(dict(row) for row in await session.fetchall(
            """SELECT fragment.id,fragment.normalized_text AS content,
                      fragment.content_hash
                 FROM creation_contract_corpus_fragment_refs reference
                 JOIN corpus_fragments fragment
                   ON fragment.corpus_source_id=reference.corpus_source_id
                  AND fragment.corpus_chapter_id=reference.corpus_chapter_id
                  AND fragment.id=reference.corpus_fragment_id
                  AND fragment.content_hash=reference.fragment_hash
                WHERE reference.creation_contract_id=%s
                ORDER BY reference.sort_order""",
            (value.get("creation_contract_id"),),
        ))
        binding_rows = await session.fetchall(
            """SELECT item.task_key,provider.id,provider.provider_type,
                      provider.model_name,provider.base_url,provider.api_key,
                      provider.enabled,provider.lifecycle_status,
                      provider.revision,provider.temperature,
                      provider.max_context_tokens,provider.max_output_tokens
                 FROM project_model_binding_heads head
                 JOIN project_model_binding_items item
                   ON item.binding_revision_id=head.binding_revision_id
                  AND item.task_key IN ('audit','extraction')
                 LEFT JOIN provider_profiles provider
                   ON provider.id=item.provider_id
                WHERE head.project_id=%s
                  AND item.resolution_status='bound'
                ORDER BY item.task_key FOR UPDATE""",
            (project_id,),
        )
        bindings = {}
        for row in binding_rows:
            binding = dict(row)
            task_key = binding.get("task_key")
            if task_key in {"audit", "extraction"} and provider_is_generation_ready(
                binding
            ):
                bindings[task_key] = binding

        return {
            "canon_context": {
                "revision": value.get("canon_revision"),
                "projectionHash": value.get("projection_hash"),
                "entities": list(entities),
                "currentState": current_state,
            },
            "planning_context": {
                "id": value.get("planning_revision_id"),
                "revision": value.get("planning_revision"),
                "contentHash": value.get("planning_hash"),
                "content": planning,
            },
            "outline_context": {
                "id": value.get("outline_revision_id"),
                "revision": value.get("outline_revision"),
                "contentHash": value.get("outline_hash"),
                "content": outline,
            },
            "contract_context": {
                "revision": value.get("contract_revision"),
                "contentHash": value.get("contract_hash"),
                "content": contract,
                "style": style,
            },
            "bible_context": {
                "revision": value.get("bible_revision"),
                "contentHash": value.get("bible_hash"),
                "content": bible,
            },
            "policy_version": value.get("policy_version"),
            "reference_sources": list(references),
            "audit_binding": bindings.get("audit"),
            "extraction_binding": bindings.get("extraction"),
        }

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

    async def mark_terminal(
        self,
        session,
        *,
        project_id: str,
        session_id: str,
        change_set_id: str,
        status: str,
        report_id: str | None,
        updated_at: int,
    ) -> bool:
        if status not in {"invalidated", "cancelled", "failed"}:
            raise ValueError("unsupported finalization terminal state")
        affected = await session.execute(
            """UPDATE finalization_change_sets
                  SET quality_report_id=COALESCE(%s,quality_report_id),
                      status=%s,active_slot=NULL,updated_at=%s
                WHERE project_id=%s AND chapter_session_id=%s AND id=%s
                  AND status='preparing' AND active_slot=1""",
            (
                report_id, status, updated_at, project_id, session_id,
                change_set_id,
            ),
        )
        return affected == 1


__all__ = ["FinalizationDataCorruption", "FinalizationRepository"]
