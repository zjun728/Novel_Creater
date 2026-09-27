import pytest

from backend.domain.project_import_plans import _empty_project_head, _validate_graph, build_publication_plan
from backend.domain.project_imports import ProjectImportInvalid
from backend.domain.project_packages import PackageRecord
from backend.tests.unit.test_project_import_authority_rewrite import _package, _project_record


HEADS = {
    'project-contract-head': ('project_contract_heads', {
        'creationContractLogicalId': 'creation_contract_id', 'styleContractLogicalId': 'style_contract_id',
        'creationHash': 'creation_hash', 'styleHash': 'style_hash',
    }),
    'project-bible-head': ('project_bible_heads', {'bibleRevisionLogicalId': 'bible_revision_id', 'contentHash': 'content_hash'}),
    'project-planning-head': ('project_planning_heads', {'planningRevisionLogicalId': 'planning_revision_id', 'contentHash': 'content_hash'}),
    'project-chapter-outline-head': ('project_chapter_outline_heads', {'outlineRevisionLogicalId': 'outline_revision_id', 'contentHash': 'content_hash'}),
}


def source_authority_fields(kind):
    if kind == 'project-contract-head':
        return ('creationContractLogicalId', 'styleContractLogicalId', 'contentHash')
    return tuple(HEADS[kind][1])


def record(kind, **changes):
    data = {'revision': 0, 'updatedAt': 2}
    if kind == 'project-chapter-outline-head':
        data['chapterNumber'] = 1
    return PackageRecord(kind, f'{kind}:1', data=data | changes)


@pytest.mark.parametrize('kind', HEADS)
@pytest.mark.parametrize('explicit_nulls', [False, True])
def test_empty_head_passes_graph_rewrite_and_encodes_complete_null_authority(kind, explicit_nulls):
    table, fields = HEADS[kind]
    source_fields = source_authority_fields(kind)
    head = record(kind, **({field: None for field in source_fields} if explicit_nulls else {}))
    assert _validate_graph((head,))
    plan = build_publication_plan(_package((_project_record(), head)),
                                  '97000000-0000-4000-8000-000000000002', 'Imported')
    batch = next(batch for batch in plan.batches if batch.table == table)
    row = dict(zip(batch.columns, batch.rows[0], strict=True))
    assert row['revision'] == 0
    assert row['updated_at'] == 2
    assert all(row[column] is None for column in fields.values())


@pytest.mark.parametrize('kind', HEADS)
def test_empty_head_rejects_every_nonnull_authority_field(kind):
    for field in source_authority_fields(kind):
        with pytest.raises(ProjectImportInvalid):
            _validate_graph((record(kind, **{field: ('a' * 64 if 'Hash' in field else 'creation-contract:1')}),))


@pytest.mark.parametrize('kind', HEADS)
@pytest.mark.parametrize('revision', [True, -1, '0', None, 1])
def test_missing_nonzero_refs_and_invalid_revision_are_not_treated_as_empty(kind, revision):
    with pytest.raises(ProjectImportInvalid):
        _validate_graph((record(kind, revision=revision),))


@pytest.mark.parametrize('kind', HEADS)
def test_nonzero_head_requires_complete_authority_tuple(kind):
    fields = source_authority_fields(kind)
    data = {field: ('a' * 64 if 'Hash' in field else 'creation-contract:1') for field in fields}
    assert not _empty_project_head(record(kind, revision=1, **data))
    for field in fields:
        if kind == 'project-contract-head' and field == 'contentHash':
            continue
        with pytest.raises(ProjectImportInvalid):
            _empty_project_head(record(kind, revision=1, **(data | {field: None})))
