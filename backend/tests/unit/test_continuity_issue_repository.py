import pytest

from backend.domain.continuity_issues import ContinuityIssueSourceInvalid
from backend.http_errors import ProjectArchived
from backend.repositories.continuity_issues import ContinuityIssueRepository, ISSUE_COLUMNS


class Session:
    def __init__(self, one=None, rows=()):
        self.one, self.rows, self.calls = one, rows, []

    async def fetchone(self, sql, args):
        self.calls.append(('read', ' '.join(sql.split()), args))
        return self.one

    async def fetchall(self, sql, args):
        self.calls.append(('read', ' '.join(sql.split()), args))
        return self.rows

    async def execute(self, sql, args):
        self.calls.append(('write', ' '.join(sql.split()), args))
        return 1


async def test_all_issue_queries_are_project_scoped_and_pages_are_bounded():
    session = Session()
    repo = ContinuityIssueRepository()
    await repo.get(session, 'project', 'issue', for_update=True)
    await repo.list(session, 'project', status='pending', offset=7, limit=51)
    await repo.list(session, 'project', status=None, offset=0, limit=31)
    assert session.calls[0][1].endswith('WHERE project_id=%s AND id=%s FOR UPDATE')
    assert session.calls[0][2] == ('project', 'issue')
    assert 'WHERE project_id=%s AND status=%s ORDER BY created_at DESC, id LIMIT %s OFFSET %s' in session.calls[1][1]
    assert session.calls[1][2] == ('project', 'pending', 51, 7)
    assert session.calls[2][2] == ('project', 31, 0)


async def test_repository_mutations_only_write_issue_table_and_status_fields():
    session = Session()
    repo = ContinuityIssueRepository()
    row = {key: key for key in ISSUE_COLUMNS}
    await repo.insert(session, row)
    await repo.update(session, 'project', 'issue', status='resolved', resolution_note='理由',
                      expected_updated_at=100, updated_at=101)
    assert session.calls[0][1].startswith('INSERT INTO continuity_issues ')
    assert session.calls[0][2] == tuple(ISSUE_COLUMNS)
    assert session.calls[1][1] == ('UPDATE continuity_issues SET status=%s, resolution_note=%s, updated_at=%s '
                                    'WHERE project_id=%s AND id=%s AND updated_at=%s')
    assert session.calls[1][2] == ('resolved', '理由', 101, 'project', 'issue', 100)


async def test_source_join_proves_same_project_same_finalization_and_committed_revision():
    session = Session(rows=[{'source_chapter': 1}])
    assert await ContinuityIssueRepository().source_for_chapter(session, 'project', 1) == {'source_chapter': 1}
    _, sql, args = session.calls[0]
    for relation in (
        'record.project_id=final.project_id', 'record.id=final.finalization_record_id',
        'record.chapter_session_id=final.chapter_session_id',
        'record.draft_candidate_id=final.draft_candidate_id',
        'record.committed_canon_revision=final.canon_revision',
        'canon.project_id=record.project_id', 'canon.revision_number=record.committed_canon_revision',
        "canon.source_type='finalization'", 'canon.source_id=record.change_set_id',
        'WHERE final.project_id=%s AND final.chapter_num=%s', 'LIMIT 2',
    ):
        assert relation in sql
    assert args == ('project', 1)
    assert await ContinuityIssueRepository().source_for_chapter(Session(), 'project', 1) is None
    with pytest.raises(ContinuityIssueSourceInvalid):
        await ContinuityIssueRepository().source_for_chapter(Session(rows=[{}, {}]), 'project', 1)


async def test_repository_uses_shared_archived_guard():
    session = Session(one={'archived_at': 100})
    with pytest.raises(ProjectArchived):
        await ContinuityIssueRepository().lock_active_project(session, 'project')
    assert session.calls == [('read', 'SELECT * FROM projects WHERE id=%s FOR UPDATE', ('project',))]
