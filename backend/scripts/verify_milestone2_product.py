"""SELECT-only bounded verifier for the Milestone 2 product state."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import PurePosixPath, PureWindowsPath
import re
import sys
from typing import Awaitable, Callable, Mapping, Sequence

from backend.domain.assets import load_asset_package
from backend.domain.json_contracts import canonical_hash
from backend.domain.model_bindings import TASK_KEYS
from backend.schema_manifest import manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from backend.scripts.seed_writer_assets import MANIFEST_PATH
from backend.services.projections import build_projection_bundle


_DATABASE_NAME = re.compile(r"[A-Za-z0-9_]+\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


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


def _relative_path(value: object) -> str:
    _require(isinstance(value, str) and bool(value), "Corpus relative path is missing")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    _require(
        not posix.is_absolute()
        and not windows.is_absolute()
        and not windows.drive
        and ".." not in posix.parts
        and ".." not in windows.parts,
        "Corpus source must use a safe relative path",
    )
    return str(value)


_METADATA_SQL = """/* m2:metadata */
SELECT schema_version,manifest_hash FROM schema_metadata WHERE singleton_id=1"""

_FOUNDATION_SQL = """/* m2:foundation */
SELECT p.id AS project_id,p.title AS project_title,
       (SELECT COUNT(*) FROM projects) AS project_count,
       (SELECT COUNT(*) FROM creative_seeds WHERE project_id=p.id) AS seed_count,
       ss.seed_id AS selected_seed_id,ss.seed_revision_id AS selected_seed_revision_id,
       JSON_UNQUOTE(JSON_EXTRACT(sr.payload_json,'$.title')) AS selected_seed_title,
       ss.seed_hash AS selected_seed_hash,sr.content_hash AS selected_revision_hash,
       ss.selection_revision,
       (SELECT COUNT(*) FROM provider_profiles) AS provider_count,
       bh.binding_revision_id,bh.revision AS binding_revision,
       br.content_hash AS binding_hash,bh.content_hash AS binding_head_hash,
       (SELECT COUNT(*) FROM project_model_binding_items bi
          WHERE bi.binding_revision_id=bh.binding_revision_id) AS binding_item_count,
       (SELECT COUNT(*) FROM project_model_binding_items bi
          WHERE bi.binding_revision_id=bh.binding_revision_id
            AND bi.resolution_status='bound') AS bound_item_count,
       ch.revision AS contract_revision,ch.creation_contract_id,ch.style_contract_id,
       ch.creation_hash,ch.style_hash,
       cr.revision_number AS canon_revision,cr.content_hash AS canon_hash,
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
 (SELECT COUNT(*) FROM final_chapters) AS final_chapters"""

_ASSET_COUNTS_SQL = """/* m2:asset_counts */
SELECT
 (SELECT COUNT(*) FROM style_template_heads) AS style_head_count,
 (SELECT COUNT(*) FROM style_template_heads h JOIN style_templates t
    ON t.id=h.style_template_id AND t.revision=h.revision AND t.content_hash=h.content_hash
    WHERE t.status='active') AS active_style_head_count,
 (SELECT COUNT(*) FROM experience_card_heads) AS card_head_count,
 (SELECT COUNT(*) FROM experience_card_heads h JOIN experience_cards c
    ON c.id=h.experience_card_id AND c.revision=h.revision AND c.content_hash=h.content_hash
    WHERE c.status='active') AS active_card_head_count"""

_STYLE_HEADS_SQL = """/* m2:style_heads */
SELECT h.stable_key,h.revision,h.content_hash FROM style_template_heads h
JOIN style_templates t ON t.id=h.style_template_id AND t.status='active'
ORDER BY h.stable_key"""

_CARD_HEADS_SQL = """/* m2:card_heads */
SELECT h.stable_key,h.revision,h.content_hash FROM experience_card_heads h
JOIN experience_cards c ON c.id=h.experience_card_id AND c.status='active'
ORDER BY h.stable_key"""

_CORPUS_SQL = """/* m2:corpus */
SELECT s.id AS source_id,s.relative_path,s.source_hash,s.status,
       s.parser_version,s.normalizer_version,s.fragmenter_version,s.index_version,
       (SELECT COUNT(*) FROM corpus_chapters c WHERE c.corpus_source_id=s.id) AS chapter_count,
       (SELECT COUNT(*) FROM corpus_fragments f JOIN corpus_chapters c
          ON c.id=f.corpus_chapter_id WHERE c.corpus_source_id=s.id) AS fragment_count,
       (SELECT COUNT(*) FROM corpus_import_runs r
          WHERE r.corpus_source_id=s.id AND r.status='succeeded') AS succeeded_run_count
