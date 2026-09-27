from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.domain.planning import DraftPlanningAggregate, PlanningAggregate, normalize_planning_aggregate, planning_content_hash
from backend.domain.project_import_plans import (
    _authority_hash, _publication_embedded_identities, _rewrite_planning,
    _rewrite_planning_draft, _validate_character_design_references,
    _validate_publication_references,
)
from backend.domain.project_imports import ProjectImportInvalid
from backend.domain.project_packages import PackageRecord, ProjectPackageInvalid, freeze_json_value
from backend.repositories.project_packages import _register_planning_nodes, _rewrite_planning_payload
from backend.tests.unit.test_planning_domain import _valid_payload


def _planning(entity_id="physical-person", *, formal=True):
    raw = _valid_payload()
    raw["plots"][0]["plotType"] = "character"
    raw["plots"][0]["characterDesign"] = {
        "entityId": entity_id, "displayName": "沈砚",
        "nodes": [{"id": "local-node-1", "title": "承担责任", "goal": "保护同行者", "expectedChapter": 3}],
    }
    draft = DraftPlanningAggregate.model_validate(raw)
    counter = iter(range(100))
    return normalize_planning_aggregate(draft, previous_confirmed=None, previous_draft=None,
        id_factory=lambda: f"physical-node-{next(counter)}") if formal else draft


@pytest.mark.parametrize("entity_id", [None, "physical-person"])
@pytest.mark.parametrize("formal", [False, True])
def test_character_design_export_import_round_trip_remaps_person_only(entity_id, formal):
    original = _planning(entity_id, formal=formal)
    identities = {}
    _register_planning_nodes(original, identities, {})
    exported = _rewrite_planning_payload(original, identities,
        {"physical-person": "canon-entity:1"}, {"physical-person": "person"})
    kind = "planning-revision" if formal else "planning-draft"
    record = PackageRecord(kind, f"{kind}:1", data={"payload": exported})
    _validate_character_design_references(record, {
        ("canon-entity", "canon-entity:1"): SimpleNamespace(data={"entityType": "person"}),
    })
    embedded = _publication_embedded_identities(record)
    assert ("canon-entity", "canon-entity:1") not in embedded
    target_ids = {(kind, logical): f"imported-{i}" for i, (kind, logical) in enumerate(embedded)}
    target_ids[("canon-entity", "canon-entity:1")] = "imported-person"
    imported = deepcopy(exported)
    (_rewrite_planning if formal else _rewrite_planning_draft)(imported, target_ids)
    design = imported["plots"][0]["characterDesign"]
    assert design["entityId"] == ("imported-person" if entity_id else None)
    assert design["nodes"][0]["id"] == "local-node-1"
    assert design["nodes"][0]["goal"] == "保护同行者"
    assert design["nodes"][0]["expectedChapter"] == 3
    digest = _authority_hash(kind, {"payload": imported})
    if formal:
        restored = PlanningAggregate.model_validate(imported)
        assert digest == planning_content_hash(restored.model_dump(mode="json", by_alias=True, exclude={"content_hash"}))
        assert restored.plots[0].content_hash != original.plots[0].content_hash
    else:
        assert DraftPlanningAggregate.model_validate(imported).plots[0].character_design.entity_id == design["entityId"]


@pytest.mark.parametrize("target", [None, "place", "organization", "item"])
def test_export_rejects_missing_or_non_person_reference(target):
    original = _planning()
    identities = {}
    _register_planning_nodes(original, identities, {})
    with pytest.raises(ProjectPackageInvalid):
        _rewrite_planning_payload(original, identities,
            {"physical-person": "canon-entity:1"} if target else {},
            {"physical-person": target} if target else {})


@pytest.mark.parametrize("change", [
    {"entityId": "canon-entity:404"}, {"entityId": "planning-plot:1"},
    {"entityId": "canon-entity:2"}, {"unexpected": "field"},
    {"nodes": [{"id": "same", "title": "A"}, {"id": "same", "title": "B"}]},
])
def test_import_preflight_rejects_invalid_or_wrong_type_character_design(change):
    design = {"entityId": "canon-entity:1", "displayName": "人物", "nodes": [], **change}
    record = PackageRecord("planning-draft", "planning-draft:1", data={"payload": {"plots": [{"characterDesign": design}]}})
    index = {
        ("canon-entity", "canon-entity:1"): SimpleNamespace(data={"entityType": "person"}),
        ("canon-entity", "canon-entity:2"): SimpleNamespace(data={"entityType": "place"}),
    }
    with pytest.raises(ProjectImportInvalid):
        _validate_character_design_references(record, index)


def test_legacy_export_payload_has_no_new_null_field():
    draft = DraftPlanningAggregate.model_validate(_valid_payload())
    identities = {}
    _register_planning_nodes(draft, identities, {})
    exported = _rewrite_planning_payload(draft, identities)
    assert all("characterDesign" not in plot for plot in exported["plots"])


@pytest.mark.parametrize("payload", [
    {"nodes": [{"id": "local-node"}]},
    {"characterDesign": {"nodes": [{"id": "local-node"}]}},
    {"plots": [{"characterDesign": {"nodes": [{"id": "ok", "entityId": "physical-id"}]}}]},
    {"plots": [{"characterDesign": {"nodes": [{"id": " "}]}}]},
])
def test_local_node_id_exception_never_allows_other_physical_identity_slots(payload):
    with pytest.raises(ProjectPackageInvalid):
        freeze_json_value(payload)


def test_direct_publication_preflight_also_rejects_dangling_person():
    raw = _planning("canon-entity:99", formal=False).model_dump(mode="json", by_alias=True)
    # Exporting draft node keys is part of the producer; no physical node IDs
    # are introduced in this deliberately malformed reference fixture.
    record = PackageRecord("planning-draft", "planning-draft:1", data={"payload": raw})
    package = SimpleNamespace(graph_index={(record.entity_type, record.logical_id): record})
    with pytest.raises(ProjectImportInvalid):
        _validate_publication_references(package)
