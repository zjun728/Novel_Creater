from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
from types import SimpleNamespace

import pytest

from backend.domain.assets import load_asset_package
from backend.domain.market_sources import load_market_source_package
from backend.domain.product_database_readiness import LEGACY_DATABASE, NEW_DATABASE
from backend.repositories.assets import AssetRepository
from backend.repositories.market import MarketRepository
from backend.schema_manifest import created_table_names, manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from backend.scripts.seed_market_sources import MANIFEST_PATH as MARKET_MANIFEST
from backend.scripts.seed_writer_assets import MANIFEST_PATH as ASSET_MANIFEST
from backend.scripts.prepare_product_database import new_database_boundary
import backend.scripts.prepare_product_database as preparation_command
from backend.services.product_database_backup import (
    ProductDatabaseBackupError,
    create_logical_backup,
    preflight_client_pair,
    private_mysql_option_file,
    restore_logical_backup,
)
from backend.services.product_database_inventory import (
    assert_inventory_equal,
    inventory_database,
)
from backend.services.assets import AssetSeedService
from backend.services.market_sources import MarketSourceSeedService
from backend.tests.support.disposable_mysql import (
    _open_admin_session,
    assert_disposable_name,
    disposable_mysql_database,
    test_server_config as _test_server_config,
    transaction_factory_for,
)


pytestmark = [pytest.mark.mysql, pytest.mark.asyncio]
_CLIENT_SKIP = "Phase 7B MySQL 8.4 clients are not configured"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_RESTORE_NAME = re.compile(r"novel_creator_phase7b_restore_[0-9a-f]{32}")


class _LogicalDatabaseSession:
    """Expose one owned physical schema under an immutable contract name."""

    def __init__(self, session, physical: str, logical: str) -> None:
        self._session = session
        self._physical = physical
        self._logical = logical

    def _sql(self, sql: str) -> str:
        return sql.replace(f"`{self._logical}`", f"`{self._physical}`")

    def _params(self, params):
        if params is None:
            return None
        return tuple(self._physical if value == self._logical else value for value in params)

    def _rows(self, value):
        if value is None:
            return None
        if isinstance(value, list):
            return [self._rows(row) for row in value]
        if isinstance(value, dict):
            return {
                key: self._logical if item == self._physical else item
                for key, item in value.items()
            }
        return value

    async def execute(self, sql, params=None):
        return await self._session.execute(self._sql(sql), self._params(params))

    async def fetchone(self, sql, params=None):
        return self._rows(
            await self._session.fetchone(self._sql(sql), self._params(params))
        )

    async def fetchall(self, sql, params=None):
        return self._rows(
            await self._session.fetchall(self._sql(sql), self._params(params))
        )

    async def close(self):
        return await self._session.close()


def _owned_external_directory() -> Path:
    return Path(tempfile.mkdtemp(prefix="novel_creator_phase7b_mysql_"))


def _remove_owned_external_directory(path: Path) -> None:
    resolved = path.resolve(strict=True)
    expected_parent = Path(tempfile.gettempdir()).resolve(strict=True)
    if resolved.parent != expected_parent or not resolved.name.startswith(
        "novel_creator_phase7b_mysql_"
    ):
        raise RuntimeError("refusing non-owned integration directory cleanup")
    shutil.rmtree(resolved)


