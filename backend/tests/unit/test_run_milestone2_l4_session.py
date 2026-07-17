import asyncio
from pathlib import Path
import tempfile
import threading
import time

import pytest


TEST_ENV = {
    "TEST_MYSQL_HOST": "127.0.0.1",
    "TEST_MYSQL_PORT": "3308",
    "TEST_MYSQL_USER": "tester",
    "TEST_MYSQL_PASSWORD": "test-password",
    "MYSQL_HOST": "product-host-must-not-be-used",
    "MYSQL_PASSWORD": "product-password-must-not-be-used",
}
DATABASE = "novel_creator_test_0123456789abcdef0123456789abcdef"


class FakeChild:
    def __init__(self, name, events, *, wait_error=None):
        self.name = name
        self.events = events
        self.wait_error = wait_error
        self.returncode = None

    def terminate(self):
        self.events.append(f"terminate:{self.name}")

    def wait(self, timeout=None):
        self.events.append(f"wait:{self.name}")
        if self.wait_error:
            raise self.wait_error
        self.returncode = 0
        return 0

    def poll(self):
        self.events.append(f"poll:{self.name}")
        return self.returncode


def source_fixture(tmp_path):
    root = tmp_path / "external-corpus"
    root.mkdir()
    source = root / "approved.txt"
    source.write_text("合成授权语料，不含真实正文。", encoding="utf-8")
    return root, source


