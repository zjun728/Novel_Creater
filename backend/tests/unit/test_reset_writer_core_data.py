from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import backend.scripts.reset_writer_core_data as reset_module
from backend.schema_manifest import created_table_names, manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION


DISPOSABLE = "novel_creator_test_0123456789abcdef0123456789abcdef"
SEED_TITLES = ("永乐长明", "文渊山海", "典镇山河")


def request() -> reset_module.ResetRequest:
    return reset_module.ResetRequest(
        project_title="永乐大典",
        seed_titles=SEED_TITLES,
        preferred_provider_name="联通云",
        preferred_model="deepseek-v4-flash",
    )


def provider_rows():
    return [{
        "id": "provider-1",
        "name": "联通云",
        "model_name": "deepseek-v4-flash",
        "enabled": 1,
        "lifecycle_status": "active",
        "deleted_at": None,
    }]


def binding_rows():
    items = tuple(
        reset_module.BindingItem(
            task_key=task_key,
            resolution_status="bound",
            provider_id="provider-1",
            provider_name_snapshot="联通云",
            model_name_snapshot="deepseek-v4-flash",
        )
        for task_key in reset_module.TASK_KEYS
    )
    binding = reset_module.BindingRevision(
        project_id="project-1",
        revision=1,
        items=items,
    )
    binding_hash = reset_module.canonical_hash(binding)
    return [
        {
            "revision": 1,
            "binding_revision_id": "binding-1",
            "binding_hash": binding_hash,
            "source_project_id": None,
            "task_key": item.task_key,
            "resolution_status": item.resolution_status,
            "provider_id": item.provider_id,
            "provider_name_snapshot": item.provider_name_snapshot,
            "model_name_snapshot": item.model_name_snapshot,
            "item_hash": reset_module.canonical_hash(item),
            "provider_name": "联通云",
            "provider_model": "deepseek-v4-flash",
            "provider_enabled": 1,
            "provider_lifecycle": "active",
            "provider_deleted_at": None,
        }
        for item in items
    ]


class CurrentSession:
    def __init__(
        self,
        *,
        metadata=None,
        fail_on: str | None = None,
        providers=None,
        bindings=None,
    ):
        self.metadata = metadata or {
            "schema_version": EXPECTED_SCHEMA_VERSION,
            "manifest_hash": manifest_hash(),
        }
        self.fail_on = fail_on
        self.providers = provider_rows() if providers is None else providers
        self.bindings = binding_rows() if bindings is None else bindings
        self.calls: list[tuple[str, str, object]] = []
        self.closed = False

    async def fetchall(self, sql, args=None):
        self.calls.append(("fetchall", sql, args))
        if "information_schema.TABLES" in sql:
            return [{"TABLE_NAME": name} for name in created_table_names()]
        if "`projects`" in sql:
            return [{
                "id": "project-1",
                "title": "永乐大典",
                "status": "drafting",
                "archived_at": None,
            }]
        if "`creative_seeds`" in sql:
            return [
                {
                    "id": f"seed-{index}",
                    "title": title,
                    "revision": 1,
                    "content_hash": str(index) * 64,
                }
                for index, title in enumerate(SEED_TITLES, 1)
            ]
        if "`project_model_binding_heads`" in sql:
            return self.bindings
        if "`provider_profiles`" in sql:
            return self.providers
        raise AssertionError(sql)

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", sql, args))
        if "SELECT DATABASE()" in sql:
            return {"database_name": DISPOSABLE}
        if "`schema_metadata`" in sql:
            return dict(self.metadata)
        if "`project_selected_seeds`" in sql:
            return {
                "seed_id": "seed-3",
                "title": "典镇山河",
                "selection_revision": 1,
            }
        if "FROM projects" in sql and "FOR UPDATE" in sql:
            return {"id": "project-1"}
        if "GET_LOCK" in sql:
            return {"acquired": 1}
        if "RELEASE_LOCK" in sql:
            return {"released": 1}
        if "MIN(" in sql:
            return {"count": 1, "min_revision": 0, "max_revision": 0}
        if "COUNT(*) AS count" in sql:
            return {"count": 0}
        raise AssertionError(sql)

    async def execute(self, sql, args=None):
        self.calls.append(("execute", sql, args))
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("injected reset failure")

    async def close(self):
        self.closed = True


