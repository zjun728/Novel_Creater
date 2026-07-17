from pathlib import Path
import json
import subprocess
import sys

import pytest

import backend.scripts.reset_writer_core_data as reset_module
from backend import config as backend_config
from backend.config import LocalMySQLConfigError
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.model_bindings import TASK_KEYS
from backend.domain.seeds import SeedPayload
from backend.scripts.reset_writer_core_data import (
    M1_MANIFEST_HASH,
    M1_SCHEMA_VERSION,
    M1_TABLE_NAMES,
    ResetPartialStateError,
    ResetRequest,
    ResetSafetyError,
    ResetValidationError,
    main,
    reset_writer_core_data,
    run_cli,
    _PreservedState,
    _insert_preserved_state,
    _map_m1_project,
    _map_m1_provider,
    _map_m1_seed,
    _map_v11_seed,
    _classify_reset_source,
    _report,
    format_reset_report,
)
from backend.schema_manifest import created_table_names, manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
DISPOSABLE = "novel_creator_test_0123456789abcdef0123456789abcdef"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.asyncio
async def test_cli_default_config_rejects_missing_password_before_connection(monkeypatch):
    called = False

    async def connection_factory(connection_config):
        nonlocal called
        called = True
        raise AssertionError("must not connect")

    monkeypatch.setattr(
        backend_config,
        "MYSQL_CONFIG",
        dict(backend_config.MYSQL_CONFIG, password=None),
    )

    with pytest.raises(LocalMySQLConfigError, match="MYSQL_PASSWORD"):
        await run_cli(
            [
                "--database", DISPOSABLE,
                "--confirm-reset", DISPOSABLE,
                "--project-title", "永乐大典",
                "--seed-title", "永乐长明",
                "--seed-title", "文渊山海",
                "--seed-title", "典镇山河",
                "--preferred-provider-name", "local",
                "--preferred-model", "local-model",
            ],
            connection_factory=connection_factory,
        )

    assert called is False


def test_cli_help_exits_zero_with_empty_stderr():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.scripts.reset_writer_core_data",
            "--help",
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert result.stderr == ""


def test_cli_main_still_converts_runtime_failures_to_exit_one(monkeypatch, capsys):
    def fail_run(coroutine):
        coroutine.close()
        raise RuntimeError("runtime sentinel")

    monkeypatch.setattr(
        "backend.scripts.reset_writer_core_data.asyncio.run",
        fail_run,
    )

    assert main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Writer Core data reset failed.\n"


class RecordingAdminSession:
    def __init__(self):
        self.calls = []
        self.closed = False

    async def fetchall(self, sql, args=None):
        self.calls.append(("fetchall", " ".join(sql.split()), args))
        if "information_schema.TABLES" in sql:
            return [
                {"TABLE_NAME": name}
                for name in ("projects", "creative_seeds", "provider_profiles")
            ]
        if ".`projects`" in sql:
            return [{
                "id": "project", "title": "永乐大典", "genre": "历史",
                "description": "DESCRIPTION_SENTINEL", "target_words": 1,
                "target_chapters": 1, "status": "active", "current_chapter_num": 17,
                "created_at": 1, "updated_at": 1,
            }]
        if ".`creative_seeds`" in sql:
            return [
                {
                    "id": str(index), "project_id": "project", "title": title,
                    "genre": "历史", "logline": title, "protagonist": "主角",
                    "desire": "目标", "core_conflict": "冲突",
                    "world_pressure": "压力", "opening_hook": "钩子",
                    "emotional_promise": "承诺", "differentiation": "差异",
                    "style_target": "风格", "source": "user", "risk_notes": None,
                    "ending_anchor": "结局", "status": "candidate", "created_at": 1,
                }
                for index, title in enumerate(("永乐长明", "文渊山海", "典镇山河"), 1)
            ]
        if ".`provider_profiles`" in sql:
            return [{
                "id": "provider", "name": "联通云", "provider_type": "test",
                "model": "deepseek-v4-flash", "base_url": "BASE_URL_SENTINEL",
                "api_key": "API_KEY_SENTINEL",
                "stream": 1, "max_context_tokens": 1, "max_output_tokens": 1,
                "temperature": 0.7, "top_p": 0.9, "supports_json": 1,
                "supports_streaming": 1, "notes": "NOTES_SENTINEL",
                "thinking": None, "created_at": 1, "updated_at": 1,
            }]
        raise AssertionError(f"unexpected SELECT: {sql}")

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", " ".join(sql.split()), args))
        if "collation_conflict" in sql:
            left, right = (value.casefold().rstrip(" ") for value in args)
            return {"collation_conflict": int(left == right)}
        raise AssertionError(f"unexpected SELECT: {sql}")

    async def execute(self, sql, args=None):
        self.calls.append(("execute", " ".join(sql.split()), args))
        raise AssertionError(f"dry-run executed SQL: {sql}")

    async def close(self):
        self.closed = True


