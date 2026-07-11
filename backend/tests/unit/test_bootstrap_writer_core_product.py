import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from backend.scripts import bootstrap_writer_core_product as bootstrap
from backend.services.projects import TASK_KEYS


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PRODUCT = "novel_creator"
SECRET_VALUES = (
    "SOURCE_API_KEY_SENTINEL",
    "SOURCE_BASE_URL_SENTINEL",
    "SOURCE_DESCRIPTION_SENTINEL",
    "SOURCE_NOTES_SENTINEL",
    "SOURCE_DSN_SENTINEL",
)


def project_row():
    return {
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "title": "永乐大典",
        "genre": "历史",
        "description": SECRET_VALUES[2],
        "target_words": 1_000_000,
        "target_chapters": 500,
        "current_chapter_num": 17,
        "status": "active",
        "created_at": 100,
        "updated_at": 200,
    }


def seed_row(seed_id, title):
    return {
        "id": seed_id,
        "project_id": project_row()["id"],
        "title": title,
        "genre": "历史",
        "logline": f"{title}故事",
        "protagonist": f"{title}主人公",
        "desire": "守护典籍",
        "core_conflict": "朝局冲突",
        "world_pressure": "天下大势",
        "opening_hook": "开篇危机",
        "emotional_promise": "守护文明",
        "differentiation": "独特史观",
        "style_target": "克制厚重",
        "source": "user",
        "risk_notes": None,
        "ending_anchor": None,
        "status": "candidate",
        "created_at": 100,
    }


def provider_row(provider_id, name, model, *, created_at):
    return {
        "id": provider_id,
        "name": name,
        "provider_type": "openai-compatible",
        "base_url": SECRET_VALUES[1],
        "api_key": SECRET_VALUES[0],
        "model": model,
        "stream": 1,
        "max_context_tokens": None,
        "max_output_tokens": None,
        "temperature": None,
        "top_p": 0.95,
        "supports_json": 1,
        "supports_streaming": 1,
        "notes": SECRET_VALUES[3],
        "thinking": json.dumps({"budget": 3}),
        "created_at": created_at,
        "updated_at": created_at + 10,
    }


