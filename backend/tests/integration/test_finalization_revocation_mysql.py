import asyncio
from uuid import uuid4

import pytest

from backend.domain.finalization import change_set_hash
from backend.repositories.finalization import FinalizationRepository
from backend.services.finalization import FinalizationService, RevokeFinalization
from backend.services.finalization_commit import CommitFinalization
from backend.tests.integration.test_atomic_finalization_mysql import (
    ATTEMPT_ID, HASH_B, NOW, PROJECT_ID, SESSION_ID, _seed, _service as atomic_service,
)
from backend.tests.support.disposable_mysql import transaction_factory_for


def review_service(transactions, repository):
    return FinalizationService(
        transaction_factory=transactions, repository=repository,
        quality_provider=None, extraction_provider=None, clock=lambda: NOW + 2,
    )


async def evidence(session):
    result = {}
    for table in ('finalization_change_set_revisions', 'draft_candidates', 'working_drafts',
                  'project_planning_heads', 'canon_revisions', 'projection_heads', 'final_chapters'):
        result[table] = await session.fetchall(f'SELECT * FROM {table} WHERE project_id=%s', (PROJECT_ID,))
    return result


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_revocation_preserves_all_evidence_and_replays_without_cancelling_new_review(disposable_mysql):
    transactions = transaction_factory_for(disposable_mysql.connection_config)
    repository = FinalizationRepository()
    async with transactions() as session:
        _, changes = await _seed(session, transactions)
        before = await evidence(session)
        original = await repository.lock_attempt(session, PROJECT_ID, SESSION_ID, ATTEMPT_ID)
    service = review_service(transactions, repository)
    command = RevokeFinalization(PROJECT_ID, SESSION_ID, 1, change_set_hash(changes), ATTEMPT_ID)
    result = await service.revoke(command)
    assert result.status == 'cancelled'
    async with transactions() as session:
        assert await evidence(session) == before
        cancelled = await repository.lock_attempt(session, PROJECT_ID, SESSION_ID, ATTEMPT_ID)
        assert cancelled == {**original, 'status': 'cancelled', 'active_slot': None, 'updated_at': NOW + 2}
        newer = {**original, 'id': str(uuid4()), 'idempotency_key': 'e' * 64,
                 'context_manifest': {}, 'created_at': NOW + 3, 'updated_at': NOW + 3}
        await repository.insert_preparing_attempt(session, newer)
    assert await service.revoke(command) == result
    async with transactions() as session:
        active = await repository.lock_current_attempt(session, PROJECT_ID, SESSION_ID)
        assert active['id'] == newer['id'] and active['status'] == 'preparing'
        assert await evidence(session) == before


@pytest.mark.mysql
@pytest.mark.asyncio
@pytest.mark.parametrize('winner', ['revoke', 'commit'])
async def test_commit_and_revocation_serialize_and_only_one_can_win(disposable_mysql, winner):
    transactions = transaction_factory_for(disposable_mysql.connection_config)
    async with transactions() as session:
        _, changes = await _seed(session, transactions)
    acquired, release = asyncio.Event(), asyncio.Event()

    class FirstRepository(FinalizationRepository):
        async def lock_project(self, session, project_id):
            row = await super().lock_project(session, project_id)
            acquired.set()
            await release.wait()
            return row

    repos = {name: FirstRepository() if name == winner else FinalizationRepository()
             for name in ('revoke', 'commit')}
    revoke = review_service(transactions, repos['revoke'])
    commit = atomic_service(transactions, repos['commit'], (str(uuid4()) for _ in range(3)))
    actions = {
        'revoke': lambda: revoke.revoke(RevokeFinalization(PROJECT_ID, SESSION_ID, 1, change_set_hash(changes), ATTEMPT_ID)),
        'commit': lambda: commit.commit(CommitFinalization(PROJECT_ID, SESSION_ID, HASH_B, 1, change_set_hash(changes))),
    }
    first = asyncio.create_task(actions[winner]())
    await asyncio.wait_for(acquired.wait(), 5)
    loser = 'commit' if winner == 'revoke' else 'revoke'
    second = asyncio.create_task(actions[loser]())
    release.set()
    results = await asyncio.wait_for(asyncio.gather(first, second, return_exceptions=True), 15)
    assert not isinstance(results[0], BaseException), results[0]
    assert isinstance(results[1], (ValueError, RuntimeError)), results[1]
    async with transactions() as session:
        attempt = await FinalizationRepository().lock_attempt(session, PROJECT_ID, SESSION_ID, ATTEMPT_ID)
        count = await session.fetchone('SELECT COUNT(*) AS n FROM final_chapters WHERE project_id=%s', (PROJECT_ID,))
    assert attempt['status'] == ('cancelled' if winner == 'revoke' else 'committed')
    assert count['n'] == (0 if winner == 'revoke' else 1)
