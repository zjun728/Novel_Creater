from __future__ import annotations

import asyncio

import pytest


class ManualTime:
    def __init__(self) -> None:
        self.now_ms = 0
        self.waiters: list[tuple[int, asyncio.Future[None]]] = []

    def clock(self) -> int:
        return self.now_ms

    async def sleep(self, seconds: float) -> None:
        future = asyncio.get_running_loop().create_future()
        self.waiters.append((self.now_ms + round(seconds * 1000), future))
        await future

    async def advance(self, milliseconds: int) -> None:
        self.now_ms += milliseconds
        for deadline, future in tuple(self.waiters):
            if deadline <= self.now_ms and not future.done():
                future.set_result(None)
        self.waiters = [item for item in self.waiters if not item[1].done()]
        await asyncio.sleep(0)
        await asyncio.sleep(0)


async def _chunks(*values: str):
    for value in values:
        yield value


async def _wait_for(predicate) -> None:
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0)
    assert predicate()


def test_execution_public_constants_are_fixed():
    from backend.services.draft_operation_execution import (
        DELTA_FLUSH_MS,
        DELTA_FLUSH_SCALARS,
        DRAFT_OPERATION_LEASE_MS,
        HEARTBEAT_MS,
        MAX_DRAFT_OPERATION_EVENTS,
    )

    assert DELTA_FLUSH_SCALARS == 256
    assert DELTA_FLUSH_MS == 1_000
    assert HEARTBEAT_MS == 10_000
    assert DRAFT_OPERATION_LEASE_MS == 30_000
    assert MAX_DRAFT_OPERATION_EVENTS == 2_048


@pytest.mark.asyncio
async def test_stream_flushes_at_256_scalars_and_completes_with_exact_text():
    from backend.services.draft_operation_execution import DraftOperationExecution

    deltas: list[str] = []
    completed: list[str] = []
    execution = DraftOperationExecution()

    await execution.run_stream(
        stream=_chunks("a" * 255, "\U0001f600", "  tail\n"),
        on_delta=lambda text: _append(deltas, text),
        on_heartbeat=lambda: _append(deltas, "heartbeat"),
        on_complete=lambda text: _append(completed, text),
    )

    assert deltas == ["a" * 255 + "\U0001f600", "a" * 255 + "\U0001f600  tail\n"]
    assert completed == ["a" * 255 + "\U0001f600  tail\n"]


@pytest.mark.asyncio
async def test_stream_flushes_private_buffer_after_one_second_provider_stall():
    from backend.services.draft_operation_execution import DraftOperationExecution

    timer = ManualTime()
    release = asyncio.Event()
    deltas: list[str] = []

    async def stream():
        yield "private so far"
        await release.wait()
        yield " and done"

    task = asyncio.create_task(
        DraftOperationExecution(clock=timer.clock, sleep=timer.sleep).run_stream(
            stream=stream(),
            on_delta=lambda text: _append(deltas, text),
            on_heartbeat=lambda: _noop(),
            on_complete=lambda text: _noop(),
        )
    )
    await _wait_for(lambda: any(deadline == 1_000 for deadline, _ in timer.waiters))
    await timer.advance(999)
    assert deltas == []
    await timer.advance(1)
    await _wait_for(lambda: deltas == ["private so far"])
    release.set()
    await task
    assert deltas[-1] == "private so far and done"


@pytest.mark.asyncio
async def test_stream_heartbeat_is_independent_and_delta_renews_its_deadline():
    from backend.services.draft_operation_execution import DraftOperationExecution

    timer = ManualTime()
    release = asyncio.Event()
    events: list[str] = []

    async def stream():
        yield "x"
        await release.wait()

    task = asyncio.create_task(
        DraftOperationExecution(clock=timer.clock, sleep=timer.sleep).run_stream(
            stream=stream(),
            on_delta=lambda text: _append(events, f"delta:{text}"),
            on_heartbeat=lambda: _append(events, "heartbeat"),
            on_complete=lambda text: _append(events, f"complete:{text}"),
        )
    )
    await _wait_for(lambda: any(deadline == 1_000 for deadline, _ in timer.waiters))
    await timer.advance(1_000)
    await _wait_for(lambda: events == ["delta:x"])
    await _wait_for(lambda: any(deadline == 11_000 for deadline, _ in timer.waiters))
    await timer.advance(9_999)
    assert events == ["delta:x"]
    await timer.advance(1)
    await _wait_for(lambda: events[-1] == "heartbeat")
    release.set()
    await task


@pytest.mark.asyncio
async def test_non_stream_heartbeats_without_fake_delta_then_completes():
    from backend.services.draft_operation_execution import DraftOperationExecution

    timer = ManualTime()
    release = asyncio.Event()
    events: list[tuple[str, str | None]] = []

    async def generate():
        await release.wait()
        return " exact output "

    task = asyncio.create_task(
        DraftOperationExecution(clock=timer.clock, sleep=timer.sleep).run_non_stream(
            generate=generate,
            on_heartbeat=lambda: _append(events, ("heartbeat", None)),
            on_complete=lambda text: _append(events, ("complete", text)),
        )
    )
    await _wait_for(lambda: bool(timer.waiters))
    await timer.advance(10_000)
    await _wait_for(lambda: events == [("heartbeat", None)])
    release.set()
    await task
    assert events == [("heartbeat", None), ("complete", " exact output ")]


@pytest.mark.asyncio
async def test_cancelled_stream_discards_private_buffer_and_propagates():
    from backend.services.draft_operation_execution import DraftOperationExecution

    started = asyncio.Event()
    deltas: list[str] = []
    completed: list[str] = []

    async def stream():
        yield "not persisted"
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(
        DraftOperationExecution().run_stream(
            stream=stream(),
            on_delta=lambda text: _append(deltas, text),
            on_heartbeat=lambda: _noop(),
            on_complete=lambda text: _append(completed, text),
        )
    )
    await started.wait()
    task.cancel("cancel-request")
    with pytest.raises(asyncio.CancelledError) as exc_info:
        await task
    assert exc_info.value.args == ("cancel-request",)
    assert deltas == []
    assert completed == []


async def _append(target, value):
    target.append(value)


async def _noop():
    return None
