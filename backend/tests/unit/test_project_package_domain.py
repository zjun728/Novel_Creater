from __future__ import annotations

from dataclasses import FrozenInstanceError
from hashlib import sha256
import math

import pytest

from backend.domain.project_packages import (
    MAX_ARCHIVE_BYTES,
    MAX_CORPUS_BLOB_BYTES,
    MAX_ENTRY_COUNT,
    MAX_STRUCTURED_ENTRY_BYTES,
    MAX_TOTAL_ENTRY_BYTES,
    ManifestEntry,
    PAYLOAD_PATHS,
    PackageEntry,
    PackageRecord,
    ProjectPackageInvalid,
    ProjectPackageManifest,
    ProjectPackageTooLarge,
    build_manifest,
    build_structured_entries,
    canonical_jsonl,
    canonical_line,
    enforce_package_limits,
    validate_archive_bytes,
    validate_json_depth,
)


def _record(entity_type: str, logical_id: str, revision: int, order: int) -> PackageRecord:
    return PackageRecord(
        entity_type=entity_type,
        logical_id=logical_id,
        revision=revision,
        order=order,
        data={"label": logical_id},
    )


class _SizedBytes(bytes):
    def __new__(cls, size: int) -> "_SizedBytes":
        value = super().__new__(cls, b"x")
        value._size = size
        return value

    def __len__(self) -> int:
        return self._size


def _snapshot(reverse: bool = False) -> dict[str, object]:
    records = [_record("chapter", "chapter:2", 2, 0), _record("project", "project:1", 1, 0)]
    if reverse:
        records.reverse()
    return {
        "graph_records": records,
        "operation_records": [_record("operation", "operation:1", 0, 1)],
        "provider_history_records": [_record("provider-history", "provider-history:1", 0, 0)],
        "frozen_asset_records": [_record("asset", "asset:1", 1, 0)],
        "corpus_revision_records": [_record("corpus-revision", "corpus-revision:1", 1, 0)],
        "projection_validation": {"hashes": ["b", "a"], "count": 2},
    }


def test_payload_entries_are_exact_ascii_sorted_and_deterministic() -> None:
    entries = build_structured_entries(_snapshot(reverse=True))

    assert [entry.path for entry in entries] == list(PAYLOAD_PATHS)
    assert all(entry.path.isascii() and entry.data.endswith(b"\n") for entry in entries)
    assert entries == build_structured_entries(_snapshot(reverse=False))


def test_manifest_has_no_self_reference_and_hashes_exact_bytes() -> None:
    entries = build_structured_entries(_snapshot())
    manifest = build_manifest(entries, project_logical_id="project:1", counts={"project": 1})

    assert [item.path for item in manifest.entries] == list(PAYLOAD_PATHS)
    assert "manifest.json" not in {item.path for item in manifest.entries}
    assert "manifest.sha256" not in {item.path for item in manifest.entries}
    assert manifest.entries[0].sha256 == sha256(entries[0].data).hexdigest()
    assert manifest.to_bytes().endswith(b"\n")


def test_build_manifest_default_project_identity_is_canonical() -> None:
    manifest = build_manifest(build_structured_entries(_snapshot()), counts={"project": 1})

    assert manifest.project_logical_id == "project:1"


def test_records_are_immutable_and_canonical_jsonl_uses_logical_sort_key() -> None:
    first = _record("project", "project:1", 2, 1)
    second = _record("project", "project:1", 1, 3)

    with pytest.raises(FrozenInstanceError):
        first.revision = 3  # type: ignore[misc]

    assert canonical_jsonl([first, second]) == (
        canonical_line(second.to_public_dict()) + canonical_line(first.to_public_dict())
    )


@pytest.mark.parametrize("entity_type,logical_id", [
    ("project", "project:1"),
    ("chapter", "chapter:2"),
    ("operation", "operation:3"),
    ("provider-history", "provider-history:4"),
    ("asset", "asset:5"),
    ("corpus-revision", "corpus-revision:6"),
])
def test_closed_record_registry_accepts_only_minimal_label_shape(entity_type: str, logical_id: str) -> None:
    assert PackageRecord(entity_type, logical_id, data={"label": logical_id}).to_public_dict()["logicalId"] == logical_id


@pytest.mark.parametrize("kwargs", [
    {"entity_type": "unknown", "logical_id": "unknown:1", "data": {"label": "x"}},
    {"entity_type": "project", "logical_id": "chapter:1", "data": {"label": "x"}},
    {"entity_type": "project", "logical_id": "project:550e8400-e29b-41d4-a716-446655440000", "data": {"label": "x"}},
    {"entity_type": "project", "logical_id": "project:1", "data": {"unknown": "x"}},
    {"entity_type": "project", "logical_id": "project:1", "revision": True, "data": {"label": "x"}},
    {"entity_type": "project", "logical_id": "project:1", "order": False, "data": {"label": "x"}},
])
def test_record_rejects_noncanonical_identity_unknown_data_and_boolean_integers(kwargs: dict[str, object]) -> None:
    with pytest.raises(ProjectPackageInvalid, match="invalid package value"):
        PackageRecord(**kwargs)  # type: ignore[arg-type]


