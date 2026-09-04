from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from hashlib import sha256

import pytest

from backend.domain.market_sources import PACKAGE_VERSION
from backend.schema_manifest import STATEMENT_DELIMITER, created_table_names, manifest_hash
from backend.scripts.upgrade_product_database_v114 import (
    MARKET_SOURCE_INVENTORY_INCOMPATIBLE,
    ProductUpgradeDependencies,
    SchemaUpgradeError,
    SchemaUpgradeResult,
    SchemaUpgradeRestoreRequired,
    UpgradeBackupReceipt,
    UpgradeInventory,
    UpgradeVerification,
    UPGRADE_LOCK_NAME,
    _default_dependencies,
    _backup_runner,
    _ensure_private_backup_directory,
    _version_runner,
    format_product_upgrade_result,
    run_cli,
    run_product_upgrade,
    topic_statements,
    upgrade_v113_to_v114,
    v113_manifest_hash,
    v113_statements,
    v113_table_names,
)


DATABASE = "novel_creator_v113"
V113_MARKET_SOURCE_KEYS = (
    "fanqie.reading",
    "qidian.newsign",
    "qimao.public-catalog",
    "qq-reading.male-popular",
    "shuqi.public-catalog",
)
PRE_CORRECTION_V11_MARKET_SOURCE_KEYS = (
    "17k.top",
    "fanqie.reading",
    "heiyan.diamond",
    "hongxiu.hotsales",
    "jjwxc.quarterly-score",
    "qidian.newsign",
    "qimao.public-catalog",
    "qq-reading.male-popular",
    "shuqi.public-catalog",
    "zongheng.monthly",
)
CURRENT_V11_MARKET_SOURCE_KEYS = (
    "fanqie.reading",
    "heiyan.daily-recommendation",
    "jjwxc.quarterly-score",
    "qidian.newsign",
    "qimao.public-catalog",
    "qq-reading.male-popular",
    "readnovel.original-monthly-ticket",
    "shuqi.public-catalog",
    "xxsy.xiaoxiang-ticket",
    "zongheng.monthly",
)
CONFIRMED_DATABASE = {
    "database": DATABASE,
    "confirm_database": DATABASE,
    "now_ms": 1_800_000_000_000,
}


class FakeUpgradeSession:
    def __init__(
        self,
        *,
        version: str = "writer-core-v1.13.0",
        manifest: str | None = None,
        tables: tuple[str, ...] | None = None,
        server_version: str = "8.4.6",
        fail_ddl_at: int | None = None,
        ddl_error: BaseException | None = None,
        metadata_changed: int = 1,
    ) -> None:
        self.version = version
        self.manifest = manifest or v113_manifest_hash()
        self.tables = tuple(sorted(tables or v113_table_names()))
        self.server_version = server_version
        self.fail_ddl_at = fail_ddl_at
        self.ddl_error = ddl_error or RuntimeError("password=secret-sentinel")
        self.metadata_changed = metadata_changed
        self.executed: list[tuple[str, object]] = []
        self.executed_ddl: list[str] = []
        self.metadata_update: tuple[object, ...] | None = None
        self._topic_count = 0

    async def fetchone(self, sql, parameters=None):
        if "VERSION()" in sql:
            return {"version": self.server_version}
        assert "schema_metadata" in sql
        return {"schema_version": self.version, "manifest_hash": self.manifest}

    async def fetchall(self, sql, parameters=None):
        assert "information_schema.TABLES" in sql
        assert parameters == (DATABASE,)
        names = tuple(sorted(created_table_names())) if self._topic_count else self.tables
        return tuple({"TABLE_NAME": name} for name in names)

    async def execute(self, sql, parameters=None):
        self.executed.append((sql, parameters))
        if sql in topic_statements():
            self._topic_count += 1
            if self.fail_ddl_at == self._topic_count:
                raise self.ddl_error
            self.executed_ddl.append(sql)
            return 0
        assert sql.startswith("UPDATE schema_metadata")
        self.metadata_update = parameters
        return self.metadata_changed


