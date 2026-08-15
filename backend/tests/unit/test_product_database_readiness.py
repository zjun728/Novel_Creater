from __future__ import annotations

import asyncio
import ast
from dataclasses import FrozenInstanceError, asdict, dataclass, is_dataclass, replace
import hashlib
import json
from pathlib import Path
import traceback

import pytest

from backend.domain.assets import PACKAGE_VERSION as ASSET_VERSION, load_asset_package
from backend.domain.market_sources import PACKAGE_VERSION as MARKET_VERSION, load_market_source_package
from backend.domain.product_database_readiness import (
    BackupReceipt, DatabaseInventory, LEGACY_DATABASE, NEW_DATABASE,
    ProductDatabaseReadinessError, ReadinessState,
)
from backend.schema_manifest import created_table_names, manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from backend.services.assets import AssetSeedReport
from backend.services.market_sources import MarketSourceSeedReport
from backend.services.product_database_inventory import TableStorage
from backend.services.product_database_readiness import (
    NewDatabaseInitialization, PreexistingNewDatabase, PreparationRequest,
    RestoreDrillResult, SmokeResult, assert_new_database_ready,
    prepare_product_database,
)


ZERO_HASH = "0" * 64
RESTORE_DATABASE = "novel_creator_phase7b_restore_0123456789abcdef0123456789abcdef"
BACKEND_ROOT = Path(__file__).resolve().parents[2]
ASSET_MANIFEST_PATH = BACKEND_ROOT / "assets" / ASSET_VERSION / "manifest.json"
MARKET_MANIFEST_PATH = BACKEND_ROOT / "assets" / MARKET_VERSION / "manifest.json"
ASSET_PACKAGE = load_asset_package(ASSET_MANIFEST_PATH, mode="release")
MARKET_PACKAGE = load_market_source_package(MARKET_MANIFEST_PATH)
SCHEMA_HASH = manifest_hash()


def _hash(value: object) -> str:
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    encoded = json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


