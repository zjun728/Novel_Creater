from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from itertools import count
import json

import pytest

from backend.domain.json_contracts import canonical_json
from backend.domain.planning import DraftPlanningAggregate, normalize_planning_aggregate
from backend.domain.planning_expansion import validate_expansion_output, merge_continuation, merge_block_adjustment
from backend.services.planning_expansion import prepare_expansion
from backend.services.planning_generation import PlanningGenerationNotReady, PlanningGenerationIdempotencyConflict, PlanningGenerationService
from backend.tests.unit.test_planning_generation_service import FakePlanningRepository, FakeGateway, _service, _command, _draft_payload


def complete_payload():
    payload = _draft_payload()
    payload["activeStoryBlockRef"] = "block-1"
    payload["storyBlocks"] = [new_block("block-1", "volume-1", "plot-1", 1)]
    return payload


def new_block(key, volume, plot, order):
    return {"clientNodeKey": key, "order": order, "title": "追查线索", "volumeRef": volume,
            "plotRefs": [plot], "entrySituation": "追兵正在接近", "blockGoal": "找到落脚点",
            "mainPressure": "期限将至", "expectedChange": "得到线索", "openQuestions": [],
            "involvedCharacters": ["主角"], "stages": [{"clientNodeKey": key + "-stage", "order": 1,
            "title": "核查", "purpose": "找到证据", "dramaticQuestion": "能否说服证人",
            "sceneTasks": [{"clientNodeKey": key + "-task", "order": 1, "task": "询问证人",
                            "completionEvidence": "证人交出账本"}]}]}


class ExpansionRepository(FakePlanningRepository):
    def __init__(self):
        super().__init__()
        self.authority = {"projection": {"canon_revision_number": 0, "projection_revision_number": 0},
                          "current": None, "activeSession": None}

    async def read_expansion_authority(self, session, project_id):
        return deepcopy(self.authority)


def continuation_fixture():
    repo = ExpansionRepository()
    ids = count(1)
    content = normalize_planning_aggregate(DraftPlanningAggregate.model_validate(complete_payload()),
        previous_confirmed=None, previous_draft=None, id_factory=lambda: f"node-{next(ids)}")
    persisted = content.model_dump(mode="json", by_alias=True)
    repo.head.update(revision=1, planning_revision_id="plan-1", content_hash=content.content_hash, content_json=canonical_json(persisted))
    repo.draft.update(base_head_revision=1, content_hash=content.content_hash, content_json=canonical_json(persisted))
    repo.authority["projection"] = {"canon_revision_number": 1, "projection_revision_number": 1}
    repo.authority["current"] = {"canon_revision": 1, "projection_revision": 1, "projection_hash": "a" * 64,
        "planning_content": persisted, "previous_final_chapter": {"id": "final-1", "chapter_num": 1,
        "canon_revision": 1, "content": "证人终于交出了账本。", "content_hash": sha256("证人终于交出了账本。".encode()).hexdigest()},
        "actual_progress": [{"revision_number": 1, "content_hash": "a" * 64,
        "subject_key": "__global__", "entity_id": None, "field_path": f"plot.progress.story_block.{content.active_story_block_id}",
        "payload_json": canonical_json({"chapterNumber": 1, "targetType": "story_block",
                                     "targetId": content.active_story_block_id, "status": "completed"})}]}
    return repo, PlanningGenerationService._editable_draft(content)


