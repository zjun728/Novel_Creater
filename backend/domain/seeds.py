"""Immutable creative-seed, provenance, and inspiration domain values."""

from __future__ import annotations

import json
import re
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from backend.domain.json_contracts import canonical_hash
from backend.http_errors import PublicDomainError


SEED_FIELD_MAX_LENGTH = 2_000
MAX_SEED_CHAT_TURNS = 12
MAX_SEED_CHAT_TURN_LENGTH = 2_000
MAX_SEED_ASSISTANT_LENGTH = 6_000
MAX_SEED_PROVENANCE_SNAPSHOTS = 4
MAX_SEED_PROVENANCE_NOTES = 8
MAX_SEED_PROVENANCE_NOTE_LENGTH = 300
SEED_PROVENANCE_KEY = "_provenance"
_SECRET_SHAPED_TEXT = re.compile(
    r"(?:api[\s_-]*key|base[\s_-]*url|authorization|"
    r"bearer\s+[A-Za-z0-9]|password\s*[:=]|token\s*[:=])",
    re.IGNORECASE,
)


def _validated_public_notes(value: tuple[str, ...]) -> tuple[str, ...]:
    if any(
        not note
        or len(note) > MAX_SEED_PROVENANCE_NOTE_LENGTH
        or _SECRET_SHAPED_TEXT.search(note)
        for note in value
    ):
        raise ValueError("public provenance note is invalid")
    return value


_INSPIRATION_MESSAGES = {
    "SEED_INSPIRATION_NOT_READY": "Seed inspiration prerequisites are unavailable",
    "SEED_INSPIRATION_NOT_FOUND": "Seed inspiration or project was not found",
    "SEED_INSPIRATION_IDEMPOTENCY_CONFLICT": (
        "Seed inspiration key was already used for a different request"
    ),
    "SEED_INSPIRATION_IN_PROGRESS": "Seed inspiration is already in progress",
    "SEED_INSPIRATION_INVALID_REQUEST": "Seed inspiration request is invalid",
}
_INSPIRATION_STATUS = {
    "SEED_INSPIRATION_NOT_READY": 422,
    "SEED_INSPIRATION_NOT_FOUND": 404,
    "SEED_INSPIRATION_IDEMPOTENCY_CONFLICT": 409,
    "SEED_INSPIRATION_IN_PROGRESS": 409,
    "SEED_INSPIRATION_INVALID_REQUEST": 422,
}


class SeedInspirationFailure(PublicDomainError):
    def __init__(self, code: str) -> None:
        if code not in _INSPIRATION_MESSAGES:
            raise TypeError("SeedInspirationFailure requires a fixed public code")
        self.code = code
        self.message = _INSPIRATION_MESSAGES[code]
        self.status_code = _INSPIRATION_STATUS[code]
        super().__init__()


