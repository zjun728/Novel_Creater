"""Reserve, collect outside transactions, and atomically publish snapshots."""

from __future__ import annotations

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
        request_hash = canonical_hash(
            {
                "sourceId": source_id,
                "mode": "manual",
                "snapshot": payload,
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
            snapshot = self.manual_adapter.parse(payload)
            self._validate_identity(snapshot, reservation["source"])
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
