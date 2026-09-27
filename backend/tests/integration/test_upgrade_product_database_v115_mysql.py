"""Real MySQL migration proof, always redirected to fixture-owned databases."""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest

from backend.scripts import upgrade_product_database_v115 as upgrade
from backend.scripts.upgrade_product_database_v114 import v114_statements
from backend.services.product_database_inventory import inventory_database
from backend.tests.integration.test_product_database_readiness_mysql import (
    _LogicalDatabaseSession, _owned_external_directory, _remove_owned_external_directory,
)
from backend.tests.support.disposable_mysql import assert_disposable_name


pytestmark = [pytest.mark.mysql, pytest.mark.asyncio]
NOW = 1_800_000_000_000


async def old_database(database):
    for statement in v114_statements():
        await database.session.execute(statement)
    await database.session.execute("INSERT INTO schema_metadata VALUES (1,%s,%s,%s)",
                                   (upgrade.V114_SCHEMA_VERSION, upgrade.V114_MANIFEST_HASH, NOW))
    project_id = str(uuid4())
    await database.session.execute(
        "INSERT INTO projects (id,title,genre,description,target_words,target_chapters,status,created_at,updated_at) "
        "VALUES (%s,'迁移保留项目','奇幻','需要完整保留的作者数据',120000,10,'drafting',%s,%s)",
        (project_id, NOW, NOW),
    )
    logical = _LogicalDatabaseSession(database.session, database.database_name, upgrade.PRODUCT_DATABASE)
    return logical, project_id


async def apply(session, callback=None):
    return await upgrade.upgrade_v114_to_v115(
        session, database=upgrade.PRODUCT_DATABASE, confirm_database=upgrade.PRODUCT_DATABASE,
        now_ms=NOW + 1, on_ddl_started=callback,
    )


async def test_real_incremental_upgrade_preserves_every_old_table_and_author_row(empty_disposable_mysql):
    session, project_id = await old_database(empty_disposable_mysql)
    before = await inventory_database(session, upgrade.PRODUCT_DATABASE)
    original = await session.fetchone("SELECT * FROM projects WHERE id=%s", (project_id,))
    assert before.structural_fingerprint == upgrade.V114_STRUCTURAL_FINGERPRINT
    assert len(before.table_names) == 99
    result = await apply(session)
    after = await inventory_database(session, upgrade.PRODUCT_DATABASE)
    assert result.added_tables == 1 and result.table_count == 100
    assert after.structural_fingerprint == upgrade.V115_STRUCTURAL_FINGERPRINT
    assert after.row_counts == tuple(sorted((*before.row_counts, ("continuity_issues", 0))))
    assert after.schema_version == upgrade.V115_SCHEMA_VERSION
    assert after.manifest_hash == upgrade.V115_MANIFEST_HASH
    assert await session.fetchone("SELECT * FROM projects WHERE id=%s", (project_id,)) == original
    with pytest.raises(upgrade.SchemaUpgradeError):
        await apply(session)


async def test_historical_v114_upgrade_stays_at_99_before_independent_v115(empty_disposable_mysql):
    from backend.scripts.upgrade_product_database_v114 import (
        V113_SCHEMA_VERSION, V113_MANIFEST_HASH, v113_statements, upgrade_v113_to_v114,
    )
    database = empty_disposable_mysql
    for statement in v113_statements():
        await database.session.execute(statement)
    await database.session.execute("INSERT INTO schema_metadata VALUES (1,%s,%s,%s)",
                                   (V113_SCHEMA_VERSION, V113_MANIFEST_HASH, NOW))
    session = _LogicalDatabaseSession(database.session, database.database_name, upgrade.PRODUCT_DATABASE)
    historical = await upgrade_v113_to_v114(
        session, database=upgrade.PRODUCT_DATABASE, confirm_database=upgrade.PRODUCT_DATABASE,
        now_ms=NOW + 1,
    )
    middle = await inventory_database(session, upgrade.PRODUCT_DATABASE)
    assert historical.to_schema == upgrade.V114_SCHEMA_VERSION
    assert historical.added_tables == 8 and historical.table_count == 99
    assert middle.structural_fingerprint == upgrade.V114_STRUCTURAL_FINGERPRINT
    assert middle.manifest_hash == upgrade.V114_MANIFEST_HASH
    assert "continuity_issues" not in middle.table_names
    result = await apply(session)
    assert result.to_schema == upgrade.V115_SCHEMA_VERSION
    assert result.added_tables == 1 and result.table_count == 100


