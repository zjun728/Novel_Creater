from __future__ import annotations

import inspect
import json
from pathlib import Path
import subprocess
import sys

import pytest

import backend.scripts.reset_writer_core_data as reset_module
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.model_bindings import TASK_KEYS
from backend.domain.seeds import SeedPayload
from backend.schema_manifest import created_table_names, manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION


DISPOSABLE = "novel_creator_test_0123456789abcdef0123456789abcdef"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SEED_TITLES = ("永乐长明", "文渊山海", "典镇山河")


def _request(**changes):
    values = {
        "project_title": "永乐大典",
        "seed_titles": SEED_TITLES,
        "preferred_provider_name": "联通云",
        "preferred_model": "deepseek-v4-flash",
    }
    values.update(changes)
    return reset_module.ResetRequest(**values)


def _seed_payload(title: str) -> SeedPayload:
    return SeedPayload(
        title=title,
        genre="历史穿越",
        logline="在历史压力下完成目标。",
        protagonist="主角",
        desire="守住承诺",
        coreConflict="时间不足",
        worldPressure="局势变化",
        openingHook="危机发生",
        differentiation="只用于重建测试",
    )


def _provider_row() -> dict[str, object]:
    return {
        "id": "provider",
        "name": "联通云",
        "provider_type": "openai-compatible",
        "model_name": "deepseek-v4-flash",
        "base_url": "BASE_URL_SENTINEL",
        "api_key": "API_KEY_SENTINEL",
        "enabled": 1,
        "sort_order": 0,
        "stream": 1,
        "max_context_tokens": 4096,
        "max_output_tokens": 1024,
        "temperature": "0.800",
        "top_p": "0.900",
        "supports_json": 1,
        "supports_streaming": 1,
        "notes": "NOTES_SENTINEL",
        "thinking": None,
        "lifecycle_status": "active",
        "deleted_at": None,
        "created_at": 1,
        "updated_at": 1,
    }


def _foundation_state():
    project = reset_module._map_project(
        {
            "id": "project",
            "title": "永乐大典",
            "genre": "历史穿越",
            "description": "DESCRIPTION_SENTINEL",
            "target_words": 100_000,
            "target_chapters": 100,
            "status": "drafting",
            "current_chapter": 0,
            "created_at": 1,
            "updated_at": 1,
        }
    )
    seeds = []
    for index, title in enumerate(SEED_TITLES, 1):
        payload = _seed_payload(title)
        seeds.append(
            reset_module._map_v11_seed(
                {
                    "id": f"seed-{index}",
                    "project_id": "project",
                    "title": title,
                    "premise_json": canonical_json(payload),
                    "content_hash": canonical_hash(payload),
                    "status": "candidate",
                    "created_at": 1,
                },
                "project",
            )
        )
    provider = reset_module._map_provider(_provider_row())
    return reset_module._PreservedState(project, tuple(seeds), (provider,), provider)


class InventorySession:
    def __init__(self, tables, version, manifest):
        self.tables = tuple(tables)
        self.version = version
        self.manifest = manifest
        self.calls = []

    async def fetchall(self, sql, args=None):
        self.calls.append(("fetchall", " ".join(sql.split()), args))
        return [{"TABLE_NAME": table} for table in self.tables]

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", " ".join(sql.split()), args))
        return {
            "schema_version": self.version,
            "manifest_hash": self.manifest,
        }


def test_reset_source_contract_freezes_only_v11_and_current_v12():
    assert reset_module.V11_SCHEMA_VERSION == "writer-core-v1.1.0"
    assert (
        reset_module.V11_MANIFEST_HASH
        == "cf993ccf7f000935aaa5777bfb9adda4cd6cbd47cb4f83be5d073d7d3e6b30c5"
    )
    assert len(reset_module.V11_TABLE_NAMES) == 49
    assert len(set(reset_module.V11_TABLE_NAMES)) == 49
    assert reset_module.V11_TABLE_NAMES == (
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
        "style_templates",
        "style_template_heads",
        "experience_cards",
        "experience_card_heads",
        "corpus_sources",
        "corpus_chapters",
        "corpus_fragments",
        "corpus_import_runs",
        "story_engine_batches",
        "story_engine_options",
        "project_contract_drafts",
        "creation_contracts",
        "style_contracts",
        "project_contract_heads",
        "contract_confirmation_requests",
        "creation_contract_engine_refs",
        "style_contract_template_refs",
        "creation_contract_experience_refs",
        "creation_contract_corpus_refs",
        "volume_plans",
        "story_blocks",
        "story_stages",
        "scene_tasks",
        "chapter_sessions",
        "working_drafts",
        "draft_candidates",
        "finalization_change_sets",
        "finalization_records",
        "final_chapters",
        "canon_entities",
        "entity_aliases",
        "canon_revisions",
        "canon_events",
        "current_state_projections",
        "memory_views",
        "arc_projections",
        "plot_thread_projections",
        "projection_heads",
        "reference_uses",
    )
    assert EXPECTED_SCHEMA_VERSION == "writer-core-v1.2.0"
    assert not hasattr(reset_module, "M1_SCHEMA_VERSION")
    assert not hasattr(reset_module, "M1_MANIFEST_HASH")
    assert not hasattr(reset_module, "M1_TABLE_NAMES")
    assert not hasattr(reset_module, "_map_m1_seed")
    assert not hasattr(reset_module, "_load_m1_preserved_state")


