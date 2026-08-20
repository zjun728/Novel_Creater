"""Explicit Stage B product database configuration cutover and recovery."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import inspect
import json
import os
from pathlib import Path
import sys
from typing import Callable, ContextManager, Mapping, NoReturn, Sequence, cast

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.product_database_readiness import (
    DatabaseInventory,
    LEGACY_DATABASE,
    NEW_DATABASE,
    PreparationReceipt,
    ReadinessState,
    StateReceipt,
    advance_receipt,
    inventory_hash,
)
from backend.scripts.configure_local_mysql import (
    LOCAL_CONFIG_PATH,
    LocalDocumentSnapshot,
    atomic_compare_and_swap_local_document,
    capture_local_document_snapshot,
    restrict_windows_acl,
)
from backend.scripts.prepare_product_database import load_preparation_receipt
from backend.services.product_database_backup import verify_backup_file
from backend.services.product_database_lifecycle_lock import (
    ProductDatabaseLifecycleError,
    product_database_lifecycle_lock,
)


_CUTOVER_CONFIRMATION = "CUTOVER-PHASE7B"
_RECOVERY_CONFIRMATION = "RECOVER-PHASE7B"
_REQUIRED_CONFIG_KEYS = frozenset({
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DB",
})
_OPTIONAL_CONFIG_KEYS = frozenset({"CORPUS_ROOT", "MANAGED_CORPUS_ROOT"})
_APPROVAL_ERROR = "product database cutover approval is invalid"
_CONFIG_ERROR = "product database cutover configuration is invalid"
_EVIDENCE_ERROR = "product database cutover evidence is invalid"
_SMOKE_ERROR = "product database cutover smoke failed"
_ROLLBACK_ERROR = "product database cutover rollback failed"
_RECOVERY_ERROR = "product database recovery failed"
_LIFECYCLE_ERROR = "product database lifecycle lock failed"
_LIFECYCLE_CLEANUP_ERROR = "product database lifecycle lock cleanup failed"
_BROWSER_SMOKE_EXPECTED = {
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
_BROWSER_SMOKE_TIMEOUT_SECONDS = 300
_MYSQL_ENVIRONMENT_KEYS = (
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DB",
)


class ProductDatabaseCutoverError(RuntimeError):
    """One fixed, public-safe Stage B command failure."""


class _HelpRequested(BaseException):
    pass


@dataclass(frozen=True)
class CutoverResult:
    state: str
    receipts: tuple[StateReceipt, ...] = ()


class _SafeArgumentParser(argparse.ArgumentParser):
    def exit(self, status: int = 0, message: str | None = None) -> None:
        if status == 0:
            if message:
                self._print_message(message, sys.stdout)
            raise _HelpRequested() from None
        raise ProductDatabaseCutoverError(_APPROVAL_ERROR) from None

    def error(self, message: str) -> NoReturn:
        del message
        raise ProductDatabaseCutoverError(_APPROVAL_ERROR) from None


def _argument_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(description="Cut over the Writer Core product database.")
    parser.add_argument("--receipt")
    parser.add_argument("--database")
    parser.add_argument("--confirm-cutover")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--recover-legacy", action="store_true")
    return parser


def _raise(error: BaseException) -> NoReturn:
    try:
        raise error from None
    except BaseException as outgoing:
        outgoing.__cause__ = None
        outgoing.__context__ = None
        outgoing.__suppress_context__ = True
        raise


def _exception_group_children(
    error: BaseExceptionGroup,
) -> tuple[BaseException, ...] | None:
    try:
        children = BaseExceptionGroup.exceptions.__get__(
            error,
            BaseExceptionGroup,
        )
    except BaseException:
        return None
    if (
        type(children) is not tuple
        or not children
        or not all(issubclass(type(child), BaseException) for child in children)
    ):
        return None
    return children


def _is_exception_kind(
    error: BaseException,
    kinds: tuple[type[BaseException], ...],
) -> bool:
    actual_type = type(error)
    return any(issubclass(actual_type, kind) for kind in kinds)


def _sanitized(error: BaseException, message: str) -> BaseException:
    if _is_exception_kind(error, (BaseExceptionGroup,)):
        children = _exception_group_children(error)
        if children is None:
            return ProductDatabaseCutoverError(message)
        return BaseExceptionGroup(
            message,
            [_sanitized(child, message) for child in children],
        )
    if _is_exception_kind(error, (asyncio.CancelledError,)):
        return asyncio.CancelledError()
    if _is_exception_kind(error, (KeyboardInterrupt,)):
        return KeyboardInterrupt()
    if _is_exception_kind(error, (SystemExit,)):
        if type(error) is SystemExit:
            code = SystemExit.code.__get__(error, SystemExit)
            if type(code) is int:
                return SystemExit(code)
        return SystemExit()
    return ProductDatabaseCutoverError(message)


async def _invoke(
    operation: Callable[..., object], *args: object, **kwargs: object
) -> object:
    value = operation(*args, **kwargs)
    if inspect.isawaitable(value):
        return await value
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _parse_local_document(document: bytes) -> dict[str, object]:
    try:
        value = json.loads(
            document.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        if type(value) is not dict:
            raise ValueError
        keys = set(value)
        if not _REQUIRED_CONFIG_KEYS <= keys or not keys <= (
            _REQUIRED_CONFIG_KEYS | _OPTIONAL_CONFIG_KEYS
        ):
            raise ValueError
        if (
            type(value["MYSQL_HOST"]) is not str
            or not value["MYSQL_HOST"].strip()
            or type(value["MYSQL_PORT"]) is not int
            or not 1 <= value["MYSQL_PORT"] <= 65535
            or type(value["MYSQL_USER"]) is not str
            or not value["MYSQL_USER"].strip()
            or type(value["MYSQL_PASSWORD"]) is not str
            or not value["MYSQL_PASSWORD"]
            or type(value["MYSQL_DB"]) is not str
        ):
            raise ValueError
        for optional in _OPTIONAL_CONFIG_KEYS & keys:
            if type(value[optional]) is not str or not value[optional].strip():
                raise ValueError
        return value
    except BaseException as error:
        _raise(_sanitized(error, _CONFIG_ERROR))


def read_local_document(path: Path) -> dict[str, object]:
    """Read one strict complete local configuration document."""
    try:
        return _parse_local_document(capture_local_document_snapshot(path).content)
    except BaseException as error:
        _raise(_sanitized(error, _CONFIG_ERROR))


def _connection_config(document: Mapping[str, object]) -> dict[str, object]:
    return {
        "host": document["MYSQL_HOST"],
        "port": document["MYSQL_PORT"],
        "user": document["MYSQL_USER"],
        "password": document["MYSQL_PASSWORD"],
        "db": document["MYSQL_DB"],
        "charset": "utf8mb4",
        "autocommit": True,
    }


def _validate_observed_inventories(
    value: object, receipt: PreparationReceipt | None = None
) -> tuple[DatabaseInventory, DatabaseInventory]:
    if type(value) is not tuple or len(value) != 2:
        raise ValueError
    legacy, new = value
    if (
        type(legacy) is not DatabaseInventory
        or type(new) is not DatabaseInventory
        or legacy.database != LEGACY_DATABASE
        or new.database != NEW_DATABASE
    ):
        raise ValueError
    if receipt is not None and (
        inventory_hash(legacy) != receipt.legacy_inventory_hash
        or inventory_hash(new) != receipt.new_inventory_hash
    ):
        raise ValueError
    return legacy, new


def _cutover_receipts(receipt: PreparationReceipt) -> tuple[StateReceipt, ...]:
    previous = receipt.receipts[-1]
    switched = advance_receipt(
        previous,
        ReadinessState.CONFIGURATION_SWITCHED,
        canonical_hash({"MYSQL_DB": NEW_DATABASE}),
    )
    verified = advance_receipt(
        switched,
        ReadinessState.CUTOVER_VERIFIED,
        receipt.new_inventory_hash,
    )
    retained = advance_receipt(
        verified,
        ReadinessState.LEGACY_RETAINED,
        receipt.legacy_inventory_hash,
    )
    return switched, verified, retained


def _lock_boundary_error(
    lock_error: BaseException,
    *,
    entered: bool,
    operation_error: BaseException | None,
) -> BaseException:
    def exact_lifecycle_category(error: BaseException) -> str | None:
        if type(error) is not ProductDatabaseLifecycleError:
            return None
        arguments = BaseException.args.__get__(error, BaseException)
        if (
            type(arguments) is tuple
            and len(arguments) == 1
            and type(arguments[0]) is str
            and arguments[0] in (_LIFECYCLE_ERROR, _LIFECYCLE_CLEANUP_ERROR)
        ):
            return arguments[0]
        return None

    def subtree_matches(error: BaseException, expected: str) -> bool:
        if _is_exception_kind(error, (BaseExceptionGroup,)):
            children = _exception_group_children(error)
            if children is None:
                return False
            return all(
                subtree_matches(child, expected)
                for child in children
            )
        if _is_exception_kind(
            error,
            (asyncio.CancelledError, KeyboardInterrupt, SystemExit),
        ):
            return True
        return exact_lifecycle_category(error) == expected

    def rebuild_subtree(
        error: BaseException,
        expected: str,
        *,
        trusted: bool,
    ) -> BaseException:
        if _is_exception_kind(error, (BaseExceptionGroup,)):
            children = _exception_group_children(error)
            if children is None:
                return ProductDatabaseCutoverError(expected)
            return BaseExceptionGroup(
                expected,
                [
                    rebuild_subtree(child, expected, trusted=trusted)
                    for child in children
                ],
            )
        if _is_exception_kind(
            error,
            (asyncio.CancelledError, KeyboardInterrupt, SystemExit),
        ):
            return _sanitized(error, expected)
        if trusted and exact_lifecycle_category(error) == expected:
            return ProductDatabaseLifecycleError(expected)
        return ProductDatabaseCutoverError(expected)

    if entered:
        consistent = subtree_matches(lock_error, _LIFECYCLE_CLEANUP_ERROR)
        cleanup_error = rebuild_subtree(
            lock_error,
            _LIFECYCLE_CLEANUP_ERROR,
            trusted=consistent,
        )
    elif _is_exception_kind(lock_error, (BaseExceptionGroup,)):
        children = _exception_group_children(lock_error)
        if children is None:
            cleanup_error = ProductDatabaseCutoverError(_LIFECYCLE_ERROR)
        else:
            primary_only = subtree_matches(lock_error, _LIFECYCLE_ERROR)
            primary_with_cleanup = (
                subtree_matches(children[0], _LIFECYCLE_ERROR)
                and all(
                    subtree_matches(child, _LIFECYCLE_CLEANUP_ERROR)
                    for child in children[1:]
                )
            )
            if primary_only:
                cleanup_error = rebuild_subtree(
                    lock_error,
                    _LIFECYCLE_ERROR,
                    trusted=True,
                )
            elif primary_with_cleanup:
                cleanup_error = BaseExceptionGroup(
                    _LIFECYCLE_ERROR,
                    [
                        rebuild_subtree(
                            children[0],
                            _LIFECYCLE_ERROR,
                            trusted=True,
                        ),
                        *[
                            rebuild_subtree(
                                child,
                                _LIFECYCLE_CLEANUP_ERROR,
                                trusted=True,
                            )
                            for child in children[1:]
                        ],
                    ],
                )
            else:
                cleanup_error = rebuild_subtree(
                    lock_error,
                    _LIFECYCLE_ERROR,
                    trusted=False,
                )
    else:
        consistent = subtree_matches(lock_error, _LIFECYCLE_ERROR)
        cleanup_error = rebuild_subtree(
            lock_error,
            _LIFECYCLE_ERROR,
            trusted=consistent,
        )
    if operation_error is None:
        return cleanup_error
    return BaseExceptionGroup(
        _LIFECYCLE_CLEANUP_ERROR,
        [operation_error, cleanup_error],
    )


async def cutover(
    *,
    receipt: PreparationReceipt,
    config_path: Path,
    confirm_database: str,
    confirm_cutover: str,
    smoke: Callable[..., object],
    writer: Callable[..., object] = atomic_compare_and_swap_local_document,
    inventory_reader: Callable[..., object],
    acl_runner: object = restrict_windows_acl,
    lifecycle_lock: Callable[[Path], ContextManager[object]] = (
        product_database_lifecycle_lock
    ),
) -> CutoverResult:
    """Verify Stage A evidence, switch one field, smoke, and retain legacy."""
    if confirm_database != NEW_DATABASE or confirm_cutover != _CUTOVER_CONFIRMATION:
        _raise(ProductDatabaseCutoverError(_APPROVAL_ERROR))
    try:
        if (
            type(receipt) is not PreparationReceipt
            or receipt.state != ReadinessState.AWAITING_CUTOVER_APPROVAL.value
        ):
            raise ValueError
        PreparationReceipt.__post_init__(receipt)
    except BaseException as error:
        _raise(_sanitized(error, _EVIDENCE_ERROR))

    path = Path(config_path)
    original_snapshot: LocalDocumentSnapshot | None = None
    original: dict[str, object] | None = None
    switched_snapshot: LocalDocumentSnapshot | None = None
    operation_error: BaseException | None = None
    entered = False
    try:
        with lifecycle_lock(path):
            entered = True
            try:
                original_snapshot = capture_local_document_snapshot(path)
                original = _parse_local_document(original_snapshot.content)
                if original["MYSQL_DB"] != LEGACY_DATABASE:
                    raise ValueError
            except BaseException as error:
                operation_error = _sanitized(error, _CONFIG_ERROR)
            if operation_error is None:
                try:
                    observed = await _invoke(
                        inventory_reader,
                        cast(dict[str, object], original),
                    )
                    _validate_observed_inventories(observed, receipt)
                except BaseException as error:
                    operation_error = _sanitized(error, _EVIDENCE_ERROR)
            if operation_error is None:
                try:
                    switched = {
                        **cast(dict[str, object], original),
                        "MYSQL_DB": NEW_DATABASE,
                    }
                    candidate_snapshot = await _invoke(
                        writer,
                        path,
                        switched,
                        acl_runner,
                        original_snapshot,
                    )
                    if type(candidate_snapshot) is not LocalDocumentSnapshot:
                        raise TypeError
                    switched_snapshot = candidate_snapshot
                except BaseException as error:
                    operation_error = _sanitized(error, _CONFIG_ERROR)
    except BaseException as error:
        _raise(
            _lock_boundary_error(
                error,
                entered=entered,
                operation_error=operation_error,
            )
        )
    if operation_error is not None:
        _raise(operation_error)
    original = cast(dict[str, object], original)
    original_snapshot = cast(LocalDocumentSnapshot, original_snapshot)
    switched_snapshot = cast(LocalDocumentSnapshot, switched_snapshot)
    switched = {**original, "MYSQL_DB": NEW_DATABASE}

    try:
        await _invoke(smoke, switched)
    except BaseException as smoke_error:
        rollback_error: BaseException | None = None
        rollback_entered = False
        try:
            with lifecycle_lock(path):
                rollback_entered = True
                try:
                    # One atomic attempt is deliberately bounded: never retry a secret write.
                    rollback_snapshot = await _invoke(
                        writer,
                        path,
                        original,
                        acl_runner,
                        switched_snapshot,
                    )
                    if type(rollback_snapshot) is not LocalDocumentSnapshot:
                        raise TypeError
                except BaseException as error:
                    rollback_error = _sanitized(error, _ROLLBACK_ERROR)
        except BaseException as error:
            rollback_error = _lock_boundary_error(
                error,
                entered=rollback_entered,
                operation_error=rollback_error,
            )
        if rollback_error is not None:
            _raise(
                BaseExceptionGroup(
                    _ROLLBACK_ERROR,
                    [
                        _sanitized(smoke_error, _SMOKE_ERROR),
                        rollback_error,
                    ],
                )
            )
        _raise(_sanitized(smoke_error, _SMOKE_ERROR))

    verify_error: BaseException | None = None
    verify_entered = False
    try:
        with lifecycle_lock(path):
            verify_entered = True
            try:
                if capture_local_document_snapshot(path) != switched_snapshot:
                    raise ValueError
            except BaseException as error:
                verify_error = _sanitized(error, _CONFIG_ERROR)
    except BaseException as error:
        _raise(
            _lock_boundary_error(
                error,
                entered=verify_entered,
                operation_error=verify_error,
            )
        )
    if verify_error is not None:
        _raise(verify_error)

    receipts = _cutover_receipts(receipt)
    return CutoverResult(ReadinessState.LEGACY_RETAINED.value, receipts)


async def recover_legacy(
    *,
    config_path: Path,
    database: str,
    confirm_cutover: str,
    writer: Callable[..., object] = atomic_compare_and_swap_local_document,
    inventory_reader: Callable[..., object],
    acl_runner: object = restrict_windows_acl,
    lifecycle_lock: Callable[[Path], ContextManager[object]] = (
        product_database_lifecycle_lock
    ),
) -> CutoverResult:
    """Switch only MYSQL_DB back to legacy after proving both databases exist."""
    if database != LEGACY_DATABASE or confirm_cutover != _RECOVERY_CONFIRMATION:
        _raise(ProductDatabaseCutoverError(_APPROVAL_ERROR))
    path = Path(config_path)
    operation_error: BaseException | None = None
    entered = False
    try:
        with lifecycle_lock(path):
            entered = True
            try:
                original_snapshot = capture_local_document_snapshot(path)
                original = _parse_local_document(original_snapshot.content)
                if original["MYSQL_DB"] != NEW_DATABASE:
                    raise ValueError
                _validate_observed_inventories(
                    await _invoke(inventory_reader, original)
                )
                recovered_snapshot = await _invoke(
                    writer,
                    path,
                    {**original, "MYSQL_DB": LEGACY_DATABASE},
                    acl_runner,
                    original_snapshot,
                )
                if type(recovered_snapshot) is not LocalDocumentSnapshot:
                    raise TypeError
            except BaseException as error:
                operation_error = _sanitized(error, _RECOVERY_ERROR)
    except BaseException as error:
        _raise(
            _lock_boundary_error(
                error,
                entered=entered,
                operation_error=operation_error,
            )
        )
    if operation_error is not None:
        _raise(operation_error)
    return CutoverResult(ReadinessState.LEGACY_RETAINED.value)


async def _default_inventory_reader(document: Mapping[str, object]) -> object:
    from backend.scripts.prepare_product_database import _default_inventory

    config = _connection_config(document)
    return (
        await _default_inventory(config, LEGACY_DATABASE),
        await _default_inventory(config, NEW_DATABASE),
    )


async def _default_post_cutover_smoke(
    document: Mapping[str, object],
    *,
    runner: Callable[..., object] | None = None,
) -> object:
    """Exercise normal config startup without a process-local database override."""
    from backend.scripts.prepare_product_database import (
        _BROWSER_NODE_COMMAND,
        _default_browser_smoke_runner,
        _open_browser_root_lease,
        run_owned_phase7b_browser,
    )
    from backend.services.product_database_readiness import SmokeResult

    try:
        if document.get("MYSQL_DB") != NEW_DATABASE:
            raise ValueError
        environment = dict(os.environ)
        for key in _MYSQL_ENVIRONMENT_KEYS:
            environment.pop(key, None)
        environment["MARKET_SCHEDULER_ENABLED"] = "false"
        summary = await _invoke(
            run_owned_phase7b_browser,
            node_command=_BROWSER_NODE_COMMAND,
            cwd=Path(__file__).resolve().parents[2],
            environment=environment,
            timeout_seconds=_BROWSER_SMOKE_TIMEOUT_SECONDS,
            runner=runner or _default_browser_smoke_runner,
            root_factory=_open_browser_root_lease,
        )
        if (
            type(summary) is not dict
            or summary != _BROWSER_SMOKE_EXPECTED
            or set(summary) != set(_BROWSER_SMOKE_EXPECTED)
        ):
            raise ValueError
        return SmokeResult(provider_calls=0, outbound_requests=0)
    except BaseException as error:
        _raise(_sanitized(error, _SMOKE_ERROR))


async def run_cli(
    argv: Sequence[str] | None = None,
    *,
    config_path: Path = LOCAL_CONFIG_PATH,
    receipt_loader: Callable[[Path], object] = load_preparation_receipt,
    backup_verifier: Callable[[Path, str, int], object] = verify_backup_file,
    inventory_reader: Callable[..., object] = _default_inventory_reader,
    smoke: Callable[..., object] = _default_post_cutover_smoke,
    writer: Callable[..., object] = atomic_compare_and_swap_local_document,
    acl_runner: object = restrict_windows_acl,
    lifecycle_lock: Callable[[Path], ContextManager[object]] = (
        product_database_lifecycle_lock
    ),
    output: Callable[[str], None] = print,
) -> int:
    args = _argument_parser().parse_args(argv)
    if type(args.execute) is not bool or not args.execute:
        _raise(ProductDatabaseCutoverError(_APPROVAL_ERROR))
    if args.recover_legacy:
        if (
            args.receipt is not None
            or type(args.database) is not str
            or args.database != LEGACY_DATABASE
            or type(args.confirm_cutover) is not str
            or args.confirm_cutover != _RECOVERY_CONFIRMATION
        ):
            _raise(ProductDatabaseCutoverError(_APPROVAL_ERROR))
        result = await recover_legacy(
            config_path=config_path,
            database=args.database,
            confirm_cutover=args.confirm_cutover,
            writer=writer,
            inventory_reader=inventory_reader,
            acl_runner=acl_runner,
            lifecycle_lock=lifecycle_lock,
        )
    else:
        if (
            type(args.receipt) is not str
            or not args.receipt
            or type(args.database) is not str
            or args.database != NEW_DATABASE
            or type(args.confirm_cutover) is not str
            or args.confirm_cutover != _CUTOVER_CONFIRMATION
        ):
            _raise(ProductDatabaseCutoverError(_APPROVAL_ERROR))
        receipt_path = Path(args.receipt)
        try:
            receipt = await _invoke(receipt_loader, receipt_path)
            if (
                type(receipt) is not PreparationReceipt
                or receipt.state != ReadinessState.AWAITING_CUTOVER_APPROVAL.value
            ):
                raise ValueError
            PreparationReceipt.__post_init__(receipt)
            backup_path = receipt_path.parent / receipt.backup_filename
            await _invoke(
                backup_verifier,
                backup_path,
                receipt.backup_sha256,
                receipt.backup_byte_length,
            )
        except BaseException as error:
            _raise(_sanitized(error, _EVIDENCE_ERROR))
        result = await cutover(
            receipt=receipt,  # type: ignore[arg-type]
            config_path=config_path,
            confirm_database=args.database,
            confirm_cutover=args.confirm_cutover,
            smoke=smoke,
            writer=writer,
            inventory_reader=inventory_reader,
            acl_runner=acl_runner,
            lifecycle_lock=lifecycle_lock,
        )
    output(f"state={result.state}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(run_cli(argv))
    except _HelpRequested:
        return 0
    except BaseException:
        print("Product database cutover failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
