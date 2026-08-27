import asyncio

import aiomysql
import pytest

from backend import config as backend_config
from backend import database
from backend.config import RuntimeConfigurationError
from backend.tests.support.fakes import FakePool


def use_pool(monkeypatch, pool):
    async def fake_get_pool():
        return pool

    monkeypatch.setattr(database, "get_pool", fake_get_pool)


def runtime_configuration(**replacements):
    values = {
        "host": "snapshot-host",
        "port": 3307,
        "user": "snapshot-user",
        "password": "snapshot-password",
        "db": "snapshot-database",
        "charset": "utf8mb4",
        "autocommit": True,
        "minsize": 1,
        "maxsize": 10,
    }
    values.update(replacements)
    return backend_config.RuntimeConfiguration(
        mysql_items=tuple(values.items()),
        corpus_root=None,
        managed_corpus_root=None,
        market_scheduler_enabled=False,
    )


@pytest.fixture(autouse=True)
def no_active_runtime_configuration(monkeypatch):
    monkeypatch.setattr(
        backend_config, "_active_runtime_configuration", None, raising=False
    )


def use_complete_runtime_configuration():
    snapshot = runtime_configuration()
    backend_config.install_runtime_configuration(snapshot)
    return snapshot


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
async def test_read_only_transaction_uses_mysql_read_only_start_and_commits_once(monkeypatch):
    pool = FakePool()
    use_pool(monkeypatch, pool)

    async with database.read_only_transaction() as session:
        assert session.raw is pool.raw
        assert await session.fetchone("SELECT one") == {"value": "one"}

    assert pool.acquire_count == pool.release_count == 1
    assert pool.raw.executions[0] == ("START TRANSACTION READ ONLY", None)
    assert pool.raw.begin_count == 0
    assert pool.raw.commit_count == 1
    assert pool.raw.rollback_count == 0


@pytest.mark.asyncio
async def test_read_only_transaction_rolls_back_body_error_and_preserves_programmer_error(monkeypatch):
    pool = FakePool()
    use_pool(monkeypatch, pool)

    with pytest.raises(RuntimeError, match="body failure"):
        async with database.read_only_transaction():
            raise RuntimeError("body failure")

    assert pool.raw.commit_count == 0
    assert pool.raw.rollback_count == 1
    assert pool.release_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["acquire", "start", "commit"])
