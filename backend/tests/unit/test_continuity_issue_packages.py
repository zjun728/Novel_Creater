from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.domain.project_import_plans import _validate_continuity_issue, _validate_graph
from backend.domain.project_imports import ProjectImportInvalid
from backend.domain.project_packages import PackageRecord
from backend.repositories.project_packages import PACKAGE_COLUMN_EXPORT_DECISIONS


BASE = dict(category='fact', severity='high', status='pending', description='需要未来纠偏', createdAt=1, updatedAt=1)


def test_issue_package_covers_every_author_field_without_exporting_physical_ids():
    fields = {key: value for (table, key), value in PACKAGE_COLUMN_EXPORT_DECISIONS.items() if table == 'continuity_issues'}
    assert len(fields) == 12
    assert fields['source_finalization_id'] == 'sourceFinalizationLogicalId'
    assert fields['source_chapter'] == 'sourceChapterNumber'
    assert fields['resolution_note'] == 'resolutionNote'
    assert 'id' not in fields and 'project_id' not in fields


@pytest.mark.parametrize('change', [
    {'status': 'done'}, {'status': 'resolved'}, {'category': 'style'},
    {'severity': 'urgent'}, {'description': ''}, {'suggestion': ' '},
    {'futureTarget': 'x' * 4001}, {'updatedAt': 0}, {'createdAt': True},
    {'sourceChapterNumber': 1}, {'sourceCanonRevision': 1},
])
def test_invalid_issue_package_fails_preflight(change):
    record = PackageRecord('continuity-issue', 'continuity-issue:1', data={**BASE, **change})
    with pytest.raises(ProjectImportInvalid):
        _validate_graph((record,))


def test_issue_source_requires_same_chapter_candidate_finalization_and_canon():
    issue = {**BASE, 'sourceChapterNumber': 2, 'sourceCanonRevision': 2, 'sourceFinalizationLogicalId': 'finalization-record:2'}
    rows = {
        ('finalization-record', 'finalization-record:2'): dict(chapterLogicalId='chapter:2', candidateLogicalId='draft-candidate:2', committedCanonRevision=2, changeSetLogicalId='finalization-change-set:2'),
        ('final-chapter', 'final-chapter:2'): dict(chapterNumber=2, canonRevision=2, chapterLogicalId='chapter:2', candidateLogicalId='draft-candidate:2', finalizationRecordLogicalId='finalization-record:2'),
        ('canon-revision', 'canon-revision:2'): dict(revisionNumber=2, sourceType='finalization', sourceLogicalId='finalization-change-set:2'),
    }
    wrap = lambda values: {key: SimpleNamespace(data=data) for key, data in values.items()}
    _validate_continuity_issue(issue, wrap(rows))
    for kind, field, value in [
        ('final-chapter', 'chapterNumber', 1), ('final-chapter', 'candidateLogicalId', 'draft-candidate:1'),
        ('finalization-record', 'committedCanonRevision', 1), ('canon-revision', 'sourceLogicalId', 'finalization-change-set:1'),
    ]:
        broken = deepcopy(rows)
        key = next(key for key in broken if key[0] == kind)
        broken[key][field] = value
        with pytest.raises(ProjectImportInvalid):
            _validate_continuity_issue(issue, wrap(broken))


def test_issue_with_no_source_and_with_resolution_can_round_trip_public_shape():
    for status in ('pending', 'resolved', 'ignored'):
        record = PackageRecord('continuity-issue', 'continuity-issue:1', data={**BASE, 'status': status, 'resolutionNote': '后续第3章解释此差异' if status != 'pending' else None})
        assert _validate_graph((record,))[(record.entity_type, record.logical_id)] == record
