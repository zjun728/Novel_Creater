from __future__ import annotations

import asyncio
import ast
from dataclasses import FrozenInstanceError, asdict, dataclass, replace
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
import backend.services.product_database_readiness as readiness_module
from backend.services.product_database_readiness import (
    OfficialDataAudit, PreparationRequest, RestoreDrillResult, SmokeResult,
    assert_new_database_ready, prepare_product_database,
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
    return hashlib.sha256(json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


ASSET_MANIFEST_RAW = json.loads(ASSET_MANIFEST_PATH.read_text(encoding="utf-8"))
MARKET_MANIFEST_RAW = json.loads(MARKET_MANIFEST_PATH.read_text(encoding="utf-8"))
STYLE_ROWS = json.loads((ASSET_MANIFEST_PATH.parent / ASSET_MANIFEST_RAW["styles_file"]["path"]).read_text(encoding="utf-8"))
CARD_ROWS = json.loads((ASSET_MANIFEST_PATH.parent / ASSET_MANIFEST_RAW["experience_cards_file"]["path"]).read_text(encoding="utf-8"))
MARKET_ROWS = json.loads((MARKET_MANIFEST_PATH.parent / MARKET_MANIFEST_RAW["sources_file"]["path"]).read_text(encoding="utf-8"))
ASSET_HASH = _hash(ASSET_MANIFEST_RAW)
MARKET_HASH = _hash(MARKET_MANIFEST_RAW)
STYLE_CONTENT_HASH = ASSET_MANIFEST_RAW["styles_file"]["sha256"]
CARD_CONTENT_HASH = ASSET_MANIFEST_RAW["experience_cards_file"]["sha256"]
MARKET_CONTENT_HASH = MARKET_MANIFEST_RAW["sources_file"]["sha256"]
STYLE_COUNT = len(STYLE_ROWS)
CARD_COUNT = len(CARD_ROWS)
MARKET_COUNT = len(MARKET_ROWS)
MARKET_AUTHORITY = tuple(sorted(row["stableKey"] for row in MARKET_ROWS))


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


def _official_row() -> dict[str, object]:
    return {
        "asset_package_version": ASSET_MANIFEST_RAW["package_version"],
        "asset_package_hash": ASSET_HASH,
        "style_content_hash": STYLE_CONTENT_HASH,
        "style_count": STYLE_COUNT,
        "card_content_hash": CARD_CONTENT_HASH,
        "card_count": CARD_COUNT,
        "market_package_version": MARKET_MANIFEST_RAW["package_version"],
        "market_package_hash": MARKET_HASH,
        "market_content_hash": MARKET_CONTENT_HASH,
        "market_source_count": MARKET_COUNT,
        "market_source_authority": MARKET_AUTHORITY,
    }


def _audit_payload() -> dict[str, object]:
    row = _official_row()
    return {
        "assetPackageVersion": row["asset_package_version"],
        "assetPackageHash": row["asset_package_hash"],
        "styleContentHash": row["style_content_hash"],
        "styleCount": row["style_count"],
        "cardContentHash": row["card_content_hash"],
        "cardCount": row["card_count"],
        "marketPackageVersion": row["market_package_version"],
        "marketPackageHash": row["market_package_hash"],
        "marketContentHash": row["market_content_hash"],
        "marketSourceCount": row["market_source_count"],
        "marketSourceAuthority": row["market_source_authority"],
    }


def _inventory_from_json(payload: dict[str, object]) -> DatabaseInventory:
    payload = dict(payload)
    payload["table_names"] = tuple(payload["table_names"])  # type: ignore[arg-type]
    payload["row_counts"] = tuple(tuple(row) for row in payload["row_counts"])  # type: ignore[arg-type]
    return DatabaseInventory(**payload)  # type: ignore[arg-type]


class World:
    """Stateful fake whose reads derive from database and backup-file state."""

    def __init__(self, *, target: str = "absent") -> None:
        self.tables: dict[str, dict[str, int]] = {LEGACY_DATABASE: {"projects": 4}}
        self.official_rows: dict[str, dict[str, object]] = {}
        if target == "ready":
            self.tables[NEW_DATABASE] = _ready_counts()
            self.official_rows[NEW_DATABASE] = _official_row()
        elif target == "empty":
            self.tables[NEW_DATABASE] = _empty_counts()
        elif target == "partial":
            self.tables[NEW_DATABASE] = _empty_counts() | {"projects": 1}
        self.calls: list[str] = []
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.backup_directory: Path | None = None
        self.backup_path: Path | None = None
        self.fail_stage: str | None = None
        self.cleanup_failure: BaseException | None = None
        self.tamper_backup = False
        self.legacy_drift = False
        self.restore_inventory_mismatch = False
        self.restore_primary: BaseException | None = None
        self.restore_cleanup_failure: BaseException | None = None
        self.smoke_result: object = SmokeResult(0, 0)

    def snapshot(self, database: str) -> DatabaseInventory:
        rows = tuple(sorted(self.tables[database].items()))
        product = database == NEW_DATABASE
        fingerprint = "2" * 64 if product else "1" * 64
        return DatabaseInventory(
            database, "8.4.3",
            EXPECTED_SCHEMA_VERSION if product else "writer-core-v1.12.0",
            SCHEMA_HASH if product else "3" * 64, fingerprint,
            tuple(name for name, _ in rows), rows,
            sum(count > 0 for _, count in rows), sum(count for _, count in rows),
        )

    def storage(self, database: str) -> tuple[TableStorage, ...]:
        return tuple(TableStorage(name, "InnoDB", "utf8mb4_0900_ai_ci") for name in sorted(self.tables[database]))

    def _fail(self, stage: str) -> None:
        if self.fail_stage == stage:
            raise RuntimeError(f"password=secret-{stage} dsn=mysql://private")

    async def inventory(self, role: str) -> DatabaseInventory:
        self.calls.append(f"inventory:{role}")
        self._fail(role)
        value = self.snapshot(LEGACY_DATABASE if role.startswith("legacy") else NEW_DATABASE)
        if role == "legacy-after" and self.legacy_drift:
            value = replace(value, structural_fingerprint="8" * 64)
        return value

    async def create_backup(self, authority: DatabaseInventory, directory: Path) -> BackupReceipt:
        self.calls.append("backup")
        directory.mkdir(parents=True, exist_ok=True)
        self.backup_directory = directory
        self.backup_path = directory / "phase7b.json"
        raw = json.dumps(asdict(authority), allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
        self.backup_path.write_bytes(raw)
        first = {"state": ReadinessState.INVENTORY_VERIFIED.value, "previous_receipt_hash": ZERO_HASH, "legacy_database": LEGACY_DATABASE, "new_database": NEW_DATABASE, "evidence_hash": _hash(asdict(authority))}
        receipt = BackupReceipt(ReadinessState.BACKUP_CREATED.value, _hash(first), LEGACY_DATABASE, self.backup_path.name, hashlib.sha256(raw).hexdigest(), len(raw), "8.4.3", _hash(asdict(authority)))
        if self.tamper_backup:
            self.backup_path.write_bytes(raw + b"tampered")
        self._fail("backup")
        return receipt

    async def restore_drill(self, receipt: BackupReceipt, authority: DatabaseInventory) -> RestoreDrillResult:
        self.calls.append("restore")
        self._fail("restore")
        assert self.backup_directory is not None
        path = self.backup_directory / receipt.backup_filename
        raw = path.read_bytes()
        if len(raw) != receipt.backup_byte_length or hashlib.sha256(raw).hexdigest() != receipt.backup_sha256:
            raise RuntimeError("password=backup-tamper")
        restored_authority = _inventory_from_json(json.loads(raw.decode("utf-8")))
        if (
            restored_authority != authority
            or _hash(asdict(restored_authority)) != receipt.source_inventory_hash
        ):
            raise RuntimeError("password=backup-authority-mismatch")
        self.tables[RESTORE_DATABASE] = dict(restored_authority.row_counts)
        self.created.append(RESTORE_DATABASE)
        restored = replace(restored_authority, database=RESTORE_DATABASE)
        if self.restore_inventory_mismatch:
            restored = replace(restored, structural_fingerprint="7" * 64)
        if self.restore_primary is not None:
            primary = self.restore_primary
            try:
                await self._drop_restore()
            except BaseException as cleanup:
                raise BaseExceptionGroup("restore boundary failed", [primary, cleanup])
            raise primary
        await self._drop_restore()
        return RestoreDrillResult(restored, (RESTORE_DATABASE,), (RESTORE_DATABASE,))

    async def _drop_restore(self) -> None:
        self.calls.append("restore-cleanup")
        if self.restore_cleanup_failure is not None:
            raise self.restore_cleanup_failure
        del self.tables[RESTORE_DATABASE]
        self.deleted.append(RESTORE_DATABASE)

    async def probe_new(self, database: str) -> DatabaseInventory | None:
        self.calls.append("probe:new")
        self._fail("probe")
        return None if database not in self.tables else self.snapshot(database)

    async def initialize_new(self, database: str) -> InitializationResult:
        self.calls.append("initialize")
        if self.fail_stage == "initialize-before-create":
            self._fail("initialize-before-create")
        self.tables[database] = _empty_counts()
        self.created.append(database)
        self._fail("initialize")
        return INITIALIZED

    async def seed_assets(self, database: str) -> AssetSeedReport:
        self.calls.append("seed-assets")
        self._fail("seed-assets")
        self.tables[database].update({"style_templates": 10, "style_template_heads": 10, "experience_cards": 64, "experience_card_heads": 64})
        row = self.official_rows.setdefault(database, {})
        row.update({"asset_package_version": ASSET_MANIFEST_RAW["package_version"], "asset_package_hash": ASSET_HASH, "style_content_hash": STYLE_CONTENT_HASH, "style_count": STYLE_COUNT, "card_content_hash": CARD_CONTENT_HASH, "card_count": CARD_COUNT})
        return AssetSeedReport(ASSET_MANIFEST_RAW["package_version"], ASSET_HASH, STYLE_COUNT, CARD_COUNT, STYLE_COUNT + CARD_COUNT, 0, 0)

    async def seed_market(self, database: str) -> MarketSourceSeedReport:
        self.calls.append("seed-market")
        self._fail("seed-market")
        self.tables[database].update({"market_sources": 2, "market_source_policy_revisions": 2, "market_source_policy_heads": 2, "market_source_refresh_states": 2})
        row = self.official_rows.setdefault(database, {})
        row.update({"market_package_version": MARKET_MANIFEST_RAW["package_version"], "market_package_hash": MARKET_HASH, "market_content_hash": MARKET_CONTENT_HASH, "market_source_count": MARKET_COUNT, "market_source_authority": MARKET_AUTHORITY})
        return MarketSourceSeedReport(MARKET_MANIFEST_RAW["package_version"], MARKET_COUNT, MARKET_HASH, MARKET_COUNT, 0)

    async def read_storage(self, database: str) -> tuple[TableStorage, ...]:
        self.calls.append("storage")
        self._fail("storage")
        return self.storage(database)

    async def audit_official_data(self, database: str) -> OfficialDataAudit:
        self.calls.append("official-audit")
        self._fail("official-audit")
        return OfficialDataAudit(**self.official_rows[database])  # type: ignore[arg-type]

    async def smoke(self, _database: str) -> object:
        self.calls.append("smoke")
        self._fail("smoke")
        return self.smoke_result

    async def cleanup_new(self, database: str) -> None:
        self.calls.append("cleanup:new")
        if self.cleanup_failure is not None:
            raise self.cleanup_failure
        if database in self.tables:
            del self.tables[database]
            self.official_rows.pop(database, None)
            self.deleted.append(database)

    async def run(self, tmp_path: Path):
        return await prepare_product_database(
            request=PreparationRequest(LEGACY_DATABASE, NEW_DATABASE, tmp_path.resolve()),
            inventory=self.inventory, create_backup=self.create_backup,
            restore_drill=self.restore_drill, probe_new=self.probe_new,
            initialize_new=self.initialize_new, seed_assets=self.seed_assets,
            seed_market=self.seed_market, read_storage=self.read_storage,
            audit_official_data=self.audit_official_data, smoke=self.smoke,
            cleanup_new=self.cleanup_new,
        )


def _flatten(error: BaseException) -> list[BaseException]:
    if isinstance(error, BaseExceptionGroup):
        return [leaf for child in error.exceptions for leaf in _flatten(child)]
    return [error]


def _assert_receipts(result: object, world: World) -> None:
    receipts = result.receipts  # type: ignore[attr-defined]
    before, target = world.snapshot(LEGACY_DATABASE), world.snapshot(NEW_DATABASE)
    assert world.backup_path is not None
    raw = world.backup_path.read_bytes()
    first_payload = {"state": ReadinessState.INVENTORY_VERIFIED.value, "previous_receipt_hash": ZERO_HASH, "legacy_database": LEGACY_DATABASE, "new_database": NEW_DATABASE, "evidence_hash": _hash(asdict(before))}
    backup = BackupReceipt(ReadinessState.BACKUP_CREATED.value, _hash(first_payload), LEGACY_DATABASE, world.backup_path.name, hashlib.sha256(raw).hexdigest(), len(raw), "8.4.3", _hash(asdict(before)))
    expected_evidence = (
        first_payload["evidence_hash"], _hash(asdict(backup)),
        _hash({"restoreInventoryHash": _hash(asdict(replace(before, database=RESTORE_DATABASE))), "createdDatabases": (RESTORE_DATABASE,), "cleanedDatabases": (RESTORE_DATABASE,)}),
        _hash({"databaseName": NEW_DATABASE, "schemaVersion": EXPECTED_SCHEMA_VERSION, "manifestHash": SCHEMA_HASH, "tableCount": len(created_table_names())}),
        _hash(_audit_payload()), _hash(asdict(target)),
        _hash({"providerCalls": 0, "outboundRequests": 0}),
    )
    states = tuple(state.value for state in tuple(ReadinessState)[:7])
    previous = ZERO_HASH
    for receipt, state, evidence in zip(receipts, states, expected_evidence, strict=True):
        expected_payload = {"state": state, "previous_receipt_hash": previous, "legacy_database": LEGACY_DATABASE, "new_database": NEW_DATABASE, "evidence_hash": evidence}
        assert asdict(receipt) == expected_payload
        previous = _hash(expected_payload)
    assert result.previous_receipt_hash == previous  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_absent_preflight_creates_audits_and_receipts_from_state(tmp_path: Path) -> None:
    world = World()
    result = await world.run(tmp_path)
    assert world.calls == ["inventory:legacy-before", "backup", "restore", "restore-cleanup", "inventory:legacy-after", "probe:new", "initialize", "seed-assets", "seed-market", "inventory:new", "storage", "official-audit", "smoke"]
    assert world.tables[NEW_DATABASE] == _ready_counts()
    assert world.created == [RESTORE_DATABASE, NEW_DATABASE]
    assert world.deleted == [RESTORE_DATABASE]
    _assert_receipts(result, world)


@pytest.mark.asyncio
async def test_exact_ready_preexisting_target_is_read_only(tmp_path: Path) -> None:
    world = World(target="ready")
    original_tables, original_official = dict(world.tables[NEW_DATABASE]), dict(world.official_rows[NEW_DATABASE])
    result = await world.run(tmp_path)
    assert world.tables[NEW_DATABASE] == original_tables
    assert world.official_rows[NEW_DATABASE] == original_official
    assert not {"initialize", "seed-assets", "seed-market", "cleanup:new"} & set(world.calls)
    assert world.calls[-4:] == ["probe:new", "storage", "official-audit", "smoke"]
    _assert_receipts(result, world)


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ("empty", "partial"))
async def test_nonready_preexisting_target_rejects_before_writes(tmp_path: Path, target: str) -> None:
    world = World(target=target); original = dict(world.tables[NEW_DATABASE])
    with pytest.raises(ProductDatabaseReadinessError, match="^new database readiness audit failed$"):
        await world.run(tmp_path)
    assert world.tables[NEW_DATABASE] == original
    assert not {"initialize", "seed-assets", "seed-market", "cleanup:new", "official-audit"} & set(world.calls)


@pytest.mark.asyncio
async def test_create_then_raise_is_found_by_probe_and_cleaned_by_service(tmp_path: Path) -> None:
    world = World(); world.fail_stage = "initialize"
    with pytest.raises(ProductDatabaseReadinessError, match="^new database initialization failed$") as raised:
        await world.run(tmp_path)
    assert world.calls[-4:] == ["probe:new", "initialize", "probe:new", "cleanup:new"]
    assert NEW_DATABASE in world.created and NEW_DATABASE in world.deleted and NEW_DATABASE not in world.tables
    assert "secret" not in "".join(traceback.format_exception(raised.value))
    assert world.backup_path is not None and world.backup_path.is_file()


@pytest.mark.asyncio
async def test_initialize_failure_before_create_probes_absent_and_never_cleans(tmp_path: Path) -> None:
    world = World(); world.fail_stage = "initialize-before-create"
    with pytest.raises(ProductDatabaseReadinessError, match="^new database initialization failed$"):
        await world.run(tmp_path)
    assert world.calls[-3:] == ["probe:new", "initialize", "probe:new"]
    assert "cleanup:new" not in world.calls and NEW_DATABASE not in world.deleted


@pytest.mark.asyncio
@pytest.mark.parametrize(("stage", "message"), (("seed-assets", "official asset seed failed"), ("seed-market", "official market source seed failed"), ("new", "new database inventory failed"), ("storage", "new database readiness audit failed"), ("official-audit", "new database readiness audit failed"), ("smoke", "readiness smoke failed")))
async def test_later_failure_cleans_only_service_owned_target(tmp_path: Path, stage: str, message: str) -> None:
    world = World(); world.fail_stage = stage
    with pytest.raises(ProductDatabaseReadinessError, match=f"^{message}$") as raised:
        await world.run(tmp_path)
    assert NEW_DATABASE not in world.tables and world.deleted.count(NEW_DATABASE) == 1
    assert LEGACY_DATABASE in world.tables and LEGACY_DATABASE not in world.deleted
    assert world.backup_path is not None and world.backup_path.is_file()
    assert "secret" not in "".join(traceback.format_exception(raised.value))


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ("asset_package_hash", "style_content_hash", "card_content_hash", "market_package_hash", "market_content_hash"))
async def test_correct_counts_but_wrong_observed_hash_rejects(tmp_path: Path, field: str) -> None:
    world = World(target="ready")
    world.official_rows[NEW_DATABASE][field] = "9" * 64
    with pytest.raises(ProductDatabaseReadinessError, match="^new database readiness audit failed$"):
        await world.run(tmp_path)
    assert world.tables[NEW_DATABASE] == _ready_counts()
    assert not {"initialize", "seed-assets", "seed-market", "cleanup:new"} & set(world.calls)
    assert "smoke" not in world.calls


@pytest.mark.asyncio
async def test_wrong_observed_source_authority_rejects_without_writes(tmp_path: Path) -> None:
    world = World(target="ready")
    world.official_rows[NEW_DATABASE]["market_source_authority"] = ("unapproved.source",)
    with pytest.raises(ProductDatabaseReadinessError, match="^new database readiness audit failed$"):
        await world.run(tmp_path)
    assert not {"initialize", "seed-assets", "seed-market", "cleanup:new", "smoke"} & set(world.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(("stage", "message"), (("legacy-before", "legacy database inventory failed"), ("backup", "product database backup failed"), ("restore", "product database restore drill failed"), ("legacy-after", "legacy database inventory failed"), ("probe", "new database inventory failed")))
async def test_each_prewrite_stage_failure_never_deletes_preexisting_target(tmp_path: Path, stage: str, message: str) -> None:
    world = World(target="ready"); world.fail_stage = stage
    with pytest.raises(ProductDatabaseReadinessError, match=f"^{message}$"):
        await world.run(tmp_path)
    assert NEW_DATABASE in world.tables and NEW_DATABASE not in world.deleted
    if stage != "legacy-before":
        assert world.backup_path is not None and world.backup_path.is_file()


@pytest.mark.asyncio
async def test_malformed_successful_initialization_is_owned_and_cleaned(tmp_path: Path) -> None:
    world = World()

    class EqualitySpoof:
        def __eq__(self, _other: object) -> bool:
            return True

    async def malformed(database: str) -> InitializationResult:
        world.calls.append("initialize")
        world.tables[database] = _empty_counts()
        world.created.append(database)
        return replace(INITIALIZED, manifest_hash=EqualitySpoof())

    world.initialize_new = malformed  # type: ignore[method-assign]
    with pytest.raises(ProductDatabaseReadinessError, match="^new database initialization failed$"):
        await world.run(tmp_path)
    assert NEW_DATABASE not in world.tables and world.deleted.count(NEW_DATABASE) == 1
    assert "seed-assets" not in world.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("cancelled", "keyboard", "system-exit"))
async def test_initialization_primary_flow_is_first_when_cleanup_fails(tmp_path: Path, kind: str) -> None:
    world = World(); world.cleanup_failure = RuntimeError("password=cleanup")

    async def interrupted(database: str) -> InitializationResult:
        world.calls.append("initialize")
        world.tables[database] = _empty_counts()
        world.created.append(database)
        if kind == "cancelled":
            raise asyncio.CancelledError("password=primary")
        if kind == "keyboard":
            raise KeyboardInterrupt("password=primary")
        raise SystemExit(31)

    world.initialize_new = interrupted  # type: ignore[method-assign]
    with pytest.raises(BaseExceptionGroup) as raised:
        await world.run(tmp_path)
    leaves = _flatten(raised.value)
    assert type(leaves[0]) is {"cancelled": asyncio.CancelledError, "keyboard": KeyboardInterrupt, "system-exit": SystemExit}[kind]
    assert str(leaves[1]) == "product database cleanup failed"


@pytest.mark.asyncio
async def test_backup_tamper_fails_restore_from_receipt_bytes_and_retains_file(tmp_path: Path) -> None:
    world = World(); world.tamper_backup = True
    with pytest.raises(ProductDatabaseReadinessError, match="^product database restore drill failed$"):
        await world.run(tmp_path)
    assert world.calls == ["inventory:legacy-before", "backup", "restore"]
    assert world.backup_path is not None and world.backup_path.is_file()
    assert "probe:new" not in world.calls and "smoke" not in world.calls


@pytest.mark.asyncio
async def test_valid_restore_ledger_with_inventory_mismatch_rejects(tmp_path: Path) -> None:
    world = World(); world.restore_inventory_mismatch = True
    with pytest.raises(ProductDatabaseReadinessError, match="^product database restore drill failed$"):
        await world.run(tmp_path)
    assert world.deleted == [RESTORE_DATABASE]
    assert world.backup_path is not None and world.backup_path.is_file()


@pytest.mark.asyncio
async def test_legacy_drift_after_valid_restore_stops_before_probe(tmp_path: Path) -> None:
    world = World(); world.legacy_drift = True
    with pytest.raises(ProductDatabaseReadinessError, match="^legacy database changed during preparation$"):
        await world.run(tmp_path)
    assert world.calls[-1] == "inventory:legacy-after" and "probe:new" not in world.calls
    assert world.deleted == [RESTORE_DATABASE]


@pytest.mark.asyncio
async def test_restore_create_then_failure_still_drops_restore_database(tmp_path: Path) -> None:
    world = World(); world.restore_primary = RuntimeError("password=restore-primary")
    with pytest.raises(ProductDatabaseReadinessError, match="^product database restore drill failed$"):
        await world.run(tmp_path)
    assert RESTORE_DATABASE in world.created and RESTORE_DATABASE in world.deleted
    assert world.backup_path is not None and world.backup_path.is_file()


@pytest.mark.asyncio
async def test_restore_primary_and_drop_failure_keep_primary_first(tmp_path: Path) -> None:
    world = World(); world.restore_primary = RuntimeError("password=restore-primary"); world.restore_cleanup_failure = RuntimeError("password=drop-failure")
    with pytest.raises(BaseExceptionGroup) as raised:
        await world.run(tmp_path)
    assert [str(leaf) for leaf in _flatten(raised.value)] == ["product database restore drill failed", "product database restore drill failed"]
    assert RESTORE_DATABASE in world.tables
    assert "secret" not in "".join(traceback.format_exception(raised.value))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("cancelled", "keyboard", "system-exit"))
