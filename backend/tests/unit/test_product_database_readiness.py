from __future__ import annotations

import asyncio
import ast
from dataclasses import FrozenInstanceError, dataclass, replace
from pathlib import Path

import pytest

from backend.domain.assets import (
    PACKAGE_VERSION as ASSET_PACKAGE_VERSION,
    load_asset_package,
)
from backend.domain.json_contracts import canonical_hash
from backend.domain.market_sources import (
    PACKAGE_VERSION as MARKET_PACKAGE_VERSION,
    load_market_source_package,
)
from backend.domain.product_database_readiness import (
    BackupReceipt,
    DatabaseInventory,
    LEGACY_DATABASE,
    NEW_DATABASE,
    ProductDatabaseReadinessError,
    ReadinessState,
    advance_receipt,
    canonical_receipt_hash,
    inventory_hash,
    validate_restore_database,
)
from backend.schema_manifest import created_table_names, manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from backend.services.assets import AssetSeedReport
from backend.services.market_sources import MarketSourceSeedReport
from backend.services.product_database_inventory import TableStorage
from backend.services.product_database_readiness import (
    NewDatabaseInitialization,
    PreparationRequest,
    RestoreDrillResult,
    SmokeResult,
    assert_new_database_ready,
    prepare_product_database,
)


ZERO_HASH = "0" * 64
LEGACY_FINGERPRINT = "1" * 64
NEW_FINGERPRINT = "2" * 64
BACKEND_ROOT = Path(__file__).resolve().parents[2]
ASSET_PACKAGE = load_asset_package(
    BACKEND_ROOT / "assets" / ASSET_PACKAGE_VERSION / "manifest.json",
    mode="release",
)
MARKET_PACKAGE = load_market_source_package(
    BACKEND_ROOT / "assets" / MARKET_PACKAGE_VERSION / "manifest.json"
)
SCHEMA_HASH = manifest_hash()
ASSET_HASH = canonical_hash(ASSET_PACKAGE.manifest)
MARKET_HASH = canonical_hash(MARKET_PACKAGE.manifest)


@dataclass(frozen=True)
class InitializationResult:
    database_name: str
    schema_version: str
    manifest_hash: str
    table_count: int


def _legacy_inventory(*, fingerprint: str = LEGACY_FINGERPRINT) -> DatabaseInventory:
    return DatabaseInventory(
        database=LEGACY_DATABASE,
        server_version="8.4.3",
        schema_version="writer-core-v1.12.0",
        manifest_hash="3" * 64,
        structural_fingerprint=fingerprint,
        table_names=("projects",),
        row_counts=(("projects", 4),),
        nonempty_table_count=1,
        total_row_count=4,
    )


def _ready_counts() -> tuple[tuple[str, int], ...]:
    counts = {name: 0 for name in created_table_names()}
    counts.update(
        {
            "schema_metadata": 1,
            "style_templates": 10,
            "style_template_heads": 10,
            "experience_cards": 64,
            "experience_card_heads": 64,
            "market_sources": 2,
            "market_source_policy_revisions": 2,
            "market_source_policy_heads": 2,
            "market_source_refresh_states": 2,
        }
    )
    return tuple(sorted(counts.items()))


def _new_inventory() -> DatabaseInventory:
    counts = _ready_counts()
    return DatabaseInventory(
        database=NEW_DATABASE,
        server_version="8.4.3",
        schema_version=EXPECTED_SCHEMA_VERSION,
        manifest_hash=SCHEMA_HASH,
        structural_fingerprint=NEW_FINGERPRINT,
        table_names=tuple(name for name, _ in counts),
        row_counts=counts,
        nonempty_table_count=sum(count > 0 for _, count in counts),
        total_row_count=sum(count for _, count in counts),
    )


def _initialized_empty_inventory() -> DatabaseInventory:
    counts = tuple(
        (name, 1 if name == "schema_metadata" else 0)
        for name in sorted(created_table_names())
    )
    return DatabaseInventory(
        database=NEW_DATABASE,
        server_version="8.4.3",
        schema_version=EXPECTED_SCHEMA_VERSION,
        manifest_hash=SCHEMA_HASH,
        structural_fingerprint=NEW_FINGERPRINT,
        table_names=tuple(name for name, _ in counts),
        row_counts=counts,
        nonempty_table_count=1,
        total_row_count=1,
    )