@pytest.mark.asyncio
async def test_l4_session_uses_only_test_authority_and_cleans_in_strict_order(workspace_tmp_path):
    from backend.scripts.run_milestone2_l4_session import run_l4_session

    tmp_path = workspace_tmp_path
    root, _ = source_fixture(tmp_path)
    events = []
    child_envs = []
    database_envs = []
    commands = []

    async def prepare(database, env, log_dir):
        events.append(f"prepare:{database}")
        database_envs.append(dict(env))

    def start(label, command, args, cwd, env, log_dir):
        events.append(f"start:{label}")
        commands.append((label, command, args))
        child_envs.append(dict(env))
        return FakeChild(label, events)

    async def health(label, url, child, **_kwargs):
        events.append(f"health:{label}")

    async def wait_for_input(prompt):
        events.append("input")

    async def verify(database, source_hash, env, log_dir):
        events.append(f"verify:{database}:{source_hash}")
        return {
            "sourceHash": source_hash,
            "chapterCount": 2,
            "fragmentCount": 4,
            "fileSize": (root / "approved.txt").stat().st_size,
            "versions": {
                "parser": "p", "normalizer": "n", "fragmenter": "f", "index": "i",
            },
        }

    def scan(log_dir, values):
        events.append("scan")
        assert "test-password" in values
        assert str(root.resolve()) in values
        assert any(value.startswith("mysql://") for value in values)
        return 0

    async def drop(database, env, log_dir):
        events.append(f"drop:{database}")
        database_envs.append(dict(env))

    def remove(path):
        events.append("remove-temp")

    receipt = await run_l4_session(
        corpus_root=root,
        relative_file="approved.txt",
        environment=TEST_ENV,
        database_name_factory=lambda: DATABASE,
        nonce_factory=lambda: "strict-order-nonce",
        temp_parent=tmp_path,
        temp_dir_factory=lambda prefix: Path(str(prefix) + "logs"),
        prepare=prepare,
        start_process=start,
        wait_for_health=health,
        wait_for_input=wait_for_input,
        verifier=verify,
        scan_logs=scan,
        drop=drop,
        remove_temp=remove,
        output=lambda _value: None,
    )

    assert receipt["remaining_database"] == 0
    assert receipt["remaining_processes"] == 0
    assert receipt["remaining_temp_paths"] == 0
    assert all(env["MYSQL_DB"] == DATABASE for env in child_envs)
    assert all(env["MYSQL_HOST"] == "127.0.0.1" for env in child_envs)
    assert all("product-host" not in str(env) for env in child_envs)
    assert all(not any(key.startswith("TEST_MYSQL_") for key in env) for env in child_envs)
    assert database_envs == [
        {key: TEST_ENV[key] for key in (
            "TEST_MYSQL_HOST",
            "TEST_MYSQL_PORT",
            "TEST_MYSQL_USER",
            "TEST_MYSQL_PASSWORD",
        )}
    ] * 2
    assert all(not any(key.startswith("MYSQL_") for key in env) for env in database_envs)
    assert commands[0][1] != commands[1][1]
    assert Path(commands[1][1]).name.lower() in {"node", "node.exe"}
    assert commands[1][2][0].endswith("vite.js")
    assert events.index("terminate:vite") < events.index("wait:vite") < events.index("scan")
    assert events.index("terminate:backend") < events.index("wait:backend") < events.index("scan")
    assert events.index(f"drop:{DATABASE}") < events.index("scan") < events.index("remove-temp")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "environment,match",
    [
        ({key: value for key, value in TEST_ENV.items() if key != "TEST_MYSQL_PASSWORD"}, "TEST_MYSQL_PASSWORD"),
        ({**TEST_ENV, "TEST_MYSQL_PORT": "not-a-port"}, "TEST_MYSQL_PORT"),
    ],
)
async def test_l4_session_rejects_invalid_test_authority_before_process_start(
    workspace_tmp_path, environment, match
):
    from backend.scripts.run_milestone2_l4_session import L4SessionSafetyError, run_l4_session

    tmp_path = workspace_tmp_path
    root, _ = source_fixture(tmp_path)
    started = []
    with pytest.raises(L4SessionSafetyError, match=match):
        await run_l4_session(
            corpus_root=root,
            relative_file="approved.txt",
            environment=environment,
            start_process=lambda *args: started.append(args),
        )
    assert started == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "database",
    ["novel_creator", "novel_creator_test_short", "novel_creator_test_" + "A" * 32],
)
async def test_l4_session_refuses_non_disposable_database_name(workspace_tmp_path, database):
    from backend.scripts.run_milestone2_l4_session import L4SessionSafetyError, run_l4_session

    tmp_path = workspace_tmp_path
    root, _ = source_fixture(tmp_path)
    with pytest.raises(L4SessionSafetyError, match="non-disposable"):
        await run_l4_session(
            corpus_root=root,
            relative_file="approved.txt",
            environment=TEST_ENV,
            database_name_factory=lambda: database,
            temp_dir_factory=lambda: tmp_path / "logs",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("relative_file", ["missing.txt", "../outside.txt", "C:/private.txt"])
async def test_l4_session_refuses_missing_or_outside_source(workspace_tmp_path, relative_file):
    from backend.scripts.run_milestone2_l4_session import L4SessionSafetyError, run_l4_session

    tmp_path = workspace_tmp_path
    root, _ = source_fixture(tmp_path)
    with pytest.raises(L4SessionSafetyError, match="authorized corpus"):
        await run_l4_session(
            corpus_root=root,
            relative_file=relative_file,
            environment=TEST_ENV,
            database_name_factory=lambda: DATABASE,
            temp_dir_factory=lambda: tmp_path / "logs",
        )


@pytest.mark.asyncio
async def test_ctrl_c_and_cleanup_failure_are_both_reported_without_skipping_drop(workspace_tmp_path):
    from backend.scripts.run_milestone2_l4_session import run_l4_session

    tmp_path = workspace_tmp_path
    root, _ = source_fixture(tmp_path)
    events = []

    def start(label, *args):
        return FakeChild(label, events, wait_error=RuntimeError("wait failed") if label == "vite" else None)

    async def interrupt(_prompt):
        raise KeyboardInterrupt("operator cancelled")

    async def drop(database, env, log_dir):
        events.append(f"drop:{database}")

    with pytest.raises(BaseExceptionGroup) as raised:
        await run_l4_session(
            corpus_root=root,
            relative_file="approved.txt",
            environment=TEST_ENV,
            database_name_factory=lambda: DATABASE,
            nonce_factory=lambda: "cleanup-nonce",
            temp_parent=tmp_path,
            temp_dir_factory=lambda prefix: Path(str(prefix) + "logs"),
            prepare=lambda *args: _async_none(),
            start_process=start,
            wait_for_health=lambda *args, **kwargs: _async_none(),
            wait_for_input=interrupt,
            verifier=lambda *args: _async_none(),
            scan_logs=lambda *_args: 0,
            drop=drop,
            remove_temp=lambda _path: events.append("remove-temp"),
            output=lambda _value: None,
        )

    messages = repr(raised.value)
    assert "operator cancelled" in messages
    assert "wait failed" in messages
    assert f"drop:{DATABASE}" in events
    assert "remove-temp" in events


async def _async_none():
    return None


class FakeReservation:
    def __init__(self, port, events):
        self.port = port
        self.events = events

    def release(self):
        self.events.append(f"release:{self.port}")


@pytest.mark.asyncio
async def test_l4_owns_ports_nonce_minimal_child_env_liveness_and_final_evidence():
    from backend.scripts.run_milestone2_l4_session import run_l4_session

    with tempfile.TemporaryDirectory(prefix="m2e-l4-external-") as directory:
        root = Path(directory) / "corpus"
        root.mkdir()
        source = root / "approved.txt"
        source.write_text("跨块非ASCII秘密：典镇山河", encoding="utf-8")
        events = []
        child_envs = []
        reservations = iter((
            FakeReservation(43101, events), FakeReservation(43102, events),
        ))
        children = {}

        class OwnedChild(FakeChild):
            def __init__(self, label):
                super().__init__(label, events)
                self.returncode = None

            def poll(self):
                events.append(f"poll:{self.name}")
                return self.returncode

        def start(label, command, args, cwd, env, log_dir):
            events.append(f"start:{label}")
            child_envs.append(dict(env))
            child = OwnedChild(label)
            children[label] = child
            return child

        async def health(label, url, child, *, expected_nonce, timeout_seconds):
            events.append(f"health:{label}:{url}:{expected_nonce}:{timeout_seconds}")

        async def wait_for_input(_prompt):
            events.append("input")

        verification = {
            "sourceHash": "ignored-by-test-double",
            "chapterCount": 2,
            "fragmentCount": 4,
            "fileSize": source.stat().st_size,
            "versions": {
                "parser": "p1", "normalizer": "n1",
                "fragmenter": "f1", "index": "i1",
            },
        }

        async def verifier(database, source_hash, env, log_dir):
            events.append("verify")
            return {**verification, "sourceHash": source_hash}

        async def drop(database, env, log_dir):
            events.append("drop")

        def scan(log_dir, values):
            events.append("scan")
            assert "test-password" in values
            return 0

        nonce = "owned-l4-nonce"
        temp_parent = Path(tempfile.gettempdir()).resolve()
        receipt = await run_l4_session(
            corpus_root=root,
            relative_file="approved.txt",
            environment={
                **TEST_ENV,
                "GITHUB_TOKEN": "PARENT_TOKEN_MUST_NOT_ENTER_CHILD",
                "VITE_SECRET": "PARENT_VITE_SECRET_MUST_NOT_ENTER_CHILD",
                "PATH": "safe-path",
                "SystemRoot": "C:/Windows",
            },
            database_name_factory=lambda: DATABASE,
            nonce_factory=lambda: nonce,
            port_reservation_factory=lambda: next(reservations),
            temp_parent=temp_parent,
            temp_dir_factory=lambda prefix: tempfile.mkdtemp(
                prefix=Path(prefix).name, dir=temp_parent
            ),
            prepare=lambda *args: _async_none(),
            start_process=start,
            wait_for_health=health,
            wait_for_input=wait_for_input,
            verifier=verifier,
            scan_logs=scan,
            drop=drop,
            output=lambda _value: None,
        )

    assert events.index("release:43101") < events.index("start:backend")
    assert events.index("release:43102") < events.index("start:vite")
    assert any("/api/health" in event and nonce in event for event in events)
    assert any("/__m2-browser-owner" in event and nonce in event for event in events)
    assert events.index("drop") < events.index("scan")
    assert events.count("poll:backend") >= 3
    assert events.count("poll:vite") >= 3
    for env in child_envs:
        assert env["M2_BROWSER_RUN_NONCE"] == nonce
        assert env["PYTHONUTF8"] == "1"
        assert env["PYTHONIOENCODING"] == "utf-8"
        assert env["MYSQL_PASSWORD"] == "test-password"
        assert "TEST_MYSQL_PASSWORD" not in env
        assert "GITHUB_TOKEN" not in env
        assert "VITE_SECRET" not in env
    assert receipt["verification"] == {
        **verification,
        "sourceHash": receipt["sourceHash"],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["parent", "outside", "wrong-prefix", "empty-suffix"])
async def test_l4_refuses_temp_directory_not_owned_by_this_nonce(shape):
    from backend.scripts.run_milestone2_l4_session import L4SessionSafetyError, run_l4_session

    with tempfile.TemporaryDirectory(prefix="m2e-l4-source-") as source_directory, tempfile.TemporaryDirectory(prefix="m2e-l4-parent-") as temp_directory:
        root = Path(source_directory)
        (root / "approved.txt").write_text("synthetic", encoding="utf-8")
        parent = Path(temp_directory).resolve()
        removed = []
        events = []
        reservations = iter((FakeReservation(43201, events), FakeReservation(43202, events)))

        def bad_factory(prefix):
            prefix = Path(prefix)
            if shape == "parent":
                return parent
            if shape == "outside":
                return Path(source_directory)
            if shape == "wrong-prefix":
                path = parent / "another-run-suffix"
            else:
                path = parent / prefix.name.rstrip("-")
            path.mkdir(exist_ok=True)
            return path

        with pytest.raises(L4SessionSafetyError, match="owned temporary"):
            await run_l4_session(
                corpus_root=root,
                relative_file="approved.txt",
                environment=TEST_ENV,
                database_name_factory=lambda: DATABASE,
                nonce_factory=lambda: "owned-temp-nonce",
                port_reservation_factory=lambda: next(reservations),
                temp_parent=parent,
                temp_dir_factory=bad_factory,
                remove_temp=lambda path: removed.append(path),
                prepare=lambda *args: _async_none(),
            )
        assert removed == []
        assert events == ["release:43201", "release:43202"]


@pytest.mark.asyncio
async def test_l4_releases_first_reservation_when_second_acquisition_fails():
    from backend.scripts.run_milestone2_l4_session import run_l4_session

    with tempfile.TemporaryDirectory(prefix="m2e-l4-reservation-source-") as directory:
        root = Path(directory)
        (root / "approved.txt").write_text("synthetic", encoding="utf-8")
        events = []
        first = FakeReservation(43301, events)
        calls = 0

        def reserve():
            nonlocal calls
            calls += 1
            if calls == 1:
                return first
            raise RuntimeError("second reservation failed")

        with pytest.raises(RuntimeError, match="second reservation"):
            await run_l4_session(
                corpus_root=root,
                relative_file="approved.txt",
                environment=TEST_ENV,
                database_name_factory=lambda: DATABASE,
                port_reservation_factory=reserve,
            )
        assert events == ["release:43301"]


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["relative-root", "symlink-escape"])
async def test_l4_rejects_non_external_or_symlinked_corpus_authority(shape, monkeypatch):
    from backend.scripts.run_milestone2_l4_session import L4SessionSafetyError, run_l4_session

    with tempfile.TemporaryDirectory(prefix="m2e-l4-authority-") as directory:
        external = Path(directory)
        relative_file = "approved.txt"
        if shape == "relative-root":
            root = Path("relative-corpus")
        else:
            root = external / "root"
            root.mkdir()
            outside = external / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            source_candidate = root / "approved.txt"
            original_resolve = Path.resolve

            def escaped_resolve(path, *args, **kwargs):
                if path == source_candidate:
                    return outside.resolve()
                return original_resolve(path, *args, **kwargs)

            monkeypatch.setattr(Path, "resolve", escaped_resolve)

        async def forbidden_prepare(*_args):
            raise AssertionError("invalid corpus authority reached prepare")

        with pytest.raises(L4SessionSafetyError, match="corpus"):
            await run_l4_session(
                corpus_root=root,
                relative_file=relative_file,
                environment=TEST_ENV,
                database_name_factory=lambda: DATABASE,
                prepare=forbidden_prepare,
                drop=lambda *args: _async_none(),
                scan_logs=lambda *_args: 0,
            )


