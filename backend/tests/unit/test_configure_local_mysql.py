import asyncio
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


class FakeMutexAPI:
    def __init__(
        self,
        *,
        handle=91,
        wait_result=0,
        release_result=True,
        close_result=True,
        fail_at=None,
    ):
        self.handle = handle
        self.wait_result = wait_result
        self.release_result = release_result
        self.close_result = close_result
        self.fail_at = fail_at
        self.events = []

    def _event(self, name, value=None):
        self.events.append(name if value is None else (name, value))
        if self.fail_at == name:
            raise RuntimeError(f"private-mutex-{name}-{SECRET}")

    def create_mutex(self, name):
        self._event("create", name)
        return self.handle

    def wait(self, handle):
        self._event("wait", handle)
        return self.wait_result

    def release(self, handle):
        self._event("release", handle)
        return self.release_result

    def close(self, handle):
        self._event("close", handle)
        return self.close_result


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


def test_mutex_non_windows_fails_before_api_create(workspace_tmp_path):
    api = FakeMutexAPI()
    with pytest.raises(setup.LocalMySQLSetupError, match="Windows"):
        with setup._windows_local_config_mutex(
            workspace_tmp_path / ".env.local.json",
            platform_name="posix",
            api=api,
        ):
            pytest.fail("unsupported mutex body entered")
    assert api.events == []


def test_mutex_create_null_fails_without_wait_release_or_close(workspace_tmp_path):
    api = FakeMutexAPI(handle=None)
    with pytest.raises(setup.LocalMySQLSetupError, match="lock"):
        with setup._windows_local_config_mutex(
            workspace_tmp_path / ".env.local.json", platform_name="nt", api=api
        ):
            pytest.fail("null mutex body entered")
    assert [event[0] if isinstance(event, tuple) else event for event in api.events] == [
        "create"
    ]


@pytest.mark.parametrize("wait_result", (0x00000102, 0xFFFFFFFF))
def test_mutex_timeout_and_wait_failed_close_without_release(
    workspace_tmp_path, wait_result
):
    api = FakeMutexAPI(wait_result=wait_result)
    with pytest.raises(setup.LocalMySQLSetupError, match="lock"):
        with setup._windows_local_config_mutex(
            workspace_tmp_path / ".env.local.json", platform_name="nt", api=api
        ):
            pytest.fail("unacquired mutex body entered")
    assert [event[0] if isinstance(event, tuple) else event for event in api.events] == [
        "create", "wait", "close"
    ]


def test_mutex_abandoned_fails_closed_but_releases_and_closes(workspace_tmp_path):
    api = FakeMutexAPI(wait_result=0x00000080)
    with pytest.raises(setup.LocalMySQLSetupError, match="abandoned"):
        with setup._windows_local_config_mutex(
            workspace_tmp_path / ".env.local.json", platform_name="nt", api=api
        ):
            pytest.fail("abandoned mutex body entered")
    assert [event[0] if isinstance(event, tuple) else event for event in api.events] == [
        "create", "wait", "release", "close"
    ]


def test_mutex_success_enters_body_then_releases_and_closes(workspace_tmp_path):
    api = FakeMutexAPI()
    with setup._windows_local_config_mutex(
        workspace_tmp_path / ".env.local.json", platform_name="nt", api=api
    ):
        api.events.append("body")
    assert [event[0] if isinstance(event, tuple) else event for event in api.events] == [
        "create", "wait", "body", "release", "close"
    ]


@pytest.mark.parametrize(
    "primary_factory",
    (lambda: RuntimeError("primary"), asyncio.CancelledError, KeyboardInterrupt, SystemExit),
)
def test_mutex_body_primary_stays_first_when_release_and_close_fail(
    workspace_tmp_path, primary_factory
):
    api = FakeMutexAPI(release_result=False, close_result=False)
    primary = primary_factory()
    with pytest.raises(BaseExceptionGroup) as raised:
        with setup._windows_local_config_mutex(
            workspace_tmp_path / ".env.local.json", platform_name="nt", api=api
        ):
            raise primary
    assert raised.value.exceptions[0] is primary
    assert isinstance(raised.value.exceptions[1], setup.LocalMySQLSetupError)
    assert isinstance(raised.value.exceptions[2], setup.LocalMySQLSetupError)
    assert [event[0] if isinstance(event, tuple) else event for event in api.events] == [
        "create", "wait", "release", "close"
    ]


