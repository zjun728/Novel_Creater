"""Strict immutable models and validation for Writer Core asset packages."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
from typing import Annotated, Literal, Self
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


PACKAGE_VERSION = "writer-core-v1.1.0"
ASSET_CATEGORIES = (
    "plot_organization",
    "ensemble",
    "dialogue",
    "emotion",
    "interiority",
    "information_release",
    "pacing",
    "suspense",
)

AssetCategory = Literal[
    "plot_organization",
    "ensemble",
    "dialogue",
    "emotion",
    "interiority",
    "information_release",
    "pacing",
    "suspense",
]
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


class AssetPackageError(ValueError):
    """An asset package is malformed or violates package policy."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class StylePromptPayload(_FrozenModel):
    schemaVersion: SchemaVersion
    reading_experience: PromptText
    applicability: tuple[ListItem, ...] = Field(min_length=1, max_length=32)
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

    @field_validator("applicability", "preferred_techniques", "risks", mode="before")
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
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("review_time must be an ISO-8601 timestamp") from exc
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
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts or path.suffix.lower() != ".json":
            raise ValueError("asset child path must be a relative JSON path")
        return normalized


class AssetManifest(_FrozenModel):
    package_version: Literal["writer-core-v1.1.0"]
    styles_file: AssetFile
    experience_cards_file: AssetFile


class AssetPackage(_FrozenModel):
    manifest: AssetManifest
    styles: tuple[StyleTemplateRevision, ...]
    experience_cards: tuple[ExperienceCardRevision, ...]

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


def _ensure_unique(values: list[str], *, label: str) -> None:
    normalized = [_normalized_identity(value) for value in values]
    if len(normalized) != len(set(normalized)):
        raise AssetPackageError(f"duplicate {label}")


def _validate_release_review(package: AssetPackage) -> None:
    for asset in (*package.styles, *package.experience_cards):
        provenance = asset.provenance
        if (
            provenance.decision != "approved"
            or provenance.reviewer is None
            or provenance.review_time is None
        ):
            raise AssetPackageError(
                f"release review metadata is incomplete for {asset.stable_key}"
            )


def validate_asset_package(
    package: AssetPackage | dict[str, object],
    *,
    mode: ValidationMode = "structural",
) -> AssetPackage:
    """Validate inventory, hashes, uniqueness and optional release approval."""

    if mode not in ("structural", "release"):
        raise AssetPackageError(f"unsupported validation mode: {mode}")
    if not isinstance(package, AssetPackage):
        try:
            package = AssetPackage.model_validate(package)
        except ValidationError as exc:
            raise _validation_error("asset package", exc) from exc
    if package.manifest.package_version != PACKAGE_VERSION:
        raise AssetPackageError(f"package_version must be {PACKAGE_VERSION}")
    if len(package.styles) != 8:
        raise AssetPackageError("asset package must contain exactly 8 styles")
    if not 40 <= len(package.experience_cards) <= 60:
        raise AssetPackageError("asset package must contain 40 to 60 experience cards")
    if {card.category for card in package.experience_cards} != set(ASSET_CATEGORIES):
        raise AssetPackageError("experience cards must cover all asset categories")

    _ensure_unique(
        [style.stable_key for style in package.styles],
        label="stable_key in styles",
    )
    _ensure_unique(
        [card.stable_key for card in package.experience_cards],
        label="stable_key in experience_cards",
    )
    _ensure_unique(
        [card.payload.method for card in package.experience_cards],
        label="normalized method",
    )
    _ensure_unique(
        [card.payload.original_micro_demo for card in package.experience_cards],
        label="normalized original_micro_demo",
    )

    assets = (*package.styles, *package.experience_cards)
    hashes = [asset.content_hash for asset in assets]
    if len(hashes) != len(set(hashes)):
        raise AssetPackageError("duplicate content_hash")
    for asset in assets:
        expected_hash = canonical_hash(asset.payload)
        if asset.content_hash != expected_hash:
            raise AssetPackageError(f"content_hash mismatch for {asset.stable_key}")

    if mode == "release":
        _validate_release_review(package)
    return package


def _validation_error(label: str, exc: ValidationError) -> AssetPackageError:
    first = exc.errors(include_url=False)[0]
    location = ".".join(str(part) for part in first["loc"])
    return AssetPackageError(
        f"invalid {label} at {location}: {first['msg']}"
    )


def _parse_json_bytes(raw: bytes, *, label: str) -> object:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssetPackageError(f"invalid JSON in {label}") from exc


def _read_child(
    manifest_path: Path,
    descriptor: AssetFile,
    *,
    label: str,
) -> object:
    root = manifest_path.parent.resolve()
    child_path = (root / descriptor.path).resolve()
    if root not in child_path.parents:
        raise AssetPackageError(f"{label} path escapes manifest directory")
    try:
        raw = child_path.read_bytes()
    except OSError as exc:
        raise AssetPackageError(f"unable to read {label}") from exc
    actual_hash = sha256(raw).hexdigest()
    if actual_hash != descriptor.sha256:
        raise AssetPackageError(f"{label} sha256 mismatch")
    return _parse_json_bytes(raw, label=label)


def load_asset_package(
    manifest_path: Path,
    *,
    mode: ValidationMode = "structural",
) -> AssetPackage:
    """Load and validate a package deterministically from one manifest path."""

    path = Path(manifest_path)
    try:
        manifest_raw = path.read_bytes()
    except OSError as exc:
        raise AssetPackageError("unable to read asset manifest") from exc
    manifest_values = _parse_json_bytes(manifest_raw, label="asset manifest")
    try:
        manifest = AssetManifest.model_validate(manifest_values)
    except ValidationError as exc:
        raise _validation_error("asset manifest", exc) from exc

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
        raise AssetPackageError("styles_file must contain a JSON array")
    if not isinstance(cards_values, list):
        raise AssetPackageError("experience_cards_file must contain a JSON array")

    try:
        package = AssetPackage.model_validate(
            {
                "manifest": manifest,
                "styles": styles_values,
                "experience_cards": cards_values,
            }
        )
    except ValidationError as exc:
        raise _validation_error("asset package", exc) from exc
    return validate_asset_package(package, mode=mode)
