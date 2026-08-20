import asyncio
from dataclasses import asdict, replace
from contextlib import contextmanager
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
from backend.services import product_database_lifecycle_lock as lifecycle_service


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


@contextmanager
def open_lifecycle_lock(_config_path):
    yield object()


class RecordingLifecycleLock:
    def __init__(self, events, *, failures=()):
        self.events = events
        self.failures = list(failures)
        self.active = False
        self.scopes = 0

    @contextmanager
    def __call__(self, config_path):
        self.events.append(("lock-attempt", Path(config_path)))
        failure = self.failures.pop(0) if self.failures else None
        if failure == "acquire":
            raise RuntimeError(f"acquire {SECRET}")
        assert not self.active
        self.active = True
        self.scopes += 1
        self.events.append("lock-enter")
        try:
            yield SimpleNamespace(
                defer_until=lambda *_args: pytest.fail("cutover must never defer")
            )
        finally:
            self.events.append("lock-exit")
            self.active = False
            if failure == "release":
                raise RuntimeError(f"release {SECRET}")


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
        acl_runner=object(),
        lifecycle_lock=open_lifecycle_lock,
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
            acl_runner=object(),
            lifecycle_lock=open_lifecycle_lock,
        )

    assert calls == []


@pytest.mark.asyncio
async def test_cutover_contention_precedes_config_inventory_write_and_smoke(
    workspace_tmp_path,
):
    config = workspace_tmp_path / ".env.local.json"
    original = mysql_document()
    config.write_text(json.dumps(original), encoding="utf-8")
    calls = []

    def contended_lock(_path):
        calls.append("lock")
        raise RuntimeError(f"contended {SECRET}")

    def forbidden(*_args, **_kwargs):
        calls.append("forbidden")
        raise AssertionError("contention must precede protected work")

    original_capture = command.capture_local_document_snapshot
    command.capture_local_document_snapshot = forbidden
    try:
        with pytest.raises(Exception, match="lifecycle") as raised:
            await command.cutover(
                receipt=PREPARATION_RECEIPT,
                config_path=config,
                confirm_database=NEW_DATABASE,
                confirm_cutover="CUTOVER-PHASE7B",
                smoke=forbidden,
                writer=forbidden,
                inventory_reader=forbidden,
                acl_runner=object(),
                lifecycle_lock=contended_lock,
            )
    finally:
        command.capture_local_document_snapshot = original_capture

    assert calls == ["lock"]
    assert SECRET not in repr(raised.value)


@pytest.mark.asyncio
async def test_cutover_success_uses_two_exact_nondeferred_lock_scopes(
    workspace_tmp_path, monkeypatch,
):
    config = workspace_tmp_path / ".env.local.json"
    config.write_text(json.dumps(mysql_document()), encoding="utf-8")
    events = []
    lifecycle = RecordingLifecycleLock(events)
    real_capture = command.capture_local_document_snapshot

    def capture(path):
        assert lifecycle.active
        events.append("capture")
        return real_capture(path)

    monkeypatch.setattr(command, "capture_local_document_snapshot", capture)

    async def inventories(_document):
        assert lifecycle.active
        events.append("inventory")
        return LEGACY_INVENTORY, NEW_INVENTORY

    def writer(path, document, acl, expected_snapshot):
        assert lifecycle.active
        events.append(("write", document["MYSQL_DB"]))
        return write_json(path, document, acl, expected_snapshot)

    async def smoke(_document):
        assert not lifecycle.active
        events.append("smoke")

    result = await command.cutover(
        receipt=PREPARATION_RECEIPT,
        config_path=config,
        confirm_database=NEW_DATABASE,
        confirm_cutover="CUTOVER-PHASE7B",
        smoke=smoke,
        writer=writer,
        inventory_reader=inventories,
        acl_runner=object(),
        lifecycle_lock=lifecycle,
    )

    assert result.state == ReadinessState.LEGACY_RETAINED.value
    assert events == [
        ("lock-attempt", config),
        "lock-enter",
        "capture",
        "inventory",
        ("write", NEW_DATABASE),
        "lock-exit",
        "smoke",
        ("lock-attempt", config),
        "lock-enter",
        "capture",
        "lock-exit",
    ]
    assert lifecycle.scopes == 2


