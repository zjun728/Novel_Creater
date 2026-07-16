import pytest


DATABASE = "novel_creator"
HASH = "a" * 64


class FakeChild:
    def __init__(self, label, events):
        self.label = label
        self.events = events

    def terminate(self):
        self.events.append(f"terminate:{self.label}")

    def wait(self, timeout=None):
        self.events.append(f"wait:{self.label}")
        return 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,expected_flags",
    [
        ("corpus-import", {"require_assets": True, "require_corpus": True, "require_l5": False}),
        ("provider-l5", {"require_assets": True, "require_corpus": True, "require_l5": True}),
    ],
)
async def test_product_session_is_closed_mode_read_only_and_never_drops(
    workspace_tmp_path, mode, expected_flags
):
    from backend.scripts.run_milestone2_product_session import run_product_session

    events = []
    commands = []
    secrets = {
        "provider-key",
        "https://private-provider.example/v1",
        "db-password",
        "mysql://product-private-dsn",
        "C:/private/corpus-root",
    }

    def start(label, command, args, cwd, env, log_dir):
        events.append(f"start:{label}")
        commands.append((label, command, args))
        return FakeChild(label, events)

    async def sensitive_loader(config, database):
        events.append("load-sensitive")
        assert database == DATABASE
        return secrets

    async def wait_for_input(_prompt):
        events.append("input")

    async def verifier(database, source_hash, flags, environment, log_dir):
        events.append("verify")
        assert database == DATABASE
        assert source_hash == HASH
        assert flags == expected_flags
        return {"ok": True}

    def scan(log_dir, values):
        events.append("scan")
        assert secrets <= set(values)
        return 0

    receipt = await run_product_session(
        mode=mode,
        database=DATABASE,
        confirm_product=DATABASE,
        source_hash=HASH,
        connection_config={
            "host": "127.0.0.1",
            "port": 3307,
            "user": "root",
            "password": "db-password",
            "db": DATABASE,
        },
        environment={"CORPUS_ROOT": "C:/private/corpus-root"},
        temp_dir_factory=lambda: workspace_tmp_path / "product-session",
        sensitive_loader=sensitive_loader,
        start_process=start,
        wait_for_health=lambda *args: _async_none(),
        wait_for_input=wait_for_input,
        verifier=verifier,
        scan_logs=scan,
        remove_temp=lambda _path: events.append("remove-temp"),
        output=lambda _value: None,
    )

    assert receipt["remaining_processes"] == 0
    assert receipt["remaining_temp_paths"] == 0
    assert "drop" not in " ".join(events)
    assert commands[0][1] != commands[1][1]
    assert commands[1][2][0].endswith("vite.js")
    assert events.index("wait:vite") < events.index("scan") < events.index("remove-temp")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes,match",
    [
        ({"mode": "other"}, "mode"),
        ({"database": "other"}, "novel_creator"),
        ({"confirm_product": "other"}, "confirmation"),
        ({"source_hash": "A" * 64}, "source hash"),
        ({"source_hash": "short"}, "source hash"),
    ],
)
async def test_product_session_rejects_open_or_mismatched_authority_before_services(
    workspace_tmp_path, changes, match
):
    from backend.scripts.run_milestone2_product_session import (
        ProductSessionSafetyError,
        run_product_session,
    )

    arguments = {
        "mode": "corpus-import",
        "database": DATABASE,
        "confirm_product": DATABASE,
        "source_hash": HASH,
        "connection_config": {
            "host": "127.0.0.1",
            "port": 3307,
            "user": "root",
            "password": "db-password",
            "db": DATABASE,
        },
        "environment": {"CORPUS_ROOT": "C:/private/corpus-root"},
        "temp_dir_factory": lambda: workspace_tmp_path / "logs",
    }
    arguments.update(changes)
    started = []
    with pytest.raises(ProductSessionSafetyError, match=match):
        await run_product_session(
            **arguments,
            start_process=lambda *args: started.append(args),
        )
    assert started == []


@pytest.mark.asyncio
async def test_product_session_requires_configured_database_to_match_target(workspace_tmp_path):
    from backend.scripts.run_milestone2_product_session import (
        ProductSessionSafetyError,
        run_product_session,
    )

    with pytest.raises(ProductSessionSafetyError, match="configured database"):
        await run_product_session(
            mode="corpus-import",
            database=DATABASE,
            confirm_product=DATABASE,
            source_hash=HASH,
            connection_config={
                "host": "127.0.0.1",
                "port": 3307,
                "user": "root",
                "password": "db-password",
                "db": "different_database",
            },
            environment={"CORPUS_ROOT": "C:/private/corpus-root"},
            temp_dir_factory=lambda: workspace_tmp_path / "logs",
        )


async def _async_none():
    return None