def old_inventory(**changes) -> UpgradeInventory:
    names = tuple(sorted(v113_table_names()))
    base = UpgradeInventory(
        database=DATABASE,
        server_version="8.4.6",
        schema_version="writer-core-v1.13.0",
        manifest_hash=v113_manifest_hash(),
        table_names=names,
    )
    return replace(base, **changes)


def test_v113_manifest_is_derived_by_excluding_only_topics_with_same_hash_algorithm():
    expected = "\n;-- statement\n".join(v113_statements()).encode("utf-8")

    assert len(v113_statements()) == 92
    assert len(v113_table_names()) == 91
    assert len(topic_statements()) == 8
    assert len(created_table_names()) == 99
    assert v113_manifest_hash() == sha256(expected).hexdigest()
    assert v113_manifest_hash() != manifest_hash()
    assert STATEMENT_DELIMITER == ";-- statement"


@pytest.mark.asyncio
async def test_upgrade_requires_exact_old_metadata_and_91_tables():
    session = FakeUpgradeSession()

    result = await upgrade_v113_to_v114(session, **CONFIRMED_DATABASE)

    assert result.table_count == 99
    assert tuple(session.executed_ddl) == topic_statements()
    assert session.metadata_update == (
        "writer-core-v1.14.0",
        manifest_hash(),
        1_800_000_000_000,
        "writer-core-v1.13.0",
        v113_manifest_hash(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "session,arguments",
    [
        (FakeUpgradeSession(), {**CONFIRMED_DATABASE, "confirm_database": "other"}),
        (FakeUpgradeSession(version="writer-core-v1.12.0"), CONFIRMED_DATABASE),
        (
            FakeUpgradeSession(
                version="writer-core-v1.14.0",
                manifest=manifest_hash(),
                tables=tuple(created_table_names()),
            ),
            CONFIRMED_DATABASE,
        ),
        (FakeUpgradeSession(manifest="0" * 64), CONFIRMED_DATABASE),
        (FakeUpgradeSession(server_version="8.0.40"), CONFIRMED_DATABASE),
        (FakeUpgradeSession(tables=v113_table_names()[:-1]), CONFIRMED_DATABASE),
        (FakeUpgradeSession(tables=(*v113_table_names(), "unexpected_table")), CONFIRMED_DATABASE),
        (FakeUpgradeSession(tables=(*v113_table_names(), "topic_discussions")), CONFIRMED_DATABASE),
    ],
)
async def test_upgrade_rejects_invalid_or_partial_old_authority_before_writing(session, arguments):
    with pytest.raises(SchemaUpgradeError, match="preflight"):
        await upgrade_v113_to_v114(session, **arguments)

    assert session.executed == []


@pytest.mark.asyncio
async def test_upgrade_reports_fixed_restore_required_after_any_ddl_failure():
    session = FakeUpgradeSession(fail_ddl_at=3)

    with pytest.raises(SchemaUpgradeRestoreRequired) as raised:
        await upgrade_v113_to_v114(session, **CONFIRMED_DATABASE)

    assert str(raised.value) == "schema upgrade failed after DDL began; restore required"
    assert "secret-sentinel" not in str(raised.value)
    assert session.metadata_update is None


@pytest.mark.asyncio
async def test_cancelled_ddl_still_reports_restore_required_instead_of_silent_partial_exit():
    session = FakeUpgradeSession(
        fail_ddl_at=3,
        ddl_error=asyncio.CancelledError("secret-sentinel"),
    )

    with pytest.raises(SchemaUpgradeRestoreRequired) as raised:
        await upgrade_v113_to_v114(session, **CONFIRMED_DATABASE)

    assert str(raised.value) == "schema upgrade failed after DDL began; restore required"
    assert "secret-sentinel" not in str(raised.value)


@pytest.mark.asyncio
async def test_upgrade_metadata_cas_conflict_requires_restore_and_never_claims_rollback():
    session = FakeUpgradeSession(metadata_changed=0)

    with pytest.raises(SchemaUpgradeRestoreRequired) as raised:
        await upgrade_v113_to_v114(session, **CONFIRMED_DATABASE)

    assert "restore required" in str(raised.value)
    assert "rollback" not in str(raised.value).lower()


class FakeProductWorld:
    def __init__(self, market_source_keys=V113_MARKET_SOURCE_KEYS) -> None:
        self.events: list[str] = []
        self.market_source_keys = market_source_keys

    @asynccontextmanager
    async def lock(self, database):
        assert database == DATABASE
        self.events.append("lock-acquire")
        try:
            yield
        finally:
            self.events.append("lock-release")

    async def inventory(self, database):
        assert database == DATABASE
        self.events.append("inventory")
        return old_inventory()

    async def market_source_inventory(self, database):
        assert database == DATABASE
        self.events.append("market-source-inventory")
        return tuple({"stable_key": key} for key in self.market_source_keys)

    async def backup(self, **kwargs):
        assert kwargs["inventory"] == old_inventory()
        self.events.append("backup")
        return UpgradeBackupReceipt(
            database=DATABASE,
            from_schema="writer-core-v1.13.0",
            backup_path=kwargs["backup_directory"]
            / "phase7b-backup-0123456789abcdef0123456789abcdef.sql",
            backup_sha256="a" * 64,
            backup_byte_length=42,
            restore_mode="drop-recreate-clean-target",
        )

    async def verify_backup(self, receipt):
        assert receipt.backup_sha256 == "a" * 64
        self.events.append("backup-verify")

    async def schema(self, database, confirm_database, now_ms, on_ddl_started):
        assert (database, confirm_database, now_ms) == (
            DATABASE,
            DATABASE,
            1_800_000_000_000,
        )
        on_ddl_started()
        self.events.extend(("ddl", "metadata"))
        return SchemaUpgradeResult(
            database=DATABASE,
            from_schema="writer-core-v1.13.0",
            to_schema="writer-core-v1.14.0",
            added_tables=8,
            table_count=99,
        )

    async def market(self, database):
        self.events.append("seed-market")
        return type(
            "MarketReport",
            (),
            {"package_version": PACKAGE_VERSION, "source_count": 10},
        )()

    async def verify(self, database):
        self.events.append("verify")
        return UpgradeVerification(
            database=DATABASE,
            schema_version="writer-core-v1.14.0",
            manifest_hash=manifest_hash(),
            table_count=99,
            package_version=PACKAGE_VERSION,
            source_count=10,
        )

    def dependencies(self):
        return ProductUpgradeDependencies(
            upgrade_lock=self.lock,
            inventory=self.inventory,
            market_source_inventory=self.market_source_inventory,
            create_backup=self.backup,
            verify_backup=self.verify_backup,
            apply_schema=self.schema,
            seed_market=self.market,
            verify=self.verify,
        )


@pytest.mark.asyncio
async def test_product_upgrade_orders_backup_before_ddl_and_sources_after_metadata(tmp_path):
    world = FakeProductWorld()
    receipts = []

    result = await run_product_upgrade(
        dependencies=world.dependencies(),
        database=DATABASE,
        confirm_database=DATABASE,
        backup_directory=tmp_path,
        mysqldump=tmp_path / "mysqldump.exe",
        mysql=tmp_path / "mysql.exe",
        now_ms=1_800_000_000_000,
        receipt_output=receipts.append,
    )

    assert world.events == [
        "lock-acquire",
        "inventory",
        "market-source-inventory",
        "backup",
        "backup-verify",
        "ddl",
        "metadata",
        "seed-market",
        "verify",
        "lock-release",
    ]
    assert result.backup_sha256 == "a" * 64
    assert result.added_tables == 8
    assert receipts == [
        UpgradeBackupReceipt(
            database=DATABASE,
            from_schema="writer-core-v1.13.0",
            backup_path=tmp_path
            / "phase7b-backup-0123456789abcdef0123456789abcdef.sql",
            backup_sha256="a" * 64,
            backup_byte_length=42,
            restore_mode="drop-recreate-clean-target",
        )
    ]
    assert "rollback" not in format_product_upgrade_result(result).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "market_source_keys",
    (
        (),
        V113_MARKET_SOURCE_KEYS[:-1],
        (*V113_MARKET_SOURCE_KEYS, "unexpected.source"),
        (*V113_MARKET_SOURCE_KEYS, V113_MARKET_SOURCE_KEYS[0]),
        PRE_CORRECTION_V11_MARKET_SOURCE_KEYS,
        CURRENT_V11_MARKET_SOURCE_KEYS,
    ),
)
async def test_incompatible_market_source_inventory_refuses_before_backup_or_ddl(
    tmp_path, market_source_keys
):
    world = FakeProductWorld(market_source_keys)

    with pytest.raises(SchemaUpgradeError) as raised:
        await run_product_upgrade(
            dependencies=world.dependencies(),
            database=DATABASE,
            confirm_database=DATABASE,
            backup_directory=tmp_path,
            mysqldump=tmp_path / "mysqldump.exe",
            mysql=tmp_path / "mysql.exe",
            now_ms=1_800_000_000_000,
        )

    assert str(raised.value) == MARKET_SOURCE_INVENTORY_INCOMPATIBLE
    assert world.events == [
        "lock-acquire",
        "inventory",
        "market-source-inventory",
        "lock-release",
    ]
    assert not any(
        event in world.events
        for event in ("backup", "backup-verify", "ddl", "metadata", "seed-market")
    )


