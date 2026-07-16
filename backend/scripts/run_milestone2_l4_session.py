"""Guarded disposable L4 browser/corpus acceptance session."""

from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import inspect
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable, Mapping, Sequence
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import urlopen
from uuid import uuid4


_POPEN_TYPE = subprocess.Popen


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = REPOSITORY_ROOT / "frontend"
_DISPOSABLE_DATABASE = re.compile(r"novel_creator_test_[a-f0-9]{32}\Z")
_SAFE_NONCE = re.compile(r"[A-Za-z0-9_-]+\Z")
_REQUIRED_TEST_VARIABLES = (
    "TEST_MYSQL_HOST",
    "TEST_MYSQL_PORT",
    "TEST_MYSQL_USER",
    "TEST_MYSQL_PASSWORD",
)
_INHERITED_CHILD_KEYS = (
    "PATH", "SystemRoot", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR",
    "PATHEXT", "COMSPEC", "PYTHONHOME", "PYTHONPATH",
)
_COMMAND_TIMEOUT_SECONDS = 120.0
_HEALTH_TIMEOUT_SECONDS = 30.0
_TEMP_SENTINEL = ".m2-session-owner.json"
_DEFAULT_TEMP_PARENT = Path(tempfile.gettempdir()) / "novel-creator-m2-private"


class L4SessionSafetyError(RuntimeError):
    """The L4 session is not provably disposable and private."""


