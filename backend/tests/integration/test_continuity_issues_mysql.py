"""Issue writes on isolated databases with real finalization authorities."""

import asyncio
from contextlib import asynccontextmanager

import aiomysql
import pytest

from backend.domain.continuity_issues import (
    ContinuityIssueConflict, ContinuityIssueNotFound, ContinuityIssueSourceInvalid,
    CreateContinuityIssue, UpdateContinuityIssue,
)
from backend.http_errors import ProjectArchived
from backend.repositories.continuity_issues import ContinuityIssueRepository
from backend.services.continuity_issues import ContinuityIssueService
from backend.tests.integration.test_atomic_finalization_mysql import PROJECT_ID
from backend.tests.integration.test_manuscript_repository_mysql import _seed_three_chapters
from backend.tests.support.disposable_mysql import _TestDatabaseSession


ISSUE_ID = '98000000-0000-4000-8000-000000000001'
OTHER_PROJECT = '98000000-0000-4000-8000-000000000002'
SECOND_ISSUE = '98000000-0000-4000-8000-000000000003'


def _request(**changes):
    return CreateContinuityIssue(**({'id': ISSUE_ID, 'category': 'fact', 'severity': 'high',
        'description': '第一章与后文已发生事实冲突', 'suggestion': '后续解释原因',
        'futureTarget': '第四章补充解释', 'sourceChapterNumber': 1} | changes))


def _reader_factory(database):
    @asynccontextmanager
    async def readonly():
        raw = await aiomysql.connect(**{**database.connection_config, 'autocommit': False})
        session = _TestDatabaseSession(raw)
        try:
            await session.execute('START TRANSACTION READ ONLY')
            yield session
        finally:
            await raw.rollback()
            raw.close()
    return readonly


def _service(connection, database):
    return ContinuityIssueService(ContinuityIssueRepository(), transaction_factory=connection,
                                  connection_factory=_reader_factory(database), clock=lambda: 100)


async def _other_project(session):
    await session.execute('''INSERT INTO projects
        (id,title,genre,description,target_words,target_chapters,status,current_chapter,created_at,updated_at)
        SELECT %s,title,genre,description,target_words,target_chapters,status,current_chapter,created_at,updated_at
        FROM projects WHERE id=%s''', (OTHER_PROJECT, PROJECT_ID))


async def _authority_snapshot(session):
    snapshot = {}
    for table in (
        'canon_entities', 'entity_aliases', 'canon_revisions', 'canon_events',
        'projection_heads', 'current_state_projections', 'arc_projections', 'memory_views',
        'plot_thread_projections', 'planning_revisions', 'project_planning_heads',
        'chapter_outline_revisions', 'chapter_sessions', 'finalization_records',
        'finalization_change_sets', 'finalization_change_set_revisions', 'final_chapters',
    ):
        rows = await session.fetchall(f'SELECT * FROM {table} WHERE project_id=%s', (PROJECT_ID,))
        snapshot[table] = sorted(rows, key=lambda row: repr(sorted(row.items())))
    return snapshot


@pytest.mark.mysql
async def test_issue_lifecycle_retry_paging_archive_and_no_authority_writes(disposable_mysql):
    connection = await _seed_three_chapters(disposable_mysql)
    sut = _service(connection, disposable_mysql)
    async with connection() as session:
        before = await _authority_snapshot(session)
        final = await session.fetchone('''SELECT finalization_record_id,canon_revision FROM final_chapters
            WHERE project_id=%s AND chapter_num=1''', (PROJECT_ID,))
        await _other_project(session)
    created = await sut.create(PROJECT_ID, _request())
    assert created['sourceFinalizationId'] == final['finalization_record_id']
    assert created['sourceCanonRevision'] == final['canon_revision']
    assert await sut.get(PROJECT_ID, ISSUE_ID) == created
    resolved = await sut.update(PROJECT_ID, ISSUE_ID, UpdateContinuityIssue(
        status='resolved', resolutionNote='已在第四章解释原因', expectedUpdatedAt=100))
    assert resolved['updatedAt'] == 101
    assert await sut.create(PROJECT_ID, _request()) == resolved
    with pytest.raises(ContinuityIssueConflict):
        await sut.create(PROJECT_ID, _request(description='不同原始说明'))
    with pytest.raises(ContinuityIssueConflict):
        await sut.create(OTHER_PROJECT, _request(sourceChapterNumber=None))
    with pytest.raises(ContinuityIssueNotFound):
        await sut.get(OTHER_PROJECT, ISSUE_ID)
    assert (await sut.list(OTHER_PROJECT))['items'] == []
    manual = await sut.create(PROJECT_ID, _request(id=SECOND_ISSUE, sourceChapterNumber=None))
    assert manual['sourceFinalizationId'] is None
    page = await sut.list(PROJECT_ID, limit=1)
    assert len(page['items']) == 1 and page['nextOffset'] == 1
    assert (await sut.list(PROJECT_ID, offset=1, limit=1))['nextOffset'] is None
    assert (await sut.list(PROJECT_ID, status='resolved'))['items'] == [resolved]
    async with connection() as session:
        assert await _authority_snapshot(session) == before
        await session.execute('UPDATE projects SET archived_at=200 WHERE id=%s', (PROJECT_ID,))
    assert (await sut.list(PROJECT_ID))['lifecycle'] == 'archived'
    assert (await sut.get(PROJECT_ID, ISSUE_ID))['lifecycle'] == 'archived'
    with pytest.raises(ProjectArchived):
        await sut.create(PROJECT_ID, _request())
    with pytest.raises(ProjectArchived):
        await sut.update(PROJECT_ID, ISSUE_ID, UpdateContinuityIssue(status='pending', expectedUpdatedAt=101))
    async with connection() as session:
        rows = await session.fetchall('SELECT id,status,updated_at FROM continuity_issues WHERE project_id=%s', (PROJECT_ID,))
        assert len(rows) == 2


