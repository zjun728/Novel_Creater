from pathlib import Path
import json
import subprocess
import sys

import pytest

from backend import config as backend_config
from backend.config import LocalMySQLConfigError
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.model_bindings import TASK_KEYS
from backend.domain.seeds import SeedPayload
from backend.scripts.reset_writer_core_data import (
    M1_MANIFEST_HASH,
    M1_SCHEMA_VERSION,
    M1_TABLE_NAMES,
    RESET_LOCK_NAME,
    _recover_failed_commit,
    ResetPartialStateError,
    ResetRequest,
    ResetSafetyError,
    ResetValidationError,
    main,
    reset_writer_core_data,
    run_cli,
    _PreservedState,
    _insert_preserved_state,
    _map_project,
    _map_provider,
    _map_seed,
    _classify_reset_source,
    format_reset_report,
)
from backend.schema_manifest import created_table_names, manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from backend.tests.support.legacy_writer_core import (
    LEGACY_BASELINE_COMMIT,
    PROJECTS_DDL,
    PROVIDERS_DDL,
    SEEDS_DDL,
)


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
    source = RecordingAdminSession()
    project = _map_project(__import__("asyncio").run(source.fetchall("FROM .`projects`"))[0])
    seeds = tuple(
        _map_seed(row, project["id"])
        for row in __import__("asyncio").run(source.fetchall("FROM .`creative_seeds`"))
    )
    provider = _map_provider(
        {
            **__import__("asyncio").run(source.fetchall("FROM .`provider_profiles`"))[0],
            "name": "safe-name\napi_key=forged",
        },
        0,
    )
    from backend.scripts.reset_writer_core_data import _report

    rendered = format_reset_report(
        _report(
            DISPOSABLE,
            _PreservedState(project, seeds, (provider,), provider),
            executed=False,
        )
    )
    decoded = json.loads(rendered)
    assert decoded["mode"] == "dry-run"
    assert decoded["providers"][0]["name"] == "safe-name\napi_key=forged"
    assert rendered.count("\n") == 0
    for forbidden in ("base_url", "api_key\":", "notes", "thinking", "dsn"):
        assert forbidden not in rendered.lower()


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


def test_seed_mapping_builds_exact_immutable_nine_field_payload():
    legacy = RecordingAdminSession()
    row = next(iter(__import__("asyncio").run(legacy.fetchall("FROM .`creative_seeds`"))))

    mapped = _map_seed(row, "project")
    payload = SeedPayload(
        title=row["title"],
        genre=row["genre"],
        logline=row["logline"],
        protagonist=row["protagonist"],
        desire=row["desire"],
        coreConflict=row["core_conflict"],
        worldPressure=row["world_pressure"],
        openingHook=row["opening_hook"],
        differentiation=row["differentiation"],
    )

    assert {key: mapped[key] for key in (
        "id", "project_id", "status", "payload_json", "content_hash", "created_at"
    )} == {
        "id": row["id"],
        "project_id": "project",
        "status": "candidate",
        "payload_json": canonical_json(payload),
        "content_hash": canonical_hash(payload),
        "created_at": 1,
    }
    assert mapped["updated_at"] == 1
    rendered = mapped["payload_json"]
    for discarded in (
        "emotionalPromise", "styleTarget", "source", "riskNotes", "endingAnchor"
    ):
        assert discarded not in rendered


@pytest.mark.asyncio
async def test_foundation_insert_order_uses_revisioned_seed_binding_and_contract_heads():
    source = RecordingAdminSession()
    project = _map_project((await source.fetchall("FROM .`projects`"))[0])
    seeds = tuple(
        _map_seed(row, project["id"])
        for row in await source.fetchall("FROM .`creative_seeds`")
    )
    provider = _map_provider((await source.fetchall("FROM .`provider_profiles`"))[0], 0)
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


def test_legacy_preserve_fixture_is_pinned_to_the_only_baseline_shape():
    assert LEGACY_BASELINE_COMMIT == "4b85e8d"
    assert "current_chapter_num INT" in PROJECTS_DDL
    assert "current_chapter INT" not in PROJECTS_DDL
    assert "model VARCHAR(200)" in PROVIDERS_DDL
    for v1_only in ("model_name", "enabled", "sort_order"):
        assert v1_only not in PROVIDERS_DDL
    for legacy_seed_field in (
        "genre", "logline", "protagonist", "desire", "core_conflict",
        "world_pressure", "opening_hook", "emotional_promise",
        "differentiation", "style_target", "source", "risk_notes",
        "ending_anchor",
    ):
        assert legacy_seed_field in SEEDS_DDL
    for v1_only in ("premise_json", "content_hash"):
        assert v1_only not in SEEDS_DDL