@pytest.mark.asyncio
async def test_interruption_after_schema_change_still_requires_backup_restore(tmp_path):
    world = FakeProductWorld()

    async def cancelled_market(_database):
        world.events.append("seed-market")
        raise asyncio.CancelledError("secret-sentinel")

    dependencies = replace(world.dependencies(), seed_market=cancelled_market)

    with pytest.raises(SchemaUpgradeRestoreRequired) as raised:
        await run_product_upgrade(
            dependencies=dependencies,
            database=DATABASE,
            confirm_database=DATABASE,
            backup_directory=tmp_path,
            mysqldump=tmp_path / "mysqldump.exe",
            mysql=tmp_path / "mysql.exe",
            now_ms=1_800_000_000_000,
        )

    assert str(raised.value) == "schema upgrade failed after DDL began; restore required"
    assert "secret-sentinel" not in str(raised.value)


@pytest.mark.asyncio
async def test_backup_receipt_is_emitted_before_ddl_failure_and_remains_exact(tmp_path):
    world = FakeProductWorld()
    receipts = []

    async def failed_schema(*args):
        args[-1]()
        world.events.append("ddl")
        raise SchemaUpgradeRestoreRequired(
            "schema upgrade failed after DDL began; restore required"
        )

    def emit(receipt):
        world.events.append("receipt")
        receipts.append(receipt)

    dependencies = replace(world.dependencies(), apply_schema=failed_schema)

    with pytest.raises(SchemaUpgradeRestoreRequired):
        await run_product_upgrade(
            dependencies=dependencies,
            database=DATABASE,
            confirm_database=DATABASE,
            backup_directory=tmp_path,
            mysqldump=tmp_path / "mysqldump.exe",
            mysql=tmp_path / "mysql.exe",
            now_ms=1_800_000_000_000,
            receipt_output=emit,
        )

    assert world.events == [
        "lock-acquire", "inventory", "market-source-inventory",
        "backup", "receipt", "backup-verify",
        "ddl", "lock-release",
    ]
    assert receipts == [
        UpgradeBackupReceipt(
            database=DATABASE,
            from_schema="writer-core-v1.13.0",
            backup_path=tmp_path
            / "phase7b-backup-0123456789abcdef0123456789abcdef.sql",
            backup_sha256="a" * 64,
            backup_byte_length=42,
            restore_mode="drop-recreate-clean-target",
        )
    ]


