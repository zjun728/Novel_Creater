from __future__ import annotations

from pathlib import Path
from dataclasses import asdict
from contextlib import contextmanager
import json

import pytest

from backend.domain.product_database_readiness import (
    DatabaseInventory,
    BackupReceipt,
    LEGACY_DATABASE,
    NEW_DATABASE,
    PreparationReceipt,
    ReadinessState,
    advance_receipt,
    canonical_receipt_hash,
    inventory_hash,
)
from backend.domain.json_contracts import canonical_json
from backend.schema_manifest import created_table_names, manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from backend.scripts.prepare_product_database import (
    ProductDatabasePreparationCommandError,
    PreparationCommandDependencies,
    _default_transaction_scope,
    _default_connection_scope,
    create_current_schema_proof,
    new_database_boundary,
    publish_readiness_receipt,
    main,
    run_cli,
)
from backend.services.product_database_inventory import TableStorage
from backend.services.product_database_readiness import (
    NewDatabaseBoundaryEnterFailure,
    NewDatabaseBoundaryExitFailure,
    NewDatabaseBoundaryState,
)


def _arguments(tmp_path: Path) -> list[str]:
    external = Path(tmp_path.anchor) / "phase7b-external" / tmp_path.name
    return [
        "--legacy-database",
        LEGACY_DATABASE,
        "--new-database",
        NEW_DATABASE,
        "--backup-dir",
        str(external / "backups"),
        "--mysqldump",
        str(external / "mysql-8.4" / "mysqldump.exe"),
        "--mysql",
        str(external / "mysql-8.4" / "mysql.exe"),
    ]


class ForbiddenDependencies:
    def __getattribute__(self, name: str) -> object:
        if name.startswith("__"):
            return super().__getattribute__(name)
        raise AssertionError(f"preview accessed dependency {name}")


@pytest.mark.asyncio
async def test_default_mode_is_exact_preview_with_zero_dependency_calls(
    tmp_path: Path,
) -> None:
    lines: list[str] = []

    status = await run_cli(
        _arguments(tmp_path),
        dependencies=ForbiddenDependencies(),
        output=lines.append,
    )

    assert status == 0
    assert lines == [
        "mode=preview",
        "legacy_database=novel_creator",
        "new_database=novel_creator_v113",
        "stage=approval-required",
    ]
    rendered = "\n".join(lines)
    assert str(tmp_path) not in rendered
    assert "mysqldump" not in rendered
    assert "mysql.exe" not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ([], "product database preparation approval is invalid"),
        (
            [
                "--confirm-legacy",
                "wrong",
                "--confirm-new",
                NEW_DATABASE,
                "--confirm-prepare",
                "PREPARE-PHASE7B",
            ],
            "product database preparation approval is invalid",
        ),
        (
            [
                "--confirm-legacy",
                LEGACY_DATABASE,
                "--confirm-new",
                "wrong",
                "--confirm-prepare",
                "PREPARE-PHASE7B",
            ],
            "product database preparation approval is invalid",
        ),
        (
            [
                "--confirm-legacy",
                LEGACY_DATABASE,
                "--confirm-new",
                NEW_DATABASE,
                "--confirm-prepare",
                "wrong",
            ],
            "product database preparation approval is invalid",
        ),
    ],
)
async def test_execute_requires_all_exact_confirmations_before_dependencies(
    tmp_path: Path,
    extra: list[str],
    expected: str,
) -> None:
    with pytest.raises(ProductDatabasePreparationCommandError) as raised:
        await run_cli(
            [*_arguments(tmp_path), "--execute", *extra],
            dependencies=ForbiddenDependencies(),
        )

    assert str(raised.value) == expected
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "replace_index,value",
    [
        (1, "novel_creator_v113"),
        (3, "novel_creator"),
        (5, "relative/backups"),
        (7, "mysqldump.exe"),
        (9, "mysql.exe"),
    ],
)
async def test_preview_rejects_unsafe_names_and_relative_paths_without_dependencies(
    tmp_path: Path,
    replace_index: int,
    value: str,
) -> None:
    argv = _arguments(tmp_path)
    argv[replace_index] = value

    with pytest.raises(ProductDatabasePreparationCommandError) as raised:
        await run_cli(argv, dependencies=ForbiddenDependencies())

    assert str(raised.value) == "product database preparation arguments are invalid"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def _empty_inventory(database: str) -> DatabaseInventory:
    return DatabaseInventory(
        database=database,
        server_version="8.4.10",
        schema_version=None,
        manifest_hash=None,
        structural_fingerprint="1" * 64,
        table_names=(),
        row_counts=(),
        nonempty_table_count=0,
        total_row_count=0,
    )


class DatabaseExistsError(RuntimeError):
    errno = 1007


