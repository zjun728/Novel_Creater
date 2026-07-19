from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy

import pytest


NOW = 1_721_000_000_000
SOURCE_ID = "00000000-0000-0000-0000-000000000101"


def _snapshot():
    from backend.domain.market import MarketEntry, MarketSnapshot

    return MarketSnapshot(
        platform="qidian",
        ranking_name="newsign",
        category="male",
        captured_at=NOW,
        source_url="https://www.qidian.com/rank/newsign/",
        entries=(
            MarketEntry(
                rank=1,
                title="雾港天文钟",
                author="合成作者甲",
                category="奇幻",
                work_url="https://www.qidian.com/book/900000001/",
                public_metrics={"weeklyRecommendations": 321},
            ),
        ),
    )


class FakeRepository:
    def __init__(self, source):
        self.source = source
        self.events = []
        self.published = []
        self.failed = []
        self.last_success = "previous-snapshot"

    async def reserve_refresh(
        self,
        session,
        *,
        source_id,
        idempotency_key,
        request_hash,
        input_manifest_hash,
        now_ms,
        enforce_cooldown,
    ):
        self.events.append(
            ("reserve", source_id, idempotency_key, enforce_cooldown)
        )
        return {
            "kind": "reserved",
            "request_id": "request-1",
            "source": deepcopy(self.source),
        }

    async def publish_snapshot(self, session, **values):
        self.events.append(("publish", values["snapshot_hash"]))
        self.published.append(values)
        self.last_success = values["snapshot_id"]
        return {
            "id": values["snapshot_id"],
            "source_id": SOURCE_ID,
            "content_hash": values["snapshot_hash"],
            "entry_count": len(values["snapshot"].entries),
        }

    async def fail_refresh(self, session, **values):
        self.events.append(("fail", values["public_error_code"]))
        self.failed.append(values)


def _contexts(repository):
    in_transaction = {"value": False}

    @asynccontextmanager
    async def transaction():
        assert in_transaction["value"] is False
        in_transaction["value"] = True
        repository.events.append(("transaction-enter",))
        try:
            yield object()
        finally:
            repository.events.append(("transaction-exit",))
            in_transaction["value"] = False

    return transaction, in_transaction


class FakeAdapter:
    adapter_version = "fixture-adapter-v1"

    def __init__(self, snapshot, in_transaction, failure=None):
        self.snapshot = snapshot
        self.in_transaction = in_transaction
        self.failure = failure
        self.calls = []

    async def fetch(self, **kwargs):
        assert self.in_transaction["value"] is False
        self.calls.append(kwargs)
        if self.failure is not None:
            raise self.failure
        return self.snapshot


def _source():
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.market_sources import SourcePolicy

    policy = SourcePolicy(
        status="verified_public",
        checkedAt=NOW - 100,
        evidenceURL="https://evidence.example/qidian",
        evidenceHash="a" * 64,
        allowedOrigins=("https://www.qidian.com",),
        pathPrefixes=("/rank/newsign/",),
        requestIntervalSeconds=3600,
        policyVersion="public-rank-policy-v1",
        enabled=False,
    )
    return {
        "id": SOURCE_ID,
        "adapter_key": "qidian_public_rank",
        "public_config": {
            "platform": "qidian",
            "rankingName": "newsign",
            "category": "male",
        },
        "policy": policy,
        "policy_hash": canonical_hash(policy),
        "policy_revision_id": "policy-revision-1",
        "policy_revision": 1,
    }


@pytest.mark.asyncio
async def test_refresh_fetches_outside_transactions_then_publishes_complete_snapshot():
    from backend.services.market_snapshots import MarketSnapshotService

    repository = FakeRepository(_source())
    transaction, state = _contexts(repository)
    adapter = FakeAdapter(_snapshot(), state)
    ids = iter(("snapshot-1", "entry-1", "manifest-1"))
    service = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        adapters={"qidian_public_rank": adapter},
        id_factory=lambda: next(ids),
        clock=lambda: NOW,
    )

    result = await service.refresh(SOURCE_ID, idempotency_key="r" * 64)

    assert result["entry_count"] == 1
    assert [event[0] for event in repository.events] == [
        "transaction-enter",
        "reserve",
        "transaction-exit",
        "transaction-enter",
        "publish",
        "transaction-exit",
    ]
    assert len(repository.published) == 1
    published = repository.published[0]
    assert published["snapshot_hash"]
    assert published["manifest"]["policyHash"] == _source()["policy_hash"]
    assert "raw" not in repr(published).casefold()


@pytest.mark.asyncio
async def test_failed_fetch_retains_last_success_and_persists_only_fixed_public_code():
    from backend.gateways.market_sources.base import MarketSourceFailure
    from backend.services.market_snapshots import MarketSnapshotService

    repository = FakeRepository(_source())
    transaction, state = _contexts(repository)
    failure = MarketSourceFailure("MARKET_HTML_UNKNOWN")
    adapter = FakeAdapter(None, state, failure=failure)
    service = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        adapters={"qidian_public_rank": adapter},
        id_factory=lambda: "unused",
        clock=lambda: NOW,
    )

    with pytest.raises(MarketSourceFailure) as captured:
        await service.refresh(SOURCE_ID, idempotency_key="f" * 64)

    assert captured.value.code == "MARKET_HTML_UNKNOWN"
    assert repository.last_success == "previous-snapshot"
    assert repository.published == []
    assert repository.failed == [
        {
            "request_id": "request-1",
            "source_id": SOURCE_ID,
            "public_error_code": "MARKET_HTML_UNKNOWN",
            "completed_at": NOW,
        }
    ]
    assert "<html" not in repr(repository.failed).casefold()