async def test_restore_primary_flow_precedes_drop_failure(tmp_path: Path, kind: str) -> None:
    world = World(); world.restore_primary = {"cancelled": asyncio.CancelledError("secret"), "keyboard": KeyboardInterrupt("secret"), "system-exit": SystemExit(17)}[kind]; world.restore_cleanup_failure = RuntimeError("password=drop")
    with pytest.raises(BaseExceptionGroup) as raised:
        await world.run(tmp_path)
    leaves = _flatten(raised.value)
    expected = {"cancelled": asyncio.CancelledError, "keyboard": KeyboardInterrupt, "system-exit": SystemExit}[kind]
    assert type(leaves[0]) is expected and str(leaves[1]) == "product database restore drill failed"


@pytest.mark.asyncio
async def test_primary_failure_precedes_cleanup_failure(tmp_path: Path) -> None:
    world = World(); world.fail_stage = "smoke"; world.cleanup_failure = RuntimeError("password=cleanup")
    with pytest.raises(BaseExceptionGroup) as raised:
        await world.run(tmp_path)
    assert [str(leaf) for leaf in _flatten(raised.value)] == ["readiness smoke failed", "product database cleanup failed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("cancelled", "keyboard", "system-exit"))
async def test_cleanup_flow_is_retained_after_primary_failure(tmp_path: Path, kind: str) -> None:
    world = World(); world.smoke_result = SmokeResult(1, 0); world.cleanup_failure = {"cancelled": asyncio.CancelledError("secret"), "keyboard": KeyboardInterrupt("secret"), "system-exit": SystemExit(29)}[kind]
    with pytest.raises(BaseExceptionGroup) as raised:
        await world.run(tmp_path)
    leaves = _flatten(raised.value)
    assert str(leaves[0]) == "readiness smoke crossed network boundary"
    assert type(leaves[1]) is {"cancelled": asyncio.CancelledError, "keyboard": KeyboardInterrupt, "system-exit": SystemExit}[kind]


def test_restore_ledger_and_storage_fields_require_exact_builtin_strings() -> None:
    restored = replace(World().snapshot(LEGACY_DATABASE), database=RESTORE_DATABASE)
    class Text(str): pass
    for created, cleaned in (((Text(RESTORE_DATABASE),), (RESTORE_DATABASE,)), ((RESTORE_DATABASE, RESTORE_DATABASE), (RESTORE_DATABASE, RESTORE_DATABASE)), ((RESTORE_DATABASE,), ()), (("",), ("",)), ((True,), (True,))):
        with pytest.raises(ProductDatabaseReadinessError, match="^product database restore drill failed$"):
            RestoreDrillResult(restored, created, cleaned)  # type: ignore[arg-type]
    world = World(target="ready"); target = world.snapshot(NEW_DATABASE); audit = OfficialDataAudit(**_official_row())  # type: ignore[arg-type]
    original = world.storage(NEW_DATABASE)[0]
    for field in ("name", "engine", "collation"):
        valid = getattr(original, field)
        for invalid in (Text(valid), "", "   ", True):
            rows = list(world.storage(NEW_DATABASE)); rows[0] = replace(original, **{field: invalid})
            with pytest.raises(ProductDatabaseReadinessError, match="^new database readiness audit failed$"):
                assert_new_database_ready(target, INITIALIZED, audit, tuple(rows))


def test_official_audit_fields_require_exact_builtin_types() -> None:
    audit = OfficialDataAudit(**_official_row())  # type: ignore[arg-type]

    class Text(str):
        pass

    for field in ("asset_package_version", "asset_package_hash", "style_content_hash", "card_content_hash", "market_package_version", "market_package_hash", "market_content_hash"):
        with pytest.raises(ProductDatabaseReadinessError, match="^new database readiness audit failed$"):
            replace(audit, **{field: Text(getattr(audit, field))})
    for field in ("style_count", "card_count", "market_source_count"):
        with pytest.raises(ProductDatabaseReadinessError, match="^new database readiness audit failed$"):
            replace(audit, **{field: True})
    with pytest.raises(ProductDatabaseReadinessError, match="^new database readiness audit failed$"):
        replace(audit, market_source_authority=(Text(MARKET_AUTHORITY[0]),))


def test_public_callable_ownership_contract_is_removed() -> None:
    assert not hasattr(readiness_module, "NewDatabaseInitialization")
    assert not hasattr(readiness_module, "PreexistingNewDatabase")


def test_request_is_frozen_and_module_has_no_real_resource_imports(tmp_path: Path) -> None:
    request = PreparationRequest(LEGACY_DATABASE, NEW_DATABASE, tmp_path.resolve())
    with pytest.raises(FrozenInstanceError): request.new_database = LEGACY_DATABASE  # type: ignore[misc]
    source = (BACKEND_ROOT / "services" / "product_database_readiness.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None}
    imported.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
    forbidden = ("backend.config", "backend.database", "backend.gateways", "backend.scripts", "backend.security", "httpx", "subprocess")
    assert all(not any(module == prefix or module.startswith(f"{prefix}.") for prefix in forbidden) for module in imported)
