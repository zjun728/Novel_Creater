"""Strict, immutable story-engine domain contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


STORY_ENGINE_TEXT_MAX_LENGTH = 2_000
CONTRACT_COLLECTION_MAX_ITEMS = 20
SELECTION_SUPERSEDED_CODE = "selection_superseded"
_SELECTION_GENERATION_FIELDS = (
    "selection_revision",
    "seed_id",
    "seed_revision_id",
    "seed_hash",
)
StoryEngineText = Annotated[
    str,
    Field(min_length=1, max_length=STORY_ENGINE_TEXT_MAX_LENGTH),
]


class EnsembleRole(BaseModel):
    """One role in the story engine's supporting ensemble."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    role: StoryEngineText
    purpose: StoryEngineText


class StoryEngineOption(BaseModel):
    """The exact canonical payload for one story-engine option."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    name: StoryEngineText
    storyPromise: StoryEngineText
    protagonistDesire: StoryEngineText
    sustainedPressure: StoryEngineText
    growthDirection: StoryEngineText
    conflictLoop: StoryEngineText
    ensembleRoles: tuple[EnsembleRole, ...] = Field(
        min_length=1,
        max_length=CONTRACT_COLLECTION_MAX_ITEMS,
    )
    advantageAndCost: StoryEngineText
    satisfactionSources: tuple[StoryEngineText, ...] = Field(
        min_length=1,
        max_length=CONTRACT_COLLECTION_MAX_ITEMS,
    )
    longFormVariation: tuple[StoryEngineText, ...] = Field(
        min_length=1,
        max_length=CONTRACT_COLLECTION_MAX_ITEMS,
    )
    endingAnchor: StoryEngineText
    risks: tuple[StoryEngineText, ...] = Field(
        min_length=1,
        max_length=CONTRACT_COLLECTION_MAX_ITEMS,
    )
    differentiation: StoryEngineText


def selection_generation_matches(
    frozen: Mapping[str, object],
    current: Mapping[str, object] | None,
) -> bool:
    """Match the complete seed-selection generation, not seed identity alone."""

    if current is None:
        return False
    try:
        for generation in (frozen, current):
            revision = generation["selection_revision"]
            if type(revision) is not int or revision <= 0:
                return False
            if any(
                not isinstance(generation[field], str)
                or not generation[field].strip()
                for field in _SELECTION_GENERATION_FIELDS[1:]
            ):
                return False
        return all(
            frozen[field] == current[field]
            for field in _SELECTION_GENERATION_FIELDS
        )
    except (KeyError, TypeError):
        return False


def validate_three_options(
    options: tuple[StoryEngineOption, ...],
) -> tuple[StoryEngineOption, ...]:
    """Require exactly three options with distinct structural signatures."""

    if not isinstance(options, tuple):
        raise TypeError("options must be an immutable tuple")
    if len(options) != 3:
        raise ValueError("options must contain exactly three items")
    if not all(isinstance(option, StoryEngineOption) for option in options):
        raise TypeError("every option must be a StoryEngineOption")

    signatures = {
        (
            option.storyPromise,
            option.conflictLoop,
            option.advantageAndCost,
            option.endingAnchor,
        )
        for option in options
    }
    if len(signatures) != 3:
        raise ValueError("options must be structurally distinct")
    return options
