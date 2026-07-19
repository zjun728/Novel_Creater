"""FastAPI-owned lifecycle for the optional local market scheduler."""

from __future__ import annotations

import asyncio

from backend.config import MARKET_SCHEDULER_ENABLED


MIN_POLL_INTERVAL_SECONDS = 60.0
DEFAULT_SHUTDOWN_TIMEOUT_SECONDS = 3.0
_STATUS = {
    "enabled": MARKET_SCHEDULER_ENABLED,
    "state": "idle" if MARKET_SCHEDULER_ENABLED else "disabled",
    "next_run_at": None,
}


def get_scheduler_status() -> dict[str, object]:
    return dict(_STATUS)


def _set_status(*, enabled: bool, state: str, next_run_at) -> None:
    _STATUS.update(
        enabled=enabled is True,
        state=state,
        next_run_at=next_run_at if type(next_run_at) is int else None,
    )


def _consume_background_result(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    try:
        task.exception()
    except BaseException:
        return


class MarketSchedulerRuntime:
    def __init__(
        self,
        scheduler,
        *,
        poll_interval_seconds: float = MIN_POLL_INTERVAL_SECONDS,
        shutdown_timeout_seconds: float = DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
    ) -> None:
        if poll_interval_seconds < MIN_POLL_INTERVAL_SECONDS:
            raise ValueError("market scheduler poll interval must be at least 60 seconds")
        if shutdown_timeout_seconds <= 0:
            raise ValueError("market scheduler shutdown timeout must be positive")
        self.scheduler = scheduler
        self.poll_interval_seconds = poll_interval_seconds
        self.shutdown_timeout_seconds = shutdown_timeout_seconds
        self._task: asyncio.Task | None = None
        self.state = "disabled" if not scheduler.enabled else "idle"
        self.next_run_at = None

    def start(self) -> None:
        if self._task is not None:
            return
        if not self.scheduler.enabled:
            self.state = "disabled"
            _set_status(enabled=False, state=self.state, next_run_at=None)
            return
        self.state = "idle"
        _set_status(enabled=True, state=self.state, next_run_at=None)
        self._task = asyncio.create_task(
            self._run(),
            name="market-scheduler",
        )

    async def _run(self) -> None:
        while True:
            self.state = "running"
            _set_status(
                enabled=True,
                state=self.state,
                next_run_at=self.next_run_at,
            )
            try:
                await self.scheduler.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.state = "failed"
            else:
                self.state = "idle"
                self.next_run_at = self.scheduler.next_run_at
            _set_status(
                enabled=True,
                state=self.state,
                next_run_at=self.next_run_at,
            )
            await asyncio.sleep(self.poll_interval_seconds)

    async def stop(self) -> None:
        task = self._task
        self._task = None
        try:
            if task is not None:
                task.cancel()
                done, pending = await asyncio.wait(
                    (task,),
                    timeout=self.shutdown_timeout_seconds,
                )
                if pending:
                    task.cancel()
                    task.add_done_callback(_consume_background_result)
                    raise TimeoutError(
                        "market scheduler shutdown cleanup timed out"
                    )
                if task in done and not task.cancelled():
                    error = task.exception()
                    if error is not None:
                        raise error
        finally:
            self.state = "stopped"
            self.next_run_at = None
            _set_status(
                enabled=self.scheduler.enabled,
                state=self.state,
                next_run_at=None,
            )


def build_market_scheduler_runtime() -> MarketSchedulerRuntime:
    from backend.database import connection, transaction
    from backend.gateways.market_sources.base import HttpxMarketTransport
    from backend.gateways.market_sources.qidian_public_rank import (
        QidianPublicRankAdapter,
    )
    from backend.gateways.market_sources.qq_reading_public_rank import (
        QQReadingPublicRankAdapter,
    )
    from backend.repositories.market import MarketRepository
    from backend.services.market_scheduler import MarketScheduler
    from backend.services.market_snapshots import MarketSnapshotService

    repository = MarketRepository()
    transport = HttpxMarketTransport()
    snapshots = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        connection_factory=connection,
        adapters={
            "qidian_public_rank": QidianPublicRankAdapter(transport),
            "qq_reading_public_rank": QQReadingPublicRankAdapter(transport),
        },
    )
    scheduler = MarketScheduler(
        repository,
        connection_factory=connection,
        executor=snapshots.refresh_scheduled,
        enabled=MARKET_SCHEDULER_ENABLED,
    )
    return MarketSchedulerRuntime(scheduler)
