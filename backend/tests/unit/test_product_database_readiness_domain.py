from dataclasses import FrozenInstanceError, asdict, replace
import traceback

import pytest

from backend.domain.json_contracts import canonical_hash
from backend.domain.product_database_readiness import (
    LEGACY_DATABASE,
    MAX_CONTRACT_DEPTH,
    NEW_DATABASE,
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


ZERO_HASH = "0" * 64
A_HASH = "a" * 64
B_HASH = "b" * 64
C_HASH = "c" * 64


class StringSubclass(str):
    pass


class IntSubclass(int):
    pass


def inventory(database: str) -> DatabaseInventory:
    return DatabaseInventory(
        database=database,
        server_version="8.4.10",
        schema_version="writer-core-v1.13.0",
        manifest_hash="a" * 64,
        structural_fingerprint="b" * 64,
        table_names=("schema_metadata",),
        row_counts=(("schema_metadata", 1),),
        nonempty_table_count=1,
        total_row_count=1,
    )


def backup_receipt(**changes: object) -> BackupReceipt:
    values: dict[str, object] = {
        "state": ReadinessState.BACKUP_CREATED.value,
        "previous_receipt_hash": A_HASH,
        "source_database": LEGACY_DATABASE,
        "backup_filename": "phase7b-backup.sql",
        "backup_sha256": B_HASH,
        "backup_byte_length": 100,
        "client_version": "mysqldump  Ver 8.4.10",
        "source_inventory_hash": C_HASH,
    }
    values.update(changes)
    return BackupReceipt(**values)  # type: ignore[arg-type]


def receipt_chain(last_state: ReadinessState) -> tuple[StateReceipt, ...]:
    receipts: list[StateReceipt] = []
    for state in ReadinessState:
        receipts.append(advance_receipt(receipts[-1] if receipts else None, state, A_HASH))
        if state is last_state:
            return tuple(receipts)
    raise AssertionError("state not found")


def preparation_receipt(**changes: object) -> PreparationReceipt:
    receipts = receipt_chain(ReadinessState.AWAITING_CUTOVER_APPROVAL)
    values: dict[str, object] = {
        "state": ReadinessState.AWAITING_CUTOVER_APPROVAL.value,
        "previous_receipt_hash": canonical_receipt_hash(receipts[-1]),
        "legacy_database": LEGACY_DATABASE,
        "new_database": NEW_DATABASE,
        "legacy_inventory_hash": B_HASH,
        "new_inventory_hash": C_HASH,
        "backup_filename": "phase7b.sql",
        "backup_sha256": A_HASH,
        "backup_byte_length": 123,
        "style_count": 10,
        "experience_card_count": 64,
        "market_source_count": 2,
        "receipts": receipts,
    }
    values.update(changes)
    return PreparationReceipt(**values)  # type: ignore[arg-type]


def assert_contract_error(
    callable_: object,
    *args: object,
    message: str = "product database readiness contract is invalid",
    **kwargs: object,
) -> None:
    with pytest.raises(ProductDatabaseReadinessError) as captured:
        callable_(*args, **kwargs)  # type: ignore[operator]
    assert str(captured.value) == message


def test_database_roles_and_restore_names_are_closed():
    assert validate_database_role("legacy", LEGACY_DATABASE) == LEGACY_DATABASE
    assert validate_database_role("new", NEW_DATABASE) == NEW_DATABASE
    assert validate_restore_database(
        "novel_creator_phase7b_restore_0123456789abcdef0123456789abcdef"
    ).startswith("novel_creator_phase7b_restore_")
    for role, value in (("old", LEGACY_DATABASE), ("legacy", NEW_DATABASE), ("new", LEGACY_DATABASE)):
        assert_contract_error(validate_database_role, role, value, message="database target is invalid")
    for unsafe_role in ([], StringSubclass("legacy")):
        assert_contract_error(
            validate_database_role,
            unsafe_role,
            LEGACY_DATABASE,
            message="database target is invalid",
        )
    for unsafe in (
        LEGACY_DATABASE,
        NEW_DATABASE,
        "novel_creator_phase7b_restore_bad",
        "novel_creator_phase7b_restore_0123456789ABCDEF0123456789ABCDEF",
        "x",
        1,
    ):
        assert_contract_error(validate_restore_database, unsafe, message="database target is invalid")


def test_inventory_hash_is_canonical_and_database_bound():
    source = inventory(LEGACY_DATABASE)
    assert inventory_hash(source) == canonical_hash(asdict(source))
    assert inventory_hash(source) == inventory_hash(source)
    assert inventory_hash(source) != inventory_hash(replace(source, database=NEW_DATABASE))


def test_state_order_cannot_skip_cutover_approval():
    assert tuple(ReadinessState) == (
        ReadinessState.INVENTORY_VERIFIED,
        ReadinessState.BACKUP_CREATED,
        ReadinessState.RESTORE_DRILL_VERIFIED,
        ReadinessState.NEW_DATABASE_INITIALIZED,
        ReadinessState.OFFICIAL_DATA_SEEDED,
        ReadinessState.READINESS_VERIFIED,
        ReadinessState.AWAITING_CUTOVER_APPROVAL,
        ReadinessState.CONFIGURATION_SWITCHED,
        ReadinessState.CUTOVER_VERIFIED,
        ReadinessState.LEGACY_RETAINED,
    )


def test_contracts_are_frozen_and_valid_receipts_hash_canonically():
    receipt = backup_receipt()
    assert canonical_receipt_hash(receipt) == canonical_hash(asdict(receipt))
    with pytest.raises(FrozenInstanceError):
        receipt.backup_byte_length = 101  # type: ignore[misc]
    assert canonical_receipt_hash(asdict(receipt)) == canonical_receipt_hash(receipt)
    assert canonical_receipt_hash(preparation_receipt()) == canonical_hash(asdict(preparation_receipt()))


@pytest.mark.parametrize(
    ("changes"),
    (
        {"manifest_hash": "A" * 64},
        {"structural_fingerprint": "g" * 64},
        {"table_names": ("z", "a"), "row_counts": (("a", 0), ("z", 0))},
        {"table_names": ("a", "a"), "row_counts": (("a", 0), ("a", 0))},
        {"table_names": ("unsafe-name",), "row_counts": (("unsafe-name", 0),)},
        {"table_names": ("a",), "row_counts": (("b", 0),)},
        {"table_names": ("a", "b"), "row_counts": (("b", 0), ("a", 0))},
        {"row_counts": (("schema_metadata", -1),), "nonempty_table_count": 0, "total_row_count": -1},
        {"row_counts": (("schema_metadata", True),), "total_row_count": 1},
        {"nonempty_table_count": True},
        {"nonempty_table_count": 0},
        {"total_row_count": 2},
    ),
)
def test_inventory_rejects_malformed_hashes_tables_and_counts(changes: dict[str, object]):
    values = asdict(inventory(LEGACY_DATABASE))
    values.update(changes)
    assert_contract_error(DatabaseInventory, **values)


@pytest.mark.parametrize(
    "changes",
    (
        {"state": ReadinessState.INVENTORY_VERIFIED.value},
        {"state": ReadinessState.BACKUP_CREATED},
        {"previous_receipt_hash": "A" * 64},
        {"source_database": NEW_DATABASE},
        {"source_database": StringSubclass(LEGACY_DATABASE)},
        {"backup_filename": "folder/backup.sql"},
        {"backup_filename": "folder\\backup.sql"},
        {"backup_filename": "C:backup.sql"},
        {"backup_filename": "C:\\backup.sql"},
        {"backup_filename": "\\\\server\\share\\backup.sql"},
        {"backup_filename": ".."},
        {"backup_sha256": "short"},
        {"backup_byte_length": -1},
        {"backup_byte_length": True},
        {"source_inventory_hash": "g" * 64},
    ),
)
def test_backup_receipt_rejects_invalid_state_binding_filename_hash_or_count(changes: dict[str, object]):
    assert_contract_error(backup_receipt, **changes)


@pytest.mark.parametrize(
    "filename",
    (
        "NUL",
        "CON.txt",
        "prn.SQL",
        "aux.backup",
        "com1.sql",
        "LPT9.dump",
        "COM¹.txt",
        "LPT³.log",
        "CONIN$.txt",
        "CONOUT$",
        "backup.sql.",
        "backup.sql ",
        "bad\0.sql",
        "bad\n.sql",
        "bad<name.sql",
        "bad>name.sql",
        'bad"name.sql',
        "bad|name.sql",
        "bad?name.sql",
        "bad*name.sql",
        "\ud800.sql",
        "\udfff.sql",
        "a" * 252 + ".sql",
        "😀" * 63 + ".sql",
        "😀" * 125 + ".sql",
    ),
)
def test_backup_filename_rejects_nonportable_basenames_without_echo(filename: str):
    with pytest.raises(ProductDatabaseReadinessError) as captured:
        backup_receipt(backup_filename=filename)
    assert str(captured.value) == "product database readiness contract is invalid"
    assert filename not in str(captured.value)


def test_backup_filename_accepts_simple_ascii_and_unicode_basenames():
    for filename in (
        "phase7b-backup.sql",
        "阶段七备份.sql",
        "a" * 251 + ".sql",
    ):
        receipt = backup_receipt(backup_filename=filename)
        assert receipt.backup_filename == filename
        assert len(canonical_receipt_hash(receipt)) == 64


def test_backup_filename_accepts_exactly_255_utf8_bytes_and_hashes():
    filename = "😀" * 62 + "abc.sql"
    assert len(filename.encode("utf-8")) == 255
    receipt = backup_receipt(backup_filename=filename)
    assert receipt.backup_filename == filename
    assert len(canonical_receipt_hash(receipt)) == 64


def test_state_receipt_rejects_invalid_states_hashes_and_cross_database_replay():
    valid = receipt_chain(ReadinessState.INVENTORY_VERIFIED)[0]
    for changes in (
        {"state": "unknown"},
        {"state": ReadinessState.INVENTORY_VERIFIED},
        {"previous_receipt_hash": "A" * 64},
        {"state": ReadinessState.BACKUP_CREATED.value, "previous_receipt_hash": ZERO_HASH},
        {"legacy_database": NEW_DATABASE},
        {"legacy_database": StringSubclass(LEGACY_DATABASE)},
        {"new_database": LEGACY_DATABASE},
        {"new_database": StringSubclass(NEW_DATABASE)},
        {"evidence_hash": "bad"},
    ):
        assert_contract_error(StateReceipt, **(asdict(valid) | changes))


def test_advance_receipt_requires_exact_sequence_and_canonical_link():
    first = advance_receipt(None, ReadinessState.INVENTORY_VERIFIED, A_HASH)
    assert first.previous_receipt_hash == ZERO_HASH
    second = advance_receipt(first, ReadinessState.BACKUP_CREATED, B_HASH)
    assert second.previous_receipt_hash == canonical_receipt_hash(first)
    for previous, state in (
        (None, ReadinessState.BACKUP_CREATED),
        (first, ReadinessState.INVENTORY_VERIFIED),
        (first, ReadinessState.RESTORE_DRILL_VERIFIED),
        (receipt_chain(ReadinessState.LEGACY_RETAINED)[-1], ReadinessState.LEGACY_RETAINED),
    ):
        assert_contract_error(
            advance_receipt,
            previous,
            state,
            A_HASH,
            message="readiness state sequence is invalid",
        )
    assert_contract_error(
        advance_receipt,
        first,
        "backup_created",
        A_HASH,
        message="readiness state sequence is invalid",
    )


def test_preparation_receipt_requires_exact_database_bound_chain_and_counts():
    valid = preparation_receipt()
    assert valid.receipts[-1].state == ReadinessState.AWAITING_CUTOVER_APPROVAL.value
    assert valid.backup_filename == "phase7b.sql"
    assert valid.backup_byte_length == 123
    for changes in (
        {"state": ReadinessState.READINESS_VERIFIED.value},
        {"state": ReadinessState.AWAITING_CUTOVER_APPROVAL},
        {"previous_receipt_hash": A_HASH},
        {"legacy_database": NEW_DATABASE},
        {"legacy_database": StringSubclass(LEGACY_DATABASE)},
        {"new_database": LEGACY_DATABASE},
        {"new_database": StringSubclass(NEW_DATABASE)},
        {"backup_sha256": "short"},
        {"backup_byte_length": -1},
        {"backup_byte_length": True},
        {"backup_byte_length": IntSubclass(123)},
        {"style_count": -1},
        {"experience_card_count": True},
        {"market_source_count": -1},
        {"receipts": valid.receipts[:-1]},
        {"receipts": (valid.receipts[0], valid.receipts[2])},
    ):
        assert_contract_error(PreparationReceipt, **(vars(valid) | changes))


@pytest.mark.parametrize(
    "filename",
    (
        "folder/phase7b.sql",
        "folder\\phase7b.sql",
        ".",
        "..",
        "phase7b.sql\0",
        "phase7b.sql.",
        "phase7b.sql ",
        "CON.sql",
        "prn.SQL",
        "aux.backup.sql",
        "com1.sql",
        "LPT9.sql",
        "phase7b.dump",
        "phase7b.SQL",
        "phase7b",
        StringSubclass("phase7b.sql"),
    ),
)
def test_preparation_receipt_rejects_unsafe_backup_filename(filename: object):
    assert_contract_error(preparation_receipt, backup_filename=filename)


def test_receipt_mapping_rejects_unknown_and_missing_fields():
    payload = asdict(backup_receipt())
    assert_contract_error(canonical_receipt_hash, payload | {"extra": "value"})
    payload.pop("client_version")
    assert_contract_error(canonical_receipt_hash, payload)
    assert_contract_error(canonical_receipt_hash, {"unrecognized": "mapping"})


def test_hashing_accepts_closed_mappings_for_every_contract_type():
    state = receipt_chain(ReadinessState.INVENTORY_VERIFIED)[0]
    preparation = preparation_receipt()
    for contract in (inventory(LEGACY_DATABASE), backup_receipt(), state, preparation):
        assert canonical_receipt_hash(asdict(contract)) == canonical_receipt_hash(contract)


def test_nested_preparation_mapping_rejects_unknown_state_receipt_fields():
    payload = asdict(preparation_receipt())
    nested = dict(payload["receipts"][0])
    nested["extra"] = "value"
    payload["receipts"] = (nested,) + payload["receipts"][1:]
    assert_contract_error(canonical_receipt_hash, payload)


def test_hashing_revalidates_a_corrupted_frozen_contract():
    receipt = backup_receipt()
    object.__setattr__(receipt, "backup_sha256", "invalid")
    assert_contract_error(canonical_receipt_hash, receipt)


def test_hashing_rejects_a_corrupted_contract_with_a_deleted_field():
    receipt = backup_receipt()
    object.__delattr__(receipt, "backup_sha256")
    assert_contract_error(canonical_receipt_hash, receipt)


def test_hashing_rejects_a_corrupted_contract_with_a_benign_extra_field():
    receipt = backup_receipt()
    object.__setattr__(receipt, "unexpected", "value")
    assert_contract_error(canonical_receipt_hash, receipt)


def test_hashing_rejects_a_corrupted_contract_with_a_sensitive_extra_field():
    sensitive = "do-not-leak-this-value"
    receipt = backup_receipt()
    object.__setattr__(receipt, "password", sensitive)
    with pytest.raises(ProductDatabaseReadinessError) as captured:
        canonical_receipt_hash(receipt)
    assert str(captured.value) == "receipt contains prohibited data"
    assert sensitive not in str(captured.value)


def test_hashing_rejects_a_dataclass_type_with_a_fixed_error():
    assert_contract_error(canonical_receipt_hash, DatabaseInventory)


def test_advance_rejects_a_corrupted_previous_receipt_with_sequence_error():
    previous = receipt_chain(ReadinessState.INVENTORY_VERIFIED)[0]
    object.__setattr__(previous, "state", "corrupt-state")
    assert_contract_error(
        advance_receipt,
        previous,
        ReadinessState.BACKUP_CREATED,
        A_HASH,
        message="readiness state sequence is invalid",
    )


def test_advance_rejects_a_previous_receipt_with_a_deleted_field():
    previous = receipt_chain(ReadinessState.INVENTORY_VERIFIED)[0]
    object.__delattr__(previous, "evidence_hash")
    assert_contract_error(
        advance_receipt,
        previous,
        ReadinessState.BACKUP_CREATED,
        A_HASH,
        message="readiness state sequence is invalid",
    )


@pytest.mark.parametrize("cycle_kind", ("dict", "list", "mutual"))
def test_hashing_rejects_recursive_container_cycles_with_a_fixed_error(cycle_kind: str):
    payload = asdict(backup_receipt())
    if cycle_kind == "dict":
        recursive: object = {}
        recursive["child"] = recursive  # type: ignore[index]
    elif cycle_kind == "list":
        recursive = []
        recursive.append(recursive)  # type: ignore[union-attr]
    else:
        left: dict[str, object] = {}
        right: list[object] = [left]
        left["child"] = right
        recursive = left
    payload["client_version"] = recursive
    assert_contract_error(canonical_receipt_hash, payload)


def nested_lists(depth: int, leaf: object) -> object:
    value = leaf
    for _ in range(depth):
        value = [value]
    return value


def test_hashing_traverses_the_maximum_contract_depth():
    payload = asdict(backup_receipt())
    payload["client_version"] = nested_lists(
        MAX_CONTRACT_DEPTH - 1,
        {"password": "do-not-leak-this-value"},
    )
    with pytest.raises(ProductDatabaseReadinessError) as captured:
        canonical_receipt_hash(payload)
    assert str(captured.value) == "receipt contains prohibited data"


def test_hashing_allows_repeated_noncyclic_shared_containers():
    empty = DatabaseInventory(
        database=LEGACY_DATABASE,
        server_version="8.4.10",
        schema_version=None,
        manifest_hash=None,
        structural_fingerprint=B_HASH,
        table_names=(),
        row_counts=(),
        nonempty_table_count=0,
        total_row_count=0,
    )
    payload = asdict(empty)
    shared: list[object] = []
    payload["table_names"] = shared
    payload["row_counts"] = shared
    assert canonical_receipt_hash(payload) == canonical_receipt_hash(empty)


@pytest.mark.parametrize("depth", (MAX_CONTRACT_DEPTH, 1200))
def test_hashing_rejects_excessive_depth_without_recursion_error(depth: int):
    payload = asdict(backup_receipt())
    payload["client_version"] = nested_lists(
        depth,
        {"password": "do-not-leak-this-value"},
    )
    with pytest.raises(ProductDatabaseReadinessError) as captured:
        canonical_receipt_hash(payload)
    assert str(captured.value) == "product database readiness contract is invalid"
    assert not isinstance(captured.value, RecursionError)
    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__


@pytest.mark.parametrize("key", ("password", "Secret", "connection_dsn", "requestBody", "raw_sql", "Provider"))
def test_hashing_rejects_secret_bearing_keys_recursively_without_echo(key: str):
    sensitive = "do-not-leak-this-value"
    payload = asdict(backup_receipt())
    payload["nested"] = [{key: sensitive}]
    with pytest.raises(ProductDatabaseReadinessError) as captured:
        canonical_receipt_hash(payload)
    assert str(captured.value) == "receipt contains prohibited data"
    assert key not in str(captured.value)
    assert sensitive not in str(captured.value)


@pytest.mark.parametrize("unsafe", ({1, 2}, float("nan"), object()))
def test_hashing_rejects_noncanonical_data_with_a_fixed_error(unsafe: object):
    payload = asdict(backup_receipt())
    payload["client_version"] = unsafe
    with pytest.raises(ProductDatabaseReadinessError) as captured:
        canonical_receipt_hash(payload)
    assert str(captured.value) == "product database readiness contract is invalid"
    assert "object" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None or captured.value.__suppress_context__


def test_hashing_suppresses_invalid_unicode_serialization_context():
    payload = asdict(backup_receipt())
    payload["client_version"] = "\ud800"
    with pytest.raises(ProductDatabaseReadinessError) as captured:
        canonical_receipt_hash(payload)
    assert str(captured.value) == "product database readiness contract is invalid"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None or captured.value.__suppress_context__


@pytest.mark.parametrize(
    ("callable_", "message"),
    (
        (lambda: validate_database_role("legacy", NEW_DATABASE), "database target is invalid"),
        (lambda: validate_restore_database(LEGACY_DATABASE), "database target is invalid"),
        (lambda: backup_receipt(backup_sha256="bad"), "product database readiness contract is invalid"),
        (
            lambda: canonical_receipt_hash(asdict(backup_receipt()) | {"password": "hidden"}),
            "receipt contains prohibited data",
        ),
        (
            lambda: advance_receipt(None, ReadinessState.BACKUP_CREATED, A_HASH),
            "readiness state sequence is invalid",
        ),
    ),
)
def test_public_errors_suppress_ambient_sensitive_exception_context(callable_: object, message: str):
    sentinel = "password=hidden dsn=mysql://private"
    try:
        raise RuntimeError(sentinel)
    except RuntimeError:
        with pytest.raises(ProductDatabaseReadinessError) as captured:
            callable_()  # type: ignore[operator]
    assert str(captured.value) == message
    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__
    assert sentinel not in "".join(traceback.format_exception(captured.value))
