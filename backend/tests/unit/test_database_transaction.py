import aiomysql
import pytest

from backend import database
from backend.tests.support.fakes import FakePool


def use_pool(monkeypatch, pool):
    async def fake_get_pool():
        return pool

    monkeypatch.setattr(database, "get_pool", fake_get_pool)


@pytest.mark.asyncio
async def test_database_session_operations_use_dict_cursors_and_same_raw():
    pool = FakePool()
    session = database.DatabaseSession(pool.raw)

    assert await session.execute("INSERT INTO x VALUES (%s)", (1,)) == 1
    assert await session.fetchone("SELECT one") == {"value": "one"}
    assert await session.fetchall("SELECT many") == [{"value": "many"}]

    assert len(pool.raw.opened_cursors) == 3
    assert pool.raw.closed_cursors == pool.raw.opened_cursors
    assert all(cursor.raw is pool.raw for cursor in pool.raw.opened_cursors)
    assert all(
        cursor.cursor_class is aiomysql.DictCursor
        for cursor in pool.raw.opened_cursors
    )


@pytest.mark.asyncio
async def test_transaction_commits_once_and_keeps_one_session_and_raw(monkeypatch):
    pool = FakePool()
    use_pool(monkeypatch, pool)

    async with database.transaction() as session:
        first_session = session
        assert session.raw is pool.raw
        await session.execute("INSERT INTO x VALUES (%s)", (1,))
        await session.fetchone("SELECT one")
        await session.fetchall("SELECT many")
        assert session is first_session

    assert pool.acquire_count == 1
    assert pool.raw.begin_count == 1
    assert pool.raw.commit_count == 1
    assert pool.raw.rollback_count == 0
    assert pool.release_count == 1
    assert pool.released == [pool.raw]
    assert all(cursor.raw is pool.raw for cursor in pool.raw.opened_cursors)


@pytest.mark.asyncio
async def test_transaction_body_error_rolls_back_and_releases(monkeypatch):
    pool = FakePool()
    use_pool(monkeypatch, pool)

    with pytest.raises(RuntimeError, match="projection failed"):
        async with database.transaction() as session:
            await session.execute("INSERT INTO x VALUES (%s)", (1,))
            raise RuntimeError("projection failed")

    assert pool.raw.commit_count == 0
    assert pool.raw.rollback_count == 1
    assert pool.release_count == 1


@pytest.mark.asyncio
async def test_transaction_begin_failure_still_releases(monkeypatch):
    pool = FakePool()
    pool.raw.begin_error = RuntimeError("begin failed")
    use_pool(monkeypatch, pool)

    with pytest.raises(RuntimeError, match="begin failed"):
        async with database.transaction():
            pytest.fail("transaction body must not run")

    assert pool.raw.begin_count == 1
    assert pool.raw.commit_count == 0
    assert pool.raw.rollback_count == 0
    assert pool.release_count == 1


@pytest.mark.asyncio
async def test_transaction_commit_failure_releases_without_rollback(monkeypatch):
    pool = FakePool()
    pool.raw.commit_error = RuntimeError("commit failed")
    use_pool(monkeypatch, pool)

    with pytest.raises(RuntimeError, match="commit failed"):
        async with database.transaction():
            pass

    assert pool.raw.begin_count == 1
    assert pool.raw.commit_count == 1
    assert pool.raw.rollback_count == 0
    assert pool.release_count == 1


@pytest.mark.asyncio
async def test_transaction_rollback_failure_keeps_body_and_rollback_errors(monkeypatch):
    pool = FakePool()
    body_error = RuntimeError("body failed")
    rollback_error = OSError("rollback failed")
    pool.raw.rollback_error = rollback_error
    use_pool(monkeypatch, pool)

    with pytest.raises(ExceptionGroup) as raised:
        async with database.transaction():
            raise body_error

    assert raised.value.exceptions == (body_error, rollback_error)
    assert pool.raw.commit_count == 0
    assert pool.raw.rollback_count == 1
    assert pool.release_count == 1


@pytest.mark.asyncio
async def test_connection_body_error_releases_without_transaction_calls(monkeypatch):
    pool = FakePool()
    use_pool(monkeypatch, pool)

    with pytest.raises(RuntimeError, match="read failed"):
        async with database.connection() as session:
            assert session.raw is pool.raw
            raise RuntimeError("read failed")

    assert pool.acquire_count == 1
    assert pool.raw.begin_count == 0
    assert pool.raw.commit_count == 0
    assert pool.raw.rollback_count == 0
    assert pool.release_count == 1


@pytest.mark.asyncio
async def test_module_helpers_each_use_a_single_connection(monkeypatch):
    pool = FakePool()
    use_pool(monkeypatch, pool)

    assert await database.execute("UPDATE x SET value=%s", (2,)) == 1
    assert await database.fetchone("SELECT one") == {"value": "one"}
    assert await database.fetchall("SELECT many") == [{"value": "many"}]

    assert pool.acquire_count == 3
    assert pool.release_count == 3
    assert pool.raw.begin_count == 0


@pytest.mark.asyncio
async def test_get_pool_uses_backend_config_and_caches_pool(monkeypatch):
    created_pool = FakePool()
    calls = []

    async def fake_create_pool(**kwargs):
        calls.append(kwargs)
        return created_pool

    monkeypatch.setattr(database, "_pool", None)
    monkeypatch.setattr(database.aiomysql, "create_pool", fake_create_pool)

    assert await database.get_pool() is created_pool
    assert await database.get_pool() is created_pool
    assert calls == [database.MYSQL_CONFIG]


@pytest.mark.asyncio
async def test_close_pool_closes_waits_and_clears_global(monkeypatch):
    pool = FakePool()
    monkeypatch.setattr(database, "_pool", pool)

    await database.close_pool()

    assert pool.close_count == 1
    assert pool.wait_closed_count == 1
    assert database._pool is None
