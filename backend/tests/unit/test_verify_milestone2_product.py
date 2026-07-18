import json
import sys
from types import SimpleNamespace

import pytest

from backend.domain.assets import load_asset_package
from backend.domain.contracts import CreationContractPayload, StyleContractPayload
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.model_bindings import BindingItem, BindingRevision, TASK_KEYS
from backend.domain.seeds import SeedPayload
from backend.domain.story_engines import StoryEngineOption
from backend.schema_manifest import created_table_names, manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from backend.scripts.seed_writer_assets import MANIFEST_PATH
from backend.services.projections import build_projection_bundle
from backend.services.contracts import style_contract_hash
from backend.services.project_lifecycle import ProjectLifecycleService


PROJECT_ID = "00000000-0000-0000-0000-000000000001"
SEED_ID = "00000000-0000-0000-0000-000000000003"
SEED_REVISION_ID = "00000000-0000-0000-0000-000000000013"
BINDING_REVISION_ID = "00000000-0000-0000-0000-000000000021"
BATCH_ID = "00000000-0000-0000-0000-000000000031"
OPTION_ID = "00000000-0000-0000-0000-000000000032"
CREATION_ID = "00000000-0000-0000-0000-000000000041"
STYLE_ID = "00000000-0000-0000-0000-000000000042"
PROVIDER_ID = "00000000-0000-0000-0000-000000000022"
ATTEMPT_ID = "00000000-0000-0000-0000-000000000033"
STYLE_ASSET_ID = "00000000-0000-0000-0000-000000000061"
CARD_ASSET_ID = "00000000-0000-0000-0000-000000000062"
CORPUS_SOURCE_ID = "00000000-0000-0000-0000-000000000051"
DATABASE = "m2_test_database"


class NonExactString(str):
    pass


@pytest.mark.asyncio
async def test_default_connection_passes_only_single_connection_kwargs_and_closes(
    monkeypatch, capsys,
):
    from backend.scripts.verify_milestone2_product import _default_connection

    captured = {}

    class FakeConnection:
        def __init__(self):
            self.closed = False

        async def ensure_closed(self):
            self.closed = True

    raw = FakeConnection()

    async def connect(**kwargs):
        captured.update(kwargs)
        return raw

    monkeypatch.setitem(sys.modules, "aiomysql", SimpleNamespace(connect=connect))
    session = await _default_connection({
        "host": "db.internal",
        "port": 3307,
        "user": "writer",
        "password": "secret",
        "db": DATABASE,
        "charset": "utf8mb4",
        "autocommit": True,
        "minsize": 1,
        "maxsize": 10,
        "unknown_option": "must-not-leak",
    })
    await session.close()

    assert captured == {
        "host": "db.internal",
        "port": 3307,
        "user": "writer",
        "password": "secret",
        "db": DATABASE,
        "charset": "utf8mb4",
        "autocommit": True,
    }
    assert raw.closed is True
    assert capsys.readouterr() == ("", "")


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
        if self._key(sql) == "corpus" and isinstance(value, dict):
            return [value]
        assert isinstance(value, list)
        return value


class MultiCorpusReceiptSession(ReceiptSession):
    """Expose every same-hash source while keeping the old fetch-one bug observable."""

    async def fetchone(self, sql, args=None):
        key = self._key(sql)
        if key == "corpus":
            self.calls.append(("fetchone", sql, args))
            return self.rows[key][0]
        return await super().fetchone(sql, args)