class PortReservation:
    """A loopback port whose socket remains bound until release()."""

    def __init__(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.bind(("127.0.0.1", 0))
        except BaseException:
            server.close()
            raise
        self._server: socket.socket | None = server
        self.port = int(server.getsockname()[1])

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None


def _test_config(environment: Mapping[str, str]) -> dict[str, object]:
    missing = [name for name in _REQUIRED_TEST_VARIABLES if not environment.get(name)]
    if missing:
        raise L4SessionSafetyError(
            "L4 requires explicit test variables: " + ", ".join(missing)
        )
    try:
        port = int(environment["TEST_MYSQL_PORT"])
    except (TypeError, ValueError) as exc:
        raise L4SessionSafetyError("TEST_MYSQL_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise L4SessionSafetyError("TEST_MYSQL_PORT is outside the TCP port range")
    return {
        "host": environment["TEST_MYSQL_HOST"],
        "port": port,
        "user": environment["TEST_MYSQL_USER"],
        "password": environment["TEST_MYSQL_PASSWORD"],
    }


def _assert_disposable_database(database: str) -> None:
    if not isinstance(database, str) or _DISPOSABLE_DATABASE.fullmatch(database) is None:
        raise L4SessionSafetyError(f"Refusing non-disposable L4 database: {database!r}")


def _validated_nonce(nonce: object) -> str:
    if not isinstance(nonce, str) or not nonce or _SAFE_NONCE.fullmatch(nonce) is None:
        raise L4SessionSafetyError("M2 session nonce must be a non-empty path-safe string")
    return nonce


def _authorized_source(corpus_root: Path | str, relative_file: str) -> Path:
    unresolved_root = Path(corpus_root)
    relative_posix = PurePosixPath(relative_file)
    relative_windows = PureWindowsPath(relative_file)
    if (
        not unresolved_root.is_absolute()
        or not isinstance(relative_file, str)
        or not relative_file
        or relative_posix.is_absolute()
        or relative_windows.is_absolute()
        or bool(relative_windows.drive)
        or ".." in relative_posix.parts
        or ".." in relative_windows.parts
    ):
        raise L4SessionSafetyError("L4 authorized corpus path is invalid")
    try:
        root = unresolved_root.resolve(strict=True)
        source = (root / relative_file).resolve(strict=True)
    except OSError as exc:
        raise L4SessionSafetyError("L4 authorized corpus file does not exist") from exc
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise L4SessionSafetyError("L4 authorized corpus must remain under its root") from exc
    if not source.is_file():
        raise L4SessionSafetyError("L4 authorized corpus file does not exist")
    return source


def _minimal_inherited_environment(environment: Mapping[str, str]) -> dict[str, str]:
    return {
        key: str(environment[key])
        for key in _INHERITED_CHILD_KEYS
        if environment.get(key) not in (None, "")
    }


def build_test_child_environment(
    environment: Mapping[str, str], database: str, corpus_root: Path,
) -> dict[str, str]:
    config = _test_config(environment)
    _assert_disposable_database(database)
    return {
        **_minimal_inherited_environment(environment),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "MYSQL_HOST": str(config["host"]),
        "MYSQL_PORT": str(config["port"]),
        "MYSQL_USER": str(config["user"]),
        "MYSQL_PASSWORD": str(config["password"]),
        "MYSQL_DB": database,
        "CORPUS_ROOT": str(corpus_root),
    }


def private_scan_values(
    config: Mapping[str, object], database: str, corpus_root: str, *extra: str,
) -> set[str]:
    user = str(config["user"])
    password = str(config["password"])
    host = str(config["host"])
    port = int(config["port"])
    encoded_user = quote(user, safe="")
    encoded_password = quote(password, safe="")
    values = {
        password,
        database,
        corpus_root,
        f"mysql://{user}:{password}@{host}:{port}/{database}",
        f"mysql://{encoded_user}:{encoded_password}@{host}:{port}/{database}",
        f"mysql+aiomysql://{user}:{password}@{host}:{port}/{database}",
        f"mysql+aiomysql://{encoded_user}:{encoded_password}@{host}:{port}/{database}",
        *extra,
    }
    return {value for value in values if isinstance(value, str) and value}


def _reserve_port() -> PortReservation:
    return PortReservation()


def _validate_reservation(reservation: object) -> None:
    port = getattr(reservation, "port", None)
    release = getattr(reservation, "release", None)
    if not isinstance(port, int) or not 1 <= port <= 65535 or not callable(release):
        raise L4SessionSafetyError("M2 session port reservation is invalid")


def _release_reservations(reservations: Sequence[object]) -> list[BaseException]:
    errors: list[BaseException] = []
    for reservation in reservations:
        try:
            reservation.release()
        except BaseException as exc:
            errors.append(exc)
    return errors


def _acquire_reservations(factory) -> list[object]:
    reservations: list[object] = []
    try:
        for _index in range(2):
            reservation = factory()
            reservations.append(reservation)
            _validate_reservation(reservation)
        if reservations[0].port == reservations[1].port:
            raise L4SessionSafetyError("M2 session ports must be distinct")
    except BaseException as exc:
        _raise_errors(
            [exc, *_release_reservations(reservations)],
            "M2 port reservation and cleanup failed",
        )
        raise AssertionError("unreachable")
    return reservations


def _creation_flags(platform_name: str | None = None) -> int:
    selected_platform = os.name if platform_name is None else platform_name
    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if selected_platform == "nt":
        flags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        # subprocess does not expose CREATE_SUSPENDED on every supported
        # Python build.  The Win32 value is stable and documented.
        flags |= int(getattr(subprocess, "CREATE_SUSPENDED", 0x00000004))
    return flags


class _WindowsJobApi:
    """Small ctypes boundary for an owned, kill-on-close Windows Job Object."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class BASIC_LIMITS(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class EXTENDED_LIMITS(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC_LIMITS),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        class BASIC_ACCOUNTING(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_int64),
                ("TotalKernelTime", ctypes.c_int64),
                ("ThisPeriodTotalUserTime", ctypes.c_int64),
                ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                ("TotalPageFaultCount", wintypes.DWORD),
                ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD),
                ("TotalTerminatedProcesses", wintypes.DWORD),
            ]

        self._extended_limits = EXTENDED_LIMITS
        self._basic_accounting = BASIC_ACCOUNTING
        kernel32 = self._kernel32
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        class THREADENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG),
                ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
            ]

        self._thread_entry = THREADENTRY32
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Thread32First.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(THREADENTRY32),
        ]
        kernel32.Thread32First.restype = wintypes.BOOL
        kernel32.Thread32Next.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(THREADENTRY32),
        ]
        kernel32.Thread32Next.restype = wintypes.BOOL
        kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenThread.restype = wintypes.HANDLE
        kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel32.ResumeThread.restype = wintypes.DWORD

    def _error(self, operation: str) -> OSError:
        return OSError(self._ctypes.get_last_error(), f"{operation} failed")

    def create_kill_on_close_job(self):
        handle = self._kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise self._error("CreateJobObjectW")
        limits = self._extended_limits()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        if not self._kernel32.SetInformationJobObject(
            handle, 9, self._ctypes.byref(limits), self._ctypes.sizeof(limits)
        ):
            error = self._error("SetInformationJobObject")
            self._kernel32.CloseHandle(handle)
            raise error
        return handle

    def assign(self, job, child) -> None:
        process_handle = getattr(child, "_handle", None)
        if process_handle in (None, 0):
            raise L4SessionSafetyError("Spawned Windows process handle is unavailable")
        if not self._kernel32.AssignProcessToJobObject(job, process_handle):
            raise self._error("AssignProcessToJobObject")

    def terminate(self, job) -> None:
        if not self._kernel32.TerminateJobObject(job, 1):
            raise self._error("TerminateJobObject")

    def active_processes(self, job) -> int:
        accounting = self._basic_accounting()
        returned = self._wintypes.DWORD()
        if not self._kernel32.QueryInformationJobObject(
            job,
            1,
            self._ctypes.byref(accounting),
            self._ctypes.sizeof(accounting),
            self._ctypes.byref(returned),
        ):
            raise self._error("QueryInformationJobObject")
        return int(accounting.ActiveProcesses)

    def close(self, job) -> None:
        if not self._kernel32.CloseHandle(job):
            raise self._error("CloseHandle(job)")

    def resume_main_thread(self, child) -> None:
        """Resume the sole primary thread of a CREATE_SUSPENDED child."""

        pid = getattr(child, "pid", None)
        if not isinstance(pid, int) or pid <= 0:
            raise L4SessionSafetyError("Spawned Windows process PID is unavailable")
        snapshot = self._kernel32.CreateToolhelp32Snapshot(0x00000004, 0)
        invalid = self._ctypes.c_void_p(-1).value
        if snapshot in (None, 0, invalid):
            raise self._error("CreateToolhelp32Snapshot(threads)")
        thread_ids: list[int] = []
        enumeration_error: BaseException | None = None
        try:
            entry = self._thread_entry()
            entry.dwSize = self._ctypes.sizeof(entry)
            self._ctypes.set_last_error(0)
            present = self._kernel32.Thread32First(
                snapshot, self._ctypes.byref(entry)
            )
            if not present:
                error = self._ctypes.get_last_error()
                if error != 18:  # ERROR_NO_MORE_FILES is the clean terminator.
                    raise OSError(error, "Thread32First failed")
            while present:
                if int(entry.th32OwnerProcessID) == pid:
                    thread_ids.append(int(entry.th32ThreadID))
                self._ctypes.set_last_error(0)
                present = self._kernel32.Thread32Next(
                    snapshot, self._ctypes.byref(entry)
                )
            error = self._ctypes.get_last_error()
            if error != 18:
                raise OSError(error, "Thread32Next failed")
        except BaseException as exc:
            enumeration_error = exc
        try:
            if not self._kernel32.CloseHandle(snapshot):
                raise self._error("CloseHandle(thread snapshot)")
        except BaseException as close_error:
            if enumeration_error is not None:
                raise BaseExceptionGroup(
                    "Windows thread enumeration and snapshot cleanup failed",
                    [enumeration_error, close_error],
                )
            raise
        if enumeration_error is not None:
            raise enumeration_error
        if len(thread_ids) != 1:
            raise L4SessionSafetyError(
                "CREATE_SUSPENDED child did not expose exactly one primary thread"
            )
        thread_handle = self._kernel32.OpenThread(0x0002, False, thread_ids[0])
        if not thread_handle:
            raise self._error("OpenThread(THREAD_SUSPEND_RESUME)")
        resume_error: BaseException | None = None
        try:
            previous_count = int(self._kernel32.ResumeThread(thread_handle))
            if previous_count == 0xFFFFFFFF:
                raise self._error("ResumeThread")
            if previous_count < 1:
                raise L4SessionSafetyError(
                    "CREATE_SUSPENDED primary thread was not suspended"
                )
        except BaseException as exc:
            resume_error = exc
        try:
            if not self._kernel32.CloseHandle(thread_handle):
                raise self._error("CloseHandle(thread)")
        except BaseException as close_error:
            if resume_error is not None:
                raise BaseExceptionGroup(
                    "Windows thread resume and handle cleanup failed",
                    [resume_error, close_error],
                )
            raise
        if resume_error is not None:
            raise resume_error


def _wait_until(predicate, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        if predicate():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))


class WindowsJobProcessGuard:
    """Owns exactly the processes assigned to one opaque Job Object handle."""

    def __init__(self, job, api) -> None:
        self._job = job
        self._api = api
        self._closed = False

    @classmethod
    def attach(cls, child, *, api=None):
        selected_api = api or _WindowsJobApi()
        job = selected_api.create_kill_on_close_job()
        try:
            selected_api.assign(job, child)
        except BaseException:
            try:
                selected_api.close(job)
            except BaseException as close_error:
                raise BaseExceptionGroup(
                    "Windows Job assignment and handle cleanup failed",
                    [sys.exception(), close_error],
                )
            raise
        return cls(job, selected_api)

    def cleanup(
        self, child, *, grace_seconds: float = 10.0, kill_seconds: float = 5.0,
    ) -> list[BaseException]:
        if self._closed:
            return []
        errors: list[BaseException] = []
        try:
            self._api.terminate(self._job)
        except BaseException as exc:
            errors.append(exc)
        wait = getattr(child, "wait", None)
        if callable(wait):
            try:
                wait(timeout=max(0.0, grace_seconds))
            except (subprocess.TimeoutExpired, TimeoutError):
                pass
            except BaseException as exc:
                errors.append(exc)
        try:
            zero = _wait_until(
                lambda: self._api.active_processes(self._job) == 0,
                kill_seconds,
            )
            if not zero:
                errors.append(RuntimeError(
                    "Windows Job active process count did not reach zero"
                ))
        except BaseException as exc:
            errors.append(exc)
        try:
            self._api.close(self._job)
        except BaseException as exc:
            errors.append(exc)
        self._closed = True
        return errors

    def resume(self, child) -> None:
        self._api.resume_main_thread(child)


class PosixProcessGroupGuard:
    """Owns a saved POSIX process-group identity created by start_new_session."""

    def __init__(self, pgid: int, os_module) -> None:
        self._pgid = pgid
        self._os = os_module
        self._closed = False

    @classmethod
    def attach(cls, child, *, os_module=os):
        pid = getattr(child, "pid", None)
        if not isinstance(pid, int) or pid <= 0:
            raise L4SessionSafetyError("Spawned POSIX process PID is unavailable")
        pgid = int(os_module.getpgid(pid))
        if pgid != pid:
            raise L4SessionSafetyError(
                "Spawned POSIX process did not create its own process group"
            )
        return cls(pgid, os_module)

    def _group_exists(self) -> bool:
        try:
            self._os.killpg(self._pgid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def cleanup(
        self, child, *, grace_seconds: float = 10.0, kill_seconds: float = 5.0,
    ) -> list[BaseException]:
        if self._closed:
            return []
        errors: list[BaseException] = []
        sigterm = getattr(signal, "SIGTERM", 15)
        sigkill = getattr(signal, "SIGKILL", 9)
        try:
            self._os.killpg(self._pgid, sigterm)
        except ProcessLookupError:
            pass
        except BaseException as exc:
            errors.append(exc)

        def poll_and_probe() -> bool:
            poll = getattr(child, "poll", None)
            if callable(poll):
                try:
                    poll()
                except BaseException as exc:
                    errors.append(exc)
            try:
                return not self._group_exists()
            except BaseException as exc:
                errors.append(exc)
                return False

        gone = _wait_until(poll_and_probe, grace_seconds)
        wait = getattr(child, "wait", None)
        if callable(wait):
            try:
                wait(timeout=0)
            except (subprocess.TimeoutExpired, TimeoutError):
                pass
            except BaseException as exc:
                errors.append(exc)
        if not gone:
            gone = _wait_until(poll_and_probe, 0)
        if not gone:
            try:
                self._os.killpg(self._pgid, sigkill)
            except ProcessLookupError:
                pass
            except BaseException as exc:
                errors.append(exc)
            gone = _wait_until(poll_and_probe, kill_seconds)
        if callable(wait):
            try:
                wait(timeout=max(0.0, kill_seconds))
            except (subprocess.TimeoutExpired, TimeoutError):
                pass
            except BaseException as exc:
                errors.append(exc)
        try:
            gone = not self._group_exists()
        except BaseException as exc:
            errors.append(exc)
            gone = False
        if not gone:
            errors.append(RuntimeError("POSIX process group exit could not be proven"))
        self._closed = True
        return errors


def default_start_process(label, command, args, cwd, env, log_dir):
    log_dir = Path(log_dir)
    stdout_handle = (log_dir / f"{label}.stdout.log").open("wb")
    stderr_handle = (log_dir / f"{label}.stderr.log").open("wb")
    try:
        kwargs = {
            "cwd": str(cwd),
            "env": dict(env),
            "shell": False,
            "stdin": subprocess.DEVNULL,
            "stdout": stdout_handle,
            "stderr": stderr_handle,
            "creationflags": _creation_flags(),
        }
        if os.name != "nt":
            kwargs["start_new_session"] = True
        def popen_with_logs(*popen_args, **popen_kwargs):
            spawned = subprocess.Popen(*popen_args, **popen_kwargs)
            spawned._m2_log_handles = (  # type: ignore[attr-defined]
                stdout_handle, stderr_handle,
            )
            return spawned

        child, _guard = _spawn_guarded_process(
            [command, *args], kwargs, popen_factory=popen_with_logs,
        )
    except BaseException:
        stdout_handle.close()
        stderr_handle.close()
        raise
    return child


async def _run_captured(
    label: str,
    command: list[str],
    cwd: Path,
    env,
    log_dir: Path,
    *,
    timeout_seconds: float = _COMMAND_TIMEOUT_SECONDS,
    process_guard_factory=None,
) -> None:
    stdout_handle = (log_dir / f"{label}.stdout.log").open("wb")
    stderr_handle = (log_dir / f"{label}.stderr.log").open("wb")
    child = None
    guard = None
    body_error: BaseException | None = None
    returncode: int | None = None
    try:
        kwargs = {
            "cwd": str(cwd),
            "env": dict(env),
            "shell": False,
            "stdin": subprocess.DEVNULL,
            "stdout": stdout_handle,
            "stderr": stderr_handle,
            "creationflags": _creation_flags(),
        }
        if os.name != "nt":
            kwargs["start_new_session"] = True
        def popen_with_logs(*popen_args, **popen_kwargs):
            spawned = subprocess.Popen(*popen_args, **popen_kwargs)
            spawned._m2_log_handles = (  # type: ignore[attr-defined]
                stdout_handle, stderr_handle,
            )
            return spawned

        child, guard = _spawn_guarded_process(
            command,
            kwargs,
            process_guard_factory=(
                process_guard_factory or _default_process_guard_factory
            ),
            popen_factory=popen_with_logs,
        )
        deadline = time.monotonic() + timeout_seconds
        while True:
            returncode = child.poll()
            if returncode is not None:
                break
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(command, timeout_seconds)
            await asyncio.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        if returncode != 0:
            raise RuntimeError(f"{label} command exited with status {returncode}")
    except BaseException as exc:
        body_error = exc
    cleanup_errors: list[BaseException] = []
    if child is not None:
        if guard is not None:
            cleanup_errors.extend(_stop_process(child, guard=guard))
    else:
        try:
            stdout_handle.close()
            stderr_handle.close()
        except BaseException as exc:
            cleanup_errors.append(exc)
    if body_error is not None:
        _raise_errors(
            [body_error, *cleanup_errors],
            f"{label} command and process-tree cleanup failed",
        )
    _raise_errors(cleanup_errors, f"{label} process-tree cleanup failed")


async def _monitor_descendants(
    child,
    tracked: set[int],
    errors: list[BaseException],
    ready: asyncio.Event,
    stop: asyncio.Event,
) -> None:
    try:
        while not stop.is_set():
            try:
                tracked.update(_capture_descendant_pids(child))
            except BaseException as exc:
                errors.append(exc)
                return
            finally:
                ready.set()
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.02)
            except asyncio.TimeoutError:
                continue
    finally:
        ready.set()


async def _daemon_call(function, *args, **kwargs):
    """Run a bounded blocking operation without owning asyncio's default executor."""

    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def worker() -> None:
        try:
            result = function(*args, **kwargs)
        except BaseException as exc:
            if not loop.is_closed():
                loop.call_soon_threadsafe(_settle_future, future, None, exc)
        else:
            if not loop.is_closed():
                loop.call_soon_threadsafe(_settle_future, future, result, None)

    threading.Thread(target=worker, daemon=True, name="m2-bounded-worker").start()
    return await future


def _settle_future(future, result, error) -> None:
    if future.done():
        return
    if error is not None:
        future.set_exception(error)
    else:
        future.set_result(result)


async def default_prepare(database, env, log_dir):
    await _run_captured(
        "prepare",
        [
            sys.executable, "-m", "backend.scripts.prepare_milestone2_browser_db",
            "--database", database, "--scenario", "settings",
        ],
        REPOSITORY_ROOT,
        env,
        Path(log_dir),
        timeout_seconds=_COMMAND_TIMEOUT_SECONDS,
    )


async def default_drop(database, env, log_dir):
    await _run_captured(
        "drop",
        [
            sys.executable, "-m", "backend.scripts.prepare_milestone2_browser_db",
            "--database", database, "--scenario", "settings", "--drop",
        ],
        REPOSITORY_ROOT,
        env,
        Path(log_dir),
        timeout_seconds=_COMMAND_TIMEOUT_SECONDS,
    )


def _read_json_log(path: Path, *, max_bytes: int = 128 * 1024) -> object:
    if path.stat().st_size > max_bytes:
        raise L4SessionSafetyError("Verifier receipt exceeded the bounded size")
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise L4SessionSafetyError("Verifier returned no receipt")
    try:
        return json.loads(lines[-1])
    except (TypeError, ValueError) as exc:
        raise L4SessionSafetyError("Verifier returned invalid JSON") from exc


def _normalize_corpus_command_receipt(value: object, source_hash: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise L4SessionSafetyError("L4 verification receipt must be an object")
    required = {
        "relativePath", "rawHash", "encoding", "size", "chapterCount",
        "fragmentCount", "firstByteStart", "lastByteEnd", "firstCharStart",
        "lastCharEnd", "parserVersion", "normalizerVersion",
        "fragmenterVersion", "indexVersion", "status",
    }
    if set(value) != required or value.get("rawHash") != source_hash:
        raise L4SessionSafetyError("L4 verification receipt did not match the selected source")
    size = value.get("size")
    chapter_count = value.get("chapterCount")
    fragment_count = value.get("fragmentCount")
    if (
        not isinstance(size, int) or size <= 0
        or not isinstance(chapter_count, int) or chapter_count <= 0
        or not isinstance(fragment_count, int) or fragment_count <= 0
        or value.get("firstByteStart") != 0
        or value.get("lastByteEnd") != size
        or value.get("firstCharStart") != 0
        or not isinstance(value.get("lastCharEnd"), int)
        or value.get("lastCharEnd") <= 0
        or value.get("status") != "analyzed"
    ):
        raise L4SessionSafetyError("L4 verification receipt failed closed invariants")
    versions = {
        "parser": value.get("parserVersion"),
        "normalizer": value.get("normalizerVersion"),
        "fragmenter": value.get("fragmenterVersion"),
        "index": value.get("indexVersion"),
    }
    if any(not isinstance(item, str) or not item or len(item) > 128 for item in versions.values()):
        raise L4SessionSafetyError("L4 verification versions are incomplete")
    return {
        "sourceHash": source_hash,
        "chapterCount": chapter_count,
        "fragmentCount": fragment_count,
        "fileSize": size,
        "versions": versions,
    }


async def default_verifier(database, source_hash, env, log_dir):
    await _run_captured(
        "verifier",
        [
            sys.executable, "-m", "backend.scripts.verify_corpus_import",
            "--database", database, "--source-hash", source_hash,
        ],
        REPOSITORY_ROOT,
        env,
        Path(log_dir),
        timeout_seconds=_COMMAND_TIMEOUT_SECONDS,
    )
    value = _read_json_log(Path(log_dir) / "verifier.stdout.log")
    return _normalize_corpus_command_receipt(value, source_hash)


async def default_wait_for_health(
    label,
    url,
    child,
    *,
    expected_nonce,
    timeout_seconds=_HEALTH_TIMEOUT_SECONDS,
):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError(f"{label} process exited before health verification")
        try:
            response = await asyncio.wait_for(
                _daemon_call(urlopen, url, None, 2),
                timeout=min(3.0, max(0.1, deadline - time.monotonic())),
            )
            try:
                if response.status != 200:
                    await asyncio.sleep(0.1)
                    continue
                payload = response.read(65_537)
            finally:
                response.close()
            if len(payload) > 65_536:
                raise L4SessionSafetyError(f"{label} ownership response exceeded its bound")
            try:
                decoded = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise L4SessionSafetyError(f"{label} ownership response was invalid") from exc
            expected_payload = (
                {"ok": True, "browserRunNonce": expected_nonce}
                if label == "backend"
                else {"browserRunNonce": expected_nonce}
                if label == "vite"
                else None
            )
            if expected_payload is None or decoded != expected_payload:
                raise L4SessionSafetyError(
                    f"{label} ownership response shape or nonce did not match"
                )
            return
        except L4SessionSafetyError:
            raise
        except (OSError, URLError, asyncio.TimeoutError):
            await asyncio.sleep(0.1)
    raise RuntimeError(f"{label} health verification timed out")


async def default_wait_for_input(prompt):
    return await _daemon_call(input, prompt)


def default_scan_logs(
    log_dir,
    sensitive_values,
    *,
    chunk_size: int = 64 * 1024,
    max_total_bytes: int = 32 * 1024 * 1024,
) -> int:
    if chunk_size <= 0 or max_total_bytes < 0:
        raise ValueError("log scan bounds must be non-negative")
    patterns = tuple(
        value.encode("utf-8")
        for value in sensitive_values
        if isinstance(value, str) and value
    )
    paths = sorted(path for path in Path(log_dir).glob("*.log") if path.is_file())
    total_size = sum(path.stat().st_size for path in paths)
    if total_size > max_total_bytes:
        raise L4SessionSafetyError("L4 log size exceeded the scan bound")
    if not patterns:
        return 0
    overlap_size = max(len(pattern) for pattern in patterns) - 1
    match_count = 0
    for path in paths:
        overlap = b""
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                payload = overlap + chunk
                old_boundary = len(overlap)
                for pattern in patterns:
                    start = 0
                    while True:
                        index = payload.find(pattern, start)
                        if index < 0:
                            break
                        if index + len(pattern) > old_boundary:
                            match_count += 1
                        start = index + 1
                overlap = payload[-overlap_size:] if overlap_size else b""
    return match_count


def _close_process_logs(child) -> None:
    for handle in getattr(child, "_m2_log_handles", ()):
        handle.flush()
        handle.close()


def _descendants_from_parent_map(root_pid: int, parent_by_pid: Mapping[int, int]) -> set[int]:
    descendants: set[int] = set()
    frontier = [root_pid]
    while frontier:
        parent = frontier.pop()
        children = [pid for pid, ppid in parent_by_pid.items() if ppid == parent]
        for pid in children:
            if pid not in descendants:
                descendants.add(pid)
                frontier.append(pid)
    return descendants


def _windows_parent_map() -> dict[int, int]:
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W),
    ]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W),
    ]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    invalid = ctypes.c_void_p(-1).value
    if snapshot == invalid:
        raise OSError(ctypes.get_last_error(), "CreateToolhelp32Snapshot failed")
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    result: dict[int, int] = {}
    try:
        ctypes.set_last_error(0)
        present = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        if not present:
            error = ctypes.get_last_error()
            if error != 18:  # ERROR_NO_MORE_FILES is the only clean empty result.
                raise L4SessionSafetyError(
                    f"Windows Toolhelp Process32FirstW failed with error {error}"
                )
            return result
        while present:
            result[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            ctypes.set_last_error(0)
            present = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        error = ctypes.get_last_error()
        if error != 18:  # ERROR_NO_MORE_FILES terminates a complete enumeration.
            raise L4SessionSafetyError(
                f"Windows Toolhelp Process32NextW failed with error {error}"
            )
    finally:
        kernel32.CloseHandle(snapshot)
    return result


def _posix_parent_map() -> dict[int, int]:
    result: dict[int, int] = {}
    proc = Path("/proc")
    if not proc.is_dir():
        return result
    for path in proc.iterdir():
        if not path.name.isdigit():
            continue
        try:
            value = (path / "stat").read_text(encoding="ascii")
            suffix = value[value.rfind(")") + 2:].split()
            result[int(path.name)] = int(suffix[1])
        except (OSError, ValueError, IndexError):
            continue
    return result


def _capture_descendant_pids(child) -> set[int]:
    custom = getattr(child, "capture_descendant_pids", None)
    if callable(custom):
        values = custom()
        if not isinstance(values, (set, frozenset, list, tuple)):
            raise RuntimeError("Descendant PID capture returned an invalid value")
        return {int(pid) for pid in values}
    pid = getattr(child, "pid", None)
    if not isinstance(pid, int):
        return set()
    parent_map = _windows_parent_map() if os.name == "nt" else _posix_parent_map()
    return _descendants_from_parent_map(pid, parent_map)


def _pid_is_alive(child, pid: int) -> bool:
    custom = getattr(child, "pid_is_alive", None)
    if callable(custom):
        return bool(custom(pid))
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x00100000, False, pid)
        if not handle:
            # ERROR_INVALID_PARAMETER is the documented result for a PID that
            # no longer exists. Access-denied and other failures are fail-closed
            # as potentially alive.
            return ctypes.get_last_error() != 87
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 0x00000102
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _kill_process_tree(child, descendant_pids: set[int]) -> None:
    custom = getattr(child, "kill_tree", None)
    if callable(custom):
        parameters = inspect.signature(custom).parameters
        custom(descendant_pids) if parameters else custom()
        return
    pid = getattr(child, "pid", None)
    if os.name == "nt":
        raise RuntimeError(
            "Windows process-tree termination requires an owned Job Object"
        )
    if isinstance(pid, int):
        try:
            os.killpg(pid, 9)
        except ProcessLookupError:
            pass
        return
    kill = getattr(child, "kill", None)
    if callable(kill):
        kill()
        return
    raise RuntimeError("Process tree cannot be force-terminated")


