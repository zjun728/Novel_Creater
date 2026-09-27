import asyncio
from copy import deepcopy

import pytest

from backend.tests.unit.test_planning_generation_service import (
    BlockingGateway, TransactionTracker, _command, _service,
)
from backend.services.planning_generation import PlanningGenerationOperationNotFound, PlanningGenerationRetryable


@pytest.mark.asyncio
async def test_author_stop_is_idempotent_and_prevents_late_publish():
    tracker = TransactionTracker()
    gateway = BlockingGateway(tracker=tracker)
    service, repo, _, _ = _service(gateway=gateway, tracker=tracker)
    before = deepcopy(repo.draft)
    task = asyncio.create_task(service.generate(_command()))
    await gateway.entered.wait()
    try:
        stopped = await service.cancel_by_key('p1', 'draft-1', 'generate-1')
        assert stopped.failure_code == 'PlanningGenerationCancelled'
        assert stopped.loaded is False
        assert await service.cancel_by_key('p1', 'draft-1', 'generate-1') == stopped
        gateway.release.set()
        assert await asyncio.wait_for(task, 2) == stopped
        assert repo.draft == before
    finally:
        gateway.release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_stop_after_success_reports_success_without_undo():
    service, repo, _, _ = _service()
    result = await service.generate(_command())
    before = deepcopy(repo.draft)
    assert await service.cancel_by_key('p1', 'draft-1', 'generate-1') == result
    assert repo.draft == before


@pytest.mark.asyncio
async def test_stop_cannot_target_another_draft_or_claim_unreserved_work_stopped():
    service, repo, _, _ = _service()
    with pytest.raises(PlanningGenerationRetryable):
        await service.cancel_by_key('p1', 'draft-1', 'not-reserved')
    await service.generate(_command())
    before = deepcopy(repo.attempts)
    with pytest.raises(PlanningGenerationOperationNotFound):
        await service.cancel_by_key('p1', 'other-draft', 'generate-1')
    assert repo.attempts == before
