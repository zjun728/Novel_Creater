"""One-time preserve-and-reset command for the Writer Core V1 schema.

The reset reads only the three explicitly preserved legacy tables.  It does
not migrate legacy writing, Canon, planning, settings, audit or QA content.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
import json
import re
import sys
import time
from typing import Awaitable, Callable, Mapping, Sequence
from uuid import uuid4

from backend.schema_manifest import created_table_names
from backend.scripts.initialize_database import (
    _default_connection_factory,
    initialize_database,
)
from backend.services.projects import ProjectService, TASK_KEYS
from backend.services.projections import build_projection_bundle


PRODUCT_DATABASE = "novel_creator"
RESET_LOCK_NAME = "novel_creator_writer_core_reset"
SELECTED_SEED_TITLE = "典镇山河"
PRESERVE_TABLES = ("projects", "creative_seeds", "provider_profiles")
FOUNDATION_TABLES = frozenset({
    "schema_metadata",
    "projects",
    "creative_seeds",
    "project_selected_seeds",
    "provider_profiles",
    "task_model_bindings",
    "task_model_binding_items",
    "canon_revisions",
    "projection_heads",
})
VERIFIED_EMPTY_TABLES = tuple(
    table for table in created_table_names() if table not in FOUNDATION_TABLES
)
_DISPOSABLE_DATABASE = re.compile(r"novel_creator_test_[a-f0-9]{32}")
_CLI_PRODUCT_AUTHORITY = object()

_PROJECT_COLUMNS = (
    "id", "title", "genre", "description", "target_words",
    "target_chapters", "status", "current_chapter", "created_at", "updated_at",
)
_SEED_COLUMNS = (
    "id", "project_id", "title", "premise_json", "content_hash", "status",
    "created_at",
)
_PROVIDER_COLUMNS = (
    "id", "name", "provider_type", "model_name", "base_url", "api_key",
    "enabled", "sort_order", "stream", "max_context_tokens",
    "max_output_tokens", "temperature", "top_p", "supports_json",
    "supports_streaming", "notes", "thinking", "created_at", "updated_at",
)


class ResetError(RuntimeError):
    """Base class for safe reset failures."""


class ResetSafetyError(ResetError):
    """The requested target or confirmation is unsafe."""


class ResetValidationError(ResetError):
    """Preserved rows do not match the exact reset contract."""


class ResetPartialStateError(ResetError):
    """DDL started and the target may now contain partial reset state."""


def _trimmed(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty trimmed string")
    return value


@dataclass(frozen=True)
class ResetRequest:
    project_title: str
    seed_titles: tuple[str, ...]
    preferred_provider_name: str
    preferred_model: str

    def __post_init__(self) -> None:
        _trimmed(self.project_title, "project_title")
        if type(self.seed_titles) is not tuple:
            raise ValueError("seed_titles must be a tuple of three unique titles")
        if (
            len(self.seed_titles) != 3
            or len(set(self.seed_titles)) != 3
            or any(
                not isinstance(title, str)
                or not title
                or title != title.strip()
                for title in self.seed_titles
            )
        ):
            raise ValueError("seed_titles must contain exactly three unique titles")
        if SELECTED_SEED_TITLE not in self.seed_titles:
            raise ValueError(f"seed_titles must include {SELECTED_SEED_TITLE}")
        _trimmed(self.preferred_provider_name, "preferred_provider_name")
        _trimmed(self.preferred_model, "preferred_model")


@dataclass(frozen=True)
class ResetReport:
    executed: bool
    database_name: str
    project_id: str
    project_title: str
    seed_count: int
    seeds: tuple[tuple[str, str], ...]
    provider_count: int
    providers: tuple[tuple[str, str, str, bool], ...]
    preferred_provider_id: str
    table_names: tuple[str, ...]
    verified_empty_tables: tuple[str, ...]


@dataclass(frozen=True)
class _PreservedState:
    project: Mapping[str, object]
    seeds: tuple[Mapping[str, object], ...]
    providers: tuple[Mapping[str, object], ...]
    preferred_provider: Mapping[str, object]


def _qualified(database_name: str, table_name: str) -> str:
    return f"`{database_name}`.`{table_name}`"


def _guard_database(database_name: str, allow_product_database: bool) -> None:
    if database_name == PRODUCT_DATABASE:
        if not allow_product_database:
            raise ResetSafetyError(
                "Refusing product database novel_creator without explicit CLI authorization"
            )
        return
    if (
        not isinstance(database_name, str)
        or _DISPOSABLE_DATABASE.fullmatch(database_name) is None
    ):
        raise ResetSafetyError(f"Refusing non-disposable database: {database_name}")


def _validate_target(
    database_name: str,
    confirm_reset: str,
    allow_product_database: bool,
) -> None:
    _guard_database(database_name, allow_product_database)
    if database_name != confirm_reset:
        raise ResetSafetyError("Database confirmation does not match reset target")


async def _load_preserved_state(admin_session, database_name: str, request: ResetRequest):
    project_rows = await admin_session.fetchall(
        f"SELECT {', '.join(_PROJECT_COLUMNS)} "
        f"FROM {_qualified(database_name, 'projects')} WHERE title=%s",
        (request.project_title,),
    )
    if len(project_rows) != 1:
        raise ResetValidationError(
            "Reset requires exactly one project with the requested title"
        )
    project = project_rows[0]

    placeholders = ",".join(("%s",) * len(request.seed_titles))
    seed_rows = await admin_session.fetchall(
        f"SELECT {', '.join(_SEED_COLUMNS)} "
        f"FROM {_qualified(database_name, 'creative_seeds')} "
        f"WHERE project_id=%s AND title IN ({placeholders}) ORDER BY title, id",
        (project["id"], *request.seed_titles),
    )
    actual_titles = Counter(row["title"] for row in seed_rows)
    if len(seed_rows) != 3 or actual_titles != Counter(request.seed_titles):
        raise ResetValidationError(
            "Reset requires exactly one row for each requested seed title"
        )

    provider_rows = await admin_session.fetchall(
        f"SELECT {', '.join(_PROVIDER_COLUMNS)} "
        f"FROM {_qualified(database_name, 'provider_profiles')} "
        "ORDER BY sort_order, created_at, id"
    )
    preferred = tuple(
        row for row in provider_rows
        if row["name"] == request.preferred_provider_name
        and row["model_name"] == request.preferred_model
        and row["enabled"] == 1
    )
    if len(preferred) != 1:
        raise ResetValidationError(
            "Reset requires exactly one enabled preferred Provider/model row"
        )
    return _PreservedState(
        project=project,
        seeds=tuple(seed_rows),
        providers=tuple(provider_rows),
        preferred_provider=preferred[0],
    )


def _report(
    database_name: str,
    state: _PreservedState,
    *,
    executed: bool,
) -> ResetReport:
    return ResetReport(
        executed=executed,
        database_name=database_name,
        project_id=str(state.project["id"]),
        project_title=str(state.project["title"]),
        seed_count=len(state.seeds),
        seeds=tuple((str(row["id"]), str(row["title"])) for row in state.seeds),
        provider_count=len(state.providers),
        providers=tuple(
            (
                str(row["id"]),
                str(row["name"]),
                str(row["model_name"]),
                row["enabled"] == 1,
            )
            for row in state.providers
        ),
        preferred_provider_id=str(state.preferred_provider["id"]),
        table_names=created_table_names(),
        verified_empty_tables=VERIFIED_EMPTY_TABLES if executed else (),
    )


def format_reset_report(report: ResetReport) -> str:
    """Render only identifiers, public labels, counts and manifest table names."""
    lines = [
        f"mode={'execute' if report.executed else 'dry-run'}",
        f"database={report.database_name}",
        "projects.count=1",
        f"project.id={report.project_id}",
        f"project.title={report.project_title}",
        f"seeds.count={report.seed_count}",
    ]
    lines.extend(
        f"seed.id={seed_id} seed.title={title}"
        for seed_id, title in report.seeds
    )
    lines.append(f"providers.count={report.provider_count}")
    lines.extend(
        f"provider.id={provider_id} provider.name={name} "
        f"provider.model={model} provider.enabled={str(enabled).lower()}"
        for provider_id, name, model, enabled in report.providers
    )
    lines.extend((
        f"preferred_provider.id={report.preferred_provider_id}",
        "tables=" + ",".join(report.table_names),
    ))
    if report.executed:
        lines.append("verified_empty_tables=" + ",".join(report.verified_empty_tables))
    return "\n".join(lines)


def _db_json(value: object) -> object:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


async def _insert_preserved_state(
    admin_session,
    state: _PreservedState,
    *,
    now_ms: int,
    id_factory: Callable[[], str],
) -> None:
    project = state.project
    await admin_session.execute(
        f"INSERT INTO projects ({', '.join(_PROJECT_COLUMNS)}) "
        f"VALUES ({','.join(('%s',) * len(_PROJECT_COLUMNS))})",
        tuple(project[column] for column in _PROJECT_COLUMNS),
    )
    for seed in state.seeds:
        values = tuple(
            _db_json(seed[column]) if column == "premise_json" else seed[column]
            for column in _SEED_COLUMNS
        )
        await admin_session.execute(
            f"INSERT INTO creative_seeds ({', '.join(_SEED_COLUMNS)}) "
            f"VALUES ({','.join(('%s',) * len(_SEED_COLUMNS))})",
            values,
        )
    for provider in state.providers:
        values = tuple(
            _db_json(provider[column]) if column == "thinking" else provider[column]
            for column in _PROVIDER_COLUMNS
        )
        await admin_session.execute(
            f"INSERT INTO provider_profiles ({', '.join(_PROVIDER_COLUMNS)}) "
            f"VALUES ({','.join(('%s',) * len(_PROVIDER_COLUMNS))})",
            values,
        )

    selected_seed = next(
        seed for seed in state.seeds if seed["title"] == SELECTED_SEED_TITLE
    )
    await admin_session.execute(
        "INSERT INTO project_selected_seeds (project_id, seed_id, selected_at) "
        "VALUES (%s,%s,%s)",
        (project["id"], selected_seed["id"], now_ms),
    )

    empty_hash = build_projection_bundle(0, ()).content_hash
    await admin_session.execute(
        """INSERT INTO canon_revisions
           (id, project_id, revision_number, parent_revision_number,
            idempotency_key, source_type, source_id, content_hash, created_at)
           VALUES (%s,%s,0,0,%s,'bootstrap',NULL,%s,%s)""",
        (
            id_factory(),
            project["id"],
            ProjectService.bootstrap_idempotency_key(str(project["id"])),
            empty_hash,
            now_ms,
        ),
    )
    await admin_session.execute(
        """INSERT INTO projection_heads
           (project_id, canon_revision_number, projection_revision_number,
            content_hash, updated_at) VALUES (%s,0,0,%s,%s)""",
        (project["id"], empty_hash, now_ms),
    )

    binding_id = id_factory()
    await admin_session.execute(
        """INSERT INTO task_model_bindings
           (id, project_id, source_project_id, created_at, updated_at)
           VALUES (%s,%s,NULL,%s,%s)""",
        (binding_id, project["id"], now_ms, now_ms),
    )
    preferred = state.preferred_provider
    for task_key in TASK_KEYS:
        await admin_session.execute(
            """INSERT INTO task_model_binding_items
               (id, project_id, binding_id, task_key, provider_id, model_name,
                created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                id_factory(), project["id"], binding_id, task_key,
                preferred["id"], preferred["model_name"], now_ms, now_ms,
            ),
        )


