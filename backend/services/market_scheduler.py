"""Bounded local orchestration for due market-source schedules."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time

from backend.domain.json_contracts import canonical_hash


MIN_FAILURE_BACKOFF_MS = 60_000
MAX_FAILURE_BACKOFF_MS = 15 * 60_000
MAX_SOURCES_PER_TICK = 16
logger = logging.getLogger(__name__)


def scheduled_failure_backoff_ms(interval_minutes: int) -> int:
    requested = int(interval_minutes) * 60_000
    return min(
        max(requested, MIN_FAILURE_BACKOFF_MS),
        MAX_FAILURE_BACKOFF_MS,
    )


def scheduled_idempotency_key(
    source_id: str,
    *,
    next_run_at: int,
    attempt_at: int,
) -> str:
    return canonical_hash(
        {
            "sourceId": source_id,
            "nextRunAt": next_run_at,
            "attemptMinute": attempt_at // 60_000,
            "mode": "scheduled",
        }
    )


@dataclass(frozen=True)
class MarketScheduleResult:
    source_id: str
    status: str

    def as_public_dict(self) -> dict[str, str]:
        return {"sourceId": self.source_id, "status": self.status}


class MarketScheduler:
    """Find a bounded due set, then execute outside the read boundary."""

    def __init__(
        self,
        repository,
        *,
        connection_factory,
        executor,
        clock=None,
        enabled: bool,
        max_sources_per_tick: int = MAX_SOURCES_PER_TICK,
    ) -> None:
        if not 1 <= max_sources_per_tick <= MAX_SOURCES_PER_TICK:
            raise ValueError("market scheduler tick bound is invalid")
        self.repository = repository
        self._connection = connection_factory
        self._executor = executor
        self._clock = clock or (lambda: int(time.time() * 1000))
        self.enabled = enabled is True
        self.max_sources_per_tick = max_sources_per_tick
        self.next_run_at: int | None = None

    async def _read_due(self, now_ms: int):
        async with self._connection() as session:
            due = await self.repository.list_due_schedules(
                session,
                now_ms=now_ms,
                limit=self.max_sources_per_tick,
            )
            if not due:
                self.next_run_at = await self.repository.next_scheduled_run(
                    session
                )
        return due

    async def _read_next_run(self) -> None:
        async with self._connection() as session:
            self.next_run_at = await self.repository.next_scheduled_run(session)

    async def run_once(self) -> tuple[MarketScheduleResult, ...]:
        if not self.enabled:
            self.next_run_at = None
            return ()
        attempt_at = self._clock()
        due = await self._read_due(attempt_at)
        if not due:
            return ()

        results = []
        for source in due:
            source_id = source["source_id"]
            idempotency_key = scheduled_idempotency_key(
                source_id,
                next_run_at=source["next_run_at"],
                attempt_at=attempt_at,
            )
            status = "succeeded"
            try:
                result = await self._executor(
                    source_id,
                    idempotency_key=idempotency_key,
                )
                if (
                    isinstance(result, dict)
                    and result.get("kind") == "skipped"
                ):
                    status = "skipped"
            except Exception:
                status = "failed"
            public_result = MarketScheduleResult(source_id, status)
            results.append(public_result)
            logger.info(
                "market scheduler source_id=%s status=%s",
                source_id,
                status,
            )
        await self._read_next_run()
        return tuple(results)
