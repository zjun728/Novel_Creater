from __future__ import annotations

import json
from hashlib import sha256

import pytest
from pydantic import ValidationError

from backend.prompts.finalization import (
    FINALIZATION_MAX_PROMPT_BYTES,
    FinalizationProviderManifest,
    build_extraction_messages,
    build_quality_messages,
)


HASH_A = "a" * 64
HASH_B = "b" * 64


def _manifest(**overrides):
    candidate_prose = overrides.pop("candidate_prose", "沈砚走进山门。")
    value = {
        "schema_version": "finalization-provider-v1",
        "chapter_number": 1,
        "candidate_hash": sha256(candidate_prose.encode("utf-8")).hexdigest(),
        "candidate_prose": candidate_prose,
        "canon_context": {"revision": 0, "entities": []},
        "planning_context": {"revision": 1, "storyBlocks": []},
        "outline_context": {"revision": 1, "chapterGoal": "进入山门"},
        "contract_context": {"revision": 1, "genre": "玄幻"},
        "bible_context": {"revision": 1, "rules": []},
        "policy_version": "quality-v1",
        "binding": {
            "provider_id": "provider-1",
            "model_name": "finalization-model",
            "provider_profile_revision": 3,
        },
    }
    value.update(overrides)
    return FinalizationProviderManifest.model_validate(value, strict=True)


def test_manifest_is_closed_frozen_bounded_and_secret_free():
    value = _manifest()

    assert value.chapter_number == 1
    with pytest.raises(ValidationError):
        value.chapter_number = 2
    with pytest.raises(ValidationError):
        FinalizationProviderManifest.model_validate({
            **value.model_dump(mode="json"),
            "unexpected": True,
        }, strict=True)
    with pytest.raises(ValidationError):
        _manifest(candidate_prose="api_key=PRIVATE_SENTINEL")


def test_quality_and_extraction_messages_keep_roles_separate_and_json_only():
    manifest = _manifest()

    quality = build_quality_messages(manifest=manifest)
    extraction = build_extraction_messages(manifest=manifest)

    assert tuple(item["role"] for item in quality) == ("system", "user")
    assert tuple(item["role"] for item in extraction) == ("system", "user")
    quality_system = json.loads(quality[0]["content"])
    extraction_system = json.loads(extraction[0]["content"])
    quality_user = json.loads(quality[1]["content"])
    extraction_user = json.loads(extraction[1]["content"])
    assert quality_system["task"] == "quality_audit"
    assert quality_system["mayCreateCanonFacts"] is False
    assert quality_system["outputShape"] == {
        "findings": [{
            "id": "unique finding id",
            "dimension": (
                "plot_effectiveness|content_richness|character_vitality|"
                "dialogue_credibility|emotional_naturalness|continuity|"
                "pacing|style_stability|ai_flavor|reading_motivation"
            ),
            "reason": "specific reason",
            "suggestedAction": "specific action",
            "evidence": {
                "startScalar": "integer >= 0",
                "endScalar": "integer > startScalar and <= Candidate length",
                "confidence": "number from 0 to 1",
                "rationale": "brief reason",
            },
        }],
    }
    assert extraction_system["task"] == "finalization_extraction"
    assert extraction_system["singleExtraction"] is True
    assert quality_user == extraction_user
    assert quality_user["candidateProse"] == "沈砚走进山门。"
    assert "candidateProse" not in quality_system
    assert "candidateProse" not in extraction_system


def test_extraction_prompt_declares_the_exact_closed_changeset_shape():
    system = json.loads(build_extraction_messages(manifest=_manifest())[0]["content"])

    shape = system["outputShape"]
    assert set(shape) == {
        "schemaVersion", "title", "summary", "existingEntityIds",
        "entities", "aliases", "canonEvents", "storyProgressEvents",
        "planningPatches", "planningSuggestions",
    }
    assert shape["schemaVersion"] == "finalization-changeset-v1"
    assert "existingEntityIds" in system["requiredCollections"]
    assert shape["entities"][0] == {
        "id": "unique change id",
        "entityType": "person|organization|place|item",
        "canonicalName": "name",
    }
    assert shape["storyProgressEvents"][0]["targetType"] == (
        "story_block|stage|scene_task"
    )
    assert shape["planningPatches"][0]["expectedHash"] == (
        "exact target hash from planningContext"
    )
    assert shape["planningSuggestions"][0]["targetId"] == (
        "exact planning id or null"
    )
    assert system["forbiddenOutput"] == [
        "changeset wrapper", "top-level evidence", "excerptHash",
        "unknown fields", "markdown", "commentary",
    ]


def test_prompt_bytes_are_bounded_before_provider_call():
    manifest = _manifest(candidate_prose="文" * 100_000)

    messages = build_extraction_messages(manifest=manifest)

    rendered = json.dumps(messages, ensure_ascii=False).encode("utf-8")
    assert len(rendered) <= FINALIZATION_MAX_PROMPT_BYTES
    with pytest.raises(ValidationError):
        _manifest(candidate_prose="文" * 100_001)


@pytest.mark.parametrize(
    "field",
    ("canon_context", "planning_context", "outline_context", "contract_context", "bible_context"),
)
def test_context_must_be_finite_strict_json_object(field):
    with pytest.raises(ValidationError):
        _manifest(**{field: {"bad": float("nan")}})
    with pytest.raises(ValidationError):
        _manifest(**{field: ["not", "an", "object"]})