def request(**changes):
    values = {
        "project_title": "永乐大典",
        "seed_titles": ("永乐长明", "文渊山海", "典镇山河"),
        "preferred_provider_name": "联通云",
        "preferred_model": "deepseek-v4-flash",
    }
    values.update(changes)
    return ResetRequest(**values)


def _seed_payload(title):
    return SeedPayload(
        title=title,
        genre="历史穿越",
        logline=f"{title}的测试梗概",
        protagonist="测试主角",
        desire="完成目标",
        coreConflict="守住唯一事实源",
        worldPressure="时间窗口收紧",
        openingHook="一页异常典籍出现",
        differentiation="只用于重建测试",
    )


M1_PREMISE_FIELDS = (
    "genre", "logline", "protagonist", "desire", "coreConflict",
    "worldPressure", "openingHook", "emotionalPromise",
    "differentiation", "styleTarget", "source", "riskNotes",
    "endingAnchor",
)


def _m1_premise(title):
    return {
        "genre": "历史穿越",
        "logline": f"{title}的测试梗概",
        "protagonist": "测试主角",
        "desire": "完成目标",
        "coreConflict": "守住唯一事实源",
        "worldPressure": "时间窗口收紧",
        "openingHook": "一页异常典籍出现",
        "emotionalPromise": "读者看见普通人逐步改变时代",
        "differentiation": "只用于重建测试",
        "styleTarget": "通俗、具体、以故事推进",
        "source": "user",
        "riskNotes": "避免设定堆砌",
        "endingAnchor": "",
    }


def _m1_seed_row(title="典镇山河", **changes):
    premise = _m1_premise(title)
    row = {
        "id": "seed",
        "project_id": "project",
        "title": title,
        "premise_json": canonical_json(premise),
        "content_hash": canonical_hash({"title": title, "premise": premise}),
        "status": "selected" if title == "典镇山河" else "candidate",
        "created_at": 1,
    }
    row.update(changes)
    return row


def _foundation_state_values():
    project = _map_m1_project({
        "id": "project", "title": "永乐大典", "genre": "历史穿越",
        "description": "DESCRIPTION_SENTINEL", "target_words": 1,
        "target_chapters": 1, "status": "drafting", "current_chapter": 0,
        "created_at": 1, "updated_at": 1,
    })
    seeds = []
    for index, title in enumerate(("永乐长明", "文渊山海", "典镇山河"), 1):
        payload = _seed_payload(title)
        seeds.append(_map_v11_seed({
            "id": f"seed-{index}", "project_id": "project", "title": title,
            "premise_json": canonical_json(payload),
            "content_hash": canonical_hash(payload), "status": "candidate",
            "created_at": 1,
        }, "project"))
    provider = _map_m1_provider({
        "id": "provider", "name": "联通云",
        "provider_type": "openai-compatible",
        "model_name": "deepseek-v4-flash", "base_url": "BASE_URL_SENTINEL",
        "api_key": "API_KEY_SENTINEL", "enabled": 1, "sort_order": 0,
        "stream": 1, "max_context_tokens": 1, "max_output_tokens": 1,
        "temperature": "0.800", "top_p": "0.900", "supports_json": 1,
        "supports_streaming": 1, "notes": "NOTES_SENTINEL", "thinking": None,
        "created_at": 1, "updated_at": 1,
    })
    return project, tuple(seeds), provider


def test_m2_provider_mapping_preserves_actual_lifecycle_and_deletion_state():
    row = {
        "id": "provider", "name": "联通云",
        "provider_type": "openai-compatible",
        "model_name": "deepseek-v4-flash", "base_url": "BASE_URL_SENTINEL",
        "api_key": "API_KEY_SENTINEL", "enabled": 1, "sort_order": 0,
        "stream": 1, "max_context_tokens": 1, "max_output_tokens": 1,
        "temperature": "0.800", "top_p": "0.900", "supports_json": 1,
        "supports_streaming": 1, "notes": "NOTES_SENTINEL", "thinking": None,
        "lifecycle_status": "retired", "deleted_at": 123,
        "created_at": 1, "updated_at": 1,
    }

    mapped = _map_m1_provider(row)

    assert mapped["lifecycle_status"] == "retired"
    assert mapped["deleted_at"] == 123


