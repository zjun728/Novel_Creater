from __future__ import annotations

import json

from backend.domain.json_contracts import canonical_json
from backend.domain.provider_policy import GENERATION_PROVIDER_TYPE
from backend.repositories.planning import PlanningRepository
from backend.repositories.project_lifecycle import lock_active_project


_GENERATION_JOINS = """
LEFT JOIN project_selected_seeds selected
  ON selected.project_id=session.project_id
LEFT JOIN project_contract_heads contract_head
  ON contract_head.project_id=session.project_id
LEFT JOIN creation_contracts current_contract
  ON current_contract.project_id=contract_head.project_id
 AND current_contract.id=contract_head.creation_contract_id
 AND current_contract.revision=contract_head.revision
 AND current_contract.content_hash=contract_head.creation_hash
LEFT JOIN project_bible_heads bible_head
  ON bible_head.project_id=session.project_id
LEFT JOIN creation_bible_revisions current_bible
  ON current_bible.project_id=bible_head.project_id
 AND current_bible.id=bible_head.bible_revision_id
 AND current_bible.revision=bible_head.revision
 AND current_bible.content_hash=bible_head.content_hash
LEFT JOIN volume_plans planning_root
  ON planning_root.project_id=session.project_id
 AND planning_root.id=session.volume_plan_id
"""
_EFFECTIVE_STATUS = """
CASE WHEN selected.selection_revision=session.selection_revision
  AND current_contract.selection_revision=session.selection_revision
  AND contract_head.revision=session.contract_revision
  AND contract_head.creation_hash=session.contract_hash
  AND current_bible.selection_revision=session.selection_revision
  AND current_bible.contract_revision=session.contract_revision
  AND current_bible.creation_hash=session.contract_hash
  AND bible_head.revision=session.bible_revision
  AND bible_head.content_hash=session.bible_hash
  AND planning_root.manifest_hash=session.planning_manifest_hash
  AND planning_root.selection_revision=session.selection_revision
  AND planning_root.contract_revision=session.contract_revision
  AND planning_root.contract_hash=session.contract_hash
  AND planning_root.bible_revision=session.bible_revision
  AND planning_root.bible_hash=session.bible_hash
  AND planning_root.status='active'
THEN session.status ELSE 'superseded' END
"""
_SESSION_SELECT = f"""
SELECT session.*,{_EFFECTIVE_STATUS} AS effective_status
  FROM chapter_sessions session
  {_GENERATION_JOINS}
"""


