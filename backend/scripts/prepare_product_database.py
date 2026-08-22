"""Explicit Stage A product database preparation command."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict, dataclass, fields
import inspect
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from typing import Callable, Mapping, NoReturn, Sequence

from backend.domain.json_contracts import canonical_json
from backend.domain.product_database_readiness import (
    BackupReceipt,
    DatabaseInventory,
    LEGACY_DATABASE,
    NEW_DATABASE,
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
from backend.services.product_database_backup import ProductDatabaseBackupError
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
_RECEIPT_DOCUMENT_ERROR = "readiness receipt document is invalid"
_EXECUTION_ERROR = "product database preparation execution failed"
_AUDIT_ERROR = "new database readiness audit failed"
_SMOKE_ERROR = "readiness smoke failed"
_RESTORE_DRILL_ERROR = "restore drill lifecycle failed"
_RESTORE_DRILL_CLEANUP_ERROR = "restore drill cleanup failed"
_LOCK_NAME = "novel_creator:phase7b:prepare"
_HEX_ID = re.compile(r"^[0-9a-f]{32}$", re.ASCII)
_MAX_RECEIPT_BYTES = 1_000_000
_BROWSER_SMOKE_PREFIX = "PHASE7B_BROWSER_SMOKE_SUMMARY="
_BROWSER_INTERNAL_EVIDENCE_PREFIX = "PHASE7B_BROWSER_INTERNAL_EVIDENCE="
_BROWSER_FAILURE_STAGE_PREFIX = "PHASE7B_BROWSER_FAILURE_STAGE="
_BROWSER_FAILURE_STAGES = frozenset(
    {
        "contract",
        "root-setup",
        "port-reservation",
        "backend-start",
        "vite-start",
        "browser-test",
        "runtime-audit",
        "server-cleanup",
        "port-cleanup",
        "artifact-cleanup",
    }
)
_BROWSER_INTERNAL_EVIDENCE_EXPECTED = {
    "firstStage": None,
    "firstCause": None,
    "scenarioCount": 1,
    "providerCalls": 0,
    "outboundRequests": 0,
    "processCount": 0,
    "portCount": 0,
    "artifactCount": 0,
}
_BROWSER_SMOKE_EXPECTED = {
    **_BROWSER_INTERNAL_EVIDENCE_EXPECTED,
    "rootCount": 0,
}
_BROWSER_NODE_COMMAND = ("node", "frontend/e2e/run-phase7b.mjs")
_BROWSER_SMOKE_TIMEOUT_SECONDS = 300
_BROWSER_RUNNER_TIMEOUT_SECONDS = 240
_BROWSER_ROOT_CLEANUP_SECONDS = 2.0
_BROWSER_ROOT_CLEANUP_ATTEMPTS = 8
_BROWSER_TASK_ROOT_KEY = "PHASE7B_BROWSER_TASK_ROOT"
_BROWSER_TASK_NONCE_KEY = "PHASE7B_BROWSER_TASK_NONCE"
_REFRESH_AUDIT_COLUMNS = (
    "source_id",
    "last_snapshot_id",
    "refresh_status",
    "lease_owner",
    "lease_expires_at",
    "last_attempted_at",
    "last_succeeded_at",
    "next_run_at",
    "public_error_code",
)


class ProductDatabasePreparationCommandError(RuntimeError):
    """A fixed, public-safe command failure."""


_FIXED_CLEANUP_MESSAGES = frozenset(
    {
        "private mysql option file cleanup failed",
        "logical backup cleanup failed",
        "logical restore cleanup failed",
        "product database cleanup failed",
        _BOUNDARY_CLEANUP_ERROR,
        _PROOF_CLEANUP_ERROR,
        _RECEIPT_CLEANUP_ERROR,
        _RESTORE_DRILL_CLEANUP_ERROR,
    }
)


class _HelpRequested(BaseException):
    """Private marker for the parser's sole successful early exit."""