def _stop_test_double_process(
    child, *, tracked_descendants: set[int] | None = None,
) -> list[BaseException]:
    errors: list[BaseException] = []
    descendants: set[int] = set(tracked_descendants or ())
    try:
        descendants.update(_capture_descendant_pids(child))
    except BaseException as exc:
        errors.append(exc)
    parent_running = getattr(child, "returncode", None) is None
    if parent_running:
        try:
            child.terminate()
        except BaseException as exc:
            errors.append(exc)
    needs_force = False
    if parent_running:
        try:
            child.wait(timeout=10)
        except (subprocess.TimeoutExpired, TimeoutError):
            needs_force = True
        except BaseException as exc:
            errors.append(exc)
            needs_force = True
    try:
        descendants.update(_capture_descendant_pids(child))
    except BaseException as exc:
        errors.append(exc)
    if needs_force or descendants:
        try:
            _kill_process_tree(child, descendants)
        except BaseException as exc:
            errors.append(exc)
        try:
            child.wait(timeout=5)
        except BaseException as exc:
            errors.append(exc)
    try:
        poll = getattr(child, "poll", None)
        returncode = poll() if callable(poll) else getattr(child, "returncode", None)
        if returncode is None:
            errors.append(RuntimeError("Process exit could not be proven"))
    except BaseException as exc:
        errors.append(exc)
    for pid in sorted(descendants):
        try:
            if _pid_is_alive(child, pid):
                errors.append(RuntimeError(f"Descendant PID {pid} is still alive"))
        except BaseException as exc:
            errors.append(exc)
    try:
        _close_process_logs(child)
    except BaseException as exc:
        errors.append(exc)
    return errors