def _restore_inventory(
    authority: DatabaseInventory,
    *,
    fingerprint: str | None = None,
) -> DatabaseInventory:
    return DatabaseInventory(
        database="novel_creator_phase7b_restore_0123456789abcdef0123456789abcdef",
        server_version=authority.server_version,
        schema_version=authority.schema_version,
        manifest_hash=authority.manifest_hash,
        structural_fingerprint=fingerprint or authority.structural_fingerprint,
        table_names=authority.table_names,
        row_counts=authority.row_counts,
        nonempty_table_count=authority.nonempty_table_count,
        total_row_count=authority.total_row_count,
    )


def _restore_result(authority: DatabaseInventory) -> RestoreDrillResult:
    restored = _restore_inventory(authority)
    return RestoreDrillResult(
        inventory=restored,
        created_databases=(restored.database,),
        cleaned_databases=(restored.database,),
    )


INITIALIZED = InitializationResult(
    database_name=NEW_DATABASE,
    schema_version=EXPECTED_SCHEMA_VERSION,
    manifest_hash=SCHEMA_HASH,
    table_count=91,
)
ASSETS = AssetSeedReport(
    package_version="writer-core-v1.1.0",
    package_hash=ASSET_HASH,
    style_count=10,
    card_count=64,
    inserted=74,
    replayed=0,
    advanced=0,
)
MARKET = MarketSourceSeedReport(
    package_version="market-sources-v1.0.0",
    source_count=2,
    package_hash=MARKET_HASH,
    inserted=2,
    replayed=0,
)
_BEFORE = _legacy_inventory()
_FIRST_RECEIPT = advance_receipt(
    None, ReadinessState.INVENTORY_VERIFIED, inventory_hash(_BEFORE)
)
BACKUP = BackupReceipt(
    state=ReadinessState.BACKUP_CREATED.value,
    previous_receipt_hash=canonical_receipt_hash(_FIRST_RECEIPT),
    source_database=LEGACY_DATABASE,
    backup_filename="phase7b.sql",
    backup_sha256="5" * 64,
    backup_byte_length=512,
    client_version="8.4.3",
    source_inventory_hash=inventory_hash(_BEFORE),
)


@pytest.mark.asyncio
async def test_prepare_advances_exactly_to_cutover_gate(tmp_path: Path) -> None:
    calls: list[str] = []
    before = _BEFORE
    after = _legacy_inventory()
    target = _new_inventory()

    async def inventory(role: str) -> DatabaseInventory:
        calls.append(f"inventory:{role}")
        return {"legacy-before": before, "legacy-after": after, "new": target}[role]

    async def create_backup(
        authority: DatabaseInventory, backup_directory: Path
    ) -> BackupReceipt:
        calls.append("backup")
        assert authority is before
        assert backup_directory == tmp_path.resolve()
        return BACKUP

    async def restore_drill(
        backup: BackupReceipt, authority: DatabaseInventory
    ) -> RestoreDrillResult:
        calls.append("restore")
        assert (backup, authority) == (BACKUP, before)
        return _restore_result(authority)

    async def initialize_new(database: str) -> NewDatabaseInitialization:
        calls.append("initialize")
        assert database == NEW_DATABASE
        return NewDatabaseInitialization(INITIALIZED, created_by_current_run=True)

    async def seed_assets(database: str) -> AssetSeedReport:
        calls.append("seed-assets")
        assert database == NEW_DATABASE
        return ASSETS

    async def seed_market(database: str) -> MarketSourceSeedReport:
        calls.append("seed-market")
        assert database == NEW_DATABASE
        return MARKET

    storage_calls: list[str] = []

    async def read_storage(database: str) -> tuple[TableStorage, ...]:
        storage_calls.append(database)
        return tuple(
            TableStorage(name, "InnoDB", "utf8mb4_0900_ai_ci")
            for name in target.table_names
        )

    async def smoke(database: str) -> SmokeResult:
        calls.append("smoke")
        assert database == NEW_DATABASE
        return SmokeResult(provider_calls=0, outbound_requests=0)

    result = await prepare_product_database(
        request=PreparationRequest(LEGACY_DATABASE, NEW_DATABASE, tmp_path.resolve()),
        inventory=inventory,
        create_backup=create_backup,
        restore_drill=restore_drill,
        initialize_new=initialize_new,
        seed_assets=seed_assets,
        seed_market=seed_market,
        read_storage=read_storage,
        smoke=smoke,
    )

    assert calls == [
        "inventory:legacy-before",
        "backup",
        "restore",
        "inventory:legacy-after",
        "initialize",
        "seed-assets",
        "seed-market",
        "inventory:new",
        "smoke",
    ]
    assert result.state == ReadinessState.AWAITING_CUTOVER_APPROVAL.value
    assert tuple(receipt.state for receipt in result.receipts) == tuple(
        state.value for state in tuple(ReadinessState)[:7]
    )
    assert storage_calls == [NEW_DATABASE]