@pytest.mark.parametrize("driver_error", [aiomysql.OperationalError, aiomysql.InterfaceError])
async def test_read_only_transaction_translates_driver_availability_failures_safely(
    monkeypatch, phase, driver_error,
):
    pool = FakePool()
    error = driver_error(2006, "RAW_DB_SENTINEL")
    if phase == "acquire":
        pool.acquire_error = error
    elif phase == "start":
        pool.raw.execute_error = error
    else:
        pool.raw.commit_error = error
    use_pool(monkeypatch, pool)

    with pytest.raises(database.DatabaseUnavailable) as raised:
        async with database.read_only_transaction():
            if phase != "commit":
                pytest.fail("body must not run before failed acquisition or start")

    assert str(raised.value) == "Database is temporarily unavailable"
    assert raised.value.__cause__ is None
    assert "RAW_DB_SENTINEL" not in str(raised.value)
    assert pool.release_count == (0 if phase == "acquire" else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("driver_error", [aiomysql.OperationalError, aiomysql.InterfaceError])
async def test_read_only_transaction_translates_pool_creation_and_body_driver_failures(
    monkeypatch, driver_error,
):
    pool_error = driver_error(2006, "RAW_POOL_SENTINEL")

    async def failed_pool():
        raise pool_error

    monkeypatch.setattr(database, "get_pool", failed_pool)
    with pytest.raises(database.DatabaseUnavailable) as raised:
        async with database.read_only_transaction():
            pytest.fail("body must not run without a pool")
    assert raised.value.__cause__ is None
    assert "RAW_POOL_SENTINEL" not in str(raised.value)

    pool = FakePool()
    use_pool(monkeypatch, pool)
    with pytest.raises(database.DatabaseUnavailable) as raised:
        async with database.read_only_transaction():
            raise driver_error(2006, "RAW_BODY_SENTINEL")
    assert raised.value.__cause__ is None
    assert "RAW_BODY_SENTINEL" not in str(raised.value)
    assert pool.raw.rollback_count == pool.release_count == 1


@pytest.mark.asyncio
async def test_read_only_transaction_preserves_driver_body_and_programmer_rollback_failures(
    monkeypatch,
):
    pool = FakePool()
    body_error = aiomysql.OperationalError(2006, "RAW_BODY_SENTINEL")
    rollback_error = RuntimeError("rollback programmer bug")
    pool.raw.rollback_error = rollback_error
    use_pool(monkeypatch, pool)

    with pytest.raises(BaseExceptionGroup) as raised:
        async with database.read_only_transaction():
            raise body_error

    assert raised.value.exceptions[0].__class__ is database.DatabaseUnavailable
    assert raised.value.exceptions[0].__cause__ is None
    assert raised.value.exceptions[1] is rollback_error
    assert pool.raw.rollback_count == pool.release_count == 1


@pytest.mark.asyncio
async def test_read_only_transaction_preserves_cancellation_when_driver_body_and_rollback_fail(
    monkeypatch,
):
    pool = FakePool()
    cancellation = asyncio.CancelledError("rollback cancellation")
    pool.raw.rollback_error = cancellation
    use_pool(monkeypatch, pool)

    with pytest.raises(BaseExceptionGroup) as raised:
        async with database.read_only_transaction():
            raise aiomysql.OperationalError(2006, "RAW_BODY_SENTINEL")

    assert raised.value.exceptions[0].__class__ is database.DatabaseUnavailable
    assert raised.value.exceptions[1] is cancellation
    assert pool.raw.rollback_count == pool.release_count == 1


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
async def test_get_pool_uses_installed_snapshot_and_caches_pool(monkeypatch):
    created_pool = FakePool()
    calls = []

    async def fake_create_pool(**kwargs):
        calls.append(kwargs)
        return created_pool

    snapshot = use_complete_runtime_configuration()
    monkeypatch.setenv("MYSQL_DB", "later-value-must-not-win")
    monkeypatch.setattr(
        backend_config,
        "load_mysql_config",
        lambda *args, **kwargs: pytest.fail("pool reread local configuration"),
    )
    monkeypatch.setattr(database, "_pool", None)
    monkeypatch.setattr(database.aiomysql, "create_pool", fake_create_pool)

    assert await database.get_pool() is created_pool
    assert await database.get_pool() is created_pool
    assert calls == [snapshot.mysql_pool_options()]


@pytest.mark.asyncio
async def test_get_pool_rejects_missing_runtime_snapshot_before_connector(monkeypatch):
    called = False

    async def fake_create_pool(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(database, "_pool", None)
    monkeypatch.setattr(database.aiomysql, "create_pool", fake_create_pool)

    with pytest.raises(
        RuntimeConfigurationError,
        match="^runtime configuration is unavailable$",
    ):
        await database.get_pool()

    assert called is False


@pytest.mark.asyncio
async def test_get_pool_rejects_snapshot_invalidated_after_install(monkeypatch):
    called = False

    async def fake_create_pool(**kwargs):
        nonlocal called
        called = True

    snapshot = use_complete_runtime_configuration()
    object.__setattr__(snapshot, "mysql_items", (("host", "secret"),))
    monkeypatch.setattr(database, "_pool", None)
    monkeypatch.setattr(database.aiomysql, "create_pool", fake_create_pool)

    with pytest.raises(
        RuntimeConfigurationError,
        match="^runtime configuration is unavailable$",
    ) as caught:
        await database.get_pool()

    assert caught.value.args == ("runtime configuration is unavailable",)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert called is False


@pytest.mark.asyncio
async def test_concurrent_first_get_pool_creates_one_shared_pool(monkeypatch):
    create_started = asyncio.Event()
    allow_create = asyncio.Event()
    created_pools = []

    async def fake_create_pool(**kwargs):
        pool = FakePool()
        created_pools.append(pool)
        create_started.set()
        await allow_create.wait()
        return pool

    use_complete_runtime_configuration()
    monkeypatch.setattr(database, "_pool", None)
    monkeypatch.setattr(database, "_pool_lock", asyncio.Lock(), raising=False)
    monkeypatch.setattr(database.aiomysql, "create_pool", fake_create_pool)

    first = asyncio.create_task(database.get_pool())
    await create_started.wait()
    second = asyncio.create_task(database.get_pool())
    await asyncio.sleep(0)
    allow_create.set()
    first_pool, second_pool = await asyncio.gather(first, second)

    assert len(created_pools) == 1
    assert first_pool is second_pool is created_pools[0]


@pytest.mark.asyncio
async def test_close_pool_waits_for_initialization_and_closes_once(monkeypatch):
    create_started = asyncio.Event()
    allow_create = asyncio.Event()
    created_pool = FakePool()

    async def fake_create_pool(**kwargs):
        create_started.set()
        await allow_create.wait()
        return created_pool

    use_complete_runtime_configuration()
    monkeypatch.setattr(database, "_pool", None)
    monkeypatch.setattr(database, "_pool_lock", asyncio.Lock(), raising=False)
    monkeypatch.setattr(database.aiomysql, "create_pool", fake_create_pool)

    get_task = asyncio.create_task(database.get_pool())
    await create_started.wait()
    close_task = asyncio.create_task(database.close_pool())
    await asyncio.sleep(0)
    close_waited_for_initialization = not close_task.done()
    allow_create.set()

    assert await get_task is created_pool
    await close_task
    assert close_waited_for_initialization
    assert created_pool.close_count == 1
    assert created_pool.wait_closed_count == 1
    assert database._pool is None


def test_pool_lock_is_created_at_module_scope():
    assert isinstance(database._pool_lock, asyncio.Lock)


@pytest.mark.asyncio
async def test_close_pool_closes_waits_and_clears_global(monkeypatch):
    pool = FakePool()
    monkeypatch.setattr(database, "_pool", pool)

    await database.close_pool()

    assert pool.close_count == 1
    assert pool.wait_closed_count == 1
    assert database._pool is None