class InventorySession:
    def __init__(self, tables, version, manifest):
        self.tables = tuple(tables)
        self.version = version
        self.manifest = manifest
        self.calls = []

    async def fetchall(self, sql, args=None):
        self.calls.append(("fetchall", " ".join(sql.split()), args))
        assert "information_schema.TABLES" in sql
        return [{"TABLE_NAME": table} for table in self.tables]

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", " ".join(sql.split()), args))
        assert "schema_metadata" in sql
        return {"schema_version": self.version, "manifest_hash": self.manifest}


def test_reset_source_contract_freezes_m1_and_current_manifest_inventory():
    assert M1_SCHEMA_VERSION == "writer-core-v1.0.0"
    assert M1_MANIFEST_HASH == "0697b6da4826b98c8e502ff7ad68a61b51fe7037b167b6d8175ae9d78dcff826"
    assert len(M1_TABLE_NAMES) == 34
    assert len(set(M1_TABLE_NAMES)) == 34
    assert M1_TABLE_NAMES == (
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
    assert len(created_table_names()) == 49
    assert manifest_hash() == "cf993ccf7f000935aaa5777bfb9adda4cd6cbd47cb4f83be5d073d7d3e6b30c5"


def test_reset_receipt_is_one_strict_json_document_and_cannot_forge_fields():
    project, seeds, provider = _foundation_state_values()
    provider = {**provider, "name": "safe-name\napi_key=forged"}

    rendered = format_reset_report(
        _report(
            DISPOSABLE,
            _PreservedState(project, seeds, (provider,), provider),
            executed=False,
            source_kind="m1-v1.0",
        )
    )
    decoded = json.loads(rendered)
    assert decoded["mode"] == "dry-run"
    assert "counts" not in decoded
    assert "tables" not in decoded
    assert decoded["source"] == {
        "kind": "m1-v1.0",
        "schemaVersion": M1_SCHEMA_VERSION,
        "manifestHash": M1_MANIFEST_HASH,
        "tables": list(M1_TABLE_NAMES),
        "counts": {
            "projects": 1,
            "seeds": 3,
            "selectedSeeds": 1,
            "providers": 1,
            "taskModelBindings": 1,
            "taskModelBindingItems": len(TASK_KEYS),
            "canonRevisions": 1,
            "projectionHeads": 1,
        },
        "verifiedEmptyTables": [
            table
            for table in M1_TABLE_NAMES
            if table not in {
                "schema_metadata", "projects", "creative_seeds",
                "project_selected_seeds", "provider_profiles",
                "task_model_bindings", "task_model_binding_items",
                "canon_revisions", "projection_heads",
            }
        ],
    }
    assert decoded["target"] == {
        "kind": "m2-v1.1",
        "schemaVersion": EXPECTED_SCHEMA_VERSION,
        "manifestHash": manifest_hash(),
        "tables": list(created_table_names()),
        "expectedCounts": {
            "projects": 1,
            "seeds": 3,
            "selectedSeeds": 1,
            "providers": 1,
            "seedRevisions": 3,
            "seedHeads": 3,
            "bindingRevisions": 1,
            "bindingItems": len(TASK_KEYS),
            "bindingHeads": 1,
            "canonRevisions": 1,
            "projectionHeads": 1,
            "contractHeads": 1,
        },
        "expectedEmptyTables": list(reset_module.VERIFIED_EMPTY_TABLES),
        "verified": False,
    }
    assert decoded["providers"][0]["name"] == "safe-name\napi_key=forged"
    assert rendered.count("\n") == 0
    for forbidden in ("base_url", "api_key\":", "notes", "thinking", "dsn"):
        assert forbidden not in rendered.lower()


def test_m2_noop_receipt_labels_current_source_and_verified_target():
    project, seeds, provider = _foundation_state_values()
    decoded = json.loads(format_reset_report(_report(
        DISPOSABLE,
        _PreservedState(project, seeds, (provider,), provider),
        executed=False,
        mode="no-op",
        source_kind="m2-v1.1",
    )))

    assert decoded["mode"] == "no-op"
    assert decoded["source"]["kind"] == "m2-v1.1"
    assert decoded["source"]["schemaVersion"] == EXPECTED_SCHEMA_VERSION
    assert decoded["source"]["manifestHash"] == manifest_hash()
    assert decoded["source"]["tables"] == list(created_table_names())
    assert decoded["source"]["counts"] == decoded["target"]["expectedCounts"]
    assert decoded["source"]["verifiedEmptyTables"] == list(
        reset_module.VERIFIED_EMPTY_TABLES
    )
    assert decoded["target"]["verified"] is True


@pytest.mark.asyncio
async def test_locked_recheck_runtime_failure_before_drop_is_not_partial(monkeypatch):
    project, seeds, provider = _foundation_state_values()
    state = _PreservedState(project, seeds, (provider,), provider)
    classifications = iter(("m1-v1.0", RuntimeError("LOCKED_RECHECK_SENTINEL")))

    async def classify(_session, _database_name):
        outcome = next(classifications)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def load(_session, _database_name, _request):
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
            raise AssertionError("DDL/DML must not run before locked recheck succeeds")

    monkeypatch.setattr(reset_module, "_classify_reset_source", classify)
    monkeypatch.setattr(reset_module, "_load_m1_preserved_state", load)
    session = Session()

    with pytest.raises(RuntimeError, match="LOCKED_RECHECK_SENTINEL"):
        await reset_writer_core_data(
            session,
            database_name=DISPOSABLE,
            confirm_reset=DISPOSABLE,
            request=request(),
            execute=True,
            output=lambda _value: None,
        )

    assert session.execute_calls == []
    assert session.lock_released is True


@pytest.mark.asyncio
async def test_drop_call_failure_is_partial_without_unowned_cleanup_drop(monkeypatch):
    project, seeds, provider = _foundation_state_values()
    state = _PreservedState(project, seeds, (provider,), provider)

    async def classify(_session, _database_name):
        return "m1-v1.0"

    async def load(_session, _database_name, _request):
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
            raise AssertionError("No DDL may follow an outcome-unknown DROP")

    monkeypatch.setattr(reset_module, "_classify_reset_source", classify)
    monkeypatch.setattr(reset_module, "_load_m1_preserved_state", load)
    monkeypatch.setattr(reset_module, "_verify_reset_server_capabilities", verify_capabilities)
    session = Session()

    with pytest.raises(ResetPartialStateError, match="may remain") as raised:
        await reset_writer_core_data(
            session,
            database_name=DISPOSABLE,
            confirm_reset=DISPOSABLE,
            request=request(),
            execute=True,
            output=lambda _value: None,
        )

    assert "DROP_OUTCOME_UNKNOWN_SENTINEL" in repr(raised.value.__cause__)
    assert session.execute_calls == [f"DROP DATABASE `{DISPOSABLE}`"]
    assert session.lock_released is True


@pytest.mark.asyncio
async def test_failure_after_successful_destructive_drop_is_partial(monkeypatch):
    project, seeds, provider = _foundation_state_values()
    state = _PreservedState(project, seeds, (provider,), provider)

    async def classify(_session, _database_name):
        return "m1-v1.0"

    async def load(_session, _database_name, _request):
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
    monkeypatch.setattr(reset_module, "_load_m1_preserved_state", load)
    monkeypatch.setattr(reset_module, "_verify_reset_server_capabilities", verify_capabilities)
    session = Session()

    with pytest.raises(ResetPartialStateError, match="may remain") as raised:
        await reset_writer_core_data(
            session,
            database_name=DISPOSABLE,
            confirm_reset=DISPOSABLE,
            request=request(),
            execute=True,
            output=lambda _value: None,
        )

    assert "AFTER_DROP_SENTINEL" in repr(raised.value.__cause__)
    assert session.execute_calls[0].startswith("DROP DATABASE `")
    assert session.execute_calls[1].startswith("CREATE DATABASE `")
    assert session.execute_calls[2].startswith("DROP DATABASE IF EXISTS `")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tables,version,manifest,expected",
    [
        (M1_TABLE_NAMES, M1_SCHEMA_VERSION, M1_MANIFEST_HASH, "m1-v1.0"),
        (created_table_names(), EXPECTED_SCHEMA_VERSION, manifest_hash(), "m2-v1.1"),
    ],
)
async def test_reset_classifies_only_exact_m1_or_current_inventory(
    tables, version, manifest, expected
):
    session = InventorySession(tables, version, manifest)
    assert await _classify_reset_source(session, DISPOSABLE) == expected
    assert session.calls[0][2] == (DISPOSABLE,)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tables,version,manifest",
    [
        (M1_TABLE_NAMES[:-1], M1_SCHEMA_VERSION, M1_MANIFEST_HASH),
        ((*M1_TABLE_NAMES, "unexpected_table"), M1_SCHEMA_VERSION, M1_MANIFEST_HASH),
        (M1_TABLE_NAMES, EXPECTED_SCHEMA_VERSION, M1_MANIFEST_HASH),
        (created_table_names(), EXPECTED_SCHEMA_VERSION, "0" * 64),
    ],
)
async def test_reset_rejects_mixed_or_tampered_inventory_before_ddl(
    tables, version, manifest
):
    session = InventorySession(tables, version, manifest)
    with pytest.raises(ResetValidationError, match="exact M1 v1.0 or M2 v1.1"):
        await _classify_reset_source(session, DISPOSABLE)
    assert not any(call[0] == "execute" for call in session.calls)


