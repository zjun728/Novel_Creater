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
from backend.domain.product_database_readiness import BackupReceipt, DatabaseInventory, LEGACY_DATABASE, NEW_DATABASE, ProductDatabaseReadinessError, ReadinessState
from backend.schema_manifest import created_table_names, manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from backend.services.assets import AssetSeedReport
from backend.services.market_sources import MarketSourceSeedReport
from backend.services.product_database_inventory import TableStorage
import backend.services.product_database_readiness as readiness_module
from backend.services.product_database_readiness import NewDatabaseBoundaryState, OfficialDataAudit, PreparationRequest, RestoreDrillResult, SmokeResult, assert_new_database_ready, prepare_product_database


ZERO_HASH = "0" * 64
RESTORE_DATABASE = "novel_creator_phase7b_restore_0123456789abcdef0123456789abcdef"
PROOF_DATABASE = "novel_creator_phase7b_restore_fedcba9876543210fedcba9876543210"
LEGACY_SCHEMA_VERSION = "writer-core-v1.1.0"
LEGACY_MANIFEST_HASH = "3" * 64
LEGACY_STRUCTURE_HASH = "1" * 64
CURRENT_STRUCTURE_HASH = "2" * 64
BACKEND_ROOT = Path(__file__).resolve().parents[2]
ASSET_MANIFEST_PATH = BACKEND_ROOT / "assets" / ASSET_VERSION / "manifest.json"
MARKET_MANIFEST_PATH = BACKEND_ROOT / "assets" / MARKET_VERSION / "manifest.json"
ASSET_PACKAGE = load_asset_package(ASSET_MANIFEST_PATH, mode="release")
MARKET_PACKAGE = load_market_source_package(MARKET_MANIFEST_PATH)
SCHEMA_HASH = manifest_hash()


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


ASSET_MANIFEST = json.loads(ASSET_MANIFEST_PATH.read_text(encoding="utf-8"))
MARKET_MANIFEST = json.loads(MARKET_MANIFEST_PATH.read_text(encoding="utf-8"))
STYLE_ROWS = json.loads((ASSET_MANIFEST_PATH.parent / ASSET_MANIFEST["styles_file"]["path"]).read_text(encoding="utf-8"))
CARD_ROWS = json.loads((ASSET_MANIFEST_PATH.parent / ASSET_MANIFEST["experience_cards_file"]["path"]).read_text(encoding="utf-8"))
MARKET_ROWS = json.loads((MARKET_MANIFEST_PATH.parent / MARKET_MANIFEST["sources_file"]["path"]).read_text(encoding="utf-8"))
ASSET_HASH, MARKET_HASH = _hash(ASSET_MANIFEST), _hash(MARKET_MANIFEST)
STYLE_HASH, CARD_HASH = ASSET_MANIFEST["styles_file"]["sha256"], ASSET_MANIFEST["experience_cards_file"]["sha256"]
MARKET_CONTENT_HASH = MARKET_MANIFEST["sources_file"]["sha256"]
STYLE_COUNT, CARD_COUNT, MARKET_COUNT = len(STYLE_ROWS), len(CARD_ROWS), len(MARKET_ROWS)
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
    counts.update({"style_templates": 10, "style_template_heads": 10, "experience_cards": 64, "experience_card_heads": 64, "market_sources": 2, "market_source_policy_revisions": 2, "market_source_policy_heads": 2, "market_source_refresh_states": 2})
    return counts


def _proof_inventory() -> DatabaseInventory:
    counts = tuple(sorted(_empty_counts().items()))
    return DatabaseInventory(PROOF_DATABASE, "8.4.3", EXPECTED_SCHEMA_VERSION, SCHEMA_HASH, CURRENT_STRUCTURE_HASH, tuple(name for name, _ in counts), counts, 1, 1)


def _schema_proof() -> object:
    inventory = _proof_inventory()
    storage = tuple(TableStorage(name, "InnoDB", "utf8mb4_0900_ai_ci") for name in inventory.table_names)
    return readiness_module.CurrentSchemaProof(inventory, storage, (PROOF_DATABASE,), (PROOF_DATABASE,))


def _official_row() -> dict[str, object]:
    return {"asset_package_version": ASSET_MANIFEST["package_version"], "asset_package_hash": ASSET_HASH, "style_content_hash": STYLE_HASH, "style_count": STYLE_COUNT, "card_content_hash": CARD_HASH, "card_count": CARD_COUNT, "market_package_version": MARKET_MANIFEST["package_version"], "market_package_hash": MARKET_HASH, "market_content_hash": MARKET_CONTENT_HASH, "market_source_count": MARKET_COUNT, "market_source_authority": MARKET_AUTHORITY}


def _audit_payload() -> dict[str, object]:
    row = _official_row()
    return {"assetPackageVersion": row["asset_package_version"], "assetPackageHash": row["asset_package_hash"], "styleContentHash": row["style_content_hash"], "styleCount": row["style_count"], "cardContentHash": row["card_content_hash"], "cardCount": row["card_count"], "marketPackageVersion": row["market_package_version"], "marketPackageHash": row["market_package_hash"], "marketContentHash": row["market_content_hash"], "marketSourceCount": row["market_source_count"], "marketSourceAuthority": row["market_source_authority"]}


def _seed_payload() -> dict[str, object]:
    return {"assets": {"packageVersion": ASSET_MANIFEST["package_version"], "packageHash": ASSET_HASH, "styleCount": STYLE_COUNT, "cardCount": CARD_COUNT, "inserted": STYLE_COUNT + CARD_COUNT, "replayed": 0, "advanced": 0}, "market": {"packageVersion": MARKET_MANIFEST["package_version"], "packageHash": MARKET_HASH, "sourceCount": MARKET_COUNT, "inserted": MARKET_COUNT, "replayed": 0}}


