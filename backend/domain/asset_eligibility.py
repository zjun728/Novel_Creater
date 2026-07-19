"""Typed, immutable eligibility metadata for approved creative assets."""

from __future__ import annotations

from enum import Enum
from hashlib import sha256
from itertools import product
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from typing import Annotated, Literal, get_args
import unicodedata

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from backend.domain.assets import AssetPackage, validate_asset_package


TaxonomyPackageVersion = Literal["recommendation-taxonomy-v1.0.0"]
TAXONOMY_PACKAGE_VERSION = get_args(TaxonomyPackageVersion)[0]
EligibilitySchemaVersion = Literal["asset-eligibility-v1"]
AssetPackageVersion = Literal["writer-core-v1.1.0"]
AssetEligibilityType = Literal["style", "experience_card"]
AssetStatus = Literal["active", "archived"]
ValidationMode = Literal["structural", "release"]

Genre = Literal[
    "general",
    "fantasy",
    "xianxia",
    "wuxia",
    "historical",
    "urban",
    "romance",
    "mystery",
    "science_fiction",
    "horror",
]
Channel = Literal["all", "male_frequency", "female_frequency"]
CreationStage = Literal[
    "contract",
    "planning",
    "chapter_outline",
    "drafting",
    "revision",
    "quality_audit",
]
WritingPurpose = Literal[
    "style_direction",
    "plot_organization",
    "ensemble",
    "dialogue",
    "emotion",
    "interiority",
    "information_release",
    "pacing",
    "suspense",
    "long_arc_continuity",
    "progression_economy",
    "character_arcs",
    "action_conflict",
]
ProhibitedDirection = Literal[
    "comedic",
    "romance_centric",
    "graphic_violence",
    "rapid_power_fantasy",
    "grim_tragedy",
    "slow_burn",
    "dense_exposition",
]

GENRES = get_args(Genre)
CHANNELS = get_args(Channel)
CREATION_STAGES = get_args(CreationStage)
WRITING_PURPOSES = get_args(WritingPurpose)
PROHIBITED_DIRECTIONS = get_args(ProhibitedDirection)

MAX_TAXONOMY_MANIFEST_BYTES = 64 * 1024
MAX_ELIGIBILITY_BYTES = 512 * 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_StableKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
]
_ManifestPath = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2_048),
]


class _EligibilityError(Enum):
    MANIFEST_IO = (
        "ASSET_ELIGIBILITY_MANIFEST_IO",
        "asset eligibility manifest could not be read",
    )
    MANIFEST_TOO_LARGE = (
        "ASSET_ELIGIBILITY_MANIFEST_TOO_LARGE",
        "asset eligibility manifest exceeds maximum size",
    )
    MANIFEST_INVALID = (
        "ASSET_ELIGIBILITY_MANIFEST_INVALID",
        "asset eligibility manifest is invalid",
    )
    DOCUMENT_IO = (
        "ASSET_ELIGIBILITY_DOCUMENT_IO",
        "asset eligibility document could not be read",
    )
    DOCUMENT_TOO_LARGE = (
        "ASSET_ELIGIBILITY_DOCUMENT_TOO_LARGE",
        "asset eligibility document exceeds maximum size",
    )
    DOCUMENT_INVALID = (
        "ASSET_ELIGIBILITY_DOCUMENT_INVALID",
        "asset eligibility document is invalid",
    )
    PATH_ESCAPE = (
        "ASSET_ELIGIBILITY_PATH_ESCAPE",
        "asset eligibility path escapes package directory",
    )
    SHA256_MISMATCH = (
        "ASSET_ELIGIBILITY_SHA256_MISMATCH",
        "asset eligibility document hash differs from manifest",
    )
    COVERAGE_MISMATCH = (
        "ASSET_ELIGIBILITY_COVERAGE_MISMATCH",
        "asset eligibility coverage differs from approved asset package",
    )
    MODE_UNSUPPORTED = (
        "ASSET_ELIGIBILITY_MODE_UNSUPPORTED",
        "asset eligibility validation mode is unsupported",
    )


class AssetEligibilityPackageError(ValueError):
    """Stable, non-sensitive taxonomy package failure."""

    def __init__(self, error: _EligibilityError) -> None:
        self.code, self.safe_message = error.value
        super().__init__(f"{self.code}: {self.safe_message}")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
        hide_input_in_errors=True,
        populate_by_name=True,
    )