class BoundarySession:
    def __init__(
        self,
        calls: list[object],
        *,
        create_error: BaseException | None = None,
        drop_error: BaseException | None = None,
        release_error: BaseException | None = None,
        commit_error: BaseException | None = None,
    ) -> None:
        self.calls = calls
        self.create_error = create_error
        self.drop_error = drop_error
        self.release_error = release_error
        self.commit_error = commit_error

    async def fetchone(self, sql: str, params: tuple[object, ...] = ()) -> dict:
        self.calls.append(("fetchone", sql, params))
        if sql.startswith("SELECT GET_LOCK"):
            return {"acquired": 1}
        if sql.startswith("SELECT RELEASE_LOCK"):
            if self.release_error is not None:
                raise self.release_error
            return {"released": 1}
        raise AssertionError(sql)

    async def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.calls.append(("execute", sql, params))
        if sql.startswith("CREATE DATABASE") and self.create_error is not None:
            raise self.create_error
        if sql.startswith("DROP DATABASE") and self.drop_error is not None:
            raise self.drop_error
        if sql == "COMMIT" and self.commit_error is not None:
            raise self.commit_error

    async def close(self) -> None:
        self.calls.append("close")


async def _factory_for(session: BoundarySession) -> BoundarySession:
    session.calls.append("connect")
    return session


@pytest.mark.asyncio
async def test_new_database_boundary_holds_lock_and_retains_only_successful_create() -> None:
    calls: list[object] = []
    session = BoundarySession(calls)

    async def initialize(
        observed: object, database: str, confirmation: str, timestamp: int
    ) -> object:
        calls.append(("initialize", observed, database, confirmation, timestamp))
        return {"initialized": database}

    boundary = new_database_boundary(
        NEW_DATABASE,
        session_factory=lambda: _factory_for(session),
        initialize=initialize,
        inventory=lambda *_args: pytest.fail("created branch inventoried on enter"),
        now_ms=lambda: 123,
    )
    async with boundary as state:
        assert state == NewDatabaseBoundaryState(
            mode="created",
            initialized={"initialized": NEW_DATABASE},
            inventory=None,
        )
        assert not any(
            isinstance(call, tuple)
            and len(call) > 1
            and str(call[1]).startswith("SELECT RELEASE_LOCK")
            for call in calls
        )
        calls.append("body")

    assert calls == [
        "connect",
        (
            "fetchone",
            "SELECT GET_LOCK(%s, 0) AS acquired",
            ("novel_creator:phase7b:prepare",),
        ),
        (
            "execute",
            "CREATE DATABASE `novel_creator_v113` CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_0900_ai_ci",
            (),
        ),
        ("initialize", session, NEW_DATABASE, NEW_DATABASE, 123),
        "body",
        ("execute", "COMMIT", ()),
        (
            "fetchone",
            "SELECT RELEASE_LOCK(%s) AS released",
            ("novel_creator:phase7b:prepare",),
        ),
        "close",
    ]


@pytest.mark.asyncio
async def test_new_database_boundary_existing_race_is_never_owned_or_cleaned() -> None:
    calls: list[object] = []
    session = BoundarySession(calls, create_error=DatabaseExistsError("external"))
    observed = _empty_inventory(NEW_DATABASE)

    async def inventory(got_session: object, database: str) -> DatabaseInventory:
        calls.append(("inventory", got_session, database))
        return observed

    with pytest.raises(RuntimeError, match="body-primary"):
        async with new_database_boundary(
            NEW_DATABASE,
            session_factory=lambda: _factory_for(session),
            initialize=lambda *_args: pytest.fail("preexisting branch initialized"),
            inventory=inventory,
            now_ms=lambda: 123,
        ) as state:
            assert state == NewDatabaseBoundaryState("preexisting", None, observed)
            raise RuntimeError("body-primary")

    assert ("inventory", session, NEW_DATABASE) in calls
    assert not any(
        isinstance(call, tuple)
        and len(call) > 1
        and str(call[1]).startswith("DROP DATABASE")
        for call in calls
    )
    assert calls[-2:] == [
        (
            "fetchone",
            "SELECT RELEASE_LOCK(%s) AS released",
            ("novel_creator:phase7b:prepare",),
        ),
        "close",
    ]


@pytest.mark.asyncio
async def test_new_database_boundary_create_then_enter_failure_rolls_back_exact_target() -> None:
    calls: list[object] = []
    session = BoundarySession(calls)

    async def fail_initialize(*_args: object) -> object:
        raise RuntimeError("secret-initialize-detail")

    with pytest.raises(ProductDatabasePreparationCommandError) as raised:
        async with new_database_boundary(
            NEW_DATABASE,
            session_factory=lambda: _factory_for(session),
            initialize=fail_initialize,
            inventory=lambda *_args: pytest.fail("unexpected inventory"),
            now_ms=lambda: 123,
        ):
            pytest.fail("body entered")

    assert str(raised.value) == "new database boundary failed"
    assert (
        "execute",
        "DROP DATABASE `novel_creator_v113`",
        (),
    ) in calls
    assert calls[-2][1].startswith("SELECT RELEASE_LOCK")  # type: ignore[index]
    assert calls[-1] == "close"


