from contextlib import asynccontextmanager

import aiomysql
import pytest

from backend.repositories.workbench_reviews import WorkbenchReviewRepository
from backend.services.workbench_reviews import WorkbenchReviewReader, WorkbenchReviewMissing
from backend.tests.integration.test_manuscript_repository_mysql import _seed_three_chapters
from backend.tests.integration.test_atomic_finalization_mysql import PROJECT_ID, ATTEMPT_ID
from backend.tests.support.disposable_mysql import _TestDatabaseSession


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_review_reads_committed_revision_after_a_later_failed_attempt_without_writes(disposable_mysql):
    connection = await _seed_three_chapters(disposable_mysql)
    @asynccontextmanager
    async def readonly():
        raw = await aiomysql.connect(**{**disposable_mysql.connection_config, 'autocommit': False})
        session = _TestDatabaseSession(raw)
        try:
            await session.execute('START TRANSACTION READ ONLY')
            yield session
        finally:
            await raw.rollback()
            raw.close()
    async with connection() as session:
        await session.execute('''INSERT INTO finalization_change_sets
            (id,project_id,chapter_session_id,draft_candidate_id,idempotency_key,request_fingerprint,
             candidate_hash,expected_canon_revision,expected_planning_hash,expected_outline_hash,
             context_manifest_json,context_manifest_hash,status,created_at,updated_at)
            SELECT %s,project_id,chapter_session_id,draft_candidate_id,%s,request_fingerprint,
             candidate_hash,expected_canon_revision,expected_planning_hash,expected_outline_hash,
             context_manifest_json,context_manifest_hash,'failed',created_at+100,updated_at+100
            FROM finalization_change_sets WHERE id=%s AND project_id=%s''',
            ('99000000-0000-4000-8000-000000000001', '9' * 64, ATTEMPT_ID, PROJECT_ID))
        await session.execute('''INSERT INTO projects
            (id,title,genre,description,target_words,target_chapters,status,current_chapter,created_at,updated_at)
            SELECT %s,title,genre,description,target_words,target_chapters,status,current_chapter,created_at,updated_at
            FROM projects WHERE id=%s''', ('99000000-0000-4000-8000-000000000002', PROJECT_ID))
        before = await session.fetchone('SELECT COUNT(*) AS total FROM finalization_change_sets WHERE project_id=%s', (PROJECT_ID,))
    reader = WorkbenchReviewReader(WorkbenchReviewRepository(), readonly)
    result = await reader.review(PROJECT_ID, 1)
    assert result.summary == '主角成功入城。'
    assert result.canonEvents[0]['entityName'] == '守门人'
    assert result.canonEvents[0]['evidence']['verified'] is True
    assert result.storyProgressEvents[0]['targetTitle']
    assert result.planningPatches[0]['targetTitle']
    assert result.qualityReport['status'] == 'completed'
    with pytest.raises(WorkbenchReviewMissing):
        await reader.review(PROJECT_ID, 4)
    with pytest.raises(WorkbenchReviewMissing):
        await reader.review('99000000-0000-4000-8000-000000000002', 1)
    async with readonly() as session:
        after = await session.fetchone('SELECT COUNT(*) AS total FROM finalization_change_sets WHERE project_id=%s', (PROJECT_ID,))
        assert before == after
        with pytest.raises(aiomysql.OperationalError):
            await session.execute('UPDATE projects SET title=title WHERE id=%s', (PROJECT_ID,))