def test_reset_runtime_is_current_only_and_contains_no_conversion_contract():
    source = Path(reset_module.__file__).read_text(encoding="utf-8")

    assert "EXPECTED_SCHEMA_VERSION" in source
    assert "manifest_hash()" in source
    assert "initialize_database" in source
    assert "frozen_writer_core" not in source
    for retired in (
        "writer-core-v1.1.0",
        "writer-core-v1.4.0",
        "v1.1-source",
        "v1.4-target",
        "V11_TABLE_NAMES",
        "volume_plans",
        "story_blocks",
        "story_stages",
        "scene_tasks",
    ):
        assert retired not in source


def test_reset_request_requires_exact_approved_seed_closed_set():
    with pytest.raises(ValueError, match="three unique"):
        reset_module.ResetRequest(
            "永乐大典",
            ("典镇山河", "典镇山河", "文渊山海"),
            "联通云",
            "deepseek-v4-flash",
        )
    with pytest.raises(ValueError, match="典镇山河"):
        reset_module.ResetRequest(
            "永乐大典",
            ("永乐长明", "文渊山海", "另一种子"),
            "联通云",
            "deepseek-v4-flash",
        )


@pytest.mark.asyncio
async def test_classification_accepts_only_exact_current_manifest():
    session = CurrentSession()
    assert (
        await reset_module._classify_reset_source(session, DISPOSABLE)
        == "current"
    )

    bad = CurrentSession(metadata={
        "schema_version": "unsupported",
        "manifest_hash": "0" * 64,
    })
    with pytest.raises(
        reset_module.ResetValidationError,
        match="initialize_database",
    ):
        await reset_module._classify_reset_source(bad, DISPOSABLE)
    assert not any("`projects`" in sql for _, sql, _ in bad.calls)


@pytest.mark.asyncio
async def test_dry_run_reads_foundation_without_mutation_or_secret_output():
    session = CurrentSession()
    output: list[str] = []

    report = await reset_module.reset_writer_core_data(
        session,
        database_name=DISPOSABLE,
        confirm_reset=DISPOSABLE,
        request=request(),
        output=output.append,
    )

    assert report.executed is False
    assert report.mode == "dry-run"
    assert not any(kind == "execute" for kind, _, _ in session.calls)
    receipt = json.loads(output[0])
    assert receipt["schema"]["version"] == EXPECTED_SCHEMA_VERSION
    assert receipt["reset"]["verified"] is False
    assert receipt["reset"]["heads"]["planning"] == 0
    assert set(reset_module._CASCADED_DERIVED_TABLES).issubset(
        receipt["reset"]["clearedTables"]
    )
    assert "api_key" not in output[0].lower()
    assert "secret" not in output[0].lower()


@pytest.mark.asyncio
async def test_foundation_requires_every_provider_row_active_and_non_deleted():
    invalid = provider_rows() + [{
        "id": "provider-hidden",
        "name": "旧配置",
        "model_name": "retired-model",
        "enabled": 0,
        "lifecycle_status": "deleted",
        "deleted_at": 123,
    }]
    with pytest.raises(
        reset_module.ResetValidationError,
        match="Provider rows",
    ):
        await reset_module._load_current_foundation(
            CurrentSession(providers=invalid),
            DISPOSABLE,
            request(),
        )


@pytest.mark.asyncio
async def test_foundation_requires_exact_bound_task_closed_set():
    duplicate_seed = binding_rows()
    duplicate_seed[-1] = {**duplicate_seed[-1], "task_key": "seed"}
    with pytest.raises(
        reset_module.ResetValidationError,
        match="task closed set",
    ):
        await reset_module._load_current_foundation(
            CurrentSession(bindings=duplicate_seed),
            DISPOSABLE,
            request(),
        )

    unbound = binding_rows()
    unbound[0] = {
        **unbound[0],
        "resolution_status": "unbound",
        "provider_id": None,
        "provider_name_snapshot": None,
        "model_name_snapshot": None,
    }
    with pytest.raises(
        reset_module.ResetValidationError,
        match="bound preferred provider",
    ):
        await reset_module._load_current_foundation(
            CurrentSession(bindings=unbound),
            DISPOSABLE,
            request(),
        )


