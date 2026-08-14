"""Immutable, secret-free contracts for product database readiness evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, is_dataclass
from enum import StrEnum
import re
from typing import Mapping

from backend.domain.json_contracts import canonical_hash


LEGACY_DATABASE = "novel_creator"
NEW_DATABASE = "novel_creator_v113"
RESTORE_DATABASE_PATTERN = re.compile(
    r"^novel_creator_phase7b_restore_[0-9a-f]{32}$"
)

_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PROHIBITED_KEY_PATTERN = re.compile(r"password|secret|dsn|body|sql|provider", re.IGNORECASE)
_CONTRACT_ERROR = "readiness contract is invalid"
_PROHIBITED_DATA_ERROR = "receipt contains prohibited data"
_SEQUENCE_ERROR = "readiness state sequence is invalid"


class ProductDatabaseReadinessError(RuntimeError):
    """A fixed, public-safe failure in a readiness domain contract."""


class ReadinessState(StrEnum):
    INVENTORY_VERIFIED = "inventory_verified"
    BACKUP_CREATED = "backup_created"
    RESTORE_DRILL_VERIFIED = "restore_drill_verified"
    NEW_DATABASE_INITIALIZED = "new_database_initialized"
    OFFICIAL_DATA_SEEDED = "official_data_seeded"
    READINESS_VERIFIED = "readiness_verified"
    AWAITING_CUTOVER_APPROVAL = "awaiting_cutover_approval"
    CONFIGURATION_SWITCHED = "configuration_switched"
    CUTOVER_VERIFIED = "cutover_verified"
    LEGACY_RETAINED = "legacy_retained"


def _invalid() -> None:
    raise ProductDatabaseReadinessError(_CONTRACT_ERROR)


def _is_hash(value: object) -> bool:
    return type(value) is str and _HASH_PATTERN.fullmatch(value) is not None


def _require_hash(value: object, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not _is_hash(value):
        _invalid()


def _require_nonnegative_int(value: object) -> None:
    if type(value) is not int or value < 0:
        _invalid()


def _is_database_name(value: object) -> bool:
    return type(value) is str and (
        value in (LEGACY_DATABASE, NEW_DATABASE)
        or RESTORE_DATABASE_PATTERN.fullmatch(value) is not None
    )


@dataclass(frozen=True)
class DatabaseInventory:
    database: str
    server_version: str
    schema_version: str | None
    manifest_hash: str | None
    structural_fingerprint: str
    table_names: tuple[str, ...]
    row_counts: tuple[tuple[str, int], ...]
    nonempty_table_count: int
    total_row_count: int

    def __post_init__(self) -> None:
        if not _is_database_name(self.database):
            _invalid()
        if type(self.server_version) is not str or not self.server_version:
            _invalid()
        if self.schema_version is not None and type(self.schema_version) is not str:
            _invalid()
        _require_hash(self.manifest_hash, optional=True)
        _require_hash(self.structural_fingerprint)
        if type(self.table_names) is not tuple or type(self.row_counts) is not tuple:
            _invalid()
        if any(
            type(name) is not str or _IDENTIFIER_PATTERN.fullmatch(name) is None
            for name in self.table_names
        ):
            _invalid()
        if self.table_names != tuple(sorted(set(self.table_names))):
            _invalid()
        row_names: list[str] = []
        row_values: list[int] = []
        for entry in self.row_counts:
            if type(entry) is not tuple or len(entry) != 2:
                _invalid()
            name, count = entry
            if type(name) is not str or _IDENTIFIER_PATTERN.fullmatch(name) is None:
                _invalid()
            _require_nonnegative_int(count)
            row_names.append(name)
            row_values.append(count)
        if tuple(row_names) != tuple(sorted(set(row_names))):
            _invalid()
        if tuple(row_names) != self.table_names:
            _invalid()
        _require_nonnegative_int(self.nonempty_table_count)
        _require_nonnegative_int(self.total_row_count)
        if self.nonempty_table_count != sum(count > 0 for count in row_values):
            _invalid()
        if self.total_row_count != sum(row_values):
            _invalid()


@dataclass(frozen=True)
class BackupReceipt:
    state: str
    previous_receipt_hash: str
    source_database: str
    backup_filename: str
    backup_sha256: str
    backup_byte_length: int
    client_version: str
    source_inventory_hash: str

    def __post_init__(self) -> None:
        if type(self.state) is not str or self.state != ReadinessState.BACKUP_CREATED.value:
            _invalid()
        _require_hash(self.previous_receipt_hash)
        if type(self.source_database) is not str or self.source_database != LEGACY_DATABASE:
            _invalid()
        if (
            type(self.backup_filename) is not str
            or not self.backup_filename
            or self.backup_filename in (".", "..")
            or "/" in self.backup_filename
            or "\\" in self.backup_filename
        ):
            _invalid()
        _require_hash(self.backup_sha256)
        _require_nonnegative_int(self.backup_byte_length)
        if type(self.client_version) is not str or not self.client_version:
            _invalid()
        _require_hash(self.source_inventory_hash)


@dataclass(frozen=True)
class StateReceipt:
    state: str
    previous_receipt_hash: str
    legacy_database: str
    new_database: str
    evidence_hash: str

    def __post_init__(self) -> None:
        if type(self.state) is not str:
            _invalid()
        try:
            parsed_state = ReadinessState(self.state)
        except (TypeError, ValueError):
            _invalid()
            return
        _require_hash(self.previous_receipt_hash)
        is_first_state = parsed_state is ReadinessState.INVENTORY_VERIFIED
        has_initial_link = self.previous_receipt_hash == "0" * 64
        if is_first_state != has_initial_link:
            _invalid()
        if (
            type(self.legacy_database) is not str
            or self.legacy_database != LEGACY_DATABASE
            or type(self.new_database) is not str
            or self.new_database != NEW_DATABASE
        ):
            _invalid()
        _require_hash(self.evidence_hash)


@dataclass(frozen=True)
class PreparationReceipt:
    state: str
    previous_receipt_hash: str
    legacy_database: str
    new_database: str
    legacy_inventory_hash: str
    new_inventory_hash: str
    backup_sha256: str
    style_count: int
    experience_card_count: int
    market_source_count: int
    receipts: tuple[StateReceipt, ...]

    def __post_init__(self) -> None:
        if type(self.state) is not str or self.state != ReadinessState.AWAITING_CUTOVER_APPROVAL.value:
            _invalid()
        _require_hash(self.previous_receipt_hash)
        if (
            type(self.legacy_database) is not str
            or self.legacy_database != LEGACY_DATABASE
            or type(self.new_database) is not str
            or self.new_database != NEW_DATABASE
        ):
            _invalid()
        _require_hash(self.legacy_inventory_hash)
        _require_hash(self.new_inventory_hash)
        _require_hash(self.backup_sha256)
        for count in (self.style_count, self.experience_card_count, self.market_source_count):
            _require_nonnegative_int(count)
        if type(self.receipts) is not tuple:
            _invalid()
        expected_states = tuple(ReadinessState)[: tuple(ReadinessState).index(ReadinessState.AWAITING_CUTOVER_APPROVAL) + 1]
        if len(self.receipts) != len(expected_states):
            _invalid()
        previous: StateReceipt | None = None
        for receipt, expected_state in zip(self.receipts, expected_states, strict=True):
            if type(receipt) is not StateReceipt or receipt.state != expected_state.value:
                _invalid()
            expected_hash = "0" * 64 if previous is None else canonical_receipt_hash(previous)
            if receipt.previous_receipt_hash != expected_hash:
                _invalid()
            previous = receipt
        if previous is None or self.previous_receipt_hash != canonical_receipt_hash(previous):
            _invalid()


def validate_database_role(role: str, value: str) -> str:
    """Return a database name only when it matches its immutable role."""

    if type(role) is not str:
        raise ProductDatabaseReadinessError("database target is invalid")
    expected = {"legacy": LEGACY_DATABASE, "new": NEW_DATABASE}.get(role)
    if expected is None or type(value) is not str or value != expected:
        raise ProductDatabaseReadinessError("database target is invalid")
    return value


def validate_restore_database(value: str) -> str:
    """Accept only a Phase 7B-owned random restore database name."""

    if type(value) is not str or RESTORE_DATABASE_PATTERN.fullmatch(value) is None:
        raise ProductDatabaseReadinessError("database target is invalid")
    return value


def _reject_prohibited_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if type(key) is not str:
                _invalid()
            if _PROHIBITED_KEY_PATTERN.search(key) is not None:
                raise ProductDatabaseReadinessError(_PROHIBITED_DATA_ERROR)
            _reject_prohibited_keys(nested)
    elif isinstance(value, (tuple, list)):
        for nested in value:
            _reject_prohibited_keys(nested)
    elif not isinstance(value, type) and is_dataclass(value):
        for field in fields(value):
            if _PROHIBITED_KEY_PATTERN.search(field.name) is not None:
                raise ProductDatabaseReadinessError(_PROHIBITED_DATA_ERROR)
            _reject_prohibited_keys(getattr(value, field.name))


def _mapping_to_contract(value: Mapping[str, object]) -> object:
    keys = frozenset(value)
    contract_types = (DatabaseInventory, BackupReceipt, StateReceipt, PreparationReceipt)
    for contract_type in contract_types:
        expected = frozenset(field.name for field in fields(contract_type))
        if keys != expected:
            continue
        payload = dict(value)
        if contract_type is DatabaseInventory:
            table_names = payload.get("table_names")
            row_counts = payload.get("row_counts")
            if type(table_names) is list:
                payload["table_names"] = tuple(table_names)
            if type(row_counts) in (list, tuple):
                payload["row_counts"] = tuple(
                    tuple(entry) if type(entry) is list else entry for entry in row_counts
                )
        elif contract_type is PreparationReceipt:
            raw_receipts = payload.get("receipts")
            if type(raw_receipts) not in (tuple, list):
                _invalid()
            converted: list[StateReceipt] = []
            for raw_receipt in raw_receipts:
                if type(raw_receipt) is StateReceipt:
                    converted.append(raw_receipt)
                elif isinstance(raw_receipt, Mapping):
                    converted_receipt = _mapping_to_contract(raw_receipt)
                    if type(converted_receipt) is not StateReceipt:
                        _invalid()
                    converted.append(converted_receipt)
                else:
                    _invalid()
            payload["receipts"] = tuple(converted)
        try:
            return contract_type(**payload)
        except ProductDatabaseReadinessError:
            raise
        except (TypeError, ValueError):
            _invalid()
    _invalid()


def _contract_payload(value: Mapping[str, object] | object) -> dict[str, object]:
    _reject_prohibited_keys(value)
    if isinstance(value, Mapping):
        validated = _mapping_to_contract(value)
    elif is_dataclass(value) and type(value) in (
        DatabaseInventory,
        BackupReceipt,
        StateReceipt,
        PreparationReceipt,
    ):
        validated = _mapping_to_contract(asdict(value))
    else:
        _invalid()
    payload = asdict(validated)  # type: ignore[arg-type]
    _reject_prohibited_keys(payload)
    return payload


def canonical_receipt_hash(value: Mapping[str, object] | object) -> str:
    """Hash a validated receipt using the repository canonical JSON contract."""

    payload = _contract_payload(value)
    try:
        return canonical_hash(payload)
    except (TypeError, ValueError, OverflowError):
        _invalid()


def inventory_hash(value: DatabaseInventory) -> str:
    """Return the canonical, database-bound inventory digest."""

    if type(value) is not DatabaseInventory:
        _invalid()
    return canonical_receipt_hash(value)


def advance_receipt(
    previous: StateReceipt | None,
    state: ReadinessState,
    evidence_hash: str,
) -> StateReceipt:
    """Advance exactly one state and bind the prior canonical receipt hash."""

    states = tuple(ReadinessState)
    if type(state) is not ReadinessState:
        raise ProductDatabaseReadinessError(_SEQUENCE_ERROR)
    if previous is not None and type(previous) is not StateReceipt:
        raise ProductDatabaseReadinessError(_SEQUENCE_ERROR)
    previous_hash: str | None = None
    if previous is None:
        expected_index = 0
    else:
        try:
            previous_hash = canonical_receipt_hash(previous)
            expected_index = states.index(ReadinessState(previous.state)) + 1
        except (ProductDatabaseReadinessError, TypeError, ValueError):
            raise ProductDatabaseReadinessError(_SEQUENCE_ERROR) from None
    if expected_index >= len(states) or states[expected_index] is not state:
        raise ProductDatabaseReadinessError(_SEQUENCE_ERROR)
    return StateReceipt(
        state=state.value,
        previous_receipt_hash="0" * 64 if previous_hash is None else previous_hash,
        legacy_database=LEGACY_DATABASE,
        new_database=NEW_DATABASE,
        evidence_hash=evidence_hash,
    )
