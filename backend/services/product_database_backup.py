"""Private, fail-closed MySQL logical backup and restore boundaries.

All process execution and ACL changes are dependency-injected.  The narrow
``version_runner`` contract accepts a ``Path`` and returns either an exact
string output or an object with ``returncode == 0`` and a string ``stdout``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
from typing import Any

if os.name == "nt":
    import msvcrt
else:  # pragma: no cover - the product boundary deliberately fails closed off Windows.
    msvcrt = None  # type: ignore[assignment]

from backend.domain.product_database_readiness import (
    LEGACY_DATABASE,
    BackupReceipt,
    DatabaseInventory,
    ProductDatabaseReadinessError,
    ReadinessState,
    inventory_hash,
    validate_database_role,
    validate_restore_database,
)
from backend.scripts.configure_local_mysql import restrict_windows_acl


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_FLOW_CONTROL = (asyncio.CancelledError, KeyboardInterrupt, SystemExit)
_CLIENT_ERROR = "mysql client preflight failed"
_CONNECTION_ERROR = "mysql connection preflight failed"
_OPTION_ERROR = "private mysql option file failed"
_OPTION_CLEANUP_ERROR = "private mysql option file cleanup failed"
_DIRECTORY_ERROR = "backup directory preflight failed"
_BACKUP_ERROR = "logical backup failed"
_BACKUP_CLEANUP_ERROR = "logical backup cleanup failed"
_VERIFY_ERROR = "backup verification failed"
_RESTORE_ERROR = "logical restore failed"
_RESTORE_CLEANUP_ERROR = "logical restore cleanup failed"
_HASH = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SERVER_VERSION = re.compile(
    r"^8\.4\.\d+(?:[-+][0-9A-Za-z][0-9A-Za-z._-]*)?$", re.ASCII
)
_CLIENT_VERSION = re.compile(
    r"^(?:(mysqldump|mysql)(?:\.exe)?[ \t]+(?:Ver[ \t]+)?)?"
    r"(8\.4\.\d+(?:[-+][0-9A-Za-z][0-9A-Za-z._-]*)?)"
    r"(?:[ \t]+for[ \t]+[^\r\n]+)?$",
    re.ASCII | re.IGNORECASE,
)


class ProductDatabaseBackupError(RuntimeError):
    """A fixed, public-safe failure at the logical backup boundary."""


class _SafeBoundaryGroup(BaseExceptionGroup):
    """An already-sanitized operation/cleanup precedence group."""


class _OwnedDeletePending(Exception):
    pass


@dataclass(frozen=True)
class MySQLClientPair:
    mysqldump: Path
    mysql: Path
    version: str


@dataclass(frozen=True)
class _PathSnapshot:
    raw: Path
    resolved: Path
    components: tuple[tuple[Path, os.stat_result], ...]


@dataclass(frozen=True)
class _OwnedFileIdentity:
    volume_serial: int
    file_index: int


@dataclass
class _OwnedFileLease:
    identity: _OwnedFileIdentity
    handle: int | None


def _fixed(message: str) -> ProductDatabaseBackupError:
    return ProductDatabaseBackupError(message)


def _raise_fixed(message: str) -> None:
    raise _fixed(message) from None


def _is_reparse(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except (OSError, ValueError):
        return True
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & marker)


def _has_reparse_component(path: Path) -> bool:
    current = path
    while True:
        if current.is_symlink() or _is_reparse(current):
            return True
        parent = current.parent
        if parent == current:
            return False
        current = parent


def _absolute_path(value: object) -> Path:
    if isinstance(value, bool):
        raise ValueError
    path = Path(value)  # type: ignore[arg-type]
    if not path.is_absolute():
        raise ValueError
    return path


def _resolved_repository(repository_root: object) -> Path:
    root = _absolute_path(repository_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError
    return root


def _inside(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


def _safe_existing_path(
    value: object,
    *,
    regular_file: bool,
    repository_root: object | None = None,
) -> tuple[Path, os.stat_result]:
    raw = _absolute_path(value)
    before = raw.lstat()
    if _has_reparse_component(raw):
        raise ValueError
    resolved = raw.resolve(strict=True)
    after = resolved.stat()
    if not os.path.samestat(before, after):
        raise ValueError
    if regular_file:
        if not stat.S_ISREG(after.st_mode):
            raise ValueError
    elif not stat.S_ISDIR(after.st_mode):
        raise ValueError
    if repository_root is not None:
        root = _resolved_repository(repository_root)
        if _inside(resolved, root):
            raise ValueError
    return resolved, after


def _path_components(path: Path) -> tuple[Path, ...]:
    return tuple(reversed(path.parents)) + (path,)


def _capture_path_snapshot(value: object, repository_root: object) -> _PathSnapshot:
    raw = _absolute_path(value)
    components: list[tuple[Path, os.stat_result]] = []
    for component in _path_components(raw):
        identity = component.lstat()
        if component.is_symlink() or _is_reparse(component):
            raise ValueError
        components.append((component, identity))
    resolved = raw.resolve(strict=True)
    if not stat.S_ISREG(components[-1][1].st_mode):
        raise ValueError
    root = _resolved_repository(repository_root)
    if _inside(resolved, root):
        raise ValueError
    if not os.path.samestat(components[-1][1], resolved.stat()):
        raise ValueError
    return _PathSnapshot(raw, resolved, tuple(components))


def _recheck_path_snapshot(
    snapshot: _PathSnapshot, repository_root: object
) -> None:
    for component, expected in snapshot.components:
        current = component.lstat()
        if component.is_symlink() or _is_reparse(component):
            raise ValueError
        if not os.path.samestat(expected, current):
            raise ValueError
    if snapshot.raw.resolve(strict=True) != snapshot.resolved:
        raise ValueError
    if not stat.S_ISREG(snapshot.components[-1][0].lstat().st_mode):
        raise ValueError
    root = _resolved_repository(repository_root)
    if _inside(snapshot.resolved, root):
        raise ValueError


def _result_output(result: object) -> str:
    if type(result) is str:
        return result
    if type(getattr(result, "returncode", None)) is not int:
        raise ValueError
    if result.returncode != 0:  # type: ignore[attr-defined]
        raise ValueError
    output = getattr(result, "stdout", None)
    if type(output) is not str:
        raise ValueError
    return output


def _one_line(output: str) -> str:
    if type(output) is not str:
        raise ValueError
    if output.endswith("\r\n"):
        value = output[:-2]
    elif output.endswith("\n"):
        value = output[:-1]
    else:
        value = output
    if not value or "\r" in value or "\n" in value:
        raise ValueError
    return value


def _client_semver(output: str, expected_name: str) -> str:
    match = _CLIENT_VERSION.fullmatch(_one_line(output))
    if match is None:
        raise ValueError
    reported_name, version = match.groups()
    if reported_name is not None and reported_name.lower() != expected_name:
        raise ValueError
    return version


def preflight_client_pair(
    dump_path: Path,
    mysql_path: Path,
    repository_root: Path,
    version_runner: Callable[[Path], object],
) -> MySQLClientPair:
    """Validate explicit, repository-external and exactly matched MySQL 8.4 clients."""

    try:
        dump_snapshot = _capture_path_snapshot(dump_path, repository_root)
        mysql_snapshot = _capture_path_snapshot(mysql_path, repository_root)
        dump = dump_snapshot.resolved
        mysql = mysql_snapshot.resolved
        dump_result = version_runner(dump)
        _recheck_path_snapshot(dump_snapshot, repository_root)
        _recheck_path_snapshot(mysql_snapshot, repository_root)
        dump_version = _client_semver(_result_output(dump_result), "mysqldump")
        mysql_result = version_runner(mysql)
        _recheck_path_snapshot(dump_snapshot, repository_root)
        _recheck_path_snapshot(mysql_snapshot, repository_root)
        mysql_version = _client_semver(_result_output(mysql_result), "mysql")
        if dump_version != mysql_version:
            raise ValueError
        return MySQLClientPair(dump, mysql, dump_version)
    except _FLOW_CONTROL:
        raise
    except BaseException:
        _raise_fixed(_CLIENT_ERROR)


def _validated_pair(pair: object) -> MySQLClientPair:
    if type(pair) is not MySQLClientPair:
        raise ValueError
    if type(pair.version) is not str or _SERVER_VERSION.fullmatch(pair.version) is None:
        raise ValueError
    dump, _ = _safe_existing_path(pair.mysqldump, regular_file=True)
    mysql, _ = _safe_existing_path(pair.mysql, regular_file=True)
    if dump != pair.mysqldump.resolve() or mysql != pair.mysql.resolve():
        raise ValueError
    return pair


def _validated_option_file(option_file: object) -> Path:
    path, _ = _safe_existing_path(option_file, regular_file=True)
    return path


def dump_command(
    pair: MySQLClientPair, option_file: Path, database: str
) -> list[str]:
    database = validate_database_role("legacy", database)
    try:
        pair = _validated_pair(pair)
        option = _validated_option_file(option_file)
    except _FLOW_CONTROL:
        raise
    except BaseException:
        _raise_fixed(_CLIENT_ERROR)
    return [
        str(pair.mysqldump),
        f"--defaults-extra-file={option}",
        "--protocol=TCP",
        "--single-transaction",
        "--quick",
        "--hex-blob",
        "--routines",
        "--events",
        "--triggers",
        "--set-gtid-purged=OFF",
        "--skip-add-locks",
        "--skip-lock-tables",
        database,
    ]


def restore_command(
    pair: MySQLClientPair, option_file: Path, database: str
) -> list[str]:
    database = validate_restore_database(database)
    try:
        pair = _validated_pair(pair)
        option = _validated_option_file(option_file)
    except _FLOW_CONTROL:
        raise
    except BaseException:
        _raise_fixed(_CLIENT_ERROR)
    return [
        str(pair.mysql),
        f"--defaults-extra-file={option}",
        "--protocol=TCP",
        "--binary-mode=1",
        database,
    ]


def preflight_client_connection(
    pair: MySQLClientPair,
    option_file: Path,
    runner: Callable[..., object],
) -> str:
    """Run only ``SELECT VERSION()`` through the selected explicit mysql client."""

    try:
        pair = _validated_pair(pair)
        option = _validated_option_file(option_file)
        result = runner(
            [
                str(pair.mysql),
                f"--defaults-extra-file={option}",
                "--protocol=TCP",
                "--batch",
                "--skip-column-names",
                "--execute=SELECT VERSION()",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        output = _one_line(_result_output(result))
        if _SERVER_VERSION.fullmatch(output) is None:
            raise ValueError
        return output
    except _FLOW_CONTROL:
        raise
    except BaseException:
        _raise_fixed(_CONNECTION_ERROR)


def _validated_config(config: object) -> tuple[str, int, str, str]:
    if not isinstance(config, Mapping):
        raise ValueError
    lower = frozenset(("host", "port", "user", "password"))
    upper = frozenset(("MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD"))
    keys = frozenset(config)
    if keys == lower:
        values = tuple(config[key] for key in ("host", "port", "user", "password"))
    elif keys == upper:
        values = tuple(
            config[key] for key in ("MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD")
        )
    else:
        raise ValueError
    host, port, user, password = values
    for value in (host, user, password):
        if type(value) is not str or not value or any(mark in value for mark in ("\x00", "\r", "\n")):
            raise ValueError
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError
    return host, port, user, password


def _quote_option(value: str) -> str:
    escaped = "".join(("\\" + char) if char in '\\"#;=' else char for char in value)
    return f'"{escaped}"'


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


class _FileDispositionInformation(ctypes.Structure):
    _fields_ = [("DeleteFile", wintypes.BOOL)]


def _kernel32() -> object:
    if os.name != "nt":
        raise OSError
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _identity_from_handle(handle: int) -> _OwnedFileIdentity:
    kernel32 = _kernel32()
    information = _ByHandleFileInformation()
    getter = kernel32.GetFileInformationByHandle  # type: ignore[attr-defined]
    getter.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ByHandleFileInformation)]
    getter.restype = wintypes.BOOL
    if not getter(wintypes.HANDLE(handle), ctypes.byref(information)):
        raise OSError
    return _OwnedFileIdentity(
        int(information.dwVolumeSerialNumber),
        (int(information.nFileIndexHigh) << 32) | int(information.nFileIndexLow),
    )


def _link_count_from_handle(handle: int) -> int:
    kernel32 = _kernel32()
    information = _ByHandleFileInformation()
    getter = kernel32.GetFileInformationByHandle  # type: ignore[attr-defined]
    getter.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ByHandleFileInformation)]
    getter.restype = wintypes.BOOL
    if not getter(wintypes.HANDLE(handle), ctypes.byref(information)):
        raise OSError
    return int(information.nNumberOfLinks)


def _identity_from_fd(descriptor: int) -> _OwnedFileIdentity:
    if msvcrt is None:
        raise OSError
    return _identity_from_handle(msvcrt.get_osfhandle(descriptor))


def _set_delete_disposition(handle: int) -> None:
    kernel32 = _kernel32()
    disposition = _FileDispositionInformation(True)
    setter = kernel32.SetFileInformationByHandle  # type: ignore[attr-defined]
    setter.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    setter.restype = wintypes.BOOL
    if not setter(
        wintypes.HANDLE(handle),
        4,
        ctypes.byref(disposition),
        ctypes.sizeof(disposition),
    ):
        raise OSError


def _close_windows_handle(handle: int) -> None:
    kernel32 = _kernel32()
    close = kernel32.CloseHandle  # type: ignore[attr-defined]
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    if not close(wintypes.HANDLE(handle)):
        raise OSError


def _reopen_exact_windows(handle: int, desired_access: int) -> int:
    kernel32 = _kernel32()
    reopen = kernel32.ReOpenFile  # type: ignore[attr-defined]
    reopen.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    reopen.restype = wintypes.HANDLE
    reopened = reopen(
        wintypes.HANDLE(handle),
        desired_access,
        0x00000001 | 0x00000002 | 0x00000004,
        0x00200000,
    )
    if reopened == ctypes.c_void_p(-1).value:
        if ctypes.get_last_error() == 303:
            raise _OwnedDeletePending
        raise OSError
    return int(reopened)


def _delete_from_owner_handle(owner_handle: int) -> None:
    deletion_handle = _reopen_exact_windows(
        owner_handle, 0x00010000 | 0x00000080
    )
    try:
        _set_delete_disposition(deletion_handle)
    finally:
        _close_windows_handle(deletion_handle)


def _create_owned_windows(path: Path) -> tuple[int, _OwnedFileLease]:
    if msvcrt is None:
        raise OSError
    kernel32 = _kernel32()
    creator = kernel32.CreateFileW  # type: ignore[attr-defined]
    creator.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    creator.restype = wintypes.HANDLE
    handle = creator(
        str(path),
        0x40000000 | 0x00000080,
        0x00000001 | 0x00000002 | 0x00000004,
        None,
        1,
        0x00000080 | 0x00200000,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle == invalid:
        if ctypes.get_last_error() in (80, 183):
            raise FileExistsError
        raise OSError
    creation_handle = int(handle)
    owner_handle: int | None = None
    descriptor: int | None = None
    try:
        identity = _identity_from_handle(creation_handle)
        owner_handle = _reopen_exact_windows(creation_handle, 0x00000080)
        descriptor = msvcrt.open_osfhandle(
            creation_handle, os.O_WRONLY | getattr(os, "O_BINARY", 0)
        )
        creation_handle = -1
        return descriptor, _OwnedFileLease(identity, owner_handle)
    except BaseException:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except BaseException:
                pass
        elif creation_handle != -1:
            try:
                _delete_from_owner_handle(creation_handle)
            finally:
                _close_windows_handle(creation_handle)
        if owner_handle is not None:
            _close_windows_handle(owner_handle)
        raise


def _delete_owned_windows(path: Path, lease: _OwnedFileLease) -> bool:
    del path
    handle = lease.handle
    if handle is None:
        return True
    if _identity_from_handle(handle) != lease.identity:
        raise OSError
    if _link_count_from_handle(handle) != 0:
        try:
            _delete_from_owner_handle(handle)
        except _OwnedDeletePending:
            pass
    _close_windows_handle(handle)
    lease.handle = None
    return True


def _random_owned_path(
    directory: Path, prefix: str, suffix: str
) -> tuple[Path, int, _OwnedFileLease]:
    for _ in range(32):
        path = directory / f"{prefix}{secrets.token_hex(16)}{suffix}"
        try:
            descriptor, lease = _create_owned_windows(path)
            return path, descriptor, lease
        except FileExistsError:
            continue
    raise OSError


def _same_owned_file(path: Path, descriptor: int) -> bool:
    try:
        current = path.lstat()
        return (
            not _has_reparse_component(path)
            and stat.S_ISREG(current.st_mode)
            and os.path.samestat(os.fstat(descriptor), current)
        )
    except (OSError, ValueError):
        return False


def _delete_owned_twice(
    path: Path | None,
    lease: _OwnedFileLease | None,
    owned_delete: Callable[[Path, _OwnedFileLease], bool],
) -> BaseException | None:
    if path is None or lease is None:
        return None
    last: BaseException | None = None
    for _ in range(2):
        try:
            if owned_delete(path, lease) is True:
                if lease.handle is not None:
                    _delete_owned_windows(path, lease)
                return None
            last = OSError()
        except BaseException as error:
            if isinstance(error, _FLOW_CONTROL):
                try:
                    if lease.handle is not None:
                        _delete_owned_windows(path, lease)
                except BaseException as cleanup_error:
                    return BaseExceptionGroup(
                        "owned file cleanup failed", [error, cleanup_error]
                    )
                return error
            last = error
    try:
        if lease.handle is not None:
            _delete_owned_windows(path, lease)
    except BaseException as cleanup_error:
        if last is None:
            return cleanup_error
        return BaseExceptionGroup("owned file cleanup failed", [last, cleanup_error])
    return last


def _cleanup_exception(error: BaseException, message: str) -> BaseException:
    if _contains_flow_control(error):
        return error
    return _fixed(message)


def _contains_flow_control(error: BaseException) -> bool:
    if isinstance(error, _FLOW_CONTROL):
        return True
    if isinstance(error, BaseExceptionGroup):
        return any(_contains_flow_control(nested) for nested in error.exceptions)
    return False


def _finish_with_cleanup(
    primary: BaseException | None,
    cleanup_errors: list[BaseException],
    cleanup_message: str,
    *,
    group_message: str | None = None,
    safe_group: bool = False,
) -> None:
    clean = [_cleanup_exception(error, cleanup_message) for error in cleanup_errors]
    if primary is not None:
        if clean:
            group_type = _SafeBoundaryGroup if safe_group else BaseExceptionGroup
            raise group_type(
                group_message or cleanup_message, [primary, *clean]
            ) from None
        raise primary from None
    if len(clean) == 1:
        raise clean[0] from None
    if clean:
        raise BaseExceptionGroup(cleanup_message, clean) from None


@contextmanager
def private_mysql_option_file(
    config: Mapping[str, object],
    temp_root: Path,
    acl_runner: Callable[[Path], None] = restrict_windows_acl,
    *,
    repository_root: Path | None = None,
    owned_delete: Callable[[Path, _OwnedFileLease], bool] = _delete_owned_windows,
) -> Iterator[Path]:
    """Yield a flushed private option file and erase it on every exit path."""

    path: Path | None = None
    descriptor: int | None = None
    lease: _OwnedFileLease | None = None
    handle: Any | None = None
    try:
        host, port, user, password = _validated_config(config)
        root, _ = _safe_existing_path(
            temp_root, regular_file=False, repository_root=repository_root
        )
        path, descriptor, lease = _random_owned_path(root, ".mysql-client-", ".cnf")
        acl_runner(path)
        if not _same_owned_file(path, descriptor):
            raise OSError
        handle = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n", closefd=True)
        descriptor = None
        handle.write(
            "[client]\n"
            f"host={_quote_option(host)}\n"
            f"port={port}\n"
            f"user={_quote_option(user)}\n"
            f"password={_quote_option(password)}\n"
            'default-character-set="utf8mb4"\n'
        )
        handle.flush()
        os.fsync(handle.fileno())
        closing_handle = handle
        handle = None
        closing_handle.close()
    except _FLOW_CONTROL as error:
        cleanup: list[BaseException] = []
        if handle is not None:
            try:
                handle.close()
            except BaseException as close_error:
                cleanup.append(close_error)
        elif descriptor is not None:
            try:
                os.close(descriptor)
            except BaseException as close_error:
                cleanup.append(close_error)
        unlink_error = _delete_owned_twice(path, lease, owned_delete)
        if unlink_error is not None:
            cleanup.append(unlink_error)
        _finish_with_cleanup(error, cleanup, _OPTION_CLEANUP_ERROR)
        raise AssertionError("unreachable")
    except BaseException:
        cleanup = []
        if handle is not None:
            try:
                handle.close()
            except BaseException as close_error:
                cleanup.append(close_error)
        elif descriptor is not None:
            try:
                os.close(descriptor)
            except BaseException as close_error:
                cleanup.append(close_error)
        unlink_error = _delete_owned_twice(path, lease, owned_delete)
        if unlink_error is not None:
            cleanup.append(unlink_error)
        _finish_with_cleanup(_fixed(_OPTION_ERROR), cleanup, _OPTION_CLEANUP_ERROR)
        raise AssertionError("unreachable")

    primary: BaseException | None = None
    try:
        assert path is not None
        yield path
    except BaseException as error:
        primary = error
    cleanup = []
    unlink_error = _delete_owned_twice(path, lease, owned_delete)
    if unlink_error is not None:
        cleanup.append(unlink_error)
    if primary is not None or cleanup:
        _finish_with_cleanup(primary, cleanup, _OPTION_CLEANUP_ERROR)


def preflight_backup_directory(
    backup_dir: Path,
    repository_root: Path,
    acl_runner: Callable[[Path], None] = restrict_windows_acl,
) -> Path:
    """Validate and restrict an explicit repository-external backup directory."""

    try:
        directory, identity = _safe_existing_path(
            backup_dir, regular_file=False, repository_root=repository_root
        )
        acl_runner(directory)
        checked, after = _safe_existing_path(
            directory, regular_file=False, repository_root=repository_root
        )
        if checked != directory or not os.path.samestat(identity, after):
            raise ValueError
        return directory
    except _FLOW_CONTROL:
        raise
    except BaseException:
        _raise_fixed(_DIRECTORY_ERROR)


def _source_hash(
    source_inventory: DatabaseInventory | str | None,
    supplied_hash: str | None,
    source_database: str,
) -> str:
    validate_database_role("legacy", source_database)
    if type(source_inventory) is DatabaseInventory:
        validate_database_role("legacy", source_inventory.database)
        calculated = inventory_hash(source_inventory)
        if supplied_hash is not None and supplied_hash != calculated:
            raise ValueError
        return calculated
    if type(source_inventory) is str and supplied_hash is None:
        supplied_hash = source_inventory
    if source_inventory is not None and type(source_inventory) is not str:
        raise ValueError
    if type(supplied_hash) is not str or _HASH.fullmatch(supplied_hash) is None:
        raise ValueError
    return supplied_hash


def _validate_receipt_inputs(filename: object, previous_hash: object) -> str:
    if type(filename) is not str or type(previous_hash) is not str:
        raise ValueError
    BackupReceipt(
        state=ReadinessState.BACKUP_CREATED.value,
        previous_receipt_hash=previous_hash,
        source_database=LEGACY_DATABASE,
        backup_filename=filename,
        backup_sha256="0" * 64,
        backup_byte_length=0,
        client_version="8.4.0",
        source_inventory_hash="0" * 64,
    )
    return filename


def _hash_stream(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    length = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(64 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            length += len(chunk)
    return digest.hexdigest(), length


def create_logical_backup(
    pair: MySQLClientPair,
    option_file: Path,
    source_inventory: DatabaseInventory | str | None = None,
    backup_dir: Path | None = None,
    backup_filename: str | None = None,
    previous_receipt_hash: str | None = None,
    runner: Callable[..., object] = subprocess.run,
    acl_runner: Callable[[Path], None] = restrict_windows_acl,
    *,
    source_inventory_hash: str | None = None,
    source_database: str = LEGACY_DATABASE,
    repository_root: Path = REPOSITORY_ROOT,
    owned_delete: Callable[[Path, _OwnedFileLease], bool] = _delete_owned_windows,
) -> BackupReceipt:
    """Create and absent-only publish a private logical backup."""

    try:
        pair = _validated_pair(pair)
        option = _validated_option_file(option_file)
        filename = _validate_receipt_inputs(backup_filename, previous_receipt_hash)
        source_hash = _source_hash(source_inventory, source_inventory_hash, source_database)
        if backup_dir is None:
            raise ValueError
    except _FLOW_CONTROL:
        raise
    except ProductDatabaseReadinessError:
        _raise_fixed(_BACKUP_ERROR)
    except BaseException:
        _raise_fixed(_BACKUP_ERROR)

    # Capability failure must occur before any backup file is created.
    preflight_client_connection(pair, option, runner)
    directory = preflight_backup_directory(backup_dir, repository_root, acl_runner)
    final = directory / filename
    temporary: Path | None = None
    descriptor: int | None = None
    lease: _OwnedFileLease | None = None
    handle: Any | None = None
    published = False
    primary: BaseException | None = None
    cleanup: list[BaseException] = []

    try:
        temporary, descriptor, lease = _random_owned_path(
            directory, ".phase7b-backup-", ".tmp"
        )
        acl_runner(temporary)
        if not _same_owned_file(temporary, descriptor):
            raise OSError
        handle = os.fdopen(descriptor, "wb", closefd=True)
        descriptor = None
        result = runner(
            dump_command(pair, option, source_database),
            stdout=handle,
            stderr=subprocess.PIPE,
            check=False,
        )
        if type(getattr(result, "returncode", None)) is not int or result.returncode != 0:
            raise OSError
        handle.flush()
        os.fsync(handle.fileno())
        closing_handle = handle
        handle = None
        closing_handle.close()
        if temporary.stat().st_size <= 0:
            raise OSError
        digest, length = _hash_stream(temporary)
        if length <= 0:
            raise OSError
        os.link(temporary, final)
        published = True
        unlink_error = _delete_owned_twice(temporary, lease, owned_delete)
        if unlink_error is not None:
            cleanup.append(unlink_error)
        else:
            temporary = None
    except _FLOW_CONTROL as error:
        primary = error
    except BaseException:
        primary = _fixed(_BACKUP_ERROR)
    finally:
        if handle is not None:
            try:
                handle.close()
            except BaseException as error:
                cleanup.append(error)
        elif descriptor is not None:
            try:
                os.close(descriptor)
            except BaseException as error:
                cleanup.append(error)
        if temporary is not None and not published:
            unlink_error = _delete_owned_twice(temporary, lease, owned_delete)
            if unlink_error is not None:
                cleanup.append(unlink_error)

    if primary is not None or cleanup:
        _finish_with_cleanup(primary, cleanup, _BACKUP_CLEANUP_ERROR)

    try:
        return BackupReceipt(
            state=ReadinessState.BACKUP_CREATED.value,
            previous_receipt_hash=previous_receipt_hash,  # type: ignore[arg-type]
            source_database=source_database,
            backup_filename=filename,
            backup_sha256=digest,
            backup_byte_length=length,
            client_version=pair.version,
            source_inventory_hash=source_hash,
        )
    except _FLOW_CONTROL:
        raise
    except BaseException:
        _raise_fixed(_BACKUP_ERROR)


def _validate_expected_backup(expected_sha256: object, expected_length: object) -> None:
    if type(expected_sha256) is not str or _HASH.fullmatch(expected_sha256) is None:
        raise ValueError
    if type(expected_length) is not int or expected_length < 0:
        raise ValueError


def _hash_handle(handle: object) -> tuple[str, int]:
    digest = hashlib.sha256()
    length = 0
    while True:
        chunk = handle.read(64 * 1024)  # type: ignore[attr-defined]
        if not chunk:
            break
        if type(chunk) is not bytes:
            raise OSError
        digest.update(chunk)
        length += len(chunk)
    return digest.hexdigest(), length


def _open_verified_backup(
    path: Path,
    expected_sha256: str,
    expected_length: int,
    *,
    error_message: str,
) -> tuple[Path, object]:
    handle: object | None = None
    try:
        _validate_expected_backup(expected_sha256, expected_length)
        raw = _absolute_path(path)
        components: list[tuple[Path, os.stat_result]] = []
        for component in _path_components(raw):
            observed = component.lstat()
            if component.is_symlink() or _is_reparse(component):
                raise OSError
            components.append((component, observed))
        if not stat.S_ISREG(components[-1][1].st_mode):
            raise OSError
        handle = raw.open("rb")
        opened = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(opened.st_mode)
            or not os.path.samestat(components[-1][1], opened)
        ):
            raise OSError
        for component, expected in components[:-1]:
            current = component.lstat()
            if component.is_symlink() or _is_reparse(component):
                raise OSError
            if not os.path.samestat(expected, current):
                raise OSError
        digest, length = _hash_handle(handle)
        if digest != expected_sha256 or length != expected_length:
            raise OSError
        handle.seek(0)
        return raw, handle
    except BaseException as error:
        primary = error if _contains_flow_control(error) else _fixed(error_message)
        cleanup: list[BaseException] = []
        if handle is not None:
            closing_handle = handle
            handle = None
            try:
                closing_handle.close()  # type: ignore[attr-defined]
            except BaseException as close_error:
                cleanup.append(close_error)
        cleanup_message = (
            _RESTORE_CLEANUP_ERROR
            if error_message == _RESTORE_ERROR
            else error_message
        )
        _finish_with_cleanup(
            primary,
            cleanup,
            cleanup_message,
            group_message=error_message,
            safe_group=error_message == _RESTORE_ERROR,
        )
        raise AssertionError("unreachable")


def verify_backup_file(path: Path, expected_sha256: str, expected_length: int) -> None:
    """Open once and verify a non-link regular backup using fixed 64 KiB reads."""

    handle: object | None = None
    try:
        _path, handle = _open_verified_backup(
            path,
            expected_sha256,
            expected_length,
            error_message=_VERIFY_ERROR,
        )
        closing_handle = handle
        handle = None
        closing_handle.close()  # type: ignore[attr-defined]
    except BaseException as error:
        if _contains_flow_control(error):
            raise
        _raise_fixed(_VERIFY_ERROR)


def restore_logical_backup(
    pair: MySQLClientPair,
    option_file: Path,
    backup_path: Path,
    expected_sha256: str,
    expected_length: int,
    restore_database: str,
    runner: Callable[..., object] = subprocess.run,
    *,
    after_verification: Callable[[Path, object], None] | None = None,
) -> None:
    """Verify a backup and stream it to an explicit Phase 7B restore database."""

    command = restore_command(pair, option_file, restore_database)
    handle: Any | None = None
    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    try:
        path, handle = _open_verified_backup(
            backup_path,
            expected_sha256,
            expected_length,
            error_message=_RESTORE_ERROR,
        )
        if after_verification is not None:
            after_verification(path, handle)
        result = runner(
            command,
            stdin=handle,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
        if type(getattr(result, "returncode", None)) is not int or result.returncode != 0:
            raise OSError
    except BaseException as error:
        primary = (
            error
            if isinstance(error, _SafeBoundaryGroup) or _contains_flow_control(error)
            else _fixed(_RESTORE_ERROR)
        )
    finally:
        if handle is not None:
            try:
                handle.close()
            except BaseException as error:
                cleanup.append(error)
    if primary is not None or cleanup:
        _finish_with_cleanup(
            primary,
            cleanup,
            _RESTORE_CLEANUP_ERROR,
            group_message=_RESTORE_ERROR,
        )