class EligibilityFile(_FrozenModel):
    path: _ManifestPath
    sha256: str = Field(pattern=_SHA256_PATTERN.pattern)

    @field_validator("path")
    @classmethod
    def safe_relative_json_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        posix = PurePosixPath(normalized)
        windows = PureWindowsPath(value)
        if (
            posix.is_absolute()
            or windows.is_absolute()
            or bool(windows.drive)
            or bool(windows.root)
            or ".." in posix.parts
            or ".." in windows.parts
            or posix.suffix.casefold() != ".json"
        ):
            raise ValueError("eligibility path must be a relative JSON path")
        return normalized


class AssetEligibilityManifest(_FrozenModel):
    package_version: TaxonomyPackageVersion
    asset_package_version: AssetPackageVersion
    eligibility_file: EligibilityFile


class AssetEligibilityEntry(_FrozenModel):
    asset_type: AssetEligibilityType = Field(alias="assetType")
    stable_key: _StableKey = Field(alias="stableKey")
    asset_content_hash: str = Field(
        alias="assetContentHash",
        pattern=_SHA256_PATTERN.pattern,
    )
    genres: tuple[Genre, ...] = Field(min_length=1, max_length=len(GENRES))
    channels: tuple[Channel, ...] = Field(
        min_length=1,
        max_length=len(CHANNELS),
    )
    creation_stages: tuple[CreationStage, ...] = Field(
        alias="creationStages",
        min_length=1,
        max_length=len(CREATION_STAGES),
    )
    writing_purposes: tuple[WritingPurpose, ...] = Field(
        alias="writingPurposes",
        min_length=1,
        max_length=len(WRITING_PURPOSES),
    )
    prohibited_directions: tuple[ProhibitedDirection, ...] = Field(
        alias="prohibitedDirections",
        max_length=len(PROHIBITED_DIRECTIONS),
    )

    @field_validator(
        "genres",
        "channels",
        "creation_stages",
        "writing_purposes",
        "prohibited_directions",
        mode="before",
    )
    @classmethod
    def freeze_unique_tags(cls, value: object) -> object:
        values = tuple(value) if isinstance(value, list) else value
        if isinstance(values, tuple) and len(values) != len(set(values)):
            raise ValueError("typed eligibility tags must be unique")
        return values


class AssetEligibilityDocument(_FrozenModel):
    schema_version: EligibilitySchemaVersion = Field(alias="schemaVersion")
    entries: tuple[AssetEligibilityEntry, ...] = Field(
        min_length=1,
        max_length=1_000,
    )

    @field_validator("entries", mode="before")
    @classmethod
    def freeze_entries(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class AssetEligibilityPackage(_FrozenModel):
    manifest: AssetEligibilityManifest
    document: AssetEligibilityDocument

    @property
    def package_version(self) -> str:
        return self.manifest.package_version

    @property
    def asset_package_version(self) -> str:
        return self.manifest.asset_package_version

    @property
    def entries(self) -> tuple[AssetEligibilityEntry, ...]:
        return self.document.entries


class AssetEligibilityQuery(_FrozenModel):
    genre: Genre
    channel: Channel
    creation_stage: CreationStage
    writing_purpose: WritingPurpose
    prohibited_directions: tuple[ProhibitedDirection, ...] = Field(
        max_length=len(PROHIBITED_DIRECTIONS),
    )

    @field_validator("prohibited_directions", mode="before")
    @classmethod
    def freeze_prohibited_directions(cls, value: object) -> object:
        values = tuple(value) if isinstance(value, list) else value
        if isinstance(values, tuple) and len(values) != len(set(values)):
            raise ValueError("prohibited directions must be unique")
        return values


class AssetEligibilityScope(_FrozenModel):
    """Bounded typed dimensions explicitly supplied for recommendation."""

    genres: tuple[Genre, ...] = Field(min_length=1, max_length=len(GENRES))
    channels: tuple[Channel, ...] = Field(
        min_length=1,
        max_length=len(CHANNELS),
    )
    creation_stages: tuple[CreationStage, ...] = Field(
        alias="creationStages",
        min_length=1,
        max_length=len(CREATION_STAGES),
    )
    writing_purposes: tuple[WritingPurpose, ...] = Field(
        alias="writingPurposes",
        min_length=1,
        max_length=len(WRITING_PURPOSES),
    )
    prohibited_directions: tuple[ProhibitedDirection, ...] = Field(
        alias="prohibitedDirections",
        max_length=len(PROHIBITED_DIRECTIONS),
    )
    status: AssetStatus

    @field_validator(
        "genres",
        "channels",
        "creation_stages",
        "writing_purposes",
        "prohibited_directions",
        mode="before",
    )
    @classmethod
    def freeze_unique_dimensions(cls, value: object) -> object:
        values = tuple(value) if isinstance(value, list) else value
        if (
            isinstance(values, tuple)
            and all(isinstance(item, str) for item in values)
            and len(values) != len(set(values))
        ):
            raise ValueError("typed eligibility dimensions must be unique")
        return values


_GENRE_PROFILE_SIGNALS: tuple[tuple[Genre, tuple[str, ...]], ...] = (
    ("science_fiction", ("science_fiction", "science fiction", "sci-fi", "科幻")),
    ("xianxia", ("xianxia", "cultivation", "仙侠", "修仙", "仙道")),
    ("wuxia", ("wuxia", "武侠")),
    ("fantasy", ("xuanhuan", "fantasy", "玄幻", "奇幻", "魔法")),
    ("historical", ("historical", "history", "历史", "古代", "穿越")),
    ("urban", ("urban", "都市", "现代")),
    ("romance", ("romance", "言情", "爱情", "恋爱")),
    ("mystery", ("mystery", "悬疑", "推理")),
    ("horror", ("horror", "恐怖", "惊悚")),
)
_FEMALE_CHANNEL_SIGNALS = ("female", "女频", "晋江", "潇湘")
_MALE_CHANNEL_SIGNALS = ("male", "男频", "起点", "qidian", "qq")
_BASE_RECOMMENDATION_PURPOSES: tuple[WritingPurpose, ...] = (
    "style_direction",
    "plot_organization",
    "character_arcs",
)
_GENRE_RECOMMENDATION_PURPOSES: dict[Genre, tuple[WritingPurpose, ...]] = {
    "fantasy": ("progression_economy",),
    "xianxia": ("progression_economy",),
    "wuxia": ("progression_economy",),
    "historical": ("long_arc_continuity",),
    "science_fiction": ("long_arc_continuity",),
    "urban": ("dialogue",),
    "romance": ("emotion", "dialogue"),
    "mystery": ("suspense",),
    "horror": ("suspense",),
    "general": (),
}


def _normalized_profile_text(*values: object) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", str(value or "")).casefold()
        for value in values
    )