def _inventory_from_json(payload: dict[str, object]) -> DatabaseInventory:
    payload = dict(payload); payload["table_names"] = tuple(payload["table_names"]); payload["row_counts"] = tuple(tuple(row) for row in payload["row_counts"])  # type: ignore[arg-type]
    return DatabaseInventory(**payload)  # type: ignore[arg-type]


class AtomicBoundary:
    """Trusted fake boundary: lock and deletion authority never leave this object."""

    def __init__(self, world: World, database: str) -> None:
        self.world, self.database, self.owned = world, database, False

    async def __aenter__(self) -> NewDatabaseBoundaryState:
        await self.world.target_lock.acquire()
        self.world.calls.append("boundary-enter")
        if self.database in self.world.tables:
            self.world.calls.append("boundary-resume")
            if self.world.misreport_created:
                class EqualitySpoof:
                    def __eq__(self, _other: object) -> bool: return True
                return NewDatabaseBoundaryState("created", replace(INITIALIZED, manifest_hash=EqualitySpoof()), None)
            return NewDatabaseBoundaryState("preexisting", None, self.world.snapshot(self.database))
        self.world.tables[self.database] = _empty_counts()
        self.world.created.append(self.database)
        self.owned = True
        self.world.calls.append("initialize")
        if self.world.enter_failure is not None:
            primary = self.world.enter_failure
            try:
                await self._cleanup()
            except BaseException as cleanup:
                self.world.target_lock.release()
                raise readiness_module.NewDatabaseBoundaryEnterFailure(primary, cleanup)
            self.world.target_lock.release()
            raise primary
        return NewDatabaseBoundaryState("created", INITIALIZED, None)

    async def __aexit__(self, exc_type: object, exc: BaseException | None, _tb: object) -> bool:
        outgoing: BaseException | None = None
        try:
            if exc is None:
                self.world.calls.append("boundary-commit")
                if self.world.commit_failure is not None:
                    try:
                        raise self.world.commit_failure
                    except BaseException as commit:
                        if self.owned:
                            try:
                                await self._cleanup()
                            except BaseException as cleanup:
                                outgoing = BaseExceptionGroup("commit failed", [commit, cleanup])
                            else:
                                outgoing = commit
            elif self.owned:
                try:
                    await self._cleanup()
                except BaseException as cleanup:
                    outgoing = cleanup
            if outgoing is None and self.world.exit_failure is not None:
                outgoing = self.world.exit_failure
        finally:
            self.world.target_lock.release()
            if self.world.release_failure is not None:
                release = self.world.release_failure
                if outgoing is not None:
                    outgoing = BaseExceptionGroup("release failed", [outgoing, release])
                elif exc is not None:
                    outgoing = BaseExceptionGroup("release failed", [exc, release])
                else:
                    outgoing = release
        if outgoing is not None:
            raise readiness_module.NewDatabaseBoundaryExitFailure(outgoing)
        if self.world.malicious_exit_failure is not None:
            raise self.world.malicious_exit_failure
        return self.world.suppress_body

    async def _cleanup(self) -> None:
        self.world.calls.append("boundary-cleanup")
        if self.world.boundary_cleanup_failure is not None:
            raise self.world.boundary_cleanup_failure
        if self.database in self.world.tables:
            del self.world.tables[self.database]
            self.world.official_rows.pop(self.database, None)
            self.world.deleted.append(self.database)
        self.owned = False


