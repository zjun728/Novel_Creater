from copy import deepcopy

import pytest

from backend.domain.planning import DraftPlanningAggregate
from backend.domain.planning_completion import missing_block_fields, merge_missing_node
from backend.services.planning_continuation import inspect_continuation
from backend.tests.unit.test_planning_expansion import continuation_fixture, new_block


def test_check_is_read_only_and_reports_next_block_and_volume_choices():
    repo, draft = continuation_fixture()
    snapshot = deepcopy(repo.authority)
    result = inspect_continuation(draft, repo.authority)
    assert result['status'] == 'ready'
    assert [a['mode'] for a in result['actions']] == ['next_block', 'next_volume']
    assert repo.authority == snapshot


@pytest.mark.parametrize('blocker', ['sync', 'writing', 'draft', 'unfinished'])
def test_check_explains_blockers_without_offering_generation(blocker):
    repo, draft = continuation_fixture()
    if blocker == 'sync': repo.authority['projection']['projection_revision_number'] = 0
    if blocker == 'writing': repo.authority['activeSession'] = {'id': 'writing'}
    if blocker == 'unfinished': repo.authority['current']['actual_progress'] = []
    result = inspect_continuation(draft, repo.authority, draft_changed=blocker == 'draft')
    assert result['status'] == {'sync': 'sync_pending', 'writing': 'chapter_active', 'draft': 'draft_pending', 'unfinished': 'block_active'}[blocker]
    assert result['actions'] == []


def test_existing_incomplete_block_is_named_and_cannot_be_skipped_by_cross_volume():
    repo, draft = continuation_fixture()
    value = draft.model_dump(mode='json', by_alias=True)
    future = new_block('future', draft.volumes[0].id, draft.plots[0].id, 2)
    future['stages'] = []
    value['storyBlocks'].append(future)
    result = inspect_continuation(DraftPlanningAggregate.model_validate(value), repo.authority)
    assert result['actions'][0]['mode'] == 'fill_next_block'
    assert result['targetBlock']['title'] == future['title']
    assert result['missing']
    assert not any(a['mode'].endswith('volume') for a in result['actions'])


def test_missing_node_merge_preserves_author_content_and_existing_identity():
    old = new_block('future', 'v', 'p', 2)
    old['stages'] = []
    completed = new_block('future', 'v', 'p', 2)
    assert merge_missing_node(old, completed) == completed
    completed['title'] = '模型擅自重写'
    with pytest.raises(ValueError): merge_missing_node(old, completed)


def test_nonempty_stage_list_allows_only_missing_tasks_not_extra_stages():
    old = new_block('future', 'v', 'p', 2)
    old['stages'][0]['sceneTasks'] = []
    completed = new_block('future', 'v', 'p', 2)
    assert merge_missing_node(old, completed) == completed
    completed['stages'].append({**completed['stages'][0], 'clientNodeKey': 'extra'})
    with pytest.raises(ValueError): merge_missing_node(old, completed)


def test_completion_requires_tasks_in_every_active_stage():
    value = new_block('future', 'v', 'p', 2)
    value['stages'].append({**value['stages'][0], 'clientNodeKey': 'empty', 'order': 2, 'sceneTasks': []})
    assert missing_block_fields(value)


def prepared_future(*, incomplete=True, volume=False):
    from itertools import count
    from backend.domain.planning import normalize_planning_aggregate
    from backend.domain.json_contracts import canonical_json
    from backend.services.planning_generation import PlanningGenerationService
    repo, before = continuation_fixture()
    value = before.model_dump(mode='json', by_alias=True)
    target_volume = before.volumes[0].id
    if volume:
        target_volume = 'later-volume'
        value['volumes'].append({'clientNodeKey': target_volume, 'order': 2, 'title': '作者下一卷',
                                'coreChange': '作者确定的变化', 'mainPressure': '' if incomplete else '期限',
                                'ensembleFocus': [], 'forbiddenEvents': []})
    future = new_block('future', target_volume, before.plots[0].id, 2)
    if incomplete: future['stages'] = []
    value['storyBlocks'].append(future)
    ids = count(30)
    content = normalize_planning_aggregate(DraftPlanningAggregate.model_validate(value),
        previous_confirmed=PlanningGenerationService._planning_from_json(repo.head['content_json']),
        previous_draft=None, id_factory=lambda: f'node-{next(ids)}')
    repo.head.update(content_json=canonical_json(content.model_dump(mode='json', by_alias=True)), content_hash=content.content_hash)
    repo.draft.update(content_json=repo.head['content_json'], content_hash=content.content_hash)
    repo.authority['current']['planning_content'] = content.model_dump(mode='json', by_alias=True)
    return repo, PlanningGenerationService._editable_draft(content)