def _storage(target: DatabaseInventory | None = None) -> tuple[TableStorage, ...]:
    current = target or _new_inventory()
    return tuple(
        TableStorage(name, "InnoDB", "utf8mb4_0900_ai_ci")
        for name in current.table_names
    )


class Scenario:
    def __init__(
        self,
        *,
        before: DatabaseInventory | None = None,
        after: DatabaseInventory | None = None,
        target: DatabaseInventory | BaseException | None = None,
        initialization: object | None = None,
        assets: AssetSeedReport = ASSETS,
        market: MarketSourceSeedReport = MARKET,
        smoke_result: object = SmokeResult(0, 0),
    ) -> None:
        self.before = before or _BEFORE
        self.after = after or self.before
        self.target = _new_inventory() if target is None else target
        self.initialization = (
            NewDatabaseInitialization(INITIALIZED, created_by_current_run=True)
            if initialization is None
            else initialization
        )
        self.assets = assets
        self.market = market
        self.smoke_result = smoke_result
        self.calls: list[str] = []
        self.cleaned: list[str] = []

    def backup(self) -> BackupReceipt:
        first = advance_receipt(
            None,
            ReadinessState.INVENTORY_VERIFIED,
            inventory_hash(self.before),
        )
        return replace(
            BACKUP,
            previous_receipt_hash=canonical_receipt_hash(first),
            source_inventory_hash=inventory_hash(self.before),
        )

    async def inventory(self, role: str) -> DatabaseInventory:
        self.calls.append(f"inventory:{role}")
        value = {
            "legacy-before": self.before,
            "legacy-after": self.after,
            "new": self.target,
        }[role]
        if isinstance(value, BaseException):
            raise value
        return value

    async def create_backup(
        self, _authority: DatabaseInventory, backup_directory: Path
    ) -> BackupReceipt:
        self.calls.append("backup")
        assert backup_directory.is_absolute()
        return self.backup()

    async def restore_drill(
        self, _backup: BackupReceipt, _authority: DatabaseInventory
    ) -> RestoreDrillResult:
        self.calls.append("restore")
        return _restore_result(self.before)

    async def initialize_new(self, database: str) -> object:
        self.calls.append("initialize")
        assert database == NEW_DATABASE
        return self.initialization

    async def seed_assets(self, database: str) -> AssetSeedReport:
        self.calls.append("seed-assets")
        assert database == NEW_DATABASE
        return self.assets

    async def seed_market(self, database: str) -> MarketSourceSeedReport:
        self.calls.append("seed-market")
        assert database == NEW_DATABASE
        return self.market

    async def read_storage(self, _database: str) -> tuple[TableStorage, ...]:
        self.calls.append("storage")
        return _storage(self.target if isinstance(self.target, DatabaseInventory) else None)

    async def smoke(self, _database: str) -> object:
        self.calls.append("smoke")
        return self.smoke_result

    async def cleanup_new(self, database: str) -> None:
        self.cleaned.append(database)

    async def run(self, tmp_path: Path):
        return await prepare_product_database(
            request=PreparationRequest(
                LEGACY_DATABASE, NEW_DATABASE, tmp_path.resolve()
            ),
            inventory=self.inventory,
            create_backup=self.create_backup,
            restore_drill=self.restore_drill,
            initialize_new=self.initialize_new,
            seed_assets=self.seed_assets,
            seed_market=self.seed_market,
            read_storage=self.read_storage,
            smoke=self.smoke,
            cleanup_new=self.cleanup_new,
        )


def test_preparation_request_is_frozen_and_rejects_wrong_roles_or_paths(
    tmp_path: Path,
) -> None:
    request = PreparationRequest(LEGACY_DATABASE, NEW_DATABASE, tmp_path.resolve())
    with pytest.raises(FrozenInstanceError):
        request.new_database = LEGACY_DATABASE  # type: ignore[misc]

    invalid = (
        (NEW_DATABASE, NEW_DATABASE, tmp_path.resolve()),
        (LEGACY_DATABASE, LEGACY_DATABASE, tmp_path.resolve()),
        (LEGACY_DATABASE, NEW_DATABASE, Path("relative")),
        (LEGACY_DATABASE, NEW_DATABASE, str(tmp_path.resolve())),
    )
    for values in invalid:
        with pytest.raises(
            ProductDatabaseReadinessError,
            match="^product database preparation request is invalid$",
        ) as raised:
            PreparationRequest(*values)  # type: ignore[arg-type]
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None