def base_rows():
    empty_hash = build_projection_bundle(0, ()).content_hash
    seed_payloads = tuple(SeedPayload(
        title=title,
        genre="历史穿越",
        logline=f"{title}的长篇故事",
        protagonist="沈砚",
        desire="守护典籍",
        coreConflict="朝局与文明存续冲突",
        worldPressure="天下大势倾轧",
        openingHook="典籍将毁",
        differentiation=f"{title}差异化",
    ) for title in ("永乐长明", "文渊山海", "典镇山河"))
    seed_ids = (
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
        SEED_ID,
    )
    seed_revision_ids = (
        "00000000-0000-0000-0000-000000000011",
        "00000000-0000-0000-0000-000000000012",
        SEED_REVISION_ID,
    )
    seed_rows = [{
        "seed_id": seed_id,
        "status": "candidate",
        "seed_revision_id": revision_id,
        "revision": 1,
        "payload_json": canonical_json(payload),
        "content_hash": canonical_hash(payload),
        "head_revision_id": revision_id,
        "head_revision": 1,
        "head_hash": canonical_hash(payload),
    } for seed_id, revision_id, payload in zip(
        seed_ids, seed_revision_ids, seed_payloads, strict=True
    )]
    binding_items = tuple(BindingItem(
        task_key=task_key,
        resolution_status="bound",
        provider_id=PROVIDER_ID,
        provider_name_snapshot="联通云",
        model_name_snapshot="deepseek-v4-flash",
    ) for task_key in TASK_KEYS)
    binding_hash = canonical_hash(BindingRevision(
        project_id=PROJECT_ID, revision=1, items=binding_items,
    ))
    return {
        "database_identity": {"database_name": DATABASE},
        "schema_inventory": [
            {"TABLE_NAME": table} for table in created_table_names()
        ],
        "metadata": {
            "schema_version": EXPECTED_SCHEMA_VERSION,
            "manifest_hash": manifest_hash(),
        },
        "foundation": {
            "project_id": PROJECT_ID,
            "project_title": "永乐大典",
            "project_status": "drafting",
            "current_chapter": 0,
            "project_count": 1,
            "seed_count": 3,
            "selected_seed_id": SEED_ID,
            "selected_seed_revision_id": SEED_REVISION_ID,
            "selected_seed_title": "典镇山河",
            "selected_seed_hash": seed_rows[-1]["content_hash"],
            "selected_revision_hash": seed_rows[-1]["content_hash"],
            "selection_revision": 1,
            "history_selection_revision": 1,
            "history_seed_id": SEED_ID,
            "history_seed_revision_id": SEED_REVISION_ID,
            "history_seed_hash": seed_rows[-1]["content_hash"],
            "provider_count": 9,
            "application_settings_count": 1,
            "application_settings_revision": 0,
            "fallback_provider_id": None,
            "application_settings_updated_at": 0,
            "binding_revision_id": BINDING_REVISION_ID,
            "binding_revision": 1,
            "binding_hash": binding_hash,
            "binding_head_hash": binding_hash,
            "binding_source_project_id": None,
            "binding_item_count": len(TASK_KEYS),
            "bound_item_count": len(TASK_KEYS),
            "contract_revision": 0,
            "creation_contract_id": None,
            "style_contract_id": None,
            "creation_hash": None,
            "style_hash": None,
            "bible_revision": 0,
            "bible_revision_id": None,
            "bible_hash": None,
            "canon_revision": 0,
            "canon_parent_revision": 0,
            "canon_idempotency_key": ProjectLifecycleService.bootstrap_idempotency_key(PROJECT_ID),
            "canon_source_type": "bootstrap",
            "canon_source_id": None,
            "canon_hash": empty_hash,
            "projection_canon_revision": 0,
            "projection_revision": 0,
            "projection_hash": empty_hash,
        },
        "seed_revisions": seed_rows,
        "providers": [
            {
                "id": PROVIDER_ID,
                "name": "联通云",
                "model_name": "deepseek-v4-flash",
                "enabled": 1,
                "lifecycle_status": "active",
                "deleted_at": None,
            },
            *({
                "id": f"00000000-0000-0000-0000-{index:012d}",
                "name": f"备用模型{index}",
                "model_name": f"fallback-model-{index}",
                "enabled": 0,
                "lifecycle_status": "active",
                "deleted_at": None,
            } for index in range(23, 31)),
        ],
        "binding_items": [
            {
                **item.model_dump(mode="json"),
                "item_hash": canonical_hash(item),
                "provider_name": "联通云",
                "provider_model": "deepseek-v4-flash",
                "provider_enabled": 1,
                "provider_lifecycle": "active",
            }
            for item in binding_items
        ],
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
            "canon_entities": 0,
            "entity_aliases": 0,
            "canon_events": 0,
            "current_state_projections": 0,
            "memory_views": 0,
            "arc_projections": 0,
            "plot_thread_projections": 0,
            "reference_uses": 0,
            "provider_profile_mutation_requests": 0,
            "market_sources": 0,
            "market_source_policy_revisions": 0,
            "market_source_policy_heads": 0,
            "market_snapshots": 0,
            "market_snapshot_entries": 0,
            "market_snapshot_manifests": 0,
            "market_source_refresh_states": 0,
            "market_refresh_requests": 0,
            "market_analyses": 0,
            "seed_inspiration_attempts": 0,
            "seed_inspiration_requests": 0,
            "asset_recommendation_attempts": 0,
            "asset_recommendation_requests": 0,
            "style_trial_attempts": 0,
            "style_trial_requests": 0,
            "project_bible_drafts": 0,
            "bible_generation_attempts": 0,
            "creation_bible_revisions": 0,
            "bible_confirmation_requests": 0,
            "creation_contract_engine_refs": 0,
            "style_contract_template_refs": 0,
            "creation_contract_experience_refs": 0,
            "creation_contract_corpus_refs": 0,
            "creation_contract_corpus_fragment_refs": 0,
        },
    }


def asset_rows():
    package = load_asset_package(MANIFEST_PATH, mode="release")
    def row(asset, index, *, card=False):
        return {
            "id": (CARD_ASSET_ID if card and index == 101 else
                   STYLE_ASSET_ID if not card and index == 1 else
                   f"10000000-0000-0000-0000-{index:012d}"),
            "stable_key": asset.stable_key,
            "revision": asset.revision,
            "label": asset.title if card else asset.name,
            "category": asset.category if card else None,
            "content_hash": asset.content_hash,
            "head_hash": asset.content_hash,
            "head_revision": asset.revision,
            "payload_json": canonical_json(asset.payload),
            "provenance_json": canonical_json(asset.provenance),
            "status": "active",
        }
    return {
        "asset_counts": {
            "style_head_count": 10,
            "active_style_head_count": 10,
            "style_revision_count": 10,
            "card_head_count": 64,
            "active_card_head_count": 64,
            "card_revision_count": 64,
        },
        "style_heads": [row(value, index) for index, value in enumerate(package.styles, 1)],
        "card_heads": [row(value, index + 100, card=True) for index, value in enumerate(package.experience_cards, 1)],
    }