@pytest.mark.asyncio
async def test_initial_complete_generation_only_loads_draft_and_replays_by_mode():
    repo = ExpansionRepository()
    service, _, gateway, _ = _service(repository=repo, gateway=FakeGateway(complete_payload()))
    command = replace(_command(), generation_mode="initial")
    result = await service.generate(command)
    assert result.status == "succeeded" and repo.head["revision"] == 0
    assert json.loads(repo.draft["content_json"])["activeStoryBlockId"]
    assert (await service.generate(command)) == result
    assert len(gateway.calls) == 1
    with pytest.raises(PlanningGenerationIdempotencyConflict):
        await service.generate(replace(command, generation_mode="volumes_plots"))


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing_tasks", "progress_drift", "active_session", "unsynchronized"])
async def test_initial_failures_preserve_draft(failure):
    repo = ExpansionRepository()
    original = deepcopy(repo.draft)
    payload = complete_payload()
    hook = None
    if failure == "missing_tasks":
        payload["storyBlocks"][0]["stages"][0]["sceneTasks"] = []
    if failure == "progress_drift":
        hook = lambda: repo.authority["projection"].update(canon_revision_number=1)
    if failure == "active_session": repo.authority["activeSession"] = {"id": "writing"}
    if failure == "unsynchronized": repo.authority["projection"]["canon_revision_number"] = 1
    service, _, gateway, _ = _service(repository=repo, gateway=FakeGateway(payload, hook=hook))
    if failure in {"active_session", "unsynchronized"}:
        with pytest.raises(PlanningGenerationNotReady): await service.generate(replace(_command(), generation_mode="initial"))
        assert not gateway.calls
    else:
        result = await service.generate(replace(_command(), generation_mode="initial"))
        assert result.status == ("superseded" if failure == "progress_drift" else "failed")
    assert repo.draft == original


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["next_block", "next_volume"])
async def test_continuation_preserves_history_and_loads_only_new_work_draft(mode):
    repo, before = continuation_fixture()
    output = before.model_dump(mode="json", by_alias=True, exclude_none=True)
    volume = before.volumes[0].id
    if mode == "next_volume":
        new = _draft_payload()["volumes"][0]
        new.update(clientNodeKey="volume-next", order=2)
        output["volumes"].append(new)
        volume = "volume-next"
    output["storyBlocks"].append(new_block("block-next", volume, before.plots[0].id, 2))
    output["activeStoryBlockRef"] = "block-next"
    original_head = deepcopy(repo.head)
    service, _, gateway, _ = _service(repository=repo, gateway=FakeGateway(output))
    command = replace(_command(), generation_mode=mode, draft_hash=repo.draft["content_hash"])
    result = await service.generate(command)
    assert result.status == "succeeded" and repo.head == original_head
    content = json.loads(repo.draft["content_json"])
    assert content["storyBlocks"][0] == json.loads(original_head["content_json"])["storyBlocks"][0]
    assert gateway.calls[0]["manifest"].expansion.continuity["previous_chapter"]["content"].endswith("账本。")


@pytest.mark.parametrize("mutation", ["rewrite", "remove", "extra_block", "wrong_volume", "wrong_active"])
def test_continuation_rejects_destructive_or_wrong_output(mutation):
    repo, before = continuation_fixture()
    expansion = prepare_expansion("next_block", before, 1, repo.authority)
    output = before.model_dump(mode="json", by_alias=True)
    output["storyBlocks"].append(new_block("next", before.volumes[0].id, before.plots[0].id, 2))
    output["activeStoryBlockRef"] = "next"
    if mutation == "rewrite": output["storyBlocks"][0]["title"] = "改写"
    if mutation == "remove": output["storyBlocks"].pop(0)
    if mutation == "extra_block": output["storyBlocks"].append(new_block("extra", before.volumes[0].id, before.plots[0].id, 3))
    if mutation == "wrong_volume": output["storyBlocks"][-1]["volumeRef"] = "unknown"
    if mutation == "wrong_active": output["activeStoryBlockRef"] = before.active_story_block_ref
    with pytest.raises(ValueError): validate_expansion_output(before, DraftPlanningAggregate.model_validate(output), expansion)


def test_unfinished_progress_or_revised_draft_cannot_prepare_continuation():
    repo, before = continuation_fixture()
    repo.authority["current"]["actual_progress"] = []
    with pytest.raises(ValueError): prepare_expansion("next_block", before, 1, repo.authority)
    repo, before = continuation_fixture()
    output = before.model_dump(mode="json", by_alias=True)
    output["volumes"][0]["title"] = "作者未采用的修改"
    with pytest.raises(ValueError): prepare_expansion("next_block", DraftPlanningAggregate.model_validate(output), 1, repo.authority)


