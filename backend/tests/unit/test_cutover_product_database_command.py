import asyncio
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from backend.domain.product_database_readiness import (
    DatabaseInventory,
    LEGACY_DATABASE,
    NEW_DATABASE,
    PreparationReceipt,
    ReadinessState,
    advance_receipt,
    canonical_receipt_hash,
    inventory_hash,
)
from backend.domain.json_contracts import canonical_json
from backend.scripts import cutover_product_database as command
from backend.scripts import prepare_product_database as preparation_command


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SECRET = "cutover-secret-must-not-leak"


def inventory(database: str, fingerprint: str) -> DatabaseInventory:
    return DatabaseInventory(
        database=database,
        server_version="8.4.10",
        schema_version="1.13",
        manifest_hash="d" * 64,
        structural_fingerprint=fingerprint,
        table_names=("projects",),
        row_counts=(("projects", 0),),
        nonempty_table_count=0,
        total_row_count=0,
    )


LEGACY_INVENTORY = inventory(LEGACY_DATABASE, "1" * 64)
NEW_INVENTORY = inventory(NEW_DATABASE, "2" * 64)


def preparation_receipt() -> PreparationReceipt:
    previous = None
    receipts = []
    for index, state in enumerate(tuple(ReadinessState)[:7]):
        previous = advance_receipt(previous, state, f"{index + 1:064x}")
        receipts.append(previous)
    assert previous is not None
    return PreparationReceipt(
        state=ReadinessState.AWAITING_CUTOVER_APPROVAL.value,
        previous_receipt_hash=canonical_receipt_hash(previous),
        legacy_database=LEGACY_DATABASE,
        new_database=NEW_DATABASE,
        legacy_inventory_hash=inventory_hash(LEGACY_INVENTORY),
        new_inventory_hash=inventory_hash(NEW_INVENTORY),
        backup_filename="phase7b.sql",
        backup_sha256="c" * 64,
        backup_byte_length=123,
        style_count=10,
        experience_card_count=64,
        market_source_count=2,
        receipts=tuple(receipts),
    )


PREPARATION_RECEIPT = preparation_receipt()


def mysql_document(database: str = LEGACY_DATABASE) -> dict[str, object]:
    return {
        "MYSQL_HOST": "127.0.0.1",
        "MYSQL_PORT": 3307,
        "MYSQL_USER": "root",
        "MYSQL_PASSWORD": SECRET,
        "MYSQL_DB": database,
        "CORPUS_ROOT": "D:/corpus",
        "MANAGED_CORPUS_ROOT": "D:/managed-corpus",
    }


async def successful_smoke(_document):
    return None


async def observe_inventories(_document):
    return LEGACY_INVENTORY, NEW_INVENTORY


def no_product_process():
    return None


def write_json(path, document, _acl, expected_snapshot):
    return command.atomic_compare_and_swap_local_document(
        path,
        document,
        lambda _path: None,
        expected_snapshot,
    )


@pytest.mark.asyncio
async def test_cutover_changes_only_mysql_db_and_finishes_legacy_retained(workspace_tmp_path):
    config = workspace_tmp_path / ".env.local.json"
    original = mysql_document()
    config.write_text(json.dumps(original), encoding="utf-8")

    result = await command.cutover(
        receipt=PREPARATION_RECEIPT,
        config_path=config,
        confirm_database=NEW_DATABASE,
        confirm_cutover="CUTOVER-PHASE7B",
        smoke=successful_smoke,
        writer=write_json,
        inventory_reader=observe_inventories,
        observed_backup_sha256="c" * 64,
        acl_runner=object(),
        idle_guard=no_product_process,
    )

    current = json.loads(config.read_text(encoding="utf-8"))
    assert current == {**original, "MYSQL_DB": NEW_DATABASE}
    assert result.state == ReadinessState.LEGACY_RETAINED.value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("database", "confirmation"),
    ((LEGACY_DATABASE, "CUTOVER-PHASE7B"), (NEW_DATABASE, "wrong")),
)
async def test_cutover_requires_both_exact_approvals_before_read_or_write(
    workspace_tmp_path, database, confirmation
):
    config = workspace_tmp_path / ".env.local.json"
    config.write_text(json.dumps(mysql_document()), encoding="utf-8")
    calls = []

    with pytest.raises(command.ProductDatabaseCutoverError, match="approval"):
        await command.cutover(
            receipt=PREPARATION_RECEIPT,
            config_path=config,
            confirm_database=database,
            confirm_cutover=confirmation,
            smoke=lambda *_args: calls.append("smoke"),
            writer=lambda *_args: calls.append("write"),
            inventory_reader=lambda *_args: calls.append("inventory"),
            observed_backup_sha256="c" * 64,
            acl_runner=object(),
            idle_guard=no_product_process,
        )

    assert calls == []


