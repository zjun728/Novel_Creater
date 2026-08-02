from __future__ import annotations

import asyncio

import pytest

from backend.runtime.draft_operation_tasks import DraftOperationTaskRegistry


async def _wait_for(predicate):
    for _ in range(50):
        if predicate():
            return
        await asyncio.sleep(0)
    assert predicate()


@pytest.mark.asyncio
async def test_launch_requires_start_and_start_is_idempotent_and_restartable():
    registry = DraftOperationTaskRegistry()

    with pytest.raises(RuntimeError):
        registry.launch("op-1", lambda signal: asyncio.sleep(0))

    await registry.start()
    await registry.start()
    completed = []

    async def worker(signal):
        assert not signal.is_set()
        completed.append(signal)

    registry.launch("op-1", worker)
    await _wait_for(lambda: len(completed) == 1)
    await _wait_for(lambda: registry.size == 0)
    await registry.aclose()
    await registry.start()
    registry.launch("op-1", worker)
    await _wait_for(lambda: len(completed) == 2)
    await registry.aclose()
    assert registry.size == 0


@pytest.mark.asyncio
async def test_launch_owns_unique_operation_id_and_passes_its_unset_signal():
    registry = DraftOperationTaskRegistry()
    await registry.start()
    started = asyncio.Event()
    release = asyncio.Event()
    received = []

    async def worker(signal):
        received.append(signal)
        started.set()
        await release.wait()

    signal = registry.launch("op-1", worker)
    await started.wait()
    assert signal is received[0]
    assert not signal.is_set()
    assert registry.size == 1
    with pytest.raises(RuntimeError):
        registry.launch("op-1", worker)
    assert registry.size == 1
    assert not signal.is_set()
    release.set()
    await _wait_for(lambda: registry.size == 0)
    await registry.aclose()


@pytest.mark.asyncio
async def test_completed_and_failed_workers_are_removed_without_loop_errors():
    registry = DraftOperationTaskRegistry()
    await registry.start()
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    errors = []
    loop.set_exception_handler(lambda _loop, context: errors.append(context))
    try:
        registry.launch("complete", lambda signal: asyncio.sleep(0))

        async def failing(signal):
            raise ValueError("private worker detail")

        registry.launch("fail", failing)
        await _wait_for(lambda: registry.size == 0)
        await asyncio.sleep(0)
        assert errors == []
    finally:
        loop.set_exception_handler(previous_handler)
        await registry.aclose()


@pytest.mark.asyncio
async def test_cancel_sets_signal_before_cancelling_and_is_idempotent():
    registry = DraftOperationTaskRegistry()
    await registry.start()
    started = asyncio.Event()
    observed = []

    async def worker(signal):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            observed.append(signal.is_set())
            raise

    signal = registry.launch("op-1", worker)
    await started.wait()
    assert registry.cancel("missing") is False
    assert registry.cancel("op-1") is True
    assert signal.is_set()
    assert registry.cancel("op-1") is True
    await _wait_for(lambda: registry.size == 0)
    assert observed == [True]
    await registry.aclose()


@pytest.mark.asyncio
async def test_aclose_rejects_launches_and_settles_success_failure_and_cancelled_workers():
    registry = DraftOperationTaskRegistry()
    await registry.start()
    cancellation_seen = asyncio.Event()

    async def success(signal):
        return None

    async def failure(signal):
        raise ValueError("worker failure")

    async def blocked(signal):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            assert signal.is_set()
            cancellation_seen.set()
            raise

    first = registry.launch("success", success)
    second = registry.launch("failure", failure)
    third = registry.launch("blocked", blocked)
    await asyncio.sleep(0)
    close_task = asyncio.create_task(registry.aclose())
    await asyncio.sleep(0)
    with pytest.raises(RuntimeError):
        registry.launch("new", blocked)
    await close_task
    assert not first.is_set() and not second.is_set() and third.is_set()
    assert cancellation_seen.is_set()
    assert registry.size == 0


@pytest.mark.asyncio
async def test_stale_completion_callback_cannot_remove_same_id_in_restart_generation():
    registry = DraftOperationTaskRegistry()
    await registry.start()
    old_started = asyncio.Event()

    async def old_worker(signal):
        old_started.set()
        await asyncio.Event().wait()

    registry.launch("op-1", old_worker)
    await old_started.wait()
    await registry.aclose()
    await registry.start()
    new_started = asyncio.Event()
    release = asyncio.Event()

    async def new_worker(signal):
        new_started.set()
        await release.wait()

    registry.launch("op-1", new_worker)
    await new_started.wait()
    await asyncio.sleep(0)
    assert registry.size == 1
    release.set()
    await _wait_for(lambda: registry.size == 0)
    await registry.aclose()


@pytest.mark.asyncio
async def test_aclose_preserves_caller_cancellation_after_settling_children():
    registry = DraftOperationTaskRegistry()
    await registry.start()
    worker_cancelled = asyncio.Event()

    async def worker(signal):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            worker_cancelled.set()
            raise

    registry.launch("op-1", worker)
    close_task = asyncio.create_task(registry.aclose())
    await asyncio.sleep(0)
    close_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await close_task
    await _wait_for(lambda: worker_cancelled.is_set() and registry.size == 0)
    with pytest.raises(RuntimeError):
        registry.launch("op-2", worker)
