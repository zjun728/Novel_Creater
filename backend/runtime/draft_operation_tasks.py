"""Application-scoped supervision for in-process draft-operation workers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


class DraftOperationTaskRegistry:
    """Own only active worker tasks and their cooperative cancellation signals."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[asyncio.Task[None], asyncio.Event]] = {}
        self._active = False
        self._closing = False

    async def start(self) -> None:
        if self._closing:
            raise RuntimeError("draft operation task registry is closing")
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
        task = asyncio.create_task(worker(signal))
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
        self._active = False
        self._closing = True
        entries = tuple(self._entries.items())
        tasks = []
        for _, (task, signal) in entries:
            signal.set()
            task.cancel()
            tasks.append(task)

        cancelled = False
        try:
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            cancelled = True
            if tasks:
                try:
                    await asyncio.gather(*tasks, return_exceptions=True)
                except asyncio.CancelledError:
                    pass
        finally:
            for operation_id, entry in entries:
                if self._entries.get(operation_id) is entry:
                    self._entries.pop(operation_id)
            self._closing = False

        if cancelled:
            raise asyncio.CancelledError

    @property
    def size(self) -> int:
        return len(self._entries)

    def _on_done(self, operation_id: str, task: asyncio.Task[None]) -> None:
        entry = self._entries.get(operation_id)
        if entry is not None and entry[0] is task:
            self._entries.pop(operation_id)
        try:
            task.result()
        except BaseException:
            pass
