"""Application-scoped supervision for in-process draft-operation workers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


_DRAFT_OPERATION_TASK_SHUTDOWN_TIMEOUT_SECONDS = 5.0


def _consume_background_result(task: asyncio.Future[object]) -> None:
    if task.cancelled():
        return
    try:
        task.exception()
    except BaseException:
        return


class DraftOperationTasksTransferLifecycleError(RuntimeError):
    """Safe public failure for transferred drain or pool cleanup."""


class DraftOperationTasksCleanupTransfer:
    """Own a pending registry drain and optionally close the pool afterward."""

    def __init__(self, drain_task: asyncio.Task[None]) -> None:
        self._drain_task: asyncio.Task[None] | None = drain_task
        self._drain_succeeded = False
        self._pool_close_task: asyncio.Task[None] | None = None
        self._drain_task.add_done_callback(self._on_drain_done)

    def start_pool_close(
        self,
        close_pool: Callable[[], Awaitable[None]],
    ) -> asyncio.Task[None]:
        if self._pool_close_task is None:
            self._pool_close_task = asyncio.create_task(
                self._finish_pool_close(close_pool),
                name="draft-operation-shutdown-transfer",
            )
            self._pool_close_task.add_done_callback(_consume_background_result)
        return self._pool_close_task

    def _allows_restart(self) -> bool:
        if self._drain_task is not None:
            return False
        if not self._drain_succeeded:
            return False
        if self._pool_close_task is None:
            return True
        return self._task_succeeded(self._pool_close_task)

    async def _finish_pool_close(
        self,
        close_pool: Callable[[], Awaitable[None]],
    ) -> None:
        cancellation: asyncio.CancelledError | None = None
        current = asyncio.current_task()
        drain_failed = False
        drain_task = self._drain_task
        if drain_task is not None:
            while not drain_task.done():
                try:
                    await asyncio.shield(drain_task)
                except asyncio.CancelledError as error:
                    if (
                        current is not None
                        and current.cancelling() > 0
                        and cancellation is None
                    ):
                        cancellation = error
                except BaseException:
                    pass
            if not self._task_succeeded(drain_task):
                drain_failed = True
            drain_task = None
        elif not self._drain_succeeded:
            drain_failed = True

        if drain_failed:
            if cancellation is not None:
                raise cancellation from None
            raise DraftOperationTasksTransferLifecycleError(
                "draft operation shutdown transfer failed"
            ) from None

        pool_failed = False
        pool_task: asyncio.Future[None] | None = None
        try:
            pool_task = asyncio.ensure_future(close_pool())
        except BaseException:
            pool_failed = True
        if pool_task is not None:
            while not pool_task.done():
                try:
                    await asyncio.shield(pool_task)
                except asyncio.CancelledError as error:
                    if cancellation is None:
                        cancellation = error
            if pool_task.cancelled():
                pool_failed = True
            else:
                try:
                    pool_task.result()
                except BaseException:
                    pool_failed = True

        if cancellation is not None:
            raise cancellation
        if drain_failed or pool_failed:
            raise DraftOperationTasksTransferLifecycleError(
                "draft operation shutdown transfer failed"
            ) from None

    def _on_drain_done(self, task: asyncio.Task[None]) -> None:
        self._drain_succeeded = self._task_succeeded(task)
        self._drain_task = None
        _consume_background_result(task)

    @staticmethod
    def _task_succeeded(task: asyncio.Future[object]) -> bool:
        if not task.done() or task.cancelled():
            return False
        try:
            task.result()
        except BaseException:
            return False
        return True


class DraftOperationTasksDrainPending(TimeoutError):
    """The bounded shutdown decision transferred an unfinished drain."""

    def __init__(self, transfer: DraftOperationTasksCleanupTransfer) -> None:
        super().__init__("draft operation task shutdown drain is pending")
        self.cleanup_transfer = transfer


class DraftOperationTaskRegistry:
    """Own worker tasks and their cancellation signals across app generations."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[asyncio.Future[None], asyncio.Event]] = {}
        self._state = "inactive"
        self._close_task: asyncio.Task[None] | None = None
        self._cleanup_transfer: DraftOperationTasksCleanupTransfer | None = None

    async def start(self) -> None:
        if self._state == "closing":
            raise RuntimeError("draft operation task registry is closing")
        if self._state == "active":
            return
        if (
            self._cleanup_transfer is not None
            and not self._cleanup_transfer._allows_restart()
        ):
            raise RuntimeError("draft operation task registry transfer is pending")
        self._close_task = None
        self._cleanup_transfer = None
        self._state = "active"

    def launch(
        self,
        operation_id: str,
        worker: Callable[[asyncio.Event], Awaitable[None]],
    ) -> asyncio.Event:
        if self._state != "active":
            raise RuntimeError("draft operation task registry is not active")
        if operation_id in self._entries:
            raise RuntimeError("draft operation task is already registered")

        signal = asyncio.Event()
        task = asyncio.ensure_future(worker(signal))
        self._entries[operation_id] = (task, signal)
        task.add_done_callback(
            lambda completed: self._on_done(operation_id, completed)
        )
        return signal

    def cancel(self, operation_id: str) -> bool:
        entry = self._entries.get(operation_id)
        if entry is None:
            return False
        task, signal = entry
        signal.set()
        task.cancel()
        return True

    async def aclose(self) -> None:
        if self._state == "closed":
            return
        if self._close_task is None:
            self._begin_close()

        close_task = self._close_task
        cancellation: asyncio.CancelledError | None = None
        while not close_task.done():
            try:
                await asyncio.shield(close_task)
            except asyncio.CancelledError as error:
                if cancellation is None:
                    cancellation = error
            except BaseException:
                pass

        close_error: BaseException | None = None
        try:
            close_task.result()
        except BaseException as error:
            error.__traceback__ = None
            error.__cause__ = None
            error.__context__ = None
            close_error = error
        if cancellation is not None:
            raise cancellation
        if close_error is not None:
            raise close_error from None

    def _begin_close(self) -> None:
        self._state = "closing"
        entries = tuple(self._entries.items())
        for _, (task, signal) in entries:
            signal.set()
            task.cancel()
        self._close_task = asyncio.create_task(
            self._make_bounded_close_decision(entries),
            name="draft-operation-task-registry-drain-decision",
        )

    @property
    def size(self) -> int:
        return len(self._entries)

    @property
    def state(self) -> str:
        return self._state

    def _on_done(self, operation_id: str, task: asyncio.Future[None]) -> None:
        entry = self._entries.get(operation_id)
        if (
            self._state != "closing"
            and entry is not None
            and entry[0] is task
        ):
            self._entries.pop(operation_id)
        self._consume_result(task)

    async def _make_bounded_close_decision(
        self,
        entries: tuple[
            tuple[str, tuple[asyncio.Future[None], asyncio.Event]],
            ...,
        ],
    ) -> None:
        tasks = tuple(entry[0] for _, entry in entries)
        if not tasks:
            self._finish_close(entries)
            return
        _, pending = await asyncio.wait(
            tasks,
            timeout=_DRAFT_OPERATION_TASK_SHUTDOWN_TIMEOUT_SECONDS,
        )
        if not pending:
            self._finish_close(entries)
            return

        drain_task = asyncio.create_task(
            self._finish_transferred_close(entries),
            name="draft-operation-task-registry-transferred-drain",
        )
        transfer = DraftOperationTasksCleanupTransfer(drain_task)
        self._cleanup_transfer = transfer
        raise DraftOperationTasksDrainPending(transfer)

    async def _finish_transferred_close(
        self,
        entries: tuple[
            tuple[str, tuple[asyncio.Future[None], asyncio.Event]],
            ...,
        ],
    ) -> None:
        tasks = tuple(entry[0] for _, entry in entries)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._finish_close(entries)

    def _finish_close(
        self,
        entries: tuple[
            tuple[str, tuple[asyncio.Future[None], asyncio.Event]],
            ...,
        ],
    ) -> None:
        for operation_id, entry in entries:
            self._consume_result(entry[0])
            if self._entries.get(operation_id) is entry:
                self._entries.pop(operation_id)
        self._state = "closed"

    @staticmethod
    def _consume_result(task: asyncio.Future[None]) -> None:
        if not task.done():
            return
        try:
            task.result()
        except BaseException:
            pass
