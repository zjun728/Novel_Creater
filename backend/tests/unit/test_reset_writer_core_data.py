from __future__ import annotations

import inspect
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

import backend.scripts.reset_writer_core_data as reset_module
from backend import config as backend_config
from backend.config import LocalMySQLConfigError
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


def test_reset_source_contract_freezes_only_v11_and_current_v13():
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
    assert EXPECTED_SCHEMA_VERSION == "writer-core-v1.3.0"
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
            "writer-core-v1.3.0",
            manifest_hash,
            "v1.3-target",
        ),
    ],
)
async def test_reset_classifies_only_frozen_v11_or_current_v13(
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
        match="v1.1 source or v1.3 target",
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
        "revision": 0,
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
    assert not {
        "selectionRevisions",
        "bibleHeads",
        "applicationSettings",
    } & decoded["source"]["counts"].keys()
    assert set(decoded["source"]["verifiedEmptyTables"]) <= set(
        reset_module.V11_TABLE_NAMES
    )
    assert decoded["target"]["kind"] == "v1.3-target"
    assert decoded["target"]["schemaVersion"] == EXPECTED_SCHEMA_VERSION
    assert decoded["target"]["manifestHash"] == manifest_hash()
    assert decoded["target"]["expectedCounts"]["selectionRevisions"] == 1
    assert decoded["target"]["expectedCounts"]["bibleHeads"] == 1
    assert decoded["target"]["expectedCounts"]["applicationSettings"] == 1
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
async def test_v13_source_is_a_verified_noop(monkeypatch):
    state = _foundation_state()
    classifications = iter(("v1.3-target", "v1.3-target"))
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
async def test_v11_source_rebuilds_v13_and_preserves_locked_state(monkeypatch):
    state = _foundation_state()
    classifications = iter(("v1.1-source", "v1.1-source", "v1.3-target"))
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
async def test_foundation_insert_uses_v13_project_columns_and_owned_foundation_order():
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
        "project_seed_selection_revisions",
        "project_selected_seeds",
        "project_model_binding_revisions",
        *("project_model_binding_items" for _ in TASK_KEYS),
        "project_model_binding_heads",
        "canon_revisions",
        "projection_heads",
        "project_contract_heads",
        "project_bible_heads",
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


def test_destructive_cli_safety_regression_inventory_is_complete():
    required = {
        "test_cli_default_config_rejects_missing_password_before_connection",
        "test_cli_main_still_converts_runtime_failures_to_exit_one",
        "test_cli_requires_configured_database_to_match_explicit_target_before_connection",
        "test_execute_confirmation_mismatch_rejects_before_connection",
        "test_cli_product_dry_run_uses_read_authority",
        "test_cli_product_execute_uses_destructive_authority",
        "test_cli_dry_run_uses_injected_server_session_and_closes_it",
        "test_cli_combines_reset_and_connection_close_failures",
        "test_cli_connection_failure_never_runs_reset_or_close",
        "test_reset_connection_factory_combines_cursor_and_close_failures",
        "test_locked_recheck_runtime_failure_before_drop_is_not_partial",
        "test_drop_call_failure_is_partial_without_unowned_cleanup_drop",
        "test_failure_after_successful_destructive_drop_is_partial",
        "test_reset_rejects_unversioned_shape_before_preserve_reads_or_ddl",
        "test_product_cli_binds_exact_local_host_port_before_connect",
        "test_product_cli_rechecks_selected_database_and_server_identity_before_reset",
        "test_product_cli_four_tuple_authority_checks_identity_before_core",
    }
    present = {
        name
        for name, value in globals().items()
        if name.startswith("test_") and callable(value)
    }
    assert required <= present


@pytest.mark.asyncio
async def test_reset_rejects_unversioned_shape_before_preserve_reads_or_ddl():
    class UnversionedSession:
        def __init__(self):
            self.calls = []

        async def fetchall(self, sql, args=None):
            self.calls.append(("fetchall", sql, args))
            if "information_schema.TABLES" in sql:
                return [
                    {"TABLE_NAME": name}
                    for name in (
                        "projects",
                        "creative_seeds",
                        "provider_profiles",
                    )
                ]
            raise AssertionError("unversioned shape reached preserve reads")

        async def fetchone(self, sql, args=None):
            self.calls.append(("fetchone", sql, args))
            raise AssertionError("unversioned shape reached row reads")

        async def execute(self, sql, args=None):
            self.calls.append(("execute", sql, args))
            raise AssertionError("unversioned shape reached DDL/DML")

    session = UnversionedSession()

    with pytest.raises(
        reset_module.ResetValidationError,
        match="exact v1.1 source or v1.3 target",
    ):
        await reset_module.reset_writer_core_data(
            session,
            database_name=DISPOSABLE,
            confirm_reset=DISPOSABLE,
            request=_request(),
            execute=True,
            output=lambda _value: None,
        )

    assert len(session.calls) == 1
    assert "information_schema.TABLES" in session.calls[0][1]


@pytest.mark.asyncio
async def test_locked_recheck_runtime_failure_before_drop_is_not_partial(
    monkeypatch,
):
    state = _foundation_state()
    classifications = iter(
        ("v1.1-source", RuntimeError("LOCKED_RECHECK_SENTINEL"))
    )

    async def classify(_session, _database_name):
        outcome = next(classifications)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def load(*_args, **_kwargs):
        return state

    class Session:
        def __init__(self):
            self.execute_calls = []
            self.lock_released = False

        async def fetchone(self, sql, args=None):
            if "GET_LOCK" in sql:
                return {"acquired": 1}
            if "RELEASE_LOCK" in sql:
                self.lock_released = True
                return {"released": 1}
            raise AssertionError(sql)

        async def execute(self, sql, args=None):
            self.execute_calls.append((sql, args))
            raise AssertionError("DDL/DML ran before the locked recheck")

    monkeypatch.setattr(reset_module, "_classify_reset_source", classify)
    monkeypatch.setattr(reset_module, "_load_v11_preserved_state", load)
    session = Session()

    with pytest.raises(RuntimeError, match="LOCKED_RECHECK_SENTINEL"):
        await reset_module.reset_writer_core_data(
            session,
            database_name=DISPOSABLE,
            confirm_reset=DISPOSABLE,
            request=_request(),
            execute=True,
            output=lambda _value: None,
        )

    assert session.execute_calls == []
    assert session.lock_released is True


@pytest.mark.asyncio
async def test_drop_call_failure_is_partial_without_unowned_cleanup_drop(
    monkeypatch,
):
    state = _foundation_state()

    async def classify(_session, _database_name):
        return "v1.1-source"

    async def load(*_args, **_kwargs):
        return state

    async def verify_capabilities(_session):
        return "8.0-test"

    class Session:
        def __init__(self):
            self.execute_calls = []
            self.lock_released = False

        async def fetchone(self, sql, args=None):
            if "GET_LOCK" in sql:
                return {"acquired": 1}
            if "RELEASE_LOCK" in sql:
                self.lock_released = True
                return {"released": 1}
            raise AssertionError(sql)

        async def execute(self, sql, args=None):
            self.execute_calls.append(sql)
            if sql.startswith("DROP DATABASE `"):
                raise RuntimeError("DROP_OUTCOME_UNKNOWN_SENTINEL")
            raise AssertionError("DDL followed an outcome-unknown DROP")

    monkeypatch.setattr(reset_module, "_classify_reset_source", classify)
    monkeypatch.setattr(reset_module, "_load_v11_preserved_state", load)
    monkeypatch.setattr(
        reset_module,
        "_verify_reset_server_capabilities",
        verify_capabilities,
    )
    session = Session()

    with pytest.raises(
        reset_module.ResetPartialStateError,
        match="may remain",
    ) as raised:
        await reset_module.reset_writer_core_data(
            session,
            database_name=DISPOSABLE,
            confirm_reset=DISPOSABLE,
            request=_request(),
            execute=True,
            output=lambda _value: None,
        )

    assert "DROP_OUTCOME_UNKNOWN_SENTINEL" in repr(raised.value.__cause__)
    assert session.execute_calls == [f"DROP DATABASE `{DISPOSABLE}`"]
    assert session.lock_released is True


@pytest.mark.asyncio
async def test_failure_after_successful_destructive_drop_is_partial(
    monkeypatch,
):
    state = _foundation_state()

    async def classify(_session, _database_name):
        return "v1.1-source"

    async def load(*_args, **_kwargs):
        return state

    async def verify_capabilities(_session):
        return "8.0-test"

    class Session:
        def __init__(self):
            self.execute_calls = []

        async def fetchone(self, sql, args=None):
            if "GET_LOCK" in sql:
                return {"acquired": 1}
            if "RELEASE_LOCK" in sql:
                return {"released": 1}
            raise AssertionError(sql)

        async def execute(self, sql, args=None):
            self.execute_calls.append(sql)
            if sql.startswith("CREATE DATABASE"):
                raise RuntimeError("AFTER_DROP_SENTINEL")

    monkeypatch.setattr(reset_module, "_classify_reset_source", classify)
    monkeypatch.setattr(reset_module, "_load_v11_preserved_state", load)
    monkeypatch.setattr(
        reset_module,
        "_verify_reset_server_capabilities",
        verify_capabilities,
    )
    session = Session()

    with pytest.raises(
        reset_module.ResetPartialStateError,
        match="may remain",
    ) as raised:
        await reset_module.reset_writer_core_data(
            session,
            database_name=DISPOSABLE,
            confirm_reset=DISPOSABLE,
            request=_request(),
            execute=True,
            output=lambda _value: None,
        )

    assert "AFTER_DROP_SENTINEL" in repr(raised.value.__cause__)
    assert session.execute_calls[0].startswith("DROP DATABASE `")
    assert session.execute_calls[1].startswith("CREATE DATABASE `")
    assert session.execute_calls[2].startswith("DROP DATABASE IF EXISTS `")


def _cli_args(
    *,
    database=DISPOSABLE,
    confirm_reset=DISPOSABLE,
    execute=False,
):
    values = [
        "--database",
        database,
        "--confirm-reset",
        confirm_reset,
        "--project-title",
        "永乐大典",
        "--seed-title",
        "永乐长明",
        "--seed-title",
        "文渊山海",
        "--seed-title",
        "典镇山河",
        "--preferred-provider-name",
        "联通云",
        "--preferred-model",
        "deepseek-v4-flash",
    ]
    if execute:
        values.append("--execute")
    return values


def _product_cli_args(*, execute=False, host="127.0.0.1", port=3307):
    return [
        *_cli_args(
            database=reset_module.PRODUCT_DATABASE,
            confirm_reset=reset_module.PRODUCT_DATABASE,
            execute=execute,
        ),
        "--confirm-host",
        host,
        "--confirm-port",
        str(port),
    ]


class RecordingAdminSession:
    def __init__(self):
        self.calls = []
        self.closed = False

    async def close(self):
        self.calls.append(("close", None))
        self.closed = True


class ProductIdentitySession(RecordingAdminSession):
    def __init__(
        self,
        *,
        database="novel_creator",
        port=3307,
        identity="local-mysql8",
    ):
        super().__init__()
        self.database = database
        self.port = port
        self.identity = identity

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", " ".join(sql.split()), args))
        if "DATABASE()" in sql and "@@port" in sql and "@@server_uuid" in sql:
            return {
                "database_name": self.database,
                "server_port": self.port,
                "server_identity": self.identity,
            }
        raise AssertionError(f"unexpected product identity query: {sql}")


@pytest.mark.asyncio
async def test_cli_default_config_rejects_missing_password_before_connection(
    monkeypatch,
):
    called = False

    async def connection_factory(_connection_config):
        nonlocal called
        called = True
        raise AssertionError("must not connect")

    monkeypatch.setattr(
        backend_config,
        "MYSQL_CONFIG",
        dict(backend_config.MYSQL_CONFIG, password=None),
    )

    with pytest.raises(LocalMySQLConfigError, match="MYSQL_PASSWORD"):
        await reset_module.run_cli(
            _cli_args(),
            connection_factory=connection_factory,
        )

    assert called is False


def test_cli_main_still_converts_runtime_failures_to_exit_one(monkeypatch, capsys):
    def fail_run(coroutine):
        coroutine.close()
        raise RuntimeError("runtime sentinel")

    monkeypatch.setattr(reset_module.asyncio, "run", fail_run)

    assert reset_module.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Writer Core data reset failed.\n"


@pytest.mark.asyncio
async def test_cli_requires_configured_database_to_match_explicit_target_before_connection():
    connected = False

    async def connection_factory(_config):
        nonlocal connected
        connected = True
        raise AssertionError("must not connect")

    with pytest.raises(
        reset_module.ResetSafetyError,
        match="configured database",
    ):
        await reset_module.run_cli(
            _cli_args(),
            connection_config={
                "host": "127.0.0.1",
                "port": 3308,
                "user": "tester",
                "password": "secret",
                "db": "different_database",
            },
            connection_factory=connection_factory,
        )

    assert connected is False


@pytest.mark.asyncio
async def test_execute_confirmation_mismatch_rejects_before_connection():
    connected = False

    async def connection_factory(_config):
        nonlocal connected
        connected = True
        raise AssertionError("must not connect")

    with pytest.raises(reset_module.ResetSafetyError, match="confirmation"):
        await reset_module.run_cli(
            _cli_args(
                confirm_reset=(
                    "novel_creator_test_ffffffffffffffffffffffffffffffff"
                ),
                execute=True,
            ),
            connection_factory=connection_factory,
            connection_config={"password": "PASSWORD_SENTINEL", "db": DISPOSABLE},
        )

    assert connected is False


@pytest.mark.asyncio
async def test_cli_product_dry_run_uses_read_authority():
    session = ProductIdentitySession()
    captured = []

    async def connection_factory(_config):
        return session

    async def reset_function(admin_session, **kwargs):
        captured.append((admin_session, kwargs))

    result = await reset_module.run_cli(
        _product_cli_args(),
        connection_factory=connection_factory,
        connection_config={
            "host": "127.0.0.1",
            "port": 3307,
            "db": "novel_creator",
        },
        reset_function=reset_function,
    )

    assert result == 0
    assert session.closed is True
    assert len(captured) == 1
    assert captured[0][0] is session
    assert captured[0][1]["execute"] is False
    assert captured[0][1]["allow_product_database"] is True
    assert (
        captured[0][1]["_product_authority"]
        is reset_module._CLI_PRODUCT_READ_AUTHORITY
    )


@pytest.mark.asyncio
async def test_cli_product_execute_uses_destructive_authority():
    session = ProductIdentitySession()
    captured = []

    async def connection_factory(_config):
        return session

    async def reset_function(admin_session, **kwargs):
        captured.append((admin_session, kwargs))

    result = await reset_module.run_cli(
        _product_cli_args(execute=True),
        connection_factory=connection_factory,
        connection_config={
            "host": "127.0.0.1",
            "port": 3307,
            "db": "novel_creator",
        },
        reset_function=reset_function,
    )

    assert result == 0
    assert session.closed is True
    assert len(captured) == 1
    assert captured[0][0] is session
    assert captured[0][1]["execute"] is True
    assert captured[0][1]["allow_product_database"] is True
    assert (
        captured[0][1]["_product_authority"]
        is reset_module._CLI_PRODUCT_EXECUTE_AUTHORITY
    )


@pytest.mark.asyncio
async def test_cli_dry_run_uses_injected_server_session_and_closes_it():
    session = RecordingAdminSession()
    captured = []

    async def connection_factory(config):
        assert config == {"password": "PASSWORD_SENTINEL", "db": DISPOSABLE}
        return session

    async def reset_function(admin_session, **kwargs):
        captured.append((admin_session, kwargs))

    result = await reset_module.run_cli(
        _cli_args(),
        connection_factory=connection_factory,
        connection_config={"password": "PASSWORD_SENTINEL", "db": DISPOSABLE},
        reset_function=reset_function,
    )

    assert result == 0
    assert captured[0][0] is session
    assert captured[0][1]["execute"] is False
    assert captured[0][1]["allow_product_database"] is False
    assert session.closed is True


@pytest.mark.asyncio
async def test_cli_combines_reset_and_connection_close_failures():
    class CloseFailingSession(RecordingAdminSession):
        async def close(self):
            raise RuntimeError("close failed")

    async def connection_factory(_config):
        return CloseFailingSession()

    async def reset_function(_session, **_kwargs):
        raise RuntimeError("body failed")

    with pytest.raises(BaseExceptionGroup) as raised:
        await reset_module.run_cli(
            _cli_args(),
            connection_config={"db": DISPOSABLE},
            connection_factory=connection_factory,
            reset_function=reset_function,
        )

    assert [str(error) for error in raised.value.exceptions] == [
        "body failed",
        "close failed",
    ]


@pytest.mark.asyncio
async def test_cli_connection_failure_never_runs_reset_or_close():
    events = []

    async def connection_factory(_config):
        events.append("connect")
        raise RuntimeError("connect failed")

    async def reset_function(_session, **_kwargs):
        events.append("reset")

    with pytest.raises(RuntimeError, match="connect failed"):
        await reset_module.run_cli(
            _cli_args(),
            connection_config={"db": DISPOSABLE},
            connection_factory=connection_factory,
            reset_function=reset_function,
        )

    assert events == ["connect"]


@pytest.mark.asyncio
async def test_reset_connection_factory_combines_cursor_and_close_failures(
    monkeypatch,
):
    class FailingConnection:
        async def cursor(self, _cursor_type):
            raise RuntimeError("cursor failed")

        async def ensure_closed(self):
            raise RuntimeError("connection close failed")

    async def connect(**_kwargs):
        return FailingConnection()

    monkeypatch.setitem(
        sys.modules,
        "aiomysql",
        SimpleNamespace(connect=connect, DictCursor=object()),
    )

    with pytest.raises(BaseExceptionGroup) as raised:
        await reset_module._reset_connection_factory(
            {
                "host": "127.0.0.1",
                "port": 3307,
                "user": "tester",
                "password": "private",
                "db": DISPOSABLE,
            }
        )

    assert [str(error) for error in raised.value.exceptions] == [
        "cursor failed",
        "connection close failed",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config,confirm_host,confirm_port,match",
    [
        ({"host": "remote.example", "port": 3307}, "127.0.0.1", 3307, "loopback"),
        ({"host": "127.0.0.1", "port": 3306}, "127.0.0.1", 3307, "3307"),
        (
            {"host": "127.0.0.1", "port": 3307},
            "localhost",
            3307,
            "host confirmation",
        ),
        (
            {"host": "127.0.0.1", "port": 3307},
            "127.0.0.1",
            3306,
            "port confirmation",
        ),
    ],
)
async def test_product_cli_binds_exact_local_host_port_before_connect(
    config,
    confirm_host,
    confirm_port,
    match,
):
    connected = False

    async def connection_factory(_config):
        nonlocal connected
        connected = True
        raise AssertionError("must not connect")

    with pytest.raises(reset_module.ResetSafetyError, match=match):
        await reset_module.run_cli(
            _product_cli_args(host=confirm_host, port=confirm_port),
            connection_config={
                **config,
                "user": "root",
                "password": "PRIVATE",
                "db": "novel_creator",
            },
            connection_factory=connection_factory,
        )

    assert connected is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "database,port,identity,match",
    [
        ("other", 3307, "local-mysql8", "selected database"),
        ("novel_creator", 3306, "local-mysql8", "server port"),
        ("novel_creator", 3307, "", "server identity"),
    ],
)
async def test_product_cli_rechecks_selected_database_and_server_identity_before_reset(
    database,
    port,
    identity,
    match,
):
    session = ProductIdentitySession(
        database=database,
        port=port,
        identity=identity,
    )
    reset_called = False

    async def connection_factory(_config):
        return session

    async def reset_function(_session, **_kwargs):
        nonlocal reset_called
        reset_called = True

    with pytest.raises(reset_module.ResetSafetyError, match=match):
        await reset_module.run_cli(
            _product_cli_args(execute=True),
            connection_config={
                "host": "127.0.0.1",
                "port": 3307,
                "user": "root",
                "password": "PRIVATE",
                "db": "novel_creator",
            },
            connection_factory=connection_factory,
            reset_function=reset_function,
        )

    assert reset_called is False
    assert session.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("execute", (False, True))
async def test_product_cli_four_tuple_authority_checks_identity_before_core(
    execute,
):
    session = ProductIdentitySession()
    events = []

    async def connection_factory(config):
        events.append(("connect", dict(config)))
        return session

    async def reset_function(_session, **kwargs):
        events.append(("reset", kwargs))

    await reset_module.run_cli(
        _product_cli_args(execute=execute),
        connection_config={
            "host": "127.0.0.1",
            "port": 3307,
            "user": "root",
            "password": "PRIVATE",
            "db": "novel_creator",
        },
        connection_factory=connection_factory,
        reset_function=reset_function,
    )

    assert session.calls[0][0] == "fetchone"
    assert "DATABASE()" in session.calls[0][1]
    assert events[-1][0] == "reset"
    assert events[-1][1]["_product_authority"] is (
        reset_module._CLI_PRODUCT_EXECUTE_AUTHORITY
        if execute
        else reset_module._CLI_PRODUCT_READ_AUTHORITY
    )
    assert session.closed is True
