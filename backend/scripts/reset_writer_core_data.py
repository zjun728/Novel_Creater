"""Reset derived Writer Core data inside the exact current development schema."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
import re
import sys
import time
from typing import Awaitable, Callable, Mapping, Sequence
from uuid import uuid4

from backend.domain.json_contracts import canonical_hash
from backend.domain.model_bindings import BindingItem, BindingRevision, TASK_KEYS
from backend.schema_manifest import created_table_names, manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from backend.services.project_lifecycle import ProjectLifecycleService
from backend.services.projections import build_projection_bundle


PRODUCT_DATABASE = "novel_creator"
PRODUCT_HOST = "127.0.0.1"
PRODUCT_PORT = 3307
RESET_LOCK_NAME = "novel_creator_writer_core_reset"
SELECTED_SEED_TITLE = "典镇山河"
_DISPOSABLE_DATABASE = re.compile(r"novel_creator_test_[a-f0-9]{32}\Z")
_CLI_PRODUCT_READ_AUTHORITY = object()
_CLI_PRODUCT_EXECUTE_AUTHORITY = object()
_SCHEMA_REINITIALIZATION_GUIDANCE = (
    "Reset requires the exact current development schema. Reinitialize an empty "
    "database with `python -m backend.scripts.initialize_database`."
)

# Reverse dependency order for data that begins after the approved project,
# seed-selection, provider, and model-binding foundation.
_DERIVED_PROJECT_TABLES = (
    "reference_uses",
    "final_chapters",
    "finalization_records",
    "finalization_change_sets",
    "draft_candidates",
    "working_drafts",
    "chapter_sessions",
    "chapter_outline_confirmation_requests",
    "project_chapter_outline_heads",
    "chapter_outline_generation_attempts",
    "chapter_outline_drafts",
    "chapter_outline_revisions",
    "planning_confirmation_requests",
    "project_planning_heads",
    "planning_generation_attempts",
    "planning_drafts",
    "planning_revisions",
    "bible_confirmation_requests",
    "project_bible_heads",
    "bible_generation_attempts",
    "project_bible_drafts",
    "creation_bible_revisions",
    "creation_contract_engine_refs",
    "contract_confirmation_requests",
    "project_contract_heads",
    "style_contracts",
    "creation_contracts",
    "project_contract_drafts",
    "story_engine_options",
    "story_engine_batches",
    "style_trial_requests",
    "style_trial_attempts",
    "asset_recommendation_requests",
    "asset_recommendation_attempts",
    "seed_inspiration_requests",
    "seed_inspiration_attempts",
    "market_analyses",
    "current_state_projections",
    "memory_views",
    "arc_projections",
    "plot_thread_projections",
    "canon_events",
    "entity_aliases",
    "canon_entities",
    "projection_heads",
    "canon_revisions",
)
_CASCADED_DERIVED_TABLES = (
    "style_contract_template_refs",
    "creation_contract_experience_refs",
    "creation_contract_corpus_refs",
    "creation_contract_corpus_fragment_refs",
)


class ResetError(RuntimeError):
    """Base class for safe reset failures."""


class ResetSafetyError(ResetError):
    """The requested target or confirmation is unsafe."""


class ResetValidationError(ResetError):
    """The current database does not match the reset contract."""


class ResetPartialStateError(ResetError):
    """The reset failed and cleanup could not prove a clean rollback."""


class ResetCommittedCleanupError(ResetError):
    """The reset committed, but advisory-lock cleanup failed."""


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
        if (
            type(self.seed_titles) is not tuple
            or len(self.seed_titles) != 3
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
class _Foundation:
    project_id: str
    project_title: str
    seeds: tuple[tuple[str, str, int, str], ...]
    providers: tuple[tuple[str, str, str, bool], ...]
    selected_seed_id: str
    selected_seed_title: str
    selection_revision: int
    binding_revision: int


@dataclass(frozen=True)
class ResetReport:
    mode: str
    executed: bool
    database_name: str
    project_id: str
    project_title: str
    seeds: tuple[tuple[str, str], ...]
    providers: tuple[tuple[str, str, str, bool], ...]
    schema_version: str
    manifest_hash: str
    table_names: tuple[str, ...]
    cleared_tables: tuple[str, ...]
    verified: bool


def _guard_database(database_name: str, allow_product_database: bool) -> None:
    if not isinstance(database_name, str) or not database_name:
        raise ResetSafetyError("Database name must be non-empty")
    if database_name == PRODUCT_DATABASE:
        if not allow_product_database:
            raise ResetSafetyError("Refusing product database without explicit CLI authorization")
        return
    if _DISPOSABLE_DATABASE.fullmatch(database_name) is None:
        raise ResetSafetyError("Reset target must be a disposable test database")


def _validate_target(
    database_name: str,
    confirm_reset: str,
    allow_product_database: bool,
) -> None:
    if database_name != confirm_reset:
        raise ResetSafetyError("Database confirmation does not match reset target")
    _guard_database(database_name, allow_product_database)


async def _classify_reset_source(admin_session, database_name: str) -> str:
    """Accept only the exact current manifest before reading foundation rows."""

    table_rows = await admin_session.fetchall(
        "SELECT TABLE_NAME FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME",
        (database_name,),
    )
    tables = {row["TABLE_NAME"] for row in table_rows}
    metadata = None
    if "schema_metadata" in tables:
        metadata = await admin_session.fetchone(
            f"SELECT schema_version,manifest_hash FROM `{database_name}`."
            "`schema_metadata` WHERE singleton_id=1"
        )
    if (
        tables != set(created_table_names())
        or metadata
        != {
            "schema_version": EXPECTED_SCHEMA_VERSION,
            "manifest_hash": manifest_hash(),
        }
    ):
        raise ResetValidationError(_SCHEMA_REINITIALIZATION_GUIDANCE)
    return "current"


async def _verify_selected_database(admin_session, database_name: str) -> None:
    row = await admin_session.fetchone("SELECT DATABASE() AS database_name")
    if row != {"database_name": database_name}:
        raise ResetSafetyError(
            "Selected database identity does not match the explicit reset target"
        )


async def _load_current_foundation(
    admin_session,
    database_name: str,
    request: ResetRequest,
) -> _Foundation:
    projects = await admin_session.fetchall(
        f"SELECT id,title,status,archived_at FROM `{database_name}`.`projects`"
    )
    if len(projects) != 1:
        raise ResetValidationError("Reset requires exactly one foundation project")
    project = projects[0]
    if (
        project.get("title") != request.project_title
        or project.get("archived_at") is not None
    ):
        raise ResetValidationError("Reset foundation project must be the expected active project")
    project_id = str(project["id"])

    seed_rows = await admin_session.fetchall(
        f"""SELECT seed.id,
                   JSON_UNQUOTE(JSON_EXTRACT(revision.payload_json,'$.title'))
                     AS title,
                   head.revision,head.content_hash
            FROM `{database_name}`.`creative_seeds` seed
            JOIN `{database_name}`.`creative_seed_heads` head
              ON head.seed_id=seed.id
            JOIN `{database_name}`.`creative_seed_revisions` revision
              ON revision.seed_id=head.seed_id
             AND revision.id=head.revision_id
             AND revision.revision=head.revision
             AND revision.content_hash=head.content_hash
            WHERE seed.project_id=%s
            ORDER BY title,seed.id""",
        (project_id,),
    )
    if (
        len(seed_rows) != 3
        or {row["title"] for row in seed_rows} != set(request.seed_titles)
    ):
        raise ResetValidationError("Reset requires the exact three approved seed heads")

    selection = await admin_session.fetchone(
        f"""SELECT selected.seed_id,payload.title,selected.selection_revision
            FROM `{database_name}`.`project_selected_seeds` selected
            JOIN `{database_name}`.`creative_seed_revisions` revision
              ON revision.id=selected.seed_revision_id
             AND revision.content_hash=selected.seed_hash
            JOIN JSON_TABLE(
              revision.payload_json,
              '$' COLUMNS(title VARCHAR(255) PATH '$.title')
            ) payload
            WHERE selected.project_id=%s""",
        (project_id,),
    )
    if selection is None or selection.get("title") != SELECTED_SEED_TITLE:
        raise ResetValidationError("Reset requires the approved selected seed")

    providers = await admin_session.fetchall(
        f"""SELECT id,name,model_name,enabled,lifecycle_status,deleted_at
            FROM `{database_name}`.`provider_profiles`
            ORDER BY sort_order,id"""
    )
    if not providers or any(
        not isinstance(row.get("id"), str)
        or not row["id"]
        or not isinstance(row.get("name"), str)
        or not row["name"]
        or not isinstance(row.get("model_name"), str)
        or not row["model_name"]
        or row.get("enabled") not in (0, 1)
        or row.get("lifecycle_status") != "active"
        or row.get("deleted_at") is not None
        for row in providers
    ):
        raise ResetValidationError(
            "Reset foundation Provider rows must all be complete, active, and non-deleted"
        )
    preferred = [
        row
        for row in providers
        if row.get("name") == request.preferred_provider_name
        and row.get("model_name") == request.preferred_model
        and row.get("enabled") == 1
    ]
    if len(preferred) != 1:
        raise ResetValidationError("Reset requires the configured preferred provider")

    binding_rows = await admin_session.fetchall(
        f"""SELECT head.revision,head.binding_revision_id,
                   head.content_hash AS binding_hash,
                   revision.source_project_id,
                   item.task_key,item.resolution_status,item.provider_id,
                   item.provider_name_snapshot,item.model_name_snapshot,
                   item.item_hash,
                   provider.name AS provider_name,
                   provider.model_name AS provider_model,
                   provider.enabled AS provider_enabled,
                   provider.lifecycle_status AS provider_lifecycle,
                   provider.deleted_at AS provider_deleted_at
            FROM `{database_name}`.`project_model_binding_heads` head
            JOIN `{database_name}`.`project_model_binding_revisions` revision
              ON revision.project_id=head.project_id
             AND revision.id=head.binding_revision_id
             AND revision.revision=head.revision
             AND revision.content_hash=head.content_hash
            JOIN `{database_name}`.`project_model_binding_items` item
              ON item.binding_revision_id=head.binding_revision_id
            LEFT JOIN `{database_name}`.`provider_profiles` provider
              ON provider.id=item.provider_id
            WHERE head.project_id=%s
            ORDER BY FIELD(item.task_key,'seed','planning','writing','audit',
                           'summary','extraction','polish','market')""",
        (project_id,),
    )
    if tuple(row.get("task_key") for row in binding_rows) != TASK_KEYS:
        raise ResetValidationError(
            "Reset requires the exact model binding task closed set"
        )
    try:
        binding_items = tuple(
            BindingItem.model_validate(
                {
                    "task_key": row.get("task_key"),
                    "resolution_status": row.get("resolution_status"),
                    "provider_id": row.get("provider_id"),
                    "provider_name_snapshot": row.get("provider_name_snapshot"),
                    "model_name_snapshot": row.get("model_name_snapshot"),
                },
                strict=True,
            )
            for row in binding_rows
        )
        binding_revision = int(binding_rows[0]["revision"])
        binding = BindingRevision(
            project_id=project_id,
            revision=binding_revision,
            items=binding_items,
        )
    except (KeyError, TypeError, ValueError):
        raise ResetValidationError(
            "Reset requires the exact model binding task closed set"
        ) from None
    expected_binding_hash = canonical_hash(binding)
    if any(
        item.resolution_status != "bound"
        or item.provider_name_snapshot != request.preferred_provider_name
        or item.model_name_snapshot != request.preferred_model
        or row.get("provider_name") != item.provider_name_snapshot
        or row.get("provider_model") != item.model_name_snapshot
        or row.get("provider_enabled") != 1
        or row.get("provider_lifecycle") != "active"
        or row.get("provider_deleted_at") is not None
        or row.get("item_hash") != canonical_hash(item)
        or row.get("binding_hash") != expected_binding_hash
        or row.get("source_project_id") is not None
        for row, item in zip(binding_rows, binding_items, strict=True)
    ):
        raise ResetValidationError(
            "Reset requires every task to use the bound preferred provider"
        )

    return _Foundation(
        project_id=project_id,
        project_title=str(project["title"]),
        seeds=tuple(
            (
                str(row["id"]),
                str(row["title"]),
                int(row["revision"]),
                str(row["content_hash"]),
            )
            for row in seed_rows
        ),
        providers=tuple(
            (
                str(row["id"]),
                str(row["name"]),
                str(row["model_name"]),
                row["enabled"] == 1,
            )
            for row in providers
        ),
        selected_seed_id=str(selection["seed_id"]),
        selected_seed_title=str(selection["title"]),
        selection_revision=int(selection["selection_revision"]),
        binding_revision=binding_revision,
    )


def _report(
    database_name: str,
    foundation: _Foundation,
    *,
    executed: bool,
) -> ResetReport:
    return ResetReport(
        mode="execute" if executed else "dry-run",
        executed=executed,
        database_name=database_name,
        project_id=foundation.project_id,
        project_title=foundation.project_title,
        seeds=tuple((seed_id, title) for seed_id, title, _, _ in foundation.seeds),
        providers=foundation.providers,
        schema_version=EXPECTED_SCHEMA_VERSION,
        manifest_hash=manifest_hash(),
        table_names=created_table_names(),
        cleared_tables=(
            _DERIVED_PROJECT_TABLES + _CASCADED_DERIVED_TABLES
        ),
        verified=executed,
    )


def format_reset_report(report: ResetReport) -> str:
    """Render an allowlisted JSON receipt that never contains provider secrets."""

    return json.dumps(
        {
            "mode": report.mode,
            "database": report.database_name,
            "project": {"id": report.project_id, "title": report.project_title},
            "seeds": [
                {"id": seed_id, "title": title}
                for seed_id, title in report.seeds
            ],
            "providers": [
                {"id": row[0], "name": row[1], "model": row[2], "enabled": row[3]}
                for row in report.providers
            ],
            "schema": {
                "version": report.schema_version,
                "manifestHash": report.manifest_hash,
                "tables": list(report.table_names),
            },
            "reset": {
                "clearedTables": list(report.cleared_tables),
                "heads": {
                    "contract": 0,
                    "bible": 0,
                    "planning": 0,
                    "outlineCount": 0,
                    "canon": 0,
                    "projection": 0,
                },
                "verified": report.verified,
            },
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


async def _clear_derived_state(
    admin_session,
    foundation: _Foundation,
    *,
    now_ms: int,
    id_factory: Callable[[], str],
) -> None:
    project_id = foundation.project_id
    for table_name in _DERIVED_PROJECT_TABLES:
        await admin_session.execute(
            f"DELETE FROM {table_name} WHERE project_id=%s",
            (project_id,),
        )
    empty_hash = build_projection_bundle(0, ()).content_hash
    await admin_session.execute(
        """INSERT INTO canon_revisions
           (id,project_id,revision_number,parent_revision_number,idempotency_key,
            source_type,source_id,content_hash,created_at)
           VALUES (%s,%s,0,0,%s,'bootstrap',NULL,%s,%s)""",
        (
            id_factory(),
            project_id,
            ProjectLifecycleService.bootstrap_idempotency_key(project_id),
            empty_hash,
            now_ms,
        ),
    )
    await admin_session.execute(
        """INSERT INTO projection_heads
           (project_id,canon_revision_number,projection_revision_number,
            content_hash,updated_at) VALUES (%s,0,0,%s,%s)""",
        (project_id, empty_hash, now_ms),
    )
    await admin_session.execute(
        """INSERT INTO project_contract_heads
           (project_id,revision,creation_contract_id,style_contract_id,
            creation_hash,style_hash,updated_at)
           VALUES (%s,0,NULL,NULL,NULL,NULL,%s)""",
        (project_id, now_ms),
    )
    await admin_session.execute(
        """INSERT INTO project_bible_heads
           (project_id,revision,bible_revision_id,content_hash,updated_at)
           VALUES (%s,0,NULL,NULL,%s)""",
        (project_id, now_ms),
    )
    await admin_session.execute(
        """INSERT INTO project_planning_heads
           (project_id,revision,planning_revision_id,content_hash,updated_at)
           VALUES (%s,0,NULL,NULL,%s)""",
        (project_id, now_ms),
    )
    await admin_session.execute(
        """UPDATE projects
           SET status='drafting',current_chapter=0,updated_at=%s
           WHERE id=%s""",
        (now_ms, project_id),
    )


async def _verify_reset_state(admin_session, foundation: _Foundation) -> None:
    project_id = foundation.project_id
    for table_name in _DERIVED_PROJECT_TABLES:
        if table_name in {
            "project_contract_heads",
            "project_bible_heads",
            "project_planning_heads",
            "canon_revisions",
            "projection_heads",
        }:
            continue
        row = await admin_session.fetchone(
            f"SELECT COUNT(*) AS count FROM {table_name} WHERE project_id=%s",
            (project_id,),
        )
        if row is None or row["count"] != 0:
            raise ResetValidationError(f"Derived rows remain in {table_name}")
    for table_name in _CASCADED_DERIVED_TABLES:
        row = await admin_session.fetchone(
            f"SELECT COUNT(*) AS count FROM {table_name}"
        )
        if row is None or row["count"] != 0:
            raise ResetValidationError(f"Derived rows remain in {table_name}")
    head_checks = (
        ("project_contract_heads", "revision"),
        ("project_bible_heads", "revision"),
        ("project_planning_heads", "revision"),
        ("canon_revisions", "revision_number"),
        ("projection_heads", "projection_revision_number"),
    )
    for table_name, revision_column in head_checks:
        row = await admin_session.fetchone(
            f"""SELECT COUNT(*) AS count,MIN({revision_column}) AS min_revision,
                       MAX({revision_column}) AS max_revision
                FROM {table_name} WHERE project_id=%s""",
            (project_id,),
        )
        if row != {"count": 1, "min_revision": 0, "max_revision": 0}:
            raise ResetValidationError(f"{table_name} was not rebuilt at revision 0")
    outline = await admin_session.fetchone(
        "SELECT COUNT(*) AS count FROM project_chapter_outline_heads "
        "WHERE project_id=%s",
        (project_id,),
    )
    if outline != {"count": 0}:
        raise ResetValidationError("Chapter Outline heads must be empty after reset")


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
    """Inspect or clear derived data in one explicitly authorized current schema."""

    if type(request) is not ResetRequest:
        raise TypeError("request must be ResetRequest")
    product_read_authorized = bool(
        allow_product_database
        and _product_authority
        in {_CLI_PRODUCT_READ_AUTHORITY, _CLI_PRODUCT_EXECUTE_AUTHORITY}
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
    await _verify_selected_database(admin_session, database_name)
    await _classify_reset_source(admin_session, database_name)
    initial = await _load_current_foundation(admin_session, database_name, request)
    if not execute:
        report = _report(database_name, initial, executed=False)
        output(format_reset_report(report))
        return report

    acquired = False
    transaction_started = False
    committed = False
    body_error: BaseException | None = None
    report: ResetReport | None = None
    formatted_report: str | None = None
    try:
        lock = await admin_session.fetchone(
            "SELECT GET_LOCK(%s,%s) AS acquired", (RESET_LOCK_NAME, 30)
        )
        if lock is None or lock["acquired"] != 1:
            raise ResetError("Could not acquire Writer Core reset advisory lock")
        acquired = True
        await _verify_selected_database(admin_session, database_name)
        await admin_session.execute("START TRANSACTION")
        transaction_started = True
        locked_project = await admin_session.fetchone(
            """SELECT id FROM projects
               WHERE id=%s AND archived_at IS NULL FOR UPDATE""",
            (initial.project_id,),
        )
        if locked_project != {"id": initial.project_id}:
            raise ResetValidationError("Reset foundation project is unavailable")
        await _classify_reset_source(admin_session, database_name)
        locked = await _load_current_foundation(admin_session, database_name, request)
        if locked != initial:
            raise ResetValidationError("Reset foundation changed while waiting for lock")
        timestamp = (now_ms or (lambda: int(time.time() * 1000)))()
        await _clear_derived_state(
            admin_session,
            locked,
            now_ms=timestamp,
            id_factory=id_factory or (lambda: str(uuid4())),
        )
        await _verify_reset_state(admin_session, locked)
        report = _report(database_name, locked, executed=True)
        formatted_report = format_reset_report(report)
        await admin_session.execute("COMMIT")
        transaction_started = False
        committed = True
    except BaseException as exc:
        body_error = exc
    finally:
        cleanup_errors: list[BaseException] = []
        if transaction_started:
            try:
                await admin_session.execute("ROLLBACK")
            except BaseException as exc:
                cleanup_errors.append(exc)
        if acquired:
            try:
                await _release_lock(admin_session)
            except BaseException as exc:
                cleanup_errors.append(exc)
        if body_error is not None:
            if cleanup_errors:
                raise ResetPartialStateError(
                    "Writer Core reset failed and rollback or lock cleanup also failed"
                ) from BaseExceptionGroup(
                    "reset and cleanup failures", [body_error, *cleanup_errors]
                )
            raise body_error
        if cleanup_errors:
            if committed:
                raise ResetCommittedCleanupError(
                    "Writer Core reset committed, but cleanup failed"
                ) from BaseExceptionGroup(
                    "committed reset cleanup failures", cleanup_errors
                )
            if len(cleanup_errors) == 1:
                raise cleanup_errors[0]
            raise BaseExceptionGroup("Writer Core reset cleanup failed", cleanup_errors)

    assert report is not None
    assert formatted_report is not None
    output(formatted_report)
    return report


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preserve the approved foundation and reset derived Writer Core data"
    )
    parser.add_argument("--database", required=True)
    parser.add_argument("--project-title", required=True)
    parser.add_argument("--seed-title", action="append", required=True)
    parser.add_argument("--preferred-provider-name", required=True)
    parser.add_argument("--preferred-model", required=True)
    parser.add_argument("--confirm-reset", required=True)
    parser.add_argument("--confirm-host")
    parser.add_argument("--confirm-port", type=int)
    parser.add_argument("--execute", action="store_true")
    return parser


class _AdminSession:
    def __init__(self, connection, cursor):
        self._connection = connection
        self._cursor = cursor
        self._closed = False

    async def fetchone(self, sql, parameters=None):
        await self._cursor.execute(sql, parameters)
        return await self._cursor.fetchone()

    async def fetchall(self, sql, parameters=None):
        await self._cursor.execute(sql, parameters)
        return await self._cursor.fetchall()

    async def execute(self, sql, parameters=None):
        await self._cursor.execute(sql, parameters)

    async def close(self):
        if self._closed:
            return
        failures: list[BaseException] = []
        try:
            await self._cursor.close()
        except BaseException as exc:
            failures.append(exc)
        try:
            ensure_closed = getattr(self._connection, "ensure_closed", None)
            if ensure_closed is not None:
                await ensure_closed()
            else:
                self._connection.close()
        except BaseException as exc:
            failures.append(exc)
        else:
            self._closed = True
        if len(failures) == 1:
            raise failures[0]
        if failures:
            raise BaseExceptionGroup("reset session close failed", failures)


async def _reset_connection_factory(connection_config: Mapping[str, object]):
    import aiomysql

    allowed = {
        "host", "port", "user", "password", "db", "charset", "autocommit",
    }
    kwargs = {
        key: value for key, value in connection_config.items() if key in allowed
    }
    kwargs["autocommit"] = True
    connection = await aiomysql.connect(**kwargs)
    try:
        cursor = await connection.cursor(aiomysql.DictCursor)
    except BaseException as cursor_error:
        try:
            ensure_closed = getattr(connection, "ensure_closed", None)
            if ensure_closed is not None:
                await ensure_closed()
            else:
                connection.close()
        except BaseException as close_error:
            raise BaseExceptionGroup(
                "reset cursor creation and connection close both failed",
                [cursor_error, close_error],
            ) from cursor_error
        raise
    return _AdminSession(connection, cursor)


async def _verify_product_connection_identity(admin_session) -> None:
    row = await admin_session.fetchone(
        "SELECT DATABASE() AS database_name,@@port AS server_port,"
        "CONCAT(@@server_uuid,':',VERSION()) AS server_identity"
    )
    if (row or {}).get("database_name") != PRODUCT_DATABASE:
        raise ResetSafetyError("Product selected database identity does not match")
    if (row or {}).get("server_port") != PRODUCT_PORT:
        raise ResetSafetyError("Product server port identity does not match")
    identity = (row or {}).get("server_identity")
    if not isinstance(identity, str) or not identity.strip():
        raise ResetSafetyError("Product server identity is empty")


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
        args.database == PRODUCT_DATABASE and args.confirm_reset == PRODUCT_DATABASE
    )
    _guard_database(args.database, allow_product_database)
    if connection_config is None:
        from backend.config import require_mysql_config

        connection_config = require_mysql_config()
    if connection_config.get("db") != args.database:
        raise ResetSafetyError(
            "The configured database does not match the explicit reset target"
        )
    if allow_product_database:
        if connection_config.get("host") != PRODUCT_HOST:
            raise ResetSafetyError("Product reset requires the exact loopback host")
        if connection_config.get("port") != PRODUCT_PORT:
            raise ResetSafetyError("Product reset requires local port 3307")
        if args.confirm_host != PRODUCT_HOST:
            raise ResetSafetyError("Product host confirmation does not match")
        if args.confirm_port != PRODUCT_PORT:
            raise ResetSafetyError("Product port confirmation does not match")
    factory = connection_factory or _reset_connection_factory
    session = await factory(connection_config)
    errors: list[BaseException] = []
    try:
        if allow_product_database:
            await _verify_product_connection_identity(session)
        await (reset_function or reset_writer_core_data)(
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
            "Writer Core reset command and connection close both failed", errors
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(run_cli(argv))
    except SystemExit:
        raise
    except BaseException:
        print("Writer Core data reset failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