@pytest.mark.asyncio
async def test_same_single_receipt_survives_failure_after_metadata_before_verify(tmp_path):
    world = FakeProductWorld()
    receipts = []

    async def failed_market(_database):
        world.events.append("seed-market")
        raise RuntimeError("password=secret-sentinel")

    def emit(receipt):
        world.events.append("receipt")
        receipts.append(receipt)

    dependencies = replace(world.dependencies(), seed_market=failed_market)

    with pytest.raises(SchemaUpgradeRestoreRequired) as raised:
        await run_product_upgrade(
            dependencies=dependencies,
            database=DATABASE,
            confirm_database=DATABASE,
            backup_directory=tmp_path,
            mysqldump=tmp_path / "mysqldump.exe",
            mysql=tmp_path / "mysql.exe",
            now_ms=1_800_000_000_000,
            receipt_output=emit,
        )

    assert str(raised.value) == "schema upgrade failed after DDL began; restore required"
    assert world.events == [
        "lock-acquire",
        "inventory",
        "market-source-inventory",
        "backup",
        "receipt",
        "backup-verify",
        "ddl",
        "metadata",
        "seed-market",
        "lock-release",
    ]
    assert len(receipts) == 1
    assert receipts[0].backup_path == (
        tmp_path / "phase7b-backup-0123456789abcdef0123456789abcdef.sql"
    )
    assert receipts[0].backup_sha256 == "a" * 64
    assert receipts[0].backup_byte_length == 42
    assert raised.value.receipt is receipts[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"backup_byte_length": 0},
        {"backup_sha256": "x" * 64},
        {"restore_mode": "import-over-partial"},
    ],
)
async def test_invalid_backup_receipt_blocks_all_database_writes(tmp_path, changes):
    events = []

    async def inventory(_database):
        events.append("inventory")
        return old_inventory()

    async def create_backup(**kwargs):
        events.append("backup")
        return replace(
            UpgradeBackupReceipt(
                database=DATABASE,
                from_schema="writer-core-v1.13.0",
                backup_path=kwargs["backup_directory"]
                / "phase7b-backup-0123456789abcdef0123456789abcdef.sql",
                backup_sha256="a" * 64,
                backup_byte_length=42,
                restore_mode="drop-recreate-clean-target",
            ),
            **changes,
        )

    async def forbidden(*_args, **_kwargs):
        events.append("write")
        raise AssertionError("must not write")

    world = FakeProductWorld()
    dependencies = replace(
        world.dependencies(),
        inventory=inventory,
        create_backup=create_backup,
        verify_backup=forbidden,
        apply_schema=forbidden,
        seed_market=forbidden,
        verify=forbidden,
    )

    with pytest.raises(SchemaUpgradeError, match="backup"):
        await run_product_upgrade(
            dependencies=dependencies,
            database=DATABASE,
            confirm_database=DATABASE,
            backup_directory=tmp_path,
            mysqldump=tmp_path / "mysqldump.exe",
            mysql=tmp_path / "mysql.exe",
            now_ms=1_800_000_000_000,
        )

    assert events == ["inventory", "backup"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    (
        "mysql client preflight failed",
        "mysql connection preflight failed",
        "logical backup failed",
    ),
)
async def test_client_connection_or_backup_refusal_has_no_server_writes_or_disposable_db(
    tmp_path, failure
):
    world = FakeProductWorld()

    async def refused_backup(**_kwargs):
        world.events.append("backup-refused")
        raise SchemaUpgradeError(failure)

    with pytest.raises(SchemaUpgradeError, match=failure):
        await run_product_upgrade(
            dependencies=replace(world.dependencies(), create_backup=refused_backup),
            database=DATABASE,
            confirm_database=DATABASE,
            backup_directory=tmp_path,
            mysqldump=tmp_path / "mysqldump.exe",
            mysql=tmp_path / "mysql.exe",
            now_ms=1_800_000_000_000,
        )

    assert world.events == [
        "lock-acquire",
        "inventory",
        "market-source-inventory",
        "backup-refused",
        "lock-release",
    ]
    assert not any("create" in event or "drop" in event for event in world.events)