def test_log_scanner_streams_nonascii_across_chunks_and_rejects_oversize(workspace_tmp_path):
    from backend.scripts.run_milestone2_l4_session import (
        L4SessionSafetyError,
        default_scan_logs,
    )

    log_dir = workspace_tmp_path / "logs"
    log_dir.mkdir()
    secret = "典镇山河秘密"
    payload = b"x" * 7 + secret.encode("utf-8") + b"tail"
    (log_dir / "cross.log").write_bytes(payload)
    assert default_scan_logs(
        log_dir, {secret}, chunk_size=8, max_total_bytes=1024,
    ) == 1
    (log_dir / "huge.log").write_bytes(b"z" * 128)
    with pytest.raises(L4SessionSafetyError, match="size"):
        default_scan_logs(log_dir, {secret}, chunk_size=8, max_total_bytes=64)


@pytest.mark.asyncio
async def test_captured_command_timeout_owns_and_zeroes_parent_and_descendant(
    monkeypatch, workspace_tmp_path,
):
    from subprocess import TimeoutExpired
    from backend.scripts.run_milestone2_l4_session import _run_captured

    events = []

    class ControlledChild:
        pid = 7001
        returncode = None
        descendant_alive = True

        def poll(self):
            events.append("poll")
            return self.returncode

        def capture_descendant_pids(self):
            events.append("capture")
            return {7002} if self.descendant_alive else set()

        def terminate(self):
            events.append("terminate")

        def wait(self, timeout=None):
            events.append(f"wait:{timeout}")
            self.returncode = 0
            return 0

        def kill_tree(self, pids):
            events.append(f"kill-tree:{sorted(pids)}")
            self.descendant_alive = False

        def pid_is_alive(self, pid):
            return pid == 7002 and self.descendant_alive

    child = ControlledChild()
    monkeypatch.setattr(
        "backend.scripts.run_milestone2_l4_session.subprocess.Popen",
        lambda *args, **kwargs: child,
    )
    with pytest.raises(TimeoutExpired):
        await _run_captured(
            "bounded", ["python", "-V"], Path.cwd(), {}, workspace_tmp_path,
            timeout_seconds=0,
        )
    assert any(event.startswith("kill-tree:") and "7002" in event for event in events)
    assert child.returncode == 0
    assert child.descendant_alive is False