ASSET_HASH = _hash(json.loads(ASSET_MANIFEST_PATH.read_text(encoding="utf-8")))
MARKET_HASH = _hash(json.loads(MARKET_MANIFEST_PATH.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class InitializationResult:
    database_name: str
    schema_version: str
    manifest_hash: str
    table_count: int


INITIALIZED = InitializationResult(NEW_DATABASE, EXPECTED_SCHEMA_VERSION, SCHEMA_HASH, len(created_table_names()))


def _empty_counts() -> dict[str, int]:
    return {name: 1 if name == "schema_metadata" else 0 for name in created_table_names()}


def _ready_counts() -> dict[str, int]:
    counts = _empty_counts()
    counts.update({
        "style_templates": 10, "style_template_heads": 10,
        "experience_cards": 64, "experience_card_heads": 64,
        "market_sources": 2, "market_source_policy_revisions": 2,
        "market_source_policy_heads": 2, "market_source_refresh_states": 2,
    })
    return counts


class World:
    """Stateful fake: inventory, reports, restore, and cleanup derive from state."""

    def __init__(self, *, target: str = "absent") -> None:
        self.tables: dict[str, dict[str, int]] = {LEGACY_DATABASE: {"projects": 4}}
        if target == "ready":
            self.tables[NEW_DATABASE] = _ready_counts()
        elif target == "empty":
            self.tables[NEW_DATABASE] = _empty_counts()
        elif target == "partial":
            self.tables[NEW_DATABASE] = _empty_counts() | {"projects": 1}
        self.calls: list[str] = []
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.backup_path: Path | None = None
        self.backup_snapshot: dict[str, int] | None = None
        self.fail_stage: str | None = None
        self.cleanup_failure: BaseException | None = None
        self.restore_result: object | None = None
        self.storage_result: object | None = None
        self.smoke_result: object = SmokeResult(0, 0)

    def snapshot(self, database: str) -> DatabaseInventory:
        rows = tuple(sorted(self.tables[database].items()))
        product = database == NEW_DATABASE
        return DatabaseInventory(
            database=database, server_version="8.4.3",
            schema_version=EXPECTED_SCHEMA_VERSION if product else "writer-core-v1.12.0",
            manifest_hash=SCHEMA_HASH if product else "3" * 64,
            structural_fingerprint="2" * 64 if product else "1" * 64,
            table_names=tuple(name for name, _ in rows), row_counts=rows,
            nonempty_table_count=sum(count > 0 for _, count in rows),
            total_row_count=sum(count for _, count in rows),
        )

    def storage(self, database: str) -> tuple[TableStorage, ...]:
        return tuple(TableStorage(name, "InnoDB", "utf8mb4_0900_ai_ci") for name in sorted(self.tables[database]))

    def _fail(self, stage: str) -> None:
        if self.fail_stage == stage:
            raise RuntimeError(f"password=secret-{stage} dsn=mysql://private")

    async def inventory(self, role: str) -> DatabaseInventory:
        self.calls.append(f"inventory:{role}")
        self._fail(role)
        return self.snapshot(LEGACY_DATABASE if role.startswith("legacy") else NEW_DATABASE)

    async def create_backup(self, authority: DatabaseInventory, directory: Path) -> BackupReceipt:
        self.calls.append("backup")
        directory.mkdir(parents=True, exist_ok=True)
        self.backup_path = directory / "phase7b.sql"
        payload = json.dumps(dict(authority.row_counts), sort_keys=True).encode()
        self.backup_path.write_bytes(payload)
        self.backup_snapshot = dict(authority.row_counts)
        self._fail("backup")
        first = {
            "state": ReadinessState.INVENTORY_VERIFIED.value,
            "previous_receipt_hash": ZERO_HASH,
            "legacy_database": LEGACY_DATABASE, "new_database": NEW_DATABASE,
            "evidence_hash": _hash(asdict(authority)),
        }
        return BackupReceipt(
            ReadinessState.BACKUP_CREATED.value, _hash(first), LEGACY_DATABASE,
            self.backup_path.name, hashlib.sha256(payload).hexdigest(), len(payload),
            "8.4.3", _hash(asdict(authority)),
        )

    async def restore_drill(self, _backup: BackupReceipt, _authority: DatabaseInventory) -> object:
        self.calls.append("restore")
        self._fail("restore")
        if self.restore_result is not None:
            return self.restore_result
        assert self.backup_path is not None and self.backup_path.is_file()
        assert self.backup_snapshot is not None
        self.tables[RESTORE_DATABASE] = dict(self.backup_snapshot)
        self.created.append(RESTORE_DATABASE)
        restored = self.snapshot(RESTORE_DATABASE)
        del self.tables[RESTORE_DATABASE]
        self.deleted.append(RESTORE_DATABASE)
        return RestoreDrillResult(restored, (RESTORE_DATABASE,), (RESTORE_DATABASE,))

    async def initialize_new(self, database: str) -> object:
        self.calls.append("target-boundary")
        if database in self.tables:
            return PreexistingNewDatabase(self.snapshot(database), self.storage(database))
        self.tables[database] = _empty_counts()
        self.created.append(database)
        self.calls.append("initialize")
        try:
            self._fail("initialize")
        except BaseException:
            await self._delete(database)
            raise
        return NewDatabaseInitialization(INITIALIZED, lambda: self._delete(database))

    async def seed_assets(self, database: str) -> AssetSeedReport:
        self.calls.append("seed-assets")
        self._fail("seed-assets")
        self.tables[database].update({"style_templates": 10, "style_template_heads": 10, "experience_cards": 64, "experience_card_heads": 64})
        return AssetSeedReport(ASSET_PACKAGE.package_version, ASSET_HASH, len(ASSET_PACKAGE.styles), len(ASSET_PACKAGE.experience_cards), 74, 0, 0)

    async def seed_market(self, database: str) -> MarketSourceSeedReport:
        self.calls.append("seed-market")
        self._fail("seed-market")
        self.tables[database].update({"market_sources": 2, "market_source_policy_revisions": 2, "market_source_policy_heads": 2, "market_source_refresh_states": 2})
        return MarketSourceSeedReport(MARKET_PACKAGE.package_version, len(MARKET_PACKAGE.sources), MARKET_HASH, 2, 0)

    async def read_storage(self, database: str) -> object:
        self.calls.append("storage")
        self._fail("storage")
        return self.storage_result if self.storage_result is not None else self.storage(database)

    async def smoke(self, _database: str) -> object:
        self.calls.append("smoke")
        self._fail("smoke")
        return self.smoke_result

    async def _delete(self, database: str) -> None:
        self.calls.append("lease-cleanup")
        if self.cleanup_failure is not None:
            raise self.cleanup_failure
        if database in self.tables:
            del self.tables[database]
            self.deleted.append(database)

    async def run(self, tmp_path: Path):
        return await prepare_product_database(
            request=PreparationRequest(LEGACY_DATABASE, NEW_DATABASE, tmp_path.resolve()),
            inventory=self.inventory, create_backup=self.create_backup,
            restore_drill=self.restore_drill, initialize_new=self.initialize_new,
            seed_assets=self.seed_assets, seed_market=self.seed_market,
            read_storage=self.read_storage, smoke=self.smoke,
        )


def _flatten(error: BaseException) -> list[BaseException]:
    if isinstance(error, BaseExceptionGroup):
        return [leaf for child in error.exceptions for leaf in _flatten(child)]
    return [error]


def _seed_payload(inserted: bool) -> dict[str, object]:
    asset_total = len(ASSET_PACKAGE.styles) + len(ASSET_PACKAGE.experience_cards)
    market_total = len(MARKET_PACKAGE.sources)
    return {
        "assets": {"packageVersion": ASSET_PACKAGE.package_version, "packageHash": ASSET_HASH, "styleCount": len(ASSET_PACKAGE.styles), "cardCount": len(ASSET_PACKAGE.experience_cards), "inserted": asset_total if inserted else 0, "replayed": 0 if inserted else asset_total, "advanced": 0},
        "market": {"packageVersion": MARKET_PACKAGE.package_version, "packageHash": MARKET_HASH, "sourceCount": market_total, "inserted": market_total if inserted else 0, "replayed": 0 if inserted else market_total},
    }


def _assert_receipts(result: object, world: World, *, inserted: bool) -> None:
    receipts = result.receipts  # type: ignore[attr-defined]
    before, target = world.snapshot(LEGACY_DATABASE), world.snapshot(NEW_DATABASE)
    assert world.backup_path is not None
    payload = world.backup_path.read_bytes()
    backup = BackupReceipt(ReadinessState.BACKUP_CREATED.value, _hash(asdict(receipts[0])), LEGACY_DATABASE, world.backup_path.name, hashlib.sha256(payload).hexdigest(), len(payload), "8.4.3", _hash(asdict(before)))
    expected = (
        _hash(asdict(before)), _hash(asdict(backup)),
        _hash({"restoreInventoryHash": _hash(asdict(replace(before, database=RESTORE_DATABASE))), "createdDatabases": (RESTORE_DATABASE,), "cleanedDatabases": (RESTORE_DATABASE,)}),
        _hash({"databaseName": NEW_DATABASE, "schemaVersion": EXPECTED_SCHEMA_VERSION, "manifestHash": SCHEMA_HASH, "tableCount": len(created_table_names())}),
        _hash(_seed_payload(inserted)), _hash(asdict(target)),
        _hash({"providerCalls": 0, "outboundRequests": 0}),
    )
    assert tuple(receipt.evidence_hash for receipt in receipts) == expected
    previous = ZERO_HASH
    for receipt in receipts:
        assert receipt.previous_receipt_hash == previous
        previous = _hash(asdict(receipt))
    assert result.previous_receipt_hash == previous  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_absent_target_is_created_seeded_and_independently_receipted(tmp_path: Path) -> None:
    world = World()
    result = await world.run(tmp_path)
    assert world.calls == ["inventory:legacy-before", "backup", "restore", "inventory:legacy-after", "target-boundary", "initialize", "seed-assets", "seed-market", "inventory:new", "storage", "smoke"]
    assert world.tables[NEW_DATABASE] == _ready_counts()
    assert world.created == [RESTORE_DATABASE, NEW_DATABASE]
    assert world.deleted == [RESTORE_DATABASE]
    assert world.backup_path is not None and world.backup_path.is_file()
    _assert_receipts(result, world, inserted=True)


@pytest.mark.asyncio
async def test_exact_ready_resume_is_read_only_and_skips_initialize_and_seeds(tmp_path: Path) -> None:
    world = World(target="ready")
    original = dict(world.tables[NEW_DATABASE])
    result = await world.run(tmp_path)
    assert world.tables[NEW_DATABASE] == original
    assert not {"initialize", "seed-assets", "seed-market", "lease-cleanup"} & set(world.calls)
    assert NEW_DATABASE not in world.created and NEW_DATABASE not in world.deleted
    _assert_receipts(result, world, inserted=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ("empty", "partial"))
async def test_preexisting_nonready_target_is_rejected_without_writes_or_deletion(tmp_path: Path, target: str) -> None:
    world = World(target=target)
    original = dict(world.tables[NEW_DATABASE])
    with pytest.raises(ProductDatabaseReadinessError, match="^new database readiness audit failed$"):
        await world.run(tmp_path)
    assert world.tables[NEW_DATABASE] == original
    assert not {"initialize", "seed-assets", "seed-market", "lease-cleanup"} & set(world.calls)
    assert NEW_DATABASE not in world.created and NEW_DATABASE not in world.deleted
    assert world.backup_path is not None and world.backup_path.is_file()


@pytest.mark.asyncio
async def test_create_then_raise_is_cleaned_inside_initialization_boundary(tmp_path: Path) -> None:
    world = World(); world.fail_stage = "initialize"
    with pytest.raises(ProductDatabaseReadinessError, match="^new database initialization failed$") as raised:
        await world.run(tmp_path)
    assert NEW_DATABASE in world.created and NEW_DATABASE in world.deleted
    assert NEW_DATABASE not in world.tables and world.calls.count("lease-cleanup") == 1
    assert world.backup_path is not None and world.backup_path.is_file()
    assert "secret" not in "".join(traceback.format_exception(raised.value))


@pytest.mark.asyncio
@pytest.mark.parametrize(("stage", "message"), (("seed-assets", "official asset seed failed"), ("seed-market", "official market source seed failed"), ("new", "new database inventory failed"), ("storage", "new database readiness audit failed"), ("smoke", "readiness smoke failed")))
async def test_later_failure_cleans_only_current_run_and_retains_backup(tmp_path: Path, stage: str, message: str) -> None:
    world = World(); world.fail_stage = stage
    with pytest.raises(ProductDatabaseReadinessError, match=f"^{message}$") as raised:
        await world.run(tmp_path)
    assert NEW_DATABASE not in world.tables and world.deleted.count(NEW_DATABASE) == 1
    assert LEGACY_DATABASE in world.tables and LEGACY_DATABASE not in world.deleted
    assert world.backup_path is not None and world.backup_path.is_file()
    assert "secret" not in "".join(traceback.format_exception(raised.value))


@pytest.mark.asyncio
@pytest.mark.parametrize(("stage", "message"), (("legacy-before", "legacy database inventory failed"), ("backup", "product database backup failed"), ("restore", "product database restore drill failed"), ("legacy-after", "legacy database inventory failed")))
async def test_early_failure_never_deletes_preexisting_target(tmp_path: Path, stage: str, message: str) -> None:
    world = World(target="ready"); world.fail_stage = stage
    with pytest.raises(ProductDatabaseReadinessError, match=f"^{message}$"):
        await world.run(tmp_path)
    assert NEW_DATABASE in world.tables and NEW_DATABASE not in world.deleted
    if stage != "legacy-before":
        assert world.backup_path is not None and world.backup_path.is_file()


@pytest.mark.asyncio
async def test_primary_failure_precedes_safe_cleanup_failure(tmp_path: Path) -> None:
    world = World(); world.fail_stage = "smoke"; world.cleanup_failure = RuntimeError("password=cleanup-secret")
    with pytest.raises(BaseExceptionGroup) as raised:
        await world.run(tmp_path)
    assert [str(leaf) for leaf in _flatten(raised.value)] == ["readiness smoke failed", "product database cleanup failed"]
    assert "secret" not in "".join(traceback.format_exception(raised.value))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("cancelled", "keyboard", "system-exit"))
async def test_cleanup_flow_control_is_retained_after_primary_failure(tmp_path: Path, kind: str) -> None:
    world = World(); world.smoke_result = SmokeResult(1, 0)
    world.cleanup_failure = {"cancelled": asyncio.CancelledError("secret"), "keyboard": KeyboardInterrupt("secret"), "system-exit": SystemExit(29)}[kind]
    with pytest.raises(BaseExceptionGroup) as raised:
        await world.run(tmp_path)
    leaves = _flatten(raised.value)
    assert str(leaves[0]) == "readiness smoke crossed network boundary"
    expected = {"cancelled": asyncio.CancelledError, "keyboard": KeyboardInterrupt, "system-exit": SystemExit}[kind]
    assert type(leaves[1]) is expected
    assert (leaves[1].code == 29) if kind == "system-exit" else (leaves[1].args == ())


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("cancelled", "keyboard", "system-exit"))
async def test_primary_flow_control_is_sanitized_after_lease_cleanup(tmp_path: Path, kind: str) -> None:
    world = World()

    async def interrupted(_database: str) -> SmokeResult:
        world.calls.append("smoke")
        if kind == "cancelled":
            raise asyncio.CancelledError("password=primary-secret")
        if kind == "keyboard":
            raise KeyboardInterrupt("password=primary-secret")
        raise SystemExit(23)

    world.smoke = interrupted  # type: ignore[method-assign]
    expected = {"cancelled": asyncio.CancelledError, "keyboard": KeyboardInterrupt, "system-exit": SystemExit}[kind]
    with pytest.raises(expected) as raised:
        await world.run(tmp_path)
    assert NEW_DATABASE not in world.tables and world.deleted.count(NEW_DATABASE) == 1
    assert raised.value.code == 23 if kind == "system-exit" else raised.value.args == ()
    assert world.backup_path is not None and world.backup_path.is_file()