def test_preplanned_next_block_is_reused_and_cannot_skip_to_next_volume():
    repo, before = continuation_fixture()
    output = before.model_dump(mode="json", by_alias=True)
    output["storyBlocks"].append(new_block("next", before.volumes[0].id, before.plots[0].id, 2))
    current = repo.authority["current"]["planning_content"]
    ids = count(20)
    content = normalize_planning_aggregate(DraftPlanningAggregate.model_validate(output),
        previous_confirmed=PlanningGenerationService._planning_from_json(current),
        previous_draft=None, id_factory=lambda: f"node-{next(ids)}")
    repo.authority["current"]["planning_content"] = content.model_dump(mode="json", by_alias=True)
    before = PlanningGenerationService._editable_draft(content)
    expansion = prepare_expansion("next_block", before, 1, repo.authority)
    assert expansion.target_block_ref == before.story_blocks[-1].id
    after = before.model_copy(update={"active_story_block_ref": expansion.target_block_ref})
    validate_expansion_output(before, after, expansion)
    with pytest.raises(ValueError): prepare_expansion("next_volume", before, 1, repo.authority)


def test_delta_merges_exact_old_nodes_and_rejects_missing_or_extra_content():
    repo, before = continuation_fixture()
    expansion = prepare_expansion("next_block", before, 1, repo.authority)
    delta = {"nextVolume": None, "nextStoryBlock": new_block("next", before.volumes[0].id, before.plots[0].id, 2)}
    result = merge_continuation(before, delta, expansion)
    assert result.story_blocks[:-1] == before.story_blocks and result.volumes == before.volumes and result.plots == before.plots
    with pytest.raises(ValueError): merge_continuation(before, {"nextVolume": None, "nextStoryBlock": None}, expansion)
    with pytest.raises(ValueError): merge_continuation(before, {**delta, "storyBlocks": []}, expansion)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["next_block", "next_volume"])
async def test_gateway_uses_delta_contract_and_explicit_null_targets(mode):
    import httpx
    from backend.gateways.planning_provider import PlanningProviderGateway
    from backend.tests.unit.test_planning_gateway import _provider, _manifest
    repo, before = continuation_fixture()
    expansion = prepare_expansion(mode, before, 1, repo.authority)
    manifest = _manifest()
    manifest.update(draft=before.model_dump(mode="json", by_alias=True), expansion=expansion.model_dump(mode="json", by_alias=True))
    delta = {"nextVolume": None, "nextStoryBlock": new_block("next", before.volumes[0].id, before.plots[0].id, 2)}
    if mode == "next_volume":
        delta["nextVolume"] = {**_draft_payload()["volumes"][0], "clientNodeKey": "new-volume", "order": 2}
        delta["nextStoryBlock"]["volumeRef"] = "new-volume"
    def respond(request):
        body = json.loads(request.content)
        assert any("json" in message["content"].lower() for message in body["messages"])
        evidence = json.loads(body["messages"][1]["content"])
        assert evidence["manifest"]["expansion"]["targetBlockRef"] is None
        assert set(evidence["outputContract"]["properties"]) == {"nextVolume", "nextStoryBlock"}
        assert evidence["outputContract"]["properties"]["nextVolume"] == (
            {"$ref": "#/$defs/DraftVolume"} if mode == "next_volume" else {"type": "null"})
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(delta)}}]})
    gateway = PlanningProviderGateway(transport=httpx.MockTransport(respond))
    await gateway.start()
    try:
        output = await gateway.generate(provider=_provider(), model_name="test", manifest=manifest, author_instructions="")
        assert output["activeStoryBlockRef"] == "next"
        assert len(output["storyBlocks"]) == 2
    finally:
        await gateway.aclose()


