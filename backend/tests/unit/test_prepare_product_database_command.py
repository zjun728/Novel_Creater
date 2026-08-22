from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from dataclasses import asdict, replace
from contextlib import asynccontextmanager, contextmanager
import asyncio
import gc
import json
import os
import shutil
import stat
import subprocess
from types import SimpleNamespace

import pytest
import backend.scripts.prepare_product_database as command_module

from backend.domain.product_database_readiness import (
    DatabaseInventory,
    BackupReceipt,
    LEGACY_DATABASE,
    NEW_DATABASE,
    PreparationReceipt,
    ProductDatabaseReadinessError,
    ReadinessState,
    StateReceipt,
    advance_receipt,
    canonical_receipt_hash,
    inventory_hash,
)
from backend.domain.assets import PACKAGE_VERSION as ASSET_VERSION, load_asset_package
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.market_sources import (
    PACKAGE_VERSION as MARKET_VERSION,
    load_market_source_package,
)
from backend.schema_manifest import created_table_names, manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from backend.security.private_files import apply_private_permissions
from backend.scripts.prepare_product_database import (
    ProductDatabasePreparationCommandError,
    PreparationCommandDependencies,
    _default_dependencies,
    _primary_first_context,
    _default_transaction_scope,
    _default_connection_scope,
    create_current_schema_proof,
    new_database_boundary,
    load_preparation_receipt,
    parse_backup_receipt_document,
    parse_preparation_receipt_document,
    parse_state_receipt_document,
    publish_readiness_receipt,
    main,
    run_cli,
)
from backend.scripts.initialize_database import InitializationResult
from backend.services.assets import AssetSeedReport
from backend.services.market_sources import MarketSourceSeedReport
from backend.services.product_database_backup import ProductDatabaseBackupError
from backend.services.product_database_inventory import TableStorage
from backend.services.product_database_readiness import (
    CurrentSchemaProof,
    NewDatabaseBoundaryEnterFailure,
    NewDatabaseBoundaryExitFailure,
    NewDatabaseBoundaryState,
    OfficialDataAudit,
    RestoreDrillResult,
    SmokeResult,
    prepare_product_database,
)


FLOW_CONTROLS = (asyncio.CancelledError, KeyboardInterrupt, SystemExit)
FLOW_MATRIX_CASES = (
    "cancelled",
    "keyboard-interrupt",
    "system-exit-int",
    "system-exit-text",
)


@pytest.fixture
def sync_main_event_loop_owner() -> Iterator[None]:
    try:
        with _owned_sync_main_event_loop():
            yield
    finally:
        gc.collect()


@contextmanager
def _owned_sync_main_event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    policy = asyncio.get_event_loop_policy()
    policy_local = getattr(policy, "_local", None)
    if policy_local is None:
        raise RuntimeError("sync main tests require the default asyncio event loop policy")
    preexisting = getattr(policy_local, "_loop", None)
    owned = asyncio.new_event_loop()
    asyncio.set_event_loop(owned)
    try:
        yield owned
    finally:
        if not owned.is_closed():
            owned.close()
        if preexisting is not None and not preexisting.is_closed():
            asyncio.set_event_loop(preexisting)
        else:
            asyncio.set_event_loop(None)


def test_sync_main_loop_owner_restores_unrelated_loop_without_closing_it() -> None:
    policy = asyncio.get_event_loop_policy()
    policy_local = getattr(policy, "_local", None)
    assert policy_local is not None
    preexisting = getattr(policy_local, "_loop", None)
    unrelated = asyncio.new_event_loop()
    asyncio.set_event_loop(unrelated)
    try:
        with _owned_sync_main_event_loop() as owned:
            assert asyncio.get_event_loop() is owned
            asyncio.run(asyncio.sleep(0))

        assert owned.is_closed()
        assert unrelated.is_closed() is False
        assert asyncio.get_event_loop() is unrelated
    finally:
        unrelated.close()
        if preexisting is not None and not preexisting.is_closed():
            asyncio.set_event_loop(preexisting)
        else:
            asyncio.set_event_loop(None)


def test_sync_main_loop_owner_restores_no_current_loop() -> None:
    policy = asyncio.get_event_loop_policy()
    policy_local = getattr(policy, "_local", None)
    assert policy_local is not None
    preexisting = getattr(policy_local, "_loop", None)
    try:
        asyncio.set_event_loop(None)

        with _owned_sync_main_event_loop() as owned:
            assert asyncio.get_event_loop() is owned
            asyncio.run(asyncio.sleep(0))

        assert owned.is_closed()
        with pytest.raises(RuntimeError, match="There is no current event loop"):
            asyncio.get_event_loop()
    finally:
        if preexisting is not None and not preexisting.is_closed():
            asyncio.set_event_loop(preexisting)
        else:
            asyncio.set_event_loop(None)


@pytest.mark.parametrize("exceptional_exit", (False, True))
def test_sync_main_loop_owner_does_not_adopt_fresh_policy_implicit_loop(
    exceptional_exit: bool,
) -> None:
    original_policy = asyncio.get_event_loop_policy()
    fresh_policy = asyncio.DefaultEventLoopPolicy()
    asyncio.set_event_loop_policy(fresh_policy)
    try:
        policy_local = fresh_policy._local  # type: ignore[attr-defined]
        assert vars(policy_local) == {}

        if exceptional_exit:
            with pytest.raises(RuntimeError, match="fixture-body-failed"):
                with _owned_sync_main_event_loop() as owned:
                    raise RuntimeError("fixture-body-failed")
        else:
            with _owned_sync_main_event_loop() as owned:
                asyncio.run(asyncio.sleep(0))

        assert owned.is_closed()
        assert getattr(policy_local, "_loop", None) is None
        with pytest.raises(RuntimeError, match="There is no current event loop"):
            asyncio.get_event_loop()
    finally:
        implicit = getattr(fresh_policy._local, "_loop", None)  # type: ignore[attr-defined]
        if implicit is not None and not implicit.is_closed():
            implicit.close()
        asyncio.set_event_loop_policy(original_policy)


def _secret_flow_control(flow_type: type[BaseException]) -> BaseException:
    return flow_type("secret-flow-control")


def _assert_clean_flow_control(
    error: BaseException, expected_type: type[BaseException]
) -> None:
    assert type(error) is expected_type
    assert "secret" not in repr(error)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert getattr(error, "__notes__", None) in (None, [])
    if isinstance(error, SystemExit):
        assert error.code is None
    else:
        assert error.args == ()


def _matrix_flow(case: str) -> BaseException:
    if case == "cancelled":
        return asyncio.CancelledError("secret-flow-control")
    if case == "keyboard-interrupt":
        return KeyboardInterrupt("secret-flow-control")
    if case == "system-exit-int":
        return SystemExit(17)
    if case == "system-exit-text":
        return SystemExit("secret-flow-control")
    raise AssertionError(case)


def _assert_matrix_flow(error: BaseException, case: str) -> None:
    expected = {
        "cancelled": asyncio.CancelledError,
        "keyboard-interrupt": KeyboardInterrupt,
        "system-exit-int": SystemExit,
        "system-exit-text": SystemExit,
    }[case]
    assert type(error) is expected
    assert "secret" not in repr(error)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert getattr(error, "__notes__", None) in (None, [])
    if case == "system-exit-int":
        assert error.code == 17  # type: ignore[attr-defined]
    elif isinstance(error, SystemExit):
        assert error.code is None
    else:
        assert error.args == ()


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
        close_error: BaseException | None = None,
    ) -> None:
        self.calls = calls
        self.create_error = create_error
        self.drop_error = drop_error
        self.release_error = release_error
        self.commit_error = commit_error
        self.close_error = close_error

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
        if self.close_error is not None:
            raise self.close_error


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
async def test_two_boundaries_share_one_lock_and_only_the_owner_can_create() -> None:
    calls: list[object] = []
    lock_owner: list[object] = []
    entered = asyncio.Event()
    finish = asyncio.Event()

    class SharedLockSession(BoundarySession):
        async def fetchone(
            self, sql: str, params: tuple[object, ...] = ()
        ) -> dict[str, int]:
            self.calls.append(("fetchone", sql, params, self))
            if sql.startswith("SELECT GET_LOCK"):
                if lock_owner:
                    return {"acquired": 0}
                lock_owner.append(self)
                return {"acquired": 1}
            if sql.startswith("SELECT RELEASE_LOCK"):
                assert lock_owner == [self]
                lock_owner.clear()
                return {"released": 1}
            raise AssertionError(sql)

    sessions = [SharedLockSession(calls), SharedLockSession(calls)]

    async def session_factory() -> SharedLockSession:
        session = sessions.pop(0)
        calls.append(("connect", session))
        return session

    async def owner() -> None:
        async with new_database_boundary(
            NEW_DATABASE,
            session_factory=session_factory,
            initialize=lambda *_args: {"initialized": NEW_DATABASE},
            inventory=lambda *_args: pytest.fail("owner inventoried"),
            now_ms=lambda: 123,
        ):
            entered.set()
            await finish.wait()

    owner_task = asyncio.create_task(owner())
    await entered.wait()
    with pytest.raises(ProductDatabasePreparationCommandError) as raised:
        async with new_database_boundary(
            NEW_DATABASE,
            session_factory=session_factory,
            initialize=lambda *_args: pytest.fail("contender initialized"),
            inventory=lambda *_args: pytest.fail("contender inventoried"),
            now_ms=lambda: 123,
        ):
            pytest.fail("contender entered")
    assert str(raised.value) == "new database boundary failed"
    assert len(lock_owner) == 1
    assert sum(
        isinstance(call, tuple)
        and len(call) > 1
        and str(call[1]).startswith("CREATE DATABASE")
        for call in calls
    ) == 1

    finish.set()
    await owner_task
    assert lock_owner == []
    assert sum(
        isinstance(call, tuple)
        and len(call) > 1
        and str(call[1]).startswith("DROP DATABASE")
        for call in calls
    ) == 0


@pytest.mark.asyncio
async def test_numeric_1007_create_ambiguity_is_observed_but_never_owned() -> None:
    calls: list[object] = []
    session = BoundarySession(calls, create_error=RuntimeError(1007, "secret-race"))
    observed = _empty_inventory(NEW_DATABASE)

    async with new_database_boundary(
        NEW_DATABASE,
        session_factory=lambda: _factory_for(session),
        initialize=lambda *_args: pytest.fail("ambiguous existing DB initialized"),
        inventory=lambda *_args: observed,
        now_ms=lambda: 123,
    ) as state:
        assert state == NewDatabaseBoundaryState("preexisting", None, observed)

    assert not any(
        isinstance(call, tuple)
        and len(call) > 1
        and str(call[1]).startswith("DROP DATABASE")
        for call in calls
    )


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


@pytest.mark.asyncio
@pytest.mark.parametrize("flow_type", FLOW_CONTROLS)
async def test_boundary_enter_flow_control_is_cloned_and_releases_every_resource(
    flow_type: type[BaseException],
) -> None:
    calls: list[object] = []
    session = BoundarySession(calls)

    async def fail_initialize(*_args: object) -> object:
        raise _secret_flow_control(flow_type)

    with pytest.raises(BaseException) as raised:
        async with new_database_boundary(
            NEW_DATABASE,
            session_factory=lambda: _factory_for(session),
            initialize=fail_initialize,
            inventory=lambda *_args: pytest.fail("unexpected inventory"),
            now_ms=lambda: 123,
        ):
            pytest.fail("body entered")

    _assert_clean_flow_control(raised.value, flow_type)
    assert sum(call == "close" for call in calls) == 1
    assert (
        "execute",
        "DROP DATABASE `novel_creator_v113`",
        (),
    ) in calls
    assert calls[-2][1].startswith("SELECT RELEASE_LOCK")  # type: ignore[index]