@pytest.mark.asyncio
async def test_smoke_gap_is_unlocked_and_failure_rollback_uses_fresh_scope(
    workspace_tmp_path,
):
    config = workspace_tmp_path / ".env.local.json"
    original = mysql_document()
    config.write_text(json.dumps(original), encoding="utf-8")
    events = []
    lifecycle = RecordingLifecycleLock(events)

    def writer(path, document, acl, expected_snapshot):
        assert lifecycle.active
        events.append(("write", document["MYSQL_DB"]))
        return write_json(path, document, acl, expected_snapshot)

    async def smoke(_document):
        assert not lifecycle.active
        events.append("smoke")
        with lifecycle(config):
            events.append("contender")
        raise RuntimeError(SECRET)

    with pytest.raises(command.ProductDatabaseCutoverError, match="smoke"):
        await command.cutover(
            receipt=PREPARATION_RECEIPT,
            config_path=config,
            confirm_database=NEW_DATABASE,
            confirm_cutover="CUTOVER-PHASE7B",
            smoke=smoke,
            writer=writer,
            inventory_reader=observe_inventories,
            acl_runner=object(),
            lifecycle_lock=lifecycle,
        )

    assert events == [
        ("lock-attempt", config), "lock-enter", ("write", NEW_DATABASE), "lock-exit",
        "smoke", ("lock-attempt", config), "lock-enter", "contender", "lock-exit",
        ("lock-attempt", config), "lock-enter", ("write", LEGACY_DATABASE), "lock-exit",
    ]
    assert lifecycle.scopes == 3
    assert json.loads(config.read_text(encoding="utf-8")) == original


def exception_leaves(error):
    if isinstance(error, BaseExceptionGroup):
        return [leaf for child in error.exceptions for leaf in exception_leaves(child)]
    return [error]


@pytest.mark.asyncio
async def test_final_lock_contention_skips_final_read_and_retains_new_config(
    workspace_tmp_path, monkeypatch,
):
    config = workspace_tmp_path / ".env.local.json"
    config.write_text(json.dumps(mysql_document()), encoding="utf-8")
    events = []
    lifecycle = RecordingLifecycleLock(events, failures=(None, "acquire"))
    captures = 0
    real_capture = command.capture_local_document_snapshot

    def capture(path):
        nonlocal captures
        captures += 1
        return real_capture(path)

    monkeypatch.setattr(command, "capture_local_document_snapshot", capture)
    with pytest.raises(Exception, match="lifecycle"):
        await command.cutover(
            receipt=PREPARATION_RECEIPT,
            config_path=config,
            confirm_database=NEW_DATABASE,
            confirm_cutover="CUTOVER-PHASE7B",
            smoke=successful_smoke,
            writer=write_json,
            inventory_reader=observe_inventories,
            acl_runner=object(),
            lifecycle_lock=lifecycle,
        )

    assert captures == 1
    assert lifecycle.scopes == 1
    assert json.loads(config.read_text(encoding="utf-8"))["MYSQL_DB"] == NEW_DATABASE


@pytest.mark.asyncio
async def test_rollback_lock_contention_skips_rollback_write_and_keeps_smoke_first(
    workspace_tmp_path,
):
    config = workspace_tmp_path / ".env.local.json"
    config.write_text(json.dumps(mysql_document()), encoding="utf-8")
    events = []
    lifecycle = RecordingLifecycleLock(events, failures=(None, "acquire"))
    writes = []

    def writer(path, document, acl, expected_snapshot):
        writes.append(document["MYSQL_DB"])
        return write_json(path, document, acl, expected_snapshot)

    async def smoke(_document):
        raise RuntimeError(SECRET)

    with pytest.raises(BaseExceptionGroup) as raised:
        await command.cutover(
            receipt=PREPARATION_RECEIPT,
            config_path=config,
            confirm_database=NEW_DATABASE,
            confirm_cutover="CUTOVER-PHASE7B",
            smoke=smoke,
            writer=writer,
            inventory_reader=observe_inventories,
            acl_runner=object(),
            lifecycle_lock=lifecycle,
        )

    assert writes == [NEW_DATABASE]
    assert str(raised.value.exceptions[0]) == "product database cutover smoke failed"
    assert str(raised.value.exceptions[1]) == "product database lifecycle lock failed"
    assert json.loads(config.read_text(encoding="utf-8"))["MYSQL_DB"] == NEW_DATABASE
    assert SECRET not in repr(raised.value)


@pytest.mark.asyncio
async def test_recovery_contention_precedes_config_inventory_and_write(
    workspace_tmp_path, monkeypatch,
):
    config = workspace_tmp_path / ".env.local.json"
    config.write_text(json.dumps(mysql_document(NEW_DATABASE)), encoding="utf-8")
    lifecycle = RecordingLifecycleLock([], failures=("acquire",))
    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append("io")
        raise AssertionError

    monkeypatch.setattr(command, "capture_local_document_snapshot", forbidden)
    with pytest.raises(Exception, match="lifecycle"):
        await command.recover_legacy(
            config_path=config,
            database=LEGACY_DATABASE,
            confirm_cutover="RECOVER-PHASE7B",
            inventory_reader=forbidden,
            writer=forbidden,
            lifecycle_lock=lifecycle,
        )

    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ("initial", "final", "rollback", "recovery"))