FROM corpus_sources s
WHERE s.status='analyzed'
  AND EXISTS (SELECT 1 FROM corpus_import_runs r
               WHERE r.corpus_source_id=s.id AND r.status='succeeded')
ORDER BY s.imported_at DESC,s.id DESC LIMIT 1"""

_L5_SQL = """/* m2:l5 */
SELECT b.id AS batch_id,
       (SELECT COUNT(*) FROM story_engine_batches x
         WHERE x.project_id=ss.project_id AND x.source_type='provider'
           AND x.status='succeeded' AND x.seed_id=ss.seed_id
           AND x.seed_revision_id=ss.seed_revision_id AND x.seed_hash=ss.seed_hash
           AND x.binding_revision_id=bh.binding_revision_id
           AND x.binding_hash=bh.content_hash) AS batch_count,
       b.source_type,b.status AS batch_status,b.seed_id AS batch_seed_id,
       b.seed_revision_id AS batch_seed_revision_id,b.seed_hash AS batch_seed_hash,
       b.binding_revision_id AS batch_binding_revision_id,b.binding_hash AS batch_binding_hash,
       CASE WHEN b.attempt_id IS NULL THEN 0 ELSE 1 END AS attempt_count,
       (SELECT COUNT(*) FROM story_engine_options o WHERE o.batch_id=b.id) AS option_count,
       (SELECT COUNT(DISTINCT o.content_hash) FROM story_engine_options o
          WHERE o.batch_id=b.id) AS distinct_option_hash_count,
       h.revision AS contract_head_revision,h.creation_contract_id,h.style_contract_id,
       c.content_hash AS creation_hash,h.creation_hash AS head_creation_hash,
       st.content_hash AS style_hash,h.style_hash AS head_style_hash,
       c.revision AS creation_revision,st.revision AS style_revision,
       c.seed_id AS creation_seed_id,c.seed_revision_id AS creation_seed_revision_id,
       c.seed_hash AS creation_seed_hash,
       c.binding_revision_id AS creation_binding_revision_id,
       c.binding_hash AS creation_binding_hash,
       er.engine_option_id,er.engine_hash,o.content_hash AS engine_option_hash,
       o.batch_id AS engine_option_batch_id,
       er.engine_option_id AS selected_engine_option_id,
       cf.status AS confirmation_status,cf.result_revision AS confirmation_result_revision
FROM project_selected_seeds ss
JOIN project_model_binding_heads bh ON bh.project_id=ss.project_id
JOIN project_contract_heads h ON h.project_id=ss.project_id
JOIN creation_contracts c ON c.id=h.creation_contract_id
JOIN style_contracts st ON st.id=h.style_contract_id
 AND st.creation_contract_id=c.id AND st.revision=c.revision
JOIN creation_contract_engine_refs er ON er.creation_contract_id=c.id
JOIN story_engine_options o ON o.id=er.engine_option_id
JOIN story_engine_batches b ON b.id=o.batch_id
JOIN contract_confirmation_requests cf ON cf.project_id=ss.project_id
 AND cf.creation_contract_id=c.id AND cf.style_contract_id=st.id
 AND cf.result_revision=h.revision
