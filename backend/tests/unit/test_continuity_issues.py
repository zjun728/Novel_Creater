from contextlib import asynccontextmanager
from copy import deepcopy

import aiomysql
import pytest
from pydantic import ValidationError

from backend.domain.continuity_issues import (
    ContinuityIssueConflict, ContinuityIssueInvalid, ContinuityIssueNotFound,
    ContinuityIssueSourceInvalid, CreateContinuityIssue, UpdateContinuityIssue,
)
from backend.http_errors import ProjectArchived, ProjectNotFound
from backend.services.continuity_issues import ContinuityIssueService


PROJECT_ID = '10000000-0000-4000-8000-000000000001'
ISSUE_ID = '20000000-0000-4000-8000-000000000001'
FINALIZATION_ID = '30000000-0000-4000-8000-000000000001'


@asynccontextmanager
async def connection():
    yield object()


class Repository:
    def __init__(self):
        self.project = {'id': PROJECT_ID, 'archived_at': None}
        self.rows = {}
        self.actions = []
        self.source = {'project_id': PROJECT_ID, 'source_chapter': 1,
                       'source_finalization_id': FINALIZATION_ID, 'source_canon_revision': 1}

    async def lock_active_project(self, session, project_id):
        self.actions.append('guard')
        if self.project and self.project['archived_at'] is not None:
            raise ProjectArchived()
        return self.project if self.project and self.project['id'] == project_id else None

    async def read_project(self, session, project_id):
        return self.project if self.project and self.project['id'] == project_id else None

    async def get(self, session, project_id, issue_id, *, for_update=False):
        self.actions.append('lock_issue' if for_update else 'get')
        row = self.rows.get(issue_id)
        return deepcopy(row) if row and row['project_id'] == project_id else None

    async def source_for_chapter(self, session, project_id, number):
        self.actions.append('source')
        return self.source if self.source and self.source['source_chapter'] == number else None

    async def insert(self, session, row):
        self.actions.append('insert')
        if row['id'] in self.rows:
            raise aiomysql.IntegrityError(1062, 'PRIVATE_DATABASE_CONSTRAINT')
        self.rows[row['id']] = deepcopy(row)

    async def update(self, session, project_id, issue_id, *, status, resolution_note, expected_updated_at, updated_at):
        self.actions.append('update')
        row = self.rows[issue_id]
        if row['project_id'] != project_id or row['updated_at'] != expected_updated_at:
            return 0
        row.update(status=status, resolution_note=resolution_note, updated_at=updated_at)
        return 1

    async def list(self, session, project_id, *, status, offset, limit):
        self.actions.append(('list', offset, limit))
        rows = [deepcopy(row) for row in self.rows.values()
                if row['project_id'] == project_id and (status is None or row['status'] == status)]
        return sorted(rows, key=lambda row: (-row['created_at'], row['id']))[offset:offset + limit]


def service(repository=None, now=100):
    return ContinuityIssueService(repository or Repository(), transaction_factory=connection,
                                  connection_factory=connection, clock=lambda: now)


def request(**changes):
    return CreateContinuityIssue(id=ISSUE_ID, category='fact', severity='medium',
                                 description='已发生事实冲突', **changes)


@pytest.mark.parametrize('changes', [
    {'id': 'arbitrary'}, {'category': 'style'}, {'severity': 'critical'},
    {'description': '  '}, {'description': '字' * 4001}, {'suggestion': ''},
    {'futureTarget': ' '}, {'sourceChapterNumber': 0}, {'sourceChapterNumber': True},
    {'sourceFinalizationId': FINALIZATION_ID}, {'source_chapter': 1},
])
def test_create_contract_is_strict_and_cannot_accept_arbitrary_source(changes):
    values = {'id': ISSUE_ID, 'category': 'fact', 'severity': 'medium', 'description': '事实冲突'}
    with pytest.raises(ValidationError):
        CreateContinuityIssue(**(values | changes))


@pytest.mark.parametrize('changes', [
    {'status': 'resolved'}, {'status': 'ignored', 'resolutionNote': ' '},
    {'status': 'closed'}, {'expectedUpdatedAt': True}, {'expectedUpdatedAt': -1},
    {'description': '不能修改原问题'}, {'futureTarget': '不能修改原目标'},
])
def test_update_contract_requires_resolution_and_keeps_creation_fields_fixed(changes):
    with pytest.raises(ValidationError):
        UpdateContinuityIssue(**({'status': 'pending', 'expectedUpdatedAt': 100} | changes))