async def test_release_failures_are_fixed_and_never_erase_primary(
    workspace_tmp_path, stage,
):
    config = workspace_tmp_path / ".env.local.json"
    config.write_text(
        json.dumps(mysql_document(NEW_DATABASE if stage == "recovery" else LEGACY_DATABASE)),
        encoding="utf-8",
    )
    failures = ("release",) if stage in ("initial", "recovery") else (None, "release")
    lifecycle = RecordingLifecycleLock([], failures=failures)

    async def smoke(_document):
        if stage == "rollback":
            raise RuntimeError(SECRET)

    with pytest.raises(BaseException) as raised:
        if stage == "recovery":
            await command.recover_legacy(
                config_path=config,
                database=LEGACY_DATABASE,
                confirm_cutover="RECOVER-PHASE7B",
                inventory_reader=observe_inventories,
                writer=write_json,
                lifecycle_lock=lifecycle,
            )
        else:
            await command.cutover(
                receipt=PREPARATION_RECEIPT,
                config_path=config,
                confirm_database=NEW_DATABASE,
                confirm_cutover="CUTOVER-PHASE7B",
                smoke=smoke,
                writer=write_json,
                inventory_reader=observe_inventories,
                lifecycle_lock=lifecycle,
            )

    leaves = exception_leaves(raised.value)
    if stage == "rollback":
        assert str(leaves[0]) == "product database cutover smoke failed"
        assert str(leaves[1]) == "product database lifecycle lock cleanup failed"
    else:
        assert [str(leaf) for leaf in leaves] == [
            "product database lifecycle lock cleanup failed"
        ]
    assert SECRET not in repr(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stage", "expected_messages"),
    (
        ("initial", (
            "product database cutover configuration is invalid",
            "product database lifecycle lock cleanup failed",
        )),
        ("final", (
            "product database cutover configuration is invalid",
            "product database lifecycle lock cleanup failed",
        )),
        ("rollback", (
            "product database cutover smoke failed",
            "product database cutover rollback failed",
            "product database lifecycle lock cleanup failed",
        )),
        ("recovery", (
            "product database recovery failed",
            "product database lifecycle lock cleanup failed",
        )),
    ),
)
async def test_stage_error_remains_first_when_same_scope_release_also_fails(
    workspace_tmp_path, stage, expected_messages,
):
    config = workspace_tmp_path / ".env.local.json"
    original = mysql_document(NEW_DATABASE if stage == "recovery" else LEGACY_DATABASE)
    config.write_text(json.dumps(original), encoding="utf-8")
    failures = ("release",) if stage in ("initial", "recovery") else (None, "release")
    lifecycle = RecordingLifecycleLock([], failures=failures)
    writes = 0

    def writer(path, document, acl, expected_snapshot):
        nonlocal writes
        writes += 1
        if stage == "initial" or (stage == "rollback" and writes == 2):
            return None
        return write_json(path, document, acl, expected_snapshot)

    async def inventories(_document):
        if stage == "recovery":
            raise RuntimeError(SECRET)
        return LEGACY_INVENTORY, NEW_INVENTORY

    async def smoke(_document):
        if stage == "final":
            concurrent = {**original, "MYSQL_DB": NEW_DATABASE, "CORPUS_ROOT": "D:/winner"}
            config.write_text(json.dumps(concurrent), encoding="utf-8")
        if stage == "rollback":
            raise RuntimeError(SECRET)

    with pytest.raises(BaseException) as raised:
        if stage == "recovery":
            await command.recover_legacy(
                config_path=config,
                database=LEGACY_DATABASE,
                confirm_cutover="RECOVER-PHASE7B",
                inventory_reader=inventories,
                writer=writer,
                lifecycle_lock=lifecycle,
            )
        else:
            await command.cutover(
                receipt=PREPARATION_RECEIPT,
                config_path=config,
                confirm_database=NEW_DATABASE,
                confirm_cutover="CUTOVER-PHASE7B",
                smoke=smoke,
                inventory_reader=inventories,
                writer=writer,
                lifecycle_lock=lifecycle,
            )

    assert tuple(str(leaf) for leaf in exception_leaves(raised.value)) == expected_messages
    assert SECRET not in repr(raised.value)


class FakeWindowsLifecycleAPI:
    def __init__(self, *, wait_result=0, release_result=False, close_result=False):
        self.handle = object()
        self.wait_result = wait_result
        self.release_result = release_result
        self.close_result = close_result

    def create(self, _name):
        return self.handle

    def wait(self, handle):
        assert handle is self.handle
        return self.wait_result

    def release(self, handle):
        assert handle is self.handle
        return self.release_result

    def close(self, handle):
        assert handle is self.handle
        return self.close_result