def adjustment_fixture():
    repo, before = continuation_fixture()
    task_id = before.story_blocks[0].stages[0].scene_tasks[0].id
    row = repo.authority["current"]["actual_progress"][0]
    row["field_path"] = f"plot.progress.scene_task.{task_id}"
    row["payload_json"] = canonical_json({"chapterNumber": 1, "targetType": "scene_task", "targetId": task_id, "status": "advanced"})
    return repo, before


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['next_block', 'next_volume'])
async def test_continuation_gateway_assigns_missing_keys_only_to_new_block_nodes(mode):
    import httpx
    from backend.gateways.planning_provider import PlanningProviderGateway
    from backend.tests.unit.test_planning_gateway import _provider, _manifest
    repo, before = continuation_fixture()
    expansion = prepare_expansion(mode, before, 1, repo.authority)
    manifest = _manifest()
    manifest.update(draft=before.model_dump(mode='json',by_alias=True),expansion=expansion.model_dump(mode='json',by_alias=True))
    volume = None
    volume_ref = before.volumes[0].id
    if mode == 'next_volume':
        volume = {**_draft_payload()['volumes'][0], 'clientNodeKey': 'new-volume', 'order': 2}
        volume_ref = 'new-volume'
    block = new_block('new-block', volume_ref, before.plots[0].id, 2)
    for node in [block, *[n for s in block['stages'] for n in [s, *s['sceneTasks']]]]: node.pop('clientNodeKey')
    def respond(request):
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'nextVolume':volume,'nextStoryBlock':block})}}]})
    gateway=PlanningProviderGateway(transport=httpx.MockTransport(respond))
    await gateway.start()
    try:
        result=await gateway.generate(provider=_provider(),model_name='test',manifest=manifest,author_instructions='')
        draft=DraftPlanningAggregate.model_validate(result)
        assert draft.story_blocks[:-1] == before.story_blocks
        assert draft.active_story_block_ref == draft.story_blocks[-1].client_key
        assert draft.story_blocks[-1].stages[0].scene_tasks[0].client_key
    finally: await gateway.aclose()


def test_ai_adjustment_protects_implemented_tasks_but_can_add_future_work():
    repo, before = adjustment_fixture()
    expansion = prepare_expansion("revise_block", before, 1, repo.authority)
    block = before.story_blocks[0].model_dump(mode="json", by_alias=True)
    block["blockGoal"] = "核查证据后保护证人"
    block["stages"][0]["sceneTasks"].append({"clientNodeKey": "future-task", "order": 2,
        "task": "安排证人转移", "completionEvidence": "证人抵达安全地点"})
    revised = merge_block_adjustment(before, {"storyBlock": block}, expansion)
    assert revised.active_story_block_ref == before.active_story_block_ref
    assert revised.story_blocks[0].block_goal == "核查证据后保护证人"
    block["stages"][0]["sceneTasks"][0]["task"] = "改写已经推进的工作"
    with pytest.raises(ValueError, match="implemented"):
        merge_block_adjustment(before, {"storyBlock": block}, expansion)


def test_completed_block_cannot_be_rewritten_or_moved_to_another_volume():
    repo, before = continuation_fixture()
    with pytest.raises(ValueError): prepare_expansion("revise_block", before, 1, repo.authority)
    repo, before = adjustment_fixture()
    expansion = prepare_expansion("revise_block", before, 1, repo.authority)
    block = before.story_blocks[0].model_dump(mode="json", by_alias=True)
    block["volumeRef"] = "other-volume"
    with pytest.raises(ValueError): merge_block_adjustment(before, {"storyBlock": block}, expansion)


def test_completed_stage_cannot_gain_or_lose_tasks_during_ai_adjustment():
    repo, before = adjustment_fixture()
    stage = before.story_blocks[0].stages[0]
    expansion = prepare_expansion("revise_block", before, 1, repo.authority).model_copy(
        update={"protected_node_refs": (stage.id,)})
    block = before.story_blocks[0].model_dump(mode="json", by_alias=True)
    block["stages"][0]["sceneTasks"].append({"clientNodeKey": "future-task", "order": 2,
        "task": "新任务", "completionEvidence": "新依据"})
    with pytest.raises(ValueError, match="implemented"):
        merge_block_adjustment(before, {"storyBlock": block}, expansion)


@pytest.mark.asyncio
async def test_adjustment_generation_preserves_head_and_requires_instructions():
    repo, before = adjustment_fixture()
    output = before.model_dump(mode="json", by_alias=True)
    output["storyBlocks"][0]["blockGoal"] = "保护证人并核查记录"
    service, _, gateway, _ = _service(repository=repo, gateway=FakeGateway(output))
    command = replace(_command(), generation_mode="revise_block", draft_hash=repo.draft["content_hash"])
    with pytest.raises(PlanningGenerationNotReady): await service.generate(replace(command, author_instructions=""))
    assert not gateway.calls
    result = await service.generate(command)
    assert result.status == "succeeded" and repo.head["revision"] == 1
