"""Closed, deterministic values for the project package v1 boundary."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
import math
import re
from types import MappingProxyType
from typing import Any

from backend.domain.json_contracts import canonical_json


PACKAGE_FORMAT = "novel-creator-project"
PACKAGE_VERSION = 1
HASH_ALGORITHM = "sha256"

MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_ENTRY_COUNT = 20_000
MAX_TOTAL_ENTRY_BYTES = 4 * 1024**3
MAX_STRUCTURED_ENTRY_BYTES = 128 * 1024**2
MAX_CORPUS_BLOB_BYTES = 1024**3
MAX_ENTRY_PATH_BYTES = 240
MAX_JSON_NESTING = 64

MANIFEST_PATH = "manifest.json"
MANIFEST_HASH_PATH = "manifest.sha256"
PAYLOAD_PATHS = (
    "assets/frozen.jsonl",
    "corpus/revisions.jsonl",
    "history/operations.jsonl",
    "history/providers.jsonl",
    "project/graph.jsonl",
    "validation/projections.json",
)

# Task 1 intentionally exports six closed record kinds. Task 2 extends this
# registry only after its ownership inventory has classified every authority.
RECORD_FIELD_ALLOWLISTS: Mapping[str, frozenset[str]] = MappingProxyType({
    "project": frozenset({"label"}),
    "chapter": frozenset({"label"}),
    "operation": frozenset({"label"}),
    "provider-history": frozenset({"label"}),
    "asset": frozenset({"label"}),
    "corpus-revision": frozenset({"label"}),
})
_ENTITY_TYPE_RE = re.compile(r"^[a-z]+(?:-[a-z]+)*$")
_LOWER_HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ProjectPackageError(Exception):
    """Base class for fixed public package-boundary errors."""


class ProjectPackageNotFound(ProjectPackageError):
    pass


class ProjectPackageConflict(ProjectPackageError):
    pass


class ProjectPackageTooLarge(ProjectPackageError):
    pass


class ProjectPackageInvalid(ProjectPackageError):
    pass


class ProjectPackageIntegrity(ProjectPackageError):
    pass


class ProjectPackageSensitiveData(ProjectPackageError):
    pass


def _invalid_value() -> ProjectPackageInvalid:
    return ProjectPackageInvalid("invalid package value")


def validate_json_depth(value: object, maximum: int = MAX_JSON_NESTING, _depth: int = 0) -> None:
    """Validate JSON-compatible values without ever reporting their contents."""

    if _depth > maximum:
        raise _invalid_value()
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _invalid_value()
        return
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise _invalid_value()
            validate_json_depth(nested, maximum, _depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            validate_json_depth(nested, maximum, _depth + 1)
        return
    raise _invalid_value()


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(nested) for key, nested in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(nested) for nested in value)
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(nested) for key, nested in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(nested) for nested in value]
    return value


def _reject_sensitive(value: object) -> None:
    # Importing lazily avoids a module cycle while keeping the security policy in its boundary.
    from backend.security.project_package_paths import reject_sensitive_keys

    reject_sensitive_keys(value)


def canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    validate_json_depth(value)
    _reject_sensitive(value)
    try:
        return canonical_json(dict(value)).encode("utf-8")
    except (TypeError, ValueError):
        raise _invalid_value() from None


def canonical_line(value: Mapping[str, object]) -> bytes:
    return canonical_json_bytes(value) + b"\n"


@dataclass(frozen=True, slots=True)
class PackageRecord:
    """A closed public record identified only by a package-local logical id."""

    entity_type: str
    logical_id: str
    revision: int = 0
    order: int = 0
    data: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.entity_type, str)
            or not _ENTITY_TYPE_RE.fullmatch(self.entity_type)
            or self.entity_type not in RECORD_FIELD_ALLOWLISTS
            or not isinstance(self.logical_id, str)
            or not re.fullmatch(rf"{re.escape(self.entity_type)}:[1-9][0-9]*", self.logical_id)
            or type(self.revision) is not int
            or self.revision < 0
            or type(self.order) is not int
            or self.order < 0
            or not isinstance(self.data, Mapping)
            or not set(self.data).issubset(RECORD_FIELD_ALLOWLISTS[self.entity_type])
        ):
            raise _invalid_value()
        validate_json_depth(self.data)
        _reject_sensitive(self.data)
        object.__setattr__(self, "data", _freeze_json(self.data))

    def to_public_dict(self) -> dict[str, object]:
        return {
            "data": _thaw_json(self.data),
            "entityType": self.entity_type,
            "logicalId": self.logical_id,
            "order": self.order,
            "revision": self.revision,
        }


def record_sort_key(record: PackageRecord) -> tuple[str, str, int, int]:
    return (record.entity_type, record.logical_id, record.revision, record.order)


def canonical_jsonl(records: Iterable[PackageRecord]) -> bytes:
    materialized = tuple(records)
    if any(type(record) is not PackageRecord for record in materialized):
        raise ProjectPackageInvalid("invalid package record")
    identities = tuple(record_sort_key(record) for record in materialized)
    if len(set(identities)) != len(identities):
        raise ProjectPackageInvalid("invalid package record")
    return b"".join(canonical_line(record.to_public_dict()) for record in sorted(materialized, key=record_sort_key))


@dataclass(frozen=True, slots=True)
class PackageEntry:
    path: str
    data: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes):
            raise _invalid_value()
        _validate_entry_path(self.path)


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    path: str
    byte_length: int
    sha256: str

    def __post_init__(self) -> None:
        _validate_entry_path(self.path)
        if self.path in {MANIFEST_PATH, MANIFEST_HASH_PATH}:
            raise ProjectPackageInvalid("invalid package entry path")
        if type(self.byte_length) is not int or self.byte_length < 0:
            raise _invalid_value()
        if not isinstance(self.sha256, str) or not _LOWER_HEX_SHA256_RE.fullmatch(self.sha256):
            raise _invalid_value()

    def to_public_dict(self) -> dict[str, object]:
        return {"byteLength": self.byte_length, "path": self.path, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class ProjectPackageManifest:
    project_logical_id: str
    entries: tuple[ManifestEntry, ...]
    counts: Mapping[str, int]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.project_logical_id, str)
            or not re.fullmatch(r"project:[1-9][0-9]*", self.project_logical_id)
        ):
            raise _invalid_value()
        if not isinstance(self.entries, tuple) or any(type(entry) is not ManifestEntry for entry in self.entries):
            raise ProjectPackageInvalid("invalid package manifest")
        paths = tuple(entry.path for entry in self.entries)
        from backend.security.project_package_paths import CORPUS_BLOB_RE

        if (
            paths != tuple(sorted(paths))
            or len(set(paths)) != len(paths)
            or len({path.casefold() for path in paths}) != len(paths)
            or set(PAYLOAD_PATHS) - set(paths)
            or any(path not in PAYLOAD_PATHS and not CORPUS_BLOB_RE.fullmatch(path) for path in paths)
        ):
            raise ProjectPackageInvalid("invalid package manifest")
        if (
            not isinstance(self.counts, Mapping)
            or any(
                not isinstance(key, str)
                or key not in RECORD_FIELD_ALLOWLISTS
                or type(value) is not int
                or value < 0
                for key, value in self.counts.items()
            )
        ):
            raise _invalid_value()
        object.__setattr__(self, "counts", MappingProxyType(dict(self.counts)))

    def to_public_dict(self) -> dict[str, object]:
        return {
            "counts": dict(sorted(self.counts.items())),
            "entries": [entry.to_public_dict() for entry in self.entries],
            "format": PACKAGE_FORMAT,
            "hashAlgorithm": HASH_ALGORITHM,
            "projectLogicalId": self.project_logical_id,
            "version": PACKAGE_VERSION,
        }

    def to_bytes(self) -> bytes:
        return canonical_line(self.to_public_dict())


def _validate_entry_path(value: str) -> str:
    from backend.security.project_package_paths import validate_entry_path

    return validate_entry_path(value)


def validate_archive_bytes(value: int) -> int:
    if type(value) is not int or value < 0:
        raise _invalid_value()
    if value > MAX_ARCHIVE_BYTES:
        raise ProjectPackageTooLarge("project package exceeds configured limit")
    return value


def enforce_package_limits(entries: Iterable[PackageEntry], *, archive_bytes: int | None = None) -> tuple[PackageEntry, ...]:
    """Validate path uniqueness and every v1 size bound before ZIP construction."""

    materialized = tuple(entries)
    if len(materialized) > MAX_ENTRY_COUNT:
        raise ProjectPackageTooLarge("project package exceeds configured limit")
    from backend.security.project_package_paths import validate_entry_paths

    validate_entry_paths(entry.path for entry in materialized)
    total = 0
    for entry in materialized:
        byte_length = len(entry.data)
        maximum = MAX_CORPUS_BLOB_BYTES if entry.path.startswith("corpus/blobs/sha256/") else MAX_STRUCTURED_ENTRY_BYTES
        if byte_length > maximum:
            raise ProjectPackageTooLarge("project package exceeds configured limit")
        total += byte_length
        if total > MAX_TOTAL_ENTRY_BYTES:
            raise ProjectPackageTooLarge("project package exceeds configured limit")
    if archive_bytes is not None:
        validate_archive_bytes(archive_bytes)
    return materialized


def build_manifest(
    payload_entries: Iterable[PackageEntry],
    *,
    project_logical_id: str = "project:1",
    counts: Mapping[str, int],
) -> ProjectPackageManifest:
    entries = enforce_package_limits(payload_entries)
    if any(entry.path in {MANIFEST_PATH, MANIFEST_HASH_PATH} for entry in entries):
        raise ProjectPackageInvalid("invalid package entry path")
    return ProjectPackageManifest(
        project_logical_id=project_logical_id,
        entries=tuple(
            ManifestEntry(path=entry.path, byte_length=len(entry.data), sha256=sha256(entry.data).hexdigest())
            for entry in sorted(entries, key=lambda entry: entry.path)
        ),
        counts=counts,
    )


def _snapshot_value(snapshot: object, name: str, default: object) -> object:
    if isinstance(snapshot, Mapping):
        return snapshot.get(name, default)
    return getattr(snapshot, name, default)


def build_structured_entries(snapshot: object) -> tuple[PackageEntry, ...]:
    """Build the six exact non-blob payload entries from an immutable snapshot."""

    record_paths = (
        ("assets/frozen.jsonl", "frozen_asset_records"),
        ("corpus/revisions.jsonl", "corpus_revision_records"),
        ("history/operations.jsonl", "operation_records"),
        ("history/providers.jsonl", "provider_history_records"),
        ("project/graph.jsonl", "graph_records"),
    )
    entries = [
        PackageEntry(path, canonical_jsonl(_snapshot_value(snapshot, field_name, ())))
        for path, field_name in record_paths
    ]
    projection = _snapshot_value(snapshot, "projection_validation", {})
    if not isinstance(projection, Mapping):
        raise _invalid_value()
    entries.append(PackageEntry("validation/projections.json", canonical_line(projection)))
    result = tuple(sorted(entries, key=lambda entry: entry.path))
    enforce_package_limits(result)
    return result