@pytest.mark.asyncio
async def test_new_database_boundary_enter_cleanup_failure_uses_explicit_envelope() -> None:
    calls: list[object] = []
    session = BoundarySession(
        calls,
        drop_error=RuntimeError("secret-drop-detail"),
    )

    async def fail_initialize(*_args: object) -> object:
        raise RuntimeError("secret-initialize-detail")

    with pytest.raises(NewDatabaseBoundaryEnterFailure) as raised:
        async with new_database_boundary(
            NEW_DATABASE,
            session_factory=lambda: _factory_for(session),
            initialize=fail_initialize,
            inventory=lambda *_args: pytest.fail("unexpected inventory"),
            now_ms=lambda: 123,
        ):
            pytest.fail("body entered")

    assert str(raised.value.primary) == "new database boundary failed"
    assert str(raised.value.cleanup) == "new database boundary cleanup failed"
    assert "secret" not in repr(raised.value.primary)
    assert "secret" not in repr(raised.value.cleanup)


@pytest.mark.asyncio
async def test_new_database_boundary_body_failure_rolls_back_and_cleanup_envelope_excludes_body() -> None:
    calls: list[object] = []
    session = BoundarySession(
        calls,
        drop_error=RuntimeError("secret-drop-detail"),
    )

    async def initialize(*_args: object) -> object:
        return {"initialized": NEW_DATABASE}

    with pytest.raises(NewDatabaseBoundaryExitFailure) as raised:
        async with new_database_boundary(
            NEW_DATABASE,
            session_factory=lambda: _factory_for(session),
            initialize=initialize,
            inventory=lambda *_args: pytest.fail("unexpected inventory"),
            now_ms=lambda: 123,
        ):
            raise RuntimeError("secret-body-primary")

    assert str(raised.value.cleanup) == "new database boundary cleanup failed"
    assert not hasattr(raised.value, "primary")
    assert "secret-body-primary" not in repr(raised.value.cleanup)


@pytest.mark.asyncio
async def test_new_database_boundary_body_primary_is_propagated_after_exact_rollback_and_release() -> None:
    calls: list[object] = []
    session = BoundarySession(calls)
    primary = RuntimeError("body-primary")

    with pytest.raises(RuntimeError) as raised:
        async with new_database_boundary(
            NEW_DATABASE,
            session_factory=lambda: _factory_for(session),
            initialize=lambda *_args: {"initialized": NEW_DATABASE},
            inventory=lambda *_args: pytest.fail("unexpected inventory"),
            now_ms=lambda: 123,
        ):
            raise primary

    assert raised.value is primary
    assert (
        "execute",
        "DROP DATABASE `novel_creator_v113`",
        (),
    ) in calls
    assert calls[-2] == (
        "fetchone",
        "SELECT RELEASE_LOCK(%s) AS released",
        ("novel_creator:phase7b:prepare",),
    )
    assert calls[-1] == "close"


@pytest.mark.asyncio
async def test_new_database_boundary_release_failure_is_cleanup_only_exit_envelope() -> None:
    calls: list[object] = []
    session = BoundarySession(
        calls,
        release_error=RuntimeError("secret-release-detail"),
    )

    with pytest.raises(NewDatabaseBoundaryExitFailure) as raised:
        async with new_database_boundary(
            NEW_DATABASE,
            session_factory=lambda: _factory_for(session),
            initialize=lambda *_args: {"initialized": NEW_DATABASE},
            inventory=lambda *_args: pytest.fail("unexpected inventory"),
            now_ms=lambda: 123,
        ):
            pass

    assert not hasattr(raised.value, "primary")
    assert str(raised.value.cleanup) == "new database boundary cleanup failed"
    assert "secret" not in repr(raised.value.cleanup)
    assert calls[-1] == "close"


@pytest.mark.asyncio
async def test_new_database_boundary_preserves_commit_before_drop_and_release_failures() -> None:
    calls: list[object] = []
    session = BoundarySession(
        calls,
        commit_error=RuntimeError("secret-commit"),
        drop_error=RuntimeError("secret-drop"),
        release_error=RuntimeError("secret-release"),
    )

    with pytest.raises(NewDatabaseBoundaryExitFailure) as raised:
        async with new_database_boundary(
            NEW_DATABASE,
            session_factory=lambda: _factory_for(session),
            initialize=lambda *_args: {"initialized": NEW_DATABASE},
            inventory=lambda *_args: pytest.fail("unexpected inventory"),
            now_ms=lambda: 123,
        ):
            pass

    cleanup = raised.value.cleanup
    assert isinstance(cleanup, BaseExceptionGroup)
    assert [str(error) for error in cleanup.exceptions] == [
        "new database boundary commit failed",
        "new database boundary cleanup failed",
        "new database boundary cleanup failed",
    ]
    assert "secret" not in repr(cleanup)


