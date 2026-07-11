"""One-time cross-server Writer Core product bootstrap."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from typing import Callable, Mapping, Sequence
from uuid import uuid4

from backend.scripts.initialize_database import (
    _default_connection_factory,
    initialize_database,
)
from backend.scripts.reset_writer_core_data import (
    PRODUCT_DATABASE,
    ResetSafetyError,
    ResetValidationError,
    _LEGACY_PROJECT_COLUMNS,
    _LEGACY_PROVIDER_COLUMNS,
    _LEGACY_SEED_COLUMNS,
    _PreservedState,
    _map_project,
    _map_provider,
    _map_seed,
    _guard_database,
    _insert_preserved_state,
    _require_exact_unique,
    _require_target_collation_unique,
    _verify_empty_tables,
    _verify_reset_server_capabilities,
)
from backend.services.projects import TASK_KEYS


SOURCE_PROJECT_TITLE = "永乐大典"
SOURCE_SEED_TITLES = ("永乐长明", "文渊山海", "典镇山河")
SOURCE_PREFERRED_PROVIDER_NAME = "联通云-DeepSeek-V4-Flash"
SOURCE_PREFERRED_MODEL = "DeepSeek-V4-Flash"
TARGET_PREFERRED_PROVIDER_NAME = "联通云"
TARGET_PREFERRED_MODEL = "deepseek-v4-flash"
BOOTSTRAP_LOCK_NAME = "novel_creator_writer_core_cross_server_bootstrap"
_CLI_PRODUCT_READ_AUTHORITY = object()
_CLI_PRODUCT_EXECUTE_AUTHORITY = object()
_TARGET_EXISTS_QUERY = (
    "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s"
)


class BootstrapError(RuntimeError):
    """Base class for guarded cross-server bootstrap failures."""


class BootstrapSourceError(BootstrapError):
    """The legacy mysql client did not return the approved inventory."""


class BootstrapValidationError(BootstrapError):
    """The legacy inventory cannot map exactly into Writer Core V1."""


class BootstrapSafetyError(BootstrapError):
    """The target or requested mutation lacks required authority."""


@dataclass(frozen=True)
class LegacyInventory:
    source_version: str
    projects: tuple[Mapping[str, object], ...]
    seeds: tuple[Mapping[str, object], ...]
    providers: tuple[Mapping[str, object], ...]


@dataclass(frozen=True)
class BootstrapReport:
    project_id: str
    project_title: str
    seeds: tuple[tuple[str, str], ...]
    providers: tuple[tuple[str, str, str], ...]
    preferred_provider_id: str
    binding_count: int = 1
    binding_item_count: int = 8
    canon_revision_count: int = 1
    projection_head_count: int = 1


def _json_object_expression(columns: Sequence[str]) -> str:
    return "JSON_OBJECT(" + ",".join(
        f"'{column}',`{column}`" for column in columns
    ) + ")"


_SOURCE_CAPABILITY_QUERY = (
    "SELECT JSON_OBJECT('version',VERSION(),'json_supported',"
    "JSON_VALID('{\"writerCore\":true}'))"
)
_SOURCE_PROJECT_QUERY = (
    f"SELECT {_json_object_expression(_LEGACY_PROJECT_COLUMNS)} "
    "FROM `projects` WHERE `title`='永乐大典' ORDER BY `id`"
)
_SOURCE_SEED_QUERY = (
    f"SELECT {_json_object_expression(_LEGACY_SEED_COLUMNS)} "
    "FROM `creative_seeds` WHERE `title` IN "
    "('永乐长明','文渊山海','典镇山河') ORDER BY `title`,`id`"
)
_SOURCE_PROVIDER_QUERY = (
    f"SELECT {_json_object_expression(_LEGACY_PROVIDER_COLUMNS)} "
    "FROM `provider_profiles` ORDER BY `created_at`,`id`"
)
SOURCE_SELECT_WHITELIST = (
    _SOURCE_CAPABILITY_QUERY,
    _SOURCE_PROJECT_QUERY,
    _SOURCE_SEED_QUERY,
    _SOURCE_PROVIDER_QUERY,
)

_BLOCKED_MYSQL_ENVIRONMENT_KEYS = {
    "LIBMYSQL_PLUGIN_DIR",
    "LIBMYSQL_ENABLE_CLEARTEXT_PLUGIN",
}


def _source_client_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("MYSQL_")
        and key.upper() not in _BLOCKED_MYSQL_ENVIRONMENT_KEYS
    }


def _run_source_select(
    mysql_client: str,
    query: str,
    *,
    login_path: str,
    source_database: str,
    runner: Callable[..., object],
) -> tuple[Mapping[str, object], ...]:
    if query not in SOURCE_SELECT_WHITELIST:
        raise BootstrapSourceError("Refusing a non-whitelisted legacy query")
    result = runner(
        [
            mysql_client,
            "--no-defaults",
            f"--login-path={login_path}",
            f"--database={source_database}",
            "--default-character-set=utf8mb4",
            "--batch",
            "--raw",
            "--skip-column-names",
            "--execute",
            query,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        shell=False,
        env=_source_client_environment(),
    )
    if getattr(result, "returncode", 1) != 0:
        raise BootstrapSourceError("Legacy mysql client SELECT failed")
    rows = []
    try:
        for line in getattr(result, "stdout", "").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if type(row) is not dict:
                raise ValueError("legacy JSON row must be an object")
            rows.append(row)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise BootstrapSourceError("Legacy mysql client returned invalid JSON") from exc
    return tuple(rows)


def read_legacy_inventory(
    mysql_client: str,
    *,
    runner: Callable[..., object] = subprocess.run,
    login_path: str = "novel57-admin",
    source_database: str = "novel_creator",
) -> LegacyInventory:
    """Read one fixed source capability row and exactly three legacy tables."""
    if login_path != "novel57-admin" or source_database != "novel_creator":
        raise BootstrapSafetyError("Refusing a noncanonical legacy source boundary")
    batches = tuple(
        _run_source_select(
            mysql_client,
            query,
            login_path=login_path,
            source_database=source_database,
            runner=runner,
        )
        for query in SOURCE_SELECT_WHITELIST
    )
    capability = batches[0]
    if len(capability) != 1:
        raise BootstrapSourceError("Legacy capability SELECT returned wrong cardinality")
    version = capability[0].get("version")
    match = re.match(r"^5\.7\.(\d+)", version if isinstance(version, str) else "")
    if (
        match is None
        or int(match.group(1)) < 8
        or capability[0].get("json_supported") != 1
    ):
        raise BootstrapSourceError("Legacy source is not compatible MySQL 5.7")
    return LegacyInventory(
        source_version=version,
        projects=batches[1],
        seeds=batches[2],
        providers=batches[3],
    )


def map_legacy_inventory(source: LegacyInventory) -> _PreservedState:
    """Apply the existing V1 mappers and one approved preferred rename."""
    if type(source) is not LegacyInventory:
        raise TypeError("source must be LegacyInventory")
    if (
        len(source.projects) != 1
        or source.projects[0].get("title") != SOURCE_PROJECT_TITLE
    ):
        raise BootstrapValidationError("Bootstrap requires exactly one approved project")
    actual_seed_titles = Counter(row.get("title") for row in source.seeds)
    if (
        len(source.seeds) != 3
        or actual_seed_titles != Counter(SOURCE_SEED_TITLES)
    ):
        raise BootstrapValidationError("Bootstrap requires exactly three approved seeds")
    try:
        _require_exact_unique(source.providers, "id", "provider")
    except (KeyError, ResetValidationError) as exc:
        raise BootstrapValidationError(
            "Legacy source provider ids must be unique"
        ) from exc
    preferred_indexes = tuple(
        index for index, row in enumerate(source.providers)
        if row.get("name") == SOURCE_PREFERRED_PROVIDER_NAME
        and row.get("model") == SOURCE_PREFERRED_MODEL
    )
    if len(preferred_indexes) != 1:
        raise BootstrapValidationError(
            "Bootstrap requires exactly one approved preferred Provider/model"
        )
    preferred_index = preferred_indexes[0]
    preferred_row = source.providers[preferred_index]
    preferred_id = preferred_row.get("id")
    ordered = (
        preferred_row,
        *(row for index, row in enumerate(source.providers) if index != preferred_index),
    )
    try:
        project = _map_project(source.projects[0])
        seeds = tuple(_map_seed(row, project["id"]) for row in source.seeds)
        providers = []
        for index, row in enumerate(ordered):
            mapped = _map_provider(row, 0 if index == 0 else index * 10)
            if mapped["id"] == preferred_id:
                mapped = dict(
                    mapped,
                    name=TARGET_PREFERRED_PROVIDER_NAME,
                    model_name=TARGET_PREFERRED_MODEL,
                )
            providers.append(mapped)
        mapped_providers = tuple(providers)
        _require_exact_unique(seeds, "id", "seed")
        _require_exact_unique(mapped_providers, "id", "provider")
    except (KeyError, ResetValidationError, ValueError, TypeError) as exc:
        raise BootstrapValidationError("Legacy foundation mapping failed") from exc
    preferred = tuple(row for row in mapped_providers if row["id"] == preferred_id)
    if len(preferred) != 1:
        raise BootstrapValidationError("Mapped preferred Provider is not unique")
    return _PreservedState(
        project=project,
        seeds=seeds,
        providers=mapped_providers,
        preferred_provider=preferred[0],
    )


async def validate_mapped_state(target_session, state: _PreservedState) -> None:
    try:
        await _require_target_collation_unique(
            target_session, state.seeds, "title", "seed"
        )
        await _require_target_collation_unique(
            target_session, state.providers, "name", "provider"
        )
    except ResetValidationError as exc:
        raise BootstrapValidationError("Target collation validation failed") from exc


def build_report(state: _PreservedState) -> BootstrapReport:
    return BootstrapReport(
        project_id=str(state.project["id"]),
        project_title=str(state.project["title"]),
        seeds=tuple((str(row["id"]), str(row["title"])) for row in state.seeds),
        providers=tuple(
            (str(row["id"]), str(row["name"]), str(row["model_name"]))
            for row in state.providers
        ),
        preferred_provider_id=str(state.preferred_provider["id"]),
    )


def _receipt_value(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return "".join(
        f"\\u{ord(character):04x}"
        if unicodedata.category(character) == "Cc"
        else character
        for character in encoded
    )


def format_bootstrap_report(report: BootstrapReport) -> str:
    lines = [
        f"projects.count={_receipt_value(1)}",
        f"project.id={_receipt_value(report.project_id)}",
        f"project.title={_receipt_value(report.project_title)}",
        f"seeds.count={_receipt_value(len(report.seeds))}",
    ]
    lines.extend(
        f"seed.id={_receipt_value(seed_id)} seed.title={_receipt_value(title)}"
        for seed_id, title in report.seeds
    )
    lines.append(f"providers.count={_receipt_value(len(report.providers))}")
    lines.extend(
        f"provider.id={_receipt_value(provider_id)} "
        f"provider.name={_receipt_value(name)} "
        f"provider.model={_receipt_value(model)}"
        for provider_id, name, model in report.providers
    )
    lines.extend((
        f"preferred_provider.id={_receipt_value(report.preferred_provider_id)}",
        f"bindings.count={_receipt_value(report.binding_count)}",
        f"binding_items.count={_receipt_value(report.binding_item_count)}",
        f"canon_revisions.count={_receipt_value(report.canon_revision_count)}",
        f"projection_heads.count={_receipt_value(report.projection_head_count)}",
    ))
    return "\n".join(lines)


def _guard_target(
    database_name: str,
    *,
    execute: bool,
    confirm_bootstrap: str | None,
    product_authority: object | None,
) -> None:
    product_read_authorized = product_authority in {
        _CLI_PRODUCT_READ_AUTHORITY,
        _CLI_PRODUCT_EXECUTE_AUTHORITY,
    }
    product_execute_authorized = product_authority is _CLI_PRODUCT_EXECUTE_AUTHORITY
    try:
        _guard_database(database_name, product_read_authorized)
    except ResetSafetyError as exc:
        raise BootstrapSafetyError("Refusing unsafe bootstrap target") from exc
    if execute and not product_execute_authorized:
        raise BootstrapSafetyError(
            "Bootstrap execute requires private CLI execute authority"
        )
    if execute and confirm_bootstrap != database_name:
        raise BootstrapSafetyError("Bootstrap confirmation does not match target")


async def _assert_target_absent(target_session, database_name: str) -> None:
    existing = await target_session.fetchone(_TARGET_EXISTS_QUERY, (database_name,))
    if existing is not None:
        raise BootstrapSafetyError("Bootstrap target database must be absent")


async def _verify_foundation_state(
    target_session,
    state: _PreservedState,
) -> None:
    selected_seed = next(
        seed for seed in state.seeds if seed["title"] == "典镇山河"
    )
    checks = (
        ("projects", 1, "WHERE id=%s", (state.project["id"],)),
        ("creative_seeds", 3, "WHERE project_id=%s", (state.project["id"],)),
        ("project_selected_seeds", 1, "WHERE project_id=%s AND seed_id=%s", (
            state.project["id"], selected_seed["id"],
        )),
        ("provider_profiles", len(state.providers), "", None),
        ("task_model_bindings", 1, "WHERE project_id=%s", (state.project["id"],)),
        ("task_model_binding_items", len(TASK_KEYS), (
            "WHERE project_id=%s AND provider_id=%s AND model_name=%s"
        ), (
            state.project["id"], state.preferred_provider["id"],
            state.preferred_provider["model_name"],
        )),
        ("canon_revisions", 1, "WHERE project_id=%s AND revision_number=0", (
            state.project["id"],
        )),
        ("projection_heads", 1, (
            "WHERE project_id=%s AND canon_revision_number=0 "
            "AND projection_revision_number=0"
        ), (state.project["id"],)),
    )
    for table, expected, where, parameters in checks:
        row = await target_session.fetchone(
            f"SELECT COUNT(*) AS count FROM {table} {where}".strip(),
            parameters,
        )
        if row is None or row.get("count") != expected:
            raise BootstrapError(f"Bootstrap verification failed for {table}")


async def bootstrap_writer_core_product(
    target_session,
    *,
    database_name: str,
    source_loader: Callable[[], LegacyInventory],
    execute: bool = False,
    confirm_bootstrap: str | None = None,
    output: Callable[[str], None] = print,
    now_ms: Callable[[], int] | None = None,
    id_factory: Callable[[], str] | None = None,
    initializer: Callable[..., object] = initialize_database,
    inserter: Callable[..., object] = _insert_preserved_state,
    _product_authority: object | None = None,
) -> BootstrapReport:
    """Preflight or initialize one absent target from an in-memory source snapshot."""
    _guard_target(
        database_name,
        execute=execute,
        confirm_bootstrap=confirm_bootstrap,
        product_authority=_product_authority,
    )
    try:
        await _verify_reset_server_capabilities(target_session)
    except ResetValidationError as exc:
        raise BootstrapValidationError("Target MySQL capability validation failed") from exc
    await _assert_target_absent(target_session, database_name)
    state = map_legacy_inventory(source_loader())
    await validate_mapped_state(target_session, state)
    report = build_report(state)
    if not execute:
        output(format_bootstrap_report(report))
        return report

    acquired = False
    ddl_owned = False
    transaction_started = False
    body_error: BaseException | None = None
    cleanup_errors: list[BaseException] = []
    try:
        lock = await target_session.fetchone(
            "SELECT GET_LOCK(%s,%s) AS acquired",
            (BOOTSTRAP_LOCK_NAME, 30),
        )
        if lock is None or lock.get("acquired") != 1:
            raise BootstrapError("Could not acquire bootstrap advisory lock")
        acquired = True
        await _assert_target_absent(target_session, database_name)
        await target_session.execute(
            f"CREATE DATABASE `{database_name}` CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_0900_ai_ci"
        )
        ddl_owned = True
        timestamp = (now_ms or (lambda: int(time.time() * 1000)))()
        await initializer(target_session, database_name, database_name, timestamp)
        await target_session.execute("START TRANSACTION")
        transaction_started = True
        await inserter(
            target_session,
            state,
            now_ms=timestamp,
            id_factory=id_factory or (lambda: str(uuid4())),
        )
        await _verify_foundation_state(target_session, state)
        await _verify_empty_tables(target_session)
        await target_session.execute("COMMIT")
        transaction_started = False
    except BaseException as exc:
        body_error = exc
        if transaction_started:
            try:
                await target_session.execute("ROLLBACK")
            except BaseException as rollback_error:
                cleanup_errors.append(rollback_error)
        if ddl_owned:
            try:
                _guard_target(
                    database_name,
                    execute=True,
                    confirm_bootstrap=database_name,
                    product_authority=_product_authority,
                )
                await target_session.execute(
                    f"DROP DATABASE IF EXISTS `{database_name}`"
                )
            except BaseException as drop_error:
                cleanup_errors.append(drop_error)
    finally:
        if acquired:
            try:
                released = await target_session.fetchone(
                    "SELECT RELEASE_LOCK(%s) AS released",
                    (BOOTSTRAP_LOCK_NAME,),
                )
                if released is None or released.get("released") != 1:
                    raise BootstrapError("Bootstrap advisory lock was not released")
            except BaseException as release_error:
                cleanup_errors.append(release_error)

    if body_error is not None:
        if cleanup_errors:
            raise BaseExceptionGroup(
                "Bootstrap failed and cleanup also failed",
                [body_error, *cleanup_errors],
            ) from body_error
        raise body_error
    if cleanup_errors:
        if len(cleanup_errors) == 1:
            raise cleanup_errors[0]
        raise BaseExceptionGroup("Bootstrap cleanup failed", cleanup_errors)
    output(format_bootstrap_report(report))
    return report


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bootstrap Writer Core product from legacy MySQL 5.7"
    )
    parser.add_argument("--mysql-client", required=True)
    parser.add_argument(
        "--source-login-path",
        choices=("novel57-admin",),
        default="novel57-admin",
    )
    parser.add_argument(
        "--source-database",
        choices=("novel_creator",),
        default="novel_creator",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-bootstrap")
    return parser


async def run_cli(
    argv: Sequence[str] | None = None,
    *,
    connection_factory: Callable[..., object] | None = None,
    connection_config: Mapping[str, object] | None = None,
    source_reader: Callable[..., LegacyInventory] = read_legacy_inventory,
    output: Callable[[str], None] = print,
) -> int:
    args = _argument_parser().parse_args(argv)
    if connection_config is None:
        from backend.config import require_mysql_config

        connection_config = require_mysql_config()
    database_name = connection_config.get("db")
    if not isinstance(database_name, str):
        raise BootstrapSafetyError("Configured target database is invalid")
    factory = connection_factory or _default_connection_factory
    target_session = await factory(connection_config)
    body_error: BaseException | None = None
    try:
        source_loader = lambda: source_reader(
            args.mysql_client,
            login_path=args.source_login_path,
            source_database=args.source_database,
        )
        await bootstrap_writer_core_product(
            target_session,
            database_name=database_name,
            source_loader=source_loader,
            execute=args.execute,
            confirm_bootstrap=args.confirm_bootstrap,
            output=output,
            _product_authority=(
                _CLI_PRODUCT_EXECUTE_AUTHORITY
                if args.execute
                else _CLI_PRODUCT_READ_AUTHORITY
            ),
        )
    except BaseException as exc:
        body_error = exc
    close_error: BaseException | None = None
    try:
        await target_session.close()
    except BaseException as exc:
        close_error = exc
    if body_error is not None and close_error is not None:
        raise BaseExceptionGroup(
            "Bootstrap CLI body and target close both failed",
            [body_error, close_error],
        ) from body_error
    if body_error is not None:
        raise body_error
    if close_error is not None:
        raise close_error
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(run_cli(argv))
    except SystemExit:
        raise
    except BaseException:
        print("Writer Core product bootstrap failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
