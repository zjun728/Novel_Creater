from __future__ import annotations

import asyncio
import errno
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import traceback
from types import SimpleNamespace
from typing import Callable

import pytest

from backend.services import product_database_lifecycle_lock as lifecycle


SECRET = "password=lifecycle-lock-secret"
LOCK_ERROR = "product database lifecycle lock failed"
CLEANUP_ERROR = "product database lifecycle lock cleanup failed"
_DEFAULT = object()
_FAKE_POSIX_LOCK_PATHS: set[Path] = set()


@pytest.fixture(autouse=True)
def cleanup_fake_posix_lock_paths():
    yield
    for lock_path in _FAKE_POSIX_LOCK_PATHS:
        lock_path.unlink(missing_ok=True)
    _FAKE_POSIX_LOCK_PATHS.clear()


class FakeWindowsAPI:
    def __init__(
        self,
        *,
        handle: object = _DEFAULT,
        wait_result: object = 0x00000000,
        release_result: object = True,
        close_result: object = True,
        fail_at: str | None = None,
        release_error: BaseException | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self.handle = object() if handle is _DEFAULT else handle
        self.wait_result = wait_result
        self.release_result = release_result
        self.close_result = close_result
        self.fail_at = fail_at
        self.release_error = release_error
        self.close_error = close_error
        self.events: list[object] = []

    def create(self, name: str) -> object:
        self.events.append(("create", name))
        if self.fail_at == "create":
            raise OSError(SECRET)
        return self.handle

    def wait(self, handle: object) -> object:
        self.events.append(("wait", handle))
        if self.fail_at == "wait":
            raise OSError(SECRET)
        return self.wait_result

    def release(self, handle: object) -> object:
        self.events.append(("release", handle))
        if self.release_error is not None:
            raise self.release_error
        if self.fail_at == "release":
            raise OSError(SECRET)
        return self.release_result

    def close(self, handle: object) -> object:
        self.events.append(("close", handle))
        if self.close_error is not None:
            raise self.close_error
        if self.fail_at == "close":
            raise OSError(SECRET)
        return self.close_result


class FakePosixAPI:
    def __init__(
        self,
        *,
        open_result: object = _DEFAULT,
        opener: Callable[[Path, int, int], object] | None = None,
        flock_result: object = None,
        unlock_result: object = None,
        close_result: object = None,
        fail_at: str | None = None,
        unlock_error: BaseException | None = None,
        close_error: BaseException | None = None,
        o_cloexec: object = 0x00100000,
        o_nofollow: object = 0x00200000,
        lock_ex: object = 0x00001000,
        lock_nb: object = 0x00002000,
    ) -> None:
        self.open_result = open_result
        self.opener = opener
        self.flock_result = flock_result
        self.unlock_result = unlock_result
        self.close_result = close_result
        self.fail_at = fail_at
        self.unlock_error = unlock_error
        self.close_error = close_error
        self.o_cloexec = o_cloexec
        self.o_nofollow = o_nofollow
        self.lock_ex = lock_ex
        self.lock_nb = lock_nb
        self.events: list[object] = []
        self.real_descriptors: set[int] = set()

    def open(self, path: Path, flags: int, mode: int) -> object:
        self.events.append(("open", path, flags, mode))
        _FAKE_POSIX_LOCK_PATHS.add(Path(path))
        if self.fail_at == "open":
            raise OSError(SECRET)
        if self.opener is not None:
            result = self.opener(path, flags, mode)
        elif self.open_result is _DEFAULT:
            result = os.open(path, flags, mode)
        else:
            result = self.open_result
        if type(result) is int and result >= 0:
            self.real_descriptors.add(result)
        return result

    def flock(self, descriptor: int, operation: int) -> object:
        self.events.append(("flock", descriptor, operation))
        if self.fail_at == "flock":
            raise BlockingIOError(errno.EWOULDBLOCK, SECRET)
        return self.flock_result

    def unlock(self, descriptor: int) -> object:
        self.events.append(("unlock", descriptor))
        if self.unlock_error is not None:
            raise self.unlock_error
        if self.fail_at == "unlock":
            raise OSError(SECRET)
        return self.unlock_result

    def close(self, descriptor: int) -> object:
        self.events.append(("close", descriptor))
        if descriptor in self.real_descriptors:
            self.real_descriptors.remove(descriptor)
            os.close(descriptor)
        if self.close_error is not None:
            raise self.close_error
        if self.fail_at == "close":
            raise OSError(SECRET)
        return self.close_result


def _event_names(events: list[object]) -> list[str]:
    return [event[0] if isinstance(event, tuple) else event for event in events]


def _leaves(error: BaseException) -> list[BaseException]:
    if isinstance(error, BaseExceptionGroup):
        return [leaf for child in error.exceptions for leaf in _leaves(child)]
    return [error]


def _assert_clean_tree(error: BaseException) -> None:
    assert error.__cause__ is None
    assert error.__context__ is None
    assert not hasattr(error, "__notes__")
    assert SECRET not in repr(error)
    if isinstance(error, BaseExceptionGroup):
        assert error.message in (LOCK_ERROR, CLEANUP_ERROR)
        for child in error.exceptions:
            _assert_clean_tree(child)
        return
    if isinstance(error, lifecycle.ProductDatabaseLifecycleError):
        assert error.args in ((LOCK_ERROR,), (CLEANUP_ERROR,))
        return
    assert type(error) in (asyncio.CancelledError, KeyboardInterrupt, SystemExit)
    if type(error) in (asyncio.CancelledError, KeyboardInterrupt):
        assert error.args == ()
    if type(error) is SystemExit:
        assert error.code is None or type(error.code) is int


def _raise_dirty(error: BaseException) -> None:
    error.__cause__ = RuntimeError(SECRET)
    error.__context__ = RuntimeError(SECRET)
    error.add_note(SECRET)
    raise error


def test_windows_success_is_zero_wait_and_releases_then_closes(tmp_path: Path):
    api = FakeWindowsAPI()

    with lifecycle.product_database_lifecycle_lock(
        tmp_path / "config.json", platform_name="nt", windows_api=api
    ):
        api.events.append("body")

    assert _event_names(api.events) == ["create", "wait", "body", "release", "close"]
    assert api.events[1][1] is api.handle  # type: ignore[index]
    assert api.events[3][1] is api.handle  # type: ignore[index]
    assert api.events[4][1] is api.handle  # type: ignore[index]


@pytest.mark.parametrize("handle", (None, 0, False))
def test_windows_null_create_fails_without_wait_release_or_close(
    tmp_path: Path, handle: object
):
    api = FakeWindowsAPI(handle=handle)

    with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name="nt", windows_api=api
        ):
            pytest.fail("null handle entered body")

    assert raised.value.args == (LOCK_ERROR,)
    assert _event_names(api.events) == ["create"]
    _assert_clean_tree(raised.value)