class _TestDoubleProcessGuard:
    """Compatibility only for injected unit-test children, never real Popen."""

    def cleanup(self, child, **_kwargs) -> list[BaseException]:
        if any(callable(getattr(child, name, None)) for name in (
            "capture_descendant_pids", "kill_tree", "pid_is_alive",
        )):
            return _stop_test_double_process(child)
        errors: list[BaseException] = []
        try:
            poll = getattr(child, "poll", None)
            status = poll() if callable(poll) else getattr(child, "returncode", None)
            if status is None:
                terminate = getattr(child, "terminate", None)
                if not callable(terminate):
                    raise RuntimeError("Injected child cannot be terminated")
                terminate()
                child.wait(timeout=10)
            if callable(poll) and poll() is None:
                errors.append(RuntimeError("Injected child exit could not be proven"))
        except BaseException as exc:
            errors.append(exc)
        try:
            _close_process_logs(child)
        except BaseException as exc:
            errors.append(exc)
        return errors


def _default_process_guard_factory(child):
    if not isinstance(child, _POPEN_TYPE):
        return _TestDoubleProcessGuard()
    if os.name == "nt":
        return WindowsJobProcessGuard.attach(child)
    return PosixProcessGroupGuard.attach(child)


def _stop_unassigned_child(child) -> list[BaseException]:
    """Stop only the direct process object just returned by Popen."""

    errors: list[BaseException] = []
    try:
        child.terminate()
    except BaseException as exc:
        errors.append(exc)
    try:
        child.wait(timeout=5)
    except (subprocess.TimeoutExpired, TimeoutError):
        try:
            child.kill()
        except BaseException as exc:
            errors.append(exc)
        try:
            child.wait(timeout=5)
        except BaseException as exc:
            errors.append(exc)
    except BaseException as exc:
        errors.append(exc)
    try:
        poll = getattr(child, "poll", None)
        if callable(poll) and poll() is None:
            errors.append(RuntimeError("Unassigned child exit could not be proven"))
    except BaseException as exc:
        errors.append(exc)
    try:
        _close_process_logs(child)
    except BaseException as exc:
        errors.append(exc)
    return errors


