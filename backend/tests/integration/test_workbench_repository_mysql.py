import pytest
from hashlib import sha256

from backend.repositories.workbench import WorkbenchRepository
from backend.services.workbench import WorkbenchReader
from backend.tests.integration.test_manuscript_repository_mysql import _seed_three_chapters


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_workbench_reads_pinned_history_and_pages_without_creating_sessions(disposable_mysql):
    connection = await _seed_three_chapters(disposable_mysql)
    from backend.tests.integration.test_atomic_finalization_mysql import PROJECT_ID
    reader = WorkbenchReader(WorkbenchRepository(), connection)
    async with connection() as session:
        before = await session.fetchone('SELECT COUNT(*) AS count FROM chapter_sessions WHERE project_id=%s', (PROJECT_ID,))
    historical = await reader.bootstrap(PROJECT_ID, 1)
    assert historical.mode == 'historical'
    assert historical.available_actions == ('view_chapter', 'view_outline')
    future = await reader.bootstrap(PROJECT_ID, 5)
    assert future.mode == 'future' and future.session is None
    summary = await reader.volumes(PROJECT_ID)
    volume = summary.volumes[0].volume.id
    first = await reader.chapters(PROJECT_ID, volume, limit=2)
    second = await reader.chapters(PROJECT_ID, volume, limit=2, cursor=first.next_cursor)
    assert [item.chapter_number for item in first.chapters] == [1, 2]
    assert second.chapters[0].chapter_number == 3
    async with connection() as session:
        after = await session.fetchone('SELECT COUNT(*) AS count FROM chapter_sessions WHERE project_id=%s', (PROJECT_ID,))
    assert before == after


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_thousand_final_chapters_return_only_one_bounded_page(disposable_mysql):
    from backend.tests.integration.test_atomic_finalization_mysql import PROJECT_ID
    from backend.tests.integration.test_novel_download_repository_mysql import _insert_additional_final_chapter
    connection = await _seed_three_chapters(disposable_mysql)
    async with connection() as session:
        for number in range(4, 1002):
            prose = f'测试章节 {number}。'
            await _insert_additional_final_chapter(session, chapter_number=number, suffix=f'{number:012x}',
                                                  content=prose, persisted_hash=sha256(prose.encode()).hexdigest())
    reader = WorkbenchReader(WorkbenchRepository(), connection)
    summary = await reader.volumes(PROJECT_ID)
    assert summary.volumes[0].finalized_chapter_count == 1001
    first = await reader.chapters(PROJECT_ID, summary.volumes[0].volume.id, limit=100)
    assert len(first.chapters) == 100
    assert [item.chapter_number for item in first.chapters] == list(range(1, 101))
    second = await reader.chapters(PROJECT_ID, summary.volumes[0].volume.id, limit=100, cursor=first.next_cursor)
    assert [item.chapter_number for item in second.chapters] == list(range(101, 201))
    document = first.model_dump(mode='json')
    assert all('content' not in item and 'planning' not in item and 'outline' not in item for item in document['chapters'])