@pytest.mark.asyncio
async def test_reset_rejects_unversioned_legacy_shape_before_any_preserve_read_or_ddl():
    class UnversionedSession:
        def __init__(self):
            self.calls = []

        async def fetchall(self, sql, args=None):
            self.calls.append(("fetchall", sql, args))
            if "information_schema.TABLES" in sql:
                return [
                    {"TABLE_NAME": name}
                    for name in ("projects", "creative_seeds", "provider_profiles")
                ]
            raise AssertionError("unversioned shape reached preserve reads")

        async def fetchone(self, sql, args=None):
            self.calls.append(("fetchone", sql, args))
            raise AssertionError("unversioned shape reached row reads")

        async def execute(self, sql, args=None):
            self.calls.append(("execute", sql, args))
            raise AssertionError("unversioned shape reached DDL/DML")

    session = UnversionedSession()
    with pytest.raises(ResetValidationError, match="exact M1 v1.0 or M2 v1.1"):
        await reset_writer_core_data(
            session,
            database_name=DISPOSABLE,
            confirm_reset=DISPOSABLE,
            request=request(),
            execute=True,
            output=lambda _value: None,
        )
    assert len(session.calls) == 1
    assert "information_schema.TABLES" in session.calls[0][1]


@pytest.mark.asyncio
async def test_cli_requires_configured_database_to_match_explicit_target_before_connection():
    connected = False

    async def connection_factory(_config):
        nonlocal connected
        connected = True

    with pytest.raises(ResetSafetyError, match="configured database"):
        await run_cli(
            [
                "--database", DISPOSABLE,
                "--confirm-reset", DISPOSABLE,
                "--project-title", "永乐大典",
                "--seed-title", "永乐长明",
                "--seed-title", "文渊山海",
                "--seed-title", "典镇山河",
                "--preferred-provider-name", "联通云",
                "--preferred-model", "deepseek-v4-flash",
            ],
            connection_config={
                "host": "127.0.0.1", "port": 3308, "user": "tester",
                "password": "secret", "db": "different_database",
            },
            connection_factory=connection_factory,
        )
    assert not connected