@pytest.mark.asyncio
async def test_real_lifecycle_cm_preserves_operation_then_release_close_categories(
    workspace_tmp_path,
):
    config = workspace_tmp_path / ".env.local.json"
    config.write_text(json.dumps(mysql_document()), encoding="utf-8")
    api = FakeWindowsLifecycleAPI()

    def lifecycle(path):
        return lifecycle_service.product_database_lifecycle_lock(
            path, platform_name="nt", windows_api=api
        )

    async def inventories(_document):
        raise RuntimeError(SECRET)

    with pytest.raises(BaseExceptionGroup) as raised:
        await command.cutover(
            receipt=PREPARATION_RECEIPT,
            config_path=config,
            confirm_database=NEW_DATABASE,
            confirm_cutover="CUTOVER-PHASE7B",
            smoke=successful_smoke,
            inventory_reader=inventories,
            lifecycle_lock=lifecycle,
        )

    leaves = exception_leaves(raised.value)
    assert [type(leaf) for leaf in leaves] == [
        command.ProductDatabaseCutoverError,
        lifecycle_service.ProductDatabaseLifecycleError,
        lifecycle_service.ProductDatabaseLifecycleError,
    ]
    assert [leaf.args for leaf in leaves] == [
        ("product database cutover evidence is invalid",),
        ("product database lifecycle lock cleanup failed",),
        ("product database lifecycle lock cleanup failed",),
    ]
    assert SECRET not in repr(raised.value)


@pytest.mark.asyncio
async def test_real_lifecycle_cm_preserves_acquisition_then_close_categories(
    workspace_tmp_path, monkeypatch,
):
    config = workspace_tmp_path / ".env.local.json"
    config.write_text(json.dumps(mysql_document()), encoding="utf-8")
    api = FakeWindowsLifecycleAPI(wait_result=0x00000102)
    reads = 0

    def lifecycle(path):
        return lifecycle_service.product_database_lifecycle_lock(
            path, platform_name="nt", windows_api=api
        )

    def forbidden(_path):
        nonlocal reads
        reads += 1
        raise AssertionError

    monkeypatch.setattr(command, "capture_local_document_snapshot", forbidden)
    with pytest.raises(BaseExceptionGroup) as raised:
        await command.cutover(
            receipt=PREPARATION_RECEIPT,
            config_path=config,
            confirm_database=NEW_DATABASE,
            confirm_cutover="CUTOVER-PHASE7B",
            smoke=successful_smoke,
            inventory_reader=observe_inventories,
            lifecycle_lock=lifecycle,
        )

    assert reads == 0
    assert [leaf.args for leaf in exception_leaves(raised.value)] == [
        ("product database lifecycle lock failed",),
        ("product database lifecycle lock cleanup failed",),
    ]
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
            acl_runner=object(),
            lifecycle_lock=open_lifecycle_lock,
        )

    assert writes == []


@pytest.mark.asyncio
async def test_cutover_validates_exact_receipt_before_lifecycle_lock(workspace_tmp_path):
    config = workspace_tmp_path / ".env.local.json"
    config.write_text(json.dumps(mysql_document()), encoding="utf-8")
    forged = replace(PREPARATION_RECEIPT)
    object.__setattr__(forged, "backup_filename", "../outside.sql")
    calls = []

    def forbidden_lock(_path):
        calls.append("lock")
        raise AssertionError

    with pytest.raises(command.ProductDatabaseCutoverError, match="evidence"):
        await command.cutover(
            receipt=forged,
            config_path=config,
            confirm_database=NEW_DATABASE,
            confirm_cutover="CUTOVER-PHASE7B",
            smoke=successful_smoke,
            inventory_reader=observe_inventories,
            lifecycle_lock=forbidden_lock,
        )

    assert calls == []


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
            acl_runner=object(),
            lifecycle_lock=open_lifecycle_lock,
        )
    assert writes == []


