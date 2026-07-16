import json

import pytest

from backend.domain.assets import load_asset_package
from backend.domain.json_contracts import canonical_hash
from backend.domain.model_bindings import TASK_KEYS
from backend.schema_manifest import manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from backend.scripts.seed_writer_assets import MANIFEST_PATH
from backend.services.projections import build_projection_bundle


PROJECT_ID = "00000000-0000-0000-0000-000000000001"
SEED_ID = "00000000-0000-0000-0000-000000000003"
SEED_REVISION_ID = "00000000-0000-0000-0000-000000000013"
BINDING_REVISION_ID = "00000000-0000-0000-0000-000000000021"
BATCH_ID = "00000000-0000-0000-0000-000000000031"
OPTION_ID = "00000000-0000-0000-0000-000000000032"
CREATION_ID = "00000000-0000-0000-0000-000000000041"
STYLE_ID = "00000000-0000-0000-0000-000000000042"


class ReceiptSession:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def _key(self, sql):
        return sql.split("/* m2:", 1)[1].split(" */", 1)[0]

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", sql, args))
        value = self.rows[self._key(sql)]
        assert not isinstance(value, list)
        return value

    async def fetchall(self, sql, args=None):
        self.calls.append(("fetchall", sql, args))
        value = self.rows[self._key(sql)]
        assert isinstance(value, list)
        return value


def base_rows():
    empty_hash = build_projection_bundle(0, ()).content_hash
    return {
        "metadata": {
            "schema_version": EXPECTED_SCHEMA_VERSION,
            "manifest_hash": manifest_hash(),
        },
        "foundation": {
            "project_id": PROJECT_ID,
            "project_title": "永乐大典",
            "project_count": 1,
            "seed_count": 3,
            "selected_seed_id": SEED_ID,
            "selected_seed_revision_id": SEED_REVISION_ID,
            "selected_seed_title": "典镇山河",
            "selected_seed_hash": "a" * 64,
            "selected_revision_hash": "a" * 64,
            "selection_revision": 1,
            "provider_count": 2,
            "binding_revision_id": BINDING_REVISION_ID,
            "binding_revision": 1,
            "binding_hash": "b" * 64,
            "binding_head_hash": "b" * 64,
            "binding_item_count": len(TASK_KEYS),
            "bound_item_count": len(TASK_KEYS),
            "contract_revision": 0,
            "creation_contract_id": None,
            "style_contract_id": None,
            "creation_hash": None,
            "style_hash": None,
            "canon_revision": 0,
            "canon_hash": empty_hash,
            "projection_canon_revision": 0,
            "projection_revision": 0,
            "projection_hash": empty_hash,
        },
        "later_counts": {
            "story_engine_batches": 0,
            "story_engine_options": 0,
            "project_contract_drafts": 0,
            "creation_contracts": 0,
            "style_contracts": 0,
            "contract_confirmation_requests": 0,
            "volume_plans": 0,
            "story_blocks": 0,
            "story_stages": 0,
            "scene_tasks": 0,
            "chapter_sessions": 0,
            "working_drafts": 0,
            "draft_candidates": 0,
            "finalization_change_sets": 0,
            "finalization_records": 0,
            "final_chapters": 0,
        },
    }


def asset_rows():
    package = load_asset_package(MANIFEST_PATH, mode="release")
    return {
        "asset_counts": {
            "style_head_count": 10,
            "active_style_head_count": 10,
            "card_head_count": 64,
            "active_card_head_count": 64,
        },
        "style_heads": [
            {
                "stable_key": value.stable_key,
                "revision": value.revision,
                "content_hash": value.content_hash,
            }
            for value in package.styles
        ],
        "card_heads": [
            {
                "stable_key": value.stable_key,
                "revision": value.revision,
                "content_hash": value.content_hash,
            }
            for value in package.experience_cards
        ],
    }


def corpus_rows():
    return {
        "corpus": {
            "source_id": "00000000-0000-0000-0000-000000000051",
            "relative_path": "approved/reference.txt",
            "source_hash": "c" * 64,
            "status": "analyzed",
            "parser_version": "parser-v1",
            "normalizer_version": "normalizer-v1",
            "fragmenter_version": "fragmenter-v1",
            "index_version": "index-v1",
            "chapter_count": 5,
            "fragment_count": 12,
            "succeeded_run_count": 1,
        },
    }


def l5_rows():
    return {
        "l5": {
            "batch_id": BATCH_ID,
            "batch_count": 1,
            "source_type": "provider",
            "batch_status": "succeeded",
            "batch_seed_id": SEED_ID,
            "batch_seed_revision_id": SEED_REVISION_ID,
            "batch_seed_hash": "a" * 64,
            "batch_binding_revision_id": BINDING_REVISION_ID,
            "batch_binding_hash": "b" * 64,
            "attempt_count": 1,
            "option_count": 3,
            "distinct_option_hash_count": 3,
            "contract_head_revision": 1,
            "creation_contract_id": CREATION_ID,
            "style_contract_id": STYLE_ID,
            "creation_hash": "d" * 64,
            "head_creation_hash": "d" * 64,
            "style_hash": "e" * 64,
            "head_style_hash": "e" * 64,
            "creation_revision": 1,
            "style_revision": 1,
            "creation_seed_id": SEED_ID,
            "creation_seed_revision_id": SEED_REVISION_ID,
            "creation_seed_hash": "a" * 64,
            "creation_binding_revision_id": BINDING_REVISION_ID,
            "creation_binding_hash": "b" * 64,
            "engine_option_id": OPTION_ID,
            "engine_hash": "f" * 64,
            "engine_option_hash": "f" * 64,
            "engine_option_batch_id": BATCH_ID,
            "selected_engine_option_id": OPTION_ID,
            "confirmation_status": "succeeded",
            "confirmation_result_revision": 1,
        },
    }