@pytest.mark.asyncio
async def test_execute_clears_derived_rows_and_rebuilds_all_head_zero_state():
    session = CurrentSession()

    report = await reset_module.reset_writer_core_data(
        session,
        database_name=DISPOSABLE,
        confirm_reset=DISPOSABLE,
        request=request(),
        execute=True,
        output=lambda _value: None,
        now_ms=lambda: 123,
        id_factory=lambda: "canon-bootstrap",
    )

    assert report.executed is True
    statements = [sql for kind, sql, _ in session.calls if kind == "execute"]
    assert statements[0] == "START TRANSACTION"
    first_after_start = session.calls[
        next(
            index
            for index, call in enumerate(session.calls)
            if call[0] == "execute" and call[1] == "START TRANSACTION"
        )
        + 1
    ]
    assert first_after_start[0] == "fetchone"
    assert "FOR UPDATE" in first_after_start[1]
    assert any("DELETE FROM planning_drafts" in sql for sql in statements)
    assert any("INSERT INTO project_planning_heads" in sql for sql in statements)
    assert any("INSERT INTO canon_revisions" in sql for sql in statements)
    assert statements[-1] == "COMMIT"
    assert any("RELEASE_LOCK" in sql for _, sql, _ in session.calls)
    assert not any("DROP DATABASE" in sql or "CREATE DATABASE" in sql for sql in statements)
    commit_index = next(
        index
        for index, call in enumerate(session.calls)
        if call[0] == "execute" and call[1] == "COMMIT"
    )
    release_index = next(
        index
        for index, call in enumerate(session.calls)
        if "RELEASE_LOCK" in call[1]
    )
    assert session.calls[commit_index + 1 : release_index] == []


@pytest.mark.asyncio
async def test_execute_builds_complete_report_before_commit(monkeypatch):
    session = CurrentSession()
    original_report = reset_module._report
    original_format = reset_module.format_reset_report

    def report(*args, **kwargs):
        assert not any(
            kind == "execute" and sql == "COMMIT"
            for kind, sql, _ in session.calls
        )
        return original_report(*args, **kwargs)

    def format_report(value):
        assert not any(
            kind == "execute" and sql == "COMMIT"
            for kind, sql, _ in session.calls
        )
        return original_format(value)

    monkeypatch.setattr(reset_module, "_report", report)
    monkeypatch.setattr(reset_module, "format_reset_report", format_report)
    await reset_module.reset_writer_core_data(
        session,
        database_name=DISPOSABLE,
        confirm_reset=DISPOSABLE,
        request=request(),
        execute=True,
        output=lambda _value: None,
    )


@pytest.mark.asyncio
async def test_post_commit_lock_cleanup_failure_is_explicit(monkeypatch):
    session = CurrentSession()

    async def fail_release(_session):
        raise RuntimeError("PRIVATE_LOCK_SENTINEL")

    monkeypatch.setattr(reset_module, "_release_lock", fail_release)
    with pytest.raises(
        reset_module.ResetCommittedCleanupError,
        match="committed, but cleanup failed",
    ):
        await reset_module.reset_writer_core_data(
            session,
            database_name=DISPOSABLE,
            confirm_reset=DISPOSABLE,
            request=request(),
            execute=True,
            output=lambda _value: None,
        )
    assert any(
        kind == "execute" and sql == "COMMIT"
        for kind, sql, _ in session.calls
    )
    assert not any(
        kind == "execute" and sql == "ROLLBACK"
        for kind, sql, _ in session.calls
    )


@pytest.mark.asyncio
async def test_execute_failure_rolls_back_and_releases_lock():
    session = CurrentSession(fail_on="DELETE FROM planning_drafts")

    with pytest.raises(RuntimeError, match="injected reset failure"):
        await reset_module.reset_writer_core_data(
            session,
            database_name=DISPOSABLE,
            confirm_reset=DISPOSABLE,
            request=request(),
            execute=True,
            output=lambda _value: None,
        )

    statements = [sql for kind, sql, _ in session.calls if kind == "execute"]
    assert "ROLLBACK" in statements
    assert "COMMIT" not in statements
    assert any("RELEASE_LOCK" in sql for _, sql, _ in session.calls)


@pytest.mark.asyncio
async def test_direct_core_call_cannot_authorize_product_database():
    with pytest.raises(reset_module.ResetSafetyError):
        await reset_module.reset_writer_core_data(
            CurrentSession(),
            database_name=reset_module.PRODUCT_DATABASE,
            confirm_reset=reset_module.PRODUCT_DATABASE,
            request=request(),
            execute=False,
            allow_product_database=True,
        )


@pytest.mark.asyncio
async def test_reset_rejects_selected_database_mismatch_before_inventory_or_write():
    session = CurrentSession()

    async def wrong_identity(sql, args=None):
        session.calls.append(("fetchone", sql, args))
        return {"database_name": "another_database"}

    session.fetchone = wrong_identity
    with pytest.raises(reset_module.ResetSafetyError, match="Selected database identity"):
        await reset_module.reset_writer_core_data(
            session,
            database_name=DISPOSABLE,
            confirm_reset=DISPOSABLE,
            request=request(),
            execute=True,
        )
    assert session.calls == [
        ("fetchone", "SELECT DATABASE() AS database_name", None)
    ]


