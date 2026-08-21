"""Fail-closed, zero-wait serialization for product-database lifecycle work."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import tempfile


_LOCK_ERROR = "product database lifecycle lock failed"
_CLEANUP_ERROR = "product database lifecycle lock cleanup failed"
_WINDOWS_PREFIX = "Local\\NovelCreator.ProductDatabaseLifecycle."
_POSIX_PREFIX = "novel-creator-product-database-lifecycle-"
_WAIT_OBJECT_0 = 0x00000000
_WAIT_ABANDONED = 0x00000080
_MAX_PUBLIC_EXCEPTION_GROUP_DEPTH = 64
_MAX_PUBLIC_EXCEPTION_OCCURRENCES = 256


class ProductDatabaseLifecycleError(RuntimeError):
    """A fixed, public-safe lifecycle-lock failure."""


class _CleanupFailures(BaseException):
    """A trusted, internal transport for cleanup failures."""

    def __init__(self, failures: tuple[BaseException, ...]) -> None:
        super().__init__()
        self.failures = failures


def _trusted_cleanup_failures(
    error: BaseException,
) -> tuple[BaseException, ...] | None:
    if type(error) is not _CleanupFailures:
        return None
    failures = object.__getattribute__(error, "failures")
    if (
        type(failures) is not tuple
        or not failures
        or not all(issubclass(type(failure), BaseException) for failure in failures)
    ):
        return None
    return failures


def _consume_deferred_result(future: asyncio.Future[object]) -> None:
    if future.cancelled():
        return
    try:
        future.exception()
    except BaseException:
        return


class ProductDatabaseLifecycleLease:
    """Own deferred physical cleanup for one acquired lifecycle lock."""

    def __init__(self) -> None:
        self._transfer: asyncio.Future[object] | None = None
        self._completion: asyncio.Future[object] | None = None
        self._cleanup: Callable[[], list[BaseException]] | None = None

    def defer_until(
        self,
        transfer: asyncio.Future[object],
    ) -> asyncio.Future[object]:
        """Publish completion after transfer settlement and lock cleanup."""

        if type(transfer) not in (asyncio.Future, asyncio.Task):
            raise TypeError
        if self._transfer is not None:
            if transfer is self._transfer and self._completion is not None:
                return self._completion
            raise RuntimeError
        loop = asyncio.get_running_loop()
        if transfer.get_loop() is not loop:
            raise ValueError
        completion = loop.create_future()
        completion.add_done_callback(_consume_deferred_result)
        self._transfer = transfer
        self._completion = completion
        return completion

    def _arm(self, cleanup: Callable[[], list[BaseException]]) -> bool:
        if self._transfer is None:
            return False
        if self._completion is None:
            self._transfer = None
            self._completion = None
            return False
        self._cleanup = cleanup
        try:
            self._transfer.add_done_callback(self._finish)
        except BaseException:
            completion = self._completion
            self._transfer = None
            self._completion = None
            self._cleanup = None
            if completion is not None:
                completion.cancel()
            raise
        return True

    def _finish(self, transfer: asyncio.Future[object]) -> None:
        if transfer is not self._transfer or self._cleanup is None:
            return
        result = None
        primary = None
        try:
            result = transfer.result()
        except BaseException as error:
            primary = error
        cleanup = self._cleanup()
        outgoing = None
        try:
            _raise_failures(primary, cleanup)
        except BaseException as error:
            outgoing = error

        completion = self._completion
        self._transfer = None
        self._completion = None
        self._cleanup = None
        primary = None
        cleanup = []
        if completion is None or completion.done():
            return
        if outgoing is not None:
            completion.set_exception(outgoing)
        else:
            completion.set_result(result)


@dataclass(frozen=True)
class _WindowsAPI:
    create: Callable[[str], object]
    wait: Callable[[object], object]
    release: Callable[[object], object]
    close: Callable[[object], object]


@dataclass(frozen=True)
class _PosixAPI:
    open: Callable[[Path, int, int], object]
    flock: Callable[[int, int], object]
    unlock: Callable[[int], object]
    close: Callable[[int], object]
    o_cloexec: int
    o_nofollow: int
    lock_ex: int
    lock_nb: int


def _fixed(message: str) -> ProductDatabaseLifecycleError:
    return ProductDatabaseLifecycleError(message)


def _is_exception_kind(
    error: BaseException,
    kinds: tuple[type[BaseException], ...],
) -> bool:
    actual_type = type(error)
    return any(issubclass(actual_type, kind) for kind in kinds)


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


def _clean_flow_control(error: BaseException) -> BaseException:
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
    raise TypeError


def _exception_group_within_budget(error: BaseExceptionGroup) -> bool:
    pending: list[tuple[BaseException, int]] = [(error, 0)]
    scheduled = 1
    while pending:
        current, depth = pending.pop()
        if depth > _MAX_PUBLIC_EXCEPTION_GROUP_DEPTH:
            return False
        if not _is_exception_kind(current, (BaseExceptionGroup,)):
            continue
        children = _exception_group_children(current)
        if children is None:
            return False
        if len(children) > _MAX_PUBLIC_EXCEPTION_OCCURRENCES - scheduled:
            return False
        scheduled += len(children)
        pending.extend((child, depth + 1) for child in reversed(children))
    return True


def _sanitize_validated(error: BaseException, message: str) -> BaseException:
    pending: list[
        tuple[BaseException, tuple[BaseException, ...] | None]
    ] = [(error, None)]
    rebuilt: list[BaseException] = []
    while pending:
        current, expanded_children = pending.pop()
        if expanded_children is not None:
            child_count = len(expanded_children)
            clean_children = rebuilt[-child_count:]
            del rebuilt[-child_count:]
            rebuilt.append(BaseExceptionGroup(message, clean_children))
            continue
        if _is_exception_kind(current, (BaseExceptionGroup,)):
            children = _exception_group_children(current)
            if children is None:
                rebuilt.append(_fixed(message))
                continue
            pending.append((current, children))
            pending.extend((child, None) for child in reversed(children))
            continue
        if _is_exception_kind(
            current,
            (asyncio.CancelledError, KeyboardInterrupt, SystemExit),
        ):
            rebuilt.append(_clean_flow_control(current))
        else:
            rebuilt.append(_fixed(message))
    return rebuilt[0]


def _sanitize(error: BaseException, message: str) -> BaseException:
    if _is_exception_kind(error, (BaseExceptionGroup,)):
        if not _exception_group_within_budget(error):
            return _fixed(message)
    return _sanitize_validated(error, message)


def _strip_metadata(error: BaseException) -> None:
    pending = [error]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        identity = id(current)
        if identity in visited:
            continue
        visited.add(identity)
        current.__cause__ = None
        current.__context__ = None
        current.__suppress_context__ = True
        if hasattr(current, "__notes__"):
            del current.__notes__
        if _is_exception_kind(current, (BaseExceptionGroup,)):
            children = _exception_group_children(current)
            if children is not None:
                pending.extend(reversed(children))


def _raise_public(error: BaseException) -> None:
    _strip_metadata(error)
    try:
        raise error from None
    except BaseException as outgoing:
        _strip_metadata(outgoing)
        raise


def _raise_failures(
    primary: BaseException | None,
    cleanup: list[BaseException],
) -> None:
    clean_primary = None if primary is None else _sanitize(primary, _LOCK_ERROR)
    clean_cleanup = [_sanitize(error, _CLEANUP_ERROR) for error in cleanup]
    if clean_primary is not None and clean_cleanup:
        _raise_public(
            BaseExceptionGroup(_LOCK_ERROR, [clean_primary, *clean_cleanup])
        )
    if clean_primary is not None:
        _raise_public(clean_primary)
    if len(clean_cleanup) == 1:
        _raise_public(clean_cleanup[0])
    if clean_cleanup:
        _raise_public(BaseExceptionGroup(_CLEANUP_ERROR, clean_cleanup))


def _normalized_config_path(config_path: Path, platform_name: str) -> str:
    path = Path(config_path)
    normalized = os.path.normpath(os.path.abspath(os.fspath(path)))
    if platform_name == "nt":
        normalized = normalized.replace("/", "\\").casefold()
    return normalized


def _path_digest(config_path: Path, platform_name: str) -> str:
    normalized = _normalized_config_path(config_path, platform_name)
    return hashlib.sha256(os.fsencode(normalized)).hexdigest()


def _windows_lock_name(config_path: Path) -> str:
    return _WINDOWS_PREFIX + _path_digest(config_path, "nt")


def _posix_lock_path(config_path: Path) -> Path:
    filename = _POSIX_PREFIX + _path_digest(config_path, "posix") + ".lock"
    return Path(tempfile.gettempdir()).absolute() / filename


def _default_windows_api() -> _WindowsAPI:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel32.CreateMutexW
    create.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    create.restype = wintypes.HANDLE
    wait = kernel32.WaitForSingleObject
    wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait.restype = wintypes.DWORD
    release = kernel32.ReleaseMutex
    release.argtypes = [wintypes.HANDLE]
    release.restype = wintypes.BOOL
    close = kernel32.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    return _WindowsAPI(
        create=lambda name: create(None, False, name),
        wait=lambda handle: int(wait(handle, 0)),
        release=lambda handle: bool(release(handle)),
        close=lambda handle: bool(close(handle)),
    )


def _default_posix_api() -> _PosixAPI:
    import fcntl

    return _PosixAPI(
        open=lambda path, flags, mode: os.open(path, flags, mode),
        flock=lambda descriptor, operation: fcntl.flock(descriptor, operation),
        unlock=lambda descriptor: fcntl.flock(descriptor, fcntl.LOCK_UN),
        close=os.close,
        o_cloexec=os.O_CLOEXEC,
        o_nofollow=os.O_NOFOLLOW,
        lock_ex=fcntl.LOCK_EX,
        lock_nb=fcntl.LOCK_NB,
    )


def _api_methods(api: object, names: tuple[str, ...]) -> tuple[Callable[..., object], ...]:
    methods = tuple(getattr(api, name) for name in names)
    if not all(callable(method) for method in methods):
        raise TypeError
    return methods  # type: ignore[return-value]


def _posix_capabilities(api: object) -> tuple[int, int, int, int]:
    values = tuple(
        getattr(api, name)
        for name in ("o_cloexec", "o_nofollow", "lock_ex", "lock_nb")
    )
    if not all(type(value) is int and value > 0 for value in values):
        raise TypeError
    o_cloexec, o_nofollow, lock_ex, lock_nb = values
    if (
        o_cloexec & o_nofollow
        or (o_cloexec | o_nofollow) & (os.O_CREAT | os.O_RDWR)
        or lock_ex & lock_nb
    ):
        raise ValueError
    return o_cloexec, o_nofollow, lock_ex, lock_nb  # type: ignore[return-value]


def _windows_null_handle(handle: object) -> bool:
    return handle is None or handle is False or (type(handle) is int and handle == 0)


def _validate_open_file(descriptor: int) -> os.stat_result:
    identity = os.fstat(descriptor)
    if (
        not stat.S_ISREG(identity.st_mode)
        or identity.st_size != 0
        or identity.st_nlink != 1
    ):
        raise ValueError
    return identity


def _validate_stable_path(
    descriptor: int,
    lock_path: Path,
    opened_identity: os.stat_result,
) -> None:
    held_identity = _validate_open_file(descriptor)
    path_identity = os.lstat(lock_path)
    if (
        not stat.S_ISREG(path_identity.st_mode)
        or path_identity.st_size != 0
        or path_identity.st_nlink != 1
        or not os.path.samestat(opened_identity, held_identity)
        or not os.path.samestat(held_identity, path_identity)
    ):
        raise ValueError


@contextmanager
def _product_database_lifecycle_lock_scope(
    config_path: Path,
    *,
    platform_name: str = os.name,
    windows_api: object | None = None,
    posix_api: object | None = None,
) -> Iterator[ProductDatabaseLifecycleLease]:
    """Acquire the stable lifecycle lock without waiting and release it on exit.

    Only cooperating repository participants are serialized.  All failures are
    rebuilt at this boundary so paths, operating-system details, and body
    exception text cannot escape through public exceptions.
    """

    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    resource: object | None = None
    acquired = False
    release: Callable[[object], object] | None = None
    close: Callable[[object], object] | None = None
    release_success: object = None
    close_success: object = None
    lease = ProductDatabaseLifecycleLease()

    def cleanup_resource() -> list[BaseException]:
        nonlocal resource, release, close
        errors: list[BaseException] = []
        if acquired and resource is not None and release is not None:
            try:
                released = release(resource)
                if released is not release_success:
                    raise ValueError
            except BaseException as error:
                errors.append(error)
        if resource is not None and close is not None:
            try:
                closed = close(resource)
                if closed is not close_success:
                    raise ValueError
            except BaseException as error:
                errors.append(error)
        resource = None
        release = None
        close = None
        return errors

    try:
        if platform_name == "nt":
            selected = _default_windows_api() if windows_api is None else windows_api
            create, wait, release, close = _api_methods(
                selected, ("create", "wait", "release", "close")
            )
            release_success = True
            close_success = True
            handle = create(_windows_lock_name(config_path))
            if _windows_null_handle(handle):
                raise ValueError
            resource = handle
            result = wait(handle)
            if type(result) is not int:
                raise ValueError
            if result == _WAIT_ABANDONED:
                acquired = True
                raise ValueError
            if result != _WAIT_OBJECT_0:
                raise ValueError
            acquired = True
        elif platform_name == "posix":
            selected = _default_posix_api() if posix_api is None else posix_api
            open_file, flock, release, close = _api_methods(
                selected, ("open", "flock", "unlock", "close")
            )
            o_cloexec, o_nofollow, lock_ex, lock_nb = _posix_capabilities(
                selected
            )
            lock_path = _posix_lock_path(config_path)
            flags = os.O_CREAT | os.O_RDWR | o_cloexec | o_nofollow
            descriptor = open_file(lock_path, flags, 0o600)
            if type(descriptor) is not int or descriptor < 0:
                raise ValueError
            resource = descriptor
            opened_identity = _validate_open_file(descriptor)
            if flock(descriptor, lock_ex | lock_nb) is not None:
                raise ValueError
            acquired = True
            _validate_stable_path(descriptor, lock_path, opened_identity)
        else:
            raise ValueError
        yield lease
    except BaseException as error:
        primary = error
    finally:
        deferred = False
        try:
            deferred = lease._arm(cleanup_resource)
        except BaseException as error:
            cleanup.append(error)
        if not deferred:
            cleanup.extend(cleanup_resource())
        if primary is None and cleanup:
            raise _CleanupFailures(tuple(cleanup)) from None
        _raise_failures(primary, cleanup)


class _ProductDatabaseLifecycleLockBoundary:
    """Keep untrusted body exceptions out of contextlib's dynamic type checks."""

    def __init__(self, scope: object) -> None:
        self._enter = getattr(scope, "__enter__")
        self._exit = getattr(scope, "__exit__")

    def __enter__(self) -> ProductDatabaseLifecycleLease:
        return self._enter()

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: object,
    ) -> bool:
        del exception_type, traceback
        cleanup: list[BaseException] = []
        try:
            self._exit(None, None, None)
        except BaseException as cleanup_error:
            transported = _trusted_cleanup_failures(cleanup_error)
            if transported is not None:
                cleanup.extend(transported)
            else:
                cleanup.append(cleanup_error)
        _raise_failures(error, cleanup)
        return False


def product_database_lifecycle_lock(
    config_path: Path,
    *,
    platform_name: str = os.name,
    windows_api: object | None = None,
    posix_api: object | None = None,
) -> _ProductDatabaseLifecycleLockBoundary:
    """Build a lifecycle-lock boundary that never inspects body attributes."""

    scope = _product_database_lifecycle_lock_scope(
        config_path,
        platform_name=platform_name,
        windows_api=windows_api,
        posix_api=posix_api,
    )
    return _ProductDatabaseLifecycleLockBoundary(scope)


__all__ = [
    "ProductDatabaseLifecycleError",
    "ProductDatabaseLifecycleLease",
    "product_database_lifecycle_lock",
]