def corpus_rows():
    return {
        "corpus": {
            "source_id": CORPUS_SOURCE_ID,
            "source_revision_id": "00000000-0000-0000-0000-000000000051",
            "relative_path": "approved/reference.txt",
            "source_hash": "c" * 64,
            "source_revision": 1,
            "file_size": 4096,
            "status": "analyzed",
            "parser_version": "parser-v1",
            "normalizer_version": "normalizer-v1",
            "fragmenter_version": "fragmenter-v1",
            "index_version": "index-v1",
            "chapter_count": 5,
            "fragment_count": 12,
            "succeeded_run_count": 1,
            "invalid_boundary_count": 0,
            "invalid_version_count": 0,
            "first_byte_start": 0,
            "last_byte_end": 4096,
            "first_char_start": 0,
            "last_char_end": 3600,
        },
    }


def l5_rows():
    option_ids = (
        OPTION_ID,
        "00000000-0000-0000-0000-000000000034",
        "00000000-0000-0000-0000-000000000035",
    )
    options = tuple(StoryEngineOption(
        name=f"发动机{index}", storyPromise=f"承诺{index}",
        protagonistDesire=f"欲望{index}", sustainedPressure=f"压力{index}",
        growthDirection=f"成长{index}", conflictLoop=f"循环{index}",
        ensembleRoles=({"role": f"群像{index}", "purpose": f"作用{index}"},),
        advantageAndCost=f"代价{index}", satisfactionSources=(f"满足{index}",),
        longFormVariation=(f"变化{index}",), endingAnchor=f"终局{index}",
        risks=(f"风险{index}",), differentiation=f"差异{index}",
    ) for index in range(1, 4))
    option_rows = [{
        "id": option_id, "selection_revision": 1, "option_order": index,
        "payload_json": canonical_json(option), "content_hash": canonical_hash(option),
    } for index, (option_id, option) in enumerate(zip(option_ids, options, strict=True), 1)]
    seed_payload = SeedPayload(
        title="典镇山河", genre="历史穿越", logline="典镇山河的长篇故事",
        protagonist="沈砚", desire="守护典籍", coreConflict="朝局与文明存续冲突",
        worldPressure="天下大势倾轧", openingHook="典籍将毁",
        differentiation="典镇山河差异化",
    )
    binding_items = tuple(BindingItem(
        task_key=task_key, resolution_status="bound", provider_id=PROVIDER_ID,
        provider_name_snapshot="联通云", model_name_snapshot="deepseek-v4-flash",
    ) for task_key in TASK_KEYS)
    binding_hash = canonical_hash(BindingRevision(
        project_id=PROJECT_ID, revision=1, items=binding_items,
    ))
    creation_payload = CreationContractPayload(
        schemaVersion="creation-contract-v1", channelProfileKey="qidian-male",
        genreProfileKey="historical-crossing", qualityCharterVersion="quality-v1",
        selectionRevision=1, selectedSeed=seed_payload, selectedEngine=options[0],
        totalWordRange=(800000, 1200000),
        chapterCapacityPolicy="故事块按情节自然跨章", modelBindingRevision=1,
    )
    style_payload = StyleContractPayload(
        schemaVersion="style-contract-v1", readingExperience="通俗丰满且引人继续阅读",
        narrativeDistance="贴近人物", sentenceParagraphRhythm="长短句自然变化",
        dictionDensity="大白话为主", dialogueAndSubtext="对白符合身份并包含潜台词",
        characterVoices=("人物声音可区分",),
        emotionAndInteriority="情绪与内心自然嵌入行动",
        actionExplanationEnvironment="行动说明环境服务故事",
        primaryRules=("先讲好故事",), secondaryFlavor=None, risks=("机械推进",),
    )
    likes = ["人物声音有区分"]
    dislikes = ["机械推进"]
    style_ref = {
        "role": "primary", "id": STYLE_ASSET_ID, "revision": 1,
        "contentHash": load_asset_package(MANIFEST_PATH, mode="release").styles[0].content_hash,
    }
    card_ref = {
        "id": CARD_ASSET_ID, "revision": 1,
        "contentHash": load_asset_package(MANIFEST_PATH, mode="release").experience_cards[0].content_hash,
    }
    corpus_ref = {
        "id": CORPUS_SOURCE_ID, "revision": 1, "contentHash": "c" * 64,
        "selectionMode": "author",
    }
    reference_manifest = {
        "schemaVersion": "contract-reference-manifest-v1",
        "seedRef": {
            "id": SEED_ID, "revisionId": SEED_REVISION_ID,
            "contentHash": canonical_hash(seed_payload),
        },
        "engineRef": {
            "id": OPTION_ID, "batchId": BATCH_ID,
            "contentHash": canonical_hash(options[0]),
        },
        "bindingRef": {
            "id": BINDING_REVISION_ID, "revision": 1,
            "contentHash": binding_hash,
        },
        "styleRefs": [style_ref],
        "experienceCardRefs": [card_ref],
        "corpusSourceRefs": [corpus_ref],
    }
    creation_hash = canonical_hash(creation_payload)
    style_hash = style_contract_hash(style_payload, likes, dislikes)
    return {
        "l5": {
            "batch_id": BATCH_ID,
            "batch_count": 1,
            "source_type": "provider",
            "batch_status": "succeeded",
            "batch_seed_id": SEED_ID,
            "batch_seed_revision_id": SEED_REVISION_ID,
            "batch_seed_hash": canonical_hash(seed_payload),
            "batch_selection_revision": 1,
            "batch_binding_revision_id": BINDING_REVISION_ID,
            "batch_binding_hash": binding_hash,
            "attempt_count": 1,
            "attempt_id": ATTEMPT_ID,
            "request_hash": "5" * 64,
            "raw_response_hash": "6" * 64,
            "batch_provider_id": PROVIDER_ID,
            "batch_model_name": "deepseek-v4-flash",
            "binding_provider_id": PROVIDER_ID,
            "binding_provider_name": "联通云",
            "binding_model_name": "deepseek-v4-flash",
            "provider_name": "联通云",
            "provider_model": "deepseek-v4-flash",
            "provider_enabled": 1,
            "provider_lifecycle": "active",
            "option_count": 3,
            "distinct_option_hash_count": 3,
            "contract_head_revision": 1,
            "creation_contract_id": CREATION_ID,
            "style_contract_id": STYLE_ID,
            "creation_hash": creation_hash,
            "head_creation_hash": creation_hash,
            "style_hash": style_hash,
            "head_style_hash": style_hash,
            "creation_revision": 1,
            "style_revision": 1,
            "creation_selection_revision": 1,
            "creation_seed_id": SEED_ID,
            "creation_seed_revision_id": SEED_REVISION_ID,
            "creation_seed_hash": canonical_hash(seed_payload),
            "creation_binding_revision_id": BINDING_REVISION_ID,
            "creation_binding_hash": binding_hash,
            "engine_option_id": OPTION_ID,
            "engine_hash": canonical_hash(options[0]),
            "engine_option_hash": canonical_hash(options[0]),
            "engine_option_batch_id": BATCH_ID,
            "selected_engine_option_id": OPTION_ID,
            "confirmation_status": "succeeded",
            "confirmation_result_revision": 1,
        },
        "l5_options": option_rows,
        "l5_confirmations": [{
            "id": "00000000-0000-0000-0000-000000000043",
            "selection_revision": 1,
            "status": "succeeded",
            "creation_contract_id": CREATION_ID,
            "style_contract_id": STYLE_ID,
            "result_revision": 1,
        }],
        "l5_contract_payload": {
            "creation_json": canonical_json(creation_payload),
            "creation_content_hash": creation_hash,
            "style_json": canonical_json(style_payload),
            "likes_json": canonical_json(likes),
            "dislikes_json": canonical_json(dislikes),
            "style_content_hash": style_hash,
            "reference_manifest_json": canonical_json(reference_manifest),
            "reference_manifest_hash": canonical_hash(reference_manifest),
        },
        "l5_style_refs": [{
            "role": "primary", "style_template_id": STYLE_ASSET_ID,
            "asset_revision": 1, "asset_hash": style_ref["contentHash"],
            "actual_asset_hash": style_ref["contentHash"], "sort_order": 1,
        }],
        "l5_experience_refs": [{
            "experience_card_id": CARD_ASSET_ID,
            "asset_revision": 1, "asset_hash": card_ref["contentHash"],
            "actual_asset_hash": card_ref["contentHash"], "sort_order": 1,
        }],
        "l5_corpus_refs": [{
            "corpus_source_id": CORPUS_SOURCE_ID, "source_revision": 1,
            "source_hash": "c" * 64, "actual_source_hash": "c" * 64,
            "selection_mode": "author", "sort_order": 1,
        }],
    }


