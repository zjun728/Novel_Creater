import copy
import pytest
from backend.domain.review_disputes import evidence_catalogue, validate_history
from backend.domain.review_decisions import effective_findings, has_required_findings


def history():
    ref = evidence_catalogue({'content': '此前关闭。今天管理员明确宣布重新开放。'}, {})[0]
    ref['quote'] = '今天管理员明确宣布重新开放。'
    note = dict(id='a'*64, revision=1, findingId='required', action='note', category='state_change',
                reason='新指令改变此前状态，不是改写历史。', evidence=[ref], createdAt=1)
    retain = {**copy.deepcopy(note), 'id': 'b'*64, 'revision': 2, 'action': 'retain'}
    return [note, retain]


REPORT = {'findings': [{'id': 'required', 'severity': 'required'}, {'id': 'other', 'severity': 'required'}]}


def test_note_does_not_release_gate_and_retain_affects_only_one_finding():
    events = history()
    assert len(effective_findings(REPORT, {'revision': 1, 'disputeEvents': events[:1]})) == 2
    decisions = {'revision': 2, 'disputeEvents': events}
    assert [f['id'] for f in effective_findings(REPORT, decisions)] == ['other']
    assert has_required_findings(REPORT, decisions)
    assert not has_required_findings({'findings': REPORT['findings'][:1]}, decisions)
    events.append({**copy.deepcopy(events[-1]), 'id': 'c'*64, 'revision': 3, 'action': 'revoke'})
    assert len(effective_findings(REPORT, {'revision': 3, 'disputeEvents': events})) == 2


@pytest.mark.parametrize('change', ['missing_note', 'reason_changed', 'wrong_type', 'fabricated_quote', 'other_report', 'wrong_revision', 'wrong_source', 'no_evidence'])
def test_invalid_dispute_never_releases_gate(change):
    events = history(); report = copy.deepcopy(REPORT)
    if change == 'missing_note': events = events[1:]
    if change == 'reason_changed': events[1]['reason'] = 'different'
    if change == 'wrong_type': report['findings'][0]['severity'] = 'optional'
    if change == 'fabricated_quote': events[0]['evidence'][0]['quote'] = '不存在'
    if change == 'other_report': report['findings'] = []
    if change == 'wrong_revision': events[1]['revision'] = 1
    if change == 'wrong_source': events[0]['evidence'][0]['sourceType'] = 'canon'
    if change == 'no_evidence':
        for event in events: event['evidence'] = []
    with pytest.raises(ValueError): validate_history(events, report, 2)


def test_catalogue_preserves_source_and_text_identity():
    candidate = {'content': '原文'}; snapshot = {'canon_context': {'fact': '历史'}, 'planning_context': {'task': '计划'}}
    records = evidence_catalogue(candidate, snapshot)
    assert records == evidence_catalogue(candidate, snapshot)
    assert {r['sourceType'] for r in records} == {'candidate', 'canon', 'planning'}
    assert len({r['id'] for r in records}) == 3


from backend.tests.unit.test_review_finding_decisions import DecisionRepository
from backend.tests.unit.test_finalization_service import _review_service, _candidate
from backend.services.finalization import DisputeFinding, ConfirmFinalization, FinalizationConflict


class DisputeRepository(DecisionRepository):
    async def save_dispute_events(self, session, project, attempt, report, revision, ignored, events, now):
        assert revision == self.view['findingDecisions']['revision']
        self.view = copy.deepcopy(self.view)
        self.view['findingDecisions'] = {'revision': revision + 1, 'ignoredFindingIds': ignored, 'disputeEvents': events}
        return True


def command(repo, action='note', event_id='a'*64, **overrides):
    record = evidence_catalogue(_candidate(), {})[0]
    args = dict(project_id='project-1', chapter_session_id='session-1', expected_revision=1,
                expected_revision_hash=repo.current_attempt['current_revision_hash'], attempt_id='attempt-1',
                report_hash='f'*64, expected_decisions_revision=repo.view['findingDecisions']['revision'],
                finding_id='required', action=action, category='state_change', reason='作者已核对原文。',
                evidence=({'id': record['id'], 'quote': record['text']},), event_id=event_id)
    return DisputeFinding(**{**args, **overrides})


@pytest.mark.asyncio
async def test_service_note_retain_revoke_and_retry_preserve_report():
    repo = DisputeRepository(); service, *_ = _review_service(repo)
    report = copy.deepcopy(repo.view['qualityReport'])
    first = command(repo)
    await service.dispute_finding(first)
    assert has_required_findings(report, repo.view['findingDecisions'])
    await service.dispute_finding(first)  # exact retry must not append
    assert repo.view['findingDecisions']['revision'] == 1
    await service.dispute_finding(command(repo, 'retain', 'b'*64))
    assert not has_required_findings(report, repo.view['findingDecisions'])
    with pytest.raises(FinalizationConflict):
        await service.confirm(ConfirmFinalization('project-1', 'session-1', 1, repo.current_attempt['current_revision_hash']))
    await service.dispute_finding(command(repo, 'revoke', 'c'*64))
    assert has_required_findings(report, repo.view['findingDecisions'])
    assert repo.view['qualityReport'] == report
    assert len(repo.view['findingDecisions']['disputeEvents']) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('overrides', [
    {'action': 'retain'}, {'report_hash': 'e'*64}, {'attempt_id': 'elsewhere'},
    {'finding_id': 'missing'}, {'expected_decisions_revision': 9},
    {'evidence': ({'id': 'f'*64, 'quote': 'fabricated'},)},
])
async def test_service_rejects_unpinned_or_unsaved_disputes(overrides):
    repo = DisputeRepository(); service, *_ = _review_service(repo)
    with pytest.raises((ValueError, FinalizationConflict)):
        await service.dispute_finding(command(repo, **overrides))
    assert repo.view['findingDecisions']['revision'] == 0


@pytest.mark.asyncio
async def test_rewrite_excludes_only_retained_finding_without_mutating_report():
    from backend.tests.unit.test_review_draft_adjustment import ReviewRepository
    from backend.tests.unit.test_draft_operation_service import make_service, start_and_finish
    repo = ReviewRepository()
    report = repo.review['view']['qualityReport']
    finding = report['findings'][0]
    finding.update(severity='required', suggestedAction='UNIQUE_AUTHOR_REJECTED_ACTION')
    events = history()
    for event in events: event['findingId'] = finding['id']
    repo.review['view']['findingDecisions'] = {'revision': 2, 'ignoredFindingIds': [], 'disputeEvents': events}
    original = copy.deepcopy(report)
    service, _, gateway, *_ = make_service(repo)
    result = await start_and_finish(service, repo.request(decisionsRevision=2))
    assert result.status == 'completed'
    assert 'UNIQUE_AUTHOR_REJECTED_ACTION' not in gateway.calls[0]['messages'][1]['content']
    assert report == original
