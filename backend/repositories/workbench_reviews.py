"""Single-chapter reads pinned by an immutable finalization record."""

from backend.repositories.manuscripts import _AUTHORITY_COLUMNS, _AUTHORITY_JOINS


_REVIEW_SELECT = f"""
SELECT {_AUTHORITY_COLUMNS},
       final.content AS final_content, final.content_hash AS final_content_hash,
       final.finalization_record_id AS final_finalization_id,
       final.draft_candidate_id AS final_candidate_id,
       final.canon_revision AS final_canon_revision,
       record.id AS record_id, record.project_id AS record_project_id,
       record.chapter_session_id AS record_session_id,
       record.draft_candidate_id AS record_candidate_id,
       record.candidate_hash AS record_candidate_hash,
       record.change_set_id AS record_change_set_id,
       record.change_set_revision AS record_revision,
       record.change_set_hash AS record_hash,
       record.expected_canon_revision AS record_expected_canon,
       record.committed_canon_revision AS record_committed_canon,
       attempt.id AS attempt_id, attempt.project_id AS attempt_project_id,
       attempt.chapter_session_id AS attempt_session_id,
       attempt.draft_candidate_id AS attempt_candidate_id,
       attempt.candidate_hash AS attempt_candidate_hash,
       attempt.status AS attempt_status,
       attempt.expected_canon_revision AS attempt_expected_canon,
       attempt.expected_planning_hash AS attempt_planning_hash,
       attempt.expected_outline_hash AS attempt_outline_hash,
       attempt.current_revision AS attempt_current_revision,
       attempt.current_revision_hash AS attempt_current_hash,
       attempt.confirmed_revision AS attempt_confirmed_revision,
       attempt.confirmed_revision_hash AS attempt_confirmed_hash,
       attempt.context_manifest_json AS context_manifest_json,
       attempt.context_manifest_hash AS attempt_context_hash,
       attempt.quality_report_id AS attempt_quality_id,
       revision.project_id AS revision_project_id,
       revision.change_set_id AS revision_change_set_id,
       revision.revision AS revision_number, revision.content_hash AS revision_hash,
       revision.payload_json AS payload_json,
       report.id AS quality_id, report.project_id AS quality_project_id,
       report.chapter_session_id AS quality_session_id,
       report.draft_candidate_id AS quality_candidate_id,
       report.candidate_hash AS quality_candidate_hash,
       report.expected_canon_revision AS quality_expected_canon,
       report.expected_planning_hash AS quality_planning_hash,
       report.expected_outline_hash AS quality_outline_hash,
       report.context_manifest_hash AS quality_context_hash,
       report.status AS quality_status, report.content_hash AS quality_hash,
       report.deterministic_blocks_json, report.findings_json,
       canon.project_id AS canon_project_id, canon.revision_number AS canon_revision,
       canon.source_id AS canon_source_id, canon.source_type AS canon_source_type
  FROM projects project
{_AUTHORITY_JOINS}
  LEFT JOIN finalization_records record
    ON record.project_id=final.project_id AND record.id=final.finalization_record_id
  LEFT JOIN finalization_change_sets attempt
    ON attempt.project_id=record.project_id AND attempt.id=record.change_set_id
  LEFT JOIN finalization_change_set_revisions revision
    ON revision.project_id=record.project_id AND revision.change_set_id=record.change_set_id
   AND revision.revision=record.change_set_revision AND revision.content_hash=record.change_set_hash
  LEFT JOIN candidate_quality_reports report
    ON report.project_id=attempt.project_id AND report.id=attempt.quality_report_id
  LEFT JOIN canon_revisions canon
    ON canon.project_id=record.project_id AND canon.revision_number=record.committed_canon_revision
 WHERE project.id=%s AND final.chapter_num=%s
 ORDER BY final.id LIMIT 2
"""


class WorkbenchReviewRepository:
    async def project(self, session, project_id):
        return await session.fetchone('SELECT id FROM projects WHERE id=%s', (project_id,))

    async def chapter(self, session, project_id, number):
        rows = await session.fetchall(_REVIEW_SELECT, (project_id, number))
        if len(rows) > 1:
            raise ValueError('ambiguous finalized chapter')
        return rows[0] if rows else None

    async def entities(self, session, project_id, revision, ids):
        if not ids:
            return []
        if len(ids) > 2560:
            raise ValueError('entity set exceeds review bounds')
        placeholders = ','.join('%s' for _ in ids)
        return await session.fetchall(
            f'''SELECT id, project_id, canonical_name FROM canon_entities
                WHERE project_id=%s AND created_revision<=%s AND id IN ({placeholders})
                ORDER BY id LIMIT 2561''',
            (project_id, revision, *ids),
        )
