"""SELECT-only, fail-closed verifier for the Milestone 2 product state."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import PurePosixPath, PureWindowsPath
import re
import sys
from typing import Awaitable, Callable, Mapping, Sequence

from pydantic import ValidationError

from backend.domain.assets import (
    ExperienceCardRevision,
    StyleTemplateRevision,
    load_asset_package,
)
from backend.domain.contracts import CreationContractPayload, StyleContractPayload
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.model_bindings import BindingItem, BindingRevision, TASK_KEYS
from backend.domain.seeds import SeedPayload
from backend.domain.story_engines import StoryEngineOption
from backend.schema_manifest import created_table_names, manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from backend.scripts.seed_writer_assets import MANIFEST_PATH
from backend.services.contracts import ContractService, _strict_engine, style_contract_hash
from backend.services.projects import ProjectService
from backend.services.projections import build_projection_bundle


_DATABASE_NAME = re.compile(r"[A-Za-z0-9_]+\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_MODES = frozenset({"foundation", "corpus-import", "provider-l5"})


class ProductVerificationError(RuntimeError):
    """The database is not exactly the requested M2 state."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProductVerificationError(message)


def _integer(row: Mapping[str, object], key: str) -> int:
    value = row.get(key)
    if type(value) is not int:
        raise ProductVerificationError(f"M2 receipt field {key} must be an integer")
    return value


def _hash(value: object, label: str) -> str:
    _require(isinstance(value, str) and _HASH.fullmatch(value) is not None,
             f"{label} hash is invalid")
    return value


def _json_object(value: object, label: str) -> dict[str, object]:
    try:
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("utf-8")
        if isinstance(value, str):
            value = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProductVerificationError(f"{label} JSON is invalid") from None
    _require(isinstance(value, dict), f"{label} JSON is invalid")
    return value


def _json_array(value: object, label: str) -> list[object]:
    try:
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("utf-8")
        if isinstance(value, str):
            value = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProductVerificationError(f"{label} JSON is invalid") from None
    _require(isinstance(value, list), f"{label} JSON is invalid")
    return value


def _relative_path(value: object) -> str:
    _require(isinstance(value, str) and bool(value), "Corpus relative path is missing")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    _require(
        "\\" not in value
        and not posix.is_absolute()
        and not windows.is_absolute()
        and not windows.drive
        and bool(posix.parts)
        and all(part not in {"", ".", ".."} for part in posix.parts)
        and posix.as_posix() == value,
        "Corpus source must use a safe relative path",
    )
    return value


_DATABASE_IDENTITY_SQL = """/* m2:database_identity */
SELECT DATABASE() AS database_name"""

_SCHEMA_INVENTORY_SQL = """/* m2:schema_inventory */
SELECT TABLE_NAME FROM information_schema.TABLES
WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"""

_METADATA_SQL = """/* m2:metadata */
SELECT schema_version,manifest_hash FROM schema_metadata WHERE singleton_id=1"""

_FOUNDATION_SQL = """/* m2:foundation */
SELECT p.id AS project_id,p.title AS project_title,p.status AS project_status,
       p.current_chapter,
       (SELECT COUNT(*) FROM projects) AS project_count,
       (SELECT COUNT(*) FROM creative_seeds WHERE project_id=p.id) AS seed_count,
       ss.seed_id AS selected_seed_id,ss.seed_revision_id AS selected_seed_revision_id,
       JSON_UNQUOTE(JSON_EXTRACT(sr.payload_json,'$.title')) AS selected_seed_title,
       ss.seed_hash AS selected_seed_hash,sr.content_hash AS selected_revision_hash,
       ss.selection_revision,
       (SELECT COUNT(*) FROM provider_profiles) AS provider_count,
       bh.binding_revision_id,bh.revision AS binding_revision,
       br.content_hash AS binding_hash,bh.content_hash AS binding_head_hash,
       br.source_project_id AS binding_source_project_id,
       (SELECT COUNT(*) FROM project_model_binding_items bi
          WHERE bi.binding_revision_id=bh.binding_revision_id) AS binding_item_count,
       (SELECT COUNT(*) FROM project_model_binding_items bi
          WHERE bi.binding_revision_id=bh.binding_revision_id
            AND bi.resolution_status='bound') AS bound_item_count,
       ch.revision AS contract_revision,ch.creation_contract_id,ch.style_contract_id,
       ch.creation_hash,ch.style_hash,
       cr.revision_number AS canon_revision,
       cr.parent_revision_number AS canon_parent_revision,
       cr.idempotency_key AS canon_idempotency_key,
       cr.source_type AS canon_source_type,cr.source_id AS canon_source_id,
       cr.content_hash AS canon_hash,
       ph.canon_revision_number AS projection_canon_revision,
       ph.projection_revision_number AS projection_revision,
       ph.content_hash AS projection_hash
FROM projects p
JOIN project_selected_seeds ss ON ss.project_id=p.id
JOIN creative_seed_revisions sr ON sr.id=ss.seed_revision_id AND sr.seed_id=ss.seed_id
JOIN project_model_binding_heads bh ON bh.project_id=p.id
JOIN project_model_binding_revisions br ON br.id=bh.binding_revision_id
JOIN project_contract_heads ch ON ch.project_id=p.id
JOIN projection_heads ph ON ph.project_id=p.id
JOIN canon_revisions cr ON cr.project_id=p.id AND cr.revision_number=ph.canon_revision_number
LIMIT 2"""

_SEED_REVISIONS_SQL = """/* m2:seed_revisions */
SELECT s.id AS seed_id,s.status,r.id AS seed_revision_id,r.revision,r.payload_json,
       r.content_hash,h.revision_id AS head_revision_id,h.revision AS head_revision,
       h.content_hash AS head_hash
FROM creative_seeds s JOIN creative_seed_revisions r ON r.seed_id=s.id
JOIN creative_seed_heads h ON h.seed_id=s.id
WHERE s.project_id=%s ORDER BY s.id"""

