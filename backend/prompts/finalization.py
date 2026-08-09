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
        "rules": [
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
            "entities", "aliases", "canonEvents", "storyProgressEvents",
            "planningPatches", "planningSuggestions",
        ],
        "rules": [
            "Return one complete closed ChangeSet.",
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