@pytest.mark.asyncio
async def test_cutover_refuses_an_active_product_process_before_config_write(
    workspace_tmp_path,
):
    config = workspace_tmp_path / ".env.local.json"
    original = mysql_document()
    config.write_text(json.dumps(original), encoding="utf-8")
    writes = []

    def active_process_guard():
        raise RuntimeError(f"active {SECRET}")

    with pytest.raises(command.ProductDatabaseCutoverError, match="process") as raised:
        await command.cutover(
            receipt=PREPARATION_RECEIPT,
            config_path=config,
            confirm_database=NEW_DATABASE,
            confirm_cutover="CUTOVER-PHASE7B",
            smoke=successful_smoke,
            writer=lambda *_args: writes.append(True),
            inventory_reader=observe_inventories,
            observed_backup_sha256="c" * 64,
            acl_runner=object(),
            idle_guard=active_process_guard,
        )

    assert writes == []
    assert SECRET not in repr(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    (
        lambda receipt: SimpleNamespace(
            **{**asdict(receipt), "state": ReadinessState.LEGACY_RETAINED.value}
        ),
        lambda receipt: replace(receipt, legacy_inventory_hash="f" * 64),
        lambda receipt: replace(receipt, new_inventory_hash="f" * 64),
        lambda receipt: replace(receipt, backup_sha256="f" * 64),
    ),
)
async def test_cutover_rejects_stale_or_mismatched_evidence_without_write(
    workspace_tmp_path, mutation
):
    config = workspace_tmp_path / ".env.local.json"
    config.write_text(json.dumps(mysql_document()), encoding="utf-8")
    writes = []

    with pytest.raises(command.ProductDatabaseCutoverError):
        await command.cutover(
            receipt=mutation(PREPARATION_RECEIPT),
            config_path=config,
            confirm_database=NEW_DATABASE,
            confirm_cutover="CUTOVER-PHASE7B",
            smoke=successful_smoke,
            writer=lambda *_args: writes.append(True),
            inventory_reader=observe_inventories,
            observed_backup_sha256="c" * 64,
            acl_runner=object(),
            idle_guard=no_product_process,
        )

    assert writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "document",
    (
        mysql_document(NEW_DATABASE),
        {**mysql_document(), "UNKNOWN": "bad"},
        {key: value for key, value in mysql_document().items() if key != "MYSQL_PASSWORD"},
    ),
)
async def test_cutover_rejects_wrong_or_invalid_current_config(workspace_tmp_path, document):
    config = workspace_tmp_path / ".env.local.json"
    config.write_text(json.dumps(document), encoding="utf-8")
    writes = []
    with pytest.raises(command.ProductDatabaseCutoverError, match="configuration"):
        await command.cutover(
            receipt=PREPARATION_RECEIPT,
            config_path=config,
            confirm_database=NEW_DATABASE,
            confirm_cutover="CUTOVER-PHASE7B",
            smoke=successful_smoke,
            writer=lambda *_args: writes.append(True),
            inventory_reader=observe_inventories,
            observed_backup_sha256="c" * 64,
            acl_runner=object(),
            idle_guard=no_product_process,
        )
    assert writes == []


