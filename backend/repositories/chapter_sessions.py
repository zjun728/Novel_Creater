from __future__ import annotations

from hashlib import sha256
import json
from typing import Mapping

from backend.domain.json_contracts import canonical_json
from backend.domain.provider_policy import GENERATION_PROVIDER_TYPE
from backend.repositories.project_lifecycle import lock_active_project


_EMPTY_PARTIAL_TEXT = ""
_EMPTY_PARTIAL_HASH = sha256(_EMPTY_PARTIAL_TEXT.encode("utf-8")).hexdigest()


class ActiveChapterSessionConflict(RuntimeError):
    pass


def authoritative_chapter(
    active_session: Mapping[str, object] | None,
    max_final_chapter: int | None,
) -> int:
    if active_session is not None:
        return int(active_session["chapter_num"])
    if max_final_chapter is not None:
        return int(max_final_chapter) + 1
    return 1


_SESSION_SELECT = """
SELECT session.*,outline.content_json AS chapter_outline_json,
       outline.canon_revision AS outline_canon_revision,
       outline.projection_revision AS outline_projection_revision,
       outline.projection_hash AS outline_projection_hash
  FROM chapter_sessions session
  JOIN chapter_outline_revisions outline
    ON outline.project_id=session.project_id
   AND outline.chapter_num=session.chapter_num
   AND outline.id=session.chapter_outline_revision_id
   AND outline.revision=session.chapter_outline_revision
   AND outline.content_hash=session.chapter_outline_hash
   AND outline.planning_revision_id=session.planning_revision_id
   AND outline.planning_revision=session.planning_revision
   AND outline.planning_hash=session.planning_hash
"""


