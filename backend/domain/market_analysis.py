"""Strict frozen market-analysis values and public failures."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from backend.http_errors import PublicDomainError


MARKET_ANALYSIS_POLICY_VERSION = "market-analysis-policy-v1"
MAX_ANALYSIS_SNAPSHOTS = 4
MAX_ANALYSIS_STATEMENTS = 12

_MESSAGES = {
    "MARKET_ANALYSIS_NOT_READY": "Market analysis prerequisites are unavailable",
    "MARKET_ANALYSIS_NOT_FOUND": "Market analysis or project was not found",
    "MARKET_ANALYSIS_IDEMPOTENCY_CONFLICT": (
        "Market analysis key was already used for a different request"
    ),
    "MARKET_ANALYSIS_INVALID_REQUEST": "Market analysis request is invalid",
}
_STATUS = {
    "MARKET_ANALYSIS_NOT_READY": 422,
    "MARKET_ANALYSIS_NOT_FOUND": 404,
    "MARKET_ANALYSIS_IDEMPOTENCY_CONFLICT": 409,
    "MARKET_ANALYSIS_INVALID_REQUEST": 422,
}


class MarketAnalysisFailure(PublicDomainError):
    def __init__(self, code: str) -> None:
        if code not in _MESSAGES:
            raise TypeError("MarketAnalysisFailure requires a fixed public code")
        self.code = code
        self.message = _MESSAGES[code]
        self.status_code = _STATUS[code]
        super().__init__()


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )


class AnalysisStatement(_FrozenModel):
    text: str = Field(min_length=1, max_length=600)
    snapshot_ids: tuple[str, ...] = Field(
        alias="snapshotIds",
        min_length=1,
        max_length=MAX_ANALYSIS_SNAPSHOTS,
    )
    inference: bool

    @field_validator("snapshot_ids", mode="before")
    @classmethod
    def freeze_ids(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        if len(self.snapshot_ids) != len(set(self.snapshot_ids)):
            raise ValueError("statement snapshot IDs must be unique")
        return self


class SourceCoverage(_FrozenModel):
    snapshot_ids: tuple[str, ...] = Field(
        alias="snapshotIds",
        min_length=1,
        max_length=MAX_ANALYSIS_SNAPSHOTS,
    )
    summary: str = Field(min_length=1, max_length=600)

    @field_validator("snapshot_ids", mode="before")
    @classmethod
    def freeze_ids(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class MarketAnalysis(_FrozenModel):
    current_heat: tuple[AnalysisStatement, ...] = Field(
        alias="currentHeat",
        max_length=MAX_ANALYSIS_STATEMENTS,
    )
    growth_directions: tuple[AnalysisStatement, ...] = Field(
        alias="growthDirections",
        max_length=MAX_ANALYSIS_STATEMENTS,
    )
    crowding: tuple[AnalysisStatement, ...] = Field(
        max_length=MAX_ANALYSIS_STATEMENTS,
    )
    opportunities: tuple[AnalysisStatement, ...] = Field(
        max_length=MAX_ANALYSIS_STATEMENTS,
    )
    uncertainties: tuple[AnalysisStatement, ...] = Field(
        max_length=MAX_ANALYSIS_STATEMENTS,
    )
    source_coverage: SourceCoverage = Field(alias="sourceCoverage")

    @field_validator(
        "current_heat",
        "growth_directions",
        "crowding",
        "opportunities",
        "uncertainties",
        mode="before",
    )
    @classmethod
    def freeze_statements(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


def parse_market_analysis(
    value: object,
    *,
    snapshot_ids: tuple[str, ...],
) -> MarketAnalysis:
    """Validate one response against the exact ordered frozen manifest."""

    try:
        analysis = MarketAnalysis.model_validate(value, strict=True)
        allowed = set(snapshot_ids)
        statements = (
            analysis.current_heat
            + analysis.growth_directions
            + analysis.crowding
            + analysis.opportunities
            + analysis.uncertainties
        )
        if any(
            not statement.snapshot_ids
            or not set(statement.snapshot_ids).issubset(allowed)
            for statement in statements
        ):
            raise ValueError("citation outside frozen manifest")
        if any(not item.inference for item in analysis.growth_directions):
            raise ValueError("growth directions must be inference")
        if any(not item.inference for item in analysis.opportunities):
            raise ValueError("opportunities must be inference")
        if analysis.source_coverage.snapshot_ids != snapshot_ids:
            raise ValueError("source coverage must match frozen order")
    except (ValidationError, TypeError, ValueError, RecursionError):
        raise ValueError("invalid market analysis") from None
    return analysis