@pytest.mark.asyncio
async def test_new_database_boundary_never_trusts_fixed_type_from_drop_or_release() -> None:
    calls: list[object] = []
    session = BoundarySession(
        calls,
        commit_error=RuntimeError("secret-commit"),
        drop_error=ProductDatabasePreparationCommandError("secret-drop"),
        release_error=ProductDatabasePreparationCommandError("secret-release"),
    )

    with pytest.raises(NewDatabaseBoundaryExitFailure) as raised:
        async with new_database_boundary(
            NEW_DATABASE,
            session_factory=lambda: _factory_for(session),
            initialize=lambda *_args: {"initialized": NEW_DATABASE},
            inventory=lambda *_args: pytest.fail("unexpected inventory"),
            now_ms=lambda: 123,
        ):
            pass

    cleanup = raised.value.cleanup
    assert isinstance(cleanup, BaseExceptionGroup)
    assert [str(error) for error in cleanup.exceptions] == [
        "new database boundary commit failed",
        "new database boundary cleanup failed",
        "new database boundary cleanup failed",
    ]
    assert "secret" not in repr(cleanup)


def _proof_inventory(database: str) -> DatabaseInventory:
    tables = tuple(sorted(created_table_names()))
    counts = tuple(
        (name, 1 if name == "schema_metadata" else 0) for name in tables
    )
    return DatabaseInventory(
        database=database,
        server_version="8.4.10",
        schema_version=EXPECTED_SCHEMA_VERSION,
        manifest_hash=manifest_hash(),
        structural_fingerprint="2" * 64,
        table_names=tables,
        row_counts=counts,
        nonempty_table_count=1,
        total_row_count=1,
    )


@pytest.mark.asyncio
async def test_current_schema_proof_uses_unique_disposable_database_and_closes_ledger() -> None:
    calls: list[object] = []
    session = BoundarySession(calls)
    proof_name = "novel_creator_phase7b_restore_0123456789abcdef0123456789abcdef"
    inventory = _proof_inventory(proof_name)
    storage = tuple(
        TableStorage(name, "InnoDB", "utf8mb4_0900_ai_ci")
        for name in inventory.table_names
    )

    async def initialize(
        got_session: object, database: str, confirmation: str, timestamp: int
    ) -> object:
        calls.append(("initialize", got_session, database, confirmation, timestamp))
        return object()

    async def read_inventory(got_session: object, database: str) -> DatabaseInventory:
        calls.append(("inventory", got_session, database))
        return inventory

    async def read_storage(got_session: object, database: str) -> tuple[TableStorage, ...]:
        calls.append(("storage", got_session, database))
        return storage

    proof = await create_current_schema_proof(
        session_factory=lambda: _factory_for(session),
        initialize=initialize,
        inventory=read_inventory,
        read_storage=read_storage,
        id_factory=lambda: "0123456789abcdef0123456789abcdef",
        now_ms=lambda: 456,
    )

    assert proof.inventory is inventory
    assert proof.storage is storage
    assert proof.created_databases == (proof_name,)
    assert proof.cleaned_databases == (proof_name,)
    assert all(NEW_DATABASE not in repr(call) for call in calls)
    assert calls == [
        "connect",
        (
            "execute",
            f"CREATE DATABASE `{proof_name}` CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_0900_ai_ci",
            (),
        ),
        ("initialize", session, proof_name, proof_name, 456),
        ("inventory", session, proof_name),
        ("storage", session, proof_name),
        ("execute", f"DROP DATABASE `{proof_name}`", ()),
        "close",
    ]


@pytest.mark.asyncio
async def test_current_schema_proof_cleanup_failure_returns_no_proof_and_is_sanitized() -> None:
    calls: list[object] = []
    session = BoundarySession(calls, drop_error=RuntimeError("secret-drop-detail"))
    proof_name = "novel_creator_phase7b_restore_0123456789abcdef0123456789abcdef"
    inventory = _proof_inventory(proof_name)
    storage = tuple(
        TableStorage(name, "InnoDB", "utf8mb4_0900_ai_ci")
        for name in inventory.table_names
    )

    with pytest.raises(ProductDatabasePreparationCommandError) as raised:
        await create_current_schema_proof(
            session_factory=lambda: _factory_for(session),
            initialize=lambda *_args: object(),
            inventory=lambda *_args: inventory,
            read_storage=lambda *_args: storage,
            id_factory=lambda: "0123456789abcdef0123456789abcdef",
            now_ms=lambda: 456,
        )

    assert str(raised.value) == "current schema proof cleanup failed"
    assert "secret" not in repr(raised.value)