@pytest.mark.asyncio
async def test_cli_output_is_fixed_and_contains_no_connection_secrets(tmp_path):
    world = FakeProductWorld()
    output = []
    secret_config = {
        "host": "host-sentinel",
        "port": 3307,
        "user": "user-sentinel",
        "password": "password-sentinel",
        "db": DATABASE,
    }

    code = await run_cli(
        [
            "--database", DATABASE,
            "--confirm-database", DATABASE,
            "--backup-directory", str(tmp_path),
            "--mysqldump", str(tmp_path / "mysqldump.exe"),
            "--mysql", str(tmp_path / "mysql.exe"),
        ],
        dependencies=world.dependencies(),
        connection_config=secret_config,
        now_ms=lambda: 1_800_000_000_000,
        output=output.append,
    )

    rendered = "\n".join(output)
    assert code == 0
    assert "host-sentinel" not in rendered
    assert "user-sentinel" not in rendered
    assert "password-sentinel" not in rendered
    assert rendered.count("backup_receipt.path=") == 1
    assert "backup_receipt.database=novel_creator_v113" in rendered
    assert "backup_receipt.from_schema=writer-core-v1.13.0" in rendered
    assert (
        f"backup_receipt.path={tmp_path}\\"
        "phase7b-backup-0123456789abcdef0123456789abcdef.sql"
    ) in rendered
    assert "backup_receipt.sha256=" + "a" * 64 in rendered
    assert "backup_receipt.byte_length=42" in rendered
    assert "backup_receipt.restore_mode=drop-recreate-clean-target" in rendered
    assert (
        "backup_receipt.restore_guidance="
        "drop/recreate target before importing exact backup"
    ) in rendered
    assert "database=novel_creator_v113" in rendered
    assert "from_schema=writer-core-v1.13.0" in rendered
    assert "to_schema=writer-core-v1.14.0" in rendered
    assert "table_count=99" in rendered
    assert "source_count=10" in rendered