@pytest.mark.asyncio
async def test_dry_run_reads_only_three_preserve_tables_and_redacts_secrets():
    session = RecordingAdminSession()
    output = []

    report = await reset_writer_core_data(
        session,
        database_name=DISPOSABLE,
        confirm_reset=DISPOSABLE,
        request=request(),
        execute=False,
        allow_product_database=False,
        output=output.append,
    )

    assert report.executed is False
    selected_sql = " ".join(sql for kind, sql, _ in session.calls if kind.startswith("fetch"))
    assert "`projects`" in selected_sql
    assert "`creative_seeds`" in selected_sql
    assert "`provider_profiles`" in selected_sql
    assert "current_chapter_num" in selected_sql
    assert " core_conflict" in selected_sql
    assert " model," in selected_sql
    for v1_only in ("current_chapter,", "premise_json", "content_hash", "model_name", " enabled", "sort_order"):
        assert v1_only not in selected_sql
    for forbidden in (
        "chapters", "versions", "canon_events", "settings", "memory_views",
        "arc_projections", "volume_plans", "story_blocks", "audits", "qa",
    ):
        assert f".`{forbidden}`" not in selected_sql.lower()
    rendered = "\n".join(output)
    for secret in ("DESCRIPTION_SENTINEL", "BASE_URL_SENTINEL", "API_KEY_SENTINEL", "NOTES_SENTINEL"):
        assert secret not in rendered


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
    session = RecordingAdminSession()
    captured = []

    async def connection_factory(config):
        return session

    async def reset_function(admin_session, **kwargs):
        captured.append((admin_session, kwargs))

    result = await run_cli(
        [
            "--database", "novel_creator",
            "--confirm-reset", "novel_creator",
            "--project-title", "永乐大典",
            "--seed-title", "永乐长明",
            "--seed-title", "文渊山海",
            "--seed-title", "典镇山河",
            "--preferred-provider-name", "联通云",
            "--preferred-model", "deepseek-v4-flash",
        ],
        connection_factory=connection_factory,
        connection_config={"db": "novel_creator"},
        reset_function=reset_function,
    )

    assert result == 0
    assert session.closed
    assert not any(kind == "execute" for kind, _, _ in session.calls)
    assert captured[0][1]["execute"] is False
    assert captured[0][1]["allow_product_database"] is True


@pytest.mark.asyncio
async def test_only_matching_cli_execute_authorizes_product_core_flag():
    session = RecordingAdminSession()
    captured = []

    async def connection_factory(config):
        return session

    async def reset_function(admin_session, **kwargs):
        captured.append((admin_session, kwargs))

    result = await run_cli(
        [
            "--database", "novel_creator",
            "--confirm-reset", "novel_creator",
            "--project-title", "永乐大典",
            "--seed-title", "永乐长明",
            "--seed-title", "文渊山海",
            "--seed-title", "典镇山河",
            "--preferred-provider-name", "联通云",
            "--preferred-model", "deepseek-v4-flash",
            "--execute",
        ],
        connection_factory=connection_factory,
        connection_config={"db": "novel_creator"},
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

    async def connection_factory(config):
        assert config == {"password": "PASSWORD_SENTINEL", "db": DISPOSABLE}
        return session

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
    )

    assert result == 0
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


