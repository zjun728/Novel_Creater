"""Deterministic, secret-free project package creation and owned temp lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from itertools import islice
import logging
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time
import zipfile

from backend.domain import project_packages as project_package_domain
from backend.domain.json_contracts import canonical_json
from backend.domain.project_packages import (
    MANIFEST_HASH_PATH,
    MANIFEST_PATH,
    MAX_CORPUS_BLOB_BYTES,
    PackageEntry,
    ProjectPackageError,
    ProjectPackageIntegrity,
    ProjectPackageInvalid,
    ProjectPackageSensitiveData,
    ProjectPackageTooLarge,
    build_manifest,
    build_structured_entries,
    enforce_package_limits,
    validate_archive_bytes,
)
from backend.repositories.project_packages import FrozenCorpusBlob, ProjectPackageSnapshot
from backend.security.paths import UnsafeLocalPath, managed_corpus_blob_path
from backend.security.private_files import (
    PrivateFilePermissionsError,
    apply_private_permissions as _shared_apply_private_permissions,
)
from backend.security.project_package_paths import validate_entry_path


TEMP_PREFIX = "novel-creator-phase6b-"
ARCHIVE_FILENAME = "project-backup.zip"
STALE_AFTER_SECONDS = 24 * 60 * 60
STALE_SCAN_LIMIT = 32
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PRIVATE_PERMISSIONS_ERROR = "project package private permissions are unavailable"
_logger = logging.getLogger("backend.project_packages")


def _is_link(path: Path) -> bool:
    metadata = path.lstat()
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & 0x400
    )


def _contained(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _apply_private_permissions(path: Path, *, is_directory: bool) -> None:
    """Retain the Phase 6B public error contract around the shared ACL helper."""

    try:
        _shared_apply_private_permissions(path, is_directory=is_directory)
    except PrivateFilePermissionsError:
        raise ProjectPackageIntegrity(_PRIVATE_PERMISSIONS_ERROR) from None


@dataclass(slots=True)
class ProjectPackageTempOwner:
    root: Path
    archive_path: Path
    _parent: Path
    _cleaned: bool = False

    @classmethod
    def create(cls, *, temp_parent: Path, managed_corpus_root: Path) -> "ProjectPackageTempOwner":
        created_root: Path | None = None
        try:
            parent = Path(temp_parent).resolve(strict=True)
            corpus = Path(managed_corpus_root).resolve(strict=True)
            if not parent.is_dir() or not corpus.is_dir() or _is_link(parent) or _is_link(corpus):
                raise ProjectPackageIntegrity("project package temporary storage is unavailable")
            created_root = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX, dir=parent))
            root = created_root.resolve(strict=True)
            if (
                root.parent != parent
                or not root.name.startswith(TEMP_PREFIX)
                or _contained(corpus, root)
                or _contained(root, corpus)
            ):
                raise ProjectPackageIntegrity("project package temporary storage is unavailable")
            _apply_private_permissions(root, is_directory=True)
            return cls(root=root, archive_path=root / ARCHIVE_FILENAME, _parent=parent)
        except ProjectPackageError:
            if created_root is not None:
                shutil.rmtree(created_root, ignore_errors=True)
            raise
        except (OSError, RuntimeError, TypeError, ValueError):
            if created_root is not None:
                shutil.rmtree(created_root, ignore_errors=True)
            raise ProjectPackageIntegrity("project package temporary storage is unavailable") from None

    def cleanup(self) -> None:
        if self._cleaned:
            return
        try:
            if not self.root.exists():
                self._cleaned = True
                return
            resolved = self.root.resolve(strict=True)
            if (
                resolved.parent != self._parent
                or resolved.name != self.root.name
                or not resolved.name.startswith(TEMP_PREFIX)
                or _is_link(self.root)
                or not self.root.is_dir()
            ):
                raise ProjectPackageIntegrity("project package temporary cleanup refused")
            shutil.rmtree(resolved)
            self._cleaned = True
        except ProjectPackageError:
            raise
        except (OSError, RuntimeError, ValueError):
            raise ProjectPackageIntegrity("project package temporary cleanup failed") from None

    def handoff_cleanup(self) -> Callable[[], None]:
        return self.cleanup


def cleanup_stale_project_package_roots(
    temp_parent: Path,
    *,
    now: float | None = None,
) -> int:
    """Examine at most 32 immediate children and remove only stale owned-prefix roots."""

    try:
        parent = Path(temp_parent).resolve(strict=True)
        if not parent.is_dir() or _is_link(parent):
            return 0
        cutoff = (time.time() if now is None else now) - STALE_AFTER_SECONDS
        examined = 0
        for candidate in islice(parent.iterdir(), STALE_SCAN_LIMIT):
            examined += 1
            if not candidate.name.startswith(TEMP_PREFIX):
                continue
            try:
                metadata = candidate.lstat()
                if (
                    not stat.S_ISDIR(metadata.st_mode)
                    or _is_link(candidate)
                    or metadata.st_mtime >= cutoff
                ):
                    continue
                resolved = candidate.resolve(strict=True)
                if resolved.parent != parent or resolved.name != candidate.name:
                    continue
                shutil.rmtree(resolved)
            except (OSError, RuntimeError, ValueError):
                _logger.warning("project_package_stale_candidate_cleanup_failed")
                continue
        return examined
    except (OSError, RuntimeError, TypeError, ValueError):
        _logger.warning("project_package_stale_scan_failed")
        return 0


def _zip_info(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(validate_entry_path(path), (1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    info.extra = b""
    info.comment = b""
    return info


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _BoundedArchiveWriter:
    """Seekable writer that rejects an archive as soon as its extent is too large."""

    def __init__(self, target) -> None:
        self._target = target
        self._extent = 0

    def write(self, data: bytes) -> int:
        written = self._target.write(data)
        self._extent = max(self._extent, self._target.tell())
        if self._extent > project_package_domain.MAX_ARCHIVE_BYTES:
            raise ProjectPackageTooLarge("project package exceeds configured limit")
        return written

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        return self._target.seek(offset, whence)

    def tell(self) -> int:
        return self._target.tell()

    def flush(self) -> None:
        self._target.flush()


def write_deterministic_zip(
    archive_path: Path,
    payload_entries: Iterable[PackageEntry],
    *,
    project_logical_id: str,
    counts: Mapping[str, int],
) -> str:
    """Write one exact ZIP after every bounded payload and manifest byte is known."""

    payload = enforce_package_limits(payload_entries)
    manifest = build_manifest(payload, project_logical_id=project_logical_id, counts=counts)
    manifest_bytes = manifest.to_bytes()
    manifest_hash_bytes = sha256(manifest_bytes).hexdigest().encode("ascii") + b"\n"
    complete = enforce_package_limits((
        *payload,
        PackageEntry(MANIFEST_PATH, manifest_bytes),
        PackageEntry(MANIFEST_HASH_PATH, manifest_hash_bytes),
    ))
    ordered = tuple(sorted(complete, key=lambda entry: entry.path))
    path = Path(archive_path)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w+b") as target:
        _apply_private_permissions(path, is_directory=False)
        bounded = _BoundedArchiveWriter(target)
        with zipfile.ZipFile(bounded, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as package:
            package.comment = b""
            for entry in ordered:
                package.writestr(_zip_info(entry.path), entry.data)
    validate_archive_bytes(path.stat().st_size)
    return _file_sha256(path)


def _corpus_entries(snapshot: ProjectPackageSnapshot, managed_corpus_root: Path) -> tuple[PackageEntry, ...]:
    entries: list[PackageEntry] = []
    try:
        corpus_root = Path(managed_corpus_root).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise ProjectPackageIntegrity("project package corpus integrity check failed") from None
    for descriptor in snapshot.corpus_blobs:
        if type(descriptor) is not FrozenCorpusBlob:
            raise ProjectPackageInvalid("invalid package corpus descriptor")
        if descriptor.byte_length > MAX_CORPUS_BLOB_BYTES:
            raise ProjectPackageTooLarge("project package exceeds configured limit")
        try:
            path = managed_corpus_blob_path(managed_corpus_root, descriptor.content_hash)
            if _is_link(path):
                raise ProjectPackageIntegrity("project package corpus integrity check failed")
            resolved_path = path.resolve(strict=True)
            if not _contained(corpus_root, resolved_path):
                raise ProjectPackageIntegrity("project package corpus integrity check failed")
            metadata = path.stat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != descriptor.byte_length:
                raise ProjectPackageIntegrity("project package corpus integrity check failed")
            if metadata.st_size > MAX_CORPUS_BLOB_BYTES:
                raise ProjectPackageTooLarge("project package exceeds configured limit")
            data = path.read_bytes()
        except ProjectPackageError:
            raise
        except (UnsafeLocalPath, OSError, RuntimeError, ValueError):
            raise ProjectPackageIntegrity("project package corpus integrity check failed") from None
        if len(data) != descriptor.byte_length or sha256(data).hexdigest() != descriptor.content_hash:
            raise ProjectPackageIntegrity("project package corpus integrity check failed")
        entries.append(PackageEntry(f"corpus/blobs/sha256/{descriptor.content_hash}", data))
    return tuple(entries)


def _json_escaped_inner_bytes(value: bytes) -> bytearray:
    try:
        text = value.decode("utf-8", errors="strict")
        literal = canonical_json(text)
        encoded = literal.encode("utf-8")
    except (TypeError, UnicodeError, ValueError):
        raise ProjectPackageInvalid("invalid project package secret value") from None
    if len(encoded) < 2 or encoded[:1] != b'"' or encoded[-1:] != b'"':
        raise ProjectPackageInvalid("invalid project package secret value")
    return bytearray(encoded[1:-1])


def _scan_exact_referenced_secrets(
    structured_entries: Iterable[PackageEntry],
    corpus_entries: Iterable[PackageEntry],
    values: Iterable[bytes],
) -> None:
    raw_secrets: list[bytearray] = []
    escaped_secrets: list[bytearray] = []
    try:
        for value in values:
            if type(value) is not bytes:
                raise ProjectPackageInvalid("invalid project package secret value")
            if not value:
                continue
            raw_secrets.append(bytearray(value))
            escaped_secrets.append(_json_escaped_inner_bytes(value))
        for entry in structured_entries:
            if any(entry.data.find(secret) >= 0 for secret in raw_secrets) or any(
                entry.data.find(secret) >= 0 for secret in escaped_secrets
            ):
                raise ProjectPackageSensitiveData("project package contains referenced sensitive value")
        for entry in corpus_entries:
            if any(entry.data.find(secret) >= 0 for secret in raw_secrets):
                raise ProjectPackageSensitiveData("project package contains referenced sensitive value")
    finally:
        for secret in (*raw_secrets, *escaped_secrets):
            secret[:] = b"\x00" * len(secret)
        raw_secrets.clear()
        escaped_secrets.clear()


@dataclass(frozen=True, slots=True)
class ProjectPackageFile:
    path: Path
    package_sha256: str
    download_name: str
    cleanup: Callable[[], None]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.path, Path)
            or not self.path.is_file()
            or _is_link(self.path)
            or type(self.package_sha256) is not str
            or _SHA256_RE.fullmatch(self.package_sha256) is None
            or self.download_name != ARCHIVE_FILENAME
            or not callable(self.cleanup)
        ):
            raise ProjectPackageInvalid("invalid project package file")


def cleanup_project_package_file(package: ProjectPackageFile) -> None:
    if type(package) is not ProjectPackageFile:
        raise ProjectPackageInvalid("invalid project package file")
    package.cleanup()


def _cleanup_owned_temp_after_failure(owner: ProjectPackageTempOwner) -> None:
    for attempt in range(2):
        try:
            owner.cleanup()
            return
        except BaseException:
            if attempt == 1:
                _logger.warning("project_package_service_cleanup_failed")


class ProjectPackageService:
    def __init__(
        self,
        *,
        repository,
        managed_corpus_root: Path,
        temp_parent: Path,
        zip_writer: Callable[..., str] = write_deterministic_zip,
    ) -> None:
        self._repository = repository
        self._managed_corpus_root = Path(managed_corpus_root)
        self._temp_parent = Path(temp_parent)
        self._zip_writer = zip_writer

    async def create_backup(
        self,
        project_id: str,
        expected_lifecycle_revision: int,
    ) -> ProjectPackageFile:
        snapshot = await self._repository.read_snapshot(project_id, expected_lifecycle_revision)
        if type(snapshot) is not ProjectPackageSnapshot:
            raise ProjectPackageInvalid("invalid project package snapshot")
        structured = build_structured_entries(snapshot)
        owner = ProjectPackageTempOwner.create(
            temp_parent=self._temp_parent,
            managed_corpus_root=self._managed_corpus_root,
        )
        try:
            corpus = _corpus_entries(snapshot, self._managed_corpus_root)
            entries = enforce_package_limits((*structured, *corpus))
            _scan_exact_referenced_secrets(
                structured, corpus, snapshot.referenced_secret_values
            )
            try:
                package_hash = self._zip_writer(
                    owner.archive_path,
                    entries,
                    project_logical_id=snapshot.source_project_logical_id,
                    counts=snapshot.counts,
                )
            except ProjectPackageError:
                raise
            except Exception:
                raise ProjectPackageIntegrity("project package archive creation failed") from None
            cleanup = owner.handoff_cleanup()
            return ProjectPackageFile(
                path=owner.archive_path,
                package_sha256=package_hash,
                download_name=ARCHIVE_FILENAME,
                cleanup=cleanup,
            )
        except BaseException:
            _cleanup_owned_temp_after_failure(owner)
            raise


__all__ = (
    "ARCHIVE_FILENAME",
    "ProjectPackageFile",
    "ProjectPackageService",
    "ProjectPackageTempOwner",
    "TEMP_PREFIX",
    "cleanup_project_package_file",
    "cleanup_stale_project_package_roots",
    "write_deterministic_zip",
)
