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
import socket
import subprocess
import sys
import tempfile
import time
from typing import Callable, Mapping, Sequence
from urllib.parse import quote
from urllib.request import urlopen
from uuid import uuid4


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = REPOSITORY_ROOT / "frontend"
_DISPOSABLE_DATABASE = re.compile(r"novel_creator_test_[a-f0-9]{32}\Z")
_REQUIRED_TEST_VARIABLES = (
    "TEST_MYSQL_HOST",
    "TEST_MYSQL_PORT",
    "TEST_MYSQL_USER",
    "TEST_MYSQL_PASSWORD",
)


class L4SessionSafetyError(RuntimeError):
    """The L4 session is not provably disposable and private."""


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


def _authorized_source(corpus_root: Path | str, relative_file: str) -> Path:
    root = Path(corpus_root).resolve()
    relative_posix = PurePosixPath(relative_file)
    relative_windows = PureWindowsPath(relative_file)
    if (
        not root.is_absolute()
        or not isinstance(relative_file, str)
        or not relative_file
        or relative_posix.is_absolute()
        or relative_windows.is_absolute()
        or bool(relative_windows.drive)
        or ".." in relative_posix.parts
        or ".." in relative_windows.parts
    ):
        raise L4SessionSafetyError("L4 authorized corpus path is invalid")
    source = (root / relative_file).resolve()
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise L4SessionSafetyError("L4 authorized corpus must remain under its root") from exc
    if not source.is_file():
        raise L4SessionSafetyError("L4 authorized corpus file does not exist")
    return source


def build_test_child_environment(
    environment: Mapping[str, str], database: str, corpus_root: Path,
) -> dict[str, str]:
    config = _test_config(environment)
    _assert_disposable_database(database)
    clean = {
        key: value for key, value in environment.items()
        if not key.startswith("MYSQL_")
    }
    return {
        **clean,
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


def _reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def default_start_process(label, command, args, cwd, env, log_dir):
    log_dir = Path(log_dir)
    stdout_handle = (log_dir / f"{label}.stdout.log").open("wb")
    stderr_handle = (log_dir / f"{label}.stderr.log").open("wb")
    try:
        child = subprocess.Popen(
            [command, *args],
            cwd=str(cwd),
            env=dict(env),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            creationflags=_creation_flags(),
        )
    except BaseException:
        stdout_handle.close()
        stderr_handle.close()
        raise
    child._m2_log_handles = (stdout_handle, stderr_handle)  # type: ignore[attr-defined]
    return child


def _run_captured(label: str, command: list[str], cwd: Path, env, log_dir: Path) -> None:
    with (log_dir / f"{label}.stdout.log").open("wb") as stdout_handle, (
        log_dir / f"{label}.stderr.log"
    ).open("wb") as stderr_handle:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            env=dict(env),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            creationflags=_creation_flags(),
            check=False,
        )
    if result.returncode != 0:
        raise RuntimeError(f"{label} command exited with status {result.returncode}")


async def default_prepare(database, env, log_dir):
    await asyncio.to_thread(
        _run_captured,
        "prepare",
        [
            sys.executable, "-m", "backend.scripts.prepare_milestone2_browser_db",
            "--database", database, "--scenario", "settings",
        ],
        REPOSITORY_ROOT,
        env,
        Path(log_dir),
    )


async def default_drop(database, env, log_dir):
    await asyncio.to_thread(
        _run_captured,
        "drop",
        [
            sys.executable, "-m", "backend.scripts.prepare_milestone2_browser_db",
            "--database", database, "--scenario", "settings", "--drop",
        ],
        REPOSITORY_ROOT,
        env,
        Path(log_dir),
    )


async def default_verifier(database, source_hash, env, log_dir):
    await asyncio.to_thread(
        _run_captured,
        "verifier",
        [
            sys.executable, "-m", "backend.scripts.verify_corpus_import",
            "--database", database, "--source-hash", source_hash,
        ],
        REPOSITORY_ROOT,
        env,
        Path(log_dir),
    )
    return {"sourceHash": source_hash}


async def default_wait_for_health(label, url, child):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError(f"{label} process exited before health verification")
        try:
            response = await asyncio.to_thread(urlopen, url, None, 2)
            try:
                if response.status == 200:
                    return
            finally:
                response.close()
        except OSError:
            await asyncio.sleep(0.1)
    raise RuntimeError(f"{label} health verification timed out")


async def default_wait_for_input(prompt):
    await asyncio.to_thread(input, prompt)


