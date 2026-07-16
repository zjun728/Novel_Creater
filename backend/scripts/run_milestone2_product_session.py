"""Captured manual product session for corpus import or the single L5 call."""

from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import sys
import tempfile
from typing import Callable, Mapping, Sequence
from uuid import uuid4

from backend.scripts.run_milestone2_l4_session import (
    FRONTEND_ROOT,
    REPOSITORY_ROOT,
    _DEFAULT_TEMP_PARENT,
    _HEALTH_TIMEOUT_SECONDS,
    L4SessionSafetyError,
    _acquire_reservations,
    _attach_process_guard,
    _assert_services_live,
    _await,
    _bounded_await,
    _create_owned_temp,
    _default_process_guard_factory,
    _minimal_inherited_environment,
    _raise_errors,
    _release_reservations,
    _reserve_port,
    _stop_process,
    _validate_owned_temp,
    _validated_nonce,
    default_scan_logs,
    default_start_process,
    default_wait_for_health,
    default_wait_for_input,
    private_scan_values,
)


PRODUCT_DATABASE = "novel_creator"
PRODUCT_HOST = "127.0.0.1"
PRODUCT_PORT = 3307
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_MODES = frozenset({"corpus-import", "provider-l5"})
_FORBIDDEN_RECEIPT_KEYS = frozenset({
    "apikey", "baseurl", "dsn", "notes", "thinking", "body", "content",
    "contentjson", "mergedstylejson", "rawresponse", "rawcontent", "password",
})
_PRODUCT_BASE_KEYS = frozenset({"schemaVersion", "manifestHash", "project", "assets", "corpus"})
_PROJECT_KEYS = frozenset({
    "id", "title", "seedCount", "selectedSeedId", "selectedSeedTitle",
    "providerCount", "bindingRevision", "contractRevision", "canonRevision",
    "projectionRevision",
})
_ASSET_KEYS = frozenset({"packageVersion", "packageHash", "styleCount", "cardCount"})
_OUTER_CORPUS_KEYS = frozenset({
    "sourceHash", "chapterCount", "fragmentCount", "fileSize", "versions",
})
_PRODUCT_CORPUS_KEYS = frozenset({
    "sourceId", "sourceRevision", "relativePath", "sourceHash", "chapterCount",
    "fragmentCount", "versions",
})
_L5_KEYS = frozenset({
    "batchId", "attemptCount", "optionCount", "selectedEngineOptionId",
    "contractRevision", "creationContractId", "styleContractId", "requestHash",
    "attemptId", "rawResponseHash", "options", "creationHash", "styleHash",
    "referenceManifestHash",
})
_OPTION_KEYS = frozenset({"id", "option_order", "content_hash"})


class ProductSessionSafetyError(RuntimeError):
    """The product session target or closed goal is invalid."""


async def _default_endpoint_identity_loader(config, database):
    from backend.scripts.verify_milestone2_product import _default_connection

    session = await _default_connection({**config, "db": database, "autocommit": True})
    try:
        row = await session.fetchone(
            "SELECT DATABASE() AS database_name,@@port AS server_port"
        )
    finally:
        await session.close()
    if row is None:
        raise ProductSessionSafetyError("Product endpoint identity was unavailable")
    return {"database": row.get("database_name"), "port": row.get("server_port")}


