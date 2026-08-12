from __future__ import annotations

import pytest

from backend.repositories.project_imports import (
    ProjectImportCommandConflict,
    ProjectImportCommandStateConflict,
    ProjectImportPersistenceError,
    ProjectImportRepository,
)
from backend.tests.support.disposable_mysql import transaction_factory_for


COMMAND_1 = "10000000-0000-4000-8000-000000000001"
COMMAND_2 = "10000000-0000-4000-8000-000000000002"
TARGET_1 = "20000000-0000-4000-8000-000000000001"
TARGET_2 = "20000000-0000-4000-8000-000000000002"
OWNER_1 = "30000000-0000-4000-8000-000000000001"
OWNER_2 = "30000000-0000-4000-8000-000000000002"
KEY_1 = "1" * 64
KEY_2 = "2" * 64
FINGERPRINT_1 = "a" * 64
FINGERPRINT_2 = "b" * 64


async def _reserve(repository, session, **changes):
    values = {
        "command_id": COMMAND_1,
        "idempotency_key": KEY_1,
        "request_fingerprint": FINGERPRINT_1,
        "package_hash": "c" * 64,
        "manifest_hash": "d" * 64,
        "package_version": 1,
        "target_project_id": TARGET_1,
        "normalized_title": "Imported project",
        "now_ms": 100,
    }
    values.update(changes)
    return await repository.reserve_command(session, **values)


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_command_idempotency_leases_and_fixed_terminal_results(disposable_mysql):
    assert disposable_mysql.database_name.startswith("novel_creator_test_")
    repository = ProjectImportRepository()
    transaction_factory = transaction_factory_for(disposable_mysql.connection_config)

    async with transaction_factory() as session:
        reserved = await _reserve(repository, session)
        replay = await _reserve(repository, session, command_id=COMMAND_2)
        assert reserved == replay
        assert reserved.command_id == COMMAND_1

        with pytest.raises(ProjectImportCommandConflict) as key_conflict:
            await _reserve(repository, session, request_fingerprint=FINGERPRINT_2)
        assert key_conflict.value.__cause__ is None

        with pytest.raises(ProjectImportCommandConflict) as command_conflict:
            await _reserve(repository, session, idempotency_key=KEY_2)
        assert command_conflict.value.__cause__ is None

        running = await repository.acquire_lease(
            session, command_id=COMMAND_1, request_fingerprint=FINGERPRINT_1,
            owner_token=OWNER_1, now_ms=100, lease_expires_at=200,
        )
        assert running.status == "running"
        identical = await repository.acquire_lease(
            session, command_id=COMMAND_1, request_fingerprint=FINGERPRINT_1,
            owner_token=OWNER_1, now_ms=100, lease_expires_at=200,
        )
        assert identical == running
        renewed = await repository.acquire_lease(
            session, command_id=COMMAND_1, request_fingerprint=FINGERPRINT_1,
            owner_token=OWNER_1, now_ms=150, lease_expires_at=250,
        )
        assert renewed.status == "running"
        with pytest.raises(ProjectImportCommandStateConflict):
            await repository.acquire_lease(
                session, command_id=COMMAND_1,
                request_fingerprint=FINGERPRINT_1,
                owner_token=OWNER_2, now_ms=200, lease_expires_at=300,
            )
        reacquired = await repository.acquire_lease(
            session, command_id=COMMAND_1, request_fingerprint=FINGERPRINT_1,
            owner_token=OWNER_2, now_ms=250, lease_expires_at=350,
        )
        assert reacquired.retry_required is False

        with pytest.raises(ProjectImportCommandStateConflict):
            await repository.mark_failed(
                session, command_id=COMMAND_1,
                request_fingerprint=FINGERPRINT_1,
                owner_token=OWNER_1, now_ms=300,
            )

        failed = await repository.mark_failed(
            session, command_id=COMMAND_1, request_fingerprint=FINGERPRINT_1,
            owner_token=OWNER_2, now_ms=300,
        )
        assert failed.status == "failed"
        assert failed.phase == "failed"
        assert failed.public_error_code == "PROJECT_IMPORT_FAILED"
        assert failed.target_project_id is None

        await _reserve(
            repository, session, command_id=COMMAND_2, idempotency_key=KEY_2,
            request_fingerprint=FINGERPRINT_2, target_project_id=TARGET_2,
        )
        await repository.acquire_lease(
            session, command_id=COMMAND_2, request_fingerprint=FINGERPRINT_2,
            owner_token=OWNER_1, now_ms=400, lease_expires_at=500,
        )
        succeeded = await repository.mark_succeeded(
            session, command_id=COMMAND_2, request_fingerprint=FINGERPRINT_2,
            owner_token=OWNER_1, target_project_id=TARGET_2, now_ms=450,
        )
        assert succeeded.status == "succeeded"
        assert succeeded.target_project_id == TARGET_2
        assert succeeded.public_error_code is None

        assert await repository.read_command(
            session, command_id="90000000-0000-4000-8000-000000000009",
            now_ms=500,
        ) is None


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_duplicate_replay_uses_current_read_after_repeatable_read_snapshot(
    disposable_mysql,
):
    repository = ProjectImportRepository()
    transaction_factory = transaction_factory_for(disposable_mysql.connection_config)

    async with transaction_factory() as loser:
        assert await repository.read_command(
            loser, command_id=COMMAND_1, now_ms=100
        ) is None
        async with transaction_factory() as winner:
            won = await _reserve(repository, winner)

        replay = await _reserve(repository, loser, command_id=COMMAND_2)
        assert replay == won
        assert replay.command_id == COMMAND_1


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_persistence_error_escaping_transaction_rolls_back_reservation(
    disposable_mysql,
):
    repository = ProjectImportRepository()
    transaction_factory = transaction_factory_for(disposable_mysql.connection_config)

    class FailReadAfterInsert:
        def __init__(self, session):
            self.session = session

        async def execute(self, sql, args=None):
            return await self.session.execute(sql, args)

        async def fetchone(self, sql, args=None):
            raise RuntimeError("sql-id-hash-title-path-C:/private/archive.zip")

    with pytest.raises(ProjectImportPersistenceError):
        async with transaction_factory() as session:
            await _reserve(repository, FailReadAfterInsert(session))

    async with transaction_factory() as session:
        assert await repository.read_command(
            session, command_id=COMMAND_1, now_ms=100
        ) is None


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_import_tables_enforce_physical_storage_and_closed_constraints(
    disposable_mysql,
):
    transaction_factory = transaction_factory_for(disposable_mysql.connection_config)
    database_name = disposable_mysql.database_name

    async with transaction_factory() as session:
        tables = await session.fetchall(
            """SELECT TABLE_NAME AS table_name,ENGINE AS engine,
                      TABLE_COLLATION AS table_collation
               FROM information_schema.TABLES
               WHERE TABLE_SCHEMA=%s AND TABLE_NAME IN (%s,%s)
               ORDER BY TABLE_NAME""",
            (
                database_name,
                "project_import_provenance",
                "project_package_import_commands",
            ),
        )
        assert len(tables) == 2
        assert all(row["engine"] == "InnoDB" for row in tables)
        assert all(
            row["table_collation"] == "utf8mb4_0900_ai_ci" for row in tables
        )

        indexes = await session.fetchall(
            """SELECT TABLE_NAME AS table_name,INDEX_NAME AS index_name,
                      NON_UNIQUE AS non_unique,
                      GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS columns_csv
               FROM information_schema.STATISTICS
               WHERE TABLE_SCHEMA=%s AND TABLE_NAME IN (%s,%s)
               GROUP BY TABLE_NAME,INDEX_NAME,NON_UNIQUE""",
            (
                database_name,
                "project_import_provenance",
                "project_package_import_commands",
            ),
        )
        unique_indexes = {
            (row["table_name"], row["index_name"]): row["columns_csv"]
            for row in indexes
            if row["non_unique"] == 0
        }
        assert unique_indexes[
            ("project_package_import_commands", "uq_project_import_idempotency")
        ] == "idempotency_key"
        assert unique_indexes[
            ("project_package_import_commands", "uq_project_import_target")
        ] == "target_project_id"
        assert unique_indexes[
            ("project_import_provenance", "PRIMARY")
        ] == "project_id,record_order"
        assert unique_indexes[
            ("project_import_provenance", "uq_project_import_provenance_command_order")
        ] == "command_id,record_order"

        foreign_keys = await session.fetchall(
            """SELECT TABLE_NAME AS table_name,COLUMN_NAME AS column_name,
                      REFERENCED_TABLE_NAME AS referenced_table_name,
                      REFERENCED_COLUMN_NAME AS referenced_column_name
               FROM information_schema.KEY_COLUMN_USAGE
               WHERE TABLE_SCHEMA=%s AND TABLE_NAME IN (%s,%s)
                 AND REFERENCED_TABLE_NAME IS NOT NULL""",
            (
                database_name,
                "project_import_provenance",
                "project_package_import_commands",
            ),
        )
        edges = {
            (
                row["table_name"], row["column_name"],
                row["referenced_table_name"], row["referenced_column_name"],
            )
            for row in foreign_keys
        }
        assert edges == {
            ("project_import_provenance", "project_id", "projects", "id"),
            (
                "project_import_provenance", "command_id",
                "project_package_import_commands", "id",
            ),
            (
                "project_import_provenance", "project_id",
                "project_package_import_commands", "target_project_id",
            ),
        }

        for project_id in (TARGET_1, TARGET_2):
            await session.execute(
                """INSERT INTO projects
                   (id,title,genre,description,target_words,target_chapters,
                    status,current_chapter,created_at,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,'drafting',0,1,1)""",
                (project_id, "Import target", "test", "test", 1000, 10),
            )
        await _reserve(ProjectImportRepository(), session)

        invalid_statements = (
            (
                "UPDATE project_package_import_commands SET status=%s WHERE id=%s",
                ("unknown", COMMAND_1),
            ),
            (
                "UPDATE project_package_import_commands SET phase=%s WHERE id=%s",
                ("unknown", COMMAND_1),
            ),
            (
                "UPDATE project_package_import_commands SET staging_manifest_json=%s WHERE id=%s",
                ("{", COMMAND_1),
            ),
            (
                """INSERT INTO project_import_provenance
                   (project_id,command_id,record_order,category,
                    source_entity_type,source_logical_id,payload_json,
                    content_hash,created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1)""",
                (
                    TARGET_1, COMMAND_1, 0, "provider-history", "provider",
                    "provider:1", "{}", "e" * 64,
                ),
            ),
            (
                """INSERT INTO project_import_provenance
                   (project_id,command_id,record_order,category,
                    source_entity_type,source_logical_id,payload_json,
                    content_hash,created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1)""",
                (
                    TARGET_2, COMMAND_1, 1, "provider-history", "provider",
                    "provider:1", "{}", "e" * 64,
                ),
            ),
        )
        for sql, args in invalid_statements:
            with pytest.raises(Exception):
                await session.execute(sql, args)