LIMIT 2"""


async def _verify_foundation(session, *, require_l5: bool) -> tuple[dict[str, object], dict[str, object]]:
    metadata = await session.fetchone(_METADATA_SQL)
    _require(metadata is not None, "M2 schema metadata is missing")
    _require(metadata.get("schema_version") == EXPECTED_SCHEMA_VERSION, "M2 schema version mismatch")
    _require(metadata.get("manifest_hash") == manifest_hash(), "M2 manifest hash mismatch")
    row = await session.fetchone(_FOUNDATION_SQL)
    _require(row is not None, "M2 foundation is missing")
    _require(_integer(row, "project_count") == 1, "M2 requires exactly one project")
    _require(_integer(row, "seed_count") == 3, "M2 requires exactly three seeds")
    _require(row.get("selected_seed_title") == "典镇山河", "M2 selected seed must be 典镇山河")
    _require(row.get("selected_seed_hash") == row.get("selected_revision_hash"), "Selected seed hash mismatch")
    _require(_integer(row, "selection_revision") == 1, "Selected seed revision must be 1")
    _require(_integer(row, "provider_count") >= 1, "M2 requires at least one preserved Provider")
    _require(_integer(row, "binding_revision") == 1, "Binding head must be revision 1")
    _require(row.get("binding_hash") == row.get("binding_head_hash"), "Binding head hash mismatch")
    _require(_integer(row, "binding_item_count") == len(TASK_KEYS), "Binding must contain eight tasks")
    _require(_integer(row, "bound_item_count") == len(TASK_KEYS), "All M2 tasks must be bound")
    expected_contract_revision = 1 if require_l5 else 0
    _require(
        _integer(row, "contract_revision") == expected_contract_revision,
        f"M2 requires contract head revision {expected_contract_revision}",
    )
    if not require_l5:
        for key in ("creation_contract_id", "style_contract_id", "creation_hash", "style_hash"):
            _require(row.get(key) is None, "Head zero must not reference contracts")
    empty_hash = build_projection_bundle(0, ()).content_hash
    _require(_integer(row, "canon_revision") == 0, "Canon must remain revision 0")
    _require(row.get("canon_hash") == empty_hash, "Canon zero hash mismatch")
    _require(_integer(row, "projection_canon_revision") == 0, "Projection Canon head must be 0")
    _require(_integer(row, "projection_revision") == 0, "Projection must remain revision 0")
    _require(row.get("projection_hash") == empty_hash, "Projection zero hash mismatch")
    return dict(metadata), dict(row)


async def _verify_assets(session) -> dict[str, object]:
    package = load_asset_package(MANIFEST_PATH, mode="release")
    counts = await session.fetchone(_ASSET_COUNTS_SQL)
    _require(counts is not None, "M2 asset counts are missing")
    expected_counts = {
        "style_head_count": 10,
        "active_style_head_count": 10,
        "card_head_count": 64,
        "active_card_head_count": 64,
    }
    _require(
        all(_integer(counts, key) == value for key, value in expected_counts.items()),
        "M2 assets require exactly 10 active style heads and 64 active card heads",
    )
    styles = await session.fetchall(_STYLE_HEADS_SQL)
    cards = await session.fetchall(_CARD_HEADS_SQL)
    expected_styles = sorted(
        (value.stable_key, value.revision, value.content_hash) for value in package.styles
    )
    expected_cards = sorted(
        (value.stable_key, value.revision, value.content_hash)
        for value in package.experience_cards
    )
    actual_styles = sorted(
        (row.get("stable_key"), row.get("revision"), row.get("content_hash"))
        for row in styles
    )
    actual_cards = sorted(
        (row.get("stable_key"), row.get("revision"), row.get("content_hash"))
        for row in cards
    )
    _require(actual_styles == expected_styles, "M2 style head package hashes mismatch")
    _require(actual_cards == expected_cards, "M2 experience-card head package hashes mismatch")
    return {
        "packageVersion": package.package_version,
        "packageHash": canonical_hash(package.manifest),
        "styleCount": 10,
        "cardCount": 64,
    }


async def _verify_corpus(session) -> dict[str, object]:
    row = await session.fetchone(_CORPUS_SQL)
    _require(row is not None, "M2 requires a succeeded analyzed corpus import")
    relative_path = _relative_path(row.get("relative_path"))
    source_hash = row.get("source_hash")
    _require(isinstance(source_hash, str) and _HASH.fullmatch(source_hash) is not None, "Corpus source hash is invalid")
    _require(row.get("status") == "analyzed", "Corpus source must be analyzed")
    _require(_integer(row, "succeeded_run_count") >= 1, "Corpus import run must have succeeded")
    chapter_count = _integer(row, "chapter_count")
    fragment_count = _integer(row, "fragment_count")
    _require(chapter_count > 0 and fragment_count > 0, "Corpus chapter and fragment counts must be positive")
    versions = {}
    for public, field in (
        ("parser", "parser_version"),
        ("normalizer", "normalizer_version"),
        ("fragmenter", "fragmenter_version"),
        ("index", "index_version"),
    ):
        value = row.get(field)
        _require(isinstance(value, str) and bool(value), "Corpus analysis versions are incomplete")
        versions[public] = value
    return {
        "sourceId": row.get("source_id"),
        "relativePath": relative_path,
        "sourceHash": source_hash,
        "chapterCount": chapter_count,
        "fragmentCount": fragment_count,
        "versions": versions,
    }


async def _verify_l5(session, foundation: Mapping[str, object]) -> dict[str, object]:
    row = await session.fetchone(_L5_SQL)
    _require(row is not None, "M2 L5 evidence is missing")
    _require(_integer(row, "batch_count") == 1, "M2 L5 requires exactly one succeeded Provider batch")
    _require(row.get("source_type") == "provider" and row.get("batch_status") == "succeeded", "M2 L5 batch must be a succeeded Provider batch")
    _require(_integer(row, "attempt_count") == 1, "M2 L5 requires exactly one Provider attempt")
    _require(_integer(row, "option_count") == 3, "M2 L5 requires exactly three options")
    _require(_integer(row, "distinct_option_hash_count") == 3, "M2 L5 options must have distinct hashes")
    _require(_integer(row, "contract_head_revision") == 1, "M2 L5 contract head revision 1 is required")
    _require(_integer(row, "creation_revision") == 1 and _integer(row, "style_revision") == 1, "M2 L5 contracts must both be revision 1")
    equality_pairs = (
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
    )
    for actual, expected in equality_pairs:
        _require(row.get(actual) == foundation.get(expected), "M2 L5 seed/binding refs mismatch")
    _require(row.get("creation_contract_id") == foundation.get("creation_contract_id"), "CreationContract head ref mismatch")
    _require(row.get("style_contract_id") == foundation.get("style_contract_id"), "StyleContract head ref mismatch")
    _require(row.get("creation_hash") == row.get("head_creation_hash") == foundation.get("creation_hash"), "CreationContract hash mismatch")
    _require(row.get("style_hash") == row.get("head_style_hash") == foundation.get("style_hash"), "StyleContract hash mismatch")
    _require(row.get("engine_option_id") == row.get("selected_engine_option_id"), "Selected story engine ref mismatch")
    _require(row.get("engine_hash") == row.get("engine_option_hash"), "Selected story engine hash mismatch")
    _require(row.get("engine_option_batch_id") == row.get("batch_id"), "Story engine option batch mismatch")
    _require(row.get("confirmation_status") == "succeeded" and _integer(row, "confirmation_result_revision") == 1, "Contract confirmation mismatch")
    return {
        "batchId": row.get("batch_id"),
        "attemptCount": 1,
        "optionCount": 3,
        "selectedEngineOptionId": row.get("selected_engine_option_id"),
        "contractRevision": 1,
        "creationContractId": row.get("creation_contract_id"),
        "styleContractId": row.get("style_contract_id"),
    }


async def verify_milestone2_product(
    session,
    *,
    require_assets: bool = False,
    require_corpus: bool = False,
    require_l5: bool = False,
) -> dict[str, object]:
    """Verify one bounded state using SELECT statements only."""

    metadata, foundation = await _verify_foundation(session, require_l5=require_l5)
    if not require_l5:
        later = await session.fetchone(_LATER_COUNTS_SQL)
        _require(later is not None, "M2 later-domain counts are missing")
        _require(all(_integer(later, key) == 0 for key in later), "Fresh M2 state contains derived rows")
    receipt: dict[str, object] = {
        "schemaVersion": metadata["schema_version"],
        "manifestHash": metadata["manifest_hash"],
        "project": {
            "id": foundation.get("project_id"),
            "title": foundation.get("project_title"),
            "seedCount": 3,
            "selectedSeedId": foundation.get("selected_seed_id"),
            "selectedSeedTitle": foundation.get("selected_seed_title"),
            "providerCount": foundation.get("provider_count"),
            "bindingRevision": 1,
            "contractRevision": foundation.get("contract_revision"),
            "canonRevision": 0,
            "projectionRevision": 0,
        },
    }
    if require_assets or require_l5:
        receipt["assets"] = await _verify_assets(session)
    if require_corpus or require_l5:
        receipt["corpus"] = await _verify_corpus(session)
    if require_l5:
        receipt["l5"] = await _verify_l5(session, foundation)
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
    return parser


async def run_cli(
    argv: Sequence[str] | None = None,
    *,
    connection_config: Mapping[str, object] | None = None,
    connection_factory: Callable[[Mapping[str, object]], Awaitable[object]] | None = None,
    output: Callable[[str], None] = print,
) -> int:
    args = _parser().parse_args(argv)
    if _DATABASE_NAME.fullmatch(args.database) is None:
        raise ProductVerificationError("Database name contains unsupported characters")
    if connection_config is None:
        from backend.config import require_mysql_config

        connection_config = require_mysql_config()
    config = {**connection_config, "db": args.database, "autocommit": True}
    session = await (connection_factory or _default_connection)(config)
    try:
        receipt = await verify_milestone2_product(
            session,
            require_assets=args.require_assets,
            require_corpus=args.require_corpus,
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