@pytest.mark.asyncio
async def test_cli_keeps_exact_emitted_receipt_when_ddl_phase_fails(tmp_path):
    world = FakeProductWorld()
    output = []

    async def failed_schema(*args):
        args[-1]()
        raise SchemaUpgradeRestoreRequired(
            "schema upgrade failed after DDL began; restore required"
        )

    dependencies = replace(world.dependencies(), apply_schema=failed_schema)

    with pytest.raises(SchemaUpgradeRestoreRequired):
        await run_cli(
            [
                "--database", DATABASE,
                "--confirm-database", DATABASE,
                "--backup-directory", str(tmp_path),
                "--mysqldump", str(tmp_path / "mysqldump.exe"),
                "--mysql", str(tmp_path / "mysql.exe"),
            ],
            dependencies=dependencies,
            connection_config={
                "host": "host-sentinel",
                "port": 3307,
                "user": "user-sentinel",
                "password": "password-sentinel",
                "db": DATABASE,
            },
            now_ms=lambda: 1_800_000_000_000,
            output=output.append,
        )

    rendered = "\n".join(output)
    assert rendered.count("backup_receipt.path=") == 1
    assert "backup_receipt.sha256=" + "a" * 64 in rendered
    assert "backup_receipt.byte_length=42" in rendered
    assert "backup_receipt.restore_mode=drop-recreate-clean-target" in rendered
    assert "drop/recreate target before importing exact backup" in rendered
    assert "host-sentinel" not in rendered
    assert "user-sentinel" not in rendered
    assert "password-sentinel" not in rendered


@pytest.mark.asyncio
async def test_published_backup_is_revalidated_immediately_before_ddl(tmp_path):
    world = FakeProductWorld()

    async def failed_revalidation(_receipt):
        world.events.append("backup-verify")
        raise RuntimeError("password=secret-sentinel")

    with pytest.raises(SchemaUpgradeError) as raised:
        await run_product_upgrade(
            dependencies=replace(
                world.dependencies(), verify_backup=failed_revalidation
            ),
            database=DATABASE,
            confirm_database=DATABASE,
            backup_directory=tmp_path,
            mysqldump=tmp_path / "mysqldump.exe",
            mysql=tmp_path / "mysql.exe",
            now_ms=1_800_000_000_000,
        )

    assert str(raised.value) == "product database upgrade failed"
    assert "secret-sentinel" not in repr(raised.value)
    assert world.events[-2:] == ["backup-verify", "lock-release"]
    assert "ddl" not in world.events