async def _create_synthetic_legacy(session) -> None:
    await session.execute(
        """CREATE TABLE schema_metadata (
               singleton_id TINYINT NOT NULL PRIMARY KEY,
               schema_version VARCHAR(64) NOT NULL,
               manifest_hash CHAR(64) NOT NULL,
               initialized_at BIGINT NOT NULL,
               CONSTRAINT chk_schema_singleton CHECK (singleton_id = 1)
           ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"""
    )
    await session.execute(
        """CREATE TABLE legacy_parent (
               id BIGINT NOT NULL PRIMARY KEY,
               label VARCHAR(64) NOT NULL,
               CONSTRAINT chk_parent_label CHECK (CHAR_LENGTH(label) > 0),
               INDEX idx_parent_label (label)
           ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"""
    )
    await session.execute(
        """CREATE TABLE legacy_child (
               id BIGINT NOT NULL PRIMARY KEY,
               parent_id BIGINT NOT NULL,
               amount INT NOT NULL,
               CONSTRAINT chk_child_amount CHECK (amount >= 0),
               CONSTRAINT fk_child_parent FOREIGN KEY (parent_id)
                   REFERENCES legacy_parent(id),
               INDEX idx_child_parent_amount (parent_id, amount)
           ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"""
    )
    await session.execute(
        "INSERT INTO schema_metadata VALUES (1,%s,%s,%s)",
        ("legacy-synthetic", "a" * 64, 1_720_000_000_000),
    )
    await session.execute("INSERT INTO legacy_parent VALUES (1,'synthetic-parent')")
    await session.execute("INSERT INTO legacy_child VALUES (1,1,7)")


def _process_runner_for_source(physical_source: str):
    def runner(command, **kwargs):
        safe_command = list(command)
        if safe_command and safe_command[-1] == LEGACY_DATABASE:
            safe_command[-1] = physical_source
        return subprocess.run(safe_command, **kwargs)

    return runner


@asynccontextmanager
async def _legacy_backup_environment(pair):
    external = _owned_external_directory()
    try:
        async with disposable_mysql_database(initialize_schema=False) as source:
            await _create_synthetic_legacy(source.session)
            logical = _LogicalDatabaseSession(
                source.session, source.database_name, LEGACY_DATABASE
            )
            before = await inventory_database(logical, LEGACY_DATABASE)
            config = _test_server_config()
            option_config = {
                key: config[key] for key in ("host", "port", "user", "password")
            }
            with private_mysql_option_file(
                option_config,
                external,
                repository_root=_REPOSITORY_ROOT,
            ) as option_file:
                receipt = create_logical_backup(
                    pair,
                    option_file,
                    before,
                    external,
                    "synthetic-failure-proof.sql",
                    "0" * 64,
                    _process_runner_for_source(source.database_name),
                    repository_root=_REPOSITORY_ROOT,
                )
                yield SimpleNamespace(
                    source=source,
                    logical_source=logical,
                    before=before,
                    external=external,
                    option_file=option_file,
                    receipt=receipt,
                    backup_path=external / receipt.backup_filename,
                )
    finally:
        _remove_owned_external_directory(external)


@asynccontextmanager
async def _owned_restore_database(admin_session):
    name = f"novel_creator_phase7b_restore_{secrets.token_hex(16)}"
    if _RESTORE_NAME.fullmatch(name) is None:
        raise RuntimeError("invalid owned restore name")
    await admin_session.execute(
        f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 "
        "COLLATE utf8mb4_0900_ai_ci"
    )
    primary: BaseException | None = None
    try:
        yield name
    except BaseException as error:
        primary = error
    cleanup: BaseException | None = None
    try:
        if _RESTORE_NAME.fullmatch(name) is None:
            raise RuntimeError("refusing non-owned restore cleanup")
        exists = await admin_session.fetchone(
            "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s",
            (name,),
        )
        if exists is not None:
            await admin_session.execute(f"DROP DATABASE `{name}`")
        remaining = await admin_session.fetchone(
            "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s",
            (name,),
        )
        if remaining is not None:
            raise RuntimeError("owned restore database cleanup did not finish")
    except BaseException as error:
        cleanup = error
    _raise_test_primary_and_cleanup(primary, cleanup)


async def _database_exists_by_name(name: str) -> bool:
    admin = await _open_admin_session(_test_server_config())
    try:
        row = await admin.fetchone(
            "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s",
            (name,),
        )
        return row is not None
    finally:
        await admin.close()