def default_scan_logs(log_dir, sensitive_values) -> int:
    match_count = 0
    encoded = tuple(value.encode("utf-8") for value in sensitive_values if value)
    for path in Path(log_dir).glob("*.log"):
        payload = path.read_bytes()
        match_count += sum(payload.count(value) for value in encoded)
    return match_count


def _close_process_logs(child) -> None:
    for handle in getattr(child, "_m2_log_handles", ()):
        handle.flush()
        handle.close()


def _stop_process(child) -> list[BaseException]:
    errors: list[BaseException] = []
    try:
        child.terminate()
    except BaseException as exc:
        errors.append(exc)
    try:
        child.wait(timeout=10)
    except BaseException as exc:
        errors.append(exc)
        try:
            kill = getattr(child, "kill", None)
            if kill is not None:
                kill()
                child.wait(timeout=5)
        except BaseException as forced:
            errors.append(forced)
    try:
        _close_process_logs(child)
    except BaseException as exc:
        errors.append(exc)
    return errors


async def _await(value):
    return await value if inspect.isawaitable(value) else value


def _raise_errors(errors: list[BaseException], message: str) -> None:
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise BaseExceptionGroup(message, errors)


async def run_l4_session(
    *,
    corpus_root: Path | str,
    relative_file: str,
    environment: Mapping[str, str] | None = None,
    database_name_factory: Callable[[], str] = lambda: f"novel_creator_test_{uuid4().hex}",
    temp_dir_factory: Callable[[], Path | str] = lambda: tempfile.mkdtemp(prefix="novel-creator-m2-l4-"),
    prepare=default_prepare,
    start_process=default_start_process,
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
    source = _authorized_source(corpus_root, relative_file)
    root = Path(corpus_root).resolve()
    source_hash = sha256(source.read_bytes()).hexdigest()
    source_text = source.read_text(encoding="utf-8", errors="replace")
    child_environment = build_test_child_environment(source_environment, database, root)
    sensitive_values = private_scan_values(
        config, database, str(root), source_text,
        "browser-secret-must-not-leak",
        "https://private-provider.example/v1",
    )
    backend_port = _reserve_port()
    vite_port = _reserve_port()
    log_dir = Path(temp_dir_factory()).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    child_environment.update({
        "VITE_API_BASE_URL": f"http://127.0.0.1:{backend_port}/api",
        "PLAYWRIGHT_BASE_URL": f"http://127.0.0.1:{vite_port}",
    })
    node_command = source_environment.get("NODE") or shutil.which("node") or "node"
    children: list[tuple[str, object]] = []
    errors: list[BaseException] = []
    database_started = False
    remaining_database = 1
    remaining_processes = 0
    remaining_temp_paths = 1
    try:
        database_started = True
        await _await(prepare(database, child_environment, log_dir))
        backend = start_process(
            "backend", sys.executable,
            ["-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(backend_port)],
            REPOSITORY_ROOT, child_environment, log_dir,
        )
        children.append(("backend", backend))
        vite = start_process(
            "vite", node_command,
            [str(FRONTEND_ROOT / "node_modules" / "vite" / "bin" / "vite.js"), "--host", "127.0.0.1", "--port", str(vite_port), "--strictPort"],
            FRONTEND_ROOT, child_environment, log_dir,
        )
        children.append(("vite", vite))
        await _await(wait_for_health("backend", f"http://127.0.0.1:{backend_port}/api/health", backend))
        await _await(wait_for_health("vite", f"http://127.0.0.1:{vite_port}", vite))
        output(f"url=http://127.0.0.1:{vite_port}")
        await _await(wait_for_input("Complete the L4 UI goal, then press Enter: "))
        await _await(verifier(database, source_hash, child_environment, log_dir))
    except BaseException as exc:
        errors.append(exc)
    finally:
        for _label, child in reversed(children):
            errors.extend(_stop_process(child))
        remaining_processes = 0
        try:
            matches = scan_logs(log_dir, sensitive_values)
            if matches:
                errors.append(RuntimeError(f"L4 log sensitive match count was {matches}"))
        except BaseException as exc:
            errors.append(exc)
        if database_started:
            try:
                await _await(drop(database, child_environment, log_dir))
                remaining_database = 0
            except BaseException as exc:
                errors.append(exc)
        try:
            remove_temp(log_dir)
            remaining_temp_paths = 0
        except BaseException as exc:
            errors.append(exc)
    _raise_errors(errors, "M2 L4 session body and cleanup failed")
    receipt = {
        "database": database,
        "sourceHash": source_hash,
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