@pytest.mark.asyncio
async def test_smoke_failure_restores_exact_original_document(workspace_tmp_path):
    config = workspace_tmp_path / ".env.local.json"
    original = mysql_document()
    config.write_text(json.dumps(original), encoding="utf-8")
    writes = []

    def writer(path, document, acl, expected_snapshot):
        writes.append(dict(document))
        return write_json(path, document, acl, expected_snapshot)

    async def fail_smoke(_document):
        raise RuntimeError(f"private {SECRET}")

    with pytest.raises(command.ProductDatabaseCutoverError, match="smoke") as raised:
        await command.cutover(
            receipt=PREPARATION_RECEIPT,
            config_path=config,
            confirm_database=NEW_DATABASE,
            confirm_cutover="CUTOVER-PHASE7B",
            smoke=fail_smoke,
            writer=writer,
            inventory_reader=observe_inventories,
            observed_backup_sha256="c" * 64,
            acl_runner=object(),
            idle_guard=no_product_process,
        )

    assert writes == [{**original, "MYSQL_DB": NEW_DATABASE}, original]
    assert json.loads(config.read_text(encoding="utf-8")) == original
    assert SECRET not in repr(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", (RuntimeError("smoke"), asyncio.CancelledError()))
async def test_smoke_and_rollback_failure_keeps_primary_first_and_sanitized(
    workspace_tmp_path, failure
):
    config = workspace_tmp_path / ".env.local.json"
    config.write_text(json.dumps(mysql_document()), encoding="utf-8")
    writes = 0

    def writer(path, document, acl, expected_snapshot):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise RuntimeError(f"rollback {SECRET}")
        return write_json(path, document, acl, expected_snapshot)

    async def smoke(_document):
        raise failure

    with pytest.raises(BaseExceptionGroup) as raised:
        await command.cutover(
            receipt=PREPARATION_RECEIPT,
            config_path=config,
            confirm_database=NEW_DATABASE,
            confirm_cutover="CUTOVER-PHASE7B",
            smoke=smoke,
            writer=writer,
            inventory_reader=observe_inventories,
            observed_backup_sha256="c" * 64,
            acl_runner=object(),
            idle_guard=no_product_process,
        )

    assert len(raised.value.exceptions) == 2
    if isinstance(failure, asyncio.CancelledError):
        assert isinstance(raised.value.exceptions[0], asyncio.CancelledError)
    else:
        assert isinstance(raised.value.exceptions[0], command.ProductDatabaseCutoverError)
    assert isinstance(raised.value.exceptions[1], command.ProductDatabaseCutoverError)
    assert SECRET not in repr(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_type",
    (asyncio.CancelledError, KeyboardInterrupt, SystemExit),
)
async def test_flow_control_propagates_after_one_successful_rollback(
    workspace_tmp_path, failure_type
):
    config = workspace_tmp_path / ".env.local.json"
    original = mysql_document()
    config.write_text(json.dumps(original), encoding="utf-8")
    writes = []

    def writer(path, document, acl, expected_snapshot):
        writes.append(dict(document))
        return write_json(path, document, acl, expected_snapshot)

    async def smoke(_document):
        raise failure_type()

    with pytest.raises(failure_type):
        await command.cutover(
            receipt=PREPARATION_RECEIPT,
            config_path=config,
            confirm_database=NEW_DATABASE,
            confirm_cutover="CUTOVER-PHASE7B",
            smoke=smoke,
            writer=writer,
            inventory_reader=observe_inventories,
            observed_backup_sha256="c" * 64,
            acl_runner=object(),
            idle_guard=no_product_process,
        )

    assert writes == [{**original, "MYSQL_DB": NEW_DATABASE}, original]


def test_backup_digest_uses_the_backup_sibling_of_readiness_receipt(workspace_tmp_path):
    backup = workspace_tmp_path / "novel_creator-phase7b-abc.sql"
    backup.write_bytes(b"approved-backup")
    receipt = workspace_tmp_path / "novel_creator-phase7b-abc.readiness.json"

    assert command._backup_sha256_for_receipt(receipt) == hashlib.sha256(
        b"approved-backup"
    ).hexdigest()


@pytest.mark.asyncio
async def test_default_post_cutover_smoke_uses_normal_config_without_database_override(
    monkeypatch,
):
    mysql_environment_keys = (
        "MYSQL_HOST",
        "MYSQL_PORT",
        "MYSQL_USER",
        "MYSQL_PASSWORD",
        "MYSQL_DB",
    )
    for key in mysql_environment_keys:
        monkeypatch.setenv(key, f"ambient-{key}-must-not-be-forwarded")
    monkeypatch.setenv("PHASE7B_UNRELATED_ENV", "preserved")
    calls = []
    summary = {
        "artifactCount": 0,
        "firstCause": None,
        "firstStage": None,
        "outboundRequests": 0,
        "portCount": 0,
        "processCount": 0,
        "providerCalls": 0,
        "rootCount": 0,
        "scenarioCount": 1,
    }

    def runner(**kwargs):
        calls.append(kwargs)
        internal_evidence = {**summary}
        internal_evidence.pop("rootCount")
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "PHASE7B_BROWSER_INTERNAL_EVIDENCE="
                + canonical_json(internal_evidence)
            ),
            stderr="",
        )

    result = await command._default_post_cutover_smoke(
        mysql_document(NEW_DATABASE), runner=runner
    )

    assert result.provider_calls == 0
    assert result.outbound_requests == 0
    assert len(calls) == 1
    assert calls[0]["command"] == ("node", "frontend/e2e/run-phase7b.mjs")
    assert calls[0]["cwd"] == REPOSITORY_ROOT
    assert calls[0]["timeout_seconds"] == 300
    assert (
        calls[0]["root_lease_factory"]
        is preparation_command._open_browser_root_lease
    )
    assert all(key not in calls[0]["environment"] for key in mysql_environment_keys)
    assert "PHASE7B_BROWSER_TASK_ROOT" not in calls[0]["environment"]
    assert "PHASE7B_BROWSER_TASK_NONCE" not in calls[0]["environment"]
    assert calls[0]["environment"]["PHASE7B_UNRELATED_ENV"] == "preserved"
    assert calls[0]["environment"]["MARKET_SCHEDULER_ENABLED"] == "false"