async def _cleanup_exact_owned_database(name: str) -> bool:
    if _RESTORE_NAME.fullmatch(name) is None:
        assert_disposable_name(name)
    admin = await _open_admin_session(_test_server_config())
    try:
        row = await admin.fetchone(
            "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s",
            (name,),
        )
        existed = row is not None
        if existed:
            if _RESTORE_NAME.fullmatch(name) is None:
                assert_disposable_name(name)
            await admin.execute(f"DROP DATABASE `{name}`")
        remaining = await admin.fetchone(
            "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s",
            (name,),
        )
        if remaining is not None:
            raise RuntimeError("owned database cleanup did not finish")
        return existed
    finally:
        await admin.close()


def _raise_test_primary_and_cleanup(
    primary: BaseException | None,
    cleanup: BaseException | None,
) -> None:
    if primary is not None and cleanup is not None:
        raise BaseExceptionGroup(
            "integration assertion and owned cleanup both failed",
            [primary, cleanup],
        ) from None
    if primary is not None:
        raise primary from None
    if cleanup is not None:
        raise cleanup from None


@pytest.fixture(scope="session", autouse=True)
def phase7b_mysql_clients():
    dump_value = os.environ.get("TEST_MYSQLDUMP_84")
    mysql_value = os.environ.get("TEST_MYSQL_84")
    if dump_value is None or mysql_value is None:
        pytest.skip(_CLIENT_SKIP)
    dump = Path(dump_value)
    mysql = Path(mysql_value)
    if not dump.is_absolute() or not mysql.is_absolute():
        pytest.fail("Phase 7B MySQL client paths must be absolute")
    if not dump.is_file() or not mysql.is_file():
        pytest.fail("Phase 7B MySQL client paths must be regular files")

    def version_runner(path: Path):
        return subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            check=False,
        )

    return preflight_client_pair(dump, mysql, _REPOSITORY_ROOT, version_runner)


async def test_dump_restore_preserves_exact_synthetic_legacy_inventory(
    phase7b_mysql_clients,
):
    created: list[str] = []
    cleaned: list[str] = []
    external = _owned_external_directory()
    restore_name = f"novel_creator_phase7b_restore_{secrets.token_hex(16)}"
    assert _RESTORE_NAME.fullmatch(restore_name)
    try:
        async with disposable_mysql_database(
            initialize_schema=False,
            on_created=created.append,
            on_cleaned=cleaned.append,
        ) as source:
            assert_disposable_name(source.database_name)
            await _create_synthetic_legacy(source.session)
            logical_source = _LogicalDatabaseSession(
                source.session, source.database_name, LEGACY_DATABASE
            )
            before = await inventory_database(logical_source, LEGACY_DATABASE)
            runner = _process_runner_for_source(source.database_name)
            config = _test_server_config()
            option_config = {
                key: config[key] for key in ("host", "port", "user", "password")
            }
            with private_mysql_option_file(
                option_config,
                external,
                repository_root=_REPOSITORY_ROOT,
            ) as option_file:
                receipt = create_logical_backup(
                    phase7b_mysql_clients,
                    option_file,
                    before,
                    external,
                    "synthetic-legacy.sql",
                    "0" * 64,
                    runner,
                    repository_root=_REPOSITORY_ROOT,
                )
                backup_path = external / receipt.backup_filename
                assert backup_path.is_file() and backup_path.stat().st_size > 0

                await source.admin_session.execute(
                    f"CREATE DATABASE `{restore_name}` CHARACTER SET utf8mb4 "
                    "COLLATE utf8mb4_0900_ai_ci"
                )
                created.append(restore_name)
                try:
                    restore_logical_backup(
                        phase7b_mysql_clients,
                        option_file,
                        backup_path,
                        receipt.backup_sha256,
                        receipt.backup_byte_length,
                        restore_name,
                    )
                    restored = await inventory_database(source.admin_session, restore_name)
                    assert_inventory_equal(before, restored)
                    after = await inventory_database(logical_source, LEGACY_DATABASE)
                    assert_inventory_equal(before, after)
                finally:
                    if _RESTORE_NAME.fullmatch(restore_name) is None:
                        raise RuntimeError("refusing non-owned restore cleanup")
                    exists = await source.admin_session.fetchone(
                        "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
                        "WHERE SCHEMA_NAME=%s",
                        (restore_name,),
                    )
                    if exists is not None:
                        await source.admin_session.execute(
                            f"DROP DATABASE `{restore_name}`"
                        )
                        cleaned.append(restore_name)
        assert len(created) == 2
        assert len(cleaned) == 2
        assert set(created) == set(cleaned)
        assert len(set(created) - set(cleaned)) == 0
    finally:
        _remove_owned_external_directory(external)


