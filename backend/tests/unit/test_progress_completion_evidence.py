from copy import deepcopy

import pytest

from backend.gateways.finalization_provider import _parse_extraction
from backend.tests.unit.test_finalization_gateway import _extraction_payload


def payload(*, status='completed', execution='observed', unmet=None, support=None):
    value = _extraction_payload()
    value['planningSuggestions'] = []
    value['storyProgressEvents'] = [{
        'id': 'progress', 'targetType': 'scene_task', 'targetId': 'transfer', 'status': status,
        'completionBasis': {'execution': execution, 'unmetRequirements': unmet or [],
                            'supportingParagraphIds': ['p1'] if support is None else support},
        'evidence': {'paragraphRange': {'start': 'p1', 'end': 'p1'},
                     'confidence': .9, 'rationale': 'p1 记录实际行动。'},
    }]
    return value


def test_observed_completion_survives_and_transient_basis_does_not_change_storage_contract():
    value = payload()
    before = deepcopy(value)
    result = _parse_extraction(value, '刘四当天已离开工棚，抵达下游。')
    assert result is not None
    assert result.story_progress_events[0].status == 'completed'
    assert value == before
    assert 'completionBasis' not in result.story_progress_events[0].model_dump(by_alias=True)


def test_future_arrangement_stays_advanced():
    result = _parse_extraction(payload(status='advanced', execution='planned', unmet=['实际离开尚未发生']),
                               '刘四明天调去下游，今晚仍在工棚。')
    assert result is not None
    assert result.story_progress_events[0].status == 'advanced'


@pytest.mark.parametrize('execution,unmet', [('planned', []), ('uncertain', []), ('observed', ['尚未抵达'])])
def test_completed_cannot_contradict_its_basis(execution, unmet):
    assert _parse_extraction(payload(execution=execution, unmet=unmet), '刘四收到调令。') is None


def test_completed_requires_explicit_basis():
    value = payload()
    del value['storyProgressEvents'][0]['completionBasis']
    assert _parse_extraction(value, '刘四收到调令。') is None


@pytest.mark.parametrize('support', [[], ['p2'], ['p9'], ['p1', 'p1']])
def test_support_must_exist_and_fall_within_selected_interval(support):
    assert _parse_extraction(payload(support=support), '下达调令。\n\n实际离开。') is None


def test_explicit_rationale_references_extend_stored_evidence_without_inventing_sources():
    value = _extraction_payload()
    value['planningSuggestions'][0]['evidence'] = {
        'paragraphRange': {'start': 'p1', 'end': 'p1'},
        'confidence': .9, 'rationale': 'p1 下令，p2 实际离开。',
    }
    prose = '下达调令。\n\n实际离开。'
    result = _parse_extraction(value, prose)
    assert result is not None
    evidence = result.planning_suggestions[0].evidence
    assert prose[evidence.start_scalar:evidence.end_scalar] == prose


def test_unknown_rationale_reference_is_rejected():
    value = _extraction_payload()
    value['planningSuggestions'][0]['evidence'] = {
        'paragraphRange': {'start': 'p1', 'end': 'p1'}, 'confidence': .9, 'rationale': '见 p9。',
    }
    assert _parse_extraction(value, '下达调令。') is None


def test_later_observed_execution_can_complete_despite_earlier_future_wording():
    value = payload(support=['p1', 'p2'])
    event = value['storyProgressEvents'][0]
    event['evidence']['paragraphRange']['end'] = 'p2'
    event['evidence']['rationale'] = 'p1 昨日下令明日离开，p2 今晨已经出发。'
    result = _parse_extraction(value, '昨日说好明天出发。\n\n今晨刘四已离开工棚。')
    assert result is not None
    assert result.story_progress_events[0].status == 'completed'


def test_extraction_separates_future_scene_design_from_current_event_evidence():
    import json
    from backend.prompts.finalization import build_extraction_messages, build_quality_messages
    from backend.tests.unit.test_finalization_prompt import _manifest
    manifest = _manifest(
        outline_context={'content': {'storyBlockRef': {'id': 'block'}, 'sceneTaskRefs': [{'id': 'task'}],
                                     'chapterGoal': 'FUTURE_GOAL', 'scenes': ['FUTURE_SCENE']}},
        bible_context={'content': {'futureReveal': 'FUTURE_REVEAL'}},
        planning_context={'content': {'storyBlocks': []}},
    )
    extracted = json.loads(build_extraction_messages(manifest=manifest)[1]['content'])
    assert extracted['outlineContext']['content']['sceneTaskRefs'] == [{'id': 'task'}]
    assert extracted['bibleContext'] == {}
    assert 'FUTURE_' not in json.dumps(extracted)
    reviewed = build_quality_messages(manifest=manifest)[1]['content']
    assert all(value in reviewed for value in ('FUTURE_GOAL', 'FUTURE_SCENE', 'FUTURE_REVEAL'))


@pytest.mark.parametrize('mode', ['missing', 'duplicate', 'new', 'upgrade'])
def test_progress_audit_cannot_skip_add_or_promote_events(mode):
    from backend.gateways.finalization_provider import _apply_progress_audit
    value = payload(status='advanced' if mode == 'upgrade' else 'completed')
    decision = {k: deepcopy(v) for k, v in value['storyProgressEvents'][0].items()
                if k in ('id', 'status', 'completionBasis', 'evidence')}
    decision['status'] = 'completed'
    decisions = [decision]
    if mode == 'missing': decisions = []
    if mode == 'duplicate': decisions *= 2
    if mode == 'new': decision['id'] = 'unrequested'
    assert _apply_progress_audit(value, {'decisions': decisions}) is None


