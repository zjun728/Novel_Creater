"""One guarded, backup-first upgrade of the existing v1.13 product database."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from hashlib import sha256
import inspect
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from typing import AsyncContextManager

from backend.domain.market_sources import PACKAGE_VERSION, load_market_source_package
from backend.domain.product_database_readiness import DatabaseInventory
from backend.repositories.market import MarketRepository
from backend.schema_manifest import (
    FRAGMENTS,
    STATEMENT_DELIMITER,
    created_table_names,
    manifest_hash,
    read_fragment_statements,
)
from backend.schema_version import EXPECTED_SCHEMA_VERSION


PRODUCT_DATABASE = "novel_creator_v113"
V113_SCHEMA_VERSION = "writer-core-v1.13.0"
TOPIC_FRAGMENT = "19_topics.sql"
EXPECTED_OLD_TABLE_COUNT = 91
EXPECTED_TOPIC_TABLE_COUNT = 8
EXPECTED_CURRENT_TABLE_COUNT = 99
EXPECTED_MARKET_SOURCE_COUNT = 10
RESTORE_REQUIRED_ERROR = "schema upgrade failed after DDL began; restore required"
RESTORE_MODE = "drop-recreate-clean-target"
RESTORE_GUIDANCE = "drop/recreate target before importing exact backup"
UPGRADE_LOCK_NAME = "writer-core:upgrade:novel_creator_v113:v114"

_HASH = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_BACKUP_NAME = re.compile(r"^phase7b-backup-[0-9a-f]{32}\.sql$", re.ASCII)
_SERVER_84 = re.compile(r"^8\.4\.\d+(?:[-+][0-9A-Za-z][0-9A-Za-z._-]*)?$", re.ASCII)
_METADATA_QUERY = (
    "SELECT schema_version, manifest_hash FROM schema_metadata WHERE singleton_id=1"
)
_SERVER_VERSION_QUERY = "SELECT VERSION() AS version"
_TABLES_QUERY = (
    "SELECT TABLE_NAME FROM information_schema.TABLES "
    "WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"
)
_METADATA_CAS = (
    "UPDATE schema_metadata SET schema_version=%s,manifest_hash=%s,initialized_at=%s "
    "WHERE singleton_id=1 AND schema_version=%s AND manifest_hash=%s"
)


class SchemaUpgradeError(RuntimeError):
    """A fixed, secret-safe refusal before the additive DDL boundary."""


class SchemaUpgradeRestoreRequired(SchemaUpgradeError):
    """The backup must be restored because MySQL DDL may have auto-committed."""

    def __init__(
        self,
        message: str = RESTORE_REQUIRED_ERROR,
        *,
        receipt: UpgradeBackupReceipt | None = None,
    ) -> None:
        super().__init__(message)
        self.receipt = receipt


@dataclass(frozen=True)
class UpgradeInventory:
    database: str
    server_version: str
    schema_version: str | None
    manifest_hash: str | None
    table_names: tuple[str, ...]
    backup_authority: DatabaseInventory | None = field(
        default=None, repr=False, compare=False
    )


@dataclass(frozen=True)
class UpgradeBackupReceipt:
    database: str
    from_schema: str
    backup_path: Path
    backup_sha256: str
    backup_byte_length: int
    restore_mode: str


@dataclass(frozen=True)
class SchemaUpgradeResult:
    database: str
    from_schema: str
    to_schema: str
    added_tables: int
    table_count: int


@dataclass(frozen=True)
class UpgradeVerification:
    database: str
    schema_version: str
    manifest_hash: str
    table_count: int
    package_version: str
    source_count: int


@dataclass(frozen=True)
class ProductUpgradeResult:
    database: str
    backup_filename: str
    backup_sha256: str
    backup_byte_length: int
    from_schema: str
    to_schema: str
    added_tables: int
    table_count: int
    package_version: str
    source_count: int


@dataclass(frozen=True)
class ProductUpgradeDependencies:
    upgrade_lock: Callable[[str], AsyncContextManager[object]]
    inventory: Callable[[str], object]
    create_backup: Callable[..., object]
    verify_backup: Callable[[UpgradeBackupReceipt], object]
    apply_schema: Callable[[str, str, int, Callable[[], None]], object]
    seed_market: Callable[[str], object]
    verify: Callable[[str], object]


def v113_statements() -> tuple[str, ...]:
    """Derive v1.13 from the current manifest by excluding only Topic Center."""
    return tuple(
        statement
        for fragment in FRAGMENTS
        if fragment != TOPIC_FRAGMENT
        for statement in read_fragment_statements(fragment)
    )


def topic_statements() -> tuple[str, ...]:
    return read_fragment_statements(TOPIC_FRAGMENT)


def _table_names(statements: Sequence[str]) -> tuple[str, ...]:
    names: list[str] = []
    pattern = re.compile(
        r"\A(?:\s+|--[^\n]*(?:\n|\Z)|/\*.*?\*/)*CREATE\s+TABLE\s+([A-Za-z0-9_]+)\s*\(",
        re.IGNORECASE | re.DOTALL,
    )
    for statement in statements:
        match = pattern.match(statement)
        if match is not None:
            names.append(match.group(1))
    return tuple(names)


def v113_table_names() -> tuple[str, ...]:
    return _table_names(v113_statements())


def v113_manifest_hash() -> str:
    payload = f"\n{STATEMENT_DELIMITER}\n".join(v113_statements()).encode("utf-8")
    return sha256(payload).hexdigest()


def _validate_static_manifest() -> None:
    if TOPIC_FRAGMENT not in FRAGMENTS:
        raise SchemaUpgradeError("schema upgrade manifest preflight failed")
    if len(v113_table_names()) != EXPECTED_OLD_TABLE_COUNT:
        raise SchemaUpgradeError("schema upgrade manifest preflight failed")
    if len(topic_statements()) != EXPECTED_TOPIC_TABLE_COUNT:
        raise SchemaUpgradeError("schema upgrade manifest preflight failed")
    if len(created_table_names()) != EXPECTED_CURRENT_TABLE_COUNT:
        raise SchemaUpgradeError("schema upgrade manifest preflight failed")
    if set(v113_table_names()) & set(_table_names(topic_statements())):
        raise SchemaUpgradeError("schema upgrade manifest preflight failed")


def _validate_target(database: object, confirm_database: object) -> str:
    if database != PRODUCT_DATABASE or confirm_database != PRODUCT_DATABASE:
        raise SchemaUpgradeError("schema upgrade target preflight failed") from None
    return PRODUCT_DATABASE


def _validate_inventory(
    value: object,
    *,
    current: bool = False,
) -> UpgradeInventory:
    if type(value) is not UpgradeInventory:
        raise SchemaUpgradeError("schema upgrade inventory preflight failed") from None
    expected_version = EXPECTED_SCHEMA_VERSION if current else V113_SCHEMA_VERSION
    expected_hash = manifest_hash() if current else v113_manifest_hash()
    expected_tables = tuple(sorted(created_table_names() if current else v113_table_names()))
    if (
        value.database != PRODUCT_DATABASE
        or _SERVER_84.fullmatch(value.server_version) is None
        or value.schema_version != expected_version
        or value.manifest_hash != expected_hash
        or value.table_names != expected_tables
        or len(value.table_names)
        != (EXPECTED_CURRENT_TABLE_COUNT if current else EXPECTED_OLD_TABLE_COUNT)
    ):
        raise SchemaUpgradeError("schema upgrade inventory preflight failed") from None
    return value


async def _read_session_inventory(session: object, database: str) -> UpgradeInventory:
    try:
        server = await session.fetchone(_SERVER_VERSION_QUERY)  # type: ignore[attr-defined]
        metadata = await session.fetchone(_METADATA_QUERY)  # type: ignore[attr-defined]
        rows = await session.fetchall(_TABLES_QUERY, (database,))  # type: ignore[attr-defined]
        if (
            not isinstance(server, Mapping)
            or set(server) != {"version"}
            or type(server["version"]) is not str
            or not isinstance(metadata, Mapping)
            or set(metadata) != {
            "schema_version",
            "manifest_hash",
            }
        ):
            raise ValueError
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
            raise ValueError
        names: list[str] = []
        for row in rows:
            if not isinstance(row, Mapping) or set(row) != {"TABLE_NAME"}:
                raise ValueError
            name = row["TABLE_NAME"]
            if type(name) is not str or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
                raise ValueError
            names.append(name)
        if tuple(names) != tuple(sorted(set(names))):
            raise ValueError
        return UpgradeInventory(
            database=database,
            server_version=server["version"],
            schema_version=metadata["schema_version"],  # type: ignore[arg-type]
            manifest_hash=metadata["manifest_hash"],  # type: ignore[arg-type]
            table_names=tuple(names),
        )
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        raise SchemaUpgradeError("schema upgrade inventory preflight failed") from None


async def upgrade_v113_to_v114(
    session: object,
    *,
    database: str,
    confirm_database: str,
    now_ms: int,
    on_ddl_started: Callable[[], None] | None = None,
) -> SchemaUpgradeResult:
    """Apply only the eight additive Topic Center statements, then metadata CAS."""
    name = _validate_target(database, confirm_database)
    if type(now_ms) is not int or now_ms <= 0:
        raise SchemaUpgradeError("schema upgrade timestamp preflight failed") from None
    _validate_static_manifest()
    _validate_inventory(await _read_session_inventory(session, name))

    if on_ddl_started is not None:
        on_ddl_started()
    try:
        for statement in topic_statements():
            await session.execute(statement)  # type: ignore[attr-defined]

        rows = await session.fetchall(_TABLES_QUERY, (name,))  # type: ignore[attr-defined]
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
            raise ValueError
        names = tuple(row.get("TABLE_NAME") for row in rows if isinstance(row, Mapping))
        if names != tuple(sorted(created_table_names())):
            raise ValueError

        changed = await session.execute(  # type: ignore[attr-defined]
            _METADATA_CAS,
            (
                EXPECTED_SCHEMA_VERSION,
                manifest_hash(),
                now_ms,
                V113_SCHEMA_VERSION,
                v113_manifest_hash(),
            ),
        )
        if changed != 1:
            raise ValueError
    except BaseException:
        raise SchemaUpgradeRestoreRequired(RESTORE_REQUIRED_ERROR) from None

    return SchemaUpgradeResult(
        database=name,
        from_schema=V113_SCHEMA_VERSION,
        to_schema=EXPECTED_SCHEMA_VERSION,
        added_tables=EXPECTED_TOPIC_TABLE_COUNT,
        table_count=EXPECTED_CURRENT_TABLE_COUNT,
    )


def _validate_backup_receipt(
    value: object,
    *,
    database: str,
    backup_directory: Path,
) -> UpgradeBackupReceipt:
    expected_directory = backup_directory.resolve()
    if (
        type(value) is not UpgradeBackupReceipt
        or value.database != database
        or value.from_schema != V113_SCHEMA_VERSION
        or not isinstance(value.backup_path, Path)
        or not value.backup_path.is_absolute()
        or value.backup_path.parent.resolve() != expected_directory
        or _BACKUP_NAME.fullmatch(value.backup_path.name) is None
        or _HASH.fullmatch(value.backup_sha256) is None
        or type(value.backup_byte_length) is not int
        or value.backup_byte_length <= 0
        or value.restore_mode != RESTORE_MODE
    ):
        raise SchemaUpgradeError("product database backup validation failed") from None
    return value


def _validate_verification(value: object) -> UpgradeVerification:
    if (
        type(value) is not UpgradeVerification
        or value.database != PRODUCT_DATABASE
        or value.schema_version != EXPECTED_SCHEMA_VERSION
        or value.manifest_hash != manifest_hash()
        or value.table_count != EXPECTED_CURRENT_TABLE_COUNT
        or value.package_version != PACKAGE_VERSION
        or value.source_count != EXPECTED_MARKET_SOURCE_COUNT
    ):
        raise SchemaUpgradeRestoreRequired(RESTORE_REQUIRED_ERROR) from None
    return value


async def _invoke(callable_: Callable[..., object], *args: object, **kwargs: object) -> object:
    value = callable_(*args, **kwargs)
    if inspect.isawaitable(value):
        return await value
    return value


async def run_product_upgrade(
    *,
    dependencies: ProductUpgradeDependencies,
    database: str,
    confirm_database: str,
    backup_directory: Path,
    mysqldump: Path,
    mysql: Path,
    now_ms: int,
    receipt_output: Callable[[UpgradeBackupReceipt], object] | None = None,
) -> ProductUpgradeResult:
    """Own the one-way inventory, backup, DDL, metadata, seed and verify order."""
    name = _validate_target(database, confirm_database)
    if type(dependencies) is not ProductUpgradeDependencies:
        raise SchemaUpgradeError("product database upgrade dependencies are invalid")
    if (
        not isinstance(backup_directory, Path)
        or not backup_directory.is_absolute()
        or not isinstance(mysqldump, Path)
        or not mysqldump.is_absolute()
        or not isinstance(mysql, Path)
        or not mysql.is_absolute()
        or mysqldump == mysql
        or type(now_ms) is not int
        or now_ms <= 0
    ):
        raise SchemaUpgradeError("product database upgrade argument preflight failed") from None

    ddl_started = False
    receipt: UpgradeBackupReceipt | None = None

    def mark_ddl_started() -> None:
        nonlocal ddl_started
        ddl_started = True

    try:
        lock_boundary = dependencies.upgrade_lock(name)
        if not hasattr(lock_boundary, "__aenter__") or not hasattr(
            lock_boundary, "__aexit__"
        ):
            raise SchemaUpgradeError("product database upgrade lock failed")
        async with lock_boundary:
            inventory = _validate_inventory(
                await _invoke(dependencies.inventory, name)
            )
            receipt = _validate_backup_receipt(
                await _invoke(
                    dependencies.create_backup,
                    database=name,
                    inventory=inventory,
                    backup_directory=backup_directory,
                    mysqldump=mysqldump,
                    mysql=mysql,
                ),
                database=name,
                backup_directory=backup_directory,
            )
            if receipt_output is not None:
                try:
                    await _invoke(receipt_output, receipt)
                except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                    raise
                except Exception:
                    raise SchemaUpgradeError("backup receipt publication failed") from None

            await _invoke(dependencies.verify_backup, receipt)

            schema_result = await _invoke(
                dependencies.apply_schema,
                name,
                confirm_database,
                now_ms,
                mark_ddl_started,
            )
            # A successful schema dependency return is itself evidence that the
            # additive DDL boundary was crossed, even if a faulty dependency
            # neglected the callback.
            ddl_started = True
            if (
                type(schema_result) is not SchemaUpgradeResult
                or schema_result.database != name
                or schema_result.from_schema != V113_SCHEMA_VERSION
                or schema_result.to_schema != EXPECTED_SCHEMA_VERSION
                or schema_result.added_tables != EXPECTED_TOPIC_TABLE_COUNT
                or schema_result.table_count != EXPECTED_CURRENT_TABLE_COUNT
            ):
                raise ValueError

            market_report = await _invoke(dependencies.seed_market, name)
            if (
                getattr(market_report, "package_version", None) != PACKAGE_VERSION
                or getattr(market_report, "source_count", None)
                != EXPECTED_MARKET_SOURCE_COUNT
            ):
                raise ValueError
            verification = _validate_verification(
                await _invoke(dependencies.verify, name)
            )
    except BaseException as error:
        if ddl_started or isinstance(error, SchemaUpgradeRestoreRequired):
            raise SchemaUpgradeRestoreRequired(receipt=receipt) from None
        if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
            raise
        if isinstance(error, SchemaUpgradeError):
            raise error from None
        raise SchemaUpgradeError("product database upgrade failed") from None

    assert receipt is not None

    return ProductUpgradeResult(
        database=name,
        backup_filename=receipt.backup_path.name,
        backup_sha256=receipt.backup_sha256,
        backup_byte_length=receipt.backup_byte_length,
        from_schema=V113_SCHEMA_VERSION,
        to_schema=EXPECTED_SCHEMA_VERSION,
        added_tables=EXPECTED_TOPIC_TABLE_COUNT,
        table_count=verification.table_count,
        package_version=verification.package_version,
        source_count=verification.source_count,
    )


def format_product_upgrade_result(result: ProductUpgradeResult) -> str:
    return "\n".join(
        (
            f"database={result.database}",
            f"from_schema={result.from_schema}",
            f"to_schema={result.to_schema}",
            f"added_tables={result.added_tables}",
            f"table_count={result.table_count}",
            f"package_version={result.package_version}",
            f"source_count={result.source_count}",
        )
    )


def format_backup_receipt(receipt: UpgradeBackupReceipt) -> str:
    """Render the single recovery authority before any schema write begins."""
    return "\n".join(
        (
            f"backup_receipt.database={receipt.database}",
            f"backup_receipt.from_schema={receipt.from_schema}",
            f"backup_receipt.path={receipt.backup_path}",
            f"backup_receipt.sha256={receipt.backup_sha256}",
            f"backup_receipt.byte_length={receipt.backup_byte_length}",
            f"backup_receipt.restore_mode={receipt.restore_mode}",
            f"backup_receipt.restore_guidance={RESTORE_GUIDANCE}",
        )
    )


def _connection_values(config: Mapping[str, object], database: str) -> dict[str, object]:
    required = ("host", "port", "user", "password", "db")
    if any(key not in config for key in required) or config.get("db") != database:
        raise SchemaUpgradeError("product database configuration preflight failed") from None
    host, port, user, password = (config[key] for key in required[:4])
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
        raise SchemaUpgradeError("product database configuration preflight failed") from None
    return {"host": host, "port": port, "user": user, "password": password}


def _version_runner(path: Path) -> object:
    return subprocess.run(
        [str(path), "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _backup_runner(*args: object, **kwargs: object) -> object:
    return subprocess.run(*args, **kwargs, timeout=1_800)


def _ensure_private_backup_directory(path: Path) -> Path:
    from backend.security.private_files import apply_private_permissions
    from backend.services.product_database_backup import REPOSITORY_ROOT, preflight_backup_directory

    try:
        if path.exists():
            raise ValueError
        parent = path.parent.resolve(strict=True)
        path.mkdir()
        if path.parent.resolve(strict=True) != parent:
            raise ValueError
        apply_private_permissions(path, is_directory=True)
        directory = preflight_backup_directory(path, REPOSITORY_ROOT)
        if any(directory.iterdir()):
            raise ValueError
        return directory
    except BaseException as error:
        if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
            raise
        raise SchemaUpgradeError("backup directory preflight failed") from None


def _inventory_contract(value: object) -> UpgradeInventory:
    try:
        return UpgradeInventory(
            database=value.database,
            server_version=value.server_version,
            schema_version=value.schema_version,
            manifest_hash=value.manifest_hash,
            table_names=value.table_names,
            backup_authority=value if type(value) is DatabaseInventory else None,
        )
    except Exception:
        raise SchemaUpgradeError("schema upgrade inventory preflight failed") from None


def _database_inventory(value: UpgradeInventory) -> DatabaseInventory:
    authority = value.backup_authority
    if (
        type(authority) is not DatabaseInventory
        or authority.database != value.database
        or authority.server_version != value.server_version
        or authority.schema_version != value.schema_version
        or authority.manifest_hash != value.manifest_hash
        or authority.table_names != value.table_names
    ):
        raise SchemaUpgradeError("product database backup authority failed") from None
    return authority


def _default_dependencies(config: Mapping[str, object]) -> ProductUpgradeDependencies:
    import aiomysql

    from backend.database import DatabaseSession
    from backend.services.market_sources import (
        MarketSourceSeedService,
        assert_market_source_package_inventory,
    )
    from backend.services.product_database_backup import (
        REPOSITORY_ROOT,
        create_product_logical_backup,
        preflight_client_pair,
        private_mysql_option_file,
        verify_backup_file,
    )
    from backend.services.product_database_inventory import (
        inventory_database,
    )

    async def close_raw(raw: object) -> None:
        ensure_closed = getattr(raw, "ensure_closed", None)
        if ensure_closed is not None:
            await ensure_closed()
        else:
            raw.close()  # type: ignore[attr-defined]

    @asynccontextmanager
    async def session_scope(database: str):
        connection_config = {
            **_connection_values(config, database),
            "charset": "utf8mb4",
            "autocommit": True,
        }
        raw = await aiomysql.connect(**connection_config)
        try:
            session = DatabaseSession(raw)
            await session.execute(f"USE `{database}`")
            yield session
        finally:
            await close_raw(raw)

    @asynccontextmanager
    async def transaction_scope(database: str):
        connection_config = {
            **_connection_values(config, database),
            "charset": "utf8mb4",
            "autocommit": False,
        }
        raw = await aiomysql.connect(**connection_config)
        session = DatabaseSession(raw)
        try:
            await session.execute(f"USE `{database}`")
            await raw.begin()
            try:
                yield session
            except BaseException:
                await raw.rollback()
                raise
            else:
                await raw.commit()
        finally:
            await close_raw(raw)

    @asynccontextmanager
    async def upgrade_lock(database: str):
        _validate_target(database, database)
        raw = await aiomysql.connect(
            **_connection_values(config, database),
            charset="utf8mb4",
            autocommit=True,
        )
        session = DatabaseSession(raw)
        acquired = False
        primary: BaseException | None = None
        cleanup: list[BaseException] = []
        try:
            row = await session.fetchone(
                "SELECT GET_LOCK(%s, 0) AS acquired", (UPGRADE_LOCK_NAME,)
            )
            if not isinstance(row, Mapping) or row.get("acquired") != 1:
                raise SchemaUpgradeError("product database upgrade lock failed")
            acquired = True
            try:
                yield object()
            except BaseException as error:
                primary = error
        except BaseException as error:
            primary = error
        finally:
            if acquired:
                try:
                    row = await session.fetchone(
                        "SELECT RELEASE_LOCK(%s) AS released", (UPGRADE_LOCK_NAME,)
                    )
                    if not isinstance(row, Mapping) or row.get("released") != 1:
                        raise RuntimeError
                except BaseException as error:
                    cleanup.append(error)
            try:
                await close_raw(raw)
            except BaseException as error:
                cleanup.append(error)
        if primary is not None:
            if cleanup:
                raise BaseExceptionGroup(
                    "product database upgrade lock cleanup failed",
                    [primary, *cleanup],
                ) from None
            raise primary from None
        if cleanup:
            raise SchemaUpgradeError("product database upgrade lock failed") from None

    async def inventory(database: str) -> UpgradeInventory:
        async with session_scope(database) as session:
            return _inventory_contract(await inventory_database(session, database))

    async def create_backup(
        *,
        database: str,
        inventory: UpgradeInventory,
        backup_directory: Path,
        mysqldump: Path,
        mysql: Path,
    ) -> UpgradeBackupReceipt:
        pair = preflight_client_pair(mysqldump, mysql, REPOSITORY_ROOT, _version_runner)
        directory = _ensure_private_backup_directory(backup_directory)
        mysql_config = _connection_values(config, database)
        with private_mysql_option_file(
            mysql_config,
            directory,
            repository_root=REPOSITORY_ROOT,
        ) as option:
            receipt = create_product_logical_backup(
                pair=pair,
                option_file=option,
                source_inventory=_database_inventory(inventory),
                backup_dir=directory,
                backup_filename=f"phase7b-backup-{secrets.token_hex(16)}.sql",
                runner=_backup_runner,
                repository_root=REPOSITORY_ROOT,
            )
        return UpgradeBackupReceipt(
            database=database,
            from_schema=V113_SCHEMA_VERSION,
            backup_path=directory / receipt.backup_filename,
            backup_sha256=receipt.backup_sha256,
            backup_byte_length=receipt.backup_byte_length,
            restore_mode=RESTORE_MODE,
        )

    async def verify_backup(receipt: UpgradeBackupReceipt) -> None:
        verify_backup_file(
            receipt.backup_path,
            receipt.backup_sha256,
            receipt.backup_byte_length,
        )

    async def apply_schema(
        database: str,
        confirmation: str,
        now_ms: int,
        on_ddl_started: Callable[[], None],
    ) -> SchemaUpgradeResult:
        async with session_scope(database) as session:
            return await upgrade_v113_to_v114(
                session,
                database=database,
                confirm_database=confirmation,
                now_ms=now_ms,
                on_ddl_started=on_ddl_started,
            )

    async def seed_market(database: str) -> object:
        package = load_market_source_package(
            Path(__file__).resolve().parents[1]
            / "assets"
            / PACKAGE_VERSION
            / "manifest.json"
        )
        return await MarketSourceSeedService(
            MarketRepository(),
            transaction_factory=lambda: transaction_scope(database),
        ).seed(package)

    async def verify(database: str) -> UpgradeVerification:
        package = load_market_source_package(
            Path(__file__).resolve().parents[1]
            / "assets"
            / PACKAGE_VERSION
            / "manifest.json"
        )
        async with session_scope(database) as session:
            await session.execute("START TRANSACTION READ ONLY")
            try:
                current = _inventory_contract(await inventory_database(session, database))
                _validate_inventory(current, current=True)
                rows = await MarketRepository().list_seed_inventory(session)
                assert_market_source_package_inventory(package, rows)
                await session.execute("COMMIT")
            except BaseException:
                await session.execute("ROLLBACK")
                raise
        return UpgradeVerification(
            database=database,
            schema_version=EXPECTED_SCHEMA_VERSION,
            manifest_hash=manifest_hash(),
            table_count=EXPECTED_CURRENT_TABLE_COUNT,
            package_version=package.package_version,
            source_count=len(package.sources),
        )

    return ProductUpgradeDependencies(
        upgrade_lock=upgrade_lock,
        inventory=inventory,
        create_backup=create_backup,
        verify_backup=verify_backup,
        apply_schema=apply_schema,
        seed_market=seed_market,
        verify=verify,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Upgrade Writer Core v1.13 to v1.14")
    parser.add_argument("--database", required=True)
    parser.add_argument("--confirm-database", required=True)
    parser.add_argument("--backup-directory", required=True)
    parser.add_argument("--mysqldump", required=True)
    parser.add_argument("--mysql", required=True)
    return parser


async def run_cli(
    argv: Sequence[str] | None = None,
    *,
    dependencies: ProductUpgradeDependencies | None = None,
    connection_config: Mapping[str, object] | None = None,
    now_ms: Callable[[], int] | None = None,
    output: Callable[[str], None] = print,
) -> int:
    args = _parser().parse_args(argv)
    database = _validate_target(args.database, args.confirm_database)
    if connection_config is None:
        from backend.config import require_mysql_config

        connection_config = require_mysql_config()
    _connection_values(connection_config, database)
    selected = dependencies or _default_dependencies(connection_config)

    def publish_receipt(receipt: UpgradeBackupReceipt) -> None:
        output(format_backup_receipt(receipt))
        if output is print:
            sys.stdout.flush()

    result = await run_product_upgrade(
        dependencies=selected,
        database=database,
        confirm_database=args.confirm_database,
        backup_directory=Path(args.backup_directory),
        mysqldump=Path(args.mysqldump),
        mysql=Path(args.mysql),
        now_ms=(now_ms or (lambda: int(time.time() * 1000)))(),
        receipt_output=publish_receipt,
    )
    output(format_product_upgrade_result(result))
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