@pytest.mark.parametrize(
    ("release_result", "close_result", "expected_messages"),
    (
        (False, True, ("unlock",)),
        (True, False, ("close",)),
        (False, False, ("unlock", "close")),
    ),
)
def test_mutex_cleanup_only_failures_keep_release_then_close_order(
    workspace_tmp_path, release_result, close_result, expected_messages
):
    api = FakeMutexAPI(
        release_result=release_result,
        close_result=close_result,
    )
    with pytest.raises(BaseException) as raised:
        with setup._windows_local_config_mutex(
            workspace_tmp_path / ".env.local.json", platform_name="nt", api=api
        ):
            pass
    failures = (
        raised.value.exceptions
        if isinstance(raised.value, BaseExceptionGroup)
        else (raised.value,)
    )
    assert tuple(str(error).split()[2] for error in failures) == expected_messages


def test_mutex_wait_primary_precedes_close_cleanup_failure(workspace_tmp_path):
    api = FakeMutexAPI(wait_result=0xFFFFFFFF, close_result=False)
    with pytest.raises(BaseExceptionGroup) as raised:
        with setup._windows_local_config_mutex(
            workspace_tmp_path / ".env.local.json", platform_name="nt", api=api
        ):
            pytest.fail("wait failure body entered")
    assert "lock" in str(raised.value.exceptions[0])
    assert "close" in str(raised.value.exceptions[1])
    assert all(SECRET not in repr(error) for error in raised.value.exceptions)


@pytest.mark.parametrize("fail_at", ("create", "wait", "release", "close"))
def test_mutex_api_exceptions_are_fixed_and_secret_free(workspace_tmp_path, fail_at):
    api = FakeMutexAPI(fail_at=fail_at)
    with pytest.raises(BaseException) as raised:
        with setup._windows_local_config_mutex(
            workspace_tmp_path / ".env.local.json", platform_name="nt", api=api
        ):
            pass
    assert SECRET not in repr(raised.value)
    assert "private-mutex" not in repr(raised.value)
    names = [event[0] if isinstance(event, tuple) else event for event in api.events]
    assert names == {
        "create": ["create"],
        "wait": ["create", "wait", "close"],
        "release": ["create", "wait", "release", "close"],
        "close": ["create", "wait", "release", "close"],
    }[fail_at]


def test_mutex_name_is_normalized_stable_distinct_and_opaque(workspace_tmp_path):
    target = workspace_tmp_path / "secret-folder" / ".env.local.json"
    same = workspace_tmp_path / "secret-folder" / "." / ".env.local.json"
    same_case_folded = workspace_tmp_path / "SECRET-FOLDER" / ".ENV.LOCAL.JSON"
    other = workspace_tmp_path / "secret-folder" / "other.json"
    first = setup._local_config_mutex_name(target)
    assert first == setup._local_config_mutex_name(same)
    assert first == setup._local_config_mutex_name(same_case_folded)
    assert first != setup._local_config_mutex_name(other)
    assert str(target) not in first
    assert "secret-folder" not in first


def test_mutex_contention_leaves_target_and_temp_unchanged(workspace_tmp_path):
    target = workspace_tmp_path / ".env.local.json"
    document = {
        "MYSQL_HOST": "127.0.0.1",
        "MYSQL_PORT": 3307,
        "MYSQL_USER": "root",
        "MYSQL_PASSWORD": SECRET,
        "MYSQL_DB": "novel_creator",
    }
    target.write_text(json.dumps(document), encoding="utf-8")
    snapshot = setup.capture_local_document_snapshot(target)
    api = FakeMutexAPI(wait_result=0x00000102)
    acl_calls = []

    with pytest.raises(setup.LocalMySQLSetupError, match="locked"):
        setup.atomic_compare_and_swap_local_document(
            target,
            {**document, "MYSQL_DB": "novel_creator_v113"},
            lambda path: acl_calls.append(path),
            snapshot,
            mutex_api=api,
            platform_name="nt",
        )

    assert json.loads(target.read_text(encoding="utf-8")) == document
    assert acl_calls == []
    assert list(workspace_tmp_path.iterdir()) == [target]


def _required_document(database="novel_creator"):
    return {
        "MYSQL_HOST": "127.0.0.1",
        "MYSQL_PORT": 3307,
        "MYSQL_USER": "root",
        "MYSQL_PASSWORD": SECRET,
        "MYSQL_DB": database,
    }


def _failing_temp_removal(_path):
    raise RuntimeError(f"private-cleanup-{SECRET}")


