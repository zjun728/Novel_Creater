"""Reset the frozen v1.1 foundation into v1.2, or verify a v1.2 no-op."""

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
    _AiomysqlAdminSession,
    initialize_database,
)
from backend.services.projects import ProjectService
from backend.services.projections import build_projection_bundle


PRODUCT_DATABASE = "novel_creator"
PRODUCT_HOST = "127.0.0.1"
PRODUCT_PORT = 3307
RESET_LOCK_NAME = "novel_creator_writer_core_reset"
SELECTED_SEED_TITLE = "典镇山河"
V11_SCHEMA_VERSION = "writer-core-v1.1.0"
V11_MANIFEST_HASH = "cf993ccf7f000935aaa5777bfb9adda4cd6cbd47cb4f83be5d073d7d3e6b30c5"
V11_TABLE_NAMES = (
    "schema_metadata", "projects", "creative_seeds", "creative_seed_revisions",
    "creative_seed_heads", "project_selected_seeds", "provider_profiles",
    "project_model_binding_revisions", "project_model_binding_items",
    "project_model_binding_heads", "style_templates", "style_template_heads",
    "experience_cards", "experience_card_heads", "corpus_sources",
    "corpus_chapters", "corpus_fragments", "corpus_import_runs",
    "story_engine_batches", "story_engine_options", "project_contract_drafts",
    "creation_contracts", "style_contracts", "project_contract_heads",
    "contract_confirmation_requests", "creation_contract_engine_refs",
    "style_contract_template_refs", "creation_contract_experience_refs",
    "creation_contract_corpus_refs", "volume_plans", "story_blocks",
    "story_stages", "scene_tasks", "chapter_sessions", "working_drafts",
    "draft_candidates", "finalization_change_sets", "finalization_records",
    "final_chapters", "canon_entities", "entity_aliases", "canon_revisions",
    "canon_events", "current_state_projections", "memory_views",
    "arc_projections", "plot_thread_projections", "projection_heads",
    "reference_uses",
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

_PROJECT_COLUMNS = (
    "id", "title", "genre", "description", "target_words",
    "target_chapters", "status", "current_chapter", "archived_at",
    "lifecycle_revision", "created_at", "updated_at",
)
_V11_PROJECT_COLUMNS = tuple(
    column for column in _PROJECT_COLUMNS
    if column not in {"archived_at", "lifecycle_revision"}
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


class ResetError(RuntimeError):
    """Base class for safe reset failures."""


class ResetSafetyError(ResetError):
    """The requested target or confirmation is unsafe."""


class ResetValidationError(ResetError):
    """Preserved rows do not match the exact reset contract."""


class ResetPartialStateError(ResetError):
    """DDL started and the target may now contain partial reset state."""


async def _classify_reset_source(admin_session, database_name: str) -> str:
    """Accept only the frozen v1.1 source or current v1.2 target manifest."""

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
        tables == set(V11_TABLE_NAMES)
        and metadata == {
            "schema_version": V11_SCHEMA_VERSION,
            "manifest_hash": V11_MANIFEST_HASH,
        }
    ):
        return "v1.1-source"
    if (
        tables == set(created_table_names())
        and metadata == {
            "schema_version": EXPECTED_SCHEMA_VERSION,
            "manifest_hash": manifest_hash(),
        }
    ):
        return "v1.2-target"
    raise ResetValidationError(
        "Reset source must be the exact v1.1 source or v1.2 target manifest"
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
    mode: str
    executed: bool
    source_kind: str
    database_name: str
    project_id: str
    project_title: str
    seed_count: int
    seeds: tuple[tuple[str, str], ...]
    provider_count: int
    providers: tuple[tuple[str, str, str, bool], ...]
    preferred_provider_id: str
    source_schema_version: str
    source_manifest_hash: str
    source_table_names: tuple[str, ...]
    source_counts: tuple[tuple[str, int], ...]
    source_verified_empty_tables: tuple[str, ...]
    target_schema_version: str
    target_manifest_hash: str
    target_table_names: tuple[str, ...]
    target_expected_counts: tuple[tuple[str, int], ...]
    target_expected_empty_tables: tuple[str, ...]
    target_verified: bool


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
    status = _text(row["status"], "project.status", max_length=24)
    current_chapter = _integer(
        row["current_chapter"], "project.current_chapter", minimum=0,
    )
    if status != "drafting" or current_chapter != 0:
        raise ResetValidationError(
            "Reset foundation project must be drafting at current chapter 0"
        )
    if row.get("archived_at") is not None or row.get("lifecycle_revision", 0) != 0:
        raise ResetValidationError(
            "Reset foundation project must be unarchived at lifecycle revision 0"
        )
    return {
        "id": _identifier(row["id"], "project.id"),
        "title": _text(row["title"], "project.title", max_length=200),
        "genre": _text(row["genre"], "project.genre", max_length=120),
        "description": _text(row["description"], "project.description", max_length=65_535),
        "target_words": _integer(row["target_words"], "project.target_words", minimum=1),
        "target_chapters": _integer(row["target_chapters"], "project.target_chapters", minimum=1),
        "status": status,
        "current_chapter": current_chapter,
        "archived_at": None,
        "lifecycle_revision": 0,
        "created_at": _integer(row["created_at"], "project.created_at"),
        "updated_at": _integer(row["updated_at"], "project.updated_at"),
    }


def _mapped_seed(
    *,
    seed_id: str,
    owner_id: str,
    title: str,
    payload: SeedPayload,
    created_at: int,
) -> dict[str, object]:
    return {
        "id": seed_id,
        "project_id": owner_id,
        "title": title,
        "status": "candidate",
        "payload_json": canonical_json(payload),
        "content_hash": canonical_hash(payload),
        "created_at": created_at,
        "updated_at": created_at,
    }


def _map_v11_seed(
    row: Mapping[str, object], project_id: str,
) -> dict[str, object]:
    seed_id = _identifier(row["id"], "seed.id")
    owner_id = _identifier(row["project_id"], "seed.project_id")
    if owner_id != project_id:
        raise ResetValidationError("M2 requested seed belongs to another project")
    title = _text(row["title"], "seed.title", max_length=200)
    try:
        decoded = (
            json.loads(row["premise_json"])
            if isinstance(row["premise_json"], str)
            else row["premise_json"]
        )
        payload = SeedPayload.model_validate(decoded)
    except (TypeError, ValueError):
        raise ResetValidationError(
            "M2 seed payload is not a valid current SeedPayload"
        ) from None
    if payload.title != title:
        raise ResetValidationError("M2 seed title and payload disagree")
    if row["content_hash"] != canonical_hash(payload):
        raise ResetValidationError("M2 seed content_hash does not match payload")
    if _text(row["status"], "seed.status", max_length=24) != "candidate":
        raise ResetValidationError("M2 seed identities must remain candidates")
    return _mapped_seed(
        seed_id=seed_id,
        owner_id=owner_id,
        title=title,
        payload=payload,
        created_at=_integer(row["created_at"], "seed.created_at"),
    )


def _map_provider(row: Mapping[str, object]) -> dict[str, object]:
    base_url = _text(row["base_url"], "provider.base_url", max_length=2048)
    api_key = _text(row["api_key"], "provider.api_key", max_length=65_535)
    if not base_url or not api_key:
        raise ResetValidationError(
            "Preserved Provider requires non-empty connection fields"
        )
    lifecycle_status = _text(
        row.get("lifecycle_status", "active"),
        "provider.lifecycle_status",
        max_length=16,
    )
    deleted_at_value = row.get("deleted_at")
    deleted_at = (
        None
        if deleted_at_value is None
        else _integer(deleted_at_value, "provider.deleted_at", minimum=0)
    )
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
        "lifecycle_status": lifecycle_status,
        "deleted_at": deleted_at,
        "created_at": _integer(row["created_at"], "provider.created_at"),
        "updated_at": _integer(row["updated_at"], "provider.updated_at"),
    }


async def _load_v11_preserved_state(
    admin_session,
    database_name: str,
    request: ResetRequest,
    *,
    target_schema: bool = False,
) -> _PreservedState:
    project_columns = _PROJECT_COLUMNS if target_schema else _V11_PROJECT_COLUMNS
    projects = await admin_session.fetchall(
        f"SELECT {', '.join(project_columns)} FROM {_qualified(database_name, 'projects')} WHERE title=%s",
        (request.project_title,),
    )
    if len(projects) != 1:
        raise ResetValidationError("M2 fresh state requires exactly one requested project")
    project = _map_project(projects[0])
    seed_rows = await admin_session.fetchall(
        f"SELECT s.id,s.project_id,JSON_UNQUOTE(JSON_EXTRACT(r.payload_json,'$.title')) AS title,"
        f"r.payload_json AS premise_json,r.content_hash,s.status,s.created_at,"
        f"r.id AS source_revision_id,h.revision_id AS head_revision_id,"
        f"h.content_hash AS head_hash,h.revision AS head_revision,"
        f"r.revision AS source_revision "
        f"FROM {_qualified(database_name, 'creative_seeds')} s "
        f"JOIN {_qualified(database_name, 'creative_seed_heads')} h ON h.seed_id=s.id "
        f"JOIN {_qualified(database_name, 'creative_seed_revisions')} r ON r.id=h.revision_id "
        "WHERE s.project_id=%s ORDER BY title,s.id",
        (project["id"],),
    )
    if len(seed_rows) != 3 or Counter(row["title"] for row in seed_rows) != Counter(request.seed_titles):
        raise ResetValidationError("M2 fresh state requires exactly the requested three seeds")
    if any(
        row.get("head_revision") != 1
        or row.get("source_revision") != 1
        or row.get("head_revision_id") != row.get("source_revision_id")
        or row.get("head_hash") != row.get("content_hash")
        for row in seed_rows
    ):
        raise ResetValidationError("M2 seed heads must all be revision 1")
    seeds = tuple(_map_v11_seed(row, str(project["id"])) for row in seed_rows)
    selected = await admin_session.fetchone(
        f"SELECT x.seed_id,x.seed_revision_id,"
        f"JSON_UNQUOTE(JSON_EXTRACT(r.payload_json,'$.title')) AS title,"
        f"x.seed_hash,r.content_hash,x.selection_revision "
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
        or selected.get("seed_id") != next(
            row["id"] for row in seeds if row["title"] == SELECTED_SEED_TITLE
        )
        or selected.get("seed_revision_id") != next(
            row["source_revision_id"]
            for row in seed_rows if row["title"] == SELECTED_SEED_TITLE
        )
    ):
        raise ResetValidationError(f"M2 selected seed must be {SELECTED_SEED_TITLE}")
    provider_rows = await admin_session.fetchall(
        f"SELECT {', '.join(_PROVIDER_COLUMNS)} FROM {_qualified(database_name, 'provider_profiles')} ORDER BY sort_order,id"
    )
    if any(
        row.get("lifecycle_status") != "active" or row.get("deleted_at") is not None
        for row in provider_rows
    ):
        raise ResetValidationError(
            "M2 fresh state requires every Provider to be active and not deleted"
        )
    providers = tuple(_map_provider(row) for row in provider_rows)
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
        f"SELECT r.id,r.project_id,r.revision,r.content_hash,r.source_project_id,"
        f"h.revision AS head_revision,h.binding_revision_id,"
        f"h.content_hash AS head_hash "
        f"FROM {_qualified(database_name, 'project_model_binding_heads')} h "
        f"JOIN {_qualified(database_name, 'project_model_binding_revisions')} r ON r.id=h.binding_revision_id WHERE h.project_id=%s",
        (project["id"],),
    )
    if binding is None:
        raise ResetValidationError("M2 binding head is missing")
    item_rows = await admin_session.fetchall(
        f"SELECT i.task_key,i.resolution_status,i.provider_id,"
        f"i.provider_name_snapshot,i.model_name_snapshot,i.item_hash,"
        f"p.name AS provider_name,p.model_name AS provider_model,"
        f"p.enabled AS provider_enabled,p.lifecycle_status AS provider_lifecycle "
        f"FROM {_qualified(database_name, 'project_model_binding_items')} i "
        f"LEFT JOIN {_qualified(database_name, 'provider_profiles')} p "
        f"ON p.id=i.provider_id WHERE i.binding_revision_id=%s "
        "ORDER BY FIELD(i.task_key,'seed','planning','writing','audit',"
        "'summary','extraction','polish','market')",
        (binding.get("id"),),
    )
    try:
        items = tuple(BindingItem(
            task_key=row["task_key"],
            resolution_status=row["resolution_status"],
            provider_id=row["provider_id"],
            provider_name_snapshot=row["provider_name_snapshot"],
            model_name_snapshot=row["model_name_snapshot"],
        ) for row in item_rows)
        revision = BindingRevision(
            project_id=str(project["id"]), revision=1, items=items,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ResetValidationError("M2 binding snapshot is invalid") from exc
    binding_hash = canonical_hash(revision)
    if (
        len(item_rows) != len(TASK_KEYS)
        or any(
            row.get("item_hash") != canonical_hash(item)
            or row.get("provider_enabled") != 1
            or row.get("provider_lifecycle") != "active"
            or row.get("provider_name") != item.provider_name_snapshot
            or row.get("provider_model") != item.model_name_snapshot
            for row, item in zip(item_rows, items)
        )
        or binding.get("project_id") != project["id"]
        or binding.get("revision") != 1
        or binding.get("head_revision") != 1
        or binding.get("binding_revision_id") != binding.get("id")
        or binding.get("source_project_id") is not None
        or binding.get("content_hash") != binding_hash
        or binding.get("head_hash") != binding_hash
    ):
        raise ResetValidationError(
            "M2 binding head must be the exact active revision1 snapshot"
        )
    head = await admin_session.fetchone(
        f"SELECT revision,creation_contract_id,style_contract_id,creation_hash,style_hash "
        f"FROM {_qualified(database_name, 'project_contract_heads')} WHERE project_id=%s",
        (project["id"],),
    )
    canon = await admin_session.fetchone(
        f"SELECT revision_number,parent_revision_number,idempotency_key,"
        f"source_type,source_id,content_hash "
        f"FROM {_qualified(database_name, 'canon_revisions')} WHERE project_id=%s",
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
    } or canon != {
        "revision_number": 0,
        "parent_revision_number": 0,
        "idempotency_key": ProjectService.bootstrap_idempotency_key(
            str(project["id"])
        ),
        "source_type": "bootstrap",
        "source_id": None,
        "content_hash": empty_hash,
    } or projection != {
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
    source_kind: str,
    mode: str | None = None,
) -> ResetReport:
    resolved_mode = mode or ("execute" if executed else "dry-run")
    target_counts = (
        ("projects", 1),
        ("seeds", len(state.seeds)),
        ("selectedSeeds", 1),
        ("providers", len(state.providers)),
        ("seedRevisions", len(state.seeds)),
        ("seedHeads", len(state.seeds)),
        ("bindingRevisions", 1),
        ("bindingItems", len(TASK_KEYS)),
        ("bindingHeads", 1),
        ("canonRevisions", 1),
        ("projectionHeads", 1),
        ("contractHeads", 1),
    )
    if source_kind == "v1.1-source":
        source_schema_version = V11_SCHEMA_VERSION
        source_manifest_hash = V11_MANIFEST_HASH
        source_table_names = V11_TABLE_NAMES
        source_counts = target_counts
        source_verified_empty_tables = VERIFIED_EMPTY_TABLES
    elif source_kind == "v1.2-target":
        source_schema_version = EXPECTED_SCHEMA_VERSION
        source_manifest_hash = manifest_hash()
        source_table_names = created_table_names()
        source_counts = target_counts
        source_verified_empty_tables = VERIFIED_EMPTY_TABLES
    else:
        raise ResetValidationError("Unsupported reset report source manifest")
    return ResetReport(
        mode=resolved_mode,
        executed=executed,
        source_kind=source_kind,
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
        source_schema_version=source_schema_version,
        source_manifest_hash=source_manifest_hash,
        source_table_names=source_table_names,
        source_counts=source_counts,
        source_verified_empty_tables=source_verified_empty_tables,
        target_schema_version=EXPECTED_SCHEMA_VERSION,
        target_manifest_hash=manifest_hash(),
        target_table_names=created_table_names(),
        target_expected_counts=target_counts,
        target_expected_empty_tables=VERIFIED_EMPTY_TABLES,
        target_verified=executed or resolved_mode == "no-op",
    )


def format_reset_report(report: ResetReport) -> str:
    """Render one escaped JSON receipt containing only public allowlisted fields."""
    receipt = {
        "mode": report.mode,
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
        "source": {
            "kind": report.source_kind,
            "schemaVersion": report.source_schema_version,
            "manifestHash": report.source_manifest_hash,
            "tables": list(report.source_table_names),
            "counts": dict(report.source_counts),
            "verifiedEmptyTables": list(report.source_verified_empty_tables),
        },
        "target": {
            "kind": "v1.2-target",
            "schemaVersion": report.target_schema_version,
            "manifestHash": report.target_manifest_hash,
            "tables": list(report.target_table_names),
            "expectedCounts": dict(report.target_expected_counts),
            "expectedEmptyTables": list(report.target_expected_empty_tables),
            "verified": report.target_verified,
        },
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
        if kind == "v1.1-source":
            return await _load_v11_preserved_state(
                admin_session, database_name, request,
            )
        if kind == "v1.2-target":
            return await _load_v11_preserved_state(
                admin_session, database_name, request, target_schema=True,
            )
        raise ResetValidationError("Unsupported reset source manifest")

    initial_state = await load_state(source_kind)
    if not execute:
        report = _report(
            database_name, initial_state, executed=False, source_kind=source_kind,
        )
        output(format_reset_report(report))
        return report

    acquired = False
    ddl_owned = False
    destructive_ddl_attempted = False
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
        locked_kind = await _classify_reset_source(admin_session, database_name)
        if locked_kind != source_kind:
            raise ResetValidationError("Reset source inventory changed while waiting for lock")
        locked_state = await load_state(locked_kind)
        if locked_state != initial_state:
            raise ResetValidationError("Reset foundation changed while waiting for lock")
        if locked_kind == "v1.2-target":
            report = _report(
                database_name, locked_state, executed=False, mode="no-op",
                source_kind=source_kind,
            )
        else:
            await _verify_reset_server_capabilities(admin_session)
            _guard_database(database_name, product_execute_authorized)
            destructive_ddl_attempted = True
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
            except BaseException:
                raise
            transaction_started = False
            if await _classify_reset_source(admin_session, database_name) != "v1.2-target":
                raise ResetValidationError("Rebuilt database does not match the v1.2 manifest")
            readback_state = await _load_v11_preserved_state(
                admin_session, database_name, request, target_schema=True,
            )
            if readback_state != locked_state:
                raise ResetValidationError("Rebuilt v1.2 foundation differs from the locked snapshot")
            report = _report(
                database_name, readback_state, executed=True, source_kind=source_kind,
            )
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
        if body_error is not None and ddl_owned:
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
            if not destructive_ddl_attempted:
                raise combined
            raise ResetPartialStateError(
                f"Writer Core reset failed; {database_name} may remain partially reset"
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
    parser.add_argument("--confirm-host")
    parser.add_argument("--confirm-port", type=int)
    parser.add_argument("--execute", action="store_true")
    return parser


async def _reset_connection_factory(connection_config: Mapping[str, object]):
    """Open the explicitly selected reset target, including its database."""
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
        close_error: BaseException | None = None
        try:
            ensure_closed = getattr(connection, "ensure_closed", None)
            if ensure_closed is not None:
                await ensure_closed()
            else:
                connection.close()
        except BaseException as exc:
            close_error = exc
        if close_error is not None:
            raise BaseExceptionGroup(
                "reset cursor creation and connection close both failed",
                [cursor_error, close_error],
            ) from cursor_error
        raise
    return _AiomysqlAdminSession(connection, cursor)


async def _verify_product_connection_identity(admin_session) -> None:
    row = await admin_session.fetchone(
        "SELECT DATABASE() AS database_name, @@port AS server_port, "
        "CONCAT(@@server_uuid, ':', VERSION()) AS server_identity"
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