@pytest.mark.asyncio
async def test_captured_command_cancellation_settles_owned_tree_before_propagating(
    monkeypatch, workspace_tmp_path,
):
    from backend.scripts.run_milestone2_l4_session import _run_captured

    events = []

    class ControlledChild:
        pid = 7101
        returncode = None
        descendant_alive = True

        def poll(self):
            return self.returncode

        def capture_descendant_pids(self):
            return {7102} if self.descendant_alive else set()

        def terminate(self):
            events.append("terminate")

        def wait(self, timeout=None):
            events.append(f"wait:{timeout}")
            self.returncode = 0
            return 0

        def kill_tree(self, pids):
            events.append("kill-tree")
            self.descendant_alive = False

        def pid_is_alive(self, pid):
            return pid == 7102 and self.descendant_alive

    child = ControlledChild()
    monkeypatch.setattr(
        "backend.scripts.run_milestone2_l4_session.subprocess.Popen",
        lambda *args, **kwargs: child,
    )
    task = asyncio.create_task(_run_captured(
        "cancelled", ["python", "-V"], Path.cwd(), {}, workspace_tmp_path,
        timeout_seconds=30,
    ))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ["terminate", "wait:10", "kill-tree", "wait:5"]
    assert child.returncode == 0
    assert child.descendant_alive is False


@pytest.mark.asyncio
async def test_captured_guard_owns_orphan_when_parent_exits_before_cleanup(
    monkeypatch, workspace_tmp_path,
):
    from backend.scripts.run_milestone2_l4_session import _run_captured

    events = []

    class ParentExitsAfterFirstPoll:
        pid = 7151
        returncode = None
        descendant_alive = True

        def poll(self):
            self.returncode = 0
            events.append("parent-exit")
            return 0

        def wait(self, timeout=None):
            return 0

    child = ParentExitsAfterFirstPoll()

    class Guard:
        def cleanup(self, _child, **_kwargs):
            events.append("cleanup-owned-group")
            child.descendant_alive = False
            return []

    def attach(_child):
        events.append("attach-owned-group")
        return Guard()

    monkeypatch.setattr(
        "backend.scripts.run_milestone2_l4_session.subprocess.Popen",
        lambda *_args, **_kwargs: child,
    )
    await _run_captured(
        "tracked", ["python", "-V"], Path.cwd(), {}, workspace_tmp_path,
        timeout_seconds=5, process_guard_factory=attach,
    )
    assert events.index("attach-owned-group") < events.index("parent-exit")
    assert "cleanup-owned-group" in events
    assert child.descendant_alive is False


@pytest.mark.asyncio
async def test_captured_command_does_not_use_toolhelp_descendant_capture_for_ownership(
    monkeypatch, workspace_tmp_path,
):
    from backend.scripts.run_milestone2_l4_session import _run_captured

    class Child:
        pid = 7161
        returncode = None

        def poll(self):
            self.returncode = 0
            return 0

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(
        "backend.scripts.run_milestone2_l4_session.subprocess.Popen",
        lambda *_args, **_kwargs: Child(),
    )
    monkeypatch.setattr(
        "backend.scripts.run_milestone2_l4_session._capture_descendant_pids",
        lambda _child: (_ for _ in ()).throw(RuntimeError("capture denied")),
    )
    await _run_captured(
        "capture-not-authority", ["python", "-V"], Path.cwd(), {}, workspace_tmp_path,
        timeout_seconds=5,
    )


def test_process_cleanup_uses_tree_kill_and_proves_exit_after_grace_timeout():
    from backend.scripts.run_milestone2_l4_session import _stop_process

    events = []

    class StubbornChild:
        returncode = None
        wait_count = 0

        def terminate(self):
            events.append("terminate")

        def wait(self, timeout=None):
            events.append(f"wait:{timeout}")
            self.wait_count += 1
            if self.wait_count == 1:
                raise TimeoutError("still alive")
            self.returncode = 0
            return 0

        def kill_tree(self, _pids=None):
            events.append("kill-tree")

        def poll(self):
            events.append("poll")
            return self.returncode

    errors = _stop_process(StubbornChild())
    assert errors == []
    assert events[:3] == ["terminate", "wait:10", "kill-tree"]
    assert events[-1] == "poll"


def test_process_cleanup_kills_captured_descendant_when_parent_already_exited():
    from backend.scripts.run_milestone2_l4_session import _stop_process

    events = []

    class ExitedParentWithLiveChild:
        pid = 7201
        returncode = 0
        child_alive = True

        def poll(self):
            events.append("poll-parent")
            return 0

        def capture_descendant_pids(self):
            events.append("capture-child")
            return {7202} if self.child_alive else set()

        def terminate(self):
            raise AssertionError("exited parent must not be terminated again")

        def wait(self, timeout=None):
            events.append(f"wait-parent:{timeout}")
            return 0

        def kill_tree(self, pids):
            events.append(f"kill-tree:{sorted(pids)}")
            self.child_alive = False

        def pid_is_alive(self, pid):
            events.append(f"probe:{pid}")
            return pid == 7202 and self.child_alive

    child = ExitedParentWithLiveChild()
    assert _stop_process(child) == []
    assert "kill-tree:[7202]" in events
    assert child.child_alive is False


