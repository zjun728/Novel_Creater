import pytest

from backend.domain.project_packages import ProjectPackageInvalid, freeze_json_value
from backend.repositories.project_packages import _rewrite_canon_progress_reference


@pytest.mark.parametrize('target_type,kind', [
    ('volume', 'planning-volume'), ('plot', 'planning-plot'),
    ('story_block', 'story-block'), ('stage', 'planning-stage'), ('scene_task', 'scene-task'),
])
def test_progress_event_exports_both_references_as_one_logical_identity(target_type, kind):
    raw_id = '40c9208e-7826-4215-97e2-7bb555929352'
    source = {'fieldPath': f'plot.progress.{target_type}.{raw_id}',
              'value': {'targetId': raw_id, 'targetType': target_type, 'status': 'completed', 'chapterNumber': 3}}
    result = _rewrite_canon_progress_reference(source, {(kind, raw_id): f'{kind}:2'})
    assert result['value']['targetId'] == f'{kind}:2'
    assert result['fieldPath'] == f'plot.progress.{target_type}.{kind}:2'
    assert result['value']['status'] == 'completed'
    assert source['value']['targetId'] == raw_id
    freeze_json_value(result)


@pytest.mark.parametrize('field,target_type,target_id', [
    ('plot.progress.scene_task.task-a', 'scene_task', 'task-b'),
    ('plot.progress.unknown.task-a', 'unknown', 'task-a'),
    ('plot.progress.scene_task.task-a', 'scene_task', 'task-a'),
])
def test_progress_event_rejects_mismatch_unknown_kind_and_missing_target(field, target_type, target_id):
    with pytest.raises(ProjectPackageInvalid):
        _rewrite_canon_progress_reference({'fieldPath': field, 'value': {
            'targetType': target_type, 'targetId': target_id, 'status': 'completed', 'chapterNumber': 3,
        }}, {})


def test_normal_story_fact_is_not_rewritten_as_a_progress_event():
    value = {'fieldPath': 'claims.destination', 'value': {'content': 'Find the old ledger'}}
    assert _rewrite_canon_progress_reference(value, {}) == value