@pytest.mark.parametrize("result", (None, True, False, "0", 0.0))
def test_windows_malformed_wait_result_fails_closed_and_closes(
    tmp_path: Path, result: object
):
    api = FakeWindowsAPI(wait_result=result)

    with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name="nt", windows_api=api
        ):
            pytest.fail("malformed wait entered body")

    assert raised.value.args == (LOCK_ERROR,)
    assert _event_names(api.events) == ["create", "wait", "close"]


@pytest.mark.parametrize("result", (0x00000102, 0xFFFFFFFF, 1, -1))
def test_windows_timeout_wait_failure_and_unknown_results_fail_immediately(
    tmp_path: Path, result: int
):
    api = FakeWindowsAPI(wait_result=result)
    entered = False
    started = time.perf_counter()

    with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name="nt", windows_api=api
        ):
            entered = True

    assert time.perf_counter() - started < 1
    assert not entered
    assert raised.value.args == (LOCK_ERROR,)
    assert _event_names(api.events) == ["create", "wait", "close"]


def test_windows_abandoned_mutex_fails_closed_but_releases_and_closes(tmp_path: Path):
    api = FakeWindowsAPI(wait_result=0x00000080)

    with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name="nt", windows_api=api
        ):
            pytest.fail("abandoned mutex entered body")

    assert raised.value.args == (LOCK_ERROR,)
    assert _event_names(api.events) == ["create", "wait", "release", "close"]


@pytest.mark.parametrize("missing", ("create", "wait", "release", "close"))
def test_windows_malformed_api_fails_before_creating_a_handle(
    tmp_path: Path, missing: str
):
    methods = {
        name: getattr(FakeWindowsAPI(), name)
        for name in ("create", "wait", "release", "close")
        if name != missing
    }

    with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json",
            platform_name="nt",
            windows_api=SimpleNamespace(**methods),
        ):
            pytest.fail("malformed API entered body")

    assert raised.value.args == (LOCK_ERROR,)
    _assert_clean_tree(raised.value)