def test_reset_source_validation_has_no_stale_m1_labels():
    assert "M1 Provider" not in inspect.getsource(reset_module)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tables", "version", "manifest", "expected"),
    [
        (
            lambda: reset_module.V11_TABLE_NAMES,
            "writer-core-v1.1.0",
            "cf993ccf7f000935aaa5777bfb9adda4cd6cbd47cb4f83be5d073d7d3e6b30c5",
            "v1.1-source",
        ),
        (
            created_table_names,
            "writer-core-v1.2.0",
            manifest_hash,
            "v1.2-target",
        ),
    ],
)
async def test_reset_classifies_only_frozen_v11_or_current_v12(
    tables, version, manifest, expected
):
    resolved_manifest = manifest() if callable(manifest) else manifest
    session = InventorySession(tables(), version, resolved_manifest)
    assert await reset_module._classify_reset_source(session, DISPOSABLE) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tables", "version", "manifest"),
    [
        (
            (
                "schema_metadata",
                "projects",
                "creative_seeds",
                "project_selected_seeds",
                "provider_profiles",
            ),
            "writer-core-v1.0.0",
            "0697b6da4826b98c8e502ff7ad68a61b51fe7037b167b6d8175ae9d78dcff826",
        ),
        (
            lambda: reset_module.V11_TABLE_NAMES[:-1],
            "writer-core-v1.1.0",
            "cf993ccf7f000935aaa5777bfb9adda4cd6cbd47cb4f83be5d073d7d3e6b30c5",
        ),
        (
            lambda: reset_module.V11_TABLE_NAMES,
            "writer-core-v1.1.0",
            "0" * 64,
        ),
    ],
)
async def test_reset_rejects_m1_or_tampered_inventory(tables, version, manifest):
    resolved_tables = tables() if callable(tables) else tables
    session = InventorySession(resolved_tables, version, manifest)
    with pytest.raises(
        reset_module.ResetValidationError,
        match="v1.1 source or v1.2 target",
    ):
        await reset_module._classify_reset_source(session, DISPOSABLE)


def test_v11_project_mapping_adds_only_new_lifecycle_defaults():
    mapped = reset_module._map_project(
        {
            "id": "project",
            "title": "永乐大典",
            "genre": "历史",
            "description": "preserve",
            "target_words": 1,
            "target_chapters": 1,
            "status": "drafting",
            "current_chapter": 0,
            "created_at": 1,
            "updated_at": 2,
        }
    )
    assert mapped == {
        "id": "project",
        "title": "永乐大典",
        "genre": "历史",
        "description": "preserve",
        "target_words": 1,
        "target_chapters": 1,
        "status": "drafting",
        "current_chapter": 0,
        "archived_at": None,
        "lifecycle_revision": 0,
        "created_at": 1,
        "updated_at": 2,
    }


def test_v11_seed_and_provider_mapping_preserve_exact_approved_values():
    payload = _seed_payload("典镇山河")
    seed = reset_module._map_v11_seed(
        {
            "id": "seed",
            "project_id": "project",
            "title": "典镇山河",
            "premise_json": canonical_json(payload),
            "content_hash": canonical_hash(payload),
            "status": "candidate",
            "created_at": 1,
        },
        "project",
    )
    provider = reset_module._map_provider(_provider_row())
    assert seed["id"] == "seed"
    assert seed["title"] == "典镇山河"
    assert seed["content_hash"] == canonical_hash(payload)
    assert provider == {
        **_provider_row(),
        "temperature": reset_module.Decimal("0.800"),
        "top_p": reset_module.Decimal("0.900"),
    }


def test_reset_receipt_labels_frozen_source_and_new_target_without_secrets():
    state = _foundation_state()
    rendered = reset_module.format_reset_report(
        reset_module._report(
            DISPOSABLE,
            state,
            executed=False,
            source_kind="v1.1-source",
        )
    )
    decoded = json.loads(rendered)
    assert decoded["source"]["kind"] == "v1.1-source"
    assert decoded["source"]["schemaVersion"] == "writer-core-v1.1.0"
    assert decoded["source"]["manifestHash"] == reset_module.V11_MANIFEST_HASH
    assert decoded["target"]["kind"] == "v1.2-target"
    assert decoded["target"]["schemaVersion"] == EXPECTED_SCHEMA_VERSION
    assert decoded["target"]["manifestHash"] == manifest_hash()
    assert decoded["target"]["verified"] is False
    assert rendered.count("\n") == 0
    for forbidden in (
        "BASE_URL_SENTINEL",
        "API_KEY_SENTINEL",
        "NOTES_SENTINEL",
        "api_key",
        "base_url",
    ):
        assert forbidden not in rendered


