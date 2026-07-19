"""Validate or explicitly seed the fixed built-in market source package."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import re
import sys
from typing import Callable, Mapping, Sequence

from backend.domain.market_sources import (
    PACKAGE_VERSION,
    load_market_source_package,
)
from backend.repositories.market import MarketRepository
from backend.services.market_sources import MarketSourceSeedService


MANIFEST_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / PACKAGE_VERSION
    / "manifest.json"
)
_DATABASE_NAME = re.compile(r"^[A-Za-z0-9_]+$")


class MarketSourceSeedCommandError(RuntimeError):
    pass


def _parser():
    parser = argparse.ArgumentParser(
        description="Validate or explicitly seed built-in market sources."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--database")
    parser.add_argument("--confirm-seed")
    return parser


def _format_package(package) -> str:
    return "\n".join(
        (
            "mode=validate-only",
            f"package_version={package.package_version}",
            f"source_count={len(package.sources)}",
        )
    )


def _format_report(report) -> str:
    return "\n".join(
        (
            "mode=execute",
            f"package_version={report.package_version}",
            f"source_count={report.source_count}",
            f"package_hash={report.package_hash}",
            f"report.inserted={report.inserted}",
            f"report.replayed={report.replayed}",
        )
    )


async def run_cli(
    argv: Sequence[str] | None = None,
    *,
    repository=None,
    transaction_factory=None,
    connection_config: Mapping[str, object] | None = None,
    output: Callable[[str], None] = print,
) -> int:
    args = _parser().parse_args(argv)
    package = load_market_source_package(MANIFEST_PATH)
    if args.validate_only:
        if args.database is not None or args.confirm_seed is not None:
            raise MarketSourceSeedCommandError(
                "Validate-only does not accept database arguments."
            )
        output(_format_package(package))
        return 0
    if connection_config is None:
        from backend.config import require_mysql_config

        connection_config = require_mysql_config()
    database = args.database
    if (
        not isinstance(database, str)
        or _DATABASE_NAME.fullmatch(database) is None
        or database != connection_config.get("db")
        or args.confirm_seed != database
    ):
        raise MarketSourceSeedCommandError(
            "Database and confirmation must exactly match configuration."
        )
    closer = None
    if transaction_factory is None:
        from backend.database import close_pool as closer
        from backend.database import transaction as transaction_factory
    try:
        report = await MarketSourceSeedService(
            repository or MarketRepository(),
            transaction_factory=transaction_factory,
        ).seed(package)
        output(_format_report(report))
    finally:
        if closer is not None:
            await closer()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(run_cli(argv))
    except Exception:
        print("Market source seed command failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
