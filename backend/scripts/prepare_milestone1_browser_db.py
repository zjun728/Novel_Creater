"""Prepare or remove the guarded disposable database used by the M1 browser gate."""

from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
import os
import re
import sys
import time
from typing import Awaitable, Callable, Mapping, Sequence

from backend.scripts.initialize_database import (
    _default_connection_factory,
    initialize_database,
)
from backend.services.project_lifecycle import ProjectLifecycleService
from backend.services.projections import build_projection_bundle


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
PROJECT_ID = "project-1"
SELECTED_SEED_ID = "seed-3"
_NOW_MS = 1_720_000_000_000
_PROVIDER_SECRET = "browser-secret-must-not-leak"
_PROVIDER_BASE_URL = "https://private-provider.example/v1"


class BrowserDatabaseSafetyError(RuntimeError):
    """The browser database request is not provably disposable."""


def assert_browser_database_name(database_name: str) -> None:
    """Reject product and malformed names before any connection or DDL."""
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
    """Build an admin config exclusively from explicit TEST_MYSQL_* values."""
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


def _seed_payload(title: str, genre: str, logline: str) -> tuple[str, str]:
    payload = {
        "genre": genre,
        "logline": logline,
        "source": "author",
    }
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return rendered, sha256(rendered.encode("utf-8")).hexdigest()


async def _insert_fixture(session, now_ms: int) -> None:
    empty_hash = build_projection_bundle(0, ()).content_hash
    seeds = (
        ("seed-1", "永乐长明", "少年在永乐盛世守护一盏记录民间真相的长明灯。", "candidate"),
        ("seed-2", "文渊山海", "文渊阁校书郎从残卷中发现一幅会改写疆域的山海图。", "candidate"),
        (SELECTED_SEED_ID, "典镇山河", "大典修纂者以文字镇守山河秩序与百姓记忆。", "selected"),
    )

    await session.execute("START TRANSACTION")
    try:
        await session.execute(
            """INSERT INTO projects
               (id, title, genre, description, target_words, target_chapters,
                status, current_chapter, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,'drafting',0,%s,%s)""",
            (
                PROJECT_ID,
                "永乐大典",
                "架空历史",
                "Writer Core M1 浏览器验收项目。",
                1_000_000,
                300,
                now_ms,
                now_ms,
            ),
        )
        for seed_id, title, logline, status in seeds:
            premise, content_hash = _seed_payload(title, "架空历史", logline)
            await session.execute(
                """INSERT INTO creative_seeds
                   (id, project_id, title, premise_json, content_hash, status,
                    created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (
                    seed_id,
                    PROJECT_ID,
                    title,
                    premise,
                    content_hash,
                    status,
                    now_ms,
                ),
            )
        await session.execute(
            """INSERT INTO project_selected_seeds
               (project_id, seed_id, selected_at) VALUES (%s,%s,%s)""",
            (PROJECT_ID, SELECTED_SEED_ID, now_ms),
        )
        await session.execute(
            """INSERT INTO provider_profiles
               (id, name, provider_type, model_name, base_url, api_key, enabled,
                sort_order, stream, max_context_tokens, max_output_tokens,
                temperature, top_p, supports_json, supports_streaming, notes,
                thinking, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,1,0,1,%s,%s,%s,%s,1,1,%s,NULL,%s,%s)""",
            (
                "provider-1",
                "浏览器验收 Provider",
                "openai-compatible",
                "browser-test-model",
                _PROVIDER_BASE_URL,
                _PROVIDER_SECRET,
                200_000,
                4096,
                "0.800",
                "0.900",
                "M1 browser fixture; never call this Provider.",
                now_ms,
                now_ms,
            ),
        )
        await session.execute(
            """INSERT INTO canon_revisions
               (id, project_id, revision_number, parent_revision_number,
                idempotency_key, source_type, source_id, content_hash, created_at)
               VALUES (%s,%s,0,0,%s,'bootstrap',NULL,%s,%s)""",
            (
                "revision-0",
                PROJECT_ID,
                ProjectLifecycleService.bootstrap_idempotency_key(PROJECT_ID),
                empty_hash,
                now_ms,
            ),
        )
        await session.execute(
            """INSERT INTO projection_heads
               (project_id, canon_revision_number, projection_revision_number,
                content_hash, updated_at) VALUES (%s,0,0,%s,%s)""",
            (PROJECT_ID, empty_hash, now_ms),
        )
        await session.execute("COMMIT")
    except BaseException as body_error:
        try:
            await session.execute("ROLLBACK")
        except BaseException as rollback_error:
            raise BaseExceptionGroup(
                "Browser fixture insert and rollback both failed",
                [body_error, rollback_error],
            ) from body_error
        raise


async def _drop_database(session, database_name: str) -> None:
    assert_browser_database_name(database_name)
    await session.execute(f"DROP DATABASE IF EXISTS `{database_name}`")
    assert_browser_database_name(database_name)
    remaining = await session.fetchone(_DATABASE_EXISTS_QUERY, (database_name,))
    if remaining is not None:
        raise BrowserDatabaseSafetyError(
            f"Disposable browser database still exists after cleanup: {database_name}"
        )


async def _prepare_database(session, database_name: str, now_ms: int) -> None:
    assert_browser_database_name(database_name)
    await initialize_database(session, database_name, database_name, now_ms)
    try:
        await _insert_fixture(session, now_ms)
    except BaseException as prepare_error:
        try:
            await _drop_database(session, database_name)
        except BaseException as cleanup_error:
            raise BaseExceptionGroup(
                "Browser database preparation and cleanup both failed",
                [prepare_error, cleanup_error],
            ) from prepare_error
        raise


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare or drop one disposable M1 browser database"
    )
    parser.add_argument("--database", required=True)
    parser.add_argument("--drop", action="store_true")
    return parser


async def run_cli(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    connection_factory: Callable[[Mapping[str, object]], Awaitable[object]] | None = None,
    now_ms: Callable[[], int] | None = None,
    output: Callable[[str], None] = print,
) -> int:
    args = _argument_parser().parse_args(argv)
    assert_browser_database_name(args.database)
    config = browser_mysql_config(environment)
    factory = connection_factory or _default_connection_factory
    session = await factory(config)
    body_error: BaseException | None = None
    try:
        if args.drop:
            await _drop_database(session, args.database)
        else:
            timestamp = (now_ms or (lambda: int(time.time() * 1000)))()
            await _prepare_database(session, args.database, timestamp)
    except BaseException as exc:
        body_error = exc

    close_error: BaseException | None = None
    try:
        await session.close()
    except BaseException as exc:
        close_error = exc

    if body_error is not None and close_error is not None:
        raise BaseExceptionGroup(
            "Browser database operation and connection close both failed",
            [body_error, close_error],
        ) from body_error
    if body_error is not None:
        raise body_error
    if close_error is not None:
        raise close_error

    action = "dropped" if args.drop else "prepared"
    output(f"browser_database={args.database} action={action}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(run_cli(argv))
    except SystemExit:
        raise
    except BaseException:
        print("M1 browser database operation failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
