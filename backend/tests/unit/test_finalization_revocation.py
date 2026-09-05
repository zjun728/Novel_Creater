from copy import deepcopy

import pytest

from backend.services.finalization import FinalizationConflict, RevokeFinalization
from backend.tests.unit.test_finalization_service import FakeRepository, _awaiting_attempt, _service


class Repository(FakeRepository):
    def __init__(self):
        super().__init__()
        self.attempt = {**_awaiting_attempt(), 'active_slot': 1, 'confirmed_revision': 1,
                        'confirmed_revision_hash': _awaiting_attempt()['current_revision_hash'],
                        'confirmed_at': 123, 'context_manifest_hash': 'old-frozen-manifest'}
        self.revocations = []
        self.receipt = None
        self.final = None
        self.project = True
        self.cas = True

    async def lock_project(self, *args):
        return {'id': 'project-1'} if self.project else None

    async def lock_attempt(self, session, project_id, session_id, attempt_id):
        return self.attempt if (project_id, session_id, attempt_id) == ('project-1', 'session-1', 'attempt-1') else None

    async def lock_commit_by_session(self, *args):
        return self.receipt

    async def lock_final_chapter(self, *args):
        return self.final

    async def revoke_confirmed_review(self, session, **command):
        self.revocations.append(command)
        if self.cas:
            self.attempt.update(status='cancelled', active_slot=None)
        return self.cas


def command(**updates):
    return RevokeFinalization(**{
        'project_id': 'project-1', 'chapter_session_id': 'session-1', 'attempt_id': 'attempt-1',
        'expected_revision': 1, 'expected_revision_hash': _awaiting_attempt()['current_revision_hash'],
        **updates,
    })


@pytest.mark.asyncio
async def test_revocation_keeps_frozen_evidence_and_replays_exact_cancelled_attempt():
    repository = Repository()
    original = deepcopy(repository.attempt)
    service, _, quality, extraction = _service(repository)
    first = await service.revoke(command())
    # A newer attempt/finalized chapter must not be modified by replay of the old cancellation.
    repository.current_attempt = {'id': 'new-attempt'}
    repository.session['status'] = 'final'
    second = await service.revoke(command())
    assert first == second
    assert first.status == 'cancelled'
    assert repository.attempt == {**original, 'status': 'cancelled', 'active_slot': None}
    assert len(repository.revocations) == 1
    assert quality.calls == extraction.calls == repository.inserted_revisions == []
    assert len(repository.snapshots) == 2  # Old preparation authority is intentionally not loaded.
    assert repository.current_attempt == {'id': 'new-attempt'}


@pytest.mark.asyncio
@pytest.mark.parametrize('damage', [
    'archived', 'owner', 'attempt', 'revision', 'hash', 'unconfirmed', 'committing',
    'committed', 'inactive', 'final', 'receipt', 'final_row', 'draft_busy', 'cas',
])
async def test_revocation_fails_closed_for_nonmatching_or_finalizing_state(damage):
    repository = Repository()
    updates = {}
    if damage == 'archived': repository.project = False
    elif damage == 'owner': updates['chapter_session_id'] = 'other-session'
    elif damage == 'attempt': updates['attempt_id'] = 'other-attempt'
    elif damage == 'revision': updates['expected_revision'] = 2
    elif damage == 'hash': updates['expected_revision_hash'] = 'f' * 64
    elif damage == 'unconfirmed': repository.attempt['confirmed_revision'] = None
    elif damage in ('committing', 'committed'): repository.attempt['status'] = damage
    elif damage == 'inactive': repository.attempt['active_slot'] = None
    elif damage == 'final': repository.session['status'] = 'final'
    elif damage == 'receipt': repository.receipt = {'id': 'receipt'}
    elif damage == 'final_row': repository.final = {'id': 'final'}
    elif damage == 'draft_busy': repository.session['active_draft_operation_id'] = 'operation'
    elif damage == 'cas': repository.cas = False
    original = deepcopy(repository.attempt)
    service, _, _, _ = _service(repository)
    with pytest.raises(FinalizationConflict):
        await service.revoke(command(**updates))
    assert repository.attempt == original
    assert len(repository.revocations) == (1 if damage == 'cas' else 0)