def inventory(*, providers=None, seeds=None, projects=None):
    return bootstrap.LegacyInventory(
        source_version="5.7.44",
        projects=tuple(projects or (project_row(),)),
        seeds=tuple(seeds or (
            seed_row("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "永乐长明"),
            seed_row("cccccccc-cccc-cccc-cccc-cccccccccccc", "文渊山海"),
            seed_row("dddddddd-dddd-dddd-dddd-dddddddddddd", "典镇山河"),
        )),
        providers=tuple(providers or (
            provider_row(
                "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
                "联通云-DeepSeek-V4-Flash",
                "DeepSeek-V4-Flash",
                created_at=100,
            ),
            provider_row(
                "ffffffff-ffff-ffff-ffff-ffffffffffff",
                "备用云",
                "backup-model",
                created_at=90,
            ),
        )),
    )


def test_source_whitelist_uses_ascii_utf8_hex_binary_title_predicates():
    queries = bootstrap.SOURCE_SELECT_WHITELIST
    project_query = next(query for query in queries if "FROM `projects`" in query)
    seed_query = next(query for query in queries if "FROM `creative_seeds`" in query)

    assert len(queries) == 4
    assert all(query.isascii() for query in queries)
    assert all(query.lstrip().upper().startswith("SELECT ") for query in queries)
    assert project_query.endswith(
        "WHERE BINARY `title`=0xE6B0B8E4B990E5A4A7E585B8 ORDER BY `id`"
    )
    assert seed_query.endswith(
        "WHERE BINARY `title` IN "
        "(0xE6B0B8E4B990E995BFE6988E,"
        "0xE69687E6B88AE5B1B1E6B5B7,"
        "0xE585B8E99587E5B1B1E6B2B3) ORDER BY `title`,`id`"
    )


def test_source_reader_uses_only_fixed_shell_free_json_selects(monkeypatch):
    calls = []
    environment_secrets = (
        "MYSQL_PWD_SECRET",
        "MYSQL_TEST_LOGIN_FILE_SECRET",
        "MYSQL_ARBITRARY_SECRET",
        "LIBMYSQL_PLUGIN_DIR_SECRET",
        "LIBMYSQL_CLEARTEXT_SECRET",
    )
    monkeypatch.setenv("MYSQL_PWD", environment_secrets[0])
    monkeypatch.setenv("mysql_test_login_file", environment_secrets[1])
    monkeypatch.setenv("MySql_Arbitrary", environment_secrets[2])
    monkeypatch.setenv("LIBMYSQL_PLUGIN_DIR", environment_secrets[3])
    monkeypatch.setenv("libmysql_enable_cleartext_plugin", environment_secrets[4])
    monkeypatch.setenv("WRITER_CORE_SAFE_ENV", "preserved")

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        query = command[command.index("--execute") + 1]
        if "VERSION()" in query:
            rows = [{"version": "5.7.44", "json_supported": 1}]
        elif "FROM `projects`" in query:
            rows = [project_row()]
        elif "FROM `creative_seeds`" in query:
            rows = list(inventory().seeds)
        elif "FROM `provider_profiles`" in query:
            rows = list(inventory().providers)
        else:
            raise AssertionError(query)
        return SimpleNamespace(
            returncode=0,
            stdout="\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
            stderr="",
        )

    loaded = bootstrap.read_legacy_inventory(
        "C:/mysql57/bin/mysql.exe",
        runner=runner,
    )

    assert loaded.source_version == "5.7.44"
    assert (len(loaded.projects), len(loaded.seeds), len(loaded.providers)) == (1, 3, 2)
    assert len(calls) == 4
    rendered_commands = "\n".join(" ".join(command) for command, _ in calls)
    assert "--login-path=novel57-admin" in rendered_commands
    assert "--database=novel_creator" in rendered_commands
    assert "password" not in rendered_commands.lower()
    assert "task_model_bindings" not in rendered_commands
    for command, kwargs in calls:
        assert command[1:3] == ["--no-defaults", "--login-path=novel57-admin"]
        query = command[command.index("--execute") + 1]
        assert query in bootstrap.SOURCE_SELECT_WHITELIST
        assert query.lstrip().upper().startswith("SELECT ")
        environment = kwargs.pop("env")
        assert environment["WRITER_CORE_SAFE_ENV"] == "preserved"
        assert not any(
            key.upper().startswith("MYSQL_")
            or key.upper() in {
                "LIBMYSQL_PLUGIN_DIR",
                "LIBMYSQL_ENABLE_CLEARTEXT_PLUGIN",
            }
            for key in environment
        )
        assert all(secret not in repr(environment) for secret in environment_secrets)
        assert kwargs == {
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "check": False,
            "shell": False,
        }


def test_source_reader_failure_never_renders_captured_secrets():
    def runner(command, **kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout=SECRET_VALUES[0],
            stderr=SECRET_VALUES[4],
        )

    with pytest.raises(bootstrap.BootstrapSourceError) as raised:
        bootstrap.read_legacy_inventory("mysql.exe", runner=runner)

    rendered = str(raised.value)
    assert all(secret not in rendered for secret in SECRET_VALUES)


@pytest.mark.parametrize(
    "overrides",
    (
        {"login_path": "other-login"},
        {"source_database": "other_database"},
    ),
)
def test_source_reader_rejects_any_noncanonical_source_boundary(overrides):
    called = False

    def runner(command, **kwargs):
        nonlocal called
        called = True

    with pytest.raises(bootstrap.BootstrapSafetyError):
        bootstrap.read_legacy_inventory("mysql.exe", runner=runner, **overrides)

    assert called is False


def test_mapping_reuses_v1_rules_and_only_canonically_renames_preferred():
    state = bootstrap.map_legacy_inventory(inventory())

    assert state.project["title"] == "永乐大典"
    assert state.project["current_chapter"] == 0
    assert len(state.seeds) == 3
    selected = [seed for seed in state.seeds if seed["status"] == "selected"]
    assert [(row["title"], len(row["content_hash"])) for row in selected] == [
        ("典镇山河", 64),
    ]
    assert [provider["id"] for provider in state.providers] == [
        "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
        "ffffffff-ffff-ffff-ffff-ffffffffffff",
    ]
    assert state.preferred_provider["name"] == "联通云"
    assert state.preferred_provider["model_name"] == "deepseek-v4-flash"
    other = state.providers[1]
    assert (other["name"], other["model_name"]) == ("备用云", "backup-model")
    assert state.preferred_provider["max_context_tokens"] == 200_000
    assert state.preferred_provider["max_output_tokens"] == 4_096


def test_mapping_rejects_duplicate_source_provider_ids_before_reordering():
    preferred = inventory().providers[0]
    duplicate_id_other_provider = provider_row(
        preferred["id"],
        "备用重复ID云",
        "backup-model",
        created_at=90,
    )

    with pytest.raises(bootstrap.BootstrapValidationError, match="provider id"):
        bootstrap.map_legacy_inventory(inventory(providers=(
            preferred,
            duplicate_id_other_provider,
        )))


@pytest.mark.parametrize(
    "broken",
    (
        lambda source: bootstrap.LegacyInventory(
            source.source_version, (), source.seeds, source.providers
        ),
        lambda source: bootstrap.LegacyInventory(
            source.source_version, source.projects, source.seeds[:2], source.providers
        ),
        lambda source: bootstrap.LegacyInventory(
            source.source_version,
            source.projects,
            source.seeds,
            source.providers + (source.providers[0],),
        ),
    ),
)
def test_mapping_rejects_wrong_exact_cardinality(broken):
    with pytest.raises(bootstrap.BootstrapValidationError):
        bootstrap.map_legacy_inventory(broken(inventory()))


class TargetSession:
    def __init__(self, *, target_exists=False, fail_execute_contains=None):
        self.target_exists = target_exists
        self.fail_execute_contains = fail_execute_contains
        self.calls = []
        self.closed = False
        self.foundation_counts = {
            "projects": 1,
            "creative_seeds": 3,
            "project_selected_seeds": 1,
            "provider_profiles": 2,
            "task_model_bindings": 1,
            "task_model_binding_items": len(TASK_KEYS),
            "canon_revisions": 1,
            "projection_heads": 1,
        }

    async def fetchone(self, sql, parameters=None):
        normalized = " ".join(sql.split())
        self.calls.append(("fetchone", normalized, parameters))
        if "VERSION()" in sql:
            return {"version": "8.4.10"}
        if "information_schema.COLLATIONS" in sql:
            return {"COLLATION_NAME": "utf8mb4_0900_ai_ci"}
        if "JSON_VALID" in sql:
            return {"json_supported": 1}
        if "information_schema.CHECK_CONSTRAINTS" in sql:
            return {"count": 1}
        if "information_schema.SCHEMATA" in sql:
            return {"SCHEMA_NAME": PRODUCT} if self.target_exists else None
        if "GET_LOCK" in sql:
            return {"acquired": 1}
        if "RELEASE_LOCK" in sql:
            return {"released": 1}
        if "collation_conflict" in sql:
            return {"collation_conflict": 0}
        if "SELECT COUNT(*) AS count FROM" in normalized:
            table = normalized.split("FROM", 1)[1].strip().split()[0].strip("`")
            return {"count": self.foundation_counts.get(table, 0)}
        raise AssertionError(normalized)

    async def execute(self, sql, parameters=None):
        normalized = " ".join(sql.split())
        self.calls.append(("execute", normalized, parameters))
        if self.fail_execute_contains and self.fail_execute_contains in normalized:
            raise RuntimeError(f"failed {self.fail_execute_contains}")

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_target_collation_validation_is_authoritative():
    session = TargetSession()
    state = bootstrap.map_legacy_inventory(inventory())

    await bootstrap.validate_mapped_state(session, state)

    comparisons = [call for call in session.calls if "collation_conflict" in call[1]]
    assert len(comparisons) == 4


@pytest.mark.asyncio
async def test_canonical_preferred_rename_collision_is_rejected_by_target():
    colliding_other = provider_row(
        "ffffffff-ffff-ffff-ffff-ffffffffffff",
        "联通云",
        "backup-model",
        created_at=90,
    )
    state = bootstrap.map_legacy_inventory(inventory(providers=(
        inventory().providers[0],
        colliding_other,
    )))

    class CollisionSession(TargetSession):
        async def fetchone(self, sql, parameters=None):
            if "collation_conflict" in sql and parameters == ("联通云", "联通云"):
                return {"collation_conflict": 1}
            return await super().fetchone(sql, parameters)

    with pytest.raises(bootstrap.BootstrapValidationError, match="collation"):
        await bootstrap.validate_mapped_state(CollisionSession(), state)


def test_receipt_contains_only_public_identity_and_count_fields():
    report = bootstrap.build_report(bootstrap.map_legacy_inventory(inventory()))
    rendered = bootstrap.format_bootstrap_report(report)

    for public in (
        "永乐大典", "永乐长明", "文渊山海", "典镇山河",
        "联通云", "deepseek-v4-flash", "备用云", "backup-model",
        "binding_items.count=8",
    ):
        assert public in rendered
    assert all(secret not in rendered for secret in SECRET_VALUES)
    assert "description" not in rendered
    assert "base_url" not in rendered
    assert "notes" not in rendered


def test_receipt_json_encodes_dynamic_values_as_single_safe_records():
    injection = (
        "\r\nforged.count=999\x1b[31m\x07\u009b32m"
        "\u2028line-separator\u2029paragraph-separator\u202ebidi-override"
    )
    project_id = f"project-{injection}"
    project_title = f"title-{injection}"
    seed_id = f"seed-{injection}"
    seed_title = f"seed-title-{injection}"
    provider_id = f"provider-{injection}"
    provider_name = f"provider-name-{injection}"
    provider_model = f"provider-model-{injection}"
    preferred_id = f"preferred-{injection}"
    report = bootstrap.BootstrapReport(
        project_id=project_id,
        project_title=project_title,
        seeds=((seed_id, seed_title),),
        providers=((provider_id, provider_name, provider_model),),
        preferred_provider_id=preferred_id,
    )

    rendered = bootstrap.format_bootstrap_report(report)

    def encode(value):
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))

    assert rendered.splitlines() == [
        "projects.count=1",
        f"project.id={encode(project_id)}",
        f"project.title={encode(project_title)}",
        "seeds.count=1",
        f"seed.id={encode(seed_id)} seed.title={encode(seed_title)}",
        "providers.count=1",
        (
            f"provider.id={encode(provider_id)} provider.name={encode(provider_name)} "
            f"provider.model={encode(provider_model)}"
        ),
        f"preferred_provider.id={encode(preferred_id)}",
        "bindings.count=1",
        "binding_items.count=8",
        "canon_revisions.count=1",
        "projection_heads.count=1",
    ]
    assert all(
        control not in rendered
        for control in (
            "\r", "\x1b", "\x07", "\u009b", "\u2028", "\u2029", "\u202e",
        )
    )
    assert all(secret not in rendered for secret in SECRET_VALUES)