async def test_structure_drift_is_rejected_before_any_new_table(empty_disposable_mysql):
    session, _ = await old_database(empty_disposable_mysql)
    await session.execute("ALTER TABLE projects ADD COLUMN drifted_field INT NULL")
    marks = []
    with pytest.raises(upgrade.SchemaUpgradeError):
        await apply(session, lambda: marks.append("ddl"))
    assert marks == []
    current = await inventory_database(session, upgrade.PRODUCT_DATABASE)
    assert current.schema_version == upgrade.V114_SCHEMA_VERSION
    assert "continuity_issues" not in current.table_names


async def test_unmanaged_metadata_trigger_is_rejected_before_cas_or_ddl(empty_disposable_mysql):
    session, project_id = await old_database(empty_disposable_mysql)
    await session.execute(
        "CREATE TRIGGER unauthorized_metadata_side_effect AFTER UPDATE ON schema_metadata "
        "FOR EACH ROW UPDATE projects SET description='unexpected-author-write'"
    )
    # The shared table fingerprint alone cannot detect this executable object.
    before = await inventory_database(session, upgrade.PRODUCT_DATABASE)
    assert before.structural_fingerprint == upgrade.V114_STRUCTURAL_FINGERPRINT
    marks = []
    with pytest.raises(upgrade.SchemaUpgradeError, match="unmanaged objects"):
        await apply(session, lambda: marks.append("ddl"))
    assert marks == []
    after = await inventory_database(session, upgrade.PRODUCT_DATABASE)
    assert "continuity_issues" not in after.table_names
    row = await session.fetchone("SELECT description FROM projects WHERE id=%s", (project_id,))
    assert row["description"] == "需要完整保留的作者数据"


async def test_database_checks_reject_invalid_issue_values(empty_disposable_mysql):
    from pymysql.err import OperationalError, IntegrityError

    session, project_id = await old_database(empty_disposable_mysql)
    await apply(session)
    valid = dict(
        id=str(uuid4()), project_id=project_id, category="time", severity="medium",
        status="pending", source_chapter=None, source_finalization_id=None,
        source_canon_revision=None, description="时间顺序冲突", suggestion=None,
        future_target=None, resolution_note=None, created_at=NOW, updated_at=NOW,
    )
    columns = tuple(valid)
    sql = "INSERT INTO continuity_issues (" + ",".join(columns) + ") VALUES (" + ",".join(["%s"] * len(columns)) + ")"
    invalid = [
        {"category": "style"}, {"severity": "critical"}, {"status": "closed"},
        {"description": ""}, {"description": "   "}, {"description": "字" * 4001},
        {"suggestion": ""}, {"suggestion": "字" * 4001},
        {"future_target": ""}, {"future_target": "字" * 4001},
        {"resolution_note": ""}, {"resolution_note": "字" * 4001},
        {"status": "resolved"}, {"status": "ignored"},
        {"source_chapter": 1}, {"source_canon_revision": 1},
        {"source_chapter": 0}, {"source_canon_revision": 0},
        {"created_at": -1}, {"updated_at": NOW - 1},
    ]
    for changes in invalid:
        row = {**valid, **changes, "id": str(uuid4())}
        with pytest.raises((OperationalError, IntegrityError)) as raised:
            await session.execute(sql, tuple(row[column] for column in columns))
        assert raised.value.args[0] in (3819, 1452), changes
    for status in ("pending", "resolved", "ignored"):
        row = {**valid, "id": str(uuid4()), "status": status, "resolution_note": "作者记录处理结论"}
        await session.execute(sql, tuple(row[column] for column in columns))
    count = await session.fetchone("SELECT COUNT(*) AS count FROM continuity_issues")
    assert count["count"] == 3


