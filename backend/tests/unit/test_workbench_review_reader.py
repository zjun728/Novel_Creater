import copy
from contextlib import asynccontextmanager

import pytest

from backend.domain.finalization import FinalizationChangeSet, change_set_hash, change_set_payload
from backend.domain.json_contracts import canonical_hash
from backend.domain.manuscripts import ManuscriptCorrupt
from backend.repositories.workbench_reviews import WorkbenchReviewRepository
from backend.services.workbench import WorkbenchProjectMissing
from backend.services.workbench_reviews import WorkbenchReviewReader, WorkbenchReviewMissing
from backend.tests.integration.test_atomic_finalization_mysql import _change_set
from backend.tests.unit.test_manuscript_repository import _target_row
from backend.tests.unit.test_novel_download_repository import _planning


def review_row():
    planning = _planning()
    row = _target_row(planning=planning)
    changes = _change_set(planning, row['final_content'])
    payload = change_set_payload(changes)
    quality = {'status': 'completed', 'deterministicBlocks': [], 'findings': [{
        'id': 'finding', 'dimension': 'dialogue_credibility', 'reason': '对白仍可完善。',
        'suggestedAction': '后续章节注意人物语气。', 'evidence': payload['canonEvents'][0]['evidence'],
    }]}
    row.update(
        final_finalization_id='record', final_candidate_id='candidate', final_canon_revision=1,
        record_id='record', record_project_id='project-id', record_session_id='session-1',
        record_candidate_id='candidate', record_candidate_hash=row['final_content_hash'],
        record_change_set_id='attempt', record_revision=1, record_hash=change_set_hash(changes),
        record_expected_canon=0, record_committed_canon=1,
        attempt_id='attempt', attempt_project_id='project-id', attempt_session_id='session-1',
        attempt_candidate_id='candidate', attempt_candidate_hash=row['final_content_hash'],
        attempt_status='committed', attempt_expected_canon=0,
        attempt_planning_hash=row['final_planning_hash'], attempt_outline_hash=row['final_outline_hash'],
        attempt_current_revision=1, attempt_current_hash=change_set_hash(changes),
        attempt_confirmed_revision=1, attempt_confirmed_hash=change_set_hash(changes),
        context_manifest_json={'chapter': 1}, attempt_context_hash=canonical_hash({'chapter': 1}),
        attempt_quality_id='quality', revision_project_id='project-id', revision_change_set_id='attempt',
        revision_number=1, revision_hash=change_set_hash(changes), payload_json=payload,
        quality_id='quality', quality_project_id='project-id', quality_session_id='session-1',
        quality_candidate_id='candidate', quality_candidate_hash=row['final_content_hash'],
        quality_expected_canon=0, quality_planning_hash=row['final_planning_hash'],
        quality_outline_hash=row['final_outline_hash'], quality_context_hash=canonical_hash({'chapter': 1}),
        quality_status=quality['status'], quality_hash=canonical_hash(quality),
        deterministic_blocks_json=[], findings_json=quality['findings'],
        canon_project_id='project-id', canon_revision=1, canon_source_id='attempt', canon_source_type='finalization',
    )
    return row


class Repository:
    exists = True

    def __init__(self):
        self.row = review_row()
        self.entity_rows = [{'id': '30000000-0000-4000-8000-000000000001', 'project_id': 'project-id', 'canonical_name': '守门人'}]
        self.calls = []

    async def project(self, session, project_id):
        self.calls.append(('project', session, project_id))
        return {'id': project_id} if self.exists else None

    async def chapter(self, session, project_id, number):
        self.calls.append(('chapter', session, project_id, number))
        return self.row

    async def entities(self, session, project_id, revision, ids):
        self.calls.append(('entities', session, project_id, revision, ids))
        return self.entity_rows


@asynccontextmanager
async def connection():
    yield 'single-read-snapshot'


@pytest.mark.asyncio
async def test_review_is_single_snapshot_with_pinned_names_and_verified_evidence():
    repo = Repository()
    result = (await WorkbenchReviewReader(repo, connection).review('project-id', 1)).model_dump()
    assert result['finalizationId'] == 'record' and result['canonRevision'] == 1
    assert result['canonEvents'][0]['entityName'] == '守门人'
    assert [item['targetTitle'] for item in result['storyProgressEvents']] == ['故事块', '任务']
    assert result['planningPatches'][0]['targetTitle'] == '主线'
    for item in (*result['canonEvents'], *result['storyProgressEvents'], *result['planningPatches'], *result['qualityReport']['findings']):
        assert item['evidence']['verified'] is True
        assert item['evidence']['excerpt'] == '最终'
    assert all(call[1] == 'single-read-snapshot' for call in repo.calls)
    assert set(result) == {'projectId', 'chapterNumber', 'finalizationId', 'canonRevision', 'summary', 'qualityReport', 'findingDecisions', 'canonEvents', 'storyProgressEvents', 'planningPatches'}
    assert 'final_content' not in result and 'context_manifest_json' not in result


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [
    ('record_project_id', 'another-project'), ('record_session_id', 'other-session'),
    ('revision_project_id', 'another-project'), ('quality_candidate_id', 'other-candidate'),
    ('record_revision', 2), ('attempt_confirmed_hash', '0' * 64),
    ('attempt_status', 'awaiting_author'), ('canon_source_id', 'other-attempt'),
    ('canon_source_type', 'manual_test'), ('final_content', '篡改正文'),
    ('quality_hash', '0' * 64), ('context_manifest_json', {'chapter': 2}),
    ('payload_json', {'summary': 'broken'}), ('quality_outline_hash', '0' * 64),
])
async def test_pins_and_persisted_hashes_fail_closed(field, value):
    repo = Repository()
    repo.row[field] = value
    with pytest.raises((ValueError, ManuscriptCorrupt)):
        await WorkbenchReviewReader(repo, connection).review('project-id', 1)


