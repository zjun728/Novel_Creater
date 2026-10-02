"""Real services with controlled review inputs; no model or product-data writes."""
from hashlib import sha256
import asyncio
from uuid import uuid4
import pytest
from backend.domain.finalization import change_set_hash
from backend.repositories.finalization import FinalizationRepository
from backend.services.finalization import ConfirmFinalization, DisputeFinding, FinalizationConflict
from backend.services.finalization_commit import CommitFinalization
from backend.tests.integration.test_finalization_revocation_mysql import review_service
from backend.tests.integration.test_atomic_finalization_mysql import PROJECT_ID, SESSION_ID, ATTEMPT_ID, HASH_B, _seed, _service
from backend.tests.support.disposable_mysql import transaction_factory_for


def required_finding():
    return {'id': 'qa-required', 'severity': 'required', 'dimension': 'continuity',
            'reason': 'QA：需要作者核对的模型意见', 'suggestedAction': '核对原文',
            'evidence': {'startScalar': 0, 'endScalar': 2, 'excerptHash': sha256('正文'.encode()).hexdigest(), 'confidence': 1.0, 'rationale': 'QA 原文'}}


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_author_dispute_through_confirm_commit_and_history(disposable_mysql):
    tx = transaction_factory_for(disposable_mysql.connection_config)
    repo = FinalizationRepository(); service = review_service(tx, repo)
    async with tx() as session:
        _, changes = await _seed(session, tx, confirm_review=False, quality_findings=[required_finding()])
    confirm = ConfirmFinalization(PROJECT_ID, SESSION_ID, 1, change_set_hash(changes))
    initial = await service.get_review(PROJECT_ID, SESSION_ID)
    with pytest.raises(FinalizationConflict): await service.confirm(confirm)
    evidence = await service.dispute_evidence(confirm)
    ref = next(r for r in evidence['records'] if r['sourceType'] == 'candidate')
    async def act(action, revision, event_id):
        return await service.dispute_finding(DisputeFinding(PROJECT_ID, SESSION_ID, 1, change_set_hash(changes),
            ATTEMPT_ID, initial['qualityReport']['contentHash'], revision, 'qa-required', action, 'other',
            'QA 作者核对原文后确认保留。', ({'id': ref['id'], 'quote': '正文证据。'},), event_id))
    await act('note', 0, 'a'*64)
    with pytest.raises(FinalizationConflict): await service.confirm(confirm)
    await act('retain', 1, 'b'*64)
    with pytest.raises(FinalizationConflict): await service.confirm(confirm)  # stale client lacks revision pin
    replay = await act('retain', 1, 'b'*64)
    assert replay['findingDecisions']['revision'] == 2
    await act('revoke', 2, 'c'*64)
    with pytest.raises(FinalizationConflict):
        await service.confirm(ConfirmFinalization(PROJECT_ID, SESSION_ID, 1, change_set_hash(changes), expected_decisions_revision_pin=3))
    await act('note', 3, 'd'*64)
    retained = await act('retain', 4, 'e'*64)
    assert retained['qualityReport'] == initial['qualityReport']
    await service.confirm(ConfirmFinalization(PROJECT_ID, SESSION_ID, 1, change_set_hash(changes), expected_decisions_revision_pin=5))
    with pytest.raises(FinalizationConflict): await act('revoke', 5, 'f'*64)
    atomic = _service(tx, repo, (str(uuid4()) for _ in range(5)))
    committed = await atomic.commit(CommitFinalization(PROJECT_ID, SESSION_ID, HASH_B, 1, change_set_hash(changes)))
    assert committed.canon_revision == 1
    readback = await service.get_review(PROJECT_ID, SESSION_ID)
    assert readback['status'] == 'committed'
    assert readback['qualityReport'] == initial['qualityReport']
    assert [e['action'] for e in readback['findingDecisions']['disputeEvents']] == ['note', 'retain', 'revoke', 'note', 'retain']


@pytest.mark.mysql
@pytest.mark.asyncio
@pytest.mark.parametrize('winner', ['confirm', 'revoke'])
async def test_confirmation_and_dispute_revocation_serialize(disposable_mysql, winner):
    tx = transaction_factory_for(disposable_mysql.connection_config)
    repo = FinalizationRepository(); service = review_service(tx, repo)
    async with tx() as session:
        _, changes = await _seed(session, tx, confirm_review=False, quality_findings=[required_finding()])
    confirm = ConfirmFinalization(PROJECT_ID, SESSION_ID, 1, change_set_hash(changes), expected_decisions_revision_pin=2)
    view = await service.get_review(PROJECT_ID, SESSION_ID)
    evidence = await service.dispute_evidence(confirm)
    ref = next(r for r in evidence['records'] if r['sourceType'] == 'candidate')
    def command(action, revision, key):
        return DisputeFinding(PROJECT_ID, SESSION_ID, 1, change_set_hash(changes), ATTEMPT_ID,
            view['qualityReport']['contentHash'], revision, 'qa-required', action, 'other', 'QA 核对理由',
            ({'id': ref['id'], 'quote': '正文证据。'},), key*64)
    await service.dispute_finding(command('note', 0, 'a'))
    await service.dispute_finding(command('retain', 1, 'b'))
    acquired, release = asyncio.Event(), asyncio.Event()
    class FirstRepository(FinalizationRepository):
        async def lock_project(self, session, project_id):
            row = await super().lock_project(session, project_id)
            acquired.set(); await release.wait()
            return row
    first = review_service(tx, FirstRepository())
    async def act(instance, action):
        return await instance.confirm(confirm) if action == 'confirm' else await instance.dispute_finding(command('revoke', 2, 'c'))
    task = asyncio.create_task(act(first, winner))
    await asyncio.wait_for(acquired.wait(), 5)
    other = asyncio.create_task(act(service, 'revoke' if winner == 'confirm' else 'confirm'))
    release.set()
    results = await asyncio.wait_for(asyncio.gather(task, other, return_exceptions=True), 15)
    assert not isinstance(results[0], BaseException)
    assert isinstance(results[1], FinalizationConflict)
    current = await service.get_review(PROJECT_ID, SESSION_ID)
    assert bool(current['confirmation']) == (winner == 'confirm')
    assert current['findingDecisions']['disputeEvents'][-1]['action'] == ('retain' if winner == 'confirm' else 'revoke')
