"""Project-scoped issue persistence; formal sources are read-only."""

from backend.repositories.project_lifecycle import lock_active_project, read_project
from backend.domain.continuity_issues import ContinuityIssueSourceInvalid


ISSUE_COLUMNS = (
    'id', 'project_id', 'category', 'severity', 'status', 'source_chapter',
    'source_finalization_id', 'source_canon_revision', 'description', 'suggestion',
    'future_target', 'resolution_note', 'created_at', 'updated_at',
)
_SELECT = ', '.join(ISSUE_COLUMNS)


class ContinuityIssueRepository:
    async def lock_active_project(self, session, project_id):
        return await lock_active_project(session, project_id)

    async def read_project(self, session, project_id):
        return await read_project(session, project_id)

    async def get(self, session, project_id, issue_id, *, for_update=False):
        lock = ' FOR UPDATE' if for_update else ''
        return await session.fetchone(
            f'SELECT {_SELECT} FROM continuity_issues WHERE project_id=%s AND id=%s{lock}',
            (project_id, issue_id),
        )

    async def list(self, session, project_id, *, status, offset, limit):
        condition = ' AND status=%s' if status is not None else ''
        args = (project_id, status) if status is not None else (project_id,)
        return await session.fetchall(
            f'''SELECT {_SELECT} FROM continuity_issues WHERE project_id=%s{condition}
                ORDER BY created_at DESC, id LIMIT %s OFFSET %s''',
            (*args, limit, offset),
        )

    async def source_for_chapter(self, session, project_id, number):
        # A matching project FK alone does not prove these references describe
        # the same committed chapter. All links must agree before returning it.
        rows = await session.fetchall(
            '''SELECT final.project_id, final.chapter_num AS source_chapter,
                      record.id AS source_finalization_id,
                      canon.revision_number AS source_canon_revision
                 FROM final_chapters final
                 JOIN finalization_records record
                   ON record.project_id=final.project_id AND record.id=final.finalization_record_id
                  AND record.chapter_session_id=final.chapter_session_id
                  AND record.draft_candidate_id=final.draft_candidate_id
                  AND record.committed_canon_revision=final.canon_revision
                 JOIN canon_revisions canon
                   ON canon.project_id=record.project_id
                  AND canon.revision_number=record.committed_canon_revision
                  AND canon.source_type='finalization' AND canon.source_id=record.change_set_id
                WHERE final.project_id=%s AND final.chapter_num=%s
                ORDER BY final.id LIMIT 2''',
            (project_id, number),
        )
        if len(rows) > 1:
            raise ContinuityIssueSourceInvalid()
        return rows[0] if rows else None

    async def insert(self, session, row):
        return await session.execute(
            f'INSERT INTO continuity_issues ({_SELECT}) VALUES ({", ".join(["%s"] * len(ISSUE_COLUMNS))})',
            tuple(row[column] for column in ISSUE_COLUMNS),
        )

    async def update(self, session, project_id, issue_id, *, status, resolution_note,
                     expected_updated_at, updated_at):
        return await session.execute(
            '''UPDATE continuity_issues SET status=%s, resolution_note=%s, updated_at=%s
               WHERE project_id=%s AND id=%s AND updated_at=%s''',
            (status, resolution_note, updated_at, project_id, issue_id, expected_updated_at),
        )