@pytest.mark.parametrize("failure_point", ["first", "next"])
def test_windows_toolhelp_enumeration_errors_fail_closed(monkeypatch, failure_point):
    import ctypes
    from backend.scripts.run_milestone2_l4_session import (
        L4SessionSafetyError,
        _windows_parent_map,
    )

    class Function:
        def __init__(self, callback):
            self.callback = callback

        def __call__(self, *args):
            return self.callback(*args)

    class Kernel32:
        def __init__(self):
            self.CreateToolhelp32Snapshot = Function(lambda *_args: 123)
            self.Process32FirstW = Function(self.first)
            self.Process32NextW = Function(self.next)
            self.CloseHandle = Function(lambda _handle: 1)

        def first(self, _snapshot, pointer):
            if failure_point == "first":
                return 0
            pointer._obj.th32ProcessID = 9001
            pointer._obj.th32ParentProcessID = 9000
            return 1

        def next(self, _snapshot, _pointer):
            return 0

    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: Kernel32())
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5)
    with pytest.raises(L4SessionSafetyError, match="Toolhelp"):
        _windows_parent_map()


def test_default_manual_input_cancellation_does_not_wait_for_blocked_worker(monkeypatch):
    from backend.scripts.run_milestone2_l4_session import default_wait_for_input

    release = threading.Event()

    def blocked_input(_prompt):
        release.wait(timeout=1.0)
        return ""

    monkeypatch.setattr("builtins.input", blocked_input)

    async def scenario():
        task = asyncio.create_task(default_wait_for_input("prompt"))
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    started = time.monotonic()
    try:
        asyncio.run(scenario())
    finally:
        release.set()
    assert time.monotonic() - started < 0.3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "label,payload",
    [
        ("backend", {"browserRunNonce": "health-nonce"}),
        ("vite", {"ok": True, "browserRunNonce": "health-nonce"}),
    ],
)
async def test_health_verification_rejects_endpoint_shape_confusion(
    monkeypatch, label, payload,
):
    import json
    from backend.scripts.run_milestone2_l4_session import (
        L4SessionSafetyError,
        default_wait_for_health,
    )

    class Response:
        status = 200

        def read(self, _size):
            return json.dumps(payload).encode("utf-8")

        def close(self):
            return None

    class Child:
        def poll(self):
            return None

    monkeypatch.setattr(
        "backend.scripts.run_milestone2_l4_session.urlopen",
        lambda *_args: Response(),
    )
    with pytest.raises(L4SessionSafetyError, match="ownership.*shape"):
        await default_wait_for_health(
            label,
            "http://127.0.0.1/owner",
            Child(),
            expected_nonce="health-nonce",
            timeout_seconds=0.2,
        )


@pytest.mark.asyncio
async def test_l4_rechecks_liveness_after_manual_input_and_still_runs_cleanup():
    from backend.scripts.run_milestone2_l4_session import run_l4_session

    with tempfile.TemporaryDirectory(prefix="m2e-l4-liveness-source-") as source_directory, tempfile.TemporaryDirectory(prefix="m2e-l4-liveness-temp-") as temp_directory:
        root = Path(source_directory)
        (root / "approved.txt").write_text("synthetic", encoding="utf-8")
        children = {}
        events = []

        class Child(FakeChild):
            pass

        def start(label, *args):
            child = Child(label, events)
            children[label] = child
            return child

        async def manual(_prompt):
            events.append("input")
            children["backend"].returncode = 7

        async def forbidden_verifier(*_args):
            raise AssertionError("dead service reached verifier")

        async def drop(*_args):
            events.append("drop")

        with pytest.raises(RuntimeError, match="backend.*exited"):
            await run_l4_session(
                corpus_root=root,
                relative_file="approved.txt",
                environment=TEST_ENV,
                database_name_factory=lambda: DATABASE,
                nonce_factory=lambda: "liveness-nonce",
                temp_parent=Path(temp_directory),
                temp_dir_factory=lambda prefix: tempfile.mkdtemp(
                    prefix=Path(prefix).name, dir=temp_directory
                ),
                prepare=lambda *_args: _async_none(),
                start_process=start,
                wait_for_health=lambda *_args, **_kwargs: _async_none(),
                wait_for_input=manual,
                verifier=forbidden_verifier,
                drop=drop,
                scan_logs=lambda *_args: 0,
                output=lambda _value: None,
            )
        assert "drop" in events


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "verification",
    [
        {
            "sourceHash": "b" * 64,
            "chapterCount": 2,
            "fragmentCount": 4,
            "fileSize": 9,
            "versions": {"parser": "p", "normalizer": "n", "fragmenter": "f", "index": "i"},
        },
        {
            "sourceHash": "a" * 64,
            "chapterCount": 2,
            "fragmentCount": 4,
            "fileSize": 9,
            "versions": {"parser": "p", "normalizer": "n", "fragmenter": "f", "index": "i"},
            "notes": "must-not-enter-receipt",
        },
    ],
)
async def test_l4_rejects_mismatched_or_non_allowlisted_verifier_receipt(verification):
    from backend.scripts.run_milestone2_l4_session import L4SessionSafetyError, run_l4_session

    with tempfile.TemporaryDirectory(prefix="m2e-l4-receipt-source-") as source_directory, tempfile.TemporaryDirectory(prefix="m2e-l4-receipt-temp-") as temp_directory:
        root = Path(source_directory)
        source = root / "approved.txt"
        source.write_text("synthetic", encoding="utf-8")
        source_hash = __import__("hashlib").sha256(source.read_bytes()).hexdigest()
        verification = {**verification, "sourceHash": (
            verification["sourceHash"] if verification["sourceHash"] != "a" * 64 else source_hash
        )}

        with pytest.raises(L4SessionSafetyError, match="verification"):
            await run_l4_session(
                corpus_root=root,
                relative_file="approved.txt",
                environment=TEST_ENV,
                database_name_factory=lambda: DATABASE,
                nonce_factory=lambda: "receipt-nonce",
                temp_parent=Path(temp_directory),
                temp_dir_factory=lambda prefix: tempfile.mkdtemp(
                    prefix=Path(prefix).name, dir=temp_directory
                ),
                prepare=lambda *_args: _async_none(),
                start_process=lambda label, *args: FakeChild(label, []),
                wait_for_health=lambda *_args, **_kwargs: _async_none(),
                wait_for_input=lambda _prompt: _async_none(),
                verifier=lambda *_args: _async_value(verification),
                drop=lambda *_args: _async_none(),
                scan_logs=lambda *_args: 0,
                output=lambda _value: None,
            )