@pytest.mark.asyncio
@pytest.mark.parametrize("flow_type", FLOW_CONTROLS)
@pytest.mark.parametrize("failure_at", ("drop", "release"))
async def test_boundary_cleanup_flow_control_is_cleanup_only_and_body_safe(
    flow_type: type[BaseException], failure_at: str
) -> None:
    calls: list[object] = []
    session = BoundarySession(
        calls,
        drop_error=(
            _secret_flow_control(flow_type) if failure_at == "drop" else None
        ),
        release_error=(
            _secret_flow_control(flow_type) if failure_at == "release" else None
        ),
    )

    with pytest.raises(NewDatabaseBoundaryExitFailure) as raised:
        async with new_database_boundary(
            NEW_DATABASE,
            session_factory=lambda: _factory_for(session),
            initialize=lambda *_args: {"initialized": NEW_DATABASE},
            inventory=lambda *_args: pytest.fail("unexpected inventory"),
            now_ms=lambda: 123,
        ):
            if failure_at == "drop":
                raise RuntimeError("secret-body-primary")

    assert not hasattr(raised.value, "primary")
    _assert_clean_flow_control(raised.value.cleanup, flow_type)
    assert "secret-body-primary" not in repr(raised.value)
    assert sum(call == "close" for call in calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("flow_case", FLOW_MATRIX_CASES)
@pytest.mark.parametrize(
    "stage",
    ("session", "get-lock", "create", "preexisting-inventory", "commit", "close"),
)
async def test_boundary_all_stage_flow_matrix_closes_owned_resources(
    flow_case: str, stage: str
) -> None:
    calls: list[object] = []

    class Session(BoundarySession):
        def __init__(self) -> None:
            super().__init__(calls)
            self.locked = False
            self.closed = False
            self.created = False

        async def fetchone(
            self, sql: str, params: tuple[object, ...] = ()
        ) -> dict[str, int]:
            calls.append(("fetchone", sql, params))
            if sql.startswith("SELECT GET_LOCK"):
                if stage == "get-lock":
                    raise _matrix_flow(flow_case)
                self.locked = True
                return {"acquired": 1}
            if sql.startswith("SELECT RELEASE_LOCK"):
                self.locked = False
                return {"released": 1}
            raise AssertionError(sql)

        async def execute(
            self, sql: str, params: tuple[object, ...] = ()
        ) -> None:
            calls.append(("execute", sql, params))
            if sql.startswith("CREATE DATABASE"):
                if stage == "create":
                    raise _matrix_flow(flow_case)
                if stage == "preexisting-inventory":
                    raise DatabaseExistsError("external")
                self.created = True
            elif sql.startswith("DROP DATABASE"):
                self.created = False
            elif sql == "COMMIT" and stage == "commit":
                raise _matrix_flow(flow_case)

        async def close(self) -> None:
            calls.append("close")
            self.closed = True
            if stage == "close":
                raise _matrix_flow(flow_case)
            if stage in ("get-lock", "create", "preexisting-inventory", "commit"):
                raise RuntimeError("secret-secondary-cleanup")

    session = Session()

    async def session_factory() -> Session:
        calls.append("connect")
        if stage == "session":
            raise _matrix_flow(flow_case)
        return session

    async def inventory(*_args: object) -> DatabaseInventory:
        if stage == "preexisting-inventory":
            raise _matrix_flow(flow_case)
        return _empty_inventory(NEW_DATABASE)

    with pytest.raises(BaseException) as raised:
        async with new_database_boundary(
            NEW_DATABASE,
            session_factory=session_factory,
            initialize=lambda *_args: {"initialized": NEW_DATABASE},
            inventory=inventory,
            now_ms=lambda: 123,
        ):
            pass

    outgoing = (
        raised.value.cleanup
        if isinstance(raised.value, NewDatabaseBoundaryExitFailure)
        else raised.value.primary
        if isinstance(raised.value, NewDatabaseBoundaryEnterFailure)
        else raised.value
    )
    if isinstance(outgoing, BaseExceptionGroup):
        outgoing = outgoing.exceptions[0]
    _assert_matrix_flow(outgoing, flow_case)
    assert "secret" not in repr(raised.value)
    assert session.locked is False
    assert session.closed is (stage != "session")
    assert session.created is (stage == "close")
    drop_calls = [
        call
        for call in calls
        if (
            isinstance(call, tuple)
            and len(call) > 1
            and str(call[1]).startswith("DROP DATABASE")
        )
    ]
    assert not drop_calls if stage in (
        "session",
        "get-lock",
        "create",
        "preexisting-inventory",
        "close",
    ) else len(drop_calls) == 1


def _proof_inventory(database: str) -> DatabaseInventory:
    tables = tuple(sorted(created_table_names()))
    counts = tuple(
        (
            name,
            1 if name in {"schema_metadata", "application_settings"} else 0,
        )
        for name in tables
    )
    return DatabaseInventory(
        database=database,
        server_version="8.4.10",
        schema_version=EXPECTED_SCHEMA_VERSION,
        manifest_hash=manifest_hash(),
        structural_fingerprint="2" * 64,
        table_names=tables,
        row_counts=counts,
        nonempty_table_count=sum(count > 0 for _, count in counts),
        total_row_count=sum(count for _, count in counts),
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
    assert dict(proof.inventory.row_counts)["application_settings"] == 1
    assert proof.inventory.nonempty_table_count == 2
    assert proof.inventory.total_row_count == 2
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
@pytest.mark.parametrize("flow_type", FLOW_CONTROLS)
@pytest.mark.parametrize("failure_at", ("initialize", "drop", "close"))
async def test_current_schema_proof_flow_control_is_clean_and_closes_session(
    flow_type: type[BaseException], failure_at: str
) -> None:
    calls: list[object] = []
    session = BoundarySession(
        calls,
        drop_error=(
            _secret_flow_control(flow_type) if failure_at == "drop" else None
        ),
        close_error=(
            _secret_flow_control(flow_type) if failure_at == "close" else None
        ),
    )
    proof_name = "novel_creator_phase7b_restore_0123456789abcdef0123456789abcdef"
    inventory = _proof_inventory(proof_name)
    storage = tuple(
        TableStorage(name, "InnoDB", "utf8mb4_0900_ai_ci")
        for name in inventory.table_names
    )

    async def initialize(*_args: object) -> object:
        if failure_at == "initialize":
            raise _secret_flow_control(flow_type)
        return object()

    with pytest.raises(BaseException) as raised:
        await create_current_schema_proof(
            session_factory=lambda: _factory_for(session),
            initialize=initialize,
            inventory=lambda *_args: inventory,
            read_storage=lambda *_args: storage,
            id_factory=lambda: "0123456789abcdef0123456789abcdef",
            now_ms=lambda: 123,
        )

    _assert_clean_flow_control(raised.value, flow_type)
    assert sum(call == "close" for call in calls) == 1
    assert all(NEW_DATABASE not in repr(call) for call in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("flow_type", FLOW_CONTROLS)
async def test_current_schema_proof_primary_precedes_cleanup_flow_control(
    flow_type: type[BaseException],
) -> None:
    calls: list[object] = []
    session = BoundarySession(calls, drop_error=_secret_flow_control(flow_type))

    async def fail_initialize(*_args: object) -> object:
        raise _secret_flow_control(flow_type)

    with pytest.raises(BaseExceptionGroup) as raised:
        await create_current_schema_proof(
            session_factory=lambda: _factory_for(session),
            initialize=fail_initialize,
            inventory=lambda *_args: pytest.fail("unexpected inventory"),
            read_storage=lambda *_args: pytest.fail("unexpected storage"),
            id_factory=lambda: "0123456789abcdef0123456789abcdef",
            now_ms=lambda: 123,
        )

    assert len(raised.value.exceptions) == 2
    _assert_clean_flow_control(raised.value.exceptions[0], flow_type)
    _assert_clean_flow_control(raised.value.exceptions[1], flow_type)
    assert sum(call == "close" for call in calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("flow_case", FLOW_MATRIX_CASES)
@pytest.mark.parametrize(
    "stage", ("id", "session", "create", "inventory", "storage", "drop", "close")
)
async def test_current_schema_proof_all_stage_flow_matrix_closes_resources(
    flow_case: str, stage: str
) -> None:
    calls: list[object] = []
    proof_name = "novel_creator_phase7b_restore_0123456789abcdef0123456789abcdef"
    inventory_value = _proof_inventory(proof_name)
    storage_value = tuple(
        TableStorage(name, "InnoDB", "utf8mb4_0900_ai_ci")
        for name in inventory_value.table_names
    )

    class Session(BoundarySession):
        def __init__(self) -> None:
            super().__init__(calls)
            self.created = False
            self.closed = False

        async def execute(
            self, sql: str, params: tuple[object, ...] = ()
        ) -> None:
            calls.append(("execute", sql, params))
            if sql.startswith("CREATE DATABASE"):
                if stage == "create":
                    raise _matrix_flow(flow_case)
                self.created = True
            elif sql.startswith("DROP DATABASE"):
                self.created = False
                if stage == "drop":
                    raise _matrix_flow(flow_case)

        async def close(self) -> None:
            calls.append("close")
            self.closed = True
            if stage == "close":
                raise _matrix_flow(flow_case)
            if stage in ("create", "inventory", "storage"):
                raise RuntimeError("secret-secondary-cleanup")

    session = Session()

    async def session_factory() -> Session:
        if stage == "session":
            raise _matrix_flow(flow_case)
        return session

    async def inventory(*_args: object) -> DatabaseInventory:
        if stage == "inventory":
            raise _matrix_flow(flow_case)
        return inventory_value

    async def storage(*_args: object) -> tuple[TableStorage, ...]:
        if stage == "storage":
            raise _matrix_flow(flow_case)
        return storage_value

    def id_factory() -> str:
        if stage == "id":
            raise _matrix_flow(flow_case)
        return "0123456789abcdef0123456789abcdef"

    with pytest.raises(BaseException) as raised:
        await create_current_schema_proof(
            session_factory=session_factory,
            initialize=lambda *_args: object(),
            inventory=inventory,
            read_storage=storage,
            id_factory=id_factory,
            now_ms=lambda: 123,
        )

    outgoing = raised.value
    if isinstance(outgoing, BaseExceptionGroup):
        outgoing = outgoing.exceptions[0]
    _assert_matrix_flow(outgoing, flow_case)
    assert "secret" not in repr(raised.value)
    assert session.closed is (stage not in ("id", "session"))
    assert session.created is False


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
        backup_filename="approved-backup.sql",
        backup_sha256="c" * 64,
        backup_byte_length=42,
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


class FlowReceiptHandle(ReceiptHandle):
    def __init__(
        self,
        events: list[object],
        failures: set[str],
        flow_type: type[BaseException],
    ) -> None:
        super().__init__(events)
        self.failures = failures
        self.flow_type = flow_type
        self.failed: set[str] = set()

    def _fail_once(self, name: str) -> None:
        if name in self.failures and name not in self.failed:
            self.failed.add(name)
            raise _secret_flow_control(self.flow_type)

    def write(self, value: str) -> int:
        self.events.append(("write", value))
        self._fail_once("write")
        return len(value)

    def close(self) -> None:
        self.events.append("close")
        self._fail_once("close")
        self.closed = True


class FlowReceiptWorld(ReceiptWorld):
    def __init__(
        self,
        root: Path,
        failures: set[str],
        flow_type: type[BaseException],
    ) -> None:
        super().__init__(root)
        self.failures = failures
        self.flow_type = flow_type
        self.failed: set[str] = set()
        self.handle = FlowReceiptHandle(self.events, failures, flow_type)

    def unlink_owned(self, path: Path, identity: object) -> bool:
        self.events.append(("unlink", path, identity))
        if "unlink" in self.failures and "unlink" not in self.failed:
            self.failed.add("unlink")
            raise _secret_flow_control(self.flow_type)
        return identity is self.identity


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

    expected = canonical_json(asdict(receipt))
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
    parsed = parse_preparation_receipt_document(expected)
    assert parsed == receipt
    assert canonical_receipt_hash(parsed) == canonical_receipt_hash(receipt)
    assert canonical_json(json.loads(expected)) == expected


def test_receipt_parser_and_loader_are_strict_and_hash_preserving() -> None:
    receipt = _preparation_receipt()
    document = canonical_json(asdict(receipt))
    reads: list[Path] = []
    payload = document.encode("utf-8")

    class Handle:
        def __enter__(self) -> Handle:
            return self

        def __exit__(self, *_args: object) -> None:
            reads.append(Path("closed"))

        def fileno(self) -> int:
            return 41

        def read(self, limit: int) -> bytes:
            assert limit == len(payload) + 1
            return payload

    info = SimpleNamespace(
        st_file_attributes=0,
        st_mode=stat.S_IFREG,
        st_dev=1,
        st_ino=2,
        st_size=len(payload),
        st_mtime_ns=3,
        st_ctime_ns=4,
    )
    path = Path("D:/external/approved-backup.readiness.json")

    loaded = load_preparation_receipt(
        path,
        opener=lambda value: reads.append(value) or Handle(),
        resolver=lambda value: value,
        lstat_reader=lambda _value: info,
        fstat_reader=lambda _descriptor: info,
    )

    assert reads == [path, Path("closed")]
    assert loaded == receipt
    assert type(loaded) is PreparationReceipt
    assert all(type(item) is StateReceipt for item in loaded.receipts)
    assert canonical_receipt_hash(loaded) == canonical_receipt_hash(receipt)


@pytest.mark.parametrize(
    ("path", "size"),
    [
        (Path("relative.readiness.json"), 1),
        (Path("D:/external/not-a-receipt.json"), 1),
        (
            command_module.REPOSITORY_ROOT / "inside.readiness.json",
            1,
        ),
        (Path("D:/external/large.readiness.json"), 1_000_001),
    ],
)
def test_receipt_loader_rejects_unsafe_paths_and_oversize_before_read(
    path: Path, size: int
) -> None:
    opens: list[Path] = []
    info = SimpleNamespace(
        st_file_attributes=0,
        st_mode=stat.S_IFREG,
        st_dev=1,
        st_ino=2,
        st_size=size,
        st_mtime_ns=3,
        st_ctime_ns=4,
    )

    class Handle:
        def __enter__(self) -> Handle:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def fileno(self) -> int:
            return 41

        def read(self, _limit: int) -> bytes:
            pytest.fail("unsafe or oversized receipt was read")

    with pytest.raises(ProductDatabasePreparationCommandError) as raised:
        load_preparation_receipt(
            path,
            opener=lambda value: opens.append(value) or Handle(),
            resolver=lambda value: value,
            lstat_reader=lambda _value: info,
            fstat_reader=lambda _descriptor: info,
        )

    assert str(raised.value) == "readiness receipt document is invalid"
    if size <= 1_000_000:
        assert opens == []


def test_receipt_loader_rejects_stat_read_size_race() -> None:
    calls = 0
    before = SimpleNamespace(
        st_file_attributes=0,
        st_mode=stat.S_IFREG,
        st_dev=1,
        st_ino=2,
        st_size=2,
        st_mtime_ns=3,
        st_ctime_ns=4,
    )
    after = SimpleNamespace(**{**vars(before), "st_mtime_ns": 5})

    class Handle:
        def __enter__(self) -> Handle:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def fileno(self) -> int:
            return 41

        def read(self, _limit: int) -> bytes:
            return b"{}"

    def fstat_reader(_descriptor: int) -> object:
        nonlocal calls
        calls += 1
        return before if calls == 1 else after

    with pytest.raises(ProductDatabasePreparationCommandError) as raised:
        load_preparation_receipt(
            Path("D:/external/approved.readiness.json"),
            opener=lambda _path: Handle(),
            resolver=lambda value: value,
            lstat_reader=lambda _path: before,
            fstat_reader=fstat_reader,
        )

    assert str(raised.value) == "readiness receipt document is invalid"


@pytest.mark.parametrize("failure_at", ("resolved-repository", "reparse"))
def test_receipt_loader_rejects_resolved_repository_and_reparse_before_open(
    failure_at: str,
) -> None:
    path = Path("D:/external/approved.readiness.json")
    opens: list[Path] = []
    info = SimpleNamespace(
        st_file_attributes=(0x400 if failure_at == "reparse" else 0),
        st_mode=stat.S_IFREG,
        st_dev=1,
        st_ino=2,
        st_size=2,
        st_mtime_ns=3,
        st_ctime_ns=4,
    )

    with pytest.raises(ProductDatabasePreparationCommandError) as raised:
        load_preparation_receipt(
            path,
            opener=lambda value: opens.append(value) or pytest.fail("opened"),
            resolver=(
                (lambda _value: command_module.REPOSITORY_ROOT / "inside.readiness.json")
                if failure_at == "resolved-repository"
                else (lambda value: value)
            ),
            lstat_reader=lambda _path: info,
            fstat_reader=lambda _descriptor: info,
        )

    assert str(raised.value) == "readiness receipt document is invalid"
    assert opens == []


def test_strict_nested_receipt_parsers_accept_only_exact_domain_documents() -> None:
    receipt = _preparation_receipt()
    state = receipt.receipts[0]
    backup = BackupReceipt(
        state=ReadinessState.BACKUP_CREATED.value,
        previous_receipt_hash=canonical_receipt_hash(state),
        source_database=LEGACY_DATABASE,
        backup_filename="approved.sql",
        backup_sha256="d" * 64,
        backup_byte_length=123,
        client_version="mysqldump  Ver 8.4.0",
        source_inventory_hash="e" * 64,
    )

    assert parse_state_receipt_document(canonical_json(asdict(state))) == state
    assert parse_backup_receipt_document(canonical_json(asdict(backup))) == backup
    assert parse_preparation_receipt_document(canonical_json(asdict(receipt))) == receipt

    for missing_key in ("backup_filename", "backup_byte_length"):
        missing = asdict(receipt)
        missing.pop(missing_key)
        with pytest.raises(ProductDatabasePreparationCommandError) as raised:
            parse_preparation_receipt_document(canonical_json(missing))
        assert str(raised.value) == "readiness receipt document is invalid"

    for extra_key in ("backup_path", "backup_size"):
        extra = asdict(receipt)
        extra[extra_key] = "secret-value"
        with pytest.raises(ProductDatabasePreparationCommandError) as raised:
            parse_preparation_receipt_document(canonical_json(extra))
        assert str(raised.value) == "readiness receipt document is invalid"
        assert "secret-value" not in repr(raised.value)

    invalid_documents: list[str] = []
    for value in (asdict(state), asdict(backup), asdict(receipt)):
        with_extra = dict(value)
        with_extra["preparationReceiptHash"] = "f" * 64
        invalid_documents.append(canonical_json(with_extra))
    spoofed_type = asdict(receipt)
    spoofed_type["style_count"] = True
    invalid_documents.append(canonical_json(spoofed_type))
    broken_chain = asdict(receipt)
    broken_chain["receipts"][1]["previous_receipt_hash"] = "f" * 64
    invalid_documents.append(canonical_json(broken_chain))
    invalid_documents.append('{"state":"x","state":"y"}')

    parsers = (
        parse_state_receipt_document,
        parse_backup_receipt_document,
        parse_preparation_receipt_document,
    )
    for document_value in invalid_documents:
        for parser in parsers:
            with pytest.raises(ProductDatabasePreparationCommandError) as raised:
                parser(document_value)
            assert str(raised.value) == "readiness receipt document is invalid"


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


@pytest.mark.parametrize("flow_type", FLOW_CONTROLS)
@pytest.mark.parametrize("failure_at", ("write", "close", "unlink"))
def test_receipt_flow_control_is_cloned_and_releases_owned_handle(
    tmp_path: Path,
    flow_type: type[BaseException],
    failure_at: str,
) -> None:
    external = Path(tmp_path.anchor) / "phase7b-receipt-tests" / tmp_path.name
    world = FlowReceiptWorld(external, {failure_at}, flow_type)

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

    _assert_clean_flow_control(raised.value, flow_type)
    assert world.handle.closed
    assert sum(event == "close" for event in world.events) == (
        2 if failure_at == "close" else 1
    )
    assert any(
        isinstance(event, tuple) and event[0] == "unlink"
        for event in world.events
    )


@pytest.mark.parametrize("flow_type", FLOW_CONTROLS)
def test_receipt_primary_precedes_cleanup_flow_and_resources_reach_zero(
    tmp_path: Path,
    flow_type: type[BaseException],
) -> None:
    external = Path(tmp_path.anchor) / "phase7b-receipt-tests" / tmp_path.name
    world = FlowReceiptWorld(external, {"close", "unlink"}, flow_type)

    with pytest.raises(BaseExceptionGroup) as raised:
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

    assert len(raised.value.exceptions) == 2
    _assert_clean_flow_control(raised.value.exceptions[0], flow_type)
    _assert_clean_flow_control(raised.value.exceptions[1], flow_type)
    assert world.handle.closed
    assert sum(event == "close" for event in world.events) == 2


@pytest.mark.parametrize("flow_case", FLOW_MATRIX_CASES)
@pytest.mark.parametrize(
    "stage",
    (
        "open",
        "acl",
        "owner-before-write",
        "write",
        "flush",
        "fsync",
        "close",
        "owner-before-link",
        "link",
        "owner-after-link",
        "unlink",
    ),
)
def test_receipt_all_stage_flow_matrix_closes_handle_and_owned_temp(
    tmp_path: Path, flow_case: str, stage: str
) -> None:
    external = Path(tmp_path.anchor) / "phase7b-receipt-matrix" / tmp_path.name

    class Handle(ReceiptHandle):
        def __init__(self, events: list[object]) -> None:
            super().__init__(events)
            self.failed: set[str] = set()

        def _stage(self, name: str) -> None:
            if stage == name and name not in self.failed:
                self.failed.add(name)
                raise _matrix_flow(flow_case)

        def write(self, value: str) -> int:
            self.events.append(("write", value))
            self._stage("write")
            return len(value)

        def flush(self) -> None:
            self.events.append("flush")
            self._stage("flush")

        def close(self) -> None:
            self.events.append("close")
            self.closed = True
            self._stage("close")

    class World(ReceiptWorld):
        def __init__(self) -> None:
            super().__init__(external)
            self.handle = Handle(self.events)
            self.temp_owned = False
            self.owner_checks = 0
            self.failed: set[str] = set()

        def _stage(self, name: str) -> None:
            if stage == name and name not in self.failed:
                self.failed.add(name)
                raise _matrix_flow(flow_case)

        def opener(self, directory: Path) -> tuple[Path, Handle, object]:
            self.events.append(("open", directory))
            self._stage("open")
            self.temp_owned = True
            return self.temporary, self.handle, self.identity

        def acl(self, path: Path) -> None:
            self.events.append(("acl", path))
            self._stage("acl")

        def fsync(self, descriptor: int) -> None:
            self.events.append(("fsync", descriptor))
            self._stage("fsync")

        def same_owner(self, path: Path, identity: object) -> bool:
            self.owner_checks += 1
            names = {
                1: "owner-before-write",
                2: "owner-before-link",
                3: "owner-after-link",
            }
            self._stage(names[self.owner_checks])
            return identity is self.identity

        def link(self, source: Path, target: Path) -> None:
            self.events.append(("link", source, target))
            self._stage("link")
            self.linked = True

        def unlink_owned(self, path: Path, identity: object) -> bool:
            self.events.append(("unlink", path, identity))
            self.temp_owned = False
            self._stage("unlink")
            if stage not in ("open", "unlink"):
                raise RuntimeError("secret-secondary-cleanup")
            return identity is self.identity

    world = World()
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

    outgoing = raised.value
    if isinstance(outgoing, BaseExceptionGroup):
        outgoing = outgoing.exceptions[0]
    _assert_matrix_flow(outgoing, flow_case)
    assert "secret" not in repr(raised.value)
    assert world.handle.closed is (stage != "open")
    assert world.temp_owned is False
    assert world.linked is (stage in ("owner-after-link", "unlink"))


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

    async def smoke(
        self, config: object, database: str, _runner: object = None
    ) -> object:
        self.events.append(("smoke", config, database))
        return object()

    def publish(
        self, receipt: PreparationReceipt, backup: Path
    ) -> Path:
        self.events.append(("publish", receipt, backup))
        return backup.with_suffix(".readiness.json")


def _ready_inventory(database: str) -> DatabaseInventory:
    counts = {name: 0 for name in created_table_names()}
    counts.update(
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
    rows = tuple(sorted(counts.items()))
    return DatabaseInventory(
        database=database,
        server_version="8.4.10",
        schema_version=EXPECTED_SCHEMA_VERSION,
        manifest_hash=manifest_hash(),
        structural_fingerprint="2" * 64,
        table_names=tuple(name for name, _count in rows),
        row_counts=rows,
        nonempty_table_count=sum(count > 0 for count in counts.values()),
        total_row_count=sum(counts.values()),
    )


class RealTask4ExecuteWorld(ExecuteWorld):
    def __init__(self) -> None:
        super().__init__(_preparation_receipt())
        self.target = _ready_inventory(NEW_DATABASE)
        proof_name = (
            "novel_creator_phase7b_restore_"
            "abcdefabcdefabcdefabcdefabcdefab"
        )
        proof_inventory = _proof_inventory(proof_name)
        proof_storage = tuple(
            TableStorage(name, "InnoDB", "utf8mb4_0900_ai_ci")
            for name in proof_inventory.table_names
        )
        self.proof = CurrentSchemaProof(
            proof_inventory,
            proof_storage,
            (proof_name,),
            (proof_name,),
        )
        self.target_storage = tuple(
            TableStorage(name, "InnoDB", "utf8mb4_0900_ai_ci")
            for name in self.target.table_names
        )
        backend_root = Path(__file__).resolve().parents[2]
        assets = load_asset_package(
            backend_root / "assets" / ASSET_VERSION / "manifest.json",
            mode="release",
        )
        market = load_market_source_package(
            backend_root / "assets" / MARKET_VERSION / "manifest.json"
        )
        self.assets = AssetSeedReport(
            package_version=assets.package_version,
            package_hash=canonical_hash(assets.manifest),
            style_count=len(assets.styles),
            card_count=len(assets.experience_cards),
            inserted=len(assets.styles) + len(assets.experience_cards),
            replayed=0,
            advanced=0,
        )
        self.market = MarketSourceSeedReport(
            package_version=market.package_version,
            source_count=len(market.sources),
            package_hash=canonical_hash(market.manifest),
            inserted=len(market.sources),
            replayed=0,
        )
        self.audit = OfficialDataAudit(
            asset_package_version=assets.package_version,
            asset_package_hash=canonical_hash(assets.manifest),
            style_content_hash=assets.manifest.styles_file.sha256,
            style_count=len(assets.styles),
            card_content_hash=assets.manifest.experience_cards_file.sha256,
            card_count=len(assets.experience_cards),
            market_package_version=market.package_version,
            market_package_hash=canonical_hash(market.manifest),
            market_content_hash=market.manifest.sources_file.sha256,
            market_source_count=len(market.sources),
            market_source_authority=tuple(
                sorted(source.stable_key for source in market.sources)
            ),
        )

    async def inventory_database(
        self, config: object, database: str
    ) -> DatabaseInventory:
        self.events.append(("inventory", config, database))
        return self.target if database == NEW_DATABASE else self.inventory

    async def restore_drill(self, *args: object) -> RestoreDrillResult:
        self.events.append(("restore", *args))
        restore_name = (
            "novel_creator_phase7b_restore_"
            "0123456789abcdef0123456789abcdef"
        )
        return RestoreDrillResult(
            replace(self.inventory, database=restore_name),
            (restore_name,),
            (restore_name,),
        )

    async def current_schema_proof(self, config: object) -> CurrentSchemaProof:
        self.events.append(("proof", config))
        return self.proof

    def database_boundary(self, config: object, database: str) -> object:
        self.events.append(("boundary", config, database))
        events = self.events
        initialized = InitializationResult(
            database_name=NEW_DATABASE,
            schema_version=EXPECTED_SCHEMA_VERSION,
            manifest_hash=manifest_hash(),
            table_count=len(created_table_names()),
        )

        class Boundary:
            async def __aenter__(self) -> NewDatabaseBoundaryState:
                events.append("boundary-enter")
                return NewDatabaseBoundaryState("created", initialized, None)

            async def __aexit__(self, *_args: object) -> bool:
                events.append("boundary-exit")
                return False

        return Boundary()

    async def seed_assets(self, config: object, database: str) -> AssetSeedReport:
        self.events.append(("seed-assets", config, database))
        return self.assets

    async def seed_market(
        self, config: object, database: str
    ) -> MarketSourceSeedReport:
        self.events.append(("seed-market", config, database))
        return self.market

    async def read_storage(
        self, config: object, database: str
    ) -> tuple[TableStorage, ...]:
        self.events.append(("storage", config, database))
        return self.target_storage

    async def audit_official_data(
        self, config: object, database: str
    ) -> OfficialDataAudit:
        self.events.append(("audit", config, database))
        return self.audit

    async def smoke(
        self, config: object, database: str, _runner: object = None
    ) -> SmokeResult:
        self.events.append(("smoke", config, database))
        return SmokeResult(provider_calls=0, outbound_requests=0)


@pytest.mark.asyncio
async def test_execute_wires_preflight_inventory_task4_and_publication_in_order(
    tmp_path: Path,
) -> None:
    world = RealTask4ExecuteWorld()
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
        browser_smoke_runner=lambda **_kwargs: pytest.fail("unused fake runner"),
        prepare_service=prepare_product_database,
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
    assert world.events[4] == (
        "inventory",
        world.events[2][1],  # type: ignore[index]
        LEGACY_DATABASE,
    )
    assert world.events[5][:5] == (  # type: ignore[index]
        "backup",
        world.pair,
        world.option,
        world.inventory,
        backup_dir,
    )
    assert world.events[5][5] == (  # type: ignore[index]
        "novel_creator-phase7b-11111111111111111111111111111111.sql"
    )
    assert world.events[5][6] == world.backup.previous_receipt_hash  # type: ignore[index]
    assert [
        event if isinstance(event, str) else event[0]
        for event in world.events[6:19]
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
    assert world.events[6][1:] == (  # type: ignore[index]
        config,
        world.pair,
        world.option,
        world.backup,
        world.inventory,
        backup_dir,
    )
    assert world.events[7] == ("inventory", config, LEGACY_DATABASE)
    assert world.events[8] == ("proof", config)
    assert world.events[9] == ("boundary", config, NEW_DATABASE)
    for index in (11, 12, 14, 15, 16):
        assert world.events[index][1:] == (config, NEW_DATABASE)  # type: ignore[index]
    assert world.events[13] == ("inventory", config, NEW_DATABASE)
    published_receipt = world.events[19][1]  # type: ignore[index]
    assert type(published_receipt) is PreparationReceipt
    assert world.events[19] == (
        "publish",
        published_receipt,
        backup_dir / world.backup.backup_filename,
    )
    assert lines == [
        "mode=execute",
        "legacy_database=novel_creator",
        "new_database=novel_creator_v113",
        "stage=awaiting-cutover-approval",
        f"receipt_hash={canonical_receipt_hash(published_receipt)}",
    ]
    assert published_receipt.legacy_inventory_hash == inventory_hash(world.inventory)
    assert published_receipt.new_inventory_hash == inventory_hash(world.target)
    assert tuple(item.state for item in published_receipt.receipts) == tuple(
        state.value for state in tuple(ReadinessState)[:7]
    )
    rendered = "\n".join(lines)
    assert "top-secret" not in rendered
    assert str(backup_dir) not in rendered
    assert "11111111111111111111111111111111" not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("browser_stderr", "expected_browser_stage"),
    (
        (
            "phase7b browser lifecycle failed\n"
            "PHASE7B_BROWSER_FAILURE_STAGE=backend-start\n"
            "password=secret",
            "backend-start",
        ),
        (
            "PHASE7B_BROWSER_FAILURE_STAGE=secret-stage\npassword=secret",
            "unavailable",
        ),
    ),
)
async def test_malformed_browser_smoke_rolls_back_task4_and_never_publishes_receipt(
    tmp_path: Path, browser_stderr: str, expected_browser_stage: str
) -> None:
    world = RealTask4ExecuteWorld()
    browser_calls: list[object] = []

    def malformed_browser(**kwargs: object) -> object:
        browser_calls.append(kwargs)
        return SimpleNamespace(
            returncode=1,
            stdout="PHASE7B_BROWSER_SMOKE_SUMMARY={\"scenario\":1}",
            stderr=browser_stderr,
        )

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
        smoke=command_module._default_smoke,
        browser_smoke_runner=malformed_browser,
        prepare_service=prepare_product_database,
        publish_receipt=world.publish,
        id_factory=lambda: "1" * 32,
    )
    output: list[str] = []
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
        await run_cli(argv, dependencies=dependencies, output=output.append)

    assert str(raised.value) == "product database preparation execution failed"
    assert "secret" not in repr(raised.value)
    assert browser_calls and browser_calls[0]["environment"]["MYSQL_DB"] == NEW_DATABASE  # type: ignore[index]
    assert "boundary-exit" in world.events
    assert not any(
        isinstance(event, tuple) and event[0] == "publish"
        for event in world.events
    )
    assert output == [
        "outcome=failed",
        "stage=browser-smoke",
        "cleanup=no-failure-reported",
        f"browser_stage={expected_browser_stage}",
    ]


def _windows_acl_observation(
    path: Path, powershell_executable: str
) -> dict[str, object]:
    script = """
$ErrorActionPreference = 'Stop'
$rules = @((Get-Acl -LiteralPath $env:PHASE7B_ACL_LITERAL_PATH).Access |
    ForEach-Object {
    [pscustomobject]@{
        sid = $_.IdentityReference.Translate(
            [System.Security.Principal.SecurityIdentifier]
        ).Value
        rights = [uint32]$_.FileSystemRights
        access_type = [int]$_.AccessControlType
        inherited = [bool]$_.IsInherited
        inheritance_flags = [int]$_.InheritanceFlags
        propagation_flags = [int]$_.PropagationFlags
    }
})
$observation = [pscustomobject]@{
    currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    rules = $rules
}
ConvertTo-Json -InputObject $observation -Compress -Depth 3
"""
    result = subprocess.run(
        [
            powershell_executable,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        check=False,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=5,
        env={**os.environ, "PHASE7B_ACL_LITERAL_PATH": os.fspath(path)},
    )
    assert result.returncode == 0
    observed = json.loads(result.stdout)
    assert isinstance(observed, dict)
    return observed


def _set_windows_legacy_directory_acl(path: Path, sid: str) -> None:
    result = subprocess.run(
        [
            "icacls",
            os.fspath(path),
            "/inheritance:r",
            "/grant:r",
            f"*{sid}:(R,W)",
        ],
        check=False,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5,
    )
    assert result.returncode == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows private option ACL")
def test_default_dependencies_repairs_legacy_directory_before_option_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    powershell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("PowerShell ACL observation is unavailable")
    repository = tmp_path / "repository"
    repository.mkdir()
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setattr(command_module, "REPOSITORY_ROOT", repository)
    sid: str | None = None
    option: Path | None = None
    option_acl: dict[str, object] = {}
    failure: BaseException | None = None
    residue_lengths: list[int] = []
    cleanup_failures: list[str] = []

    try:
        initial_acl = _windows_acl_observation(backup_dir, powershell)
        observed_sid = initial_acl["currentSid"]
        assert isinstance(observed_sid, str)
        sid = observed_sid
        _set_windows_legacy_directory_acl(backup_dir, sid)
        dependencies = _default_dependencies()
        with dependencies.option_file(
            {
                "host": "127.0.0.1",
                "port": 3307,
                "user": "writer",
                "password": "test-only",
                "db": LEGACY_DATABASE,
            },
            backup_dir,
        ) as option:
            option_acl = _windows_acl_observation(option, powershell)
    except BaseException as error:
        failure = error
    finally:
        try:
            residue_lengths = [path.stat().st_size for path in backup_dir.iterdir()]
        except BaseException:
            cleanup_failures.append("residue observation failed")
        try:
            apply_private_permissions(backup_dir, is_directory=True)
        except BaseException:
            cleanup_failures.append("parent permission reset failed")
        try:
            residues = list(backup_dir.iterdir())
        except BaseException:
            cleanup_failures.append("residue enumeration failed")
            residues = []
        for residue in residues:
            try:
                apply_private_permissions(residue, is_directory=False)
            except BaseException:
                cleanup_failures.append("child permission reset failed")
            try:
                residue.unlink()
            except BaseException:
                cleanup_failures.append("child unlink failed")

    assert cleanup_failures == []
    assert failure is None, type(failure).__name__ if failure is not None else None
    assert sid is not None
    assert option_acl == {
        "currentSid": sid,
        "rules": [
            {
                "sid": sid,
                "rights": 0x001F01FF,
                "access_type": 0,
                "inherited": False,
                "inheritance_flags": 0,
                "propagation_flags": 0,
            }
        ],
    }
    assert residue_lengths == []
    assert option is not None
    assert not option.exists()
    assert sum(1 for _ in backup_dir.iterdir()) == 0


def test_default_dependencies_wire_public_resources_with_exact_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.config as config_module
    import backend.services.product_database_backup as backup_module

    calls: list[object] = []
    pair = object()
    option_context = object()
    backup_value = object()
    validated_backup_dir = Path("D:/validated-backups")
    config = {
        "host": "127.0.0.1",
        "port": 3307,
        "user": "writer",
        "password": "injected-only",
        "db": LEGACY_DATABASE,
    }

    def runner(command: list[str], **kwargs: object) -> object:
        calls.append(("run", command, kwargs))
        return object()

    def pair_factory(
        dump: Path, mysql: Path, repository: Path, version_runner: object
    ) -> object:
        calls.append(("pair", dump, mysql, repository))
        assert callable(version_runner)
        version_runner(dump)  # type: ignore[operator]
        version_runner(mysql)  # type: ignore[operator]
        return pair

    def option_factory(*args: object, **kwargs: object) -> object:
        calls.append(("option", args, kwargs))
        return option_context

    def directory_factory(directory: Path, repository: Path) -> Path:
        calls.append(("directory-preflight", directory, repository))
        return validated_backup_dir

    def connection_factory(*args: object) -> None:
        calls.append(("connection", args))

    def backup_factory(*args: object, **kwargs: object) -> object:
        calls.append(("backup", args, kwargs))
        return backup_value

    monkeypatch.setattr(command_module.subprocess, "run", runner)
    monkeypatch.setattr(backup_module, "preflight_client_pair", pair_factory)
    monkeypatch.setattr(
        backup_module, "preflight_backup_directory", directory_factory
    )
    monkeypatch.setattr(backup_module, "private_mysql_option_file", option_factory)
    monkeypatch.setattr(
        backup_module, "preflight_client_connection", connection_factory
    )
    monkeypatch.setattr(backup_module, "create_logical_backup", backup_factory)
    monkeypatch.setattr(config_module, "require_mysql_config", lambda: config)

    dependencies = _default_dependencies()
    dump = Path("D:/mysql/mysqldump.exe")
    mysql = Path("D:/mysql/mysql.exe")
    repository = Path("D:/repository")
    backup_dir = Path("D:/backups")
    option = Path("D:/backups/private.cnf")
    inventory = _empty_inventory(LEGACY_DATABASE)

    assert type(dependencies) is PreparationCommandDependencies
    assert dependencies.read_config() is config
    assert dependencies.preflight_clients(dump, mysql, repository) is pair
    assert dependencies.option_file(config, backup_dir) is option_context
    dependencies.preflight_connection(pair, option)
    assert (
        dependencies.create_backup(
            pair, option, inventory, backup_dir, "approved.sql", "a" * 64
        )
        is backup_value
    )
    assert dependencies.inventory_database is command_module._default_inventory
    assert dependencies.restore_drill is command_module._default_restore_drill
    assert (
        dependencies.current_schema_proof
        is command_module._default_current_schema_proof
    )
    assert (
        dependencies.database_boundary
        is command_module._default_database_boundary
    )
    assert dependencies.seed_assets is command_module._default_seed_assets
    assert dependencies.seed_market is command_module._default_seed_market
    assert dependencies.read_storage is command_module._default_storage
    assert dependencies.audit_official_data is command_module._default_official_audit
    assert dependencies.smoke is command_module._default_smoke
    assert (
        dependencies.browser_smoke_runner
        is command_module._default_browser_smoke_runner
    )
    assert dependencies.prepare_service is prepare_product_database
    assert dependencies.publish_receipt is publish_readiness_receipt
    assert calls == [
        ("pair", dump, mysql, repository),
        (
            "run",
            [str(dump), "--version"],
            {"capture_output": True, "text": True, "check": False},
        ),
        (
            "run",
            [str(mysql), "--version"],
            {"capture_output": True, "text": True, "check": False},
        ),
        (
            "directory-preflight",
            backup_dir,
            command_module.REPOSITORY_ROOT,
        ),
        (
            "option",
            (
                {
                    "host": "127.0.0.1",
                    "port": 3307,
                    "user": "writer",
                    "password": "injected-only",
                },
                validated_backup_dir,
            ),
            {"repository_root": command_module.REPOSITORY_ROOT},
        ),
        ("connection", (pair, option, runner)),
        (
            "backup",
            (
                pair,
                option,
                inventory,
                backup_dir,
                "approved.sql",
                "a" * 64,
            ),
            {
                "runner": runner,
                "repository_root": command_module.REPOSITORY_ROOT,
            },
        ),
    ]


def _browser_summary(**changes: object) -> str:
    value: dict[str, object] = {
        "firstStage": None,
        "firstCause": None,
        "scenarioCount": 1,
        "providerCalls": 0,
        "outboundRequests": 0,
        "processCount": 0,
        "portCount": 0,
        "rootCount": 0,
        "artifactCount": 0,
    }
    value.update(changes)
    return "PHASE7B_BROWSER_SMOKE_SUMMARY=" + canonical_json(value)


def _browser_internal_evidence(**changes: object) -> str:
    value = json.loads(_browser_summary(**changes).split("=", 1)[1])
    value.pop("rootCount")
    return "PHASE7B_BROWSER_INTERNAL_EVIDENCE=" + canonical_json(value)


@pytest.mark.parametrize(
    ("returncode", "stderr", "expected"),
    (
        (1, "PHASE7B_BROWSER_FAILURE_STAGE=vite-start", "vite-start"),
        (1, "PHASE7B_BROWSER_FAILURE_STAGE=secret-stage", None),
        (
            1,
            "PHASE7B_BROWSER_FAILURE_STAGE=vite-start\n"
            "PHASE7B_BROWSER_FAILURE_STAGE=backend-start",
            None,
        ),
        (1, "password=secret", None),
        (0, "PHASE7B_BROWSER_FAILURE_STAGE=vite-start", None),
    ),
)
def test_browser_failure_stage_accepts_one_allowlisted_nonzero_exit_marker(
    returncode: int, stderr: str, expected: str | None
) -> None:
    completed = SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)

    assert command_module._browser_failure_stage(completed) == expected


@pytest.mark.asyncio
async def test_default_smoke_invokes_explicit_browser_runner_and_validates_summary() -> None:
    calls: list[object] = []

    def runner(**kwargs: object) -> object:
        calls.append(kwargs)
        return SimpleNamespace(
            returncode=0, stdout=_browser_internal_evidence(), stderr=""
        )

    result = await command_module._default_smoke({}, NEW_DATABASE, runner)

    assert result == SmokeResult(provider_calls=0, outbound_requests=0)
    assert calls == [
        {
            "command": ("node", "frontend/e2e/run-phase7b.mjs"),
            "cwd": command_module.REPOSITORY_ROOT,
            "environment": {
                **dict(command_module.os.environ),
                "MYSQL_DB": NEW_DATABASE,
                "MARKET_SCHEDULER_ENABLED": "false",
            },
            "timeout_seconds": 300,
            "root_lease_factory": command_module._open_browser_root_lease,
        }
    ]


def test_default_browser_smoke_runner_uses_owned_windows_job_and_exact_task_contract(
    tmp_path: Path,
) -> None:
    calls: list[object] = []
    node = tmp_path / "node.exe"
    node.write_bytes(b"")
    environment = {"MYSQL_DB": NEW_DATABASE, "ONLY_TEST": "yes"}

    class Child:
        returncode = 0

        def communicate(self, *, timeout: float) -> tuple[str, str]:
            calls.append(("communicate", timeout))
            return _browser_internal_evidence(), "password=secret"

    class Guard:
        active_processes = 3

        def cleanup(self, *_args: object, **_kwargs: object) -> list[BaseException]:
            return []

    child = Child()
    guard = Guard()

    class Lease:
        def delete_owned(
            self, path: Path, _expected_identity: tuple[int, int]
        ) -> None:
            calls.append("delete-pending")
            command_module.shutil.rmtree(path)

        def close(self) -> None:
            calls.append("lease-close")

    def root_lease_factory(path: Path, expected_identity: tuple[int, int]) -> object:
        calls.append(("lease-open", path, expected_identity))
        return Lease()

    def spawn_guarded(command: tuple[str, ...], kwargs: dict, **options: object):
        calls.append(("spawn", command, kwargs, options))
        return child, guard

    def stop_process(actual_child: object, *, guard: object) -> list[BaseException]:
        calls.append(("stop-tree", actual_child, guard))
        Guard.active_processes = 0
        return []

    result = command_module._default_browser_smoke_runner(
        command=("node", "frontend/e2e/run-phase7b.mjs"),
        cwd=command_module.REPOSITORY_ROOT,
        environment=environment,
        timeout_seconds=300,
        executable_resolver=lambda name: str(node) if name == "node" else None,
        guarded_spawn=spawn_guarded,
        stop_process=stop_process,
        nonce_factory=lambda: "a" * 32,
        temp_parent=tmp_path / "owned",
        root_lease_factory=root_lease_factory,
    )

    assert result.returncode == 0
    assert result.stdout == _browser_internal_evidence()
    assert result.stderr == "password=secret"
    assert calls[0][0] == "lease-open"
    spawn = calls[1]
    assert spawn[0] == "spawn"
    assert spawn[1] == (str(node.resolve()), "frontend/e2e/run-phase7b.mjs")
    assert spawn[2]["cwd"] == command_module.REPOSITORY_ROOT
    assert spawn[2]["shell"] is False
    assert spawn[2]["stdout"] is subprocess.PIPE
    assert spawn[2]["stderr"] is subprocess.PIPE
    assert spawn[2]["text"] is True
    assert spawn[2]["env"]["MYSQL_DB"] == NEW_DATABASE
    assert spawn[2]["env"]["ONLY_TEST"] == "yes"
    assert spawn[2]["env"]["PHASE7B_BROWSER_TASK_NONCE"] == "a" * 32
    task_root = Path(spawn[2]["env"]["PHASE7B_BROWSER_TASK_ROOT"])
    assert task_root.is_absolute()
    assert spawn[3]["platform_name"] == "nt"
    assert calls[2] == ("communicate", 240)
    assert calls[3] == ("stop-tree", child, guard)
    assert calls[4] == "delete-pending"
    assert calls[5] == "lease-close"
    assert Guard.active_processes == 0
    assert not task_root.exists()


@pytest.mark.parametrize(
    ("primary", "expected_type"),
    (
        (subprocess.TimeoutExpired("secret-node", 240), ProductDatabasePreparationCommandError),
        (asyncio.CancelledError("secret-cancel"), asyncio.CancelledError),
        (KeyboardInterrupt("secret-keyboard"), KeyboardInterrupt),
        (SystemExit(7), SystemExit),
        (SystemExit("secret-exit"), SystemExit),
    ),
)
def test_browser_smoke_runner_keeps_primary_first_and_cleans_tree_and_root(
    tmp_path: Path, primary: BaseException, expected_type: type[BaseException]
) -> None:
    node = tmp_path / "node.exe"
    node.write_bytes(b"")
    calls: list[object] = []

    class Child:
        returncode = None

        def communicate(self, *, timeout: float) -> tuple[str, str]:
            calls.append(("communicate", timeout))
            raise primary

    class Guard:
        active_processes = 4

        def cleanup(self, *_args: object, **_kwargs: object) -> list[BaseException]:
            return []

    child = Child()
    guard = Guard()

    def spawn_guarded(*_args: object, **_kwargs: object):
        return child, guard

    def stop_process(actual_child: object, *, guard: object) -> list[BaseException]:
        calls.append(("stop-tree", actual_child, guard))
        Guard.active_processes = 0
        return [RuntimeError("secret-cleanup")]

    with pytest.raises(BaseExceptionGroup) as raised:
        command_module._default_browser_smoke_runner(
            command=("node", "frontend/e2e/run-phase7b.mjs"),
            cwd=command_module.REPOSITORY_ROOT,
            environment={"MYSQL_DB": NEW_DATABASE},
            timeout_seconds=300,
            executable_resolver=lambda _name: str(node),
            guarded_spawn=spawn_guarded,
            stop_process=stop_process,
            nonce_factory=lambda: "b" * 32,
            temp_parent=tmp_path / "owned",
        )

    first = raised.value.exceptions[0]
    assert type(first) is expected_type
    if expected_type is SystemExit:
        assert first.code == (7 if type(primary.code) is int else None)
    assert "secret" not in repr(raised.value)
    assert calls == [
        ("communicate", 240),
        ("stop-tree", child, guard),
    ]
    assert Guard.active_processes == 0
    assert list((tmp_path / "owned").iterdir()) == []


def test_browser_smoke_runner_rejects_unapproved_command_before_spawn(
    tmp_path: Path,
) -> None:
    called = False

    def resolver(_name: str) -> str:
        nonlocal called
        called = True
        return str(tmp_path / "node.exe")

    with pytest.raises(ProductDatabasePreparationCommandError) as raised:
        command_module._default_browser_smoke_runner(
            command=("npm", "run", "test:browser:phase7b"),
            cwd=command_module.REPOSITORY_ROOT,
            environment={"MYSQL_DB": NEW_DATABASE},
            timeout_seconds=300,
            executable_resolver=resolver,
            temp_parent=tmp_path / "owned",
        )

    assert str(raised.value) == "readiness smoke failed"
    assert called is False


def test_browser_smoke_runner_rejects_stale_dispatcher_before_spawn(
    tmp_path: Path,
) -> None:
    called = False

    def resolver(_name: str) -> str:
        nonlocal called
        called = True
        return str(tmp_path / "node.exe")

    with pytest.raises(ProductDatabasePreparationCommandError) as raised:
        command_module._default_browser_smoke_runner(
            command=("node", "scripts/run-tests.mjs", "browser-phase7b"),
            cwd=command_module.REPOSITORY_ROOT,
            environment={"MYSQL_DB": NEW_DATABASE},
            timeout_seconds=300,
            executable_resolver=resolver,
            temp_parent=tmp_path / "owned",
        )

    assert str(raised.value) == "readiness smoke failed"
    assert called is False


@pytest.mark.parametrize("failure", ("spawn", "stop", "root-replacement"))
def test_browser_smoke_runner_failure_stages_are_safe_and_cleanup_owned_resources(
    tmp_path: Path, failure: str
) -> None:
    node = tmp_path / "node.exe"
    node.write_bytes(b"")
    calls: list[object] = []
    task_root: Path | None = None

    class Child:
        returncode = 0

        def communicate(self, *, timeout: float) -> tuple[str, str]:
            calls.append(("communicate", timeout))
            return _browser_internal_evidence(), "secret-stderr"

    child = Child()
    guard = SimpleNamespace(
        active_processes=2,
        cleanup=lambda *_args, **_kwargs: [],
    )

    def spawn_guarded(_command: object, kwargs: dict, **_options: object):
        nonlocal task_root
        task_root = Path(kwargs["env"]["PHASE7B_BROWSER_TASK_ROOT"])
        calls.append("spawn")
        if failure == "spawn":
            raise RuntimeError("secret-spawn")
        return child, guard

    def stop_process(_child: object, *, guard: object) -> list[BaseException]:
        calls.append("stop-tree")
        guard.active_processes = 0
        if failure == "stop":
            return [RuntimeError("secret-stop")]
        return []

    def remove_temp(path: Path) -> None:
        calls.append("remove-root")
        command_module.shutil.rmtree(path)
        if failure == "root-replacement":
            path.mkdir()

    with pytest.raises(ProductDatabasePreparationCommandError) as raised:
        command_module._default_browser_smoke_runner(
            command=("node", "frontend/e2e/run-phase7b.mjs"),
            cwd=command_module.REPOSITORY_ROOT,
            environment={"MYSQL_DB": NEW_DATABASE},
            timeout_seconds=300,
            executable_resolver=lambda _name: str(node),
            guarded_spawn=spawn_guarded,
            stop_process=stop_process,
            nonce_factory=lambda: "c" * 32,
            temp_parent=tmp_path / "owned",
            remove_temp=remove_temp,
            root_lease_factory=lambda _path, _identity: SimpleNamespace(
                delete_owned=lambda path, _expected: remove_temp(path),
                close=lambda: None,
            ),
        )

    assert str(raised.value) == "readiness smoke failed"
    assert "secret" not in repr(raised.value)
    assert task_root is not None
    if failure == "spawn":
        assert calls == ["spawn", "remove-root"]
        assert not task_root.exists()
    elif failure == "stop":
        assert calls == ["spawn", ("communicate", 240), "stop-tree", "remove-root"]
        assert guard.active_processes == 0
        assert not task_root.exists()
    else:
        assert calls == ["spawn", ("communicate", 240), "stop-tree", "remove-root"]
        assert guard.active_processes == 0
        assert task_root.is_dir()


def test_browser_smoke_runner_retries_transient_owned_root_removal(
    tmp_path: Path,
) -> None:
    node = tmp_path / "node.exe"
    node.write_bytes(b"")
    removals: list[Path] = []

    class Child:
        returncode = 0

        def communicate(self, *, timeout: float) -> tuple[str, str]:
            return _browser_internal_evidence(), ""

    def spawn_guarded(_command: object, _kwargs: dict, **_options: object):
        return Child(), SimpleNamespace(cleanup=lambda *_args, **_kwargs: [])

    def remove_temp(path: Path) -> None:
        removals.append(path)
        if len(removals) == 1:
            raise PermissionError("secret transient sharing violation")
        command_module.shutil.rmtree(path)

    with pytest.raises(ProductDatabasePreparationCommandError):
        command_module._default_browser_smoke_runner(
            command=("node", "frontend/e2e/run-phase7b.mjs"),
            cwd=command_module.REPOSITORY_ROOT,
            environment={"MYSQL_DB": NEW_DATABASE},
            timeout_seconds=300,
            executable_resolver=lambda _name: str(node),
            guarded_spawn=lambda *_args, **_kwargs: pytest.fail("must not spawn"),
            nonce_factory=lambda: "d" * 32,
            temp_parent=tmp_path / "owned",
            remove_temp=remove_temp,
            root_lease_factory=lambda _path, _identity: (_ for _ in ()).throw(
                RuntimeError("secret acquisition failure")
            ),
        )

    assert len(removals) == 2
    assert not removals[0].exists()


def test_browser_smoke_runner_rejects_malformed_guard_and_stops_returned_child(
    tmp_path: Path,
) -> None:
    node = tmp_path / "node.exe"
    node.write_bytes(b"")
    calls: list[object] = []

    class Child:
        returncode = None

        def communicate(self, *, timeout: float) -> tuple[str, str]:
            pytest.fail("malformed guard must fail before child execution")

    child = Child()

    def stop_unassigned(actual_child: object) -> list[BaseException]:
        calls.append(("stop-unassigned", actual_child))
        return []

    with pytest.raises(ProductDatabasePreparationCommandError) as raised:
        command_module._default_browser_smoke_runner(
            command=("node", "frontend/e2e/run-phase7b.mjs"),
            cwd=command_module.REPOSITORY_ROOT,
            environment={"MYSQL_DB": NEW_DATABASE},
            timeout_seconds=300,
            executable_resolver=lambda _name: str(node),
            guarded_spawn=lambda *_args, **_kwargs: (child, None),
            stop_unassigned=stop_unassigned,
            nonce_factory=lambda: "e" * 32,
            temp_parent=tmp_path / "owned",
        )

    assert str(raised.value) == "readiness smoke failed"
    assert calls == [("stop-unassigned", child)]
    assert list((tmp_path / "owned").iterdir()) == []


def test_browser_smoke_runner_cleans_acquired_identity_not_precleanup_replacement(
    tmp_path: Path,
) -> None:
    node = tmp_path / "node.exe"
    node.write_bytes(b"")
    task_root: Path | None = None
    moved_root: Path | None = None

    class Child:
        returncode = 0

        def communicate(self, *, timeout: float) -> tuple[str, str]:
            nonlocal moved_root
            assert task_root is not None
            marker = task_root / ".m2-session-owner.json"
            marker_bytes = marker.read_bytes()
            moved_root = task_root.with_name(task_root.name + "-moved")
            task_root.rename(moved_root)
            task_root.mkdir()
            (task_root / marker.name).write_bytes(marker_bytes)
            return _browser_internal_evidence(), ""

    def spawn_guarded(_command: object, kwargs: dict, **_options: object):
        nonlocal task_root
        task_root = Path(kwargs["env"]["PHASE7B_BROWSER_TASK_ROOT"])
        return Child(), SimpleNamespace(cleanup=lambda *_args, **_kwargs: [])

    class Lease:
        def delete_owned(
            self, path: Path, expected_identity: tuple[int, int]
        ) -> None:
            current = path.stat(follow_symlinks=False)
            if (current.st_dev, current.st_ino) != expected_identity:
                raise OSError

        def close(self) -> None:
            return None

    with pytest.raises(BaseException) as raised:
        command_module._default_browser_smoke_runner(
            command=("node", "frontend/e2e/run-phase7b.mjs"),
            cwd=command_module.REPOSITORY_ROOT,
            environment={"MYSQL_DB": NEW_DATABASE},
            timeout_seconds=300,
            executable_resolver=lambda _name: str(node),
            guarded_spawn=spawn_guarded,
            stop_process=lambda *_args, **_kwargs: [],
            nonce_factory=lambda: "f" * 32,
            temp_parent=tmp_path / "owned",
            root_lease_factory=lambda _path, _identity: Lease(),
        )

    assert "secret" not in repr(raised.value)
    assert task_root is not None and task_root.is_dir()
    assert moved_root is not None and not moved_root.exists()


def test_browser_smoke_runner_retries_transient_directory_lease_close(
    tmp_path: Path,
) -> None:
    node = tmp_path / "node.exe"
    node.write_bytes(b"")
    closes = 0

    class Child:
        returncode = 0

        def communicate(self, *, timeout: float) -> tuple[str, str]:
            return _browser_internal_evidence(), ""

    class Lease:
        def delete_owned(
            self, path: Path, _expected_identity: tuple[int, int]
        ) -> None:
            command_module.shutil.rmtree(path)

        def close(self) -> None:
            nonlocal closes
            closes += 1
            if closes == 1:
                raise PermissionError("secret lease close sharing violation")

    result = command_module._default_browser_smoke_runner(
        command=("node", "frontend/e2e/run-phase7b.mjs"),
        cwd=command_module.REPOSITORY_ROOT,
        environment={"MYSQL_DB": NEW_DATABASE},
        timeout_seconds=300,
        executable_resolver=lambda _name: str(node),
        guarded_spawn=lambda *_args, **_kwargs: (
            Child(),
            SimpleNamespace(cleanup=lambda *_args, **_kwargs: []),
        ),
        stop_process=lambda *_args, **_kwargs: [],
        nonce_factory=lambda: "1" * 32,
        temp_parent=tmp_path / "owned",
        root_lease_factory=lambda _path, _identity: Lease(),
    )

    assert result.returncode == 0
    assert closes == 2
    assert list((tmp_path / "owned").iterdir()) == []


def test_browser_smoke_runner_establishes_handle_delete_before_lease_close(
    tmp_path: Path,
) -> None:
    node = tmp_path / "node.exe"
    node.write_bytes(b"")
    task_root: Path | None = None
    escaped = tmp_path / "escaped-owned-root"
    calls: list[str] = []

    class Child:
        returncode = 0

        def communicate(self, *, timeout: float) -> tuple[str, str]:
            return _browser_internal_evidence(), ""

    class Lease:
        def delete_owned(
            self, path: Path, _expected_identity: tuple[int, int]
        ) -> None:
            calls.append("delete-pending")
            command_module.shutil.rmtree(path)

        def close(self) -> None:
            calls.append("lease-close")
            assert task_root is not None
            if task_root.exists():
                task_root.rename(escaped)
                task_root.mkdir()

    def spawn_guarded(_command: object, kwargs: dict, **_options: object):
        nonlocal task_root
        task_root = Path(kwargs["env"]["PHASE7B_BROWSER_TASK_ROOT"])
        return Child(), SimpleNamespace(cleanup=lambda *_args, **_kwargs: [])

    result = command_module._default_browser_smoke_runner(
        command=("node", "frontend/e2e/run-phase7b.mjs"),
        cwd=command_module.REPOSITORY_ROOT,
        environment={"MYSQL_DB": NEW_DATABASE},
        timeout_seconds=300,
        executable_resolver=lambda _name: str(node),
        guarded_spawn=spawn_guarded,
        stop_process=lambda *_args, **_kwargs: [],
        nonce_factory=lambda: "2" * 32,
        temp_parent=tmp_path / "owned",
        root_lease_factory=lambda _path, _identity: Lease(),
    )

    assert result.returncode == 0
    assert calls == ["delete-pending", "lease-close"]
    assert not escaped.exists()
    assert task_root is not None and not task_root.exists()


def test_browser_root_lease_identity_failure_closes_handle_and_removes_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.services.product_database_backup as backup_module

    node = tmp_path / "node.exe"
    node.write_bytes(b"")
    closed: list[int] = []
    spawn_called = False

    class Creator:
        argtypes: object = None
        restype: object = None

        def __call__(self, *_args: object) -> int:
            return 123

    monkeypatch.setattr(
        backup_module,
        "_kernel32",
        lambda: SimpleNamespace(CreateFileW=Creator()),
    )
    monkeypatch.setattr(
        backup_module,
        "_identity_from_handle",
        lambda _handle: (_ for _ in ()).throw(OSError("secret identity read")),
    )
    monkeypatch.setattr(
        backup_module, "_close_windows_handle", lambda handle: closed.append(handle)
    )

    def spawn_guarded(*_args: object, **_kwargs: object):
        nonlocal spawn_called
        spawn_called = True
        pytest.fail("identity failure must happen before spawn")

    with pytest.raises(ProductDatabasePreparationCommandError) as raised:
        command_module._default_browser_smoke_runner(
            command=("node", "frontend/e2e/run-phase7b.mjs"),
            cwd=command_module.REPOSITORY_ROOT,
            environment={"MYSQL_DB": NEW_DATABASE},
            timeout_seconds=300,
            executable_resolver=lambda _name: str(node),
            guarded_spawn=spawn_guarded,
            nonce_factory=lambda: "3" * 32,
            temp_parent=tmp_path / "owned",
        )

    assert str(raised.value) == "readiness smoke failed"
    assert "secret" not in repr(raised.value)
    assert closed == [123]
    assert spawn_called is False
    assert list((tmp_path / "owned").iterdir()) == []


@pytest.mark.parametrize("outside_parent", (False, True))
def test_browser_root_lease_acquisition_race_preserves_replacement_and_recovers_exact_owner(
    tmp_path: Path, outside_parent: bool
) -> None:
    node = tmp_path / "node.exe"
    node.write_bytes(b"")
    task_root: Path | None = None
    alias: Path | None = None

    def lease_factory(path: Path, _expected_identity: tuple[int, int]) -> object:
        nonlocal task_root, alias
        task_root = path
        marker = path / ".m2-session-owner.json"
        marker_bytes = marker.read_bytes()
        alias = (
            tmp_path / "escaped-original"
            if outside_parent
            else path.with_name(path.name + "-alias")
        )
        path.rename(alias)
        path.mkdir()
        (path / marker.name).write_bytes(marker_bytes)
        (path / "replacement-proof.txt").write_text("replacement", encoding="utf-8")
        raise RuntimeError("secret acquisition identity mismatch")

    with pytest.raises(BaseException) as raised:
        command_module._default_browser_smoke_runner(
            command=("node", "frontend/e2e/run-phase7b.mjs"),
            cwd=command_module.REPOSITORY_ROOT,
            environment={"MYSQL_DB": NEW_DATABASE},
            timeout_seconds=300,
            executable_resolver=lambda _name: str(node),
            guarded_spawn=lambda *_args, **_kwargs: pytest.fail("must not spawn"),
            nonce_factory=lambda: "4" * 32,
            temp_parent=tmp_path / "owned",
            root_lease_factory=lease_factory,
        )

    assert "secret" not in repr(raised.value)
    assert task_root is not None
    assert (task_root / "replacement-proof.txt").read_text(encoding="utf-8") == "replacement"
    assert alias is not None
    assert alias.exists() is outside_parent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("returncode", "stdout"),
    (
        (1, _browser_summary()),
        (0, ""),
        (0, "not-json"),
        (0, _browser_summary() + "\n" + _browser_summary()),
        (0, _browser_summary(scenarioCount=0)),
        (0, _browser_summary(providerCalls=1)),
        (0, _browser_summary(processCount=True)),
        (0, _browser_summary(firstStage="secret-stage")),
        (0, _browser_summary(firstCause="secret-cause")),
        (0, _browser_summary(extra=0)),
        (
            0,
            "PHASE7B_BROWSER_SMOKE_SUMMARY="
            + json.dumps(
                json.loads(_browser_summary().split("=", 1)[1]), sort_keys=True
            ),
        ),
    ),
)
async def test_default_smoke_rejects_runner_failure_or_unsafe_summary(
    returncode: int, stdout: str
) -> None:
    def runner(**_kwargs: object) -> object:
        return SimpleNamespace(
            returncode=returncode,
            stdout=stdout,
            stderr="password=secret D:/private/browser.log",
        )

    with pytest.raises(ProductDatabasePreparationCommandError) as raised:
        await command_module._default_smoke({}, NEW_DATABASE, runner)

    assert str(raised.value) == "readiness smoke failed"
    assert "secret" not in repr(raised.value)


@pytest.mark.asyncio
async def test_default_smoke_normalizes_missing_browser_runner_without_leak() -> None:
    def missing_runner(**_kwargs: object) -> object:
        raise FileNotFoundError("secret node path D:/private/node.exe")

    with pytest.raises(ProductDatabasePreparationCommandError) as raised:
        await command_module._default_smoke({}, NEW_DATABASE, missing_runner)

    assert str(raised.value) == "readiness smoke failed"
    assert "secret" not in repr(raised.value)


def _official_market_rows_and_refresh_states() -> tuple[list[dict], list[dict]]:
    backend_root = Path(__file__).resolve().parents[2]
    market = load_market_source_package(
        backend_root / "assets" / MARKET_VERSION / "manifest.json"
    )
    inventory: list[dict] = []
    refresh: list[dict] = []
    for index, source in enumerate(market.sources):
        source_id = f"official-source-{index}"
        revision_id = f"official-revision-{index}"
        inventory.append(
            {
                "id": source_id,
                "stable_key": source.stable_key,
                "adapter_key": source.adapter_key,
                "display_name": source.display_name,
                "public_config_json": canonical_json(dict(source.public_config)),
                "status": "active",
                "policy": {
                    "id": revision_id,
                    "source_id": source_id,
                    "revision": 1,
                    "policy_status": source.policy.status,
                    "policy_version": source.policy.policy_version,
                    "checked_at": source.policy.checked_at,
                    "evidence_url": source.policy.evidence_url,
                    "evidence_hash": source.policy.evidence_hash,
                    "allowed_origins_json": canonical_json(
                        list(source.policy.allowed_origins)
                    ),
                    "path_prefixes_json": canonical_json(
                        list(source.policy.path_prefixes)
                    ),
                    "enabled": int(source.policy.enabled),
                    "interval_minutes": source.policy.request_interval_seconds // 60,
                    "next_run_at": None,
                    "content_hash": source.policy_hash,
                },
                "head": {
                    "source_id": source_id,
                    "revision_id": revision_id,
                    "revision": 1,
                    "content_hash": source.policy_hash,
                },
            }
        )
        refresh.append(
            {
                "source_id": source_id,
                "last_snapshot_id": None,
                "refresh_status": "idle",
                "lease_owner": None,
                "lease_expires_at": None,
                "last_attempted_at": None,
                "last_succeeded_at": None,
                "next_run_at": None,
                "public_error_code": None,
            }
        )
    return inventory, refresh


async def _run_default_official_audit_with_refresh(
    monkeypatch: pytest.MonkeyPatch,
    refresh_rows: list[dict],
    *,
    inventory_rows: list[dict] | None = None,
) -> tuple[OfficialDataAudit, list[object]]:
    import backend.repositories.market as market_repository_module
    import backend.services.assets as asset_service_module

    default_inventory, _valid_refresh = _official_market_rows_and_refresh_states()
    inventory = default_inventory if inventory_rows is None else inventory_rows
    calls: list[object] = []

    class Session:
        async def fetchall(
            self, sql: str, params: tuple[object, ...] = ()
        ) -> list[dict]:
            calls.append(("fetchall", sql, params))
            return list(refresh_rows)

    @asynccontextmanager
    async def connection_scope(_config: object, database: str):  # type: ignore[no-untyped-def]
        calls.append(("connection-enter", database))
        try:
            yield Session()
        finally:
            calls.append("connection-exit")

    async def dry_run(_self: object, package: object) -> object:
        return SimpleNamespace(
            inserted=0,
            replayed=len(package.styles) + len(package.experience_cards),
            advanced=0,
        )

    async def list_inventory(_self: object, _session: object) -> tuple[dict, ...]:
        calls.append("market-inventory")
        return tuple(inventory)

    monkeypatch.setattr(command_module, "_default_connection_scope", connection_scope)
    monkeypatch.setattr(asset_service_module.AssetSeedService, "dry_run", dry_run)
    monkeypatch.setattr(
        market_repository_module.MarketRepository,
        "list_seed_inventory",
        list_inventory,
    )
    result = await command_module._default_official_audit({}, NEW_DATABASE)
    return result, calls


@pytest.mark.asyncio
async def test_default_official_audit_reads_exact_idle_refresh_state_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _inventory, refresh = _official_market_rows_and_refresh_states()

    result, calls = await _run_default_official_audit_with_refresh(
        monkeypatch, refresh
    )

    assert type(result) is OfficialDataAudit
    assert "official-source-" not in canonical_json(asdict(result))
    fetch = next(call for call in calls if isinstance(call, tuple) and call[0] == "fetchall")
    assert fetch[2] == ()
    assert "SELECT source_id,last_snapshot_id,refresh_status,lease_owner," in fetch[1]
    assert "lease_expires_at,last_attempted_at,last_succeeded_at," in fetch[1]
    assert "next_run_at,public_error_code" in fetch[1]
    assert "FROM market_source_refresh_states" in fetch[1]
    assert "ORDER BY source_id" in fetch[1]
    assert "updated_at" not in fetch[1]
    assert "SELECT *" not in fetch[1]
    assert calls[-1] == "connection-exit"


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ("source", "policy", "head"))
async def test_default_official_audit_rejects_corrupted_market_authority_with_valid_refresh(
    monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:
    inventory, refresh = _official_market_rows_and_refresh_states()
    if corruption == "source":
        inventory[0]["adapter_key"] = "secret-corrupt-adapter"
    elif corruption == "policy":
        inventory[0]["policy"]["content_hash"] = "secret-corrupt-policy"
    elif corruption == "head":
        inventory[0]["head"]["content_hash"] = "secret-corrupt-head"

    with pytest.raises(ProductDatabasePreparationCommandError) as raised:
        await _run_default_official_audit_with_refresh(
            monkeypatch, refresh, inventory_rows=inventory
        )

    assert str(raised.value) == "new database readiness audit failed"
    assert "secret" not in repr(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    (
        "leased",
        "attempted",
        "next",
        "error",
        "snapshot",
        "duplicate",
        "missing",
        "unknown",
        "extra-column",
        "spoofed-type",
    ),
)
async def test_default_official_audit_rejects_nonidle_or_unclosed_refresh_state(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    _inventory, refresh = _official_market_rows_and_refresh_states()
    if failure == "leased":
        refresh[0]["refresh_status"] = "leased"
        refresh[0]["lease_owner"] = "secret-worker"
    elif failure == "attempted":
        refresh[0]["last_attempted_at"] = 123
    elif failure == "next":
        refresh[0]["next_run_at"] = 123
    elif failure == "error":
        refresh[0]["public_error_code"] = "secret-error"
    elif failure == "snapshot":
        refresh[0]["last_snapshot_id"] = "secret-snapshot"
    elif failure == "duplicate":
        refresh.append(dict(refresh[0]))
    elif failure == "missing":
        refresh.pop()
    elif failure == "unknown":
        refresh[0]["source_id"] = "secret-unknown"
    elif failure == "extra-column":
        refresh[0]["updated_at"] = 123
    elif failure == "spoofed-type":
        refresh[0]["source_id"] = type("SpoofedString", (str,), {})(
            refresh[0]["source_id"]
        )

    with pytest.raises(ProductDatabasePreparationCommandError) as raised:
        await _run_default_official_audit_with_refresh(monkeypatch, refresh)

    assert str(raised.value) == "new database readiness audit failed"
    assert "secret" not in repr(raised.value)


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
        browser_smoke_runner=lambda **_kwargs: pytest.fail("unused fake runner"),
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


@pytest.mark.asyncio
@pytest.mark.parametrize("flow_type", FLOW_CONTROLS)
async def test_execute_body_flow_control_is_cloned_after_boundary_cleanup(
    tmp_path: Path,
    flow_type: type[BaseException],
) -> None:
    world = ExecuteWorld(_preparation_receipt())

    async def fail_seed(*_args: object) -> object:
        raise _secret_flow_control(flow_type)

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
        seed_assets=fail_seed,
        seed_market=world.seed_market,
        read_storage=world.read_storage,
        audit_official_data=world.audit_official_data,
        smoke=world.smoke,
        browser_smoke_runner=lambda **_kwargs: pytest.fail("unused fake runner"),
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

    with pytest.raises(BaseException) as raised:
        await run_cli(argv, dependencies=dependencies)

    _assert_clean_flow_control(raised.value, flow_type)
    assert "boundary-exit" in world.events
    assert world.events[-1] == "option-exit"


@pytest.mark.asyncio
@pytest.mark.parametrize("flow_case", FLOW_MATRIX_CASES)
@pytest.mark.parametrize(
    ("injected_stage", "public_stage"),
    (
        ("client-preflight", "preflight"),
        ("connection", "preflight"),
        ("inventory", "legacy-inventory-before"),
        ("backup", "backup"),
        ("restore", "restore-drill"),
        ("proof", "schema-proof"),
        ("seed-assets", "asset-seed"),
        ("seed-market", "market-seed"),
        ("audit", "readiness-audit"),
        ("smoke", "browser-smoke"),
        ("publication", "receipt-publish"),
    ),
)
async def test_execute_all_stage_flow_matrix_uses_real_task4_and_closes_resources(
    tmp_path: Path,
    flow_case: str,
    injected_stage: str,
    public_stage: str,
) -> None:
    class World(RealTask4ExecuteWorld):
        def __init__(self) -> None:
            super().__init__()
            self.option_open = False
            self.backup_retained = False
            self.target_active = False
            self.target_retained = False
            self.receipt_published = False

        @contextmanager
        def option_file(self, config: object, root: Path):  # type: ignore[no-untyped-def]
            self.events.append(("option-enter", config, root))
            self.option_open = True
            try:
                yield self.option
            finally:
                self.option_open = False
                self.events.append("option-exit")
                if injected_stage not in ("client-preflight", "publication"):
                    raise RuntimeError("secret-option-cleanup")

        def create_backup(self, *args: object) -> BackupReceipt:
            value = super().create_backup(*args)  # type: ignore[arg-type]
            self.backup_retained = True
            return value

        def database_boundary(self, config: object, database: str) -> object:
            inner = super().database_boundary(config, database)
            world = self

            class Boundary:
                async def __aenter__(self) -> NewDatabaseBoundaryState:
                    value = await inner.__aenter__()  # type: ignore[attr-defined]
                    world.target_active = True
                    return value

                async def __aexit__(
                    self,
                    exc_type: object,
                    exc: BaseException | None,
                    traceback: object,
                ) -> bool:
                    result = await inner.__aexit__(  # type: ignore[attr-defined]
                        exc_type, exc, traceback
                    )
                    if exc is None:
                        world.target_retained = True
                    else:
                        world.target_active = False
                    return result

            return Boundary()

        def publish(self, receipt: PreparationReceipt, backup: Path) -> Path:
            value = super().publish(receipt, backup)
            self.receipt_published = True
            return value

    world = World()

    def injected(name: str, operation: object):
        def wrapper(*args: object, **kwargs: object) -> object:
            if injected_stage == name:
                raise _matrix_flow(flow_case)
            return operation(*args, **kwargs)  # type: ignore[operator]

        return wrapper

    dependencies = PreparationCommandDependencies(
        preflight_clients=injected("client-preflight", world.preflight_clients),
        read_config=world.read_config,
        option_file=world.option_file,
        preflight_connection=injected("connection", world.preflight_connection),
        inventory_database=injected("inventory", world.inventory_database),
        create_backup=injected("backup", world.create_backup),
        restore_drill=injected("restore", world.restore_drill),
        current_schema_proof=injected("proof", world.current_schema_proof),
        database_boundary=world.database_boundary,
        seed_assets=injected("seed-assets", world.seed_assets),
        seed_market=injected("seed-market", world.seed_market),
        read_storage=world.read_storage,
        audit_official_data=injected("audit", world.audit_official_data),
        smoke=injected("smoke", world.smoke),
        browser_smoke_runner=lambda **_kwargs: pytest.fail("unused fake runner"),
        prepare_service=prepare_product_database,
        publish_receipt=injected("publication", world.publish),
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
    output: list[str] = []

    with pytest.raises(BaseException) as raised:
        await run_cli(argv, dependencies=dependencies, output=output.append)

    outgoing = raised.value
    if isinstance(outgoing, BaseExceptionGroup):
        outgoing = outgoing.exceptions[0]
    _assert_matrix_flow(outgoing, flow_case)
    assert "secret" not in repr(raised.value)
    assert world.option_open is False
    backup_expected = injected_stage not in (
        "client-preflight",
        "connection",
        "inventory",
        "backup",
    )
    assert world.backup_retained is backup_expected
    if injected_stage in ("seed-assets", "seed-market", "audit", "smoke"):
        assert world.target_active is False
        assert world.target_retained is False
    elif injected_stage == "publication":
        assert world.target_active is True
        assert world.target_retained is True
    else:
        assert world.target_active is False
        assert world.target_retained is False
    assert world.receipt_published is False
    expected_output = [
        "outcome=failed",
        f"stage={public_stage}",
        "cleanup=no-failure-reported",
    ]
    if public_stage == "browser-smoke":
        expected_output.append("browser_stage=unavailable")
    assert output == expected_output


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("injected_stage", "public_stage", "cleanup"),
    (
        ("legacy-after", "legacy-inventory-after", "no-failure-reported"),
        ("boundary-enter", "new-database-init", "no-failure-reported"),
        ("storage", "readiness-audit", "no-failure-reported"),
        ("boundary-commit", "boundary-commit", "failed"),
    ),
)
async def test_execute_reports_missing_fixed_stages(
    tmp_path: Path,
    injected_stage: str,
    public_stage: str,
    cleanup: str,
) -> None:
    class StageWorld(RealTask4ExecuteWorld):
        def __init__(self) -> None:
            super().__init__()
            self.legacy_inventory_count = 0
            self.receipt_published = False

        async def inventory_database(
            self, config: object, database: str
        ) -> DatabaseInventory:
            if database == LEGACY_DATABASE:
                self.legacy_inventory_count += 1
                if (
                    injected_stage == "legacy-after"
                    and self.legacy_inventory_count == 2
                ):
                    raise RuntimeError("password=secret-legacy-after")
            return await super().inventory_database(config, database)

        async def read_storage(self, config: object, database: str) -> object:
            if injected_stage == "storage":
                raise RuntimeError("dsn=mysql://secret-storage")
            return await super().read_storage(config, database)

        def database_boundary(self, config: object, database: str) -> object:
            inner = super().database_boundary(config, database)

            class Boundary:
                async def __aenter__(self) -> NewDatabaseBoundaryState:
                    if injected_stage == "boundary-enter":
                        raise RuntimeError("password=secret-boundary-enter")
                    return await inner.__aenter__()  # type: ignore[attr-defined]

                async def __aexit__(
                    self,
                    exc_type: object,
                    exc: BaseException | None,
                    traceback: object,
                ) -> bool:
                    result = await inner.__aexit__(  # type: ignore[attr-defined]
                        exc_type, exc, traceback
                    )
                    if injected_stage == "boundary-commit" and exc is None:
                        raise ProductDatabaseReadinessError(
                            "product database cleanup failed"
                        )
                    return result

            return Boundary()

        def publish(self, receipt: PreparationReceipt, backup: Path) -> Path:
            self.receipt_published = True
            return super().publish(receipt, backup)

    world = StageWorld()
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
        browser_smoke_runner=lambda **_kwargs: pytest.fail("unused fake runner"),
        prepare_service=prepare_product_database,
        publish_receipt=world.publish,
        id_factory=lambda: "1" * 32,
    )
    output: list[str] = []

    with pytest.raises(ProductDatabasePreparationCommandError) as raised:
        await run_cli(
            [
                *_arguments(tmp_path),
                "--execute",
                "--confirm-legacy",
                LEGACY_DATABASE,
                "--confirm-new",
                NEW_DATABASE,
                "--confirm-prepare",
                "PREPARE-PHASE7B",
            ],
            dependencies=dependencies,
            output=output.append,
        )

    assert "secret" not in repr(raised.value)
    assert world.receipt_published is False
    assert output == [
        "outcome=failed",
        f"stage={public_stage}",
        f"cleanup={cleanup}",
    ]


@pytest.mark.asyncio
async def test_execute_reports_primary_stage_and_fixed_cleanup_failure(
    tmp_path: Path,
) -> None:
    world = ExecuteWorld(_preparation_receipt())

    class FailingOptionContext:
        def __enter__(self) -> Path:
            world.events.append("option-enter")
            return world.option

        def __exit__(self, *_args: object) -> bool:
            world.events.append("option-exit")
            raise ProductDatabaseBackupError(
                "private mysql option file cleanup failed"
            )

    async def fail_seed_assets(*_args: object) -> object:
        raise RuntimeError("password=secret-seed-assets")

    dependencies = PreparationCommandDependencies(
        preflight_clients=world.preflight_clients,
        read_config=world.read_config,
        option_file=lambda *_args: FailingOptionContext(),
        preflight_connection=world.preflight_connection,
        inventory_database=world.inventory_database,
        create_backup=world.create_backup,
        restore_drill=world.restore_drill,
        current_schema_proof=world.current_schema_proof,
        database_boundary=world.database_boundary,
        seed_assets=fail_seed_assets,
        seed_market=world.seed_market,
        read_storage=world.read_storage,
        audit_official_data=world.audit_official_data,
        smoke=world.smoke,
        browser_smoke_runner=lambda **_kwargs: pytest.fail("unused fake runner"),
        prepare_service=world.prepare,
        publish_receipt=world.publish,
        id_factory=lambda: "1" * 32,
    )
    output: list[str] = []

    with pytest.raises(BaseExceptionGroup) as raised:
        await run_cli(
            [
                *_arguments(tmp_path),
                "--execute",
                "--confirm-legacy",
                LEGACY_DATABASE,
                "--confirm-new",
                NEW_DATABASE,
                "--confirm-prepare",
                "PREPARE-PHASE7B",
            ],
            dependencies=dependencies,
            output=output.append,
        )

    assert len(raised.value.exceptions) == 2
    assert all(
        str(error) == "product database preparation execution failed"
        for error in raised.value.exceptions
    )
    assert "secret" not in repr(raised.value)
    assert output == [
        "outcome=failed",
        "stage=asset-seed",
        "cleanup=failed",
    ]


def test_main_prints_only_fixed_failure(
    monkeypatch: pytest.MonkeyPatch, capsys, sync_main_event_loop_owner: None
) -> None:
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


@pytest.mark.parametrize("code", (None, 0, "secret-system-exit"))
def test_main_never_treats_execute_system_exit_as_help_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    code: object,
    sync_main_event_loop_owner: None,
) -> None:
    async def fail(*_args: object, **_kwargs: object) -> int:
        raise SystemExit(code)

    monkeypatch.setattr(command_module, "run_cli", fail)

    assert main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Product database preparation failed.\n"
    assert "secret" not in captured.err


def test_main_help_uses_dedicated_success_path(
    capsys, sync_main_event_loop_owner: None
) -> None:
    assert main(["--help"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "Product database preparation failed." not in captured.out


def test_primary_first_context_resolves_exit_before_acquiring_resource() -> None:
    acquired = False

    class MissingExit:
        def __enter__(self) -> object:
            nonlocal acquired
            acquired = True
            return object()

    with pytest.raises(AttributeError):
        with _primary_first_context(MissingExit()):
            pytest.fail("body entered")

    assert acquired is False


def test_primary_first_context_uses_type_exit_cached_before_enter() -> None:
    events: list[str] = []

    class MutatingManager:
        def __enter__(self) -> object:
            events.append("enter")
            self.__exit__ = lambda *_args: events.append("instance-exit")
            return object()

        def __exit__(self, *_args: object) -> bool:
            events.append("type-exit")
            return False

    with _primary_first_context(MutatingManager()):
        events.append("body")

    assert events == ["enter", "body", "type-exit"]


@pytest.mark.parametrize(
    "argv",
    (
        [],
        ["--unknown-option"],
        ["--legacy-database"],
        [
            "--legacy-database",
            "wrong-database",
            "--new-database",
            NEW_DATABASE,
            "--backup-dir",
            "D:/private/backups",
            "--mysqldump",
            "D:/private/mysql-8.4/mysqldump.exe",
            "--mysql",
            "D:/private/mysql-8.4/mysql.exe",
        ],
    ),
)
def test_main_normalizes_real_argument_errors_to_one_fixed_line(
    argv: list[str], capsys, sync_main_event_loop_owner: None
) -> None:
    assert main(argv) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Product database preparation failed.\n"
    assert "usage:" not in captured.err.lower()
    assert "D:/" not in captured.err


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