class ChapterSessionRepository:
    async def lock_project(self, session, project_id: str):
        return await lock_active_project(session, project_id)

    async def read_active_session(self, session, project_id: str):
        rows = await session.fetchall(
            """SELECT id,project_id,chapter_num,status
                 FROM chapter_sessions
                WHERE project_id=%s AND status='drafting'
                ORDER BY chapter_num,id
                LIMIT 2""",
            (project_id,),
        )
        if len(rows) > 1:
            raise ActiveChapterSessionConflict(
                "multiple active ChapterSession rows exist for project"
            )
        return dict(rows[0]) if rows else None

    async def read_max_final_chapter_number(self, session, project_id: str):
        row = await session.fetchone(
            """SELECT MAX(chapter_num) AS chapter_num
                 FROM final_chapters
                WHERE project_id=%s""",
            (project_id,),
        )
        if row is None or row["chapter_num"] is None:
            return None
        return int(row["chapter_num"])

    async def read_current_outline(
        self,
        session,
        project_id: str,
        chapter_number: int,
    ):
        row = await session.fetchone(
            """SELECT outline.id AS chapter_outline_revision_id,
                      outline.revision AS chapter_outline_revision,
                      outline.content_hash AS chapter_outline_hash,
                      outline.planning_revision_id,
                      outline.planning_revision,
                      outline.planning_hash,
                      outline.canon_revision,outline.projection_revision,
                      outline.projection_hash,
                      outline.content_json AS chapter_outline_json,
                      current_head.planning_revision_id
                        AS current_planning_revision_id,
                      current_head.revision AS current_planning_revision,
                      current_head.content_hash AS current_planning_hash,
                      planning.selection_revision
                        AS planning_selection_revision,
                      planning.seed_id AS planning_seed_id,
                      planning.seed_revision_id
                        AS planning_seed_revision_id,
                      planning.seed_hash AS planning_seed_hash,
                      planning.contract_revision
                        AS planning_contract_revision,
                      planning.creation_contract_id
                        AS planning_creation_contract_id,
                      planning.creation_hash AS planning_creation_hash,
                      planning.style_contract_id
                        AS planning_style_contract_id,
                      planning.style_hash AS planning_style_hash,
                      planning.bible_revision AS planning_bible_revision,
                      planning.bible_revision_id
                        AS planning_bible_revision_id,
                      planning.bible_hash AS planning_bible_hash,
                      selected.selection_revision
                        AS current_selection_revision,
                      selected.seed_id AS current_seed_id,
                      selected.seed_revision_id
                        AS current_seed_revision_id,
                      selected.seed_hash AS current_seed_hash,
                      contract_head.revision AS current_contract_revision,
                      contract_head.creation_contract_id
                        AS current_creation_contract_id,
                      contract_head.creation_hash
                        AS current_creation_hash,
                      contract_head.style_contract_id
                        AS current_style_contract_id,
                      contract_head.style_hash AS current_style_hash,
                      bible_head.revision AS current_bible_revision,
                      bible_head.bible_revision_id
                        AS current_bible_revision_id,
                      bible_head.content_hash AS current_bible_hash,
                      JSON_UNQUOTE(JSON_EXTRACT(
                        outline.content_json,'$.storyBlockRef.id'
                      )) AS story_block_id,
                      CAST(JSON_UNQUOTE(JSON_EXTRACT(
                        outline.content_json,'$.storyBlockRef.revision'
                      )) AS UNSIGNED) AS story_block_revision,
                      JSON_UNQUOTE(JSON_EXTRACT(
                        outline.content_json,'$.storyBlockRef.contentHash'
                      )) AS story_block_hash
                 FROM project_chapter_outline_heads outline_head
                 JOIN chapter_outline_revisions outline
                   ON outline.project_id=outline_head.project_id
                  AND outline.chapter_num=outline_head.chapter_num
                  AND outline.id=outline_head.outline_revision_id
                  AND outline.revision=outline_head.revision
                  AND outline.content_hash=outline_head.content_hash
                 JOIN planning_revisions planning
                   ON planning.project_id=outline.project_id
                  AND planning.id=outline.planning_revision_id
                  AND planning.revision=outline.planning_revision
                  AND planning.content_hash=outline.planning_hash
                 JOIN project_selected_seeds selected
                   ON selected.project_id=outline.project_id
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
                  AND bible.creation_contract_id=
                      contract_head.creation_contract_id
                  AND bible.creation_hash=contract_head.creation_hash
                  AND bible.style_contract_id=contract_head.style_contract_id
                  AND bible.style_hash=contract_head.style_hash
                 JOIN project_planning_heads current_head
                   ON current_head.project_id=outline.project_id
                WHERE outline_head.project_id=%s
                  AND outline_head.chapter_num=%s
                  AND outline_head.revision>0""",
            (project_id, chapter_number),
        )
        if row is None:
            return None
        result = dict(row)
        result["chapter_outline"] = self._json(
            result.pop("chapter_outline_json"),
        )
        return result

    async def read_projection_head(self, session, project_id: str):
        return await session.fetchone(
            """SELECT canon_revision_number,projection_revision_number,
                      content_hash
                 FROM projection_heads
                WHERE project_id=%s""",
            (project_id,),
        )

    async def read_draft_prompt_context(
        self,
        session,
        project_id: str,
        chapter_number: int,
    ):
        head = await session.fetchone(
            """SELECT seed.payload_json AS seed_json,
                      creation.content_json AS creation_json,
                      style.merged_style_json AS style_json,
                      bible.content_json AS bible_json
                 FROM project_selected_seeds selected
                 JOIN creative_seed_revisions seed
                   ON seed.project_id=selected.project_id
                  AND seed.seed_id=selected.seed_id
                  AND seed.id=selected.seed_revision_id
                  AND seed.content_hash=selected.seed_hash
                 JOIN project_contract_heads contract_head
                   ON contract_head.project_id=selected.project_id
                  AND contract_head.revision>0
                 JOIN creation_contracts creation
                   ON creation.project_id=contract_head.project_id
                  AND creation.id=contract_head.creation_contract_id
                  AND creation.revision=contract_head.revision
                  AND creation.content_hash=contract_head.creation_hash
                 JOIN style_contracts style
                   ON style.project_id=contract_head.project_id
                  AND style.id=contract_head.style_contract_id
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
                WHERE selected.project_id=%s""",
            (project_id,),
        )
        if head is None:
            return None
        canon_rows = await session.fetchall(
            """SELECT entity.id,entity.entity_type,entity.canonical_name,
                      state.field_path,state.payload_json
                 FROM projection_heads projection
                 JOIN canon_entities entity
                   ON entity.project_id=projection.project_id
                  AND entity.created_revision<=projection.canon_revision_number
                 LEFT JOIN current_state_projections state
                   ON state.project_id=entity.project_id
                  AND state.entity_id=entity.id
                  AND state.revision_number=projection.canon_revision_number
                WHERE projection.project_id=%s
                ORDER BY entity.entity_type,entity.canonical_name,state.field_path""",
            (project_id,),
        )
        previous = await session.fetchone(
            """SELECT chapter_num,title,content
                 FROM final_chapters
                WHERE project_id=%s AND chapter_num<%s
                ORDER BY chapter_num DESC,id DESC LIMIT 1""",
            (project_id, chapter_number),
        )
        canon = []
        for row in canon_rows:
            item = dict(row)
            payload = item.pop("payload_json", None)
            item["payload"] = self._json(payload) if payload is not None else None
            canon.append(item)
        previous_chapter = None
        if previous is not None:
            previous_chapter = {
                "chapterNumber": int(previous["chapter_num"]),
                "title": str(previous["title"]),
                "content": str(previous["content"]),
            }
        return {
            "seed": self._json(head["seed_json"]),
            "creationContract": self._json(head["creation_json"]),
            "styleContract": self._json(head["style_json"]),
            "creationBible": self._json(head["bible_json"]),
            "canon": {"currentState": canon},
            "previousFinalChapter": previous_chapter,
        }

    async def read_chapter_session(
        self,
        session,
        project_id: str,
        chapter_number: int,
    ):
        row = await session.fetchone(
            f"""{_SESSION_SELECT}
                 WHERE session.project_id=%s AND session.chapter_num=%s""",
            (project_id, chapter_number),
        )
        return self._session(row) if row else None

    async def read_session_by_id(
        self,
        session,
        project_id: str,
        chapter_session_id: str,
    ):
        row = await session.fetchone(
            f"""{_SESSION_SELECT}
                 WHERE session.project_id=%s AND session.id=%s""",
            (project_id, chapter_session_id),
        )
        return self._session(row) if row else None

    async def insert_chapter_session(self, session, row: dict) -> bool:
        return await session.execute(
            """INSERT INTO chapter_sessions
               (id,project_id,planning_revision_id,planning_revision,
                planning_hash,story_block_id,story_block_revision,
                story_block_hash,chapter_outline_revision_id,
                chapter_outline_revision,chapter_outline_hash,chapter_num,
                expected_canon_revision,status,created_at,finalized_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["id"],
                row["project_id"],
                row["planning_revision_id"],
                row["planning_revision"],
                row["planning_hash"],
                row["story_block_id"],
                row["story_block_revision"],
                row["story_block_hash"],
                row["chapter_outline_revision_id"],
                row["chapter_outline_revision"],
                row["chapter_outline_hash"],
                row["chapter_num"],
                row["expected_canon_revision"],
                row["status"],
                row["created_at"],
                row["finalized_at"],
            ),
        ) == 1

    async def read_working_draft(self, session, chapter_session_id: str):
        row = await session.fetchone(
            """SELECT draft.*,chapter.status AS effective_status
                 FROM working_drafts draft
                 JOIN chapter_sessions chapter
                   ON chapter.project_id=draft.project_id
                  AND chapter.id=draft.chapter_session_id
                WHERE draft.chapter_session_id=%s""",
            (chapter_session_id,),
        )
        return self._draft(row) if row else None

    async def lock_working_draft_for_operation(
        self,
        session,
        project_id: str,
        chapter_session_id: str,
    ):
        row = await session.fetchone(
            """SELECT draft.*,chapter.status AS effective_status
                 FROM working_drafts draft
                 JOIN chapter_sessions chapter
                   ON chapter.project_id=draft.project_id
                  AND chapter.id=draft.chapter_session_id
                WHERE draft.project_id=%s AND draft.chapter_session_id=%s
                FOR UPDATE""",
            (project_id, chapter_session_id),
        )
        return self._draft(row) if row else None

    async def lock_session_for_operation(
        self,
        session,
        project_id: str,
        chapter_session_id: str,
    ):
        row = await session.fetchone(
            """SELECT * FROM chapter_sessions
                 WHERE project_id=%s AND id=%s
                 FOR UPDATE""",
            (project_id, chapter_session_id),
        )
        return dict(row) if row else None

    async def read_draft_operation_by_key(
        self,
        session,
        chapter_session_id: str,
        idempotency_key: str,
    ):
        row = await session.fetchone(
            """SELECT * FROM draft_operation_attempts
                 WHERE chapter_session_id=%s AND idempotency_key=%s
                 FOR UPDATE""",
            (chapter_session_id, idempotency_key),
        )
        return dict(row) if row else None

    async def read_draft_operation(
        self,
        session,
        project_id: str,
        chapter_session_id: str,
        operation_id: str,
    ):
        row = await session.fetchone(
            """SELECT * FROM draft_operation_attempts
                 WHERE project_id=%s AND chapter_session_id=%s AND id=%s
                 FOR UPDATE""",
            (project_id, chapter_session_id, operation_id),
        )
        return dict(row) if row else None

    async def read_working_draft_recovery_for_operation(
        self,
        session,
        project_id: str,
        chapter_session_id: str,
        source_operation_id: str,
    ):
        row = await session.fetchone(
            """SELECT id,project_id,chapter_session_id,working_draft_id,
                      working_draft_revision,snapshot_role,replacement_reason,
                      source_operation_id,source_candidate_id,content,
                      content_hash,created_at
                 FROM working_draft_revisions
                WHERE project_id=%s AND chapter_session_id=%s
                  AND source_operation_id=%s AND snapshot_role='before'
                FOR UPDATE""",
            (project_id, chapter_session_id, source_operation_id),
        )
        return dict(row) if row else None

    async def read_active_draft_operation(self, session, chapter_session_id: str):
        row = await session.fetchone(
            """SELECT * FROM draft_operation_attempts
                 WHERE chapter_session_id=%s AND active_slot=1
                 FOR UPDATE""",
            (chapter_session_id,),
        )
        return dict(row) if row else None

    async def next_draft_operation_fencing_token(
        self,
        session,
        project_id: str,
        chapter_session_id: str,
    ) -> int | None:
        row = await session.fetchone(
            """SELECT draft_operation_fencing_token
                 FROM chapter_sessions
                WHERE project_id=%s AND id=%s
                FOR UPDATE""",
            (project_id, chapter_session_id),
        )
        if row is None:
            return None
        previous = int(row["draft_operation_fencing_token"])
        token = previous + 1
        changed = await session.execute(
            """UPDATE chapter_sessions
                  SET draft_operation_fencing_token=%s
                WHERE project_id=%s AND id=%s
                  AND draft_operation_fencing_token=%s""",
            (token, project_id, chapter_session_id, previous),
        )
        return token if changed == 1 else None

    async def insert_draft_operation(self, session, row: dict) -> bool:
        changed = await session.execute(
            """INSERT INTO draft_operation_attempts
               (id,project_id,chapter_session_id,operation_type,idempotency_key,
                request_fingerprint,active_slot,fencing_token,lease_expires_at,
                 base_working_draft_revision,base_working_draft_hash,
                 input_manifest_json,input_manifest_hash,provider_id,
                 model_name_snapshot,result_working_draft_revision,
                 result_content_hash,last_event_sequence,failure_code,
                 partial_output_text,partial_output_hash,partial_output_scalars,
                 heartbeat_at,status,created_at,updated_at,completed_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       %s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["id"],
                row["project_id"],
                row["chapter_session_id"],
                row["operation_type"],
                row["idempotency_key"],
                row["request_fingerprint"],
                row["active_slot"],
                row["fencing_token"],
                row["lease_expires_at"],
                row["base_working_draft_revision"],
                row["base_working_draft_hash"],
                canonical_json(row["input_manifest"]),
                row["input_manifest_hash"],
                row["provider_id"],
                row["model_name_snapshot"],
                row["result_working_draft_revision"],
                row["result_content_hash"],
                row["last_event_sequence"],
                row["failure_code"],
                _EMPTY_PARTIAL_TEXT,
                _EMPTY_PARTIAL_HASH,
                0,
                row["created_at"],
                row["status"],
                row["created_at"],
                row["updated_at"],
                row["completed_at"],
            ),
        )
        return changed == 1

    async def mark_draft_operation_running(
        self,
        session,
        operation_id: str,
        fencing_token: int,
        now: int,
    ) -> bool:
        changed = await session.execute(
            """UPDATE draft_operation_attempts operation
                 JOIN chapter_sessions chapter
                   ON chapter.project_id=operation.project_id
                  AND chapter.id=operation.chapter_session_id
                  SET operation.status='running',operation.updated_at=%s,
                      chapter.active_draft_operation_id=operation.id
                WHERE operation.id=%s AND operation.fencing_token=%s
                  AND operation.status='starting'
                  AND operation.active_slot=1
                  AND chapter.active_draft_operation_id IS NULL""",
            (now, operation_id, fencing_token),
        )
        return changed > 0

    async def append_draft_operation_delta(self, session, row: dict) -> bool:
        if not self._valid_stream_sequence(row, maximum=2047):
            return False
        changed = await session.execute(
            """UPDATE draft_operation_attempts operation
                 JOIN chapter_sessions chapter
                   ON chapter.project_id=operation.project_id
                  AND chapter.id=operation.chapter_session_id
                  SET operation.partial_output_text=%s,
                      operation.partial_output_hash=%s,
                      operation.partial_output_scalars=%s,
                      operation.heartbeat_at=%s,
                      operation.lease_expires_at=%s,
                      operation.updated_at=%s,
                      operation.last_event_sequence=%s
                WHERE operation.project_id=%s
                  AND operation.chapter_session_id=%s
                  AND operation.id=%s
                  AND operation.fencing_token=%s
                  AND operation.status='running'
                  AND operation.active_slot=1
                  AND chapter.active_draft_operation_id=operation.id
                  AND operation.lease_expires_at>%s
                  AND operation.partial_output_hash=%s
                  AND operation.last_event_sequence=%s""",
            (
                row["partial_output_text"],
                row["partial_output_hash"],
                row["partial_output_scalars"],
                row["heartbeat_at"],
                row["lease_expires_at"],
                row["updated_at"],
                row["sequence_num"],
                row["project_id"],
                row["chapter_session_id"],
                row["draft_operation_id"],
                row["fencing_token"],
                row["updated_at"],
                row["previous_partial_output_hash"],
                row["previous_last_event_sequence"],
            ),
        )
        if changed != 1:
            return False
        return await self._insert_stream_event(
            session,
            row,
            event_type="delta",
            closed_payload=row["closed_payload"],
        )

    async def append_draft_operation_heartbeat(self, session, row: dict) -> bool:
        if not self._valid_stream_sequence(row, maximum=2047):
            return False
        changed = await session.execute(
            """UPDATE draft_operation_attempts operation
                 JOIN chapter_sessions chapter
                   ON chapter.project_id=operation.project_id
                  AND chapter.id=operation.chapter_session_id
                  SET operation.heartbeat_at=%s,
                      operation.lease_expires_at=%s,
                      operation.updated_at=%s,
                      operation.last_event_sequence=%s
                WHERE operation.project_id=%s
                  AND operation.chapter_session_id=%s
                  AND operation.id=%s
                  AND operation.fencing_token=%s
                  AND operation.status='running'
                  AND operation.active_slot=1
                  AND chapter.active_draft_operation_id=operation.id
                  AND operation.lease_expires_at>%s
                  AND operation.partial_output_hash=%s
                  AND operation.last_event_sequence=%s""",
            (
                row["heartbeat_at"],
                row["lease_expires_at"],
                row["updated_at"],
                row["sequence_num"],
                row["project_id"],
                row["chapter_session_id"],
                row["draft_operation_id"],
                row["fencing_token"],
                row["updated_at"],
                row["previous_partial_output_hash"],
                row["previous_last_event_sequence"],
            ),
        )
        if changed != 1:
            return False
        return await self._insert_stream_event(
            session,
            row,
            event_type="heartbeat",
            closed_payload=None,
        )

    async def cancel_draft_operation(self, session, row: dict) -> bool:
        if not self._valid_stream_sequence(row, maximum=2048):
            return False
        result_revision = row["result_working_draft_revision"]
        result_hash = row["result_content_hash"]
        if (result_revision is None) != (result_hash is None):
            return False
        commits_partial = result_revision is not None
        common_guard = """operation.project_id=%s
                  AND operation.chapter_session_id=%s
                  AND operation.id=%s
                  AND operation.fencing_token=%s
                  AND operation.status='running'
                  AND operation.active_slot=1
                  AND chapter.active_draft_operation_id=operation.id
                  AND operation.lease_expires_at>%s
                  AND operation.partial_output_hash=%s
                  AND operation.last_event_sequence=%s"""
        guard_args = (
            row["project_id"],
            row["chapter_session_id"],
            row["draft_operation_id"],
            row["fencing_token"],
            row["updated_at"],
            row["previous_partial_output_hash"],
            row["previous_last_event_sequence"],
        )
        locked = await session.fetchone(
            """SELECT operation.id
                 FROM draft_operation_attempts operation
                 JOIN chapter_sessions chapter
                   ON chapter.project_id=operation.project_id
                  AND chapter.id=operation.chapter_session_id
                WHERE """
            + common_guard
            + " FOR UPDATE",
            guard_args,
        )
        if locked is None:
            return False

        if commits_partial:
            if not await self.insert_working_draft_revision(
                session, row["before_revision"]
            ):
                return False
            if not await self.upsert_working_draft(
                session,
                row["working_draft"],
                expected_revision=row["expected_working_draft_revision"],
                expected_content_hash=row["expected_working_draft_hash"],
            ):
                return False
            if not await self.insert_working_draft_revision(
                session, row["after_revision"]
            ):
                return False

        changed = await session.execute(
            """UPDATE draft_operation_attempts operation
                 JOIN chapter_sessions chapter
                   ON chapter.project_id=operation.project_id
                  AND chapter.id=operation.chapter_session_id
                  SET operation.status='cancelled',
                      operation.active_slot=NULL,
                      operation.result_working_draft_revision=%s,
                      operation.result_content_hash=%s,
                      operation.partial_output_text=%s,
                      operation.partial_output_hash=%s,
                      operation.partial_output_scalars=%s,
                      operation.failure_code=NULL,
                      operation.updated_at=%s,
                      operation.completed_at=%s,
                      operation.cancelled_at=%s,
                      operation.last_event_sequence=%s,
                      chapter.active_draft_operation_id=NULL
                WHERE """
            + common_guard,
            (
                result_revision,
                result_hash,
                row["partial_output_text"],
                row["partial_output_hash"],
                row["partial_output_scalars"],
                row["updated_at"],
                row["completed_at"],
                row["cancelled_at"],
                row["sequence_num"],
                *guard_args,
            ),
        )
        if changed != 2:
            return False
        return await self._insert_stream_event(
            session,
            row,
            event_type="cancelled",
            closed_payload=row["closed_payload"],
        )

    @staticmethod
    def _valid_stream_sequence(row: dict, *, maximum: int) -> bool:
        sequence = row.get("sequence_num")
        previous = row.get("previous_last_event_sequence")
        return (
            type(sequence) is int
            and type(previous) is int
            and 2 <= sequence <= maximum
            and previous == sequence - 1
        )

    async def _insert_stream_event(
        self,
        session,
        row: dict,
        *,
        event_type: str,
        closed_payload,
    ) -> bool:
        return await session.execute(
            """INSERT INTO draft_operation_events
               (id,project_id,draft_operation_id,sequence_num,event_type,
                closed_payload_json,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["id"],
                row["project_id"],
                row["draft_operation_id"],
                row["sequence_num"],
                event_type,
                (
                    canonical_json(closed_payload)
                    if closed_payload is not None
                    else None
                ),
                row["created_at"],
            ),
        ) == 1

    async def complete_draft_operation(self, session, row: dict) -> bool:
        if not self._valid_stream_sequence(row, maximum=2048):
            return False
        if (
            row["result_working_draft_revision"] is None
            or row["result_content_hash"] is None
        ):
            return False
        return await self._terminal_draft_operation_update(
            session,
            row,
            status="completed",
            assignments="""operation.result_working_draft_revision=%s,
                      operation.result_content_hash=%s,
                      operation.partial_output_text=%s,
                      operation.partial_output_hash=%s,
                      operation.partial_output_scalars=%s,
                      operation.failure_code=NULL,""",
            values=(
                row["result_working_draft_revision"],
                row["result_content_hash"],
                row["partial_output_text"],
                row["partial_output_hash"],
                row["partial_output_scalars"],
            ),
        )

    async def fail_draft_operation(self, session, row: dict) -> bool:
        if not self._valid_stream_sequence(row, maximum=2048):
            return False
        return await self._terminal_draft_operation_update(
            session,
            row,
            status="failed",
            assignments="operation.failure_code=%s,",
            values=(row["failure_code"],),
        )

    async def expire_draft_operation(
        self,
        session,
        operation_id: str,
        fencing_token: int,
        now: int,
    ) -> bool:
        changed = await session.execute(
            """UPDATE draft_operation_attempts operation
                 JOIN chapter_sessions chapter
                   ON chapter.project_id=operation.project_id
                  AND chapter.id=operation.chapter_session_id
                  SET operation.status='expired',operation.active_slot=NULL,
                      operation.updated_at=%s,operation.completed_at=%s,
                      chapter.active_draft_operation_id=NULL
                WHERE operation.id=%s AND operation.fencing_token=%s
                  AND operation.active_slot=1
                  AND operation.lease_expires_at<=%s
                  AND (
                    (operation.status='starting' AND (
                      chapter.active_draft_operation_id IS NULL
                      OR chapter.active_draft_operation_id=operation.id
                    ))
                    OR (operation.status='running'
                      AND chapter.active_draft_operation_id=operation.id)
                  )""",
            (now, now, operation_id, fencing_token, now),
        )
        return changed > 0

    async def expire_draft_operation_for_drift(
        self,
        session,
        project_id: str,
        chapter_session_id: str,
        operation_id: str,
        fencing_token: int,
        now: int,
    ) -> bool:
        changed = await session.execute(
            """UPDATE draft_operation_attempts operation
                 JOIN chapter_sessions chapter
                   ON chapter.project_id=operation.project_id
                  AND chapter.id=operation.chapter_session_id
                  SET operation.status='expired',operation.active_slot=NULL,
                      operation.updated_at=%s,operation.completed_at=%s,
                      chapter.active_draft_operation_id=NULL
                WHERE operation.project_id=%s
                  AND operation.chapter_session_id=%s
                  AND operation.id=%s AND operation.fencing_token=%s
                  AND operation.status='running'
                  AND operation.active_slot=1
                  AND operation.lease_expires_at>%s
                  AND chapter.active_draft_operation_id=operation.id""",
            (
                now,
                now,
                project_id,
                chapter_session_id,
                operation_id,
                fencing_token,
                now,
            ),
        )
        return changed > 0

    async def _terminal_draft_operation_update(
        self,
        session,
        row: dict,
        *,
        status: str,
        assignments: str,
        values: tuple,
    ) -> bool:
        changed = await session.execute(
            """UPDATE draft_operation_attempts operation
                 JOIN chapter_sessions chapter
                   ON chapter.project_id=operation.project_id
                  AND chapter.id=operation.chapter_session_id
                  SET """
            + assignments
            + """
                      operation.status='"""
            + status
            + """',operation.active_slot=NULL,
                      operation.updated_at=%s,operation.completed_at=%s,
                      operation.last_event_sequence=%s,
                      chapter.active_draft_operation_id=NULL
                WHERE operation.project_id=%s
                  AND operation.chapter_session_id=%s AND operation.id=%s
                  AND operation.fencing_token=%s
                  AND operation.status='running'
                  AND operation.active_slot=1
                  AND chapter.active_draft_operation_id=operation.id
                  AND operation.lease_expires_at>%s
                  AND operation.partial_output_hash=%s
                  AND operation.last_event_sequence=%s""",
            (
                *values,
                row["updated_at"],
                row["completed_at"],
                row["sequence_num"],
                row["project_id"],
                row["chapter_session_id"],
                row["id"],
                row["fencing_token"],
                row["updated_at"],
                row["previous_partial_output_hash"],
                row["sequence_num"],
            ),
        )
        return changed == 2

    async def insert_draft_operation_event(self, session, row: dict) -> bool:
        sequence_num = row["sequence_num"]
        changed = await session.execute(
            """UPDATE draft_operation_attempts
                  SET last_event_sequence=%s
                WHERE id=%s AND project_id=%s
                  AND last_event_sequence=%s""",
            (
                sequence_num,
                row["draft_operation_id"],
                row["project_id"],
                sequence_num - 1,
            ),
        )
        if changed != 1:
            return False
        return await session.execute(
            """INSERT INTO draft_operation_events
               (id,project_id,draft_operation_id,sequence_num,event_type,
                closed_payload_json,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["id"],
                row["project_id"],
                row["draft_operation_id"],
                sequence_num,
                row["event_type"],
                (
                    canonical_json(row["closed_payload"])
                    if row["closed_payload"] is not None
                    else None
                ),
                row["created_at"],
            ),
        ) == 1

    async def list_draft_operation_events(
        self,
        session,
        operation_id: str,
        after_sequence: int,
        limit: int,
    ):
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise ValueError("draft operation event limit must be within 1..100")
        rows = await session.fetchall(
            """SELECT id,project_id,draft_operation_id,sequence_num,event_type,
                      closed_payload_json,created_at
                 FROM draft_operation_events
                WHERE draft_operation_id=%s AND sequence_num>%s
                ORDER BY sequence_num,id
                LIMIT %s""",
            (operation_id, after_sequence, limit),
        )
        return [dict(row) for row in rows]

    async def insert_working_draft_revision(self, session, row: dict) -> bool:
        changed = await session.execute(
            """INSERT INTO working_draft_revisions
               (id,project_id,chapter_session_id,working_draft_id,
                working_draft_revision,snapshot_role,replacement_reason,
                source_operation_id,source_candidate_id,content,content_hash,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE id=id""",
            (
                row["id"],
                row["project_id"],
                row["chapter_session_id"],
                row["working_draft_id"],
                row["working_draft_revision"],
                row["snapshot_role"],
                row["replacement_reason"],
                row["source_operation_id"],
                row.get("source_candidate_id"),
                row["content"],
                row["content_hash"],
                row["created_at"],
            ),
        )
        if changed == 1:
            return True
        existing = await session.fetchone(
            """SELECT id,working_draft_id,replacement_reason,
                      source_operation_id,source_candidate_id,content,
                      content_hash,created_at
                 FROM working_draft_revisions
                 WHERE project_id=%s AND chapter_session_id=%s
                   AND working_draft_revision=%s AND snapshot_role=%s
                 FOR UPDATE""",
            (
                row["project_id"],
                row["chapter_session_id"],
                row["working_draft_revision"],
                row["snapshot_role"],
            ),
        )
        return bool(
            existing
            and all(
                existing[field] == row[field]
                for field in (
                    "id",
                    "working_draft_id",
                    "replacement_reason",
                    "source_operation_id",
                    "source_candidate_id",
                    "content",
                    "content_hash",
                    "created_at",
                )
            )
        )

    async def upsert_working_draft(
        self,
        session,
        row: dict,
        *,
        expected_revision: int | None = None,
        expected_content_hash: str | None = None,
    ) -> bool:
        if expected_revision is not None or expected_content_hash is not None:
            if expected_revision is None or expected_content_hash is None:
                raise TypeError("working draft CAS requires revision and content hash")
            changed = await session.execute(
                """UPDATE working_drafts
                      SET revision=%s,content=%s,content_hash=%s,
                          source_payload_json=%s,updated_at=%s
                    WHERE id=%s AND project_id=%s AND chapter_session_id=%s
                      AND revision=%s AND content_hash=%s""",
                (
                    row["revision"],
                    row["content"],
                    row["content_hash"],
                    canonical_json(row["source_payload"]),
                    row["updated_at"],
                    row["id"],
                    row["project_id"],
                    row["chapter_session_id"],
                    expected_revision,
                    expected_content_hash,
                ),
            )
            return changed == 1
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
                row["id"],
                row["project_id"],
                row["chapter_session_id"],
                row["revision"],
                row["content"],
                row["content_hash"],
                canonical_json(row["source_payload"]),
                row["updated_at"],
            ),
        )
        return changed in (1, 2)

    async def insert_candidate(self, session, row: dict) -> bool:
        changed = await session.execute(
            """INSERT INTO draft_candidates
               (id,project_id,chapter_session_id,working_draft_revision,content,
                content_hash,basis_hash,provenance_json,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE id=id""",
            (
                row["id"],
                row["project_id"],
                row["chapter_session_id"],
                row["working_draft_revision"],
                row["content"],
                row["content_hash"],
                row["basis_hash"],
                canonical_json(row["provenance"]),
                row["created_at"],
            ),
        )
        if changed == 1:
            return True
        existing = await session.fetchone(
            """SELECT basis_hash,provenance_json FROM draft_candidates
                 WHERE chapter_session_id=%s AND content_hash=%s AND basis_hash=%s""",
            (
                row["chapter_session_id"],
                row["content_hash"],
                row["basis_hash"],
            ),
        )
        if existing is None or existing["basis_hash"] != row["basis_hash"]:
            return False
        provenance = self._json(existing["provenance_json"])
        if not isinstance(provenance, Mapping):
            return False
        ignored = {"source", "workingDraftRevision"}
        stored_basis = {
            key: value for key, value in provenance.items() if key not in ignored
        }
        incoming_basis = {
            key: value for key, value in row["provenance"].items() if key not in ignored
        }
        return canonical_json(stored_basis) == canonical_json(incoming_basis)

    async def read_candidate_by_identity(
        self,
        session,
        chapter_session_id: str,
        content_hash: str,
        basis_hash: str,
    ):
        row = await session.fetchone(
            """SELECT * FROM draft_candidates
                 WHERE chapter_session_id=%s AND content_hash=%s AND basis_hash=%s""",
            (chapter_session_id, content_hash, basis_hash),
        )
        return self._candidate(row) if row else None

    async def read_candidate_for_load(
        self,
        session,
        project_id: str,
        chapter_session_id: str,
        candidate_id: str,
    ):
        row = await session.fetchone(
            """SELECT * FROM draft_candidates
                 WHERE project_id=%s AND chapter_session_id=%s AND id=%s
                 FOR UPDATE""",
            (project_id, chapter_session_id, candidate_id),
        )
        return self._candidate(row) if row else None

    async def read_candidate_freeze_request(
        self,
        session,
        chapter_session_id: str,
        idempotency_key: str,
    ):
        return await session.fetchone(
            """SELECT request_hash,draft_candidate_id
                 FROM candidate_freeze_requests
                WHERE chapter_session_id=%s AND idempotency_key=%s""",
            (chapter_session_id, idempotency_key),
        )

    async def insert_candidate_freeze_request(self, session, row: dict) -> bool:
        changed = await session.execute(
            """INSERT INTO candidate_freeze_requests
               (id,project_id,chapter_session_id,idempotency_key,request_hash,
                draft_candidate_id,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["id"],
                row["project_id"],
                row["chapter_session_id"],
                row["idempotency_key"],
                row["request_hash"],
                row["draft_candidate_id"],
                row["created_at"],
            ),
        )
        return changed == 1

    async def list_candidates(self, session, chapter_session_id: str):
        rows = await session.fetchall(
            """SELECT candidate.*,chapter.status AS effective_status
                 FROM draft_candidates candidate
                 JOIN chapter_sessions chapter
                   ON chapter.project_id=candidate.project_id
                  AND chapter.id=candidate.chapter_session_id
                WHERE candidate.chapter_session_id=%s
                ORDER BY candidate.created_at,candidate.id""",
            (chapter_session_id,),
        )
        return [self._candidate(row) for row in rows]

    async def resolve_writing_provider(self, session, project_id: str):
        row = await session.fetchone(
            f"""SELECT h.binding_revision_id,
                      h.revision AS binding_revision,
                      h.content_hash AS binding_hash,
                      i.item_hash AS binding_item_hash,
                      p.id,p.name,p.provider_type,p.model_name,p.base_url,p.api_key,
                      p.temperature,p.max_output_tokens,p.stream,p.supports_streaming
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
            "id": row["id"],
            "project_id": row["project_id"],
            "planning_revision_id": row["planning_revision_id"],
            "planning_revision": row["planning_revision"],
            "planning_hash": row["planning_hash"],
            "story_block_id": row["story_block_id"],
            "story_block_revision": row["story_block_revision"],
            "story_block_hash": row["story_block_hash"],
            "chapter_outline_revision_id": row[
                "chapter_outline_revision_id"
            ],
            "chapter_outline_revision": row["chapter_outline_revision"],
            "chapter_outline_hash": row["chapter_outline_hash"],
            "chapter_num": row["chapter_num"],
            "expected_canon_revision": row["expected_canon_revision"],
            "outline_canon_revision": row["outline_canon_revision"],
            "outline_projection_revision": row["outline_projection_revision"],
            "outline_projection_hash": row["outline_projection_hash"],
            "chapter_outline": self._json(row["chapter_outline_json"]),
            "status": row["status"],
            "active_draft_operation_id": row["active_draft_operation_id"],
            "created_at": row["created_at"],
            "finalized_at": row["finalized_at"],
        }

    def _draft(self, row):
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "chapter_session_id": row["chapter_session_id"],
            "revision": row["revision"],
            "content": row["content"],
            "content_hash": row["content_hash"],
            "source_payload": self._json(row["source_payload_json"]),
            "updated_at": row["updated_at"],
            "effective_status": row.get("effective_status", "drafting"),
        }

    def _candidate(self, row):
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "chapter_session_id": row["chapter_session_id"],
            "working_draft_revision": row["working_draft_revision"],
            "content": row["content"],
            "content_hash": row["content_hash"],
            "basis_hash": row["basis_hash"],
            "provenance": self._json(row["provenance_json"]),
            "created_at": row["created_at"],
            "effective_status": row.get("effective_status", "drafting"),
        }