async def _verify_empty_tables(admin_session) -> None:
    for table in VERIFIED_EMPTY_TABLES:
        row = await admin_session.fetchone(f"SELECT COUNT(*) AS count FROM {table}")
        if row is None or row["count"] != 0:
            raise ResetPartialStateError(
                f"Reset verification found unexpected derived rows in {table}"
            )


async def _release_lock(admin_session) -> None:
    row = await admin_session.fetchone(
        "SELECT RELEASE_LOCK(%s) AS released", (RESET_LOCK_NAME,)
    )
    if row is None or row["released"] != 1:
        raise ResetError("Writer Core reset advisory lock was not released")


async def reset_writer_core_data(
    admin_session,
    *,
    database_name: str,
    confirm_reset: str,
    request: ResetRequest,
    execute: bool = False,
    allow_product_database: bool = False,
    output: Callable[[str], None] = print,
    now_ms: Callable[[], int] | None = None,
    id_factory: Callable[[], str] | None = None,
    _product_authority: object | None = None,
) -> ResetReport:
    """Inspect or rebuild one explicitly authorized target database."""
    if type(request) is not ResetRequest:
        raise TypeError("request must be ResetRequest")
    product_authorized = bool(
        allow_product_database and _product_authority is _CLI_PRODUCT_AUTHORITY
    )
    _validate_target(database_name, confirm_reset, product_authorized)

    if not execute:
        state = await _load_preserved_state(admin_session, database_name, request)
        report = _report(database_name, state, executed=False)
        output(format_reset_report(report))
        return report

    acquired = False
    ddl_started = False
    body_error = None
    report = None
    try:
        lock = await admin_session.fetchone(
            "SELECT GET_LOCK(%s, %s) AS acquired", (RESET_LOCK_NAME, 30)
        )
        if lock is None or lock["acquired"] != 1:
            raise ResetError("Could not acquire Writer Core reset advisory lock")
        acquired = True
        state = await _load_preserved_state(admin_session, database_name, request)

        _guard_database(database_name, product_authorized)
        ddl_started = True
        await admin_session.execute(f"DROP DATABASE `{database_name}`")
        _guard_database(database_name, product_authorized)
        await admin_session.execute(
            f"CREATE DATABASE `{database_name}` CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_0900_ai_ci"
        )
        _guard_database(database_name, product_authorized)
        timestamp = (now_ms or (lambda: int(time.time() * 1000)))()
        await initialize_database(
            admin_session,
            database_name,
            database_name,
            timestamp,
        )
        await admin_session.execute("START TRANSACTION")
        try:
            await _insert_preserved_state(
                admin_session,
                state,
                now_ms=timestamp,
                id_factory=id_factory or (lambda: str(uuid4())),
            )
            await _verify_empty_tables(admin_session)
        except BaseException as insert_error:
            try:
                await admin_session.execute("ROLLBACK")
            except BaseException as rollback_error:
                raise BaseExceptionGroup(
                    "Writer Core restore and rollback both failed",
                    [insert_error, rollback_error],
                ) from insert_error
            raise
        else:
            await admin_session.execute("COMMIT")
        report = _report(database_name, state, executed=True)
    except BaseException as exc:
        body_error = exc
    finally:
        release_error = None
        if acquired:
            try:
                await _release_lock(admin_session)
            except BaseException as exc:
                release_error = exc
        if body_error is not None and release_error is not None:
            raise BaseExceptionGroup(
                "Writer Core reset and advisory lock release both failed",
                [body_error, release_error],
            ) from body_error
        if body_error is not None:
            if isinstance(body_error, (ResetSafetyError, ResetValidationError)):
                raise body_error
            if not ddl_started:
                raise body_error
            raise ResetPartialStateError(
                f"Writer Core reset failed; {database_name} may remain partially reset"
            ) from body_error
        if release_error is not None:
            raise release_error

    output(format_reset_report(report))
    return report


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preserve foundation rows and reset Writer Core data"
    )
    parser.add_argument("--database", required=True)
    parser.add_argument("--project-title", required=True)
    parser.add_argument("--seed-title", action="append", required=True)
    parser.add_argument("--preferred-provider-name", required=True)
    parser.add_argument("--preferred-model", required=True)
    parser.add_argument("--confirm-reset", required=True)
    parser.add_argument("--execute", action="store_true")
    return parser