def test_readiness_module_has_no_cli_database_provider_or_network_imports() -> None:
    source = (
        BACKEND_ROOT / "services" / "product_database_readiness.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    forbidden = (
        "backend.config",
        "backend.database",
        "backend.gateways",
        "backend.scripts",
        "backend.security",
        "httpx",
        "subprocess",
    )
    assert all(
        not any(module == prefix or module.startswith(f"{prefix}.") for prefix in forbidden)
        for module in imported
    )


@pytest.mark.parametrize(
    ("mutation", "value"),
    (
        ("schema_version", "writer-core-v0"),
        ("manifest_hash", ZERO_HASH),
        ("table_names", tuple()),
        ("row_counts", tuple()),
    ),
)
def test_exact_audit_rejects_schema_table_and_count_drift(
    mutation: str, value: object
) -> None:
    target = _new_inventory()
    if mutation in {"table_names", "row_counts"}:
        target = DatabaseInventory(
            database=NEW_DATABASE,
            server_version=target.server_version,
            schema_version=target.schema_version,
            manifest_hash=target.manifest_hash,
            structural_fingerprint=target.structural_fingerprint,
            table_names=tuple(),
            row_counts=tuple(),
            nonempty_table_count=0,
            total_row_count=0,
        )
    else:
        target = replace(target, **{mutation: value})
    with pytest.raises(
        ProductDatabaseReadinessError,
        match="^new database readiness audit failed$",
    ):
        assert_new_database_ready(target, INITIALIZED, ASSETS, MARKET, _storage())


@pytest.mark.parametrize(
    "storage",
    (
        tuple(),
        tuple(
            TableStorage(
                row.name,
                "MyISAM" if index == 0 else row.engine,
                row.collation,
            )
            for index, row in enumerate(_storage())
        ),
        tuple(
            TableStorage(
                row.name,
                row.engine,
                "utf8mb4_general_ci" if index == 0 else row.collation,
            )
            for index, row in enumerate(_storage())
        ),
    ),
)
def test_exact_audit_rejects_missing_or_wrong_storage_policy(
    storage: tuple[TableStorage, ...],
) -> None:
    with pytest.raises(
        ProductDatabaseReadinessError,
        match="^new database readiness audit failed$",
    ):
        assert_new_database_ready(_new_inventory(), INITIALIZED, ASSETS, MARKET, storage)


@pytest.mark.parametrize(
    ("assets", "market"),
    (
        (replace(ASSETS, package_hash=ZERO_HASH), MARKET),
        (replace(ASSETS, style_count=9), MARKET),
        (replace(ASSETS, advanced=1, inserted=73), MARKET),
        (ASSETS, replace(MARKET, package_hash=ZERO_HASH)),
        (ASSETS, replace(MARKET, source_count=1)),
        (ASSETS, replace(MARKET, inserted=1, replayed=0)),
    ),
)
def test_exact_audit_derives_and_enforces_official_packages(
    assets: AssetSeedReport, market: MarketSourceSeedReport
) -> None:
    with pytest.raises(
        ProductDatabaseReadinessError,
        match="^new database readiness audit failed$",
    ):
        assert_new_database_ready(
            _new_inventory(), INITIALIZED, assets, market, _storage()
        )


@pytest.mark.asyncio
async def test_malformed_seed_report_fails_with_fixed_error_before_receipt_hashing(
    tmp_path: Path,
) -> None:
    scenario = Scenario(assets=replace(ASSETS, inserted=object()))
    with pytest.raises(
        ProductDatabaseReadinessError,
        match="^new database readiness audit failed$",
    ) as raised:
        await scenario.run(tmp_path)
    assert type(raised.value) is ProductDatabaseReadinessError
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "inventory:new" not in scenario.calls


@pytest.mark.asyncio
async def test_restore_inventory_mismatch_stops_before_second_legacy_read(
    tmp_path: Path,
) -> None:
    scenario = Scenario()
    restored = _restore_inventory(scenario.before, fingerprint="7" * 64)
    restore = RestoreDrillResult(
        inventory=restored,
        created_databases=(restored.database,),
        cleaned_databases=(restored.database,),
    )

    async def mismatch(*_args: object) -> RestoreDrillResult:
        scenario.calls.append("restore")
        return restore

    scenario.restore_drill = mismatch  # type: ignore[method-assign]
    with pytest.raises(
        ProductDatabaseReadinessError,
        match="^product database restore drill failed$",
    ):
        await scenario.run(tmp_path)
    assert scenario.calls == ["inventory:legacy-before", "backup", "restore"]
    assert scenario.cleaned == []


