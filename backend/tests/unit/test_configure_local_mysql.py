import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from backend.scripts import configure_local_mysql as setup


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SECRET = "local-password-must-not-leak"


class CapabilitySession:
    def __init__(
        self,
        *,
        version="8.4.10",
        collation="utf8mb4_0900_ai_ci",
        json_supported=1,
        check_count=3,
    ):
        self.version = version
        self.collation = collation
        self.json_supported = json_supported
        self.check_count = check_count
        self.calls = []
        self.closed = False

    async def fetchone(self, sql, parameters=None):
        self.calls.append((" ".join(sql.split()), parameters))
        if "VERSION()" in sql:
            return {"version": self.version}
        if "information_schema.COLLATIONS" in sql:
            return {"COLLATION_NAME": self.collation}
        if "JSON_VALID" in sql:
            return {"json_supported": self.json_supported}
        if "information_schema.CHECK_CONSTRAINTS" in sql:
            return {"count": self.check_count}
        raise AssertionError(f"unexpected capability query: {sql}")

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "version",
    (
        "8.4.10",
        "8.0.36-0ubuntu0.22.04.1",
        "8.0.36+commercial_1",
    ),
)
async def test_cli_uses_safe_defaults_full_capability_gate_and_secret_free_output(
    workspace_tmp_path,
    version,
):
    session = CapabilitySession(version=version)
    connector_configs = []
    writes = []
    prompts = []
    output = []
    acl_runner = object()

    async def connector(connection_config):
        connector_configs.append(connection_config)
        return session

    def password_reader(prompt):
        prompts.append(prompt)
        return SECRET

    def file_writer(path, document, injected_acl_runner):
        writes.append((path, document, injected_acl_runner, session.closed))

    result = await setup.run_cli(
        [],
        password_reader=password_reader,
        connector=connector,
        file_writer=file_writer,
        acl_runner=acl_runner,
        config_path=workspace_tmp_path / ".env.local.json",
        output=output.append,
    )

    assert result == 0
    assert prompts == ["MySQL password: "]
    assert connector_configs == [{
        "host": "127.0.0.1",
        "port": 3307,
        "user": "root",
        "password": SECRET,
        "charset": "utf8mb4",
        "autocommit": True,
    }]
    assert "db" not in connector_configs[0]
    assert len(session.calls) == 4
    assert any("VERSION()" in sql for sql, _ in session.calls)
    assert any("utf8mb4_0900_ai_ci" in sql for sql, _ in session.calls)
    assert any("JSON_VALID" in sql for sql, _ in session.calls)
    assert any("CHECK_CONSTRAINTS" in sql for sql, _ in session.calls)
    assert writes == [(
        workspace_tmp_path / ".env.local.json",
        {
            "MYSQL_HOST": "127.0.0.1",
            "MYSQL_PORT": 3307,
            "MYSQL_USER": "root",
            "MYSQL_PASSWORD": SECRET,
            "MYSQL_DB": "novel_creator",
        },
        acl_runner,
        True,
    )]
    rendered = "\n".join(output)
    for public in ("127.0.0.1", "3307", "root", "novel_creator", version):
        assert public in rendered
    assert SECRET not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "session",
    (
        CapabilitySession(version="5.7.44"),
        CapabilitySession(version="8.0.15"),
        CapabilitySession(version="9.0.1"),
        CapabilitySession(version=80410),
        CapabilitySession(version="8.0.16garbage"),
        CapabilitySession(version="8.0.16-"),
        CapabilitySession(version="8.0.16+"),
        CapabilitySession(collation=None),
        CapabilitySession(json_supported=0),
        CapabilitySession(json_supported=True),
        CapabilitySession(json_supported=1.0),
        CapabilitySession(check_count="3"),
    ),
)
async def test_cli_rejects_incompatible_server_before_file_write(workspace_tmp_path, session):
    writes = []

    async def connector(connection_config):
        assert connection_config["password"] == SECRET
        return session

    with pytest.raises(setup.LocalMySQLSetupError):
        await setup.run_cli(
            [],
            password_reader=lambda prompt: SECRET,
            connector=connector,
            file_writer=lambda *args: writes.append(args),
            acl_runner=object(),
            config_path=workspace_tmp_path / ".env.local.json",
            output=lambda message: None,
        )

    assert session.closed is True
    assert writes == []


@pytest.mark.asyncio
async def test_cli_rejects_empty_password_before_connector(workspace_tmp_path):
    connected = False

    async def connector(connection_config):
        nonlocal connected
        connected = True

    with pytest.raises(setup.LocalMySQLSetupError, match="password"):
        await setup.run_cli(
            [],
            password_reader=lambda prompt: "",
            connector=connector,
            file_writer=lambda *args: None,
            acl_runner=object(),
            config_path=workspace_tmp_path / ".env.local.json",
        )

    assert connected is False


