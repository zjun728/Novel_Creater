from copy import deepcopy

import pytest

from backend.domain.finalization import FinalizationChangeSet, change_set_hash
from backend.domain.json_contracts import canonical_hash
from backend.services.finalization import (
    ConfirmFinalization, CorrectFinalization, FinalizationConflict, FinalizationService,
)
from backend.tests.unit.test_finalization_commit import _planning
from backend.tests.unit.test_finalization_service import (
    FakeRepository, _awaiting_attempt, _candidate, _change_set, _command,
    _finding, _service, _snapshot,
)


def _inputs():
    planning = _planning()
    snapshot = _snapshot()
    snapshot['planning_context']['content'] = planning.model_dump(by_alias=True, mode='json')
    snapshot['planning_context']['protectedNodeIds'] = ['block-1', 'stage-1', 'task-1', 'volume-1']
    payload = _change_set().model_dump(by_alias=True, mode='json')
    payload['planningPatches'] = [{
        'id': 'protected-patch', 'targetType': 'story_block', 'targetId': 'block-1',
        'expectedRevision': planning.story_blocks[0].revision,
        'expectedHash': planning.story_blocks[0].content_hash,
        'fieldPath': 'expectedChange', 'replacement': '已经进入城中。',
        'evidence': _finding().evidence.model_dump(by_alias=True, mode='json'),
    }, {
        'id': 'future-patch', 'targetType': 'plot', 'targetId': 'plot-1',
        'expectedRevision': planning.plots[0].revision,
        'expectedHash': planning.plots[0].content_hash,
        'fieldPath': 'futureDirection', 'replacement': '寻找接头人。',
        'evidence': _finding().evidence.model_dump(by_alias=True, mode='json'),
    }]
    payload['storyProgressEvents'] = [{
        'id': 'progress', 'targetType': 'story_block', 'targetId': 'block-1',
        'status': 'advanced', 'evidence': payload['planningPatches'][0]['evidence'],
    }]
    return snapshot, payload


@pytest.mark.asyncio
async def test_prepare_demotes_only_protected_patches_and_preserves_progress_and_evidence():
    snapshot, payload = _inputs()
    original = FinalizationChangeSet.model_validate(payload)
    repository = FakeRepository(snapshots=[snapshot, deepcopy(snapshot)])
    service, _, _, _ = _service(repository, extraction_result=original)
    result = await service.prepare(_command())
    assert result.status == 'awaiting_author'
    saved = repository.inserted_revisions[0]['change_set']
    assert [p.id for p in saved.planning_patches] == ['future-patch']
    assert saved.story_progress_events == original.story_progress_events
    assert saved.canon_events == original.canon_events
    suggestion, = saved.planning_suggestions
    assert suggestion.id == 'protected-patch'
    assert suggestion.target_id == 'block-1'
    assert suggestion.evidence == original.planning_patches[0].evidence
    assert all(s in suggestion.message for s in ('block-1', 'expectedChange', '已经进入城中。', '不会修改'))
    assert repository.inserted_revisions[0]['content_hash'] == change_set_hash(saved)


@pytest.mark.asyncio
@pytest.mark.parametrize('damage', ['identity', 'hash', 'evidence', 'too_long', 'too_many'])
async def test_prepare_never_launders_invalid_or_unrepresentable_protected_patch(damage):
    snapshot, payload = _inputs()
    patch = payload['planningPatches'][0]
    if damage == 'identity':
        patch['targetId'] = 'missing'
    elif damage == 'hash':
        patch['expectedHash'] = 'f' * 64
    elif damage == 'evidence':
        patch['evidence']['excerptHash'] = 'f' * 64
    elif damage == 'too_long':
        patch['replacement'] = '长' * 2000
    else:
        payload['planningSuggestions'] = [
            {'id': f's-{i}', 'targetId': None, 'message': '建议', 'evidence': patch['evidence']}
            for i in range(256)
        ]
    repository = FakeRepository(snapshots=[snapshot, deepcopy(snapshot)])
    service, _, _, _ = _service(repository, extraction_result=FinalizationChangeSet.model_validate(payload))
    result = await service.prepare(_command())
    assert result.status == 'failed'
    assert repository.inserted_revisions == repository.published == []


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['correct', 'confirm'])
async def test_review_rejects_protected_patch_before_revision_or_confirmation_write(action):
    snapshot, payload = _inputs()
    changes = FinalizationChangeSet.model_validate(payload)
    repository = FakeRepository(snapshots=[snapshot])
    attempt = _awaiting_attempt()
    attempt['context_manifest_hash'] = canonical_hash(FinalizationService._context_manifest(_command(), 1, snapshot))
    attempt['current_revision_hash'] = change_set_hash(changes)
    repository.current_attempt = attempt
    repository.current_revision = {'change_set': changes, 'content_hash': change_set_hash(changes)}
    service, _, quality, extraction = _service(repository)
    kwargs = dict(project_id='project-1', chapter_session_id='session-1', expected_revision=1,
                  expected_revision_hash=attempt['current_revision_hash'])
    command = CorrectFinalization(**kwargs, change_set=changes) if action == 'correct' else ConfirmFinalization(**kwargs)
    with pytest.raises(FinalizationConflict) as raised:
        await getattr(service, action)(command)
    assert type(raised.value).__name__ == 'FinalizationPreflightConflict'
    assert repository.inserted_revisions == repository.confirmed == repository.advanced == []
    assert quality.calls == extraction.calls == []