@pytest.mark.asyncio
async def test_apply_returns_then_session_exit_cancellation_requires_restore(tmp_path):
    world = FakeProductWorld()

    @asynccontextmanager
    async def cancelling_session():
        yield
        raise asyncio.CancelledError("password=secret-sentinel")

    async def schema(database, confirmation, now_ms, on_ddl_started):
        async with cancelling_session():
            on_ddl_started()
            world.events.extend(("ddl", "metadata"))
            return SchemaUpgradeResult(
                database=database,
                from_schema="writer-core-v1.13.0",
                to_schema="writer-core-v1.14.0",
                added_tables=8,
                table_count=99,
            )

    with pytest.raises(SchemaUpgradeRestoreRequired) as raised:
        await run_product_upgrade(
            dependencies=replace(world.dependencies(), apply_schema=schema),
            database=DATABASE,
            confirm_database=DATABASE,
            backup_directory=tmp_path,
            mysqldump=tmp_path / "mysqldump.exe",
            mysql=tmp_path / "mysql.exe",
            now_ms=1_800_000_000_000,
        )

    assert str(raised.value) == "schema upgrade failed after DDL began; restore required"
    assert raised.value.receipt is not None


@pytest.mark.asyncio
async def test_preddl_cancellation_propagates_and_lock_releases(tmp_path):
    world = FakeProductWorld()

    async def cancelled_before_ddl(*_args):
        raise asyncio.CancelledError("pre-ddl")

    with pytest.raises(asyncio.CancelledError, match="pre-ddl"):
        await run_product_upgrade(
            dependencies=replace(world.dependencies(), apply_schema=cancelled_before_ddl),
            database=DATABASE,
            confirm_database=DATABASE,
            backup_directory=tmp_path,
            mysqldump=tmp_path / "mysqldump.exe",
            mysql=tmp_path / "mysql.exe",
            now_ms=1_800_000_000_000,
        )

    assert world.events[-1] == "lock-release"


@pytest.mark.asyncio
async def test_concurrent_upgrade_lock_refuses_before_backup_and_ddl(tmp_path):
    world = FakeProductWorld()

    @asynccontextmanager
    async def refused_lock(_database):
        world.events.append("lock-refused")
        raise SchemaUpgradeError("product database upgrade lock failed")
        yield

    with pytest.raises(SchemaUpgradeError, match="upgrade lock failed"):
        await run_product_upgrade(
            dependencies=replace(world.dependencies(), upgrade_lock=refused_lock),
            database=DATABASE,
            confirm_database=DATABASE,
            backup_directory=tmp_path,
            mysqldump=tmp_path / "mysqldump.exe",
            mysql=tmp_path / "mysql.exe",
            now_ms=1_800_000_000_000,
        )

    assert world.events == ["lock-refused"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_result",
    [
        type("Lookalike", (), {
            "database": DATABASE,
            "from_schema": "writer-core-v1.13.0",
            "to_schema": "writer-core-v1.14.0",
            "added_tables": 8,
            "table_count": 99,
        })(),
        SchemaUpgradeResult(DATABASE, "wrong", "writer-core-v1.14.0", 8, 99),
        SchemaUpgradeResult(DATABASE, "writer-core-v1.13.0", "writer-core-v1.14.0", 7, 99),
    ],
)
async def test_schema_result_contract_is_exact_after_ddl(tmp_path, bad_result):
    world = FakeProductWorld()

    async def bad_schema(*args):
        args[-1]()
        world.events.append("ddl")
        return bad_result

    with pytest.raises(SchemaUpgradeRestoreRequired):
        await run_product_upgrade(
            dependencies=replace(world.dependencies(), apply_schema=bad_schema),
            database=DATABASE,
            confirm_database=DATABASE,
            backup_directory=tmp_path,
            mysqldump=tmp_path / "mysqldump.exe",
            mysql=tmp_path / "mysql.exe",
            now_ms=1_800_000_000_000,
        )