@pytest.mark.asyncio
async def test_gateway_checks_progress_before_returning_the_proposal():
    import httpx
    from backend.gateways.finalization_provider import FinalizationExtractionGateway
    from backend.tests.unit.test_finalization_gateway import _provider, _response, _call
    from backend.tests.unit.test_finalization_prompt import _manifest
    value = payload()
    decision = {k: deepcopy(v) for k, v in value['storyProgressEvents'][0].items()
                if k in ('id', 'status', 'completionBasis', 'evidence')}
    decision['status'] = 'advanced'
    decision['completionBasis'].update(execution='planned', unmetRequirements=['实际离开'])
    calls = []
    def handler(request):
        calls.append(request)
        return _response(value if len(calls) == 1 else {'decisions': [decision]}, request)
    result = await _call(FinalizationExtractionGateway(transport=httpx.MockTransport(handler)), 'extract',
                         provider=_provider(), model_name='finalization-model',
                         manifest=_manifest(candidate_prose='刘四明日调走，今晚仍在工棚。'))
    assert len(calls) == 2
    assert result.story_progress_events[0].status == 'advanced'
    assert value['storyProgressEvents'][0]['status'] == 'completed'


def test_independent_audit_does_not_receive_the_first_extractors_claims():
    from backend.prompts.finalization import build_progress_audit_messages
    from backend.tests.unit.test_finalization_prompt import _manifest
    value = payload()
    value['storyProgressEvents'][0]['evidence']['rationale'] = 'BIASED_COMPLETION_CLAIM'
    messages = build_progress_audit_messages(manifest=_manifest(), events=value['storyProgressEvents'])
    assert 'BIASED_COMPLETION_CLAIM' not in messages[1]['content']
    assert 'supportingParagraphIds' not in messages[1]['content']
    assert 'transfer' in messages[1]['content']


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel', [False, True])
async def test_audit_failure_or_cancellation_never_returns_unchecked_progress(cancel):
    import asyncio
    import httpx
    from backend.gateways.finalization_provider import FinalizationExtractionGateway, FinalizationProviderError
    from backend.tests.unit.test_finalization_gateway import _provider, _response, _call
    from backend.tests.unit.test_finalization_prompt import _manifest
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return _response(payload(), request)
        if cancel:
            raise asyncio.CancelledError()
        return httpx.Response(503, text='PRIVATE_REMOTE_DETAIL')
    with pytest.raises(asyncio.CancelledError if cancel else FinalizationProviderError) as caught:
        task = asyncio.create_task(_call(FinalizationExtractionGateway(transport=httpx.MockTransport(handler)), 'extract',
                    provider=_provider(), model_name='finalization-model',
                    manifest=_manifest(candidate_prose='刘四明日调走，今晚仍在工棚。')))
        await task
    assert len(calls) == 2
    assert 'PRIVATE_REMOTE_DETAIL' not in str(caught.value)


def test_parent_progress_uses_only_its_actual_descendants_and_preserves_completed_other_stage():
    from backend.gateways.finalization_provider import _apply_progress_audit
    from backend.tests.unit.test_finalization_prompt import _manifest
    value = payload()
    original = value['storyProgressEvents'][0]
    value['storyProgressEvents'] = []
    for identity, kind in [('done', 'scene_task'), ('future', 'scene_task'), ('stage1', 'stage'), ('stage2', 'stage'), ('block', 'story_block')]:
        value['storyProgressEvents'].append({**deepcopy(original), 'id': 'event-' + identity, 'targetId': identity, 'targetType': kind})
    decisions = [{k: deepcopy(v) for k, v in e.items() if k in ('id', 'status', 'completionBasis', 'evidence')}
                 for e in value['storyProgressEvents'][:2]]
    decisions[1]['status'] = 'advanced'
    decisions[1]['completionBasis'].update(execution='planned', unmetRequirements=['实际执行'])
    value['storyProgressEvents'][3]['evidence']['rationale'] = 'p2 记录后续安排。'
    value['storyProgressEvents'][3]['completionBasis']['supportingParagraphIds'] = ['p2']
    manifest = _manifest(candidate_prose='已完成任务。\n\n后续仍待执行。', planning_context={'content': {'storyBlocks': [{'id': 'block', 'stages': [
        {'id': 'stage1', 'sceneTasks': [{'id': 'done'}]}, {'id': 'stage2', 'sceneTasks': [{'id': 'future'}]},
    ]}]}}, outline_context={'content': {'storyBlockRef': {'id': 'block'}}})
    before = deepcopy(value)
    result = _apply_progress_audit(value, {'decisions': decisions}, manifest)
    assert result is not None
    states = {e['targetId']: e['status'] for e in result['storyProgressEvents']}
    assert states == {'done': 'completed', 'future': 'advanced', 'stage1': 'completed', 'stage2': 'advanced', 'block': 'advanced'}
    assert value == before
    assert _parse_extraction(result, manifest.candidate_prose) is not None
