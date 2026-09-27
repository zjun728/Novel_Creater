import pytest

from backend.domain.finalization import FinalizationChangeSet
from backend.services.finalization_checks import validate_change_set_context
from backend.tests.unit.test_finalization_checks import _change_set_context, _context_change_set, HASH_A


def fixture():
    canon, planning = _change_set_context()
    planning['content']['storyBlocks'][0]['stages'] = [{
        'id': 'stage-1', 'revision': 1, 'contentHash': HASH_A,
        'sceneTasks': [{'id': f'task-{i}', 'revision': 1, 'contentHash': HASH_A} for i in (1, 2)],
    }]
    payload = _context_change_set('正文证据').model_dump(by_alias=True, mode='json')
    event = payload['storyProgressEvents'][0]
    event['status'] = 'completed'
    payload['storyProgressEvents'] += [
        {**event, 'id': 'stage-event', 'targetType': 'stage', 'targetId': 'stage-1'},
        {**event, 'id': 'task-event', 'targetType': 'scene_task', 'targetId': 'task-1'},
    ]
    return canon, planning, payload


def validate(canon, planning, payload):
    validate_change_set_context(FinalizationChangeSet.model_validate(payload),
                               candidate_content='正文证据', canon_context=canon, planning_context=planning)


def test_parent_cannot_complete_while_second_child_is_unfinished():
    with pytest.raises(ValueError):
        validate(*fixture())


def test_children_can_complete_in_same_review_regardless_of_event_order():
    canon, planning, payload = fixture()
    payload['storyProgressEvents'].append({**payload['storyProgressEvents'][-1], 'id': 'task2-event', 'targetId': 'task-2'})
    validate(canon, planning, payload)


def test_previous_confirmed_child_progress_can_complete_parent():
    canon, planning, payload = fixture()
    canon['actualProgress'] = [{'field_path': 'plot.progress.scene_task.task-2',
                               'payload': {'targetType': 'scene_task', 'targetId': 'task-2', 'status': 'completed'}}]
    validate(canon, planning, payload)


def test_current_child_regression_overrides_previous_completion():
    canon, planning, payload = fixture()
    canon['actualProgress'] = [{'field_path': 'plot.progress.scene_task.task-2',
                               'payload': {'targetType': 'scene_task', 'targetId': 'task-2', 'status': 'completed'}}]
    payload['storyProgressEvents'].append({**payload['storyProgressEvents'][-1], 'id': 'task2-event', 'targetId': 'task-2', 'status': 'advanced'})
    with pytest.raises(ValueError):
        validate(canon, planning, payload)


def test_generic_canon_event_cannot_bypass_progress_validation():
    canon, planning, payload = fixture()
    evidence = payload['storyProgressEvents'][0]['evidence']
    payload['storyProgressEvents'] = []
    payload['canonEvents'] = [{
        'id': 'bypass', 'entityId': None, 'factKind': 'dynamic_event',
        'fieldPath': 'plot.progress.story_block.block-1',
        'value': {'targetType': 'story_block', 'targetId': 'block-1', 'status': 'completed'},
        'evidence': evidence, 'effectiveStartChapter': 1, 'effectiveEndChapter': None,
        'assertionOperator': 'equals', 'valueCardinality': 'single',
    }]
    with pytest.raises(ValueError):
        validate(canon, planning, payload)