@pytest.mark.asyncio
async def test_default_advisory_lock_uses_one_fixed_name_and_releases(monkeypatch):
    events = []

    class Cursor:
        def __init__(self):
            self.row = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def execute(self, sql, parameters):
            events.append((sql, parameters))
            self.row = {"acquired": 1} if "GET_LOCK" in sql else {"released": 1}

        async def fetchone(self):
            return self.row

    class Raw:
        def cursor(self, _kind):
            return Cursor()

        async def ensure_closed(self):
            events.append("closed")

    async def connect(**kwargs):
        assert kwargs == {
            "host": "localhost",
            "port": 3307,
            "user": "user",
            "password": "password",
            "charset": "utf8mb4",
            "autocommit": True,
        }
        return Raw()

    monkeypatch.setattr("aiomysql.connect", connect)
    dependencies = _default_dependencies(
        {
            "host": "localhost",
            "port": 3307,
            "user": "user",
            "password": "password",
            "db": DATABASE,
        }
    )

    async with dependencies.upgrade_lock(DATABASE):
        events.append("body")

    assert UPGRADE_LOCK_NAME == "writer-core:upgrade:novel_creator_v113:v114"
    assert events == [
        ("SELECT GET_LOCK(%s, 0) AS acquired", (UPGRADE_LOCK_NAME,)),
        "body",
        ("SELECT RELEASE_LOCK(%s) AS released", (UPGRADE_LOCK_NAME,)),
        "closed",
    ]


@pytest.mark.asyncio
async def test_default_market_source_inventory_uses_one_read_only_select(monkeypatch):
    events = []

    class Cursor:
        def __init__(self):
            self.sql = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def execute(self, sql, parameters):
            self.sql = sql
            events.append((sql, parameters))

        async def fetchall(self):
            assert self.sql == "SELECT stable_key FROM market_sources ORDER BY stable_key"
            return tuple({"stable_key": key} for key in V113_MARKET_SOURCE_KEYS)

        @property
        def rowcount(self):
            return 0

    class Raw:
        def cursor(self, _kind):
            return Cursor()

        async def ensure_closed(self):
            events.append("closed")

    async def connect(**kwargs):
        assert kwargs == {
            "host": "localhost",
            "port": 3307,
            "user": "user",
            "password": "password",
            "charset": "utf8mb4",
            "autocommit": True,
        }
        return Raw()

    monkeypatch.setattr("aiomysql.connect", connect)
    dependencies = _default_dependencies(
        {
            "host": "localhost",
            "port": 3307,
            "user": "user",
            "password": "password",
            "db": DATABASE,
        }
    )

    rows = await dependencies.market_source_inventory(DATABASE)

    assert rows == tuple({"stable_key": key} for key in V113_MARKET_SOURCE_KEYS)
    assert events == [
        (f"USE `{DATABASE}`", None),
        ("START TRANSACTION READ ONLY", None),
        ("SELECT stable_key FROM market_sources ORDER BY stable_key", None),
        ("ROLLBACK", None),
        "closed",
    ]


def test_all_mysql_client_processes_have_finite_timeouts(monkeypatch, tmp_path):
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr("subprocess.run", run)
    _version_runner(tmp_path / "mysql.exe")
    _backup_runner(["mysqldump.exe"])

    assert [call[1]["timeout"] for call in calls] == [30, 1_800]


def test_backup_directory_must_be_a_dedicated_new_leaf(tmp_path):
    existing = tmp_path / "already-present"
    existing.mkdir()

    with pytest.raises(SchemaUpgradeError, match="directory preflight"):
        _ensure_private_backup_directory(existing)