class World:
    def __init__(self, *, target: str = "absent") -> None:
        self.tables: dict[str, dict[str, int]] = {LEGACY_DATABASE: {f"legacy_table_{index:02d}": index % 3 for index in range(49)}}
        self.official_rows: dict[str, dict[str, object]] = {}
        if target == "ready": self.tables[NEW_DATABASE], self.official_rows[NEW_DATABASE] = _ready_counts(), _official_row()
        elif target == "empty": self.tables[NEW_DATABASE] = _empty_counts()
        elif target == "partial": self.tables[NEW_DATABASE] = _empty_counts() | {"projects": 1}
        self.calls: list[str] = []; self.created: list[str] = []; self.deleted: list[str] = []
        self.target_lock = asyncio.Lock(); self.backup_directory: Path | None = None; self.backup_path: Path | None = None
        self.fail_stage: str | None = None; self.legacy_drift = False; self.tamper_backup = False; self.restore_mismatch = False
        self.restore_primary: BaseException | None = None; self.restore_cleanup_failure: BaseException | None = None
        self.enter_failure: BaseException | None = None; self.boundary_cleanup_failure: BaseException | None = None; self.misreport_created = False
        self.commit_failure: BaseException | None = None; self.exit_failure: BaseException | None = None; self.release_failure: BaseException | None = None
        self.malicious_exit_failure: BaseException | None = None
        self.smoke_failure: BaseException | None = None
        self.suppress_body = False
        self.target_structural_fingerprint = CURRENT_STRUCTURE_HASH
        self.proof_override: object | None = None
        self.proof_failure: BaseException | None = None
        self.proof_cleanup_failure: BaseException | None = None
        self.smoke_result: object = SmokeResult(0, 0)

    def snapshot(self, database: str) -> DatabaseInventory:
        rows = tuple(sorted(self.tables[database].items())); legacy = database == LEGACY_DATABASE
        schema_version = LEGACY_SCHEMA_VERSION if legacy else EXPECTED_SCHEMA_VERSION
        schema_hash = LEGACY_MANIFEST_HASH if legacy else SCHEMA_HASH
        structure_hash = LEGACY_STRUCTURE_HASH if legacy else self.target_structural_fingerprint if database == NEW_DATABASE else CURRENT_STRUCTURE_HASH
        return DatabaseInventory(database, "8.4.3", schema_version, schema_hash, structure_hash, tuple(name for name, _ in rows), rows, sum(count > 0 for _, count in rows), sum(count for _, count in rows))

    def storage(self, database: str) -> tuple[TableStorage, ...]:
        return tuple(TableStorage(name, "InnoDB", "utf8mb4_0900_ai_ci") for name in sorted(self.tables[database]))

    def _fail(self, stage: str) -> None:
        if self.fail_stage == stage: raise RuntimeError(f"password=secret-{stage} dsn=mysql://private")

    async def inventory(self, role: str) -> DatabaseInventory:
        self.calls.append(f"inventory:{role}"); self._fail(role); value = self.snapshot(LEGACY_DATABASE if role.startswith("legacy") else NEW_DATABASE)
        return replace(value, structural_fingerprint="8" * 64) if role == "legacy-after" and self.legacy_drift else value

    async def create_backup(self, authority: DatabaseInventory, directory: Path) -> BackupReceipt:
        self.calls.append("backup"); directory.mkdir(parents=True, exist_ok=True); self.backup_directory = directory; self.backup_path = directory / "phase7b.json"
        raw = json.dumps(asdict(authority), allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(); self.backup_path.write_bytes(raw)
        first = {"state": ReadinessState.INVENTORY_VERIFIED.value, "previous_receipt_hash": ZERO_HASH, "legacy_database": LEGACY_DATABASE, "new_database": NEW_DATABASE, "evidence_hash": _hash(asdict(authority))}
        receipt = BackupReceipt(ReadinessState.BACKUP_CREATED.value, _hash(first), LEGACY_DATABASE, self.backup_path.name, hashlib.sha256(raw).hexdigest(), len(raw), "8.4.3", _hash(asdict(authority)))
        if self.tamper_backup: self.backup_path.write_bytes(raw + b"tampered")
        self._fail("backup"); return receipt

    async def restore_drill(self, receipt: BackupReceipt, authority: DatabaseInventory) -> RestoreDrillResult:
        self.calls.append("restore"); self._fail("restore"); assert self.backup_directory is not None
        raw = (self.backup_directory / receipt.backup_filename).read_bytes()
        if len(raw) != receipt.backup_byte_length or hashlib.sha256(raw).hexdigest() != receipt.backup_sha256: raise RuntimeError("password=backup-tamper")
        restored_authority = _inventory_from_json(json.loads(raw.decode()))
        if restored_authority != authority or _hash(asdict(restored_authority)) != receipt.source_inventory_hash: raise RuntimeError("password=backup-authority")
        self.tables[RESTORE_DATABASE] = dict(restored_authority.row_counts); self.created.append(RESTORE_DATABASE); restored = replace(restored_authority, database=RESTORE_DATABASE)
        if self.restore_mismatch: restored = replace(restored, structural_fingerprint="7" * 64)
        if self.restore_primary is not None:
            primary = self.restore_primary
            try: await self._drop_restore()
            except BaseException as cleanup: raise BaseExceptionGroup("restore boundary failed", [primary, cleanup])
            raise primary
        await self._drop_restore(); return RestoreDrillResult(restored, (RESTORE_DATABASE,), (RESTORE_DATABASE,))

    async def _drop_restore(self) -> None:
        self.calls.append("restore-cleanup")
        if self.restore_cleanup_failure is not None: raise self.restore_cleanup_failure
        del self.tables[RESTORE_DATABASE]; self.deleted.append(RESTORE_DATABASE)

    def new_database_boundary(self, database: str) -> AtomicBoundary:
        self.calls.append("boundary-factory"); return AtomicBoundary(self, database)

    async def current_schema_proof(self) -> object:
        self.calls.append("schema-proof")
        self.tables[PROOF_DATABASE] = _empty_counts(); self.created.append(PROOF_DATABASE)
        primary: BaseException | None = None; proof: DatabaseInventory | None = None; proof_storage: tuple[TableStorage, ...] | None = None
        try:
            if self.proof_failure is not None: raise self.proof_failure
            proof = self.snapshot(PROOF_DATABASE)
            proof_storage = self.storage(PROOF_DATABASE)
        except BaseException as error:
            primary = error
        self.calls.append("schema-proof-cleanup"); del self.tables[PROOF_DATABASE]; self.deleted.append(PROOF_DATABASE)
        if self.proof_cleanup_failure is not None:
            if primary is not None: raise BaseExceptionGroup("schema proof failed", [primary, self.proof_cleanup_failure])
            raise self.proof_cleanup_failure
        if primary is not None: raise primary
        if self.proof_override is not None: return self.proof_override
        return readiness_module.CurrentSchemaProof(proof, proof_storage, (PROOF_DATABASE,), (PROOF_DATABASE,))

    async def seed_assets(self, database: str) -> AssetSeedReport:
        self.calls.append("seed-assets"); self._fail("seed-assets"); self.tables[database].update({"style_templates": 10, "style_template_heads": 10, "experience_cards": 64, "experience_card_heads": 64})
        self.official_rows.setdefault(database, {}).update({key: value for key, value in _official_row().items() if key.startswith(("asset_", "style_", "card_"))})
        return AssetSeedReport(ASSET_MANIFEST["package_version"], ASSET_HASH, STYLE_COUNT, CARD_COUNT, STYLE_COUNT + CARD_COUNT, 0, 0)

    async def seed_market(self, database: str) -> MarketSourceSeedReport:
        self.calls.append("seed-market"); self._fail("seed-market"); self.tables[database].update({"market_sources": 2, "market_source_policy_revisions": 2, "market_source_policy_heads": 2, "market_source_refresh_states": 2})
        self.official_rows.setdefault(database, {}).update({key: value for key, value in _official_row().items() if key.startswith("market_")})
        return MarketSourceSeedReport(MARKET_MANIFEST["package_version"], MARKET_COUNT, MARKET_HASH, MARKET_COUNT, 0)

    async def read_storage(self, database: str) -> tuple[TableStorage, ...]: self.calls.append("storage"); self._fail("storage"); return self.storage(database)
    async def audit_official_data(self, database: str) -> OfficialDataAudit: self.calls.append("official-audit"); self._fail("official-audit"); return OfficialDataAudit(**self.official_rows[database])  # type: ignore[arg-type]
    async def smoke(self, _database: str) -> object:
        self.calls.append("smoke"); self._fail("smoke")
        if self.smoke_failure is not None: raise self.smoke_failure
        return self.smoke_result

    async def run(self, tmp_path: Path):
        return await prepare_product_database(request=PreparationRequest(LEGACY_DATABASE, NEW_DATABASE, tmp_path.resolve()), inventory=self.inventory, create_backup=self.create_backup, restore_drill=self.restore_drill, current_schema_proof=self.current_schema_proof, new_database_boundary=self.new_database_boundary, seed_assets=self.seed_assets, seed_market=self.seed_market, read_storage=self.read_storage, audit_official_data=self.audit_official_data, smoke=self.smoke)


def _flatten(error: BaseException) -> list[BaseException]:
    return [leaf for child in error.exceptions for leaf in _flatten(child)] if isinstance(error, BaseExceptionGroup) else [error]


def _tainted(error: BaseException) -> BaseException:
    error.__cause__ = RuntimeError("password=secret-cause")
    error.__context__ = RuntimeError("password=secret-context")
    error.add_note("password=secret-note")
    return error


def _assert_safe(error: BaseException) -> None:
    assert "secret" not in "".join(traceback.format_exception(error))
    pending = [error]
    while pending:
        current = pending.pop()
        assert current.__cause__ is None and current.__context__ is None
        assert not getattr(current, "__notes__", ())
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions)