def _spawn_guarded_process(
    command,
    kwargs,
    *,
    process_guard_factory=None,
    popen_factory=None,
    platform_name: str | None = None,
    windows_resume=None,
):
    """Spawn without exposing a Windows child before Job ownership is complete."""

    selected_platform = os.name if platform_name is None else platform_name
    selected_popen = subprocess.Popen if popen_factory is None else popen_factory
    selected_factory = process_guard_factory or _default_process_guard_factory
    spawn_kwargs = dict(kwargs)
    spawn_kwargs["creationflags"] = int(spawn_kwargs.get("creationflags", 0)) | (
        _creation_flags(selected_platform)
    )
    child = selected_popen(command, **spawn_kwargs)
    guard = None
    try:
        guard = selected_factory(child)
        if not callable(getattr(guard, "cleanup", None)):
            raise L4SessionSafetyError("Process guard does not expose cleanup")
        child._m2_process_guard = guard  # type: ignore[attr-defined]
    except BaseException as exc:
        _raise_errors(
            [exc, *_stop_unassigned_child(child)],
            "Process guard assignment and suspended-child cleanup failed",
        )
        raise AssertionError("unreachable")
    # Injected unit-test children are not OS processes and therefore have no
    # suspended primary thread.  Every real Windows Popen still takes this path.
    must_resume = selected_platform == "nt" and (
        isinstance(child, _POPEN_TYPE) or windows_resume is not None
    )
    if must_resume:
        resume = windows_resume or getattr(guard, "resume", None)
        if not callable(resume):
            resume_error: BaseException = L4SessionSafetyError(
                "Windows process guard cannot resume the suspended primary thread"
            )
        else:
            try:
                resume(child)
            except BaseException as exc:
                resume_error = exc
            else:
                resume_error = None  # type: ignore[assignment]
        if resume_error is not None:
            _raise_errors(
                [resume_error, *_stop_process(child, guard=guard)],
                "Windows primary-thread resume and owned-Job cleanup failed",
            )
            raise AssertionError("unreachable")
    return child, guard


