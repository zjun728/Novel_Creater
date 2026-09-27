from copy import deepcopy
import json

import pytest

from backend.domain.json_contracts import canonical_hash
from backend.domain.project_packages import (
    PackageRecord, ProjectPackageInvalid, canonical_jsonl, freeze_json_value,
)
from backend.domain.seeds import decode_seed_revision, seed_payload_hash
from backend.tests.unit.test_seed_domain import SEED_VALUES


def seed_document(kind="ai_chat"):
    facts = {
        "kind": kind,
        "snapshots": [{
            "id": "11111111-1111-4111-8111-111111111111", "hash": "a" * 64,
            "sourceId": "22222222-2222-4222-8222-222222222222",
            "sourceURL": "https://example.com/public", "capturedAt": 1,
        }],
        "analysis": {"id": "33333333-3333-4333-8333-333333333333", "hash": "b" * 64},
        "inspirationAttempt": {"id": "44444444-4444-4444-8444-444444444444", "resultHash": "c" * 64},
        "publicNotes": ["Frozen source evidence"],
    }
    if kind == "topic_candidate":
        facts.update(analysis=None, inspirationAttempt=None, topicCandidate={
            "id": "55555555-5555-4555-8555-555555555555", "version": 1, "hash": "d" * 64,
        })
    return {**SEED_VALUES, "_provenance": {**facts, "provenanceHash": canonical_hash(facts)}}


def record(payload, kind="creative-seed-revision"):
    return PackageRecord(kind, f"{kind}:1", data={"payload": payload})


@pytest.mark.parametrize("kind", ["ai_chat", "topic_candidate"])
def test_seed_provenance_round_trips_as_immutable_inert_evidence(kind):
    payload = seed_document(kind)
    seed, provenance = decode_seed_revision(payload)
    restored = json.loads(canonical_jsonl([record(payload)]))["data"]["payload"]
    assert restored == payload
    restored_seed, restored_provenance = decode_seed_revision(restored)
    assert restored_provenance == provenance
    assert seed_payload_hash(restored_seed) == seed_payload_hash(seed)
    assert canonical_jsonl([record(restored)]) == canonical_jsonl([record(payload)])


@pytest.mark.parametrize("case", ["hash", "unknown", "shape", "url", "seed_field"])
def test_seed_provenance_rejects_corrupt_or_non_schema_evidence(case):
    payload = deepcopy(seed_document())
    provenance = payload["_provenance"]
    if case == "hash":
        provenance["provenanceHash"] = "0" * 64
    elif case == "unknown":
        provenance["nested"] = {"id": "raw-id"}
    elif case == "shape":
        provenance["kind"] = "manual"
    elif case == "url":
        provenance["snapshots"][0]["sourceURL"] = "https://example.com/?token=private"
    else:
        payload["surpriseId"] = "raw-id"
    if case != "hash":
        provenance["provenanceHash"] = canonical_hash({
            key: value for key, value in provenance.items() if key != "provenanceHash"
        })
    with pytest.raises(ProjectPackageInvalid):
        record(payload)


def test_provenance_exception_cannot_escape_seed_revision_payload():
    payload = seed_document()
    with pytest.raises(ProjectPackageInvalid):
        record(payload, "project")
    with pytest.raises(ProjectPackageInvalid):
        record({"nested": payload})
    with pytest.raises(ProjectPackageInvalid):
        freeze_json_value(payload)


def test_import_retains_inert_seed_provenance_without_live_source_binding():
    from types import SimpleNamespace
    from backend.domain.project_import_plans import (
        _rewrite_record_data, _validate_source_hashes,
    )

    payload = seed_document()
    seed, _ = decode_seed_revision(payload)
    revision = PackageRecord("creative-seed-revision", "creative-seed-revision:1", data={
        "seedLogicalId": "creative-seed:1", "payload": payload,
        "contentHash": seed_payload_hash(seed),
    })
    _validate_source_hashes(SimpleNamespace(graph_index={"revision": revision}))
    rewritten = _rewrite_record_data(
        revision, {("creative-seed", "creative-seed:1"): "new-seed-id"}, {},
    )
    assert rewritten["seedLogicalId"] == "new-seed-id"
    assert rewritten["payload"] == payload
