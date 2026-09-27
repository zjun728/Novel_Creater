import copy
import pytest
from backend.services.finalization import DecideFinding, ConfirmFinalization, FinalizationConflict
from backend.tests.unit.test_finalization_service import FakeRepository, _awaiting_attempt, _review_service, _snapshot, _change_set
from backend.domain.review_decisions import effective_findings, has_required_findings
from backend.services.draft_review import current_review_report
from backend.tests.unit.test_review_draft_adjustment import ReviewRepository
from backend.tests.unit.test_draft_operation_service import make_service, start_and_finish, FakeGateway
from backend.services.draft_operations import DraftOperationPreconditionFailed


def test_only_optional_findings_can_be_ignored_and_legacy_is_not_optional():
    report = {'findings': [{'id':'old'}, {'id':'required','severity':'required'}, {'id':'optional','severity':'optional'}]}
    assert has_required_findings(report)
    assert [f['id'] for f in effective_findings(report, {'ignoredFindingIds':['optional']})] == ['old','required']
    for item in ('old','required','missing'):
        with pytest.raises(ValueError):
            effective_findings(report, {'ignoredFindingIds':[item]})


class DecisionRepository(FakeRepository):
    def __init__(self):
        super().__init__(snapshots=[_snapshot() for _ in range(10)])
        self.current_attempt = _awaiting_attempt()
        self.view = {'attemptId':'attempt-1','qualityReport':{'contentHash':'f'*64,'status':'completed','findings':[{'id':'optional','severity':'optional'},{'id':'required','severity':'required'},{'id':'legacy'}]},'findingDecisions':{'revision':0,'ignoredFindingIds':[]}}
    async def save_finding_decisions(self, session, project, attempt, report_hash, revision, ignored, now):
        assert self.view['findingDecisions']['revision'] == revision
        self.view = copy.deepcopy(self.view)
        self.view['findingDecisions'] = {'revision':revision+1,'ignoredFindingIds':ignored}
        return True
    def command(self, **overrides):
        return DecideFinding(**{'project_id':'project-1','chapter_session_id':'session-1','expected_revision':1,'expected_revision_hash':self.current_attempt['current_revision_hash'],'attempt_id':'attempt-1','report_hash':'f'*64,'expected_decisions_revision':self.view['findingDecisions']['revision'],'finding_id':'optional','ignored':True,**overrides})


@pytest.mark.asyncio
async def test_ignore_restore_roundtrip_is_versioned_and_does_not_mutate_report():
    repo = DecisionRepository(); service,*_= _review_service(repo)
    original = copy.deepcopy(repo.view['qualityReport'])
    stale = repo.command()
    saved = await service.decide_finding(stale)
    assert saved['findingDecisions'] == {'revision':1,'ignoredFindingIds':['optional']}
    with pytest.raises(FinalizationConflict): await service.decide_finding(stale)
    restored = await service.decide_finding(repo.command(ignored=False))
    assert restored['findingDecisions'] == {'revision':2,'ignoredFindingIds':[]}
    assert restored['qualityReport'] == original


@pytest.mark.asyncio
@pytest.mark.parametrize('overrides', [{'finding_id':'required'},{'finding_id':'legacy'},{'finding_id':'missing'},{'attempt_id':'another'},{'report_hash':'e'*64}])
async def test_invalid_or_unignorable_finding_is_rejected(overrides):
    repo = DecisionRepository(); service,*_= _review_service(repo)
    with pytest.raises((ValueError,FinalizationConflict)): await service.decide_finding(repo.command(**overrides))
    assert repo.view['findingDecisions']['revision'] == 0


@pytest.mark.asyncio
async def test_required_findings_block_confirmation_on_server():
    repo = DecisionRepository(); service,*_= _review_service(repo)
    with pytest.raises(FinalizationConflict, match='REQUIRED_FINDINGS'):
        await service.confirm(ConfirmFinalization('project-1','session-1',1,repo.current_attempt['current_revision_hash']))
    assert not repo.confirmed


@pytest.mark.asyncio
async def test_rewrite_excludes_ignored_opinions_and_preserves_original_report():
    repo = ReviewRepository()
    report = repo.review['view']['qualityReport']
    report['findings'][0].update(severity='optional', suggestedAction='UNIQUE_IGNORED_ACTION')
    repo.review['view']['findingDecisions'] = {'revision':1,'ignoredFindingIds':['0']}
    original = copy.deepcopy(report)
    service, _, gateway, *_ = make_service(repo)
    result = await start_and_finish(service, repo.request(decisionsRevision=1))
    assert result.status == 'completed'
    assert 'UNIQUE_IGNORED_ACTION' not in gateway.calls[0]['messages'][1]['content']
    assert report == original


@pytest.mark.asyncio
async def test_legacy_reference_cannot_skip_saved_decisions():
    repo = ReviewRepository()
    repo.review['view']['findingDecisions'] = {'revision':1,'ignoredFindingIds':[]}
    service, _, gateway, *_ = make_service(repo)
    with pytest.raises(DraftOperationPreconditionFailed):
        await service.start(repo.request())
    assert not gateway.calls


@pytest.mark.asyncio
async def test_decision_revision_drift_before_write_preserves_draft():
    repo = ReviewRepository()
    repo.review['view']['findingDecisions'] = {'revision':1,'ignoredFindingIds':[]}
    original = copy.deepcopy(repo.draft)
    service, *_ = make_service(repo, FakeGateway(on_generate=lambda: repo.review['view']['findingDecisions'].update(revision=2)))
    result = await start_and_finish(service, repo.request(decisionsRevision=1))
    assert result.status == 'expired'
    assert repo.draft == original


@pytest.mark.asyncio
async def test_all_ignored_prevents_generation():
    repo = ReviewRepository()
    findings = repo.review['view']['qualityReport']['findings']
    for item in findings: item['severity'] = 'optional'
    repo.review['view']['findingDecisions'] = {'revision':1,'ignoredFindingIds':[f['id'] for f in findings]}
    service, _, gateway, *_ = make_service(repo)
    with pytest.raises(DraftOperationPreconditionFailed): await service.start(repo.request(decisionsRevision=1))
    assert not gateway.calls
