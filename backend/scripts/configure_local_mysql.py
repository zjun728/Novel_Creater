"""Validate and atomically publish private local MySQL access settings."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import getpass
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


def atomic_write_local_document(
    target: Path,
    document: Mapping[str, object],
    acl_runner: Callable[[Path], None],
) -> None:
    """Atomically publish the exact MySQL document and existing corpus fields."""
    target = Path(target)
    keys = set(document)
    if not _CONFIG_KEYS <= keys or not keys <= _CONFIG_KEYS | _OPTIONAL_CONFIG_KEYS:
        raise LocalMySQLSetupError(
            "Local MySQL document must contain required and allowed keys only"
        )

    temporary_path: Path | None = None
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
        os.replace(temporary_path, target)
        temporary_path = None
    except OSError as exc:
        raise LocalMySQLSetupError(
            "Could not atomically save the local MySQL configuration"
        ) from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as exc:
                raise LocalMySQLSetupError(
                    "Could not remove an unpublished local configuration"
                ) from exc


def atomic_compare_and_swap_local_document(
    target: Path,
    document: Mapping[str, object],
    acl_runner: Callable[[Path], None],
    expected_snapshot: LocalDocumentSnapshot,
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
        if not _snapshot_is_current(target, expected_snapshot):
            raise LocalMySQLSetupError("Local MySQL configuration changed")
        os.replace(temporary_path, target)
        temporary_path = None
        return LocalDocumentSnapshot(
            target,
            published_owner.identity,
            published_owner.content,
        )
    except LocalMySQLSetupError:
        raise
    except OSError as exc:
        raise LocalMySQLSetupError(
            "Could not atomically save the local MySQL configuration"
        ) from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as exc:
                raise LocalMySQLSetupError(
                    "Could not remove an unpublished local configuration"
                ) from exc


def atomic_write_local_config(
    target: Path,
    document: Mapping[str, object],
    acl_runner: Callable[[Path], None],
) -> None:
    """Compatibility writer requiring exactly the original five MySQL keys."""
    if set(document) != _CONFIG_KEYS:
        raise LocalMySQLSetupError("Local MySQL document must contain exactly five keys")
    atomic_write_local_document(target, document, acl_runner)


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