def _attach_process_guard(child, factory):
    existing = getattr(child, "_m2_process_guard", None)
    if existing is not None:
        if not callable(getattr(existing, "cleanup", None)):
            raise L4SessionSafetyError("Process guard does not expose cleanup")
        return existing
    try:
        guard = factory(child)
        if not callable(getattr(guard, "cleanup", None)):
            raise L4SessionSafetyError("Process guard does not expose cleanup")
    except BaseException as exc:
        _raise_errors(
            [exc, *_stop_unassigned_child(child)],
            "Process guard assignment and spawned-child cleanup failed",
        )
        raise AssertionError("unreachable")
    child._m2_process_guard = guard  # type: ignore[attr-defined]
    return guard


def _stop_process(child, *, guard=None) -> list[BaseException]:
    selected = guard or getattr(child, "_m2_process_guard", None)
    if selected is None:
        selected = _default_process_guard_factory(child)
    errors = list(selected.cleanup(child))
    if not isinstance(selected, _TestDoubleProcessGuard):
        try:
            _close_process_logs(child)
        except BaseException as exc:
            errors.append(exc)
    return errors


async def _await(value):
    return await value if inspect.isawaitable(value) else value


async def _bounded_await(value, label: str, timeout_seconds: float = _COMMAND_TIMEOUT_SECONDS):
    try:
        return await asyncio.wait_for(_await(value), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f"{label} exceeded its hard timeout") from exc


