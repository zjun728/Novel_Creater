from pathlib import Path
import tempfile

import pytest

from backend.schema_version import EXPECTED_SCHEMA_VERSION


DATABASE = "novel_creator"
HASH = "a" * 64


@pytest.mark.asyncio
async def test_default_product_verifier_connects_explicit_source_hash_to_product_schema(
    monkeypatch,
):
    """The production default collaborator must not silently fall back to latest corpus."""

    import backend.scripts.verify_corpus_import as corpus_module
    import backend.scripts.verify_milestone2_product as product_module
    from backend.scripts.run_milestone2_product_session import _default_verifier

    calls = []

    class FakeSession:
        async def close(self):
            calls.append(("close",))

    async def connect(config):
        calls.append(("connect", config["db"]))
        return FakeSession()

    async def corpus_receipt(session, *, source_hash):
        calls.append(("corpus", session, source_hash))
        return {
            "rawHash": HASH, "chapterCount": 3, "fragmentCount": 9,
            "size": 128, "parserVersion": "p", "normalizerVersion": "n",
            "fragmenterVersion": "f", "indexVersion": "i",
        }

    async def product_receipt(
        session, *, expected_database, expected_source_hash, **flags
    ):
        calls.append(
            ("product", session, expected_database, expected_source_hash, flags)
        )
        return verification_fixture()["product"]

    monkeypatch.setattr(product_module, "_default_connection", connect)
    monkeypatch.setattr(product_module, "verify_milestone2_product", product_receipt)
    monkeypatch.setattr(corpus_module, "build_receipt", corpus_receipt)
    flags = {"require_assets": True, "require_corpus": True, "require_l5": False}

    result = await _default_verifier(
        {"host": "127.0.0.1"}, DATABASE, HASH, flags, {}, None
    )

    assert result == verification_fixture()
    assert calls[1][2] == HASH
    assert calls[2][2:] == (DATABASE, HASH, flags)
    assert calls[-1] == ("close",)


def verification_fixture(*, require_l5=False):
    product = {
        "schemaVersion": EXPECTED_SCHEMA_VERSION,
        "manifestHash": "b" * 64,
        "project": {
            "id": "project-id",
            "title": "永乐大典",
            "seedCount": 3,
            "selectedSeedId": "seed-id",
            "selectedSeedTitle": "典镇山河",
            "providerCount": 9,
            "bindingRevision": 1,
            "contractRevision": 1 if require_l5 else 0,
            "canonRevision": 0,
            "projectionRevision": 0,
        },
        "assets": {
            "packageVersion": "writer-core-v1.1.0",
            "packageHash": "c" * 64,
            "styleCount": 10,
            "cardCount": 64,
        },
        "corpus": {
            "sourceId": "source-id",
            "sourceRevision": 1,
            "relativePath": "approved/reference.txt",
            "sourceHash": HASH,
            "chapterCount": 3,
            "fragmentCount": 9,
            "versions": {"parser": "p", "normalizer": "n", "fragmenter": "f", "index": "i"},
        },
    }
    if require_l5:
        product["l5"] = {
            "batchId": "batch-id",
            "requestHash": "d" * 64,
            "attemptId": "attempt-id",
            "rawResponseHash": "e" * 64,
            "attemptCount": 1,
            "optionCount": 3,
            "options": [
                {"id": f"option-{index}", "option_order": index, "content_hash": character * 64}
                for index, character in enumerate(("1", "2", "3"), 1)
            ],
            "selectedEngineOptionId": "option-1",
            "contractRevision": 1,
            "creationContractId": "creation-id",
            "styleContractId": "style-id",
            "creationHash": "4" * 64,
            "styleHash": "5" * 64,
            "referenceManifestHash": "6" * 64,
        }
    return {
        "corpus": {
            "sourceHash": HASH,
            "chapterCount": 3,
            "fragmentCount": 9,
            "fileSize": 128,
            "versions": {"parser": "p", "normalizer": "n", "fragmenter": "f", "index": "i"},
        },
        "product": product,
    }


