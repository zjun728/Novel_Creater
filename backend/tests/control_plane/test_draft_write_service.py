from dataclasses import replace
import hashlib
import inspect
import json
import unittest

from backend.control_plane.draft_write_errors import DraftWriteError, UnsafeDisposableDatabase
from backend.control_plane.draft_write_models import parse_manifest_value, to_command
from backend.control_plane.restricted_jcs import canonical_sha256
from backend.control_plane.draft_write_service import DraftWriteService
import backend.control_plane.draft_write_repository as repository
from fakes import ExpectedExecution, FakeConnection, FakeMySQLError, FakePool


TOKEN = "run123"
SCHEMA = "novel_creator_control_plane_disposable_" + TOKEN


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def payload() -> dict[str, object]:
    return {
        "manifestVersion": 1,
        "purpose": "draft_only_pair",
        "projectId": "project-1",
        "writes": [
            {
                "chapterId": "chapter-2",
                "chapterNum": 2,
                "sourceVersionId": "source-2",
                "expectedSourceContentSha256": sha("source-two"),
                "title": "Second request item",
                "content": "candidate-two",
                "contentSha256": sha("candidate-two"),
                "promptBrief": "Prompt two",
            },
            {
                "chapterId": "chapter-1",
                "chapterNum": 1,
                "sourceVersionId": "source-1",
                "expectedSourceContentSha256": sha("source-one"),
                "title": "First database chapter",
                "content": "candidate-one",
                "contentSha256": sha("candidate-one"),
                "promptBrief": "Prompt one",
            },
        ],
    }


def command(*, key="CaseSensitive-Key", manifest_hash=None):
    value = payload()
    return to_command(
        route_project_id="project-1",
        request=parse_manifest_value(value),
        idempotency_key=key,
        manifest_sha256=manifest_hash or canonical_sha256(value),
    )


def project_row():
    return {"id": "project-1"}


def chapter_rows():
    return [
        {
            "id": "chapter-1",
            "project_id": "project-1",
            "chapter_num": 1,
            "status": "drafting",
            "final_version_id": None,
        },
        {
            "id": "chapter-2",
            "project_id": "project-1",
            "chapter_num": 2,
            "status": "drafting",
            "final_version_id": None,
        },
    ]


def source_rows():
    return [
        {
            "id": "source-1",
            "project_id": "project-1",
            "chapter_id": "chapter-1",
            "content": "source-one",
        },
        {
            "id": "source-2",
            "project_id": "project-1",
            "chapter_id": "chapter-2",
            "content": "source-two",
        },
    ]


def success_executions(*, projects=None, chapters=None, sources=None):
    return [
        ExpectedExecution("FROM projects", rows=[project_row()] if projects is None else projects),
        ExpectedExecution("INSERT INTO draft_write_batches", rowcount=1),
        ExpectedExecution("FROM chapters", rows=chapter_rows() if chapters is None else chapters),
        ExpectedExecution("FROM chapter_versions", rows=source_rows() if sources is None else sources),
        ExpectedExecution("INSERT INTO chapter_versions", rowcount=1),
        ExpectedExecution("INSERT INTO chapter_versions", rowcount=1),
        ExpectedExecution("UPDATE draft_write_batches", rowcount=1),
    ]


def uuid_factory(values=None):
    iterator = iter(values or ["batch-1", "candidate-for-chapter-2", "candidate-for-chapter-1"])
    return lambda: next(iterator)


def make_service(pool, *, hook=None, commit_operation=None):
    return DraftWriteService(
        pool=pool,
        expected_schema=SCHEMA,
        run_token=TOKEN,
        uuid_factory=uuid_factory(),
        clock_ms=lambda: 1700000000000,
        after_candidate_insert=hook,
        commit_operation=commit_operation,
    )