_PROVIDERS_SQL = """/* m2:providers */
SELECT id,name,model_name,enabled,lifecycle_status,deleted_at
FROM provider_profiles ORDER BY sort_order,id"""

_BINDING_ITEMS_SQL = """/* m2:binding_items */
SELECT i.task_key,i.resolution_status,i.provider_id,i.provider_name_snapshot,
       i.model_name_snapshot,i.item_hash,p.name AS provider_name,
       p.model_name AS provider_model,p.enabled AS provider_enabled,
       p.lifecycle_status AS provider_lifecycle
FROM project_model_binding_items i LEFT JOIN provider_profiles p ON p.id=i.provider_id
WHERE i.binding_revision_id=%s
ORDER BY FIELD(i.task_key,'seed','planning','writing','audit','summary','extraction','polish','market')"""

_LATER_COUNTS_SQL = """/* m2:later_counts */
SELECT
 (SELECT COUNT(*) FROM story_engine_batches) AS story_engine_batches,
 (SELECT COUNT(*) FROM story_engine_options) AS story_engine_options,
 (SELECT COUNT(*) FROM project_contract_drafts) AS project_contract_drafts,
 (SELECT COUNT(*) FROM creation_contracts) AS creation_contracts,
 (SELECT COUNT(*) FROM style_contracts) AS style_contracts,
 (SELECT COUNT(*) FROM contract_confirmation_requests) AS contract_confirmation_requests,
 (SELECT COUNT(*) FROM volume_plans) AS volume_plans,
 (SELECT COUNT(*) FROM story_blocks) AS story_blocks,
 (SELECT COUNT(*) FROM story_stages) AS story_stages,
 (SELECT COUNT(*) FROM scene_tasks) AS scene_tasks,
 (SELECT COUNT(*) FROM chapter_sessions) AS chapter_sessions,
 (SELECT COUNT(*) FROM working_drafts) AS working_drafts,
 (SELECT COUNT(*) FROM draft_candidates) AS draft_candidates,
 (SELECT COUNT(*) FROM finalization_change_sets) AS finalization_change_sets,
 (SELECT COUNT(*) FROM finalization_records) AS finalization_records,
 (SELECT COUNT(*) FROM final_chapters) AS final_chapters,
 (SELECT COUNT(*) FROM canon_entities) AS canon_entities,
 (SELECT COUNT(*) FROM entity_aliases) AS entity_aliases,
 (SELECT COUNT(*) FROM canon_events) AS canon_events,
 (SELECT COUNT(*) FROM current_state_projections) AS current_state_projections,
 (SELECT COUNT(*) FROM memory_views) AS memory_views,
 (SELECT COUNT(*) FROM arc_projections) AS arc_projections,
 (SELECT COUNT(*) FROM plot_thread_projections) AS plot_thread_projections,
 (SELECT COUNT(*) FROM reference_uses) AS reference_uses,
 (SELECT COUNT(*) FROM creation_contract_engine_refs) AS creation_contract_engine_refs,
 (SELECT COUNT(*) FROM style_contract_template_refs) AS style_contract_template_refs,
 (SELECT COUNT(*) FROM creation_contract_experience_refs) AS creation_contract_experience_refs,
 (SELECT COUNT(*) FROM creation_contract_corpus_refs) AS creation_contract_corpus_refs"""

_ASSET_COUNTS_SQL = """/* m2:asset_counts */
SELECT (SELECT COUNT(*) FROM style_template_heads) AS style_head_count,
 (SELECT COUNT(*) FROM style_templates) AS style_revision_count,
 (SELECT COUNT(*) FROM style_template_heads h JOIN style_templates t
   ON t.id=h.style_template_id AND t.revision=h.revision AND t.content_hash=h.content_hash
   WHERE t.status='active') AS active_style_head_count,
 (SELECT COUNT(*) FROM experience_card_heads) AS card_head_count,
 (SELECT COUNT(*) FROM experience_cards) AS card_revision_count,
 (SELECT COUNT(*) FROM experience_card_heads h JOIN experience_cards c
   ON c.id=h.experience_card_id AND c.revision=h.revision AND c.content_hash=h.content_hash
   WHERE c.status='active') AS active_card_head_count"""

_STYLE_HEADS_SQL = """/* m2:style_heads */
SELECT t.id,t.stable_key,t.revision,t.name AS label,NULL AS category,
       t.payload_json,t.provenance_json,t.content_hash,t.status,
       h.revision AS head_revision,h.content_hash AS head_hash
FROM style_template_heads h JOIN style_templates t ON t.id=h.style_template_id
ORDER BY t.stable_key"""

_CARD_HEADS_SQL = """/* m2:card_heads */
SELECT c.id,c.stable_key,c.revision,c.title AS label,c.category,
       c.payload_json,c.provenance_json,c.content_hash,c.status,
       h.revision AS head_revision,h.content_hash AS head_hash
FROM experience_card_heads h JOIN experience_cards c ON c.id=h.experience_card_id
ORDER BY c.stable_key"""

