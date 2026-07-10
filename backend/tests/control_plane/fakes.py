from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class FakeMySQLError(Exception):
    pass


@dataclass
class ExpectedExecution:
    contains: str
    rows: list[Any] = field(default_factory=list)
    rowcount: int | None = None
    error: BaseException | None = None


class FakeCursor:
    def __init__(self, connection: "FakeConnection"):
        self.connection = connection
        self.rows: list[Any] = []
        self.rowcount = 0
        self.lastrowid = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())
        self.connection.sql.append((normalized, params))
        self.connection.events.append(f"execute:{normalized}")
        if normalized.upper() == "SELECT DATABASE()":
            self.rows = [(self.connection.database_name,)]
            self.rowcount = 1
            return self.rowcount
        if normalized.upper() == "SET TRANSACTION ISOLATION LEVEL READ COMMITTED":
            self.rows = []
            self.rowcount = 0
            return self.rowcount
        if not self.connection.executions:
            raise AssertionError(f"Unexpected SQL: {normalized}")
        expected = self.connection.executions.pop(0)
        if expected.contains.lower() not in normalized.lower():
            raise AssertionError(
                f"Expected SQL containing {expected.contains!r}, got {normalized!r}"
            )
        if expected.error is not None:
            raise expected.error
        self.rows = list(expected.rows)
        self.rowcount = expected.rowcount if expected.rowcount is not None else len(self.rows)
        return self.rowcount

    async def fetchone(self):
        return self.rows[0] if self.rows else None

    async def fetchall(self):
        return list(self.rows)


class FakeConnection:
    def __init__(
        self,
        *,
        database_name: str,
        autocommit: bool = True,
        commit_error: BaseException | None = None,
        rollback_error: BaseException | None = None,
        restore_error: BaseException | None = None,
        executions: list[ExpectedExecution] | None = None,
    ):
        self.database_name = database_name
        self._autocommit = autocommit
        self.commit_error = commit_error
        self.rollback_error = rollback_error
        self.restore_error = restore_error
        self.executions = list(executions or [])
        self.events: list[str] = []
        self.sql: list[tuple[str, object]] = []
        self.begin_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0
        self.autocommit_changes: list[bool] = []
        self.closed = False
        self._restore_value = autocommit

    def cursor(self, *_args, **_kwargs):
        return FakeCursor(self)

    def get_autocommit(self):
        self.events.append("get_autocommit")
        return self._autocommit

    async def autocommit(self, value):
        value = bool(value)
        self.events.append(f"autocommit:{value}")
        self.autocommit_changes.append(value)
        if self.restore_error is not None and value == self._restore_value and len(self.autocommit_changes) > 1:
            raise self.restore_error
        self._autocommit = value

    async def begin(self):
        self.events.append("begin")
        self.begin_calls += 1

    async def commit(self):
        self.events.append("commit")
        self.commit_calls += 1
        if self.commit_error is not None:
            raise self.commit_error

    async def rollback(self):
        self.events.append("rollback")
        self.rollback_calls += 1
        if self.rollback_error is not None:
            raise self.rollback_error

    def close(self):
        self.events.append("close")
        self.closed = True


class FakeAcquireContext:
    def __init__(self, pool: "FakePool", connection: FakeConnection):
        self.pool = pool
        self.connection = connection

    async def __aenter__(self):
        self.pool.acquire_calls += 1
        self.pool.events.append("acquire")
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        self.pool.release_calls += 1
        reusable = not self.connection.closed
        self.pool.releases.append((self.connection, reusable))
        self.pool.events.append(f"release:{reusable}")
        return False


class FakePool:
    def __init__(self, connections: list[FakeConnection]):
        self.connections = list(connections)
        self.acquire_calls = 0
        self.release_calls = 0
        self.releases: list[tuple[FakeConnection, bool]] = []
        self.events: list[str] = []

    def acquire(self):
        if not self.connections:
            raise AssertionError("No scripted fake connection remains")
        return FakeAcquireContext(self, self.connections.pop(0))

    def was_returned_reusable(self, connection):
        return any(conn is connection and reusable for conn, reusable in self.releases)