def test_atomic_writer_restricts_temp_before_same_directory_replace(workspace_tmp_path):
    target = workspace_tmp_path / ".env.local.json"
    target.write_text("old-config", encoding="utf-8")
    events = []
    document = {
        "MYSQL_HOST": "127.0.0.1",
        "MYSQL_PORT": 3307,
        "MYSQL_USER": "root",
        "MYSQL_PASSWORD": SECRET,
        "MYSQL_DB": "novel_creator",
    }

    def acl_runner(temp_path):
        events.append((temp_path, temp_path.parent, target.read_text(encoding="utf-8")))
        assert temp_path.exists()
        assert temp_path != target
        assert temp_path.name.startswith(".env.local.")
        assert temp_path.name.endswith(".tmp")
        assert temp_path.read_bytes() == b""

    setup.atomic_write_local_config(target, document, acl_runner)

    assert len(events) == 1
    assert events[0][1] == target.parent
    assert events[0][2] == "old-config"
    assert json.loads(target.read_text(encoding="utf-8")) == document
    assert list(workspace_tmp_path.iterdir()) == [target]


def test_atomic_document_writer_preserves_allowed_optional_corpus_roots(workspace_tmp_path):
    target = workspace_tmp_path / ".env.local.json"
    document = {
        "MYSQL_HOST": "127.0.0.1",
        "MYSQL_PORT": 3307,
        "MYSQL_USER": "root",
        "MYSQL_PASSWORD": SECRET,
        "MYSQL_DB": "novel_creator_v113",
        "CORPUS_ROOT": "D:/corpus",
        "MANAGED_CORPUS_ROOT": "D:/managed-corpus",
    }

    setup.atomic_write_local_document(target, document, lambda _path: None)

    assert json.loads(target.read_text(encoding="utf-8")) == document


@pytest.mark.parametrize(
    "document",
    (
        {
            "MYSQL_HOST": "127.0.0.1",
            "MYSQL_PORT": 3307,
            "MYSQL_USER": "root",
            "MYSQL_PASSWORD": SECRET,
            "MYSQL_DB": "novel_creator",
            "UNKNOWN": "rejected",
        },
        {
            "MYSQL_HOST": "127.0.0.1",
            "MYSQL_PORT": 3307,
            "MYSQL_USER": "root",
            "MYSQL_PASSWORD": SECRET,
            "MYSQL_DB": "novel_creator",
            "CORPUS_ROOT": "D:/corpus",
            "UNKNOWN": "rejected",
        },
        {
            "MYSQL_HOST": "127.0.0.1",
            "MYSQL_PORT": 3307,
            "MYSQL_USER": "root",
            "MYSQL_PASSWORD": SECRET,
            "MYSQL_DB": "novel_creator",
            "CORPUS_ROOT": "D:/corpus",
            "MANAGED_CORPUS_ROOT": "D:/managed-corpus",
            "EXTRA_CORPUS_ROOT": "D:/extra",
        },
    ),
)
def test_atomic_document_writer_rejects_unknown_keys(workspace_tmp_path, document):
    with pytest.raises(setup.LocalMySQLSetupError, match="allowed keys"):
        setup.atomic_write_local_document(
            workspace_tmp_path / ".env.local.json",
            document,
            lambda _path: None,
        )


def test_compatibility_writer_still_rejects_optional_corpus_keys(workspace_tmp_path):
    with pytest.raises(setup.LocalMySQLSetupError, match="exactly five"):
        setup.atomic_write_local_config(
            workspace_tmp_path / ".env.local.json",
            {
                "MYSQL_HOST": "127.0.0.1",
                "MYSQL_PORT": 3307,
                "MYSQL_USER": "root",
                "MYSQL_PASSWORD": SECRET,
                "MYSQL_DB": "novel_creator",
                "CORPUS_ROOT": "D:/corpus",
            },
            lambda _path: None,
        )


def test_compare_and_swap_writer_rejects_changed_snapshot_without_overwrite(
    workspace_tmp_path,
):
    target = workspace_tmp_path / ".env.local.json"
    original = {
        "MYSQL_HOST": "127.0.0.1",
        "MYSQL_PORT": 3307,
        "MYSQL_USER": "root",
        "MYSQL_PASSWORD": SECRET,
        "MYSQL_DB": "novel_creator",
    }
    target.write_text(json.dumps(original), encoding="utf-8")
    snapshot = setup.capture_local_document_snapshot(target)
    concurrent = {**original, "CORPUS_ROOT": "D:/concurrent"}
    target.write_text(json.dumps(concurrent), encoding="utf-8")

    with pytest.raises(setup.LocalMySQLSetupError, match="changed"):
        setup.atomic_compare_and_swap_local_document(
            target,
            {**original, "MYSQL_DB": "novel_creator_v113"},
            lambda _path: None,
            snapshot,
        )

    assert json.loads(target.read_text(encoding="utf-8")) == concurrent