@pytest.mark.asyncio
async def test_base_receipt_is_select_only_bounded_and_requires_fresh_head_zero():
    from backend.scripts.verify_milestone2_product import (
        format_product_receipt,
        verify_milestone2_product,
    )

    session = ReceiptSession(base_rows())
    receipt = await verify_milestone2_product(session, expected_database=DATABASE)

    assert receipt["schemaVersion"] == EXPECTED_SCHEMA_VERSION
    assert receipt["project"] == {
        "id": PROJECT_ID,
        "title": "永乐大典",
        "seedCount": 3,
        "selectedSeedId": SEED_ID,
        "selectedSeedTitle": "典镇山河",
        "providerCount": 9,
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
        ReceiptSession(rows), expected_database=DATABASE, require_assets=True
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
        await verify_milestone2_product(
            ReceiptSession(rows), expected_database=DATABASE, require_assets=True
        )


@pytest.mark.asyncio
async def test_corpus_requires_succeeded_relative_metadata_and_positive_counts():
    from backend.scripts.verify_milestone2_product import verify_milestone2_product

    rows = {**base_rows(), **corpus_rows()}
    receipt = await verify_milestone2_product(
        ReceiptSession(rows), expected_database=DATABASE, require_corpus=True,
        expected_source_hash="c" * 64,
    )
    assert receipt["corpus"] == {
        "sourceId": rows["corpus"]["source_id"],
        "sourceRevision": 1,
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
        await verify_milestone2_product(
            ReceiptSession(rows), expected_database=DATABASE, require_corpus=True,
            expected_source_hash="c" * 64,
        )


@pytest.mark.asyncio
async def test_l5_requires_one_provider_attempt_three_options_and_consistent_contract_refs():
    from backend.scripts.verify_milestone2_product import verify_milestone2_product

    base = base_rows()
    base["foundation"]["contract_revision"] = 1
    base["foundation"]["creation_contract_id"] = CREATION_ID
    base["foundation"]["style_contract_id"] = STYLE_ID
    l5 = l5_rows()
    base["foundation"]["creation_hash"] = l5["l5"]["creation_hash"]
    base["foundation"]["style_hash"] = l5["l5"]["style_hash"]
    base["later_counts"].update({
        "story_engine_batches": 1,
        "story_engine_options": 3,
        "creation_contracts": 1,
        "style_contracts": 1,
        "contract_confirmation_requests": 1,
        "creation_contract_engine_refs": 1,
        "style_contract_template_refs": 1,
        "creation_contract_experience_refs": 1,
        "creation_contract_corpus_refs": 1,
    })
    rows = {**base, **asset_rows(), **corpus_rows(), **l5}
    receipt = await verify_milestone2_product(
        ReceiptSession(rows), expected_database=DATABASE, require_l5=True,
        expected_source_hash="c" * 64,
    )
    assert receipt["l5"] == {
        "batchId": BATCH_ID,
        "requestHash": "5" * 64,
        "attemptId": ATTEMPT_ID,
        "rawResponseHash": "6" * 64,
        "attemptCount": 1,
        "optionCount": 3,
        "options": [{key: row[key] for key in ("id", "option_order", "content_hash")}
                    for row in l5["l5_options"]],
        "selectedEngineOptionId": OPTION_ID,
        "contractRevision": 1,
        "creationContractId": CREATION_ID,
        "styleContractId": STYLE_ID,
        "creationHash": l5["l5"]["creation_hash"],
        "styleHash": l5["l5"]["style_hash"],
        "referenceManifestHash": l5["l5_contract_payload"]["reference_manifest_hash"],
    }

    rows["l5"]["option_count"] = 2
    with pytest.raises(RuntimeError, match="exactly three"):
        await verify_milestone2_product(
            ReceiptSession(rows), expected_database=DATABASE, require_l5=True,
            expected_source_hash="c" * 64,
        )


@pytest.mark.asyncio
async def test_l5_allows_multiple_experience_card_refs_with_canonical_order():
    from backend.scripts.verify_milestone2_product import verify_milestone2_product

    rows = _valid_l5_rows()
    package = load_asset_package(MANIFEST_PATH, mode="release")
    second = package.experience_cards[1]
    rows["later_counts"]["creation_contract_experience_refs"] = 2
    rows["l5_experience_refs"].append({
        "experience_card_id": "10000000-0000-0000-0000-000000000102",
        "asset_revision": 1,
        "asset_hash": second.content_hash,
        "actual_asset_hash": second.content_hash,
        "sort_order": 2,
    })
    manifest = json.loads(rows["l5_contract_payload"]["reference_manifest_json"])
    manifest["experienceCardRefs"].append({
        "id": "10000000-0000-0000-0000-000000000102",
        "revision": 1,
        "contentHash": second.content_hash,
    })
    rows["l5_contract_payload"]["reference_manifest_json"] = canonical_json(manifest)
    rows["l5_contract_payload"]["reference_manifest_hash"] = canonical_hash(manifest)

    receipt = await verify_milestone2_product(
        ReceiptSession(rows),
        expected_database=DATABASE,
        require_l5=True,
        expected_source_hash="c" * 64,
    )

    assert receipt["l5"]["referenceManifestHash"] == canonical_hash(manifest)


@pytest.mark.asyncio
async def test_l5_allows_manual_story_engine_batch_without_provider_attempt():
    from backend.scripts.verify_milestone2_product import verify_milestone2_product

    rows = _valid_l5_rows()
    rows["l5"].update({
        "source_type": "manual",
        "attempt_id": None,
        "request_hash": "5" * 64,
        "raw_response_hash": None,
        "batch_provider_id": None,
        "batch_model_name": None,
        "batch_binding_revision_id": None,
        "batch_binding_hash": None,
    })

    receipt = await verify_milestone2_product(
        ReceiptSession(rows),
        expected_database=DATABASE,
        require_l5=True,
        expected_source_hash="c" * 64,
    )

    assert receipt["l5"]["batchId"] == BATCH_ID
    assert receipt["l5"]["requestHash"] == "5" * 64
    assert receipt["l5"]["attemptCount"] == 0
    assert receipt["l5"]["attemptId"] is None


@pytest.mark.asyncio
async def test_require_l5_implies_assets_and_corpus_and_rejects_head_zero():
    from backend.scripts.verify_milestone2_product import verify_milestone2_product

    rows = {**base_rows(), **asset_rows(), **corpus_rows(), **l5_rows()}
    with pytest.raises(RuntimeError, match="contract head revision 1"):
        await verify_milestone2_product(
            ReceiptSession(rows), expected_database=DATABASE, require_l5=True,
            expected_source_hash="c" * 64,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda rows: rows["schema_inventory"].append({"TABLE_NAME": "legacy_table"}), "table inventory"),
        (lambda rows: rows["schema_inventory"].pop(), "table inventory"),
        (lambda rows: rows["database_identity"].update(database_name=None), "database"),
        (lambda rows: rows["foundation"].update(project_title="错误项目"), "永乐大典"),
        (lambda rows: rows["foundation"].update(project_status="active"), "drafting"),
        (lambda rows: rows["foundation"].update(current_chapter=1), "chapter 0"),
        (lambda rows: rows["seed_revisions"][0].update(status="archived"), "candidate"),
        (lambda rows: rows["seed_revisions"][0].update(payload_json=canonical_json({"tampered": True})), "seed"),
        (lambda rows: rows["seed_revisions"][0].update(head_hash="0" * 64), "seed head"),
        (lambda rows: rows["binding_items"].pop(), "task"),
        (lambda rows: rows["binding_items"][0].update(provider_enabled=0), "active"),
        (lambda rows: rows["binding_items"][0].update(model_name_snapshot="wrong-model"), "deepseek-v4-flash"),
        (lambda rows: rows["binding_items"][0].update(item_hash="0" * 64), "item hash"),
        (lambda rows: rows["foundation"].update(binding_hash="0" * 64, binding_head_hash="0" * 64), "binding"),
        (lambda rows: rows["foundation"].update(canon_source_type="manual_test"), "Canon"),
    ],
)
async def test_foundation_requires_exact_schema_project_and_recomputed_binding_closed_set(
    mutation, match,
):
    from backend.scripts.verify_milestone2_product import verify_milestone2_product

    rows = base_rows()
    mutation(rows)
    with pytest.raises(RuntimeError, match=match):
        await verify_milestone2_product(
            ReceiptSession(rows), expected_database=DATABASE
        )


