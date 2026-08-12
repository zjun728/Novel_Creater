from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from backend.domain.finalization import (
    ChangeSetSource,
    ConfirmationPin,
    EvidenceLocation,
    FinalizationAuthority,
    FinalizationChangeSet,
    FinalizationState,
    QualityReportPayload,
    QualityReportStatus,
    change_set_hash,
    change_set_payload,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _evidence(start=0, end=4):
    return {
        "startScalar": start,
        "endScalar": end,
        "excerptHash": HASH_A,
        "confidence": 0.9,
        "rationale": "正文直接陈述",
    }


def _payload():
    return {
        "schemaVersion": "finalization-changeset-v1",
        "title": "第一章 山门",
        "summary": "主角抵达山门并作出选择。",
        "existingEntityIds": [],
        "entities": [{
            "id": "entity-1",
            "entityType": "person",
            "canonicalName": "沈砚",
        }],
        "aliases": [{
            "id": "alias-1",
            "entityId": "entity-1",
            "alias": "阿砚",
        }],
        "canonEvents": [{
            "id": "event-1",
            "entityId": "entity-1",
            "factKind": "dynamic_event",
            "fieldPath": "state.location",
            "value": {"place": "山门", "safe": True},
            "evidence": _evidence(),
            "effectiveStartChapter": 1,
            "effectiveEndChapter": None,
            "assertionOperator": "equals",
            "valueCardinality": "single",
        }],
        "storyProgressEvents": [{
            "id": "progress-1",
            "targetType": "story_block",
            "targetId": "block-1",
            "status": "advanced",
            "evidence": _evidence(5, 9),
        }],
        "planningPatches": [{
            "id": "patch-1",
            "targetType": "story_block",
            "targetId": "block-2",
            "expectedRevision": 3,
            "expectedHash": HASH_B,
            "fieldPath": "openQuestions",
            "replacement": ["谁在追踪沈砚？"],
            "evidence": _evidence(10, 14),
        }],
        "planningSuggestions": [{
            "id": "suggestion-1",
            "targetId": "block-2",
            "message": "后续可延长山门冲突。",
            "evidence": _evidence(10, 14),
        }],
    }


def test_change_set_accepts_closed_payload_and_has_stable_alias_hash():
    value = FinalizationChangeSet.model_validate(_payload())

    assert value.title == "第一章 山门"
    assert change_set_payload(value) == _payload()
    assert change_set_hash(value) == change_set_hash(
        FinalizationChangeSet.model_validate(_payload())
    )
    assert len(change_set_hash(value)) == 64


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("unexpected",), True),
        (("canonEvents", 0, "unexpected"), True),
        (("canonEvents", 0, "factKind"), "invented"),
        (("storyProgressEvents", 0, "status"), "almost_done"),
        (("planningPatches", 0, "fieldPath"), "__proto__"),
    ],
)
def test_change_set_rejects_unknown_fields_and_open_enums(path, value):
    payload = _payload()
    cursor = payload
    for part in path[:-1]:
        cursor = cursor[part]
    cursor[path[-1]] = value

    with pytest.raises(ValidationError):
        FinalizationChangeSet.model_validate(payload)


def test_change_set_rejects_duplicate_ids_across_all_change_collections():
    payload = _payload()
    payload["planningSuggestions"][0]["id"] = "event-1"

    with pytest.raises(ValidationError, match="duplicate change id"):
        FinalizationChangeSet.model_validate(payload)


@pytest.mark.parametrize("bad_value", [math.nan, math.inf, -math.inf, object()])
def test_change_set_rejects_non_strict_json_values(bad_value):
    payload = _payload()
    payload["canonEvents"][0]["value"] = {"bad": bad_value}

    with pytest.raises(ValidationError, match="strict JSON"):
        FinalizationChangeSet.model_validate(payload)


def test_nested_json_and_sequences_are_deeply_immutable():
    payload = _payload()
    value = FinalizationChangeSet.model_validate(payload)
    payload["canonEvents"][0]["value"]["place"] = "被篡改"
    payload["planningPatches"][0]["replacement"].append("被篡改")

    assert change_set_payload(value)["canonEvents"][0]["value"] == {
        "place": "山门",
        "safe": True,
    }
    assert change_set_payload(value)["planningPatches"][0]["replacement"] == [
        "谁在追踪沈砚？"
    ]
    with pytest.raises(ValidationError):
        value.title = "不可修改"