class FakeChild:
    def __init__(self, label, events):
        self.label = label
        self.events = events
        self.returncode = None

    def terminate(self):
        self.events.append(f"terminate:{self.label}")

    def wait(self, timeout=None):
        self.events.append(f"wait:{self.label}")
        self.returncode = 0
        return 0

    def poll(self):
        self.events.append(f"poll:{self.label}")
        return self.returncode


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
    child_envs = []
    expected_private_values = {
        "provider-key",
        "https://private-provider.example/v1",
        "db-password",
        "C:/private/corpus-root",
    }
    provider_secrets = {
        "provider-key",
        "https://private-provider.example/v1",
    }

    def start(label, command, args, cwd, env, log_dir):
        events.append(f"start:{label}")
        commands.append((label, command, args))
        child_envs.append(dict(env))
        return FakeChild(label, events)

    async def sensitive_loader(config, database):
        events.append("load-sensitive")
        assert database == DATABASE
        return {
            "scanValues": provider_secrets,
            "providerFingerprint": "7" * 64,
            "providerCount": 9,
        }

    async def wait_for_input(_prompt):
        events.append("input")

    async def verifier(database, source_hash, flags, environment, log_dir):
        events.append("verify")
        assert database == DATABASE
        assert source_hash == HASH
        assert flags == expected_flags
        return verification_fixture(require_l5=mode == "provider-l5")

    def scan(log_dir, values):
        events.append("scan")
        assert expected_private_values <= set(values)
        return 0

    receipt = await run_product_session(
        mode=mode,
        database=DATABASE,
        confirm_product=DATABASE,
        confirm_host="127.0.0.1",
        confirm_port=3307,
        source_hash=HASH,
        connection_config={
            "host": "127.0.0.1",
            "port": 3307,
            "user": "root",
            "password": "db-password",
            "db": DATABASE,
        },
        environment={"CORPUS_ROOT": "C:/private/corpus-root"},
        nonce_factory=lambda: "closed-mode-nonce",
        temp_parent=workspace_tmp_path,
        temp_dir_factory=lambda prefix: Path(str(prefix) + "logs"),
        endpoint_identity_loader=lambda *_args: _async_identity(),
        sensitive_loader=sensitive_loader,
        start_process=start,
        wait_for_health=lambda *args, **kwargs: _async_none(),
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
    for env in child_envs:
        assert env["M2_BROWSER_RUN_NONCE"] == "closed-mode-nonce"
        assert env["PYTHONUTF8"] == "1"
        assert env["PYTHONIOENCODING"] == "utf-8"
        assert env["CORPUS_ROOT"] == "C:/private/corpus-root"
        assert not any(key.startswith("TEST_MYSQL_") for key in env)


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
        "confirm_host": "127.0.0.1",
        "confirm_port": 3307,
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
            confirm_host="127.0.0.1",
            confirm_port=3307,
            source_hash=HASH,
            connection_config={
                "host": "127.0.0.1",
                "port": 3307,
                "user": "root",
                "password": "db-password",
                "db": "different_database",
            },
            environment={"CORPUS_ROOT": "C:/private/corpus-root"},
            temp_dir_factory=lambda prefix: Path(str(prefix) + "logs"),
        )


async def _async_none():
    return None


def _product_config(**changes):
    config = {
        "host": "127.0.0.1",
        "port": 3307,
        "user": "root",
        "password": "db-password",
        "db": DATABASE,
    }
    config.update(changes)
    return config


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config,confirm_host,confirm_port,match",
    [
        (_product_config(host="remote.example"), "127.0.0.1", 3307, "loopback"),
        (_product_config(port=3306), "127.0.0.1", 3307, "3307"),
        (_product_config(), "localhost", 3307, "host confirmation"),
        (_product_config(), "127.0.0.1", 3306, "port confirmation"),
    ],
)
async def test_product_session_requires_exact_local_host_port_four_tuple_before_reads(
    config, confirm_host, confirm_port, match,
):
    from backend.scripts.run_milestone2_product_session import (
        ProductSessionSafetyError,
        run_product_session,
    )

    loaded = False

    async def sensitive_loader(*_args):
        nonlocal loaded
        loaded = True
        return {"scanValues": set(), "providerFingerprint": "8" * 64, "providerCount": 0}

    with pytest.raises(ProductSessionSafetyError, match=match):
        await run_product_session(
            mode="corpus-import",
            database=DATABASE,
            confirm_product=DATABASE,
            confirm_host=confirm_host,
            confirm_port=confirm_port,
            source_hash=HASH,
            connection_config=config,
            environment={"CORPUS_ROOT": "C:/private/corpus-root"},
            sensitive_loader=sensitive_loader,
        )
    assert loaded is False


