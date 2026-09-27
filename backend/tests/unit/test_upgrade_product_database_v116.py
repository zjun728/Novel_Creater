from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import replace
from pathlib import Path
import traceback

import pytest

from backend.domain.product_database_readiness import DatabaseInventory
from backend.scripts import upgrade_product_database_v116 as upgrade


def inventory(*, current=False):
    names = tuple(sorted(upgrade.v116_table_names() if current else upgrade.v115_table_names()))
    counts = tuple((name, int(name == "schema_metadata")) for name in names)
    return DatabaseInventory(
        database=upgrade.PRODUCT_DATABASE, server_version="8.4.10",
        schema_version=upgrade.V116_SCHEMA_VERSION if current else upgrade.V115_SCHEMA_VERSION,
        manifest_hash=upgrade.V116_MANIFEST_HASH if current else upgrade.V115_MANIFEST_HASH,
        structural_fingerprint=upgrade.V116_STRUCTURAL_FINGERPRINT if current else upgrade.V115_STRUCTURAL_FINGERPRINT,
        table_names=names, row_counts=counts, nonempty_table_count=1, total_row_count=1,
    )


class World:
    def __init__(self, directory):
        self.events = []
        self.old = inventory()
        self.new = inventory(current=True)
        self.fail = None
        self.receipt = upgrade.UpgradeBackupReceipt(
            upgrade.PRODUCT_DATABASE, upgrade.V115_SCHEMA_VERSION,
            directory / ("phase7b-backup-" + "a" * 32 + ".sql"), "b" * 64, 100,
            upgrade.RESTORE_MODE,
        )

    def step(self, event):
        self.events.append(event)
        if self.fail == event:
            raise RuntimeError("private-password-sentinel")

    @asynccontextmanager
    async def lock(self, _database):
        self.step("lock")
        try:
            yield
        finally:
            self.step("unlock")

    async def read(self, _database):
        self.step("inventory")
        return self.old

    async def backup(self, **_kwargs):
        self.step("backup")
        return self.receipt

    async def verify_backup(self, receipt):
        assert receipt is self.receipt
        self.step("verify_backup")

    async def apply(self, database, confirmation, now_ms, callback):
        callback()
        self.step("ddl")
        return upgrade.SchemaUpgradeResult(database, upgrade.V115_SCHEMA_VERSION, upgrade.V116_SCHEMA_VERSION, 1, 101)

    async def verify(self, _database):
        self.step("verify")
        return self.new

    def dependencies(self):
        return upgrade.ProductUpgradeDependencies(self.lock, self.read, self.backup, self.verify_backup, self.apply, self.verify)


async def run(world, directory, **kwargs):
    return await upgrade.run_product_upgrade(
        dependencies=kwargs.pop("dependencies", world.dependencies()),
        database=upgrade.PRODUCT_DATABASE, confirm_database=upgrade.PRODUCT_DATABASE,
        backup_directory=directory, mysqldump=directory / "mysqldump.exe",
        mysql=directory / "mysql.exe", now_ms=1000,
        receipt_output=lambda receipt: world.step("receipt"), **kwargs,
    )


def test_historical_and_new_manifests_are_fixed():
    upgrade._validate_static_manifest()
    assert len(upgrade.v115_table_names()) == 100
    assert len(upgrade.v116_table_names()) == 101
    assert set(upgrade.v116_table_names()) - set(upgrade.v115_table_names()) == {"review_finding_decisions"}
    assert len(upgrade.review_decision_statements()) == 1


@pytest.mark.asyncio
async def test_backup_receipt_is_verified_before_the_only_schema_change(tmp_path):
    world = World(tmp_path)
    result = await run(world, tmp_path)
    assert result.to_schema == "writer-core-v1.16.0"
    assert result.added_tables == 1 and result.table_count == 101
    assert world.events == ["lock", "inventory", "backup", "receipt", "verify_backup", "ddl", "verify", "unlock"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["lock", "inventory", "backup", "receipt", "verify_backup"])
async def test_preflight_failures_never_reach_ddl(tmp_path, failure):
    world = World(tmp_path)
    world.fail = failure
    with pytest.raises(upgrade.SchemaUpgradeError) as raised:
        await run(world, tmp_path)
    assert not isinstance(raised.value, upgrade.SchemaUpgradeRestoreRequired)
    assert "ddl" not in world.events
    assert "private-password-sentinel" not in "".join(traceback.format_exception(raised.value))


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["ddl", "verify", "unlock"])
async def test_post_ddl_failure_retains_exact_receipt_without_automatic_restore(tmp_path, failure):
    world = World(tmp_path)
    world.fail = failure
    with pytest.raises(upgrade.SchemaUpgradeRestoreRequired) as raised:
        await run(world, tmp_path)
    assert raised.value.receipt is world.receipt
    assert "restore required" in str(raised.value)
    assert "private-password-sentinel" not in "".join(traceback.format_exception(raised.value))


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"manifest_hash": "a" * 64}, {"schema_version": "writer-core-v1.13.0"},
    {"structural_fingerprint": "a" * 64}, {"server_version": "8.0.40"},
])
async def test_inventory_drift_rejects_before_backup(tmp_path, changes):
    world = World(tmp_path)
    world.old = replace(world.old, **changes)
    with pytest.raises(upgrade.SchemaUpgradeError):
        await run(world, tmp_path)
    assert world.events == ["lock", "inventory", "unlock"]