@pytest.mark.asyncio
async def test_current_schema_proof_initialization_failure_drops_only_created_proof() -> None:
    calls: list[object] = []
    session = BoundarySession(calls)
    proof_name = "novel_creator_phase7b_restore_0123456789abcdef0123456789abcdef"

    async def fail_initialize(*_args: object) -> object:
        raise RuntimeError("secret-proof-initialize")

    with pytest.raises(ProductDatabasePreparationCommandError) as raised:
        await create_current_schema_proof(
            session_factory=lambda: _factory_for(session),
            initialize=fail_initialize,
            inventory=lambda *_args: pytest.fail("failed proof inventoried"),
            read_storage=lambda *_args: pytest.fail("failed proof storage read"),
            id_factory=lambda: "0123456789abcdef0123456789abcdef",
            now_ms=lambda: 456,
        )

    assert str(raised.value) == "current schema proof failed"
    assert (
        "execute",
        f"DROP DATABASE `{proof_name}`",
        (),
    ) in calls
    assert all(NEW_DATABASE not in repr(call) for call in calls)


def _preparation_receipt() -> PreparationReceipt:
    previous = None
    receipts = []
    for index, state in enumerate(tuple(ReadinessState)[:7]):
        previous = advance_receipt(previous, state, f"{index + 1:064x}")
        receipts.append(previous)
    assert previous is not None
    return PreparationReceipt(
        state=ReadinessState.AWAITING_CUTOVER_APPROVAL.value,
        previous_receipt_hash=canonical_receipt_hash(previous),
        legacy_database=LEGACY_DATABASE,
        new_database=NEW_DATABASE,
        legacy_inventory_hash="a" * 64,
        new_inventory_hash="b" * 64,
        backup_sha256="c" * 64,
        style_count=10,
        experience_card_count=64,
        market_source_count=2,
        receipts=tuple(receipts),
    )


class ReceiptHandle:
    def __init__(self, events: list[object], fail_at: str | None = None) -> None:
        self.events = events
        self.fail_at = fail_at
        self.closed = False

    def _event(self, name: str, value: object | None = None) -> None:
        self.events.append(name if value is None else (name, value))
        if self.fail_at == name:
            raise OSError(f"secret-{name}")

    def write(self, value: str) -> int:
        self._event("write", value)
        return len(value)

    def flush(self) -> None:
        self._event("flush")

    def fileno(self) -> int:
        self._event("fileno")
        return 41

    def close(self) -> None:
        self._event("close")
        if self.fail_at == "close":
            raise OSError("secret-close")
        self.closed = True


class ReceiptWorld:
    def __init__(
        self,
        root: Path,
        *,
        fail_at: str | None = None,
        replacement: bool = False,
    ) -> None:
        self.root = root
        self.fail_at = fail_at
        self.replacement = replacement
        self.events: list[object] = []
        self.handle = ReceiptHandle(self.events, fail_at)
        self.temporary = root / ".phase7b-readiness-owned.tmp"
        self.identity = object()
        self.linked = False

    def opener(self, directory: Path) -> tuple[Path, ReceiptHandle, object]:
        self.events.append(("open", directory))
        if self.fail_at == "open":
            raise OSError("secret-open")
        return self.temporary, self.handle, self.identity

    def acl(self, path: Path) -> None:
        self.events.append(("acl", path))
        if self.fail_at == "acl":
            raise OSError("secret-acl")

    def fsync(self, descriptor: int) -> None:
        self.events.append(("fsync", descriptor))
        if self.fail_at == "fsync":
            raise OSError("secret-fsync")

    def same_owner(self, path: Path, identity: object) -> bool:
        self.events.append(("owner", path, identity))
        return not self.replacement and identity is self.identity

    def link(self, source: Path, target: Path) -> None:
        self.events.append(("link", source, target))
        if self.fail_at == "link":
            raise FileExistsError("secret-link")
        self.linked = True

    def unlink_owned(self, path: Path, identity: object) -> bool:
        self.events.append(("unlink", path, identity))
        if self.fail_at == "unlink":
            raise OSError("secret-unlink")
        return not self.replacement and identity is self.identity


def test_receipt_publication_is_canonical_private_absent_only_and_owner_bound(
    tmp_path: Path,
) -> None:
    receipt = _preparation_receipt()
    external = Path(tmp_path.anchor) / "phase7b-receipt-tests" / tmp_path.name
    world = ReceiptWorld(external)
    backup = external / "approved-backup.sql"

    published = publish_readiness_receipt(
        receipt,
        backup,
        temporary_opener=world.opener,
        acl_runner=world.acl,
        fsync=world.fsync,
        linker=world.link,
        same_owner=world.same_owner,
        unlink_owned=world.unlink_owned,
    )

    expected = canonical_json(
        {
            "preparationReceipt": asdict(receipt),
            "preparationReceiptHash": canonical_receipt_hash(receipt),
        }
    )
    assert published == external / "approved-backup.readiness.json"
    assert world.events == [
        ("open", external),
        ("acl", world.temporary),
        ("owner", world.temporary, world.identity),
        ("write", expected),
        "flush",
        "fileno",
        ("fsync", 41),
        "close",
        ("owner", world.temporary, world.identity),
        ("link", world.temporary, published),
        ("owner", published, world.identity),
        ("unlink", world.temporary, world.identity),
    ]
    document = json.loads(expected)
    assert document["preparationReceiptHash"] == canonical_receipt_hash(receipt)
    assert canonical_json(document) == expected


