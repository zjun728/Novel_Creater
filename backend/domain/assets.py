"""Strict immutable models and validation for Writer Core asset packages."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from types import MappingProxyType
from typing import Annotated, Literal, Self, get_args
import unicodedata

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from backend.domain.json_contracts import canonical_hash


PackageVersion = Literal["writer-core-v1.1.0"]
PACKAGE_VERSION = get_args(PackageVersion)[0]
MAX_ASSET_MANIFEST_BYTES = 64 * 1024
MAX_ASSET_CHILD_BYTES = 4 * 1024 * 1024

AssetCategory = Literal[
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
ASSET_CATEGORIES = get_args(AssetCategory)
ASSET_CATEGORY_COUNTS = MappingProxyType(
    {
        "plot_organization": 6,
        "ensemble": 6,
        "dialogue": 6,
        "emotion": 6,
        "interiority": 6,
        "information_release": 6,
        "pacing": 6,
        "suspense": 6,
        "long_arc_continuity": 4,
        "progression_economy": 4,
        "character_arcs": 4,
        "action_conflict": 4,
    }
)
ReviewDecision = Literal["approved", "candidate", "rewrite", "rejected"]
ValidationMode = Literal["structural", "release"]

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

SchemaVersion = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]
StableKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
]
AssetName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
PromptText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000),
]
ExampleText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000),
]
ListItem = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000),
]
ReviewerName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
ReviewTime = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]
ManifestPath = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2_048),
]


class _AssetError(Enum):
    PACKAGE_INVALID = ("ASSET_PACKAGE_INVALID", "asset package is invalid")
    MANIFEST_INVALID = ("ASSET_MANIFEST_INVALID", "asset manifest is invalid")
    VALIDATION_MODE_UNSUPPORTED = (
        "ASSET_VALIDATION_MODE_UNSUPPORTED",
        "asset package validation mode is unsupported",
    )
    MANIFEST_IO = ("ASSET_MANIFEST_IO", "asset manifest could not be read")
    MANIFEST_JSON_INVALID = (
        "ASSET_MANIFEST_JSON_INVALID",
        "asset manifest JSON is invalid",
    )
    MANIFEST_TOO_LARGE = (
        "ASSET_MANIFEST_TOO_LARGE",
        "asset manifest exceeds maximum size",
    )
    STYLES_IO = ("ASSET_STYLES_IO", "styles asset file could not be read")
    STYLES_JSON_INVALID = (
        "ASSET_STYLES_JSON_INVALID",
        "styles asset JSON is invalid",
    )
    STYLES_TOO_LARGE = (
        "ASSET_STYLES_TOO_LARGE",
        "styles asset file exceeds maximum size",
    )
    STYLES_PATH_ESCAPE = (
        "ASSET_STYLES_PATH_ESCAPE",
        "styles asset path escapes package directory",
    )
    STYLES_SHA256_MISMATCH = (
        "ASSET_STYLES_SHA256_MISMATCH",
        "styles_file sha256 mismatch",
    )
    STYLES_NOT_ARRAY = (
        "ASSET_STYLES_NOT_ARRAY",
        "styles_file must contain a JSON array",
    )
    CARDS_IO = (
        "ASSET_CARDS_IO",
        "experience cards asset file could not be read",
    )
    CARDS_JSON_INVALID = (
        "ASSET_CARDS_JSON_INVALID",
        "experience cards asset JSON is invalid",
    )
    CARDS_TOO_LARGE = (
        "ASSET_CARDS_TOO_LARGE",
        "experience cards asset file exceeds maximum size",
    )
    CARDS_PATH_ESCAPE = (
        "ASSET_CARDS_PATH_ESCAPE",
        "experience cards asset path escapes package directory",
    )
    CARDS_SHA256_MISMATCH = (
        "ASSET_CARDS_SHA256_MISMATCH",
        "experience_cards_file sha256 mismatch",
    )
    CARDS_NOT_ARRAY = (
        "ASSET_CARDS_NOT_ARRAY",
        "experience_cards_file must contain a JSON array",
    )
    PACKAGE_VERSION = (
        "ASSET_PACKAGE_VERSION_INVALID",
        "asset package version is invalid",
    )
    STYLE_COUNT = (
        "ASSET_STYLE_COUNT_INVALID",
        "asset package must contain exactly 10 styles",
    )
    CARD_COUNT = (
        "ASSET_CARD_COUNT_INVALID",
        "asset package must contain exactly 64 experience cards",
    )
    CATEGORY_COVERAGE = (
        "ASSET_CATEGORY_COVERAGE_INVALID",
        "experience cards must match approved category counts",
    )
    STYLE_KEY_DUPLICATE = (
        "ASSET_STYLE_KEY_DUPLICATE",
        "duplicate stable_key in styles",
    )
    CARD_KEY_DUPLICATE = (
        "ASSET_CARD_KEY_DUPLICATE",
        "duplicate stable_key in experience_cards",
    )
    METHOD_DUPLICATE = (
        "ASSET_METHOD_DUPLICATE",
        "duplicate normalized method",
    )
    MICRO_DEMO_DUPLICATE = (
        "ASSET_MICRO_DEMO_DUPLICATE",
        "duplicate normalized original_micro_demo",
    )
    CONTENT_HASH_DUPLICATE = (
        "ASSET_CONTENT_HASH_DUPLICATE",
        "duplicate content_hash",
    )
    CONTENT_HASH_MISMATCH = (
        "ASSET_CONTENT_HASH_MISMATCH",
        "asset content_hash mismatch",
    )
    RELEASE_REVIEW_INCOMPLETE = (
        "ASSET_RELEASE_REVIEW_INCOMPLETE",
        "release review metadata is incomplete",
    )


class AssetPackageError(ValueError):
    """A stable, non-sensitive error at the public asset-package boundary."""

    def __init__(self, error: _AssetError) -> None:
        if not isinstance(error, _AssetError):
            raise TypeError("AssetPackageError requires a fixed asset error")
        self.code, self.safe_message = error.value
        super().__init__(f"{self.code}: {self.safe_message}")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )


class StylePromptPayload(_FrozenModel):
    schemaVersion: SchemaVersion
    reading_experience: PromptText
    applicability: tuple[ListItem, ...] = Field(min_length=1, max_length=32)
    non_applicability: tuple[ListItem, ...] = Field(min_length=1, max_length=32)
    standard_scene_example: ExampleText
    complete_application_example: ExampleText
    narrative_distance: PromptText
    rhythm: PromptText
    diction_density: PromptText
    dialogue: PromptText
    subtext: PromptText
    character_voices: PromptText
    emotion: PromptText
    interiority: PromptText
    action: PromptText
    explanation: PromptText
    environment: PromptText
    body_response: PromptText
    preferred_techniques: tuple[ListItem, ...] = Field(
        min_length=1,
        max_length=32,
    )
    risks: tuple[ListItem, ...] = Field(min_length=1, max_length=32)
    original_anchor: PromptText

    @field_validator(
        "applicability",
        "non_applicability",
        "preferred_techniques",
        "risks",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ExperienceCardPromptPayload(_FrozenModel):
    schemaVersion: SchemaVersion
    category: AssetCategory
    method: PromptText
    applicability: tuple[ListItem, ...] = Field(min_length=1, max_length=32)
    non_applicability: tuple[ListItem, ...] = Field(
        min_length=1,
        max_length=32,
    )
    risks: tuple[ListItem, ...] = Field(min_length=1, max_length=32)
    original_micro_demo: ExampleText

    @field_validator("applicability", "non_applicability", "risks", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class AssetProvenance(_FrozenModel):
    reviewer: ReviewerName | None = None
    review_time: ReviewTime | None = None
    decision: ReviewDecision

    @field_validator("review_time")
    @classmethod
    def require_aware_iso_timestamp(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parse_failed = False
        parsed: datetime | None = None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            parse_failed = True
        if parse_failed:
            raise ValueError("review_time must be an ISO-8601 timestamp")
        assert parsed is not None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("review_time must include a timezone offset")
        return value


class StyleTemplateRevision(_FrozenModel):
    stable_key: StableKey
    revision: int = Field(gt=0)
    name: AssetName
    payload: StylePromptPayload
    provenance: AssetProvenance
    content_hash: str = Field(pattern=_SHA256_PATTERN.pattern)


class ExperienceCardRevision(_FrozenModel):
    stable_key: StableKey
    revision: int = Field(gt=0)
    title: AssetName
    category: AssetCategory
    payload: ExperienceCardPromptPayload
    provenance: AssetProvenance
    content_hash: str = Field(pattern=_SHA256_PATTERN.pattern)

    @model_validator(mode="after")
    def category_matches_payload(self) -> Self:
        if self.category != self.payload.category:
            raise ValueError("category must match payload category")
        return self


class AssetFile(_FrozenModel):
    path: ManifestPath
    sha256: str = Field(pattern=_SHA256_PATTERN.pattern)

    @field_validator("path")
    @classmethod
    def require_safe_relative_json_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        posix_path = PurePosixPath(normalized)
        windows_path = PureWindowsPath(value)
        if (
            posix_path.is_absolute()
            or windows_path.is_absolute()
            or bool(windows_path.drive)
            or bool(windows_path.root)
            or ".." in posix_path.parts
            or ".." in windows_path.parts
            or posix_path.suffix.lower() != ".json"
        ):
            raise ValueError("asset child path must be a relative JSON path")
        return normalized


class AssetManifest(_FrozenModel):
    package_version: PackageVersion
    styles_file: AssetFile
    experience_cards_file: AssetFile


class AssetPackage(_FrozenModel):
    manifest: AssetManifest
    styles: tuple[StyleTemplateRevision, ...] = Field(min_length=10, max_length=10)
    experience_cards: tuple[ExperienceCardRevision, ...] = Field(
        min_length=64,
        max_length=64,
    )

    @field_validator("styles", "experience_cards", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @property
    def package_version(self) -> str:
        """Expose the validated manifest version at the package boundary."""

        return self.manifest.package_version


def _normalized_identity(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split()).casefold()


def _ensure_unique(values: list[str], *, error: _AssetError) -> None:
    normalized = [_normalized_identity(value) for value in values]
    if len(normalized) != len(set(normalized)):
        raise AssetPackageError(error)


def _validate_release_review(package: AssetPackage) -> None:
    for asset in (*package.styles, *package.experience_cards):
        provenance = asset.provenance
        if (
            provenance.decision != "approved"
            or provenance.reviewer is None
            or provenance.review_time is None
        ):
            raise AssetPackageError(_AssetError.RELEASE_REVIEW_INCOMPLETE)


def validate_asset_package(
    package: AssetPackage | dict[str, object],
    *,
    mode: ValidationMode = "structural",
) -> AssetPackage:
    """Validate inventory, hashes, uniqueness and optional release approval."""

    if mode not in ("structural", "release"):
        raise AssetPackageError(_AssetError.VALIDATION_MODE_UNSUPPORTED)
    if not isinstance(package, AssetPackage):
        validation_failed = False
        try:
            package = AssetPackage.model_validate(package)
        except ValidationError:
            validation_failed = True
        if validation_failed:
            raise _validation_error("asset package")
    if package.manifest.package_version != PACKAGE_VERSION:
        raise AssetPackageError(_AssetError.PACKAGE_VERSION)
    if len(package.styles) != 10:
        raise AssetPackageError(_AssetError.STYLE_COUNT)
    if len(package.experience_cards) != 64:
        raise AssetPackageError(_AssetError.CARD_COUNT)
    category_counts = {
        category: sum(card.category == category for card in package.experience_cards)
        for category in ASSET_CATEGORIES
    }
    if category_counts != ASSET_CATEGORY_COUNTS:
        raise AssetPackageError(_AssetError.CATEGORY_COVERAGE)

    _ensure_unique(
        [style.stable_key for style in package.styles],
        error=_AssetError.STYLE_KEY_DUPLICATE,
    )
    _ensure_unique(
        [card.stable_key for card in package.experience_cards],
        error=_AssetError.CARD_KEY_DUPLICATE,
    )
    _ensure_unique(
        [card.payload.method for card in package.experience_cards],
        error=_AssetError.METHOD_DUPLICATE,
    )
    _ensure_unique(
        [card.payload.original_micro_demo for card in package.experience_cards],
        error=_AssetError.MICRO_DEMO_DUPLICATE,
    )

    assets = (*package.styles, *package.experience_cards)
    hashes = [asset.content_hash for asset in assets]
    if len(hashes) != len(set(hashes)):
        raise AssetPackageError(_AssetError.CONTENT_HASH_DUPLICATE)
    for asset in assets:
        expected_hash = canonical_hash(asset.payload)
        if asset.content_hash != expected_hash:
            raise AssetPackageError(_AssetError.CONTENT_HASH_MISMATCH)

    if mode == "release":
        _validate_release_review(package)
    return package


def _validation_error(label: str) -> AssetPackageError:
    error = (
        _AssetError.MANIFEST_INVALID
        if label == "asset manifest"
        else _AssetError.PACKAGE_INVALID
    )
    return AssetPackageError(error)


def _parse_json_bytes(raw: bytes, *, label: str) -> object:
    parse_failed = False
    parsed: object = None
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        parse_failed = True
    if parse_failed:
        error = {
            "asset manifest": _AssetError.MANIFEST_JSON_INVALID,
            "styles_file": _AssetError.STYLES_JSON_INVALID,
            "experience_cards_file": _AssetError.CARDS_JSON_INVALID,
        }[label]
        raise AssetPackageError(error)
    return parsed


def _read_bounded_bytes(
    path: Path,
    *,
    limit: int,
    io_error: _AssetError,
    size_error: _AssetError,
) -> bytes:
    stat_failed = False
    size = 0
    try:
        size = path.stat().st_size
    except OSError:
        stat_failed = True
    if stat_failed:
        raise AssetPackageError(io_error)
    if size > limit:
        raise AssetPackageError(size_error)

    read_failed = False
    raw = b""
    try:
        with path.open("rb") as source:
            raw = source.read(limit + 1)
    except OSError:
        read_failed = True
    if read_failed:
        raise AssetPackageError(io_error)
    if len(raw) > limit:
        raise AssetPackageError(size_error)
    return raw


def _read_child(
    manifest_path: Path,
    descriptor: AssetFile,
    *,
    label: str,
) -> object:
    root = manifest_path.parent.resolve()
    child_path = (root / descriptor.path).resolve()
    if root not in child_path.parents:
        error = (
            _AssetError.STYLES_PATH_ESCAPE
            if label == "styles_file"
            else _AssetError.CARDS_PATH_ESCAPE
        )
        raise AssetPackageError(error)
    is_styles = label == "styles_file"
    raw = _read_bounded_bytes(
        child_path,
        limit=MAX_ASSET_CHILD_BYTES,
        io_error=_AssetError.STYLES_IO if is_styles else _AssetError.CARDS_IO,
        size_error=(
            _AssetError.STYLES_TOO_LARGE
            if is_styles
            else _AssetError.CARDS_TOO_LARGE
        ),
    )
    actual_hash = sha256(raw).hexdigest()
    if actual_hash != descriptor.sha256:
        error = (
            _AssetError.STYLES_SHA256_MISMATCH
            if label == "styles_file"
            else _AssetError.CARDS_SHA256_MISMATCH
        )
        raise AssetPackageError(error)
    return _parse_json_bytes(raw, label=label)


def load_asset_package(
    manifest_path: Path,
    *,
    mode: ValidationMode = "structural",
) -> AssetPackage:
    """Load and validate a package deterministically from one manifest path."""

    path = Path(manifest_path)
    manifest_raw = _read_bounded_bytes(
        path,
        limit=MAX_ASSET_MANIFEST_BYTES,
        io_error=_AssetError.MANIFEST_IO,
        size_error=_AssetError.MANIFEST_TOO_LARGE,
    )
    manifest_values = _parse_json_bytes(manifest_raw, label="asset manifest")
    manifest_validation_failed = False
    try:
        manifest = AssetManifest.model_validate(manifest_values)
    except ValidationError:
        manifest_validation_failed = True
    if manifest_validation_failed:
        raise _validation_error("asset manifest")

    styles_values = _read_child(
        path,
        manifest.styles_file,
        label="styles_file",
    )
    cards_values = _read_child(
        path,
        manifest.experience_cards_file,
        label="experience_cards_file",
    )
    if not isinstance(styles_values, list):
        raise AssetPackageError(_AssetError.STYLES_NOT_ARRAY)
    if not isinstance(cards_values, list):
        raise AssetPackageError(_AssetError.CARDS_NOT_ARRAY)

    package_validation_failed = False
    try:
        package = AssetPackage.model_validate(
            {
                "manifest": manifest,
                "styles": styles_values,
                "experience_cards": cards_values,
            }
        )
    except ValidationError:
        package_validation_failed = True
    if package_validation_failed:
        raise _validation_error("asset package")
    return validate_asset_package(package, mode=mode)