@pytest.mark.parametrize("fail_at", ("create", "wait", "release", "close"))
def test_windows_api_exceptions_are_fixed_safe_and_close_when_possible(
    tmp_path: Path, fail_at: str
):
    api = FakeWindowsAPI(fail_at=fail_at)

    with pytest.raises(BaseException) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name="nt", windows_api=api
        ):
            pass

    assert _event_names(api.events) == {
        "create": ["create"],
        "wait": ["create", "wait", "close"],
        "release": ["create", "wait", "release", "close"],
        "close": ["create", "wait", "release", "close"],
    }[fail_at]
    _assert_clean_tree(raised.value)
    assert SECRET not in "".join(traceback.format_exception(raised.value))


@pytest.mark.parametrize("bad_result", (None, False, 0, 1, "true"))
def test_windows_release_requires_exact_true_and_still_closes(
    tmp_path: Path, bad_result: object
):
    api = FakeWindowsAPI(release_result=bad_result)

    with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name="nt", windows_api=api
        ):
            pass

    assert raised.value.args == (CLEANUP_ERROR,)
    assert _event_names(api.events) == ["create", "wait", "release", "close"]


@pytest.mark.parametrize("bad_result", (None, False, 0, 1, "true"))
def test_windows_close_requires_exact_true(tmp_path: Path, bad_result: object):
    api = FakeWindowsAPI(close_result=bad_result)

    with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name="nt", windows_api=api
        ):
            pass

    assert raised.value.args == (CLEANUP_ERROR,)


def test_windows_cleanup_failures_are_retained_in_release_close_order(tmp_path: Path):
    api = FakeWindowsAPI(release_result=False, close_result=False)

    with pytest.raises(BaseExceptionGroup) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name="nt", windows_api=api
        ):
            pass

    assert raised.value.message == CLEANUP_ERROR
    assert [error.args for error in raised.value.exceptions] == [
        (CLEANUP_ERROR,),
        (CLEANUP_ERROR,),
    ]
    _assert_clean_tree(raised.value)


def test_windows_body_primary_precedes_release_and_close_failures(tmp_path: Path):
    api = FakeWindowsAPI(release_result=False, close_result=False)

    with pytest.raises(BaseExceptionGroup) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name="nt", windows_api=api
        ):
            raise RuntimeError(SECRET)

    assert raised.value.message == LOCK_ERROR
    assert [error.args for error in raised.value.exceptions] == [
        (LOCK_ERROR,),
        (CLEANUP_ERROR,),
        (CLEANUP_ERROR,),
    ]
    _assert_clean_tree(raised.value)


def test_windows_wait_primary_precedes_close_cleanup_failure(tmp_path: Path):
    api = FakeWindowsAPI(wait_result=0xFFFFFFFF, close_result=False)

    with pytest.raises(BaseExceptionGroup) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name="nt", windows_api=api
        ):
            pytest.fail("wait failure entered body")

    assert [error.args for error in raised.value.exceptions] == [
        (LOCK_ERROR,),
        (CLEANUP_ERROR,),
    ]


def test_windows_mutex_name_is_stable_distinct_case_folded_and_opaque(tmp_path: Path):
    def name_for(path: Path) -> str:
        api = FakeWindowsAPI()
        with lifecycle.product_database_lifecycle_lock(
            path, platform_name="nt", windows_api=api
        ):
            pass
        return api.events[0][1]  # type: ignore[index,return-value]

    secret_path = tmp_path / "Private-Config" / "database.json"
    same = tmp_path / "Private-Config" / "." / "database.json"
    case_variant = tmp_path / "private-config" / "DATABASE.JSON"
    other = tmp_path / "Private-Config" / "other.json"
    name = name_for(secret_path)

    assert name == name_for(same) == name_for(case_variant)
    assert name != name_for(other)
    assert re.fullmatch(
        r"Local\\NovelCreator\.ProductDatabaseLifecycle\.[0-9a-f]{64}", name
    )
    assert str(secret_path) not in name
    assert "private-config" not in name.casefold()