@pytest.mark.asyncio
async def test_product_session_scans_pre_and_post_secret_snapshots_and_keeps_verifier_evidence():
    from backend.scripts.run_milestone2_product_session import run_product_session

    events = []
    snapshots = iter((
        {"scanValues": {"pre-key", "https://pre.invalid"}, "providerFingerprint": "9" * 64, "providerCount": 9},
        {"scanValues": {"pre-key", "https://pre.invalid"}, "providerFingerprint": "9" * 64, "providerCount": 9},
    ))

    class Child(FakeChild):
        def __init__(self, label):
            super().__init__(label, events)
            self.returncode = None

        def poll(self):
            events.append(f"poll:{self.label}")
            return self.returncode

    async def loader(config, database):
        events.append("load-sensitive")
        return next(snapshots)

    def start(label, *args):
        events.append(f"start:{label}")
        return Child(label)

    async def verifier(*_args):
        events.append("verify")
        return verification_fixture()

    def scan(_log_dir, values):
        events.append("scan")
        assert {"pre-key", "https://pre.invalid"} <= set(values)
        return 0

    with tempfile.TemporaryDirectory(prefix="m2e-product-parent-") as directory:
        parent = Path(directory).resolve()
        ports = iter((44001, 44002))
        receipt = await run_product_session(
            mode="corpus-import",
            database=DATABASE,
            confirm_product=DATABASE,
            confirm_host="127.0.0.1",
            confirm_port=3307,
            source_hash=HASH,
            connection_config=_product_config(),
            environment={"CORPUS_ROOT": "C:/private/corpus-root"},
            nonce_factory=lambda: "owned-product-nonce",
            port_reservation_factory=lambda: type(
                "Reservation", (), {"port": next(ports), "release": lambda self: events.append("release")}
            )(),
            temp_parent=parent,
            temp_dir_factory=lambda prefix: tempfile.mkdtemp(prefix=Path(prefix).name, dir=parent),
            endpoint_identity_loader=_async_identity,
            sensitive_loader=loader,
            start_process=start,
            wait_for_health=lambda *args, **kwargs: _async_none(),
            wait_for_input=lambda _prompt: _async_none(),
            verifier=verifier,
            scan_logs=scan,
            output=lambda _value: None,
        )

    assert events.count("load-sensitive") == 2
    assert events.index("verify") < events.index("load-sensitive", events.index("verify"))
    assert events.index("load-sensitive", events.index("verify")) < events.index("scan")
    assert receipt["verification"]["corpus"]["sourceHash"] == HASH
    assert receipt["verification"]["product"]["project"] == verification_fixture()["product"]["project"]
    rendered = str(receipt)
    for forbidden in ("pre-key", "rotated-key", "private/corpus-root", "db-password"):
        assert forbidden not in rendered


@pytest.mark.asyncio
async def test_product_session_rejects_provider_fingerprint_change_without_secret_echo(workspace_tmp_path):
    from backend.scripts.run_milestone2_product_session import (
        ProductSessionSafetyError,
        run_product_session,
    )

    snapshots = iter((
        {"scanValues": {"SECRET_BEFORE"}, "providerFingerprint": "a" * 64, "providerCount": 9},
        {"scanValues": {"SECRET_AFTER"}, "providerFingerprint": "b" * 64, "providerCount": 9},
    ))

    async def loader(*_args):
        return next(snapshots)

    with pytest.raises(ProductSessionSafetyError) as raised:
        await run_product_session(
            mode="corpus-import",
            database=DATABASE,
            confirm_product=DATABASE,
            confirm_host="127.0.0.1",
            confirm_port=3307,
            source_hash=HASH,
            connection_config=_product_config(),
            environment={"CORPUS_ROOT": "C:/private/corpus-root"},
            nonce_factory=lambda: "fingerprint-nonce",
            temp_parent=workspace_tmp_path,
            temp_dir_factory=lambda prefix: workspace_tmp_path / (Path(prefix).name + "suffix"),
            endpoint_identity_loader=_async_identity,
            sensitive_loader=loader,
            start_process=lambda label, *args: FakeChild(label, []),
            wait_for_health=lambda *args, **kwargs: _async_none(),
            wait_for_input=lambda _prompt: _async_none(),
            verifier=lambda *args: _async_result(verification_fixture()),
            scan_logs=lambda *_args: 0,
            output=lambda _value: None,
        )
    assert "fingerprint" in str(raised.value).lower()
    assert "SECRET_BEFORE" not in str(raised.value)
    assert "SECRET_AFTER" not in str(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["parent", "outside", "wrong-prefix"])