def _assert_receipts(result: object, world: World, mode: str) -> None:
    receipts = result.receipts; before, target = world.snapshot(LEGACY_DATABASE), world.snapshot(NEW_DATABASE)  # type: ignore[attr-defined]
    assert world.backup_path is not None; raw = world.backup_path.read_bytes()
    first = {"state": ReadinessState.INVENTORY_VERIFIED.value, "previous_receipt_hash": ZERO_HASH, "legacy_database": LEGACY_DATABASE, "new_database": NEW_DATABASE, "evidence_hash": _hash(asdict(before))}
    backup = BackupReceipt(ReadinessState.BACKUP_CREATED.value, _hash(first), LEGACY_DATABASE, world.backup_path.name, hashlib.sha256(raw).hexdigest(), len(raw), "8.4.3", _hash(asdict(before)))
    official = {"mode": mode, "observed": _audit_payload()}
    if mode == "created": official["seedReports"] = _seed_payload()
    proof_inventory = _proof_inventory()
    proof = {"proofDatabase": PROOF_DATABASE, "proofInventoryHash": _hash(asdict(proof_inventory)), "createdDatabases": (PROOF_DATABASE,), "cleanedDatabases": (PROOF_DATABASE,)}
    initialized = {"databaseName": NEW_DATABASE, "schemaVersion": EXPECTED_SCHEMA_VERSION, "manifestHash": SCHEMA_HASH, "tableCount": len(created_table_names())}
    evidence = (_hash(asdict(before)), _hash(asdict(backup)), _hash({"restoreInventoryHash": _hash(asdict(replace(before, database=RESTORE_DATABASE))), "createdDatabases": (RESTORE_DATABASE,), "cleanedDatabases": (RESTORE_DATABASE,)}), _hash({"initialization": initialized, "currentSchemaProof": proof}), _hash(official), _hash(asdict(target)), _hash({"providerCalls": 0, "outboundRequests": 0}))
    previous = ZERO_HASH
    for receipt, state, digest in zip(receipts, tuple(state.value for state in tuple(ReadinessState)[:7]), evidence, strict=True):
        expected = {"state": state, "previous_receipt_hash": previous, "legacy_database": LEGACY_DATABASE, "new_database": NEW_DATABASE, "evidence_hash": digest}; assert asdict(receipt) == expected; previous = _hash(expected)
    assert result.previous_receipt_hash == previous  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_created_boundary_seeds_audits_commits_and_receipts_created_mode(tmp_path: Path) -> None:
    world = World(); result = await world.run(tmp_path)
    assert world.calls[-2:] == ["smoke", "boundary-commit"]
    assert world.tables[NEW_DATABASE] == _ready_counts() and world.deleted == [RESTORE_DATABASE, PROOF_DATABASE]
    assert world.calls.index("schema-proof-cleanup") < world.calls.index("boundary-factory")
    _assert_receipts(result, world, "created")


@pytest.mark.asyncio
async def test_preexisting_ready_boundary_is_zero_write_resume(tmp_path: Path) -> None:
    world = World(target="ready"); original = dict(world.tables[NEW_DATABASE]); result = await world.run(tmp_path)
    legacy = world.snapshot(LEGACY_DATABASE)
    assert len(legacy.table_names) == 49 and legacy.schema_version == LEGACY_SCHEMA_VERSION
    assert legacy.structural_fingerprint != CURRENT_STRUCTURE_HASH
    assert world.tables[NEW_DATABASE] == original
    assert not {"initialize", "seed-assets", "seed-market", "boundary-cleanup"} & set(world.calls)
    assert PROOF_DATABASE not in world.tables and PROOF_DATABASE in world.deleted
    _assert_receipts(result, world, "resume")


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ("absent", "ready"))
async def test_target_structural_drift_rejects_with_unchanged_counts_and_storage(tmp_path: Path, target: str) -> None:
    world = World(target=target); world.target_structural_fingerprint = "9" * 64
    with pytest.raises(ProductDatabaseReadinessError, match="^new database readiness audit failed$"): await world.run(tmp_path)
    assert "smoke" not in world.calls
    if target == "absent":
        assert NEW_DATABASE not in world.tables and world.deleted.count(NEW_DATABASE) == 1
    else:
        assert NEW_DATABASE in world.tables and "boundary-cleanup" not in world.calls