def test_m1_seed_mapping_converts_exact_historical_envelope_to_current_payload():
    row = _m1_seed_row()
    assert set(json.loads(row["premise_json"])) == set(M1_PREMISE_FIELDS)

    mapped = _map_m1_seed(row, "project")

    expected = SeedPayload(
        title="典镇山河",
        **{
            field: _m1_premise("典镇山河")[field]
            for field in (
                "genre", "logline", "protagonist", "desire",
                "coreConflict", "worldPressure", "openingHook",
                "differentiation",
            )
        },
    )
    assert mapped["payload_json"] == canonical_json(expected)
    assert mapped["content_hash"] == canonical_hash(expected)
    assert mapped["status"] == "candidate"
    assert set(json.loads(mapped["payload_json"])) == set(SeedPayload.model_fields)
    assert not set(json.loads(mapped["payload_json"])) & {
        "emotionalPromise", "styleTarget", "source", "riskNotes",
        "endingAnchor",
    }


@pytest.mark.parametrize(
    "mutate",
    (
        lambda premise: premise.pop("riskNotes"),
        lambda premise: premise.__setitem__("legacyExtra", "forbidden"),
        lambda premise: premise.__setitem__("source", 1),
        lambda premise: premise.__setitem__("openingHook", ""),
    ),
)
def test_m1_seed_mapping_rejects_non_exact_or_invalid_historical_premise(mutate):
    premise = _m1_premise("典镇山河")
    mutate(premise)
    row = _m1_seed_row(
        premise_json=canonical_json(premise),
        content_hash=canonical_hash({
            "title": "典镇山河",
            "premise": premise,
        }),
    )

    with pytest.raises(ResetValidationError):
        _map_m1_seed(row, "project")