class _BrowserRootLease:
    """No-share-delete Windows directory handle held across the child lifetime."""

    def __init__(
        self,
        handle: int,
        closer: Callable[[int], None],
        identity_reader: Callable[[int], object],
        delete_disposition: Callable[[int], None],
        path: Path,
        expected_owner_identity: tuple[int, int],
    ) -> None:
        self._handle: int | None = handle
        self._closer = closer
        self._identity_reader = identity_reader
        self._delete_disposition = delete_disposition
        self._identity = identity_reader(handle)
        current = path.stat(follow_symlinks=False)
        if (current.st_dev, current.st_ino) != expected_owner_identity:
            raise OSError
        self._expected_owner_identity = expected_owner_identity

    def delete_owned(
        self, path: Path, expected_owner_identity: tuple[int, int]
    ) -> None:
        handle = self._handle
        if (
            handle is None
            or expected_owner_identity != self._expected_owner_identity
            or self._identity_reader(handle) != self._identity
        ):
            raise OSError
        deadline = time.monotonic() + _BROWSER_ROOT_CLEANUP_SECONDS
        first_flow: BaseException | None = None
        last_error: BaseException | None = None
        for attempt in range(_BROWSER_ROOT_CLEANUP_ATTEMPTS):
            try:
                current = path.stat(follow_symlinks=False)
                if (current.st_dev, current.st_ino) != expected_owner_identity:
                    raise OSError
                if self._identity_reader(handle) != self._identity:
                    raise OSError
                for child in tuple(path.iterdir()):
                    if child.is_symlink() or child.is_file():
                        child.unlink()
                    elif child.is_dir():
                        shutil.rmtree(child)
                    else:
                        raise OSError
                if tuple(path.iterdir()):
                    raise OSError
                if self._identity_reader(handle) != self._identity:
                    raise OSError
                self._delete_disposition(handle)
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit) as error:
                if first_flow is None:
                    first_flow = error
                last_error = error
            except BaseException as error:
                last_error = error
            else:
                if first_flow is not None:
                    raise first_flow
                return
            if (
                attempt + 1 >= _BROWSER_ROOT_CLEANUP_ATTEMPTS
                or time.monotonic() >= deadline
            ):
                raise first_flow or last_error or RuntimeError
            time.sleep(0.02)
        raise first_flow or last_error or RuntimeError

    def close(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._closer(handle)
        self._handle = None


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
    browser_smoke_runner: Callable[..., object]
    prepare_service: Callable[..., object]
    publish_receipt: Callable[..., object]
    id_factory: Callable[[], str]


class _SafeArgumentParser(argparse.ArgumentParser):
    def exit(self, status: int = 0, message: str | None = None) -> None:
        if status == 0:
            if message:
                self._print_message(message, sys.stdout)
            raise _HelpRequested() from None
        raise ProductDatabasePreparationCommandError(_ARGUMENT_ERROR) from None

    def error(self, message: str) -> None:
        del message
        raise ProductDatabasePreparationCommandError(_ARGUMENT_ERROR) from None


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


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


def _is_exact_browser_record(
    value: object, expected: Mapping[str, object]
) -> bool:
    return (
        type(value) is dict
        and set(value) == set(expected)
        and all(
            type(value[key]) is type(expected_value)
            and value[key] == expected_value
            for key, expected_value in expected.items()
        )
    )


def _parse_canonical_json_document(document: str | bytes) -> object:
    if type(document) is bytes:
        text = document.decode("utf-8")
    elif type(document) is str:
        text = document
    else:
        raise TypeError
    value = json.loads(
        text,
        object_pairs_hook=_unique_json_object,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
    )
    if canonical_json(value) != text:
        raise ValueError
    return value


def _exact_receipt_values(
    value: object,
    receipt_type: type[StateReceipt] | type[BackupReceipt] | type[PreparationReceipt],
) -> dict[str, object]:
    if type(value) is not dict:
        raise TypeError
    expected = {field.name for field in fields(receipt_type)}
    if set(value) != expected:
        raise ValueError
    return value


def parse_state_receipt_document(document: str | bytes) -> StateReceipt:
    """Parse one exact canonical :class:`StateReceipt` document."""

    try:
        values = _exact_receipt_values(
            _parse_canonical_json_document(document), StateReceipt
        )
        return StateReceipt(**values)  # type: ignore[arg-type]
    except BaseException as error:
        _raise_public(_sanitized(error, _RECEIPT_DOCUMENT_ERROR))


def parse_backup_receipt_document(document: str | bytes) -> BackupReceipt:
    """Parse one exact canonical :class:`BackupReceipt` document."""

    try:
        values = _exact_receipt_values(
            _parse_canonical_json_document(document), BackupReceipt
        )
        return BackupReceipt(**values)  # type: ignore[arg-type]
    except BaseException as error:
        _raise_public(_sanitized(error, _RECEIPT_DOCUMENT_ERROR))


def parse_preparation_receipt_document(document: str | bytes) -> PreparationReceipt:
    """Parse and validate an exact canonical preparation receipt and hash chain."""

    try:
        values = _exact_receipt_values(
            _parse_canonical_json_document(document), PreparationReceipt
        )
        nested = values.get("receipts")
        if type(nested) is not list:
            raise TypeError
        receipts = tuple(
            StateReceipt(
                **_exact_receipt_values(value, StateReceipt)  # type: ignore[arg-type]
            )
            for value in nested
        )
        values = dict(values)
        values["receipts"] = receipts
        return PreparationReceipt(**values)  # type: ignore[arg-type]
    except BaseException as error:
        _raise_public(_sanitized(error, _RECEIPT_DOCUMENT_ERROR))


def _open_receipt_for_read(path: Path) -> object:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        return os.fdopen(descriptor, "rb", closefd=True)
    except BaseException:
        os.close(descriptor)
        raise


def _receipt_file_identity(value: object) -> tuple[int, int, int, int, int]:
    attributes = getattr(value, "st_file_attributes", 0)
    mode = getattr(value, "st_mode", None)
    identity = (
        getattr(value, "st_dev", None),
        getattr(value, "st_ino", None),
        getattr(value, "st_size", None),
        getattr(value, "st_mtime_ns", None),
        getattr(value, "st_ctime_ns", None),
    )
    if (
        type(attributes) is not int
        or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        or type(mode) is not int
        or not stat.S_ISREG(mode)
        or any(type(item) is not int for item in identity)
    ):
        raise ValueError
    return identity  # type: ignore[return-value]


def load_preparation_receipt(
    path: Path,
    *,
    opener: Callable[[Path], object] = _open_receipt_for_read,
    resolver: Callable[[Path], Path] = lambda value: value.resolve(strict=True),
    lstat_reader: Callable[[Path], object] = os.lstat,
    fstat_reader: Callable[[int], object] = os.fstat,
) -> PreparationReceipt:
    """Read and strictly validate a published preparation receipt."""

    try:
        receipt_path = Path(path)
        if (
            not receipt_path.is_absolute()
            or receipt_path.parent == receipt_path
            or ".." in receipt_path.parts
            or not receipt_path.name.endswith(".readiness.json")
            or _is_inside(
                os.path.normcase(os.path.normpath(str(receipt_path))),
                os.path.normcase(os.path.normpath(str(REPOSITORY_ROOT))),
            )
        ):
            raise ValueError
        resolved_before = Path(resolver(receipt_path))
        if (
            not resolved_before.is_absolute()
            or _is_inside(
                os.path.normcase(os.path.normpath(str(resolved_before))),
                os.path.normcase(os.path.normpath(str(REPOSITORY_ROOT))),
            )
            or os.path.normcase(os.path.normpath(str(resolved_before)))
            != os.path.normcase(os.path.normpath(str(receipt_path)))
        ):
            raise ValueError
        path_identity = _receipt_file_identity(lstat_reader(receipt_path))
        with opener(receipt_path) as handle:  # type: ignore[attr-defined]
            descriptor = handle.fileno()  # type: ignore[attr-defined]
            if type(descriptor) is not int:
                raise ValueError
            before = _receipt_file_identity(fstat_reader(descriptor))
            if path_identity != before:
                raise ValueError
            size = before[2]
            if not 0 < size <= _MAX_RECEIPT_BYTES:
                raise ValueError
            document = handle.read(size + 1)  # type: ignore[attr-defined]
            after = _receipt_file_identity(fstat_reader(descriptor))
            if type(document) is not bytes or len(document) != size or after != before:
                raise ValueError
        if (
            _receipt_file_identity(lstat_reader(receipt_path)) != path_identity
            or os.path.normcase(os.path.normpath(str(Path(resolver(receipt_path)))))
            != os.path.normcase(os.path.normpath(str(resolved_before)))
        ):
            raise ValueError
        return parse_preparation_receipt_document(document)
    except BaseException as error:
        _raise_public(_sanitized(error, _RECEIPT_DOCUMENT_ERROR))


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


def _fixed_failure_messages(error: BaseException) -> tuple[str, ...]:
    if isinstance(error, BaseExceptionGroup):
        return tuple(
            message
            for child in error.exceptions
            for message in _fixed_failure_messages(child)
        )
    if type(error) in (
        ProductDatabasePreparationCommandError,
        ProductDatabaseReadinessError,
        ProductDatabaseBackupError,
    ):
        return (str(error),)
    return ()


def _safe_failure_fields(stage: str, error: BaseException) -> tuple[str, str]:
    messages = _fixed_failure_messages(error)
    cleanup_failed = any(
        message in _FIXED_CLEANUP_MESSAGES for message in messages
    )
    if (
        stage == "browser-smoke"
        and messages
        and all(message in _FIXED_CLEANUP_MESSAGES for message in messages)
    ):
        stage = "boundary-commit"
    return stage, "failed" if cleanup_failed else "no-failure-reported"


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


@contextmanager
def _primary_first_context(manager: object):  # type: ignore[no-untyped-def]
    """Retain a body primary when a synchronous resource cleanup also fails."""

    manager_type = type(manager)
    enter = manager_type.__enter__  # type: ignore[attr-defined]
    exit_context = manager_type.__exit__  # type: ignore[attr-defined]
    value = enter(manager)
    primary: BaseException | None = None
    traceback: object | None = None
    try:
        yield value
    except BaseException as error:
        primary = error
        traceback = error.__traceback__

    cleanup: BaseException | None = None
    suppressed = False
    try:
        suppressed = bool(
            exit_context(
                manager,
                None if primary is None else type(primary),
                primary,
                traceback,
            )
        )
    except BaseException as error:
        cleanup = error

    if primary is not None and cleanup is not None:
        raise BaseExceptionGroup(
            _EXECUTION_ERROR,
            [primary, cleanup],
        ) from None
    if primary is not None and not suppressed:
        raise primary.with_traceback(traceback) from None  # type: ignore[arg-type]
    if cleanup is not None:
        raise cleanup from None


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
        document = canonical_json(asdict(receipt))
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
        closing.close()  # type: ignore[attr-defined]
        handle = None
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
        refresh_rows = tuple(
            await session.fetchall(  # type: ignore[attr-defined]
                """SELECT source_id,last_snapshot_id,refresh_status,lease_owner,
                          lease_expires_at,last_attempted_at,last_succeeded_at,
                          next_run_at,public_error_code
                   FROM market_source_refresh_states
                   ORDER BY source_id""",
                (),
            )
        )
    by_key = {row.get("stable_key"): row for row in market_rows}
    expected_keys = {source.stable_key for source in market.sources}
    try:
        if set(by_key) != expected_keys or len(by_key) != len(market_rows):
            raise ValueError
        for source in market.sources:
            row = by_key[source.stable_key]
            policy = row.get("policy")
            head = row.get("head")
            if type(policy) is not dict or type(head) is not dict:
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
        expected_source_ids = tuple(
            by_key[source.stable_key].get("id") for source in market.sources
        )
        if (
            type(refresh_rows) is not tuple
            or len(expected_source_ids) != 2
            or any(type(source_id) is not str or not source_id for source_id in expected_source_ids)
            or len(set(expected_source_ids)) != len(expected_source_ids)
            or len(refresh_rows) != len(expected_source_ids)
        ):
            raise ValueError
        observed_source_ids: list[str] = []
        for row in refresh_rows:
            if type(row) is not dict or set(row) != set(_REFRESH_AUDIT_COLUMNS):
                raise ValueError
            source_id = row["source_id"]
            if (
                type(source_id) is not str
                or not source_id
                or type(row["refresh_status"]) is not str
                or row["refresh_status"] != "idle"
                or any(
                    row[column] is not None
                    for column in _REFRESH_AUDIT_COLUMNS
                    if column not in ("source_id", "refresh_status")
                )
            ):
                raise ValueError
            observed_source_ids.append(source_id)
        if (
            len(set(observed_source_ids)) != len(observed_source_ids)
            or set(observed_source_ids) != set(expected_source_ids)
        ):
            raise ValueError
        if (
            asset_report.inserted != 0
            or asset_report.replayed
            != len(assets.styles) + len(assets.experience_cards)
            or asset_report.advanced != 0
        ):
            raise ValueError
    except BaseException as error:
        _raise_public(_sanitized(error, _AUDIT_ERROR))
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


def _remove_owned_browser_root(
    path: Path,
    *,
    parent: Path,
    owner_identity: tuple[int, int],
    remove_temp: Callable[[Path], object],
) -> None:
    resolved_parent = parent.resolve(strict=True)
    deadline = time.monotonic() + _BROWSER_ROOT_CLEANUP_SECONDS
    first_flow: BaseException | None = None
    last_error: BaseException | None = None
    for attempt in range(_BROWSER_ROOT_CLEANUP_ATTEMPTS):
        matches: list[Path] = []
        for candidate in resolved_parent.iterdir():
            try:
                if candidate.is_symlink():
                    continue
                current = candidate.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if (current.st_dev, current.st_ino) == owner_identity:
                matches.append(candidate)
        if len(matches) > 1:
            raise RuntimeError
        if not matches:
            if path.exists() or path.is_symlink():
                raise RuntimeError
            if first_flow is not None:
                raise first_flow
            return
        owned_path = matches[0]
        try:
            if owned_path.is_symlink():
                raise RuntimeError
            current = owned_path.stat(follow_symlinks=False)
            if (current.st_dev, current.st_ino) != owner_identity:
                raise RuntimeError
            remove_temp(owned_path)
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit) as error:
            if first_flow is None:
                first_flow = error
            last_error = error
        except BaseException as error:
            last_error = error
        if (
            attempt + 1 >= _BROWSER_ROOT_CLEANUP_ATTEMPTS
            or time.monotonic() >= deadline
        ):
            raise first_flow or last_error or RuntimeError
        time.sleep(0.02)
    raise first_flow or last_error or RuntimeError