@pytest.mark.asyncio
async def test_schema_proof_old_authority_shape_is_fixed_before_target_boundary(tmp_path: Path) -> None:
    class EqualitySpoof:
        def __eq__(self, _other: object) -> bool: return True
        schema_version = EXPECTED_SCHEMA_VERSION; manifest_hash = SCHEMA_HASH; table_names = tuple(sorted(created_table_names())); table_count = len(table_names); structural_fingerprint = CURRENT_STRUCTURE_HASH
    world = World(target="ready"); original = dict(world.tables[NEW_DATABASE]); world.proof_override = EqualitySpoof()
    with pytest.raises(ProductDatabaseReadinessError, match="^current schema proof failed$") as raised: await world.run(tmp_path)
    assert world.tables[NEW_DATABASE] == original and PROOF_DATABASE not in world.tables
    assert "boundary-factory" not in world.calls
    _assert_safe(raised.value)


@pytest.mark.asyncio
async def test_fabricated_schema_proof_missing_ledger_is_fixed(tmp_path: Path) -> None:
    world = World(); valid = _schema_proof()
    fabricated = object.__new__(readiness_module.CurrentSchemaProof)
    object.__setattr__(fabricated, "inventory", valid.inventory)  # type: ignore[attr-defined]
    object.__setattr__(fabricated, "storage", valid.storage)  # type: ignore[attr-defined]
    world.proof_override = fabricated
    with pytest.raises(ProductDatabaseReadinessError, match="^current schema proof failed$") as raised: await world.run(tmp_path)
    assert PROOF_DATABASE not in world.tables and "boundary-factory" not in world.calls
    _assert_safe(raised.value)


@pytest.mark.asyncio
async def test_schema_proof_cleanup_error_is_fixed_safe_and_never_returns_proof_or_writes_target(tmp_path: Path) -> None:
    world = World(target="ready"); original = dict(world.tables[NEW_DATABASE]); world.proof_cleanup_failure = _tainted(RuntimeError("password=secret-proof-cleanup"))
    with pytest.raises(ProductDatabaseReadinessError, match="^current schema proof failed$") as raised: await world.run(tmp_path)
    assert world.tables[NEW_DATABASE] == original and PROOF_DATABASE not in world.tables
    assert "schema-proof-cleanup" in world.calls and "boundary-factory" not in world.calls
    assert world.backup_path is not None and world.backup_path.is_file()
    _assert_safe(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ("empty", "partial"))
async def test_preexisting_partial_rejects_without_boundary_cleanup(tmp_path: Path, target: str) -> None:
    world = World(target=target); original = dict(world.tables[NEW_DATABASE])
    with pytest.raises(ProductDatabaseReadinessError, match="^new database readiness audit failed$"): await world.run(tmp_path)
    assert world.tables[NEW_DATABASE] == original and "boundary-cleanup" not in world.calls
    assert not {"seed-assets", "seed-market", "official-audit"} & set(world.calls)


@pytest.mark.asyncio
async def test_create_then_enter_failure_is_cleaned_inside_boundary(tmp_path: Path) -> None:
    world = World(); world.enter_failure = ProductDatabaseReadinessError("new database initialization failed")
    with pytest.raises(ProductDatabaseReadinessError, match="^new database initialization failed$"): await world.run(tmp_path)
    assert world.calls[-3:] == ["boundary-enter", "initialize", "boundary-cleanup"]
    assert NEW_DATABASE not in world.tables and NEW_DATABASE in world.deleted