@pytest.mark.parametrize('value', [None, [], ['x', 'x'], ['z', 'a'], [1]])
def test_manifest_requires_explicit_canonical_protected_node_context(value):
    snapshot = _snapshot()
    if value is None:
        snapshot['planning_context'].pop('protectedNodeIds', None)
    else:
        snapshot['planning_context']['protectedNodeIds'] = value
    if value == []:
        FinalizationService._context_manifest(_command(), 1, snapshot)
    else:
        with pytest.raises(FinalizationConflict):
            FinalizationService._context_manifest(_command(), 1, snapshot)


@pytest.mark.asyncio
async def test_old_unconfirmed_manifest_is_not_silently_upgraded():
    snapshot = _snapshot()
    repository = FakeRepository(snapshots=[snapshot])
    attempt = _awaiting_attempt()
    old_manifest = FinalizationService._context_manifest(_command(), 1, snapshot)
    old_planning = dict(snapshot['planning_context'])
    old_planning.pop('protectedNodeIds')
    old_manifest['contexts']['planningHash'] = canonical_hash(old_planning)
    attempt['context_manifest_hash'] = canonical_hash(old_manifest)
    repository.current_attempt = attempt
    repository.current_revision = {'change_set': _change_set()}
    service, _, quality, extraction = _service(repository)
    with pytest.raises(FinalizationConflict) as raised:
        await service.confirm(ConfirmFinalization(
            project_id='project-1', chapter_session_id='session-1', expected_revision=1,
            expected_revision_hash=attempt['current_revision_hash'],
        ))
    assert type(raised.value).__name__ == 'FinalizationPreflightConflict'
    assert repository.confirmed == repository.inserted_revisions == []
    assert quality.calls == extraction.calls == []


@pytest.mark.asyncio
async def test_protected_set_drift_during_provider_call_rejects_publication():
    snapshot, payload = _inputs()
    changed = deepcopy(snapshot)
    changed['planning_context']['protectedNodeIds'].append('zz-historical-task')
    repository = FakeRepository(snapshots=[snapshot, changed])
    service, _, _, _ = _service(repository, extraction_result=FinalizationChangeSet.model_validate(payload))
    result = await service.prepare(_command())
    assert result.status == 'invalidated'
    assert repository.inserted_revisions == repository.published == []


def test_shared_outline_protection_matches_commit_and_rejects_corruption():
    from backend.domain.finalization_planning import protected_outline_node_ids
    from backend.services.finalization_commit import _implemented_ids
    from backend.tests.unit.test_finalization_commit import _FinalizationRepository
    outline = _FinalizationRepository(_planning(), _change_set()).outline
    history = deepcopy(outline)
    history['volumeRef']['id'] = 'historical-volume'
    values = [outline, history]
    assert protected_outline_node_ids(values) == _implemented_ids(values) == frozenset({
        'volume-1', 'historical-volume', 'block-1', 'stage-1', 'task-1',
    })
    for bad in (None, {}, {'sceneTaskRefs': []}, 'not json'):
        with pytest.raises(ValueError):
            protected_outline_node_ids([outline, bad])


def test_public_preflight_error_has_stable_sanitized_code():
    from backend.domain.routers.finalization import _raise_public
    from backend.http_errors import PublicDomainError
    from backend.services.finalization import FinalizationPreflightConflict
    with pytest.raises(PublicDomainError) as raised:
        _raise_public(FinalizationPreflightConflict('PRIVATE_CONTEXT_SENTINEL'))
    assert raised.value.status_code == 409
    assert raised.value.code == 'FinalizationPreflightConflict'
    assert 'PRIVATE_CONTEXT_SENTINEL' not in str(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('replacement', [123, '过长' * 20000], ids=['wrong-type', 'too-long'])
@pytest.mark.parametrize('action', ['prepare', 'correct', 'confirm'])
async def test_unapplicable_future_patch_never_reaches_author_confirmation(action, replacement):
    snapshot, payload = _inputs()
    payload['planningPatches'] = [payload['planningPatches'][1]]
    payload['planningPatches'][0]['replacement'] = replacement
    changes = FinalizationChangeSet.model_validate(payload)
    repository = FakeRepository(snapshots=[snapshot, deepcopy(snapshot)])
    service, _, _, _ = _service(repository, extraction_result=changes)
    if action == 'prepare':
        result = await service.prepare(_command())
        assert result.status == 'failed'
        assert repository.published == repository.inserted_revisions == []
        return
    attempt = _awaiting_attempt()
    attempt['context_manifest_hash'] = canonical_hash(FinalizationService._context_manifest(_command(), 1, snapshot))
    attempt['current_revision_hash'] = change_set_hash(changes)
    repository.current_attempt = attempt
    repository.current_revision = {'change_set': changes}
    kwargs = dict(project_id='project-1', chapter_session_id='session-1', expected_revision=1,
                  expected_revision_hash=attempt['current_revision_hash'])
    command = CorrectFinalization(**kwargs, change_set=changes) if action == 'correct' else ConfirmFinalization(**kwargs)
    with pytest.raises(FinalizationConflict) as raised:
        await getattr(service, action)(command)
    assert type(raised.value).__name__ == 'FinalizationPreflightConflict'
    assert repository.inserted_revisions == repository.confirmed == repository.advanced == []
