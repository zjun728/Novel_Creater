"""Strict future-design payload for immutable creation-Bible revisions."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.domain.json_contracts import canonical_hash


BIBLE_TEXT_MAX_LENGTH = 4_000
BIBLE_LIST_MAX_ITEMS = 20
BibleText = Annotated[
    str,
    Field(min_length=1, max_length=BIBLE_TEXT_MAX_LENGTH),
]
BibleItemId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    ),
]


class _StrictBibleValue(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class BibleDesignItem(_StrictBibleValue):
    """One stable item in a future-design collection."""

    id: BibleItemId
    text: BibleText


BibleDesignList = Annotated[
    tuple[BibleDesignItem, ...],
    Field(min_length=1, max_length=BIBLE_LIST_MAX_ITEMS),
]


class BiblePayload(_StrictBibleValue):
    """The closed canonical payload; it intentionally has no Canon/event fields."""

    premiseAndPromise: BibleText
    worldRules: BibleDesignList
    powerOrProgressionSystem: BibleText
    protagonist: BibleText
    coreCast: BibleDesignList
    factions: BibleDesignList
    longTermConflicts: BibleDesignList
    relationshipDynamics: BibleDesignList
    toneAndNarrativeBoundaries: BibleText
    continuityGuardrails: BibleDesignList
    openDesignQuestions: BibleDesignList

    @model_validator(mode="after")
    def validate_stable_item_ids(self) -> Self:
        for field_name in (
            "worldRules",
            "coreCast",
            "factions",
            "longTermConflicts",
            "relationshipDynamics",
            "continuityGuardrails",
            "openDesignQuestions",
        ):
            values = getattr(self, field_name)
            if len({item.id for item in values}) != len(values):
                raise ValueError(
                    f"{field_name} must not contain duplicate stable item ids"
                )
        return self


def canonical_bible_hash(payload: BiblePayload) -> str:
    """Hash only an already validated canonical Bible payload."""

    if not isinstance(payload, BiblePayload):
        raise TypeError("payload must be a validated BiblePayload")
    return canonical_hash(payload)


__all__ = (
    "BIBLE_LIST_MAX_ITEMS",
    "BIBLE_TEXT_MAX_LENGTH",
    "BibleDesignItem",
    "BiblePayload",
    "canonical_bible_hash",
)