@pytest.mark.asyncio
async def test_enter_primary_and_cleanup_failure_preserve_order(tmp_path: Path) -> None:
    world = World(); world.enter_failure = ProductDatabaseReadinessError("new database initialization failed"); world.boundary_cleanup_failure = ProductDatabaseReadinessError("product database cleanup failed")
    with pytest.raises(BaseExceptionGroup) as raised: await world.run(tmp_path)
    assert [str(leaf) for leaf in _flatten(raised.value)] == ["new database initialization failed", "product database cleanup failed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("cancelled", "keyboard", "system-exit"))
async def test_enter_flow_primary_and_cleanup_are_safely_cloned(tmp_path: Path, kind: str) -> None:
    world = World()
    world.enter_failure = _tainted({"cancelled": asyncio.CancelledError("secret"), "keyboard": KeyboardInterrupt("secret"), "system-exit": SystemExit("secret-code")}[kind])
    world.boundary_cleanup_failure = _tainted(RuntimeError("password=secret-cleanup"))
    with pytest.raises(BaseExceptionGroup) as raised: await world.run(tmp_path)
    leaves = _flatten(raised.value); expected = {"cancelled": asyncio.CancelledError, "keyboard": KeyboardInterrupt, "system-exit": SystemExit}[kind]
    assert type(leaves[0]) is expected and str(leaves[1]) == "product database cleanup failed"
    assert leaves[0].code is None if kind == "system-exit" else leaves[0].args == ()
    _assert_safe(raised.value)


@pytest.mark.asyncio
async def test_enter_ordinary_error_is_fixed_and_safe(tmp_path: Path) -> None:
    world = World(); world.enter_failure = _tainted(RuntimeError("password=secret-enter"))
    with pytest.raises(ProductDatabaseReadinessError, match="^new database initialization failed$") as raised: await world.run(tmp_path)
    _assert_safe(raised.value)


@pytest.mark.asyncio
async def test_generic_enter_group_does_not_infer_cleanup_from_leaf_order(tmp_path: Path) -> None:
    world = World(); world.enter_failure = BaseExceptionGroup(
        "malicious order",
        [RuntimeError("password=secret-first"), RuntimeError("password=secret-second")],
    )
    with pytest.raises(BaseExceptionGroup) as raised: await world.run(tmp_path)
    assert [str(leaf) for leaf in _flatten(raised.value)] == ["new database initialization failed", "new database initialization failed"]
    _assert_safe(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(("stage", "message"), (("seed-assets", "official asset seed failed"), ("seed-market", "official market source seed failed"), ("new", "new database inventory failed"), ("storage", "new database readiness audit failed"), ("official-audit", "new database readiness audit failed"), ("smoke", "readiness smoke failed")))
async def test_created_body_failure_is_cleaned_only_by_boundary(tmp_path: Path, stage: str, message: str) -> None:
    world = World(); world.fail_stage = stage
    with pytest.raises(ProductDatabaseReadinessError, match=f"^{message}$"): await world.run(tmp_path)
    assert NEW_DATABASE not in world.tables and world.deleted.count(NEW_DATABASE) == 1
    assert world.backup_path is not None and world.backup_path.is_file()


@pytest.mark.asyncio
async def test_body_primary_precedes_boundary_cleanup_failure(tmp_path: Path) -> None:
    world = World(); world.fail_stage = "smoke"; world.boundary_cleanup_failure = ProductDatabaseReadinessError("product database cleanup failed")
    with pytest.raises(BaseExceptionGroup) as raised: await world.run(tmp_path)
    assert [str(leaf) for leaf in _flatten(raised.value)] == ["readiness smoke failed", "product database cleanup failed"]


@pytest.mark.asyncio
async def test_exit_envelope_nested_cleanup_keeps_body_once_and_cleanup_order(tmp_path: Path) -> None:
    world = World(); world.fail_stage = "smoke"
    world.boundary_cleanup_failure = BaseExceptionGroup(
        "nested cleanup",
        [RuntimeError("secret-one"), BaseExceptionGroup("nested", [SystemExit(37), RuntimeError("secret-two")])],
    )
    with pytest.raises(BaseExceptionGroup) as raised: await world.run(tmp_path)
    leaves = _flatten(raised.value)
    assert [str(leaf) for leaf in leaves] == ["readiness smoke failed", "product database cleanup failed", "37", "product database cleanup failed"]
    assert sum(str(leaf) == "readiness smoke failed" for leaf in leaves) == 1
    _assert_safe(raised.value)


@pytest.mark.asyncio
async def test_generic_malicious_exit_group_cannot_reclassify_cloned_body(tmp_path: Path) -> None:
    world = World(); world.fail_stage = "smoke"
    world.malicious_exit_failure = BaseExceptionGroup(
        "malicious",
        [ProductDatabaseReadinessError("readiness smoke failed"), RuntimeError("password=secret")],
    )
    with pytest.raises(BaseExceptionGroup) as raised: await world.run(tmp_path)
    leaves = _flatten(raised.value)
    assert [str(leaf) for leaf in leaves] == ["readiness smoke failed", "product database cleanup failed", "product database cleanup failed"]
    assert sum(str(leaf) == "readiness smoke failed" for leaf in leaves) == 1
    _assert_safe(raised.value)


@pytest.mark.asyncio
async def test_boundary_cannot_suppress_body_primary_after_cleanup(tmp_path: Path) -> None:
    world = World(); world.fail_stage = "smoke"; world.suppress_body = True
    with pytest.raises(ProductDatabaseReadinessError, match="^readiness smoke failed$") as raised: await world.run(tmp_path)
    assert NEW_DATABASE not in world.tables and world.deleted.count(NEW_DATABASE) == 1
    _assert_safe(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("cancelled", "keyboard", "system-exit"))
async def test_boundary_cleanup_flow_is_second_after_body_primary(tmp_path: Path, kind: str) -> None:
    world = World(); world.smoke_result = SmokeResult(1, 0); world.boundary_cleanup_failure = {"cancelled": asyncio.CancelledError(), "keyboard": KeyboardInterrupt(), "system-exit": SystemExit(29)}[kind]
    with pytest.raises(BaseExceptionGroup) as raised: await world.run(tmp_path)
    leaves = _flatten(raised.value); assert str(leaves[0]) == "readiness smoke crossed network boundary"
    assert type(leaves[1]) is {"cancelled": asyncio.CancelledError, "keyboard": KeyboardInterrupt, "system-exit": SystemExit}[kind]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("cancelled", "keyboard", "system-exit"))
async def test_body_flow_primary_precedes_safe_cleanup_error(tmp_path: Path, kind: str) -> None:
    world = World(); world.smoke_failure = _tainted({"cancelled": asyncio.CancelledError("secret"), "keyboard": KeyboardInterrupt("secret"), "system-exit": SystemExit(41)}[kind]); world.boundary_cleanup_failure = _tainted(RuntimeError("password=secret-cleanup"))
    with pytest.raises(BaseExceptionGroup) as raised: await world.run(tmp_path)
    leaves = _flatten(raised.value); expected = {"cancelled": asyncio.CancelledError, "keyboard": KeyboardInterrupt, "system-exit": SystemExit}[kind]
    assert type(leaves[0]) is expected and str(leaves[1]) == "product database cleanup failed"
    assert leaves[0].code == 41 if kind == "system-exit" else leaves[0].args == ()
    _assert_safe(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ("commit", "exit", "release"))
async def test_success_lifecycle_ordinary_error_is_fixed_and_safe(tmp_path: Path, stage: str) -> None:
    world = World(); setattr(world, f"{stage}_failure", _tainted(RuntimeError(f"password=secret-{stage}")))
    with pytest.raises(ProductDatabaseReadinessError, match="^product database cleanup failed$") as raised: await world.run(tmp_path)
    _assert_safe(raised.value)
    if stage == "commit": assert NEW_DATABASE not in world.tables


@pytest.mark.asyncio
async def test_commit_and_release_failures_are_both_safe_cleanup_leaves(tmp_path: Path) -> None:
    world = World(); world.commit_failure = _tainted(RuntimeError("password=secret-commit")); world.release_failure = _tainted(RuntimeError("password=secret-release"))
    with pytest.raises(BaseExceptionGroup) as raised: await world.run(tmp_path)
    assert [str(leaf) for leaf in _flatten(raised.value)] == ["product database cleanup failed", "product database cleanup failed"]
    _assert_safe(raised.value)


@pytest.mark.asyncio
async def test_misreported_mode_cannot_make_service_delete_preexisting(tmp_path: Path) -> None:
    world = World(target="ready"); world.misreport_created = True
    with pytest.raises(ProductDatabaseReadinessError, match="^new database initialization failed$"): await world.run(tmp_path)
    assert NEW_DATABASE in world.tables and NEW_DATABASE not in world.deleted
    assert "boundary-cleanup" not in world.calls and "seed-assets" not in world.calls


@pytest.mark.asyncio
async def test_atomic_boundary_serializes_concurrent_acquisition() -> None:
    world = World(); first_entered = asyncio.Event(); release_first = asyncio.Event(); modes: list[str] = []
    async def first() -> None:
        async with world.new_database_boundary(NEW_DATABASE) as state:
            modes.append(state.mode); first_entered.set(); await release_first.wait(); world.tables[NEW_DATABASE] = _ready_counts(); world.official_rows[NEW_DATABASE] = _official_row()
    async def second() -> None:
        await first_entered.wait()
        async with world.new_database_boundary(NEW_DATABASE) as state: modes.append(state.mode)
    tasks = [asyncio.create_task(first()), asyncio.create_task(second())]; await asyncio.sleep(0); release_first.set(); await asyncio.gather(*tasks)
    assert modes == ["created", "preexisting"] and world.deleted == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ("asset_package_hash", "style_content_hash", "card_content_hash", "market_package_hash", "market_content_hash"))