@pytest.mark.parametrize('volume', [False, True])
def test_completion_merges_only_missing_fields_and_keeps_past_nodes(volume):
    from backend.services.planning_expansion import prepare_expansion
    from backend.domain.planning_expansion import merge_completion
    repo, before = prepared_future(volume=volume)
    mode = 'fill_next_volume' if volume else 'fill_next_block'
    expansion = prepare_expansion(mode, before, 1, repo.authority)
    block = before.story_blocks[-1].model_dump(mode='json', by_alias=True)
    block['stages'] = new_block('filled', block['volumeRef'], before.plots[0].id, 2)['stages']
    vol = before.volumes[-1].model_dump(mode='json', by_alias=True) if volume else None
    if vol: vol['mainPressure'] = '补全压力'
    delta = {'nextVolume': vol, 'nextStoryBlock': block}
    after = merge_completion(before, delta, expansion)
    assert after.story_blocks[0] == before.story_blocks[0]
    assert after.story_blocks[-1].title == before.story_blocks[-1].title
    assert after.active_story_block_ref == before.story_blocks[-1].id
    assert not missing_block_fields(after.story_blocks[-1])
    block['title'] = '不允许模型覆盖'
    with pytest.raises(ValueError): merge_completion(before, delta, expansion)


@pytest.mark.asyncio
async def test_complete_existing_arrangement_reuses_without_gateway_call():
    from dataclasses import replace
    from backend.tests.unit.test_planning_generation_service import _service, _command, FakeGateway
    repo, before = prepared_future(incomplete=False)
    gateway = FakeGateway({})
    service, _, _, _ = _service(repository=repo, gateway=gateway)
    command = replace(_command(), generation_mode='next_block', draft_hash=repo.draft['content_hash'])
    result = await service.generate(command)
    assert result.status == 'succeeded'
    assert gateway.calls == []
    assert (await service.generate(command)) == result


@pytest.mark.parametrize('blocker', ['sync', 'writing', 'unfinished'])
def test_manual_reuse_rechecks_progress_at_confirmation(blocker):
    from backend.services.planning_generation import PlanningGenerationService
    from backend.services.planning_expansion import validate_manual_continuation
    repo, draft = prepared_future(incomplete=False)
    before = PlanningGenerationService._planning_from_json(repo.head['content_json'])
    after = before.model_copy(update={'active_story_block_id': before.story_blocks[-1].id})
    validate_manual_continuation(before, after, repo.authority)
    if blocker == 'sync': repo.authority['projection']['projection_revision_number'] = 0
    if blocker == 'writing': repo.authority['activeSession'] = {'id': 'active'}
    if blocker == 'unfinished': repo.authority['current']['actual_progress'] = []
    with pytest.raises(ValueError): validate_manual_continuation(before, after, repo.authority)


@pytest.mark.asyncio
async def test_fill_gateway_renders_contract_and_merges_response():
    import json
    import httpx
    from backend.gateways.planning_provider import PlanningProviderGateway
    from backend.tests.unit.test_planning_gateway import _provider, _manifest
    from backend.services.planning_expansion import prepare_expansion
    repo, before = prepared_future()
    manifest = _manifest()
    expansion = prepare_expansion('fill_next_block', before, 1, repo.authority)
    manifest.update(draft=before.model_dump(mode='json', by_alias=True), expansion=expansion.model_dump(mode='json', by_alias=True))
    block = before.story_blocks[-1].model_dump(mode='json', by_alias=True)
    block['stages'] = new_block('filled', block['volumeRef'], before.plots[0].id, 2)['stages']
    calls = []
    # Real compatible providers can omit temporary keys on wholly new children.
    del block['stages'][0]['sceneTasks'][0]['clientNodeKey']
    for key in ('id', 'clientNodeKey', 'revision', 'contentHash'): block.pop(key, None)
    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        assert 'json' in body['messages'][0]['content'].lower()
        evidence = json.loads(body['messages'][1]['content'])
        patch_schema=evidence['outputContract']['properties']['nextStoryBlock']
        assert 'stages' in patch_schema['properties'] and 'id' not in patch_schema['properties']
        assert 'title' not in patch_schema['properties']
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'nextVolume': None, 'nextStoryBlock': block})}}]})
    gateway = PlanningProviderGateway(transport=httpx.MockTransport(respond))
    await gateway.start()
    try:
        result = await gateway.generate(provider=_provider(), model_name='test', manifest=manifest, author_instructions='')
        assert result['activeStoryBlockRef'] == before.story_blocks[-1].id
        assert len(calls) == 1
    finally: await gateway.aclose()


