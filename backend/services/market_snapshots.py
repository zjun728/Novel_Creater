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
    ) -> None:
        self.repository = repository
        self._transaction = transaction_factory
        self._connection = connection_factory
        self.adapters = dict(adapters)
        self.manual_adapter = manual_adapter or ManualSnapshotAdapter()
        self._id = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: int(time.time() * 1000))

    async def _reserve(
        self,
        source_id: str,
        idempotency_key: str,
        request_hash: str,
        *,
        enforce_cooldown: bool,
    ):
        async with self._transaction() as session:
            reservation = await self.repository.reserve_refresh(
                session,
                source_id=source_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                input_manifest_hash=canonical_hash(
                    {
                        "sourceId": source_id,
                        "requestHash": request_hash,
                    }
                ),
                now_ms=self._clock(),
                enforce_cooldown=enforce_cooldown,
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
        async with self._transaction() as session:
            await self.repository.fail_refresh(
                session,
                request_id=reservation["request_id"],
                source_id=reservation["source"]["id"],
                public_error_code=failure.code,
                completed_at=self._clock(),
            )

    async def _cleanup_cancellation(
        self,
        reservation: dict,
    ) -> BaseException | None:
        async def abandon() -> None:
            async with self._transaction() as session:
                await self.repository.abandon_refresh(
                    session,
                    request_id=reservation["request_id"],
                    source_id=reservation["source"]["id"],
                    public_error_code="MARKET_REFRESH_CANCELLED",
                    completed_at=self._clock(),
                )

        cleanup = asyncio.create_task(abandon())
        try:
            await asyncio.wait_for(
                asyncio.shield(cleanup),
                timeout=CANCELLATION_CLEANUP_TIMEOUT_SECONDS,
            )
        except TimeoutError as error:
            cleanup.cancel()
            done, _ = await asyncio.wait(
                (cleanup,),
                timeout=CANCELLATION_CLEANUP_TIMEOUT_SECONDS,
            )
            if cleanup in done and not cleanup.cancelled():
                cleanup.exception()
            elif cleanup not in done:
                cleanup.add_done_callback(
                    lambda task: None
                    if task.cancelled()
                    else task.exception()
                )
            return error
        except BaseException as error:
            return error
        return None

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
        async with self._transaction() as session:
            result = await self.repository.publish_snapshot(
                session,
                request_id=reservation["request_id"],
                source_id=source["id"],
                snapshot=snapshot,
                snapshot_id=snapshot_id,
                snapshot_hash=snapshot_hash,
                entry_ids=entry_ids,
                entry_hashes=entry_hashes,
                manifest_id=manifest_id,
                manifest=manifest,
                manifest_hash=canonical_hash(manifest),
                adapter_version=adapter_version,
                policy_revision_id=source["policy_revision_id"],
                policy_revision=source["policy_revision"],
                policy_hash=source["policy_hash"],
                completed_at=self._clock(),
            )
        if result.get("kind") == "rejected":
            raise MarketSourceFailure(result["code"])
        return result

    async def refresh(self, source_id: str, *, idempotency_key: str):
        request_hash = canonical_hash(
            {"sourceId": source_id, "mode": "automatic"}
        )
        reservation = await self._reserve(
            source_id,
            idempotency_key,
            request_hash,
            enforce_cooldown=True,
        )
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