@pytest.mark.asyncio
async def test_base_receipt_is_select_only_bounded_and_requires_fresh_head_zero():
    from backend.scripts.verify_milestone2_product import (
        format_product_receipt,
        verify_milestone2_product,
    )

    session = ReceiptSession(base_rows())
    receipt = await verify_milestone2_product(session)

    assert receipt["schemaVersion"] == EXPECTED_SCHEMA_VERSION
    assert receipt["project"] == {
        "id": PROJECT_ID,
        "title": "永乐大典",
        "seedCount": 3,
        "selectedSeedId": SEED_ID,
        "selectedSeedTitle": "典镇山河",
        "providerCount": 2,
        "bindingRevision": 1,
        "contractRevision": 0,
        "canonRevision": 0,
        "projectionRevision": 0,
    }
    assert all(call[1].lstrip().upper().startswith("/* M2:") for call in session.calls)
    assert all("SELECT" in call[1].upper() for call in session.calls)
    rendered = format_product_receipt(receipt)
    assert json.loads(rendered) == receipt
    for forbidden in ("api_key", "base_url", "notes", "thinking", "dsn", "正文"):
        assert forbidden not in rendered.lower()


@pytest.mark.asyncio
async def test_assets_require_exact_approved_ten_and_sixty_four_head_hashes():
    from backend.scripts.verify_milestone2_product import verify_milestone2_product

    rows = {**base_rows(), **asset_rows()}
    receipt = await verify_milestone2_product(
        ReceiptSession(rows), require_assets=True
    )
    assert receipt["assets"] == {
        "packageVersion": "writer-core-v1.1.0",
        "packageHash": canonical_hash(
            load_asset_package(MANIFEST_PATH, mode="release").manifest
        ),
        "styleCount": 10,
        "cardCount": 64,
    }

    rows["style_heads"][0]["content_hash"] = "0" * 64
    with pytest.raises(RuntimeError, match="style head package"):
        await verify_milestone2_product(ReceiptSession(rows), require_assets=True)


@pytest.mark.asyncio
async def test_corpus_requires_succeeded_relative_metadata_and_positive_counts():
    from backend.scripts.verify_milestone2_product import verify_milestone2_product

    rows = {**base_rows(), **corpus_rows()}
    receipt = await verify_milestone2_product(
        ReceiptSession(rows), require_corpus=True
    )
    assert receipt["corpus"] == {
        "sourceId": rows["corpus"]["source_id"],
        "relativePath": "approved/reference.txt",
        "sourceHash": "c" * 64,
        "chapterCount": 5,
        "fragmentCount": 12,
        "versions": {
            "parser": "parser-v1",
            "normalizer": "normalizer-v1",
            "fragmenter": "fragmenter-v1",
            "index": "index-v1",
        },
    }

    rows["corpus"]["relative_path"] = "C:/private/novels/reference.txt"
    with pytest.raises(RuntimeError, match="relative path"):
        await verify_milestone2_product(ReceiptSession(rows), require_corpus=True)


@pytest.mark.asyncio
async def test_l5_requires_one_provider_attempt_three_options_and_consistent_contract_refs():
    from backend.scripts.verify_milestone2_product import verify_milestone2_product

    base = base_rows()
    base["foundation"]["contract_revision"] = 1
    base["foundation"]["creation_contract_id"] = CREATION_ID
    base["foundation"]["style_contract_id"] = STYLE_ID
    base["foundation"]["creation_hash"] = "d" * 64
    base["foundation"]["style_hash"] = "e" * 64
    rows = {**base, **asset_rows(), **corpus_rows(), **l5_rows()}
    receipt = await verify_milestone2_product(ReceiptSession(rows), require_l5=True)
    assert receipt["l5"] == {
        "batchId": BATCH_ID,
        "attemptCount": 1,
        "optionCount": 3,
        "selectedEngineOptionId": OPTION_ID,
        "contractRevision": 1,
        "creationContractId": CREATION_ID,
        "styleContractId": STYLE_ID,
    }

    rows["l5"]["option_count"] = 2
    with pytest.raises(RuntimeError, match="exactly three"):
        await verify_milestone2_product(ReceiptSession(rows), require_l5=True)


@pytest.mark.asyncio
async def test_require_l5_implies_assets_and_corpus_and_rejects_head_zero():
    from backend.scripts.verify_milestone2_product import verify_milestone2_product

    rows = {**base_rows(), **asset_rows(), **corpus_rows(), **l5_rows()}
    with pytest.raises(RuntimeError, match="contract head revision 1"):
        await verify_milestone2_product(ReceiptSession(rows), require_l5=True)
