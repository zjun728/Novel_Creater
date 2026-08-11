from __future__ import annotations

from copy import deepcopy

import pytest

from backend.domain.project_import_plans import (
    FORMAL_ENTITY_TYPES, INVALID_ENTITY_TYPES, PROVENANCE_ENTITY_TYPES,
    RECONSTRUCTED_ENTITY_TYPES, _embedded_identities,
    _publication_embedded_identities, _validate_graph, all_v1_record_types,
)
from backend.domain.project_imports import ProjectImportInvalid
from backend.domain.project_packages import (
    PackageRecord, ProjectPackageInvalid, RECORD_FIELD_ALLOWLISTS,
)


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


def test_draft_candidate_declares_closed_basis_authority() -> None:
    from backend.domain.project_import_plans import VALIDATORS

    assert {
        "chapterLogicalId", "workingDraftRevision", "basisHash", "provenance",
    } <= VALIDATORS["draft-candidate"].required_fields
    assert RECORD_FIELD_ALLOWLISTS["draft-candidate"] >= {
        "workingDraftRevision", "basisHash", "provenance",
    }


def test_draft_candidate_basis_is_closed_and_pinned_fail_closed() -> None:
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.project_import_plans import _validate_candidate_basis

    outline_hash, planning_hash = "1" * 64, "2" * 64
    index = {
        ("chapter-outline-revision", "chapter-outline-revision:1"): PackageRecord(
            "chapter-outline-revision", "chapter-outline-revision:1",
            revision=3, data={"revision": 3, "contentHash": outline_hash},
        ),
        ("planning-revision", "planning-revision:1"): PackageRecord(
            "planning-revision", "planning-revision:1",
            revision=4, data={"revision": 4, "contentHash": planning_hash},
        ),
    }
    provenance = {
        "source": "explicit-save-candidate", "workingDraftRevision": 2,
        "schemaVersion": "draft-candidate-basis-v1",
        "outlineRevisionId": "chapter-outline-revision:1", "outlineRevision": 3,
        "outlineHash": outline_hash,
        "planningRevisionId": "planning-revision:1", "planningRevision": 4,
        "planningHash": planning_hash, "canonRevision": 1,
        "projectionRevision": 1, "projectionHash": "3" * 64,
    }
    basis_keys = tuple(key for key in provenance if key not in {"source", "workingDraftRevision"})
    valid = {
        "workingDraftRevision": 2,
        "provenance": provenance,
        "basisHash": canonical_hash({key: provenance[key] for key in basis_keys}),
    }
    assert _validate_candidate_basis(valid, index)["planningRevision"] == 4

    invalid: list[dict[str, object]] = []
    missing = deepcopy(valid); del missing["provenance"]["projectionHash"]
    invalid.append(missing)
    extra = deepcopy(valid); extra["provenance"]["unknown"] = "closed"
    invalid.append(extra)
    dangling = deepcopy(valid); dangling["provenance"]["outlineRevisionId"] = "chapter-outline-revision:2"
    invalid.append(dangling)
    wrong_type = deepcopy(valid); wrong_type["provenance"]["planningRevisionId"] = "chapter-outline-revision:1"
    invalid.append(wrong_type)
    wrong_pin = deepcopy(valid); wrong_pin["provenance"]["planningRevision"] = 5
    invalid.append(wrong_pin)
    wrong_hash = deepcopy(valid); wrong_hash["provenance"]["outlineHash"] = "4" * 64
    invalid.append(wrong_hash)
    bad_basis = deepcopy(valid); bad_basis["basisHash"] = "5" * 64
    invalid.append(bad_basis)
    for data in invalid:
        with pytest.raises(ProjectImportInvalid):
            _validate_candidate_basis(data, index)


def test_real_bible_exporter_item_ids_are_typed_embedded_identities_only_for_bible() -> None:
    fields = {
        "worldRules": "bible-world-rule", "coreCast": "bible-core-cast",
        "factions": "bible-faction", "longTermConflicts": "bible-long-term-conflict",
        "relationshipDynamics": "bible-relationship-dynamic",
        "continuityGuardrails": "bible-continuity-guardrail",
        "openDesignQuestions": "bible-open-design-question",
    }
    bible = PackageRecord("creation-bible-revision", "creation-bible-revision:1", data={
        "payload": {
            field: [{"id": f"{kind}:1", "text": "authority"}]
            for field, kind in fields.items()
        },
    })

    assert _embedded_identities(bible) == {(kind, f"{kind}:1") for kind in fields.values()}
    with pytest.raises(ProjectImportInvalid):
        _embedded_identities(PackageRecord("corpus-revision", "corpus-revision:1", data={
            "chapters": [{"id": "corpus-chapter:1"}],
        }))


