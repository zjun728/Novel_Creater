import pytest

from backend import main
from backend.schema_version import SchemaMismatch
from backend.tests.support.fakes import FakeAsyncContext


def install_lifespan_fakes(monkeypatch, verify_error=None):
    events = []
    session = object()
    context = FakeAsyncContext(session, events)

    async def fake_verify(actual_session):
        assert actual_session is session
        events.append("verify")
        if verify_error is not None:
            raise verify_error

    async def fake_close_pool():
        events.append("close")

    class FakeRuntime:
        def start(self):
            events.append("scheduler-start")

        async def stop(self):
            events.append("scheduler-stop")

    def fake_build_runtime():
        events.append("scheduler-build")
        return FakeRuntime()

    monkeypatch.setattr(main, "connection", lambda: context)
    monkeypatch.setattr(main, "verify_schema_version", fake_verify)
    monkeypatch.setattr(main, "close_pool", fake_close_pool)
    monkeypatch.setattr(
        main,
        "build_market_scheduler_runtime",
        fake_build_runtime,
    )
    return events


@pytest.mark.asyncio
async def test_lifespan_verifies_once_before_yield_and_closes_after_success(monkeypatch):
    events = install_lifespan_fakes(monkeypatch)
    context = main.lifespan(main.app)

    await context.__aenter__()
    events.append("app-yielded")

    assert events == [
        "connection-enter",
        "verify",
        "connection-exit",
        "scheduler-build",
        "scheduler-start",
        "app-yielded",
    ]

    await context.__aexit__(None, None, None)
    assert events == [
        "connection-enter",
        "verify",
        "connection-exit",
        "scheduler-build",
        "scheduler-start",
        "app-yielded",
        "scheduler-stop",
        "close",
    ]


@pytest.mark.asyncio
async def test_lifespan_does_not_yield_or_swallow_schema_mismatch(monkeypatch):
    mismatch = SchemaMismatch("wrong schema")
    events = install_lifespan_fakes(monkeypatch, verify_error=mismatch)
    context = main.lifespan(main.app)

    with pytest.raises(SchemaMismatch) as raised:
        await context.__aenter__()

    assert raised.value is mismatch
    assert events == ["connection-enter", "verify", "connection-exit", "close"]


@pytest.mark.asyncio
async def test_lifespan_closes_pool_when_yielded_application_fails(monkeypatch):
    events = install_lifespan_fakes(monkeypatch)
    context = main.lifespan(main.app)
    await context.__aenter__()
    app_error = RuntimeError("application failed")

    suppressed = await context.__aexit__(
        RuntimeError, app_error, app_error.__traceback__
    )

    assert suppressed is False
    assert events == [
        "connection-enter",
        "verify",
        "connection-exit",
        "scheduler-build",
        "scheduler-start",
        "scheduler-stop",
        "close",
    ]


@pytest.mark.asyncio
async def test_lifespan_aggregates_scheduler_and_pool_cleanup_failures(monkeypatch):
    events = install_lifespan_fakes(monkeypatch)
    scheduler_error = RuntimeError("synthetic scheduler cleanup")
    pool_error = RuntimeError("synthetic pool cleanup")

    class FailingRuntime:
        def start(self):
            events.append("scheduler-start")

        async def stop(self):
            events.append("scheduler-stop")
            raise scheduler_error

    monkeypatch.setattr(main, "build_market_scheduler_runtime", FailingRuntime)

    async def failing_close_pool():
        events.append("close")
        raise pool_error

    monkeypatch.setattr(main, "close_pool", failing_close_pool)
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(BaseExceptionGroup) as aggregated:
        await context.__aexit__(None, None, None)

    assert aggregated.value.exceptions == (scheduler_error, pool_error)
    assert events[-2:] == ["scheduler-stop", "close"]


@pytest.mark.asyncio
async def test_lifespan_preserves_application_error_with_all_cleanup_failures(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    application_error = RuntimeError("synthetic application failure")
    scheduler_error = RuntimeError("synthetic scheduler cleanup")
    pool_error = RuntimeError("synthetic pool cleanup")

    class FailingRuntime:
        def start(self):
            events.append("scheduler-start")

        async def stop(self):
            events.append("scheduler-stop")
            raise scheduler_error

    monkeypatch.setattr(main, "build_market_scheduler_runtime", FailingRuntime)

    async def failing_close_pool():
        events.append("close")
        raise pool_error

    monkeypatch.setattr(main, "close_pool", failing_close_pool)
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(BaseExceptionGroup) as aggregated:
        await context.__aexit__(
            RuntimeError,
            application_error,
            application_error.__traceback__,
        )

    assert aggregated.value.exceptions == (
        application_error,
        scheduler_error,
        pool_error,
    )


@pytest.mark.asyncio
async def test_health_echoes_browser_owner_nonce_only_when_explicitly_injected(
    monkeypatch,
):
    monkeypatch.delenv("M2_BROWSER_RUN_NONCE", raising=False)
    assert await main.health() == {"ok": True}

    monkeypatch.setenv("M2_BROWSER_RUN_NONCE", "owned-browser-child-123")
    assert await main.health() == {
        "ok": True,
        "browserRunNonce": "owned-browser-child-123",
    }
