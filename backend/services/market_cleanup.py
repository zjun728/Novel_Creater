"""Stable ownership ledger for bounded market database cleanup tasks."""

from __future__ import annotations

import asyncio


class MarketCleanupLedger:
    def __init__(self) -> None:
        self._next_sequence = 0
        self._sequences: dict[asyncio.Task, int] = {}
        self._active: dict[asyncio.Task, int] = {}
        self._completed: dict[
            int,
            tuple[asyncio.Task, BaseException | None],
        ] = {}

    def track(self, task: asyncio.Task) -> None:
        if task in self._sequences:
            raise RuntimeError("market cleanup task is already tracked")
        self._next_sequence += 1
        sequence = self._next_sequence
        self._sequences[task] = sequence
        self._active[task] = sequence
        task.add_done_callback(self._capture)

    def _capture(self, task: asyncio.Task) -> None:
        sequence = self._sequences.get(task)
        if sequence is None or sequence in self._completed:
            return
        self._active.pop(task, None)
        error = None
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except BaseException as task_error:
            error = task_error
        self._completed[sequence] = (task, error)

    def capture_done(self, tasks) -> None:
        for task in tasks:
            if task.done():
                self._capture(task)

    def release(self, task: asyncio.Task) -> None:
        sequence = self._sequences.pop(task, None)
        if sequence is None:
            return
        self._active.pop(task, None)
        self._completed.pop(sequence, None)
        if task.done():
            try:
                task.result()
            except BaseException:
                pass

    def pending_tasks(self) -> tuple[asyncio.Task, ...]:
        return tuple(
            task
            for task, _ in sorted(
                self._active.items(),
                key=lambda item: item[1],
            )
        )

    def take_errors(self) -> tuple[BaseException, ...]:
        errors = []
        for sequence in sorted(self._completed):
            task, error = self._completed[sequence]
            self._sequences.pop(task, None)
            if error is not None:
                errors.append(error)
        self._completed.clear()
        return tuple(errors)

    def has_work(self) -> bool:
        return bool(self._active or self._completed)
