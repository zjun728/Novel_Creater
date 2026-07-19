"""Reserve, collect outside transactions, and atomically publish snapshots."""

from __future__ import annotations

import asyncio
import time
from uuid import uuid4

from backend.domain.json_contracts import canonical_hash
from backend.domain.market import MarketSnapshot, snapshot_content_value
from backend.domain.market_sources import (
    MarketSourceFailure,
    MarketSourceNotFound,
)
from backend.gateways.market_sources.manual_snapshot import ManualSnapshotAdapter
from backend.services.market_cleanup import MarketCleanupLedger
from backend.services.market_scheduler import scheduled_failure_backoff_ms


_FIXED_SOURCE_URLS = {
    "qidian_public_rank": "https://www.qidian.com/rank/newsign/",
    "qq_reading_public_rank": "https://book.qq.com/book-rank",
}
CANCELLATION_CLEANUP_TIMEOUT_SECONDS = 2.0


class MarketSnapshotService:
    def __init__(
        self,
        repository,
        *,
        transaction_factory,
        connection_factory=None,
        adapters,
        manual_adapter=None,
        id_factory=None,
        clock=None,
        cleanup_ledger: MarketCleanupLedger | None = None,
    ) -> None:
        self.repository = repository
        self._transaction = transaction_factory
        self._connection = connection_factory
        self.adapters = dict(adapters)
        self.manual_adapter = manual_adapter or ManualSnapshotAdapter()
        self._id = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._cleanup_ledger = cleanup_ledger
        self._cleanup_sequence = 0

    def _create_cleanup_task(self, coroutine) -> asyncio.Task:
        self._cleanup_sequence += 1
        task = asyncio.create_task(
            coroutine,
            name=f"market-database-cleanup-{self._cleanup_sequence}",
        )
        if self._cleanup_ledger is not None:
            self._cleanup_ledger.track(task)
        return task

    def _release_cleanup_task(self, task: asyncio.Task) -> None:
        if self._cleanup_ledger is not None:
            self._cleanup_ledger.release(task)

    @staticmethod
    def _contains_timeout(error: BaseException | None) -> bool:
        if isinstance(error, TimeoutError):
            return True
        if isinstance(error, BaseExceptionGroup):
            return any(
                MarketSnapshotService._contains_timeout(child)
                for child in error.exceptions
            )
        return False

    async def _reserve(
        self,
        source_id: str,
        idempotency_key: str,
        request_hash: str,
        *,
        enforce_cooldown: bool,
        scheduled: bool = False,
    ):
        values = {
            "source_id": source_id,
            "idempotency_key": idempotency_key,
            "request_hash": request_hash,
            "input_manifest_hash": canonical_hash(
                {
                    "sourceId": source_id,
                    "requestHash": request_hash,
                }
            ),
            "now_ms": self._clock(),
            "enforce_cooldown": enforce_cooldown,
        }
        if scheduled:
            values["scheduled"] = True
        async with self._transaction() as session:
            reservation = await self.repository.reserve_refresh(
                session,
                **values,
            )
        if reservation["kind"] == "rejected":
            raise MarketSourceFailure(reservation["code"])
        return reservation

    @staticmethod
    def _validate_identity(snapshot: MarketSnapshot, source: dict) -> None:
        config = source["public_config"]
        expected_source_url = _FIXED_SOURCE_URLS.get(source["adapter_key"])
        if (
            snapshot.platform != config["platform"]
            or snapshot.ranking_name != config["rankingName"]
            or snapshot.category != config["category"]
            or expected_source_url is None
            or snapshot.source_url != expected_source_url
        ):
            raise MarketSourceFailure("MARKET_SNAPSHOT_IDENTITY_MISMATCH")

    async def _record_failure(
        self,
        reservation: dict,
        failure: MarketSourceFailure,
    ) -> None:
        completed_at = self._clock()
        interval = reservation.get("scheduled_interval_minutes")
        next_run_at = (
            completed_at + scheduled_failure_backoff_ms(interval)
            if interval is not None
            else None
        )
        values = {
            "request_id": reservation["request_id"],
            "source_id": reservation["source"]["id"],
            "public_error_code": failure.code,
            "completed_at": completed_at,
        }
        if next_run_at is not None:
            values["next_run_at"] = next_run_at

        async def persist() -> None:
            async with self._transaction() as session:
                await self.repository.fail_refresh(
                    session,
                    **values,
                )

        persistence = self._create_cleanup_task(persist())
        try:
            await asyncio.shield(persistence)
        except asyncio.CancelledError as cancellation:
            cleanup_error = await self._await_bounded_task(persistence)
            if not self._contains_timeout(cleanup_error):
                self._release_cleanup_task(persistence)
            if cleanup_error is not None:
                raise BaseExceptionGroup(
                    "market refresh failure persistence cleanup failed",
                    [cancellation, cleanup_error],
                ) from None
            raise
        except BaseException:
            self._release_cleanup_task(persistence)
            raise
        else:
            self._release_cleanup_task(persistence)

    @staticmethod
    async def _await_bounded_task(
        cleanup: asyncio.Task,
    ) -> BaseException | None:
        def aggregate(errors: list[BaseException]) -> BaseException | None:
            if not errors:
                return None
            if len(errors) == 1:
                return errors[0]
            return BaseExceptionGroup(
                "market refresh cleanup was interrupted",
                errors,
            )

        def consume(task: asyncio.Task) -> None:
            try:
                task.result()
            except BaseException:
                pass

        async def cancel_at_deadline(
            error: TimeoutError,
        ) -> BaseException | None:
            cleanup.cancel()
            cleanup.add_done_callback(consume)
            try:
                await asyncio.sleep(0)
            except asyncio.CancelledError as interruption:
                interruptions.append(interruption)
            return aggregate([*interruptions, error])

        loop = asyncio.get_running_loop()
        deadline = (
            loop.time() + CANCELLATION_CLEANUP_TIMEOUT_SECONDS
        )
        interruptions: list[BaseException] = []
        while not cleanup.done():
            remaining = deadline - loop.time()
            if remaining <= 0:
                error = TimeoutError(
                    "market refresh cancellation cleanup timed out"
                )
                return await cancel_at_deadline(error)
            try:
                done, _ = await asyncio.wait(
                    (cleanup,),
                    timeout=remaining,
                )
            except asyncio.CancelledError as error:
                interruptions.append(error)
                cleanup.cancel()
                continue
            if not done:
                error = TimeoutError(
                    "market refresh cancellation cleanup timed out"
                )
                return await cancel_at_deadline(error)

        try:
            cleanup.result()
        except asyncio.CancelledError as error:
            if not interruptions:
                interruptions.append(error)
        except BaseException as error:
            interruptions.append(error)
        return aggregate(interruptions)

    async def _cleanup_cancellation(
        self,
        reservation: dict,
    ) -> BaseException | None:
        async def abandon() -> None:
            completed_at = self._clock()
            interval = reservation.get("scheduled_interval_minutes")
            next_run_at = (
                completed_at + scheduled_failure_backoff_ms(interval)
                if interval is not None
                else None
            )
            values = {
                "request_id": reservation["request_id"],
                "source_id": reservation["source"]["id"],
                "public_error_code": "MARKET_REFRESH_CANCELLED",
                "completed_at": completed_at,
            }
            if next_run_at is not None:
                values["next_run_at"] = next_run_at
            async with self._transaction() as session:
                await self.repository.abandon_refresh(
                    session,
                    **values,
                )

        cleanup = self._create_cleanup_task(abandon())
        cleanup_error = await self._await_bounded_task(cleanup)
        if not self._contains_timeout(cleanup_error):
            self._release_cleanup_task(cleanup)
        return cleanup_error

    async def _raise_after_cancellation(
        self,
        reservation: dict,
        cancellation: asyncio.CancelledError,
    ) -> None:
        cleanup_error = await self._cleanup_cancellation(reservation)
        if cleanup_error is not None:
            raise BaseExceptionGroup(
                "market refresh cancellation cleanup failed",
                [cancellation, cleanup_error],
            ) from None

    async def _source_for_manual_validation(self, source_id: str) -> dict:
        connection_factory = self._connection or self._transaction
        async with connection_factory() as session:
            source = await self.repository.get_source(session, source_id)
        if source is None:
            raise MarketSourceNotFound()
        return source

    async def _publish(
        self,
        reservation: dict,
        snapshot: MarketSnapshot,
        *,
        adapter_version: str,
    ):
        source = reservation["source"]
        self._validate_identity(snapshot, source)
        snapshot_hash = canonical_hash(snapshot_content_value(snapshot))
        manifest = {
            "sourceId": source["id"],
            "snapshotHash": snapshot_hash,
            "policyRevisionId": source["policy_revision_id"],
            "policyRevision": source["policy_revision"],
            "policyHash": source["policy_hash"],
            "adapterVersion": adapter_version,
            "publicConfig": source["public_config"],
        }
        snapshot_id = self._id()
        entry_ids = tuple(self._id() for _ in snapshot.entries)
        entry_hashes = tuple(
            canonical_hash(entry.model_dump(mode="json", by_alias=True))
            for entry in snapshot.entries
        )
        manifest_id = self._id()
        completed_at = self._clock()
        interval = reservation.get("scheduled_interval_minutes")
        next_run_at = (
            completed_at + int(interval) * 60_000
            if interval is not None
            else None
        )
        values = {
            "request_id": reservation["request_id"],
            "source_id": source["id"],
            "snapshot": snapshot,
            "snapshot_id": snapshot_id,
            "snapshot_hash": snapshot_hash,
            "entry_ids": entry_ids,
            "entry_hashes": entry_hashes,
            "manifest_id": manifest_id,
            "manifest": manifest,
            "manifest_hash": canonical_hash(manifest),
            "adapter_version": adapter_version,
            "policy_revision_id": source["policy_revision_id"],
            "policy_revision": source["policy_revision"],
            "policy_hash": source["policy_hash"],
            "completed_at": completed_at,
        }
        if next_run_at is not None:
            values["next_run_at"] = next_run_at
        async with self._transaction() as session:
            result = await self.repository.publish_snapshot(
                session,
                **values,
            )
        if result.get("kind") == "rejected":
            raise MarketSourceFailure(result["code"])
        return result

    async def _refresh(
        self,
        source_id: str,
        *,
        idempotency_key: str,
        scheduled: bool,
    ):
        request_hash = canonical_hash(
            {
                "sourceId": source_id,
                "mode": "scheduled" if scheduled else "automatic",
            }
        )
        reservation = await self._reserve(
            source_id,
            idempotency_key,
            request_hash,
            enforce_cooldown=True,
            scheduled=scheduled,
        )
        if reservation["kind"] == "skipped":
            return reservation
        if reservation["kind"] == "succeeded":
            return reservation["snapshot"]
        source = reservation["source"]
        try:
            adapter = self.adapters.get(source["adapter_key"])
            if adapter is None:
                raise MarketSourceFailure("MARKET_SOURCE_ADAPTER_UNAVAILABLE")
            snapshot = await adapter.fetch(
                policy=source.get("policy"),
                policy_hash=source.get("policy_hash"),
                captured_at=self._clock(),
            )
            self._validate_identity(snapshot, source)
        except asyncio.CancelledError as cancellation:
            await self._raise_after_cancellation(reservation, cancellation)
            raise
        except MarketSourceFailure as failure:
            await self._record_failure(reservation, failure)
            raise
        except Exception:
            failure = MarketSourceFailure("MARKET_REFRESH_FAILED")
            await self._record_failure(reservation, failure)
            raise failure from None

        try:
            return await self._publish(
                reservation,
                snapshot,
                adapter_version=adapter.adapter_version,
            )
        except asyncio.CancelledError as cancellation:
            await self._raise_after_cancellation(reservation, cancellation)
            raise
        except MarketSourceFailure:
            raise
        except Exception:
            failure = MarketSourceFailure("MARKET_REFRESH_FAILED")
            await self._record_failure(reservation, failure)
            raise failure from None

    async def refresh(self, source_id: str, *, idempotency_key: str):
        return await self._refresh(
            source_id,
            idempotency_key=idempotency_key,
            scheduled=False,
        )

    async def refresh_scheduled(
        self,
        source_id: str,
        *,
        idempotency_key: str,
    ):
        return await self._refresh(
            source_id,
            idempotency_key=idempotency_key,
            scheduled=True,
        )

    async def import_manual(
        self,
        source_id: str,
        payload,
        *,
        idempotency_key: str,
    ):
        source = await self._source_for_manual_validation(source_id)
        snapshot = self.manual_adapter.parse(
            payload,
            adapter_key=source["adapter_key"],
        )
        self._validate_identity(snapshot, source)
        normalized_payload = snapshot.model_dump(mode="json", by_alias=True)
        request_hash = canonical_hash(
            {
                "sourceId": source_id,
                "mode": "manual",
                "snapshot": normalized_payload,
            }
        )
        reservation = await self._reserve(
            source_id,
            idempotency_key,
            request_hash,
            enforce_cooldown=False,
        )
        if reservation["kind"] == "succeeded":
            return reservation["snapshot"]
        try:
            reserved_source = reservation["source"]
            snapshot = self.manual_adapter.parse(
                normalized_payload,
                adapter_key=reserved_source["adapter_key"],
            )
            self._validate_identity(snapshot, reserved_source)
        except MarketSourceFailure as failure:
            await self._record_failure(reservation, failure)
            raise
        except Exception:
            failure = MarketSourceFailure("MARKET_REFRESH_FAILED")
            await self._record_failure(reservation, failure)
            raise failure from None
        try:
            return await self._publish(
                reservation,
                snapshot,
                adapter_version=self.manual_adapter.adapter_version,
            )
        except asyncio.CancelledError as cancellation:
            await self._raise_after_cancellation(reservation, cancellation)
            raise
        except MarketSourceFailure:
            raise
        except Exception:
            failure = MarketSourceFailure("MARKET_REFRESH_FAILED")
            await self._record_failure(reservation, failure)
            raise failure from None

    async def list_snapshots(self, source_id: str):
        if self._connection is None:
            raise RuntimeError("market snapshot reads require a connection")
        async with self._connection() as session:
            source = await self.repository.get_source(session, source_id)
            if source is None:
                raise MarketSourceNotFound()
            return await self.repository.list_snapshots(session, source_id)

    async def get_snapshot(self, source_id: str, snapshot_id: str):
        if self._connection is None:
            raise RuntimeError("market snapshot reads require a connection")
        async with self._connection() as session:
            snapshot = await self.repository.get_snapshot(
                session,
                source_id,
                snapshot_id,
            )
        if snapshot is None:
            raise MarketSourceNotFound()
        return snapshot