@pytest.mark.asyncio
async def test_default_post_cutover_smoke_rejects_nonexact_post_cleanup_summary(
    monkeypatch,
):
    monkeypatch.setattr(
        preparation_command,
        "run_owned_phase7b_browser",
        lambda **_kwargs: {
            **command._BROWSER_SMOKE_EXPECTED,
            "nestedRootCount": 1,
        },
    )

    with pytest.raises(command.ProductDatabaseCutoverError, match="smoke"):
        await command._default_post_cutover_smoke(
            mysql_document(NEW_DATABASE), runner=lambda **_kwargs: None
        )


def test_stage_b_environment_passes_actual_node_configured_mode_contract(
    workspace_tmp_path,
):
    task_root = workspace_tmp_path / "node-contract-owner"
    task_root.mkdir()
    script = """
import {
  createBackendEnvironment, validateBorrowedContract,
} from './frontend/e2e/run-phase7b.mjs'
const environment = {
  ONLY_TEST: 'stage-b',
  MARKET_SCHEDULER_ENABLED: 'false',
  PHASE7B_BROWSER_TASK_ROOT: process.argv[1],
  PHASE7B_BROWSER_TASK_NONCE: 'f'.repeat(32),
}
validateBorrowedContract(environment)
const backend = createBackendEnvironment(environment)
const mysqlKeys = ['MYSQL_HOST', 'MYSQL_PORT', 'MYSQL_USER', 'MYSQL_PASSWORD', 'MYSQL_DB']
if (mysqlKeys.some(key => Object.hasOwn(backend, key))) process.exitCode = 7
else console.log(JSON.stringify(backend))
"""

    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script, str(task_root)],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert json.loads(completed.stdout) == {
        "ONLY_TEST": "stage-b",
        "MARKET_SCHEDULER_ENABLED": "false",
    }