async def test_product_session_refuses_unowned_temp_directory(workspace_tmp_path, shape):
    from backend.scripts.run_milestone2_product_session import (
        ProductSessionSafetyError,
        run_product_session,
    )

    parent = workspace_tmp_path.resolve()
    events = []
    ports = iter((
        type("Reservation", (), {"port": 44101, "release": lambda self: events.append("release:44101")})(),
        type("Reservation", (), {"port": 44102, "release": lambda self: events.append("release:44102")})(),
    ))

    def factory(prefix):
        if shape == "parent":
            return parent
        if shape == "outside":
            return parent.parent
        path = parent / "wrong-prefix-suffix"
        path.mkdir(exist_ok=True)
        return path

    with pytest.raises(ProductSessionSafetyError, match="owned temporary"):
        await run_product_session(
            mode="corpus-import",
            database=DATABASE,
            confirm_product=DATABASE,
            confirm_host="127.0.0.1",
            confirm_port=3307,
            source_hash=HASH,
            connection_config=_product_config(),
            environment={"CORPUS_ROOT": "C:/private/corpus-root"},
            nonce_factory=lambda: "owned-product-temp",
            port_reservation_factory=lambda: next(ports),
            temp_parent=parent,
            temp_dir_factory=factory,
            endpoint_identity_loader=_async_identity,
            sensitive_loader=lambda *args: _async_snapshot(),
        )
    assert events == ["release:44101", "release:44102"]


async def _async_snapshot():
    return {"scanValues": set(), "providerFingerprint": "c" * 64, "providerCount": 0}


async def _async_identity(*_args):
    return {"database": DATABASE, "port": 3307}


@pytest.mark.parametrize(
    "snapshot",
    [
        "raw-provider-key",
        {"raw-provider-key"},
        {"scanValues": set(), "providerFingerprint": "stable", "providerCount": 0},
        {"scanValues": set(), "providerFingerprint": "A" * 64, "providerCount": 0},
        {"scanValues": set(), "providerFingerprint": "a" * 64},
        {"scanValues": set(), "providerFingerprint": "a" * 64, "providerCount": -1},
        {"scanValues": {"secret"}, "providerFingerprint": "a" * 64, "providerCount": 0},
        {"scanValues": set(), "providerFingerprint": "a" * 64, "providerCount": 1},
        {
            "scanValues": {"one", "two", "three"},
            "providerFingerprint": "a" * 64,
            "providerCount": 1,
        },
        {
            "scanValues": {"secret", 1},
            "providerFingerprint": "a" * 64,
            "providerCount": 1,
        },
        {"scanValues": {"secret"}, "providerFingerprint": "a" * 64, "providerCount": True},
    ],
)
def test_provider_secret_snapshot_requires_canonical_hash_and_explicit_count(snapshot):
    from backend.scripts.run_milestone2_product_session import (
        ProductSessionSafetyError,
        _normalize_sensitive_snapshot,
    )

    with pytest.raises(ProductSessionSafetyError, match="snapshot"):
        _normalize_sensitive_snapshot(snapshot)


def test_provider_secret_snapshot_allows_shared_values_for_dynamic_inventory():
    from backend.scripts.run_milestone2_product_session import (
        _normalize_sensitive_snapshot,
    )

    snapshot = _normalize_sensitive_snapshot({
        "scanValues": {"shared-key", "https://shared-provider.invalid"},
        "providerFingerprint": "a" * 64,
        "providerCount": 9,
    })

    assert snapshot == {
        "scanValues": {"shared-key", "https://shared-provider.invalid"},
        "providerFingerprint": "a" * 64,
        "providerCount": 9,
    }


def _invalid_exact_receipts():
    missing_assets = verification_fixture()
    del missing_assets["product"]["assets"]
    empty_project = verification_fixture()
    empty_project["product"]["project"] = {}
    missing_file_size = verification_fixture()
    del missing_file_size["corpus"]["fileSize"]
    missing_trace = verification_fixture(require_l5=True)
    del missing_trace["product"]["l5"]["requestHash"]
    unordered_options = verification_fixture(require_l5=True)
    unordered_options["product"]["l5"]["options"][2]["option_order"] = 2
    uppercase_hash = verification_fixture(require_l5=True)
    uppercase_hash["product"]["l5"]["rawResponseHash"] = "E" * 64
    return [
        ("corpus-import", missing_assets),
        ("corpus-import", empty_project),
        ("corpus-import", missing_file_size),
        ("provider-l5", missing_trace),
        ("provider-l5", unordered_options),
        ("provider-l5", uppercase_hash),
    ]