def test_posix_success_uses_secure_flags_locks_then_unlocks_and_closes(tmp_path: Path):
    api = FakePosixAPI()

    with lifecycle.product_database_lifecycle_lock(
        tmp_path / "config.json", platform_name="posix", posix_api=api
    ):
        api.events.append("body")

    assert _event_names(api.events) == ["open", "flock", "body", "unlock", "close"]
    _, lock_path, flags, mode = api.events[0]  # type: ignore[misc]
    assert flags == os.O_CREAT | os.O_RDWR | api.o_cloexec | api.o_nofollow
    assert mode == 0o600
    assert api.events[1][2] == api.lock_ex | api.lock_nb  # type: ignore[index]
    assert Path(lock_path).is_file()
    assert Path(lock_path).read_bytes() == b""


@pytest.mark.parametrize("result", (None, False, -1, "3", 1.0))
def test_posix_null_or_malformed_open_fails_without_flock_unlock_or_close(
    tmp_path: Path, result: object
):
    api = FakePosixAPI(open_result=result)

    with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name="posix", posix_api=api
        ):
            pytest.fail("malformed descriptor entered body")

    assert raised.value.args == (LOCK_ERROR,)
    assert _event_names(api.events) == ["open"]


@pytest.mark.parametrize("missing", ("open", "flock", "unlock", "close"))
def test_posix_malformed_api_fails_before_opening(tmp_path: Path, missing: str):
    fake = FakePosixAPI()
    methods = {
        name: getattr(fake, name)
        for name in ("open", "flock", "unlock", "close")
        if name != missing
    }
    capabilities = {
        name: getattr(fake, name)
        for name in ("o_cloexec", "o_nofollow", "lock_ex", "lock_nb")
    }

    with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json",
            platform_name="posix",
            posix_api=SimpleNamespace(**methods, **capabilities),
        ):
            pytest.fail("malformed API entered body")

    assert raised.value.args == (LOCK_ERROR,)
    assert fake.events == []


@pytest.mark.parametrize(
    "missing", ("o_cloexec", "o_nofollow", "lock_ex", "lock_nb")
)
def test_posix_missing_required_capability_fails_before_opening(
    tmp_path: Path, missing: str
):
    api = FakePosixAPI()
    delattr(api, missing)

    with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name="posix", posix_api=api
        ):
            pytest.fail("missing POSIX capability entered body")

    assert raised.value.args == (LOCK_ERROR,)
    assert api.events == []


@pytest.mark.parametrize("capability", ("o_cloexec", "o_nofollow", "lock_ex", "lock_nb"))
@pytest.mark.parametrize("invalid", (None, False, True, 0, -1, 1.0, "8"))
def test_posix_malformed_required_capability_fails_before_opening(
    tmp_path: Path, capability: str, invalid: object
):
    api = FakePosixAPI()
    setattr(api, capability, invalid)

    with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name="posix", posix_api=api
        ):
            pytest.fail("malformed POSIX capability entered body")

    assert raised.value.args == (LOCK_ERROR,)
    assert api.events == []


@pytest.mark.parametrize(
    ("first", "second", "value"),
    (
        ("o_cloexec", "o_nofollow", 0x00100000),
        ("o_cloexec", "o_nofollow", 0x00300000),
        ("o_cloexec", "base", os.O_CREAT),
        ("o_nofollow", "base", os.O_RDWR),
        ("lock_ex", "lock_nb", 0x00001000),
        ("lock_ex", "lock_nb", 0x00003000),
    ),
)
def test_posix_aliased_capabilities_fail_before_opening(
    tmp_path: Path, first: str, second: str, value: int
):
    api = FakePosixAPI()
    setattr(api, first, value)
    if second != "base":
        setattr(api, second, value)

    with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name="posix", posix_api=api
        ):
            pytest.fail("aliased POSIX capabilities entered body")

    assert raised.value.args == (LOCK_ERROR,)
    assert api.events == []


@pytest.mark.parametrize("bad_result", (False, 0, True, "none"))
def test_posix_flock_requires_exact_none_and_closes_without_unlock(
    tmp_path: Path, bad_result: object
):
    api = FakePosixAPI(flock_result=bad_result)

    with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name="posix", posix_api=api
        ):
            pytest.fail("malformed flock entered body")

    assert raised.value.args == (LOCK_ERROR,)
    assert _event_names(api.events) == ["open", "flock", "close"]