def canonical_recommendation_scope(
    *,
    genre_profile_key: str,
    channel_profile_key: str,
    dislikes: tuple[str, ...] = (),
) -> AssetEligibilityScope:
    """Derive the one trusted scope from persisted seed/contract facts."""

    genre_text = _normalized_profile_text(genre_profile_key)
    genre: Genre = "general"
    for candidate, signals in _GENRE_PROFILE_SIGNALS:
        if any(signal in genre_text for signal in signals):
            genre = candidate
            break

    channel_text = _normalized_profile_text(channel_profile_key)
    channel: Channel = "all"
    if any(signal in channel_text for signal in _FEMALE_CHANNEL_SIGNALS):
        channel = "female_frequency"
    elif any(signal in channel_text for signal in _MALE_CHANNEL_SIGNALS):
        channel = "male_frequency"

    purposes = (
        *_BASE_RECOMMENDATION_PURPOSES,
        *_GENRE_RECOMMENDATION_PURPOSES[genre],
    )
    prohibited = tuple(
        value
        for value in PROHIBITED_DIRECTIONS
        if value in set(dislikes)
    )
    return AssetEligibilityScope(
        genres=(genre,),
        channels=(channel,),
        creation_stages=("drafting",),
        writing_purposes=purposes,
        prohibited_directions=prohibited,
        status="active",
    )


def eligible_asset_identities(
    entries: tuple[AssetEligibilityEntry, ...],
    scope: AssetEligibilityScope,
    *,
    asset_type: AssetEligibilityType,
) -> frozenset[tuple[str, str]]:
    """Select exact taxonomy identities inside an already trusted scope."""

    return frozenset(
        (entry.stable_key, entry.asset_content_hash)
        for entry in entries
        if entry.asset_type == asset_type
        and any(
            is_asset_eligible(
                entry,
                AssetEligibilityQuery(
                    genre=genre,
                    channel=channel,
                    creation_stage=stage,
                    writing_purpose=purpose,
                    prohibited_directions=scope.prohibited_directions,
                ),
                status=scope.status,
            )
            for genre, channel, stage, purpose in product(
                scope.genres,
                scope.channels,
                scope.creation_stages,
                scope.writing_purposes,
            )
        )
    )


def _read_bounded(path: Path, *, limit: int, io_error, size_error) -> bytes:
    try:
        if path.stat().st_size > limit:
            raise AssetEligibilityPackageError(size_error)
        raw = path.read_bytes()
    except AssetEligibilityPackageError:
        raise
    except OSError:
        raise AssetEligibilityPackageError(io_error) from None
    if len(raw) > limit:
        raise AssetEligibilityPackageError(size_error)
    return raw


