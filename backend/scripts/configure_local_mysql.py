"""Validate and atomically publish private local MySQL access settings."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Awaitable, Callable, Mapping, Sequence

from backend.scripts.initialize_database import _default_connection_factory


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOCAL_CONFIG_PATH = REPOSITORY_ROOT / ".env.local.json"
_CONFIG_KEYS = frozenset({
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DB",
})
_OPTIONAL_CONFIG_KEYS = frozenset({"CORPUS_ROOT", "MANAGED_CORPUS_ROOT"})
_PUBLICATION_ERROR = "Could not atomically save the local MySQL configuration"
_PUBLICATION_CLEANUP_ERROR = "Could not remove an unpublished local configuration"


class LocalMySQLSetupError(RuntimeError):
    """Local MySQL settings could not be verified and published safely."""


@dataclass(frozen=True)
class LocalDocumentSnapshot:
    """Exact path owner and byte content used by compare-and-swap writes."""

    path: Path
    identity: tuple[int, int]
    content: bytes


def _snapshot_identity(value: object) -> tuple[int, int]:
    mode = getattr(value, "st_mode", None)
    attributes = getattr(value, "st_file_attributes", 0)
    identity = (
        getattr(value, "st_dev", None),
        getattr(value, "st_ino", None),
    )
    if (
        type(mode) is not int
        or not stat.S_ISREG(mode)
        or type(attributes) is not int
        or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        or any(type(item) is not int for item in identity)
    ):
        raise OSError
    return identity  # type: ignore[return-value]


def capture_local_document_snapshot(target: Path) -> LocalDocumentSnapshot:
    """Open once and bind an exact regular non-link configuration snapshot."""
    try:
        path = Path(target).absolute()
        before = path.lstat()
        if path.is_symlink():
            raise OSError
        path_identity = _snapshot_identity(before)
        with path.open("rb") as handle:
            opened = _snapshot_identity(os.fstat(handle.fileno()))
            if opened != path_identity:
                raise OSError
            content = handle.read()
            if _snapshot_identity(os.fstat(handle.fileno())) != opened:
                raise OSError
        if _snapshot_identity(path.lstat()) != path_identity:
            raise OSError
        return LocalDocumentSnapshot(path, path_identity, content)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
            raise
        raise LocalMySQLSetupError("Local MySQL configuration changed") from None


def _snapshot_is_current(target: Path, expected: LocalDocumentSnapshot) -> bool:
    try:
        current = capture_local_document_snapshot(target)
    except LocalMySQLSetupError:
        return False
    return current == expected


@dataclass(frozen=True)
class WindowsMutexAPI:
    """Injectable Win32 named-mutex calls used by the publication boundary."""

    create_mutex: Callable[[str], object]
    wait: Callable[[object], int]
    release: Callable[[object], bool]
    close: Callable[[object], bool]


def _local_config_mutex_name(target: Path) -> str:
    normalized = os.path.normcase(os.path.normpath(str(Path(target).absolute())))
    return (
        "Local\\NovelCreator.Phase7B.Config."
        + hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    )


def _default_windows_mutex_api() -> WindowsMutexAPI:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel32.CreateMutexW
    create.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    create.restype = wintypes.HANDLE
    wait = kernel32.WaitForSingleObject
    wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait.restype = wintypes.DWORD
    release = kernel32.ReleaseMutex
    release.argtypes = [wintypes.HANDLE]
    release.restype = wintypes.BOOL
    close = kernel32.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    return WindowsMutexAPI(
        create_mutex=lambda name: create(None, False, name),
        wait=lambda handle: int(wait(handle, 0)),
        release=lambda handle: bool(release(handle)),
        close=lambda handle: bool(close(handle)),
    )


def _fixed_mutex_call(
    operation: Callable[..., object], message: str, *args: object
) -> object:
    try:
        return operation(*args)
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        raise LocalMySQLSetupError(message) from None


def _sanitized_publication_error(error: BaseException, message: str) -> BaseException:
    if isinstance(error, BaseExceptionGroup):
        return BaseExceptionGroup(
            message,
            [_sanitized_publication_error(child, message) for child in error.exceptions],
        )
    if isinstance(error, asyncio.CancelledError):
        return asyncio.CancelledError()
    if isinstance(error, KeyboardInterrupt):
        return KeyboardInterrupt()
    if isinstance(error, SystemExit):
        return SystemExit(error.code) if type(error.code) is int else SystemExit()
    if (
        message == _PUBLICATION_ERROR
        and type(error) is LocalMySQLSetupError
        and str(error) == "Local MySQL configuration changed"
    ):
        return LocalMySQLSetupError("Local MySQL configuration changed")
    return LocalMySQLSetupError(message)


def _raise_publication_failures(
    primary: BaseException | None,
    cleanup: list[BaseException],
) -> None:
    """Raise fixed publication failures without allowing cleanup to hide primary."""
    clean_primary = (
        None
        if primary is None
        else _sanitized_publication_error(primary, _PUBLICATION_ERROR)
    )
    clean_cleanup = [
        _sanitized_publication_error(error, _PUBLICATION_CLEANUP_ERROR)
        for error in cleanup
    ]
    if clean_primary is not None and clean_cleanup:
        cleanup_error: BaseException = (
            clean_cleanup[0]
            if len(clean_cleanup) == 1
            else BaseExceptionGroup(_PUBLICATION_CLEANUP_ERROR, clean_cleanup)
        )
        raise BaseExceptionGroup(
            _PUBLICATION_ERROR,
            [clean_primary, cleanup_error],
        ) from None
    if clean_primary is not None:
        raise clean_primary from None
    if clean_cleanup:
        if len(clean_cleanup) == 1:
            raise clean_cleanup[0] from None
        raise BaseExceptionGroup(_PUBLICATION_CLEANUP_ERROR, clean_cleanup) from None


def _remove_local_temporary(path: Path) -> None:
    path.unlink(missing_ok=True)


@contextmanager
def _windows_local_config_mutex(
    target: Path,
    *,
    platform_name: str = os.name,
    api: WindowsMutexAPI | object | None = None,
):  # type: ignore[no-untyped-def]
    """Serialize repository-supported administrative writers.

    An uncooperative direct filesystem editor does not participate in this mutex;
    compare-and-swap writers detect it at their pre/post-publication boundaries.
    """
    if platform_name != "nt":
        raise LocalMySQLSetupError("Windows configuration publication is required")
    selected = api or _default_windows_mutex_api()
    create = getattr(selected, "create_mutex", None)
    wait = getattr(selected, "wait", None)
    release = getattr(selected, "release", None)
    close = getattr(selected, "close", None)
    if not all(callable(item) for item in (create, wait, release, close)):
        raise LocalMySQLSetupError("Could not lock local MySQL configuration")

    handle: object | None = None
    acquired = False
    primary: BaseException | None = None
    primary_traceback: object | None = None
    try:
        handle = _fixed_mutex_call(
            create,  # type: ignore[arg-type]
            "Could not lock local MySQL configuration",
            _local_config_mutex_name(target),
        )
        if not handle:
            raise LocalMySQLSetupError("Could not lock local MySQL configuration")
        result = _fixed_mutex_call(
            wait,  # type: ignore[arg-type]
            "Could not lock local MySQL configuration",
            handle,
        )
        if type(result) is not int:
            raise LocalMySQLSetupError("Could not lock local MySQL configuration")
        if result == 0x00000080:
            acquired = True
            raise LocalMySQLSetupError("Local MySQL configuration lock was abandoned")
        if result != 0x00000000:
            raise LocalMySQLSetupError("Local MySQL configuration is locked")
        acquired = True
        yield
    except BaseException as error:
        primary = error
        primary_traceback = error.__traceback__
    finally:
        cleanup: list[BaseException] = []
        if acquired and handle is not None:
            try:
                released = _fixed_mutex_call(
                    release,  # type: ignore[arg-type]
                    "Could not unlock local MySQL configuration",
                    handle,
                )
                if released is not True:
                    raise LocalMySQLSetupError(
                        "Could not unlock local MySQL configuration"
                    )
            except BaseException as error:
                cleanup.append(error)
        if handle is not None:
            try:
                closed = _fixed_mutex_call(
                    close,  # type: ignore[arg-type]
                    "Could not close local MySQL configuration lock",
                    handle,
                )
                if closed is not True:
                    raise LocalMySQLSetupError(
                        "Could not close local MySQL configuration lock"
                    )
            except BaseException as error:
                cleanup.append(error)
        if primary is not None and cleanup:
            raise BaseExceptionGroup(
                "Local MySQL configuration publication failed",
                [primary, *cleanup],
            ) from None
        if primary is not None:
            raise primary.with_traceback(primary_traceback) from None  # type: ignore[arg-type]
        if cleanup:
            if len(cleanup) == 1:
                raise cleanup[0] from None
            raise BaseExceptionGroup(
                "Local MySQL configuration lock cleanup failed", cleanup
            ) from None


async def _verify_server_capabilities(session) -> str:
    version_row = await session.fetchone("SELECT VERSION() AS version")
    version = (version_row or {}).get("version")
    if type(version) is not str:
        raise LocalMySQLSetupError("Could not verify the MySQL server version")
    match = re.fullmatch(
        r"(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z][0-9A-Za-z._-]*)?",
        version,
    )
    if match is None:
        raise LocalMySQLSetupError("Could not verify the MySQL server version")
    version_tuple = tuple(int(part) for part in match.groups())
    if version_tuple < (8, 0, 16) or version_tuple >= (9, 0, 0):
        raise LocalMySQLSetupError(
            "Local Writer Core requires MySQL 8.0.16 or newer, below MySQL 9"
        )
    collation = await session.fetchone(
        """SELECT COLLATION_NAME FROM information_schema.COLLATIONS
           WHERE COLLATION_NAME='utf8mb4_0900_ai_ci'"""
    )
    if (collation or {}).get("COLLATION_NAME") != "utf8mb4_0900_ai_ci":
        raise LocalMySQLSetupError(
            "MySQL server does not provide required utf8mb4_0900_ai_ci collation"
        )
    json_support = await session.fetchone(
        "SELECT JSON_VALID(%s) AS json_supported",
        ('{"writerCore":true}',),
    )
    json_supported = (json_support or {}).get("json_supported")
    if type(json_supported) is not int or json_supported != 1:
        raise LocalMySQLSetupError("MySQL server JSON capability check failed")
    check_support = await session.fetchone(
        "SELECT COUNT(*) AS count FROM information_schema.CHECK_CONSTRAINTS"
    )
    if type((check_support or {}).get("count")) is not int:
        raise LocalMySQLSetupError("MySQL server CHECK capability check failed")
    return version


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and save private local MySQL 8 settings"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=_port, default=3307)
    parser.add_argument("--user", default="root")
    parser.add_argument("--database", default="novel_creator")
    return parser


def restrict_windows_acl(
    path: Path,
    *,
    runner: Callable[..., object] = subprocess.run,
    username: str | None = None,
) -> None:
    """Remove inherited access and grant only the current user read/write access."""
    if os.name != "nt":
        raise LocalMySQLSetupError("Windows file permissions are required")
    account = username or getpass.getuser()
    if not account:
        raise LocalMySQLSetupError("Could not determine the current Windows user")
    result = runner(
        [
            "icacls",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"{account}:(R,W)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if getattr(result, "returncode", 1) != 0:
        raise LocalMySQLSetupError("Could not restrict local configuration permissions")


def _atomic_write_local_document_locked(
    target: Path,
    document: Mapping[str, object],
    acl_runner: Callable[[Path], None],
    remove_temp: Callable[[Path], None],
    replacer: Callable[[Path, Path], None],
) -> None:
    """Atomically publish the exact MySQL document and existing corpus fields."""
    target = Path(target)
    keys = set(document)
    if not _CONFIG_KEYS <= keys or not keys <= _CONFIG_KEYS | _OPTIONAL_CONFIG_KEYS:
        raise LocalMySQLSetupError(
            "Local MySQL document must contain required and allowed keys only"
        )

    temporary_path: Path | None = None
    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".env.local.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
        acl_runner(temporary_path)
        with temporary_path.open(
            mode="w",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            json.dump(
                dict(document),
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        replacer(temporary_path, target)
        temporary_path = None
    except BaseException as error:
        primary = error
    finally:
        if temporary_path is not None:
            try:
                remove_temp(temporary_path)
            except BaseException as error:
                cleanup.append(error)
    _raise_publication_failures(primary, cleanup)


def atomic_write_local_document(
    target: Path,
    document: Mapping[str, object],
    acl_runner: Callable[[Path], None],
    *,
    mutex_api: WindowsMutexAPI | object | None = None,
    platform_name: str = os.name,
    remove_temp: Callable[[Path], None] = _remove_local_temporary,
    replacer: Callable[[Path, Path], None] = os.replace,
) -> None:
    """Publish under the shared Windows owner-bound configuration mutex."""
    with _windows_local_config_mutex(
        Path(target), platform_name=platform_name, api=mutex_api
    ):
        _atomic_write_local_document_locked(
            target, document, acl_runner, remove_temp, replacer
        )


def _atomic_compare_and_swap_local_document_locked(
    target: Path,
    document: Mapping[str, object],
    acl_runner: Callable[[Path], None],
    expected_snapshot: LocalDocumentSnapshot,
    before_publish: Callable[[Path], None] | None,
    remove_temp: Callable[[Path], None],
    replacer: Callable[[Path, Path], None],
) -> LocalDocumentSnapshot:
    """Publish only while the exact captured target owner and bytes remain current."""
    target = Path(target).absolute()
    if (
        type(expected_snapshot) is not LocalDocumentSnapshot
        or expected_snapshot.path != target
        or not _snapshot_is_current(target, expected_snapshot)
    ):
        raise LocalMySQLSetupError("Local MySQL configuration changed")
    keys = set(document)
    if not _CONFIG_KEYS <= keys or not keys <= _CONFIG_KEYS | _OPTIONAL_CONFIG_KEYS:
        raise LocalMySQLSetupError(
            "Local MySQL document must contain required and allowed keys only"
        )

    temporary_path: Path | None = None
    published_snapshot: LocalDocumentSnapshot | None = None
    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".env.local.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
        acl_runner(temporary_path)
        with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(dict(document), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        published_owner = capture_local_document_snapshot(temporary_path)
        if before_publish is not None:
            before_publish(temporary_path)
        if not _snapshot_is_current(target, expected_snapshot):
            raise LocalMySQLSetupError("Local MySQL configuration changed")
        replacer(temporary_path, target)
        temporary_path = None
        published_snapshot = LocalDocumentSnapshot(
            target,
            published_owner.identity,
            published_owner.content,
        )
        if capture_local_document_snapshot(target) != published_snapshot:
            raise LocalMySQLSetupError("Local MySQL configuration changed")
    except BaseException as error:
        primary = error
    finally:
        if temporary_path is not None:
            try:
                remove_temp(temporary_path)
            except BaseException as error:
                cleanup.append(error)
    _raise_publication_failures(primary, cleanup)
    if published_snapshot is None:  # pragma: no cover - defensive invariant
        raise LocalMySQLSetupError(_PUBLICATION_ERROR)
    return published_snapshot


def atomic_compare_and_swap_local_document(
    target: Path,
    document: Mapping[str, object],
    acl_runner: Callable[[Path], None],
    expected_snapshot: LocalDocumentSnapshot,
    *,
    before_publish: Callable[[Path], None] | None = None,
    mutex_api: WindowsMutexAPI | object | None = None,
    platform_name: str = os.name,
    remove_temp: Callable[[Path], None] = _remove_local_temporary,
    replacer: Callable[[Path, Path], None] = os.replace,
) -> LocalDocumentSnapshot:
    """CAS cooperating writers without claiming external-editor linearizability."""
    with _windows_local_config_mutex(
        Path(target), platform_name=platform_name, api=mutex_api
    ):
        return _atomic_compare_and_swap_local_document_locked(
            target,
            document,
            acl_runner,
            expected_snapshot,
            before_publish,
            remove_temp,
            replacer,
        )


def atomic_write_local_config(
    target: Path,
    document: Mapping[str, object],
    acl_runner: Callable[[Path], None],
    *,
    mutex_api: WindowsMutexAPI | object | None = None,
    platform_name: str = os.name,
    remove_temp: Callable[[Path], None] = _remove_local_temporary,
    replacer: Callable[[Path, Path], None] = os.replace,
) -> None:
    """Compatibility writer requiring exactly the original five MySQL keys."""
    if set(document) != _CONFIG_KEYS:
        raise LocalMySQLSetupError("Local MySQL document must contain exactly five keys")
    atomic_write_local_document(
        target,
        document,
        acl_runner,
        mutex_api=mutex_api,
        platform_name=platform_name,
        remove_temp=remove_temp,
        replacer=replacer,
    )


async def run_cli(
    argv: Sequence[str] | None = None,
    *,
    password_reader: Callable[[str], str] = getpass.getpass,
    connector: Callable[[Mapping[str, object]], Awaitable[object]] | None = None,
    file_writer: Callable[
        [Path, Mapping[str, object], Callable[[Path], None]], None
    ] | None = None,
    acl_runner: Callable[[Path], None] | None = None,
    config_path: Path = LOCAL_CONFIG_PATH,
    output: Callable[[str], None] = print,
) -> int:
    """Prompt, validate through read-only capability queries, and publish settings."""
    args = _argument_parser().parse_args(argv)
    for name, value in (
        ("host", args.host),
        ("user", args.user),
        ("database", args.database),
    ):
        if type(value) is not str or not value.strip():
            raise LocalMySQLSetupError(f"{name} must be non-empty")
    password = password_reader("MySQL password: ")
    if type(password) is not str or not password:
        raise LocalMySQLSetupError("MySQL password must be non-empty")

    connection_config = {
        "host": args.host,
        "port": args.port,
        "user": args.user,
        "password": password,
        "charset": "utf8mb4",
        "autocommit": True,
    }
    connect = connector or _default_connection_factory
    session = await connect(connection_config)
    try:
        version = await _verify_server_capabilities(session)
    finally:
        await session.close()

    document = {
        "MYSQL_HOST": args.host,
        "MYSQL_PORT": args.port,
        "MYSQL_USER": args.user,
        "MYSQL_PASSWORD": password,
        "MYSQL_DB": args.database,
    }
    write = file_writer or atomic_write_local_config
    restrict = acl_runner or restrict_windows_acl
    write(Path(config_path), document, restrict)
    output(
        "\n".join((
            f"host={args.host}",
            f"port={args.port}",
            f"user={args.user}",
            f"database={args.database}",
            f"version={version}",
        ))
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(run_cli(argv))
    except SystemExit:
        raise
    except BaseException:
        print("Local MySQL configuration failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