def _secret_fingerprint(rows: list[dict[str, object]]) -> str:
    public = [
        {
            "baseUrlHash": sha256(str(row.get("base_url", "")).encode("utf-8")).hexdigest(),
            "apiKeyHash": sha256(str(row.get("api_key", "")).encode("utf-8")).hexdigest(),
        }
        for row in rows
    ]
    payload = json.dumps(public, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(payload).hexdigest()


async def _default_sensitive_loader(config, database):
    from backend.scripts.verify_milestone2_product import _default_connection

    session = await _default_connection({**config, "db": database, "autocommit": True})
    try:
        rows = await session.fetchall(
            "SELECT base_url,api_key FROM provider_profiles ORDER BY id"
        )
    finally:
        await session.close()
    scan_values = {
        str(value)
        for row in rows
        for value in (row.get("base_url"), row.get("api_key"))
        if isinstance(value, str) and value
    }
    return {
        "scanValues": scan_values,
        "providerFingerprint": _secret_fingerprint(rows),
        "providerCount": len(rows),
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
        product = await verify_milestone2_product(
            session,
            expected_database=database,
            expected_source_hash=source_hash,
            **flags,
        )
    finally:
        await session.close()
    corpus_evidence = {
        "sourceHash": corpus.get("rawHash"),
        "chapterCount": corpus.get("chapterCount"),
        "fragmentCount": corpus.get("fragmentCount"),
        "fileSize": corpus.get("size"),
        "versions": {
            "parser": corpus.get("parserVersion"),
            "normalizer": corpus.get("normalizerVersion"),
            "fragmenter": corpus.get("fragmenterVersion"),
            "index": corpus.get("indexVersion"),
        },
    }
    return {"corpus": corpus_evidence, "product": product}


def _product_child_environment(
    environment: Mapping[str, str], config: Mapping[str, object], database: str,
) -> dict[str, str]:
    return {
        **_minimal_inherited_environment(environment),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "MYSQL_HOST": str(config["host"]),
        "MYSQL_PORT": str(config["port"]),
        "MYSQL_USER": str(config["user"]),
        "MYSQL_PASSWORD": str(config["password"]),
        "MYSQL_DB": database,
        "CORPUS_ROOT": str(environment["CORPUS_ROOT"]),
    }


def _normalize_sensitive_snapshot(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != {
        "scanValues", "providerFingerprint", "providerCount"
    }:
        raise ProductSessionSafetyError("Provider secret snapshot was invalid")
    raw_values = value.get("scanValues")
    fingerprint = value.get("providerFingerprint")
    count = value.get("providerCount")
    if (
        not isinstance(raw_values, (set, frozenset, list, tuple))
        or any(not isinstance(item, str) for item in raw_values)
        or not isinstance(fingerprint, str)
        or _HASH.fullmatch(fingerprint) is None
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count < 0
    ):
        raise ProductSessionSafetyError("Provider secret snapshot was invalid")
    scan_values = {item for item in raw_values if item}
    if (
        (count == 0) != (not scan_values)
        or (count > 0 and not count <= len(scan_values) <= count * 2)
    ):
        raise ProductSessionSafetyError(
            "Provider secret snapshot count did not match its normalized values"
        )
    return {
        "scanValues": scan_values,
        "providerFingerprint": fingerprint,
        "providerCount": count,
    }


def _key_token(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _assert_bounded_public_value(value: object, *, depth: int = 0) -> None:
    if depth > 6:
        raise ProductSessionSafetyError("Product verification evidence exceeded its depth bound")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > 10**12:
            raise ProductSessionSafetyError("Product verification evidence integer was unbounded")
        return
    if isinstance(value, str):
        if len(value) > 512:
            raise ProductSessionSafetyError("Product verification evidence string was unbounded")
        return
    if isinstance(value, list):
        if len(value) > 16:
            raise ProductSessionSafetyError("Product verification evidence list was unbounded")
        for item in value:
            _assert_bounded_public_value(item, depth=depth + 1)
        return
    if isinstance(value, Mapping):
        if len(value) > 32:
            raise ProductSessionSafetyError("Product verification evidence object was unbounded")
        for key, item in value.items():
            if not isinstance(key, str) or _key_token(key) in _FORBIDDEN_RECEIPT_KEYS:
                raise ProductSessionSafetyError("Product verification evidence contained a forbidden field")
            _assert_bounded_public_value(item, depth=depth + 1)
        return
    raise ProductSessionSafetyError("Product verification evidence contained an unsupported value")


def _assert_allowed_keys(value: object, allowed: frozenset[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != allowed:
        raise ProductSessionSafetyError(f"Product verification {label} is not allowlisted")
    return value


def _require_public_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ProductSessionSafetyError(f"Product verification {label} is invalid")
    return value


def _require_canonical_relative_path(value: object) -> str:
    relative_path = _require_public_string(value, "corpus.relativePath")
    posix = PurePosixPath(relative_path)
    windows = PureWindowsPath(relative_path)
    raw_parts = relative_path.split("/")
    if (
        "\\" in relative_path
        or relative_path in {".", ""}
        or posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or any(part in {"", ".", ".."} for part in raw_parts)
        or posix.as_posix() != relative_path
    ):
        raise ProductSessionSafetyError(
            "Product verification corpus.relativePath is not canonical and relative"
        )
    return relative_path


def _require_hash(value: object, label: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise ProductSessionSafetyError(f"Product verification {label} is invalid")
    return value


def _require_count(value: object, label: str, *, positive: bool = False) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < (1 if positive else 0)
    ):
        raise ProductSessionSafetyError(f"Product verification {label} is invalid")
    return value


def _exact_versions(value: object, label: str) -> dict[str, str]:
    versions = _assert_allowed_keys(
        value,
        frozenset({"parser", "normalizer", "fragmenter", "index"}),
        label,
    )
    return {
        key: _require_public_string(versions[key], f"{label}.{key}")
        for key in ("parser", "normalizer", "fragmenter", "index")
    }


def _sanitize_product_verification(
    value: object, source_hash: str, mode: str,
) -> dict[str, object]:
    _assert_bounded_public_value(value)
    top = _assert_allowed_keys(value, frozenset({"corpus", "product"}), "receipt")
    corpus = _assert_allowed_keys(
        top["corpus"], _OUTER_CORPUS_KEYS, "corpus evidence"
    )
    if corpus["sourceHash"] != source_hash:
        raise ProductSessionSafetyError("Product verification sourceHash does not match")
    _require_hash(corpus["sourceHash"], "sourceHash")
    chapter_count = _require_count(
        corpus["chapterCount"], "chapterCount", positive=True
    )
    fragment_count = _require_count(
        corpus["fragmentCount"], "fragmentCount", positive=True
    )
    _require_count(corpus["fileSize"], "fileSize", positive=True)
    versions = _exact_versions(corpus["versions"], "corpus versions")
    expected_product_keys = (
        _PRODUCT_BASE_KEYS | {"l5"}
        if mode == "provider-l5"
        else _PRODUCT_BASE_KEYS
    )
    raw_product = top["product"]
    if isinstance(raw_product, Mapping) and (
        ("l5" in raw_product) != (mode == "provider-l5")
    ):
        raise ProductSessionSafetyError(
            "Product verification evidence does not match the closed session mode"
        )
    product = _assert_allowed_keys(
        raw_product, frozenset(expected_product_keys), "product evidence"
    )
    if product["schemaVersion"] != "writer-core-v1.1.0":
        raise ProductSessionSafetyError("Product verification schemaVersion is invalid")
    _require_hash(product["manifestHash"], "manifestHash")
    project = _assert_allowed_keys(product["project"], _PROJECT_KEYS, "project evidence")
    for key in ("id", "selectedSeedId"):
        _require_public_string(project[key], f"project.{key}")
    if project["title"] != "永乐大典" or project["selectedSeedTitle"] != "典镇山河":
        raise ProductSessionSafetyError("Product verification project identity is invalid")
    expected_contract_revision = 1 if mode == "provider-l5" else 0
    expected_project_values = {
        "seedCount": 3,
        "providerCount": 2,
        "bindingRevision": 1,
        "contractRevision": expected_contract_revision,
        "canonRevision": 0,
        "projectionRevision": 0,
    }
    if any(project[key] != expected for key, expected in expected_project_values.items()):
        raise ProductSessionSafetyError("Product verification project counts are invalid")
    assets = _assert_allowed_keys(product["assets"], _ASSET_KEYS, "asset evidence")
    if (
        assets["packageVersion"] != "writer-core-v1.1.0"
        or assets["styleCount"] != 10
        or assets["cardCount"] != 64
    ):
        raise ProductSessionSafetyError("Product verification asset counts are invalid")
    _require_hash(assets["packageHash"], "assets.packageHash")
    product_corpus = _assert_allowed_keys(
        product["corpus"], _PRODUCT_CORPUS_KEYS, "nested corpus evidence"
    )
    _require_public_string(product_corpus["sourceId"], "corpus.sourceId")
    _require_count(product_corpus["sourceRevision"], "corpus.sourceRevision", positive=True)
    _require_canonical_relative_path(product_corpus["relativePath"])
    if (
        product_corpus["sourceHash"] != source_hash
        or product_corpus["chapterCount"] != chapter_count
        or product_corpus["fragmentCount"] != fragment_count
        or _exact_versions(product_corpus["versions"], "nested corpus versions") != versions
    ):
        raise ProductSessionSafetyError(
            "Product verification nested corpus evidence does not match"
        )
    _require_hash(product_corpus["sourceHash"], "nested corpus sourceHash")
    if mode == "provider-l5":
        l5 = _assert_allowed_keys(product["l5"], _L5_KEYS, "L5 evidence")
        for key in (
            "batchId", "attemptId", "selectedEngineOptionId", "creationContractId",
            "styleContractId",
        ):
            _require_public_string(l5[key], f"l5.{key}")
        for key in (
            "requestHash", "rawResponseHash", "creationHash", "styleHash",
            "referenceManifestHash",
        ):
            _require_hash(l5[key], f"l5.{key}")
        if (
            l5["attemptCount"] != 1
            or l5["optionCount"] != 3
            or l5["contractRevision"] != 1
        ):
            raise ProductSessionSafetyError("Product verification L5 counts are invalid")
        options = l5["options"]
        if not isinstance(options, list) or len(options) != 3:
            raise ProductSessionSafetyError("Product verification L5 options are invalid")
        option_ids: list[str] = []
        option_hashes: list[str] = []
        option_orders: list[int] = []
        for option in options:
            row = _assert_allowed_keys(option, _OPTION_KEYS, "L5 option evidence")
            option_ids.append(_require_public_string(row["id"], "l5.option.id"))
            option_hashes.append(_require_hash(row["content_hash"], "l5.option.contentHash"))
            option_orders.append(_require_count(row["option_order"], "l5.option.order", positive=True))
        if (
            option_orders != [1, 2, 3]
            or len(set(option_ids)) != 3
            or len(set(option_hashes)) != 3
            or l5["selectedEngineOptionId"] not in option_ids
        ):
            raise ProductSessionSafetyError("Product verification L5 option order is invalid")
    # JSON round-trip creates a detached, plain allowlisted copy.
    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _validate_product_authority(
    database: str,
    confirm_product: str,
    confirm_host: str,
    confirm_port: int,
    config: Mapping[str, object],
) -> None:
    if database != PRODUCT_DATABASE:
        raise ProductSessionSafetyError("Product session database must be novel_creator")
    if confirm_product != database:
        raise ProductSessionSafetyError("Product database confirmation does not match")
    configured_host = str(config.get("host", "")).strip().lower()
    if configured_host != PRODUCT_HOST:
        raise ProductSessionSafetyError("Product database host must be canonical loopback 127.0.0.1")
    try:
        configured_port = int(config.get("port"))
    except (TypeError, ValueError) as exc:
        raise ProductSessionSafetyError("Product database port must be 3307") from exc
    if configured_port != PRODUCT_PORT:
        raise ProductSessionSafetyError("Product database port must be 3307")
    if confirm_host != PRODUCT_HOST:
        raise ProductSessionSafetyError("Product host confirmation must be exactly 127.0.0.1")
    if confirm_port != PRODUCT_PORT:
        raise ProductSessionSafetyError("Product port confirmation must be exactly 3307")
    if config.get("db") != database:
        raise ProductSessionSafetyError("The configured database does not match the product target")
    for key in ("host", "port", "user", "password"):
        if config.get(key) in (None, ""):
            raise ProductSessionSafetyError("Product database configuration is incomplete")


def _validate_endpoint_identity(identity: object, database: str) -> None:
    if not isinstance(identity, Mapping):
        raise ProductSessionSafetyError("Product endpoint identity was invalid")
    if identity.get("database") != database:
        raise ProductSessionSafetyError("Product connected database identity did not match")
    try:
        port = int(identity.get("port"))
    except (TypeError, ValueError) as exc:
        raise ProductSessionSafetyError("Product connected port identity was invalid") from exc
    if port != PRODUCT_PORT:
        raise ProductSessionSafetyError("Product connected port identity did not match 3307")


async def run_product_session(
    *,
    mode: str,
    database: str,
    confirm_product: str,
    confirm_host: str,
    confirm_port: int,
    source_hash: str,
    connection_config: Mapping[str, object] | None = None,
    environment: Mapping[str, str] | None = None,
    nonce_factory: Callable[[], str] = lambda: uuid4().hex,
    port_reservation_factory: Callable[[], object] = _reserve_port,
    temp_parent: Path | str = _DEFAULT_TEMP_PARENT,
    temp_dir_factory=lambda prefix: tempfile.mkdtemp(
        prefix=Path(prefix).name, dir=Path(prefix).parent
    ),
    endpoint_identity_loader=None,
    sensitive_loader=None,
    start_process=default_start_process,
    process_guard_factory=_default_process_guard_factory,
    wait_for_health=default_wait_for_health,
    wait_for_input=default_wait_for_input,
    verifier=None,
    scan_logs=default_scan_logs,
    remove_temp=lambda path: shutil.rmtree(path),
    output: Callable[[str], None] = print,
) -> dict[str, object]:
    if mode not in _MODES:
        raise ProductSessionSafetyError("Product session mode is not in the closed goal list")
    if not isinstance(source_hash, str) or _HASH.fullmatch(source_hash) is None:
        raise ProductSessionSafetyError("Product session source hash must be lowercase SHA-256")
    if connection_config is None:
        from backend.config import require_mysql_config

        connection_config = require_mysql_config()
    _validate_product_authority(
        database, confirm_product, confirm_host, confirm_port, connection_config
    )
    source_environment = os.environ if environment is None else environment
    corpus_root = source_environment.get("CORPUS_ROOT")
    if not corpus_root:
        raise ProductSessionSafetyError("CORPUS_ROOT is required for product evidence")
    selected_identity_loader = endpoint_identity_loader or _default_endpoint_identity_loader
    identity = await _bounded_await(
        _await(selected_identity_loader(connection_config, database)),
        "Product endpoint identity",
    )
    _validate_endpoint_identity(identity, database)
    selected_loader = sensitive_loader or _default_sensitive_loader
    selected_verifier = verifier
    if selected_verifier is None:
        async def selected_verifier(database, source_hash, flags, environment, log_dir):
            return await _default_verifier(
                connection_config, database, source_hash, flags, environment, log_dir
            )
    pre_snapshot = _normalize_sensitive_snapshot(await _bounded_await(
        _await(selected_loader(connection_config, database)), "Product pre-secret snapshot"
    ))
    sensitive_values = private_scan_values(
        connection_config,
        database,
        str(corpus_root),
        *tuple(pre_snapshot["scanValues"]),
    )
    nonce = _validated_nonce(nonce_factory())
    try:
        reservations = _acquire_reservations(port_reservation_factory)
    except L4SessionSafetyError as exc:
        raise ProductSessionSafetyError(
            "Product session port reservations are invalid"
        ) from exc
    try:
        log_dir, temp_sentinel = _create_owned_temp(
            Path(temp_parent), nonce, "product", temp_dir_factory
        )
    except L4SessionSafetyError as exc:
        cleanup_errors = _release_reservations(reservations)
        if cleanup_errors:
            _raise_errors(
                [exc, *cleanup_errors],
                "Product temporary setup and reservation cleanup failed",
            )
        raise ProductSessionSafetyError(
            "Refusing an unowned temporary product-session path"
        ) from exc
    except BaseException as exc:
        _raise_errors(
            [exc, *_release_reservations(reservations)],
            "Product temporary setup and reservation cleanup failed",
        )
        raise AssertionError("unreachable")
    child_environment = _product_child_environment(
        source_environment, connection_config, database
    )
    child_environment.update({
        "M2_BROWSER_RUN_NONCE": nonce,
        "VITE_API_BASE_URL": f"http://127.0.0.1:{reservations[0].port}/api",
        "PLAYWRIGHT_BASE_URL": f"http://127.0.0.1:{reservations[1].port}",
    })
    node_command = source_environment.get("NODE") or shutil.which("node") or "node"
    flags = {
        "require_assets": True,
        "require_corpus": True,
        "require_l5": mode == "provider-l5",
    }
    children: list[tuple[str, object, object]] = []
    errors: list[BaseException] = []
    released: set[int] = set()
    remaining_processes = 0
    remaining_temp_paths = 1
    verification_evidence: dict[str, object] | None = None
    post_snapshot: dict[str, object] | None = None

    def release_reservation(index: int) -> None:
        if index not in released:
            reservations[index].release()
            released.add(index)

    try:
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
            "Product backend ownership health", _HEALTH_TIMEOUT_SECONDS + 1,
        )
        await _bounded_await(
            _await(wait_for_health(
                "vite", f"http://127.0.0.1:{reservations[1].port}/__m2-browser-owner", vite,
                expected_nonce=nonce, timeout_seconds=_HEALTH_TIMEOUT_SECONDS,
            )),
            "Product Vite ownership health", _HEALTH_TIMEOUT_SECONDS + 1,
        )
        _assert_services_live(children)
        output(f"url=http://127.0.0.1:{reservations[1].port}")
        output(f"session_id={nonce}")
        _assert_services_live(children)
        await _await(wait_for_input("Complete the product UI goal, then press Enter: "))
        _assert_services_live(children)
        raw_verification = await _bounded_await(
            _await(selected_verifier(
                database, source_hash, flags, child_environment, log_dir
            )),
            "Product verifier",
        )
        _assert_services_live(children)
        verification_evidence = _sanitize_product_verification(
            raw_verification, source_hash, mode
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
        try:
            post_snapshot = _normalize_sensitive_snapshot(await _bounded_await(
                _await(selected_loader(connection_config, database)),
                "Product post-secret snapshot",
            ))
            sensitive_values.update(post_snapshot["scanValues"])
            if (
                post_snapshot["providerFingerprint"] != pre_snapshot["providerFingerprint"]
                or post_snapshot["providerCount"] != pre_snapshot["providerCount"]
            ):
                errors.append(ProductSessionSafetyError(
                    "Product Provider fingerprint changed during the closed session"
                ))
        except BaseException as exc:
            errors.append(exc)
        try:
            matches = scan_logs(log_dir, sensitive_values)
            if matches:
                errors.append(RuntimeError(
                    f"Product session log sensitive match count was {matches}"
                ))
        except BaseException as exc:
            errors.append(exc)
        try:
            _validate_owned_temp(
                log_dir, Path(temp_parent), nonce, "product", temp_sentinel
            )
            remove_temp(log_dir)
            remaining_temp_paths = 0
        except BaseException as exc:
            errors.append(exc)
        child_environment.clear()
        sensitive_values.clear()
        pre_snapshot["scanValues"].clear()
        if post_snapshot is not None:
            post_snapshot["scanValues"].clear()
    _raise_errors(errors, "M2 product session body and cleanup failed")
    if verification_evidence is None or post_snapshot is None:
        raise ProductSessionSafetyError("Product verification evidence is missing")
    receipt = {
        "mode": mode,
        "sessionId": nonce,
        "sourceHash": source_hash,
        "verification": verification_evidence,
        "providerSecretState": {
            "fingerprint": post_snapshot["providerFingerprint"],
            "count": post_snapshot["providerCount"],
        },
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
    parser.add_argument("--confirm-host", required=True)
    parser.add_argument("--confirm-port", required=True, type=int)
    parser.add_argument("--source-hash", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        asyncio.run(run_product_session(
            mode=args.mode,
            database=args.database,
            confirm_product=args.confirm_product,
            confirm_host=args.confirm_host,
            confirm_port=args.confirm_port,
            source_hash=args.source_hash,
        ))
        return 0
    except BaseException:
        print("M2 product session failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