_CORPUS_SQL = """/* m2:corpus */
SELECT s.id AS source_id,s.relative_path,s.source_hash,s.revision AS source_revision,
       s.file_size,s.status,s.parser_version,s.normalizer_version,
       s.fragmenter_version,s.index_version,
       (SELECT COUNT(*) FROM corpus_chapters c WHERE c.corpus_source_id=s.id) AS chapter_count,
       (SELECT COUNT(*) FROM corpus_fragments f JOIN corpus_chapters c
          ON c.id=f.corpus_chapter_id WHERE c.corpus_source_id=s.id) AS fragment_count,
       (SELECT COUNT(*) FROM corpus_import_runs r
          WHERE r.corpus_source_id=s.id AND r.status='succeeded') AS succeeded_run_count,
       (SELECT COUNT(*) FROM corpus_chapters c WHERE c.corpus_source_id=s.id AND
          (c.raw_byte_start<0 OR c.raw_byte_end<c.raw_byte_start OR
           c.normalized_char_start<0 OR c.normalized_char_end<c.normalized_char_start))
          AS invalid_boundary_count,
       (SELECT COUNT(*) FROM corpus_import_runs r WHERE r.corpus_source_id=s.id
          AND r.status='succeeded' AND (
            NOT (JSON_UNQUOTE(JSON_EXTRACT(r.parser_versions_json,'$.parserVersion')) <=> s.parser_version) OR
            NOT (JSON_UNQUOTE(JSON_EXTRACT(r.parser_versions_json,'$.normalizerVersion')) <=> s.normalizer_version) OR
            NOT (JSON_UNQUOTE(JSON_EXTRACT(r.parser_versions_json,'$.fragmenterVersion')) <=> s.fragmenter_version) OR
            NOT (JSON_UNQUOTE(JSON_EXTRACT(r.parser_versions_json,'$.indexVersion')) <=> s.index_version)))
          AS invalid_version_count,
       (SELECT MIN(c.raw_byte_start) FROM corpus_chapters c WHERE c.corpus_source_id=s.id) AS first_byte_start,
       (SELECT MAX(c.raw_byte_end) FROM corpus_chapters c WHERE c.corpus_source_id=s.id) AS last_byte_end,
       (SELECT MIN(c.normalized_char_start) FROM corpus_chapters c WHERE c.corpus_source_id=s.id) AS first_char_start,
       (SELECT MAX(c.normalized_char_end) FROM corpus_chapters c WHERE c.corpus_source_id=s.id) AS last_char_end
FROM corpus_sources s WHERE s.source_hash=%s ORDER BY s.imported_at DESC,s.id DESC LIMIT 2"""

_L5_SQL = """/* m2:l5 */
SELECT b.id AS batch_id,
       (SELECT COUNT(*) FROM story_engine_batches x WHERE x.project_id=ss.project_id) AS batch_count,
       b.source_type,b.status AS batch_status,b.seed_id AS batch_seed_id,
       b.seed_revision_id AS batch_seed_revision_id,b.seed_hash AS batch_seed_hash,
       b.binding_revision_id AS batch_binding_revision_id,b.binding_hash AS batch_binding_hash,
       b.attempt_id, b.request_hash,b.raw_response_hash,b.provider_id AS batch_provider_id,
       b.model_name_snapshot AS batch_model_name,
       bi.provider_id AS binding_provider_id,
       bi.provider_name_snapshot AS binding_provider_name,
       bi.model_name_snapshot AS binding_model_name,
       p.name AS provider_name,p.model_name AS provider_model,
       p.enabled AS provider_enabled,p.lifecycle_status AS provider_lifecycle,
       (SELECT COUNT(*) FROM story_engine_options o WHERE o.batch_id=b.id) AS option_count,
       (SELECT COUNT(DISTINCT o.content_hash) FROM story_engine_options o WHERE o.batch_id=b.id)
         AS distinct_option_hash_count,
       h.revision AS contract_head_revision,h.creation_contract_id,h.style_contract_id,
       c.content_hash AS creation_hash,h.creation_hash AS head_creation_hash,
       st.content_hash AS style_hash,h.style_hash AS head_style_hash,
       c.revision AS creation_revision,st.revision AS style_revision,
       c.seed_id AS creation_seed_id,c.seed_revision_id AS creation_seed_revision_id,
       c.seed_hash AS creation_seed_hash,c.binding_revision_id AS creation_binding_revision_id,
       c.binding_hash AS creation_binding_hash,er.engine_option_id,er.engine_hash,
       o.content_hash AS engine_option_hash,o.batch_id AS engine_option_batch_id,
       er.engine_option_id AS selected_engine_option_id
FROM project_selected_seeds ss
JOIN project_model_binding_heads bh ON bh.project_id=ss.project_id
JOIN project_model_binding_items bi ON bi.binding_revision_id=bh.binding_revision_id
 AND bi.task_key='seed'
JOIN provider_profiles p ON p.id=bi.provider_id
JOIN project_contract_heads h ON h.project_id=ss.project_id
JOIN creation_contracts c ON c.id=h.creation_contract_id
JOIN style_contracts st ON st.id=h.style_contract_id AND st.creation_contract_id=c.id
JOIN creation_contract_engine_refs er ON er.creation_contract_id=c.id
JOIN story_engine_options o ON o.id=er.engine_option_id
JOIN story_engine_batches b ON b.id=o.batch_id
LIMIT 2"""