@pytest.mark.asyncio
async def test_l4_timeout_still_drops_then_scans_and_removes_owned_temp():
    from subprocess import TimeoutExpired
    from backend.scripts.run_milestone2_l4_session import run_l4_session

    with tempfile.TemporaryDirectory(prefix="m2e-l4-timeout-source-") as source_directory, tempfile.TemporaryDirectory(prefix="m2e-l4-timeout-temp-") as temp_directory:
        root = Path(source_directory)
        (root / "approved.txt").write_text("synthetic", encoding="utf-8")
        events = []

        async def timeout_prepare(*_args):
            raise TimeoutExpired("prepare", 1)

        async def drop(*_args):
            events.append("drop")

        def scan(*_args):
            events.append("scan")
            return 0

        with pytest.raises(TimeoutExpired):
            await run_l4_session(
                corpus_root=root,
                relative_file="approved.txt",
                environment=TEST_ENV,
                database_name_factory=lambda: DATABASE,
                nonce_factory=lambda: "timeout-nonce",
                temp_parent=Path(temp_directory),
                temp_dir_factory=lambda prefix: tempfile.mkdtemp(
                    prefix=Path(prefix).name, dir=temp_directory
                ),
                prepare=timeout_prepare,
                drop=drop,
                scan_logs=scan,
                remove_temp=lambda _path: events.append("remove"),
                output=lambda _value: None,
            )
        assert events == ["drop", "scan", "remove"]


async def _async_value(value):
    return value


class _FakeJobApi:
    def __init__(self, active_counts=(0,), *, assign_error=None):
        self.active_counts = iter(active_counts)
        self.last_active = 0
        self.assign_error = assign_error
        self.events = []

    def create_kill_on_close_job(self):
        self.events.append("create-job")
        return "owned-job-handle"

    def assign(self, job, child):
        self.events.append(("assign", job, child))
        if self.assign_error is not None:
            raise self.assign_error

    def terminate(self, job):
        self.events.append(("terminate-job", job))

    def active_processes(self, job):
        self.events.append(("query-job", job))
        try:
            self.last_active = next(self.active_counts)
        except StopIteration:
            pass
        return self.last_active

    def close(self, job):
        self.events.append(("close-job", job))


def test_windows_job_guard_owns_orphan_after_parent_exit_without_pid_kill():
    from backend.scripts.run_milestone2_l4_session import WindowsJobProcessGuard

    child = type("ExitedParent", (), {"pid": 7301, "returncode": 0})()
    api = _FakeJobApi((1, 0))
    guard = WindowsJobProcessGuard.attach(child, api=api)

    assert guard.cleanup(child, grace_seconds=0, kill_seconds=0.05) == []
    assert ("terminate-job", "owned-job-handle") in api.events
    assert ("close-job", "owned-job-handle") in api.events
    assert all(event != 7301 for event in api.events)


def test_windows_job_guard_fails_closed_when_active_processes_never_reach_zero():
    from backend.scripts.run_milestone2_l4_session import WindowsJobProcessGuard

    child = type("Child", (), {"pid": 7311, "returncode": 0})()
    api = _FakeJobApi((1,))
    guard = WindowsJobProcessGuard.attach(child, api=api)

    errors = guard.cleanup(child, grace_seconds=0, kill_seconds=0)

    assert any("active" in str(error).lower() for error in errors)
    assert ("close-job", "owned-job-handle") in api.events


def test_windows_job_guard_assignment_failure_closes_job_and_never_targets_reused_pid():
    from backend.scripts.run_milestone2_l4_session import WindowsJobProcessGuard

    child = type("Child", (), {"pid": 7321, "returncode": None})()
    api = _FakeJobApi(assign_error=OSError("assign denied"))

    with pytest.raises(OSError, match="assign denied"):
        WindowsJobProcessGuard.attach(child, api=api)

    assert ("close-job", "owned-job-handle") in api.events
    assert not any(
        isinstance(event, tuple) and event[0] == "terminate-job"
        for event in api.events
    )


def test_posix_group_guard_kills_saved_group_when_parent_already_exited():
    from backend.scripts.run_milestone2_l4_session import PosixProcessGroupGuard

    class FakeOs:
        def __init__(self):
            self.alive = True
            self.events = []

        def getpgid(self, pid):
            self.events.append(("getpgid", pid))
            return 7401

        def killpg(self, pgid, signal_number):
            self.events.append(("killpg", pgid, signal_number))
            if signal_number == 0 and not self.alive:
                raise ProcessLookupError
            if signal_number != 0:
                self.alive = False

    child = type("ExitedParent", (), {"pid": 7401, "returncode": 0})()
    fake_os = FakeOs()
    guard = PosixProcessGroupGuard.attach(child, os_module=fake_os)

    assert guard.cleanup(child, grace_seconds=0, kill_seconds=0) == []
    assert any(event[:2] == ("killpg", 7401) for event in fake_os.events)