def test_m1_seed_mapping_rejects_historical_envelope_hash_mismatch():
    with pytest.raises(ResetValidationError, match="content_hash"):
        _map_m1_seed(_m1_seed_row(content_hash="0" * 64), "project")


@pytest.mark.parametrize("premise_json", ("[]", "null"))
def test_m1_seed_mapping_rejects_non_object_json(premise_json):
    with pytest.raises(ResetValidationError, match="historical object"):
        _map_m1_seed(
            _m1_seed_row(
                premise_json=premise_json,
                content_hash="0" * 64,
            ),
            "project",
        )


def test_m1_seed_mapping_rejects_oversized_retained_field():
    premise = _m1_premise("典镇山河")
    premise["openingHook"] = "x" * 2001
    row = _m1_seed_row(
        premise_json=canonical_json(premise),
        content_hash=canonical_hash({
            "title": "典镇山河",
            "premise": premise,
        }),
    )
    with pytest.raises(ResetValidationError, match="current SeedPayload"):
        _map_m1_seed(row, "project")


def test_m1_seed_mapping_rejects_title_outside_historical_contract():
    with pytest.raises(ResetValidationError, match="title/status contract"):
        _map_m1_seed(
            _m1_seed_row("陌生种子", status="candidate"),
            "project",
        )


@pytest.mark.parametrize(
    ("title", "status"),
    (
        ("典镇山河", "candidate"),
        ("永乐长明", "selected"),
        ("文渊山海", "archived"),
    ),
)
def test_m1_seed_mapping_rejects_wrong_historical_status(title, status):
    with pytest.raises(ResetValidationError, match="status"):
        _map_m1_seed(_m1_seed_row(title, status=status), "project")


def test_v11_seed_mapping_accepts_only_current_payload_and_candidate_status():
    payload = _seed_payload("典镇山河")
    current = {
        "id": "seed",
        "project_id": "project",
        "title": payload.title,
        "premise_json": canonical_json(payload),
        "content_hash": canonical_hash(payload),
        "status": "candidate",
        "created_at": 1,
    }

    mapped = _map_v11_seed(current, "project")
    assert mapped["payload_json"] == canonical_json(payload)

    legacy_premise = _m1_premise("典镇山河")
    legacy = _m1_seed_row(
        premise_json=canonical_json(legacy_premise),
        content_hash=canonical_hash(legacy_premise),
        status="candidate",
    )
    with pytest.raises(ResetValidationError, match="current SeedPayload"):
        _map_v11_seed(legacy, "project")
    with pytest.raises(ResetValidationError, match="candidates"):
        _map_v11_seed({**current, "status": "selected"}, "project")


def test_v11_seed_mapping_rejects_current_content_hash_mismatch():
    payload = _seed_payload("典镇山河")
    current = {
        "id": "seed",
        "project_id": "project",
        "title": payload.title,
        "premise_json": canonical_json(payload),
        "content_hash": "0" * 64,
        "status": "candidate",
        "created_at": 1,
    }

    with pytest.raises(ResetValidationError, match="content_hash"):
        _map_v11_seed(current, "project")


@pytest.mark.asyncio
async def test_foundation_insert_order_uses_revisioned_seed_binding_and_contract_heads():
    project, seeds, provider = _foundation_state_values()
    state = _PreservedState(project, seeds, (provider,), provider)

    class InsertSession:
        def __init__(self):
            self.calls = []

        async def execute(self, sql, args=None):
            self.calls.append((" ".join(sql.split()), args))

    session = InsertSession()
    ids = iter(f"generated-{index}" for index in range(10))
    await _insert_preserved_state(
        session, state, now_ms=123, id_factory=lambda: next(ids)
    )

    insert_tables = [sql.split("INSERT INTO ", 1)[1].split()[0] for sql, _ in session.calls]
    assert insert_tables == [
        "projects",
        "provider_profiles",
        "creative_seeds", "creative_seeds", "creative_seeds",
        "creative_seed_revisions", "creative_seed_revisions", "creative_seed_revisions",
        "creative_seed_heads", "creative_seed_heads", "creative_seed_heads",
        "project_selected_seeds",
        "project_model_binding_revisions",
        *("project_model_binding_items" for _ in TASK_KEYS),
        "project_model_binding_heads",
        "canon_revisions",
        "projection_heads",
        "project_contract_heads",
    ]
    rendered_sql = "\n".join(sql for sql, _ in session.calls)
    assert "task_model_bindings" not in rendered_sql
    assert "task_model_binding_items" not in rendered_sql