@pytest.mark.asyncio
async def test_asset_verifier_recomputes_every_database_payload_hash():
    from backend.scripts.verify_milestone2_product import verify_milestone2_product

    rows = {**base_rows(), **asset_rows()}
    rows["style_heads"][0]["payload_json"] = canonical_json({"tampered": True})
    with pytest.raises(RuntimeError, match="payload hash"):
        await verify_milestone2_product(
            ReceiptSession(rows), expected_database=DATABASE, require_assets=True
        )

    rows = {**base_rows(), **asset_rows()}
    rows["card_heads"][0]["provenance_json"] = canonical_json({"decision": "pending"})
    with pytest.raises(RuntimeError, match="package"):
        await verify_milestone2_product(
            ReceiptSession(rows), expected_database=DATABASE, require_assets=True
        )


@pytest.mark.asyncio
async def test_corpus_verifier_requires_the_explicit_source_hash_and_valid_boundaries():
    from backend.scripts.verify_milestone2_product import verify_milestone2_product

    rows = {**base_rows(), **corpus_rows()}
    with pytest.raises(RuntimeError, match="source hash"):
        await verify_milestone2_product(
            ReceiptSession(rows),
            expected_database=DATABASE,
            require_corpus=True,
            expected_source_hash="d" * 64,
        )
    rows["corpus"]["source_hash"] = "d" * 64
    rows["corpus"]["invalid_boundary_count"] = 1
    with pytest.raises(RuntimeError, match="boundar"):
        await verify_milestone2_product(
            ReceiptSession(rows),
            expected_database=DATABASE,
            require_corpus=True,
            expected_source_hash="d" * 64,
        )

    rows = {**base_rows(), **corpus_rows()}
    rows["corpus"]["last_byte_end"] = 4095
    with pytest.raises(RuntimeError, match="boundar"):
        await verify_milestone2_product(
            ReceiptSession(rows), expected_database=DATABASE, require_corpus=True,
            expected_source_hash="c" * 64,
        )