@pytest.mark.asyncio
async def test_inventory_time_config_edit_is_not_overwritten_by_cutover(workspace_tmp_path):
    config = workspace_tmp_path / ".env.local.json"
    original = mysql_document()
    config.write_text(json.dumps(original), encoding="utf-8")
    concurrent = {**original, "CORPUS_ROOT": "D:/concurrent-inventory"}

    async def inventories(_document):
        config.write_text(json.dumps(concurrent), encoding="utf-8")
        return LEGACY_INVENTORY, NEW_INVENTORY

    with pytest.raises(command.ProductDatabaseCutoverError, match="configuration"):
        await command.cutover(
            receipt=PREPARATION_RECEIPT,
            config_path=config,
            confirm_database=NEW_DATABASE,
            confirm_cutover="CUTOVER-PHASE7B",
            smoke=successful_smoke,
            inventory_reader=inventories,
            observed_backup_sha256="c" * 64,
            acl_runner=lambda _path: None,
            idle_guard=no_product_process,
        )

    assert json.loads(config.read_text(encoding="utf-8")) == concurrent


@pytest.mark.asyncio
async def test_smoke_time_config_edit_is_not_overwritten_by_rollback(workspace_tmp_path):
    config = workspace_tmp_path / ".env.local.json"
    original = mysql_document()
    config.write_text(json.dumps(original), encoding="utf-8")
    concurrent = {**original, "MYSQL_DB": NEW_DATABASE, "CORPUS_ROOT": "D:/concurrent-smoke"}

    async def smoke(_document):
        config.write_text(json.dumps(concurrent), encoding="utf-8")
        raise RuntimeError("smoke")

    with pytest.raises(BaseExceptionGroup) as raised:
        await command.cutover(
            receipt=PREPARATION_RECEIPT,
            config_path=config,
            confirm_database=NEW_DATABASE,
            confirm_cutover="CUTOVER-PHASE7B",
            smoke=smoke,
            inventory_reader=observe_inventories,
            observed_backup_sha256="c" * 64,
            acl_runner=lambda _path: None,
            idle_guard=no_product_process,
        )

    assert isinstance(raised.value.exceptions[0], command.ProductDatabaseCutoverError)
    assert isinstance(raised.value.exceptions[1], command.ProductDatabaseCutoverError)
    assert json.loads(config.read_text(encoding="utf-8")) == concurrent


@pytest.mark.asyncio
async def test_successful_smoke_config_edit_prevents_legacy_retained_result(
    workspace_tmp_path,
):
    config = workspace_tmp_path / ".env.local.json"
    original = mysql_document()
    config.write_text(json.dumps(original), encoding="utf-8")
    concurrent = {
        **original,
        "MYSQL_DB": NEW_DATABASE,
        "CORPUS_ROOT": "D:/successful-smoke-editor",
    }

    async def smoke(_document):
        config.write_text(json.dumps(concurrent), encoding="utf-8")

    with pytest.raises(command.ProductDatabaseCutoverError, match="configuration"):
        await command.cutover(
            receipt=PREPARATION_RECEIPT,
            config_path=config,
            confirm_database=NEW_DATABASE,
            confirm_cutover="CUTOVER-PHASE7B",
            smoke=smoke,
            inventory_reader=observe_inventories,
            observed_backup_sha256="c" * 64,
            acl_runner=lambda _path: None,
            idle_guard=no_product_process,
        )

    assert json.loads(config.read_text(encoding="utf-8")) == concurrent


@pytest.mark.asyncio
async def test_inventory_time_config_edit_is_not_overwritten_by_recovery(workspace_tmp_path):
    config = workspace_tmp_path / ".env.local.json"
    original = mysql_document(NEW_DATABASE)
    config.write_text(json.dumps(original), encoding="utf-8")
    concurrent = {**original, "MANAGED_CORPUS_ROOT": "D:/concurrent-recovery"}

    async def inventories(_document):
        config.write_text(json.dumps(concurrent), encoding="utf-8")
        return LEGACY_INVENTORY, NEW_INVENTORY

    with pytest.raises(command.ProductDatabaseCutoverError, match="recovery"):
        await command.recover_legacy(
            config_path=config,
            database=LEGACY_DATABASE,
            confirm_cutover="RECOVER-PHASE7B",
            inventory_reader=inventories,
            acl_runner=lambda _path: None,
            idle_guard=no_product_process,
        )

    assert json.loads(config.read_text(encoding="utf-8")) == concurrent