async def test_current_bootstrap_and_official_seed_replay_are_exact():
    async with disposable_mysql_database() as current:
        transaction = transaction_factory_for(current.connection_config)
        asset_package = load_asset_package(ASSET_MANIFEST, mode="release")
        market_package = load_market_source_package(MARKET_MANIFEST)
        asset_service = AssetSeedService(
            AssetRepository(), transaction_factory=transaction
        )
        market_service = MarketSourceSeedService(
            MarketRepository(), transaction_factory=transaction
        )

        first_assets = await asset_service.seed(asset_package)
        first_market = await market_service.seed(market_package)
        replay_assets = await asset_service.seed(asset_package)
        replay_market = await market_service.seed(market_package)

        assert (
            first_assets.style_count,
            first_assets.card_count,
            first_assets.inserted,
            first_assets.replayed,
            first_assets.advanced,
        ) == (10, 64, 74, 0, 0)
        assert (
            replay_assets.inserted,
            replay_assets.replayed,
            replay_assets.advanced,
        ) == (0, 74, 0)
        assert (
            first_market.source_count,
            first_market.inserted,
            first_market.replayed,
        ) == (2, 2, 0)
        assert (replay_market.inserted, replay_market.replayed) == (0, 2)

        logical = _LogicalDatabaseSession(
            current.session, current.database_name, NEW_DATABASE
        )
        observed = await inventory_database(logical, NEW_DATABASE)
        assert observed.schema_version == EXPECTED_SCHEMA_VERSION
        assert observed.manifest_hash == manifest_hash()
        assert observed.table_names == tuple(sorted(created_table_names()))
        assert len(observed.table_names) == 91
        counts = dict(observed.row_counts)
        assert {
            name: counts[name]
            for name in (
                "style_templates",
                "style_template_heads",
                "experience_cards",
                "experience_card_heads",
                "market_sources",
                "market_source_policy_revisions",
                "market_source_policy_heads",
                "market_source_refresh_states",
            )
        } == {
            "style_templates": 10,
            "style_template_heads": 10,
            "experience_cards": 64,
            "experience_card_heads": 64,
            "market_sources": 2,
            "market_source_policy_revisions": 2,
            "market_source_policy_heads": 2,
            "market_source_refresh_states": 2,
        }
        official_tables = {
            "schema_metadata",
            "application_settings",
            "style_templates",
            "style_template_heads",
            "experience_cards",
            "experience_card_heads",
            "market_sources",
            "market_source_policy_revisions",
            "market_source_policy_heads",
            "market_source_refresh_states",
        }
        assert counts["schema_metadata"] == 1
        assert counts["application_settings"] == 1
        assert [
            (table, count)
            for table, count in observed.row_counts
            if table not in official_tables and count != 0
        ] == []