async def test_observed_hash_drift_rejects_and_resume_never_writes(tmp_path: Path, field: str) -> None:
    world = World(target="ready"); world.official_rows[NEW_DATABASE][field] = "9" * 64
    with pytest.raises(ProductDatabaseReadinessError, match="^new database readiness audit failed$"): await world.run(tmp_path)
    assert not {"initialize", "seed-assets", "seed-market", "boundary-cleanup", "smoke"} & set(world.calls)


@pytest.mark.asyncio
async def test_observed_source_authority_drift_rejects_resume_without_writes(tmp_path: Path) -> None:
    world = World(target="ready"); world.official_rows[NEW_DATABASE]["market_source_authority"] = ("unapproved.source",)
    with pytest.raises(ProductDatabaseReadinessError, match="^new database readiness audit failed$"): await world.run(tmp_path)
    assert not {"initialize", "seed-assets", "seed-market", "boundary-cleanup", "smoke"} & set(world.calls)


@pytest.mark.asyncio
async def test_created_receipt_rejects_seed_report_with_resume_mode(tmp_path: Path) -> None:
    world = World(); original = world.seed_assets

    async def wrong_mode(database: str) -> AssetSeedReport:
        report = await original(database)
        return replace(report, inserted=0, replayed=STYLE_COUNT + CARD_COUNT)

    world.seed_assets = wrong_mode  # type: ignore[method-assign]
    with pytest.raises(ProductDatabaseReadinessError, match="^new database readiness audit failed$"): await world.run(tmp_path)
    assert NEW_DATABASE not in world.tables and world.deleted.count(NEW_DATABASE) == 1
    assert "official-audit" not in world.calls


@pytest.mark.asyncio
async def test_backup_tamper_fails_restore_and_retains_receipt_file(tmp_path: Path) -> None:
    world = World(); world.tamper_backup = True
    with pytest.raises(ProductDatabaseReadinessError, match="^product database restore drill failed$"): await world.run(tmp_path)
    assert world.calls == ["inventory:legacy-before", "backup", "restore"]
    assert world.backup_path is not None and world.backup_path.is_file()


@pytest.mark.asyncio
async def test_valid_ledger_restore_mismatch_and_legacy_drift_reject(tmp_path: Path) -> None:
    mismatch = World(); mismatch.restore_mismatch = True
    with pytest.raises(ProductDatabaseReadinessError, match="^product database restore drill failed$"): await mismatch.run(tmp_path / "mismatch")
    drift = World(); drift.legacy_drift = True
    with pytest.raises(ProductDatabaseReadinessError, match="^legacy database changed during preparation$"): await drift.run(tmp_path / "drift")
    assert "boundary-factory" not in drift.calls


@pytest.mark.asyncio
async def test_restore_create_primary_and_drop_failure_preserve_order(tmp_path: Path) -> None:
    world = World(); world.restore_primary = asyncio.CancelledError(); world.restore_cleanup_failure = RuntimeError("secret")
    with pytest.raises(BaseExceptionGroup) as raised: await world.run(tmp_path)
    leaves = _flatten(raised.value); assert type(leaves[0]) is asyncio.CancelledError and str(leaves[1]) == "product database restore drill failed"


