"""Provider execution loops for fenced draft operations.

This module deliberately knows nothing about persistence.  Every callback is a
short, awaited boundary supplied by :mod:`draft_operations`; provider and timer
waits therefore cannot accidentally hold a database transaction open.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
import time


DELTA_FLUSH_SCALARS = 256
DELTA_FLUSH_MS = 1_000
HEARTBEAT_MS = 10_000
DRAFT_OPERATION_LEASE_MS = 30_000
MAX_DRAFT_OPERATION_EVENTS = 2_048
_MAX_OUTPUT_SCALARS = 100_000


class DraftOperationExecution:
    """Drive one provider call while delegating durable state transitions."""

    def __init__(self, *, clock=None, sleep=None) -> None:
        self._clock = clock or (lambda: int(time.monotonic() * 1000))
        self._sleep = sleep or asyncio.sleep

    async def run_stream(
        self,
        *,
        stream: AsyncIterator[str],
        on_delta: Callable[[str], Awaitable[None]],
        on_heartbeat: Callable[[], Awaitable[None]],
        on_complete: Callable[[str], Awaitable[None]],
    ) -> None:
        iterator = stream.__aiter__()
        accumulated = ""
        persisted_scalars = 0
        renewed_at = self._clock()
        delta_at = renewed_at
        next_chunk: asyncio.Task[str] | None = asyncio.create_task(anext(iterator))
        timer: asyncio.Task[None] | None = None
        try:
            while True:
                now = self._clock()
                deadlines = [renewed_at + HEARTBEAT_MS]
                if len(accumulated) > persisted_scalars:
                    deadlines.append(delta_at + DELTA_FLUSH_MS)
                deadline = min(deadlines)
                timer = asyncio.create_task(
                    self._sleep(max(0, deadline - now) / 1000)
                )
                done, _ = await asyncio.wait(
                    (next_chunk, timer), return_when=asyncio.FIRST_COMPLETED
                )

                if next_chunk in done:
                    await self._cancel_timer(timer)
                    timer = None
                    try:
                        chunk = next_chunk.result()
                    except StopAsyncIteration:
                        next_chunk = None
                        if len(accumulated) > persisted_scalars:
                            await on_delta(accumulated)
                        await on_complete(accumulated)
                        return
                    self._validate_chunk(chunk)
                    accumulated += chunk
                    if len(accumulated) > _MAX_OUTPUT_SCALARS:
                        raise ValueError("draft provider result exceeds scalar limit")
                    if len(accumulated) - persisted_scalars >= DELTA_FLUSH_SCALARS:
                        await on_delta(accumulated)
                        persisted_scalars = len(accumulated)
                        renewed_at = self._clock()
                        delta_at = renewed_at
                    next_chunk = asyncio.create_task(anext(iterator))
                    continue

                timer.result()
                timer = None
                now = self._clock()
                if (
                    len(accumulated) > persisted_scalars
                    and now >= delta_at + DELTA_FLUSH_MS
                ):
                    await on_delta(accumulated)
                    persisted_scalars = len(accumulated)
                    renewed_at = self._clock()
                    delta_at = renewed_at
                elif now >= renewed_at + HEARTBEAT_MS:
                    await on_heartbeat()
                    renewed_at = self._clock()
        finally:
            await self._cancel_timer(timer)
            if next_chunk is not None and not next_chunk.done():
                next_chunk.cancel()
                await asyncio.gather(next_chunk, return_exceptions=True)

    async def run_non_stream(
        self,
        *,
        generate: Callable[[], Awaitable[str]],
        on_heartbeat: Callable[[], Awaitable[None]],
        on_complete: Callable[[str], Awaitable[None]],
    ) -> None:
        generation = asyncio.create_task(generate())
        heartbeat: asyncio.Task[None] | None = None
        renewed_at = self._clock()
        try:
            while True:
                heartbeat = asyncio.create_task(
                    self._sleep(
                        max(0, renewed_at + HEARTBEAT_MS - self._clock()) / 1000
                    )
                )
                done, _ = await asyncio.wait(
                    (generation, heartbeat), return_when=asyncio.FIRST_COMPLETED
                )
                if generation in done:
                    await self._cancel_timer(heartbeat)
                    heartbeat = None
                    generated = generation.result()
                    await on_complete(generated)
                    return
                heartbeat.result()
                heartbeat = None
                await on_heartbeat()
                renewed_at = self._clock()
        finally:
            await self._cancel_timer(heartbeat)
            if not generation.done():
                generation.cancel()
                await asyncio.gather(generation, return_exceptions=True)

    @staticmethod
    def _validate_chunk(chunk: object) -> None:
        if not isinstance(chunk, str):
            raise ValueError("draft provider stream chunk is invalid")
        try:
            chunk.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("draft provider stream chunk is invalid") from None

    @staticmethod
    async def _cancel_timer(timer: asyncio.Task[None] | None) -> None:
        if timer is None or timer.done():
            return
        timer.cancel()
        await asyncio.gather(timer, return_exceptions=True)


__all__ = [
    "DELTA_FLUSH_MS",
    "DELTA_FLUSH_SCALARS",
    "DRAFT_OPERATION_LEASE_MS",
    "DraftOperationExecution",
    "HEARTBEAT_MS",
    "MAX_DRAFT_OPERATION_EVENTS",
]
