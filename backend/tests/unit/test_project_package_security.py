from __future__ import annotations

import pytest

from backend.domain.project_packages import ProjectPackageInvalid, ProjectPackageSensitiveData
from backend.security.project_package_paths import (
    reject_sensitive_keys,
    validate_entry_path,
    validate_entry_paths,
)


@pytest.mark.parametrize("value", [
    "/project/graph.jsonl",
    "project/../graph.jsonl",
    "project\\graph.jsonl",
    "project/graph\x00.jsonl",
    "project/gráph.jsonl",
    "unrecognized/file.json",
])
def test_entry_path_rejects_unsafe_or_unrecognized_values(value: str) -> None:
    with pytest.raises(ProjectPackageInvalid, match="invalid package entry path"):
        validate_entry_path(value)


def test_entry_paths_reject_duplicate_case_collisions_and_overlong_paths() -> None:
    with pytest.raises(ProjectPackageInvalid, match="invalid package entry path"):
        validate_entry_paths(["project/graph.jsonl", "project/graph.jsonl"])
    with pytest.raises(ProjectPackageInvalid, match="invalid package entry path"):
        validate_entry_paths(["project/graph.jsonl", "PROJECT/GRAPH.JSONL"])
    with pytest.raises(ProjectPackageInvalid, match="invalid package entry path"):
        validate_entry_path("a" * 241)


def test_entry_path_accepts_only_fixed_paths_or_lowercase_sha256_blob() -> None:
    digest = "0" * 64
    assert validate_entry_path("project/graph.jsonl") == "project/graph.jsonl"
    assert validate_entry_path(f"corpus/blobs/sha256/{digest}") == f"corpus/blobs/sha256/{digest}"
    with pytest.raises(ProjectPackageInvalid):
        validate_entry_path("corpus/blobs/sha256/" + "A" * 64)


@pytest.mark.parametrize("key", [
    "apiKey", "api_key", "baseURL", "base_url", "Authorization", "token", "password", "dsn", "lease", "ownerToken",
    "includeApiKeys", "hasApiKey", "absolutePath", "localPath", "filesystemPath", "enabled",
    "providerUuid",
])
def test_sensitive_key_is_rejected_without_value_or_path(key: str) -> None:
    sentinel = "SECRET_MUST_NOT_APPEAR"
    with pytest.raises(ProjectPackageSensitiveData, match="sensitive field class") as raised:
        reject_sensitive_keys({"nested": {key: sentinel}})

    assert sentinel not in str(raised.value)
    assert "nested" not in str(raised.value)


def test_sensitive_key_rejection_recurses_through_lists() -> None:
    with pytest.raises(ProjectPackageSensitiveData, match="sensitive field class"):
        reject_sensitive_keys({"items": [{"password": "not-reported"}]})
