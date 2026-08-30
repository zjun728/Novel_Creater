from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.domain import seeds as seed_domain
from backend.domain.json_contracts import canonical_hash
from backend.domain.seeds import SEED_FIELD_MAX_LENGTH, SeedPayload


SEED_VALUES = {
    "title": "典镇山河",
    "genre": "东方奇幻",
    "logline": "少年以县志镇压黑潮。",
    "protagonist": "沈码",
    "desire": "让被抹去的乡民重获姓名。",
    "coreConflict": "修史会同时唤醒镇物。",
    "worldPressure": "黑潮上涨，王朝封存旧志。",
    "openingHook": "县志预写了新县令的死期。",
    "differentiation": "以地方志书写为力量体系。",
}


def make_seed(**overrides: object) -> SeedPayload:
    values: dict[str, object] = dict(SEED_VALUES)
    values.update(overrides)
    return SeedPayload(**values)


def test_seed_payload_has_backward_compatible_thirteen_contract_fields():
    payload = make_seed()

    assert tuple(type(payload).model_fields) == (
        "title",
        "genre",
        "logline",
        "protagonist",
        "desire",
        "coreConflict",
        "worldPressure",
        "openingHook",
        "differentiation",
        "targetAudience",
        "storyPromise",
        "longFormPotential",
        "marketBasis",
    )

    with pytest.raises(ValidationError):
        SeedPayload(**SEED_VALUES, legacyField="legacy")


def test_old_nine_field_revision_decodes_with_empty_new_fields_without_rehash():
    stored_hash = canonical_hash(dict(SEED_VALUES))

    payload, provenance = seed_domain.decode_seed_revision(dict(SEED_VALUES))

    assert payload.targetAudience == ""
    assert payload.storyPromise == ""
    assert payload.longFormPotential == ""
    assert payload.marketBasis == ""
    assert provenance is None
    assert stored_hash != canonical_hash(payload)


def test_topic_candidate_provenance_is_internal_and_hash_valid():
    candidate = seed_domain.SeedTopicCandidateProvenance(
        id="candidate-1",
        version=2,
        hash="c" * 64,
    )
    provenance = seed_domain.build_seed_provenance(
        kind="topic_candidate",
        snapshots=(),
        analysis=None,
        inspiration_attempt=None,
        public_notes=(),
        topic_candidate=candidate,
    )

    assert provenance.kind == "topic_candidate"
    assert provenance.topic_candidate == candidate
    with pytest.raises(ValidationError):
        seed_domain.SeedProvenanceSelection(kind="topic_candidate")


@pytest.mark.parametrize("field_name", tuple(SEED_VALUES))
@pytest.mark.parametrize("invalid", ["", "   \t\n"])
def test_seed_payload_rejects_empty_or_whitespace_only_strings(
    field_name: str,
    invalid: str,
):
    with pytest.raises(ValidationError):
        make_seed(**{field_name: invalid})


@pytest.mark.parametrize("field_name", tuple(SEED_VALUES))
def test_seed_payload_applies_one_explicit_maximum_to_every_field(
    field_name: str,
):
    payload = make_seed(**{field_name: "x" * SEED_FIELD_MAX_LENGTH})

    assert len(payload.model_dump()[field_name]) == SEED_FIELD_MAX_LENGTH

    with pytest.raises(ValidationError):
        make_seed(**{field_name: "x" * (SEED_FIELD_MAX_LENGTH + 1)})


@pytest.mark.parametrize("field_name", tuple(SEED_VALUES))
@pytest.mark.parametrize("invalid", [1, True, b"text"])
def test_seed_payload_is_strict_about_string_types(
    field_name: str,
    invalid: object,
):
    with pytest.raises(ValidationError):
        make_seed(**{field_name: invalid})


def test_seed_payload_strips_outer_whitespace_and_is_frozen():
    payload = make_seed(title="  典镇山河\n")

    assert payload.title == "典镇山河"
    with pytest.raises(ValidationError):
        payload.title = "新标题"


def test_hash_valid_stored_provenance_rejects_secret_shaped_public_notes():
    facts = {
        "kind": "manual",
        "snapshots": [],
        "analysis": None,
        "inspirationAttempt": None,
        "publicNotes": ["apiKey=LEAK"],
    }
    document = {
        **SEED_VALUES,
        "_provenance": {
            **facts,
            "provenanceHash": canonical_hash(facts),
        },
    }

    with pytest.raises(ValidationError):
        seed_domain.decode_seed_revision(document)


def test_hash_valid_stored_provenance_rejects_duplicate_snapshot_ids():
    snapshot = {
        "id": "snapshot-1",
        "hash": "a" * 64,
        "sourceId": "source-1",
        "sourceURL": "https://example.com/rank",
        "capturedAt": 1,
    }
    facts = {
        "kind": "market_snapshot",
        "snapshots": [snapshot, snapshot],
        "analysis": None,
        "inspirationAttempt": None,
        "publicNotes": [],
    }
    document = {
        **SEED_VALUES,
        "_provenance": {
            **facts,
            "provenanceHash": canonical_hash(facts),
        },
    }

    with pytest.raises(ValidationError):
        seed_domain.decode_seed_revision(document)


def test_seed_mutation_capabilities_are_strict_frozen_server_facts():
    facts = seed_domain.SeedMutationCapabilities(
        referenced=True,
        hasFinalChapters=True,
        canEdit=False,
        canSelect=False,
        canArchive=True,
        canRestore=False,
        canPermanentlyDelete=False,
    )

    assert facts.model_dump() == {
        "referenced": True,
        "hasFinalChapters": True,
        "canEdit": False,
        "canSelect": False,
        "canArchive": True,
        "canRestore": False,
        "canPermanentlyDelete": False,
    }
    with pytest.raises(ValidationError):
        facts.canEdit = True
