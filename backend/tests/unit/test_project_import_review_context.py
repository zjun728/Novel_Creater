"""Imported review context is explicit provenance scoped to the restored report."""
from dataclasses import replace

from backend.domain.json_contracts import canonical_hash
from backend.domain.project_import_publication import PublicationEncodingContext, _restored_review_context


def test_restored_context_preserves_source_digest_and_scopes_report_identity():
    context = PublicationEncodingContext(
        command_id="10000000-0000-4000-8000-000000000005", target_project_id="target-project",
        new_title="Restored", records={}, rewritten={}, ids={},
    )
    quality = {"chapterLogicalId": "target-chapter", "candidateLogicalId": "target-candidate",
        "candidateHash": "a" * 64, "contextManifestHash": "b" * 64}
    restored = _restored_review_context(quality, context, "target-quality-1")
    assert restored == {
        "kind": "project-backup-review-context-v1", "projectId": "target-project",
        "qualityReportId": "target-quality-1", "chapterSessionId": "target-chapter",
        "candidateId": "target-candidate", "candidateHash": "a" * 64,
        "sourceContextManifestHash": "b" * 64,
    }
    digest = canonical_hash(restored)
    assert digest != quality["contextManifestHash"]
    assert digest == canonical_hash(_restored_review_context(quality, context, "target-quality-1"))
    assert digest != canonical_hash(_restored_review_context(quality, context, "target-quality-2"))
    assert digest != canonical_hash(_restored_review_context(quality, replace(context, target_project_id="another-project"), "target-quality-1"))
    assert quality["contextManifestHash"] == "b" * 64

import pytest
from backend.domain.finalization import FinalizationChangeSet
from backend.domain.project_import_plans import _rewrite_finalization, _publication_embedded_identities, _validate_review_entity_references
from backend.domain.project_imports import ProjectImportInvalid
from backend.domain.project_packages import PackageRecord
from backend.repositories.project_packages import _rewrite_finalization_change_set


@pytest.mark.parametrize("canon_name,expected", [("Lin", "canon-entity:1"), ("Later name", "finalization-entity:1"), (None, "finalization-entity:1")])
def test_committed_entity_identity_is_shared_but_uncommitted_definition_stays_local(canon_name, expected):
    changes = FinalizationChangeSet.model_validate({
        "schemaVersion": "finalization-changeset-v1", "title": "Chapter", "summary": "A person arrived.",
        "existingEntityIds": [], "entities": [{"id": "person-raw", "entityType": "person", "canonicalName": "Lin"}],
        "aliases": [{"id": "alias-raw", "entityId": "person-raw", "alias": "L"}], "canonEvents": [],
        "storyProgressEvents": [], "planningPatches": [], "planningSuggestions": [],
    })
    definitions = {"person-raw": {"entity_type": "person", "canonical_name": canon_name}} if canon_name else {}
    payload = _rewrite_finalization_change_set(changes, planning_identities={},
        canon_entity_ids={"person-raw": "canon-entity:1"} if canon_name else {}, counters={}, canon_entity_definitions=definitions)
    assert payload["entities"][0]["id"] == payload["aliases"][0]["entityId"] == expected
    record = PackageRecord("finalization-change-set-revision", "finalization-change-set-revision:1", data={"payload": payload})
    embedded = _publication_embedded_identities(record)
    assert (("finalization-entity", expected) in embedded) == (canon_name != "Lin")
    ids = {("finalization-alias", "finalization-alias:1"): "alias-target", ("canon-entity" if canon_name == "Lin" else "finalization-entity", expected): "person-target"}
    _rewrite_finalization(payload, ids)
    assert payload["entities"][0]["id"] == payload["aliases"][0]["entityId"] == "person-target"


def test_committed_entity_reference_requires_exact_canon_definition():
    record = PackageRecord("finalization-change-set-revision", "finalization-change-set-revision:1", data={
        "payload": {"entities": [{"id": "canon-entity:1", "entityType": "person", "canonicalName": "Lin"}]}})
    with pytest.raises(ProjectImportInvalid):
        _validate_review_entity_references(record, {})
    target = PackageRecord("canon-entity", "canon-entity:1", data={"entityType": "person", "canonicalName": "Other"})
    with pytest.raises(ProjectImportInvalid):
        _validate_review_entity_references(record, {("canon-entity", "canon-entity:1"): target})