@pytest.mark.asyncio
async def test_dry_run_preflights_absent_target_and_never_writes():
    session = TargetSession()
    output = []

    report = await bootstrap.bootstrap_writer_core_product(
        session,
        database_name=PRODUCT,
        source_loader=inventory,
        output=output.append,
        _product_authority=bootstrap._CLI_PRODUCT_READ_AUTHORITY,
    )

    assert report.binding_item_count == 8
    assert not any(kind == "execute" for kind, _, _ in session.calls)
    assert any("information_schema.SCHEMATA" in sql for _, sql, _ in session.calls)
    assert all(secret not in "\n".join(output) for secret in SECRET_VALUES)


@pytest.mark.asyncio
async def test_execute_requires_confirmation_and_private_authority():
    session = TargetSession()

    with pytest.raises(bootstrap.BootstrapSafetyError):
        await bootstrap.bootstrap_writer_core_product(
            session,
            database_name=PRODUCT,
            source_loader=inventory,
            execute=True,
            confirm_bootstrap=PRODUCT,
        )
    assert session.calls == []


@pytest.mark.asyncio
async def test_disposable_execute_also_requires_private_cli_authority():
    session = TargetSession()
    disposable = "novel_creator_test_0123456789abcdef0123456789abcdef"

    with pytest.raises(bootstrap.BootstrapSafetyError, match="authority"):
        await bootstrap.bootstrap_writer_core_product(
            session,
            database_name=disposable,
            source_loader=inventory,
            execute=True,
            confirm_bootstrap=disposable,
        )

    assert session.calls == []