def _parse_json(raw: bytes, error: _EligibilityError) -> object:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise AssetEligibilityPackageError(error) from None


def _validate_coverage(
    package: AssetEligibilityPackage,
    asset_package: AssetPackage,
) -> None:
    expected = {
        ("style", asset.stable_key, asset.content_hash)
        for asset in asset_package.styles
    } | {
        ("experience_card", asset.stable_key, asset.content_hash)
        for asset in asset_package.experience_cards
    }
    actual = {
        (entry.asset_type, entry.stable_key, entry.asset_content_hash)
        for entry in package.entries
    }
    if len(actual) != len(package.entries) or actual != expected:
        raise AssetEligibilityPackageError(
            _EligibilityError.COVERAGE_MISMATCH
        )


def load_asset_eligibility_package(
    manifest_path: Path,
    *,
    asset_package: AssetPackage,
    mode: ValidationMode = "structural",
) -> AssetEligibilityPackage:
    """Load one content-addressed taxonomy and bind it to exact asset hashes."""

    if mode not in ("structural", "release"):
        raise AssetEligibilityPackageError(_EligibilityError.MODE_UNSUPPORTED)
    manifest_path = Path(manifest_path)
    manifest_raw = _read_bounded(
        manifest_path,
        limit=MAX_TAXONOMY_MANIFEST_BYTES,
        io_error=_EligibilityError.MANIFEST_IO,
        size_error=_EligibilityError.MANIFEST_TOO_LARGE,
    )
    try:
        manifest = AssetEligibilityManifest.model_validate(
            _parse_json(manifest_raw, _EligibilityError.MANIFEST_INVALID)
        )
    except ValidationError:
        raise AssetEligibilityPackageError(
            _EligibilityError.MANIFEST_INVALID
        ) from None

    root = manifest_path.parent.resolve()
    child_path = (root / manifest.eligibility_file.path).resolve()
    if root not in child_path.parents:
        raise AssetEligibilityPackageError(_EligibilityError.PATH_ESCAPE)
    child_raw = _read_bounded(
        child_path,
        limit=MAX_ELIGIBILITY_BYTES,
        io_error=_EligibilityError.DOCUMENT_IO,
        size_error=_EligibilityError.DOCUMENT_TOO_LARGE,
    )
    if sha256(child_raw).hexdigest() != manifest.eligibility_file.sha256:
        raise AssetEligibilityPackageError(
            _EligibilityError.SHA256_MISMATCH
        )
    try:
        document = AssetEligibilityDocument.model_validate(
            _parse_json(child_raw, _EligibilityError.DOCUMENT_INVALID)
        )
    except ValidationError:
        raise AssetEligibilityPackageError(
            _EligibilityError.DOCUMENT_INVALID
        ) from None

    try:
        asset_package = validate_asset_package(
            asset_package,
            mode="release" if mode == "release" else "structural",
        )
    except Exception:
        raise AssetEligibilityPackageError(
            _EligibilityError.COVERAGE_MISMATCH
        ) from None
    if manifest.asset_package_version != asset_package.package_version:
        raise AssetEligibilityPackageError(
            _EligibilityError.COVERAGE_MISMATCH
        )
    package = AssetEligibilityPackage(
        manifest=manifest,
        document=document,
    )
    _validate_coverage(package, asset_package)
    return package


def _typed_match(value: str, allowed: tuple[str, ...], wildcard: str) -> bool:
    return wildcard in allowed or value in allowed


def is_asset_eligible(
    entry: AssetEligibilityEntry,
    query: AssetEligibilityQuery,
    *,
    status: AssetStatus,
) -> bool:
    """Apply eligibility solely to typed tags and the stored revision status."""

    if status != "active":
        return False
    if not _typed_match(query.genre, entry.genres, "general"):
        return False
    if not _typed_match(query.channel, entry.channels, "all"):
        return False
    if query.creation_stage not in entry.creation_stages:
        return False
    if query.writing_purpose not in entry.writing_purposes:
        return False
    return not (
        set(query.prohibited_directions) & set(entry.prohibited_directions)
    )


__all__ = (
    "AssetEligibilityEntry",
    "AssetEligibilityPackage",
    "AssetEligibilityPackageError",
    "AssetEligibilityQuery",
    "AssetEligibilityScope",
    "CHANNELS",
    "CREATION_STAGES",
    "GENRES",
    "PROHIBITED_DIRECTIONS",
    "TAXONOMY_PACKAGE_VERSION",
    "WRITING_PURPOSES",
    "canonical_recommendation_scope",
    "eligible_asset_identities",
    "is_asset_eligible",
    "load_asset_eligibility_package",
)