@pytest.mark.asyncio
async def test_malformed_preexisting_snapshot_is_fixed_and_never_cleaned(tmp_path: Path) -> None:
    world = World(target="ready")

    async def malformed(_database: str) -> PreexistingNewDatabase:
        return PreexistingNewDatabase({"database": NEW_DATABASE}, world.storage(NEW_DATABASE))  # type: ignore[arg-type]

    world.initialize_new = malformed  # type: ignore[method-assign]
    with pytest.raises(ProductDatabaseReadinessError, match="^new database readiness audit failed$") as raised:
        await world.run(tmp_path)
    assert raised.value.__cause__ is None and raised.value.__context__ is None
    assert NEW_DATABASE in world.tables and NEW_DATABASE not in world.deleted
    assert not {"seed-assets", "seed-market", "lease-cleanup"} & set(world.calls)


def test_restore_ledger_requires_exact_strings_identity_order_and_uniqueness() -> None:
    restored = replace(World().snapshot(LEGACY_DATABASE), database=RESTORE_DATABASE)
    class Text(str): pass
    malformed = (
        ((Text(RESTORE_DATABASE),), (RESTORE_DATABASE,)),
        ((RESTORE_DATABASE, RESTORE_DATABASE), (RESTORE_DATABASE, RESTORE_DATABASE)),
        ((RESTORE_DATABASE,), ()),
        ((RESTORE_DATABASE,), ("novel_creator_phase7b_restore_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",)),
        (("",), ("",)), ((True,), (True,)),
    )
    for created, cleaned in malformed:
        with pytest.raises(ProductDatabaseReadinessError, match="^product database restore drill failed$") as raised:
            RestoreDrillResult(restored, created, cleaned)  # type: ignore[arg-type]
        assert raised.value.__cause__ is None and raised.value.__context__ is None