@pytest.mark.asyncio
async def test_existing_target_is_rejected_before_source_reader():
    session = TargetSession(target_exists=True)
    source_read = False

    def source_loader():
        nonlocal source_read
        source_read = True
        return inventory()

    with pytest.raises(bootstrap.BootstrapSafetyError, match="absent"):
        await bootstrap.bootstrap_writer_core_product(
            session,
            database_name=PRODUCT,
            source_loader=source_loader,
            _product_authority=bootstrap._CLI_PRODUCT_READ_AUTHORITY,
        )

    assert source_read is False
    assert not any(kind == "execute" for kind, _, _ in session.calls)


@pytest.mark.asyncio
async def test_execute_initializes_inserts_verifies_commits_and_releases():
    session = TargetSession()
    events = []

    async def initializer(admin_session, database_name, confirm_create, now_ms):
        events.append(("initialize", database_name, confirm_create, now_ms))

    async def inserter(admin_session, state, *, now_ms, id_factory):
        events.append((
            "insert",
            state.preferred_provider["name"],
            state.preferred_provider["model_name"],
            len(TASK_KEYS),
        ))

    report = await bootstrap.bootstrap_writer_core_product(
        session,
        database_name=PRODUCT,
        source_loader=inventory,
        execute=True,
        confirm_bootstrap=PRODUCT,
        initializer=initializer,
        inserter=inserter,
        now_ms=lambda: 123,
        id_factory=lambda: "00000000-0000-0000-0000-000000000001",
        _product_authority=bootstrap._CLI_PRODUCT_EXECUTE_AUTHORITY,
    )

    assert report.binding_item_count == len(TASK_KEYS)
    assert events == [
        ("initialize", PRODUCT, PRODUCT, 123),
        ("insert", "联通云", "deepseek-v4-flash", 8),
    ]
    executed = [sql for kind, sql, _ in session.calls if kind == "execute"]
    assert any(sql.startswith("CREATE DATABASE") for sql in executed)
    assert "START TRANSACTION" in executed
    assert "COMMIT" in executed
    assert not any(sql.startswith("DROP DATABASE") for sql in executed)
    assert any("RELEASE_LOCK" in sql for _, sql, _ in session.calls)