@pytest.mark.asyncio
async def test_v12_source_is_a_verified_noop(monkeypatch):
    state = _foundation_state()
    classifications = iter(("v1.2-target", "v1.2-target"))
    events = []

    async def classify(*_args):
        return next(classifications)

    async def load(*_args, **_kwargs):
        return state

    monkeypatch.setattr(reset_module, "_classify_reset_source", classify)
    monkeypatch.setattr(reset_module, "_load_v11_preserved_state", load)
    session = ResetFlowSession(events)
    report = await reset_module.reset_writer_core_data(
        session,
        database_name=DISPOSABLE,
        confirm_reset=DISPOSABLE,
        request=_request(),
        execute=True,
        output=lambda _value: None,
    )
    assert report.mode == "no-op"
    assert report.executed is False
    assert report.target_verified is True
    assert not any("DROP DATABASE" in sql for sql in events)


@pytest.mark.asyncio
async def test_v11_source_rebuilds_v12_and_preserves_locked_state(monkeypatch):
    state = _foundation_state()
    classifications = iter(("v1.1-source", "v1.1-source", "v1.2-target"))
    loads = []
    events = []

    async def classify(*_args):
        return next(classifications)

    async def load(*_args, **_kwargs):
        loads.append("load")
        return state

    async def initialize(*_args):
        events.append("initialize")

    async def insert(*_args, **_kwargs):
        events.append("insert")

    async def verify(*_args):
        events.append("verify")

    monkeypatch.setattr(reset_module, "_classify_reset_source", classify)
    monkeypatch.setattr(reset_module, "_load_v11_preserved_state", load)
    monkeypatch.setattr(reset_module, "_verify_reset_server_capabilities", verify)
    monkeypatch.setattr(reset_module, "initialize_database", initialize)
    monkeypatch.setattr(reset_module, "_insert_preserved_state", insert)
    monkeypatch.setattr(reset_module, "_verify_empty_tables", verify)
    session = ResetFlowSession(events)
    report = await reset_module.reset_writer_core_data(
        session,
        database_name=DISPOSABLE,
        confirm_reset=DISPOSABLE,
        request=_request(),
        execute=True,
        output=lambda _value: None,
        now_ms=lambda: 123,
    )
    assert report.executed is True
    assert report.source_kind == "v1.1-source"
    assert loads == ["load", "load", "load"]
    assert any(sql.startswith("DROP DATABASE") for sql in events)
    assert "initialize" in events
    assert "insert" in events


class ResetFlowSession:
    def __init__(self, events):
        self.events = events

    async def fetchone(self, sql, args=None):
        self.events.append(" ".join(sql.split()))
        if "GET_LOCK" in sql:
            return {"acquired": 1}
        if "RELEASE_LOCK" in sql:
            return {"released": 1}
        raise AssertionError(sql)

    async def execute(self, sql, args=None):
        self.events.append(" ".join(sql.split()))


@pytest.mark.asyncio
async def test_foundation_insert_uses_v12_project_columns_and_owned_foundation_order():
    state = _foundation_state()

    class InsertSession:
        def __init__(self):
            self.calls = []

        async def execute(self, sql, args=None):
            self.calls.append((" ".join(sql.split()), args))

    session = InsertSession()
    ids = iter(f"generated-{index}" for index in range(10))
    await reset_module._insert_preserved_state(
        session,
        state,
        now_ms=123,
        id_factory=lambda: next(ids),
    )
    project_sql, project_args = session.calls[0]
    assert (
        "archived_at, lifecycle_revision, created_at, updated_at"
        in project_sql
    )
    assert project_args[-4:] == (None, 0, 1, 1)
    insert_tables = [
        sql.split("INSERT INTO ", 1)[1].split()[0] for sql, _ in session.calls
    ]
    assert insert_tables == [
        "projects",
        "provider_profiles",
        "creative_seeds",
        "creative_seeds",
        "creative_seeds",
        "creative_seed_revisions",
        "creative_seed_revisions",
        "creative_seed_revisions",
        "creative_seed_heads",
        "creative_seed_heads",
        "creative_seed_heads",
        "project_selected_seeds",
        "project_model_binding_revisions",
        *("project_model_binding_items" for _ in TASK_KEYS),
        "project_model_binding_heads",
        "canon_revisions",
        "projection_heads",
        "project_contract_heads",
    ]


@pytest.mark.parametrize(
    "seed_titles",
    [(), ("a", "b"), ("a", "a", "c"), ("a", "b", "c", "d")],
)
def test_reset_request_requires_exactly_three_unique_seed_titles(seed_titles):
    with pytest.raises(ValueError, match="three unique"):
        _request(seed_titles=seed_titles)


@pytest.mark.asyncio
@pytest.mark.parametrize("execute", (False, True))
async def test_direct_core_call_cannot_authorize_product_database(execute):
    with pytest.raises(reset_module.ResetSafetyError, match="novel_creator"):
        await reset_module.reset_writer_core_data(
            ResetFlowSession([]),
            database_name="novel_creator",
            confirm_reset="novel_creator",
            request=_request(),
            execute=execute,
            allow_product_database=True,
        )


def test_cli_help_exits_zero_with_empty_stderr():
    result = subprocess.run(
        [sys.executable, "-m", "backend.scripts.reset_writer_core_data", "--help"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert result.stderr == ""