@pytest.mark.asyncio
async def test_smoke_failure_restores_exact_original_document(workspace_tmp_path):
    config = workspace_tmp_path / ".env.local.json"
    original = mysql_document()
    config.write_text(json.dumps(original), encoding="utf-8")
    writes = []
    events = []
    lifecycle = RecordingLifecycleLock(events)

    def writer(path, document, acl, expected_snapshot):
        assert lifecycle.active
        writes.append(dict(document))
        events.append(("write", document["MYSQL_DB"]))
        return write_json(path, document, acl, expected_snapshot)

    async def fail_smoke(_document):
        assert not lifecycle.active
        events.append("smoke")
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
            acl_runner=object(),
            lifecycle_lock=lifecycle,
        )

    assert writes == [{**original, "MYSQL_DB": NEW_DATABASE}, original]
    assert events == [
        ("lock-attempt", config), "lock-enter", ("write", NEW_DATABASE), "lock-exit",
        "smoke",
        ("lock-attempt", config), "lock-enter", ("write", LEGACY_DATABASE), "lock-exit",
    ]
    assert lifecycle.scopes == 2
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
            acl_runner=object(),
            lifecycle_lock=open_lifecycle_lock,
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
            acl_runner=object(),
            lifecycle_lock=open_lifecycle_lock,
        )

    assert writes == [{**original, "MYSQL_DB": NEW_DATABASE}, original]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_factory", "expected_type", "expected_args"),
    (
        (lambda: RuntimeError(SECRET), command.ProductDatabaseCutoverError,
         ("product database cutover evidence is invalid",)),
        (asyncio.CancelledError, asyncio.CancelledError, ()),
        (KeyboardInterrupt, KeyboardInterrupt, ()),
        (lambda: SystemExit(7), SystemExit, (7,)),
        (lambda: SystemExit(True), SystemExit, ()),
        (lambda: SystemExit(SECRET), SystemExit, ()),
    ),
)
async def test_staged_operation_flow_control_precedes_lock_cleanup_exactly(
    workspace_tmp_path, failure_factory, expected_type, expected_args,
):
    config = workspace_tmp_path / ".env.local.json"
    config.write_text(json.dumps(mysql_document()), encoding="utf-8")
    lifecycle = RecordingLifecycleLock([], failures=("release",))

    async def inventories(_document):
        raise failure_factory()

    with pytest.raises(BaseExceptionGroup) as raised:
        await command.cutover(
            receipt=PREPARATION_RECEIPT,
            config_path=config,
            confirm_database=NEW_DATABASE,
            confirm_cutover="CUTOVER-PHASE7B",
            smoke=successful_smoke,
            inventory_reader=inventories,
            lifecycle_lock=lifecycle,
        )

    assert len(raised.value.exceptions) == 2
    primary, cleanup = raised.value.exceptions
    assert type(primary) is expected_type
    assert primary.args == expected_args
    assert type(cleanup) is command.ProductDatabaseCutoverError
    assert cleanup.args == ("product database lifecycle lock cleanup failed",)
    assert SECRET not in repr(raised.value)


@pytest.mark.asyncio
async def test_nested_operation_group_is_preserved_before_lock_cleanup(
    workspace_tmp_path,
):
    config = workspace_tmp_path / ".env.local.json"
    config.write_text(json.dumps(mysql_document()), encoding="utf-8")
    lifecycle = RecordingLifecycleLock([], failures=("release",))

    async def inventories(_document):
        raise BaseExceptionGroup(
            SECRET,
            [RuntimeError(SECRET), BaseExceptionGroup(SECRET, [SystemExit(True)])],
        )

    with pytest.raises(BaseExceptionGroup) as raised:
        await command.cutover(
            receipt=PREPARATION_RECEIPT,
            config_path=config,
            confirm_database=NEW_DATABASE,
            confirm_cutover="CUTOVER-PHASE7B",
            smoke=successful_smoke,
            inventory_reader=inventories,
            lifecycle_lock=lifecycle,
        )

    assert isinstance(raised.value.exceptions[0], BaseExceptionGroup)
    assert [type(leaf) for leaf in exception_leaves(raised.value.exceptions[0])] == [
        command.ProductDatabaseCutoverError,
        SystemExit,
    ]
    assert [leaf.args for leaf in exception_leaves(raised.value.exceptions[0])] == [
        ("product database cutover evidence is invalid",),
        (),
    ]
    assert str(raised.value.exceptions[1]) == (
        "product database lifecycle lock cleanup failed"
    )
    assert SECRET not in repr(raised.value)


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
            acl_runner=lambda _path: None,
            lifecycle_lock=open_lifecycle_lock,
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
            acl_runner=lambda _path: None,
            lifecycle_lock=open_lifecycle_lock,
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
            acl_runner=lambda _path: None,
            lifecycle_lock=open_lifecycle_lock,
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
            lifecycle_lock=open_lifecycle_lock,
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
        lifecycle_lock=open_lifecycle_lock,
    )

    assert result.state == ReadinessState.LEGACY_RETAINED.value
    assert json.loads(config.read_text(encoding="utf-8")) == {
        **original,
        "MYSQL_DB": LEGACY_DATABASE,
    }
    assert observed == [original]
    assert "drop" not in command.recover_legacy.__code__.co_names