class ChapterSessionRepository:
    def __init__(self):
        self.planning = PlanningRepository()

    async def lock_project(self, session, project_id: str):
        return await lock_active_project(session, project_id)

    async def read_active_plan(self, session, project_id: str):
        return await self.planning.read_current_plan(session, project_id)

    async def read_projection_head(self, session, project_id: str):
        return await session.fetchone(
            "SELECT canon_revision_number FROM projection_heads WHERE project_id=%s",
            (project_id,),
        )

    async def read_chapter_session(
        self,
        session,
        project_id: str,
        chapter_num: int,
        generation: dict,
    ):
        row = await session.fetchone(
            f"""{_SESSION_SELECT}
                 WHERE session.project_id=%s AND session.chapter_num=%s
                   AND session.selection_revision=%s
                   AND session.contract_revision=%s
                   AND session.contract_hash=%s
                   AND session.bible_revision=%s
                   AND session.bible_hash=%s
                   AND session.volume_plan_id=%s
                   AND session.planning_manifest_hash=%s""",
            (
                project_id, chapter_num,
                generation["selection_revision"],
                generation["contract_revision"],
                generation["contract_hash"],
                generation["bible_revision"],
                generation["bible_hash"],
                generation["volume_plan_id"],
                generation["planning_manifest_hash"],
            ),
        )
        return self._session(row) if row else None

    async def read_session_by_id(self, session, project_id: str, chapter_session_id: str):
        row = await session.fetchone(
            f"""{_SESSION_SELECT}
                 WHERE session.project_id=%s AND session.id=%s""",
            (project_id, chapter_session_id),
        )
        return self._session(row) if row else None

    async def read_latest_chapter_session(self, session, project_id: str):
        row = await session.fetchone(
            f"""{_SESSION_SELECT}
                 WHERE session.project_id=%s
                 ORDER BY session.created_at DESC,session.id DESC LIMIT 1""",
            (project_id,),
        )
        return self._session(row) if row else None

    async def insert_chapter_session(self, session, row: dict) -> bool:
        return await session.execute(
            """INSERT INTO chapter_sessions
               (id,project_id,selection_revision,contract_revision,contract_hash,
                bible_revision,bible_hash,volume_plan_id,planning_manifest_hash,
                story_block_id,chapter_num,expected_canon_revision,
                expected_story_block_revision,planning_snapshot_json,status,
                created_at,finalized_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["id"], row["project_id"], row["selection_revision"],
                row["contract_revision"], row["contract_hash"],
                row["bible_revision"], row["bible_hash"],
                row["volume_plan_id"], row["planning_manifest_hash"],
                row["story_block_id"],
                row["chapter_num"], row["expected_canon_revision"],
                row["expected_story_block_revision"],
                canonical_json(row["planning_snapshot"]),
                row["status"], row["created_at"], row["finalized_at"],
            ),
        ) == 1

    async def read_working_draft(self, session, chapter_session_id: str):
        row = await session.fetchone(
            f"""SELECT draft.*,state.effective_status
                  FROM working_drafts draft
                  JOIN ({_SESSION_SELECT}) state
                    ON state.project_id=draft.project_id
                   AND state.id=draft.chapter_session_id
                 WHERE draft.chapter_session_id=%s""",
            (chapter_session_id,),
        )
        return self._draft(row) if row else None

    async def upsert_working_draft(self, session, row: dict) -> bool:
        changed = await session.execute(
            """INSERT INTO working_drafts
               (id,project_id,chapter_session_id,revision,content,content_hash,
                source_payload_json,updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) AS new
               ON DUPLICATE KEY UPDATE
                 revision=new.revision,content=new.content,
                 content_hash=new.content_hash,
                 source_payload_json=new.source_payload_json,
                 updated_at=new.updated_at""",
            (
                row["id"], row["project_id"], row["chapter_session_id"],
                row["revision"], row["content"], row["content_hash"],
                canonical_json(row["source_payload"]), row["updated_at"],
            ),
        )
        return changed in (1, 2)

    async def insert_candidate(self, session, row: dict) -> bool:
        return await session.execute(
            """INSERT IGNORE INTO draft_candidates
               (id,project_id,chapter_session_id,working_draft_revision,content,
                content_hash,provenance_json,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["id"], row["project_id"], row["chapter_session_id"],
                row["working_draft_revision"], row["content"],
                row["content_hash"], canonical_json(row["provenance"]),
                row["created_at"],
            ),
        ) in (0, 1)

    async def list_candidates(self, session, chapter_session_id: str):
        rows = await session.fetchall(
            f"""SELECT candidate.*,state.effective_status
                  FROM draft_candidates candidate
                  JOIN ({_SESSION_SELECT}) state
                    ON state.project_id=candidate.project_id
                   AND state.id=candidate.chapter_session_id
                 WHERE candidate.chapter_session_id=%s
                 ORDER BY candidate.created_at,candidate.id""",
            (chapter_session_id,),
        )
        return [self._candidate(row) for row in rows]

    async def resolve_writing_provider(self, session, project_id: str):
        row = await session.fetchone(
            f"""SELECT p.id,p.name,p.provider_type,p.model_name,p.base_url,p.api_key,
                      p.temperature,p.max_output_tokens
               FROM project_model_binding_heads h
               JOIN project_model_binding_revisions r
                 ON r.project_id=h.project_id AND r.id=h.binding_revision_id
               JOIN project_model_binding_items i
                 ON i.binding_revision_id=r.id
               JOIN provider_profiles p ON p.id=i.provider_id
               WHERE h.project_id=%s
                 AND i.task_key='writing'
                 AND i.resolution_status='bound'
                 AND p.lifecycle_status='active'
                 AND p.enabled=1
                 AND LOWER(TRIM(p.provider_type))='{GENERATION_PROVIDER_TYPE}'
                 AND p.model_name IS NOT NULL AND TRIM(p.model_name)<>''
                 AND p.base_url IS NOT NULL AND TRIM(p.base_url)<>''
                 AND p.api_key IS NOT NULL AND TRIM(p.api_key)<>''
               LIMIT 1""",
            (project_id,),
        )
        return dict(row) if row else None

    def _json(self, value):
        if isinstance(value, dict):
            return value
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("utf-8")
        if isinstance(value, str):
            loaded = json.loads(value)
            return loaded if isinstance(loaded, dict) else {}
        return {}

    def _session(self, row):
        return {
            "id": row["id"], "project_id": row["project_id"],
            "story_block_id": row["story_block_id"],
            "selection_revision": row["selection_revision"],
            "contract_revision": row["contract_revision"],
            "contract_hash": row["contract_hash"],
            "bible_revision": row["bible_revision"],
            "bible_hash": row["bible_hash"],
            "volume_plan_id": row["volume_plan_id"],
            "planning_manifest_hash": row["planning_manifest_hash"],
            "chapter_num": row["chapter_num"],
            "expected_canon_revision": row["expected_canon_revision"],
            "expected_story_block_revision": row["expected_story_block_revision"],
            "planning_snapshot": self._json(row["planning_snapshot_json"]),
            "status": row.get("effective_status", row["status"]),
            "stored_status": row["status"], "created_at": row["created_at"],
            "finalized_at": row["finalized_at"],
        }

    def _draft(self, row):
        return {
            "id": row["id"], "project_id": row["project_id"],
            "chapter_session_id": row["chapter_session_id"],
            "revision": row["revision"], "content": row["content"],
            "content_hash": row["content_hash"],
            "source_payload": self._json(row["source_payload_json"]),
            "updated_at": row["updated_at"],
            "effective_status": row.get("effective_status", "drafting"),
        }

    def _candidate(self, row):
        return {
            "id": row["id"], "project_id": row["project_id"],
            "chapter_session_id": row["chapter_session_id"],
            "working_draft_revision": row["working_draft_revision"],
            "content": row["content"], "content_hash": row["content_hash"],
            "provenance": self._json(row["provenance_json"]),
            "created_at": row["created_at"],
            "effective_status": row.get("effective_status", "drafting"),
        }