@pytest.mark.parametrize("seed_titles", [(), ("a", "b"), ("a", "a", "c"), ("a", "b", "c", "d")])
def test_reset_request_requires_exactly_three_unique_seed_titles(seed_titles):
    with pytest.raises(ValueError, match="three unique"):
        request(seed_titles=seed_titles)


@pytest.mark.asyncio
async def test_execute_confirmation_mismatch_rejects_before_connection():
    called = False

    async def connection_factory(config):
        nonlocal called
        called = True
        return RecordingAdminSession()

    with pytest.raises(ResetSafetyError, match="confirmation"):
        await run_cli(
            [
                "--database", DISPOSABLE,
                "--confirm-reset", "novel_creator_test_ffffffffffffffffffffffffffffffff",
                "--project-title", "永乐大典",
                "--seed-title", "永乐长明",
                "--seed-title", "文渊山海",
                "--seed-title", "典镇山河",
                "--preferred-provider-name", "联通云",
                "--preferred-model", "deepseek-v4-flash",
                "--execute",
            ],
            connection_factory=connection_factory,
            connection_config={"password": "PASSWORD_SENTINEL", "db": DISPOSABLE},
        )

    assert called is False


@pytest.mark.asyncio
@pytest.mark.parametrize("execute", (False, True))
async def test_direct_core_call_cannot_authorize_product_database(execute):
    session = RecordingAdminSession()

    with pytest.raises(ResetSafetyError, match="novel_creator"):
        await reset_writer_core_data(
            session,
            database_name="novel_creator",
            confirm_reset="novel_creator",
            request=request(),
            execute=execute,
            allow_product_database=True,
        )

    assert session.calls == []


@pytest.mark.asyncio
async def test_cli_product_dry_run_connects_read_only_and_reports_without_ddl():
    session = ProductIdentitySession()
    captured = []

    async def connection_factory(config):
        return session

    async def reset_function(admin_session, **kwargs):
        captured.append((admin_session, kwargs))

    result = await run_cli(
        _product_cli_args(),
        connection_factory=connection_factory,
        connection_config={
            "host": "127.0.0.1", "port": 3307, "db": "novel_creator",
        },
        reset_function=reset_function,
    )

    assert result == 0
    assert session.closed
    assert captured[0][1]["execute"] is False
    assert captured[0][1]["allow_product_database"] is True


@pytest.mark.asyncio
async def test_only_matching_cli_execute_authorizes_product_core_flag():
    session = ProductIdentitySession()
    captured = []

    async def connection_factory(config):
        return session

    async def reset_function(admin_session, **kwargs):
        captured.append((admin_session, kwargs))

    result = await run_cli(
        _product_cli_args(execute=True),
        connection_factory=connection_factory,
        connection_config={
            "host": "127.0.0.1", "port": 3307, "db": "novel_creator",
        },
        reset_function=reset_function,
    )

    assert result == 0
    assert session.closed
    assert len(captured) == 1
    assert captured[0][0] is session
    assert captured[0][1]["allow_product_database"] is True


@pytest.mark.asyncio
async def test_cli_dry_run_uses_injected_server_session_and_closes_it():
    session = RecordingAdminSession()
    output = []
    called = False

    async def connection_factory(config):
        assert config == {"password": "PASSWORD_SENTINEL", "db": DISPOSABLE}
        return session

    async def reset_function(_session, **_kwargs):
        nonlocal called
        called = True

    result = await run_cli(
        [
            "--database", DISPOSABLE,
            "--confirm-reset", DISPOSABLE,
            "--project-title", "永乐大典",
            "--seed-title", "永乐长明",
            "--seed-title", "文渊山海",
            "--seed-title", "典镇山河",
            "--preferred-provider-name", "联通云",
            "--preferred-model", "deepseek-v4-flash",
        ],
        connection_factory=connection_factory,
        connection_config={"password": "PASSWORD_SENTINEL", "db": DISPOSABLE},
        output=output.append,
        reset_function=reset_function,
    )

    assert result == 0
    assert called
    assert session.closed
    assert "PASSWORD_SENTINEL" not in "\n".join(output)


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
        await run_cli(
            [
                "--database", DISPOSABLE,
                "--confirm-reset", DISPOSABLE,
                "--project-title", "永乐大典",
                "--seed-title", "永乐长明",
                "--seed-title", "文渊山海",
                "--seed-title", "典镇山河",
                "--preferred-provider-name", "联通云",
                "--preferred-model", "deepseek-v4-flash",
            ],
            connection_config={"db": DISPOSABLE},
            connection_factory=connection_factory,
            reset_function=reset_function,
        )
    assert [str(error) for error in raised.value.exceptions] == [
        "body failed", "close failed",
    ]


