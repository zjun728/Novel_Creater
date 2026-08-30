"""Strict global Topic Center values with no project write authority."""

from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from backend.http_errors import PublicDomainError


MAX_TOPIC_TEXT_LENGTH = 2_000
MAX_TOPIC_MESSAGE_LENGTH = 20_000
MAX_TOPIC_SUGGESTIONS = 4
_HASH_PATTERN = r"^[0-9a-f]{64}$"


def _author_text(value: str) -> str:
    if not value.strip():
        raise ValueError("author text must not be blank")
    if any(
        ord(character) < 32 and character not in "\t\r\n"
        or ord(character) == 127
        for character in value
    ):
        raise ValueError("author text contains control characters")
    return value


class _StrictTopicValue(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )


class TopicDirectionPayload(_StrictTopicValue):
    title: str = Field(min_length=1, max_length=MAX_TOPIC_TEXT_LENGTH)
    genre_opportunity: str = Field(
        alias="genreOpportunity",
        min_length=1,
        max_length=MAX_TOPIC_TEXT_LENGTH,
    )
    target_audience: str = Field(
        alias="targetAudience",
        min_length=1,
        max_length=MAX_TOPIC_TEXT_LENGTH,
    )
    reader_promise: str = Field(
        alias="readerPromise",
        min_length=1,
        max_length=MAX_TOPIC_TEXT_LENGTH,
    )
    differentiation: str = Field(min_length=1, max_length=MAX_TOPIC_TEXT_LENGTH)
    long_form_potential: str = Field(
        alias="longFormPotential",
        min_length=1,
        max_length=MAX_TOPIC_TEXT_LENGTH,
    )
    risks: str = Field(min_length=1, max_length=MAX_TOPIC_TEXT_LENGTH)
    evidence_summary: str = Field(
        alias="evidenceSummary",
        min_length=1,
        max_length=MAX_TOPIC_TEXT_LENGTH,
    )

    @field_validator("*")
    @classmethod
    def validate_author_text(cls, value: str) -> str:
        return _author_text(value)


class TopicCandidatePayload(_StrictTopicValue):
    title: str = Field(min_length=1, max_length=MAX_TOPIC_TEXT_LENGTH)
    genre: str = Field(min_length=1, max_length=MAX_TOPIC_TEXT_LENGTH)
    logline: str = Field(min_length=1, max_length=MAX_TOPIC_TEXT_LENGTH)
    target_audience: str = Field(
        alias="targetAudience",
        min_length=1,
        max_length=MAX_TOPIC_TEXT_LENGTH,
    )
    protagonist: str = Field(min_length=1, max_length=MAX_TOPIC_TEXT_LENGTH)
    desire: str = Field(min_length=1, max_length=MAX_TOPIC_TEXT_LENGTH)
    core_conflict: str = Field(
        alias="coreConflict",
        min_length=1,
        max_length=MAX_TOPIC_TEXT_LENGTH,
    )
    world_pressure: str = Field(
        alias="worldPressure",
        min_length=1,
        max_length=MAX_TOPIC_TEXT_LENGTH,
    )
    opening_hook: str = Field(
        alias="openingHook",
        min_length=1,
        max_length=MAX_TOPIC_TEXT_LENGTH,
    )
    differentiation: str = Field(min_length=1, max_length=MAX_TOPIC_TEXT_LENGTH)
    story_promise: str = Field(
        alias="storyPromise",
        min_length=1,
        max_length=MAX_TOPIC_TEXT_LENGTH,
    )
    long_form_potential: str = Field(
        alias="longFormPotential",
        min_length=1,
        max_length=MAX_TOPIC_TEXT_LENGTH,
    )
    market_basis: str = Field(
        alias="marketBasis",
        min_length=1,
        max_length=MAX_TOPIC_TEXT_LENGTH,
    )

    @field_validator("*")
    @classmethod
    def validate_author_text(cls, value: str) -> str:
        return _author_text(value)


class TopicDirectionSuggestion(TopicDirectionPayload):
    """Unsaved model suggestion; intentionally has no identity fields."""


class TopicCandidateSuggestion(TopicCandidatePayload):
    """Unsaved model suggestion; intentionally has no identity fields."""


class TopicAssistantResult(_StrictTopicValue):
    reply: str = Field(min_length=1, max_length=MAX_TOPIC_MESSAGE_LENGTH)
    direction_suggestions: tuple[TopicDirectionSuggestion, ...] = Field(
        default=(),
        alias="directionSuggestions",
        max_length=MAX_TOPIC_SUGGESTIONS,
    )
    candidate_suggestions: tuple[TopicCandidateSuggestion, ...] = Field(
        default=(),
        alias="candidateSuggestions",
        max_length=MAX_TOPIC_SUGGESTIONS,
    )

    @field_validator("direction_suggestions", "candidate_suggestions", mode="before")
    @classmethod
    def freeze_suggestions(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("reply")
    @classmethod
    def validate_reply(cls, value: str) -> str:
        return _author_text(value)


class TopicEvidenceRef(_StrictTopicValue):
    snapshot_id: str = Field(alias="snapshotId", min_length=1, max_length=36)
    content_hash: str = Field(alias="contentHash", pattern=_HASH_PATTERN)


class TopicSubjectRef(_StrictTopicValue):
    kind: Literal["direction", "candidate"]
    id: str = Field(min_length=1, max_length=36)
    version: int = Field(gt=0)
    content_hash: str = Field(alias="contentHash", pattern=_HASH_PATTERN)


class TopicMessage(_StrictTopicValue):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_TOPIC_MESSAGE_LENGTH)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        return _author_text(value)


_FAILURE_FACTS = {
    "TOPIC_NOT_FOUND": (404, "Topic record was not found"),
    "TOPIC_PROVIDER_NOT_READY": (422, "Topic model is not ready"),
    "TOPIC_PROVIDER_FAILED": (503, "Topic model request failed"),
    "TOPIC_INVALID_RESPONSE": (502, "Topic model response was invalid"),
    "TOPIC_REQUEST_CONFLICT": (409, "Topic request key was already used"),
    "TOPIC_REQUEST_IN_PROGRESS": (409, "Topic request is still in progress"),
    "TOPIC_OUTCOME_UNKNOWN": (503, "Topic request outcome is unknown"),
    "TOPIC_VERSION_CONFLICT": (409, "Topic version changed; refresh and retry"),
    "TOPIC_CANDIDATE_ARCHIVED": (409, "Topic candidate is archived"),
}


class TopicFailure(PublicDomainError):
    """Fixed, non-sensitive Topic Center failure."""

    def __init__(self, code: str) -> None:
        facts = _FAILURE_FACTS.get(code)
        if facts is None:
            raise TypeError("TopicFailure requires a fixed public code")
        self.code = code
        self.status_code, self.message = facts
        super().__init__()