async def test_restore_nonzero_keeps_backup_and_source_unchanged(
    phase7b_mysql_clients,
):
    async with _legacy_backup_environment(phase7b_mysql_clients) as proof:
        async with _owned_restore_database(proof.source.admin_session) as target:
            with pytest.raises(ProductDatabaseBackupError, match="logical restore failed"):
                restore_logical_backup(
                    phase7b_mysql_clients,
                    proof.option_file,
                    proof.backup_path,
                    proof.receipt.backup_sha256,
                    proof.receipt.backup_byte_length,
                    target,
                    lambda *_args, **_kwargs: SimpleNamespace(returncode=9),
                )
            assert proof.backup_path.is_file()
            after = await inventory_database(proof.logical_source, LEGACY_DATABASE)
            assert_inventory_equal(proof.before, after)


async def test_restore_row_count_mismatch_is_detected(phase7b_mysql_clients):
    async with _legacy_backup_environment(phase7b_mysql_clients) as proof:
        async with _owned_restore_database(proof.source.admin_session) as target:
            restore_logical_backup(
                phase7b_mysql_clients,
                proof.option_file,
                proof.backup_path,
                proof.receipt.backup_sha256,
                proof.receipt.backup_byte_length,
                target,
            )
            await proof.source.admin_session.execute(
                f"INSERT INTO `{target}`.`legacy_parent` VALUES (2,'mismatch')"
            )
            mismatched = await inventory_database(proof.source.admin_session, target)
            with pytest.raises(RuntimeError, match="comparison failed"):
                assert_inventory_equal(proof.before, mismatched)
            assert proof.backup_path.is_file()
            after = await inventory_database(proof.logical_source, LEGACY_DATABASE)
            assert_inventory_equal(proof.before, after)


async def test_partial_target_and_current_run_database_are_cleaned():
    physical = f"novel_creator_test_{secrets.token_hex(16)}"
    assert_disposable_name(physical)
    created: list[str] = []
    cleaned: list[str] = []

    async def session_factory():
        raw = await _open_admin_session(_test_server_config())
        return _LogicalDatabaseSession(raw, physical, NEW_DATABASE)

    async def partial_initialize(session, database, confirm, now_ms):
        assert (database, confirm, now_ms) == (NEW_DATABASE, NEW_DATABASE, 17)
        created.append(physical)
        await session.execute(f"USE `{database}`")
        await session.execute(
            "CREATE TABLE partial_target (id INT PRIMARY KEY) ENGINE=InnoDB"
        )
        raise RuntimeError("injected bootstrap failure")

    boundary = new_database_boundary(
        NEW_DATABASE,
        session_factory=session_factory,
        initialize=partial_initialize,
        inventory=inventory_database,
        now_ms=lambda: 17,
    )
    primary: BaseException | None = None
    try:
        with pytest.raises(RuntimeError, match="new database boundary failed"):
            async with boundary:
                raise AssertionError("unreachable")
        assert not await _database_exists_by_name(physical)
    except BaseException as error:
        primary = error
    cleanup: BaseException | None = None
    try:
        assert_disposable_name(physical)
        await _cleanup_exact_owned_database(physical)
        if created:
            cleaned.append(physical)
    except BaseException as error:
        cleanup = error
    _raise_test_primary_and_cleanup(primary, cleanup)
    assert created == [physical]
    assert cleaned == [physical]
    assert set(created) - set(cleaned) == set()
    assert not await _database_exists_by_name(physical)


