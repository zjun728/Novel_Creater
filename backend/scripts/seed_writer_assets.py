"""Validate, plan, or explicitly seed the one fixed approved asset package."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import re
import sys
from typing import Callable, Mapping, Sequence

from backend.domain.assets import PACKAGE_VERSION, load_asset_package
from backend.domain.json_contracts import canonical_hash
from backend.repositories.assets import AssetRepository
from backend.services.assets import AssetSeedReport, AssetSeedService


MANIFEST_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / PACKAGE_VERSION
    / "manifest.json"
)
_DATABASE_NAME = re.compile(r"^[A-Za-z0-9_]+$")


class AssetSeedCommandError(RuntimeError):
    """A fixed CLI safety precondition was not satisfied."""


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, "Writer asset seed arguments are invalid.\n")


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        description="Validate or seed the fixed approved Writer Core asset package."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--database")
    parser.add_argument("--confirm-seed")
    return parser


def _validate_database_args(args, config: Mapping[str, object]) -> None:
    database = args.database
    configured = config.get("db")
    if not isinstance(database, str) or not _DATABASE_NAME.fullmatch(database):
        raise AssetSeedCommandError("A valid --database is required.")
    if database != configured:
        raise AssetSeedCommandError(
            "--database must exactly match the configured database."
        )
    if args.dry_run:
        if args.confirm_seed is not None:
            raise AssetSeedCommandError("Dry-run does not accept --confirm-seed.")
        return
    if args.confirm_seed != database:
        raise AssetSeedCommandError(
            "--confirm-seed must exactly match --database."
        )


def _format_package(package, *, mode: str) -> str:
    return "\n".join(
        (
            f"mode={mode}",
            f"package_version={package.package_version}",
            f"package_hash={canonical_hash(package.manifest)}",
            f"style_count={len(package.styles)}",
            f"card_count={len(package.experience_cards)}",
        )
    )


def _format_report(report: AssetSeedReport, *, mode: str) -> str:
    return "\n".join(
        (
            f"mode={mode}",
            f"package_version={report.package_version}",
            f"package_hash={report.package_hash}",
            f"style_count={report.style_count}",
            f"card_count={report.card_count}",
            f"report.inserted={report.inserted}",
            f"report.replayed={report.replayed}",
            f"report.advanced={report.advanced}",
        )
    )


async def run_cli(
    argv: Sequence[str] | None = None,
    *,
    repository=None,
    connection_factory=None,
    transaction_factory=None,
    connection_config: Mapping[str, object] | None = None,
    output: Callable[[str], None] = print,
) -> int:
    """Run one explicit mode; validation never imports the DB runtime."""

    args = _parser().parse_args(argv)
    package = load_asset_package(MANIFEST_PATH, mode="release")
    if args.validate_only:
        if args.database is not None or args.confirm_seed is not None:
            raise AssetSeedCommandError(
                "Validate-only does not accept database arguments."
            )
        output(_format_package(package, mode="validate-only"))
        return 0

    if connection_config is None:
        from backend.config import require_mysql_config

        connection_config = require_mysql_config()
    _validate_database_args(args, connection_config)
    selected_repository = repository or AssetRepository()

    database_pool_closer = None
    try:
        if args.dry_run:
            if connection_factory is None:
                from backend.database import close_pool as database_pool_closer
                from backend.database import connection as connection_factory

            service = AssetSeedService(
                selected_repository,
                transaction_factory=None,
                connection_factory=connection_factory,
            )
            report = await service.dry_run(package)
            output(_format_report(report, mode="dry-run"))
            return 0

        if transaction_factory is None:
            from backend.database import close_pool as database_pool_closer
            from backend.database import transaction as transaction_factory

        service = AssetSeedService(
            selected_repository,
            transaction_factory=transaction_factory,
        )
        report = await service.seed(package)
        output(_format_report(report, mode="execute"))
        return 0
    finally:
        if database_pool_closer is not None:
            await database_pool_closer()


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(run_cli(argv))
    except Exception:
        print("Writer asset seed command failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