_L5_OPTIONS_SQL = """/* m2:l5_options */
SELECT id,option_order,payload_json,content_hash FROM story_engine_options
WHERE batch_id=%s ORDER BY option_order"""
_L5_CONFIRMATIONS_SQL = """/* m2:l5_confirmations */
SELECT id,status,creation_contract_id,style_contract_id,result_revision
FROM contract_confirmation_requests WHERE project_id=%s ORDER BY created_at,id"""
_L5_CONTRACT_PAYLOAD_SQL = """/* m2:l5_contract_payload */
SELECT c.content_json AS creation_json,c.content_hash AS creation_content_hash,
       s.merged_style_json AS style_json,s.likes_json,s.dislikes_json,
       s.content_hash AS style_content_hash,c.reference_manifest_json,
       c.reference_manifest_hash
FROM creation_contracts c JOIN style_contracts s ON s.creation_contract_id=c.id
WHERE c.id=%s AND s.id=%s"""
_L5_STYLE_REFS_SQL = """/* m2:l5_style_refs */
SELECT r.role,r.style_template_id,r.asset_revision,r.asset_hash,a.content_hash AS actual_asset_hash,r.sort_order
FROM style_contract_template_refs r LEFT JOIN style_templates a
 ON a.id=r.style_template_id AND a.revision=r.asset_revision
WHERE r.style_contract_id=%s ORDER BY r.sort_order"""
_L5_EXPERIENCE_REFS_SQL = """/* m2:l5_experience_refs */
SELECT r.experience_card_id,r.asset_revision,r.asset_hash,a.content_hash AS actual_asset_hash,r.sort_order
FROM creation_contract_experience_refs r LEFT JOIN experience_cards a
 ON a.id=r.experience_card_id AND a.revision=r.asset_revision
WHERE r.creation_contract_id=%s ORDER BY r.sort_order"""
_L5_CORPUS_REFS_SQL = """/* m2:l5_corpus_refs */
SELECT r.corpus_source_id,r.source_revision,r.source_hash,a.source_hash AS actual_source_hash,
       r.selection_mode,r.sort_order
FROM creation_contract_corpus_refs r LEFT JOIN corpus_sources a
 ON a.id=r.corpus_source_id AND a.revision=r.source_revision
WHERE r.creation_contract_id=%s ORDER BY r.sort_order"""


async def _verify_foundation(
    session, *, expected_database: str, require_l5: bool
):
    identity = await session.fetchone(_DATABASE_IDENTITY_SQL)
    _require(
        identity is not None
        and identity.get("database_name") == expected_database,
        "Current database identity does not match the explicit expected database identity",
    )
    inventory = await session.fetchall(_SCHEMA_INVENTORY_SQL)
    names = tuple(row.get("TABLE_NAME") for row in inventory)
    _require(len(names) == 49 and set(names) == set(created_table_names()),
             "M2 table inventory must be the exact 49-table closed set")
    metadata = await session.fetchone(_METADATA_SQL)
    _require(metadata is not None, "M2 schema metadata is missing")
    _require(metadata.get("schema_version") == EXPECTED_SCHEMA_VERSION,
             "M2 schema version mismatch")
    _require(metadata.get("manifest_hash") == manifest_hash(), "M2 manifest hash mismatch")
    row = await session.fetchone(_FOUNDATION_SQL)
    _require(row is not None, "M2 foundation is missing")
    _require(_integer(row, "project_count") == 1, "M2 requires exactly one project")
    _require(row.get("project_title") == "永乐大典", "M2 project must be 永乐大典")
    _require(row.get("project_status") == "drafting", "M2 project must remain drafting")
    _require(_integer(row, "current_chapter") == 0, "M2 project must remain at chapter 0")
    _require(_integer(row, "seed_count") == 3, "M2 requires exactly three seeds")
    seeds = await session.fetchall(_SEED_REVISIONS_SQL, (row.get("project_id"),))
    _require(len(seeds) == 3, "M2 seed inventory must contain exactly three revisions")
    titles = []
    for seed in seeds:
        try:
            payload = SeedPayload.model_validate(
                _json_object(seed.get("payload_json"), "seed payload"), strict=True
            )
        except ValidationError:
            raise ProductVerificationError("M2 seed payload is invalid") from None
        content_hash = canonical_hash(payload)
        _require(seed.get("status") == "candidate", "M2 seeds must remain candidates")
        _require(_integer(seed, "revision") == 1 and _integer(seed, "head_revision") == 1,
                 "M2 seed head must remain revision 1")
        _require(seed.get("seed_revision_id") == seed.get("head_revision_id")
                 and seed.get("content_hash") == content_hash
                 and seed.get("head_hash") == content_hash,
                 "M2 seed head hash mismatch")
        titles.append(payload.title)
    _require(sorted(titles) == sorted(("永乐长明", "文渊山海", "典镇山河")),
             "M2 seed titles are invalid")
    selected = next(seed for seed in seeds if
                    _json_object(seed["payload_json"], "seed payload")["title"] == "典镇山河")
    _require(row.get("selected_seed_title") == "典镇山河"
             and row.get("selected_seed_id") == selected.get("seed_id")
             and row.get("selected_seed_revision_id") == selected.get("seed_revision_id")
             and row.get("selected_seed_hash") == selected.get("content_hash")
             and row.get("selected_revision_hash") == selected.get("content_hash")
             and _integer(row, "selection_revision") == 1,
             "M2 selected seed must be 典镇山河 at revision 1")
    _require(_integer(row, "provider_count") == 2, "M2 requires exactly two Providers")
    providers = await session.fetchall(_PROVIDERS_SQL)
    _require(len(providers) == 2, "M2 requires exactly two Provider rows")
    for provider in providers:
        _require(
            all(
                isinstance(provider.get(key), str) and bool(provider.get(key))
                for key in ("id", "name", "model_name")
            )
            and type(provider.get("enabled")) is int
            and provider.get("enabled") in (0, 1)
            and provider.get("lifecycle_status") == "active"
            and provider.get("deleted_at") is None,
            "M2 Provider rows must all be active and non-deleted",
        )
    item_rows = await session.fetchall(_BINDING_ITEMS_SQL, (row.get("binding_revision_id"),))
    try:
        items = tuple(BindingItem.model_validate({key: item.get(key) for key in (
            "task_key", "resolution_status", "provider_id", "provider_name_snapshot",
            "model_name_snapshot",
        )}, strict=True) for item in item_rows)
        revision = BindingRevision(
            project_id=str(row.get("project_id")), revision=1, items=items,
        )
    except (TypeError, ValidationError, ValueError):
        raise ProductVerificationError("M2 binding task closed set is invalid") from None
    _require(tuple(item.task_key for item in items) == TASK_KEYS,
             "M2 binding must contain the exact eight task closed set")
    for item_row, item in zip(item_rows, items, strict=True):
        _require(item_row.get("provider_enabled") == 1
                 and item_row.get("provider_lifecycle") == "active",
                 "M2 binding Provider must be active and enabled")
        _require(item_row.get("provider_name") == item.provider_name_snapshot == "联通云"
                 and item_row.get("provider_model") == item.model_name_snapshot
                 == "deepseek-v4-flash",
                 "M2 tasks must bind 联通云/deepseek-v4-flash")
        _require(item_row.get("item_hash") == canonical_hash(item),
                 "M2 binding item hash mismatch")
    binding_hash = canonical_hash(revision)
    _require(_integer(row, "binding_revision") == 1
             and row.get("binding_source_project_id") is None
             and row.get("binding_hash") == binding_hash
             and row.get("binding_head_hash") == binding_hash
             and _integer(row, "binding_item_count") == len(TASK_KEYS)
             and _integer(row, "bound_item_count") == len(TASK_KEYS),
             "M2 binding head canonical hash mismatch")
    expected_contract_revision = 1 if require_l5 else 0
    _require(_integer(row, "contract_revision") == expected_contract_revision,
             f"M2 requires contract head revision {expected_contract_revision}")
    if not require_l5:
        _require(all(row.get(key) is None for key in (
            "creation_contract_id", "style_contract_id", "creation_hash", "style_hash"
        )), "Head zero must not reference contracts")
    empty_hash = build_projection_bundle(0, ()).content_hash
    _require(_integer(row, "canon_revision") == 0
             and _integer(row, "canon_parent_revision") == 0
             and row.get("canon_idempotency_key") == ProjectService.bootstrap_idempotency_key(
                 str(row.get("project_id")))
             and row.get("canon_source_type") == "bootstrap"
             and row.get("canon_source_id") is None
             and row.get("canon_hash") == empty_hash,
             "M2 Canon bootstrap fact mismatch")
    _require(_integer(row, "projection_canon_revision") == 0
             and _integer(row, "projection_revision") == 0
             and row.get("projection_hash") == empty_hash,
             "M2 Projection head0 mismatch")
    return dict(metadata), dict(row), tuple(dict(item) for item in item_rows)


