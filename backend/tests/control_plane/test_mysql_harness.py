from __future__ import annotations

import asyncio
import ast
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.tests.control_plane import mysql_harness
from backend.tests.control_plane.mysql_harness import (
    HarnessConfigurationError,
    disposable_mysql,
    extract_created_tables,
    load_and_validate_minimal_fixture,
    parse_admin_dsn,
    schema_name_for_token,
    validate_schema_identity,
)


class MySQLHarnessGuardTest(unittest.TestCase):
    def test_rejects_product_database_path_before_connect(self):
        with self.assertRaisesRegex(HarnessConfigurationError, "safely configured"):
            parse_admin_dsn("mysql://root:secret@127.0.0.1:3306/novel_creator")

    def test_accepts_only_loopback_admin_dsn_without_suffixes(self):
        cases = [
            ("mysql://root:secret@localhost:3306", "localhost", 3306),
            ("mysql://root:secret@127.0.0.1", "127.0.0.1", 3306),
            ("mysql://root:secret@[::1]:3307", "::1", 3307),
        ]
        for raw, host, port in cases:
            with self.subTest(raw=raw):
                parsed = parse_admin_dsn(raw)
                self.assertEqual((parsed.host, parsed.port, parsed.user, parsed.password), (host, port, "root", "secret"))
                self.assertNotIn("secret", repr(parsed))

    def test_rejects_unsafe_admin_dsn_shapes_with_fixed_safe_error(self):
        cases = [
            None,
            "",
            "postgresql://root:secret@127.0.0.1:3306",
            "mysql://root:secret@example.com:3306",
            "mysql://:secret@127.0.0.1:3306",
            "mysql://127.0.0.1:3306",
            "mysql://root:secret@127.0.0.1:3306/database",
            "mysql://root:secret@127.0.0.1:3306/",
            "mysql://root:secret@127.0.0.1:3306?charset=utf8mb4",
            "mysql://root:secret@127.0.0.1:3306?",
            "mysql://root:secret@127.0.0.1:3306#fragment",
            "mysql://root:secret@127.0.0.1:3306#",
            "mysql:///tmp/mysql.sock",
            "mysql://root:secret@127.0.0.1:notaport",
            "mysql://root:secret@127.0.0.1:70000",
            "mysql://root:secret@127.0.0.1:0",
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(HarnessConfigurationError, "^The disposable database harness was not safely configured\\.$") as caught:
                    parse_admin_dsn(raw)  # type: ignore[arg-type]
                self.assertNotIn("secret", str(caught.exception))

    def test_schema_name_is_exactly_bound_to_token(self):
        token = "a" * 24
        self.assertEqual(schema_name_for_token(token), "novel_creator_control_plane_disposable_" + token)
        validate_schema_identity("novel_creator_control_plane_disposable_" + token, token)

    def test_rejects_malformed_token_and_schema_identity(self):
        bad_tokens = ["", "a" * 23, "a" * 25, "A" * 24, "g" * 24, "a" * 23 + "-"]
        for token in bad_tokens:
            with self.subTest(token=token):
                with self.assertRaises(HarnessConfigurationError):
                    schema_name_for_token(token)
        token = "b" * 24
        for schema in [
            token,
            "novel_creator_control_plane_disposable_" + "a" * 24,
            "novel_creator_control_plane_disposable_" + token + "x",
            "novel_creator_" + token,
        ]:
            with self.subTest(schema=schema):
                with self.assertRaises(HarnessConfigurationError):
                    validate_schema_identity(schema, token)

    def test_fixture_has_only_three_allowed_tables(self):
        statements = load_and_validate_minimal_fixture()
        self.assertEqual(len(statements), 3)
        self.assertEqual(extract_created_tables(statements), {"projects", "chapters", "chapter_versions"})

    def test_fixture_text_columns_are_nullable_without_mysql57_incompatible_defaults(self):
        fixture = (Path(__file__).parent / "fixtures" / "control_plane_minimal_schema.sql").read_text(
            encoding="utf-8"
        )
        lowered = " ".join(fixture.lower().split())
        self.assertIn("content longtext null", lowered)
        self.assertIn("prompt_brief text null", lowered)
        self.assertNotIn("longtext default null", lowered)
        self.assertNotIn("text default null", lowered)

    def test_fixture_validator_rejects_forbidden_or_qualified_sql(self):
        safe = (Path(__file__).parent / "fixtures" / "control_plane_minimal_schema.sql").read_text(encoding="utf-8")
        cases = [
            safe.replace("CREATE TABLE projects", "CREATE TABLE IF NOT EXISTS projects", 1),
            safe + "\nCREATE DATABASE forbidden;",
            safe + "\nDROP DATABASE forbidden;",
            safe + "\nUSE forbidden;",
            safe + "\nALTER TABLE projects ADD COLUMN x INT;",
            safe.replace("CREATE TABLE projects", "CREATE TABLE other.projects", 1),
            safe.replace("CREATE TABLE chapters", "CREATE TABLE `other`.`chapters`", 1),
            safe.replace("CREATE TABLE chapter_versions", "CREATE TABLE extra", 1),
        ]
        for index, unsafe in enumerate(cases):
            with self.subTest(index=index):
                with tempfile.TemporaryDirectory() as temp_dir:
                    fixture = Path(temp_dir) / "fixture.sql"
                    fixture.write_text(unsafe, encoding="utf-8")
                    with patch.object(mysql_harness, "_MINIMAL_FIXTURE_PATH", fixture):
                        with self.assertRaises(HarnessConfigurationError):
                            load_and_validate_minimal_fixture()

    def test_fixture_identity_rejects_hidden_cross_schema_and_copy_constructs(self):
        safe = (Path(__file__).parent / "fixtures" / "control_plane_minimal_schema.sql").read_text(encoding="utf-8")
        cases = [
            safe.replace(
                "  updated_at BIGINT NOT NULL\n) ENGINE=InnoDB",
                "  updated_at BIGINT NOT NULL,\n  FOREIGN KEY (id) REFERENCES other.projects(id)\n) ENGINE=InnoDB",
                1,
            ),
            safe.replace(
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;",
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci "
                "AS SELECT id, created_at, updated_at FROM other.projects;",
                1,
            ),
            safe.replace(
                safe.split(";", 1)[0] + ";",
                "CREATE TABLE projects LIKE other.projects;",
                1,
            ),
            safe.replace("CREATE TABLE projects (", "CREATE TABLE projects (\n  /*!50000 id INT */,", 1),
        ]
        for index, unsafe in enumerate(cases):
            with self.subTest(index=index):
                with tempfile.TemporaryDirectory() as temp_dir:
                    fixture = Path(temp_dir) / "fixture.sql"
                    fixture.write_text(unsafe, encoding="utf-8")
                    with patch.object(mysql_harness, "_MINIMAL_FIXTURE_PATH", fixture):
                        with self.assertRaises(HarnessConfigurationError):
                            load_and_validate_minimal_fixture()

    def test_apply_migration_identity_rejects_hidden_cross_schema_and_copy_constructs(self):
        migration_path = Path(__file__).parents[2] / "migrations" / "20260710_control_plane_draft_write_batches.sql"
        safe = migration_path.read_text(encoding="utf-8")
        cases = [
            safe.replace(
                "  PRIMARY KEY (id),",
                "  FOREIGN KEY (project_id) REFERENCES other.projects(id),\n  PRIMARY KEY (id),",
                1,
            ),
            safe.replace(
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;",
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci "
                "AS SELECT * FROM other.draft_write_batches;",
                1,
            ),
            "CREATE TABLE draft_write_batches LIKE other.draft_write_batches;\n",
            safe.replace("CREATE TABLE draft_write_batches (", "CREATE TABLE draft_write_batches (\n  /*!50000 hidden INT */,", 1),
        ]
        for index, unsafe in enumerate(cases):
            with self.subTest(index=index):
                with tempfile.TemporaryDirectory() as temp_dir:
                    migration = Path(temp_dir) / "apply.sql"
                    migration.write_text(unsafe, encoding="utf-8")
                    with patch.object(mysql_harness, "_APPLY_MIGRATION_PATH", migration):
                        with self.assertRaises(HarnessConfigurationError):
                            mysql_harness._load_apply_migration()


class _UnexpectedPoolFactory:
    def __init__(self):
        self.calls = 0

    async def __call__(self, **_kwargs):
        self.calls += 1
        raise AssertionError("network pool creation must not occur")


class MySQLHarnessPreconnectGuardTest(unittest.IsolatedAsyncioTestCase):
    async def test_missing_and_unsafe_dsn_never_call_pool_factory(self):
        unsafe_values = [
            None,
            "mysql://root:secret@127.0.0.1:3306/novel_creator",
            "mysql://root:secret@example.com:3306",
        ]
        for value in unsafe_values:
            with self.subTest(value=value):
                factory = _UnexpectedPoolFactory()
                environ = {} if value is None else {"CONTROL_PLANE_DISPOSABLE_MYSQL_DSN": value}
                with self.assertRaises(HarnessConfigurationError):
                    async with disposable_mysql(environ=environ, create_pool=factory):
                        self.fail("unsafe harness unexpectedly yielded")
                self.assertEqual(factory.calls, 0)


class _FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.connection.events.append(("execute", normalized, params))
        if "information_schema.schemata" in normalized:
            self.connection.schema_queries += 1
            if params:
                self.connection.schema_name = params[0]
            if self.connection.fail_reconciliation and self.connection.schema_queries > 1:
                raise RuntimeError("schema outcome reconciliation failed")
        if normalized.startswith("CREATE DATABASE"):
            if self.connection.create_lands:
                self.connection.schema_exists = True
            if self.connection.create_error is not None:
                raise self.connection.create_error
        if normalized.startswith("DROP DATABASE"):
            if self.connection.drop_error is not None:
                raise self.connection.drop_error
            self.connection.schema_exists = False

    async def fetchone(self):
        sql = self.connection.events[-1][1]
        if "information_schema.schemata" in sql:
            return (self.connection.schema_name,) if self.connection.schema_exists else None
        if sql == "SELECT DATABASE()":
            return (self.connection.selected_database,)
        raise AssertionError(f"unexpected fetchone for {sql}")


class _FakeConnection:
    def __init__(
        self,
        *,
        selected_database=None,
        schema_name=None,
        schema_exists=False,
        create_lands=False,
        create_error=None,
        fail_reconciliation=False,
        drop_error=None,
    ):
        self.selected_database = selected_database
        self.schema_name = schema_name
        self.schema_exists = schema_exists
        self.create_lands = create_lands
        self.create_error = create_error
        self.fail_reconciliation = fail_reconciliation
        self.drop_error = drop_error
        self.schema_queries = 0
        self.events = []

    def cursor(self, *_args):
        return _FakeCursor(self)


class _FakeAcquire:
    def __init__(self, connection, events, label):
        self.connection = connection
        self.events = events
        self.label = label

    async def __aenter__(self):
        self.events.append(f"{self.label}:acquire")
        return self.connection

    async def __aexit__(self, *_args):
        self.events.append(f"{self.label}:release")
        return False


class _FakePool:
    def __init__(self, *, label, connection, events, close_error=None):
        self.label = label
        self.connection = connection
        self.events = events
        self.close_error = close_error

    def acquire(self):
        return _FakeAcquire(self.connection, self.events, self.label)

    def close(self):
        self.events.append(f"{self.label}:close")

    async def wait_closed(self):
        self.events.append(f"{self.label}:wait_closed")
        if self.close_error is not None:
            raise self.close_error


class _PoolFactory:
    def __init__(
        self,
        *,
        schema_exists=False,
        selected_database=None,
        fail_drop=False,
        fail_data_close=False,
        fail_admin_create=False,
        fail_data_create=False,
        create_error_mode=None,
        fail_reconciliation=False,
        cancel_drop=False,
        fail_admin_close=False,
        cancel_data_close=False,
    ):
        self.events = []
        self.calls = []
        self.schema_exists = schema_exists
        self.selected_database = selected_database
        self.fail_drop = fail_drop
        self.fail_data_close = fail_data_close
        self.fail_admin_create = fail_admin_create
        self.fail_data_create = fail_data_create
        self.create_error_mode = create_error_mode
        self.fail_reconciliation = fail_reconciliation
        self.cancel_drop = cancel_drop
        self.fail_admin_close = fail_admin_close
        self.cancel_data_close = cancel_data_close
        self.admin_pool = None
        self.data_pool = None

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if "db" not in kwargs:
            if self.fail_admin_create:
                raise RuntimeError("super-secret admin pool failure")
            create_error = None
            create_lands = False
            if self.create_error_mode == "after":
                create_error = ConnectionError("create outcome unknown")
                create_lands = True
            elif self.create_error_mode == "before":
                create_error = ConnectionError("create did not land")
            connection = _FakeConnection(
                schema_exists=self.schema_exists,
                create_lands=create_lands,
                create_error=create_error,
                fail_reconciliation=self.fail_reconciliation,
                drop_error=(
                    asyncio.CancelledError("drop cancelled")
                    if self.cancel_drop
                    else RuntimeError("drop failed") if self.fail_drop else None
                ),
            )
            self.admin_pool = _FakePool(
                label="admin",
                connection=connection,
                events=self.events,
                close_error=RuntimeError("admin close failed") if self.fail_admin_close else None,
            )
            return self.admin_pool
        if self.fail_data_create:
            raise RuntimeError("super-secret data pool failure")
        selected = kwargs["db"] if self.selected_database is None else self.selected_database
        connection = _FakeConnection(selected_database=selected)
        self.data_pool = _FakePool(
            label="data",
            connection=connection,
            events=self.events,
            close_error=(
                asyncio.CancelledError("data close cancelled")
                if self.cancel_data_close
                else RuntimeError("data close failed") if self.fail_data_close else None
            ),
        )
        return self.data_pool


def _leaf_errors(error: BaseException) -> list[BaseException]:
    if isinstance(error, BaseExceptionGroup):
        leaves = []
        for nested in error.exceptions:
            leaves.extend(_leaf_errors(nested))
        return leaves
    return [error]


class MySQLHarnessLifecycleTest(unittest.IsolatedAsyncioTestCase):
    DSN = "mysql://admin:super-secret@127.0.0.1:3306"
    TOKEN = "c" * 24
    SCHEMA = "novel_creator_control_plane_disposable_" + TOKEN

    async def test_creates_applies_yields_and_drops_exact_generated_schema_in_order(self):
        factory = _PoolFactory()
        output = io.StringIO()
        with patch.object(mysql_harness, "new_run_token", return_value=self.TOKEN):
            with contextlib.redirect_stdout(output):
                async with disposable_mysql(
                    environ={"CONTROL_PLANE_DISPOSABLE_MYSQL_DSN": self.DSN},
                    create_pool=factory,
                ) as disposable:
                    self.assertEqual(disposable.schema_name, self.SCHEMA)
                    self.assertEqual(disposable.run_token, self.TOKEN)
                    self.assertIs(disposable.pool, factory.data_pool)
                    factory.events.append("yield")

        self.assertEqual(len(factory.calls), 2)
        self.assertNotIn("db", factory.calls[0])
        self.assertEqual(factory.calls[1]["db"], self.SCHEMA)
        self.assertEqual(factory.calls[0]["autocommit"], True)
        self.assertEqual(factory.calls[1]["autocommit"], True)
        drop_acquire_index = max(index for index, event in enumerate(factory.events) if event == "admin:acquire")
        self.assertLess(factory.events.index("data:close"), drop_acquire_index)
        self.assertLess(factory.events.index("yield"), factory.events.index("data:close"))
        self.assertEqual(factory.events[-2:], ["admin:close", "admin:wait_closed"])

        admin_sql = factory.admin_pool.connection.events
        self.assertIn("information_schema.schemata", admin_sql[0][1])
        self.assertEqual(admin_sql[0][2], (self.SCHEMA,))
        self.assertTrue(admin_sql[1][1].startswith(f"CREATE DATABASE `{self.SCHEMA}`"))
        self.assertEqual(admin_sql[-1][1], f"DROP DATABASE `{self.SCHEMA}`")

        data_sql = factory.data_pool.connection.events
        selected_checks = [entry for entry in data_sql if entry[1] == "SELECT DATABASE()"]
        self.assertGreaterEqual(len(selected_checks), 4)
        created_tables = extract_created_tables([entry[1] for entry in data_sql if entry[1].startswith("CREATE TABLE")])
        self.assertEqual(created_tables, {"projects", "chapters", "chapter_versions", "draft_write_batches"})

        text = output.getvalue()
        self.assertIn(f"CONTROL_PLANE_DISPOSABLE_SCHEMA_CREATED={self.SCHEMA}", text)
        self.assertIn(f"CONTROL_PLANE_DISPOSABLE_SCHEMA_DROPPED={self.SCHEMA}", text)
        self.assertNotIn("super-secret", text)
        self.assertNotIn(self.DSN, text)

    async def test_existing_schema_fails_closed_then_closes_admin_without_data_pool(self):
        factory = _PoolFactory(schema_exists=True)
        with patch.object(mysql_harness, "new_run_token", return_value=self.TOKEN):
            with self.assertRaises(HarnessConfigurationError):
                async with disposable_mysql(
                    environ={"CONTROL_PLANE_DISPOSABLE_MYSQL_DSN": self.DSN},
                    create_pool=factory,
                ):
                    self.fail("existing schema unexpectedly yielded")
        self.assertEqual(len(factory.calls), 1)
        self.assertIsNone(factory.data_pool)
        self.assertEqual(factory.events[-2:], ["admin:close", "admin:wait_closed"])
        self.assertFalse(any(event[1].startswith("CREATE DATABASE") for event in factory.admin_pool.connection.events))

    async def test_create_that_lands_then_loses_ack_is_reconciled_and_dropped(self):
        factory = _PoolFactory(create_error_mode="after")
        output = io.StringIO()
        with patch.object(mysql_harness, "new_run_token", return_value=self.TOKEN):
            with contextlib.redirect_stdout(output):
                with self.assertRaisesRegex(ConnectionError, "create outcome unknown"):
                    async with disposable_mysql(
                        environ={"CONTROL_PLANE_DISPOSABLE_MYSQL_DSN": self.DSN},
                        create_pool=factory,
                    ):
                        self.fail("ambiguous create unexpectedly yielded")
        admin = factory.admin_pool.connection
        self.assertEqual(admin.schema_queries, 2)
        self.assertTrue(any(event[1] == f"DROP DATABASE `{self.SCHEMA}`" for event in admin.events))
        self.assertEqual(factory.events[-2:], ["admin:close", "admin:wait_closed"])
        self.assertIn(f"CONTROL_PLANE_DISPOSABLE_SCHEMA_CREATED={self.SCHEMA}", output.getvalue())
        self.assertIn(f"CONTROL_PLANE_DISPOSABLE_SCHEMA_DROPPED={self.SCHEMA}", output.getvalue())

    async def test_create_that_does_not_land_is_reconciled_without_drop(self):
        factory = _PoolFactory(create_error_mode="before")
        output = io.StringIO()
        with patch.object(mysql_harness, "new_run_token", return_value=self.TOKEN):
            with contextlib.redirect_stdout(output):
                with self.assertRaisesRegex(ConnectionError, "create did not land"):
                    async with disposable_mysql(
                        environ={"CONTROL_PLANE_DISPOSABLE_MYSQL_DSN": self.DSN},
                        create_pool=factory,
                    ):
                        self.fail("failed create unexpectedly yielded")
        admin = factory.admin_pool.connection
        self.assertEqual(admin.schema_queries, 2)
        self.assertFalse(any(event[1].startswith("DROP DATABASE") for event in admin.events))
        self.assertNotIn("CONTROL_PLANE_DISPOSABLE_SCHEMA_", output.getvalue())
        self.assertEqual(factory.events[-2:], ["admin:close", "admin:wait_closed"])

    async def test_unconfirmable_create_reports_orphan_and_preserves_both_errors(self):
        factory = _PoolFactory(create_error_mode="after", fail_reconciliation=True)
        output = io.StringIO()
        with patch.object(mysql_harness, "new_run_token", return_value=self.TOKEN):
            with contextlib.redirect_stdout(output):
                with self.assertRaises(BaseExceptionGroup) as caught:
                    async with disposable_mysql(
                        environ={"CONTROL_PLANE_DISPOSABLE_MYSQL_DSN": self.DSN},
                        create_pool=factory,
                    ):
                        self.fail("unconfirmed create unexpectedly yielded")
        leaves = _leaf_errors(caught.exception)
        self.assertEqual({str(error) for error in leaves}, {"create outcome unknown", "schema outcome reconciliation failed"})
        self.assertIn(f"CONTROL_PLANE_DISPOSABLE_SCHEMA_ORPHAN={self.SCHEMA}", output.getvalue())
        self.assertFalse(any(event[1].startswith("DROP DATABASE") for event in factory.admin_pool.connection.events))
        self.assertEqual(factory.events[-2:], ["admin:close", "admin:wait_closed"])

    async def test_admin_pool_creation_failure_is_sanitized(self):
        factory = _PoolFactory(fail_admin_create=True)
        with self.assertRaises(HarnessConfigurationError) as caught:
            async with disposable_mysql(
                environ={"CONTROL_PLANE_DISPOSABLE_MYSQL_DSN": self.DSN},
                create_pool=factory,
            ):
                self.fail("failed pool unexpectedly yielded")
        self.assertNotIn("super-secret", str(caught.exception))
        self.assertNotIn(self.DSN, str(caught.exception))
        self.assertEqual(len(factory.calls), 1)

    async def test_data_pool_creation_failure_is_sanitized_and_drops_schema(self):
        factory = _PoolFactory(fail_data_create=True)
        output = io.StringIO()
        with patch.object(mysql_harness, "new_run_token", return_value=self.TOKEN):
            with contextlib.redirect_stdout(output):
                with self.assertRaises(HarnessConfigurationError) as caught:
                    async with disposable_mysql(
                        environ={"CONTROL_PLANE_DISPOSABLE_MYSQL_DSN": self.DSN},
                        create_pool=factory,
                    ):
                        self.fail("failed pool unexpectedly yielded")
        self.assertNotIn("super-secret", str(caught.exception))
        self.assertNotIn(self.DSN, str(caught.exception))
        self.assertEqual(factory.admin_pool.connection.events[-1][1], f"DROP DATABASE `{self.SCHEMA}`")
        self.assertIn(f"CONTROL_PLANE_DISPOSABLE_SCHEMA_DROPPED={self.SCHEMA}", output.getvalue())

    async def test_database_identity_mismatch_drops_created_schema_and_never_yields(self):
        factory = _PoolFactory(selected_database="wrong_database")
        output = io.StringIO()
        with patch.object(mysql_harness, "new_run_token", return_value=self.TOKEN):
            with contextlib.redirect_stdout(output):
                with self.assertRaisesRegex(HarnessConfigurationError, "identity mismatch"):
                    async with disposable_mysql(
                        environ={"CONTROL_PLANE_DISPOSABLE_MYSQL_DSN": self.DSN},
                        create_pool=factory,
                    ):
                        self.fail("identity mismatch unexpectedly yielded")
        self.assertIn(f"CONTROL_PLANE_DISPOSABLE_SCHEMA_DROPPED={self.SCHEMA}", output.getvalue())
        self.assertEqual(factory.admin_pool.connection.events[-1][1], f"DROP DATABASE `{self.SCHEMA}`")

    async def test_drop_failure_reports_orphan_and_still_closes_both_pools(self):
        factory = _PoolFactory(fail_drop=True)
        output = io.StringIO()
        with patch.object(mysql_harness, "new_run_token", return_value=self.TOKEN):
            with contextlib.redirect_stdout(output):
                with self.assertRaisesRegex(RuntimeError, "drop failed"):
                    async with disposable_mysql(
                        environ={"CONTROL_PLANE_DISPOSABLE_MYSQL_DSN": self.DSN},
                        create_pool=factory,
                    ):
                        pass
        self.assertIn(f"CONTROL_PLANE_DISPOSABLE_SCHEMA_ORPHAN={self.SCHEMA}", output.getvalue())
        self.assertEqual(factory.events[-2:], ["admin:close", "admin:wait_closed"])
        self.assertIn("data:wait_closed", factory.events)

    async def test_data_close_failure_still_drops_schema_and_closes_admin(self):
        factory = _PoolFactory(fail_data_close=True)
        output = io.StringIO()
        with patch.object(mysql_harness, "new_run_token", return_value=self.TOKEN):
            with contextlib.redirect_stdout(output):
                with self.assertRaisesRegex(RuntimeError, "data close failed"):
                    async with disposable_mysql(
                        environ={"CONTROL_PLANE_DISPOSABLE_MYSQL_DSN": self.DSN},
                        create_pool=factory,
                    ):
                        pass
        self.assertEqual(factory.admin_pool.connection.events[-1][1], f"DROP DATABASE `{self.SCHEMA}`")
        self.assertEqual(factory.events[-2:], ["admin:close", "admin:wait_closed"])

    async def test_body_and_all_cleanup_failures_are_preserved_after_every_cleanup_attempt(self):
        factory = _PoolFactory(fail_data_close=True, fail_drop=True, fail_admin_close=True)
        output = io.StringIO()
        with patch.object(mysql_harness, "new_run_token", return_value=self.TOKEN):
            with contextlib.redirect_stdout(output):
                with self.assertRaises(BaseExceptionGroup) as caught:
                    async with disposable_mysql(
                        environ={"CONTROL_PLANE_DISPOSABLE_MYSQL_DSN": self.DSN},
                        create_pool=factory,
                    ):
                        raise ValueError("body failed")
        leaves = _leaf_errors(caught.exception)
        self.assertEqual(
            {str(error) for error in leaves},
            {"body failed", "data close failed", "drop failed", "admin close failed"},
        )
        self.assertIn("data:wait_closed", factory.events)
        self.assertTrue(any(event[1].startswith("DROP DATABASE") for event in factory.admin_pool.connection.events))
        self.assertEqual(factory.events[-2:], ["admin:close", "admin:wait_closed"])
        self.assertIn(f"CONTROL_PLANE_DISPOSABLE_SCHEMA_ORPHAN={self.SCHEMA}", output.getvalue())

    async def test_data_close_cancellation_does_not_skip_drop_or_admin_close(self):
        factory = _PoolFactory(cancel_data_close=True)
        output = io.StringIO()
        with patch.object(mysql_harness, "new_run_token", return_value=self.TOKEN):
            with contextlib.redirect_stdout(output):
                with self.assertRaisesRegex(asyncio.CancelledError, "data close cancelled"):
                    async with disposable_mysql(
                        environ={"CONTROL_PLANE_DISPOSABLE_MYSQL_DSN": self.DSN},
                        create_pool=factory,
                    ):
                        pass
        self.assertEqual(factory.admin_pool.connection.events[-1][1], f"DROP DATABASE `{self.SCHEMA}`")
        self.assertEqual(factory.events[-2:], ["admin:close", "admin:wait_closed"])
        self.assertIn(f"CONTROL_PLANE_DISPOSABLE_SCHEMA_DROPPED={self.SCHEMA}", output.getvalue())

    async def test_drop_cancellation_reports_orphan_and_still_closes_admin(self):
        factory = _PoolFactory(cancel_drop=True)
        output = io.StringIO()
        with patch.object(mysql_harness, "new_run_token", return_value=self.TOKEN):
            with contextlib.redirect_stdout(output):
                with self.assertRaisesRegex(asyncio.CancelledError, "drop cancelled"):
                    async with disposable_mysql(
                        environ={"CONTROL_PLANE_DISPOSABLE_MYSQL_DSN": self.DSN},
                        create_pool=factory,
                    ):
                        pass
        self.assertIn(f"CONTROL_PLANE_DISPOSABLE_SCHEMA_ORPHAN={self.SCHEMA}", output.getvalue())
        self.assertEqual(factory.events[-2:], ["admin:close", "admin:wait_closed"])


class MySQLIntegrationModuleStaticContractTest(unittest.TestCase):
    def test_opt_in_module_contains_exactly_the_twelve_required_cases(self):
        path = Path(__file__).parent / "mysql_integration_test.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        methods = {
            node.name
            for item in tree.body
            if isinstance(item, ast.ClassDef) and item.name == "DisposableMySQLDraftWriteIntegrationTest"
            for node in item.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
        }
        self.assertEqual(
            methods,
            {
                "test_two_candidates_commit_together",
                "test_failure_after_first_candidate_rolls_back_ledger_and_candidates",
                "test_same_key_same_hash_replays_without_duplicates",
                "test_same_key_different_hash_conflicts_without_writes",
                "test_source_preimage_drift_conflicts_without_writes",
                "test_final_status_conflicts_without_writes",
                "test_final_version_pointer_conflicts_without_writes",
                "test_reverse_request_order_preserves_result_order_with_deterministic_locks",
                "test_concurrent_identical_submission_commits_one_batch",
                "test_migration_apply_and_rollback_are_contained_to_generated_schema",
                "test_commit_landed_outcome_unknown_replays_committed_result",
                "test_commit_not_landed_outcome_unknown_can_retry_cleanly",
            },
        )

    def test_opt_in_module_is_excluded_and_has_no_product_bootstrap_dependency(self):
        path = Path(__file__).parent / "mysql_integration_test.py"
        source = path.read_text(encoding="utf-8")
        self.assertFalse(path.name.startswith("test_"))
        for forbidden in [
            "backend.main",
            "backend.config",
            "backend.database",
            "MYSQL_CONFIG",
            "MYSQL_DB",
            "backend/schema.sql",
            "@unittest.skip",
            "@unittest.skipUnless",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