def test_posix_contention_fails_immediately_without_entering_body(tmp_path: Path):
    api = FakePosixAPI(fail_at="flock")
    entered = False
    started = time.perf_counter()

    with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name="posix", posix_api=api
        ):
            entered = True

    assert time.perf_counter() - started < 1
    assert not entered
    assert raised.value.args == (LOCK_ERROR,)
    assert _event_names(api.events) == ["open", "flock", "close"]
    _assert_clean_tree(raised.value)


@pytest.mark.parametrize("fail_at", ("open", "flock", "unlock", "close"))
def test_posix_api_exceptions_are_fixed_safe_and_cleanup_continues(
    tmp_path: Path, fail_at: str
):
    api = FakePosixAPI(fail_at=fail_at)

    with pytest.raises(BaseException) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name="posix", posix_api=api
        ):
            pass

    assert _event_names(api.events) == {
        "open": ["open"],
        "flock": ["open", "flock", "close"],
        "unlock": ["open", "flock", "unlock", "close"],
        "close": ["open", "flock", "unlock", "close"],
    }[fail_at]
    _assert_clean_tree(raised.value)
    assert SECRET not in "".join(traceback.format_exception(raised.value))


@pytest.mark.parametrize("bad_result", (False, 0, True, "none"))
def test_posix_unlock_requires_exact_none_and_still_closes(
    tmp_path: Path, bad_result: object
):
    api = FakePosixAPI(unlock_result=bad_result)

    with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name="posix", posix_api=api
        ):
            pass

    assert raised.value.args == (CLEANUP_ERROR,)
    assert _event_names(api.events) == ["open", "flock", "unlock", "close"]


@pytest.mark.parametrize("bad_result", (False, 0, True, "none"))
def test_posix_close_requires_exact_none(tmp_path: Path, bad_result: object):
    api = FakePosixAPI(close_result=bad_result)

    with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name="posix", posix_api=api
        ):
            pass

    assert raised.value.args == (CLEANUP_ERROR,)


def test_posix_rejects_nonregular_descriptor_and_closes_it(tmp_path: Path):
    read_descriptor, write_descriptor = os.pipe()
    api = FakePosixAPI(open_result=read_descriptor)
    try:
        with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
            with lifecycle.product_database_lifecycle_lock(
                tmp_path / "config.json", platform_name="posix", posix_api=api
            ):
                pytest.fail("nonregular descriptor entered body")
    finally:
        os.close(write_descriptor)

    assert raised.value.args == (LOCK_ERROR,)
    assert _event_names(api.events) == ["open", "close"]


def test_posix_rejects_nonempty_stable_lock_file_and_never_deletes_it(tmp_path: Path):
    api = FakePosixAPI()
    config = tmp_path / "config.json"
    with lifecycle.product_database_lifecycle_lock(
        config, platform_name="posix", posix_api=api
    ):
        pass
    lock_path = api.events[0][1]  # type: ignore[index]
    Path(lock_path).write_bytes(b"unexpected")
    second = FakePosixAPI()

    with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
        with lifecycle.product_database_lifecycle_lock(
            config, platform_name="posix", posix_api=second
        ):
            pytest.fail("nonempty lock entered body")

    assert raised.value.args == (LOCK_ERROR,)
    assert _event_names(second.events) == ["open", "close"]
    assert Path(lock_path).read_bytes() == b"unexpected"


def test_posix_rejects_path_identity_mismatch_then_unlocks_and_closes(tmp_path: Path):
    other = tmp_path / "other-lock"
    other.touch()

    def wrong_owner(path: Path, _flags: int, _mode: int) -> int:
        path.touch(exist_ok=True)
        return os.open(other, os.O_RDWR)

    api = FakePosixAPI(opener=wrong_owner)

    with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name="posix", posix_api=api
        ):
            pytest.fail("mismatched path identity entered body")

    assert raised.value.args == (LOCK_ERROR,)
    assert _event_names(api.events) == ["open", "flock", "unlock", "close"]


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX symlink semantics")
def test_posix_rejects_a_symlink_at_the_stable_lock_path(tmp_path: Path):
    config = tmp_path / "config.json"
    capture = FakePosixAPI()
    with lifecycle.product_database_lifecycle_lock(
        config, platform_name="posix", posix_api=capture
    ):
        pass
    lock_path = Path(capture.events[0][1])  # type: ignore[index]
    target = tmp_path / "attacker-lock"
    target.touch()
    lock_path.unlink()
    lock_path.symlink_to(target)

    with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
        with lifecycle.product_database_lifecycle_lock(config, platform_name="posix"):
            pytest.fail("symlink lock entered body")

    assert raised.value.args == (LOCK_ERROR,)
    assert lock_path.is_symlink()