def _open_browser_root_lease(
    path: Path, expected_owner_identity: tuple[int, int]
) -> _BrowserRootLease:
    if os.name != "nt":
        raise OSError
    import ctypes
    from ctypes import wintypes
    from backend.services import product_database_backup as backup_safety

    kernel32 = backup_safety._kernel32()
    creator = kernel32.CreateFileW  # type: ignore[attr-defined]
    creator.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    creator.restype = wintypes.HANDLE
    opened = creator(
        str(path),
        0x00010000 | 0x00000080,
        0x00000001 | 0x00000002,
        None,
        3,
        0x02000000,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if opened in (None, 0, invalid):
        raise OSError
    opened_handle = int(opened)
    try:
        return _BrowserRootLease(
            opened_handle,
            backup_safety._close_windows_handle,
            backup_safety._identity_from_handle,
            backup_safety._set_delete_disposition,
            path,
            expected_owner_identity,
        )
    except BaseException as primary:
        try:
            backup_safety._close_windows_handle(opened_handle)
        except BaseException as cleanup:
            raise BaseExceptionGroup(
                _SMOKE_ERROR, [primary, cleanup]
            ) from None
        raise primary from None


def _close_browser_root_lease(lease: object) -> None:
    close = getattr(lease, "close", None)
    if not callable(close):
        raise TypeError
    deadline = time.monotonic() + _BROWSER_ROOT_CLEANUP_SECONDS
    first_flow: BaseException | None = None
    last_error: BaseException | None = None
    for attempt in range(_BROWSER_ROOT_CLEANUP_ATTEMPTS):
        try:
            close()
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit) as error:
            if first_flow is None:
                first_flow = error
            last_error = error
        except BaseException as error:
            last_error = error
        else:
            if first_flow is not None:
                raise first_flow
            return
        if (
            attempt + 1 >= _BROWSER_ROOT_CLEANUP_ATTEMPTS
            or time.monotonic() >= deadline
        ):
            raise first_flow or last_error or RuntimeError
        time.sleep(0.02)
    raise first_flow or last_error or RuntimeError