@pytest.mark.asyncio
async def test_old_table_row_count_drift_after_upgrade_requires_restore(tmp_path):
    world = World(tmp_path)
    counts = tuple((name, count + int(name == "projects")) for name, count in world.new.row_counts)
    world.new = replace(world.new, row_counts=counts, nonempty_table_count=2, total_row_count=2)
    with pytest.raises(upgrade.SchemaUpgradeRestoreRequired) as raised:
        await run(world, tmp_path)
    assert raised.value.receipt is world.receipt


@pytest.mark.asyncio
async def test_cancellation_after_ddl_keeps_recovery_authority(tmp_path):
    world = World(tmp_path)
    async def cancel(*args):
        args[-1]()
        raise asyncio.CancelledError()
    with pytest.raises(upgrade.SchemaUpgradeRestoreRequired) as raised:
        await run(world, tmp_path, dependencies=replace(world.dependencies(), apply_schema=cancel))
    assert raised.value.receipt is world.receipt


@pytest.mark.asyncio
async def test_cli_rejects_unconfirmed_database_before_loading_config():
    with pytest.raises(upgrade.SchemaUpgradeError):
        await upgrade.run_cli(["--database", "other", "--confirm-database", "other", "--backup-directory", str(Path.cwd()), "--mysqldump", "dump", "--mysql", "client"])


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"from_schema": "writer-core-v1.13.0"}, {"database": "other"},
    {"backup_sha256": "invalid"}, {"backup_byte_length": 0},
    {"backup_byte_length": True}, {"restore_mode": "overwrite"},
    {"backup_path": Path("relative.sql")},
])
async def test_bad_receipt_is_rejected_before_schema_or_publication(tmp_path, changes):
    world = World(tmp_path)
    world.receipt = replace(world.receipt, **changes)
    with pytest.raises(upgrade.SchemaUpgradeError):
        await run(world, tmp_path)
    assert world.events == ["lock", "inventory", "backup", "unlock"]


@pytest.mark.asyncio
async def test_cli_publishes_backup_recovery_authority_and_exact_version(tmp_path):
    world = World(tmp_path)
    output = []
    result = await upgrade.run_cli(
        ["--database", upgrade.PRODUCT_DATABASE, "--confirm-database", upgrade.PRODUCT_DATABASE,
         "--backup-directory", str(tmp_path), "--mysqldump", str(tmp_path / "mysqldump.exe"),
         "--mysql", str(tmp_path / "mysql.exe")],
        dependencies=world.dependencies(), connection_config={
            "host": "test-host", "port": 33060, "user": "test-user",
            "password": "private-password-sentinel", "db": upgrade.PRODUCT_DATABASE,
        }, now_ms=lambda: 1000, output=output.append,
    )
    assert result == 0
    assert f"backup_receipt.path={world.receipt.backup_path}" in output[0]
    assert "backup_receipt.from_schema=writer-core-v1.15.0" in output[0]
    assert "to_schema=writer-core-v1.16.0" in output[1]
    assert "table_count=101" in output[1]
    assert "private-password-sentinel" not in "\n".join(output)


@pytest.mark.asyncio
async def test_default_lock_holds_lifecycle_and_mysql_lock_in_one_connection(monkeypatch):
    import aiomysql
    import backend.config as config
    import backend.database as database
    import backend.services.product_database_lifecycle_lock as lifecycle

    events = []

    @contextmanager
    def local_lock(path):
        assert path == config.LOCAL_CONFIG_PATH
        events.append("lifecycle-enter")
        try:
            yield
        finally:
            events.append("lifecycle-exit")

    class Raw:
        async def ensure_closed(self):
            events.append("connection-close")

    async def connect(**kwargs):
        assert events == ["lifecycle-enter"]
        assert kwargs["db"] == upgrade.PRODUCT_DATABASE
        assert kwargs["autocommit"] is True
        events.append("connect")
        return Raw()

    class Session:
        def __init__(self, raw):
            pass
        async def fetchone(self, sql, params):
            assert params == (upgrade.UPGRADE_LOCK_NAME,)
            if "GET_LOCK" in sql:
                events.append("mysql-lock")
                return {"acquired": 1}
            assert "RELEASE_LOCK" in sql
            events.append("mysql-unlock")
            return {"released": 1}

    monkeypatch.setattr(lifecycle, "product_database_lifecycle_lock", local_lock)
    monkeypatch.setattr(aiomysql, "connect", connect)
    monkeypatch.setattr(database, "DatabaseSession", Session)
    dependencies = upgrade._default_dependencies({
        "host": "test", "port": 33060, "user": "test", "password": "secret", "db": upgrade.PRODUCT_DATABASE,
    })
    with pytest.raises(upgrade.SchemaUpgradeRestoreRequired):
        async with dependencies.upgrade_lock(upgrade.PRODUCT_DATABASE):
            events.append("body")
            raise upgrade.SchemaUpgradeRestoreRequired()
    assert events == ["lifecycle-enter", "connect", "mysql-lock", "body",
                      "mysql-unlock", "connection-close", "lifecycle-exit"]