async def _verify_counts(session, *, require_l5: bool) -> None:
    row = await session.fetchone(_LATER_COUNTS_SQL)
    _require(row is not None, "M2 later-domain counts are missing")
    expected = {key: 0 for key in row}
    if require_l5:
        expected.update({
            "story_engine_batches": 1, "story_engine_options": 3,
            "creation_contracts": 1, "style_contracts": 1,
            "contract_confirmation_requests": 1,
            "creation_contract_engine_refs": 1,
            "style_contract_template_refs": 1,
            "creation_contract_experience_refs": 1,
            "creation_contract_corpus_refs": 1,
        })
    for key, value in expected.items():
        actual = _integer(row, key)
        label = key.replace("canon", "Canon")
        _require(actual == value,
                 f"M2 closed mode count mismatch for {label}")


def _asset_domain(row: Mapping[str, object], *, card: bool):
    values = {
        "stable_key": row.get("stable_key"), "revision": row.get("revision"),
        "title" if card else "name": row.get("label"),
        "payload": _json_object(row.get("payload_json"), "asset payload"),
        "provenance": _json_object(row.get("provenance_json"), "asset provenance"),
        "content_hash": row.get("content_hash"),
    }
    if card:
        values["category"] = row.get("category")
    try:
        asset = (ExperienceCardRevision if card else StyleTemplateRevision).model_validate(
            values, strict=True
        )
    except ValidationError:
        raise ProductVerificationError("M2 asset payload hash/package row is invalid") from None
    _require(canonical_hash(asset.payload) == asset.content_hash,
             "M2 asset payload hash mismatch")
    _require(row.get("status") == "active" and row.get("head_revision") == asset.revision
             and row.get("head_hash") == asset.content_hash,
             "M2 asset head package mismatch")
    return asset


async def _verify_assets(session) -> dict[str, object]:
    package = load_asset_package(MANIFEST_PATH, mode="release")
    counts = await session.fetchone(_ASSET_COUNTS_SQL)
    _require(counts is not None and all(_integer(counts, key) == value for key, value in {
        "style_head_count": 10, "style_revision_count": 10,
        "active_style_head_count": 10, "card_head_count": 64,
        "card_revision_count": 64, "active_card_head_count": 64,
    }.items()), "M2 assets require exactly 10 active style heads and 64 active card heads")
    style_rows = await session.fetchall(_STYLE_HEADS_SQL)
    card_rows = await session.fetchall(_CARD_HEADS_SQL)
    _require(all(row.get("content_hash") == row.get("head_hash") for row in style_rows),
             "M2 style head package hashes mismatch")
    _require(all(row.get("content_hash") == row.get("head_hash") for row in card_rows),
             "M2 experience-card head package hashes mismatch")
    styles = tuple(_asset_domain(row, card=False) for row in style_rows)
    cards = tuple(_asset_domain(row, card=True) for row in card_rows)
    _require(tuple(sorted(styles, key=lambda x: x.stable_key))
             == tuple(sorted(package.styles, key=lambda x: x.stable_key)),
             "M2 style head package hashes mismatch")
    _require(tuple(sorted(cards, key=lambda x: x.stable_key))
             == tuple(sorted(package.experience_cards, key=lambda x: x.stable_key)),
             "M2 experience-card head package hashes mismatch")
    return {"packageVersion": package.package_version,
            "packageHash": canonical_hash(package.manifest),
            "styleCount": 10, "cardCount": 64}