@pytest.mark.asyncio
async def test_restore_inventory_evidence_must_name_owned_restore_database(
    tmp_path: Path,
) -> None:
    scenario = Scenario()

    async def wrong_identity(*_args: object) -> RestoreDrillResult:
        scenario.calls.append("restore")
        return RestoreDrillResult(
            inventory=scenario.before,
            created_databases=(
                "novel_creator_phase7b_restore_0123456789abcdef0123456789abcdef",
            ),
            cleaned_databases=(
                "novel_creator_phase7b_restore_0123456789abcdef0123456789abcdef",
            ),
        )

    scenario.restore_drill = wrong_identity  # type: ignore[method-assign]
    with pytest.raises(
        ProductDatabaseReadinessError,
        match="^product database restore drill failed$",
    ):
        await scenario.run(tmp_path)
    assert scenario.calls == ["inventory:legacy-before", "backup", "restore"]


@pytest.mark.asyncio
async def test_restore_noop_cannot_issue_verified_receipt(tmp_path: Path) -> None:
    scenario = Scenario()

    async def noop(*_args: object) -> None:
        scenario.calls.append("restore")

    scenario.restore_drill = noop  # type: ignore[method-assign]
    with pytest.raises(
        ProductDatabaseReadinessError,
        match="^product database restore drill failed$",
    ):
        await scenario.run(tmp_path)
    assert scenario.calls == ["inventory:legacy-before", "backup", "restore"]


