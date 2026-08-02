from __future__ import annotations

import asyncio
import gc
import weakref

import pytest

from backend.runtime import draft_operation_tasks
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


@pytest.mark.asyncio
async def test_concurrent_aclose_is_single_flight_bounded_and_detaches_stubborn_task(
    monkeypatch,
):
    monkeypatch.setattr(
        draft_operation_tasks,
        "_DRAFT_OPERATION_TASK_SHUTDOWN_TIMEOUT_SECONDS",
        0.01,
    )
    registry = DraftOperationTaskRegistry()
    await registry.start()
    worker_started = asyncio.Event()
    first_cancel_seen = asyncio.Event()
    old_release = asyncio.Event()
    old_settled = asyncio.Event()
    cancel_count = 0
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    errors = []
    loop.set_exception_handler(lambda _loop, context: errors.append(context))

    async def stubborn_worker(signal):
        nonlocal cancel_count
        worker_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancel_count += 1
            assert signal.is_set()
            first_cancel_seen.set()
            await old_release.wait()
        old_settled.set()

    try:
        registry.launch("same-id", stubborn_worker)
        await worker_started.wait()
        first_close = asyncio.create_task(registry.aclose())
        second_close = asyncio.create_task(registry.aclose())
        await first_cancel_seen.wait()
        with pytest.raises(RuntimeError):
            await registry.start()
        await asyncio.wait_for(
            asyncio.gather(first_close, second_close),
            timeout=0.2,
        )
        assert cancel_count == 1
        assert registry.size == 0

        await registry.start()
        new_release = asyncio.Event()
        new_started = asyncio.Event()

        async def new_worker(signal):
            new_started.set()
            await new_release.wait()

        registry.launch("same-id", new_worker)
        await new_started.wait()
        old_release.set()
        await old_settled.wait()
        await asyncio.sleep(0)
        assert registry.size == 1
        new_release.set()
        await _wait_for(lambda: registry.size == 0)
        await registry.aclose()
        await asyncio.sleep(0)
        assert errors == []
    finally:
        old_release.set()
        loop.set_exception_handler(previous_handler)


@pytest.mark.asyncio
async def test_cancelled_aclose_waiter_preserves_first_reason_and_shared_drain(
    monkeypatch,
):
    monkeypatch.setattr(
        draft_operation_tasks,
        "_DRAFT_OPERATION_TASK_SHUTDOWN_TIMEOUT_SECONDS",
        0.2,
    )
    registry = DraftOperationTaskRegistry()
    await registry.start()
    worker_started = asyncio.Event()
    worker_cancelled = asyncio.Event()
    worker_release = asyncio.Event()
    worker_settled = asyncio.Event()

    async def worker(signal):
        worker_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            assert signal.is_set()
            worker_cancelled.set()
            await worker_release.wait()
        worker_settled.set()

    registry.launch("op-1", worker)
    await worker_started.wait()
    cancelled_waiter = asyncio.create_task(registry.aclose())
    successful_waiter = asyncio.create_task(registry.aclose())
    await worker_cancelled.wait()
    cancelled_waiter.cancel("caller-reason")
    await asyncio.sleep(0)
    cancelled_waiter.cancel("later-reason")
    await asyncio.sleep(0)
    assert not successful_waiter.done()
    worker_release.set()

    with pytest.raises(asyncio.CancelledError) as exc_info:
        await cancelled_waiter
    assert exc_info.value.args == ("caller-reason",)
    await successful_waiter
    assert worker_settled.is_set()
    assert registry.size == 0


@pytest.mark.asyncio
async def test_detached_task_is_strongly_retained_until_its_private_wait_completes(
    monkeypatch,
):
    monkeypatch.setattr(
        draft_operation_tasks,
        "_DRAFT_OPERATION_TASK_SHUTDOWN_TIMEOUT_SECONDS",
        0.01,
    )
    registry = DraftOperationTaskRegistry()
    await registry.start()
    worker_started = asyncio.Event()
    first_cancel_seen = asyncio.Event()
    worker_settled = asyncio.Event()
    weak_handles = {}
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    errors = []
    loop.set_exception_handler(lambda _loop, context: errors.append(context))

    async def stubborn_worker(signal):
        private_wait = loop.create_future()
        weak_handles["task"] = weakref.ref(asyncio.current_task())
        weak_handles["wait"] = weakref.ref(private_wait)
        worker_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            assert signal.is_set()
            first_cancel_seen.set()
            await private_wait
        worker_settled.set()

    try:
        registry.launch("same-id", stubborn_worker)
        await worker_started.wait()
        await registry.aclose()
        await first_cancel_seen.wait()
        assert registry.size == 0

        for _ in range(3):
            gc.collect()
            await asyncio.sleep(0)
        assert weak_handles["task"]() is not None
        assert weak_handles["wait"]() is not None
        assert not any(
            context.get("message") == "Task was destroyed but it is pending!"
            for context in errors
        )

        await registry.start()
        replacement_release = asyncio.Event()

        async def replacement(signal):
            await replacement_release.wait()

        registry.launch("same-id", replacement)
        private_wait = weak_handles["wait"]()
        assert private_wait is not None
        private_wait.set_result(None)
        del private_wait
        await worker_settled.wait()
        await asyncio.sleep(0)
        assert registry.size == 1
        replacement_release.set()
        await _wait_for(lambda: registry.size == 0)
        await registry.aclose()

        for _ in range(3):
            gc.collect()
            await asyncio.sleep(0)
        assert weak_handles["task"]() is None
        assert errors == []
    finally:
        loop.set_exception_handler(previous_handler)


@pytest.mark.asyncio
async def test_launch_supports_same_loop_future_awaitables():
    registry = DraftOperationTaskRegistry()
    await registry.start()
    loop = asyncio.get_running_loop()
    completed = loop.create_future()
    received = []

    def completed_worker(signal):
        received.append(signal)
        return completed

    signal = registry.launch("complete", completed_worker)
    assert received == [signal]
    assert registry.size == 1
    completed.set_result(None)
    await _wait_for(lambda: registry.size == 0)

    cancelled = loop.create_future()

    def cancelled_worker(signal):
        received.append(signal)
        return cancelled

    cancel_signal = registry.launch("cancel", cancelled_worker)
    assert received[-1] is cancel_signal
    assert registry.cancel("cancel") is True
    assert cancel_signal.is_set()
    await _wait_for(lambda: cancelled.cancelled() and registry.size == 0)
    await registry.aclose()
