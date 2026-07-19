"""Immutable creative-seed domain values."""

from pydantic import BaseModel, ConfigDict, Field


SEED_FIELD_MAX_LENGTH = 2_000


class SeedPayload(BaseModel):
    """The exact nine-field creative seed contract."""

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
