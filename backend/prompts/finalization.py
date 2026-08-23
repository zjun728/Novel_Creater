"""Closed prompt manifests for quality audit and one finalization extraction."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.domain.json_contracts import canonical_json
from backend.prompts.planning import validate_planning_story_context_candidate


FINALIZATION_MAX_MANIFEST_BYTES = 384 * 1024
FINALIZATION_MAX_PROMPT_BYTES = 512 * 1024
_HASH_PATTERN = r"^[0-9a-f]{64}$"
_SAFE_ERROR = "Finalization prompt input invalid"
_STRICT = ConfigDict(
    strict=True,
    frozen=True,
    extra="forbid",
    hide_input_in_errors=True,
)


class FinalizationBinding(BaseModel):
    model_config = _STRICT

    provider_id: str = Field(min_length=1, max_length=100)
    model_name: str = Field(min_length=1, max_length=200)
    provider_profile_revision: int = Field(ge=0)


class FinalizationProviderManifest(BaseModel):
    model_config = _STRICT

    schema_version: Literal["finalization-provider-v1"] = (
        "finalization-provider-v1"
    )
    chapter_number: int = Field(ge=1)
    candidate_hash: str = Field(pattern=_HASH_PATTERN)
    candidate_prose: str = Field(min_length=1, max_length=100_000)
    canon_context: dict[str, object]
    planning_context: dict[str, object]
    outline_context: dict[str, object]
    contract_context: dict[str, object]
    bible_context: dict[str, object]
    policy_version: str = Field(min_length=1, max_length=32)
    binding: FinalizationBinding

    @field_validator(
        "canon_context",
        "planning_context",
        "outline_context",
        "contract_context",
        "bible_context",
        mode="before",
    )
    @classmethod
    def validate_strict_json_object(cls, value):
        if type(value) is not dict:
            raise ValueError(_SAFE_ERROR)
        try:
            rendered = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            return json.loads(rendered)
        except (UnicodeError, TypeError, ValueError, RecursionError):
            raise ValueError(_SAFE_ERROR) from None

    @model_validator(mode="after")
    def validate_frozen_safe_manifest(self) -> Self:
        if sha256(self.candidate_prose.encode("utf-8")).hexdigest() != self.candidate_hash:
            raise ValueError(_SAFE_ERROR)
        snapshot = self.model_dump(mode="json")
        try:
            validate_planning_story_context_candidate(snapshot)
            rendered = canonical_json(snapshot).encode("utf-8")
        except (UnicodeError, TypeError, ValueError, RecursionError):
            raise ValueError(_SAFE_ERROR) from None
        if len(rendered) > FINALIZATION_MAX_MANIFEST_BYTES:
            raise ValueError(_SAFE_ERROR)
        return self


def _user_payload(manifest: FinalizationProviderManifest) -> dict[str, object]:
    return {
        "schemaVersion": manifest.schema_version,
        "chapterNumber": manifest.chapter_number,
        "candidateHash": manifest.candidate_hash,
        "candidateProse": manifest.candidate_prose,
        "canonContext": manifest.canon_context,
        "planningContext": manifest.planning_context,
        "outlineContext": manifest.outline_context,
        "contractContext": manifest.contract_context,
        "bibleContext": manifest.bible_context,
        "policyVersion": manifest.policy_version,
    }


def _messages(
    manifest: FinalizationProviderManifest,
    instruction: dict[str, object],
) -> tuple[dict[str, str], ...]:
    try:
        messages = (
            {"role": "system", "content": canonical_json(instruction)},
            {"role": "user", "content": canonical_json(_user_payload(manifest))},
        )
        rendered = json.dumps(
            messages,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (UnicodeError, TypeError, ValueError, RecursionError):
        raise ValueError(_SAFE_ERROR) from None
    if len(rendered) > FINALIZATION_MAX_PROMPT_BYTES:
        raise ValueError(_SAFE_ERROR)
    return messages


def build_quality_messages(
    *,
    manifest: FinalizationProviderManifest,
) -> tuple[dict[str, str], ...]:
    value = FinalizationProviderManifest.model_validate(manifest, strict=True)
    evidence_shape = {
        "startScalar": "integer >= 0",
        "endScalar": "integer > startScalar and <= Candidate length",
        "confidence": "number from 0 to 1",
        "rationale": "brief reason",
    }
    return _messages(value, {
        "task": "quality_audit",
        "language": "zh-CN",
        "response": "json_object_only",
        "mayCreateCanonFacts": False,
        "mayRewriteCandidate": False,
        "scoreGate": False,
        "requiredFindingFields": [
            "id", "dimension", "reason", "suggestedAction", "evidence",
        ],
        "evidenceFields": [
            "startScalar", "endScalar", "confidence", "rationale",
        ],
        "dimensions": [
            "plot_effectiveness", "content_richness", "character_vitality",
            "dialogue_credibility", "emotional_naturalness", "continuity",
            "pacing", "style_stability", "ai_flavor", "reading_motivation",
        ],
        "outputShape": {
            "findings": [{
                "id": "unique finding id",
                "dimension": (
                    "plot_effectiveness|content_richness|character_vitality|"
                    "dialogue_credibility|emotional_naturalness|continuity|"
                    "pacing|style_stability|ai_flavor|reading_motivation"
                ),
                "reason": "specific reason",
                "suggestedAction": "specific action",
                "evidence": evidence_shape,
            }],
        },
        "rules": [
            "Return outputShape directly as the top-level object; never wrap it.",
            "Return an empty findings array when there is no supported finding.",
            "Return concrete paragraph locations, reasons, and actions.",
            "Return advisory findings only; do not decide finalization.",
            "Do not quote or return the Candidate prose.",
        ],
    })


def build_extraction_messages(
    *,
    manifest: FinalizationProviderManifest,
) -> tuple[dict[str, str], ...]:
    value = FinalizationProviderManifest.model_validate(manifest, strict=True)
    evidence_shape = {
        "startScalar": "integer >= 0",
        "endScalar": "integer > startScalar and <= Candidate length",
        "confidence": "number from 0 to 1",
        "rationale": "brief reason",
    }
    return _messages(value, {
        "task": "finalization_extraction",
        "language": "zh-CN",
        "response": "json_object_only",
        "singleExtraction": True,
        "schemaVersion": "finalization-changeset-v1",
        "evidenceFields": [
            "startScalar", "endScalar", "confidence", "rationale",
        ],
        "requiredCollections": [
            "existingEntityIds", "entities", "aliases", "canonEvents",
            "storyProgressEvents", "planningPatches", "planningSuggestions",
        ],
        "outputShape": {
            "schemaVersion": "finalization-changeset-v1",
            "title": "chapter title",
            "summary": "chapter summary",
            "existingEntityIds": ["exact existing Canon entity id"],
            "entities": [{
                "id": "unique change id",
                "entityType": "person|organization|place|item",
                "canonicalName": "name",
            }],
            "aliases": [{
                "id": "unique change id",
                "entityId": "declared existing or new entity id",
                "alias": "alias",
            }],
            "canonEvents": [{
                "id": "unique change id",
                "entityId": "declared entity id or null",
                "factKind": "stable_definition|dynamic_event|claim",
                "fieldPath": "fact field path",
                "value": "strict JSON value",
                "evidence": evidence_shape,
                "effectiveStartChapter": "integer >= 1 or null",
                "effectiveEndChapter": "integer >= start or null",
                "assertionOperator": "equals|not_equals",
                "valueCardinality": "single|multi",
            }],
            "storyProgressEvents": [{
                "id": "unique change id",
                "targetType": "story_block|stage|scene_task",
                "targetId": "exact target id from planningContext",
                "status": "started|advanced|completed",
                "evidence": evidence_shape,
            }],
            "planningPatches": [{
                "id": "unique change id",
                "targetType": "volume|plot|story_block|stage|scene_task",
                "targetId": "exact target id from planningContext",
                "expectedRevision": "exact target revision from planningContext",
                "expectedHash": "exact target hash from planningContext",
                "fieldPath": "allowed field for the target type",
                "replacement": "strict JSON replacement",
                "evidence": evidence_shape,
            }],
            "planningSuggestions": [{
                "id": "unique change id",
                "targetId": "exact planning id or null",
                "message": "non-authoritative suggestion",
                "evidence": evidence_shape,
            }],
        },
        "forbiddenOutput": [
            "changeset wrapper", "top-level evidence", "excerptHash",
            "unknown fields", "markdown", "commentary",
        ],
        "rules": [
            "Return one complete closed ChangeSet.",
            "Return outputShape directly as the top-level object; never wrap it.",
            "Every collection is required but may be empty when no supported change exists.",
            "Every id field must be unique within the complete ChangeSet.",
            "Use only supplied existing entity and Planning identities.",
            "Do not mutate confirmed or implemented Planning.",
            "Do not return Candidate prose or commentary.",
        ],
    })


__all__ = [
    "FINALIZATION_MAX_PROMPT_BYTES",
    "FinalizationBinding",
    "FinalizationProviderManifest",
    "build_extraction_messages",
    "build_quality_messages",
]
