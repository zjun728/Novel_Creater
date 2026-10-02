"""Controlled QA histories, not new model judgments, round-trip through real MySQL."""
import json
from hashlib import sha256
from dataclasses import replace
import pytest
from backend.domain.review_disputes import evidence_catalogue
from backend.domain.json_contracts import canonical_hash
from backend.domain.project_import_plans import _validate_graph
from backend.domain.project_imports import ProjectImportInvalid
from backend.tests.integration.test_continuity_issue_packages_mysql import PROJECT_ID, _seed_finalized_project, _packages, _lifecycle, _publish
from backend.tests.integration.test_project_package_review_history_mysql import _assert_restored_reviews_readable


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_retained_required_disputes_roundtrip_with_exact_history(disposable_mysql, monkeypatch, tmp_path):
    transaction = await _seed_finalized_project(disposable_mysql, monkeypatch)
    originals = []
    async with transaction() as session:
        rows = await session.fetchall('SELECT s.id,s.quality_report_id,q.status,q.deterministic_blocks_json,c.content FROM finalization_change_sets s JOIN candidate_quality_reports q ON q.id=s.quality_report_id JOIN draft_candidates c ON c.id=s.draft_candidate_id WHERE s.project_id=%s ORDER BY s.id', (PROJECT_ID,))
        for row in rows:
            finding = {'id': 'same-finding', 'severity': 'required', 'dimension': 'continuity', 'reason': 'QA disputed opinion', 'suggestedAction': 'Verify',
                       'evidence': {'startScalar': 0, 'endScalar': 1, 'excerptHash': sha256(row['content'][0].encode()).hexdigest(), 'confidence': 1.0, 'rationale': 'QA'}}
            report = {'status': row['status'], 'deterministicBlocks': json.loads(row['deterministic_blocks_json']), 'findings': [finding]}
            ref = evidence_catalogue({'content': row['content']}, {})[0]
            ref['quote'] = row['content'][:12]
            note = {'id': 'a'*64, 'revision': 1, 'findingId': finding['id'], 'action': 'note', 'category': 'other', 'reason': 'QA 作者核对后保留原稿', 'evidence': [ref], 'createdAt': 18}
            events = [note, {**note, 'id': 'b'*64, 'revision': 2, 'action': 'retain', 'createdAt': 19}]
            originals.append(events)
            await session.execute('UPDATE candidate_quality_reports SET findings_json=%s,content_hash=%s WHERE project_id=%s AND id=%s', (json.dumps([finding]), canonical_hash(report), PROJECT_ID, row['quality_report_id']))
            await session.execute('INSERT INTO review_finding_decisions (project_id,attempt_id,report_hash,revision,ignored_finding_ids_json,dispute_events_json,updated_at) VALUES (%s,%s,%s,2,%s,%s,19)', (PROJECT_ID, row['id'], canonical_hash(report), '[]', json.dumps(events)))
    lifecycle = await _lifecycle(transaction).get(PROJECT_ID)
    async with _packages(disposable_mysql, tmp_path) as export:
        package = await export(PROJECT_ID, lifecycle.lifecycle_revision)
        records = [r for r in package.graph_index.values() if r.entity_type == 'review-finding-decisions']
        assert len(records) == len(originals)
        record = records[0]
        bad = replace(record, data={**record.data, 'disputeEvents': [dict(record.data['disputeEvents'][1])]})
        with pytest.raises(ProjectImportInvalid):
            _validate_graph(tuple(bad if r is record else r for r in package.graph_index.values()))
        plan = await _publish(package, transaction)
        async with transaction() as session:
            restored = await session.fetchall('SELECT d.*,q.findings_json FROM review_finding_decisions d JOIN finalization_change_sets s ON s.id=d.attempt_id AND s.project_id=d.project_id JOIN candidate_quality_reports q ON q.id=s.quality_report_id WHERE d.project_id=%s', (plan.target_project_id,))
        assert len(restored) == len(originals)
        for row in restored:
            events = json.loads(row['dispute_events_json']); findings = json.loads(row['findings_json'])
            assert [e['action'] for e in events] == ['note', 'retain']
            assert all(e['findingId'] == findings[0]['id'] != 'same-finding' for e in events)
            assert any(events[0]['evidence'] == old[0]['evidence'] for old in originals)
            assert events[1]['reason'] == 'QA 作者核对后保留原稿'
        await _assert_restored_reviews_readable(transaction, plan.target_project_id)
        lifecycle = await _lifecycle(transaction).get(plan.target_project_id)
        again = await export(plan.target_project_id, lifecycle.lifecycle_revision)
        assert all(len(r.data['disputeEvents']) == 2 for r in again.graph_index.values() if r.entity_type == 'review-finding-decisions')
