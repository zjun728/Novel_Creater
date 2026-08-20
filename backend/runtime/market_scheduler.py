"""FastAPI-owned lifecycle for the optional local market scheduler."""

from __future__ import annotations

import asyncio

from backend.services.market_cleanup import MarketCleanupLedger


MIN_POLL_INTERVAL_SECONDS = 60.0
DEFAULT_SHUTDOWN_TIMEOUT_SECONDS = 3.0
_STATUS = {
    "enabled": False,
    "state": "disabled",
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


class MarketSchedulerCleanupTransfer:
    """Own stalled scheduler cleanup and close the pool after it finishes."""

    def __init__(
        self,
        task: asyncio.Task,
        cleanup_ledger: MarketCleanupLedger,
    ) -> None:
        self._scheduler_task = task
        self._cleanup_ledger = cleanup_ledger
        self._task: asyncio.Task | None = None

    async def _finish(self, close_pool) -> None:
        scheduler_errors: list[BaseException] = []
        scheduler_observed = False
        while True:
            tasks = []
            if not scheduler_observed:
                tasks.append(self._scheduler_task)
            cleanup_tasks = self._cleanup_ledger.pending_tasks()
            tasks.extend(cleanup_tasks)
            if not tasks:
                break
            results = await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )
            if not scheduler_observed:
                scheduler_result = results[0]
                scheduler_observed = True
                if (
                    isinstance(scheduler_result, BaseException)
                    and not isinstance(
                        scheduler_result,
                        asyncio.CancelledError,
                    )
                ):
                    scheduler_errors.append(scheduler_result)
            self._cleanup_ledger.capture_done(cleanup_tasks)
        errors = [
            *scheduler_errors,
            *self._cleanup_ledger.take_errors(),
        ]
        try:
            await close_pool()
        except BaseException as error:
            errors.append(error)
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise BaseExceptionGroup(
                "transferred market scheduler cleanup failed",
                errors,
            )

    def start_pool_close(self, close_pool) -> asyncio.Task:
        if self._task is None:
            self._task = asyncio.create_task(
                self._finish(close_pool),
                name="market-scheduler-shutdown-transfer",
            )
            self._task.add_done_callback(_consume_background_result)
        return self._task


class MarketSchedulerShutdownTimeout(TimeoutError):
    def __init__(self, transfer: MarketSchedulerCleanupTransfer) -> None:
        super().__init__("market scheduler shutdown cleanup timed out")
        self.cleanup_transfer = transfer


class MarketSchedulerRuntime:
    def __init__(
        self,
        scheduler,
        *,
        poll_interval_seconds: float = MIN_POLL_INTERVAL_SECONDS,
        shutdown_timeout_seconds: float = DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
        cleanup_ledger: MarketCleanupLedger | None = None,
    ) -> None:
        if poll_interval_seconds < MIN_POLL_INTERVAL_SECONDS:
            raise ValueError("market scheduler poll interval must be at least 60 seconds")
        if shutdown_timeout_seconds <= 0:
            raise ValueError("market scheduler shutdown timeout must be positive")
        self.scheduler = scheduler
        self.poll_interval_seconds = poll_interval_seconds
        self.shutdown_timeout_seconds = shutdown_timeout_seconds
        self._cleanup_ledger = cleanup_ledger or MarketCleanupLedger()
        self._task: asyncio.Task | None = None
        self._stopping = False
        self.state = "disabled" if not scheduler.enabled else "idle"
        self.next_run_at = None

    def start(self) -> None:
        if self._task is not None:
            return
        if not self.scheduler.enabled:
            self.state = "disabled"
            _set_status(enabled=False, state=self.state, next_run_at=None)
            return
        self._stopping = False
        self.state = "idle"
        _set_status(enabled=True, state=self.state, next_run_at=None)
        self._task = asyncio.create_task(
            self._run(),
            name="market-scheduler",
        )

    async def _run(self) -> None:
        while not self._stopping:
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
            if self._stopping:
                return
            await asyncio.sleep(self.poll_interval_seconds)

    async def stop(self) -> None:
        task = self._task
        self._task = None
        self._stopping = True
        try:
            if task is not None:
                loop = asyncio.get_running_loop()
                deadline = loop.time() + self.shutdown_timeout_seconds
                task.cancel()
                done, pending = await asyncio.wait(
                    (task,),
                    timeout=self.shutdown_timeout_seconds / 2,
                )
                if pending:
                    task.cancel()
                    remaining = max(0, deadline - loop.time())
                    done, pending = await asyncio.wait(
                        (task,),
                        timeout=remaining,
                    )
                    if pending:
                        raise MarketSchedulerShutdownTimeout(
                            MarketSchedulerCleanupTransfer(
                                task,
                                self._cleanup_ledger,
                            )
                        )
                    timeout_error = TimeoutError(
                        "market scheduler shutdown cleanup required forced cancellation"
                    )
                else:
                    timeout_error = None
                scheduler_error = None
                if task in done and not task.cancelled():
                    scheduler_error = task.exception()
                while self._cleanup_ledger.pending_tasks():
                    remaining = max(0, deadline - loop.time())
                    if remaining == 0:
                        raise MarketSchedulerShutdownTimeout(
                            MarketSchedulerCleanupTransfer(
                                task,
                                self._cleanup_ledger,
                            )
                        )
                    done_cleanup, pending_cleanup = await asyncio.wait(
                        self._cleanup_ledger.pending_tasks(),
                        timeout=remaining,
                    )
                    self._cleanup_ledger.capture_done(done_cleanup)
                    if pending_cleanup:
                        raise MarketSchedulerShutdownTimeout(
                            MarketSchedulerCleanupTransfer(
                                task,
                                self._cleanup_ledger,
                            )
                        )
                errors = [
                    error
                    for error in (timeout_error, scheduler_error)
                    if error is not None
                ]
                errors.extend(self._cleanup_ledger.take_errors())
                if len(errors) == 1:
                    raise errors[0]
                if errors:
                    raise BaseExceptionGroup(
                        "market scheduler shutdown cleanup failed",
                        errors,
                    )
        except asyncio.CancelledError as cancellation:
            if task is not None:
                cancellation.cleanup_transfer = (
                    MarketSchedulerCleanupTransfer(
                        task,
                        self._cleanup_ledger,
                    )
                )
            raise
        finally:
            self.state = "stopped"
            self.next_run_at = None
            _set_status(
                enabled=self.scheduler.enabled,
                state=self.state,
                next_run_at=None,
            )


def build_market_scheduler_runtime(*, enabled: bool) -> MarketSchedulerRuntime:
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
    cleanup_ledger = MarketCleanupLedger()
    snapshots = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        connection_factory=connection,
        adapters={
            "qidian_public_rank": QidianPublicRankAdapter(transport),
            "qq_reading_public_rank": QQReadingPublicRankAdapter(transport),
        },
        cleanup_ledger=cleanup_ledger,
    )
    scheduler = MarketScheduler(
        repository,
        connection_factory=connection,
        executor=snapshots.refresh_scheduled,
        enabled=enabled,
    )
    return MarketSchedulerRuntime(
        scheduler,
        cleanup_ledger=cleanup_ledger,
    )
