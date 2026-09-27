"""Backup-first, additive v1.14 -> v1.15 upgrade; never replay market seeds."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import secrets
import sys
import time
from typing import AsyncContextManager

from backend.domain.product_database_readiness import DatabaseInventory
from backend.schema_manifest import STATEMENT_DELIMITER, read_fragment_statements
from backend.scripts.upgrade_product_database_v114 import (
    PRODUCT_DATABASE, V114_SCHEMA_VERSION, V114_MANIFEST_HASH, V114_FRAGMENTS,
    RESTORE_MODE, RESTORE_REQUIRED_ERROR, SchemaUpgradeError,
    SchemaUpgradeRestoreRequired, SchemaUpgradeResult, UpgradeBackupReceipt,
    _BACKUP_NAME, _HASH, _SERVER_84, _METADATA_CAS, _TABLES_QUERY,
    _backup_runner, _connection_values, _ensure_private_backup_directory,
    _invoke, _table_names, _validate_target, _version_runner,
    format_backup_receipt, v114_manifest_hash, v114_table_names,
)


V115_SCHEMA_VERSION = "writer-core-v1.15.0"
V115_MANIFEST_HASH = "652829b3f7357e4b35e896383aa52ab3806dcfc06121368226846f1b4766fe5f"
CONTINUITY_ISSUE_FRAGMENT = "65_continuity_issues.sql"
V115_FRAGMENTS = (*V114_FRAGMENTS[:12], CONTINUITY_ISSUE_FRAGMENT, *V114_FRAGMENTS[12:])
# information_schema inventory of the fixed manifests on disposable MySQL 8.4.
# Schema names are normalized by inventory_database; no product data is encoded.
V114_STRUCTURAL_FINGERPRINT = "0a0fb066cf3718ad0030ad711d45b129426f2d58aa7f0c61e92c8a875c2bc0ca"
V115_STRUCTURAL_FINGERPRINT = "523f41b5ce0370420013e7d117ae5bacdf443db896beadbc24dacb95c8b357d5"
UPGRADE_LOCK_NAME = "writer-core:upgrade:novel_creator_v113:v115"
_UNMANAGED_OBJECT_QUERIES = (
    "SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=%s",
    "SELECT ROUTINE_NAME FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=%s",
    "SELECT EVENT_NAME FROM information_schema.EVENTS WHERE EVENT_SCHEMA=%s",
)


@dataclass(frozen=True)
class ProductUpgradeDependencies:
    upgrade_lock: Callable[[str], AsyncContextManager[object]]
    inventory: Callable[[str], object]
    create_backup: Callable[..., object]
    verify_backup: Callable[[UpgradeBackupReceipt], object]
    apply_schema: Callable[[str, str, int, Callable[[], None]], object]
    verify: Callable[[str], object]


@dataclass(frozen=True)
class ProductUpgradeResult:
    database: str
    from_schema: str
    to_schema: str
    added_tables: int
    table_count: int
    backup_receipt: UpgradeBackupReceipt


def continuity_issue_statements() -> tuple[str, ...]:
    return read_fragment_statements(CONTINUITY_ISSUE_FRAGMENT)


def v115_statements() -> tuple[str, ...]:
    return tuple(statement for fragment in V115_FRAGMENTS
                 for statement in read_fragment_statements(fragment))


def v115_table_names() -> tuple[str, ...]:
    return _table_names(v115_statements())


def v115_manifest_hash() -> str:
    return sha256(f"\n{STATEMENT_DELIMITER}\n".join(v115_statements()).encode("utf-8")).hexdigest()


def _validate_static_manifest() -> None:
    if (
        v114_manifest_hash() != V114_MANIFEST_HASH
        or v115_manifest_hash() != V115_MANIFEST_HASH
        or len(v114_table_names()) != 99
        or len(v115_table_names()) != 100
        or len(continuity_issue_statements()) != 1
        or _table_names(continuity_issue_statements()) != ("continuity_issues",)
        or set(v115_table_names()) != set(v114_table_names()) | {"continuity_issues"}
    ):
        raise SchemaUpgradeError("historical schema manifest changed")


def _validate_inventory(value: object, *, current: bool = False) -> DatabaseInventory:
    if (
        type(value) is not DatabaseInventory
        or value.database != PRODUCT_DATABASE
        or _SERVER_84.fullmatch(value.server_version) is None
        or value.schema_version != (V115_SCHEMA_VERSION if current else V114_SCHEMA_VERSION)
        or value.manifest_hash != (V115_MANIFEST_HASH if current else V114_MANIFEST_HASH)
        or value.structural_fingerprint != (
            V115_STRUCTURAL_FINGERPRINT if current else V114_STRUCTURAL_FINGERPRINT
        )
        or value.table_names != tuple(sorted(v115_table_names() if current else v114_table_names()))
    ):
        raise SchemaUpgradeError("schema upgrade inventory preflight failed")
    return value


def _validate_backup_receipt(value: object, directory: Path) -> UpgradeBackupReceipt:
    if (
        type(value) is not UpgradeBackupReceipt
        or value.database != PRODUCT_DATABASE or value.from_schema != V114_SCHEMA_VERSION
        or not isinstance(value.backup_path, Path) or not value.backup_path.is_absolute()
        or value.backup_path.parent.resolve() != directory.resolve()
        or _BACKUP_NAME.fullmatch(value.backup_path.name) is None
        or type(value.backup_sha256) is not str or _HASH.fullmatch(value.backup_sha256) is None
        or type(value.backup_byte_length) is not int or value.backup_byte_length <= 0
        or value.restore_mode != RESTORE_MODE
    ):
        raise SchemaUpgradeError("product database backup validation failed")
    return value


async def _read_inventory(session: object, database: str) -> DatabaseInventory:
    from backend.services.product_database_inventory import inventory_database

    # The fixed manifests contain none of these executable objects. The shared
    # table fingerprint omits them; a metadata trigger could otherwise write
    # author data during the seemingly metadata-only CAS.
    for query in _UNMANAGED_OBJECT_QUERIES:
        rows = await session.fetchall(query, (database,))
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or rows:
            raise SchemaUpgradeError("schema upgrade unmanaged objects preflight failed")
    return await inventory_database(session, database)


async def upgrade_v114_to_v115(
    session: object, *, database: str, confirm_database: str, now_ms: int,
    on_ddl_started: Callable[[], None] | None = None,
) -> SchemaUpgradeResult:
    """Verify the real source structure, add one table, then compare-and-set metadata."""
    name = _validate_target(database, confirm_database)
    if type(now_ms) is not int or now_ms <= 0:
        raise SchemaUpgradeError("schema upgrade timestamp preflight failed")
    _validate_static_manifest()
    _validate_inventory(await _read_inventory(session, name))
    if on_ddl_started is not None:
        on_ddl_started()
    try:
        await session.execute(continuity_issue_statements()[0])
        rows = await session.fetchall(_TABLES_QUERY, (name,))
        if tuple(row["TABLE_NAME"] for row in rows) != tuple(sorted(v115_table_names())):
            raise ValueError
        changed = await session.execute(_METADATA_CAS, (
            V115_SCHEMA_VERSION, V115_MANIFEST_HASH, now_ms,
            V114_SCHEMA_VERSION, V114_MANIFEST_HASH,
        ))
        if changed != 1:
            raise ValueError
        _validate_inventory(await _read_inventory(session, name), current=True)
    except BaseException:
        raise SchemaUpgradeRestoreRequired() from None
    return SchemaUpgradeResult(name, V114_SCHEMA_VERSION, V115_SCHEMA_VERSION, 1, 100)


async def run_product_upgrade(
    *, dependencies: ProductUpgradeDependencies, database: str, confirm_database: str,
    backup_directory: Path, mysqldump: Path, mysql: Path, now_ms: int,
    receipt_output: Callable[[UpgradeBackupReceipt], object] | None = None,
) -> ProductUpgradeResult:
    """One lock owns inventory -> private backup -> receipt -> DDL -> verification."""
    name = _validate_target(database, confirm_database)
    _validate_static_manifest()
    if (
        type(dependencies) is not ProductUpgradeDependencies
        or any(not isinstance(path, Path) or not path.is_absolute()
               for path in (backup_directory, mysqldump, mysql))
        or mysqldump == mysql or type(now_ms) is not int or now_ms <= 0
    ):
        raise SchemaUpgradeError("product database upgrade argument preflight failed")
    ddl_started = False
    receipt = None

    def mark_ddl_started():
        nonlocal ddl_started
        ddl_started = True

    try:
        async with dependencies.upgrade_lock(name):
            before = _validate_inventory(await _invoke(dependencies.inventory, name))
            receipt = _validate_backup_receipt(await _invoke(
                dependencies.create_backup, database=name, inventory=before,
                backup_directory=backup_directory, mysqldump=mysqldump, mysql=mysql,
            ), backup_directory)
            if receipt_output is not None:
                await _invoke(receipt_output, receipt)
            await _invoke(dependencies.verify_backup, receipt)
            result = await _invoke(dependencies.apply_schema, name, confirm_database, now_ms, mark_ddl_started)
            ddl_started = True
            if type(result) is not SchemaUpgradeResult or result != SchemaUpgradeResult(
                name, V114_SCHEMA_VERSION, V115_SCHEMA_VERSION, 1, 100
            ):
                raise ValueError
            after = _validate_inventory(await _invoke(dependencies.verify, name), current=True)
            expected_counts = tuple(sorted((*before.row_counts, ("continuity_issues", 0))))
            if after.row_counts != expected_counts or after.server_version != before.server_version:
                raise ValueError
    except BaseException as error:
        if ddl_started or isinstance(error, SchemaUpgradeRestoreRequired):
            raise SchemaUpgradeRestoreRequired(receipt=receipt) from None
        if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
            raise
        if isinstance(error, SchemaUpgradeError):
            raise error from None
        raise SchemaUpgradeError("product database upgrade failed") from None
    return ProductUpgradeResult(name, V114_SCHEMA_VERSION, V115_SCHEMA_VERSION, 1, 100, receipt)


def _default_dependencies(config: Mapping[str, object]) -> ProductUpgradeDependencies:
    import aiomysql
    from backend.config import LOCAL_CONFIG_PATH
    from backend.database import DatabaseSession
    from backend.services.product_database_lifecycle_lock import product_database_lifecycle_lock
    from backend.services.product_database_backup import (
        REPOSITORY_ROOT, create_product_logical_backup, preflight_client_pair,
        private_mysql_option_file, verify_backup_file,
    )

    active = None

    @asynccontextmanager
    async def upgrade_lock(database):
        nonlocal active
        _validate_target(database, database)
        primary = None
        # Capture the body exception so the lifecycle lock's public error
        # sanitizer does not discard the exact post-DDL recovery receipt.
        with product_database_lifecycle_lock(LOCAL_CONFIG_PATH):
            raw = None
            acquired = False
            try:
                raw = await aiomysql.connect(**_connection_values(config, database),
                                            db=database, charset="utf8mb4", autocommit=True)
                active = DatabaseSession(raw)
                row = await active.fetchone("SELECT GET_LOCK(%s, 0) AS acquired", (UPGRADE_LOCK_NAME,))
                if not isinstance(row, Mapping) or row.get("acquired") != 1:
                    raise SchemaUpgradeError("product database upgrade lock failed")
                acquired = True
                yield active
            except BaseException as error:
                primary = error
            finally:
                cleanup_failed = False
                if acquired:
                    try:
                        row = await active.fetchone("SELECT RELEASE_LOCK(%s) AS released", (UPGRADE_LOCK_NAME,))
                        if not isinstance(row, Mapping) or row.get("released") != 1:
                            raise ValueError
                    except BaseException:
                        cleanup_failed = True
                active = None
                if raw is not None:
                    try:
                        await raw.ensure_closed()
                    except BaseException:
                        cleanup_failed = True
                if primary is None and cleanup_failed:
                    primary = SchemaUpgradeError("product database upgrade lock cleanup failed")
        if primary is not None:
            raise primary from None

    async def inventory(database):
        if active is None:
            raise SchemaUpgradeError("product database upgrade lock failed")
        return await _read_inventory(active, database)

    async def create_backup(*, database, inventory, backup_directory, mysqldump, mysql):
        pair = preflight_client_pair(mysqldump, mysql, REPOSITORY_ROOT, _version_runner)
        directory = _ensure_private_backup_directory(backup_directory)
        with private_mysql_option_file(_connection_values(config, database), directory,
                                       repository_root=REPOSITORY_ROOT) as option:
            backup = create_product_logical_backup(
                pair=pair, option_file=option, source_inventory=inventory,
                backup_dir=directory, backup_filename=f"phase7b-backup-{secrets.token_hex(16)}.sql",
                runner=_backup_runner, repository_root=REPOSITORY_ROOT,
            )
        return UpgradeBackupReceipt(database, V114_SCHEMA_VERSION,
                                    directory / backup.backup_filename,
                                    backup.backup_sha256, backup.backup_byte_length, RESTORE_MODE)

    async def verify_backup(receipt):
        verify_backup_file(receipt.backup_path, receipt.backup_sha256, receipt.backup_byte_length)

    async def apply_schema(database, confirmation, now_ms, callback):
        if active is None:
            raise SchemaUpgradeError("product database upgrade lock failed")
        owner = await active.fetchone(
            "SELECT IS_USED_LOCK(%s) = CONNECTION_ID() AS owned", (UPGRADE_LOCK_NAME,)
        )
        if not isinstance(owner, Mapping) or owner.get("owned") != 1:
            raise SchemaUpgradeError("product database upgrade lock failed")
        return await upgrade_v114_to_v115(active, database=database,
                                         confirm_database=confirmation, now_ms=now_ms,
                                         on_ddl_started=callback)

    return ProductUpgradeDependencies(upgrade_lock, inventory, create_backup,
                                      verify_backup, apply_schema, inventory)


async def run_cli(
    argv: Sequence[str] | None = None, *, dependencies: ProductUpgradeDependencies | None = None,
    connection_config: Mapping[str, object] | None = None,
    now_ms: Callable[[], int] | None = None, output: Callable[[str], None] = print,
) -> int:
    parser = argparse.ArgumentParser(description="Upgrade Writer Core v1.14 to v1.15 without rebuilding")
    for argument in ("database", "confirm-database", "backup-directory", "mysqldump", "mysql"):
        parser.add_argument("--" + argument, required=True)
    args = parser.parse_args(argv)
    database = _validate_target(args.database, args.confirm_database)
    if connection_config is None:
        from backend.config import require_mysql_config
        connection_config = require_mysql_config()
    _connection_values(connection_config, database)

    def publish_receipt(receipt):
        output(format_backup_receipt(receipt))
        if output is print:
            sys.stdout.flush()

    result = await run_product_upgrade(
        dependencies=dependencies or _default_dependencies(connection_config),
        database=database, confirm_database=args.confirm_database,
        backup_directory=Path(args.backup_directory), mysqldump=Path(args.mysqldump),
        mysql=Path(args.mysql), now_ms=(now_ms or (lambda: int(time.time() * 1000)))(),
        receipt_output=publish_receipt,
    )
    output("\n".join(f"{key}={getattr(result, key)}" for key in
                     ("database", "from_schema", "to_schema", "added_tables", "table_count")))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(run_cli(argv))
    except SchemaUpgradeRestoreRequired:
        print(RESTORE_REQUIRED_ERROR, file=sys.stderr)
        return 1
    except Exception:
        print("product database upgrade failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