def _replace_changes(repo, mutate):
    payload = copy.deepcopy(repo.row['payload_json'])
    mutate(payload)
    changes = FinalizationChangeSet.model_validate(payload)
    repo.row['payload_json'] = payload
    for key in ('record_hash', 'revision_hash', 'attempt_current_hash', 'attempt_confirmed_hash'):
        repo.row[key] = change_set_hash(changes)


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['evidence', 'target', 'patch_pin'])
async def test_valid_json_hash_does_not_make_false_evidence_or_planning_authoritative(mutation):
    repo = Repository()
    def mutate(payload):
        if mutation == 'evidence':
            payload['canonEvents'][0]['evidence']['excerptHash'] = '0' * 64
        elif mutation == 'target':
            payload['storyProgressEvents'][0]['targetId'] = 'nonexistent'
        else:
            payload['planningPatches'][0]['expectedRevision'] += 1
    _replace_changes(repo, mutate)
    with pytest.raises(ValueError):
        await WorkbenchReviewReader(repo, connection).review('project-id', 1)


@pytest.mark.asyncio
async def test_missing_project_current_chapter_and_cross_project_entities_are_distinct():
    repo = Repository()
    repo.exists = False
    with pytest.raises(WorkbenchProjectMissing):
        await WorkbenchReviewReader(repo, connection).review('missing', 1)
    assert len(repo.calls) == 1
    repo.exists = True
    repo.row = None
    with pytest.raises(WorkbenchReviewMissing):
        await WorkbenchReviewReader(repo, connection).review('project-id', 4)
    repo.row = review_row()
    repo.entity_rows[0]['project_id'] = 'another-project'
    with pytest.raises(ValueError):
        await WorkbenchReviewReader(repo, connection).review('project-id', 1)


@pytest.mark.asyncio
async def test_quality_evidence_is_verified_after_its_own_document_hash():
    repo = Repository()
    repo.row['findings_json'] = copy.deepcopy(repo.row['findings_json'])
    repo.row['findings_json'][0]['evidence']['endScalar'] = 1000
    quality = {'status': repo.row['quality_status'], 'deterministicBlocks': [], 'findings': repo.row['findings_json']}
    repo.row['quality_hash'] = canonical_hash(quality)
    with pytest.raises(ValueError):
        await WorkbenchReviewReader(repo, connection).review('project-id', 1)


@pytest.mark.asyncio
async def test_incomplete_quality_is_explicit_and_never_fabricates_findings():
    repo = Repository()
    quality = {'status': 'quality_not_completed', 'deterministicBlocks': [], 'findings': []}
    repo.row.update(quality_status=quality['status'], findings_json=[], quality_hash=canonical_hash(quality))
    result = await WorkbenchReviewReader(repo, connection).review('project-id', 1)
    assert result.qualityReport['status'] == 'quality_not_completed'
    assert result.qualityReport['findings'] == []


@pytest.mark.asyncio
async def test_entityless_fact_has_no_inferred_person_name():
    repo = Repository()
    _replace_changes(repo, lambda payload: payload['canonEvents'][0].update(entityId=None))
    result = await WorkbenchReviewReader(repo, connection).review('project-id', 1)
    assert result.canonEvents[0]['entityName'] is None


@pytest.mark.asyncio
async def test_repository_queries_one_fixed_revision_and_bounded_explicit_entities():
    class Session:
        def __init__(self):
            self.calls = []
        async def fetchall(self, sql, args):
            self.calls.append((' '.join(sql.split()), args))
            return []
    session = Session()
    repo = WorkbenchReviewRepository()
    assert await repo.chapter(session, 'p', 7) is None
    sql, args = session.calls[0]
    assert args == ('p', 7)
    assert 'final.chapter_num=%s' in sql and 'LIMIT 2' in sql
    assert 'revision.revision=record.change_set_revision' in sql
    assert 'revision.content_hash=record.change_set_hash' in sql
    assert 'ORDER BY attempt.created_at' not in sql
    assert 'provider' not in sql.lower()
    await repo.entities(session, 'p', 8, ('one', 'two'))
    assert session.calls[1][1] == ('p', 8, 'one', 'two')
    assert 'project_id=%s' in session.calls[1][0] and 'LIMIT 2561' in session.calls[1][0]
    with pytest.raises(ValueError):
        await repo.entities(session, 'p', 8, tuple(map(str, range(2561))))

    class DuplicateSession:
        async def fetchall(self, sql, args):
            return [review_row(), review_row()]
    with pytest.raises(ValueError):
        await repo.chapter(DuplicateSession(), 'p', 7)


@pytest.mark.asyncio
async def test_scoped_committed_entity_is_read_without_rewriting_review():
    from backend.domain.finalization_identity import finalization_storage_id
    repo = Repository()
    original = copy.deepcopy(repo.row)
    raw_id = repo.entity_rows[0]["id"]
    repo.entity_rows[0]["id"] = finalization_storage_id("project-id", "attempt", "entity", raw_id)
    result = (await WorkbenchReviewReader(repo, connection).review("project-id", 1)).model_dump()
    assert result["canonEvents"][0]["entityName"] == repo.entity_rows[0]["canonical_name"]
    assert repo.row == original


@pytest.mark.asyncio
async def test_entity_scoped_to_another_attempt_is_rejected():
    from backend.domain.finalization_identity import finalization_storage_id
    repo = Repository()
    repo.entity_rows[0]["id"] = finalization_storage_id("project-id", "other-attempt", "entity", repo.entity_rows[0]["id"])
    with pytest.raises(ValueError, match="entities are incomplete"):
        await WorkbenchReviewReader(repo, connection).review("project-id", 1)
