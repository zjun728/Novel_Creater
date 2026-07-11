"""Strict, immutable creation and style JSON contracts."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.domain.seeds import SeedPayload
from backend.domain.story_engines import StoryEngineOption


CONTRACT_TEXT_MAX_LENGTH = 2_000
PositiveInt = Annotated[int, Field(gt=0)]
ContractText = Annotated[
    str,
    Field(min_length=1, max_length=CONTRACT_TEXT_MAX_LENGTH),
]


class CreationContractPayload(BaseModel):
    """The exact canonical CreationContract ``content_json`` payload."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    schemaVersion: ContractText
    channelProfileKey: ContractText
    genreProfileKey: ContractText
    qualityCharterVersion: ContractText
    selectedSeed: SeedPayload
    selectedEngine: StoryEngineOption
    totalWordRange: tuple[PositiveInt, PositiveInt]
    chapterCapacityPolicy: ContractText
    modelBindingRevision: PositiveInt

    @model_validator(mode="after")
    def validate_total_word_range(self) -> Self:
        if self.totalWordRange[0] > self.totalWordRange[1]:
            raise ValueError("totalWordRange minimum must not exceed maximum")
        return self


class StyleContractPayload(BaseModel):
    """The exact canonical StyleContract ``merged_style_json`` payload."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    schemaVersion: ContractText
    readingExperience: ContractText
    narrativeDistance: ContractText
    sentenceParagraphRhythm: ContractText
    dictionDensity: ContractText
    dialogueAndSubtext: ContractText
    characterVoices: tuple[ContractText, ...] = Field(min_length=1)
    emotionAndInteriority: ContractText
    actionExplanationEnvironment: ContractText
    primaryRules: tuple[ContractText, ...] = Field(min_length=1)
    secondaryFlavor: ContractText | None = None
    risks: tuple[ContractText, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_secondary_flavor(self) -> Self:
        if self.secondaryFlavor is not None and self.secondaryFlavor in {
            self.readingExperience,
            *self.primaryRules,
        }:
            raise ValueError("secondaryFlavor must be different from the primary style")
        return self