def _default_browser_smoke_runner(
    *,
    command: tuple[str, ...],
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: int,
    executable_resolver: Callable[[str], str | None] = shutil.which,
    guarded_spawn: Callable[..., object] | None = None,
    stop_process: Callable[..., object] | None = None,
    stop_unassigned: Callable[[object], list[BaseException]] | None = None,
    nonce_factory: Callable[[], str] = lambda: secrets.token_hex(16),
    temp_parent: Path | None = None,
    temp_dir_factory: Callable[[Path], str] | None = None,
    remove_temp: Callable[[Path], object] = shutil.rmtree,
    root_lease_factory: Callable[[Path, tuple[int, int]], object] = (
        _open_browser_root_lease
    ),
) -> object:
    from backend.scripts import run_milestone2_l4_session as process_safety

    errors: list[BaseException] = []
    child: object | None = None
    guard: object | None = None
    task_root: Path | None = None
    sentinel: object | None = None
    owner_identity: tuple[int, int] | None = None
    root_lease: object | None = None
    root_lease_has_delete_authority = False
    result: object | None = None
    selected_parent = (
        Path(tempfile.gettempdir()) / "novel-creator-phase7b-private"
        if temp_parent is None
        else Path(temp_parent)
    )
    selected_temp_factory = temp_dir_factory or (
        lambda prefix: tempfile.mkdtemp(
            prefix=Path(prefix).name, dir=Path(prefix).parent
        )
    )
    try:
        if (
            command != _BROWSER_NODE_COMMAND
            or Path(cwd).resolve(strict=True) != REPOSITORY_ROOT.resolve(strict=True)
            or type(timeout_seconds) is not int
            or timeout_seconds <= _BROWSER_RUNNER_TIMEOUT_SECONDS
            or type(environment) is not dict
            or any(
                type(key) is not str or type(value) is not str
                for key, value in environment.items()
            )
        ):
            raise ValueError
        resolved_node_value = executable_resolver("node")
        if type(resolved_node_value) is not str:
            raise ValueError
        resolved_node = Path(resolved_node_value).resolve(strict=True)
        if (
            not resolved_node.is_absolute()
            or not resolved_node.is_file()
            or resolved_node.name.lower() not in ("node", "node.exe")
        ):
            raise ValueError
        nonce = nonce_factory()
        if type(nonce) is not str or _HEX_ID.fullmatch(nonce) is None:
            raise ValueError
        task_root, sentinel = process_safety._create_owned_temp(
            selected_parent, nonce, "browser", selected_temp_factory
        )
        acquired_before_lease = task_root.stat(follow_symlinks=False)
        owner_identity = (
            acquired_before_lease.st_dev,
            acquired_before_lease.st_ino,
        )
        root_lease = root_lease_factory(task_root, owner_identity)
        if (
            not callable(getattr(root_lease, "close", None))
            or not callable(getattr(root_lease, "delete_owned", None))
        ):
            raise TypeError
        acquired_after_lease = task_root.stat(follow_symlinks=False)
        if not os.path.samestat(acquired_before_lease, acquired_after_lease):
            raise RuntimeError
        process_safety._validate_owned_temp(
            task_root, selected_parent, nonce, "browser", sentinel
        )
        root_lease_has_delete_authority = True
        child_environment = dict(environment)
        child_environment.update(
            {
                _BROWSER_TASK_ROOT_KEY: str(task_root),
                _BROWSER_TASK_NONCE_KEY: nonce,
            }
        )
        spawn = guarded_spawn or process_safety._spawn_guarded_process
        spawned = spawn(
            (str(resolved_node), *command[1:]),
            {
                "cwd": REPOSITORY_ROOT,
                "env": child_environment,
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "shell": False,
            },
            platform_name=os.name,
        )
        if type(spawned) is not tuple or len(spawned) != 2:
            raise TypeError
        child, guard = spawned
        if child is None or not callable(getattr(guard, "cleanup", None)):
            raise TypeError
        communicate = getattr(child, "communicate", None)
        if not callable(communicate):
            raise TypeError
        stdout, stderr = communicate(timeout=_BROWSER_RUNNER_TIMEOUT_SECONDS)
        returncode = getattr(child, "returncode", None)
        if (
            type(returncode) is not int
            or type(stdout) is not str
            or type(stderr) is not str
        ):
            raise TypeError
        result = subprocess.CompletedProcess(
            args=(str(resolved_node), *command[1:]),
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )
    except BaseException as error:
        errors.append(error)
    finally:
        if child is not None and callable(getattr(guard, "cleanup", None)):
            try:
                cleanup_errors = (stop_process or process_safety._stop_process)(
                    child, guard=guard
                )
                if type(cleanup_errors) is not list or any(
                    not isinstance(error, BaseException) for error in cleanup_errors
                ):
                    raise TypeError
                errors.extend(cleanup_errors)
            except BaseException as error:
                errors.append(error)
        elif child is not None:
            try:
                cleanup_errors = (
                    stop_unassigned or process_safety._stop_unassigned_child
                )(child)
                if type(cleanup_errors) is not list or any(
                    not isinstance(error, BaseException) for error in cleanup_errors
                ):
                    raise TypeError
                errors.extend(cleanup_errors)
            except BaseException as error:
                errors.append(error)
        handle_delete_established = False
        if root_lease is not None and root_lease_has_delete_authority:
            try:
                root_lease.delete_owned(  # type: ignore[attr-defined]
                    task_root, owner_identity
                )
                handle_delete_established = True
            except BaseException as error:
                errors.append(error)
        if root_lease is not None:
            try:
                _close_browser_root_lease(root_lease)
            except BaseException as error:
                errors.append(error)
        if handle_delete_established:
            if task_root is not None and (task_root.exists() or task_root.is_symlink()):
                errors.append(RuntimeError())
        elif task_root is not None and owner_identity is not None:
            try:
                _remove_owned_browser_root(
                    task_root,
                    parent=selected_parent,
                    owner_identity=owner_identity,
                    remove_temp=remove_temp,
                )
            except BaseException as error:
                errors.append(error)
        elif task_root is not None:
            errors.append(RuntimeError())
    if errors:
        _raise_public(_combined(errors, _SMOKE_ERROR))
    if result is None:
        _raise_public(ProductDatabasePreparationCommandError(_SMOKE_ERROR))
    return result