def test_compare_and_swap_final_publish_boundary_preserves_concurrent_replacement(
    workspace_tmp_path,
):
    target = workspace_tmp_path / ".env.local.json"
    original = {
        "MYSQL_HOST": "127.0.0.1",
        "MYSQL_PORT": 3307,
        "MYSQL_USER": "root",
        "MYSQL_PASSWORD": SECRET,
        "MYSQL_DB": "novel_creator",
    }
    target.write_text(json.dumps(original), encoding="utf-8")
    snapshot = setup.capture_local_document_snapshot(target)
    concurrent = {**original, "CORPUS_ROOT": "D:/final-boundary-editor"}

    def replace_at_final_boundary(_temporary_path):
        replacement = workspace_tmp_path / "editor-replacement.json"
        replacement.write_text(json.dumps(concurrent), encoding="utf-8")
        replacement.replace(target)

    with pytest.raises(setup.LocalMySQLSetupError, match="changed"):
        setup.atomic_compare_and_swap_local_document(
            target,
            {**original, "MYSQL_DB": "novel_creator_v113"},
            lambda _path: None,
            snapshot,
            before_publish=replace_at_final_boundary,
        )

    assert json.loads(target.read_text(encoding="utf-8")) == concurrent
    assert list(workspace_tmp_path.iterdir()) == [target]


def test_atomic_writer_acl_failure_keeps_old_target_and_removes_temp(workspace_tmp_path):
    target = workspace_tmp_path / ".env.local.json"
    target.write_text("old-config", encoding="utf-8")

    observed_before_acl_failure = []

    def acl_runner(temp_path):
        observed_before_acl_failure.append(temp_path.read_bytes())
        raise setup.LocalMySQLSetupError("ACL failed")

    with pytest.raises(setup.LocalMySQLSetupError, match="ACL"):
        setup.atomic_write_local_config(
            target,
            {
                "MYSQL_HOST": "127.0.0.1",
                "MYSQL_PORT": 3307,
                "MYSQL_USER": "root",
                "MYSQL_PASSWORD": SECRET,
                "MYSQL_DB": "novel_creator",
            },
            acl_runner,
        )

    assert target.read_text(encoding="utf-8") == "old-config"
    assert observed_before_acl_failure == [b""]
    assert list(workspace_tmp_path.iterdir()) == [target]


def test_interruption_during_acl_never_places_secret_in_temp(workspace_tmp_path):
    target = workspace_tmp_path / ".env.local.json"
    observed_before_interrupt = []

    def interrupt_acl(temp_path):
        observed_before_interrupt.append(temp_path.read_bytes())
        raise KeyboardInterrupt("simulated interruption")

    with pytest.raises(KeyboardInterrupt, match="simulated"):
        setup.atomic_write_local_config(
            target,
            {
                "MYSQL_HOST": "127.0.0.1",
                "MYSQL_PORT": 3307,
                "MYSQL_USER": "root",
                "MYSQL_PASSWORD": SECRET,
                "MYSQL_DB": "novel_creator",
            },
            interrupt_acl,
        )

    assert observed_before_interrupt == [b""]
    assert list(workspace_tmp_path.iterdir()) == []


def test_temporary_secret_file_has_an_explicit_gitignore_rule():
    ignore_lines = (REPOSITORY_ROOT / ".gitignore").read_text(
        encoding="utf-8"
    ).splitlines()

    assert ".env.local.*.tmp" in ignore_lines
    result = subprocess.run(
        ["git", "check-ignore", "-q", ".env.local.security-review.tmp"],
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    assert result.returncode == 0


def test_windows_acl_runner_captures_output_and_fails_closed(workspace_tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    setup.restrict_windows_acl(
        workspace_tmp_path / "private.json",
        runner=runner,
        username="DOMAIN\\writer",
    )

    assert calls == [([
        "icacls",
        str(workspace_tmp_path / "private.json"),
        "/inheritance:r",
        "/grant:r",
        "DOMAIN\\writer:(R,W)",
    ], {
        "capture_output": True,
        "text": True,
        "check": False,
    })]


def test_windows_acl_runner_rejects_nonzero_exit(workspace_tmp_path):
    def runner(command, **kwargs):
        return SimpleNamespace(returncode=5)

    with pytest.raises(setup.LocalMySQLSetupError, match="permissions"):
        setup.restrict_windows_acl(
            workspace_tmp_path / "private.json",
            runner=runner,
            username="writer",
        )


def test_cli_help_exits_zero_without_prompt_or_failure_banner():
    result = subprocess.run(
        [sys.executable, "-m", "backend.scripts.configure_local_mysql", "--help"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert "--password" not in result.stdout
    assert result.stderr == ""


def test_main_converts_runtime_failure_to_generic_secret_free_error(monkeypatch, capsys):
    def fail_run(coroutine):
        coroutine.close()
        raise RuntimeError(SECRET)

    monkeypatch.setattr(setup.asyncio, "run", fail_run)

    assert setup.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Local MySQL configuration failed.\n"
    assert SECRET not in captured.err