def _valid_l5_rows():
    base = base_rows()
    l5 = l5_rows()
    base["foundation"].update({
        "contract_revision": 1,
        "creation_contract_id": CREATION_ID,
        "style_contract_id": STYLE_ID,
        "creation_hash": l5["l5"]["creation_hash"],
        "style_hash": l5["l5"]["style_hash"],
    })
    base["later_counts"].update({
        "story_engine_batches": 1,
        "story_engine_options": 3,
        "creation_contracts": 1,
        "style_contracts": 1,
        "contract_confirmation_requests": 1,
        "creation_contract_engine_refs": 1,
        "style_contract_template_refs": 1,
        "creation_contract_experience_refs": 1,
        "creation_contract_corpus_refs": 1,
    })
    return {**base, **asset_rows(), **corpus_rows(), **l5}


def test_explicit_corpus_hash_verifies_an_immutable_revision_not_only_current_head():
    from backend.scripts.verify_milestone2_product import _CORPUS_SQL

    assert "JOIN corpus_source_revisions r ON r.source_id=s.id" in _CORPUS_SQL
    assert "JOIN corpus_source_heads" not in _CORPUS_SQL


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda rows: rows["later_counts"].update(story_engine_batches=2), "batch"),
        (lambda rows: rows["later_counts"].update(project_contract_drafts=1), "draft"),
        (lambda rows: rows["later_counts"].update(canon_events=1), "Canon"),
        (lambda rows: rows["later_counts"].update(reference_uses=1), "reference"),
        (lambda rows: rows["l5"].update(batch_model_name="wrong-model"), "deepseek-v4-flash"),
        (lambda rows: rows["l5_options"].append(dict(rows["l5_options"][0])), "three options"),
        (lambda rows: rows["l5_options"][0].update(payload_json=canonical_json({"tampered": True})), "option"),
        (lambda rows: rows["l5_confirmations"].append(dict(rows["l5_confirmations"][0])), "confirmation"),
        (lambda rows: rows["l5_contract_payload"].update(creation_json=canonical_json({"tampered": True})), "CreationContract"),
        (lambda rows: rows["l5_contract_payload"].update(style_json=canonical_json({"tampered": True})), "StyleContract"),
        (lambda rows: rows["l5_style_refs"].clear(), "style ref"),
        (lambda rows: rows["l5_experience_refs"].clear(), "experience"),
        (lambda rows: rows["l5_corpus_refs"].clear(), "corpus ref"),
        (lambda rows: rows["l5_contract_payload"].update(reference_manifest_json=canonical_json({"tampered": True})), "manifest"),
    ],
)
async def test_l5_fails_closed_on_extra_rows_provider_contract_or_ref_drift(
    mutation, match,
):
    from backend.scripts.verify_milestone2_product import verify_milestone2_product

    rows = _valid_l5_rows()
    mutation(rows)
    with pytest.raises(RuntimeError, match=match):
        await verify_milestone2_product(
            ReceiptSession(rows), expected_database=DATABASE, require_l5=True,
            expected_source_hash="c" * 64,
        )