@pytest.mark.parametrize(
    "failure",
    ["open", "acl", "write", "flush", "fsync", "close", "link", "unlink"],
)
def test_receipt_publication_failure_matrix_is_fixed_and_attempts_owned_cleanup(
    tmp_path: Path,
    failure: str,
) -> None:
    external = Path(tmp_path.anchor) / "phase7b-receipt-tests" / tmp_path.name
    world = ReceiptWorld(external, fail_at=failure)

    with pytest.raises(BaseException) as raised:
        publish_readiness_receipt(
            _preparation_receipt(),
            external / "approved-backup.sql",
            temporary_opener=world.opener,
            acl_runner=world.acl,
            fsync=world.fsync,
            linker=world.link,
            same_owner=world.same_owner,
            unlink_owned=world.unlink_owned,
        )

    rendered = repr(raised.value)
    assert "secret" not in rendered
    if failure != "open":
        assert any(
            isinstance(event, tuple) and event[0] == "unlink"
            for event in world.events
        )
    if failure == "unlink":
        assert world.linked


def test_receipt_publication_never_deletes_replacement_or_publishes_it(
    tmp_path: Path,
) -> None:
    external = Path(tmp_path.anchor) / "phase7b-receipt-tests" / tmp_path.name
    world = ReceiptWorld(external, replacement=True)

    with pytest.raises(BaseException) as raised:
        publish_readiness_receipt(
            _preparation_receipt(),
            external / "approved-backup.sql",
            temporary_opener=world.opener,
            acl_runner=world.acl,
            fsync=world.fsync,
            linker=world.link,
            same_owner=world.same_owner,
            unlink_owned=world.unlink_owned,
        )

    assert "secret" not in repr(raised.value)
    assert not world.linked
    assert (
        "unlink",
        world.temporary,
        world.identity,
    ) in world.events


class ExecuteWorld:
    def __init__(self, receipt: PreparationReceipt) -> None:
        self.receipt = receipt
        self.events: list[object] = []
        self.pair = object()
        self.option = Path("D:/private/command.cnf")
        self.inventory = _empty_inventory(LEGACY_DATABASE)
        self.backup = BackupReceipt(
            state=ReadinessState.BACKUP_CREATED.value,
            previous_receipt_hash=canonical_receipt_hash(
                advance_receipt(
                    None,
                    ReadinessState.INVENTORY_VERIFIED,
                    inventory_hash(self.inventory),
                )
            ),
            source_database=LEGACY_DATABASE,
            backup_filename="approved-backup.sql",
            backup_sha256=receipt.backup_sha256,
            backup_byte_length=42,
            client_version="8.4.10",
            source_inventory_hash=inventory_hash(self.inventory),
        )

    def preflight_clients(
        self, dump: Path, mysql: Path, repository: Path
    ) -> object:
        self.events.append(("client-preflight", dump, mysql, repository))
        return self.pair

    def read_config(self) -> dict[str, object]:
        self.events.append("config")
        return {
            "host": "127.0.0.1",
            "port": 3307,
            "user": "writer",
            "password": "top-secret",
            "db": LEGACY_DATABASE,
        }

    @contextmanager
    def option_file(
        self, config: object, root: Path
    ):  # type: ignore[no-untyped-def]
        self.events.append(("option-enter", config, root))
        try:
            yield self.option
        finally:
            self.events.append("option-exit")

    def preflight_connection(self, pair: object, option: Path) -> None:
        self.events.append(("connection-preflight", pair, option))

    async def inventory_database(
        self, config: object, database: str
    ) -> DatabaseInventory:
        self.events.append(("inventory", config, database))
        return self.inventory

    def create_backup(
        self,
        pair: object,
        option: Path,
        authority: DatabaseInventory,
        directory: Path,
        filename: str,
        previous_hash: str,
    ) -> BackupReceipt:
        self.events.append(
            (
                "backup",
                pair,
                option,
                authority,
                directory,
                filename,
                previous_hash,
            )
        )
        return self.backup

    async def prepare(self, **kwargs: object) -> PreparationReceipt:
        self.events.append(("prepare", kwargs))
        authority = await kwargs["inventory"]("legacy-before")  # type: ignore[operator]
        backup = await kwargs["create_backup"](  # type: ignore[operator]
            authority,
            kwargs["request"].backup_directory,  # type: ignore[union-attr]
        )
        await kwargs["restore_drill"](backup, authority)  # type: ignore[operator]
        await kwargs["inventory"]("legacy-after")  # type: ignore[operator]
        await kwargs["current_schema_proof"]()  # type: ignore[operator]
        boundary = kwargs["new_database_boundary"](NEW_DATABASE)  # type: ignore[operator]
        async with boundary:
            await kwargs["seed_assets"](NEW_DATABASE)  # type: ignore[operator]
            await kwargs["seed_market"](NEW_DATABASE)  # type: ignore[operator]
            await kwargs["inventory"]("new")  # type: ignore[operator]
            await kwargs["read_storage"](NEW_DATABASE)  # type: ignore[operator]
            await kwargs["audit_official_data"](NEW_DATABASE)  # type: ignore[operator]
            await kwargs["smoke"](NEW_DATABASE)  # type: ignore[operator]
        return self.receipt

    async def restore_drill(
        self, *args: object
    ) -> object:
        self.events.append(("restore", *args))
        return object()

    async def current_schema_proof(self, config: object) -> object:
        self.events.append(("proof", config))
        return object()

    def database_boundary(self, config: object, database: str) -> object:
        self.events.append(("boundary", config, database))
        events = self.events

        class Boundary:
            async def __aenter__(self) -> object:
                events.append("boundary-enter")
                return object()

            async def __aexit__(self, *_args: object) -> bool:
                events.append("boundary-exit")
                return False

        return Boundary()

    async def seed_assets(self, config: object, database: str) -> object:
        self.events.append(("seed-assets", config, database))
        return object()

    async def seed_market(self, config: object, database: str) -> object:
        self.events.append(("seed-market", config, database))
        return object()

    async def read_storage(self, config: object, database: str) -> object:
        self.events.append(("storage", config, database))
        return object()

    async def audit_official_data(self, config: object, database: str) -> object:
        self.events.append(("audit", config, database))
        return object()

    async def smoke(self, config: object, database: str) -> object:
        self.events.append(("smoke", config, database))
        return object()

    def publish(
        self, receipt: PreparationReceipt, backup: Path
    ) -> Path:
        self.events.append(("publish", receipt, backup))
        return backup.with_suffix(".readiness.json")


