import json
import pytest
from copy import deepcopy
from backend.tests.unit.test_chapter_outline_generation_service import _service as generation_service
from backend.tests.unit.test_project_preparation import (_service, _snapshot, _selection, _current_bible_head, _current_planning_head, _current_projection, _contract)
from backend.services.planning_progress import planning_progress_reason


def authority(target_type='story_block', target_id='block-1'):
    _, repository, *_ = generation_service()
    current = deepcopy(repository.authorities)
    current.update(canon_revision=1, projection_revision=1)
    current['actual_progress'] = [{
        'revision_number':1, 'subject_key':'__global__', 'entity_id':None,
        'content_hash':current['projection_hash'], 'field_path':f'plot.progress.{target_type}.{target_id}',
        'payload_json':json.dumps({'chapterNumber':1, 'targetType':target_type, 'targetId':target_id, 'status':'completed'}),
    }]
    return current


@pytest.mark.parametrize('kind,target,expected', [
    ('story_block','block-1','activeStoryBlockCompleted'),
    ('stage','stage-1','activeStoryBlockTasksCompleted'),
    ('scene_task','task-1','activeStoryBlockTasksCompleted'),
    ('story_block','other-block',None),
])
def test_readiness_matches_generation_progress_scope(kind,target,expected):
    assert planning_progress_reason(authority(kind,target)) == expected


def test_stale_projection_is_unavailable_not_completed():
    current = authority()
    current['actual_progress'][0]['content_hash'] = 'f' * 64
    assert planning_progress_reason(current) == 'planningProgressUnavailable'


@pytest.mark.asyncio
async def test_preparation_routes_completed_block_to_planning_and_preserves_authoritative_chapter():
    snapshot = _snapshot(selection=_selection(), bible_head=_current_bible_head(),
        planning_head=_current_planning_head(), canon_projection=_current_projection(), authoritative_chapter_number=8)
    snapshot['outline_authorities'] = authority()
    service, *_ = _service(snapshot, _contract())
    result = await service.preparation('project / 一')
    assert result.next_action == 'continue_planning'
    assert result.target_path.endswith('/planning/story-blocks')
    assert 'activeStoryBlockCompleted' in result.reasons
    assert result.authoritative_chapter_number == 8
    snapshot['active_session'] = {'id':'s8','chapter_num':8,'status':'drafting'}
    assert (await service.preparation('project / 一')).next_action == 'continue_writing'


@pytest.mark.asyncio
async def test_sync_mismatch_exposes_query_only_reason():
    snapshot = _snapshot(canon_projection={'canon_revision':2,'projection_revision':1})
    service, *_ = _service(snapshot, _contract())
    assert 'canon_projection_unsynchronized' in (await service.preparation('p')).reasons

@pytest.mark.asyncio
async def test_outline_state_turns_off_generation_when_the_same_block_completes():
    from backend.tests.unit.test_chapter_outline_service import _outline_state_service
    service, repository, *_ = _outline_state_service()
    current = authority()
    repository.authorities.update(planning_content=current['planning_content'], canon_revision=1,
                                  projection_revision=1, actual_progress=[])
    repository.draft.update(canon_revision=1, projection_revision=1)
    before = await service.get_current('project-1')
    assert before.capabilities.generate is True
    current['actual_progress'][0]['content_hash'] = repository.authorities['projection_hash']
    repository.authorities['actual_progress'] = current['actual_progress']
    after = await service.get_current('project-1')
    assert after.draft.status == 'current'
    assert after.capabilities.generate is False
    assert 'activeStoryBlockCompleted' in after.reasons