@pytest.mark.asyncio
async def test_l5_receipt_is_bounded_and_never_contains_contract_or_reference_body():
    from backend.scripts.verify_milestone2_product import (
        format_product_receipt,
        verify_milestone2_product,
    )

    receipt = await verify_milestone2_product(
        ReceiptSession(_valid_l5_rows()),
        expected_database=DATABASE,
        require_l5=True,
        expected_source_hash="c" * 64,
    )
    rendered = format_product_receipt(receipt)
    for forbidden in (
        "content_json", "merged_style_json", "likes_json", "dislikes_json",
        "reference_manifest_json", "bounded", "人物声音有区分", "机械推进",
    ):
        assert forbidden not in rendered


@pytest.mark.asyncio
async def test_corpus_modes_require_explicit_source_hash_before_any_select():
    from backend.scripts.verify_milestone2_product import (
        ProductVerificationError,
        verify_milestone2_product,
    )

    class NoQuerySession:
        async def fetchone(self, *_args, **_kwargs):
            raise AssertionError("verification must fail before querying")

        async def fetchall(self, *_args, **_kwargs):
            raise AssertionError("verification must fail before querying")

    for flags in ({"require_corpus": True}, {"require_l5": True}):
        with pytest.raises(ProductVerificationError, match="explicit.*source hash"):
            await verify_milestone2_product(
                NoQuerySession(), expected_database=DATABASE, **flags
            )


@pytest.mark.asyncio
async def test_verifier_requires_exact_explicit_database_identity():
    from backend.scripts.verify_milestone2_product import verify_milestone2_product

    rows = base_rows()
    with pytest.raises(RuntimeError, match="database identity"):
        await verify_milestone2_product(
            ReceiptSession(rows), expected_database="another_test_database"
        )


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (
            lambda rows: rows["foundation"].update(provider_count=0),
            "Provider count must be positive",
        ),
        (
            lambda rows: rows["foundation"].update(provider_count=-1),
            "Provider count must be positive",
        ),
        (
            lambda rows: rows["foundation"].update(provider_count=True),
            "field provider_count must be an integer",
        ),
        (
            lambda rows: rows["providers"].pop(),
            "Provider row count must match the foundation count",
        ),
        (
            lambda rows: rows["providers"][1].update(id=rows["providers"][0]["id"]),
            "Provider ids must be unique",
        ),
        (
            lambda rows: rows["providers"][1].update(name=rows["providers"][0]["name"]),
            "Provider names must be unique",
        ),
        (
            lambda rows: rows["providers"][1].update(
                lifecycle_status="deleted", deleted_at=123
            ),
            "Provider rows must all be active",
        ),
        (
            lambda rows: rows["providers"][1].update(lifecycle_status="disabled"),
            "Provider rows must all be active",
        ),
        (
            lambda rows: rows["providers"][1].update(deleted_at=123),
            "Provider rows must all be active",
        ),
        (
            lambda rows: rows["providers"][1].update(id=""),
            "Provider rows must all be active",
        ),
        (
            lambda rows: rows["providers"][1].update(
                name=NonExactString("备用模型")
            ),
            "Provider rows must all be active",
        ),
        (
            lambda rows: rows["providers"][1].update(
                model_name=NonExactString("fallback-model")
            ),
            "Provider rows must all be active",
        ),
        (
            lambda rows: rows["providers"][1].update(enabled=True),
            "Provider rows must all be active",
        ),
        (
            lambda rows: rows["providers"][1].update(enabled=2),
            "Provider rows must all be active",
        ),
    ],
)
@pytest.mark.asyncio
async def test_verifier_fails_closed_on_invalid_provider_inventory(mutation, match):
    from backend.scripts.verify_milestone2_product import verify_milestone2_product

    rows = base_rows()
    mutation(rows)
    with pytest.raises(RuntimeError, match=match):
        await verify_milestone2_product(
            ReceiptSession(rows), expected_database=DATABASE
        )


