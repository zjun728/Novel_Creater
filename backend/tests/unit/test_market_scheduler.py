from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging

import pytest


NOW = 1_721_000_000_000
SOURCE_ID = "00000000-0000-0000-0000-000000000101"


class DueRepository:
    def __init__(self, due=()):
        self.due = tuple(due)
        self.calls = []

    async def list_due_schedules(self, session, *, now_ms, limit):
        self.calls.append((session, now_ms, limit))
        return self.due

    async def next_scheduled_run(self, session):
        return min(
            (
                row["next_run_at"]
                for row in self.due
                if row.get("next_run_at") is not None
            ),
            default=None,
        )


def connection_factory(events, state):
    @asynccontextmanager
    async def connection():
        assert state["open"] is False
        state["open"] = True
        session = object()
        events.append(("connection-enter", session))
        try:
            yield session
        finally:
            events.append(("connection-exit", session))
            state["open"] = False

    return connection


@pytest.mark.asyncio
async def test_disabled_or_no_due_schedule_never_calls_executor():
    from backend.services.market_scheduler import MarketScheduler

    calls = []

    async def forbidden_executor(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("disabled or no-due scheduler must not execute")

    disabled_repository = DueRepository(
        ({"source_id": SOURCE_ID, "next_run_at": NOW},)
    )
    disabled = MarketScheduler(
        disabled_repository,
        connection_factory=lambda: pytest.fail("disabled scheduler read database"),
        executor=forbidden_executor,
        clock=lambda: NOW,
        enabled=False,
    )
    assert await disabled.run_once() == ()
    assert disabled_repository.calls == []

    events = []
    state = {"open": False}
    no_due_repository = DueRepository()
    no_due = MarketScheduler(
        no_due_repository,
        connection_factory=connection_factory(events, state),
        executor=forbidden_executor,
        clock=lambda: NOW,
        enabled=True,
    )
    assert await no_due.run_once() == ()
    assert len(no_due_repository.calls) == 1
    assert calls == []


@pytest.mark.asyncio
async def test_due_read_closes_before_executor_and_output_is_bounded_and_safe(
    caplog,
):
    from backend.services.market_scheduler import MarketScheduler

    sentinel = "PRIVATE_URL_CONFIG_SECRET_RAW_ERROR"
    events = []
    state = {"open": False}
    repository = DueRepository(
        ({"source_id": SOURCE_ID, "next_run_at": NOW},)
    )
    executor_calls = []

    async def executor(source_id, *, idempotency_key):
        assert state["open"] is False
        executor_calls.append((source_id, idempotency_key))
        raise RuntimeError(sentinel)

    scheduler = MarketScheduler(
        repository,
        connection_factory=connection_factory(events, state),
        executor=executor,
        clock=lambda: NOW,
        enabled=True,
        max_sources_per_tick=4,
    )
    caplog.set_level(logging.INFO, logger="backend.services.market_scheduler")

    results = await scheduler.run_once()

    assert len(results) == 1
    assert results[0].source_id == SOURCE_ID
    assert results[0].status == "failed"
    assert set(results[0].as_public_dict()) == {"sourceId", "status"}
    assert executor_calls[0][0] == SOURCE_ID
    assert len(executor_calls[0][1]) == 64
    assert events[1][0] == "connection-exit"
    rendered = f"{results!r} {caplog.text}"
    assert sentinel not in rendered
    assert "http" not in rendered.casefold()
    assert "config" not in rendered.casefold()
    assert "secret" not in rendered.casefold()


@pytest.mark.asyncio
async def test_scheduler_maps_owner_fenced_live_lease_to_fixed_skipped_status():
    from backend.services.market_scheduler import MarketScheduler

    repository = DueRepository(
        ({"source_id": SOURCE_ID, "next_run_at": NOW},)
    )
    events = []
    state = {"open": False}

    async def executor(source_id, *, idempotency_key):
        return {"kind": "skipped", "status": "lease-live"}

    scheduler = MarketScheduler(
        repository,
        connection_factory=connection_factory(events, state),
        executor=executor,
        clock=lambda: NOW,
        enabled=True,
    )

    results = await scheduler.run_once()

    assert tuple(result.as_public_dict() for result in results) == (
        {"sourceId": SOURCE_ID, "status": "skipped"},
    )


class BlockingScheduler:
    enabled = True
    next_run_at = NOW

    def __init__(self):
        self.started = asyncio.Event()
        self.cleaned = asyncio.Event()
        self.calls = 0

    async def run_once(self):
        self.calls += 1
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            self.cleaned.set()


@pytest.mark.asyncio
async def test_runtime_shutdown_cancels_future_work_and_awaits_inflight_cleanup():
    from backend.runtime.market_scheduler import MarketSchedulerRuntime

    scheduler = BlockingScheduler()
    runtime = MarketSchedulerRuntime(
        scheduler,
        poll_interval_seconds=60,
        shutdown_timeout_seconds=1,
    )

    runtime.start()
    await asyncio.wait_for(scheduler.started.wait(), timeout=1)
    await runtime.stop()

    assert scheduler.calls == 1
    assert scheduler.cleaned.is_set()
    assert runtime.state == "stopped"
    assert runtime.next_run_at is None


@pytest.mark.asyncio
async def test_runtime_shutdown_is_bounded_when_inflight_cleanup_stalls():
    from backend.runtime.market_scheduler import MarketSchedulerRuntime

    class StubbornScheduler:
        enabled = True
        next_run_at = NOW

        def __init__(self):
            self.started = asyncio.Event()
            self.cleaned = asyncio.Event()
            self.cancellations = 0

        async def run_once(self):
            self.started.set()
            try:
                while True:
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        self.cancellations += 1
                        if self.cancellations > 1:
                            raise
            finally:
                self.cleaned.set()

    scheduler = StubbornScheduler()
    runtime = MarketSchedulerRuntime(
        scheduler,
        poll_interval_seconds=60,
        shutdown_timeout_seconds=0.01,
    )
    runtime.start()
    await asyncio.wait_for(scheduler.started.wait(), timeout=1)
    started = asyncio.get_running_loop().time()

    with pytest.raises(TimeoutError):
        await runtime.stop()

    assert asyncio.get_running_loop().time() - started < 0.5
    await asyncio.wait_for(scheduler.cleaned.wait(), timeout=1)
    assert scheduler.cancellations == 2
    assert runtime.state == "stopped"


@pytest.mark.asyncio
async def test_runtime_never_polls_more_frequently_than_once_per_minute():
    from backend.runtime.market_scheduler import MarketSchedulerRuntime

    with pytest.raises(ValueError, match="60"):
        MarketSchedulerRuntime(
            BlockingScheduler(),
            poll_interval_seconds=59.999,
        )


@pytest.mark.parametrize(
    ("environment", "expected"),
    (({}, False), ({"MARKET_SCHEDULER_ENABLED": "true"}, True)),
)
def test_scheduler_runtime_is_optional_and_disabled_by_default(
    environment,
    expected,
):
    from backend.config import load_market_scheduler_enabled

    assert load_market_scheduler_enabled(environment=environment) is expected


def test_scheduler_runtime_rejects_ambiguous_enable_values():
    from backend.config import LocalSchedulerConfigError
    from backend.config import load_market_scheduler_enabled

    with pytest.raises(LocalSchedulerConfigError):
        load_market_scheduler_enabled(
            environment={"MARKET_SCHEDULER_ENABLED": "yes"}
        )


def test_scheduled_attempt_key_is_shared_within_a_poll_bucket_then_rotates():
    from backend.services.market_scheduler import scheduled_idempotency_key

    bucket_start = NOW // 60_000 * 60_000
    first = scheduled_idempotency_key(
        SOURCE_ID,
        next_run_at=NOW,
        attempt_at=bucket_start,
    )

    assert first == scheduled_idempotency_key(
        SOURCE_ID,
        next_run_at=NOW,
        attempt_at=bucket_start + 59_999,
    )
    assert first != scheduled_idempotency_key(
        SOURCE_ID,
        next_run_at=NOW,
        attempt_at=bucket_start + 60_000,
    )
    assert len(first) == 64