def _product_cli_args(*, execute=False, host="127.0.0.1", port=3307):
    values = [
        "--database", "novel_creator",
        "--confirm-reset", "novel_creator",
        "--confirm-host", host,
        "--confirm-port", str(port),
        "--project-title", "永乐大典",
        "--seed-title", "永乐长明",
        "--seed-title", "文渊山海",
        "--seed-title", "典镇山河",
        "--preferred-provider-name", "联通云",
        "--preferred-model", "deepseek-v4-flash",
    ]
    if execute:
        values.append("--execute")
    return values


class ProductIdentitySession:
    def __init__(self, *, database="novel_creator", port=3307, identity="local-mysql8"):
        self.database = database
        self.port = port
        self.identity = identity
        self.calls = []
        self.closed = False

    async def fetchone(self, sql, args=None):
        self.calls.append((sql, args))
        if "DATABASE()" in sql and "@@port" in sql:
            return {
                "database_name": self.database,
                "server_port": self.port,
                "server_identity": self.identity,
            }
        raise AssertionError(f"unexpected product identity query: {sql}")

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config,confirm_host,confirm_port,match",
    [
        ({"host": "remote.example", "port": 3307}, "127.0.0.1", 3307, "loopback"),
        ({"host": "127.0.0.1", "port": 3306}, "127.0.0.1", 3307, "3307"),
        ({"host": "127.0.0.1", "port": 3307}, "localhost", 3307, "host confirmation"),
        ({"host": "127.0.0.1", "port": 3307}, "127.0.0.1", 3306, "port confirmation"),
    ],
)
async def test_product_cli_binds_exact_local_host_port_before_connect(
    config, confirm_host, confirm_port, match,
):
    connected = False

    async def connection_factory(_config):
        nonlocal connected
        connected = True
        return ProductIdentitySession()

    with pytest.raises(ResetSafetyError, match=match):
        await run_cli(
            _product_cli_args(host=confirm_host, port=confirm_port),
            connection_config={
                **config, "user": "root", "password": "PRIVATE", "db": "novel_creator",
            },
            connection_factory=connection_factory,
            reset_function=lambda *_args, **_kwargs: None,
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
    database, port, identity, match,
):
    session = ProductIdentitySession(database=database, port=port, identity=identity)
    reset_called = False

    async def connection_factory(_config):
        return session

    async def reset_function(_session, **_kwargs):
        nonlocal reset_called
        reset_called = True

    with pytest.raises(ResetSafetyError, match=match):
        await run_cli(
            _product_cli_args(execute=True),
            connection_config={
                "host": "127.0.0.1", "port": 3307, "user": "root",
                "password": "PRIVATE", "db": "novel_creator",
            },
            connection_factory=connection_factory,
            reset_function=reset_function,
        )
    assert reset_called is False
    assert session.closed is True

@pytest.mark.asyncio
@pytest.mark.parametrize("execute", [False, True])
async def test_product_cli_four_tuple_authority_runs_identity_check_before_core(execute):
    session = ProductIdentitySession()
    events = []

    async def connection_factory(config):
        events.append(("connect", dict(config)))
        return session

    async def reset_function(_session, **kwargs):
        events.append(("reset", kwargs))

    await run_cli(
        _product_cli_args(execute=execute),
        connection_config={
            "host": "127.0.0.1", "port": 3307, "user": "root",
            "password": "PRIVATE", "db": "novel_creator",
        },
        connection_factory=connection_factory,
        reset_function=reset_function,
    )
    assert "DATABASE()" in session.calls[0][0]
    assert events[-1][0] == "reset"
    assert events[-1][1]["allow_product_database"] is True
    assert session.closed is True