def test_posix_lock_path_is_stable_distinct_case_sensitive_opaque_and_in_temp(
    tmp_path: Path,
):
    def path_for(config: Path) -> Path:
        api = FakePosixAPI()
        with lifecycle.product_database_lifecycle_lock(
            config, platform_name="posix", posix_api=api
        ):
            pass
        return api.events[0][1]  # type: ignore[index,return-value]

    secret_path = tmp_path / "Private-Config" / "database.json"
    same = tmp_path / "Private-Config" / "." / "database.json"
    case_variant = tmp_path / "private-config" / "DATABASE.JSON"
    other = tmp_path / "Private-Config" / "other.json"
    lock_path = path_for(secret_path)

    assert lock_path == path_for(same)
    assert lock_path != path_for(case_variant)
    assert lock_path != path_for(other)
    assert lock_path.parent == Path(tempfile.gettempdir())
    assert re.fullmatch(
        r"novel-creator-product-database-lifecycle-[0-9a-f]{64}\.lock",
        lock_path.name,
    )
    assert str(secret_path) not in str(lock_path)
    assert "private-config" not in lock_path.name.casefold()
    assert stat.S_ISREG(lock_path.lstat().st_mode)


@pytest.mark.parametrize(
    ("factory", "expected_type", "expected_args", "expected_code"),
    (
        (lambda: RuntimeError(SECRET), lifecycle.ProductDatabaseLifecycleError, (LOCK_ERROR,), None),
        (lambda: asyncio.CancelledError(SECRET), asyncio.CancelledError, (), None),
        (lambda: KeyboardInterrupt(SECRET), KeyboardInterrupt, (), None),
        (lambda: SystemExit(7), SystemExit, (7,), 7),
        (lambda: SystemExit(True), SystemExit, (), None),
        (lambda: SystemExit(SECRET), SystemExit, (), None),
    ),
)
@pytest.mark.parametrize("platform_name", ("nt", "posix"))
def test_body_ordinary_and_all_flow_variants_are_rebuilt_public_safe(
    tmp_path: Path,
    platform_name: str,
    factory: Callable[[], BaseException],
    expected_type: type[BaseException],
    expected_args: tuple[object, ...],
    expected_code: object,
):
    api_kwargs = (
        {"windows_api": FakeWindowsAPI()}
        if platform_name == "nt"
        else {"posix_api": FakePosixAPI()}
    )

    with pytest.raises(expected_type) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name=platform_name, **api_kwargs
        ):
            _raise_dirty(factory())

    assert raised.value.args == expected_args
    assert getattr(raised.value, "code", None) == expected_code
    _assert_clean_tree(raised.value)
    assert SECRET not in "".join(traceback.format_exception(raised.value))


@pytest.mark.parametrize("platform_name", ("nt", "posix"))
def test_body_exception_groups_are_recursively_rebuilt_without_secrets(
    tmp_path: Path, platform_name: str
):
    api_kwargs = (
        {"windows_api": FakeWindowsAPI()}
        if platform_name == "nt"
        else {"posix_api": FakePosixAPI()}
    )
    group = BaseExceptionGroup(
        SECRET,
        [
            RuntimeError(SECRET),
            BaseExceptionGroup(
                SECRET,
                [KeyboardInterrupt(SECRET), asyncio.CancelledError(SECRET), SystemExit(9)],
            ),
        ],
    )

    with pytest.raises(BaseExceptionGroup) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name=platform_name, **api_kwargs
        ):
            _raise_dirty(group)

    assert raised.value.message == LOCK_ERROR
    leaves = _leaves(raised.value)
    assert [type(leaf) for leaf in leaves] == [
        lifecycle.ProductDatabaseLifecycleError,
        KeyboardInterrupt,
        asyncio.CancelledError,
        SystemExit,
    ]
    assert leaves[1].args == ()
    assert leaves[2].args == ()
    assert leaves[3].args == (9,)
    _assert_clean_tree(raised.value)
    assert SECRET not in "".join(traceback.format_exception(raised.value))