def _raise_errors(errors: list[BaseException], message: str) -> None:
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise BaseExceptionGroup(message, errors)


def _temp_contract(parent: Path, nonce: str, kind: str) -> tuple[Path, str]:
    if not parent.is_absolute():
        raise L4SessionSafetyError("Owned temporary parent must be absolute")
    resolved_parent = parent.resolve()
    resolved_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    return resolved_parent, f"novel-creator-m2-{kind}-{nonce}-"


def _assert_owned_temp_shape(path: Path, parent: Path, prefix: str) -> Path:
    if path.is_symlink():
        raise L4SessionSafetyError("Refusing an unowned temporary symlink")
    resolved = path.resolve()
    if resolved == parent or resolved.parent != parent:
        raise L4SessionSafetyError("Refusing an unowned temporary path")
    if not resolved.name.startswith(prefix) or not resolved.name[len(prefix):]:
        raise L4SessionSafetyError("Refusing an unowned temporary prefix")
    return resolved


def _temp_snapshot(parent: Path, prefix: str) -> set[str]:
    try:
        return {
            child.name
            for child in parent.iterdir()
            if child.name.startswith(prefix) and child.name[len(prefix):]
        }
    except OSError as exc:
        raise L4SessionSafetyError("Owned temporary parent could not be inspected") from exc


def _rollback_new_temp_candidates(
    parent: Path, prefix: str, before: set[str],
) -> list[BaseException]:
    """Remove only empty/new nonce directories or a partial owner marker."""

    errors: list[BaseException] = []
    try:
        new_names = sorted(_temp_snapshot(parent, prefix) - before)
    except BaseException as exc:
        return [exc]
    for name in new_names:
        candidate = parent / name
        try:
            owned = _assert_owned_temp_shape(candidate, parent, prefix)
            children = list(owned.iterdir())
            if any(
                child.name != _TEMP_SENTINEL
                or child.is_symlink()
                or not child.is_file()
                for child in children
            ):
                raise L4SessionSafetyError(
                    "Refusing to remove a non-empty temporary setup remnant"
                )
            for child in children:
                child.unlink()
            owned.rmdir()
        except BaseException as exc:
            errors.append(exc)
    return errors


