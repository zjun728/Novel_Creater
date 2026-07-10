"""Opt-in integration tests for a newly generated disposable MySQL schema.

This module intentionally does not match the default ``test_*.py`` pattern.
It must only be run with CONTROL_PLANE_DISPOSABLE_MYSQL_DSN explicitly set to
a loopback admin DSN without a selected database.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import hashlib
import os
import time
import unittest
import uuid

import aiomysql

from backend.control_plane.draft_write_errors import DraftWriteError
from backend.control_plane.draft_write_models import (
    DraftWriteCommand,
    parse_manifest_value,
    to_command,
)
from backend.control_plane.draft_write_service import DraftWriteService
from backend.control_plane.restricted_jcs import canonical_sha256, loads_rejecting_duplicates
from backend.tests.control_plane.mysql_harness import (
    DisposableMySQL,
    apply_fixed_ledger_migration,
    assert_selected_database,
    disposable_mysql,
    rollback_fixed_ledger_migration,
)


PROJECT_ID = "00000000-0000-0000-0000-000000000001"
CHAPTER_ONE_ID = "00000000-0000-0000-0000-000000000011"
CHAPTER_TWO_ID = "00000000-0000-0000-0000-000000000012"
SOURCE_ONE_ID = "00000000-0000-0000-0000-000000000021"
SOURCE_TWO_ID = "00000000-0000-0000-0000-000000000022"
FINAL_VERSION_ID = "00000000-0000-0000-0000-000000000099"
SOURCE_ONE_CONTENT = "source-one exact UTF-8 文本"
SOURCE_TWO_CONTENT = "source-two exact UTF-8 文本"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _command(*, key: str = "Disposable-Case-Key", candidate_suffix: str = "") -> DraftWriteCommand:
    candidate_two = "candidate-two exact UTF-8 文本" + candidate_suffix
    candidate_one = "candidate-one exact UTF-8 文本" + candidate_suffix
    manifest = {
        "manifestVersion": 1,
        "purpose": "draft_only_pair",
        "projectId": PROJECT_ID,
        "writes": [
            {
                "chapterId": CHAPTER_TWO_ID,
                "chapterNum": 2,
                "sourceVersionId": SOURCE_TWO_ID,
                "expectedSourceContentSha256": _sha256(SOURCE_TWO_CONTENT),
                "title": "Second request item",
                "content": candidate_two,
                "contentSha256": _sha256(candidate_two),
                "promptBrief": "Disposable prompt two",
            },
            {
                "chapterId": CHAPTER_ONE_ID,
                "chapterNum": 1,
                "sourceVersionId": SOURCE_ONE_ID,
                "expectedSourceContentSha256": _sha256(SOURCE_ONE_CONTENT),
                "title": "First database chapter",
                "content": candidate_one,
                "contentSha256": _sha256(candidate_one),
                "promptBrief": "Disposable prompt one",
            },
        ],
    }
    return to_command(
        route_project_id=PROJECT_ID,
        request=parse_manifest_value(manifest),
        idempotency_key=key,
        manifest_sha256=canonical_sha256(manifest),
    )


def _service(
    disposable: DisposableMySQL,
    *,
    after_candidate_insert=None,
    commit_operation=None,
) -> DraftWriteService:
    return DraftWriteService(
        pool=disposable.pool,
        expected_schema=disposable.schema_name,
        run_token=disposable.run_token,
        uuid_factory=lambda: str(uuid.uuid4()),
        clock_ms=lambda: time.time_ns() // 1_000_000,
        after_candidate_insert=after_candidate_insert,
        commit_operation=commit_operation,
    )


async def _execute(pool, schema_name: str, sql: str, params=None) -> None:
    async with pool.acquire() as conn:
        await assert_selected_database(conn, schema_name)
        async with conn.cursor() as cursor:
            await cursor.execute(sql, params)
        await assert_selected_database(conn, schema_name)


async def _fetchone(pool, schema_name: str, sql: str, params=None):
    async with pool.acquire() as conn:
        await assert_selected_database(conn, schema_name)
        async with conn.cursor() as cursor:
            await cursor.execute(sql, params)
            row = await cursor.fetchone()
        await assert_selected_database(conn, schema_name)
        return row


async def _fetchall(pool, schema_name: str, sql: str, params=None):
    async with pool.acquire() as conn:
        await assert_selected_database(conn, schema_name)
        async with conn.cursor() as cursor:
            await cursor.execute(sql, params)
            rows = await cursor.fetchall()
        await assert_selected_database(conn, schema_name)
        return list(rows)


async def _seed(disposable: DisposableMySQL) -> None:
    timestamp = time.time_ns() // 1_000_000
    pool = disposable.pool
    schema = disposable.schema_name
    async with pool.acquire() as conn:
        await assert_selected_database(conn, schema)
        async with conn.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO projects (id, created_at, updated_at) VALUES (%s,%s,%s)",
                (PROJECT_ID, timestamp, timestamp),
            )
            await cursor.executemany(
                """INSERT INTO chapters
                   (id, project_id, chapter_num, final_version_id, status, created_at, updated_at)
                   VALUES (%s,%s,%s,NULL,'drafting',%s,%s)""",
                [
                    (CHAPTER_ONE_ID, PROJECT_ID, 1, timestamp, timestamp),
                    (CHAPTER_TWO_ID, PROJECT_ID, 2, timestamp, timestamp),
                ],
            )
            await cursor.executemany(
                """INSERT INTO chapter_versions
                   (id, project_id, chapter_id, chapter_num, title, content,
                    version_type, source_model_id, prompt_brief, created_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,'source',NULL,NULL,%s,%s)""",
                [
                    (
                        SOURCE_ONE_ID,
                        PROJECT_ID,
                        CHAPTER_ONE_ID,
                        1,
                        "Source one",
                        SOURCE_ONE_CONTENT,
                        timestamp,
                        timestamp,
                    ),
                    (
                        SOURCE_TWO_ID,
                        PROJECT_ID,
                        CHAPTER_TWO_ID,
                        2,
                        "Source two",
                        SOURCE_TWO_CONTENT,
                        timestamp,
                        timestamp,
                    ),
                ],
            )
        await assert_selected_database(conn, schema)


@dataclass(frozen=True)
class _SeededCase:
    disposable: DisposableMySQL
    command: DraftWriteCommand

    def service(self, *, after_candidate_insert=None, commit_operation=None) -> DraftWriteService:
        return _service(
            self.disposable,
            after_candidate_insert=after_candidate_insert,
            commit_operation=commit_operation,
        )


@asynccontextmanager
async def _seeded_case(*, key: str = "Disposable-Case-Key"):
    async with disposable_mysql(
        environ=os.environ,
        create_pool=aiomysql.create_pool,
    ) as disposable:
        await _seed(disposable)
        yield _SeededCase(disposable=disposable, command=_command(key=key))


async def _write_counts(case: _SeededCase) -> tuple[int, int]:
    pool = case.disposable.pool
    schema = case.disposable.schema_name
    ledger_row = await _fetchone(pool, schema, "SELECT COUNT(*) FROM draft_write_batches")
    candidate_row = await _fetchone(
        pool,
        schema,
        "SELECT COUNT(*) FROM chapter_versions WHERE version_type='qa_draft_candidate'",
    )
    return int(ledger_row[0]), int(candidate_row[0])


def _parse_stored_result_json(value: object) -> dict[str, object]:
    if type(value) is str:
        raw = value.encode("utf-8", errors="strict")
    elif type(value) is bytes:
        raw = value
    else:
        raise AssertionError("ledger result_json must be JSON text")
    parsed = loads_rejecting_duplicates(raw)
    if type(parsed) is not dict:
        raise AssertionError("ledger result_json must contain an object")
    return parsed


class DisposableMySQLDraftWriteIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_two_candidates_commit_together(self):
        async with _seeded_case() as case:
            before = await _fetchall(
                case.disposable.pool,
                case.disposable.schema_name,
                "SELECT id, status, final_version_id FROM chapters ORDER BY chapter_num, id",
            )
            result = await case.service().submit(case.command)
            self.assertEqual(await _write_counts(case), (1, 2))
            self.assertEqual(len(result.candidate_version_ids), 2)
            stored_chapters = []
            for candidate_id in result.candidate_version_ids:
                row = await _fetchone(
                    case.disposable.pool,
                    case.disposable.schema_name,
                    "SELECT chapter_id FROM chapter_versions WHERE id=%s",
                    (candidate_id,),
                )
                stored_chapters.append(row[0])
            self.assertEqual(stored_chapters, [CHAPTER_TWO_ID, CHAPTER_ONE_ID])
            after = await _fetchall(
                case.disposable.pool,
                case.disposable.schema_name,
                "SELECT id, status, final_version_id FROM chapters ORDER BY chapter_num, id",
            )
            self.assertEqual(after, before)

    async def test_failure_after_first_candidate_rolls_back_ledger_and_candidates(self):
        async with _seeded_case() as case:
            async def fail_after_first(index: int) -> None:
                if index == 1:
                    raise RuntimeError("test-only failure after first candidate")

            with self.assertRaisesRegex(RuntimeError, "test-only failure"):
                await case.service(after_candidate_insert=fail_after_first).submit(case.command)
            self.assertEqual(await _write_counts(case), (0, 0))

    async def test_same_key_same_hash_replays_without_duplicates(self):
        async with _seeded_case() as case:
            service = case.service()
            first = await service.submit(case.command)
            replay = await service.submit(case.command)
            self.assertEqual(replay, first)
            self.assertEqual(await _write_counts(case), (1, 2))

    async def test_same_key_different_hash_conflicts_without_writes(self):
        async with _seeded_case(key="Shared-Key") as case:
            await case.service().submit(case.command)
            conflicting = _command(key="Shared-Key", candidate_suffix=" changed")
            with self.assertRaises(DraftWriteError) as caught:
                await case.service().submit(conflicting)
            self.assertEqual(caught.exception.code, "idempotency_manifest_conflict")
            self.assertEqual(await _write_counts(case), (1, 2))

    async def test_source_preimage_drift_conflicts_without_writes(self):
        async with _seeded_case() as case:
            await _execute(
                case.disposable.pool,
                case.disposable.schema_name,
                "UPDATE chapter_versions SET content=%s WHERE id=%s",
                ("source content drifted", SOURCE_ONE_ID),
            )
            with self.assertRaises(DraftWriteError) as caught:
                await case.service().submit(case.command)
            self.assertEqual(caught.exception.code, "source_preimage_mismatch")
            self.assertEqual(await _write_counts(case), (0, 0))

    async def test_final_status_conflicts_without_writes(self):
        async with _seeded_case() as case:
            await _execute(
                case.disposable.pool,
                case.disposable.schema_name,
                "UPDATE chapters SET status='final' WHERE id=%s",
                (CHAPTER_ONE_ID,),
            )
            with self.assertRaises(DraftWriteError) as caught:
                await case.service().submit(case.command)
            self.assertEqual(caught.exception.code, "chapter_finalized")
            self.assertEqual(await _write_counts(case), (0, 0))

    async def test_final_version_pointer_conflicts_without_writes(self):
        async with _seeded_case() as case:
            await _execute(
                case.disposable.pool,
                case.disposable.schema_name,
                "UPDATE chapters SET final_version_id=%s WHERE id=%s",
                (FINAL_VERSION_ID, CHAPTER_ONE_ID),
            )
            with self.assertRaises(DraftWriteError) as caught:
                await case.service().submit(case.command)
            self.assertEqual(caught.exception.code, "chapter_finalized")
            self.assertEqual(await _write_counts(case), (0, 0))

    async def test_reverse_request_order_preserves_result_order_with_deterministic_locks(self):
        async with _seeded_case() as case:
            self.assertEqual(
                [write.chapter_id for write in case.command.writes],
                [CHAPTER_TWO_ID, CHAPTER_ONE_ID],
            )
            result = await case.service().submit(case.command)
            rows = []
            for candidate_id in result.candidate_version_ids:
                rows.append(
                    await _fetchone(
                        case.disposable.pool,
                        case.disposable.schema_name,
                        "SELECT chapter_id FROM chapter_versions WHERE id=%s",
                        (candidate_id,),
                    )
                )
            self.assertEqual([row[0] for row in rows], [CHAPTER_TWO_ID, CHAPTER_ONE_ID])
            self.assertEqual(await _write_counts(case), (1, 2))

    async def test_concurrent_identical_submission_commits_one_batch(self):
        async with _seeded_case(key="Concurrent-Key") as case:
            first_holds_lock = asyncio.Event()
            release_first = asyncio.Event()
            second_started = asyncio.Event()
            first_task = None
            second_task = None

            async def hold_first_after_candidate(index: int) -> None:
                if index == 1:
                    first_holds_lock.set()
                    await asyncio.wait_for(release_first.wait(), timeout=5)

            async def submit_second():
                second_started.set()
                return await case.service().submit(case.command)

            try:
                first_task = asyncio.create_task(
                    case.service(after_candidate_insert=hold_first_after_candidate).submit(case.command)
                )
                await asyncio.wait_for(first_holds_lock.wait(), timeout=5)
                self.assertFalse(first_task.done())

                second_task = asyncio.create_task(submit_second())
                await asyncio.wait_for(second_started.wait(), timeout=5)
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.shield(second_task), timeout=0.1)
                self.assertFalse(second_task.done())

                release_first.set()
                first, second = await asyncio.wait_for(
                    asyncio.gather(first_task, second_task),
                    timeout=10,
                )
                self.assertEqual(first, second)
                self.assertEqual(await _write_counts(case), (1, 2))
            finally:
                release_first.set()
                tasks = [task for task in (first_task, second_task) if task is not None]
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks:
                    try:
                        await asyncio.wait_for(
                            asyncio.gather(*tasks, return_exceptions=True),
                            timeout=5,
                        )
                    except asyncio.TimeoutError:
                        pass

    async def test_migration_apply_and_rollback_are_contained_to_generated_schema(self):
        async with _seeded_case() as case:
            pool = case.disposable.pool
            schema = case.disposable.schema_name
            applied_rows = await _fetchall(
                pool,
                schema,
                """SELECT table_schema FROM information_schema.tables
                   WHERE table_name='draft_write_batches' ORDER BY table_schema""",
            )
            applied_schema_names = {row[0] for row in applied_rows}
            self.assertIn(schema, applied_schema_names)
            unrelated_baseline = applied_schema_names - {schema}

            await rollback_fixed_ledger_migration(pool, schema)
            rolled_back_rows = await _fetchall(
                pool,
                schema,
                """SELECT table_schema FROM information_schema.tables
                   WHERE table_name='draft_write_batches' ORDER BY table_schema""",
            )
            self.assertEqual({row[0] for row in rolled_back_rows}, unrelated_baseline)
            remaining = await _fetchall(
                pool,
                schema,
                """SELECT table_name FROM information_schema.tables
                   WHERE table_schema=%s ORDER BY table_name""",
                (schema,),
            )
            self.assertEqual(
                {row[0] for row in remaining},
                {"projects", "chapters", "chapter_versions"},
            )
            await apply_fixed_ledger_migration(pool, schema)
            reapplied_rows = await _fetchall(
                pool,
                schema,
                """SELECT table_schema FROM information_schema.tables
                   WHERE table_name='draft_write_batches' ORDER BY table_schema""",
            )
            self.assertEqual({row[0] for row in reapplied_rows}, applied_schema_names)

    async def test_commit_landed_outcome_unknown_replays_committed_result(self):
        async with _seeded_case(key="Landed-Unknown-Key") as case:
            async def commit_then_disconnect(conn) -> None:
                await conn.commit()
                raise ConnectionError("test-only post-commit disconnect")

            with self.assertRaises(DraftWriteError) as caught:
                await case.service(commit_operation=commit_then_disconnect).submit(case.command)
            self.assertEqual(caught.exception.code, "commit_outcome_unknown")
            self.assertEqual(await _write_counts(case), (1, 2))

            ledger_row = await _fetchone(
                case.disposable.pool,
                case.disposable.schema_name,
                """SELECT id, project_id, manifest_sha256, result_json, committed_at
                   FROM draft_write_batches WHERE project_id=%s AND idempotency_key=%s""",
                (PROJECT_ID, case.command.idempotency_key.encode("ascii")),
            )
            self.assertIsNotNone(ledger_row)
            stored_result = _parse_stored_result_json(ledger_row[3])
            self.assertEqual(
                set(stored_result),
                {
                    "batchId",
                    "projectId",
                    "manifestSha256",
                    "candidateVersionIds",
                    "committedAt",
                },
            )
            self.assertEqual(ledger_row[0], stored_result["batchId"])
            self.assertEqual(ledger_row[1], stored_result["projectId"])
            self.assertEqual(ledger_row[2], stored_result["manifestSha256"])
            self.assertEqual(ledger_row[4], stored_result["committedAt"])
            self.assertEqual(stored_result["projectId"], PROJECT_ID)
            self.assertEqual(stored_result["manifestSha256"], case.command.manifest_sha256)
            candidate_ids = stored_result["candidateVersionIds"]
            self.assertIs(type(candidate_ids), list)
            self.assertEqual(len(candidate_ids), 2)
            self.assertTrue(all(type(candidate_id) is str and candidate_id for candidate_id in candidate_ids))
            self.assertNotEqual(candidate_ids[0], candidate_ids[1])
            stored_candidate_chapters = []
            for candidate_id in candidate_ids:
                row = await _fetchone(
                    case.disposable.pool,
                    case.disposable.schema_name,
                    "SELECT chapter_id FROM chapter_versions WHERE id=%s",
                    (candidate_id,),
                )
                self.assertIsNotNone(row)
                stored_candidate_chapters.append(row[0])
            self.assertEqual(stored_candidate_chapters, [CHAPTER_TWO_ID, CHAPTER_ONE_ID])

            replay = await case.service().submit(case.command)
            self.assertEqual(replay.to_wire(), stored_result)
            self.assertEqual(replay.batch_id, ledger_row[0])
            self.assertEqual(replay.committed_at, ledger_row[4])
            self.assertEqual(list(replay.candidate_version_ids), candidate_ids)
            self.assertEqual(await _write_counts(case), (1, 2))

    async def test_commit_not_landed_outcome_unknown_can_retry_cleanly(self):
        async with _seeded_case(key="Not-Landed-Unknown-Key") as case:
            async def disconnect_before_commit(conn) -> None:
                conn.close()
                raise ConnectionError("test-only pre-commit disconnect")

            with self.assertRaises(DraftWriteError) as caught:
                await case.service(commit_operation=disconnect_before_commit).submit(case.command)
            self.assertEqual(caught.exception.code, "commit_outcome_unknown")
            self.assertEqual(await _write_counts(case), (0, 0))
            result = await case.service().submit(case.command)
            self.assertEqual(result.manifest_sha256, case.command.manifest_sha256)
            self.assertEqual(await _write_counts(case), (1, 2))


if __name__ == "__main__":
    unittest.main()