@pytest.mark.parametrize("failure_point", ("acl", "write", "replace"))
def test_compatibility_writer_keeps_operation_primary_before_unlink_failure(
    workspace_tmp_path, monkeypatch, failure_point
):
    target = workspace_tmp_path / ".env.local.json"
    target.write_text(json.dumps(_required_document()), encoding="utf-8")

    def fail_operation(*_args, **_kwargs):
        raise RuntimeError(f"private-{failure_point}-{SECRET}")

    acl = fail_operation if failure_point == "acl" else lambda _path: None
    replacer = fail_operation if failure_point == "replace" else setup.os.replace
    if failure_point == "write":
        monkeypatch.setattr(setup.json, "dump", fail_operation)

    with pytest.raises(BaseExceptionGroup) as raised:
        setup.atomic_write_local_config(
            target,
            _required_document("novel_creator_v113"),
            acl,
            remove_temp=_failing_temp_removal,
            replacer=replacer,
        )

    assert len(raised.value.exceptions) == 2
    assert "save" in str(raised.value.exceptions[0])
    assert "remove" in str(raised.value.exceptions[1])
    assert SECRET not in repr(raised.value)


@pytest.mark.parametrize(
    "failure_point", ("acl", "write", "before_publish", "replace")
)
def test_cas_writer_keeps_operation_primary_before_unlink_failure(
    workspace_tmp_path, monkeypatch, failure_point
):
    target = workspace_tmp_path / ".env.local.json"
    target.write_text(json.dumps(_required_document()), encoding="utf-8")
    snapshot = setup.capture_local_document_snapshot(target)

    def fail_operation(*_args, **_kwargs):
        raise RuntimeError(f"private-{failure_point}-{SECRET}")

    acl = fail_operation if failure_point == "acl" else lambda _path: None
    before_publish = fail_operation if failure_point == "before_publish" else None
    replacer = fail_operation if failure_point == "replace" else setup.os.replace
    if failure_point == "write":
        monkeypatch.setattr(setup.json, "dump", fail_operation)

    with pytest.raises(BaseExceptionGroup) as raised:
        setup.atomic_compare_and_swap_local_document(
            target,
            _required_document("novel_creator_v113"),
            acl,
            snapshot,
            before_publish=before_publish,
            mutex_api=FakeMutexAPI(),
            platform_name="nt",
            remove_temp=_failing_temp_removal,
            replacer=replacer,
        )

    assert len(raised.value.exceptions) == 2
    assert "save" in str(raised.value.exceptions[0])
    assert "remove" in str(raised.value.exceptions[1])
    assert SECRET not in repr(raised.value)


@pytest.mark.parametrize(
    ("writer_kind", "failure_point"),
    (
        ("compatibility", "acl"),
        ("compatibility", "write"),
        ("compatibility", "replace"),
        ("cas", "acl"),
        ("cas", "write"),
        ("cas", "before_publish"),
        ("cas", "replace"),
    ),
)
@pytest.mark.parametrize(
    "flow_factory",
    (
        lambda: asyncio.CancelledError(f"private-cancel-{SECRET}"),
        lambda: KeyboardInterrupt(f"private-keyboard-{SECRET}"),
        lambda: SystemExit(f"private-exit-{SECRET}"),
    ),
)
def test_writer_flow_primary_is_sanitized_and_first_when_unlink_fails(
    workspace_tmp_path, monkeypatch, writer_kind, failure_point, flow_factory
):
    target = workspace_tmp_path / ".env.local.json"
    target.write_text(json.dumps(_required_document()), encoding="utf-8")
    snapshot = setup.capture_local_document_snapshot(target)
    flow = flow_factory()

    def raise_flow(*_args, **_kwargs):
        raise flow

    acl = raise_flow if failure_point == "acl" else lambda _path: None
    replacer = raise_flow if failure_point == "replace" else setup.os.replace
    if failure_point == "write":
        monkeypatch.setattr(setup.json, "dump", raise_flow)

    with pytest.raises(BaseExceptionGroup) as raised:
        if writer_kind == "compatibility":
            setup.atomic_write_local_config(
                target,
                _required_document("novel_creator_v113"),
                acl,
                mutex_api=FakeMutexAPI(),
                platform_name="nt",
                remove_temp=_failing_temp_removal,
                replacer=replacer,
            )
        else:
            setup.atomic_compare_and_swap_local_document(
                target,
                _required_document("novel_creator_v113"),
                acl,
                snapshot,
                before_publish=(
                    raise_flow if failure_point == "before_publish" else None
                ),
                mutex_api=FakeMutexAPI(),
                platform_name="nt",
                remove_temp=_failing_temp_removal,
                replacer=replacer,
            )

    primary, cleanup = raised.value.exceptions
    assert type(primary) is type(flow)
    assert primary.args == ()
    assert primary.__cause__ is None
    assert primary.__context__ is None
    assert isinstance(cleanup, setup.LocalMySQLSetupError)
    assert SECRET not in repr(raised.value)


