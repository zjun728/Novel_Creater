"""Typed eligibility and strict model-ranking contracts for creative assets."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from backend.domain.asset_eligibility import (
    AssetEligibilityEntry,
    AssetStatus,
    CreationStage,
    Genre,
    ProhibitedDirection,
)


RECOMMENDATION_VERSION = "asset-recommendation-v2"
MAX_ASSET_CANDIDATES = 100
MAX_ASSET_SUMMARY_CHARS = 600
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class RecommendationInputError(ValueError):
    """A fixed, non-sensitive failure at the recommendation boundary."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )


class AssetRecommendationScope(_FrozenModel):
    """Only typed Phase 2A dimensions may exclude an asset candidate."""

    genre: Genre
    creation_stage: CreationStage
    status: AssetStatus
    prohibited_directions: tuple[ProhibitedDirection, ...] = Field(
        default=(),
        max_length=7,
    )

    @field_validator("prohibited_directions", mode="before")
    @classmethod
    def freeze_prohibited_directions(cls, value):
        return tuple(value) if isinstance(value, list) else value

    @field_validator("prohibited_directions")
    @classmethod
    def unique_prohibited_directions(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("prohibited directions must be unique")
        return value


class AssetCandidateSummary(_FrozenModel):
    """One bounded current revision summary safe to send to the ranker."""

    asset_revision_id: str = Field(min_length=1, max_length=36)
    asset_type: Literal["style", "experience_card"]
    stable_key: str = Field(min_length=1, max_length=160)
    revision: int = Field(gt=0)
    content_hash: str = Field(pattern=_HASH_PATTERN.pattern)
    status: AssetStatus
    label: str = Field(min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=32)
    facts: str = Field(min_length=1, max_length=MAX_ASSET_SUMMARY_CHARS)


class StyleRevisionRef(_FrozenModel):
    id: str = Field(min_length=1, max_length=36)
    revision: int = Field(gt=0)
    content_hash: str = Field(alias="contentHash", pattern=_HASH_PATTERN.pattern)


class SelectedStyleCandidate(AssetCandidateSummary):
    role: Literal["primary", "secondary"]

    @model_validator(mode="after")
    def require_style_candidate(self):
        if self.asset_type != "style":
            raise ValueError("selected style candidate must be a style")
        return self


class ProviderAssetRecommendation(_FrozenModel):
    asset_revision_id: str = Field(
        alias="assetRevisionId",
        min_length=1,
        max_length=36,
    )
    reason: str = Field(min_length=1, max_length=160)
    confidence: float = Field(ge=0, le=1)


class ProviderCorpusRecommendation(_FrozenModel):
    fragment_id: str = Field(alias="fragmentId", min_length=1, max_length=36)
    range_start: int = Field(alias="rangeStart", ge=0)
    range_end: int = Field(alias="rangeEnd", gt=0)
    use: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=160)
    confidence: float = Field(ge=0, le=1)


class ProviderRankingOutput(_FrozenModel):
    asset_recommendations: tuple[ProviderAssetRecommendation, ...] = Field(
        alias="assetRecommendations",
        max_length=MAX_ASSET_CANDIDATES,
    )
    corpus_recommendations: tuple[ProviderCorpusRecommendation, ...] = Field(
        alias="corpusRecommendations",
        max_length=20,
    )

    @field_validator(
        "asset_recommendations",
        "corpus_recommendations",
        mode="before",
    )
    @classmethod
    def freeze_json_arrays(cls, value):
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def unique_recommendations(self):
        asset_ids = tuple(
            item.asset_revision_id for item in self.asset_recommendations
        )
        fragment_ids = tuple(
            item.fragment_id for item in self.corpus_recommendations
        )
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("asset recommendation IDs must be unique")
        if len(fragment_ids) != len(set(fragment_ids)):
            raise ValueError("corpus recommendation IDs must be unique")
        return self


def filter_eligible_candidates(
    candidates: tuple[AssetCandidateSummary, ...],
    *,
    taxonomy_entries: tuple[AssetEligibilityEntry, ...],
    taxonomy_version: str,
    taxonomy_hash: str,
    expected_taxonomy_version: str,
    expected_taxonomy_hash: str,
    scope: AssetRecommendationScope,
) -> tuple[AssetCandidateSummary, ...]:
    """Filter solely by exact taxonomy identity and four typed dimensions."""

    if (
        taxonomy_version != expected_taxonomy_version
        or taxonomy_hash != expected_taxonomy_hash
        or not _HASH_PATTERN.fullmatch(taxonomy_hash)
    ):
        raise RecommendationInputError("asset recommendation taxonomy is invalid")
    if not isinstance(candidates, tuple) or len(candidates) > MAX_ASSET_CANDIDATES:
        raise RecommendationInputError("asset candidate inventory is invalid")
    index = {
        (entry.asset_type, entry.stable_key, entry.asset_content_hash): entry
        for entry in taxonomy_entries
    }
    if len(index) != len(taxonomy_entries):
        raise RecommendationInputError("asset recommendation taxonomy is invalid")
    prohibited = set(scope.prohibited_directions)
    return tuple(
        candidate
        for candidate in candidates
        if (
            candidate.status == scope.status == "active"
            and (
                entry := index.get(
                    (
                        candidate.asset_type,
                        candidate.stable_key,
                        candidate.content_hash,
                    )
                )
            )
            is not None
            and (
                scope.genre in entry.genres
                or "general" in entry.genres
            )
            and scope.creation_stage in entry.creation_stages
            and not prohibited.intersection(entry.prohibited_directions)
        )
    )


__all__ = (
    "AssetCandidateSummary",
    "AssetRecommendationScope",
    "MAX_ASSET_CANDIDATES",
    "MAX_ASSET_SUMMARY_CHARS",
    "ProviderAssetRecommendation",
    "ProviderCorpusRecommendation",
    "ProviderRankingOutput",
    "RECOMMENDATION_VERSION",
    "RecommendationInputError",
    "SelectedStyleCandidate",
    "StyleRevisionRef",
    "filter_eligible_candidates",
)