@pytest.mark.asyncio
async def test_recovery_changes_only_database_and_never_exposes_drop_authority(workspace_tmp_path):
    config = workspace_tmp_path / ".env.local.json"
    original = mysql_document(NEW_DATABASE)
    config.write_text(json.dumps(original), encoding="utf-8")
    observed = []

    async def inventories(document):
        observed.append(dict(document))
        return LEGACY_INVENTORY, NEW_INVENTORY

    result = await command.recover_legacy(
        config_path=config,
        database=LEGACY_DATABASE,
        confirm_cutover="RECOVER-PHASE7B",
        writer=write_json,
        inventory_reader=inventories,
        acl_runner=object(),
        idle_guard=no_product_process,
    )

    assert result.state == ReadinessState.LEGACY_RETAINED.value
    assert json.loads(config.read_text(encoding="utf-8")) == {
        **original,
        "MYSQL_DB": LEGACY_DATABASE,
    }
    assert observed == [original]
    assert "drop" not in command.recover_legacy.__code__.co_names


def test_cli_recovery_requires_exact_closed_action_and_execute():
    assert command.main([
        "--recover-legacy",
        "--database", LEGACY_DATABASE,
        "--confirm-cutover", "RECOVER-PHASE7B",
    ]) == 1


@pytest.mark.asyncio
async def test_execute_cli_loads_exact_receipt_and_runs_guarded_cutover(workspace_tmp_path):
    config = workspace_tmp_path / ".env.local.json"
    original = mysql_document()
    config.write_text(json.dumps(original), encoding="utf-8")
    receipt_path = workspace_tmp_path / "approved.readiness.json"
    events = []
    output = []

    def load_receipt(path):
        events.append(("receipt", path))
        return PREPARATION_RECEIPT

    def backup_digest(path):
        events.append(("backup", path))
        return "c" * 64

    async def inventories(document):
        events.append(("inventory", document["MYSQL_DB"]))
        return LEGACY_INVENTORY, NEW_INVENTORY

    def idle():
        events.append("idle")

    def writer(path, document, acl, expected_snapshot):
        events.append(("write", document["MYSQL_DB"], acl))
        return write_json(path, document, acl, expected_snapshot)

    async def smoke(document):
        events.append(("smoke", document["MYSQL_DB"]))

    result = await command.run_cli(
        [
            "--receipt", str(receipt_path),
            "--database", NEW_DATABASE,
            "--confirm-cutover", "CUTOVER-PHASE7B",
            "--execute",
        ],
        config_path=config,
        receipt_loader=load_receipt,
        backup_digest=backup_digest,
        inventory_reader=inventories,
        smoke=smoke,
        writer=writer,
        acl_runner="private-acl",
        idle_guard=idle,
        output=output.append,
    )

    assert result == 0
    assert events == [
        ("receipt", receipt_path),
        ("backup", receipt_path),
        ("inventory", LEGACY_DATABASE),
        "idle",
        ("write", NEW_DATABASE, "private-acl"),
        ("smoke", NEW_DATABASE),
    ]
    assert output == ["state=legacy_retained"]


def test_cli_help_is_successful_and_failures_are_generic_secret_free(monkeypatch, capsys):
    assert command.main(["--help"]) == 0
    capsys.readouterr()

    def fail_run(coroutine):
        coroutine.close()
        raise RuntimeError(SECRET)

    monkeypatch.setattr(command.asyncio, "run", fail_run)
    assert command.main(["--execute"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Product database cutover failed.\n"
    assert SECRET not in captured.err


def test_module_help_uses_no_real_database_or_configuration():
    result = subprocess.run(
        [sys.executable, "-m", "backend.scripts.cutover_product_database", "--help"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert result.stderr == ""