@pytest.mark.asyncio
async def test_manual_import_uses_strict_adapter_and_same_publication_boundary():
    from backend.gateways.market_sources.manual_snapshot import ManualSnapshotAdapter
    from backend.services.market_snapshots import MarketSnapshotService

    source = _source()
    source["policy"] = source["policy"].model_copy(update={"status": "manual_only"})
    from backend.domain.json_contracts import canonical_hash
    source["policy_hash"] = canonical_hash(source["policy"])
    repository = FakeRepository(source)
    transaction, _ = _contexts(repository)
    ids = iter(("snapshot-1", "entry-1", "manifest-1"))
    service = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        adapters={},
        manual_adapter=ManualSnapshotAdapter(),
        id_factory=lambda: next(ids),
        clock=lambda: NOW,
    )
    payload = _snapshot().model_dump(mode="json", by_alias=True)

    result = await service.import_manual(
        SOURCE_ID,
        payload,
        idempotency_key="m" * 64,
    )

    assert result["entry_count"] == 1
    assert repository.published[0]["adapter_version"] == "manual-snapshot-v1"


@pytest.mark.asyncio
async def test_invalid_manual_payload_is_reserved_then_records_only_fixed_failure():
    from backend.gateways.market_sources.base import MarketSourceFailure
    from backend.gateways.market_sources.manual_snapshot import ManualSnapshotAdapter
    from backend.services.market_snapshots import MarketSnapshotService

    repository = FakeRepository(_source())
    transaction, _ = _contexts(repository)
    service = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        adapters={},
        manual_adapter=ManualSnapshotAdapter(),
        id_factory=lambda: "unused",
        clock=lambda: NOW,
    )
    payload = {
        **_snapshot().model_dump(mode="json", by_alias=True),
        "rawHTML": "<html>private response</html>",
    }

    with pytest.raises(MarketSourceFailure) as captured:
        await service.import_manual(
            SOURCE_ID,
            payload,
            idempotency_key="i" * 64,
        )

    assert captured.value.code == "MARKET_MANUAL_SNAPSHOT_INVALID"
    assert repository.published == []
    assert repository.failed[0]["public_error_code"] == (
        "MARKET_MANUAL_SNAPSHOT_INVALID"
    )
    assert "private response" not in repr(repository.failed)


@pytest.mark.asyncio
async def test_manual_import_cannot_replace_the_adapters_fixed_source_url():
    from backend.gateways.market_sources.base import MarketSourceFailure
    from backend.gateways.market_sources.manual_snapshot import ManualSnapshotAdapter
    from backend.services.market_snapshots import MarketSnapshotService

    repository = FakeRepository(_source())
    transaction, _ = _contexts(repository)
    service = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        adapters={},
        manual_adapter=ManualSnapshotAdapter(),
        id_factory=lambda: "unused",
        clock=lambda: NOW,
    )
    payload = {
        **_snapshot().model_dump(mode="json", by_alias=True),
        "sourceURL": "https://evil.example/rank",
    }

    with pytest.raises(MarketSourceFailure) as captured:
        await service.import_manual(
            SOURCE_ID,
            payload,
            idempotency_key="u" * 64,
        )

    assert captured.value.code == "MARKET_SNAPSHOT_IDENTITY_MISMATCH"
    assert repository.published == []


@pytest.mark.asyncio
async def test_public_inventory_does_not_advertise_expired_verified_policy():
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.market_sources import SourcePolicy
    from backend.services.market_sources import MarketSourceService

    policy = SourcePolicy(
        status="verified_public",
        checkedAt=NOW - 31 * 24 * 60 * 60 * 1000,
        evidenceURL="https://evidence.example/qidian",
        evidenceHash="a" * 64,
        allowedOrigins=("https://www.qidian.com",),
        pathPrefixes=("/rank/newsign/",),
        requestIntervalSeconds=3600,
        policyVersion="public-rank-policy-v1",
        enabled=False,
    )
    row = {
        **_source(),
        "stable_key": "qidian.newsign",
        "display_name": "起点新签榜",
        "policy": policy,
        "policy_hash": canonical_hash(policy),
        "refresh_status": "idle",
    }

    class ReadRepository:
        async def list_sources(self, session):
            return (row,)

    @asynccontextmanager
    async def connection():
        yield object()

    service = MarketSourceService(
        ReadRepository(),
        snapshot_service=None,
        connection_factory=connection,
        clock=lambda: NOW,
    )

    source = (await service.list_sources())[0]

    assert source["policy_status"] == "verified_public"
    assert source["automatic_refresh_allowed"] is False


@pytest.mark.asyncio
async def test_public_inventory_is_stably_bounded_to_one_hundred_sources():
    from backend.services.market_sources import MarketSourceService

    rows = tuple(
        {
            **_source(),
            "id": f"source-{index:03d}",
            "stable_key": f"source.{index:03d}",
            "display_name": f"Source {index:03d}",
            "refresh_status": "idle",
        }
        for index in range(105)
    )

    class ReadRepository:
        async def list_sources(self, session):
            return rows

    @asynccontextmanager
    async def connection():
        yield object()

    service = MarketSourceService(
        ReadRepository(),
        snapshot_service=None,
        connection_factory=connection,
        clock=lambda: NOW,
    )

    inventory = await service.list_sources()

    assert len(inventory) == 100
    assert inventory[0]["stable_key"] == "source.000"
    assert inventory[-1]["stable_key"] == "source.099"
