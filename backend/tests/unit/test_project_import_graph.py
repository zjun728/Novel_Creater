from __future__ import annotations

import pytest

from backend.domain.project_import_plans import (
    FORMAL_ENTITY_TYPES, INVALID_ENTITY_TYPES, PROVENANCE_ENTITY_TYPES,
    RECONSTRUCTED_ENTITY_TYPES, _validate_graph, all_v1_record_types,
)
from backend.domain.project_imports import ProjectImportInvalid
from backend.domain.project_packages import PackageRecord, RECORD_FIELD_ALLOWLISTS


def test_v1_record_classification_is_a_disjoint_complete_partition() -> None:
    groups = (FORMAL_ENTITY_TYPES, RECONSTRUCTED_ENTITY_TYPES, PROVENANCE_ENTITY_TYPES, INVALID_ENTITY_TYPES)

    assert all_v1_record_types() == frozenset(RECORD_FIELD_ALLOWLISTS)
    assert sum(len(group) for group in groups) == len(all_v1_record_types())
    assert all(left.isdisjoint(right) for index, left in enumerate(groups) for right in groups[index + 1:])


def test_every_v1_record_type_has_an_explicit_validator_declaration() -> None:
    from backend.domain.project_import_plans import VALIDATORS, _OPTIONAL_REF_FIELDS, _REFS

    assert frozenset(VALIDATORS) == all_v1_record_types()
    assert all(declaration.entity_type == entity_type for entity_type, declaration in VALIDATORS.items())
    assert all(fields <= frozenset(_REFS[entity_type]) for entity_type, fields in _OPTIONAL_REF_FIELDS.items())


def test_graph_rejects_dangling_and_wrong_typed_references() -> None:
    dangling = PackageRecord("working-draft", "working-draft:1", data={"chapterLogicalId": "chapter:1"})
    wrong_type = PackageRecord("working-draft", "working-draft:1", data={"chapterLogicalId": "project:1"})
    project = PackageRecord("project", "project:1", data={"label": "P"})

    with pytest.raises(ProjectImportInvalid):
        _validate_graph((dangling,))
    with pytest.raises(ProjectImportInvalid):
        _validate_graph((project, wrong_type))


def test_graph_requires_terminal_operation_states() -> None:
    chapter = PackageRecord("chapter", "chapter:1", data={"label": "C"})
    running = PackageRecord("operation", "operation:1", data={"chapterLogicalId": "chapter:1", "status": "running"})

    with pytest.raises(ProjectImportInvalid):
        _validate_graph((chapter, running))


def test_graph_rejects_head_revision_and_hash_mismatch() -> None:
    digest = "a" * 64
    seed = PackageRecord("creative-seed", "creative-seed:1", data={"label": "S"})
    revision = PackageRecord("creative-seed-revision", "creative-seed-revision:1", revision=4, data={"seedLogicalId": "creative-seed:1", "revision": 4, "contentHash": digest})
    head = PackageRecord("creative-seed-head", "creative-seed-head:1", data={"seedLogicalId": "creative-seed:1", "revisionLogicalId": "creative-seed-revision:1", "revision": 5, "contentHash": digest})

    with pytest.raises(ProjectImportInvalid):
        _validate_graph((seed, revision, head))


def test_graph_requires_contiguous_canon_revisions_and_matching_events() -> None:
    entity = PackageRecord("canon-entity", "canon-entity:1", data={"label": "E"})
    revision = PackageRecord("canon-revision", "canon-revision:1", data={"revisionNumber": 2, "parentRevisionNumber": 0, "sourceType": "bootstrap", "contentHash": "a" * 64})
    event = PackageRecord("canon-event", "canon-event:1", data={"canonRevisionLogicalId": "canon-revision:1", "revisionNumber": 1, "entityLogicalId": "canon-entity:1"})

    with pytest.raises(ProjectImportInvalid):
        _validate_graph((entity, revision, event))


def test_graph_requires_planning_and_chapter_pin_families() -> None:
    planning = PackageRecord("planning-revision", "planning-revision:1", data={"revision": 1, "contentHash": "a" * 64})
    chapter = PackageRecord("chapter", "chapter:1", data={"label": "C"})

    with pytest.raises(ProjectImportInvalid):
        _validate_graph((planning,))
    with pytest.raises(ProjectImportInvalid):
        _validate_graph((planning, chapter))