@pytest.mark.parametrize('incomplete', [False, True])
def test_existing_volume_reports_fill_or_reuse_and_keeps_same_volume_choice(incomplete):
    repo, before = prepared_future(volume=True, incomplete=incomplete)
    result = inspect_continuation(before, repo.authority)
    assert result['actions'][0]['mode'] == 'next_block'
    assert result['actions'][1]['mode'] == ('fill_next_volume' if incomplete else 'next_volume')
    assert result['actions'][1]['kind'] == ('fill' if incomplete else 'reuse')


def test_fill_volume_without_block_appends_only_its_first_block():
    from backend.domain.planning_expansion import merge_completion, PlanningExpansion
    repo, before = prepared_future(volume=True)
    before = before.model_copy(update={'story_blocks': before.story_blocks[:1]})
    volume = before.volumes[-1].model_dump(mode='json', by_alias=True)
    volume['mainPressure'] = '期限将至'
    expansion = PlanningExpansion.model_validate({'mode': 'fill_next_volume', 'authorityHash': 'a'*64,
        'targetVolumeRef': before.volumes[-1].id, 'targetBlockRef': None, 'continuity': {}})
    result = merge_completion(before, {'nextVolume': volume,
        'nextStoryBlock': new_block('first', before.volumes[-1].id, before.plots[0].id, 2)}, expansion)
    assert len(result.volumes) == 2 and len(result.story_blocks) == 2
    assert result.volumes[0] == before.volumes[0]
    assert result.story_blocks[0] == before.story_blocks[0]


def test_same_volume_completion_does_not_require_rewriting_accepted_volume():
    from backend.domain.planning_expansion import merge_completion, PlanningExpansion
    repo, before = prepared_future()
    before = before.model_copy(update={'volumes': (before.volumes[0].model_copy(update={'main_pressure': ''}),)})
    block = before.story_blocks[-1].model_dump(mode='json', by_alias=True)
    block['stages'] = new_block('filled', block['volumeRef'], before.plots[0].id, 2)['stages']
    expansion = PlanningExpansion.model_validate({'mode': 'fill_next_block', 'authorityHash': 'a'*64,
        'targetVolumeRef': before.volumes[0].id, 'targetBlockRef': before.story_blocks[-1].id, 'continuity': {}})
    after = merge_completion(before, {'nextVolume': None, 'nextStoryBlock': block}, expansion)
    assert after.volumes == before.volumes


def test_completion_patch_keeps_existing_identity_and_rejects_populated_field_changes():
    from backend.domain.planning_expansion import merge_completion
    from backend.services.planning_expansion import prepare_expansion
    repo,before=prepared_future(volume=True)
    expansion=prepare_expansion('fill_next_volume',before,1,repo.authority)
    stages=new_block('added',before.volumes[-1].id,before.plots[0].id,2)['stages']
    delta={'nextVolume':{'mainPressure':'新增压力'},'nextStoryBlock':{'stages':stages}}
    after=merge_completion(before,delta,expansion)
    assert after.volumes[-1].id==before.volumes[-1].id
    assert after.story_blocks[-1].title==before.story_blocks[-1].title
    assert after.story_blocks[0]==before.story_blocks[0]
    for changes in ({'title':'不允许覆盖'}, {'id':'fake'}, {'clientNodeKey':'fake'}, {'contentHash':None}):
        with pytest.raises(ValueError):
            merge_completion(before,{**delta,'nextVolume':{**delta['nextVolume'],**changes}},expansion)


def test_completion_patch_fills_nested_task_without_replacing_existing_stage():
    from backend.domain.planning_completion import apply_completion_patch, completion_patch_schema
    from backend.domain.planning import DraftStoryBlock

    before = new_block('future', 'volume', 'plot', 2)
    before['stages'][0]['sceneTasks'][0]['completionEvidence'] = ''
    schema = DraftStoryBlock.model_json_schema(by_alias=True)
    patch_schema = completion_patch_schema(before, schema, schema['$defs'])
    stage_schema = patch_schema['properties']['stages']['prefixItems'][0]
    task_schema = stage_schema['properties']['sceneTasks']['prefixItems'][0]
    assert set(task_schema['properties']) == {'completionEvidence'}
    patch = {'stages': [{'sceneTasks': [{'completionEvidence': '发现账本记录'}]}]}
    expected = deepcopy(before)
    expected['stages'][0]['sceneTasks'][0]['completionEvidence'] = '发现账本记录'
    assert apply_completion_patch(before, patch) == expected
    with pytest.raises(ValueError):
        apply_completion_patch(before, {'stages': [{}, {}]})
