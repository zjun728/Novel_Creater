from contextlib import asynccontextmanager

import pytest

from backend.services.workbench import WorkbenchReader, WorkbenchProjectMissing


@asynccontextmanager
async def connection():
    yield object()


class Repository:
    archived = None
    active = None
    maximum = 0
    synchronized = True
    bundle = None
    busy = False
    exists = True

    async def project(self, *args):
        return {'archived_at': self.archived} if self.exists else None

    async def read_active_session(self, *args):
        return self.active

    async def read_max_final_chapter_number(self, *args):
        return self.maximum

    async def read_projection_head(self, *args):
        return {'canon_revision_number': 3, 'projection_revision_number': 3 if self.synchronized else 2}

    async def current_bundle(self, *args):
        return self.bundle

    async def finalization_busy(self, *args):
        return self.busy

    async def historical(self, session, project_id, number):
        return {**BUNDLE, 'final_chapter': {'id': 'final', 'chapter_number': number, 'content_hash': 'a' * 64}}

    async def volume_summaries(self, *args):
        return [{'id': 'volume', 'volume_order': 1, 'title': '第一卷', 'chapter_count': self.maximum,
                 'first_chapter': 1 if self.maximum else None, 'last_chapter': self.maximum or None}]

    async def planned_volumes(self, *args):
        return []

    async def chapter_page(self, session, project_id, volume_id, after, limit):
        self.page_limit = limit
        return [{'chapter_number': n, 'title': f'第 {n} 章', 'mode': 'historical',
                 'scalar_count': 100, 'finalized_at_ms': 1, 'final_chapter_id': str(n)}
                for n in range(after + 1, min(after + limit, self.maximum) + 1)]


BUNDLE = {'volume': {'id': 'volume', 'order': 1, 'title': '第一卷'},
          'outline': {'id': 'outline', 'revision': 1, 'content_hash': 'a' * 64}}


@pytest.mark.asyncio
async def test_empty_project_needs_outline_and_does_not_create_a_session():
    result = await WorkbenchReader(Repository(), connection).bootstrap('p', 1)
    assert result.mode == 'current' and result.session is None
    assert result.available_actions == ()
    assert {item.code for item in result.blocked_reasons} == {'outline_required', 'session_not_created'}


@pytest.mark.asyncio
async def test_historical_and_future_never_offer_write_actions():
    repo = Repository()
    repo.maximum = 3
    reader = WorkbenchReader(repo, connection)
    old = await reader.bootstrap('p', 2)
    future = await reader.bootstrap('p', 5)
    assert old.available_actions == ('view_chapter', 'view_outline')
    assert old.session is None and old.final_chapter.chapter_number == 2
    assert future.available_actions == () and future.outline is None


@pytest.mark.asyncio
@pytest.mark.parametrize('archived,synchronized,can_create', [(None, True, True), (1, True, False), (None, False, False)])
async def test_create_availability_requires_active_synced_project(archived, synchronized, can_create):
    repo = Repository()
    repo.bundle = BUNDLE
    repo.archived = archived
    repo.synchronized = synchronized
    result = await WorkbenchReader(repo, connection).bootstrap('p', 1)
    assert ('create_session' in result.available_actions) is can_create


@pytest.mark.asyncio
async def test_existing_audit_and_unsynchronized_heads_limit_active_session_actions():
    repo = Repository()
    repo.active = {'id': 'session', 'chapter_num': 1}
    repo.bundle = BUNDLE
    repo.busy = True
    result = await WorkbenchReader(repo, connection).bootstrap('p', 1)
    assert 'audit_candidate' not in result.available_actions
    repo.synchronized = False
    result = await WorkbenchReader(repo, connection).bootstrap('p', 1)
    assert not {'run_ai_operation', 'audit_candidate', 'finalize_candidate'} & set(result.available_actions)
    assert 'edit_draft' in result.available_actions


@pytest.mark.asyncio
async def test_missing_project_and_contradictory_session_fail_closed():
    repo = Repository()
    repo.exists = False
    with pytest.raises(WorkbenchProjectMissing):
        await WorkbenchReader(repo, connection).bootstrap('p', 1)
    repo.exists = True
    repo.active = {'id': 'session', 'chapter_num': 4}
    with pytest.raises(ValueError, match='contradicts'):
        await WorkbenchReader(repo, connection).bootstrap('p', 4)


@pytest.mark.asyncio
async def test_thousand_chapter_index_is_bounded_and_current_is_last():
    repo = Repository()
    repo.maximum = 1001
    repo.bundle = BUNDLE
    reader = WorkbenchReader(repo, connection)
    page = await reader.chapters('p', 'volume', limit=100)
    assert len(page.chapters) == 100 and repo.page_limit == 101
    assert page.next_cursor == '3:3:1002:100'
    page = await reader.chapters('p', 'volume', limit=100, cursor='3:3:1002:1000')
    assert [item.chapter_number for item in page.chapters] == [1001, 1002]
    assert page.chapters[-1].mode == 'current' and page.next_cursor is None
    with pytest.raises(ValueError, match='snapshot'):
        await reader.chapters('p', 'volume', cursor='2:2:1002:100')
