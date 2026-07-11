"""One-time preserve-and-reset command for the Writer Core V1 schema.

The reset reads only the three explicitly preserved legacy tables.  It does
not migrate legacy writing, Canon, planning, settings, audit or QA content.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
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
_CLI_PRODUCT_READ_AUTHORITY = object()
_CLI_PRODUCT_EXECUTE_AUTHORITY = object()

_LEGACY_PROJECT_COLUMNS = (
    "id", "title", "genre", "description", "target_words",
    "target_chapters", "current_chapter_num", "status", "created_at", "updated_at",
)
_LEGACY_SEED_COLUMNS = (
    "id", "project_id", "title", "genre", "logline", "protagonist", "desire",
    "core_conflict", "world_pressure", "opening_hook", "emotional_promise",
    "differentiation", "style_target", "source", "risk_notes", "ending_anchor",
    "status", "created_at",
)
_LEGACY_PROVIDER_COLUMNS = (
    "id", "name", "provider_type", "base_url", "api_key", "model", "stream",
    "max_context_tokens", "max_output_tokens", "temperature", "top_p",
    "supports_json", "supports_streaming", "notes", "thinking", "created_at",
    "updated_at",
)
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
_SEED_PREMISE_MAPPING = (
    ("genre", "genre"),
    ("logline", "logline"),
    ("protagonist", "protagonist"),
    ("desire", "desire"),
    ("coreConflict", "core_conflict"),
    ("worldPressure", "world_pressure"),
    ("openingHook", "opening_hook"),
    ("emotionalPromise", "emotional_promise"),
    ("differentiation", "differentiation"),
    ("styleTarget", "style_target"),
    ("source", "source"),
    ("riskNotes", "risk_notes"),
    ("endingAnchor", "ending_anchor"),
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


def _text(value: object, field_name: str, *, default: str = "", max_length: int) -> str:
    if value is None:
        value = default
    if not isinstance(value, str):
        raise ResetValidationError(f"Legacy {field_name} must be text")
    if len(value) > max_length:
        raise ResetValidationError(
            f"Legacy {field_name} exceeds the Writer Core V1 length limit"
        )
    return value


def _identifier(value: object, field_name: str) -> str:
    result = _text(value, field_name, max_length=36)
    if not result:
        raise ResetValidationError(f"Legacy {field_name} must not be empty")
    return result


def _integer(
    value: object,
    field_name: str,
    *,
    default: int | None = None,
    minimum: int | None = None,
) -> int:
    if value is None:
        value = default
    if type(value) is not int:
        raise ResetValidationError(f"Legacy {field_name} must be an integer")
    if value < -(2**63) or value > 2**63 - 1:
        raise ResetValidationError(f"Legacy {field_name} exceeds BIGINT range")
    if minimum is not None and value < minimum:
        raise ResetValidationError(
            f"Legacy {field_name} violates the Writer Core V1 minimum"
        )
    return value


def _flag(value: object, field_name: str, *, default: int = 1) -> int:
    if value is None:
        return default
    if type(value) is not int or value not in (0, 1):
        raise ResetValidationError(f"Legacy {field_name} must be 0 or 1")
    return value


def _decimal(value: object, field_name: str, *, default: str) -> Decimal:
    if value is None:
        value = default
    if isinstance(value, bool):
        raise ResetValidationError(f"Legacy {field_name} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ResetValidationError(f"Legacy {field_name} must be numeric") from exc
    if not result.is_finite():
        raise ResetValidationError(f"Legacy {field_name} must be finite")
    result = result.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    if result < Decimal("-99.999") or result > Decimal("99.999"):
        raise ResetValidationError(
            f"Legacy {field_name} exceeds DECIMAL(5,3) range"
        )
    return result


def _json_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
        return json.dumps(
            decoded,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ResetValidationError(f"Legacy {field_name} must be valid JSON") from exc


def _require_exact_unique(
    rows: Sequence[Mapping[str, object]], field: str, noun: str,
) -> None:
    seen: set[object] = set()
    for row in rows:
        value = row[field]
        if value in seen:
            raise ResetValidationError(f"Legacy {noun} {field} values must be unique")
        seen.add(value)


async def _require_target_collation_unique(
    admin_session,
    rows: Sequence[Mapping[str, object]],
    field: str,
    noun: str,
) -> None:
    for index, row in enumerate(rows):
        for other in rows[index + 1:]:
            comparison = await admin_session.fetchone(
                """SELECT (
                         CONVERT(%s USING utf8mb4) COLLATE utf8mb4_0900_ai_ci =
                         CONVERT(%s USING utf8mb4) COLLATE utf8mb4_0900_ai_ci
                       ) AS collation_conflict""",
                (row[field], other[field]),
            )
            if (comparison or {}).get("collation_conflict") != 1:
                continue
            raise ResetValidationError(
                f"Legacy {noun} {field} values conflict under target collation"
            )


async def _verify_reset_server_capabilities(admin_session) -> None:
    version_row = await admin_session.fetchone("SELECT VERSION() AS version")
    version = (version_row or {}).get("version")
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version or "")
    if match is None:
        raise ResetValidationError("Could not verify the MySQL server version")
    version_tuple = tuple(int(part) for part in match.groups())
    if version_tuple[0] != 8 or version_tuple < (8, 0, 16):
        raise ResetValidationError(
            "Writer Core reset requires MySQL 8 with enforced CHECK constraints"
        )
    collation = await admin_session.fetchone(
        """SELECT COLLATION_NAME FROM information_schema.COLLATIONS
           WHERE COLLATION_NAME='utf8mb4_0900_ai_ci'"""
    )
    if (collation or {}).get("COLLATION_NAME") != "utf8mb4_0900_ai_ci":
        raise ResetValidationError(
            "MySQL server does not provide required utf8mb4_0900_ai_ci collation"
        )
    json_support = await admin_session.fetchone(
        "SELECT JSON_VALID(%s) AS json_supported", ('{"writerCore":true}',)
    )
    if (json_support or {}).get("json_supported") != 1:
        raise ResetValidationError("MySQL server JSON capability check failed")
    check_support = await admin_session.fetchone(
        "SELECT COUNT(*) AS count FROM information_schema.CHECK_CONSTRAINTS"
    )
    if type((check_support or {}).get("count")) is not int:
        raise ResetValidationError("MySQL server CHECK capability check failed")


def _map_project(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": _identifier(row["id"], "project.id"),
        "title": _text(row["title"], "project.title", max_length=200),
        "genre": _text(row["genre"], "project.genre", max_length=120),
        "description": _text(
            row["description"], "project.description", max_length=65_535
        ),
        "target_words": _integer(
            row["target_words"], "project.target_words", default=100_000, minimum=1
        ),
        "target_chapters": _integer(
            row["target_chapters"], "project.target_chapters", default=100, minimum=1
        ),
        # Legacy progress/status are derived writing state and are intentionally reset.
        "status": "drafting",
        "current_chapter": 0,
        "created_at": _integer(row["created_at"], "project.created_at"),
        "updated_at": _integer(row["updated_at"], "project.updated_at"),
    }


def _map_seed(row: Mapping[str, object], project_id: str) -> dict[str, object]:
    seed_id = _identifier(row["id"], "seed.id")
    owner_id = _identifier(row["project_id"], "seed.project_id")
    if owner_id != project_id:
        raise ResetValidationError("Legacy requested seed belongs to another project")
    title = _text(row["title"], "seed.title", max_length=200)
    premise = {
        target: row[source]
        for target, source in _SEED_PREMISE_MAPPING
    }
    premise_json = json.dumps(
        premise,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    envelope = json.dumps(
        {"title": title, "premise": premise},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return {
        "id": seed_id,
        "project_id": owner_id,
        "title": title,
        "premise_json": premise_json,
        "content_hash": sha256(envelope.encode("utf-8")).hexdigest(),
        "status": "selected" if title == SELECTED_SEED_TITLE else "candidate",
        "created_at": _integer(row["created_at"], "seed.created_at"),
    }


def _map_provider(row: Mapping[str, object], sort_order: int) -> dict[str, object]:
    return {
        "id": _identifier(row["id"], "provider.id"),
        "name": _text(row["name"], "provider.name", max_length=120),
        "provider_type": _text(
            row["provider_type"], "provider.provider_type",
            default="openai-compatible", max_length=64,
        ),
        "model_name": _text(row["model"], "provider.model", max_length=160),
        "base_url": _text(row["base_url"], "provider.base_url", max_length=2048),
        "api_key": _text(row["api_key"], "provider.api_key", max_length=65_535),
        "enabled": 1,
        "sort_order": sort_order,
        "stream": _flag(row["stream"], "provider.stream"),
        "max_context_tokens": _integer(
            row["max_context_tokens"], "provider.max_context_tokens",
            default=200_000, minimum=1,
        ),
        "max_output_tokens": _integer(
            row["max_output_tokens"], "provider.max_output_tokens",
            default=4_096, minimum=1,
        ),
        "temperature": _decimal(
            row["temperature"], "provider.temperature", default="0.8"
        ),
        "top_p": _decimal(row["top_p"], "provider.top_p", default="0.9"),
        "supports_json": _flag(row["supports_json"], "provider.supports_json"),
        "supports_streaming": _flag(
            row["supports_streaming"], "provider.supports_streaming"
        ),
        "notes": _text(row["notes"], "provider.notes", max_length=65_535),
        "thinking": _json_text(row["thinking"], "provider.thinking"),
        "created_at": _integer(row["created_at"], "provider.created_at"),
        "updated_at": _integer(row["updated_at"], "provider.updated_at"),
    }


async def _load_preserved_state(admin_session, database_name: str, request: ResetRequest):
    project_rows = await admin_session.fetchall(
        f"SELECT {', '.join(_LEGACY_PROJECT_COLUMNS)} "
        f"FROM {_qualified(database_name, 'projects')} WHERE title=%s",
        (request.project_title,),
    )
    if len(project_rows) != 1:
        raise ResetValidationError(
            "Reset requires exactly one project with the requested title"
        )
    project = _map_project(project_rows[0])

    placeholders = ",".join(("%s",) * len(request.seed_titles))
    seed_rows = await admin_session.fetchall(
        f"SELECT {', '.join(_LEGACY_SEED_COLUMNS)} "
        f"FROM {_qualified(database_name, 'creative_seeds')} "
        f"WHERE project_id=%s AND title IN ({placeholders}) ORDER BY title, id",
        (project["id"], *request.seed_titles),
    )
    actual_titles = Counter(row["title"] for row in seed_rows)
    if len(seed_rows) != 3 or actual_titles != Counter(request.seed_titles):
        raise ResetValidationError(
            "Reset requires exactly one row for each requested seed title"
        )

    mapped_seeds = tuple(_map_seed(row, project["id"]) for row in seed_rows)
    _require_exact_unique(mapped_seeds, "id", "seed")
    await _require_target_collation_unique(
        admin_session, mapped_seeds, "title", "seed",
    )

    provider_rows = await admin_session.fetchall(
        f"SELECT {', '.join(_LEGACY_PROVIDER_COLUMNS)} "
        f"FROM {_qualified(database_name, 'provider_profiles')} "
        "ORDER BY created_at, id"
    )
    preferred_legacy = tuple(
        row for row in provider_rows
        if row["name"] == request.preferred_provider_name
        and row["model"] == request.preferred_model
    )
    if len(preferred_legacy) != 1:
        raise ResetValidationError(
            "Reset requires exactly one preferred legacy Provider/model row"
        )
    preferred_id = preferred_legacy[0]["id"]
    ordered_provider_rows = (
        preferred_legacy[0],
        *(row for row in provider_rows if row["id"] != preferred_id),
    )
    mapped_providers = tuple(
        _map_provider(row, 0 if index == 0 else index * 10)
        for index, row in enumerate(ordered_provider_rows)
    )
    _require_exact_unique(mapped_providers, "id", "provider")
    await _require_target_collation_unique(
        admin_session, mapped_providers, "name", "provider",
    )
    preferred = tuple(
        row for row in mapped_providers
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
        seeds=mapped_seeds,
        providers=mapped_providers,
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


async def _recover_failed_commit(admin_session, commit_error: BaseException) -> None:
    """Best-effort transaction/lock cleanup without reusing an uncertain session."""
    failures = [commit_error]
    try:
        await admin_session.execute("ROLLBACK")
    except BaseException as rollback_error:
        failures.append(rollback_error)
    try:
        await _release_lock(admin_session)
    except BaseException as release_error:
        failures.append(release_error)
    try:
        await admin_session.close()
    except BaseException as close_error:
        failures.append(close_error)
    if len(failures) > 1:
        raise BaseExceptionGroup(
            "Writer Core COMMIT failed and recovery also failed",
            failures,
        ) from commit_error
    raise commit_error


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
    product_read_authorized = bool(
        allow_product_database
        and _product_authority in {
            _CLI_PRODUCT_READ_AUTHORITY,
            _CLI_PRODUCT_EXECUTE_AUTHORITY,
        }
    )
    product_execute_authorized = bool(
        allow_product_database
        and _product_authority is _CLI_PRODUCT_EXECUTE_AUTHORITY
    )
    _validate_target(database_name, confirm_reset, product_read_authorized)
    if execute and database_name == PRODUCT_DATABASE and not product_execute_authorized:
        raise ResetSafetyError(
            "Refusing product database reset without explicit CLI execute authorization"
        )

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
        await _verify_reset_server_capabilities(admin_session)
        state = await _load_preserved_state(admin_session, database_name, request)

        _guard_database(database_name, product_execute_authorized)
        ddl_started = True
        await admin_session.execute(f"DROP DATABASE `{database_name}`")
        _guard_database(database_name, product_execute_authorized)
        await admin_session.execute(
            f"CREATE DATABASE `{database_name}` CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_0900_ai_ci"
        )
        _guard_database(database_name, product_execute_authorized)
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
            try:
                await admin_session.execute("COMMIT")
            except BaseException as commit_error:
                # Recovery explicitly releases the named lock before closing; an
                # aiomysql transport close alone does not synchronously prove the
                # server has processed COM_QUIT and released the lock.
                acquired = False
                await _recover_failed_commit(admin_session, commit_error)
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
        args.database == PRODUCT_DATABASE
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
            _product_authority=(
                _CLI_PRODUCT_EXECUTE_AUTHORITY
                if args.execute
                else _CLI_PRODUCT_READ_AUTHORITY
            ),
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
