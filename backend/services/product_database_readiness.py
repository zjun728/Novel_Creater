"""Dependency-injected Stage A product database preparation orchestration."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
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
_PROOF_ERROR = "current schema proof failed"
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

_FIXED_PUBLIC_ERRORS = frozenset(
    {
        _REQUEST_ERROR,
        _LEGACY_INVENTORY_ERROR,
        _BACKUP_ERROR,
        _RESTORE_ERROR,
        _LEGACY_DRIFT_ERROR,
        _PROOF_ERROR,
        _INITIALIZE_ERROR,
        _ASSET_SEED_ERROR,
        _MARKET_SEED_ERROR,
        _TARGET_INVENTORY_ERROR,
        _AUDIT_ERROR,
        _SMOKE_ERROR,
        _NETWORK_ERROR,
        _CLEANUP_ERROR,
        _GROUP_ERROR,
    }
)


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
class NewDatabaseBoundaryState:
    """Non-authorizing evidence returned by the atomic lifecycle boundary."""

    mode: str
    initialized: object | None
    inventory: DatabaseInventory | None

    def __post_init__(self) -> None:
        if (
            type(self.mode) is not str
            or self.mode not in ("created", "preexisting")
            or self.mode == "created"
            and (self.initialized is None or self.inventory is not None)
            or self.mode == "preexisting"
            and (
                self.initialized is not None
                or type(self.inventory) is not DatabaseInventory
            )
        ):
            raise ProductDatabaseReadinessError(_INITIALIZE_ERROR)


@dataclass(frozen=True)
class CurrentSchemaProof:
    """Closed lifecycle evidence from a disposable current-schema database."""

    inventory: DatabaseInventory
    storage: tuple[TableStorage, ...]
    created_databases: tuple[str, ...]
    cleaned_databases: tuple[str, ...]

    def __post_init__(self) -> None:
        try:
            _validate_current_schema_proof_fields(
                self.inventory,
                self.storage,
                self.created_databases,
                self.cleaned_databases,
            )
        except BaseException as error:
            _raise_normalized(error, _PROOF_ERROR)


class NewDatabaseBoundaryEnterFailure(BaseException):
    """Boundary-owned enter failure with an explicit cleanup failure."""

    def __init__(self, primary: BaseException, cleanup: BaseException) -> None:
        if not isinstance(primary, BaseException) or not isinstance(
            cleanup, BaseException
        ):
            raise TypeError
        super().__init__()
        self.primary = primary
        self.cleanup = cleanup


class NewDatabaseBoundaryExitFailure(BaseException):
    """Boundary-owned cleanup, commit, or lock-release failure."""

    def __init__(self, cleanup: BaseException) -> None:
        if not isinstance(cleanup, BaseException):
            raise TypeError
        super().__init__()
        self.cleanup = cleanup


class _BoundaryBodyFailure(BaseException):
    """Private marker separating body propagation from boundary failures."""


@dataclass(frozen=True)
class OfficialDataAudit:
    """Read-only database observations for all approved official data."""

    asset_package_version: str
    asset_package_hash: str
    style_content_hash: str
    style_count: int
    card_content_hash: str
    card_count: int
    market_package_version: str
    market_package_hash: str
    market_content_hash: str
    market_source_count: int
    market_source_authority: tuple[str, ...]

    def __post_init__(self) -> None:
        strings = (
            self.asset_package_version,
            self.asset_package_hash,
            self.style_content_hash,
            self.card_content_hash,
            self.market_package_version,
            self.market_package_hash,
            self.market_content_hash,
        )
        hashes = (
            self.asset_package_hash,
            self.style_content_hash,
            self.card_content_hash,
            self.market_package_hash,
            self.market_content_hash,
        )
        if (
            any(type(value) is not str or not value.strip() for value in strings)
            or any(
                len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
                for value in hashes
            )
            or type(self.style_count) is not int
            or self.style_count < 0
            or type(self.card_count) is not int
            or self.card_count < 0
            or type(self.market_source_count) is not int
            or self.market_source_count < 0
            or type(self.market_source_authority) is not tuple
            or any(
                type(value) is not str or not value.strip()
                for value in self.market_source_authority
            )
            or self.market_source_authority
            != tuple(sorted(set(self.market_source_authority)))
        ):
            raise ProductDatabaseReadinessError(_AUDIT_ERROR)


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
                or any(
                    type(name) is not str or not name.strip()
                    for name in self.created_databases + self.cleaned_databases
                )
                or len(self.created_databases) != 1
                or len(set(self.created_databases)) != len(self.created_databases)
                or len(set(self.cleaned_databases)) != len(self.cleaned_databases)
            ):
                raise ValueError
            restore_database = validate_restore_database(self.inventory.database)
            expected_ledger = (restore_database,)
            if (
                self.created_databases != expected_ledger
                or self.cleaned_databases != expected_ledger
            ):
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


def _safe_body_primary(error: BaseException) -> BaseException:
    if isinstance(error, BaseExceptionGroup):
        return BaseExceptionGroup(
            _GROUP_ERROR,
            [_safe_body_primary(child) for child in error.exceptions],
        )
    if isinstance(error, _FLOW_CONTROL):
        return _clean_flow_control(error)
    if (
        type(error) is ProductDatabaseReadinessError
        and str(error) in _FIXED_PUBLIC_ERRORS
    ):
        return _fixed(str(error))
    return _fixed(_GROUP_ERROR)


def _raise_enter_failure(error: BaseException) -> None:
    if type(error) is not NewDatabaseBoundaryEnterFailure:
        _raise_normalized(error, _INITIALIZE_ERROR)
    primary = _normalized(error.primary, _INITIALIZE_ERROR)
    cleanup = _normalized(error.cleanup, _CLEANUP_ERROR)
    _raise_public(BaseExceptionGroup(_GROUP_ERROR, [primary, cleanup]))


def _raise_exit_failure(
    primary: BaseException, lifecycle: BaseException
) -> None:
    safe_primary = _safe_body_primary(primary)
    cleanup = (
        lifecycle.cleanup
        if type(lifecycle) is NewDatabaseBoundaryExitFailure
        else lifecycle
    )
    safe_cleanup = _normalized(cleanup, _CLEANUP_ERROR)
    _raise_public(
        BaseExceptionGroup(_GROUP_ERROR, [safe_primary, safe_cleanup])
    )


@asynccontextmanager
async def _normalized_database_boundary(boundary: object):
    entered = False
    body_primary: BaseException | None = None
    try:
        async with boundary as value:  # type: ignore[attr-defined]
            entered = True
            try:
                yield value
            except BaseException as error:
                body_primary = error
                raise _BoundaryBodyFailure() from None
    except BaseException as error:
        if not entered:
            _raise_enter_failure(error)
        if body_primary is None:
            cleanup = (
                error.cleanup
                if type(error) is NewDatabaseBoundaryExitFailure
                else error
            )
            _raise_normalized(cleanup, _CLEANUP_ERROR)
        if type(error) is _BoundaryBodyFailure:
            _raise_public(_safe_body_primary(body_primary))
        _raise_exit_failure(body_primary, error)
    else:
        if body_primary is not None:
            _raise_public(_safe_body_primary(body_primary))


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


def _validated_official_data(value: object) -> dict[str, object]:
    if type(value) is not OfficialDataAudit:
        raise ValueError
    asset_package = load_asset_package(ASSET_MANIFEST_PATH, mode="release")
    market_package = load_market_source_package(MARKET_MANIFEST_PATH)
    payload = {
        "assetPackageVersion": value.asset_package_version,
        "assetPackageHash": value.asset_package_hash,
        "styleContentHash": value.style_content_hash,
        "styleCount": value.style_count,
        "cardContentHash": value.card_content_hash,
        "cardCount": value.card_count,
        "marketPackageVersion": value.market_package_version,
        "marketPackageHash": value.market_package_hash,
        "marketContentHash": value.market_content_hash,
        "marketSourceCount": value.market_source_count,
        "marketSourceAuthority": value.market_source_authority,
    }
    expected = {
        "assetPackageVersion": asset_package.package_version,
        "assetPackageHash": canonical_hash(asset_package.manifest),
        "styleContentHash": asset_package.manifest.styles_file.sha256,
        "styleCount": len(asset_package.styles),
        "cardContentHash": asset_package.manifest.experience_cards_file.sha256,
        "cardCount": len(asset_package.experience_cards),
        "marketPackageVersion": market_package.package_version,
        "marketPackageHash": canonical_hash(market_package.manifest),
        "marketContentHash": market_package.manifest.sources_file.sha256,
        "marketSourceCount": len(market_package.sources),
        "marketSourceAuthority": tuple(
            sorted(source.stable_key for source in market_package.sources)
        ),
    }
    if payload != expected:
        raise ValueError
    return payload


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
            "application_settings": 1,
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


def _expected_proof_row_counts() -> tuple[tuple[str, int], ...]:
    return tuple(
        sorted(
            (
                name,
                1 if name in {"schema_metadata", "application_settings"} else 0,
            )
            for name in created_table_names()
        )
    )


def _validate_current_schema_proof_fields(
    inventory: object,
    storage: object,
    created_databases: object,
    cleaned_databases: object,
) -> tuple[DatabaseInventory, tuple[TableStorage, ...], str]:
    if type(inventory) is not DatabaseInventory:
        raise ValueError
    proof_database = validate_restore_database(inventory.database)
    expected_tables = tuple(sorted(created_table_names()))
    expected_counts = _expected_proof_row_counts()
    validated_storage = _validate_storage(storage)
    expected_ledger = (proof_database,)
    if (
        inventory.schema_version != EXPECTED_SCHEMA_VERSION
        or inventory.manifest_hash != manifest_hash()
        or inventory.table_names != expected_tables
        or inventory.row_counts != expected_counts
        or inventory.nonempty_table_count
        != sum(count > 0 for _, count in expected_counts)
        or inventory.total_row_count != sum(count for _, count in expected_counts)
        or tuple(row.name for row in validated_storage) != expected_tables
        or type(created_databases) is not tuple
        or type(cleaned_databases) is not tuple
        or any(
            type(name) is not str or not name.strip()
            for name in created_databases + cleaned_databases
        )
        or created_databases != expected_ledger
        or cleaned_databases != expected_ledger
    ):
        raise ValueError
    assert_storage_policy(validated_storage)
    return inventory, validated_storage, proof_database


def _validated_current_schema_proof(value: object) -> CurrentSchemaProof:
    if type(value) is not CurrentSchemaProof:
        raise ValueError
    _validate_current_schema_proof_fields(
        value.inventory,
        value.storage,
        value.created_databases,
        value.cleaned_databases,
    )
    return value


def _current_schema_proof_payload(value: object) -> dict[str, object]:
    validated = _validated_current_schema_proof(value)
    return {
        "proofDatabase": validated.inventory.database,
        "proofInventoryHash": inventory_hash(validated.inventory),
        "createdDatabases": validated.created_databases,
        "cleanedDatabases": validated.cleaned_databases,
    }


def _validate_target_state(
    target: object,
    initialized: object,
    storage: object,
    current_schema_proof: object,
    *,
    expected_counts: tuple[tuple[str, int], ...] | None = None,
) -> DatabaseInventory:
    if type(target) is not DatabaseInventory:
        raise ValueError
    validate_database_role("new", target.database)
    expected_tables = tuple(sorted(created_table_names()))
    counts = expected_counts or _expected_row_counts()
    initialization = _initialization_payload(initialized)
    validated_storage = _validate_storage(storage)
    proof = _validated_current_schema_proof(current_schema_proof)
    proof_inventory = proof.inventory
    if (
        target.structural_fingerprint != proof_inventory.structural_fingerprint
        or target.schema_version != proof_inventory.schema_version
        or target.manifest_hash != proof_inventory.manifest_hash
        or target.table_names != proof_inventory.table_names
        or target.table_names != expected_tables
        or target.row_counts != counts
        or target.nonempty_table_count != sum(
            count > 0 for _, count in counts
        )
        or target.total_row_count != sum(count for _, count in counts)
        or initialization["databaseName"] != target.database
        or tuple(row.name for row in validated_storage) != expected_tables
    ):
        raise ValueError
    assert_storage_policy(validated_storage)
    return target


def _validate_storage(storage: object) -> tuple[TableStorage, ...]:
    if type(storage) is not tuple:
        raise ValueError
    for row in storage:
        if (
            type(row) is not TableStorage
            or type(row.name) is not str
            or not row.name.strip()
            or type(row.engine) is not str
            or not row.engine.strip()
            or type(row.collation) is not str
            or not row.collation.strip()
        ):
            raise ValueError
    return storage


@dataclass(frozen=True)
class _ResumeInitialization:
    database_name: str
    schema_version: str | None
    manifest_hash: str | None
    table_count: int


def _resume_initialization(inventory: DatabaseInventory) -> _ResumeInitialization:
    return _ResumeInitialization(
        database_name=inventory.database,
        schema_version=inventory.schema_version,
        manifest_hash=inventory.manifest_hash,
        table_count=len(inventory.table_names),
    )


def assert_new_database_ready(
    target: DatabaseInventory,
    initialized: object,
    official_data: object,
    storage: tuple[TableStorage, ...],
    current_schema_proof: CurrentSchemaProof,
) -> None:
    """Fail closed unless the target is exactly the approved product state."""

    try:
        _validate_target_state(
            target,
            initialized,
            storage,
            current_schema_proof,
        )
        _validated_official_data(official_data)
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


async def prepare_product_database(
    *,
    request: PreparationRequest,
    inventory: Callable[[str], object],
    create_backup: Callable[[DatabaseInventory, Path], object],
    restore_drill: Callable[[BackupReceipt, DatabaseInventory], object],
    current_schema_proof: Callable[[], object],
    new_database_boundary: Callable[[str], object],
    seed_assets: Callable[[str], object],
    seed_market: Callable[[str], object],
    read_storage: Callable[[str], object],
    audit_official_data: Callable[[str], object],
    smoke: Callable[[str], object],
) -> PreparationReceipt:
    """Prepare Stage A inside one trusted atomic new-database lifecycle.

    Task 5 must provide ``current_schema_proof`` as an isolated lifecycle that
    creates a unique, current-run-owned disposable proof database, initializes
    it to the current manifest, records its full inventory and storage, and
    always drops it before returning ``CurrentSchemaProof`` with an exact closed
    create/clean ledger. Cleanup failure must return no proof and fail the
    dependency. The proof lifecycle must never read from or write to the target.

    Task 5 must provide ``new_database_boundary`` as an async context manager
    backed by the MySQL exclusive lock. Its ``__aenter__`` atomically returns
    ``created`` or a preexisting inventory, cleans any create/enter failure,
    and its ``__aexit__`` retains a created target only after a successful
    body. Enter cleanup failures must use ``NewDatabaseBoundaryEnterFailure``;
    exit cleanup, commit, and lock-release failures must use
    ``NewDatabaseBoundaryExitFailure``. The boundary must never return or wrap
    the body primary in its exit envelope: it reports only its own lifecycle
    failures. The service presents body failures as a private marker, so the
    boundary must treat every non-``None`` body exception as a rollback signal
    without inspecting or returning it. It must never clean a preexisting
    target. No deletion authority crosses this service boundary.
    """

    try:
        if type(request) is not PreparationRequest:
            raise ValueError
        validate_database_role("legacy", request.legacy_database)
        validate_database_role("new", request.new_database)
    except BaseException as error:
        _raise_normalized(error, _REQUEST_ERROR)

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
            restore_evidence = canonical_hash(
                {
                    "restoreInventoryHash": inventory_hash(restore),
                    "createdDatabases": restore_value.created_databases,
                    "cleanedDatabases": restore_value.cleaned_databases,
                }
            )
        except BaseException as error:
            _raise_normalized(error, _RESTORE_ERROR)
        receipts.append(
            advance_receipt(
                receipts[-1],
                ReadinessState.RESTORE_DRILL_VERIFIED,
                restore_evidence,
            )
        )

        after = await _stage(_LEGACY_INVENTORY_ERROR, inventory, "legacy-after")
        try:
            if type(after) is not DatabaseInventory or after.database != request.legacy_database:
                raise ValueError
            assert_inventory_equal(before, after)
        except BaseException as error:
            _raise_normalized(error, _LEGACY_DRIFT_ERROR)

        proof_value = await _stage(
            _PROOF_ERROR, current_schema_proof
        )
        try:
            proof_payload = _current_schema_proof_payload(proof_value)
            proof = proof_value
        except BaseException as error:
            _raise_normalized(error, _PROOF_ERROR)

        try:
            boundary = new_database_boundary(request.new_database)
            if (
                not callable(getattr(type(boundary), "__aenter__", None))
                or not callable(getattr(type(boundary), "__aexit__", None))
            ):
                raise ValueError
        except BaseException as error:
            _raise_normalized(error, _INITIALIZE_ERROR)

        async with _normalized_database_boundary(boundary) as boundary_value:
            if type(boundary_value) is not NewDatabaseBoundaryState:
                raise _fixed(_INITIALIZE_ERROR)
            mode = boundary_value.mode
            seed_report_payload: dict[str, object] | None = None
            if mode == "created":
                initialized = boundary_value.initialized
                try:
                    initialization_payload = _initialization_payload(initialized)
                except BaseException as error:
                    _raise_normalized(error, _INITIALIZE_ERROR)

                assets = await _stage(
                    _ASSET_SEED_ERROR, seed_assets, request.new_database
                )
                market = await _stage(
                    _MARKET_SEED_ERROR, seed_market, request.new_database
                )
                try:
                    seed_report_payload = _validated_seed_payload(assets, market)
                    _validate_seed_mode(seed_report_payload, True)
                except BaseException as error:
                    _raise_normalized(error, _AUDIT_ERROR)

                target = await _stage(_TARGET_INVENTORY_ERROR, inventory, "new")
                storage = await _stage(
                    _AUDIT_ERROR, read_storage, request.new_database
                )
            else:
                target = boundary_value.inventory
                storage = await _stage(
                    _AUDIT_ERROR, read_storage, request.new_database
                )
                try:
                    initialized = _resume_initialization(target)  # type: ignore[arg-type]
                    _validate_target_state(
                        target,
                        initialized,
                        storage,
                        proof,
                    )
                    initialization_payload = _initialization_payload(initialized)
                except BaseException as error:
                    _raise_normalized(error, _AUDIT_ERROR)

            receipts.append(
                advance_receipt(
                    receipts[-1],
                    ReadinessState.NEW_DATABASE_INITIALIZED,
                    canonical_hash(
                        {
                            "initialization": initialization_payload,
                            "currentSchemaProof": proof_payload,
                        }
                    ),
                )
            )

            official_value = await _stage(
                _AUDIT_ERROR, audit_official_data, request.new_database
            )
            try:
                _validate_target_state(
                    target,
                    initialized,
                    storage,
                    proof,
                )
                official_payload = _validated_official_data(official_value)
            except BaseException as error:
                _raise_normalized(error, _AUDIT_ERROR)
            seed_evidence: dict[str, object] = {
                "mode": "created" if mode == "created" else "resume",
                "observed": official_payload,
            }
            if seed_report_payload is not None:
                seed_evidence["seedReports"] = seed_report_payload
            receipts.append(
                advance_receipt(
                    receipts[-1],
                    ReadinessState.OFFICIAL_DATA_SEEDED,
                    canonical_hash(seed_evidence),
                )
            )

            smoke_value = await _stage(_SMOKE_ERROR, smoke, request.new_database)
            smoke_result = _validate_smoke(smoke_value)
            if smoke_result.provider_calls != 0 or smoke_result.outbound_requests != 0:
                raise _fixed(_NETWORK_ERROR)

            receipts.append(
                advance_receipt(
                    receipts[-1],
                    ReadinessState.READINESS_VERIFIED,
                    inventory_hash(target),  # type: ignore[arg-type]
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
                new_inventory_hash=inventory_hash(target),  # type: ignore[arg-type]
                backup_sha256=backup.backup_sha256,
                style_count=official_payload["styleCount"],  # type: ignore[arg-type]
                experience_card_count=official_payload["cardCount"],  # type: ignore[arg-type]
                market_source_count=official_payload["marketSourceCount"],  # type: ignore[arg-type]
                receipts=tuple(receipts),
            )
        return result
    except BaseException as error:
        _raise_public(error)
