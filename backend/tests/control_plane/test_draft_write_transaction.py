import asyncio
import unittest

from backend.control_plane.draft_write_errors import (
    CommitOutcomeUnknown,
    DraftWriteError,
    TransactionOutcomeUnknown,
    UnsafeDisposableDatabase,
)
from backend.control_plane.draft_write_transaction import (
    is_commit_outcome_unknown,
    read_committed_transaction,
)
from fakes import FakeConnection, FakeMySQLError, FakePool


SCHEMA = "novel_creator_control_plane_disposable_run123"


class DraftWriteTransactionTest(unittest.IsolatedAsyncioTestCase):
    async def test_success_uses_exact_lifecycle_and_one_connection(self):
        conn = FakeConnection(database_name=SCHEMA)
        pool = FakePool([conn])
        yielded = None
        async with read_committed_transaction(pool=pool, expected_schema=SCHEMA) as active:
            yielded = active
        self.assertIs(yielded, conn)
        self.assertEqual(conn.begin_calls, 1)
        self.assertEqual(conn.commit_calls, 1)
        self.assertEqual(conn.rollback_calls, 0)
        self.assertEqual(conn.autocommit_changes, [False, True])
        self.assertEqual(
            [sql for sql, _ in conn.sql],
            ["SELECT DATABASE()", "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"],
        )
        self.assertTrue(pool.was_returned_reusable(conn))

    async def test_schema_is_checked_exactly_before_begin(self):
        conn = FakeConnection(database_name=SCHEMA + "_other")
        pool = FakePool([conn])
        with self.assertRaises(UnsafeDisposableDatabase):
            async with read_committed_transaction(pool=pool, expected_schema=SCHEMA):
                self.fail("must not yield")
        self.assertEqual(conn.begin_calls, 0)
        self.assertTrue(conn.closed)
        self.assertFalse(pool.was_returned_reusable(conn))

    async def test_body_error_rolls_back_once_and_restores_before_propagating(self):
        conn = FakeConnection(database_name=SCHEMA)
        pool = FakePool([conn])
        domain_error = DraftWriteError("chapter_finalized", 409, "Chapter is finalized.")
        with self.assertRaises(DraftWriteError) as caught:
            async with read_committed_transaction(pool=pool, expected_schema=SCHEMA):
                raise domain_error
        self.assertIs(caught.exception, domain_error)
        self.assertEqual(conn.commit_calls, 0)
        self.assertEqual(conn.rollback_calls, 1)
        self.assertEqual(conn.autocommit_changes, [False, True])
        self.assertTrue(pool.was_returned_reusable(conn))

    async def test_commit_transport_failure_is_unknown_without_rollback(self):
        for error in [
            ConnectionError("lost"),
            OSError("socket lost"),
            FakeMySQLError(2006, "gone"),
            FakeMySQLError(2013, "lost"),
            FakeMySQLError(2055, "lost"),
        ]:
            with self.subTest(error=repr(error)):
                conn = FakeConnection(database_name=SCHEMA, commit_error=error)
                pool = FakePool([conn])
                with self.assertRaises(CommitOutcomeUnknown):
                    async with read_committed_transaction(pool=pool, expected_schema=SCHEMA):
                        pass
                self.assertEqual(conn.rollback_calls, 0)
                self.assertTrue(conn.closed)
                self.assertFalse(pool.was_returned_reusable(conn))

    async def test_commit_cancellation_is_unknown_without_rollback(self):
        conn = FakeConnection(database_name=SCHEMA)
        pool = FakePool([conn])

        async def cancelled_commit(_active):
            raise asyncio.CancelledError()

        with self.assertRaises(CommitOutcomeUnknown):
            async with read_committed_transaction(
                pool=pool,
                expected_schema=SCHEMA,
                commit_operation=cancelled_commit,
            ):
                pass
        self.assertEqual(conn.rollback_calls, 0)
        self.assertTrue(conn.closed)
        self.assertFalse(pool.was_returned_reusable(conn))

    async def test_known_mysql_commit_errors_attempt_confirmed_rollback(self):
        for number in [1205, 1213, 1064]:
            with self.subTest(number=number):
                error = FakeMySQLError(number, "unsafe detail")
                conn = FakeConnection(database_name=SCHEMA, commit_error=error)
                pool = FakePool([conn])
                with self.assertRaises(FakeMySQLError) as caught:
                    async with read_committed_transaction(pool=pool, expected_schema=SCHEMA):
                        pass
                self.assertIs(caught.exception, error)
                self.assertEqual(conn.rollback_calls, 1)
                self.assertEqual(conn.autocommit_changes, [False, True])
                self.assertTrue(pool.was_returned_reusable(conn))

    async def test_rollback_failure_invalidates_and_maps_unknown(self):
        conn = FakeConnection(
            database_name=SCHEMA,
            rollback_error=ConnectionError("lost during rollback"),
        )
        pool = FakePool([conn])
        with self.assertRaises(TransactionOutcomeUnknown):
            async with read_committed_transaction(pool=pool, expected_schema=SCHEMA):
                raise RuntimeError("precommit")
        self.assertEqual(conn.rollback_calls, 1)
        self.assertTrue(conn.closed)
        self.assertFalse(pool.was_returned_reusable(conn))

    async def test_known_commit_error_with_rollback_failure_maps_transaction_unknown(self):
        conn = FakeConnection(
            database_name=SCHEMA,
            commit_error=FakeMySQLError(1213, "deadlock"),
            rollback_error=ConnectionError("lost during rollback"),
        )
        pool = FakePool([conn])
        with self.assertRaises(TransactionOutcomeUnknown):
            async with read_committed_transaction(pool=pool, expected_schema=SCHEMA):
                pass
        self.assertEqual(conn.rollback_calls, 1)
        self.assertTrue(conn.closed)

    async def test_restore_failure_discards_connection_after_confirmed_commit(self):
        conn = FakeConnection(
            database_name=SCHEMA,
            restore_error=ConnectionError("cannot restore"),
        )
        pool = FakePool([conn])
        async with read_committed_transaction(pool=pool, expected_schema=SCHEMA):
            pass
        self.assertEqual(conn.commit_calls, 1)
        self.assertEqual(conn.rollback_calls, 0)
        self.assertTrue(conn.closed)
        self.assertFalse(pool.was_returned_reusable(conn))

    async def test_restore_failure_discards_connection_after_confirmed_rollback(self):
        conn = FakeConnection(
            database_name=SCHEMA,
            restore_error=ConnectionError("cannot restore"),
        )
        pool = FakePool([conn])
        body_error = RuntimeError("body")
        with self.assertRaises(RuntimeError) as caught:
            async with read_committed_transaction(pool=pool, expected_schema=SCHEMA):
                raise body_error
        self.assertIs(caught.exception, body_error)
        self.assertEqual(conn.rollback_calls, 1)
        self.assertTrue(conn.closed)

    async def test_restore_cancellation_after_confirmed_commit_is_rethrown(self):
        conn = FakeConnection(
            database_name=SCHEMA,
            restore_error=asyncio.CancelledError(),
        )
        pool = FakePool([conn])
        with self.assertRaises(asyncio.CancelledError):
            async with read_committed_transaction(pool=pool, expected_schema=SCHEMA):
                pass
        self.assertEqual(conn.commit_calls, 1)
        self.assertEqual(conn.rollback_calls, 0)
        self.assertTrue(conn.closed)
        self.assertFalse(pool.was_returned_reusable(conn))

    async def test_restore_cancellation_after_confirmed_rollback_is_rethrown(self):
        conn = FakeConnection(
            database_name=SCHEMA,
            restore_error=asyncio.CancelledError(),
        )
        pool = FakePool([conn])
        with self.assertRaises(asyncio.CancelledError):
            async with read_committed_transaction(pool=pool, expected_schema=SCHEMA):
                raise RuntimeError("body")
        self.assertEqual(conn.commit_calls, 0)
        self.assertEqual(conn.rollback_calls, 1)
        self.assertTrue(conn.closed)
        self.assertFalse(pool.was_returned_reusable(conn))

    async def test_injected_commit_operation_receives_the_same_connection(self):
        conn = FakeConnection(database_name=SCHEMA)
        pool = FakePool([conn])
        calls = []

        async def commit_operation(active):
            calls.append(active)

        async with read_committed_transaction(
            pool=pool,
            expected_schema=SCHEMA,
            commit_operation=commit_operation,
        ) as active:
            self.assertIs(active, conn)
        self.assertEqual(calls, [conn])
        self.assertEqual(conn.commit_calls, 0)

    def test_commit_unknown_classifier_is_narrow(self):
        for error in [
            asyncio.CancelledError(),
            ConnectionError(),
            OSError(),
            FakeMySQLError(2006),
            FakeMySQLError(2013),
            FakeMySQLError(2055),
        ]:
            with self.subTest(repr(error)):
                self.assertTrue(is_commit_outcome_unknown(error))
        for error in [RuntimeError(), FakeMySQLError(1205), FakeMySQLError(1213), FakeMySQLError(1064)]:
            with self.subTest(repr(error)):
                self.assertFalse(is_commit_outcome_unknown(error))

    async def test_preserves_original_false_autocommit(self):
        conn = FakeConnection(database_name=SCHEMA, autocommit=False)
        pool = FakePool([conn])
        async with read_committed_transaction(pool=pool, expected_schema=SCHEMA):
            pass
        self.assertEqual(conn.autocommit_changes, [False, False])


if __name__ == "__main__":
    unittest.main()