@pytest.mark.asyncio
async def test_ddl_failure_reports_partial_state_and_releases_advisory_lock():
    class FailingCreateSession(RecordingAdminSession):
        async def fetchone(self, sql, args=None):
            normalized = " ".join(sql.split())
            self.calls.append(("fetchone", normalized, args))
            if "GET_LOCK" in sql:
                return {"acquired": 1}
            if "VERSION()" in sql:
                return {"version": "8.0.46"}
            if "information_schema.COLLATIONS" in sql:
                return {"COLLATION_NAME": "utf8mb4_0900_ai_ci"}
            if "JSON_VALID" in sql:
                return {"json_supported": 1}
            if "information_schema.CHECK_CONSTRAINTS" in sql:
                return {"count": 1}
            if "collation_conflict" in sql:
                left, right = (value.casefold().rstrip(" ") for value in args)
                return {"collation_conflict": int(left == right)}
            if "RELEASE_LOCK" in sql:
                return {"released": 1}
            raise AssertionError(f"unexpected SELECT: {sql}")

        async def execute(self, sql, args=None):
            normalized = " ".join(sql.split())
            self.calls.append(("execute", normalized, args))
            if sql.startswith("DROP DATABASE"):
                return 1
            if sql.startswith("CREATE DATABASE"):
                raise RuntimeError("injected CREATE failure")
            raise AssertionError(f"unexpected execute: {sql}")

    session = FailingCreateSession()

    with pytest.raises(ResetPartialStateError, match="partially reset") as raised:
        await reset_writer_core_data(
            session,
            database_name=DISPOSABLE,
            confirm_reset=DISPOSABLE,
            request=request(),
            execute=True,
            allow_product_database=False,
            output=lambda value: None,
        )

    assert "injected CREATE failure" in str(raised.value.__cause__)
    assert any(
        kind == "fetchone" and "RELEASE_LOCK" in sql and args == (RESET_LOCK_NAME,)
        for kind, sql, args in session.calls
    )
    drop_index = next(
        index for index, (_, sql, _) in enumerate(session.calls)
        if sql.startswith("DROP DATABASE")
    )
    before_drop = session.calls[:drop_index]
    lock_index = next(
        index for index, (_, sql, _) in enumerate(before_drop) if "GET_LOCK" in sql
    )
    assert lock_index > 0
    preserved_selects = [
        sql for kind, sql, _ in before_drop
        if kind == "fetchall"
    ]
    assert sum("information_schema.TABLES" in sql for sql in preserved_selects) == 1
    for table in ("projects", "creative_seeds", "provider_profiles"):
        assert sum(f".`{table}`" in sql for sql in preserved_selects) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failures", ((), ("rollback",), ("release",), ("close",), ("rollback", "release", "close")))
async def test_failed_commit_recovery_runs_every_step_and_combines_failures(failures):
    class RecoverySession:
        def __init__(self):
            self.calls = []

        async def execute(self, sql, args=None):
            self.calls.append("rollback")
            if "rollback" in failures:
                raise RuntimeError("rollback failed")

        async def fetchone(self, sql, args=None):
            self.calls.append("release")
            if "release" in failures:
                raise RuntimeError("release failed")
            return {"released": 1}

        async def close(self):
            self.calls.append("close")
            if "close" in failures:
                raise RuntimeError("close failed")

    session = RecoverySession()
    commit_error = RuntimeError("commit failed")
    expected = ["commit failed", *(f"{name} failed" for name in failures)]

    if failures:
        with pytest.raises(BaseExceptionGroup) as raised:
            await _recover_failed_commit(session, commit_error)
        assert [str(error) for error in raised.value.exceptions] == expected
    else:
        with pytest.raises(RuntimeError) as raised:
            await _recover_failed_commit(session, commit_error)
        assert raised.value is commit_error
    assert session.calls == ["rollback", "release", "close"]


@pytest.mark.asyncio
async def test_mysql_57_is_rejected_before_preserve_reads_or_any_ddl():
    class MySQL57Session(RecordingAdminSession):
        async def fetchone(self, sql, args=None):
            normalized = " ".join(sql.split())
            self.calls.append(("fetchone", normalized, args))
            if "GET_LOCK" in sql:
                return {"acquired": 1}
            if "VERSION()" in sql:
                return {"version": "5.7.44"}
            if "collation_conflict" in sql:
                return {"collation_conflict": 0}
            if "RELEASE_LOCK" in sql:
                return {"released": 1}
            raise AssertionError(f"unexpected SELECT: {sql}")

    session = MySQL57Session()

    with pytest.raises(ResetValidationError, match="MySQL 8"):
        await reset_writer_core_data(
            session,
            database_name=DISPOSABLE,
            confirm_reset=DISPOSABLE,
            request=request(), execute=True, allow_product_database=False,
            output=lambda value: None,
        )

    assert any(
        kind == "fetchall" and "information_schema.TABLES" in sql
        for kind, sql, _ in session.calls
    )
    assert not any(kind == "execute" for kind, _, _ in session.calls)
    assert any("RELEASE_LOCK" in sql for _, sql, _ in session.calls)