async def test_metadata_cas_failure_exposes_autocommitted_table_and_preserves_old_metadata(empty_disposable_mysql):
    session, _ = await old_database(empty_disposable_mysql)

    class RejectCAS:
        async def execute(self, sql, params=None):
            if sql.startswith("UPDATE schema_metadata"):
                return 0
            return await session.execute(sql, params)
        async def fetchone(self, sql, params=None):
            return await session.fetchone(sql, params)
        async def fetchall(self, sql, params=None):
            return await session.fetchall(sql, params)

    with pytest.raises(upgrade.SchemaUpgradeRestoreRequired):
        await apply(RejectCAS())
    current = await inventory_database(session, upgrade.PRODUCT_DATABASE)
    assert current.schema_version == upgrade.V114_SCHEMA_VERSION
    assert "continuity_issues" in current.table_names


@pytest.mark.parametrize("fail_after_ddl", [False, True])
async def test_default_command_uses_real_private_backup_and_retains_receipt(
    empty_disposable_mysql, monkeypatch, fail_after_ddl,
):
    """Default adapters use actual clients and locks, with a guarded schema alias."""
    dump = os.environ.get("TEST_MYSQLDUMP_84")
    client = os.environ.get("TEST_MYSQL_84")
    if not dump or not client:
        pytest.skip("Explicit MySQL 8.4 client paths are required for backup proof")
    import aiomysql
    import backend.config as config_module
    import backend.database as database_module

    database = empty_disposable_mysql
    await old_database(database)
    real_connect = aiomysql.connect
    real_session = database_module.DatabaseSession
    physical = database.database_name
    assert_disposable_name(physical)

    async def guarded_connect(**kwargs):
        assert kwargs["db"] == upgrade.PRODUCT_DATABASE
        assert_disposable_name(physical)
        return await real_connect(**{**kwargs, "db": physical})

    def redirected_session(raw):
        return _LogicalDatabaseSession(real_session(raw), physical, upgrade.PRODUCT_DATABASE)

    def guarded_runner(command, **kwargs):
        command = list(command)
        if upgrade.PRODUCT_DATABASE in command:
            assert command[-1] == upgrade.PRODUCT_DATABASE
            assert_disposable_name(physical)
            command[-1] = physical
        return subprocess.run(command, **kwargs, timeout=60)

    directory = _owned_external_directory()
    try:
        monkeypatch.setattr(aiomysql, "connect", guarded_connect)
        monkeypatch.setattr(database_module, "DatabaseSession", redirected_session)
        # Keep test lifecycle serialization independent of the user's running service.
        monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", directory / "test-config.json")
        monkeypatch.setattr(upgrade, "_backup_runner", guarded_runner)
        connection = {**database.connection_config, "db": upgrade.PRODUCT_DATABASE}
        dependencies = upgrade._default_dependencies(connection)
        if fail_after_ddl:
            async def fail(_database):
                raise RuntimeError("post-DDL verification fault")
            dependencies = replace(dependencies, verify=fail)
        published = []
        kwargs = dict(
            dependencies=dependencies, database=upgrade.PRODUCT_DATABASE,
            confirm_database=upgrade.PRODUCT_DATABASE, backup_directory=directory / "backup",
            mysqldump=Path(dump), mysql=Path(client), now_ms=NOW + 1,
            receipt_output=published.append,
        )
        if fail_after_ddl:
            with pytest.raises(upgrade.SchemaUpgradeRestoreRequired) as raised:
                await upgrade.run_product_upgrade(**kwargs)
            receipt = raised.value.receipt
            assert receipt is published[0]
        else:
            result = await upgrade.run_product_upgrade(**kwargs)
            receipt = result.backup_receipt
        assert receipt.backup_path.is_file()
        assert receipt.backup_byte_length > 0
        from backend.services.product_database_backup import verify_backup_file
        verify_backup_file(receipt.backup_path, receipt.backup_sha256, receipt.backup_byte_length)
        backup_text = receipt.backup_path.read_text(encoding="utf-8")
        assert "CREATE TABLE `projects`" in backup_text
        assert "迁移保留项目" in backup_text
        assert "CREATE TABLE `continuity_issues`" not in backup_text
        assert not list(receipt.backup_path.parent.glob("*.cnf"))
    finally:
        _remove_owned_external_directory(directory)