def test_boundary_state_has_no_cleanup_authority_and_validates_mode_shape() -> None:
    fields = set(NewDatabaseBoundaryState.__dataclass_fields__)
    assert fields == {"mode", "initialized", "inventory"}
    assert not {"cleanup", "owned", "created_by_current_run"} & fields
    with pytest.raises(ProductDatabaseReadinessError): NewDatabaseBoundaryState("created", None, None)
    with pytest.raises(ProductDatabaseReadinessError): NewDatabaseBoundaryState("preexisting", INITIALIZED, None)
    assert not hasattr(readiness_module, "NewDatabaseInitialization") and not hasattr(readiness_module, "PreexistingNewDatabase")


def test_boundary_failure_envelopes_separate_enter_primary_from_lifecycle_cleanup() -> None:
    primary = RuntimeError("primary"); cleanup = RuntimeError("cleanup")
    enter = readiness_module.NewDatabaseBoundaryEnterFailure(primary, cleanup)
    exit_failure = readiness_module.NewDatabaseBoundaryExitFailure(cleanup)
    assert enter.primary is primary and enter.cleanup is cleanup
    assert exit_failure.cleanup is cleanup and not hasattr(exit_failure, "primary")


def test_current_schema_proof_rejects_target_identity_unclean_ledger_and_storage_spoof() -> None:
    proof_type = readiness_module.CurrentSchemaProof
    valid = _schema_proof()
    class Text(str): pass
    target_inventory = replace(valid.inventory, database=NEW_DATABASE)  # type: ignore[attr-defined]
    ready_rows = tuple(sorted(_ready_counts().items()))
    business_inventory = replace(valid.inventory, row_counts=ready_rows, nonempty_table_count=sum(count > 0 for _, count in ready_rows), total_row_count=sum(count for _, count in ready_rows))  # type: ignore[attr-defined]
    bad_storage = list(valid.storage)  # type: ignore[attr-defined]
    bad_storage[0] = replace(bad_storage[0], engine=Text("InnoDB"))
    invalid = (
        (target_inventory, valid.storage, (NEW_DATABASE,), (NEW_DATABASE,)),  # type: ignore[attr-defined]
        (business_inventory, valid.storage, (PROOF_DATABASE,), (PROOF_DATABASE,)),  # type: ignore[attr-defined]
        (valid.inventory, valid.storage, (PROOF_DATABASE,), ()),  # type: ignore[attr-defined]
        (valid.inventory, valid.storage, (PROOF_DATABASE, PROOF_DATABASE), (PROOF_DATABASE,)),  # type: ignore[attr-defined]
        (valid.inventory, valid.storage, (RESTORE_DATABASE,), (RESTORE_DATABASE,)),  # type: ignore[attr-defined]
        (valid.inventory, valid.storage, (Text(PROOF_DATABASE),), (PROOF_DATABASE,)),  # type: ignore[attr-defined]
        (valid.inventory, tuple(bad_storage), (PROOF_DATABASE,), (PROOF_DATABASE,)),  # type: ignore[attr-defined]
    )
    for values in invalid:
        with pytest.raises(ProductDatabaseReadinessError, match="^current schema proof failed$"):
            proof_type(*values)
    assert not hasattr(readiness_module, "CurrentSchemaAuthority")


def test_restore_storage_and_official_types_are_strict() -> None:
    world = World(target="ready"); target = world.snapshot(NEW_DATABASE); restored = replace(world.snapshot(LEGACY_DATABASE), database=RESTORE_DATABASE); audit = OfficialDataAudit(**_official_row())  # type: ignore[arg-type]
    class Text(str): pass
    with pytest.raises(ProductDatabaseReadinessError): RestoreDrillResult(restored, (Text(RESTORE_DATABASE),), (RESTORE_DATABASE,))
    original = world.storage(NEW_DATABASE)[0]
    for field in ("name", "engine", "collation"):
        rows = list(world.storage(NEW_DATABASE)); rows[0] = replace(original, **{field: Text(getattr(original, field))})
        with pytest.raises(ProductDatabaseReadinessError): assert_new_database_ready(target, INITIALIZED, audit, tuple(rows), _schema_proof())
    with pytest.raises(ProductDatabaseReadinessError): replace(audit, style_count=True)


def test_ready_audit_requires_exact_authoritative_structural_fingerprint() -> None:
    world = World(target="ready"); target = world.snapshot(NEW_DATABASE); audit = OfficialDataAudit(**_official_row())  # type: ignore[arg-type]
    class Hash(str): pass
    with pytest.raises(ProductDatabaseReadinessError, match="^new database readiness audit failed$"):
        assert_new_database_ready(replace(target, structural_fingerprint="9" * 64), INITIALIZED, audit, world.storage(NEW_DATABASE), _schema_proof())
    for invalid in (True, Hash("2" * 64), "A" * 64, "f" * 63, " " * 64):
        with pytest.raises(ProductDatabaseReadinessError, match="^new database readiness audit failed$"):
            assert_new_database_ready(target, INITIALIZED, audit, world.storage(NEW_DATABASE), invalid)  # type: ignore[arg-type]


def test_request_frozen_and_module_has_no_real_resource_imports(tmp_path: Path) -> None:
    request = PreparationRequest(LEGACY_DATABASE, NEW_DATABASE, tmp_path.resolve())
    with pytest.raises(FrozenInstanceError): request.new_database = LEGACY_DATABASE  # type: ignore[misc]
    tree = ast.parse((BACKEND_ROOT / "services" / "product_database_readiness.py").read_text(encoding="utf-8")); imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None}; imported.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
    forbidden = ("backend.config", "backend.database", "backend.gateways", "backend.scripts", "backend.security", "httpx", "subprocess")
    assert all(not any(module == prefix or module.startswith(f"{prefix}.") for prefix in forbidden) for module in imported)
