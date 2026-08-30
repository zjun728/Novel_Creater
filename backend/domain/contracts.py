"""Strict, immutable creation and style JSON contracts."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.domain.seeds import SeedPayload, decode_seed_revision
from backend.domain.json_contracts import canonical_hash
from backend.domain.story_engines import (
    CONTRACT_COLLECTION_MAX_ITEMS,
    StoryEngineOption,
)


CONTRACT_TEXT_MAX_LENGTH = 2_000
STYLE_CONTRACT_TEXT_MAX_LENGTH = 20_000
MAX_TARGET_TOTAL_WORDS = 100_000_000
MAX_EXPECTED_VOLUME_COUNT = 1_000
MAX_EXPECTED_CHAPTER_COUNT = 100_000
MAX_CHAPTER_WORD_RANGE_VALUE = 100_000
PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
TargetTotalWords = Annotated[
    int, Field(strict=True, gt=0, le=MAX_TARGET_TOTAL_WORDS)
]
ExpectedVolumeCount = Annotated[
    int, Field(strict=True, gt=0, le=MAX_EXPECTED_VOLUME_COUNT)
]
ExpectedChapterCount = Annotated[
    int, Field(strict=True, gt=0, le=MAX_EXPECTED_CHAPTER_COUNT)
]
ChapterWordRangeValue = Annotated[
    int, Field(strict=True, gt=0, le=MAX_CHAPTER_WORD_RANGE_VALUE)
]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[
    str,
    Field(min_length=1, max_length=36, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"),
]
ContractText = Annotated[
    str,
    Field(min_length=1, max_length=CONTRACT_TEXT_MAX_LENGTH),
]
ProfileOrVersionKey = Annotated[str, Field(min_length=1, max_length=120)]
StyleContractText = Annotated[
    str,
    Field(min_length=1, max_length=STYLE_CONTRACT_TEXT_MAX_LENGTH),
]


class _FrozenContractValue(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class FrozenAssetRef(_FrozenContractValue):
    id: Identifier
    revision: PositiveInt
    contentHash: Hash


class FrozenBindingRef(FrozenAssetRef):
    pass


class FrozenCorpusFragment(_FrozenContractValue):
    chapterId: Identifier
    fragmentId: Identifier
    fragmentHash: Hash
    chapterCharStart: NonNegativeInt
    chapterCharEnd: PositiveInt
    referenceUse: Literal["inspiration", "structure", "style", "fact_check"]

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.chapterCharEnd <= self.chapterCharStart:
            raise ValueError("corpus fragment range must be positive")
        return self


class FrozenCorpusSourceRef(_FrozenContractValue):
    id: Identifier
    revisionId: Identifier
    revision: PositiveInt
    contentHash: Hash
    selectionMode: Literal["author", "system"]
    fragments: tuple[FrozenCorpusFragment, ...] = Field(
        min_length=1,
        max_length=CONTRACT_COLLECTION_MAX_ITEMS,
    )
    pinnedHistoricalRevision: bool

    @model_validator(mode="after")
    def validate_fragments(self) -> Self:
        orders = tuple(
            (
                fragment.fragmentId,
                fragment.chapterCharStart,
                fragment.chapterCharEnd,
            )
            for fragment in self.fragments
        )
        if len(set(orders)) != len(orders):
            raise ValueError("corpus fragment ranges must be unique")
        return self


class CreationContractPayload(BaseModel):
    """The exact canonical CreationContract ``content_json`` payload."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    schemaVersion: ContractText
    channelProfileKey: ProfileOrVersionKey
    genreProfileKey: ProfileOrVersionKey
    qualityCharterVersion: ProfileOrVersionKey
    selectionRevision: PositiveInt
    selectedSeed: SeedPayload
    seedRevisionId: Identifier
    seedHash: Hash
    selectedEngine: StoryEngineOption
    engineOptionId: Identifier
    engineHash: Hash
    primaryStyleRef: FrozenAssetRef
    secondaryStyleRef: FrozenAssetRef | None = None
    experienceCardRefs: tuple[FrozenAssetRef, ...] = Field(
        max_length=CONTRACT_COLLECTION_MAX_ITEMS,
    )
    corpusSourceRefs: tuple[FrozenCorpusSourceRef, ...] = Field(
        max_length=CONTRACT_COLLECTION_MAX_ITEMS,
    )
    targetTotalWords: TargetTotalWords
    expectedVolumeCount: ExpectedVolumeCount
    expectedChapterCount: ExpectedChapterCount
    chapterWordRangePreference: tuple[
        ChapterWordRangeValue, ChapterWordRangeValue
    ]
    prohibitedDirections: tuple[ContractText, ...] = Field(
        max_length=CONTRACT_COLLECTION_MAX_ITEMS,
    )
    authorNotes: ContractText | None = None
    modelBindingRef: FrozenBindingRef | None = None

    @field_validator("selectedSeed", mode="before")
    @classmethod
    def preserve_selected_seed_revision_shape(cls, value: object) -> object:
        if isinstance(value, SeedPayload):
            return value
        payload, provenance = decode_seed_revision(value)
        if provenance is not None:
            raise ValueError("selectedSeed cannot contain provenance")
        return payload

    @model_validator(mode="after")
    def validate_complete_contract(self) -> Self:
        if self.chapterWordRangePreference[0] > self.chapterWordRangePreference[1]:
            raise ValueError(
                "chapterWordRangePreference minimum must not exceed maximum"
            )
        if canonical_hash(self.selectedSeed) != self.seedHash:
            raise ValueError("seedHash must match selectedSeed")
        if canonical_hash(self.selectedEngine) != self.engineHash:
            raise ValueError("engineHash must match selectedEngine")
        if (
            self.secondaryStyleRef is not None
            and self.secondaryStyleRef.id == self.primaryStyleRef.id
        ):
            raise ValueError("primary and secondary styles must be different")
        if len({ref.id for ref in self.experienceCardRefs}) != len(
            self.experienceCardRefs
        ):
            raise ValueError("experienceCardRefs must not contain duplicates")
        if len({ref.id for ref in self.corpusSourceRefs}) != len(
            self.corpusSourceRefs
        ):
            raise ValueError("corpusSourceRefs must not contain duplicates")
        return self


class StyleContractPayload(BaseModel):
    """The exact canonical StyleContract ``merged_style_json`` payload."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    schemaVersion: StyleContractText
    readingExperience: StyleContractText
    narrativeDistance: StyleContractText
    sentenceParagraphRhythm: StyleContractText
    dictionDensity: StyleContractText
    dialogueAndSubtext: StyleContractText
    characterVoices: tuple[StyleContractText, ...] = Field(
        min_length=1,
        max_length=CONTRACT_COLLECTION_MAX_ITEMS,
    )
    emotionAndInteriority: StyleContractText
    actionExplanationEnvironment: StyleContractText
    primaryRules: tuple[StyleContractText, ...] = Field(
        min_length=1,
        max_length=CONTRACT_COLLECTION_MAX_ITEMS,
    )
    secondaryFlavor: StyleContractText | None = None
    risks: tuple[StyleContractText, ...] = Field(
        min_length=1,
        max_length=CONTRACT_COLLECTION_MAX_ITEMS,
    )

    @model_validator(mode="after")
    def validate_secondary_flavor(self) -> Self:
        if self.secondaryFlavor is not None and self.secondaryFlavor in {
            self.readingExperience,
            *self.primaryRules,
        }:
            raise ValueError("secondaryFlavor must be different from the primary style")
        return self
