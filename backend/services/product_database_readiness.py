"""Dependency-injected Stage A product database preparation orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
from pathlib import Path
from typing import Callable

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
    PreparationReceipt,
    ProductDatabaseReadinessError,
    ReadinessState,
    StateReceipt,
    advance_receipt,
    canonical_receipt_hash,
    inventory_hash,
    validate_database_role,
    validate_restore_database,
)
from backend.schema_manifest import created_table_names, manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from backend.services.product_database_inventory import (
    TableStorage,
    assert_inventory_equal,
    assert_storage_policy,
)


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
ASSET_MANIFEST_PATH = (
    _BACKEND_ROOT / "assets" / ASSET_PACKAGE_VERSION / "manifest.json"
)
MARKET_MANIFEST_PATH = (
    _BACKEND_ROOT / "assets" / MARKET_PACKAGE_VERSION / "manifest.json"
)


_REQUEST_ERROR = "product database preparation request is invalid"
_LEGACY_INVENTORY_ERROR = "legacy database inventory failed"
_BACKUP_ERROR = "product database backup failed"
_RESTORE_ERROR = "product database restore drill failed"
_LEGACY_DRIFT_ERROR = "legacy database changed during preparation"
_INITIALIZE_ERROR = "new database initialization failed"
_ASSET_SEED_ERROR = "official asset seed failed"
_MARKET_SEED_ERROR = "official market source seed failed"
_TARGET_INVENTORY_ERROR = "new database inventory failed"
_AUDIT_ERROR = "new database readiness audit failed"
_SMOKE_ERROR = "readiness smoke failed"
_NETWORK_ERROR = "readiness smoke crossed network boundary"
_CLEANUP_ERROR = "product database cleanup failed"
_GROUP_ERROR = "product database preparation failed"
_FLOW_CONTROL = (asyncio.CancelledError, KeyboardInterrupt, SystemExit)


@dataclass(frozen=True)
class PreparationRequest:
    legacy_database: str
    new_database: str
    backup_directory: Path

    def __post_init__(self) -> None:
        try:
            validate_database_role("legacy", self.legacy_database)
            validate_database_role("new", self.new_database)
            path = self.backup_directory
            if (
                not isinstance(path, Path)
                or not path.is_absolute()
                or path.parent == path
                or ".." in path.parts
            ):
                raise ValueError
        except BaseException as error:
            _raise_normalized(error, _REQUEST_ERROR)


@dataclass(frozen=True)
class NewDatabaseInitialization:
    """Initialization evidence plus explicit current-run cleanup ownership."""

    result: object
    created_by_current_run: bool
    existing_inventory: DatabaseInventory | None = None
    existing_storage: tuple[TableStorage, ...] | None = None

    def __post_init__(self) -> None:
        created = self.created_by_current_run
        existing = self.existing_inventory
        storage = self.existing_storage
        if (
            type(created) is not bool
            or created
            and (existing is not None or storage is not None)
            or not created
            and (
                type(existing) is not DatabaseInventory
                or type(storage) is not tuple
                or any(type(row) is not TableStorage for row in storage)
            )
        ):
            raise ProductDatabaseReadinessError(_INITIALIZE_ERROR)


@dataclass(frozen=True)
class RestoreDrillResult:
    """Exact restore inventory with a closed, zero-residue ownership ledger."""

    inventory: DatabaseInventory
    created_databases: tuple[str, ...]
    cleaned_databases: tuple[str, ...]

    def __post_init__(self) -> None:
        try:
            if (
                type(self.inventory) is not DatabaseInventory
                or type(self.created_databases) is not tuple
                or type(self.cleaned_databases) is not tuple
                or len(self.created_databases) != 1
                or self.created_databases != self.cleaned_databases
            ):
                raise ValueError
            restore_database = validate_restore_database(
                self.created_databases[0]
            )
            if self.inventory.database != restore_database:
                raise ValueError
        except BaseException as error:
            _raise_normalized(error, _RESTORE_ERROR)


@dataclass(frozen=True)
class SmokeResult:
    provider_calls: int
    outbound_requests: int

    def __post_init__(self) -> None:
        if (
            type(self.provider_calls) is not int
            or self.provider_calls < 0
            or type(self.outbound_requests) is not int
            or self.outbound_requests < 0
        ):
            raise ProductDatabaseReadinessError(_SMOKE_ERROR)


def _fixed(message: str) -> ProductDatabaseReadinessError:
    return ProductDatabaseReadinessError(message)


def _clean_flow_control(error: BaseException) -> BaseException:
    if isinstance(error, asyncio.CancelledError):
        return asyncio.CancelledError()
    if isinstance(error, KeyboardInterrupt):
        return KeyboardInterrupt()
    if isinstance(error, SystemExit):
        return SystemExit(error.code) if type(error.code) is int else SystemExit()
    raise TypeError


def _normalized(error: BaseException, message: str) -> BaseException:
    if isinstance(error, BaseExceptionGroup):
        return BaseExceptionGroup(
            message, [_normalized(child, message) for child in error.exceptions]
        )
    if isinstance(error, _FLOW_CONTROL):
        return _clean_flow_control(error)
    return _fixed(message)


def _raise_public(error: BaseException) -> None:
    try:
        raise error from None
    except BaseException as outgoing:
        outgoing.__cause__ = None
        outgoing.__context__ = None
        outgoing.__suppress_context__ = True
        raise


def _raise_normalized(error: BaseException, message: str) -> None:
    _raise_public(_normalized(error, message))


async def _invoke(operation: Callable[..., object], *args: object) -> object:
    result = operation(*args)
    if inspect.isawaitable(result):
        return await result
    return result


async def _stage(
    message: str, operation: Callable[..., object], *args: object
) -> object:
    try:
        return await _invoke(operation, *args)
    except BaseException as error:
        _raise_normalized(error, message)


def _field(value: object, name: str) -> object:
    try:
        return getattr(value, name)
    except Exception:
        raise ValueError from None


def _initialization_payload(value: object) -> dict[str, object]:
    payload = {
        "databaseName": _field(value, "database_name"),
        "schemaVersion": _field(value, "schema_version"),
        "manifestHash": _field(value, "manifest_hash"),
        "tableCount": _field(value, "table_count"),
    }
    if (
        type(payload["databaseName"]) is not str
        or payload["databaseName"]
        != validate_database_role("new", payload["databaseName"])
        or type(payload["schemaVersion"]) is not str
        or payload["schemaVersion"] != EXPECTED_SCHEMA_VERSION
        or type(payload["manifestHash"]) is not str
        or payload["manifestHash"] != manifest_hash()
        or type(payload["tableCount"]) is not int
        or payload["tableCount"] != len(created_table_names())
    ):
        raise ValueError
    return payload


def _seed_payload(assets: object, market: object) -> dict[str, object]:
    return {
        "assets": {
            "packageVersion": _field(assets, "package_version"),
            "packageHash": _field(assets, "package_hash"),
            "styleCount": _field(assets, "style_count"),
            "cardCount": _field(assets, "card_count"),
            "inserted": _field(assets, "inserted"),
            "replayed": _field(assets, "replayed"),
            "advanced": _field(assets, "advanced"),
        },
        "market": {
            "packageVersion": _field(market, "package_version"),
            "packageHash": _field(market, "package_hash"),
            "sourceCount": _field(market, "source_count"),
            "inserted": _field(market, "inserted"),
            "replayed": _field(market, "replayed"),
        },
    }


def _validated_seed_payload(assets: object, market: object) -> dict[str, object]:
    seed = _seed_payload(assets, market)
    asset_package = load_asset_package(ASSET_MANIFEST_PATH, mode="release")
    market_package = load_market_source_package(MARKET_MANIFEST_PATH)
    asset_report = seed["assets"]
    market_report = seed["market"]
    if not isinstance(asset_report, dict) or not isinstance(market_report, dict):
        raise ValueError
    if (
        any(
            type(asset_report[key]) is not str
            for key in ("packageVersion", "packageHash")
        )
        or any(
            type(asset_report[key]) is not int or asset_report[key] < 0
            for key in (
                "styleCount",
                "cardCount",
                "inserted",
                "replayed",
                "advanced",
            )
        )
        or any(
            type(market_report[key]) is not str
            for key in ("packageVersion", "packageHash")
        )
        or any(
            type(market_report[key]) is not int or market_report[key] < 0
            for key in ("sourceCount", "inserted", "replayed")
        )
    ):
        raise ValueError
    if (
        asset_report
        != {
            "packageVersion": asset_package.package_version,
            "packageHash": canonical_hash(asset_package.manifest),
            "styleCount": len(asset_package.styles),
            "cardCount": len(asset_package.experience_cards),
            "inserted": asset_report["inserted"],
            "replayed": asset_report["replayed"],
            "advanced": 0,
        }
        or type(asset_report["inserted"]) is not int
        or type(asset_report["replayed"]) is not int
        or asset_report["inserted"] < 0
        or asset_report["replayed"] < 0
        or asset_report["inserted"] + asset_report["replayed"]
        != len(asset_package.styles) + len(asset_package.experience_cards)
        or market_report
        != {
            "packageVersion": market_package.package_version,
            "packageHash": canonical_hash(market_package.manifest),
            "sourceCount": len(market_package.sources),
            "inserted": market_report["inserted"],
            "replayed": market_report["replayed"],
        }
        or type(market_report["inserted"]) is not int
        or type(market_report["replayed"]) is not int
        or market_report["inserted"] < 0
        or market_report["replayed"] < 0
        or market_report["inserted"] + market_report["replayed"]
        != len(market_package.sources)
    ):
        raise ValueError
    return seed


def _validate_seed_mode(
    seed: dict[str, object], insertion_expected: bool
) -> None:
    assets = seed["assets"]
    market = seed["market"]
    if not isinstance(assets, dict) or not isinstance(market, dict):
        raise ValueError
    asset_total = assets["styleCount"] + assets["cardCount"]  # type: ignore[operator]
    market_total = market["sourceCount"]
    expected = (
        (asset_total, 0, market_total, 0)
        if insertion_expected
        else (0, asset_total, 0, market_total)
    )
    observed = (
        assets["inserted"],
        assets["replayed"],
        market["inserted"],
        market["replayed"],
    )
    if observed != expected:
        raise ValueError


def _expected_row_counts() -> tuple[tuple[str, int], ...]:
    expected = {name: 0 for name in created_table_names()}
    expected.update(
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
    return tuple(sorted(expected.items()))


def _validate_target_state(
    target: object,
    initialized: object,
    storage: object,
    *,
    expected_counts: tuple[tuple[str, int], ...] | None = None,
) -> DatabaseInventory:
    if type(target) is not DatabaseInventory:
        raise ValueError
    validate_database_role("new", target.database)
    expected_tables = tuple(sorted(created_table_names()))
    counts = expected_counts or _expected_row_counts()
    initialization = _initialization_payload(initialized)
    if (
        target.schema_version != EXPECTED_SCHEMA_VERSION
        or target.manifest_hash != manifest_hash()
        or target.table_names != expected_tables
        or target.row_counts != counts
        or target.nonempty_table_count != sum(
            count > 0 for _, count in counts
        )
        or target.total_row_count != sum(count for _, count in counts)
        or initialization["databaseName"] != target.database
        or type(storage) is not tuple
        or tuple(row.name for row in storage) != expected_tables
    ):
        raise ValueError
    assert_storage_policy(storage)
    return target


def _initialized_empty_counts() -> tuple[tuple[str, int], ...]:
    return tuple(
        (name, 1 if name == "schema_metadata" else 0)
        for name in sorted(created_table_names())
    )


def assert_new_database_ready(
    target: DatabaseInventory,
    initialized: object,
    assets: object,
    market: object,
    storage: tuple[TableStorage, ...],
) -> None:
    """Fail closed unless the target is exactly the approved empty product state."""

    try:
        _validate_target_state(target, initialized, storage)
        _validated_seed_payload(assets, market)
    except BaseException as error:
        _raise_normalized(error, _AUDIT_ERROR)


def _validate_backup(
    backup: object,
    authority: DatabaseInventory,
    previous: StateReceipt,
) -> BackupReceipt:
    if (
        type(backup) is not BackupReceipt
        or backup.source_database != authority.database
        or backup.source_inventory_hash != inventory_hash(authority)
        or backup.previous_receipt_hash != canonical_receipt_hash(previous)
    ):
        raise ValueError
    return backup


def _validate_smoke(value: object) -> SmokeResult:
    if type(value) is SmokeResult:
        return value
    try:
        return SmokeResult(
            provider_calls=_field(value, "provider_calls"),  # type: ignore[arg-type]
            outbound_requests=_field(value, "outbound_requests"),  # type: ignore[arg-type]
        )
    except BaseException as error:
        _raise_normalized(error, _SMOKE_ERROR)


def _finish_failure(primary: BaseException, cleanup: BaseException | None) -> None:
    normalized_cleanup = (
        None if cleanup is None else _normalized(cleanup, _CLEANUP_ERROR)
    )
    if normalized_cleanup is None:
        _raise_public(primary)
    _raise_public(BaseExceptionGroup(_GROUP_ERROR, [primary, normalized_cleanup]))


async def prepare_product_database(
    *,
    request: PreparationRequest,
    inventory: Callable[[str], object],
    create_backup: Callable[[DatabaseInventory, Path], object],
    restore_drill: Callable[[BackupReceipt, DatabaseInventory], object],
    initialize_new: Callable[[str], object],
    seed_assets: Callable[[str], object],
    seed_market: Callable[[str], object],
    read_storage: Callable[[str], object],
    smoke: Callable[[str], object],
    cleanup_new: Callable[[str], object] | None = None,
) -> PreparationReceipt:
    """Prepare the new product database and stop at the cutover approval gate."""

    try:
        if type(request) is not PreparationRequest:
            raise ValueError
        validate_database_role("legacy", request.legacy_database)
        validate_database_role("new", request.new_database)
    except BaseException as error:
        _raise_normalized(error, _REQUEST_ERROR)

    owned_new = False
    resume_ready = False
    primary: BaseException | None = None
    result: PreparationReceipt | None = None
    try:
        before = await _stage(_LEGACY_INVENTORY_ERROR, inventory, "legacy-before")
        if type(before) is not DatabaseInventory or before.database != request.legacy_database:
            raise _fixed(_LEGACY_INVENTORY_ERROR)

        receipts: list[StateReceipt] = [
            advance_receipt(
                None, ReadinessState.INVENTORY_VERIFIED, inventory_hash(before)
            )
        ]
        backup_value = await _stage(
            _BACKUP_ERROR, create_backup, before, request.backup_directory
        )
        try:
            backup = _validate_backup(backup_value, before, receipts[-1])
        except BaseException as error:
            _raise_normalized(error, _BACKUP_ERROR)
        receipts.append(
            advance_receipt(
                receipts[-1],
                ReadinessState.BACKUP_CREATED,
                canonical_receipt_hash(backup),
            )
        )

        restore_value = await _stage(_RESTORE_ERROR, restore_drill, backup, before)
        try:
            if type(restore_value) is not RestoreDrillResult:
                raise ValueError
            restore = restore_value.inventory
            assert_inventory_equal(before, restore)
        except BaseException as error:
            _raise_normalized(error, _RESTORE_ERROR)
        receipts.append(
            advance_receipt(
                receipts[-1],
                ReadinessState.RESTORE_DRILL_VERIFIED,
                canonical_hash(
                    {
                        "restoreInventoryHash": inventory_hash(restore),
                        "createdDatabases": restore_value.created_databases,
                        "cleanedDatabases": restore_value.cleaned_databases,
                    }
                ),
            )
        )

        after = await _stage(_LEGACY_INVENTORY_ERROR, inventory, "legacy-after")
        try:
            if type(after) is not DatabaseInventory or after.database != request.legacy_database:
                raise ValueError
            assert_inventory_equal(before, after)
        except BaseException as error:
            _raise_normalized(error, _LEGACY_DRIFT_ERROR)

        initialization_value = await _stage(
            _INITIALIZE_ERROR, initialize_new, request.new_database
        )
        if type(initialization_value) is not NewDatabaseInitialization:
            raise _fixed(_INITIALIZE_ERROR)
        initialized = initialization_value.result
        owned_new = initialization_value.created_by_current_run
        try:
            initialization_payload = _initialization_payload(initialized)
        except BaseException as error:
            _raise_normalized(error, _INITIALIZE_ERROR)
        if not owned_new:
            try:
                _validate_target_state(
                    initialization_value.existing_inventory,
                    initialized,
                    initialization_value.existing_storage,
                )
                resume_ready = True
            except (
                BaseExceptionGroup,
                asyncio.CancelledError,
                KeyboardInterrupt,
                SystemExit,
            ) as error:
                _raise_normalized(error, _AUDIT_ERROR)
            except Exception:
                try:
                    _validate_target_state(
                        initialization_value.existing_inventory,
                        initialized,
                        initialization_value.existing_storage,
                        expected_counts=_initialized_empty_counts(),
                    )
                except BaseException as error:
                    _raise_normalized(error, _AUDIT_ERROR)
        receipts.append(
            advance_receipt(
                receipts[-1],
                ReadinessState.NEW_DATABASE_INITIALIZED,
                canonical_hash(initialization_payload),
            )
        )

        assets = await _stage(_ASSET_SEED_ERROR, seed_assets, request.new_database)
        market = await _stage(
            _MARKET_SEED_ERROR, seed_market, request.new_database
        )
        try:
            seed_payload = _validated_seed_payload(assets, market)
            _validate_seed_mode(seed_payload, owned_new or not resume_ready)
        except BaseException as error:
            _raise_normalized(error, _AUDIT_ERROR)
        receipts.append(
            advance_receipt(
                receipts[-1],
                ReadinessState.OFFICIAL_DATA_SEEDED,
                canonical_hash(seed_payload),
            )
        )

        target = await _stage(_TARGET_INVENTORY_ERROR, inventory, "new")
        storage = await _stage(_AUDIT_ERROR, read_storage, request.new_database)
        assert_new_database_ready(target, initialized, assets, market, storage)  # type: ignore[arg-type]
        if resume_ready:
            try:
                assert_inventory_equal(
                    initialization_value.existing_inventory, target  # type: ignore[arg-type]
                )
            except BaseException as error:
                _raise_normalized(error, _AUDIT_ERROR)

        smoke_value = await _stage(_SMOKE_ERROR, smoke, request.new_database)
        smoke_result = _validate_smoke(smoke_value)
        if smoke_result.provider_calls != 0 or smoke_result.outbound_requests != 0:
            raise _fixed(_NETWORK_ERROR)

        receipts.append(
            advance_receipt(
                receipts[-1], ReadinessState.READINESS_VERIFIED, inventory_hash(target)
            )
        )
        receipts.append(
            advance_receipt(
                receipts[-1],
                ReadinessState.AWAITING_CUTOVER_APPROVAL,
                canonical_hash({"providerCalls": 0, "outboundRequests": 0}),
            )
        )
        result = PreparationReceipt(
            state=ReadinessState.AWAITING_CUTOVER_APPROVAL.value,
            previous_receipt_hash=canonical_receipt_hash(receipts[-1]),
            legacy_database=request.legacy_database,
            new_database=request.new_database,
            legacy_inventory_hash=inventory_hash(before),
            new_inventory_hash=inventory_hash(target),
            backup_sha256=backup.backup_sha256,
            style_count=seed_payload["assets"]["styleCount"],  # type: ignore[index]
            experience_card_count=seed_payload["assets"]["cardCount"],  # type: ignore[index]
            market_source_count=seed_payload["market"]["sourceCount"],  # type: ignore[index]
            receipts=tuple(receipts),
        )
    except BaseException as error:
        primary = error

    if primary is not None:
        cleanup_error: BaseException | None = None
        if owned_new:
            if cleanup_new is None:
                cleanup_error = _fixed(_CLEANUP_ERROR)
            else:
                try:
                    cleanup_target = validate_database_role("new", request.new_database)
                    await _invoke(cleanup_new, cleanup_target)
                except BaseException as error:
                    cleanup_error = error
        _finish_failure(primary, cleanup_error)
    assert result is not None
    return result
