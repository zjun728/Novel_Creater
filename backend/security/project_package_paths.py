"""Path and sensitive-field guards for deterministic project packages."""

from __future__ import annotations

import re
from collections.abc import Mapping

from backend.domain.project_packages import (
    MANIFEST_HASH_PATH,
    MANIFEST_PATH,
    MAX_ENTRY_PATH_BYTES,
    PAYLOAD_PATHS,
    ProjectPackageInvalid,
    ProjectPackageSensitiveData,
)


ALLOWED_FIXED_PATHS = frozenset((*PAYLOAD_PATHS, MANIFEST_PATH, MANIFEST_HASH_PATH))
CORPUS_BLOB_RE = re.compile(r"^corpus/blobs/sha256/[0-9a-f]{64}$")
_SENSITIVE_FIELD_CLASSES = frozenset({
    "apikey", "baseurl", "authorization", "token", "password", "dsn", "lease", "ownertoken",
    "includeapikeys", "hasapikey", "absolutepath", "localpath", "filesystempath", "enabled",
})


def _invalid_path() -> ProjectPackageInvalid:
    return ProjectPackageInvalid("invalid package entry path")


def validate_entry_path(value: str) -> str:
    if not isinstance(value, str):
        raise _invalid_path()
    try:
        encoded = value.encode("ascii", "strict")
    except UnicodeEncodeError:
        raise _invalid_path() from None
    if (
        not value
        or len(encoded) > MAX_ENTRY_PATH_BYTES
        or "\\" in value
        or "\x00" in value
        or value.startswith("/")
        or ".." in value.split("/")
    ):
        raise _invalid_path()
    if value not in ALLOWED_FIXED_PATHS and not CORPUS_BLOB_RE.fullmatch(value):
        raise _invalid_path()
    return value


def validate_entry_paths(values: object) -> tuple[str, ...]:
    paths = tuple(validate_entry_path(value) for value in values)  # type: ignore[arg-type]
    normalized = tuple(path.casefold() for path in paths)
    if len(set(normalized)) != len(normalized):
        raise _invalid_path()
    return paths


def _sensitive_field_class(key: str) -> str | None:
    normalized = key.replace("_", "").replace("-", "").casefold()
    return normalized if normalized in _SENSITIVE_FIELD_CLASSES else None


def reject_sensitive_keys(value: object) -> None:
    """Reject sensitive JSON keys without exposing a key, path, or value."""

    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str) and _sensitive_field_class(key) is not None:
                raise ProjectPackageSensitiveData("sensitive field class")
            reject_sensitive_keys(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            reject_sensitive_keys(nested)