@pytest.mark.asyncio
async def test_asset_verifier_rejects_headless_historical_revisions():
    from backend.scripts.verify_milestone2_product import verify_milestone2_product

    rows = {**base_rows(), **asset_rows()}
    rows["asset_counts"]["style_revision_count"] = 11
    with pytest.raises(RuntimeError, match="exactly 10.*64"):
        await verify_milestone2_product(
            ReceiptSession(rows),
                expected_database=DATABASE,
            require_assets=True,
        )

    rows = {**base_rows(), **asset_rows()}
    rows["asset_counts"]["card_revision_count"] = 65
    with pytest.raises(RuntimeError, match="exactly 10.*64"):
        await verify_milestone2_product(
            ReceiptSession(rows),
                expected_database=DATABASE,
            require_assets=True,
        )


@pytest.mark.asyncio
async def test_l5_corpus_ref_must_match_the_explicit_verified_source_hash():
    from backend.scripts.verify_milestone2_product import verify_milestone2_product

    rows = _valid_l5_rows()
    rows["l5_corpus_refs"][0].update(
        source_hash="d" * 64, actual_source_hash="d" * 64
    )
    with pytest.raises(RuntimeError, match="explicit.*corpus source"):
        await verify_milestone2_product(
            ReceiptSession(rows),
            expected_database=DATABASE,
            require_l5=True,
            expected_source_hash="c" * 64,
        )


@pytest.mark.asyncio
async def test_corpus_cli_without_explicit_hash_fails_before_connect():
    from backend.scripts.verify_milestone2_product import (
        ProductVerificationError,
        run_cli,
    )

    calls = []

    async def connect(_config):
        calls.append("connect")
        raise AssertionError("must fail before connect")

    with pytest.raises(ProductVerificationError, match="explicit.*source hash"):
        await run_cli(
            ["--database", "m2_test_database", "--require-corpus"],
            connection_config={},
            connection_factory=connect,
        )
    assert calls == []


@pytest.mark.parametrize(
    "unsafe_path",
    [
        r"approved\reference.txt",
        "approved//reference.txt",
        "approved/./reference.txt",
        "./approved/reference.txt",
        "approved/reference.txt/",
        "../approved/reference.txt",
        "approved/../reference.txt",
        "/approved/reference.txt",
        "C:/approved/reference.txt",
        r"C:\approved\reference.txt",
        r"\\server\share\reference.txt",
    ],
)
def test_corpus_relative_path_rejects_every_noncanonical_variant(unsafe_path):
    from backend.scripts.verify_milestone2_product import (
        ProductVerificationError,
        _relative_path,
    )

    with pytest.raises(ProductVerificationError, match="safe relative path"):
        _relative_path(unsafe_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("second_is_analyzed", [False, True])
async def test_corpus_hash_must_identify_exactly_one_source(second_is_analyzed):
    from backend.scripts.verify_milestone2_product import verify_milestone2_product

    rows = _valid_l5_rows()
    first = rows["corpus"]
    second = {
        **first,
        "source_id": "00000000-0000-0000-0000-000000000052",
        "relative_path": "approved/duplicate.txt",
        "status": "analyzed" if second_is_analyzed else "imported",
    }
    rows["corpus"] = [first, second]
    rows["l5_corpus_refs"][0].update(
        corpus_source_id=second["source_id"],
        source_revision=second["source_revision"],
    )

    with pytest.raises(RuntimeError, match="exactly one.*source"):
        await verify_milestone2_product(
            MultiCorpusReceiptSession(rows),
            expected_database=DATABASE,
            require_l5=True,
            expected_source_hash="c" * 64,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ref_key",
    ["l5_style_refs", "l5_experience_refs", "l5_corpus_refs"],
)
async def test_l5_reference_rows_require_canonical_first_sort_order(ref_key):
    from backend.scripts.verify_milestone2_product import verify_milestone2_product

    rows = _valid_l5_rows()
    rows[ref_key][0]["sort_order"] = 2
    with pytest.raises(RuntimeError, match="sort order"):
        await verify_milestone2_product(
            ReceiptSession(rows),
            expected_database=DATABASE,
            require_l5=True,
            expected_source_hash="c" * 64,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("corpus_source_id", "00000000-0000-0000-0000-000000000052"),
        ("source_revision", 2),
    ],
)
async def test_l5_corpus_ref_must_bind_the_exact_verified_source(field, value):
    from backend.scripts.verify_milestone2_product import verify_milestone2_product

    rows = _valid_l5_rows()
    rows["l5_corpus_refs"][0][field] = value
    with pytest.raises(RuntimeError, match="explicit.*corpus source"):
        await verify_milestone2_product(
            ReceiptSession(rows),
            expected_database=DATABASE,
            require_l5=True,
            expected_source_hash="c" * 64,
        )
