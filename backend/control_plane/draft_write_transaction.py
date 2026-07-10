"""Explicit single-connection transaction lifecycle for disposable pools."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncContextManager, AsyncIterator, Awaitable, Callable, Protocol, runtime_checkable

from .draft_write_errors import (
    CommitOutcomeUnknown,
    TransactionOutcomeUnknown,
    UnsafeDisposableDatabase,
    mysql_error_number,
)


@runtime_checkable
class ConnectionLike(Protocol):
    closed: bool

    def cursor(self, *args, **kwargs) -> AsyncContextManager[object]: ...
    def get_autocommit(self) -> bool: ...
    async def autocommit(self, value: bool) -> None: ...
    async def begin(self) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    def close(self) -> None: ...


@runtime_checkable
class PoolLike(Protocol):
    def acquire(self) -> AsyncContextManager[ConnectionLike]: ...


def is_commit_outcome_unknown(error: BaseException) -> bool:
    """Return true for cancellation or transport failures that make COMMIT ambiguous."""

    return (
        isinstance(error, (asyncio.CancelledError, OSError))
        or mysql_error_number(error) in {2006, 2013, 2055}
    )


def _invalidate(conn: ConnectionLike) -> None:
    try:
        conn.close()
    except BaseException:
        pass


async def _restore_or_invalidate(conn: ConnectionLike, original_autocommit: bool) -> None:
    try:
        await conn.autocommit(original_autocommit)
    except asyncio.CancelledError:
        _invalidate(conn)
        raise
    except BaseException:
        _invalidate(conn)


async def _confirmed_rollback_or_unknown(conn: ConnectionLike) -> None:
    try:
        await conn.rollback()
    except BaseException:
        _invalidate(conn)
        raise TransactionOutcomeUnknown() from None


def _database_name(row: object) -> object:
    if isinstance(row, (tuple, list)) and row:
        return row[0]
    if isinstance(row, dict):
        if "DATABASE()" in row:
            return row["DATABASE()"]
        if row:
            return next(iter(row.values()))
    return None


@asynccontextmanager
async def read_committed_transaction(
    *,
    pool: PoolLike,
    expected_schema: str,
    commit_operation: Callable[[ConnectionLike], Awaitable[None]] | None = None,
) -> AsyncIterator[ConnectionLike]:
    """Validate the injected schema and yield one READ COMMITTED connection."""

    async with pool.acquire() as conn:
        original_autocommit = bool(conn.get_autocommit())
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT DATABASE()")
            selected = await cursor.fetchone()
        if _database_name(selected) != expected_schema:
            _invalidate(conn)
            raise UnsafeDisposableDatabase()

        try:
            await conn.autocommit(False)
        except BaseException:
            _invalidate(conn)
            raise

        try:
            async with conn.cursor() as cursor:
                await cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            await conn.begin()
            yield conn
        except BaseException:
            await _confirmed_rollback_or_unknown(conn)
            await _restore_or_invalidate(conn, original_autocommit)
            raise

        try:
            if commit_operation is None:
                await conn.commit()
            else:
                await commit_operation(conn)
        except BaseException as error:
            if is_commit_outcome_unknown(error):
                _invalidate(conn)
                raise CommitOutcomeUnknown() from None
            await _confirmed_rollback_or_unknown(conn)
            await _restore_or_invalidate(conn, original_autocommit)
            raise

        await _restore_or_invalidate(conn, original_autocommit)