async def _verify_corpus(session, expected_source_hash: str) -> dict[str, object]:
    rows = await session.fetchall(_CORPUS_SQL, (expected_source_hash,))
    _require(
        len(rows) == 1,
        "M2 requires exactly one source for the specified corpus hash",
    )
    row = rows[0]
    source_hash = _hash(row.get("source_hash"), "Corpus source")
    _require(source_hash == expected_source_hash,
             "Corpus source hash does not match the explicit source hash")
    relative_path = _relative_path(row.get("relative_path"))
    _require(row.get("status") == "analyzed", "Corpus source must be analyzed")
    _require(_integer(row, "succeeded_run_count") == 1,
             "Corpus import must have exactly one succeeded run")
    chapter_count = _integer(row, "chapter_count")
    fragment_count = _integer(row, "fragment_count")
    _require(chapter_count > 0 and fragment_count > 0,
             "Corpus chapter and fragment counts must be positive")
    file_size = _integer(row, "file_size")
    _require(file_size > 0 and _integer(row, "invalid_boundary_count") == 0
             and _integer(row, "invalid_version_count") == 0
             and _integer(row, "first_byte_start") == 0
             and _integer(row, "last_byte_end") == file_size
             and _integer(row, "first_char_start") == 0
             and _integer(row, "last_char_end") > 0,
             "Corpus boundary/size/version evidence mismatch")
    versions = {}
    for public, field in (("parser", "parser_version"),
                          ("normalizer", "normalizer_version"),
                          ("fragmenter", "fragmenter_version"),
                          ("index", "index_version")):
        value = row.get(field)
        _require(isinstance(value, str) and bool(value),
                 "Corpus analysis versions are incomplete")
        versions[public] = value
    source_id = row.get("source_id")
    source_revision = _integer(row, "source_revision")
    _require(isinstance(source_id, str) and bool(source_id) and source_revision > 0,
             "Corpus source identity/revision is invalid")
    return {"sourceId": source_id, "sourceRevision": source_revision,
            "relativePath": relative_path, "sourceHash": source_hash,
            "chapterCount": chapter_count,
            "fragmentCount": fragment_count, "versions": versions}