@pytest.mark.asyncio
async def test_recovery_uses_one_exact_nondeferred_lock_scope(workspace_tmp_path):
    config = workspace_tmp_path / ".env.local.json"
    config.write_text(json.dumps(mysql_document(NEW_DATABASE)), encoding="utf-8")
    events = []
    lifecycle = RecordingLifecycleLock(events)

    async def inventories(_document):
        assert lifecycle.active
        events.append("inventory")
        return LEGACY_INVENTORY, NEW_INVENTORY

    def writer(path, document, acl, expected_snapshot):
        assert lifecycle.active
        events.append(("write", document["MYSQL_DB"]))
        return write_json(path, document, acl, expected_snapshot)

    result = await command.recover_legacy(
        config_path=config,
        database=LEGACY_DATABASE,
        confirm_cutover="RECOVER-PHASE7B",
        inventory_reader=inventories,
        writer=writer,
        lifecycle_lock=lifecycle,
    )

    assert result.state == ReadinessState.LEGACY_RETAINED.value
    assert events == [
        ("lock-attempt", config), "lock-enter", "inventory",
        ("write", LEGACY_DATABASE), "lock-exit",
    ]
    assert lifecycle.scopes == 1


def test_cli_recovery_requires_exact_closed_action_and_execute():
    assert command.main([
        "--recover-legacy",
        "--database", LEGACY_DATABASE,
        "--confirm-cutover", "RECOVER-PHASE7B",
    ]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "argv",
    (
        (
            "--receipt", "D:/approved.readiness.json",
            "--database", NEW_DATABASE,
            "--confirm-cutover", "CUTOVER-PHASE7B",
        ),
        (
            "--receipt", "D:/approved.readiness.json",
            "--database", LEGACY_DATABASE,
            "--confirm-cutover", "CUTOVER-PHASE7B",
            "--execute",
        ),
        (
            "--receipt", "D:/approved.readiness.json",
            "--database", NEW_DATABASE,
            "--confirm-cutover", "wrong",
            "--execute",
        ),
        ("--database", NEW_DATABASE, "--confirm-cutover", "CUTOVER-PHASE7B", "--execute"),
        (
            "--recover-legacy",
            "--database", LEGACY_DATABASE,
            "--confirm-cutover", "RECOVER-PHASE7B",
        ),
        (
            "--recover-legacy",
            "--database", NEW_DATABASE,
            "--confirm-cutover", "RECOVER-PHASE7B",
            "--execute",
        ),
        (
            "--recover-legacy",
            "--database", LEGACY_DATABASE,
            "--confirm-cutover", "wrong",
            "--execute",
        ),
        (
            "--recover-legacy",
            "--receipt", "D:/approved.readiness.json",
            "--database", LEGACY_DATABASE,
            "--confirm-cutover", "RECOVER-PHASE7B",
            "--execute",
        ),
    ),
)
async def test_cli_rejects_inexact_approval_before_every_io(
    monkeypatch: pytest.MonkeyPatch, argv: tuple[str, ...]
):
    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append("io")
        raise AssertionError("approval must precede all I/O")

    monkeypatch.setattr(command, "capture_local_document_snapshot", forbidden)
    with pytest.raises(command.ProductDatabaseCutoverError) as raised:
        await command.run_cli(
            argv,
            receipt_loader=forbidden,
            backup_verifier=forbidden,
            inventory_reader=forbidden,
            smoke=forbidden,
            writer=forbidden,
            lifecycle_lock=forbidden,
            output=forbidden,
        )

    assert str(raised.value) == "product database cutover approval is invalid"
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_receipt", (None, SimpleNamespace(state="missing")))
async def test_cli_requires_exact_preparation_receipt_before_backup_or_other_io(
    monkeypatch: pytest.MonkeyPatch, loaded_receipt: object
):
    receipt_path = Path("D:/approved.readiness.json")
    calls = []

    def load_receipt(path):
        calls.append(("receipt", path))
        return loaded_receipt

    def forbidden(*_args, **_kwargs):
        calls.append("forbidden")
        raise AssertionError("invalid receipt must stop I/O")

    monkeypatch.setattr(command, "capture_local_document_snapshot", forbidden)
    with pytest.raises(command.ProductDatabaseCutoverError) as raised:
        await command.run_cli(
            (
                "--receipt", str(receipt_path),
                "--database", NEW_DATABASE,
                "--confirm-cutover", "CUTOVER-PHASE7B",
                "--execute",
            ),
            receipt_loader=load_receipt,
            backup_verifier=forbidden,
            inventory_reader=forbidden,
            smoke=forbidden,
            writer=forbidden,
            lifecycle_lock=forbidden,
            output=forbidden,
        )

    assert str(raised.value) == "product database cutover evidence is invalid"
    assert calls == [("receipt", receipt_path)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe_backup_filename",
    ("../outside.sql", "nested/backup.sql", "D:/other/backup.sql"),
)
async def test_cli_rejects_exact_receipt_forged_with_unsafe_backup_authority(
    workspace_tmp_path: Path, unsafe_backup_filename: str
):
    receipt_path = workspace_tmp_path / "receipts" / "approved.readiness.json"
    forged = replace(PREPARATION_RECEIPT)
    object.__setattr__(forged, "backup_filename", unsafe_backup_filename)
    calls = []

    def load_receipt(path):
        calls.append(("receipt", path))
        return forged

    def forbidden(*args, **_kwargs):
        calls.append(("forbidden", args))
        raise AssertionError("forged receipt must not authorize any I/O")

    with pytest.raises(command.ProductDatabaseCutoverError) as raised:
        await command.run_cli(
            (
                "--receipt", str(receipt_path),
                "--database", NEW_DATABASE,
                "--confirm-cutover", "CUTOVER-PHASE7B",
                "--execute",
            ),
            receipt_loader=load_receipt,
            backup_verifier=forbidden,
            inventory_reader=forbidden,
            smoke=forbidden,
            writer=forbidden,
            lifecycle_lock=forbidden,
            output=forbidden,
        )

    assert str(raised.value) == "product database cutover evidence is invalid"
    assert calls == [("receipt", receipt_path)]