def cli_args(database=DISPOSABLE, *, execute=False):
    args = [
        "--database", database,
        "--confirm-reset", database,
        "--project-title", "永乐大典",
        "--seed-title", "永乐长明",
        "--seed-title", "文渊山海",
        "--seed-title", "典镇山河",
        "--preferred-provider-name", "联通云",
        "--preferred-model", "deepseek-v4-flash",
    ]
    if database == reset_module.PRODUCT_DATABASE:
        args += [
            "--confirm-host", reset_module.PRODUCT_HOST,
            "--confirm-port", str(reset_module.PRODUCT_PORT),
        ]
    if execute:
        args.append("--execute")
    return args


@pytest.mark.asyncio
async def test_cli_rejects_configured_database_mismatch_before_connection():
    calls = []

    async def connect(_config):
        calls.append("connect")

    with pytest.raises(reset_module.ResetSafetyError, match="configured database"):
        await reset_module.run_cli(
            cli_args(),
            connection_config={"db": "wrong"},
            connection_factory=connect,
        )
    assert calls == []


@pytest.mark.asyncio
async def test_cli_closes_session_and_uses_execute_authority():
    session = CurrentSession()
    captured = {}

    async def connect(_config):
        return session

    async def reset(_session, **kwargs):
        captured.update(kwargs)

    await reset_module.run_cli(
        cli_args(execute=True),
        connection_config={"db": DISPOSABLE},
        connection_factory=connect,
        reset_function=reset,
    )

    assert session.closed is True
    assert captured["execute"] is True
    assert captured["_product_authority"] is reset_module._CLI_PRODUCT_EXECUTE_AUTHORITY


@pytest.mark.asyncio
async def test_cli_combines_reset_and_close_failures():
    class BrokenSession(CurrentSession):
        async def close(self):
            raise RuntimeError("close failed")

    async def connect(_config):
        return BrokenSession()

    async def reset(_session, **_kwargs):
        raise RuntimeError("reset failed")

    with pytest.raises(BaseExceptionGroup) as captured:
        await reset_module.run_cli(
            cli_args(),
            connection_config={"db": DISPOSABLE},
            connection_factory=connect,
            reset_function=reset,
        )
    assert [str(item) for item in captured.value.exceptions] == [
        "reset failed",
        "close failed",
    ]


@pytest.mark.asyncio
async def test_connection_factory_closes_raw_connection_when_cursor_creation_fails(
    monkeypatch,
):
    class Raw:
        closed = False

        async def cursor(self, _kind):
            raise RuntimeError("cursor failed")

        async def ensure_closed(self):
            self.closed = True

    raw = Raw()

    async def connect(**_kwargs):
        return raw

    monkeypatch.setitem(
        __import__("sys").modules,
        "aiomysql",
        SimpleNamespace(connect=connect, DictCursor=object()),
    )
    with pytest.raises(RuntimeError, match="cursor failed"):
        await reset_module._reset_connection_factory({"db": DISPOSABLE})
    assert raw.closed is True


@pytest.mark.asyncio
async def test_product_connection_identity_is_fail_closed():
    class Identity:
        async def fetchone(self, _sql):
            return {
                "database_name": reset_module.PRODUCT_DATABASE,
                "server_port": reset_module.PRODUCT_PORT,
                "server_identity": "",
            }

    with pytest.raises(reset_module.ResetSafetyError, match="identity is empty"):
        await reset_module._verify_product_connection_identity(Identity())


@pytest.mark.parametrize(
    "failure",
    (
        RuntimeError("PASSWORD_SENTINEL"),
        BaseExceptionGroup(
            "PRIVATE_CONNECTION_SENTINEL",
            [RuntimeError("API_KEY_SENTINEL")],
        ),
    ),
)
def test_main_redacts_all_runtime_and_cleanup_failures(
    monkeypatch,
    capsys,
    failure,
):
    def fail(coroutine):
        coroutine.close()
        raise failure

    monkeypatch.setattr(reset_module.asyncio, "run", fail)
    assert reset_module.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Writer Core data reset failed.\n"


def test_main_preserves_argparse_system_exit(monkeypatch):
    def fail(coroutine):
        coroutine.close()
        raise SystemExit(2)

    monkeypatch.setattr(reset_module.asyncio, "run", fail)
    with pytest.raises(SystemExit) as captured:
        reset_module.main([])
    assert captured.value.code == 2
