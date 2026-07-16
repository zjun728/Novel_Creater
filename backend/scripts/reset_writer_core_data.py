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
import json
import re
import sys
import time
from typing import Awaitable, Callable, Mapping, Sequence
from uuid import uuid4

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.model_bindings import BindingItem, BindingRevision, TASK_KEYS
from backend.domain.seeds import SeedPayload
from backend.schema_manifest import created_table_names
from backend.schema_manifest import manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from backend.scripts.initialize_database import (
    _default_connection_factory,
    initialize_database,
)
from backend.services.projects import ProjectService
from backend.services.projections import build_projection_bundle


PRODUCT_DATABASE = "novel_creator"
RESET_LOCK_NAME = "novel_creator_writer_core_reset"
SELECTED_SEED_TITLE = "典镇山河"
M1_SCHEMA_VERSION = "writer-core-v1.0.0"
M1_MANIFEST_HASH = "0697b6da4826b98c8e502ff7ad68a61b51fe7037b167b6d8175ae9d78dcff826"
M1_TABLE_NAMES = (
    "schema_metadata", "projects", "creative_seeds", "project_selected_seeds",
    "provider_profiles", "task_model_bindings", "task_model_binding_items",
    "creation_contracts", "style_contracts", "contract_asset_refs",
    "volume_plans", "story_blocks", "story_stages", "scene_tasks",
    "chapter_sessions", "working_drafts", "draft_candidates",
    "finalization_change_sets", "finalization_records", "final_chapters",
    "canon_entities", "entity_aliases", "canon_revisions", "canon_events",
    "current_state_projections", "memory_views", "arc_projections",
    "plot_thread_projections", "projection_heads", "corpus_sources",
    "corpus_chapters", "style_templates", "experience_cards", "reference_uses",
)
FOUNDATION_TABLES = frozenset({
    "schema_metadata",
    "projects",
    "creative_seeds",
    "creative_seed_revisions",
    "creative_seed_heads",
    "project_selected_seeds",
    "provider_profiles",
    "project_model_binding_revisions",
    "project_model_binding_items",
    "project_model_binding_heads",
    "canon_revisions",
    "projection_heads",
    "project_contract_heads",
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
    "id", "project_id", "status", "created_at", "updated_at",
)
_PROVIDER_COLUMNS = (
    "id", "name", "provider_type", "model_name", "base_url", "api_key",
    "enabled", "sort_order", "stream", "max_context_tokens",
    "max_output_tokens", "temperature", "top_p", "supports_json",
    "supports_streaming", "notes", "thinking", "lifecycle_status", "deleted_at",
    "created_at", "updated_at",
)
_M1_PROJECT_COLUMNS = _PROJECT_COLUMNS
_M1_SEED_COLUMNS = (
    "id", "project_id", "title", "premise_json", "content_hash", "status",
    "created_at",
)
_M1_PROVIDER_COLUMNS = (
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


async def _classify_reset_source(admin_session, database_name: str) -> str:
    """Accept only the frozen M1 product manifest or current M2 manifest."""

    table_rows = await admin_session.fetchall(
        "SELECT TABLE_NAME FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME",
        (database_name,),
    )
    tables = {row["TABLE_NAME"] for row in table_rows}
    metadata = None
    if "schema_metadata" in tables:
        metadata = await admin_session.fetchone(
            f"SELECT schema_version,manifest_hash FROM "
            f"{_qualified(database_name, 'schema_metadata')} WHERE singleton_id=1"
        )
    if (
        tables == set(M1_TABLE_NAMES)
        and metadata == {
            "schema_version": M1_SCHEMA_VERSION,
            "manifest_hash": M1_MANIFEST_HASH,
        }
    ):
        return "m1-v1.0"
    if (
        tables == set(created_table_names())
        and metadata == {
            "schema_version": EXPECTED_SCHEMA_VERSION,
            "manifest_hash": manifest_hash(),
        }
    ):
        return "m2-v1.1"
    if database_name != PRODUCT_DATABASE and "schema_metadata" not in tables:
        return "historical-disposable"
    raise ResetValidationError(
        "Reset source must be the exact M1 v1.0 or M2 v1.1 manifest"
    )


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
    seed_revision_count: int
    seed_head_count: int
    binding_revision_count: int
    binding_item_count: int
    binding_head_count: int
    canon_revision_count: int
    projection_head_count: int
    contract_head_count: int
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


async def _verify_reset_server_capabilities(admin_session) -> str:
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
    return version


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
    try:
        payload = SeedPayload(
            title=title,
            genre=row["genre"],
            logline=row["logline"],
            protagonist=row["protagonist"],
            desire=row["desire"],
            coreConflict=row["core_conflict"],
            worldPressure=row["world_pressure"],
            openingHook=row["opening_hook"],
            differentiation=row["differentiation"],
        )
    except (TypeError, ValueError) as exc:
        raise ResetValidationError("Legacy seed cannot map to SeedPayload") from exc
    payload_json = canonical_json(payload)
    created_at = _integer(row["created_at"], "seed.created_at")
    return {
        "id": seed_id,
        "project_id": owner_id,
        "title": title,
        "status": "candidate",
        "payload_json": payload_json,
        "content_hash": canonical_hash(payload),
        "created_at": created_at,
        "updated_at": created_at,
    }


def _map_provider(row: Mapping[str, object], sort_order: int) -> dict[str, object]:
    base_url = _text(row["base_url"], "provider.base_url", max_length=2048)
    api_key = _text(row["api_key"], "provider.api_key", max_length=65_535)
    if not base_url or not api_key:
        raise ResetValidationError(
            "Legacy active Provider requires non-empty connection fields"
        )
    return {
        "id": _identifier(row["id"], "provider.id"),
        "name": _text(row["name"], "provider.name", max_length=120),
        "provider_type": _text(
            row["provider_type"], "provider.provider_type",
            default="openai-compatible", max_length=64,
        ),
        "model_name": _text(row["model"], "provider.model", max_length=160),
        "base_url": base_url,
        "api_key": api_key,
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
        "lifecycle_status": "active",
        "deleted_at": None,
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


def _map_m1_project(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": _identifier(row["id"], "project.id"),
        "title": _text(row["title"], "project.title", max_length=200),
        "genre": _text(row["genre"], "project.genre", max_length=120),
        "description": _text(row["description"], "project.description", max_length=65_535),
        "target_words": _integer(row["target_words"], "project.target_words", minimum=1),
        "target_chapters": _integer(row["target_chapters"], "project.target_chapters", minimum=1),
        "status": "drafting",
        "current_chapter": 0,
        "created_at": _integer(row["created_at"], "project.created_at"),
        "updated_at": _integer(row["updated_at"], "project.updated_at"),
    }


def _map_m1_seed(row: Mapping[str, object], project_id: str) -> dict[str, object]:
    seed_id = _identifier(row["id"], "seed.id")
    owner_id = _identifier(row["project_id"], "seed.project_id")
    if owner_id != project_id:
        raise ResetValidationError("M1 requested seed belongs to another project")
    try:
        decoded = json.loads(row["premise_json"]) if isinstance(row["premise_json"], str) else row["premise_json"]
        payload = SeedPayload.model_validate(decoded)
    except (TypeError, ValueError) as exc:
        raise ResetValidationError("M1 seed premise_json is not a valid SeedPayload") from exc
    title = _text(row["title"], "seed.title", max_length=200)
    if payload.title != title:
        raise ResetValidationError("M1 seed title and premise_json disagree")
    content_hash = canonical_hash(payload)
    if row["content_hash"] != content_hash:
        raise ResetValidationError("M1 seed content_hash does not match premise_json")
    created_at = _integer(row["created_at"], "seed.created_at")
    return {
        "id": seed_id,
        "project_id": owner_id,
        "title": title,
        "status": "candidate",
        "payload_json": canonical_json(payload),
        "content_hash": content_hash,
        "created_at": created_at,
        "updated_at": created_at,
    }


def _map_m1_provider(row: Mapping[str, object]) -> dict[str, object]:
    base_url = _text(row["base_url"], "provider.base_url", max_length=2048)
    api_key = _text(row["api_key"], "provider.api_key", max_length=65_535)
    if not base_url or not api_key:
        raise ResetValidationError("M1 Provider requires non-empty connection fields")
    return {
        "id": _identifier(row["id"], "provider.id"),
        "name": _text(row["name"], "provider.name", max_length=120),
        "provider_type": _text(row["provider_type"], "provider.provider_type", max_length=64),
        "model_name": _text(row["model_name"], "provider.model_name", max_length=160),
        "base_url": base_url,
        "api_key": api_key,
        "enabled": _flag(row["enabled"], "provider.enabled"),
        "sort_order": _integer(row["sort_order"], "provider.sort_order"),
        "stream": _flag(row["stream"], "provider.stream"),
        "max_context_tokens": _integer(row["max_context_tokens"], "provider.max_context_tokens", minimum=1),
        "max_output_tokens": _integer(row["max_output_tokens"], "provider.max_output_tokens", minimum=1),
        "temperature": _decimal(row["temperature"], "provider.temperature", default="0.8"),
        "top_p": _decimal(row["top_p"], "provider.top_p", default="0.9"),
        "supports_json": _flag(row["supports_json"], "provider.supports_json"),
        "supports_streaming": _flag(row["supports_streaming"], "provider.supports_streaming"),
        "notes": _text(row["notes"], "provider.notes", max_length=65_535),
        "thinking": _json_text(row["thinking"], "provider.thinking"),
        "lifecycle_status": "active",
        "deleted_at": None,
        "created_at": _integer(row["created_at"], "provider.created_at"),
        "updated_at": _integer(row["updated_at"], "provider.updated_at"),
    }


async def _verify_zero_tables(admin_session, database_name: str, tables: Sequence[str]) -> None:
    for table in tables:
        row = await admin_session.fetchone(
            f"SELECT COUNT(*) AS count FROM {_qualified(database_name, table)}"
        )
        if row is None or row.get("count") != 0:
            raise ResetValidationError(f"Reset source contains advanced rows in {table}")


async def _load_m1_preserved_state(
    admin_session, database_name: str, request: ResetRequest,
) -> _PreservedState:
    projects = await admin_session.fetchall(
        f"SELECT {', '.join(_M1_PROJECT_COLUMNS)} FROM {_qualified(database_name, 'projects')} WHERE title=%s",
        (request.project_title,),
    )
    if len(projects) != 1:
        raise ResetValidationError("M1 reset requires exactly one requested project")
    project = _map_m1_project(projects[0])
    total_projects = await admin_session.fetchone(
        f"SELECT COUNT(*) AS count FROM {_qualified(database_name, 'projects')}"
    )
    if (total_projects or {}).get("count") != 1:
        raise ResetValidationError("M1 reset requires exactly one project total")

    placeholders = ",".join(("%s",) * len(request.seed_titles))
    seed_rows = await admin_session.fetchall(
        f"SELECT {', '.join(_M1_SEED_COLUMNS)} FROM {_qualified(database_name, 'creative_seeds')} "
        f"WHERE project_id=%s AND title IN ({placeholders}) ORDER BY title,id",
        (project["id"], *request.seed_titles),
    )
    if len(seed_rows) != 3 or Counter(row["title"] for row in seed_rows) != Counter(request.seed_titles):
        raise ResetValidationError("M1 reset requires exactly the three requested seeds")
    seeds = tuple(_map_m1_seed(row, str(project["id"])) for row in seed_rows)
    total_seeds = await admin_session.fetchone(
        f"SELECT COUNT(*) AS count FROM {_qualified(database_name, 'creative_seeds')}"
    )
    if (total_seeds or {}).get("count") != 3:
        raise ResetValidationError("M1 reset requires exactly three seeds total")
    selected = await admin_session.fetchone(
        f"SELECT s.title FROM {_qualified(database_name, 'project_selected_seeds')} x "
        f"JOIN {_qualified(database_name, 'creative_seeds')} s ON s.id=x.seed_id "
        "WHERE x.project_id=%s",
        (project["id"],),
    )
    if selected != {"title": SELECTED_SEED_TITLE}:
        raise ResetValidationError(f"M1 selected seed must be {SELECTED_SEED_TITLE}")

    provider_rows = await admin_session.fetchall(
        f"SELECT {', '.join(_M1_PROVIDER_COLUMNS)} FROM {_qualified(database_name, 'provider_profiles')} ORDER BY sort_order,id"
    )
    if not provider_rows:
        raise ResetValidationError("M1 reset requires preserved Providers")
    providers = tuple(_map_m1_provider(row) for row in provider_rows)
    _require_exact_unique(providers, "id", "provider")
    preferred = tuple(
        row for row in providers
        if row["name"] == request.preferred_provider_name
        and row["model_name"] == request.preferred_model
        and row["enabled"] == 1
    )
    if len(preferred) != 1:
        raise ResetValidationError("M1 requires exactly one enabled preferred Provider/model")

    binding = await admin_session.fetchone(
        f"SELECT (SELECT COUNT(*) FROM {_qualified(database_name, 'task_model_bindings')} b WHERE b.project_id=%s) AS binding_count,"
        f"(SELECT COUNT(*) FROM {_qualified(database_name, 'task_model_binding_items')} i WHERE i.project_id=%s) AS item_count,"
        f"(SELECT COUNT(DISTINCT i.task_key) FROM {_qualified(database_name, 'task_model_binding_items')} i WHERE i.project_id=%s) AS task_count",
        (project["id"], project["id"], project["id"]),
    )
    if binding != {"binding_count": 1, "item_count": len(TASK_KEYS), "task_count": len(TASK_KEYS)}:
        raise ResetValidationError("M1 foundation binding inventory is not head0-ready")
    task_rows = await admin_session.fetchall(
        f"SELECT task_key FROM {_qualified(database_name, 'task_model_binding_items')} WHERE project_id=%s ORDER BY task_key",
        (project["id"],),
    )
    if {row.get("task_key") for row in task_rows} != set(TASK_KEYS):
        raise ResetValidationError("M1 foundation binding task keys are not the exact closed set")
    canon = await admin_session.fetchone(
        f"SELECT COUNT(*) AS count,MIN(revision_number) AS min_revision,MAX(revision_number) AS max_revision "
        f"FROM {_qualified(database_name, 'canon_revisions')} WHERE project_id=%s",
        (project["id"],),
    )
    projection = await admin_session.fetchone(
        f"SELECT canon_revision_number,projection_revision_number FROM {_qualified(database_name, 'projection_heads')} WHERE project_id=%s",
        (project["id"],),
    )
    if canon != {"count": 1, "min_revision": 0, "max_revision": 0} or projection != {
        "canon_revision_number": 0, "projection_revision_number": 0,
    }:
        raise ResetValidationError("M1 Canon/Projection must be exactly head0")
    foundation = {
        "schema_metadata", "projects", "creative_seeds", "project_selected_seeds",
        "provider_profiles", "task_model_bindings", "task_model_binding_items",
        "canon_revisions", "projection_heads",
    }
    await _verify_zero_tables(
        admin_session, database_name,
        tuple(table for table in M1_TABLE_NAMES if table not in foundation),
    )
    return _PreservedState(project, seeds, providers, preferred[0])


async def _load_v11_preserved_state(
    admin_session, database_name: str, request: ResetRequest,
) -> _PreservedState:
    projects = await admin_session.fetchall(
        f"SELECT {', '.join(_PROJECT_COLUMNS)} FROM {_qualified(database_name, 'projects')} WHERE title=%s",
        (request.project_title,),
    )
    if len(projects) != 1:
        raise ResetValidationError("M2 fresh state requires exactly one requested project")
    project = _map_m1_project(projects[0])
    seed_rows = await admin_session.fetchall(
        f"SELECT s.id,s.project_id,JSON_UNQUOTE(JSON_EXTRACT(r.payload_json,'$.title')) AS title,"
        f"r.payload_json AS premise_json,r.content_hash,s.status,s.created_at,"
        f"h.revision AS head_revision,r.revision AS source_revision "
        f"FROM {_qualified(database_name, 'creative_seeds')} s "
        f"JOIN {_qualified(database_name, 'creative_seed_heads')} h ON h.seed_id=s.id "
        f"JOIN {_qualified(database_name, 'creative_seed_revisions')} r ON r.id=h.revision_id "
        "WHERE s.project_id=%s ORDER BY title,s.id",
        (project["id"],),
    )
    if len(seed_rows) != 3 or Counter(row["title"] for row in seed_rows) != Counter(request.seed_titles):
        raise ResetValidationError("M2 fresh state requires exactly the requested three seeds")
    if any(
        row.get("head_revision") != 1 or row.get("source_revision") != 1
        for row in seed_rows
    ):
        raise ResetValidationError("M2 seed heads must all be revision 1")
    seeds = tuple(_map_m1_seed(row, str(project["id"])) for row in seed_rows)
    selected = await admin_session.fetchone(
        f"SELECT JSON_UNQUOTE(JSON_EXTRACT(r.payload_json,'$.title')) AS title,x.seed_hash,r.content_hash,x.selection_revision "
        f"FROM {_qualified(database_name, 'project_selected_seeds')} x "
        f"JOIN {_qualified(database_name, 'creative_seed_revisions')} r ON r.id=x.seed_revision_id "
        "WHERE x.project_id=%s",
        (project["id"],),
    )
    if (
        selected is None
        or selected.get("title") != SELECTED_SEED_TITLE
        or selected.get("seed_hash") != selected.get("content_hash")
        or selected.get("selection_revision") != 1
    ):
        raise ResetValidationError(f"M2 selected seed must be {SELECTED_SEED_TITLE}")
    provider_rows = await admin_session.fetchall(
        f"SELECT {', '.join(_PROVIDER_COLUMNS)} FROM {_qualified(database_name, 'provider_profiles')} ORDER BY sort_order,id"
    )
    providers = tuple(_map_m1_provider(row) for row in provider_rows)
    preferred = tuple(
        row for row in providers
        if row["name"] == request.preferred_provider_name
        and row["model_name"] == request.preferred_model
        and row["enabled"] == 1
    )
    if len(preferred) != 1:
        raise ResetValidationError("M2 requires exactly one enabled preferred Provider/model")
    expected_counts = {
        "schema_metadata": 1, "projects": 1, "creative_seeds": 3,
        "creative_seed_revisions": 3, "creative_seed_heads": 3,
        "project_selected_seeds": 1, "provider_profiles": len(providers),
        "project_model_binding_revisions": 1,
        "project_model_binding_items": len(TASK_KEYS),
        "project_model_binding_heads": 1, "canon_revisions": 1,
        "projection_heads": 1, "project_contract_heads": 1,
    }
    for table in created_table_names():
        row = await admin_session.fetchone(
            f"SELECT COUNT(*) AS count FROM {_qualified(database_name, table)}"
        )
        if row is None or row.get("count") != expected_counts.get(table, 0):
            raise ResetValidationError(f"M2 state is advanced or incomplete in {table}")
    binding = await admin_session.fetchone(
        f"SELECT h.revision,h.content_hash AS head_hash,r.content_hash AS revision_hash,"
        f"(SELECT COUNT(*) FROM {_qualified(database_name, 'project_model_binding_items')} i WHERE i.binding_revision_id=h.binding_revision_id AND i.resolution_status='bound') AS bound_count "
        f"FROM {_qualified(database_name, 'project_model_binding_heads')} h "
        f"JOIN {_qualified(database_name, 'project_model_binding_revisions')} r ON r.id=h.binding_revision_id WHERE h.project_id=%s",
        (project["id"],),
    )
    if (
        binding is None or binding.get("revision") != 1
        or binding.get("head_hash") != binding.get("revision_hash")
        or binding.get("bound_count") != len(TASK_KEYS)
    ):
        raise ResetValidationError("M2 binding head must be revision1 with eight bound tasks")
    head = await admin_session.fetchone(
        f"SELECT revision,creation_contract_id,style_contract_id,creation_hash,style_hash "
        f"FROM {_qualified(database_name, 'project_contract_heads')} WHERE project_id=%s",
        (project["id"],),
    )
    canon = await admin_session.fetchone(
        f"SELECT revision_number,content_hash FROM {_qualified(database_name, 'canon_revisions')} WHERE project_id=%s",
        (project["id"],),
    )
    projection = await admin_session.fetchone(
        f"SELECT canon_revision_number,projection_revision_number,content_hash FROM {_qualified(database_name, 'projection_heads')} WHERE project_id=%s",
        (project["id"],),
    )
    empty_hash = build_projection_bundle(0, ()).content_hash
    if head != {
        "revision": 0, "creation_contract_id": None, "style_contract_id": None,
        "creation_hash": None, "style_hash": None,
    } or canon != {"revision_number": 0, "content_hash": empty_hash} or projection != {
        "canon_revision_number": 0, "projection_revision_number": 0,
        "content_hash": empty_hash,
    }:
        raise ResetValidationError("M2 fresh state must remain Contract/Canon/Projection head0")
    return _PreservedState(project, seeds, providers, preferred[0])


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
        seed_revision_count=len(state.seeds),
        seed_head_count=len(state.seeds),
        binding_revision_count=1,
        binding_item_count=len(TASK_KEYS),
        binding_head_count=1,
        canon_revision_count=1,
        projection_head_count=1,
        contract_head_count=1,
        table_names=created_table_names(),
        verified_empty_tables=VERIFIED_EMPTY_TABLES if executed else (),
    )


def format_reset_report(report: ResetReport) -> str:
    """Render one escaped JSON receipt containing only public allowlisted fields."""
    receipt = {
        "mode": "execute" if report.executed else "dry-run",
        "database": report.database_name,
        "project": {"id": report.project_id, "title": report.project_title},
        "seeds": [
            {"id": seed_id, "title": title} for seed_id, title in report.seeds
        ],
        "providers": [
            {
                "id": provider_id,
                "name": name,
                "model": model,
                "enabled": enabled,
            }
            for provider_id, name, model, enabled in report.providers
        ],
        "preferredProviderId": report.preferred_provider_id,
        "counts": {
            "projects": 1,
            "seeds": report.seed_count,
            "providers": report.provider_count,
            "seedRevisions": report.seed_revision_count,
            "seedHeads": report.seed_head_count,
            "bindingRevisions": report.binding_revision_count,
            "bindingItems": report.binding_item_count,
            "bindingHeads": report.binding_head_count,
            "canonRevisions": report.canon_revision_count,
            "projectionHeads": report.projection_head_count,
            "contractHeads": report.contract_head_count,
        },
        "tables": list(report.table_names),
        "verifiedEmptyTables": list(report.verified_empty_tables),
    }
    return json.dumps(
        receipt,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


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

    for seed in state.seeds:
        await admin_session.execute(
            f"INSERT INTO creative_seeds ({', '.join(_SEED_COLUMNS)}) "
            f"VALUES ({','.join(('%s',) * len(_SEED_COLUMNS))})",
            tuple(seed[column] for column in _SEED_COLUMNS),
        )

    seed_revisions: dict[str, dict[str, object]] = {}
    for seed in state.seeds:
        revision_id = id_factory()
        revision = {
            "id": revision_id,
            "seed_id": seed["id"],
            "content_hash": seed["content_hash"],
        }
        seed_revisions[str(seed["id"])] = revision
        await admin_session.execute(
            """INSERT INTO creative_seed_revisions
               (id, project_id, seed_id, revision, payload_json, content_hash, created_at)
               VALUES (%s,%s,%s,1,%s,%s,%s)""",
            (
                revision_id, project["id"], seed["id"], seed["payload_json"],
                seed["content_hash"], seed["created_at"],
            ),
        )

    for seed in state.seeds:
        revision = seed_revisions[str(seed["id"])]
        await admin_session.execute(
            """INSERT INTO creative_seed_heads
               (seed_id, revision_id, revision, content_hash, updated_at)
               VALUES (%s,%s,1,%s,%s)""",
            (seed["id"], revision["id"], revision["content_hash"], now_ms),
        )

    selected_seed = next(
        seed for seed in state.seeds if seed["title"] == SELECTED_SEED_TITLE
    )
    selected_revision = seed_revisions[str(selected_seed["id"])]
    await admin_session.execute(
        """INSERT INTO project_selected_seeds
           (project_id, seed_id, seed_revision_id, seed_hash,
            selection_revision, selected_at, updated_at)
           VALUES (%s,%s,%s,%s,1,%s,%s)""",
        (
            project["id"], selected_seed["id"], selected_revision["id"],
            selected_revision["content_hash"], now_ms, now_ms,
        ),
    )

    preferred = state.preferred_provider
    binding_items = tuple(BindingItem(
        task_key=task_key,
        resolution_status="bound",
        provider_id=str(preferred["id"]),
        provider_name_snapshot=str(preferred["name"]),
        model_name_snapshot=str(preferred["model_name"]),
    ) for task_key in TASK_KEYS)
    binding = BindingRevision(
        project_id=str(project["id"]),
        revision=1,
        items=binding_items,
    )
    binding_id = id_factory()
    binding_hash = canonical_hash(binding)
    await admin_session.execute(
        """INSERT INTO project_model_binding_revisions
           (id, project_id, revision, content_hash, source_project_id, created_at)
           VALUES (%s,%s,1,%s,NULL,%s)""",
        (binding_id, project["id"], binding_hash, now_ms),
    )
    for item in binding_items:
        await admin_session.execute(
            """INSERT INTO project_model_binding_items
               (binding_revision_id, task_key, resolution_status, provider_id,
                provider_name_snapshot, model_name_snapshot, item_hash)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (
                binding_id, item.task_key, item.resolution_status, item.provider_id,
                item.provider_name_snapshot, item.model_name_snapshot,
                canonical_hash(item),
            ),
        )
    await admin_session.execute(
        """INSERT INTO project_model_binding_heads
           (project_id, revision, binding_revision_id, content_hash, updated_at)
           VALUES (%s,1,%s,%s,%s)""",
        (project["id"], binding_id, binding_hash, now_ms),
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
    await admin_session.execute(
        """INSERT INTO project_contract_heads
           (project_id, revision, creation_contract_id, style_contract_id,
            creation_hash, style_hash, updated_at)
           VALUES (%s,0,NULL,NULL,NULL,NULL,%s)""",
        (project["id"], now_ms),
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
    source_kind = await _classify_reset_source(admin_session, database_name)

    async def load_state(kind: str) -> _PreservedState:
        if kind == "m1-v1.0":
            return await _load_m1_preserved_state(admin_session, database_name, request)
        if kind == "m2-v1.1":
            return await _load_v11_preserved_state(admin_session, database_name, request)
        return await _load_preserved_state(admin_session, database_name, request)

    initial_state = await load_state(source_kind)
    if not execute:
        report = _report(database_name, initial_state, executed=False)
        output(format_reset_report(report))
        return report

    acquired = False
    ddl_owned = False
    transaction_started = False
    body_error: BaseException | None = None
    report: ResetReport | None = None
    try:
        lock = await admin_session.fetchone(
            "SELECT GET_LOCK(%s, %s) AS acquired", (RESET_LOCK_NAME, 30)
        )
        if lock is None or lock["acquired"] != 1:
            raise ResetError("Could not acquire Writer Core reset advisory lock")
        acquired = True
        locked_kind = (
            source_kind
            if source_kind == "historical-disposable"
            else await _classify_reset_source(admin_session, database_name)
        )
        if locked_kind != source_kind:
            raise ResetValidationError("Reset source inventory changed while waiting for lock")
        locked_state = await load_state(locked_kind)
        if locked_state != initial_state:
            raise ResetValidationError("Reset foundation changed while waiting for lock")
        if locked_kind == "m2-v1.1":
            report = _report(database_name, locked_state, executed=False)
        else:
            await _verify_reset_server_capabilities(admin_session)
            _guard_database(database_name, product_execute_authorized)
            await admin_session.execute(f"DROP DATABASE `{database_name}`")
            ddl_owned = True
            _guard_database(database_name, product_execute_authorized)
            await admin_session.execute(
                f"CREATE DATABASE `{database_name}` CHARACTER SET utf8mb4 "
                "COLLATE utf8mb4_0900_ai_ci"
            )
            timestamp = (now_ms or (lambda: int(time.time() * 1000)))()
            await initialize_database(
                admin_session, database_name, database_name, timestamp,
            )
            await admin_session.execute("START TRANSACTION")
            transaction_started = True
            await _insert_preserved_state(
                admin_session,
                locked_state,
                now_ms=timestamp,
                id_factory=id_factory or (lambda: str(uuid4())),
            )
            await _verify_empty_tables(admin_session)
            try:
                await admin_session.execute("COMMIT")
            except BaseException as commit_error:
                if source_kind == "historical-disposable":
                    transaction_started = False
                    acquired = False
                    await _recover_failed_commit(admin_session, commit_error)
                raise
            transaction_started = False
            if await _classify_reset_source(admin_session, database_name) != "m2-v1.1":
                raise ResetValidationError("Rebuilt database does not match the M2 manifest")
            readback_state = await _load_v11_preserved_state(
                admin_session, database_name, request,
            )
            if readback_state != locked_state:
                raise ResetValidationError("Rebuilt M2 foundation differs from the locked snapshot")
            report = _report(database_name, readback_state, executed=True)
            ddl_owned = False
    except BaseException as exc:
        body_error = exc
    finally:
        cleanup_errors: list[BaseException] = []
        if body_error is not None and transaction_started:
            try:
                await admin_session.execute("ROLLBACK")
            except BaseException as exc:
                cleanup_errors.append(exc)
        should_drop_incomplete = ddl_owned and source_kind != "historical-disposable"
        if body_error is not None and should_drop_incomplete:
            try:
                _guard_database(database_name, product_execute_authorized)
                await admin_session.execute(f"DROP DATABASE IF EXISTS `{database_name}`")
                ddl_owned = False
            except BaseException as exc:
                cleanup_errors.append(exc)
        if acquired:
            try:
                await _release_lock(admin_session)
            except BaseException as exc:
                cleanup_errors.append(exc)
        if body_error is not None:
            if cleanup_errors:
                combined = BaseExceptionGroup(
                    "Writer Core reset failed and cleanup also failed",
                    [body_error, *cleanup_errors],
                )
            else:
                combined = body_error
            if isinstance(body_error, (ResetSafetyError, ResetValidationError)) and not ddl_owned:
                raise combined
            if source_kind == "historical-disposable" and ddl_owned:
                raise ResetPartialStateError(
                    f"Writer Core reset failed; {database_name} may remain partially reset"
                ) from combined
            raise ResetPartialStateError(
                f"Writer Core reset failed; incomplete {database_name} was removed"
            ) from combined
        if cleanup_errors:
            if len(cleanup_errors) == 1:
                raise cleanup_errors[0]
            raise BaseExceptionGroup(
                "Writer Core reset cleanup failed", cleanup_errors,
            )

    assert report is not None
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
        from backend.config import require_mysql_config

        connection_config = require_mysql_config()
    configured_database = connection_config.get("db")
    if configured_database != args.database:
        raise ResetSafetyError(
            "The configured database does not match the explicit reset target"
        )
    factory = connection_factory or _default_connection_factory
    session = await factory(connection_config)
    errors: list[BaseException] = []
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
            "Writer Core reset command and connection close both failed", errors,
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