@pytest.mark.asyncio
async def test_execute_failure_rolls_back_drops_incomplete_target_and_releases():
    session = TargetSession()

    async def initializer(*args):
        return None

    async def inserter(*args, **kwargs):
        raise RuntimeError("insert failed")

    with pytest.raises(RuntimeError, match="insert failed"):
        await bootstrap.bootstrap_writer_core_product(
            session,
            database_name=PRODUCT,
            source_loader=inventory,
            execute=True,
            confirm_bootstrap=PRODUCT,
            initializer=initializer,
            inserter=inserter,
            _product_authority=bootstrap._CLI_PRODUCT_EXECUTE_AUTHORITY,
        )

    executed = [sql for kind, sql, _ in session.calls if kind == "execute"]
    assert "ROLLBACK" in executed
    assert any(sql == "DROP DATABASE IF EXISTS `novel_creator`" for sql in executed)
    assert any("RELEASE_LOCK" in sql for _, sql, _ in session.calls)


@pytest.mark.asyncio
async def test_commit_failure_rolls_back_drops_incomplete_target_and_releases():
    session = TargetSession(fail_execute_contains="COMMIT")

    async def initializer(*args):
        return None

    async def inserter(*args, **kwargs):
        return None

    with pytest.raises(RuntimeError, match="COMMIT"):
        await bootstrap.bootstrap_writer_core_product(
            session,
            database_name=PRODUCT,
            source_loader=inventory,
            execute=True,
            confirm_bootstrap=PRODUCT,
            initializer=initializer,
            inserter=inserter,
            _product_authority=bootstrap._CLI_PRODUCT_EXECUTE_AUTHORITY,
        )

    executed = [sql for kind, sql, _ in session.calls if kind == "execute"]
    assert "ROLLBACK" in executed
    assert "DROP DATABASE IF EXISTS `novel_creator`" in executed
    assert any("RELEASE_LOCK" in sql for _, sql, _ in session.calls)


@pytest.mark.asyncio
async def test_verification_failure_preserves_error_rolls_back_drops_and_releases():
    session = TargetSession()
    session.foundation_counts["task_model_binding_items"] = 7

    async def initializer(*args):
        return None

    async def inserter(*args, **kwargs):
        return None

    with pytest.raises(
        bootstrap.BootstrapError,
        match="Bootstrap verification failed for task_model_binding_items",
    ):
        await bootstrap.bootstrap_writer_core_product(
            session,
            database_name=PRODUCT,
            source_loader=inventory,
            execute=True,
            confirm_bootstrap=PRODUCT,
            initializer=initializer,
            inserter=inserter,
            _product_authority=bootstrap._CLI_PRODUCT_EXECUTE_AUTHORITY,
        )

    executed = [sql for kind, sql, _ in session.calls if kind == "execute"]
    assert "ROLLBACK" in executed
    assert "DROP DATABASE IF EXISTS `novel_creator`" in executed
    assert any("RELEASE_LOCK" in sql for _, sql, _ in session.calls)


