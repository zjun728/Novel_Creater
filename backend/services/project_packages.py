"""Deterministic, secret-free project package creation and owned temp lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from itertools import islice
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
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
from backend.security.project_package_paths import validate_entry_path


TEMP_PREFIX = "novel-creator-phase6b-"
ARCHIVE_FILENAME = "project-backup.zip"
STALE_AFTER_SECONDS = 24 * 60 * 60
STALE_SCAN_LIMIT = 32
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_ACL_TIMEOUT_SECONDS = 5
_PRIVATE_PERMISSIONS_ERROR = "project package private permissions are unavailable"


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


def _windows_current_process_sid() -> str:
    import ctypes
    from ctypes import wintypes

    token_query = 0x0008
    token_user_class = 1

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]

    class TokenUser(ctypes.Structure):
        _fields_ = [("user", SidAndAttributes)]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    )
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_wchar_p),
    )
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), token_query, ctypes.byref(token)
    ):
        raise OSError("process token unavailable")
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(
            token, token_user_class, None, 0, ctypes.byref(required)
        )
        if required.value == 0:
            raise OSError("process token unavailable")
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            token_user_class,
            buffer,
            required,
            ctypes.byref(required),
        ):
            raise OSError("process token unavailable")
        token_user = ctypes.cast(buffer, ctypes.POINTER(TokenUser)).contents
        sid_text = ctypes.c_wchar_p()
        if not advapi32.ConvertSidToStringSidW(
            token_user.user.sid, ctypes.byref(sid_text)
        ):
            raise OSError("process SID unavailable")
        try:
            value = sid_text.value
            if value is None or re.fullmatch(r"S-[0-9]+(?:-[0-9]+)+", value) is None:
                raise OSError("process SID unavailable")
            return value
        finally:
            kernel32.LocalFree(ctypes.cast(sid_text, ctypes.c_void_p))
    finally:
        kernel32.CloseHandle(token)


def _windows_private_acl_is_valid(path: Path, sid: str, *, is_directory: bool) -> bool:
    import ctypes
    from ctypes import wintypes

    se_file_object = 1
    dacl_security_information = 0x00000004
    se_dacl_protected = 0x1000
    acl_size_information_class = 2
    access_allowed_ace_type = 0
    inherited_ace = 0x10
    object_and_container_inherit = 0x03
    file_all_access = 0x001F01FF

    class AclSizeInformation(ctypes.Structure):
        _fields_ = (
            ("ace_count", wintypes.DWORD),
            ("acl_bytes_in_use", wintypes.DWORD),
            ("acl_bytes_free", wintypes.DWORD),
        )

    class AceHeader(ctypes.Structure):
        _fields_ = (
            ("ace_type", wintypes.BYTE),
            ("ace_flags", wintypes.BYTE),
            ("ace_size", wintypes.WORD),
        )

    class AccessAllowedAce(ctypes.Structure):
        _fields_ = (
            ("header", AceHeader),
            ("mask", wintypes.DWORD),
            ("sid_start", wintypes.DWORD),
        )

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.GetNamedSecurityInfoW.argtypes = (
        wintypes.LPWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    )
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetSecurityDescriptorControl.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.WORD),
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.GetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi32.GetAclInformation.argtypes = (
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_int,
    )
    advapi32.GetAclInformation.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = (
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    )
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.ConvertStringSidToSidW.argtypes = (
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
    )
    advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
    advapi32.EqualSid.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    advapi32.EqualSid.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p

    dacl = ctypes.c_void_p()
    security_descriptor = ctypes.c_void_p()
    expected_sid = ctypes.c_void_p()
    try:
        if advapi32.GetNamedSecurityInfoW(
            os.fspath(path),
            se_file_object,
            dacl_security_information,
            None,
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(security_descriptor),
        ) != 0 or not dacl.value:
            return False
        control = wintypes.WORD()
        revision = wintypes.DWORD()
        if not advapi32.GetSecurityDescriptorControl(
            security_descriptor, ctypes.byref(control), ctypes.byref(revision)
        ) or not control.value & se_dacl_protected:
            return False
        acl_information = AclSizeInformation()
        if not advapi32.GetAclInformation(
            dacl,
            ctypes.byref(acl_information),
            ctypes.sizeof(acl_information),
            acl_size_information_class,
        ) or acl_information.ace_count != 1:
            return False
        if not advapi32.ConvertStringSidToSidW(sid, ctypes.byref(expected_sid)):
            return False
        ace_pointer = ctypes.c_void_p()
        if not advapi32.GetAce(dacl, 0, ctypes.byref(ace_pointer)):
            return False
        ace = ctypes.cast(ace_pointer, ctypes.POINTER(AccessAllowedAce)).contents
        expected_flags = object_and_container_inherit if is_directory else 0
        if (
            ace.header.ace_type != access_allowed_ace_type
            or ace.header.ace_flags & inherited_ace
            or ace.header.ace_flags != expected_flags
            or ace.mask != file_all_access
        ):
            return False
        ace_sid = ctypes.c_void_p(
            ace_pointer.value + AccessAllowedAce.sid_start.offset
        )
        return bool(advapi32.EqualSid(ace_sid, expected_sid))
    finally:
        if expected_sid.value:
            kernel32.LocalFree(expected_sid)
        if security_descriptor.value:
            kernel32.LocalFree(security_descriptor)


def _apply_private_permissions(path: Path, *, is_directory: bool) -> None:
    try:
        if os.name == "nt":
            sid = _windows_current_process_sid()
            inheritance = "(OI)(CI)" if is_directory else ""
            result = subprocess.run(
                [
                    "icacls",
                    os.fspath(path),
                    "/inheritance:r",
                    "/remove:g",
                    "*S-1-5-18",
                    "*S-1-5-32-544",
                    "*S-1-3-4",
                    "/grant:r",
                    f"*{sid}:{inheritance}F",
                ],
                check=False,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=_WINDOWS_ACL_TIMEOUT_SECONDS,
            )
            if result.returncode != 0 or not _windows_private_acl_is_valid(
                path, sid, is_directory=is_directory
            ):
                raise ProjectPackageIntegrity(_PRIVATE_PERMISSIONS_ERROR)
            return
        expected_mode = 0o700 if is_directory else 0o600
        os.chmod(path, expected_mode)
        metadata = path.lstat()
        expected_type = stat.S_ISDIR if is_directory else stat.S_ISREG
        if (
            not expected_type(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != expected_mode
            or _is_link(path)
        ):
            raise ProjectPackageIntegrity(_PRIVATE_PERMISSIONS_ERROR)
    except ProjectPackageError:
        raise
    except Exception:
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
        owned_candidates = (
            candidate for candidate in parent.iterdir() if candidate.name.startswith(TEMP_PREFIX)
        )
        for candidate in islice(owned_candidates, STALE_SCAN_LIMIT):
            examined += 1
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
                continue
        return examined
    except (OSError, RuntimeError, TypeError, ValueError):
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
            owner.cleanup()
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