@pytest.mark.asyncio
async def test_cli_uses_trusted_class_validation_before_real_backup_verification(
    workspace_tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    receipt_directory = workspace_tmp_path / "receipts"
    receipt_directory.mkdir()
    receipt_path = receipt_directory / "approved.readiness.json"
    outside_backup = workspace_tmp_path / "outside.sql"
    payload = b"outside-decoy-must-not-be-verified"
    outside_backup.write_bytes(payload)
    forged = replace(PREPARATION_RECEIPT)
    object.__setattr__(forged, "backup_filename", "../outside.sql")
    object.__setattr__(forged, "backup_sha256", hashlib.sha256(payload).hexdigest())
    object.__setattr__(forged, "backup_byte_length", len(payload))
    object.__setattr__(forged, "__post_init__", lambda: None)
    real_open = Path.open
    opened_paths = []
    config_reads = 0
    writes = 0

    def observed_open(path: Path, *args: object, **kwargs: object):
        opened_paths.append(path)
        return real_open(path, *args, **kwargs)

    def forbidden_config_read(*_args, **_kwargs):
        nonlocal config_reads
        config_reads += 1
        raise AssertionError("forged receipt must not reach configuration")

    def forbidden_write(*_args, **_kwargs):
        nonlocal writes
        writes += 1
        raise AssertionError("forged receipt must not write configuration")

    monkeypatch.setattr(Path, "open", observed_open)
    monkeypatch.setattr(
        command, "capture_local_document_snapshot", forbidden_config_read
    )
    with pytest.raises(command.ProductDatabaseCutoverError) as raised:
        await command.run_cli(
            (
                "--receipt", str(receipt_path),
                "--database", NEW_DATABASE,
                "--confirm-cutover", "CUTOVER-PHASE7B",
                "--execute",
            ),
            receipt_loader=lambda _path: forged,
            inventory_reader=lambda *_args: pytest.fail("inventory must not run"),
            smoke=lambda *_args: pytest.fail("smoke must not run"),
            writer=forbidden_write,
            lifecycle_lock=lambda _path: pytest.fail("lifecycle lock must not run"),
            output=lambda _value: pytest.fail("output must not run"),
        )

    assert str(raised.value) == "product database cutover evidence is invalid"
    assert opened_paths == []
    assert config_reads == 0
    assert writes == 0


@pytest.mark.asyncio
async def test_cli_verifies_only_receipt_parent_and_declared_closed_filename(
    workspace_tmp_path: Path,
):
    receipt_directory = workspace_tmp_path / "receipts"
    receipt_directory.mkdir()
    receipt_path = receipt_directory / "misleading-stem.readiness.json"
    same_stem_decoy = receipt_directory / "misleading-stem.sql"
    other_directory_decoy = workspace_tmp_path / PREPARATION_RECEIPT.backup_filename
    calls = []

    def load_receipt(path):
        calls.append(("receipt", path))
        return PREPARATION_RECEIPT

    def verify(path, digest, length):
        calls.append(("verify", path, digest, length))
        raise RuntimeError(SECRET)

    with pytest.raises(command.ProductDatabaseCutoverError) as raised:
        await command.run_cli(
            (
                "--receipt", str(receipt_path),
                "--database", NEW_DATABASE,
                "--confirm-cutover", "CUTOVER-PHASE7B",
                "--execute",
            ),
            receipt_loader=load_receipt,
            backup_verifier=verify,
        )

    expected_backup = receipt_directory / PREPARATION_RECEIPT.backup_filename
    assert expected_backup not in (same_stem_decoy, other_directory_decoy)
    assert calls == [
        ("receipt", receipt_path),
        (
            "verify",
            expected_backup,
            PREPARATION_RECEIPT.backup_sha256,
            PREPARATION_RECEIPT.backup_byte_length,
        ),
    ]
    assert str(raised.value) == "product database cutover evidence is invalid"
    assert SECRET not in repr(raised.value)


@pytest.mark.asyncio
async def test_cli_backup_verifier_failure_is_fixed_and_blocks_other_io(
    monkeypatch: pytest.MonkeyPatch,
):
    receipt_path = Path("D:/approved.readiness.json")
    calls = []

    def verify(path, digest, length):
        calls.append(("verify", path, digest, length))
        raise RuntimeError(SECRET)

    def forbidden(*_args, **_kwargs):
        calls.append("forbidden")
        raise AssertionError("failed verification must stop I/O")

    monkeypatch.setattr(command, "capture_local_document_snapshot", forbidden)
    with pytest.raises(command.ProductDatabaseCutoverError) as raised:
        await command.run_cli(
            (
                "--receipt", str(receipt_path),
                "--database", NEW_DATABASE,
                "--confirm-cutover", "CUTOVER-PHASE7B",
                "--execute",
            ),
            receipt_loader=lambda _path: PREPARATION_RECEIPT,
            backup_verifier=verify,
            inventory_reader=forbidden,
            smoke=forbidden,
            writer=forbidden,
            lifecycle_lock=forbidden,
            output=forbidden,
        )

    assert str(raised.value) == "product database cutover evidence is invalid"
    assert SECRET not in repr(raised.value)
    assert calls == [
        (
            "verify",
            receipt_path.parent / PREPARATION_RECEIPT.backup_filename,
            PREPARATION_RECEIPT.backup_sha256,
            PREPARATION_RECEIPT.backup_byte_length,
        )
    ]


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

    def verify_backup(path, digest, length):
        events.append(("backup", path, digest, length))

    async def inventories(document):
        events.append(("inventory", document["MYSQL_DB"]))
        return LEGACY_INVENTORY, NEW_INVENTORY

    @contextmanager
    def idle(_path):
        events.append("lock-enter")
        yield object()
        events.append("lock-exit")

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
        backup_verifier=verify_backup,
        inventory_reader=inventories,
        smoke=smoke,
        writer=writer,
        acl_runner="private-acl",
        lifecycle_lock=idle,
        output=output.append,
    )

    assert result == 0
    assert events == [
        ("receipt", receipt_path),
        (
            "backup",
            receipt_path.parent / PREPARATION_RECEIPT.backup_filename,
            PREPARATION_RECEIPT.backup_sha256,
            PREPARATION_RECEIPT.backup_byte_length,
        ),
        "lock-enter",
        ("inventory", LEGACY_DATABASE),
        ("write", NEW_DATABASE, "private-acl"),
        "lock-exit",
        ("smoke", NEW_DATABASE),
        "lock-enter",
        "lock-exit",
    ]
    assert output == ["state=legacy_retained"]