def test_canonical_jsonl_rejects_duplicate_identity_before_sorting() -> None:
    first = _record("project", "project:1", 1, 0)
    second = PackageRecord("project", "project:1", revision=1, order=0, data={"label": "other"})

    for records in ([first, second], [second, first]):
        with pytest.raises(ProjectPackageInvalid, match="invalid package record"):
            canonical_jsonl(records)


@pytest.mark.parametrize("data", [
    {"seedId": "550e8400-e29b-41d4-a716-446655440000"},
    {"nested": {"finalization": [{"entity_id": "550e8400-e29b-41d4-a716-446655440000"}]}},
])
def test_record_payload_rejects_raw_database_id_values_recursively(data: dict[str, object]) -> None:
    with pytest.raises(ProjectPackageInvalid, match="invalid package value"):
        PackageRecord("project", "project:1", data={"label": "project", "payload": data})


def test_record_payload_accepts_only_package_logical_identity_values() -> None:
    record = PackageRecord(
        "project", "project:1",
        data={"label": "project", "payload": {"seedId": "creative-seed:1", "items": [{"entity_id": None}, {"entity_id": "canon-entity:2"}]}},
    )

    assert record.to_public_dict()["logicalId"] == "project:1"


def test_manifest_entries_are_strict_payload_or_blob_values_without_self_reference() -> None:
    entries = build_structured_entries(_snapshot())
    manifest_entries = tuple(
        ManifestEntry(item.path, len(item.data), sha256(item.data).hexdigest()) for item in entries
    )
    manifest = ProjectPackageManifest("project:1", manifest_entries, {"project": 1})
    assert manifest.entries == manifest_entries

    invalid_entry_sets = [
        manifest_entries[:-1],
        manifest_entries + (manifest_entries[0],),
        tuple(reversed(manifest_entries)),
        manifest_entries + (ManifestEntry("corpus/blobs/sha256/" + "a" * 64, 0, "b" * 64),),
    ]
    for invalid_entries in invalid_entry_sets[:3]:
        with pytest.raises(ProjectPackageInvalid, match="invalid package manifest"):
            ProjectPackageManifest("project:1", invalid_entries, {"project": 1})

    with pytest.raises(ProjectPackageInvalid, match="invalid package entry path"):
        ManifestEntry("manifest.json", 0, "a" * 64)
    with pytest.raises(ProjectPackageInvalid, match="invalid package value"):
        ManifestEntry("project/graph.jsonl", True, "a" * 64)
    with pytest.raises(ProjectPackageInvalid, match="invalid package value"):
        ManifestEntry("project/graph.jsonl", 0, "A" * 64)
    with pytest.raises(ProjectPackageInvalid, match="invalid package value"):
        ProjectPackageManifest("project:1", manifest_entries, {"project": True})
    with pytest.raises(ProjectPackageInvalid, match="invalid package value"):
        ProjectPackageManifest("project:uuid-not-allowed", manifest_entries, {"project": 1})


def test_canonical_line_rejects_nan_and_excessive_json_depth() -> None:
    with pytest.raises(ProjectPackageInvalid, match="invalid package value"):
        canonical_line({"value": math.nan})

    nested: object = "leaf"
    for _ in range(64):
        nested = {"next": nested}
    validate_json_depth(nested)
    with pytest.raises(ProjectPackageInvalid, match="invalid package value"):
        validate_json_depth({"next": nested})


def test_limit_guards_cover_entries_structured_blobs_totals_and_archive() -> None:
    with pytest.raises(ProjectPackageTooLarge):
        enforce_package_limits([PackageEntry("project/graph.jsonl", b"x")] * (MAX_ENTRY_COUNT + 1))
    with pytest.raises(ProjectPackageTooLarge):
        enforce_package_limits([PackageEntry("project/graph.jsonl", _SizedBytes(MAX_STRUCTURED_ENTRY_BYTES + 1))])
    blob_path = "corpus/blobs/sha256/" + "a" * 64
    with pytest.raises(ProjectPackageTooLarge):
        enforce_package_limits([PackageEntry(blob_path, _SizedBytes(MAX_CORPUS_BLOB_BYTES + 1))])
    with pytest.raises(ProjectPackageTooLarge):
        enforce_package_limits([
            PackageEntry(f"corpus/blobs/sha256/{index:064x}", _SizedBytes(MAX_CORPUS_BLOB_BYTES))
            for index in range(5)
        ])
    with pytest.raises(ProjectPackageTooLarge):
        validate_archive_bytes(MAX_ARCHIVE_BYTES + 1)