class SeedPayload(BaseModel):
    """Creative seed contract; four newer fields default for old revisions."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    title: str = Field(min_length=1, max_length=SEED_FIELD_MAX_LENGTH)
    genre: str = Field(min_length=1, max_length=SEED_FIELD_MAX_LENGTH)
    logline: str = Field(min_length=1, max_length=SEED_FIELD_MAX_LENGTH)
    protagonist: str = Field(min_length=1, max_length=SEED_FIELD_MAX_LENGTH)
    desire: str = Field(min_length=1, max_length=SEED_FIELD_MAX_LENGTH)
    coreConflict: str = Field(min_length=1, max_length=SEED_FIELD_MAX_LENGTH)
    worldPressure: str = Field(min_length=1, max_length=SEED_FIELD_MAX_LENGTH)
    openingHook: str = Field(min_length=1, max_length=SEED_FIELD_MAX_LENGTH)
    differentiation: str = Field(min_length=1, max_length=SEED_FIELD_MAX_LENGTH)
    targetAudience: str = Field(default="", max_length=SEED_FIELD_MAX_LENGTH)
    storyPromise: str = Field(default="", max_length=SEED_FIELD_MAX_LENGTH)
    longFormPotential: str = Field(default="", max_length=SEED_FIELD_MAX_LENGTH)
    marketBasis: str = Field(default="", max_length=SEED_FIELD_MAX_LENGTH)


class _FrozenSeedModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )


class SeedChatTurn(_FrozenSeedModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_SEED_CHAT_TURN_LENGTH)


class SeedAssistantTurn(_FrozenSeedModel):
    role: Literal["assistant"]
    content: str = Field(min_length=1, max_length=MAX_SEED_ASSISTANT_LENGTH)

    @field_validator("content")
    @classmethod
    def reject_secret_shaped_text(cls, value: str) -> str:
        if _SECRET_SHAPED_TEXT.search(value):
            raise ValueError("assistant turn contains private configuration")
        return value


def parse_seed_assistant_turn(value: object) -> SeedAssistantTurn:
    try:
        return SeedAssistantTurn.model_validate(value, strict=True)
    except (ValidationError, TypeError, ValueError, RecursionError):
        raise ValueError("invalid seed assistant turn") from None


class SeedProvenanceSelection(_FrozenSeedModel):
    """Client selection of authority IDs; hashes and public facts are resolved."""

    kind: Literal["manual", "market_snapshot", "market_analysis", "ai_chat"]
    snapshot_ids: tuple[str, ...] = Field(
        default=(),
        alias="snapshotIds",
        max_length=MAX_SEED_PROVENANCE_SNAPSHOTS,
    )
    analysis_id: str | None = Field(
        default=None,
        alias="analysisId",
        min_length=1,
        max_length=36,
    )
    inspiration_attempt_id: str | None = Field(
        default=None,
        alias="inspirationAttemptId",
        min_length=1,
        max_length=36,
    )
    public_notes: tuple[str, ...] = Field(
        default=(),
        alias="publicNotes",
        max_length=MAX_SEED_PROVENANCE_NOTES,
    )

    @field_validator("snapshot_ids", "public_notes", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("snapshot_ids")
    @classmethod
    def validate_snapshot_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("snapshot IDs must be unique")
        if any(not item or len(item) > 36 for item in value):
            raise ValueError("snapshot ID is invalid")
        return value

    @field_validator("public_notes")
    @classmethod
    def validate_notes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validated_public_notes(value)

    @model_validator(mode="after")
    def validate_kind_shape(self) -> Self:
        if self.kind == "manual":
            valid = (
                not self.snapshot_ids
                and self.analysis_id is None
                and self.inspiration_attempt_id is None
            )
        elif self.kind == "market_snapshot":
            valid = (
                bool(self.snapshot_ids)
                and self.analysis_id is None
                and self.inspiration_attempt_id is None
            )
        elif self.kind == "market_analysis":
            valid = (
                bool(self.snapshot_ids)
                and self.analysis_id is not None
                and self.inspiration_attempt_id is None
            )
        else:
            valid = (
                bool(self.snapshot_ids)
                and self.analysis_id is not None
                and self.inspiration_attempt_id is not None
            )
        if not valid:
            raise ValueError("provenance selection does not match kind")
        return self


class SeedSnapshotProvenance(_FrozenSeedModel):
    id: str = Field(min_length=1, max_length=36)
    hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_id: str = Field(alias="sourceId", min_length=1, max_length=36)
    source_url: str = Field(alias="sourceURL", min_length=1, max_length=2_048)
    captured_at: int = Field(alias="capturedAt", ge=0)

    @field_validator("source_url")
    @classmethod
    def safe_public_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError("source URL is unsafe")
        return value


class SeedAnalysisProvenance(_FrozenSeedModel):
    id: str = Field(min_length=1, max_length=36)
    hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class SeedInspirationProvenance(_FrozenSeedModel):
    id: str = Field(min_length=1, max_length=36)
    result_hash: str = Field(alias="resultHash", pattern=r"^[0-9a-f]{64}$")


class SeedTopicCandidateProvenance(_FrozenSeedModel):
    id: str = Field(min_length=1, max_length=36)
    version: int = Field(gt=0)
    hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class SeedProvenance(_FrozenSeedModel):
    kind: Literal[
        "manual",
        "market_snapshot",
        "market_analysis",
        "ai_chat",
        "topic_candidate",
    ]
    snapshots: tuple[SeedSnapshotProvenance, ...] = Field(
        max_length=MAX_SEED_PROVENANCE_SNAPSHOTS
    )
    analysis: SeedAnalysisProvenance | None
    inspiration_attempt: SeedInspirationProvenance | None = Field(
        alias="inspirationAttempt"
    )
    topic_candidate: SeedTopicCandidateProvenance | None = Field(
        default=None,
        alias="topicCandidate",
    )
    public_notes: tuple[str, ...] = Field(
        alias="publicNotes",
        max_length=MAX_SEED_PROVENANCE_NOTES,
    )
    provenance_hash: str = Field(
        alias="provenanceHash",
        pattern=r"^[0-9a-f]{64}$",
    )

    @field_validator("snapshots", "public_notes", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("public_notes")
    @classmethod
    def validate_notes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validated_public_notes(value)

    @model_validator(mode="after")
    def validate_kind_shape(self) -> Self:
        snapshot_ids = tuple(item.id for item in self.snapshots)
        if len(snapshot_ids) != len(set(snapshot_ids)):
            raise ValueError("snapshot IDs must be unique")
        if self.kind == "manual":
            valid = (
                not self.snapshots
                and self.analysis is None
                and self.inspiration_attempt is None
                and self.topic_candidate is None
            )
        elif self.kind == "market_snapshot":
            valid = (
                bool(self.snapshots)
                and self.analysis is None
                and self.inspiration_attempt is None
                and self.topic_candidate is None
            )
        elif self.kind == "market_analysis":
            valid = (
                bool(self.snapshots)
                and self.analysis is not None
                and self.inspiration_attempt is None
                and self.topic_candidate is None
            )
        elif self.kind == "ai_chat":
            valid = (
                bool(self.snapshots)
                and self.analysis is not None
                and self.inspiration_attempt is not None
                and self.topic_candidate is None
            )
        else:
            valid = (
                self.analysis is None
                and self.inspiration_attempt is None
                and self.topic_candidate is not None
            )
        if not valid:
            raise ValueError("provenance does not match kind")
        return self


def build_seed_provenance(
    *,
    kind: str,
    snapshots: tuple[SeedSnapshotProvenance, ...],
    analysis: SeedAnalysisProvenance | None,
    inspiration_attempt: SeedInspirationProvenance | None,
    public_notes: tuple[str, ...],
    topic_candidate: SeedTopicCandidateProvenance | None = None,
) -> SeedProvenance:
    document = {
        "kind": kind,
        "snapshots": tuple(
            item.model_dump(mode="json", by_alias=True) for item in snapshots
        ),
        "analysis": (
            analysis.model_dump(mode="json", by_alias=True)
            if analysis is not None
            else None
        ),
        "inspirationAttempt": (
            inspiration_attempt.model_dump(mode="json", by_alias=True)
            if inspiration_attempt is not None
            else None
        ),
        "publicNotes": tuple(public_notes),
    }
    if topic_candidate is not None:
        document["topicCandidate"] = topic_candidate.model_dump(mode="json")
    return SeedProvenance.model_validate(
        {**document, "provenanceHash": canonical_hash(document)},
        strict=True,
    )


def seed_revision_document(
    payload: SeedPayload,
    provenance: SeedProvenance | None,
) -> dict[str, object]:
    document = payload.model_dump(mode="json")
    if provenance is not None:
        document[SEED_PROVENANCE_KEY] = provenance.model_dump(
            mode="json",
            by_alias=True,
        )
    return document


def decode_seed_revision(
    value: object,
) -> tuple[SeedPayload, SeedProvenance | None]:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("seed revision is invalid")
    document = dict(value)
    raw_provenance = document.pop(SEED_PROVENANCE_KEY, None)
    payload = SeedPayload.model_validate(document, strict=True)
    if raw_provenance is None:
        return payload, None
    provenance = SeedProvenance.model_validate(raw_provenance, strict=True)
    facts = provenance.model_dump(
        mode="json",
        by_alias=True,
        exclude={"provenance_hash"},
    )
    if facts.get("topicCandidate") is None:
        facts.pop("topicCandidate", None)
    if canonical_hash(facts) != provenance.provenance_hash:
        raise ValueError("seed provenance hash mismatch")
    return payload, provenance


class SeedMutationCapabilities(BaseModel):
    """Server-owned seed lifecycle facts; clients never infer these."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    referenced: bool
    hasFinalChapters: bool
    canEdit: bool
    canSelect: bool
    canArchive: bool
    canRestore: bool
    canPermanentlyDelete: bool