async def test_create_retry_preserves_later_handling_and_source_is_server_resolved():
    repo = Repository()
    sut = service(repo)
    created = await sut.create(PROJECT_ID, request(sourceChapterNumber=1, futureTarget='第四章交代原因'))
    assert created['sourceFinalizationId'] == FINALIZATION_ID
    assert created['sourceCanonRevision'] == 1 and created['status'] == 'pending'
    updated = await sut.update(PROJECT_ID, ISSUE_ID, UpdateContinuityIssue(
        status='resolved', resolutionNote='第四章已解释', expectedUpdatedAt=100))
    assert updated['updatedAt'] == 101
    assert await sut.create(PROJECT_ID, request(sourceChapterNumber=1, futureTarget='第四章交代原因')) == updated
    assert repo.actions.count('insert') == 1 and repo.actions.count('source') == 1
    assert repo.actions.index('guard') < repo.actions.index('insert')
    with pytest.raises(ContinuityIssueConflict):
        await sut.create(PROJECT_ID, request(sourceChapterNumber=1, futureTarget='第五章'))


async def test_manual_source_is_empty_and_three_state_transitions_keep_creation_fields():
    repo = Repository()
    sut = service(repo, now=100)
    created = await sut.create(PROJECT_ID, request())
    assert created['sourceChapterNumber'] is created['sourceFinalizationId'] is created['sourceCanonRevision'] is None
    for index, status in enumerate(('ignored', 'pending', 'resolved'), start=1):
        updated = await sut.update(PROJECT_ID, ISSUE_ID, UpdateContinuityIssue(
            status=status, resolutionNote='作者处理结论' if status != 'pending' else None,
            expectedUpdatedAt=99 + index))
        assert updated['updatedAt'] == 100 + index and updated['status'] == status
        assert updated['description'] == created['description'] and updated['createdAt'] == 100
    assert 'source' not in repo.actions


async def test_stale_update_and_cross_project_reads_are_rejected():
    repo = Repository()
    sut = service(repo)
    await sut.create(PROJECT_ID, request())
    with pytest.raises(ContinuityIssueConflict):
        await sut.update(PROJECT_ID, ISSUE_ID, UpdateContinuityIssue(status='pending', expectedUpdatedAt=99))
    assert 'update' not in repo.actions
    with pytest.raises(ContinuityIssueNotFound):
        await sut.get(PROJECT_ID, 'missing')
    with pytest.raises(ProjectNotFound):
        await sut.get('other-project', ISSUE_ID)


async def test_update_checks_database_cas_result():
    repo = Repository()
    sut = service(repo)
    await sut.create(PROJECT_ID, request())
    async def lost_update(*args, **kwargs):
        return 0
    repo.update = lost_update
    with pytest.raises(ContinuityIssueConflict):
        await sut.update(PROJECT_ID, ISSUE_ID, UpdateContinuityIssue(status='pending', expectedUpdatedAt=100))


@pytest.mark.parametrize('source', [None, {'project_id': 'other', 'source_chapter': 1,
    'source_finalization_id': FINALIZATION_ID, 'source_canon_revision': 1}])
async def test_invalid_or_foreign_source_is_rejected(source):
    repo = Repository()
    repo.source = source
    with pytest.raises(ContinuityIssueSourceInvalid):
        await service(repo).create(PROJECT_ID, request(sourceChapterNumber=1))
    assert not repo.rows


async def test_duplicate_global_id_has_safe_conflict():
    repo = Repository()
    repo.rows[ISSUE_ID] = {'id': ISSUE_ID, 'project_id': 'other-project'}
    with pytest.raises(ContinuityIssueConflict) as error:
        await service(repo).create(PROJECT_ID, request())
    assert 'PRIVATE_' not in str(error.value)


async def test_archived_projects_allow_reads_and_stop_both_writes_at_guard():
    repo = Repository()
    sut = service(repo)
    await sut.create(PROJECT_ID, request())
    repo.project['archived_at'] = 200
    assert (await sut.get(PROJECT_ID, ISSUE_ID))['lifecycle'] == 'archived'
    assert (await sut.list(PROJECT_ID))['lifecycle'] == 'archived'
    for operation in (lambda: sut.create(PROJECT_ID, request()), lambda: sut.update(
            PROJECT_ID, ISSUE_ID, UpdateContinuityIssue(status='pending', expectedUpdatedAt=100))):
        repo.actions.clear()
        with pytest.raises(ProjectArchived):
            await operation()
        assert repo.actions == ['guard']


async def test_list_is_bounded_and_status_is_optional():
    repo = Repository()
    sut = service(repo)
    await sut.create(PROJECT_ID, request())
    await sut.create(PROJECT_ID, CreateContinuityIssue(
        id='20000000-0000-4000-8000-000000000002', category='time', severity='low', description='时间冲突'))
    page = await sut.list(PROJECT_ID, limit=1)
    assert len(page['items']) == 1 and page['nextOffset'] == 1
    assert repo.actions[-1] == ('list', 0, 2)
    assert (await sut.list(PROJECT_ID, status='resolved'))['items'] == []
    for bounds in ({'limit': 51}, {'offset': -1}, {'limit': True}, {'status': 'closed'}):
        with pytest.raises(ContinuityIssueInvalid):
            await sut.list(PROJECT_ID, **bounds)