async def run_cli(
    argv: Sequence[str] | None = None,
    *,
    connection_factory: Callable[[Mapping[str, object]], Awaitable[object]] | None = None,
    connection_config: Mapping[str, object] | None = None,
    output: Callable[[str], None] = print,
    reset_function: Callable[..., Awaitable[object]] | None = None,
) -> int:
    args = _argument_parser().parse_args(argv)
    if args.database != args.confirm_reset:
        raise ResetSafetyError("Database confirmation does not match reset target")
    request = ResetRequest(
        project_title=args.project_title,
        seed_titles=tuple(args.seed_title),
        preferred_provider_name=args.preferred_provider_name,
        preferred_model=args.preferred_model,
    )
    allow_product_database = bool(
        args.execute
        and args.database == PRODUCT_DATABASE
        and args.confirm_reset == PRODUCT_DATABASE
    )
    _guard_database(args.database, allow_product_database)
    if connection_config is None:
        from backend.config import MYSQL_CONFIG

        connection_config = MYSQL_CONFIG
    factory = connection_factory or _default_connection_factory
    session = await factory(connection_config)
    try:
        reset_callable = reset_function or reset_writer_core_data
        await reset_callable(
            session,
            database_name=args.database,
            confirm_reset=args.confirm_reset,
            request=request,
            execute=args.execute,
            allow_product_database=allow_product_database,
            output=output,
            _product_authority=_CLI_PRODUCT_AUTHORITY,
        )
    finally:
        await session.close()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(run_cli(argv))
    except BaseException:
        print("Writer Core data reset failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