def run_owned_phase7b_browser(
    *,
    node_command: tuple[str, ...],
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: int,
    runner: Callable[..., object],
    root_factory: Callable[..., object],
) -> dict[str, object]:
    """Own the browser lifecycle and return only post-cleanup safe evidence."""

    try:
        if (
            node_command != _BROWSER_NODE_COMMAND
            or Path(cwd).resolve(strict=True) != REPOSITORY_ROOT.resolve(strict=True)
            or type(environment) is not dict
            or any(
                type(key) is not str or type(value) is not str
                for key, value in environment.items()
            )
            or type(timeout_seconds) is not int
            or timeout_seconds <= _BROWSER_RUNNER_TIMEOUT_SECONDS
            or not callable(runner)
            or not callable(root_factory)
        ):
            raise ValueError
        completed = runner(
            command=node_command,
            cwd=REPOSITORY_ROOT,
            environment=dict(environment),
            timeout_seconds=timeout_seconds,
            root_lease_factory=root_factory,
        )
        returncode = getattr(completed, "returncode", None)
        stdout = getattr(completed, "stdout", None)
        stderr = getattr(completed, "stderr", None)
        if (
            type(returncode) is not int
            or returncode != 0
            or type(stdout) is not str
            or type(stderr) is not str
        ):
            raise ValueError
        evidence_documents = [
            line[len(_BROWSER_INTERNAL_EVIDENCE_PREFIX) :]
            for line in stdout.splitlines()
            if line.startswith(_BROWSER_INTERNAL_EVIDENCE_PREFIX)
        ]
        if len(evidence_documents) != 1:
            raise ValueError
        evidence = json.loads(
            evidence_documents[0],
            object_pairs_hook=_unique_json_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        if (
            not _is_exact_browser_record(
                evidence, _BROWSER_INTERNAL_EVIDENCE_EXPECTED
            )
            or evidence_documents[0] != canonical_json(evidence)
        ):
            raise ValueError
        return {**evidence, "rootCount": 0}
    except BaseException as error:
        _raise_public(_sanitized(error, _SMOKE_ERROR))


def _browser_failure_stage(completed: object) -> str | None:
    returncode = getattr(completed, "returncode", None)
    stderr = getattr(completed, "stderr", None)
    if type(returncode) is not int or returncode == 0 or type(stderr) is not str:
        return None
    stages = [
        line[len(_BROWSER_FAILURE_STAGE_PREFIX) :]
        for line in stderr.splitlines()
        if line.startswith(_BROWSER_FAILURE_STAGE_PREFIX)
    ]
    if len(stages) != 1 or stages[0] not in _BROWSER_FAILURE_STAGES:
        return None
    return stages[0]


async def _default_smoke(
    config: Mapping[str, object],
    database: str,
    runner: Callable[..., object],
) -> object:
    from backend.services.product_database_readiness import SmokeResult

    del config
    try:
        validate_database_role("new", database)
        if not callable(runner):
            raise TypeError
        environment = dict(os.environ)
        environment.update(
            {
                "MYSQL_DB": database,
                "MARKET_SCHEDULER_ENABLED": "false",
            }
        )
        summary = await _invoke(
            run_owned_phase7b_browser,
            node_command=_BROWSER_NODE_COMMAND,
            cwd=REPOSITORY_ROOT,
            environment=environment,
            timeout_seconds=_BROWSER_SMOKE_TIMEOUT_SECONDS,
            runner=runner,
            root_factory=_open_browser_root_lease,
        )
        if (
            not _is_exact_browser_record(summary, _BROWSER_SMOKE_EXPECTED)
        ):
            raise ValueError
        return SmokeResult(provider_calls=0, outbound_requests=0)
    except BaseException as error:
        _raise_public(_sanitized(error, _SMOKE_ERROR))


def _default_dependencies() -> PreparationCommandDependencies:
    from backend.services.product_database_backup import (
        create_logical_backup,
        preflight_backup_directory,
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
        private_root = preflight_backup_directory(root, REPOSITORY_ROOT)
        return private_mysql_option_file(
            {
                name: connection[name]
                for name in ("host", "port", "user", "password")
            },
            private_root,
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
            runner=subprocess.run,
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
        browser_smoke_runner=_default_browser_smoke_runner,
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
    stage = "preflight"
    browser_stage = "unavailable"
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
            nonlocal stage
            try:
                stage, database = {
                    "legacy-before": ("legacy-inventory-before", LEGACY_DATABASE),
                    "legacy-after": ("legacy-inventory-after", LEGACY_DATABASE),
                    "new": ("readiness-audit", NEW_DATABASE),
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
            nonlocal backup_result, stage
            stage = "backup"
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
            nonlocal stage
            stage = "restore-drill"
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
            nonlocal stage
            stage = "schema-proof"
            return await _invoke(
                selected.current_schema_proof, config  # type: ignore[attr-defined]
            )

        def boundary(database: str) -> object:
            nonlocal stage
            stage = "new-database-init"
            return selected.database_boundary(config, database)  # type: ignore[attr-defined]

        async def seed_assets(database: str) -> object:
            nonlocal stage
            stage = "asset-seed"
            return await _invoke(
                selected.seed_assets, config, database  # type: ignore[attr-defined]
            )

        async def seed_market(database: str) -> object:
            nonlocal stage
            stage = "market-seed"
            return await _invoke(
                selected.seed_market, config, database  # type: ignore[attr-defined]
            )

        async def read_storage(database: str) -> object:
            nonlocal stage
            stage = "readiness-audit"
            return await _invoke(
                selected.read_storage, config, database  # type: ignore[attr-defined]
            )

        async def audit_official_data(database: str) -> object:
            nonlocal stage
            stage = "readiness-audit"
            return await _invoke(
                selected.audit_official_data, config, database  # type: ignore[attr-defined]
            )

        async def smoke(database: str) -> object:
            nonlocal browser_stage, stage
            stage = "browser-smoke"

            def browser_runner(**kwargs: object) -> object:
                nonlocal browser_stage
                completed = selected.browser_smoke_runner(  # type: ignore[attr-defined]
                    **kwargs
                )
                browser_stage = _browser_failure_stage(completed) or "unavailable"
                return completed

            return await _invoke(
                selected.smoke,  # type: ignore[attr-defined]
                config,
                database,
                browser_runner,
            )

        option_context = selected.option_file(config, backup_dir)  # type: ignore[attr-defined]
        with _primary_first_context(option_context) as option:
            stage = "preflight"
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
            stage = "boundary-commit"
        stage = "receipt-publish"
        if type(receipt_value) is not PreparationReceipt or backup_result is None:
            raise ValueError
        await _invoke(
            selected.publish_receipt,  # type: ignore[attr-defined]
            receipt_value,
            backup_dir / backup_result.backup_filename,
        )
    except BaseException as error:
        public_stage, cleanup = _safe_failure_fields(stage, error)
        lines = [
            "outcome=failed",
            f"stage={public_stage}",
            f"cleanup={cleanup}",
        ]
        if public_stage == "browser-smoke":
            lines.append(f"browser_stage={browser_stage}")
        for line in lines:
            output(line)
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
    except _HelpRequested:
        return 0
    except SystemExit:
        print("Product database preparation failed.", file=sys.stderr)
        return 1
    except BaseException:
        print("Product database preparation failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