@pytest.mark.asyncio
async def test_malformed_restore_object_maps_fixed_error_before_hashing(tmp_path: Path) -> None:
    class EqualitySpoof:
        def __eq__(self, _other: object) -> bool: return True
    world = World(); world.restore_result = EqualitySpoof()
    with pytest.raises(ProductDatabaseReadinessError, match="^product database restore drill failed$") as raised:
        await world.run(tmp_path)
    assert type(raised.value) is ProductDatabaseReadinessError and raised.value.__cause__ is None


@pytest.mark.parametrize("field", ("name", "engine", "collation"))
def test_audit_rejects_nonexact_and_blank_storage_fields(field: str) -> None:
    world = World(target="ready"); target = world.snapshot(NEW_DATABASE)
    assets = AssetSeedReport(ASSET_PACKAGE.package_version, ASSET_HASH, 10, 64, 74, 0, 0)
    market = MarketSourceSeedReport(MARKET_PACKAGE.package_version, 2, MARKET_HASH, 2, 0)
    class Text(str): pass
    original = world.storage(NEW_DATABASE)[0]
    valid = {"name": original.name, "engine": original.engine, "collation": original.collation}[field]
    for invalid in (Text(valid), "", "   ", True):
        rows = list(world.storage(NEW_DATABASE)); rows[0] = replace(original, **{field: invalid})
        with pytest.raises(ProductDatabaseReadinessError, match="^new database readiness audit failed$"):
            assert_new_database_ready(target, INITIALIZED, assets, market, tuple(rows))


