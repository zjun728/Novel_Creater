"""Application-scoped supervision for in-process draft-operation workers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


_DRAFT_OPERATION_TASK_SHUTDOWN_TIMEOUT_SECONDS = 5.0


class DraftOperationTaskRegistry:
    """Own only active worker tasks and their cooperative cancellation signals."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[asyncio.Future[None], asyncio.Event]] = {}
        self._detached: set[asyncio.Future[None]] = set()
        self._active = False
        self._closing = False
        self._close_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._closing:
            raise RuntimeError("draft operation task registry is closing")
        if self._close_task is not None and self._close_task.done():
            self._close_task = None
        self._active = True

    def launch(
        self,
        operation_id: str,
        worker: Callable[[asyncio.Event], Awaitable[None]],
    ) -> asyncio.Event:
        if not self._active or self._closing:
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
        if self._close_task is None:
            self._active = False
            self._closing = True
            entries = tuple(self._entries.items())
            for _, (task, signal) in entries:
                signal.set()
                task.cancel()
            self._close_task = asyncio.create_task(self._drain(entries))

        close_task = self._close_task
        cancellation = None
        while not close_task.done():
            try:
                await asyncio.shield(close_task)
            except asyncio.CancelledError as error:
                if cancellation is None:
                    cancellation = error
        close_task.result()
        if cancellation is not None:
            raise cancellation

    @property
    def size(self) -> int:
        return len(self._entries)

    def _on_done(self, operation_id: str, task: asyncio.Future[None]) -> None:
        self._detached.discard(task)
        entry = self._entries.get(operation_id)
        if entry is not None and entry[0] is task:
            self._entries.pop(operation_id)
        self._consume_result(task)

    async def _drain(
        self,
        entries: tuple[
            tuple[str, tuple[asyncio.Future[None], asyncio.Event]],
            ...,
        ],
    ) -> None:
        tasks = tuple(entry[0] for _, entry in entries)
        pending = set(tasks)
        try:
            if tasks:
                done, pending = await asyncio.wait(
                    tasks,
                    timeout=_DRAFT_OPERATION_TASK_SHUTDOWN_TIMEOUT_SECONDS,
                )
                for task in done:
                    self._consume_result(task)
        finally:
            for operation_id, entry in entries:
                if self._entries.get(operation_id) is entry:
                    if entry[0] in pending and not entry[0].done():
                        self._detached.add(entry[0])
                    self._entries.pop(operation_id)
            self._closing = False

    @staticmethod
    def _consume_result(task: asyncio.Future[None]) -> None:
        if not task.done():
            return
        try:
            task.result()
        except BaseException:
            pass