@pytest.mark.asyncio
async def test_execute_wires_preflight_inventory_task4_and_publication_in_order(
    tmp_path: Path,
) -> None:
    receipt = _preparation_receipt()
    world = ExecuteWorld(receipt)
    ids = iter(("11111111111111111111111111111111",))
    dependencies = PreparationCommandDependencies(
        preflight_clients=world.preflight_clients,
        read_config=world.read_config,
        option_file=world.option_file,
        preflight_connection=world.preflight_connection,
        inventory_database=world.inventory_database,
        create_backup=world.create_backup,
        restore_drill=world.restore_drill,
        current_schema_proof=world.current_schema_proof,
        database_boundary=world.database_boundary,
        seed_assets=world.seed_assets,
        seed_market=world.seed_market,
        read_storage=world.read_storage,
        audit_official_data=world.audit_official_data,
        smoke=world.smoke,
        prepare_service=world.prepare,
        publish_receipt=world.publish,
        id_factory=lambda: next(ids),
    )
    argv = [
        *_arguments(tmp_path),
        "--execute",
        "--confirm-legacy",
        LEGACY_DATABASE,
        "--confirm-new",
        NEW_DATABASE,
        "--confirm-prepare",
        "PREPARE-PHASE7B",
    ]
    lines: list[str] = []

    status = await run_cli(argv, dependencies=dependencies, output=lines.append)

    backup_dir = Path(argv[5])
    dump = Path(argv[7])
    mysql = Path(argv[9])
    assert status == 0
    assert world.events[0] == (
        "client-preflight",
        dump,
        mysql,
        Path(__file__).resolve().parents[3],
    )
    assert world.events[1] == "config"
    assert world.events[2][0] == "option-enter"  # type: ignore[index]
    assert world.events[3] == (
        "connection-preflight",
        world.pair,
        world.option,
    )
    assert world.events[4][0] == "prepare"  # type: ignore[index]
    prepare_kwargs = world.events[4][1]  # type: ignore[index]
    assert set(prepare_kwargs) == {
        "request",
        "inventory",
        "create_backup",
        "restore_drill",
        "current_schema_proof",
        "new_database_boundary",
        "seed_assets",
        "seed_market",
        "read_storage",
        "audit_official_data",
        "smoke",
    }
    assert prepare_kwargs["request"].legacy_database == LEGACY_DATABASE
    assert prepare_kwargs["request"].new_database == NEW_DATABASE
    assert prepare_kwargs["request"].backup_directory == backup_dir
    assert world.events[5] == (
        "inventory",
        world.events[2][1],  # type: ignore[index]
        LEGACY_DATABASE,
    )
    assert world.events[6][:5] == (  # type: ignore[index]
        "backup",
        world.pair,
        world.option,
        world.inventory,
        backup_dir,
    )
    assert world.events[6][5] == (  # type: ignore[index]
        "novel_creator-phase7b-11111111111111111111111111111111.sql"
    )
    assert world.events[6][6] == world.backup.previous_receipt_hash  # type: ignore[index]
    assert [
        event if isinstance(event, str) else event[0]
        for event in world.events[7:20]
    ] == [
        "restore",
        "inventory",
        "proof",
        "boundary",
        "boundary-enter",
        "seed-assets",
        "seed-market",
        "inventory",
        "storage",
        "audit",
        "smoke",
        "boundary-exit",
        "option-exit",
    ]
    config = world.events[2][1]  # type: ignore[index]
    assert world.events[7][1:] == (  # type: ignore[index]
        config,
        world.pair,
        world.option,
        world.backup,
        world.inventory,
        backup_dir,
    )
    assert world.events[8] == ("inventory", config, LEGACY_DATABASE)
    assert world.events[9] == ("proof", config)
    assert world.events[10] == ("boundary", config, NEW_DATABASE)
    for index in (12, 13, 15, 16, 17):
        assert world.events[index][1:] == (config, NEW_DATABASE)  # type: ignore[index]
    assert world.events[14] == ("inventory", config, NEW_DATABASE)
    assert world.events[20] == (
        "publish",
        receipt,
        backup_dir / world.backup.backup_filename,
    )
    assert lines == [
        "mode=execute",
        "legacy_database=novel_creator",
        "new_database=novel_creator_v113",
        "stage=awaiting-cutover-approval",
        f"receipt_hash={canonical_receipt_hash(receipt)}",
    ]
    rendered = "\n".join(lines)
    assert "top-secret" not in rendered
    assert str(backup_dir) not in rendered
    assert "11111111111111111111111111111111" not in rendered