@pytest.mark.asyncio
async def test_initialization_equality_spoof_fails_then_uses_lease(tmp_path: Path) -> None:
    class EqualitySpoof:
        def __eq__(self, _other: object) -> bool: return True
    world = World()
    async def malformed(database: str) -> NewDatabaseInitialization:
        world.tables[database] = _empty_counts(); world.created.append(database)
        return NewDatabaseInitialization(replace(INITIALIZED, manifest_hash=EqualitySpoof()), lambda: world._delete(database))
    world.initialize_new = malformed  # type: ignore[method-assign]
    with pytest.raises(ProductDatabaseReadinessError, match="^new database initialization failed$"):
        await world.run(tmp_path)
    assert NEW_DATABASE not in world.tables and world.deleted.count(NEW_DATABASE) == 1
    assert "seed-assets" not in world.calls


@pytest.mark.asyncio
@pytest.mark.parametrize(("field", "value"), (("provider_calls", 1), ("outbound_requests", 1)))
async def test_smoke_requires_zero_provider_and_outbound(tmp_path: Path, field: str, value: int) -> None:
    world = World(); world.smoke_result = replace(SmokeResult(0, 0), **{field: value})
    with pytest.raises(ProductDatabaseReadinessError, match="^readiness smoke crossed network boundary$"):
        await world.run(tmp_path)
    assert NEW_DATABASE not in world.tables


def test_request_is_frozen_and_rejects_wrong_roles_or_paths(tmp_path: Path) -> None:
    request = PreparationRequest(LEGACY_DATABASE, NEW_DATABASE, tmp_path.resolve())
    with pytest.raises(FrozenInstanceError): request.new_database = LEGACY_DATABASE  # type: ignore[misc]
    with pytest.raises(ProductDatabaseReadinessError): PreparationRequest(NEW_DATABASE, NEW_DATABASE, tmp_path.resolve())
    with pytest.raises(ProductDatabaseReadinessError): PreparationRequest(LEGACY_DATABASE, NEW_DATABASE, Path("relative"))


def test_module_has_no_cli_database_provider_network_or_config_imports() -> None:
    source = (BACKEND_ROOT / "services" / "product_database_readiness.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None}
    imported.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
    forbidden = ("backend.config", "backend.database", "backend.gateways", "backend.scripts", "backend.security", "httpx", "subprocess")
    assert all(not any(module == prefix or module.startswith(f"{prefix}.") for prefix in forbidden) for module in imported)