@pytest.mark.asyncio
async def test_create_failure_never_drops_a_target_not_owned_by_bootstrap():
    session = TargetSession(fail_execute_contains="CREATE DATABASE")

    with pytest.raises(RuntimeError, match="CREATE DATABASE"):
        await bootstrap.bootstrap_writer_core_product(
            session,
            database_name=PRODUCT,
            source_loader=inventory,
            execute=True,
            confirm_bootstrap=PRODUCT,
            _product_authority=bootstrap._CLI_PRODUCT_EXECUTE_AUTHORITY,
        )

    executed = [sql for kind, sql, _ in session.calls if kind == "execute"]
    assert any(sql.startswith("CREATE DATABASE") for sql in executed)
    assert not any(sql.startswith("DROP DATABASE") for sql in executed)
    assert any("RELEASE_LOCK" in sql for _, sql, _ in session.calls)


@pytest.mark.asyncio
async def test_execute_preserves_body_rollback_drop_and_release_failures():
    class CleanupFailureSession(TargetSession):
        async def execute(self, sql, parameters=None):
            normalized = " ".join(sql.split())
            self.calls.append(("execute", normalized, parameters))
            if normalized in {"ROLLBACK", "DROP DATABASE IF EXISTS `novel_creator`"}:
                raise RuntimeError(f"{normalized} failed")

        async def fetchone(self, sql, parameters=None):
            if "RELEASE_LOCK" in sql:
                raise RuntimeError("release failed")
            return await super().fetchone(sql, parameters)

    async def initializer(*args):
        return None

    async def inserter(*args, **kwargs):
        raise RuntimeError("insert failed")

    with pytest.raises(BaseExceptionGroup) as raised:
        await bootstrap.bootstrap_writer_core_product(
            CleanupFailureSession(),
            database_name=PRODUCT,
            source_loader=inventory,
            execute=True,
            confirm_bootstrap=PRODUCT,
            initializer=initializer,
            inserter=inserter,
            _product_authority=bootstrap._CLI_PRODUCT_EXECUTE_AUTHORITY,
        )

    assert [str(error) for error in raised.value.exceptions] == [
        "insert failed",
        "ROLLBACK failed",
        "DROP DATABASE IF EXISTS `novel_creator` failed",
        "release failed",
    ]


@pytest.mark.asyncio
async def test_run_cli_uses_injected_connections_and_closes_target():
    session = TargetSession()
    captured = []

    async def connection_factory(config):
        captured.append(config)
        return session

    result = await bootstrap.run_cli(
        ["--mysql-client", "C:/mysql57/bin/mysql.exe"],
        connection_factory=connection_factory,
        connection_config={
            "host": "TARGET_DSN_SENTINEL",
            "port": 3307,
            "user": "root",
            "password": "TARGET_PASSWORD_SENTINEL",
            "db": PRODUCT,
        },
        source_reader=lambda *args, **kwargs: inventory(),
        output=lambda message: None,
    )

    assert result == 0
    assert captured[0]["password"] == "TARGET_PASSWORD_SENTINEL"
    assert session.closed is True


@pytest.mark.asyncio
async def test_run_cli_preserves_core_and_target_close_failures():
    body_error = None
    close_error = RuntimeError("target close failed")

    class FailingCloseSession(TargetSession):
        async def close(self):
            raise close_error

    session = FailingCloseSession(target_exists=True)

    async def connection_factory(config):
        return session

    with pytest.raises(BaseExceptionGroup) as raised:
        await bootstrap.run_cli(
            ["--mysql-client", "C:/mysql57/bin/mysql.exe"],
            connection_factory=connection_factory,
            connection_config={"db": PRODUCT, "password": "test-only"},
            source_reader=lambda *args, **kwargs: inventory(),
            output=lambda message: None,
        )

    body_error = raised.value.exceptions[0]
    assert isinstance(body_error, bootstrap.BootstrapSafetyError)
    assert raised.value.exceptions[1] is close_error


def test_cli_help_is_side_effect_free():
    result = subprocess.run(
        [sys.executable, "-m", "backend.scripts.bootstrap_writer_core_product", "--help"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert result.stderr == ""


def test_main_runtime_failure_is_generic_and_secret_free(monkeypatch, capsys):
    def fail_run(coroutine):
        coroutine.close()
        raise RuntimeError(SECRET_VALUES[0])

    monkeypatch.setattr(bootstrap.asyncio, "run", fail_run)

    assert bootstrap.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Writer Core product bootstrap failed.\n"
    assert SECRET_VALUES[0] not in captured.err
