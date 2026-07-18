"""Prepare or remove one empty disposable database for product-shell browser tests."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
from typing import Awaitable, Callable, Mapping, Sequence

from backend.scripts.initialize_database import (
    _default_connection_factory,
    initialize_database,
)


_DISPOSABLE_DATABASE = re.compile(r"novel_creator_test_[a-f0-9]{32}\Z")
_DATABASE_EXISTS_QUERY = (
    "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s"
)
_REQUIRED_TEST_VARIABLES = (
    "TEST_MYSQL_HOST",
    "TEST_MYSQL_PORT",
    "TEST_MYSQL_USER",
    "TEST_MYSQL_PASSWORD",
)


class BrowserDatabaseSafetyError(RuntimeError):
    """The requested browser database is not provably disposable."""


def assert_browser_database_name(database_name: str) -> None:
    if (
        not isinstance(database_name, str)
        or _DISPOSABLE_DATABASE.fullmatch(database_name) is None
    ):
        raise BrowserDatabaseSafetyError(
            f"Refusing non-disposable browser database: {database_name!r}"
        )


def browser_mysql_config(
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Build administrative authority exclusively from explicit TEST_MYSQL_*."""
    source = os.environ if environment is None else environment
    missing = [name for name in _REQUIRED_TEST_VARIABLES if not source.get(name)]
    if missing:
        raise BrowserDatabaseSafetyError(
            "Browser MySQL requires explicit variables: " + ", ".join(missing)
        )
    try:
        port = int(source["TEST_MYSQL_PORT"])
    except (TypeError, ValueError) as exc:
        raise BrowserDatabaseSafetyError(
            "TEST_MYSQL_PORT must be an integer"
        ) from exc
    if not 1 <= port <= 65535:
        raise BrowserDatabaseSafetyError(
            "TEST_MYSQL_PORT must be between 1 and 65535"
        )
    return {
        "host": source["TEST_MYSQL_HOST"],
        "port": port,
        "user": source["TEST_MYSQL_USER"],
        "password": source["TEST_MYSQL_PASSWORD"],
        "charset": "utf8mb4",
        "autocommit": True,
    }


async def _drop_database(session, database_name: str) -> None:
    assert_browser_database_name(database_name)
    await session.execute(f"DROP DATABASE IF EXISTS `{database_name}`")
    remaining = await session.fetchone(_DATABASE_EXISTS_QUERY, (database_name,))
    if remaining is not None:
        raise BrowserDatabaseSafetyError(
            f"Disposable browser database still exists after cleanup: {database_name}"
        )


async def _prepare_database(
    session,
    database_name: str,
    now_ms: int,
) -> None:
    assert_browser_database_name(database_name)
    try:
        await initialize_database(
            session,
            database_name,
            database_name,
            now_ms,
        )
    except BaseException as prepare_error:
        try:
            await _drop_database(session, database_name)
        except BaseException as cleanup_error:
            raise BaseExceptionGroup(
                "Product-shell database preparation and cleanup both failed",
                [prepare_error, cleanup_error],
            ) from prepare_error
        raise


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare or drop one empty disposable product-shell database"
    )
    parser.add_argument("--database", required=True)
    parser.add_argument("--drop", action="store_true")
    return parser


async def run_cli(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    connection_factory: Callable[
        [Mapping[str, object]], Awaitable[object]
    ] | None = None,
    now_ms: Callable[[], int] | None = None,
    output: Callable[[str], None] = print,
) -> int:
    args = _argument_parser().parse_args(argv)
    assert_browser_database_name(args.database)
    config = browser_mysql_config(environment)
    factory = connection_factory or _default_connection_factory
    session = await factory(config)
    errors: list[BaseException] = []
    try:
        if args.drop:
            await _drop_database(session, args.database)
        else:
            timestamp = (now_ms or (lambda: int(time.time() * 1000)))()
            await _prepare_database(session, args.database, timestamp)
    except BaseException as exc:
        errors.append(exc)
    try:
        await session.close()
    except BaseException as exc:
        errors.append(exc)
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise BaseExceptionGroup(
            "Product-shell database operation and connection close both failed",
            errors,
        )
    output(f"action={'dropped' if args.drop else 'prepared'}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(run_cli(argv))
    except SystemExit:
        raise
    except BaseException:
        print("Product-shell browser database operation failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
