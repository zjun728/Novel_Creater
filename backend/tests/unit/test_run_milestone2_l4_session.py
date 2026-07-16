from pathlib import Path

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

    def terminate(self):
        self.events.append(f"terminate:{self.name}")

    def wait(self, timeout=None):
        self.events.append(f"wait:{self.name}")
        if self.wait_error:
            raise self.wait_error
        return 0


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
    commands = []

    async def prepare(database, env, log_dir):
        events.append(f"prepare:{database}")

    def start(label, command, args, cwd, env, log_dir):
        events.append(f"start:{label}")
        commands.append((label, command, args))
        child_envs.append(env)
        return FakeChild(label, events)

    async def health(label, url, child):
        events.append(f"health:{label}")

    async def wait_for_input(prompt):
        events.append("input")

    async def verify(database, source_hash, env, log_dir):
        events.append(f"verify:{database}:{source_hash}")
        return {"sourceHash": source_hash}

    def scan(log_dir, values):
        events.append("scan")
        assert "test-password" in values
        assert str(root.resolve()) in values
        assert any(value.startswith("mysql://") for value in values)
        return 0

    async def drop(database, env, log_dir):
        events.append(f"drop:{database}")

    def remove(path):
        events.append("remove-temp")

    receipt = await run_l4_session(
        corpus_root=root,
        relative_file="approved.txt",
        environment=TEST_ENV,
        database_name_factory=lambda: DATABASE,
        temp_dir_factory=lambda: tmp_path / "session-logs",
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
    assert commands[0][1] != commands[1][1]
    assert Path(commands[1][1]).name.lower() in {"node", "node.exe"}
    assert commands[1][2][0].endswith("vite.js")
    assert events.index("terminate:vite") < events.index("wait:vite") < events.index("scan")
    assert events.index("terminate:backend") < events.index("wait:backend") < events.index("scan")
    assert events.index("scan") < events.index(f"drop:{DATABASE}") < events.index("remove-temp")


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
            temp_dir_factory=lambda: tmp_path / "logs",
            prepare=lambda *args: _async_none(),
            start_process=start,
            wait_for_health=lambda *args: _async_none(),
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