@pytest.mark.mysql
async def test_formal_source_rejects_foreign_missing_and_inconsistent_links(disposable_mysql):
    connection = await _seed_three_chapters(disposable_mysql)
    sut = _service(connection, disposable_mysql)
    repo = ContinuityIssueRepository()
    async with connection() as session:
        await _other_project(session)
        final = await session.fetchone('SELECT * FROM final_chapters WHERE project_id=%s AND chapter_num=1', (PROJECT_ID,))
        source = await repo.source_for_chapter(session, PROJECT_ID, 1)
    assert source is not None
    for project_id, number in ((OTHER_PROJECT, 1), (PROJECT_ID, 999)):
        with pytest.raises(ContinuityIssueSourceInvalid):
            await sut.create(project_id, _request(sourceChapterNumber=number))

    # All three individual references can exist while describing different
    # formal outcomes; the source query must verify their relationship.
    async with connection() as session:
        await session.execute('''INSERT INTO canon_revisions
            (id,project_id,revision_number,parent_revision_number,idempotency_key,source_type,source_id,content_hash,created_at)
            SELECT %s,project_id,2,1,%s,source_type,source_id,content_hash,created_at+1
            FROM canon_revisions WHERE project_id=%s AND revision_number=%s''',
            ('98000000-0000-4000-8000-000000000004', '9' * 64, PROJECT_ID, final['canon_revision']))
        await session.execute('UPDATE final_chapters SET canon_revision=2 WHERE project_id=%s AND id=%s', (PROJECT_ID, final['id']))
    with pytest.raises(ContinuityIssueSourceInvalid):
        await sut.create(PROJECT_ID, _request())
    async with connection() as session:
        await session.execute('UPDATE final_chapters SET canon_revision=%s WHERE project_id=%s AND id=%s',
                              (final['canon_revision'], PROJECT_ID, final['id']))
        canon = await session.fetchone('SELECT source_id FROM canon_revisions WHERE project_id=%s AND revision_number=%s',
                                        (PROJECT_ID, final['canon_revision']))
        await session.execute("UPDATE canon_revisions SET source_type='manual_test',source_id=NULL WHERE project_id=%s AND revision_number=%s",
                              (PROJECT_ID, final['canon_revision']))
    with pytest.raises(ContinuityIssueSourceInvalid):
        await sut.create(PROJECT_ID, _request())
    async with connection() as session:
        await session.execute("UPDATE canon_revisions SET source_type='finalization',source_id=%s WHERE project_id=%s AND revision_number=%s",
                              (canon['source_id'], PROJECT_ID, final['canon_revision']))
        second = await session.fetchone('SELECT draft_candidate_id FROM final_chapters WHERE project_id=%s AND chapter_num=2', (PROJECT_ID,))
        # Use the second session's valid candidate after removing its final row
        # to satisfy the unique candidate constraint while breaking the record link.
        await session.execute('DELETE FROM final_chapters WHERE project_id=%s AND chapter_num=2', (PROJECT_ID,))
        await session.execute('UPDATE final_chapters SET draft_candidate_id=%s WHERE project_id=%s AND id=%s',
                              (second['draft_candidate_id'], PROJECT_ID, final['id']))
    with pytest.raises(ContinuityIssueSourceInvalid):
        await sut.create(PROJECT_ID, _request())
    async with connection() as session:
        await session.execute('UPDATE final_chapters SET draft_candidate_id=%s WHERE project_id=%s AND id=%s',
                              (final['draft_candidate_id'], PROJECT_ID, final['id']))
        assert await repo.source_for_chapter(session, PROJECT_ID, 1) == source
        assert not await session.fetchall('SELECT id FROM continuity_issues')
    created = await sut.create(PROJECT_ID, _request())
    assert created['status'] == 'pending'
    async with connection() as session:
        row = await repo.get(session, PROJECT_ID, ISSUE_ID)
        # Both finalization and canon FKs are composite with project identity.
        foreign = {**row, 'id': SECOND_ISSUE, 'project_id': OTHER_PROJECT}
        with pytest.raises(aiomysql.IntegrityError) as error:
            await repo.insert(session, foreign)
        assert error.value.args[0] == 1452


@pytest.mark.mysql
async def test_concurrent_create_is_single_and_status_update_cas_has_one_winner(disposable_mysql):
    connection = await _seed_three_chapters(disposable_mysql)
    sut = _service(connection, disposable_mysql)
    first, retry = await asyncio.gather(sut.create(PROJECT_ID, _request()), sut.create(PROJECT_ID, _request()))
    assert first == retry
    outcomes = await asyncio.gather(*[
        sut.update(PROJECT_ID, ISSUE_ID, UpdateContinuityIssue(
            status=status, resolutionNote='并发处理说明', expectedUpdatedAt=100))
        for status in ('resolved', 'ignored')
    ], return_exceptions=True)
    assert sum(isinstance(item, ContinuityIssueConflict) for item in outcomes) == 1
    winner = next(item for item in outcomes if isinstance(item, dict))
    assert winner['updatedAt'] == 101 and winner['status'] in ('resolved', 'ignored')
    assert await sut.get(PROJECT_ID, ISSUE_ID) == winner
    async with connection() as session:
        count = await session.fetchone('SELECT COUNT(*) AS total FROM continuity_issues WHERE project_id=%s', (PROJECT_ID,))
        assert count['total'] == 1