def test_planning_draft_client_keys_are_not_import_authority_identities() -> None:
    draft_payload = {
        "volumes": [{"clientNodeKey": "volume-client"}],
        "plots": [{"clientNodeKey": "plot-client"}],
        "storyBlocks": [{
            "clientNodeKey": "block-client",
            "stages": [{
                "clientNodeKey": "stage-client",
                "sceneTasks": [{"clientNodeKey": "task-client"}],
            }],
        }],
    }

    assert _embedded_identities(PackageRecord(
        "planning-draft", "planning-draft:1", data={"payload": draft_payload},
    )) == set()
    with pytest.raises(ProjectImportInvalid):
        _embedded_identities(PackageRecord(
            "planning-revision", "planning-revision:1", data={"payload": draft_payload},
        ))


def test_planning_aggregate_draft_ids_require_the_exact_typed_logical_prefix() -> None:
    payload = {
        "volumes": [{"id": "planning-volume:1"}],
        "plots": [{"id": "planning-plot:1"}],
        "storyBlocks": [{
            "id": "story-block:1",
            "stages": [{
                "id": "planning-stage:1",
                "sceneTasks": [{"id": "scene-task:1"}],
            }],
        }],
    }
    record = lambda value: PackageRecord(
        "planning-draft", "planning-draft:1", data={"payload": value},
    )

    assert _embedded_identities(record(payload)) == {
        ("planning-volume", "planning-volume:1"),
        ("planning-plot", "planning-plot:1"),
        ("story-block", "story-block:1"),
        ("planning-stage", "planning-stage:1"),
        ("scene-task", "scene-task:1"),
    }
    with pytest.raises(ProjectImportInvalid):
        _embedded_identities(record({**payload, "plots": [{"id": "plot:1"}]}))
    with pytest.raises(ProjectPackageInvalid):
        record({**payload, "plots": [{"id": "81000000-0000-0000-0000-000000000001"}]})


@pytest.mark.parametrize(("record", "expected"), [
    (
        PackageRecord("planning-revision", "planning-revision:1", data={"payload": {
            "volumes": [{"id": "planning-volume:1"}],
            "plots": [{"id": "planning-plot:1"}],
            "storyBlocks": [{"id": "story-block:1", "stages": [{
                "id": "planning-stage:1", "sceneTasks": [{"id": "scene-task:1"}],
            }]}],
        }}),
        {
            ("planning-volume", "planning-volume:1"),
            ("planning-plot", "planning-plot:1"),
            ("story-block", "story-block:1"),
            ("planning-stage", "planning-stage:1"),
            ("scene-task", "scene-task:1"),
        },
    ),
    (
        PackageRecord("finalization-change-set-revision", "finalization-change-set-revision:1", data={"payload": {
            "entities": [{"id": "finalization-entity:1"}],
            "aliases": [{"id": "finalization-alias:1"}],
            "canonEvents": [{"id": "finalization-event:1"}],
            "storyProgressEvents": [{"id": "finalization-progress-event:1"}],
            "planningPatches": [{"id": "finalization-planning-patch:1"}],
            "planningSuggestions": [{"id": "finalization-planning-suggestion:1"}],
        }}),
        {
            ("finalization-entity", "finalization-entity:1"),
            ("finalization-alias", "finalization-alias:1"),
            ("finalization-event", "finalization-event:1"),
            ("finalization-progress-event", "finalization-progress-event:1"),
            ("finalization-planning-patch", "finalization-planning-patch:1"),
            ("finalization-planning-suggestion", "finalization-planning-suggestion:1"),
        },
    ),
    (
        PackageRecord("candidate-quality", "candidate-quality:1", data={
            "findings": [{"id": "quality-finding:1"}],
        }),
        {("quality-finding", "quality-finding:1")},
    ),
])
def test_graph_and_publication_share_current_v1_typed_embedded_slots(
    record: PackageRecord, expected: set[tuple[str, str]],
) -> None:
    assert _embedded_identities(record) == expected
    assert set(_publication_embedded_identities(record)) == expected


@pytest.mark.parametrize("item", [
    {"id": "planning-volume:1"},
    {"id": "planning-plot:1", "logicalId": "planning-plot:2"},
    {"unknownId": "planning-volume:1"},
])
def test_typed_embedded_registry_rejects_duplicate_wrong_kind_and_unknown_keys(item) -> None:
    record = PackageRecord("planning-revision", "planning-revision:1", data={"payload": {
        "volumes": [item, item],
    }})
    with pytest.raises(ProjectImportInvalid):
        _embedded_identities(record)
    with pytest.raises(ProjectImportInvalid):
        _publication_embedded_identities(record)


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