def test_engine_contract_ref_requires_option_not_batch_and_reference_use_is_formal() -> None:
    contract = PackageRecord("creation-contract", "creation-contract:1", data={"label": "C"})
    batch = PackageRecord("story-engine-batch", "story-engine-batch:1", data={"label": "B"})
    ref = PackageRecord("creation-contract-engine-ref", "creation-contract-engine-ref:1", data={"creationContractLogicalId": "creation-contract:1", "storyEngineLogicalId": "story-engine-batch:1"})

    with pytest.raises(ProjectImportInvalid):
        _validate_graph((contract, batch, ref))


def test_binding_revision_requires_all_eight_ordered_task_items() -> None:
    revision = PackageRecord("project-model-binding-revision", "project-model-binding-revision:1", data={"revision": 1, "contentHash": "a" * 64})
    item = PackageRecord("project-model-binding-item", "project-model-binding-item:1", data={"bindingRevisionLogicalId": "project-model-binding-revision:1", "taskKey": "seed", "resolutionStatus": "unbound"})

    with pytest.raises(ProjectImportInvalid):
        _validate_graph((revision, item))


def test_corpus_fragment_must_match_its_chapter_order_and_window() -> None:
    corpus = PackageRecord("corpus-revision", "corpus-revision:1", data={
        "contentHash": "a" * 64, "byteLength": 1,
        "chapters": [{"logicalId": "corpus-chapter:1", "chapterOrder": 1, "normalizedCharStart": 0, "normalizedCharEnd": 10, "contentHash": "b" * 64}],
        "fragments": [{"logicalId": "corpus-fragment:1", "chapterOrder": 999, "fragmentOrder": 1, "chapterCharStart": 1, "chapterCharEnd": 2, "contentHash": "c" * 64}],
    })

    with pytest.raises(ProjectImportInvalid):
        _validate_graph((corpus,))


def test_seed_revision_recomputes_payload_content_hash() -> None:
    payload = {key: "x" for key in ("title", "genre", "logline", "protagonist", "desire", "coreConflict", "worldPressure", "openingHook", "differentiation")}
    seed = PackageRecord("creative-seed", "creative-seed:1", data={"label": "S"})
    revision = PackageRecord("creative-seed-revision", "creative-seed-revision:1", data={"seedLogicalId": "creative-seed:1", "revision": 1, "payload": payload, "contentHash": "a" * 64})

    with pytest.raises(ProjectImportInvalid):
        _validate_graph((seed, revision))


@pytest.mark.parametrize("record", [
    PackageRecord("provider-history", "provider-history:1", data={"bindingRevisionLogicalId": "project-model-binding-revision:1", "operationLogicalId": "operation:1"}),
    PackageRecord("finalization-record", "finalization-record:1", data={"chapterLogicalId": "chapter:1", "candidateLogicalId": "draft-candidate:1", "changeSetLogicalId": "finalization-change-set:1", "changeSetRevision": 1, "candidateHash": "a" * 64, "changeSetHash": "b" * 64}),
])
def test_graph_rejects_dangling_provider_and_finalization_authorities(record: PackageRecord) -> None:
    with pytest.raises(ProjectImportInvalid) as raised:
        _validate_graph((record,))
    assert raised.value.__cause__ is None


def test_required_reference_and_terminal_state_fields_cannot_be_omitted() -> None:
    contract = PackageRecord("creation-contract", "creation-contract:1", data={"label": "C"})
    engine_ref = PackageRecord("creation-contract-engine-ref", "creation-contract-engine-ref:1", data={"creationContractLogicalId": "creation-contract:1"})
    chapter = PackageRecord("chapter", "chapter:1", data={"label": "C"})
    operation = PackageRecord("operation", "operation:1", data={"chapterLogicalId": "chapter:1"})
    with pytest.raises(ProjectImportInvalid):
        _validate_graph((contract, engine_ref))
    with pytest.raises(ProjectImportInvalid):
        _validate_graph((chapter, operation))
