"""Explicit async database connection and transaction boundaries."""

import asyncio
from contextlib import asynccontextmanager

import aiomysql

from backend.config import current_runtime_configuration


_pool = None
_pool_lock = asyncio.Lock()


class DatabaseSession:
    """Operations bound to one acquired raw database connection."""

    def __init__(self, raw):
        self.raw = raw

    async def execute(self, sql, args=None):
        async with self.raw.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, args)
            return cursor.rowcount

    async def fetchone(self, sql, args=None):
        async with self.raw.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, args)
            return await cursor.fetchone()

    async def fetchall(self, sql, args=None):
        async with self.raw.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, args)
            return await cursor.fetchall()


class DatabaseUnavailable(RuntimeError):
    """A driver-level database operation could not be completed safely."""

    def __init__(self) -> None:
        super().__init__("Database is temporarily unavailable")


_DRIVER_UNAVAILABLE_ERRORS = (aiomysql.OperationalError, aiomysql.InterfaceError)


async def get_pool():
    global _pool
    if _pool is None:
        async with _pool_lock:
            if _pool is None:
                snapshot = current_runtime_configuration()
                _pool = await aiomysql.create_pool(
                    **snapshot.mysql_pool_options()
                )
    return _pool


async def close_pool():
    global _pool
    async with _pool_lock:
        pool = _pool
        _pool = None
        if pool is not None:
            pool.close()
            await pool.wait_closed()


@asynccontextmanager
async def connection():
    """Yield a session for independent operations and always release it."""
    pool = await get_pool()
    raw = await pool.acquire()
    try:
        yield DatabaseSession(raw)
    finally:
        pool.release(raw)


@asynccontextmanager
async def transaction():
    """Yield one session inside one explicit raw-connection transaction."""
    pool = await get_pool()
    raw = await pool.acquire()
    try:
        await raw.begin()
        session = DatabaseSession(raw)
        try:
            yield session
        except BaseException as body_error:
            try:
                await raw.rollback()
            except BaseException as rollback_error:
                raise BaseExceptionGroup(
                    "transaction body failed and rollback also failed",
                    [body_error, rollback_error],
                ) from body_error
            raise
        else:
            await raw.commit()
    finally:
        pool.release(raw)


@asynccontextmanager
async def read_only_transaction():
    """Yield one session inside an enforced MySQL read-only transaction."""
    raw = None
    pool = None
    try:
        try:
            pool = await get_pool()
            raw = await pool.acquire()
            session = DatabaseSession(raw)
            await session.execute("START TRANSACTION READ ONLY")
        except _DRIVER_UNAVAILABLE_ERRORS:
            raise DatabaseUnavailable() from None
        try:
            yield session
        except BaseException as body_error:
            try:
                await raw.rollback()
            except BaseException as rollback_error:
                if isinstance(body_error, _DRIVER_UNAVAILABLE_ERRORS):
                    raise DatabaseUnavailable() from None
                if isinstance(rollback_error, _DRIVER_UNAVAILABLE_ERRORS):
                    raise BaseExceptionGroup(
                        "read-only transaction body failed and rollback also failed",
                        [body_error, DatabaseUnavailable()],
                    ) from body_error
                raise BaseExceptionGroup(
                    "read-only transaction body failed and rollback also failed",
                    [body_error, rollback_error],
                ) from body_error
            if isinstance(body_error, _DRIVER_UNAVAILABLE_ERRORS):
                raise DatabaseUnavailable() from None
            raise
        else:
            try:
                await raw.commit()
            except _DRIVER_UNAVAILABLE_ERRORS:
                raise DatabaseUnavailable() from None
    finally:
        if raw is not None:
            pool.release(raw)


async def execute(sql, args=None):
    """Execute one independent statement and return its affected row count."""
    async with connection() as session:
        return await session.execute(sql, args)


async def fetchone(sql, args=None):
    """Fetch one row using one independent connection boundary."""
    async with connection() as session:
        return await session.fetchone(sql, args)


async def fetchall(sql, args=None):
    """Fetch all rows using one independent connection boundary."""
    async with connection() as session:
        return await session.fetchall(sql, args)