@pytest.mark.parametrize(
    "cleanup_factory",
    (
        lambda: RuntimeError(f"private-cleanup-{SECRET}"),
        lambda: setup.LocalMySQLSetupError("Local MySQL configuration changed"),
    ),
)
def test_ordinary_cleanup_only_failure_is_one_fixed_secret_free_error(
    cleanup_factory,
):
    with pytest.raises(setup.LocalMySQLSetupError, match="remove") as raised:
        setup._raise_publication_failures(
            None,
            [cleanup_factory()],
        )
    assert raised.value.args == ("Could not remove an unpublished local configuration",)
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert SECRET not in repr(raised.value)


@pytest.mark.parametrize(
    ("cleanup_factory", "expected_type", "expected_args", "expected_code"),
    (
        (
            lambda: asyncio.CancelledError(f"private-cleanup-{SECRET}"),
            asyncio.CancelledError,
            (),
            None,
        ),
        (
            lambda: KeyboardInterrupt(f"private-cleanup-{SECRET}"),
            KeyboardInterrupt,
            (),
            None,
        ),
        (lambda: SystemExit(23), SystemExit, (23,), 23),
        (
            lambda: SystemExit(f"private-cleanup-{SECRET}"),
            SystemExit,
            (),
            None,
        ),
    ),
)
def test_cleanup_only_flow_is_sanitized_and_raised_directly(
    cleanup_factory, expected_type, expected_args, expected_code
):
    with pytest.raises(expected_type) as raised:
        setup._raise_publication_failures(None, [cleanup_factory()])

    assert raised.value.args == expected_args
    assert getattr(raised.value, "code", None) == expected_code
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert SECRET not in repr(raised.value)


@pytest.mark.parametrize("writer_kind", ("compatibility", "cas"))
@pytest.mark.parametrize(
    ("cleanup_factory", "expected_type", "expected_args", "expected_code"),
    (
        (
            lambda: asyncio.CancelledError(f"private-cleanup-{SECRET}"),
            asyncio.CancelledError,
            (),
            None,
        ),
        (
            lambda: KeyboardInterrupt(f"private-cleanup-{SECRET}"),
            KeyboardInterrupt,
            (),
            None,
        ),
        (lambda: SystemExit(31), SystemExit, (31,), 31),
        (
            lambda: SystemExit(f"private-cleanup-{SECRET}"),
            SystemExit,
            (),
            None,
        ),
    ),
)
def test_writer_keeps_ordinary_primary_first_and_sanitized_cleanup_flow_second(
    workspace_tmp_path,
    writer_kind,
    cleanup_factory,
    expected_type,
    expected_args,
    expected_code,
):
    target = workspace_tmp_path / ".env.local.json"
    target.write_text(json.dumps(_required_document()), encoding="utf-8")
    snapshot = setup.capture_local_document_snapshot(target)

    def fail_operation(*_args):
        raise RuntimeError(f"private-operation-{SECRET}")

    def fail_cleanup(_path):
        raise cleanup_factory()

    with pytest.raises(BaseExceptionGroup) as raised:
        if writer_kind == "compatibility":
            setup.atomic_write_local_config(
                target,
                _required_document("novel_creator_v113"),
                fail_operation,
                mutex_api=FakeMutexAPI(),
                platform_name="nt",
                remove_temp=fail_cleanup,
            )
        else:
            setup.atomic_compare_and_swap_local_document(
                target,
                _required_document("novel_creator_v113"),
                lambda _path: None,
                snapshot,
                before_publish=fail_operation,
                mutex_api=FakeMutexAPI(),
                platform_name="nt",
                remove_temp=fail_cleanup,
            )

    primary, cleanup = raised.value.exceptions
    assert isinstance(primary, setup.LocalMySQLSetupError)
    assert primary.args == ("Could not atomically save the local MySQL configuration",)
    assert type(cleanup) is expected_type
    assert cleanup.args == expected_args
    assert getattr(cleanup, "code", None) == expected_code
    assert primary.__cause__ is primary.__context__ is None
    assert cleanup.__cause__ is cleanup.__context__ is None
    assert SECRET not in repr(raised.value)


def test_atomic_writer_acl_failure_keeps_old_target_and_removes_temp(workspace_tmp_path):
    target = workspace_tmp_path / ".env.local.json"
    target.write_text("old-config", encoding="utf-8")

    observed_before_acl_failure = []

    def acl_runner(temp_path):
        observed_before_acl_failure.append(temp_path.read_bytes())
        raise setup.LocalMySQLSetupError("ACL failed")

    with pytest.raises(setup.LocalMySQLSetupError, match="atomically save"):
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

    with pytest.raises(KeyboardInterrupt) as raised:
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

    assert raised.value.args == ()
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
