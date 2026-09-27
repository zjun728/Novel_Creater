from dataclasses import replace
from uuid import uuid4

import pytest

from backend.repositories.planning import PlanningRepository
from backend.services.planning import CreatePlanningDraft, ConfirmPlanningDraft, PlanningPreconditionFailed
from backend.services.planning_generation import GeneratePlanningDraft, PlanningGenerationService
from backend.services.planning import SavePlanningDraft
from backend.tests.integration.test_planning_generation import _prepare_generation_basis, _FakePlanningGateway
from backend.tests.integration.test_planning_aggregate_lifecycle import PROJECT, _canon_progress_service, _canon_progress_commit
from backend.tests.support.disposable_mysql import transaction_factory_for
from backend.tests.unit.test_planning_expansion import complete_payload
from backend.tests.unit.test_planning_expansion import new_block
from backend.tests.support.planning_expansion import finalize_active_block_fixture

pytestmark = [pytest.mark.mysql, pytest.mark.asyncio]


async def test_author_stop_from_another_service_fences_and_closes_provider(disposable_mysql):
    import asyncio
    planning = await _prepare_generation_basis(disposable_mysql)
    draft = await planning.create_draft(CreatePlanningDraft(PROJECT, 'stop-create'))
    entered, closed = asyncio.Event(), asyncio.Event()
    class WaitingGateway:
        async def generate(self, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()
    tx = transaction_factory_for(disposable_mysql.connection_config)
    worker = PlanningGenerationService(PlanningRepository(), provider_gateway=WaitingGateway(), transaction_factory=tx)
    stopper = PlanningGenerationService(PlanningRepository(), provider_gateway=WaitingGateway(), transaction_factory=tx)
    command = GeneratePlanningDraft(PROJECT, draft.draft_id, draft.draft_revision, draft.content_hash, 'stop-generation', '', 'initial')
    running = asyncio.create_task(worker.generate(command))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        result = await stopper.cancel_by_key(PROJECT, draft.draft_id, 'stop-generation')
        assert result.failure_code == 'PlanningGenerationCancelled'
        assert await asyncio.wait_for(running, 5) == result
        assert closed.is_set()
        current = await planning.get_state(PROJECT)
        assert current.draft.content_hash == draft.content_hash
        assert current.head.revision == 0
        assert await stopper.cancel_by_key(PROJECT, draft.draft_id, 'stop-generation') == result
    finally:
        if not running.done(): running.cancel()
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.parametrize("progress_drift", [False, True])
async def test_real_mysql_full_plan_confirmation_checks_generation_progress(disposable_mysql, progress_drift):
    planning = await _prepare_generation_basis(disposable_mysql)
    draft = await planning.create_draft(CreatePlanningDraft(PROJECT, "create-full-plan"))
    service = PlanningGenerationService(PlanningRepository(), provider_gateway=_FakePlanningGateway(complete_payload()),
        transaction_factory=transaction_factory_for(disposable_mysql.connection_config), id_factory=lambda: str(uuid4()))
    command = GeneratePlanningDraft(PROJECT, draft.draft_id, draft.draft_revision, draft.content_hash,
                                    "generate-full-plan", "", "initial")
    operation = await service.generate(command)
    assert operation.status == "succeeded"
    state = await planning.get_state(PROJECT)
    assert state.head.revision == 0 and state.capabilities.confirm
    confirm = ConfirmPlanningDraft(PROJECT, state.draft.draft_id, state.draft.draft_revision,
                                   state.draft.content_hash, "confirm-full-plan")
    if progress_drift:
        # A later volume-only generation must not erase the expansion's progress witness.
        gateway = _FakePlanningGateway(service._editable_draft(state.draft.content).model_dump(mode="json", by_alias=True))
        service._gateway = gateway
        await service.generate(replace(command, draft_revision=state.draft.draft_revision,
            draft_hash=state.draft.content_hash, idempotency_key="later-volume-only", generation_mode="volumes_plots"))
        state = await planning.get_state(PROJECT)
        confirm = replace(confirm, expected_draft_revision=state.draft.draft_revision, expected_draft_hash=state.draft.content_hash)
        await _canon_progress_service(disposable_mysql, 1).commit(_canon_progress_commit(1, "plot.fixture", {"status": "advanced"}))
        with pytest.raises(PlanningPreconditionFailed, match="Writing progress changed"):
            await planning.confirm_draft(confirm)
        assert (await planning.get_state(PROJECT)).head.revision == 0
    else:
        confirmed = await planning.confirm_draft(confirm)
        assert confirmed.revision == 1 and len(confirmed.content.story_blocks[0].stages[0].scene_tasks) == 1
        assert (await planning.confirm_draft(confirm)) == confirmed
        authority = await PlanningRepository().read_expansion_authority(disposable_mysql.session, PROJECT)
        assert authority["projection"]["canon_revision_number"] == 0
        assert authority["current"]["planning_revision"] == 1
        adjustment = await planning.create_draft(CreatePlanningDraft(PROJECT, "adjust-current-block"))
        payload = service._editable_draft(confirmed.content).model_dump(mode="json", by_alias=True)
        payload["storyBlocks"][0]["blockGoal"] = "找到落脚点并保护证人"
        service._gateway = _FakePlanningGateway(payload)
        adjusted = await service.generate(GeneratePlanningDraft(PROJECT, adjustment.draft_id,
            adjustment.draft_revision, adjustment.content_hash, "generate-block-adjustment", "补充保护证人目标", "revise_block"))
        assert adjusted.status == "succeeded"
        state = await planning.get_state(PROJECT)
        assert state.head.revision == 1
        adopted = await planning.confirm_draft(ConfirmPlanningDraft(PROJECT, state.draft.draft_id,
            state.draft.draft_revision, state.draft.content_hash, "confirm-block-adjustment"))
        assert adopted.revision == 2 and adopted.content.active_story_block_id == confirmed.content.active_story_block_id
        assert adopted.content.story_blocks[0].revision == confirmed.content.story_blocks[0].revision + 1
        assert (await planning.get_state(PROJECT)).canon_projection_status["canonRevision"] == 0


async def test_real_mysql_continuation_after_actual_finalization_preserves_prior_plan(disposable_mysql):
    planning = await _prepare_generation_basis(disposable_mysql)
    tx = transaction_factory_for(disposable_mysql.connection_config)
    gateway = _FakePlanningGateway(complete_payload())
    service = PlanningGenerationService(PlanningRepository(), provider_gateway=gateway, transaction_factory=tx)
    for mode in ["initial", "next_block", "next_volume"]:
        before = await planning.get_state(PROJECT)
        if mode != "initial":
            content = service._editable_draft(before.future_plan)
            output = content.model_dump(mode="json", by_alias=True)
            volume = content.volumes[0].id
            if mode == "next_volume":
                volume = "next-volume"
                v = complete_payload()["volumes"][0]
                v.update(clientNodeKey=volume, order=2)
                output["volumes"].append(v)
            output["storyBlocks"].append(new_block("next-block", volume, content.plots[0].id, len(content.story_blocks) + 1))
            output["activeStoryBlockRef"] = "next-block"
            gateway.output = output
        draft = await planning.create_draft(CreatePlanningDraft(PROJECT, "create-" + mode))
        result = await service.generate(GeneratePlanningDraft(PROJECT, draft.draft_id, draft.draft_revision,
            draft.content_hash, "generate-" + mode, "", mode))
        assert result.status == "succeeded"
        state = await planning.get_state(PROJECT)
        assert state.head == before.head
        confirmed = await planning.confirm_draft(ConfirmPlanningDraft(PROJECT, state.draft.draft_id,
            state.draft.draft_revision, state.draft.content_hash, "confirm-" + mode))
        if before.future_plan:
            assert confirmed.content.story_blocks[:-1] == before.future_plan.story_blocks
            assert state.canon_projection_status == before.canon_projection_status
        if mode != "next_volume":
            await finalize_active_block_fixture(tx, PROJECT)
    final = await planning.get_state(PROJECT)
    assert len(final.future_plan.volumes) == 2 and len(final.future_plan.story_blocks) == 3
    assert final.canon_projection_status["canonRevision"] == 2


@pytest.mark.parametrize('incomplete', [False, True])
async def test_nc7_read_check_and_existing_arrangement_adoption(disposable_mysql, incomplete):
    from backend.tests.integration.test_planning_aggregate_lifecycle import _snapshot
    planning = await _prepare_generation_basis(disposable_mysql)
    tx = transaction_factory_for(disposable_mysql.connection_config)
    draft = await planning.create_draft(CreatePlanningDraft(PROJECT, 'nc7-create'))
    payload = complete_payload()
    future = new_block('future', 'volume-1', 'plot-1', 2)
    if incomplete: future['stages'] = []
    payload['storyBlocks'].append(future)
    draft = await planning.save_draft(SavePlanningDraft(PROJECT, draft.draft_id, draft.draft_revision,
        draft.content_hash, payload, 'nc7-seed'))
    original = await planning.confirm_draft(ConfirmPlanningDraft(PROJECT, draft.draft_id,
        draft.draft_revision, draft.content_hash, 'nc7-first-confirm'))
    assert (await planning.inspect_continuation(PROJECT))['status'] == 'block_active'
    await finalize_active_block_fixture(tx, PROJECT)
    snapshot = await _snapshot(disposable_mysql.session)
    check = await planning.inspect_continuation(PROJECT)
    assert check['actions'][0]['kind'] == ('fill' if incomplete else 'reuse')
    assert await _snapshot(disposable_mysql.session) == snapshot
    draft = await planning.create_draft(CreatePlanningDraft(PROJECT, 'nc7-work'))
    before = PlanningGenerationService._editable_draft(draft.content)
    output = before.model_dump(mode='json', by_alias=True)
    output['activeStoryBlockRef'] = before.story_blocks[-1].id
    if incomplete:
        output['storyBlocks'][-1]['stages'] = new_block('filled', before.volumes[0].id, before.plots[0].id, 2)['stages']
        gateway = _FakePlanningGateway(output)
        generation = PlanningGenerationService(PlanningRepository(), provider_gateway=gateway, transaction_factory=tx)
        command = GeneratePlanningDraft(PROJECT, draft.draft_id, draft.draft_revision,
            draft.content_hash, 'nc7-fill', '', 'fill_next_block')
        assert (await generation.generate(command)).status == 'succeeded'
        assert (await generation.generate(command)).status == 'succeeded'
        assert len(gateway.calls) == 1
    else:
        # The UI reuse path saves a selected existing node without any model call.
        await planning.save_draft(SavePlanningDraft(PROJECT, draft.draft_id, draft.draft_revision,
            draft.content_hash, output, 'nc7-select'))
    state = await planning.get_state(PROJECT)
    assert (await planning.inspect_continuation(PROJECT))['status'] == 'draft_pending'
    result = await planning.confirm_draft(ConfirmPlanningDraft(PROJECT, state.draft.draft_id,
        state.draft.draft_revision, state.draft.content_hash, 'nc7-adopt'))
    assert result.content.active_story_block_id == original.content.story_blocks[-1].id
    assert result.content.story_blocks[0] == original.content.story_blocks[0]
    assert result.content.story_blocks[-1].title == original.content.story_blocks[-1].title
    assert (await planning.inspect_continuation(PROJECT))['status'] == 'block_active'
