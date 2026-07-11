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

    monkeypatch.setattr(main, "connection", lambda: context)
    monkeypatch.setattr(main, "verify_schema_version", fake_verify)
    monkeypatch.setattr(main, "close_pool", fake_close_pool)
    return events


@pytest.mark.asyncio
async def test_lifespan_verifies_once_before_yield_and_closes_after_success(monkeypatch):
    events = install_lifespan_fakes(monkeypatch)
    context = main.lifespan(main.app)

    await context.__aenter__()
    events.append("app-yielded")

    assert events == ["connection-enter", "verify", "connection-exit", "app-yielded"]

    await context.__aexit__(None, None, None)
    assert events == [
        "connection-enter",
        "verify",
        "connection-exit",
        "app-yielded",
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
    assert events == ["connection-enter", "verify", "connection-exit", "close"]