class DraftWriteServiceTest(unittest.IsolatedAsyncioTestCase):
    def test_constructor_rejects_any_nonexact_disposable_schema(self):
        conn = FakeConnection(database_name=SCHEMA)
        for schema, token in [
            ("novel_creator", TOKEN),
            (SCHEMA + "_extra", TOKEN),
            (SCHEMA, TOKEN + "x"),
        ]:
            with self.subTest(schema=schema, token=token):
                with self.assertRaises(UnsafeDisposableDatabase):
                    DraftWriteService(
                        pool=FakePool([conn]),
                        expected_schema=schema,
                        run_token=token,
                        uuid_factory=uuid_factory(),
                        clock_ms=lambda: 1,
                    )

    def test_repository_has_no_product_database_or_config_dependency(self):
        source = inspect.getsource(repository)
        for forbidden in ["from database", "import database", "MYSQL_CONFIG", "get_pool", "from config", "import config"]:
            self.assertNotIn(forbidden, source)

    async def test_success_uses_lock_order_and_preserves_request_result_order(self):
        conn = FakeConnection(database_name=SCHEMA, executions=success_executions())
        pool = FakePool([conn])
        result = await make_service(pool).submit(command())

        self.assertEqual(
            result.candidate_version_ids,
            ("candidate-for-chapter-2", "candidate-for-chapter-1"),
        )
        self.assertEqual(conn.commit_calls, 1)
        self.assertEqual(conn.rollback_calls, 0)
        operation_sql = [sql for sql, _ in conn.sql if not sql.startswith("SELECT DATABASE") and not sql.startswith("SET TRANSACTION")]
        self.assertEqual(
            [
                "projects" if "FROM projects" in sql else
                "ledger-insert" if "INSERT INTO draft_write_batches" in sql else
                "chapters" if "FROM chapters" in sql else
                "sources" if "FROM chapter_versions" in sql else
                "candidate" if "INSERT INTO chapter_versions" in sql else
                "ledger-complete"
                for sql in operation_sql
            ],
            ["projects", "ledger-insert", "chapters", "sources", "candidate", "candidate", "ledger-complete"],
        )
        chapter_sql, chapter_params = next((sql, params) for sql, params in conn.sql if "FROM chapters" in sql)
        self.assertIn("ORDER BY chapter_num ASC, id ASC FOR UPDATE", chapter_sql)
        self.assertEqual(chapter_params, ("chapter-1", "chapter-2"))
        source_sql, source_params = next((sql, params) for sql, params in conn.sql if "FROM chapter_versions" in sql)
        self.assertIn("ORDER BY id ASC FOR UPDATE", source_sql)
        self.assertEqual(source_params, ("source-1", "source-2"))

        candidate_calls = [(sql, params) for sql, params in conn.sql if "INSERT INTO chapter_versions" in sql]
        self.assertEqual(candidate_calls[0][1][0:4], ("candidate-for-chapter-2", "project-1", "chapter-2", 2))
        self.assertEqual(candidate_calls[1][1][0:4], ("candidate-for-chapter-1", "project-1", "chapter-1", 1))
        for _, params in candidate_calls:
            self.assertEqual(params[6], "qa_draft_candidate")
            self.assertIsNone(params[7])
            self.assertTrue(params[8].startswith("[control-plane:batch-1] "))

        _, complete_params = next((sql, params) for sql, params in conn.sql if "UPDATE draft_write_batches" in sql)
        stored = json.loads(complete_params[0])
        self.assertEqual(stored, result.to_wire())
        self.assertEqual(set(stored), {"batchId", "projectId", "manifestSha256", "candidateVersionIds", "committedAt"})

    async def test_missing_project_fails_before_ledger_insert(self):
        conn = FakeConnection(
            database_name=SCHEMA,
            executions=[ExpectedExecution("FROM projects", rows=[])],
        )
        with self.assertRaises(DraftWriteError) as caught:
            await make_service(FakePool([conn])).submit(command())
        self.assertEqual(caught.exception.code, "project_not_found")
        self.assertEqual(caught.exception.http_status, 404)
        self.assertEqual(conn.rollback_calls, 1)
        self.assertFalse(any("INSERT INTO draft_write_batches" in sql for sql, _ in conn.sql))

    async def test_chapter_identity_and_finalized_failures_rollback(self):
        cases = []
        missing = chapter_rows()[:1]
        cases.append(("missing", missing, "chapter_not_found", 404))
        cross_project = chapter_rows()
        cross_project[0] = {**cross_project[0], "project_id": "other"}
        cases.append(("cross project", cross_project, "chapter_not_found", 404))
        wrong_number = chapter_rows()
        wrong_number[0] = {**wrong_number[0], "chapter_num": 99}
        cases.append(("wrong number", wrong_number, "chapter_identity_conflict", 409))
        final_status = chapter_rows()
        final_status[0] = {**final_status[0], "status": "final"}
        cases.append(("final status", final_status, "chapter_finalized", 409))
        final_pointer = chapter_rows()
        final_pointer[0] = {**final_pointer[0], "final_version_id": "final-1"}
        cases.append(("final pointer", final_pointer, "chapter_finalized", 409))

        for name, rows, code, status in cases:
            with self.subTest(name):
                conn = FakeConnection(
                    database_name=SCHEMA,
                    executions=[
                        ExpectedExecution("FROM projects", rows=[project_row()]),
                        ExpectedExecution("INSERT INTO draft_write_batches", rowcount=1),
                        ExpectedExecution("FROM chapters", rows=rows),
                    ],
                )
                with self.assertRaises(DraftWriteError) as caught:
                    await make_service(FakePool([conn])).submit(command())
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.http_status, status)
                self.assertEqual(conn.rollback_calls, 1)
                self.assertFalse(any("INSERT INTO chapter_versions" in sql for sql, _ in conn.sql))

    async def test_source_identity_null_and_preimage_failures_rollback(self):
        cases = []
        cases.append(("missing", source_rows()[:1], "source_version_not_found", 404))
        cross = source_rows()
        cross[0] = {**cross[0], "project_id": "other"}
        cases.append(("cross project", cross, "source_version_not_found", 404))
        wrong_chapter = source_rows()
        wrong_chapter[0] = {**wrong_chapter[0], "chapter_id": "chapter-2"}
        cases.append(("wrong chapter", wrong_chapter, "source_identity_conflict", 409))
        null_content = source_rows()
        null_content[0] = {**null_content[0], "content": None}
        cases.append(("null content", null_content, "source_content_unavailable", 409))
        drift = source_rows()
        drift[0] = {**drift[0], "content": "changed"}
        cases.append(("preimage", drift, "source_preimage_mismatch", 409))

        for name, rows, code, status in cases:
            with self.subTest(name):
                conn = FakeConnection(
                    database_name=SCHEMA,
                    executions=[
                        ExpectedExecution("FROM projects", rows=[project_row()]),
                        ExpectedExecution("INSERT INTO draft_write_batches", rowcount=1),
                        ExpectedExecution("FROM chapters", rows=chapter_rows()),
                        ExpectedExecution("FROM chapter_versions", rows=rows),
                    ],
                )
                with self.assertRaises(DraftWriteError) as caught:
                    await make_service(FakePool([conn])).submit(command())
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.http_status, status)
                self.assertEqual(conn.rollback_calls, 1)
                self.assertFalse(any("INSERT INTO chapter_versions" in sql for sql, _ in conn.sql))

    async def test_service_rechecks_candidate_hash_before_inserts(self):
        original = command()
        invalid_write = replace(original.writes[0], content_sha256="0" * 64)
        invalid = replace(original, writes=(invalid_write, original.writes[1]))
        conn = FakeConnection(
            database_name=SCHEMA,
            executions=success_executions()[:4],
        )
        with self.assertRaises(DraftWriteError) as caught:
            await make_service(FakePool([conn])).submit(invalid)
        self.assertEqual(caught.exception.code, "candidate_content_hash_mismatch")
        self.assertEqual(caught.exception.http_status, 422)
        self.assertEqual(conn.rollback_calls, 1)

    async def test_test_hook_failure_after_first_insert_rolls_back_all(self):
        calls = []

        async def fail_after_first(index):
            calls.append(index)
            if index == 1:
                raise RuntimeError("test-only failure")

        conn = FakeConnection(
            database_name=SCHEMA,
            executions=success_executions()[:5],
        )
        with self.assertRaises(RuntimeError):
            await make_service(FakePool([conn]), hook=fail_after_first).submit(command())
        self.assertEqual(calls, [1])
        self.assertEqual(conn.rollback_calls, 1)
        self.assertEqual(conn.commit_calls, 0)

    async def test_1062_uses_new_current_read_transaction_for_committed_replay(self):
        submitted = command()
        stored = {
            "batchId": "existing-batch",
            "projectId": "project-1",
            "manifestSha256": submitted.manifest_sha256,
            "candidateVersionIds": ["existing-1", "existing-2"],
            "committedAt": 1699999999999,
        }
        first = FakeConnection(
            database_name=SCHEMA,
            executions=[
                ExpectedExecution("FROM projects", rows=[project_row()]),
                ExpectedExecution("INSERT INTO draft_write_batches", error=FakeMySQLError(1062, "duplicate unsafe")),
            ],
        )
        second = FakeConnection(
            database_name=SCHEMA,
            executions=[
                ExpectedExecution(
                    "FROM draft_write_batches",
                    rows=[{
                        "id": "existing-batch",
                        "project_id": "project-1",
                        "manifest_sha256": submitted.manifest_sha256,
                        "result_json": json.dumps(stored),
                        "committed_at": stored["committedAt"],
                    }],
                )
            ],
        )
        pool = FakePool([first, second])
        result = await make_service(pool).submit(submitted)
        self.assertEqual(result.to_wire(), stored)
        self.assertEqual(pool.acquire_calls, 2)
        self.assertEqual(first.rollback_calls, 1)
        self.assertEqual(second.commit_calls, 1)

    async def test_1062_replay_requires_result_to_cross_match_complete_ledger_row(self):
        submitted = command()
        base_result = {
            "batchId": "existing-batch",
            "projectId": "project-1",
            "manifestSha256": submitted.manifest_sha256,
            "candidateVersionIds": ["existing-1", "existing-2"],
            "committedAt": 1699999999999,
        }
        base_row = {
            "id": "existing-batch",
            "project_id": "project-1",
            "manifest_sha256": submitted.manifest_sha256,
            "result_json": base_result,
            "committed_at": 1699999999999,
        }
        cases = [
            ("row id mismatch", {"id": "other-batch"}, {}),
            ("result batch mismatch", {}, {"batchId": "other-batch"}),
            ("row project mismatch", {"project_id": "other-project"}, {}),
            ("result project mismatch", {}, {"projectId": "other-project"}),
            ("result manifest mismatch", {}, {"manifestSha256": "0" * 64}),
            ("row committed null", {"committed_at": None}, {}),
            ("row committed bool", {"committed_at": True}, {"committedAt": True}),
            ("row committed string", {"committed_at": "1699999999999"}, {}),
            ("row committed mismatch", {"committed_at": 1700000000000}, {}),
            ("result committed mismatch", {}, {"committedAt": 1700000000000}),
            (
                "duplicate candidate version ids",
                {},
                {"candidateVersionIds": ["existing-1", "existing-1"]},
            ),
        ]

        for name, row_changes, result_changes in cases:
            with self.subTest(name):
                result_json = {**base_result, **result_changes}
                row = {**base_row, **row_changes, "result_json": result_json}
                first = FakeConnection(
                    database_name=SCHEMA,
                    executions=[
                        ExpectedExecution("FROM projects", rows=[project_row()]),
                        ExpectedExecution(
                            "INSERT INTO draft_write_batches",
                            error=FakeMySQLError(1062, "unsafe"),
                        ),
                    ],
                )
                second = FakeConnection(
                    database_name=SCHEMA,
                    executions=[ExpectedExecution("FROM draft_write_batches", rows=[row])],
                )
                with self.assertRaises(DraftWriteError) as caught:
                    await make_service(FakePool([first, second])).submit(submitted)
                self.assertEqual(caught.exception.code, "idempotency_in_progress")
                self.assertEqual(caught.exception.http_status, 409)
                self.assertTrue(caught.exception.retryable)
                self.assertEqual(second.rollback_calls, 1)

    async def test_1062_replay_maps_conflict_absent_and_incomplete(self):
        submitted = command()
        cases = [
            (
                "different hash",
                [{"manifest_sha256": "0" * 64, "result_json": None}],
                "idempotency_manifest_conflict",
                False,
            ),
            ("absent", [], "idempotency_in_progress", True),
            (
                "incomplete",
                [{"manifest_sha256": submitted.manifest_sha256, "result_json": None}],
                "idempotency_in_progress",
                True,
            ),
        ]
        for name, rows, code, retryable in cases:
            with self.subTest(name):
                first = FakeConnection(
                    database_name=SCHEMA,
                    executions=[
                        ExpectedExecution("FROM projects", rows=[project_row()]),
                        ExpectedExecution("INSERT INTO draft_write_batches", error=FakeMySQLError(1062, "unsafe")),
                    ],
                )
                second = FakeConnection(
                    database_name=SCHEMA,
                    executions=[ExpectedExecution("FROM draft_write_batches", rows=rows)],
                )
                pool = FakePool([first, second])
                with self.assertRaises(DraftWriteError) as caught:
                    await make_service(pool).submit(submitted)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.http_status, 409)
                self.assertEqual(caught.exception.retryable, retryable)
                self.assertEqual(pool.acquire_calls, 2)
                self.assertEqual(second.rollback_calls, 1)

    async def test_1205_and_1213_map_after_rollback_without_retry(self):
        for number, code in [(1205, "idempotency_in_progress"), (1213, "transaction_retryable_conflict")]:
            with self.subTest(number=number):
                conn = FakeConnection(
                    database_name=SCHEMA,
                    executions=[
                        ExpectedExecution("FROM projects", rows=[project_row()]),
                        ExpectedExecution("INSERT INTO draft_write_batches", error=FakeMySQLError(number, "unsafe")),
                    ],
                )
                pool = FakePool([conn])
                with self.assertRaises(DraftWriteError) as caught:
                    await make_service(pool).submit(command())
                self.assertEqual(caught.exception.code, code)
                self.assertTrue(caught.exception.retryable)
                self.assertEqual(conn.rollback_calls, 1)
                self.assertEqual(pool.acquire_calls, 1)

    async def test_commit_operation_is_forwarded_only_as_constructor_dependency(self):
        conn = FakeConnection(database_name=SCHEMA, executions=success_executions())
        pool = FakePool([conn])
        seen = []

        async def commit_operation(active):
            seen.append(active)

        await make_service(pool, commit_operation=commit_operation).submit(command())
        self.assertEqual(seen, [conn])
        self.assertEqual(conn.commit_calls, 0)


if __name__ == "__main__":
    unittest.main()