@pytest.mark.asyncio
async def test_execute_failure_is_fixed_and_drops_ambient_secret_context(
    tmp_path: Path,
) -> None:
    receipt = _preparation_receipt()
    world = ExecuteWorld(receipt)
    dependencies = PreparationCommandDependencies(
        preflight_clients=lambda *_args: (_ for _ in ()).throw(
            RuntimeError("password=secret D:/private/mysql.exe")
        ),
        read_config=world.read_config,
        option_file=world.option_file,
        preflight_connection=world.preflight_connection,
        inventory_database=world.inventory_database,
        create_backup=world.create_backup,
        restore_drill=lambda *_args: None,
        current_schema_proof=lambda *_args: None,
        database_boundary=lambda *_args: None,
        seed_assets=lambda *_args: None,
        seed_market=lambda *_args: None,
        read_storage=lambda *_args: None,
        audit_official_data=lambda *_args: None,
        smoke=lambda *_args: None,
        prepare_service=world.prepare,
        publish_receipt=world.publish,
        id_factory=lambda: "1" * 32,
    )
    argv = [
        *_arguments(tmp_path),
        "--execute",
        "--confirm-legacy",
        LEGACY_DATABASE,
        "--confirm-new",
        NEW_DATABASE,
        "--confirm-prepare",
        "PREPARE-PHASE7B",
    ]

    with pytest.raises(ProductDatabasePreparationCommandError) as raised:
        await run_cli(argv, dependencies=dependencies)

    assert str(raised.value) == "product database preparation execution failed"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert raised.value.__suppress_context__ is True


def test_main_prints_only_fixed_failure(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    secret = "never-print-this-secret"

    async def fail(*_args: object, **_kwargs: object) -> int:
        raise RuntimeError(secret)

    monkeypatch.setattr(
        "backend.scripts.prepare_product_database.run_cli",
        fail,
    )

    assert main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Product database preparation failed.\n"
    assert secret not in captured.err


@pytest.mark.asyncio
async def test_default_transaction_retains_commit_primary_when_close_also_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Session:
        async def execute(self, sql: str) -> None:
            if sql == "COMMIT":
                raise RuntimeError("secret-commit-primary")

        async def close(self) -> None:
            raise RuntimeError("secret-close-cleanup")

    async def open_session(*_args: object) -> Session:
        return Session()

    monkeypatch.setattr(
        "backend.scripts.prepare_product_database._open_default_session",
        open_session,
    )

    with pytest.raises(BaseExceptionGroup) as raised:
        async with _default_transaction_scope({}, NEW_DATABASE):
            pass

    assert len(raised.value.exceptions) == 2
    assert all(
        str(error) == "product database preparation execution failed"
        for error in raised.value.exceptions
    )
    assert "secret" not in repr(raised.value)


@pytest.mark.asyncio
async def test_default_connection_scope_retains_body_primary_when_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Session:
        async def close(self) -> None:
            raise RuntimeError("secret-close-cleanup")

    async def open_session(*_args: object) -> Session:
        return Session()

    monkeypatch.setattr(
        "backend.scripts.prepare_product_database._open_default_session",
        open_session,
    )

    with pytest.raises(BaseExceptionGroup) as raised:
        async with _default_connection_scope({}, NEW_DATABASE):
            raise RuntimeError("secret-body-primary")

    assert len(raised.value.exceptions) == 2
    assert all(
        str(error) == "product database preparation execution failed"
        for error in raised.value.exceptions
    )
    assert "secret" not in repr(raised.value)
