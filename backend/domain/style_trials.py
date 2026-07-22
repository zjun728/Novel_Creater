"""Strict, temporary style-trial contracts and safe public failures."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.http_errors import PublicDomainError
from backend.security.provider_secrets import normalize_provider_secrets


STYLE_TRIAL_MAX_SCENARIO_LENGTH = 2_000
STYLE_TRIAL_MAX_SAMPLE_LENGTH = 6_000
STYLE_TRIAL_MAX_IDENTIFIER_LENGTH = 36
STYLE_TRIAL_HASH_PATTERN = r"^[0-9a-f]{64}$"
STYLE_TRIAL_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
STYLE_TRIAL_IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9_-]{64}$"
_STRICT = ConfigDict(
    strict=True,
    frozen=True,
    extra="forbid",
    str_strip_whitespace=True,
    hide_input_in_errors=True,
)

_FAILURES = {
    "STYLE_TRIAL_NOT_FOUND": (404, "Style trial project was not found"),
    "STYLE_TRIAL_NOT_READY": (422, "Style trial prerequisites are unavailable"),
    "STYLE_TRIAL_INPUT_CHANGED": (409, "Style trial inputs changed; refresh and retry"),
    "STYLE_TRIAL_IDEMPOTENCY_CONFLICT": (
        409,
        "Style trial request key was already used for different inputs",
    ),
    "STYLE_TRIAL_IN_PROGRESS": (409, "Style trial request is still in progress"),
}


def style_trial_value_contains_secret(
    value: object,
    secrets: Iterable[object],
) -> bool:
    """Find every direct nonempty Provider-secret substring in nested values."""

    normalized = normalize_provider_secrets(secrets)
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if any(secret in item for secret in normalized):
                return True
        elif isinstance(item, Mapping):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (list, tuple, set)):
            pending.extend(item)
    return False


class StyleTrialFailure(PublicDomainError):
    """A fixed, non-sensitive failure at the HTTP boundary."""

    def __init__(self, code: str) -> None:
        if code not in _FAILURES:
            raise TypeError("StyleTrialFailure requires a fixed public code")
        self.code = code
        self.status_code, self.message = _FAILURES[code]
        super().__init__()


class _FrozenModel(BaseModel):
    model_config = _STRICT


class StyleTrialProviderOutput(_FrozenModel):
    """The only Provider output allowed to cross the gateway."""

    sample: str = Field(min_length=1, max_length=STYLE_TRIAL_MAX_SAMPLE_LENGTH)


class SafeProviderIdentity(_FrozenModel):
    """Actual public Provider identity, without connection configuration."""

    provider_id: str = Field(
        min_length=1,
        max_length=STYLE_TRIAL_MAX_IDENTIFIER_LENGTH,
        pattern=STYLE_TRIAL_IDENTIFIER_PATTERN,
    )
    provider_type: str = Field(min_length=1, max_length=64)
    model_name: str = Field(min_length=1, max_length=160)
    profile_revision: int = Field(ge=0)


class GenerateStyleTrial(_FrozenModel):
    project_id: str = Field(
        min_length=1,
        max_length=STYLE_TRIAL_MAX_IDENTIFIER_LENGTH,
        pattern=STYLE_TRIAL_IDENTIFIER_PATTERN,
    )
    selection_revision: int = Field(gt=0)
    engine_option_id: str = Field(
        min_length=1,
        max_length=STYLE_TRIAL_MAX_IDENTIFIER_LENGTH,
        pattern=STYLE_TRIAL_IDENTIFIER_PATTERN,
    )
    engine_hash: str = Field(pattern=STYLE_TRIAL_HASH_PATTERN)
    primary_style_revision_id: str = Field(
        min_length=1,
        max_length=STYLE_TRIAL_MAX_IDENTIFIER_LENGTH,
        pattern=STYLE_TRIAL_IDENTIFIER_PATTERN,
    )
    primary_style_hash: str = Field(pattern=STYLE_TRIAL_HASH_PATTERN)
    secondary_style_revision_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=STYLE_TRIAL_MAX_IDENTIFIER_LENGTH,
        pattern=STYLE_TRIAL_IDENTIFIER_PATTERN,
    )
    secondary_style_hash: str | None = Field(
        default=None, pattern=STYLE_TRIAL_HASH_PATTERN
    )
    author_scenario: str = Field(
        min_length=1, max_length=STYLE_TRIAL_MAX_SCENARIO_LENGTH
    )
    idempotency_key: str = Field(
        min_length=64,
        max_length=64,
        pattern=STYLE_TRIAL_IDEMPOTENCY_PATTERN,
    )

    @model_validator(mode="after")
    def validate_style_pair(self) -> Self:
        if (self.secondary_style_revision_id is None) != (
            self.secondary_style_hash is None
        ):
            raise ValueError("secondary style identity must be complete")
        if self.secondary_style_revision_id == self.primary_style_revision_id:
            raise ValueError("primary and secondary styles must be different")
        return self


class StyleTrialResult(_FrozenModel):
    """One temporary attempt result; never a selection or Canon mutation."""

    attempt_id: str = Field(
        min_length=1,
        max_length=STYLE_TRIAL_MAX_IDENTIFIER_LENGTH,
        pattern=STYLE_TRIAL_IDENTIFIER_PATTERN,
    )
    status: Literal["succeeded", "failed", "outcome_unknown"]
    sample: str | None = Field(default=None, max_length=STYLE_TRIAL_MAX_SAMPLE_LENGTH)
    result_hash: str | None = Field(default=None, pattern=STYLE_TRIAL_HASH_PATTERN)
    public_error_code: str | None = Field(default=None, min_length=1, max_length=64)
    provider: SafeProviderIdentity
    created_at: int = Field(ge=0)
    completed_at: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> Self:
        if self.status == "succeeded":
            if self.sample is None or self.result_hash is None:
                raise ValueError("successful style trial requires a sample and hash")
            if self.public_error_code is not None:
                raise ValueError("successful style trial cannot contain an error")
        elif (
            self.sample is not None
            or self.result_hash is not None
            or self.public_error_code is None
        ):
            raise ValueError("failed style trial must contain only a public error")
        return self


__all__ = (
    "GenerateStyleTrial",
    "SafeProviderIdentity",
    "STYLE_TRIAL_HASH_PATTERN",
    "STYLE_TRIAL_IDEMPOTENCY_PATTERN",
    "STYLE_TRIAL_IDENTIFIER_PATTERN",
    "STYLE_TRIAL_MAX_IDENTIFIER_LENGTH",
    "STYLE_TRIAL_MAX_SAMPLE_LENGTH",
    "STYLE_TRIAL_MAX_SCENARIO_LENGTH",
    "StyleTrialFailure",
    "StyleTrialProviderOutput",
    "StyleTrialResult",
    "style_trial_value_contains_secret",
)
