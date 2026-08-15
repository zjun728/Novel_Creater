"""Explicit Stage A product database preparation command."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
import inspect
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import time
from typing import Callable, Mapping, NoReturn, Sequence

from backend.domain.json_contracts import canonical_json
from backend.domain.product_database_readiness import (
    BackupReceipt,
    DatabaseInventory,
    LEGACY_DATABASE,
    NEW_DATABASE,
    PreparationReceipt,
    ReadinessState,
    advance_receipt,
    canonical_receipt_hash,
    inventory_hash,
    validate_database_role,
    validate_restore_database,
)
from backend.services.product_database_readiness import (
    CurrentSchemaProof,
    NewDatabaseBoundaryEnterFailure,
    NewDatabaseBoundaryExitFailure,
    NewDatabaseBoundaryState,
    PreparationRequest,
)


REPOSITORY_ROOT = Path(__file__).absolute().parents[2]
_ARGUMENT_ERROR = "product database preparation arguments are invalid"
_APPROVAL_ERROR = "product database preparation approval is invalid"
_PREPARE_CONFIRMATION = "PREPARE-PHASE7B"
_BOUNDARY_ERROR = "new database boundary failed"
_BOUNDARY_CLEANUP_ERROR = "new database boundary cleanup failed"
_BOUNDARY_COMMIT_ERROR = "new database boundary commit failed"
_PROOF_ERROR = "current schema proof failed"
_PROOF_CLEANUP_ERROR = "current schema proof cleanup failed"
_RECEIPT_ERROR = "readiness receipt publication failed"
_RECEIPT_CLEANUP_ERROR = "readiness receipt cleanup failed"
_EXECUTION_ERROR = "product database preparation execution failed"
_RESTORE_DRILL_ERROR = "restore drill lifecycle failed"
_RESTORE_DRILL_CLEANUP_ERROR = "restore drill cleanup failed"
_LOCK_NAME = "novel_creator:phase7b:prepare"
_HEX_ID = re.compile(r"^[0-9a-f]{32}$", re.ASCII)


class ProductDatabasePreparationCommandError(RuntimeError):
    """A fixed, public-safe command failure."""


@dataclass(frozen=True)
class PreparationCommandDependencies:
    """Fully injectable execute-mode boundaries used by unit tests and defaults."""

    preflight_clients: Callable[..., object]
    read_config: Callable[..., object]
    option_file: Callable[..., object]
    preflight_connection: Callable[..., object]
    inventory_database: Callable[..., object]
    create_backup: Callable[..., object]
    restore_drill: Callable[..., object]
    current_schema_proof: Callable[..., object]
    database_boundary: Callable[..., object]
    seed_assets: Callable[..., object]
    seed_market: Callable[..., object]
    read_storage: Callable[..., object]
    audit_official_data: Callable[..., object]
    smoke: Callable[..., object]
    prepare_service: Callable[..., object]
    publish_receipt: Callable[..., object]
    id_factory: Callable[[], str]


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        self.exit(2, "Product database preparation arguments are invalid.\n")


def _argument_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        description="Prepare the approved Writer Core product database."
    )
    parser.add_argument("--legacy-database", required=True)
    parser.add_argument("--new-database", required=True)
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--mysqldump", required=True)
    parser.add_argument("--mysql", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-legacy")
    parser.add_argument("--confirm-new")
    parser.add_argument("--confirm-prepare")
    return parser


def _raise_fixed(message: str) -> None:
    _raise_public(ProductDatabasePreparationCommandError(message))


def _raise_public(error: BaseException) -> NoReturn:
    try:
        raise error from None
    except BaseException as outgoing:
        outgoing.__cause__ = None
        outgoing.__context__ = None
        outgoing.__suppress_context__ = True
        raise


def _sanitized(error: BaseException, message: str) -> BaseException:
    if isinstance(error, BaseExceptionGroup):
        return BaseExceptionGroup(
            message,
            [_sanitized(child, message) for child in error.exceptions],
        )
    if isinstance(error, asyncio.CancelledError):
        return asyncio.CancelledError()
    if isinstance(error, KeyboardInterrupt):
        return KeyboardInterrupt()
    if isinstance(error, SystemExit):
        return SystemExit(error.code) if type(error.code) is int else SystemExit()
    return ProductDatabasePreparationCommandError(message)


def _combined(
    errors: list[BaseException],
    message: str,
) -> BaseException:
    clean = [_sanitized(error, message) for error in errors]
    if len(clean) == 1:
        return clean[0]
    return BaseExceptionGroup(message, clean)


async def _invoke(
    operation: Callable[..., object],
    *args: object,
    **kwargs: object,
) -> object:
    value = operation(*args, **kwargs)
    if inspect.isawaitable(value):
        return await value
    return value


def _database_exists(error: BaseException) -> bool:
    errno = getattr(error, "errno", None)
    if errno == 1007:
        return True
    return bool(error.args and type(error.args[0]) is int and error.args[0] == 1007)


def _create_database_sql(database: str) -> str:
    return (
        f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 "
        "COLLATE utf8mb4_0900_ai_ci"
    )


def _drop_database_sql(database: str) -> str:
    return f"DROP DATABASE `{database}`"


class _NewDatabaseBoundary:
    def __init__(
        self,
        database: str,
        *,
        session_factory: Callable[[], object],
        initialize: Callable[..., object],
        inventory: Callable[..., object],
        now_ms: Callable[[], int],
    ) -> None:
        self._database = database
        self._session_factory = session_factory
        self._initialize = initialize
        self._inventory = inventory
        self._now_ms = now_ms
        self._session: object | None = None
        self._locked = False
        self._owned = False

    async def _release(self, errors: list[BaseException]) -> None:
        session = self._session
        if session is None:
            return
        if self._locked:
            try:
                released = await session.fetchone(  # type: ignore[attr-defined]
                    "SELECT RELEASE_LOCK(%s) AS released", (_LOCK_NAME,)
                )
                if not isinstance(released, dict) or released.get("released") != 1:
                    raise RuntimeError
            except BaseException as error:
                errors.append(error)
            self._locked = False
        try:
            await session.close()  # type: ignore[attr-defined]
        except BaseException as error:
            errors.append(error)
        self._session = None

    async def _drop_owned(self, errors: list[BaseException]) -> None:
        if not self._owned or self._session is None:
            return
        try:
            await self._session.execute(  # type: ignore[attr-defined]
                _drop_database_sql(self._database)
            )
            self._owned = False
        except BaseException as error:
            errors.append(error)

    async def __aenter__(self) -> NewDatabaseBoundaryState:
        primary: BaseException | None = None
        try:
            self._session = await _invoke(self._session_factory)
            acquired = await self._session.fetchone(  # type: ignore[attr-defined]
                "SELECT GET_LOCK(%s, 0) AS acquired", (_LOCK_NAME,)
            )
            if not isinstance(acquired, dict) or acquired.get("acquired") != 1:
                raise RuntimeError
            self._locked = True
            try:
                await self._session.execute(  # type: ignore[attr-defined]
                    _create_database_sql(self._database)
                )
            except BaseException as error:
                if not _database_exists(error):
                    raise
                observed = await _invoke(
                    self._inventory, self._session, self._database
                )
                return NewDatabaseBoundaryState(
                    mode="preexisting", initialized=None, inventory=observed
                )
            self._owned = True
            initialized = await _invoke(
                self._initialize,
                self._session,
                self._database,
                self._database,
                self._now_ms(),
            )
            return NewDatabaseBoundaryState(
                mode="created", initialized=initialized, inventory=None
            )
        except BaseException as error:
            primary = error

        cleanup: list[BaseException] = []
        await self._drop_owned(cleanup)
        await self._release(cleanup)
        assert primary is not None
        clean_primary = _sanitized(primary, _BOUNDARY_ERROR)
        if cleanup:
            _raise_public(
                NewDatabaseBoundaryEnterFailure(
                    clean_primary,
                    _combined(cleanup, _BOUNDARY_CLEANUP_ERROR),
                )
            )
        _raise_public(clean_primary)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> bool:
        del exc, traceback
        failures: list[BaseException] = []
        commit_failure: BaseException | None = None
        if exc_type is not None:
            await self._drop_owned(failures)
        else:
            commit = getattr(self._session, "commit", None)
            try:
                if callable(commit):
                    await _invoke(commit)
                else:
                    await self._session.execute("COMMIT")  # type: ignore[attr-defined]
            except BaseException as error:
                commit_failure = _sanitized(error, _BOUNDARY_COMMIT_ERROR)
                await self._drop_owned(failures)
        await self._release(failures)
        if commit_failure is not None or failures:
            clean_failures = (
                ([] if commit_failure is None else [commit_failure])
                + [
                    _sanitized(error, _BOUNDARY_CLEANUP_ERROR)
                    for error in failures
                ]
            )
            cleanup = (
                clean_failures[0]
                if len(clean_failures) == 1
                else BaseExceptionGroup(
                    _BOUNDARY_CLEANUP_ERROR, clean_failures
                )
            )
            _raise_public(
                NewDatabaseBoundaryExitFailure(cleanup)
            )
        return False


def new_database_boundary(
    database: str,
    *,
    session_factory: Callable[[], object],
    initialize: Callable[..., object],
    inventory: Callable[..., object],
    now_ms: Callable[[], int],
) -> _NewDatabaseBoundary:
    """Hold the preparation advisory lock for one exact target lifecycle."""

    try:
        validate_database_role("new", database)
    except BaseException:
        _raise_fixed(_BOUNDARY_ERROR)
    return _NewDatabaseBoundary(
        database,
        session_factory=session_factory,
        initialize=initialize,
        inventory=inventory,
        now_ms=now_ms,
    )


async def create_current_schema_proof(
    *,
    session_factory: Callable[[], object],
    initialize: Callable[..., object],
    inventory: Callable[..., object],
    read_storage: Callable[..., object],
    id_factory: Callable[[], str],
    now_ms: Callable[[], int],
) -> CurrentSchemaProof:
    """Create, inspect, and close one current-run disposable schema proof."""

    session: object | None = None
    owned = False
    proof_name = ""
    observed: object | None = None
    storage: object | None = None
    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    try:
        random_id = id_factory()
        if type(random_id) is not str or _HEX_ID.fullmatch(random_id) is None:
            raise ValueError
        proof_name = validate_restore_database(
            f"novel_creator_phase7b_restore_{random_id}"
        )
        session = await _invoke(session_factory)
        await session.execute(_create_database_sql(proof_name))  # type: ignore[attr-defined]
        owned = True
        await _invoke(initialize, session, proof_name, proof_name, now_ms())
        observed = await _invoke(inventory, session, proof_name)
        storage = await _invoke(read_storage, session, proof_name)
    except BaseException as error:
        primary = error
    finally:
        if owned and session is not None:
            try:
                await session.execute(_drop_database_sql(proof_name))  # type: ignore[attr-defined]
                owned = False
            except BaseException as error:
                cleanup.append(error)
        if session is not None:
            try:
                await session.close()  # type: ignore[attr-defined]
            except BaseException as error:
                cleanup.append(error)

    if primary is not None and cleanup:
        _raise_public(
            BaseExceptionGroup(
                _PROOF_ERROR,
                [
                    _sanitized(primary, _PROOF_ERROR),
                    _combined(cleanup, _PROOF_CLEANUP_ERROR),
                ],
            )
        )
    if primary is not None:
        _raise_public(_sanitized(primary, _PROOF_ERROR))
    if cleanup:
        _raise_public(_combined(cleanup, _PROOF_CLEANUP_ERROR))
    try:
        return CurrentSchemaProof(
            inventory=observed,  # type: ignore[arg-type]
            storage=storage,  # type: ignore[arg-type]
            created_databases=(proof_name,),
            cleaned_databases=(proof_name,),
        )
    except BaseException as error:
        _raise_public(_sanitized(error, _PROOF_ERROR))


def _open_receipt_temporary(directory: Path) -> tuple[Path, object, object]:
    import ctypes
    from ctypes import wintypes
    import msvcrt

    from backend.services.product_database_backup import (
        _delete_owned_twice,
        _delete_owned_windows,
        _random_owned_path,
    )

    path, descriptor, lease = _random_owned_path(
        directory,
        ".phase7b-readiness-",
        ".tmp",
        delete_capable=True,
    )
    independent_owner = False
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        duplicate_handle = kernel32.DuplicateHandle
        duplicate_handle.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        duplicate_handle.restype = wintypes.BOOL
        process = kernel32.GetCurrentProcess()
        duplicate = wintypes.HANDLE()
        if not duplicate_handle(
            process,
            wintypes.HANDLE(msvcrt.get_osfhandle(descriptor)),
            process,
            ctypes.byref(duplicate),
            0,
            False,
            0x00000002,
        ):
            raise OSError
        lease.handle = int(duplicate.value)
        independent_owner = True
        handle = os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
            closefd=True,
        )
    except BaseException as primary:
        cleanup: list[BaseException] = []
        if not independent_owner:
            delete_error = _delete_owned_twice(
                path, lease, _delete_owned_windows
            )
            if delete_error is not None:
                cleanup.append(delete_error)
        try:
            os.close(descriptor)
        except BaseException as error:
            cleanup.append(error)
        if independent_owner:
            try:
                _unlink_receipt_owner(path, lease)
            except BaseException as error:
                cleanup.append(error)
        if cleanup:
            _raise_public(
                BaseExceptionGroup(
                    _RECEIPT_ERROR,
                    [
                        _sanitized(primary, _RECEIPT_ERROR),
                        _combined(cleanup, _RECEIPT_CLEANUP_ERROR),
                    ],
                )
            )
        raise
    return path, handle, lease


def _same_receipt_owner(path: Path, identity: object) -> bool:
    from backend.services.product_database_backup import (
        _OwnedFileLease,
        _identity_from_fd,
    )

    if type(identity) is _OwnedFileLease:
        descriptor: int | None = None
        try:
            descriptor = os.open(
                path,
                os.O_RDONLY | getattr(os, "O_BINARY", 0),
            )
            return _identity_from_fd(descriptor) == identity.identity
        except OSError:
            return False
        finally:
            if descriptor is not None:
                os.close(descriptor)
    if type(identity) is not tuple or len(identity) != 2:
        return False
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return (
        not stat.S_ISLNK(metadata.st_mode)
        and stat.S_ISREG(metadata.st_mode)
        and (metadata.st_dev, metadata.st_ino) == identity
    )


def _unlink_receipt_owner(path: Path, identity: object) -> bool:
    from backend.services.product_database_backup import (
        _OwnedFileLease,
        _close_windows_handle,
        _delete_owned_twice,
        _delete_owned_windows,
        _identity_from_handle,
        _link_count_from_handle,
        _set_delete_disposition,
    )

    if type(identity) is _OwnedFileLease:
        if identity.delete_through_handle and not identity.deleted:
            handle = identity.handle
            if (
                handle is None
                or _identity_from_handle(handle) != identity.identity
            ):
                raise OSError
            try:
                if _link_count_from_handle(handle) != 0:
                    _set_delete_disposition(handle)
            finally:
                _close_windows_handle(handle)
                identity.handle = None
            identity.deleted = True
            return True
        error = _delete_owned_twice(path, identity, _delete_owned_windows)
        if error is not None:
            raise error
        return True
    if not _same_receipt_owner(path, identity):
        return False
    path.unlink()
    return True


def publish_readiness_receipt(
    receipt: PreparationReceipt,
    backup_path: Path,
    *,
    temporary_opener: Callable[[Path], tuple[Path, object, object]] = _open_receipt_temporary,
    acl_runner: Callable[[Path], None] | None = None,
    fsync: Callable[[int], None] = os.fsync,
    linker: Callable[[Path, Path], None] = os.link,
    same_owner: Callable[[Path, object], bool] = _same_receipt_owner,
    unlink_owned: Callable[[Path, object], bool] = _unlink_receipt_owner,
) -> Path:
    """Absent-only publish one canonical, hash-bound readiness receipt."""

    if type(receipt) is not PreparationReceipt:
        _raise_fixed(_RECEIPT_ERROR)
    try:
        backup = Path(backup_path)
        if (
            not backup.is_absolute()
            or backup.parent == backup
            or ".." in backup.parts
            or _is_inside(
                os.path.normcase(os.path.normpath(str(backup))),
                os.path.normcase(os.path.normpath(str(REPOSITORY_ROOT))),
            )
        ):
            raise ValueError
        target = backup.with_suffix(".readiness.json")
        document = canonical_json(
            {
                "preparationReceipt": asdict(receipt),
                "preparationReceiptHash": canonical_receipt_hash(receipt),
            }
        )
    except BaseException as error:
        _raise_public(_sanitized(error, _RECEIPT_ERROR))

    if acl_runner is None:
        from backend.scripts.configure_local_mysql import restrict_windows_acl

        acl_runner = restrict_windows_acl

    temporary: Path | None = None
    identity: object | None = None
    handle: object | None = None
    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    try:
        temporary, handle, identity = temporary_opener(target.parent)
        if (
            not isinstance(temporary, Path)
            or temporary.parent != target.parent
            or temporary == target
        ):
            raise OSError
        acl_runner(temporary)
        if not same_owner(temporary, identity):
            raise OSError
        written = handle.write(document)  # type: ignore[attr-defined]
        if type(written) is not int or written != len(document):
            raise OSError
        handle.flush()  # type: ignore[attr-defined]
        descriptor = handle.fileno()  # type: ignore[attr-defined]
        if type(descriptor) is not int:
            raise OSError
        fsync(descriptor)
        closing = handle
        handle = None
        closing.close()  # type: ignore[attr-defined]
        if not same_owner(temporary, identity):
            raise OSError
        linker(temporary, target)
        if not same_owner(target, identity):
            raise OSError
    except BaseException as error:
        primary = error
    finally:
        if handle is not None:
            closing = handle
            handle = None
            try:
                closing.close()  # type: ignore[attr-defined]
            except BaseException as error:
                cleanup.append(error)
        if temporary is not None and identity is not None:
            try:
                if not unlink_owned(temporary, identity):
                    raise OSError
            except BaseException as error:
                cleanup.append(error)

    if primary is not None and cleanup:
        _raise_public(
            BaseExceptionGroup(
                _RECEIPT_ERROR,
                [
                    _sanitized(primary, _RECEIPT_ERROR),
                    _combined(cleanup, _RECEIPT_CLEANUP_ERROR),
                ],
            )
        )
    if primary is not None:
        _raise_public(_sanitized(primary, _RECEIPT_ERROR))
    if cleanup:
        _raise_public(_combined(cleanup, _RECEIPT_CLEANUP_ERROR))
    return target


def _mysql_connection_config(config: Mapping[str, object]) -> dict[str, object]:
    required = ("host", "port", "user", "password")
    values = {name: config.get(name) for name in required}
    host, port, user, password = (values[name] for name in required)
    if (
        type(host) is not str
        or not host
        or type(port) is not int
        or not 1 <= port <= 65535
        or type(user) is not str
        or not user
        or type(password) is not str
        or not password
    ):
        raise ValueError
    return {
        **values,
        "charset": "utf8mb4",
        "autocommit": True,
    }


async def _open_default_session(
    config: Mapping[str, object], database: str | None = None
) -> object:
    from backend.scripts.initialize_database import _default_connection_factory

    session = await _default_connection_factory(_mysql_connection_config(config))
    try:
        if database is not None:
            if database not in (LEGACY_DATABASE, NEW_DATABASE):
                raise ValueError
            await session.execute(f"USE `{database}`")
        return session
    except BaseException as primary:
        try:
            await session.close()
        except BaseException as cleanup:
            raise BaseExceptionGroup(
                _EXECUTION_ERROR,
                [
                    _sanitized(primary, _EXECUTION_ERROR),
                    _sanitized(cleanup, _EXECUTION_ERROR),
                ],
            ) from None
        raise


async def _run_default_session(
    config: Mapping[str, object],
    operation: Callable[[object], object],
    *,
    database: str | None = None,
) -> object:
    session = await _open_default_session(config, database)
    primary: BaseException | None = None
    result: object | None = None
    try:
        result = await _invoke(operation, session)
    except BaseException as error:
        primary = error
    cleanup: BaseException | None = None
    try:
        await session.close()  # type: ignore[attr-defined]
    except BaseException as error:
        cleanup = error
    if primary is not None and cleanup is not None:
        raise BaseExceptionGroup(
            _EXECUTION_ERROR,
            [
                _sanitized(primary, _EXECUTION_ERROR),
                _sanitized(cleanup, _EXECUTION_ERROR),
            ],
        ) from None
    if primary is not None:
        raise primary
    if cleanup is not None:
        raise cleanup
    return result


@asynccontextmanager
async def _default_connection_scope(
    config: Mapping[str, object], database: str
):
    session = await _open_default_session(config, database)
    primary: BaseException | None = None
    cleanup: BaseException | None = None
    try:
        yield session
    except BaseException as error:
        primary = error
    try:
        await session.close()  # type: ignore[attr-defined]
    except BaseException as error:
        cleanup = error
    if primary is not None and cleanup is not None:
        _raise_public(
            BaseExceptionGroup(
                _EXECUTION_ERROR,
                [
                    _sanitized(primary, _EXECUTION_ERROR),
                    _sanitized(cleanup, _EXECUTION_ERROR),
                ],
            )
        )
    if primary is not None:
        _raise_public(_sanitized(primary, _EXECUTION_ERROR))
    if cleanup is not None:
        _raise_public(_sanitized(cleanup, _EXECUTION_ERROR))


@asynccontextmanager
async def _default_transaction_scope(
    config: Mapping[str, object], database: str
):
    session = await _open_default_session(config, database)
    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    try:
        await session.execute("START TRANSACTION")  # type: ignore[attr-defined]
    except BaseException as error:
        primary = error
    if primary is None:
        body_failed = False
        try:
            yield session
        except BaseException as error:
            primary = error
            body_failed = True
        if body_failed:
            try:
                await session.execute("ROLLBACK")  # type: ignore[attr-defined]
            except BaseException as error:
                cleanup.append(error)
        else:
            try:
                await session.execute("COMMIT")  # type: ignore[attr-defined]
            except BaseException as error:
                primary = error
    try:
        await session.close()  # type: ignore[attr-defined]
    except BaseException as error:
        cleanup.append(error)
    if primary is not None and cleanup:
        _raise_public(
            BaseExceptionGroup(
                _EXECUTION_ERROR,
                [
                    _sanitized(primary, _EXECUTION_ERROR),
                    _combined(cleanup, _EXECUTION_ERROR),
                ],
            )
        )
    if primary is not None:
        _raise_public(_sanitized(primary, _EXECUTION_ERROR))
    if cleanup:
        _raise_public(_combined(cleanup, _EXECUTION_ERROR))


async def _default_inventory(
    config: Mapping[str, object], database: str
) -> object:
    from backend.services.product_database_inventory import inventory_database

    return await _run_default_session(
        config,
        lambda session: inventory_database(session, database),
    )


async def _default_storage(
    config: Mapping[str, object], database: str
) -> object:
    from backend.services.product_database_inventory import read_table_storage

    return await _run_default_session(
        config,
        lambda session: read_table_storage(session, database),
    )


async def _default_restore_drill(
    config: Mapping[str, object],
    pair: object,
    option_file: Path,
    backup: BackupReceipt,
    authority: DatabaseInventory,
    backup_directory: Path,
) -> object:
    from backend.services.product_database_backup import restore_logical_backup
    from backend.services.product_database_inventory import inventory_database
    from backend.services.product_database_readiness import RestoreDrillResult

    proof_id = secrets.token_hex(16)
    database = validate_restore_database(
        f"novel_creator_phase7b_restore_{proof_id}"
    )
    session: object | None = None
    owned = False
    observed: object | None = None
    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    try:
        session = await _open_default_session(config)
        await session.execute(_create_database_sql(database))  # type: ignore[attr-defined]
        owned = True
        restore_logical_backup(
            pair,  # type: ignore[arg-type]
            option_file,
            backup_directory / backup.backup_filename,
            backup.backup_sha256,
            backup.backup_byte_length,
            database,
            subprocess.run,
        )
        observed = await inventory_database(session, database)
    except BaseException as error:
        primary = error
    finally:
        if owned and session is not None:
            try:
                await session.execute(_drop_database_sql(database))  # type: ignore[attr-defined]
                owned = False
            except BaseException as error:
                cleanup.append(error)
        if session is not None:
            try:
                await session.close()  # type: ignore[attr-defined]
            except BaseException as error:
                cleanup.append(error)
    if primary is not None and cleanup:
        _raise_public(
            BaseExceptionGroup(
                _RESTORE_DRILL_ERROR,
                [
                    _sanitized(primary, _RESTORE_DRILL_ERROR),
                    _combined(cleanup, _RESTORE_DRILL_CLEANUP_ERROR),
                ],
            )
        )
    if primary is not None:
        _raise_public(_sanitized(primary, _RESTORE_DRILL_ERROR))
    if cleanup:
        _raise_public(_combined(cleanup, _RESTORE_DRILL_CLEANUP_ERROR))
    return RestoreDrillResult(
        inventory=observed,  # type: ignore[arg-type]
        created_databases=(database,),
        cleaned_databases=(database,),
    )


async def _default_current_schema_proof(config: Mapping[str, object]) -> object:
    from backend.scripts.initialize_database import initialize_database
    from backend.services.product_database_inventory import (
        inventory_database,
        read_table_storage,
    )

    return await create_current_schema_proof(
        session_factory=lambda: _open_default_session(config),
        initialize=initialize_database,
        inventory=inventory_database,
        read_storage=read_table_storage,
        id_factory=lambda: secrets.token_hex(16),
        now_ms=lambda: int(time.time() * 1000),
    )


def _default_database_boundary(
    config: Mapping[str, object], database: str
) -> object:
    from backend.scripts.initialize_database import initialize_database
    from backend.services.product_database_inventory import inventory_database

    return new_database_boundary(
        database,
        session_factory=lambda: _open_default_session(config),
        initialize=initialize_database,
        inventory=inventory_database,
        now_ms=lambda: int(time.time() * 1000),
    )


async def _default_seed_assets(
    config: Mapping[str, object], database: str
) -> object:
    from backend.domain.assets import load_asset_package
    from backend.repositories.assets import AssetRepository
    from backend.scripts.seed_writer_assets import MANIFEST_PATH
    from backend.services.assets import AssetSeedService

    package = load_asset_package(MANIFEST_PATH, mode="release")
    return await AssetSeedService(
        AssetRepository(),
        transaction_factory=lambda: _default_transaction_scope(config, database),
    ).seed(package)


async def _default_seed_market(
    config: Mapping[str, object], database: str
) -> object:
    from backend.domain.market_sources import load_market_source_package
    from backend.repositories.market import MarketRepository
    from backend.scripts.seed_market_sources import MANIFEST_PATH
    from backend.services.market_sources import MarketSourceSeedService

    package = load_market_source_package(MANIFEST_PATH)
    return await MarketSourceSeedService(
        MarketRepository(),
        transaction_factory=lambda: _default_transaction_scope(config, database),
    ).seed(package)


async def _default_official_audit(
    config: Mapping[str, object], database: str
) -> object:
    from backend.domain.assets import load_asset_package
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.market_sources import load_market_source_package
    from backend.repositories.assets import AssetRepository
    from backend.repositories.market import MarketRepository
    from backend.scripts.seed_market_sources import MANIFEST_PATH as MARKET_MANIFEST
    from backend.scripts.seed_writer_assets import MANIFEST_PATH as ASSET_MANIFEST
    from backend.services.assets import AssetSeedService
    from backend.services.product_database_readiness import OfficialDataAudit

    assets = load_asset_package(ASSET_MANIFEST, mode="release")
    market = load_market_source_package(MARKET_MANIFEST)
    asset_report = await AssetSeedService(
        AssetRepository(),
        transaction_factory=None,
        connection_factory=lambda: _default_connection_scope(config, database),
    ).dry_run(assets)
    market_repository = MarketRepository()
    async with _default_connection_scope(config, database) as session:
        market_rows = await market_repository.list_seed_inventory(session)
    by_key = {row.get("stable_key"): row for row in market_rows}
    expected_keys = {source.stable_key for source in market.sources}
    if set(by_key) != expected_keys or len(by_key) != len(market_rows):
        raise ValueError
    for source in market.sources:
        row = by_key[source.stable_key]
        policy = row.get("policy")
        head = row.get("head")
        if not isinstance(policy, dict) or not isinstance(head, dict):
            raise ValueError
        expected_policy = source.policy
        if (
            row.get("adapter_key") != source.adapter_key
            or row.get("display_name") != source.display_name
            or row.get("public_config_json")
            != canonical_json(dict(source.public_config))
            or row.get("status") != "active"
            or policy.get("source_id") != row.get("id")
            or policy.get("revision") != 1
            or policy.get("policy_status") != expected_policy.status
            or policy.get("policy_version") != expected_policy.policy_version
            or policy.get("checked_at") != expected_policy.checked_at
            or policy.get("evidence_url") != expected_policy.evidence_url
            or policy.get("evidence_hash") != expected_policy.evidence_hash
            or policy.get("allowed_origins_json")
            != canonical_json(list(expected_policy.allowed_origins))
            or policy.get("path_prefixes_json")
            != canonical_json(list(expected_policy.path_prefixes))
            or int(policy.get("enabled", -1)) != int(expected_policy.enabled)
            or policy.get("interval_minutes")
            != expected_policy.request_interval_seconds // 60
            or policy.get("next_run_at") is not None
            or policy.get("content_hash") != source.policy_hash
            or head.get("source_id") != row.get("id")
            or head.get("revision_id") != policy.get("id")
            or head.get("revision") != 1
            or head.get("content_hash") != source.policy_hash
        ):
            raise ValueError
    if (
        asset_report.inserted != 0
        or asset_report.replayed
        != len(assets.styles) + len(assets.experience_cards)
        or asset_report.advanced != 0
    ):
        raise ValueError
    return OfficialDataAudit(
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


async def _default_smoke(
    config: Mapping[str, object], database: str
) -> object:
    from backend.services.product_database_inventory import (
        assert_storage_policy,
        inventory_database,
        read_table_storage,
    )
    from backend.services.product_database_readiness import SmokeResult

    async def inspect_local(session: object) -> None:
        await inventory_database(session, database)
        storage = await read_table_storage(session, database)
        assert_storage_policy(storage)

    await _run_default_session(config, inspect_local)
    return SmokeResult(provider_calls=0, outbound_requests=0)


def _default_dependencies() -> PreparationCommandDependencies:
    from backend.scripts.configure_local_mysql import restrict_windows_acl
    from backend.services.product_database_backup import (
        create_logical_backup,
        preflight_client_connection,
        preflight_client_pair,
        private_mysql_option_file,
    )
    from backend.services.product_database_readiness import prepare_product_database

    def version_runner(path: Path) -> object:
        return subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            check=False,
        )

    def preflight_clients(
        dump: Path, mysql: Path, repository: Path
    ) -> object:
        return preflight_client_pair(dump, mysql, repository, version_runner)

    def read_config() -> object:
        from backend.config import require_mysql_config

        return require_mysql_config()

    def option_file(config: Mapping[str, object], root: Path) -> object:
        connection = _mysql_connection_config(config)
        return private_mysql_option_file(
            {
                name: connection[name]
                for name in ("host", "port", "user", "password")
            },
            root,
            restrict_windows_acl,
            repository_root=REPOSITORY_ROOT,
        )

    def create_backup(
        pair: object,
        option: Path,
        authority: DatabaseInventory,
        directory: Path,
        filename: str,
        previous_hash: str,
    ) -> object:
        return create_logical_backup(
            pair,  # type: ignore[arg-type]
            option,
            authority,
            directory,
            filename,
            previous_hash,
            subprocess.run,
            restrict_windows_acl,
            repository_root=REPOSITORY_ROOT,
        )

    return PreparationCommandDependencies(
        preflight_clients=preflight_clients,
        read_config=read_config,
        option_file=option_file,
        preflight_connection=lambda pair, option: preflight_client_connection(
            pair, option, subprocess.run
        ),
        inventory_database=_default_inventory,
        create_backup=create_backup,
        restore_drill=_default_restore_drill,
        current_schema_proof=_default_current_schema_proof,
        database_boundary=_default_database_boundary,
        seed_assets=_default_seed_assets,
        seed_market=_default_seed_market,
        read_storage=_default_storage,
        audit_official_data=_default_official_audit,
        smoke=_default_smoke,
        prepare_service=prepare_product_database,
        publish_receipt=publish_readiness_receipt,
        id_factory=lambda: secrets.token_hex(16),
    )


def _is_inside(candidate: str, parent: str) -> bool:
    try:
        return os.path.commonpath((candidate, parent)) == parent
    except ValueError:
        return False


def _lexical_external_path(value: object, *, allow_directory: bool) -> Path:
    if type(value) is not str or not value or "\x00" in value:
        raise ValueError
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError
    if allow_directory and path.parent == path:
        raise ValueError
    normalized = os.path.normcase(os.path.normpath(str(path)))
    repository = os.path.normcase(os.path.normpath(str(REPOSITORY_ROOT)))
    if _is_inside(normalized, repository):
        raise ValueError
    return Path(normalized)


def _validated_arguments(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    failure = False
    try:
        validate_database_role("legacy", args.legacy_database)
        validate_database_role("new", args.new_database)
        backup_dir = _lexical_external_path(args.backup_dir, allow_directory=True)
        mysqldump = _lexical_external_path(args.mysqldump, allow_directory=False)
        mysql = _lexical_external_path(args.mysql, allow_directory=False)
        if mysqldump == mysql:
            raise ValueError
    except BaseException:
        failure = True
    if failure:
        _raise_fixed(_ARGUMENT_ERROR)
    return backup_dir, mysqldump, mysql


def _validate_approval(args: argparse.Namespace) -> None:
    if (
        args.confirm_legacy != LEGACY_DATABASE
        or args.confirm_new != NEW_DATABASE
        or args.confirm_prepare != _PREPARE_CONFIRMATION
    ):
        _raise_fixed(_APPROVAL_ERROR)


async def run_cli(
    argv: Sequence[str] | None = None,
    *,
    dependencies: object | None = None,
    output: Callable[[str], None] = print,
) -> int:
    """Preview safely by default; execute only after exact confirmation."""

    args = _argument_parser().parse_args(argv)
    backup_dir, mysqldump, mysql = _validated_arguments(args)
    if not args.execute:
        for line in (
            "mode=preview",
            f"legacy_database={LEGACY_DATABASE}",
            f"new_database={NEW_DATABASE}",
            "stage=approval-required",
        ):
            output(line)
        return 0

    _validate_approval(args)
    selected = dependencies or _default_dependencies()
    try:
        pair = await _invoke(
            selected.preflight_clients,  # type: ignore[attr-defined]
            mysqldump,
            mysql,
            REPOSITORY_ROOT,
        )
        config_value = await _invoke(selected.read_config)  # type: ignore[attr-defined]
        if not isinstance(config_value, Mapping):
            raise ValueError
        config = dict(config_value)
        if config.get("db") != LEGACY_DATABASE:
            raise ValueError

        backup_result: BackupReceipt | None = None

        async def inventory(role: str) -> object:
            try:
                database = {
                    "legacy-before": LEGACY_DATABASE,
                    "legacy-after": LEGACY_DATABASE,
                    "new": NEW_DATABASE,
                }[role]
            except (KeyError, TypeError):
                raise ProductDatabasePreparationCommandError(
                    _EXECUTION_ERROR
                ) from None
            return await _invoke(
                selected.inventory_database, config, database  # type: ignore[attr-defined]
            )

        async def create_backup(
            authority: DatabaseInventory, directory: Path
        ) -> object:
            nonlocal backup_result
            random_id = selected.id_factory()  # type: ignore[attr-defined]
            if type(random_id) is not str or _HEX_ID.fullmatch(random_id) is None:
                raise ValueError
            initial = advance_receipt(
                None,
                ReadinessState.INVENTORY_VERIFIED,
                inventory_hash(authority),
            )
            value = await _invoke(
                selected.create_backup,  # type: ignore[attr-defined]
                pair,
                option,
                authority,
                directory,
                f"novel_creator-phase7b-{random_id}.sql",
                canonical_receipt_hash(initial),
            )
            if type(value) is not BackupReceipt:
                raise ValueError
            backup_result = value
            return value

        async def restore_drill(backup: object, authority: object) -> object:
            return await _invoke(
                selected.restore_drill,  # type: ignore[attr-defined]
                config,
                pair,
                option,
                backup,
                authority,
                backup_dir,
            )

        async def current_schema_proof() -> object:
            return await _invoke(
                selected.current_schema_proof, config  # type: ignore[attr-defined]
            )

        def boundary(database: str) -> object:
            return selected.database_boundary(config, database)  # type: ignore[attr-defined]

        async def seed_assets(database: str) -> object:
            return await _invoke(
                selected.seed_assets, config, database  # type: ignore[attr-defined]
            )

        async def seed_market(database: str) -> object:
            return await _invoke(
                selected.seed_market, config, database  # type: ignore[attr-defined]
            )

        async def read_storage(database: str) -> object:
            return await _invoke(
                selected.read_storage, config, database  # type: ignore[attr-defined]
            )

        async def audit_official_data(database: str) -> object:
            return await _invoke(
                selected.audit_official_data, config, database  # type: ignore[attr-defined]
            )

        async def smoke(database: str) -> object:
            return await _invoke(
                selected.smoke, config, database  # type: ignore[attr-defined]
            )

        option_context = selected.option_file(config, backup_dir)  # type: ignore[attr-defined]
        with option_context as option:
            await _invoke(
                selected.preflight_connection, pair, option  # type: ignore[attr-defined]
            )
            receipt_value = await _invoke(
                selected.prepare_service,  # type: ignore[attr-defined]
                request=PreparationRequest(
                    LEGACY_DATABASE, NEW_DATABASE, backup_dir
                ),
                inventory=inventory,
                create_backup=create_backup,
                restore_drill=restore_drill,
                current_schema_proof=current_schema_proof,
                new_database_boundary=boundary,
                seed_assets=seed_assets,
                seed_market=seed_market,
                read_storage=read_storage,
                audit_official_data=audit_official_data,
                smoke=smoke,
            )
        if type(receipt_value) is not PreparationReceipt or backup_result is None:
            raise ValueError
        await _invoke(
            selected.publish_receipt,  # type: ignore[attr-defined]
            receipt_value,
            backup_dir / backup_result.backup_filename,
        )
    except BaseException as error:
        _raise_public(_sanitized(error, _EXECUTION_ERROR))

    for line in (
        "mode=execute",
        f"legacy_database={LEGACY_DATABASE}",
        f"new_database={NEW_DATABASE}",
        "stage=awaiting-cutover-approval",
        f"receipt_hash={canonical_receipt_hash(receipt_value)}",
    ):
        output(line)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(run_cli(argv))
    except SystemExit:
        raise
    except BaseException:
        print("Product database preparation failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