def _create_owned_temp(parent: Path, nonce: str, kind: str, factory) -> tuple[Path, dict[str, str]]:
    parent, prefix = _temp_contract(parent, nonce, kind)
    before = _temp_snapshot(parent, prefix)
    try:
        candidate = Path(factory(parent / prefix))
        path = _assert_owned_temp_shape(candidate, parent, prefix)
        path.mkdir(parents=False, exist_ok=True)
        if path.name in before:
            raise L4SessionSafetyError(
                "Refusing a pre-existing temporary path for this session nonce"
            )
        sentinel = {
            "kind": kind,
            "nonce": nonce,
            "pathHash": sha256(str(path).encode("utf-8")).hexdigest(),
        }
        (path / _TEMP_SENTINEL).write_text(
            json.dumps(sentinel, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        _validate_owned_temp(path, parent, nonce, kind, sentinel)
        return path, sentinel
    except BaseException as exc:
        _raise_errors(
            [exc, *_rollback_new_temp_candidates(parent, prefix, before)],
            "Owned temporary setup and rollback failed",
        )
        raise AssertionError("unreachable")


def _validate_owned_temp(path: Path, parent: Path, nonce: str, kind: str, sentinel) -> None:
    parent, prefix = _temp_contract(parent, nonce, kind)
    owned = _assert_owned_temp_shape(path, parent, prefix)
    marker = owned / _TEMP_SENTINEL
    try:
        actual = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise L4SessionSafetyError("Owned temporary sentinel is missing or invalid") from exc
    if actual != sentinel:
        raise L4SessionSafetyError("Owned temporary sentinel does not match this session")


def _assert_services_live(children: list[tuple[str, object, object]]) -> None:
    for label, child, _guard in children:
        poll = getattr(child, "poll", None)
        if not callable(poll):
            raise L4SessionSafetyError(f"{label} process does not expose liveness")
        status = poll()
        if status is not None:
            raise RuntimeError(f"{label} process exited during the acceptance session")


def _sanitize_l4_verification(value: object, source_hash: str, file_size: int) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "sourceHash", "chapterCount", "fragmentCount", "fileSize", "versions"
    }:
        raise L4SessionSafetyError("L4 verification evidence is not allowlisted")
    if value.get("sourceHash") != source_hash or value.get("fileSize") != file_size:
        raise L4SessionSafetyError("L4 verification evidence does not match the source")
    for key in ("chapterCount", "fragmentCount"):
        if not isinstance(value.get(key), int) or value[key] <= 0:
            raise L4SessionSafetyError("L4 verification evidence counts must be positive")
    versions = value.get("versions")
    if not isinstance(versions, dict) or set(versions) != {
        "parser", "normalizer", "fragmenter", "index"
    } or any(
        not isinstance(item, str) or not item or len(item) > 128
        for item in versions.values()
    ):
        raise L4SessionSafetyError("L4 verification evidence versions are invalid")
    return {
        "sourceHash": source_hash,
        "chapterCount": value["chapterCount"],
        "fragmentCount": value["fragmentCount"],
        "fileSize": file_size,
        "versions": dict(versions),
    }


async def run_l4_session(
    *,
    corpus_root: Path | str,
    relative_file: str,
    environment: Mapping[str, str] | None = None,
    database_name_factory: Callable[[], str] = lambda: f"novel_creator_test_{uuid4().hex}",
    nonce_factory: Callable[[], str] = lambda: uuid4().hex,
    port_reservation_factory: Callable[[], object] = _reserve_port,
    temp_parent: Path | str = _DEFAULT_TEMP_PARENT,
    temp_dir_factory=lambda prefix: tempfile.mkdtemp(
        prefix=Path(prefix).name, dir=Path(prefix).parent
    ),
    prepare=default_prepare,
    start_process=default_start_process,
    process_guard_factory=_default_process_guard_factory,
    wait_for_health=default_wait_for_health,
    wait_for_input=default_wait_for_input,
    verifier=default_verifier,
    scan_logs=default_scan_logs,
    drop=default_drop,
    remove_temp=lambda path: shutil.rmtree(path),
    output: Callable[[str], None] = print,
) -> dict[str, object]:
    source_environment = os.environ if environment is None else environment
    config = _test_config(source_environment)
    database = database_name_factory()
    _assert_disposable_database(database)
    nonce = _validated_nonce(nonce_factory())
    source = _authorized_source(corpus_root, relative_file)
    root = Path(corpus_root).resolve(strict=True)
    source_payload = source.read_bytes()
    source_hash = sha256(source_payload).hexdigest()
    source_text = source_payload.decode("utf-8", errors="replace")
    child_environment = build_test_child_environment(source_environment, database, root)
    sensitive_values = private_scan_values(
        config, database, str(root), source_text,
        "browser-secret-must-not-leak",
        "https://private-provider.example/v1",
    )
    reservations = _acquire_reservations(port_reservation_factory)
    try:
        log_dir, temp_sentinel = _create_owned_temp(
            Path(temp_parent), nonce, "l4", temp_dir_factory
        )
    except BaseException as exc:
        _raise_errors(
            [exc, *_release_reservations(reservations)],
            "M2 L4 temporary setup and reservation cleanup failed",
        )
        raise AssertionError("unreachable")
    child_environment.update({
        "M2_BROWSER_RUN_NONCE": nonce,
        "VITE_API_BASE_URL": f"http://127.0.0.1:{reservations[0].port}/api",
        "PLAYWRIGHT_BASE_URL": f"http://127.0.0.1:{reservations[1].port}",
    })
    node_command = source_environment.get("NODE") or shutil.which("node") or "node"
    children: list[tuple[str, object, object]] = []
    errors: list[BaseException] = []
    released: set[int] = set()
    database_started = False
    remaining_database = 1
    remaining_processes = 0
    remaining_temp_paths = 1
    verification_evidence: dict[str, object] | None = None

    def release_reservation(index: int) -> None:
        if index not in released:
            reservations[index].release()
            released.add(index)

    try:
        database_started = True
        await _bounded_await(
            _await(prepare(database, child_environment, log_dir)), "L4 prepare"
        )
        release_reservation(0)
        backend = start_process(
            "backend", sys.executable,
            ["-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(reservations[0].port)],
            REPOSITORY_ROOT, child_environment, log_dir,
        )
        backend_guard = _attach_process_guard(backend, process_guard_factory)
        children.append(("backend", backend, backend_guard))
        release_reservation(1)
        vite = start_process(
            "vite", node_command,
            [str(FRONTEND_ROOT / "node_modules" / "vite" / "bin" / "vite.js"), "--host", "127.0.0.1", "--port", str(reservations[1].port), "--strictPort"],
            FRONTEND_ROOT, child_environment, log_dir,
        )
        vite_guard = _attach_process_guard(vite, process_guard_factory)
        children.append(("vite", vite, vite_guard))
        await _bounded_await(
            _await(wait_for_health(
                "backend", f"http://127.0.0.1:{reservations[0].port}/api/health", backend,
                expected_nonce=nonce, timeout_seconds=_HEALTH_TIMEOUT_SECONDS,
            )),
            "backend ownership health", _HEALTH_TIMEOUT_SECONDS + 1,
        )
        await _bounded_await(
            _await(wait_for_health(
                "vite", f"http://127.0.0.1:{reservations[1].port}/__m2-browser-owner", vite,
                expected_nonce=nonce, timeout_seconds=_HEALTH_TIMEOUT_SECONDS,
            )),
            "Vite ownership health", _HEALTH_TIMEOUT_SECONDS + 1,
        )
        _assert_services_live(children)
        output(f"url=http://127.0.0.1:{reservations[1].port}")
        _assert_services_live(children)
        await _await(wait_for_input("Complete the L4 UI goal, then press Enter: "))
        _assert_services_live(children)
        raw_verification = await _bounded_await(
            _await(verifier(database, source_hash, child_environment, log_dir)),
            "L4 verifier",
        )
        _assert_services_live(children)
        verification_evidence = _sanitize_l4_verification(
            raw_verification, source_hash, len(source_payload)
        )
    except BaseException as exc:
        errors.append(exc)
    finally:
        for index in range(len(reservations)):
            try:
                release_reservation(index)
            except BaseException as exc:
                errors.append(exc)
        for _label, child, guard in reversed(children):
            errors.extend(_stop_process(child, guard=guard))
        remaining_processes = sum(
            1 for _label, child, _guard in children
            if callable(getattr(child, "poll", None)) and child.poll() is None
        )
        if database_started:
            try:
                await _bounded_await(
                    _await(drop(database, child_environment, log_dir)), "L4 drop"
                )
                remaining_database = 0
            except BaseException as exc:
                errors.append(exc)
        try:
            matches = scan_logs(log_dir, sensitive_values)
            if matches:
                errors.append(RuntimeError(f"L4 log sensitive match count was {matches}"))
        except BaseException as exc:
            errors.append(exc)
        try:
            _validate_owned_temp(
                log_dir, Path(temp_parent), nonce, "l4", temp_sentinel
            )
            remove_temp(log_dir)
            remaining_temp_paths = 0
        except BaseException as exc:
            errors.append(exc)
        child_environment.clear()
        sensitive_values.clear()
    _raise_errors(errors, "M2 L4 session body and cleanup failed")
    if verification_evidence is None:
        raise L4SessionSafetyError("L4 verification evidence is missing")
    receipt = {
        "database": database,
        "sourceHash": source_hash,
        "verification": verification_evidence,
        "remaining_database": remaining_database,
        "remaining_processes": remaining_processes,
        "remaining_temp_paths": remaining_temp_paths,
    }
    output(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--relative-file", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return_code = asyncio.run(
            run_l4_session(corpus_root=args.corpus_root, relative_file=args.relative_file)
        )
        return 0 if return_code is not None else 1
    except BaseException:
        print("M2 L4 session failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