@pytest.mark.parametrize(
    ("start", "end", "confidence"),
    [(-1, 1, 0.5), (2, 2, 0.5), (3, 2, 0.5), (0, 1, -0.1), (0, 1, 1.1)],
)
def test_evidence_requires_bounded_half_open_scalar_range(start, end, confidence):
    with pytest.raises(ValidationError):
        EvidenceLocation.model_validate({
            **_evidence(start, end),
            "confidence": confidence,
        })


def test_change_set_rejects_alias_that_targets_no_new_or_known_entity():
    payload = _payload()
    payload["aliases"][0]["entityId"] = "missing"

    with pytest.raises(ValidationError, match="alias entityId"):
        FinalizationChangeSet.model_validate(payload)


def test_change_set_can_explicitly_allow_an_existing_canon_entity():
    payload = _payload()
    payload["existingEntityIds"] = ["existing-1"]
    payload["aliases"][0]["entityId"] = "existing-1"
    payload["canonEvents"][0]["entityId"] = "existing-1"

    value = FinalizationChangeSet.model_validate(payload)

    assert value.existing_entity_ids == ("existing-1",)


def test_change_set_rejects_whitespace_only_identity_or_title():
    for path in (("title",), ("entities", 0, "id")):
        payload = _payload()
        cursor = payload
        for part in path[:-1]:
            cursor = cursor[part]
        cursor[path[-1]] = "   "
        with pytest.raises(ValidationError, match="trimmed non-empty"):
            FinalizationChangeSet.model_validate(payload)


def test_existing_entity_ids_cannot_overlap_new_entities():
    payload = _payload()
    payload["existingEntityIds"] = ["entity-1"]

    with pytest.raises(ValidationError, match="existing and new entity"):
        FinalizationChangeSet.model_validate(payload)


def test_authority_and_confirmation_pin_require_exact_hash_and_revision_types():
    authority = FinalizationAuthority.model_validate({
        "projectId": "project-1",
        "chapterSessionId": "session-1",
        "candidateId": "candidate-1",
        "candidateHash": HASH_A,
        "expectedCanonRevision": 0,
        "expectedPlanningHash": HASH_B,
        "expectedOutlineHash": HASH_C,
        "contextManifestHash": HASH_A,
        "idempotencyKey": HASH_B,
        "requestFingerprint": HASH_C,
    })
    pin = ConfirmationPin.model_validate({
        "expectedChangeSetRevision": 1,
        "expectedChangeSetHash": HASH_A,
    })

    assert authority.expected_canon_revision == 0
    assert pin.expected_change_set_revision == 1
    for field, bad in (
        ("expectedCanonRevision", True),
        ("candidateHash", "A" * 64),
        ("idempotencyKey", "short"),
    ):
        payload = authority.model_dump(by_alias=True)
        payload[field] = bad
        with pytest.raises(ValidationError):
            FinalizationAuthority.model_validate(payload)


def test_quality_report_is_closed_advisory_and_hash_bound():
    report = QualityReportPayload.model_validate({
        "status": "completed",
        "deterministicBlocks": [{
            "code": "candidate_hash_drift",
            "message": "候选内容已变化",
            "evidence": None,
        }],
        "findings": [{
            "id": "finding-1",
            "dimension": "dialogue_credibility",
            "reason": "人物语气缺少区分",
            "suggestedAction": "调整第二段对话",
            "evidence": _evidence(),
        }],
    })

    assert report.status is QualityReportStatus.COMPLETED
    assert report.findings[0].dimension.value == "dialogue_credibility"


def test_public_state_enums_are_exact():
    assert {item.value for item in FinalizationState} == {
        "preparing", "awaiting_author", "committing", "committed",
        "invalidated", "cancelled", "failed",
    }
    assert {item.value for item in ChangeSetSource} == {
        "extraction", "author_correction",
    }