@pytest.mark.parametrize("mode,receipt", _invalid_exact_receipts())
def test_product_verification_receipt_requires_exact_mode_schema(mode, receipt):
    from backend.scripts.run_milestone2_product_session import (
        ProductSessionSafetyError,
        _sanitize_product_verification,
    )

    with pytest.raises(ProductSessionSafetyError, match="verification"):
        _sanitize_product_verification(
            receipt, HASH, mode, expected_provider_count=9
        )


@pytest.mark.parametrize(
    ("receipt_count", "expected_count"),
    [
        (8, 9),
        (0, 9),
        (True, 9),
        (9, 0),
        (9, True),
    ],
)
def test_product_verification_provider_count_must_match_sensitive_snapshot(
    receipt_count, expected_count,
):
    from backend.scripts.run_milestone2_product_session import (
        ProductSessionSafetyError,
        _sanitize_product_verification,
    )

    receipt = verification_fixture()
    receipt["product"]["project"]["providerCount"] = receipt_count

    with pytest.raises(ProductSessionSafetyError, match="verification"):
        _sanitize_product_verification(
            receipt,
            HASH,
            "corpus-import",
            expected_provider_count=expected_count,
        )


@pytest.mark.parametrize(
    "relative_path",
    [
        "/absolute/reference.txt",
        "C:/absolute/reference.txt",
        "C:\\absolute\\reference.txt",
        "\\\\server\\share\\reference.txt",
        "../reference.txt",
        "approved/../reference.txt",
        ".",
        "./reference.txt",
        "approved//reference.txt",
        "approved/./reference.txt",
        "approved\\reference.txt",
        "",
    ],
)
def test_product_verification_rejects_noncanonical_or_unsafe_relative_path(
    relative_path,
):
    from backend.scripts.run_milestone2_product_session import (
        ProductSessionSafetyError,
        _sanitize_product_verification,
    )

    receipt = verification_fixture()
    receipt["product"]["corpus"]["relativePath"] = relative_path
    with pytest.raises(ProductSessionSafetyError, match="relativePath"):
        _sanitize_product_verification(
            receipt, HASH, "corpus-import", expected_provider_count=9
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "identity,match",
    [
        ({"database": "another_database", "port": 3307}, "database identity"),
        ({"database": DATABASE, "port": 3306}, "port identity"),
    ],
)
async def test_product_session_rechecks_connected_endpoint_identity_before_secrets(identity, match):
    from backend.scripts.run_milestone2_product_session import (
        ProductSessionSafetyError,
        run_product_session,
    )

    events = []

    with pytest.raises(ProductSessionSafetyError, match=match):
        await run_product_session(
            mode="corpus-import",
            database=DATABASE,
            confirm_product=DATABASE,
            confirm_host="127.0.0.1",
            confirm_port=3307,
            source_hash=HASH,
            connection_config=_product_config(),
            environment={"CORPUS_ROOT": "C:/private/corpus-root"},
            endpoint_identity_loader=lambda *_args: _async_result(identity),
            sensitive_loader=lambda *_args: events.append("sensitive"),
            start_process=lambda *_args: events.append("start"),
        )
    assert events == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "verification",
    [
        {"corpus": {"sourceHash": "b" * 64}, "product": {}},
        {"corpus": {"sourceHash": HASH}, "product": {}, "apiKey": "SECRET"},
        {"corpus": {"sourceHash": HASH}, "product": {"notes": "SECRET"}},
    ],
)
async def test_product_session_rejects_malicious_or_mismatched_verifier_receipt(
    workspace_tmp_path, verification,
):
    from backend.scripts.run_milestone2_product_session import (
        ProductSessionSafetyError,
        run_product_session,
    )

    parent = workspace_tmp_path.resolve()
    with pytest.raises(ProductSessionSafetyError, match="verification") as raised:
        await run_product_session(
            mode="corpus-import",
            database=DATABASE,
            confirm_product=DATABASE,
            confirm_host="127.0.0.1",
            confirm_port=3307,
            source_hash=HASH,
            connection_config=_product_config(),
            environment={"CORPUS_ROOT": "C:/private/corpus-root"},
            nonce_factory=lambda: "malicious-receipt-nonce",
            temp_parent=parent,
            temp_dir_factory=lambda prefix: tempfile.mkdtemp(
                prefix=Path(prefix).name, dir=parent
            ),
            endpoint_identity_loader=_async_identity,
            sensitive_loader=lambda *_args: _async_snapshot(),
            start_process=lambda label, *_args: FakeChild(label, []),
            wait_for_health=lambda *_args, **_kwargs: _async_none(),
            wait_for_input=lambda _prompt: _async_none(),
            verifier=lambda *_args: _async_result(verification),
            scan_logs=lambda *_args: 0,
            output=lambda _value: None,
        )
    assert "SECRET" not in str(raised.value)