@pytest.mark.parametrize("platform_name", ("nt", "posix"))
def test_body_primary_first_and_cleanup_failure_groups_retain_operation_order(
    tmp_path: Path, platform_name: str
):
    cleanup_group = BaseExceptionGroup(
        SECRET, [KeyboardInterrupt(SECRET), RuntimeError(SECRET)]
    )
    if platform_name == "nt":
        api_kwargs = {
            "windows_api": FakeWindowsAPI(
                release_error=cleanup_group, close_error=SystemExit(SECRET)
            )
        }
    else:
        api_kwargs = {
            "posix_api": FakePosixAPI(
                unlock_error=cleanup_group, close_error=SystemExit(SECRET)
            )
        }

    with pytest.raises(BaseExceptionGroup) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name=platform_name, **api_kwargs
        ):
            raise RuntimeError(SECRET)

    assert raised.value.message == LOCK_ERROR
    primary, first_cleanup, second_cleanup = raised.value.exceptions
    assert type(primary) is lifecycle.ProductDatabaseLifecycleError
    assert primary.args == (LOCK_ERROR,)
    assert isinstance(first_cleanup, BaseExceptionGroup)
    assert [type(leaf) for leaf in first_cleanup.exceptions] == [
        KeyboardInterrupt,
        lifecycle.ProductDatabaseLifecycleError,
    ]
    assert type(second_cleanup) is SystemExit
    assert second_cleanup.args == ()
    _assert_clean_tree(raised.value)
    assert SECRET not in "".join(traceback.format_exception(raised.value))


@pytest.mark.parametrize("platform_name", ("bad", "windows", "", None, True))
def test_unsupported_or_malformed_platform_fails_fixed_safe(
    tmp_path: Path, platform_name: object
):
    with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
        with lifecycle.product_database_lifecycle_lock(
            tmp_path / "config.json", platform_name=platform_name  # type: ignore[arg-type]
        ):
            pytest.fail("unsupported platform entered body")

    assert raised.value.args == (LOCK_ERROR,)
    _assert_clean_tree(raised.value)


def test_malformed_config_path_failure_does_not_leak_fspath_secret():
    class DirtyPath:
        def __fspath__(self) -> str:
            raise ValueError(SECRET)

    with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
        with lifecycle.product_database_lifecycle_lock(DirtyPath()):  # type: ignore[arg-type]
            pytest.fail("malformed path entered body")

    assert raised.value.args == (LOCK_ERROR,)
    _assert_clean_tree(raised.value)
    assert SECRET not in "".join(traceback.format_exception(raised.value))


def test_real_separate_process_contention_is_immediate_and_released_on_owner_exit(
    tmp_path: Path,
):
    config = tmp_path / "private-config.json"
    ready = tmp_path / "owner-ready"
    release = tmp_path / "owner-release"
    child = """
import sys
import time
from pathlib import Path
from backend.services.product_database_lifecycle_lock import product_database_lifecycle_lock

config, ready, release = map(Path, sys.argv[1:])
with product_database_lifecycle_lock(config):
    ready.write_text("ready", encoding="utf-8")
    while not release.exists():
        time.sleep(0.01)
"""
    entered = False

    with subprocess.Popen(
        [sys.executable, "-c", child, str(config), str(ready), str(release)],
        cwd=Path(__file__).resolve().parents[3],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    ) as owner:
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and owner.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            if not ready.exists():
                _, stderr = owner.communicate(timeout=2)
                pytest.fail(f"owner failed to acquire lifecycle lock: {stderr}")

            started = time.perf_counter()
            with pytest.raises(lifecycle.ProductDatabaseLifecycleError) as raised:
                with lifecycle.product_database_lifecycle_lock(config):
                    entered = True
            elapsed = time.perf_counter() - started

            assert not entered
            assert elapsed < 2
            assert raised.value.args == (LOCK_ERROR,)
        finally:
            release.touch(exist_ok=True)
            try:
                _, stderr = owner.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                owner.kill()
                _, stderr = owner.communicate(timeout=5)
                pytest.fail(f"owner process did not exit: {stderr}")

        assert owner.returncode == 0, stderr

    entered_after_exit = False
    with lifecycle.product_database_lifecycle_lock(config):
        entered_after_exit = True
    assert entered_after_exit