def _canon_revision(logical_order: int, revision: int, parent: int, source: str) -> PackageRecord:
    return PackageRecord(
        "canon-revision",
        f"canon-revision:{logical_order}",
        data={
            "revisionNumber": revision,
            "parentRevisionNumber": parent,
            "sourceType": source,
            "contentHash": f"{logical_order}" * 64,
        },
    )


def test_graph_accepts_production_canon_bootstrap_zero_and_next_revision() -> None:
    bootstrap = _canon_revision(1, 0, 0, "bootstrap")
    next_revision = _canon_revision(2, 1, 0, "manual_test")

    assert _validate_graph((bootstrap,))[("canon-revision", "canon-revision:1")] == bootstrap
    assert len(_validate_graph((bootstrap, next_revision))) == 2


@pytest.mark.parametrize(
    "revisions",
    [
        (_canon_revision(1, 1, 0, "manual_test"),),
        (_canon_revision(1, 0, 0, "bootstrap"), _canon_revision(2, 2, 0, "manual_test")),
        (_canon_revision(1, 0, 0, "bootstrap"), _canon_revision(2, 1, 1, "manual_test")),
    ],
    ids=("missing-zero", "gap", "wrong-parent"),
)
def test_graph_rejects_invalid_zero_based_canon_chain(revisions) -> None:
    with pytest.raises(ProjectImportInvalid):
        _validate_graph(revisions)


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


@pytest.mark.parametrize(
    ("entity_type", "owner_field", "owner_kind", "pin_fields"),
    (
        ("style-contract-template-ref", "styleContractLogicalId", "style-contract", {"templateName", "templateRevision", "contentHash"}),
        ("creation-contract-experience-ref", "creationContractLogicalId", "creation-contract", {"experienceTitle", "experienceRevision", "contentHash"}),
    ),
)
def test_frozen_asset_refs_require_typed_owner_and_asset_pins(
    entity_type: str,
    owner_field: str,
    owner_kind: str,
    pin_fields: set[str],
) -> None:
    from backend.domain.project_import_plans import VALIDATORS, _REFS

    assert _REFS[entity_type][owner_field] == frozenset({owner_kind})
    assert {owner_field, *pin_fields}.issubset(VALIDATORS[entity_type].required_fields)


def test_historical_style_and_bible_lineage_is_required_and_hash_pinned() -> None:
    from backend.domain.json_contracts import canonical_hash
    seed_payload = {key: "x" for key in ("title", "genre", "logline", "protagonist", "desire", "coreConflict", "worldPressure", "openingHook", "differentiation")}
    seed_hash = canonical_hash(seed_payload)
    contract = PackageRecord("creation-contract", "creation-contract:1", revision=2, data={"revision": 2, "selectionRevision": 1, "seedLogicalId": "creative-seed:1", "seedRevisionLogicalId": "creative-seed-revision:1", "seedHash": seed_hash, "contentHash": "a" * 64})
    style = PackageRecord("style-contract", "style-contract:1", revision=2, data={"revision": 2, "creationContractLogicalId": contract.logical_id, "contentHash": "b" * 64})
    seed = PackageRecord("creative-seed", "creative-seed:1", data={"label": "S"})
    seed_revision = PackageRecord("creative-seed-revision", "creative-seed-revision:1", revision=1, data={"seedLogicalId": seed.logical_id, "revision": 1, "payload": seed_payload, "contentHash": seed_hash})
    bible_data = {
        "revision": 3, "selectionRevision": 1, "seedLogicalId": seed.logical_id,
        "seedRevisionLogicalId": seed_revision.logical_id, "seedHash": seed_hash,
        "contractRevision": 2, "creationContractLogicalId": contract.logical_id, "creationHash": "a" * 64,
        "styleContractLogicalId": style.logical_id, "styleHash": "b" * 64,
        "policyVersion": "creation-bible-v1", "contentHash": "d" * 64,
    }
    bible = PackageRecord("creation-bible-revision", "creation-bible-revision:1", revision=3, data=bible_data)

    assert _validate_graph((seed, seed_revision, contract, style, bible))
    with pytest.raises(ProjectImportInvalid):
        _validate_graph((seed, seed_revision, contract, style, PackageRecord(
            "creation-bible-revision", "creation-bible-revision:1", revision=3,
            data={**bible_data, "styleHash": "e" * 64},
        )))
    with pytest.raises(ProjectImportInvalid):
        _validate_graph((seed, seed_revision, contract, PackageRecord(
            "style-contract", "style-contract:1", revision=2,
            data={"revision": 2, "contentHash": "b" * 64},
        ), bible))