@pytest.mark.asyncio
async def test_product_timeout_still_reloads_secrets_scans_logs_and_removes_temp(workspace_tmp_path):
    from subprocess import TimeoutExpired
    from backend.scripts.run_milestone2_product_session import run_product_session

    parent = workspace_tmp_path.resolve()
    events = []

    async def loader(*_args):
        events.append("load")
        return {"scanValues": {"secret"}, "providerFingerprint": "d" * 64, "providerCount": 1}

    async def timeout_input(_prompt):
        raise TimeoutExpired("manual", 1)

    def scan(*_args):
        events.append("scan")
        return 0

    with pytest.raises(TimeoutExpired):
        await run_product_session(
            mode="corpus-import",
            database=DATABASE,
            confirm_product=DATABASE,
            confirm_host="127.0.0.1",
            confirm_port=3307,
            source_hash=HASH,
            connection_config=_product_config(),
            environment={"CORPUS_ROOT": "C:/private/corpus-root"},
            nonce_factory=lambda: "timeout-product-nonce",
            temp_parent=parent,
            temp_dir_factory=lambda prefix: tempfile.mkdtemp(
                prefix=Path(prefix).name, dir=parent
            ),
            endpoint_identity_loader=_async_identity,
            sensitive_loader=loader,
            start_process=lambda label, *_args: FakeChild(label, events),
            wait_for_health=lambda *_args, **_kwargs: _async_none(),
            wait_for_input=timeout_input,
            verifier=lambda *_args: _async_none(),
            scan_logs=scan,
            remove_temp=lambda _path: events.append("remove"),
            output=lambda _value: None,
        )
    assert events.count("load") == 2
    assert events.index("load", 1) < events.index("scan") < events.index("remove")


async def _async_result(value):
    return value


@pytest.mark.asyncio
async def test_product_releases_first_reservation_when_second_acquisition_fails():
    from backend.scripts.run_milestone2_product_session import run_product_session

    events = []
    first = type(
        "Reservation", (),
        {"port": 44201, "release": lambda self: events.append("release:44201")},
    )()
    calls = 0

    def reserve():
        nonlocal calls
        calls += 1
        if calls == 1:
            return first
        raise RuntimeError("second product reservation failed")

    with pytest.raises(RuntimeError, match="second product reservation"):
        await run_product_session(
            mode="corpus-import",
            database=DATABASE,
            confirm_product=DATABASE,
            confirm_host="127.0.0.1",
            confirm_port=3307,
            source_hash=HASH,
            connection_config=_product_config(),
            environment={"CORPUS_ROOT": "C:/private/corpus-root"},
            endpoint_identity_loader=_async_identity,
            sensitive_loader=lambda *_args: _async_snapshot(),
            port_reservation_factory=reserve,
        )
    assert events == ["release:44201"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,require_l5",
    [("corpus-import", True), ("provider-l5", False)],
)
async def test_product_session_rejects_verification_evidence_for_the_wrong_mode(
    workspace_tmp_path, mode, require_l5,
):
    from backend.scripts.run_milestone2_product_session import (
        ProductSessionSafetyError,
        run_product_session,
    )

    parent = workspace_tmp_path.resolve()
    with pytest.raises(ProductSessionSafetyError, match="verification.*mode"):
        await run_product_session(
            mode=mode,
            database=DATABASE,
            confirm_product=DATABASE,
            confirm_host="127.0.0.1",
            confirm_port=3307,
            source_hash=HASH,
            connection_config=_product_config(),
            environment={"CORPUS_ROOT": "C:/private/corpus-root"},
            nonce_factory=lambda: "wrong-mode-nonce",
            temp_parent=parent,
            temp_dir_factory=lambda prefix: tempfile.mkdtemp(
                prefix=Path(prefix).name, dir=parent
            ),
            endpoint_identity_loader=_async_identity,
            sensitive_loader=lambda *_args: _async_snapshot(),
            start_process=lambda label, *_args: FakeChild(label, []),
            wait_for_health=lambda *_args, **_kwargs: _async_none(),
            wait_for_input=lambda _prompt: _async_none(),
            verifier=lambda *_args: _async_result(
                verification_fixture(require_l5=require_l5)
            ),
            scan_logs=lambda *_args: 0,
            output=lambda _value: None,
        )