def test_create_owned_temp_rolls_back_directory_created_before_factory_raises(
    workspace_tmp_path,
):
    from backend.scripts.run_milestone2_l4_session import _create_owned_temp

    parent = workspace_tmp_path.resolve()
    created = parent / "novel-creator-m2-l4-factory-failure-new"

    def factory(_prefix):
        created.mkdir()
        raise RuntimeError("factory failed after mkdir")

    with pytest.raises(RuntimeError, match="factory failed"):
        _create_owned_temp(parent, "factory-failure", "l4", factory)

    assert not created.exists()


def test_create_owned_temp_rolls_back_partial_sentinel_write(
    monkeypatch, workspace_tmp_path,
):
    from backend.scripts.run_milestone2_l4_session import (
        _TEMP_SENTINEL,
        _create_owned_temp,
    )

    parent = workspace_tmp_path.resolve()
    created = parent / "novel-creator-m2-l4-sentinel-failure-new"
    original_write_text = Path.write_text

    def partial_write(path, value, *args, **kwargs):
        if path.name == _TEMP_SENTINEL:
            original_write_text(path, "partial", encoding="utf-8")
            raise OSError("sentinel write failed")
        return original_write_text(path, value, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", partial_write)
    with pytest.raises(OSError, match="sentinel write failed"):
        _create_owned_temp(
            parent,
            "sentinel-failure",
            "l4",
            lambda _prefix: created,
        )

    assert not created.exists()


def test_create_owned_temp_aggregates_setup_and_safe_rmdir_failure(
    monkeypatch, workspace_tmp_path,
):
    from backend.scripts.run_milestone2_l4_session import _create_owned_temp

    parent = workspace_tmp_path.resolve()
    created = parent / "novel-creator-m2-l4-rmdir-failure-new"
    original_rmdir = Path.rmdir

    def factory(_prefix):
        created.mkdir()
        raise RuntimeError("factory failed")

    def failing_rmdir(path):
        if path == created:
            raise OSError("rmdir failed")
        return original_rmdir(path)

    monkeypatch.setattr(Path, "rmdir", failing_rmdir)
    with pytest.raises(BaseExceptionGroup) as raised:
        _create_owned_temp(parent, "rmdir-failure", "l4", factory)

    rendered = repr(raised.value)
    assert "factory failed" in rendered
    assert "rmdir failed" in rendered


@pytest.mark.asyncio
async def test_l4_temp_setup_aggregates_factory_cleanup_and_reservation_release_failures(
    monkeypatch, workspace_tmp_path,
):
    from backend.scripts.run_milestone2_l4_session import run_l4_session

    root, _source = source_fixture(workspace_tmp_path)
    parent = workspace_tmp_path.resolve()
    created = parent / "novel-creator-m2-l4-setup-errors-new"
    starts = []
    original_rmdir = Path.rmdir
    reservations = iter((
        type("Reservation", (), {
            "port": 45001,
            "release": lambda self: (_ for _ in ()).throw(OSError("release one failed")),
        })(),
        type("Reservation", (), {
            "port": 45002,
            "release": lambda self: (_ for _ in ()).throw(OSError("release two failed")),
        })(),
    ))

    def factory(_prefix):
        created.mkdir()
        raise RuntimeError("factory failed")

    def failing_rmdir(path):
        if path == created:
            raise OSError("rmdir failed")
        return original_rmdir(path)

    monkeypatch.setattr(Path, "rmdir", failing_rmdir)
    with pytest.raises(BaseExceptionGroup) as raised:
        await run_l4_session(
            corpus_root=root,
            relative_file="approved.txt",
            environment=TEST_ENV,
            database_name_factory=lambda: DATABASE,
            nonce_factory=lambda: "setup-errors",
            port_reservation_factory=lambda: next(reservations),
            temp_parent=parent,
            temp_dir_factory=factory,
            start_process=lambda *args: starts.append(args),
        )

    rendered = repr(raised.value)
    for message in (
        "factory failed", "rmdir failed", "release one failed", "release two failed",
    ):
        assert message in rendered
    assert starts == []


@pytest.mark.asyncio
async def test_captured_assigns_guard_immediately_and_cleans_it_after_parent_exit(
    monkeypatch, workspace_tmp_path,
):
    from backend.scripts.run_milestone2_l4_session import _run_captured

    events = []

    class Child:
        pid = 7501
        returncode = None

        def poll(self):
            events.append("poll")
            self.returncode = 0
            return 0

    class Guard:
        def cleanup(self, child, **_kwargs):
            events.append(("cleanup-guard", child.pid))
            return []

    child = Child()
    monkeypatch.setattr(
        "backend.scripts.run_milestone2_l4_session.subprocess.Popen",
        lambda *_args, **_kwargs: child,
    )

    await _run_captured(
        "guarded", ["python", "-V"], Path.cwd(), {}, workspace_tmp_path,
        process_guard_factory=lambda assigned: (
            events.append(("assign-guard", assigned.pid)) or Guard()
        ),
    )

    assert events.index(("assign-guard", 7501)) < events.index("poll")
    assert ("cleanup-guard", 7501) in events


@pytest.mark.asyncio
async def test_l4_guard_assignment_failure_stops_spawned_child_and_never_reaches_health(
    workspace_tmp_path,
):
    from backend.scripts.run_milestone2_l4_session import run_l4_session

    root, _source = source_fixture(workspace_tmp_path)
    events = []

    class SpawnedChild(FakeChild):
        def kill(self):
            events.append("kill:backend")
            self.returncode = 1

    def start(label, *_args):
        events.append(f"start:{label}")
        return SpawnedChild(label, events)

    def assign(_child):
        events.append("assign")
        raise OSError("guard assignment failed")

    with pytest.raises(OSError, match="guard assignment failed"):
        await run_l4_session(
            corpus_root=root,
            relative_file="approved.txt",
            environment=TEST_ENV,
            database_name_factory=lambda: DATABASE,
            nonce_factory=lambda: "guard-assignment",
            temp_parent=workspace_tmp_path,
            temp_dir_factory=lambda prefix: Path(str(prefix) + "logs"),
            prepare=lambda *_args: _async_none(),
            start_process=start,
            process_guard_factory=assign,
            wait_for_health=lambda *_args, **_kwargs: events.append("health"),
            drop=lambda *_args: _async_none(),
            scan_logs=lambda *_args: 0,
            output=lambda _value: None,
        )

    assert "health" not in events
    assert "terminate:backend" in events
    assert "wait:backend" in events


def test_posix_group_guard_reaps_parent_before_treating_zombie_group_as_live():
    from backend.scripts.run_milestone2_l4_session import PosixProcessGroupGuard

    events = []

    class FakeOs:
        def getpgid(self, pid):
            return pid

        def killpg(self, pgid, signal_number):
            events.append(("killpg", signal_number))
            if signal_number == 0 and child.returncode is not None:
                raise ProcessLookupError

    class ZombieParent:
        pid = 7601
        returncode = None

        def poll(self):
            events.append("poll-reap")
            self.returncode = 0
            return 0

        def wait(self, timeout=None):
            events.append(("wait", timeout))
            self.returncode = 0
            return 0

    child = ZombieParent()
    guard = PosixProcessGroupGuard.attach(child, os_module=FakeOs())

    assert guard.cleanup(child, grace_seconds=0.05, kill_seconds=0.05) == []
    assert ("killpg", 0) in events
    assert "poll-reap" in events
    assert ("killpg", 9) not in events


def test_posix_group_guard_reaps_again_after_sigkill_before_final_esrch_proof():
    from backend.scripts.run_milestone2_l4_session import PosixProcessGroupGuard

    events = []
    killed = False

    class FakeOs:
        def getpgid(self, pid):
            return pid

        def killpg(self, pgid, signal_number):
            nonlocal killed
            events.append(("killpg", signal_number))
            if signal_number == 9:
                killed = True
            if signal_number == 0 and child.returncode is not None:
                raise ProcessLookupError

    class StubbornParent:
        pid = 7602
        returncode = None

        def poll(self):
            events.append("poll")
            if killed:
                self.returncode = -9
            return self.returncode

        def wait(self, timeout=None):
            events.append(("wait", timeout))
            return self.poll()

    child = StubbornParent()
    guard = PosixProcessGroupGuard.attach(child, os_module=FakeOs())

    assert guard.cleanup(child, grace_seconds=0, kill_seconds=0.05) == []
    assert ("killpg", 9) in events
    assert events.index(("killpg", 9)) < max(
        index for index, event in enumerate(events) if event == "poll"
    )
    assert events[-1] == ("killpg", 0)


def test_windows_guarded_spawn_suspends_assigns_then_resumes_before_poll():
    from backend.scripts.run_milestone2_l4_session import _spawn_guarded_process

    events = []

    class Child:
        pid = 7701
        _handle = 88
        returncode = None

        def poll(self):
            events.append("poll")
            return self.returncode

    child = Child()

    class Guard:
        def cleanup(self, _child, **_kwargs):
            events.append("cleanup-job")
            return []

    def popen(command, **kwargs):
        events.append(("spawn", kwargs["creationflags"]))
        return child

    def attach(assigned):
        assert assigned is child
        events.append("assign-job")
        return Guard()

    spawned, guard = _spawn_guarded_process(
        ["python", "-V"],
        {"creationflags": 0},
        process_guard_factory=attach,
        popen_factory=popen,
        platform_name="nt",
        windows_resume=lambda assigned: events.append("resume-main-thread"),
    )
    spawned.poll()

    assert guard is spawned._m2_process_guard
    assert events[0][0] == "spawn"
    assert events[0][1] & 0x00000004
    assert events.index("assign-job") < events.index("resume-main-thread") < events.index("poll")


def test_windows_guarded_spawn_assignment_failure_cleans_suspended_child_without_resume():
    from backend.scripts.run_milestone2_l4_session import _spawn_guarded_process

    events = []

    class Child:
        pid = 7702
        _handle = 89
        returncode = None

        def terminate(self):
            events.append("terminate-direct-handle")
            self.returncode = 1

        def wait(self, timeout=None):
            events.append(("wait", timeout))
            return self.returncode

        def poll(self):
            events.append("poll")
            return self.returncode

    child = Child()
    with pytest.raises(OSError, match="assign failed"):
        _spawn_guarded_process(
            ["python", "-V"],
            {"creationflags": 0},
            process_guard_factory=lambda _child: (_ for _ in ()).throw(
                OSError("assign failed")
            ),
            popen_factory=lambda *_args, **_kwargs: child,
            platform_name="nt",
            windows_resume=lambda _child: events.append("resume-main-thread"),
        )

    assert "resume-main-thread" not in events
    assert events[:2] == ["terminate-direct-handle", ("wait", 5)]
    assert child.returncode is not None


def test_windows_guarded_spawn_resume_failure_terminates_owned_job_and_proves_zero():
    from backend.scripts.run_milestone2_l4_session import _spawn_guarded_process

    events = []

    class Child:
        pid = 7703
        _handle = 90
        returncode = None

        def wait(self, timeout=None):
            events.append(("wait", timeout))
            return self.returncode

        def poll(self):
            events.append("poll")
            return self.returncode

    child = Child()

    class Guard:
        def cleanup(self, assigned, **_kwargs):
            events.append("terminate-job")
            assigned.returncode = 1
            assigned.wait(timeout=5)
            events.append("active-processes-zero")
            events.append("close-job")
            return []

    def attach(_child):
        events.append("assign-job")
        return Guard()

    with pytest.raises(OSError, match="Toolhelp enumeration failed"):
        _spawn_guarded_process(
            ["python", "-V"],
            {"creationflags": 0},
            process_guard_factory=attach,
            popen_factory=lambda *_args, **_kwargs: child,
            platform_name="nt",
            windows_resume=lambda _child: (_ for _ in ()).throw(
                OSError("Toolhelp enumeration failed")
            ),
        )

    assert events == [
        "assign-job", "terminate-job", ("wait", 5),
        "active-processes-zero", "close-job",
    ]
    assert child.returncode is not None
