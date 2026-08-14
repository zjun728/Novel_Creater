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
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
from typing import Any

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


@dataclass(frozen=True)
class MySQLClientPair:
    mysqldump: Path
    mysql: Path
    version: str


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
        dump, dump_identity = _safe_existing_path(
            dump_path, regular_file=True, repository_root=repository_root
        )
        mysql, mysql_identity = _safe_existing_path(
            mysql_path, regular_file=True, repository_root=repository_root
        )
        dump_version = _client_semver(
            _result_output(version_runner(dump)), "mysqldump"
        )
        mysql_version = _client_semver(_result_output(version_runner(mysql)), "mysql")
        if dump_version != mysql_version:
            raise ValueError
        if not os.path.samestat(dump_identity, dump.stat()):
            raise ValueError
        if not os.path.samestat(mysql_identity, mysql.stat()):
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


def _random_owned_path(directory: Path, prefix: str, suffix: str) -> tuple[Path, int]:
    for _ in range(32):
        path = directory / f"{prefix}{secrets.token_hex(16)}{suffix}"
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            return path, descriptor
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


def _unlink_twice(path: Path | None) -> BaseException | None:
    if path is None:
        return None
    last: BaseException | None = None
    for _ in range(2):
        try:
            path.unlink(missing_ok=True)
            return None
        except BaseException as error:
            if isinstance(error, _FLOW_CONTROL):
                return error
            last = error
    return last


def _cleanup_exception(error: BaseException, message: str) -> BaseException:
    if isinstance(error, _FLOW_CONTROL):
        return error
    return _fixed(message)


def _finish_with_cleanup(
    primary: BaseException | None,
    cleanup_errors: list[BaseException],
    cleanup_message: str,
) -> None:
    clean = [_cleanup_exception(error, cleanup_message) for error in cleanup_errors]
    if primary is not None:
        if clean:
            raise BaseExceptionGroup(cleanup_message, [primary, *clean]) from None
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
) -> Iterator[Path]:
    """Yield a flushed private option file and erase it on every exit path."""

    path: Path | None = None
    descriptor: int | None = None
    handle: Any | None = None
    try:
        host, port, user, password = _validated_config(config)
        root, _ = _safe_existing_path(
            temp_root, regular_file=False, repository_root=repository_root
        )
        path, descriptor = _random_owned_path(root, ".mysql-client-", ".cnf")
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
        unlink_error = _unlink_twice(path)
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
        unlink_error = _unlink_twice(path)
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
    unlink_error = _unlink_twice(path)
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
    handle: Any | None = None
    published = False
    primary: BaseException | None = None
    cleanup: list[BaseException] = []

    try:
        temporary, descriptor = _random_owned_path(directory, ".phase7b-backup-", ".tmp")
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
        unlink_error = _unlink_twice(temporary)
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
            unlink_error = _unlink_twice(temporary)
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


def verify_backup_file(path: Path, expected_sha256: str, expected_length: int) -> None:
    """Stream and verify a non-link regular backup using fixed 64 KiB reads."""

    try:
        if type(expected_sha256) is not str or _HASH.fullmatch(expected_sha256) is None:
            raise ValueError
        if type(expected_length) is not int or expected_length < 0:
            raise ValueError
        backup_path, before = _safe_existing_path(path, regular_file=True)
        digest, length = _hash_stream(backup_path)
        after = backup_path.stat()
        if (
            not os.path.samestat(before, after)
            or length != expected_length
            or digest != expected_sha256
        ):
            raise ValueError
    except _FLOW_CONTROL:
        raise
    except BaseException:
        _raise_fixed(_VERIFY_ERROR)


def restore_logical_backup(
    pair: MySQLClientPair,
    option_file: Path,
    backup_path: Path,
    expected_sha256: str,
    expected_length: int,
    restore_database: str,
    runner: Callable[..., object] = subprocess.run,
) -> None:
    """Verify a backup and stream it to an explicit Phase 7B restore database."""

    command = restore_command(pair, option_file, restore_database)
    verify_backup_file(backup_path, expected_sha256, expected_length)
    path, _ = _safe_existing_path(backup_path, regular_file=True)
    handle: Any | None = None
    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    try:
        handle = path.open("rb")
        result = runner(
            command,
            stdin=handle,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
        if type(getattr(result, "returncode", None)) is not int or result.returncode != 0:
            raise OSError
    except _FLOW_CONTROL as error:
        primary = error
    except BaseException:
        primary = _fixed(_RESTORE_ERROR)
    finally:
        if handle is not None:
            try:
                handle.close()
            except BaseException as error:
                cleanup.append(error)
    if primary is not None or cleanup:
        _finish_with_cleanup(primary, cleanup, _RESTORE_CLEANUP_ERROR)
