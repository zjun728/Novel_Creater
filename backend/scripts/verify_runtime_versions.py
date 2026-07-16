"""Read-only, reproducible runtime-version receipt for M2 acceptance."""

from __future__ import annotations

import argparse
import asyncio
from importlib.metadata import version
import json
import os
import sys
from typing import Awaitable, Callable, Mapping, Sequence

from backend.scripts.initialize_database import _default_connection_factory


PACKAGE_KEYS = (
    "python",
    "pydantic",
    "httpx",
    "fastapi",
    "starlette",
    "uvicorn",
    "pytest",
)
_DISTRIBUTIONS = PACKAGE_KEYS[1:]
_REQUIRED_TEST_VARIABLES = (
    "TEST_MYSQL_HOST",
    "TEST_MYSQL_PORT",
    "TEST_MYSQL_USER",
    "TEST_MYSQL_PASSWORD",
)


class RuntimeVersionSafetyError(RuntimeError):
    """The read-only test-server authority is incomplete or invalid."""


def installed_package_versions() -> dict[str, str]:
    return {
        "python": ".".join(str(part) for part in sys.version_info[:3]),
        **{distribution: version(distribution) for distribution in _DISTRIBUTIONS},
    }


def test_mysql_config(environment: Mapping[str, str]) -> dict[str, object]:
    missing = [name for name in _REQUIRED_TEST_VARIABLES if not environment.get(name)]
    if missing:
        raise RuntimeVersionSafetyError(
            "Runtime version verification requires explicit variables: "
            + ", ".join(missing)
        )
    try:
        port = int(environment["TEST_MYSQL_PORT"])
    except (TypeError, ValueError) as exc:
        raise RuntimeVersionSafetyError("TEST_MYSQL_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise RuntimeVersionSafetyError("TEST_MYSQL_PORT is outside the TCP port range")
    return {
        "host": environment["TEST_MYSQL_HOST"],
        "port": port,
        "user": environment["TEST_MYSQL_USER"],
        "password": environment["TEST_MYSQL_PASSWORD"],
        "charset": "utf8mb4",
        "autocommit": True,
    }


async def collect_runtime_versions(
    session,
    *,
    package_versions: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Read only ``SELECT VERSION()`` and return an allowlisted receipt."""

    resolved = package_versions or installed_package_versions()
    missing = [key for key in PACKAGE_KEYS if not resolved.get(key)]
    if missing:
        raise RuntimeVersionSafetyError(
            "Runtime package versions are incomplete: " + ", ".join(missing)
        )
    row = await session.fetchone("SELECT VERSION() AS version")
    mysql_version = (row or {}).get("version")
    if not isinstance(mysql_version, str) or not mysql_version:
        raise RuntimeVersionSafetyError("MySQL server version was not available")
    return {
        **{key: str(resolved[key]) for key in PACKAGE_KEYS},
        "mysql": mysql_version,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-mysql", action="store_true", required=True)
    return parser


async def run_cli(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    connection_factory: Callable[[Mapping[str, object]], Awaitable[object]] | None = None,
    package_versions: Mapping[str, str] | None = None,
    output: Callable[[str], None] = print,
) -> int:
    _parser().parse_args(argv)
    config = test_mysql_config(os.environ if environment is None else environment)
    session = await (connection_factory or _default_connection_factory)(config)
    try:
        receipt = await collect_runtime_versions(
            session,
            package_versions=package_versions,
        )
    finally:
        await session.close()
    output(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(run_cli(argv))
    except SystemExit:
        raise
    except BaseException:
        print("M2 runtime version verification failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