async def test_seed_failure_rolls_back_and_audit_failure_is_read_only(monkeypatch):
    class FailingAssetRepository(AssetRepository):
        calls = 0

        async def insert_revision(self, session, asset_type, row):
            self.calls += 1
            if self.calls == 3:
                await session.execute("INSERT INTO phase7b_missing_table VALUES (1)")
            await super().insert_revision(session, asset_type, row)

    async with disposable_mysql_database() as current:
        transaction = transaction_factory_for(current.connection_config)
        assets = load_asset_package(ASSET_MANIFEST, mode="release")
        market = load_market_source_package(MARKET_MANIFEST)
        with pytest.raises(Exception):
            await AssetSeedService(
                FailingAssetRepository(), transaction_factory=transaction
            ).seed(assets)
        for table in (
            "style_templates",
            "style_template_heads",
            "experience_cards",
            "experience_card_heads",
        ):
            row = await current.session.fetchone(f"SELECT COUNT(*) AS count FROM {table}")
            assert row["count"] == 0

        await AssetSeedService(
            AssetRepository(), transaction_factory=transaction
        ).seed(assets)
        await MarketSourceSeedService(
            MarketRepository(), transaction_factory=transaction
        ).seed(market)
        stable_key = assets.styles[0].stable_key
        await current.session.execute(
            "UPDATE style_templates SET name='injected-audit-drift' WHERE stable_key=%s",
            (stable_key,),
        )
        before = await current.session.fetchone(
            "SELECT name,content_hash FROM style_templates WHERE stable_key=%s",
            (stable_key,),
        )

        async def open_alias(_config, database=None):
            raw = await _open_admin_session(_test_server_config())
            alias = _LogicalDatabaseSession(raw, current.database_name, NEW_DATABASE)
            if database is not None:
                await alias.execute(f"USE `{database}`")
            return alias

        monkeypatch.setattr(preparation_command, "_open_default_session", open_alias)
        with pytest.raises(
            RuntimeError, match="product database preparation execution failed"
        ):
            await preparation_command._default_official_audit(
                _test_server_config(), NEW_DATABASE
            )
        after = await current.session.fetchone(
            "SELECT name,content_hash FROM style_templates WHERE stable_key=%s",
            (stable_key,),
        )
        assert after == before


async def test_restore_drop_failure_is_reported_before_manual_owned_cleanup(
    phase7b_mysql_clients, monkeypatch
):
    captured: list[str] = []

    class DropOnceSession:
        def __init__(self, raw) -> None:
            self.raw = raw

        async def execute(self, sql, params=None):
            match = re.fullmatch(
                r"DROP DATABASE `(novel_creator_phase7b_restore_[0-9a-f]{32})`",
                sql,
            )
            if match is not None and not captured:
                captured.append(match.group(1))
                raise RuntimeError("injected restore drop failure")
            return await self.raw.execute(sql, params)

        async def fetchone(self, sql, params=None):
            return await self.raw.fetchone(sql, params)

        async def fetchall(self, sql, params=None):
            return await self.raw.fetchall(sql, params)

        async def close(self):
            return await self.raw.close()

    async def open_drop_once(_config, database=None):
        assert database is None
        return DropOnceSession(await _open_admin_session(_test_server_config()))

    async with _legacy_backup_environment(phase7b_mysql_clients) as proof:
        monkeypatch.setattr(
            preparation_command, "_open_default_session", open_drop_once
        )
        primary: BaseException | None = None
        try:
            with pytest.raises(RuntimeError, match="restore drill cleanup failed"):
                await preparation_command._default_restore_drill(
                    _test_server_config(),
                    phase7b_mysql_clients,
                    proof.option_file,
                    proof.receipt,
                    proof.before,
                    proof.external,
                )
            assert len(captured) == 1
            assert _RESTORE_NAME.fullmatch(captured[0])
            assert await _database_exists_by_name(captured[0])
            assert proof.backup_path.is_file()
            after = await inventory_database(proof.logical_source, LEGACY_DATABASE)
            assert_inventory_equal(proof.before, after)
        except BaseException as error:
            primary = error
        cleanup: BaseException | None = None
        cleaned: list[str] = []
        try:
            if captured:
                target = captured[0]
                if _RESTORE_NAME.fullmatch(target) is None:
                    raise RuntimeError("refusing non-owned restore cleanup")
                await _cleanup_exact_owned_database(target)
                cleaned.append(target)
        except BaseException as error:
            cleanup = error
        _raise_test_primary_and_cleanup(primary, cleanup)
        assert captured == cleaned
        assert set(captured) - set(cleaned) == set()
        assert not await _database_exists_by_name(captured[0])