@pytest.mark.asyncio
async def test_execute_cli_recovery_is_receipt_free(workspace_tmp_path):
    config = workspace_tmp_path / ".env.local.json"
    config.write_text(json.dumps(mysql_document(NEW_DATABASE)), encoding="utf-8")
    output = []

    def forbidden(*_args, **_kwargs):
        raise AssertionError("recovery must not access receipt or backup")

    result = await command.run_cli(
        (
            "--recover-legacy",
            "--database", LEGACY_DATABASE,
            "--confirm-cutover", "RECOVER-PHASE7B",
            "--execute",
        ),
        config_path=config,
        receipt_loader=forbidden,
        backup_verifier=forbidden,
        inventory_reader=observe_inventories,
        writer=write_json,
        acl_runner=object(),
        lifecycle_lock=open_lifecycle_lock,
        output=output.append,
    )

    assert result == 0
    assert output == ["state=legacy_retained"]
    assert (
        json.loads(config.read_text(encoding="utf-8"))["MYSQL_DB"]
        == LEGACY_DATABASE
    )


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


def test_cutover_source_has_no_process_enumeration_or_idle_guard():
    source = Path(command.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "idle_guard",
        "assert_no_product_application_process",
        "_PROCESS_ERROR",
        "Get-CimInstance",
        "Win32_Process",
        "subprocess",
    ):
        assert forbidden not in source
    assert "product_database_lifecycle_lock" in source
