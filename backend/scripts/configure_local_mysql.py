"""Validate and atomically publish private local MySQL access settings."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Awaitable, Callable, Mapping, Sequence

from backend.scripts.initialize_database import _default_connection_factory
from backend.scripts.reset_writer_core_data import (
    ResetValidationError,
    _verify_reset_server_capabilities,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOCAL_CONFIG_PATH = REPOSITORY_ROOT / ".env.local.json"
_CONFIG_KEYS = frozenset({
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DB",
})


class LocalMySQLSetupError(RuntimeError):
    """Local MySQL settings could not be verified and published safely."""


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


def atomic_write_local_config(
    target: Path,
    document: Mapping[str, object],
    acl_runner: Callable[[Path], None],
) -> None:
    """Restrict a same-directory temporary file before atomically replacing target."""
    target = Path(target)
    if set(document) != _CONFIG_KEYS:
        raise LocalMySQLSetupError("Local MySQL document must contain exactly five keys")

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
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
        acl_runner(temporary_path)
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
        try:
            version = await _verify_reset_server_capabilities(session)
        except ResetValidationError as exc:
            raise LocalMySQLSetupError(
                "The MySQL server does not satisfy Writer Core capabilities"
            ) from exc
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
