"""Captured manual product session for corpus import or the single L5 call."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Callable, Mapping, Sequence
from uuid import uuid4

from backend.scripts.run_milestone2_l4_session import (
    FRONTEND_ROOT,
    REPOSITORY_ROOT,
    _await,
    _raise_errors,
    _reserve_port,
    _stop_process,
    default_scan_logs,
    default_start_process,
    default_wait_for_health,
    default_wait_for_input,
    private_scan_values,
)


PRODUCT_DATABASE = "novel_creator"
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_MODES = frozenset({"corpus-import", "provider-l5"})


class ProductSessionSafetyError(RuntimeError):
    """The product session target or closed goal is invalid."""


async def _default_sensitive_loader(config, database):
    from backend.scripts.verify_milestone2_product import _default_connection

    session = await _default_connection({**config, "db": database, "autocommit": True})
    try:
        rows = await session.fetchall(
            "SELECT base_url,api_key FROM provider_profiles ORDER BY id"
        )
    finally:
        await session.close()
    return {
        str(value)
        for row in rows
        for value in (row.get("base_url"), row.get("api_key"))
        if isinstance(value, str) and value
    }


async def _default_verifier(config, database, source_hash, flags, _environment, _log_dir):
    from backend.scripts.verify_corpus_import import build_receipt
    from backend.scripts.verify_milestone2_product import (
        _default_connection,
        verify_milestone2_product,
    )

    session = await _default_connection({**config, "db": database, "autocommit": True})
    try:
        corpus = await build_receipt(session, source_hash=source_hash)
        product = await verify_milestone2_product(session, **flags)
    finally:
        await session.close()
    return {"corpus": corpus, "product": product}


def _product_child_environment(
    environment: Mapping[str, str], config: Mapping[str, object], database: str,
) -> dict[str, str]:
    clean = {key: value for key, value in environment.items() if not key.startswith("MYSQL_")}
    return {
        **clean,
        "MYSQL_HOST": str(config["host"]),
        "MYSQL_PORT": str(config["port"]),
        "MYSQL_USER": str(config["user"]),
        "MYSQL_PASSWORD": str(config["password"]),
        "MYSQL_DB": database,
    }


async def run_product_session(
    *,
    mode: str,
    database: str,
    confirm_product: str,
    source_hash: str,
    connection_config: Mapping[str, object] | None = None,
    environment: Mapping[str, str] | None = None,
    temp_dir_factory=lambda: tempfile.mkdtemp(prefix="novel-creator-m2-product-"),
    sensitive_loader=None,
    start_process=default_start_process,
    wait_for_health=default_wait_for_health,
    wait_for_input=default_wait_for_input,
    verifier=None,
    scan_logs=default_scan_logs,
    remove_temp=lambda path: shutil.rmtree(path),
    output: Callable[[str], None] = print,
) -> dict[str, object]:
    if mode not in _MODES:
        raise ProductSessionSafetyError("Product session mode is not in the closed goal list")
    if database != PRODUCT_DATABASE:
        raise ProductSessionSafetyError("Product session database must be novel_creator")
    if confirm_product != database:
        raise ProductSessionSafetyError("Product database confirmation does not match")
    if not isinstance(source_hash, str) or _HASH.fullmatch(source_hash) is None:
        raise ProductSessionSafetyError("Product session source hash must be lowercase SHA-256")
    if connection_config is None:
        from backend.config import require_mysql_config

        connection_config = require_mysql_config()
    if connection_config.get("db") != database:
        raise ProductSessionSafetyError("The configured database does not match the product target")
    for key in ("host", "port", "user", "password"):
        if connection_config.get(key) in (None, ""):
            raise ProductSessionSafetyError("Product database configuration is incomplete")
    source_environment = os.environ if environment is None else environment
    corpus_root = source_environment.get("CORPUS_ROOT")
    if not corpus_root:
        raise ProductSessionSafetyError("CORPUS_ROOT is required for product evidence")
    child_environment = _product_child_environment(
        source_environment, connection_config, database
    )
    selected_loader = sensitive_loader or _default_sensitive_loader
    selected_verifier = verifier
    if selected_verifier is None:
        async def selected_verifier(database, source_hash, flags, environment, log_dir):
            return await _default_verifier(
                connection_config, database, source_hash, flags, environment, log_dir
            )
    loaded = await _await(selected_loader(connection_config, database))
    sensitive_values = private_scan_values(
        connection_config, database, str(corpus_root), *tuple(loaded)
    )
    backend_port = _reserve_port()
    vite_port = _reserve_port()
    log_dir = Path(temp_dir_factory()).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    session_id = uuid4().hex
    child_environment.update({
        "VITE_API_BASE_URL": f"http://127.0.0.1:{backend_port}/api",
        "PLAYWRIGHT_BASE_URL": f"http://127.0.0.1:{vite_port}",
    })
    node_command = source_environment.get("NODE") or shutil.which("node") or "node"
    flags = {
        "require_assets": True,
        "require_corpus": True,
        "require_l5": mode == "provider-l5",
    }
    children = []
    errors: list[BaseException] = []
    remaining_processes = 0
    remaining_temp_paths = 1
    try:
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
        output(f"session_id={session_id}")
        await _await(wait_for_input("Complete the product UI goal, then press Enter: "))
        await _await(selected_verifier(
            database, source_hash, flags, child_environment, log_dir
        ))
    except BaseException as exc:
        errors.append(exc)
    finally:
        for _label, child in reversed(children):
            errors.extend(_stop_process(child))
        remaining_processes = 0
        try:
            matches = scan_logs(log_dir, sensitive_values)
            if matches:
                errors.append(RuntimeError(
                    f"Product session log sensitive match count was {matches}"
                ))
        except BaseException as exc:
            errors.append(exc)
        try:
            remove_temp(log_dir)
            remaining_temp_paths = 0
        except BaseException as exc:
            errors.append(exc)
    _raise_errors(errors, "M2 product session body and cleanup failed")
    receipt = {
        "mode": mode,
        "sessionId": session_id,
        "sourceHash": source_hash,
        "remaining_processes": remaining_processes,
        "remaining_temp_paths": remaining_temp_paths,
    }
    output(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=sorted(_MODES))
    parser.add_argument("--database", required=True)
    parser.add_argument("--confirm-product", required=True)
    parser.add_argument("--source-hash", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        asyncio.run(run_product_session(
            mode=args.mode,
            database=args.database,
            confirm_product=args.confirm_product,
            source_hash=args.source_hash,
        ))
        return 0
    except BaseException:
        print("M2 product session failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