@pytest.mark.asyncio
async def test_restore_boundary_cleans_only_its_current_run_database_and_retains_backup(
    tmp_path: Path,
) -> None:
    scenario = Scenario()
    restore_database = (
        "novel_creator_phase7b_restore_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )
    created: list[str] = []
    cleaned: list[str] = []

    async def failing_restore(
        _backup: BackupReceipt, _authority: DatabaseInventory
    ) -> None:
        scenario.calls.append("restore")
        owned = validate_restore_database(restore_database)
        created.append(owned)
        try:
            raise RuntimeError("sensitive restore failure")
        finally:
            cleaned.append(validate_restore_database(owned))

    scenario.restore_drill = failing_restore  # type: ignore[method-assign]
    with pytest.raises(
        ProductDatabaseReadinessError,
        match="^product database restore drill failed$",
    ):
        await scenario.run(tmp_path)
    assert created == [restore_database]
    assert cleaned == [restore_database]
    assert LEGACY_DATABASE not in cleaned
    assert NEW_DATABASE not in cleaned
    assert scenario.calls == ["inventory:legacy-before", "backup", "restore"]


@pytest.mark.asyncio
async def test_legacy_drift_stops_before_target_initialization(tmp_path: Path) -> None:
    scenario = Scenario(after=_legacy_inventory(fingerprint="8" * 64))
    with pytest.raises(
        ProductDatabaseReadinessError,
        match="^legacy database changed during preparation$",
    ):
        await scenario.run(tmp_path)
    assert scenario.calls[-1] == "inventory:legacy-after"
    assert "initialize" not in scenario.calls
    assert scenario.before == _BEFORE


@pytest.mark.asyncio
async def test_exact_ready_resume_replays_seeds_and_never_cleans_preexisting_target(
    tmp_path: Path,
) -> None:
    scenario = Scenario(
        initialization=NewDatabaseInitialization(
            INITIALIZED,
            created_by_current_run=False,
            existing_inventory=_new_inventory(),
            existing_storage=_storage(),
        ),
        assets=replace(ASSETS, inserted=0, replayed=74),
        market=replace(MARKET, inserted=0, replayed=2),
    )
    receipt = await scenario.run(tmp_path)
    assert receipt.state == ReadinessState.AWAITING_CUTOVER_APPROVAL.value
    assert scenario.cleaned == []
    assert scenario.calls.count("seed-assets") == 1
    assert scenario.calls.count("seed-market") == 1


@pytest.mark.asyncio
async def test_preexisting_empty_target_inserts_without_acquiring_cleanup_ownership(
    tmp_path: Path,
) -> None:
    empty = _initialized_empty_inventory()
    scenario = Scenario(
        initialization=NewDatabaseInitialization(
            INITIALIZED,
            created_by_current_run=False,
            existing_inventory=empty,
            existing_storage=_storage(empty),
        )
    )
    receipt = await scenario.run(tmp_path)
    assert receipt.state == ReadinessState.AWAITING_CUTOVER_APPROVAL.value
    assert scenario.cleaned == []
    assert scenario.calls.count("seed-assets") == 1
    assert scenario.calls.count("seed-market") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("created_by_current_run", (True, False))
async def test_seed_report_mode_must_match_fresh_or_resume_ownership(
    tmp_path: Path, created_by_current_run: bool
) -> None:
    if created_by_current_run:
        initialization = NewDatabaseInitialization(
            INITIALIZED, created_by_current_run=True
        )
        assets = replace(ASSETS, inserted=0, replayed=74)
        market = replace(MARKET, inserted=0, replayed=2)
    else:
        initialization = NewDatabaseInitialization(
            INITIALIZED,
            created_by_current_run=False,
            existing_inventory=_new_inventory(),
            existing_storage=_storage(),
        )
        assets = ASSETS
        market = MARKET
    scenario = Scenario(
        initialization=initialization,
        assets=assets,
        market=market,
    )
    with pytest.raises(
        ProductDatabaseReadinessError,
        match="^new database readiness audit failed$",
    ):
        await scenario.run(tmp_path)
    assert scenario.cleaned == (
        [NEW_DATABASE] if created_by_current_run else []
    )
    assert "inventory:new" not in scenario.calls


@pytest.mark.asyncio
async def test_partial_preexisting_target_is_rejected_without_cleanup(
    tmp_path: Path,
) -> None:
    counts = dict(_ready_counts())
    counts["projects"] = 1
    row_counts = tuple(sorted(counts.items()))
    partial = replace(
        _new_inventory(),
        row_counts=row_counts,
        nonempty_table_count=10,
        total_row_count=sum(count for _, count in row_counts),
    )
    scenario = Scenario(
        target=partial,
        initialization=NewDatabaseInitialization(
            INITIALIZED,
            created_by_current_run=False,
            existing_inventory=partial,
            existing_storage=_storage(partial),
        ),
    )
    with pytest.raises(
        ProductDatabaseReadinessError,
        match="^new database readiness audit failed$",
    ):
        await scenario.run(tmp_path)
    assert scenario.cleaned == []
    assert "seed-assets" not in scenario.calls
    assert "seed-market" not in scenario.calls


@pytest.mark.asyncio
async def test_bare_initialization_result_is_rejected_before_seed_or_cleanup(
    tmp_path: Path,
) -> None:
    scenario = Scenario(initialization=INITIALIZED)
    with pytest.raises(
        ProductDatabaseReadinessError,
        match="^new database initialization failed$",
    ):
        await scenario.run(tmp_path)
    assert "seed-assets" not in scenario.calls
    assert scenario.cleaned == []


@pytest.mark.asyncio
async def test_equality_spoofing_initialization_field_fails_before_hashing(
    tmp_path: Path,
) -> None:
    class EqualitySpoof:
        def __eq__(self, _other: object) -> bool:
            return True

    malformed = replace(INITIALIZED, manifest_hash=EqualitySpoof())
    scenario = Scenario(
        initialization=NewDatabaseInitialization(
            malformed, created_by_current_run=True
        )
    )
    with pytest.raises(
        ProductDatabaseReadinessError,
        match="^new database initialization failed$",
    ) as raised:
        await scenario.run(tmp_path)
    assert type(raised.value) is ProductDatabaseReadinessError
    assert scenario.cleaned == [NEW_DATABASE]
    assert "seed-assets" not in scenario.calls


@pytest.mark.asyncio
async def test_equality_spoofing_seed_hash_fails_before_receipt_hashing(
    tmp_path: Path,
) -> None:
    class EqualitySpoof:
        def __eq__(self, _other: object) -> bool:
            return True

    scenario = Scenario(assets=replace(ASSETS, package_hash=EqualitySpoof()))
    with pytest.raises(
        ProductDatabaseReadinessError,
        match="^new database readiness audit failed$",
    ) as raised:
        await scenario.run(tmp_path)
    assert type(raised.value) is ProductDatabaseReadinessError
    assert scenario.cleaned == [NEW_DATABASE]
    assert "inventory:new" not in scenario.calls


@pytest.mark.asyncio
async def test_flow_control_from_seed_evidence_access_is_not_swallowed(
    tmp_path: Path,
) -> None:
    class InterruptingAssetReport:
        package_version = ASSETS.package_version
        package_hash = ASSETS.package_hash

        @property
        def style_count(self):
            raise asyncio.CancelledError("sensitive cancellation")

    scenario = Scenario(
        initialization=NewDatabaseInitialization(
            INITIALIZED, created_by_current_run=True
        ),
        assets=InterruptingAssetReport(),  # type: ignore[arg-type]
    )
    with pytest.raises(asyncio.CancelledError) as raised:
        await scenario.run(tmp_path)
    assert raised.value.args == ()
    assert scenario.cleaned == [NEW_DATABASE]


@pytest.mark.asyncio
async def test_absent_current_run_target_is_cleaned_but_backup_is_retained(
    tmp_path: Path,
) -> None:
    scenario = Scenario(
        target=RuntimeError("sensitive database detail"),
        initialization=NewDatabaseInitialization(
            INITIALIZED, created_by_current_run=True
        ),
    )
    with pytest.raises(
        ProductDatabaseReadinessError,
        match="^new database inventory failed$",
    ) as raised:
        await scenario.run(tmp_path)
    assert scenario.cleaned == [NEW_DATABASE]
    assert "sensitive" not in str(raised.value)
    assert scenario.calls.count("backup") == 1


@pytest.mark.asyncio
async def test_owned_target_failure_without_cleanup_boundary_is_reported(
    tmp_path: Path,
) -> None:
    scenario = Scenario(
        target=RuntimeError("sensitive database detail"),
        initialization=NewDatabaseInitialization(
            INITIALIZED, created_by_current_run=True
        ),
    )
    with pytest.raises(BaseExceptionGroup) as raised:
        await prepare_product_database(
            request=PreparationRequest(
                LEGACY_DATABASE, NEW_DATABASE, tmp_path.resolve()
            ),
            inventory=scenario.inventory,
            create_backup=scenario.create_backup,
            restore_drill=scenario.restore_drill,
            initialize_new=scenario.initialize_new,
            seed_assets=scenario.seed_assets,
            seed_market=scenario.seed_market,
            read_storage=scenario.read_storage,
            smoke=scenario.smoke,
        )
    assert [str(error) for error in _leaves(raised.value)] == [
        "new database inventory failed",
        "product database cleanup failed",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(("field", "value"), (("provider_calls", 1), ("outbound_requests", 1)))
async def test_smoke_requires_zero_provider_and_outbound_activity(
    tmp_path: Path, field: str, value: int
) -> None:
    scenario = Scenario(
        initialization=NewDatabaseInitialization(
            INITIALIZED, created_by_current_run=True
        ),
        smoke_result=replace(SmokeResult(0, 0), **{field: value}),
    )
    with pytest.raises(
        ProductDatabaseReadinessError,
        match="^readiness smoke crossed network boundary$",
    ):
        await scenario.run(tmp_path)
    assert scenario.cleaned == [NEW_DATABASE]


def _leaves(error: BaseException) -> list[BaseException]:
    if isinstance(error, BaseExceptionGroup):
        return [leaf for child in error.exceptions for leaf in _leaves(child)]
    return [error]


@pytest.mark.asyncio
async def test_primary_failure_precedes_safe_cleanup_failure(tmp_path: Path) -> None:
    scenario = Scenario(
        initialization=NewDatabaseInitialization(
            INITIALIZED, created_by_current_run=True
        ),
        smoke_result=RuntimeError("primary secret"),
    )

    async def failed_smoke(_database: str) -> object:
        scenario.calls.append("smoke")
        raise scenario.smoke_result  # type: ignore[misc]

    async def failed_cleanup(database: str) -> None:
        scenario.cleaned.append(database)
        raise RuntimeError("cleanup secret")

    scenario.smoke = failed_smoke  # type: ignore[method-assign]
    scenario.cleanup_new = failed_cleanup  # type: ignore[method-assign]
    with pytest.raises(BaseExceptionGroup) as raised:
        await scenario.run(tmp_path)
    leaves = _leaves(raised.value)
    assert [str(error) for error in leaves] == [
        "readiness smoke failed",
        "product database cleanup failed",
    ]
    assert scenario.cleaned == [NEW_DATABASE]
    assert "secret" not in str(raised.value)


@pytest.mark.asyncio
async def test_cancellation_is_sanitized_and_cleanup_finishes(tmp_path: Path) -> None:
    scenario = Scenario(
        initialization=NewDatabaseInitialization(
            INITIALIZED, created_by_current_run=True
        )
    )

    async def cancelled_smoke(_database: str) -> SmokeResult:
        scenario.calls.append("smoke")
        raise asyncio.CancelledError("sensitive cancellation")

    scenario.smoke = cancelled_smoke  # type: ignore[method-assign]
    with pytest.raises(asyncio.CancelledError) as raised:
        await scenario.run(tmp_path)
    assert raised.value.args == ()
    assert scenario.cleaned == [NEW_DATABASE]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("keyboard", "system-exit"))
async def test_primary_flow_control_semantics_survive_owned_cleanup(
    tmp_path: Path, kind: str
) -> None:
    scenario = Scenario()

    async def interrupted_smoke(_database: str) -> SmokeResult:
        scenario.calls.append("smoke")
        if kind == "keyboard":
            raise KeyboardInterrupt("sensitive interruption")
        raise SystemExit(23)

    scenario.smoke = interrupted_smoke  # type: ignore[method-assign]
    expected_type = KeyboardInterrupt if kind == "keyboard" else SystemExit
    with pytest.raises(expected_type) as raised:
        await scenario.run(tmp_path)
    assert scenario.cleaned == [NEW_DATABASE]
    if kind == "keyboard":
        assert raised.value.args == ()
    else:
        assert raised.value.code == 23  # type: ignore[attr-defined]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("cancelled", "keyboard", "system-exit"))
async def test_cleanup_flow_control_is_retained_with_primary_failure(
    tmp_path: Path, kind: str
) -> None:
    scenario = Scenario(
        initialization=NewDatabaseInitialization(
            INITIALIZED, created_by_current_run=True
        ),
        smoke_result=SmokeResult(1, 0),
    )

    async def interrupted_cleanup(database: str) -> None:
        scenario.cleaned.append(database)
        if kind == "cancelled":
            raise asyncio.CancelledError("sensitive interruption")
        if kind == "keyboard":
            raise KeyboardInterrupt("sensitive interruption")
        raise SystemExit(29)

    scenario.cleanup_new = interrupted_cleanup  # type: ignore[method-assign]
    with pytest.raises(BaseExceptionGroup) as raised:
        await scenario.run(tmp_path)
    leaves = _leaves(raised.value)
    assert type(leaves[0]) is ProductDatabaseReadinessError
    expected_type = {
        "cancelled": asyncio.CancelledError,
        "keyboard": KeyboardInterrupt,
        "system-exit": SystemExit,
    }[kind]
    assert type(leaves[1]) is expected_type
    if kind == "system-exit":
        assert leaves[1].code == 29  # type: ignore[attr-defined]
    else:
        assert leaves[1].args == ()
    assert scenario.cleaned == [NEW_DATABASE]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stage", "message", "cleanup_expected"),
    (
        ("legacy-before", "legacy database inventory failed", False),
        ("backup", "product database backup failed", False),
        ("restore", "product database restore drill failed", False),
        ("legacy-after", "legacy database inventory failed", False),
        ("initialize", "new database initialization failed", False),
        ("seed-assets", "official asset seed failed", True),
        ("seed-market", "official market source seed failed", True),
        ("new", "new database inventory failed", True),
        ("storage", "new database readiness audit failed", True),
        ("smoke", "readiness smoke failed", True),
    ),
)
async def test_every_stage_failure_stops_with_one_fixed_public_error(
    tmp_path: Path, stage: str, message: str, cleanup_expected: bool
) -> None:
    scenario = Scenario()
    if stage in {"legacy-before", "legacy-after", "new"}:
        original_inventory = scenario.inventory

        async def failing_inventory(role: str) -> DatabaseInventory:
            if role == stage:
                scenario.calls.append(f"inventory:{role}")
                raise RuntimeError(f"sensitive {stage} failure")
            return await original_inventory(role)

        scenario.inventory = failing_inventory  # type: ignore[method-assign]
    else:
        attribute = {
            "backup": "create_backup",
            "restore": "restore_drill",
            "initialize": "initialize_new",
            "seed-assets": "seed_assets",
            "seed-market": "seed_market",
            "storage": "read_storage",
            "smoke": "smoke",
        }[stage]

        async def failing_operation(*_args: object) -> object:
            scenario.calls.append(stage)
            raise RuntimeError(f"sensitive {stage} failure")

        setattr(scenario, attribute, failing_operation)

    with pytest.raises(
        ProductDatabaseReadinessError,
        match=f"^{message}$",
    ) as raised:
        await scenario.run(tmp_path)
    assert "sensitive" not in str(raised.value)
    assert scenario.cleaned == ([NEW_DATABASE] if cleanup_expected else [])