async def _verify_l5(
    session,
    foundation: Mapping[str, object],
    binding_items,
    *,
    verified_corpus: Mapping[str, object],
):
    row = await session.fetchone(_L5_SQL)
    _require(row is not None, "M2 L5 evidence is missing")
    _require(_integer(row, "batch_count") == 1,
             "M2 L5 requires exactly one Provider batch")
    _require(row.get("source_type") == "provider" and row.get("batch_status") == "succeeded",
             "M2 L5 batch must be a succeeded Provider batch")
    _require(isinstance(row.get("attempt_id"), str) and bool(row.get("attempt_id")),
             "M2 L5 requires exactly one Provider attempt")
    for key in ("request_hash", "raw_response_hash"):
        _hash(row.get(key), f"M2 L5 {key}")
    _require(row.get("batch_provider_id") == row.get("binding_provider_id")
             and row.get("provider_enabled") == 1
             and row.get("provider_lifecycle") == "active"
             and row.get("provider_name") == row.get("binding_provider_name") == "联通云"
             and row.get("provider_model") == row.get("binding_model_name")
             == row.get("batch_model_name") == "deepseek-v4-flash",
             "M2 L5 must use active 联通云/deepseek-v4-flash")
    for actual, expected in (
        ("batch_seed_id", "selected_seed_id"),
        ("batch_seed_revision_id", "selected_seed_revision_id"),
        ("batch_seed_hash", "selected_seed_hash"),
        ("batch_binding_revision_id", "binding_revision_id"),
        ("batch_binding_hash", "binding_hash"),
        ("creation_seed_id", "selected_seed_id"),
        ("creation_seed_revision_id", "selected_seed_revision_id"),
        ("creation_seed_hash", "selected_seed_hash"),
        ("creation_binding_revision_id", "binding_revision_id"),
        ("creation_binding_hash", "binding_hash"),
    ):
        _require(row.get(actual) == foundation.get(expected),
                 "M2 L5 seed/binding refs mismatch")
    _require(_integer(row, "option_count") == 3
             and _integer(row, "distinct_option_hash_count") == 3,
             "M2 L5 requires exactly three distinct options")
    options = await session.fetchall(_L5_OPTIONS_SQL, (row.get("batch_id"),))
    _require(len(options) == 3, "M2 L5 requires exactly three options")
    public_options = []
    option_by_id = {}
    for expected_order, option_row in enumerate(options, 1):
        try:
            option = _strict_engine(
                _json_object(option_row.get("payload_json"), "story-engine option")
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            raise ProductVerificationError("M2 story-engine option payload is invalid") from None
        _require(_integer(option_row, "option_order") == expected_order
                 and option_row.get("content_hash") == canonical_hash(option),
                 "M2 story-engine option canonical hash/order mismatch")
        option_by_id[option_row.get("id")] = option_row
        public_options.append({key: option_row.get(key) for key in (
            "id", "option_order", "content_hash"
        )})
    _require(len(option_by_id) == 3, "M2 L5 option ids must be unique")
    selected_option = option_by_id.get(row.get("selected_engine_option_id"))
    _require(selected_option is not None
             and row.get("engine_option_id") == row.get("selected_engine_option_id")
             and row.get("engine_hash") == selected_option.get("content_hash")
             == row.get("engine_option_hash")
             and row.get("engine_option_batch_id") == row.get("batch_id"),
             "M2 selected story-engine option ref mismatch")
    confirmations = await session.fetchall(
        _L5_CONFIRMATIONS_SQL, (foundation.get("project_id"),)
    )
    _require(len(confirmations) == 1, "M2 L5 requires exactly one confirmation")
    confirmation = confirmations[0]
    _require(confirmation.get("status") == "succeeded"
             and confirmation.get("creation_contract_id") == row.get("creation_contract_id")
             and confirmation.get("style_contract_id") == row.get("style_contract_id")
             and _integer(confirmation, "result_revision") == 1,
             "M2 L5 confirmation mismatch")
    payload = await session.fetchone(_L5_CONTRACT_PAYLOAD_SQL, (
        row.get("creation_contract_id"), row.get("style_contract_id"),
    ))
    _require(payload is not None, "M2 L5 contract payload is missing")
    try:
        creation_json = _json_object(payload.get("creation_json"), "CreationContract")
        creation = CreationContractPayload.model_validate({
            **creation_json,
            "selectedEngine": _strict_engine(creation_json["selectedEngine"]),
            "totalWordRange": tuple(creation_json.get("totalWordRange", ())),
        }, strict=True)
    except (KeyError, ValidationError, TypeError, ValueError):
        raise ProductVerificationError("M2 CreationContract payload is invalid") from None
    _require(payload.get("creation_content_hash") == canonical_hash(creation)
             == row.get("creation_hash") == row.get("head_creation_hash")
             == foundation.get("creation_hash"),
             "M2 CreationContract canonical hash mismatch")
    try:
        style_json = _json_object(payload.get("style_json"), "StyleContract")
        style = StyleContractPayload.model_validate({
            **style_json,
            "characterVoices": tuple(style_json.get("characterVoices", ())),
            "primaryRules": tuple(style_json.get("primaryRules", ())),
            "risks": tuple(style_json.get("risks", ())),
        }, strict=True)
        likes = tuple(_json_array(payload.get("likes_json"), "StyleContract likes"))
        dislikes = tuple(_json_array(payload.get("dislikes_json"), "StyleContract dislikes"))
    except (ValidationError, TypeError):
        raise ProductVerificationError("M2 StyleContract payload is invalid") from None
    _require(payload.get("style_content_hash") == style_contract_hash(style, likes, dislikes)
             == row.get("style_hash") == row.get("head_style_hash")
             == foundation.get("style_hash"),
             "M2 StyleContract canonical hash mismatch")
    style_rows = await session.fetchall(_L5_STYLE_REFS_SQL, (row.get("style_contract_id"),))
    card_rows = await session.fetchall(_L5_EXPERIENCE_REFS_SQL, (row.get("creation_contract_id"),))
    corpus_rows = await session.fetchall(_L5_CORPUS_REFS_SQL, (row.get("creation_contract_id"),))
    _require(len(style_rows) == 1 and style_rows[0].get("role") == "primary"
             and style_rows[0].get("asset_hash")
             == style_rows[0].get("actual_asset_hash"),
             "M2 L5 style ref mismatch")
    _require(_integer(style_rows[0], "sort_order") == 1,
             "M2 L5 style ref sort order mismatch")
    _require(len(card_rows) == 1
             and card_rows[0].get("asset_hash")
             == card_rows[0].get("actual_asset_hash"),
             "M2 L5 experience-card ref mismatch")
    _require(_integer(card_rows[0], "sort_order") == 1,
             "M2 L5 experience-card ref sort order mismatch")
    _require(
        len(corpus_rows) == 1
        and corpus_rows[0].get("corpus_source_id") == verified_corpus.get("sourceId")
        and corpus_rows[0].get("source_revision")
        == verified_corpus.get("sourceRevision")
        and corpus_rows[0].get("source_hash")
        == corpus_rows[0].get("actual_source_hash")
        == verified_corpus.get("sourceHash"),
        "M2 L5 corpus ref must match the explicit verified corpus source",
    )
    _require(_integer(corpus_rows[0], "sort_order") == 1,
             "M2 L5 corpus ref sort order mismatch")
    style_refs = tuple({
        "role": ref.get("role"), "id": ref.get("style_template_id"),
        "revision": ref.get("asset_revision"), "contentHash": ref.get("asset_hash"),
        "actualContentHash": ref.get("actual_asset_hash"),
    } for ref in style_rows)
    card_refs = tuple({
        "id": ref.get("experience_card_id"), "revision": ref.get("asset_revision"),
        "contentHash": ref.get("asset_hash"),
        "actualContentHash": ref.get("actual_asset_hash"),
    } for ref in card_rows)
    corpus_refs = tuple({
        "id": ref.get("corpus_source_id"), "revision": ref.get("source_revision"),
        "contentHash": ref.get("source_hash"), "selectionMode": ref.get("selection_mode"),
        "actualContentHash": ref.get("actual_source_hash"),
    } for ref in corpus_rows)
    snapshot = {
        "project_id": foundation.get("project_id"), "revision": 1,
        "seed_id": foundation.get("selected_seed_id"),
        "seed_revision_id": foundation.get("selected_seed_revision_id"),
        "seed_hash": foundation.get("selected_seed_hash"),
        "actual_seed_hash": foundation.get("selected_revision_hash"),
        "creation_json": payload.get("creation_json"),
        "creation_hash": payload.get("creation_content_hash"),
        "style_json": payload.get("style_json"), "likes_json": payload.get("likes_json"),
        "dislikes_json": payload.get("dislikes_json"),
        "style_hash": payload.get("style_content_hash"),
        "reference_manifest_json": payload.get("reference_manifest_json"),
        "reference_manifest_hash": payload.get("reference_manifest_hash"),
        "engine_option_id": row.get("engine_option_id"),
        "engine_batch_id": row.get("batch_id"), "engine_hash": row.get("engine_hash"),
        "actual_engine_hash": row.get("engine_option_hash"),
        "binding_revision_id": foundation.get("binding_revision_id"),
        "binding_revision": foundation.get("binding_revision"),
        "binding_hash": foundation.get("binding_hash"),
        "actual_binding_hash": foundation.get("binding_hash"),
        "binding_items": binding_items,
        "creation_contract_id": row.get("creation_contract_id"),
        "style_contract_id": row.get("style_contract_id"),
        "style_refs": style_refs, "experience_card_refs": card_refs,
        "corpus_source_refs": corpus_refs,
    }
    try:
        service = ContractService(None, transaction_factory=None, connection_factory=None)
        result = service._result_from_snapshot(snapshot)
        expected_manifest = service._reference_manifest(result)
    except Exception:
        raise ProductVerificationError("M2 L5 confirmed snapshot/manifest mismatch") from None
    stored_manifest = _json_object(payload.get("reference_manifest_json"),
                                   "reference manifest")
    _require(payload.get("reference_manifest_hash") == canonical_hash(stored_manifest)
             and canonical_json(stored_manifest) == canonical_json(expected_manifest),
             "M2 L5 reference manifest mismatch")
    return {
        "batchId": row.get("batch_id"), "requestHash": row.get("request_hash"),
        "attemptId": row.get("attempt_id"), "rawResponseHash": row.get("raw_response_hash"),
        "attemptCount": 1, "optionCount": 3, "options": public_options,
        "selectedEngineOptionId": row.get("selected_engine_option_id"),
        "contractRevision": 1, "creationContractId": row.get("creation_contract_id"),
        "styleContractId": row.get("style_contract_id"),
        "creationHash": row.get("creation_hash"), "styleHash": row.get("style_hash"),
        "referenceManifestHash": payload.get("reference_manifest_hash"),
    }


async def verify_milestone2_product(
    session,
    *,
    expected_database: str,
    mode: str | None = None,
    expected_source_hash: str | None = None,
    require_assets: bool = False,
    require_corpus: bool = False,
    require_l5: bool = False,
) -> dict[str, object]:
    """Verify one bounded state using SELECT statements only."""

    if mode is not None:
        _require(mode in _MODES, "M2 verification mode is invalid")
        require_assets = mode in {"corpus-import", "provider-l5"}
        require_corpus = mode in {"corpus-import", "provider-l5"}
        require_l5 = mode == "provider-l5"
    _require(
        isinstance(expected_database, str)
        and _DATABASE_NAME.fullmatch(expected_database) is not None,
        "Explicit expected database identity is invalid",
    )
    if require_corpus or require_l5:
        _require(
            isinstance(expected_source_hash, str)
            and _HASH.fullmatch(expected_source_hash) is not None,
            "An explicit lowercase corpus source hash is required",
        )
    metadata, foundation, binding_items = await _verify_foundation(
        session, expected_database=expected_database, require_l5=require_l5
    )
    await _verify_counts(session, require_l5=require_l5)
    receipt: dict[str, object] = {
        "schemaVersion": metadata["schema_version"],
        "manifestHash": metadata["manifest_hash"],
        "project": {
            "id": foundation.get("project_id"), "title": foundation.get("project_title"),
            "seedCount": 3, "selectedSeedId": foundation.get("selected_seed_id"),
            "selectedSeedTitle": foundation.get("selected_seed_title"),
            "providerCount": foundation.get("provider_count"), "bindingRevision": 1,
            "contractRevision": foundation.get("contract_revision"), "canonRevision": 0,
            "projectionRevision": 0,
        },
    }
    if require_assets or require_l5:
        receipt["assets"] = await _verify_assets(session)
    verified_corpus = None
    if require_corpus or require_l5:
        verified_corpus = await _verify_corpus(session, expected_source_hash)
        receipt["corpus"] = verified_corpus
    if require_l5:
        _require(verified_corpus is not None, "M2 L5 verified corpus is missing")
        receipt["l5"] = await _verify_l5(
            session,
            foundation,
            binding_items,
            verified_corpus=verified_corpus,
        )
    return receipt


def format_product_receipt(receipt: Mapping[str, object]) -> str:
    return json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class _ConnectionSession:
    def __init__(self, raw):
        from backend.database import DatabaseSession
        self.raw = raw
        self.session = DatabaseSession(raw)

    async def fetchone(self, sql, args=None):
        return await self.session.fetchone(sql, args)

    async def fetchall(self, sql, args=None):
        return await self.session.fetchall(sql, args)

    async def close(self):
        ensure_closed = getattr(self.raw, "ensure_closed", None)
        if ensure_closed is not None:
            await ensure_closed()
        else:
            self.raw.close()


async def _default_connection(config: Mapping[str, object]):
    import aiomysql
    return _ConnectionSession(await aiomysql.connect(**config))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--require-assets", action="store_true")
    parser.add_argument("--require-corpus", action="store_true")
    parser.add_argument("--require-l5", action="store_true")
    parser.add_argument("--source-hash")
    return parser


async def run_cli(
    argv: Sequence[str] | None = None, *,
    connection_config: Mapping[str, object] | None = None,
    connection_factory: Callable[[Mapping[str, object]], Awaitable[object]] | None = None,
    output: Callable[[str], None] = print,
) -> int:
    args = _parser().parse_args(argv)
    if _DATABASE_NAME.fullmatch(args.database) is None:
        raise ProductVerificationError("Database name contains unsupported characters")
    if args.require_corpus or args.require_l5:
        _require(
            isinstance(args.source_hash, str)
            and _HASH.fullmatch(args.source_hash) is not None,
            "An explicit lowercase corpus source hash is required",
        )
    if connection_config is None:
        from backend.config import require_mysql_config
        connection_config = require_mysql_config()
    config = {**connection_config, "db": args.database, "autocommit": True}
    session = await (connection_factory or _default_connection)(config)
    try:
        receipt = await verify_milestone2_product(
            session, expected_database=args.database,
            expected_source_hash=args.source_hash,
            require_assets=args.require_assets, require_corpus=args.require_corpus,
            require_l5=args.require_l5,
        )
    finally:
        await session.close()
    output(format_product_receipt(receipt))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(run_cli(argv))
    except SystemExit:
        raise
    except BaseException:
        print("M2 product verification failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
