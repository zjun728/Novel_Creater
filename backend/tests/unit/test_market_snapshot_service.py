from __future__ import annotations

import asyncio
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
    def __init__(
        self,
        source,
        *,
        publish_started=None,
        publish_wait=None,
        abandon_failure=None,
        abandon_wait=None,
        abandon_cancelled=None,
        fail_started=None,
        fail_wait=None,
        fail_cancelled=None,
        fail_ignores_cancellation=False,
    ):
        self.source = source
        self.events = []
        self.published = []
        self.failed = []
        self.abandoned = []
        self.last_success = "previous-snapshot"
        self.publish_started = publish_started
        self.publish_wait = publish_wait
        self.abandon_failure = abandon_failure
        self.abandon_wait = abandon_wait
        self.abandon_cancelled = abandon_cancelled
        self.fail_started = fail_started
        self.fail_wait = fail_wait
        self.fail_cancelled = fail_cancelled
        self.fail_ignores_cancellation = fail_ignores_cancellation

    async def get_source(self, session, source_id):
        self.events.append(("get_source", source_id))
        return deepcopy(self.source) if source_id == SOURCE_ID else None

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
        if self.publish_started is not None:
            self.publish_started.set()
        if self.publish_wait is not None:
            await self.publish_wait.wait()
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
        if self.fail_started is not None:
            self.fail_started.set()
        if self.fail_wait is not None:
            try:
                await self.fail_wait.wait()
            except asyncio.CancelledError:
                if self.fail_cancelled is not None:
                    self.fail_cancelled.set()
                if not self.fail_ignores_cancellation:
                    raise
                asyncio.current_task().uncancel()
                await self.fail_wait.wait()
        self.events.append(("fail", values["public_error_code"]))
        self.failed.append(values)

    async def abandon_refresh(self, session, **values):
        self.events.append(("abandon", values["public_error_code"]))
        if self.abandon_wait is not None:
            try:
                await self.abandon_wait.wait()
            finally:
                if self.abandon_cancelled is not None:
                    self.abandon_cancelled.set()
        if self.abandon_failure is not None:
            raise self.abandon_failure
        self.abandoned.append(values)


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


def _connection(repository):
    @asynccontextmanager
    async def connection():
        repository.events.append(("connection-enter",))
        try:
            yield object()
        finally:
            repository.events.append(("connection-exit",))

    return connection


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
async def test_transport_timeout_records_fixed_terminal_failure_and_preserves_head():
    from backend.gateways.market_sources.base import MarketSourceFailure
    from backend.services.market_snapshots import MarketSnapshotService

    repository = FakeRepository(_source())
    transaction, state = _contexts(repository)
    adapter = FakeAdapter(
        None,
        state,
        failure=MarketSourceFailure("MARKET_TRANSPORT_TIMEOUT"),
    )
    service = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        adapters={"qidian_public_rank": adapter},
        id_factory=lambda: "unused",
        clock=lambda: NOW,
    )

    with pytest.raises(MarketSourceFailure) as timed_out:
        await service.refresh(SOURCE_ID, idempotency_key="t" * 64)

    assert timed_out.value.code == "MARKET_TRANSPORT_TIMEOUT"
    assert repository.last_success == "previous-snapshot"
    assert repository.failed[0]["public_error_code"] == (
        "MARKET_TRANSPORT_TIMEOUT"
    )


@pytest.mark.asyncio
async def test_cancellation_while_recording_failure_awaits_bounded_terminal_cleanup():
    from backend.gateways.market_sources.base import MarketSourceFailure
    from backend.services.market_snapshots import MarketSnapshotService

    failure_started = asyncio.Event()
    release_failure = asyncio.Event()
    failure_cancelled = asyncio.Event()
    repository = FakeRepository(
        _source(),
        fail_started=failure_started,
        fail_wait=release_failure,
        fail_cancelled=failure_cancelled,
    )
    transaction, state = _contexts(repository)
    adapter = FakeAdapter(
        None,
        state,
        failure=MarketSourceFailure("MARKET_HTML_UNKNOWN"),
    )
    service = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        adapters={"qidian_public_rank": adapter},
        clock=lambda: NOW,
    )
    refresh = asyncio.create_task(
        service.refresh(SOURCE_ID, idempotency_key="z" * 64)
    )
    await asyncio.wait_for(failure_started.wait(), timeout=1)

    refresh.cancel()
    await asyncio.sleep(0)
    assert not refresh.done()
    release_failure.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(refresh, timeout=1)

    assert repository.failed == [
        {
            "request_id": "request-1",
            "source_id": SOURCE_ID,
            "public_error_code": "MARKET_HTML_UNKNOWN",
            "completed_at": NOW,
        }
    ]
    assert not failure_cancelled.is_set()


@pytest.mark.asyncio
async def test_second_cancellation_cancels_and_consumes_failure_persistence():
    from backend.gateways.market_sources.base import MarketSourceFailure
    from backend.services.market_snapshots import MarketSnapshotService

    failure_started = asyncio.Event()
    release_failure = asyncio.Event()
    failure_cancelled = asyncio.Event()
    repository = FakeRepository(
        _source(),
        fail_started=failure_started,
        fail_wait=release_failure,
        fail_cancelled=failure_cancelled,
    )
    transaction, state = _contexts(repository)
    adapter = FakeAdapter(
        None,
        state,
        failure=MarketSourceFailure("MARKET_HTML_UNKNOWN"),
    )
    service = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        adapters={"qidian_public_rank": adapter},
        clock=lambda: NOW,
    )
    refresh = asyncio.create_task(
        service.refresh(SOURCE_ID, idempotency_key="y" * 64)
    )
    await asyncio.wait_for(failure_started.wait(), timeout=1)

    refresh.cancel()
    await asyncio.sleep(0)
    refresh.cancel()
    with pytest.raises(BaseExceptionGroup) as aggregated:
        await asyncio.wait_for(refresh, timeout=1)

    assert sum(
        isinstance(error, asyncio.CancelledError)
        for error in aggregated.value.exceptions
    ) == 2
    assert failure_cancelled.is_set()
    assert repository.failed == []


@pytest.mark.asyncio
async def test_bounded_cleanup_aggregates_child_failure_after_external_cancel():
    from backend.services.market_snapshots import MarketSnapshotService

    started = asyncio.Event()
    blocked = asyncio.Event()

    async def persistence() -> None:
        started.set()
        try:
            await blocked.wait()
        except asyncio.CancelledError:
            raise RuntimeError("synthetic cancellation failure") from None

    child = asyncio.create_task(persistence())
    cleanup = asyncio.create_task(
        MarketSnapshotService._await_bounded_task(child)
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    cleanup.cancel()
    result = await asyncio.wait_for(cleanup, timeout=1)

    assert isinstance(result, BaseExceptionGroup)
    assert any(
        isinstance(error, asyncio.CancelledError)
        for error in result.exceptions
    )
    assert any(
        isinstance(error, RuntimeError)
        for error in result.exceptions
    )
    assert child.done()


@pytest.mark.asyncio
async def test_stalled_database_cleanup_remains_under_runtime_ownership(
    monkeypatch,
):
    from backend.gateways.market_sources.base import MarketSourceFailure
    from backend.services import market_snapshots
    from backend.services.market_cleanup import MarketCleanupLedger
    from backend.services.market_snapshots import MarketSnapshotService

    failure_started = asyncio.Event()
    release_failure = asyncio.Event()
    failure_cancelled = asyncio.Event()
    cleanup_ledger = MarketCleanupLedger()
    repository = FakeRepository(
        _source(),
        fail_started=failure_started,
        fail_wait=release_failure,
        fail_cancelled=failure_cancelled,
        fail_ignores_cancellation=True,
    )
    transaction, state = _contexts(repository)
    adapter = FakeAdapter(
        None,
        state,
        failure=MarketSourceFailure("MARKET_HTML_UNKNOWN"),
    )
    monkeypatch.setattr(
        market_snapshots,
        "CANCELLATION_CLEANUP_TIMEOUT_SECONDS",
        0.01,
    )
    service = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        adapters={"qidian_public_rank": adapter},
        cleanup_ledger=cleanup_ledger,
        clock=lambda: NOW,
    )
    refresh = asyncio.create_task(
        service.refresh(SOURCE_ID, idempotency_key="x" * 64)
    )
    await asyncio.wait_for(failure_started.wait(), timeout=1)

    refresh.cancel()
    with pytest.raises(BaseExceptionGroup):
        await asyncio.wait_for(refresh, timeout=1)

    owned = cleanup_ledger.pending_tasks()
    assert len(owned) == 1
    assert not owned[0].done()
    assert failure_cancelled.is_set()
    release_failure.set()
    await asyncio.wait_for(asyncio.gather(*owned), timeout=1)
    await asyncio.sleep(0)

    assert cleanup_ledger.take_errors() == ()
    assert not cleanup_ledger.has_work()
    assert repository.failed[0]["public_error_code"] == "MARKET_HTML_UNKNOWN"


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ("fetch", "publish"))
async def test_cancellation_after_reservation_runs_owner_safe_terminal_cleanup(
    phase,
):
    from backend.services.market_snapshots import MarketSnapshotService

    started = asyncio.Event()
    blocked = asyncio.Event()
    repository = FakeRepository(
        _source(),
        publish_started=started if phase == "publish" else None,
        publish_wait=blocked if phase == "publish" else None,
    )
    transaction, state = _contexts(repository)

    class BlockingAdapter(FakeAdapter):
        async def fetch(self, **kwargs):
            if phase == "fetch":
                started.set()
                await blocked.wait()
            return await super().fetch(**kwargs)

    adapter = BlockingAdapter(_snapshot(), state)
    ids = iter(("snapshot-1", "entry-1", "manifest-1"))
    service = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        adapters={"qidian_public_rank": adapter},
        id_factory=lambda: next(ids),
        clock=lambda: NOW,
    )

    refresh = asyncio.create_task(
        service.refresh(SOURCE_ID, idempotency_key="c" * 64)
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    refresh.cancel()
    with pytest.raises(asyncio.CancelledError):
        await refresh

    assert repository.abandoned == [
        {
            "request_id": "request-1",
            "source_id": SOURCE_ID,
            "public_error_code": "MARKET_REFRESH_CANCELLED",
            "completed_at": NOW,
        }
    ]
    assert repository.failed == []


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_mode", ("failure", "timeout"))
async def test_cancellation_cleanup_failure_is_aggregated_and_bounded(
    cleanup_mode,
    monkeypatch,
):
    from backend.services import market_snapshots
    from backend.services.market_snapshots import MarketSnapshotService

    wait = asyncio.Event() if cleanup_mode == "timeout" else None
    cleanup_cancelled = asyncio.Event()
    repository = FakeRepository(
        _source(),
        abandon_failure=(
            RuntimeError("synthetic cleanup failure")
            if cleanup_mode == "failure"
            else None
        ),
        abandon_wait=wait,
        abandon_cancelled=cleanup_cancelled,
    )
    transaction, state = _contexts(repository)
    adapter = FakeAdapter(
        None,
        state,
        failure=asyncio.CancelledError(),
    )
    monkeypatch.setattr(
        market_snapshots,
        "CANCELLATION_CLEANUP_TIMEOUT_SECONDS",
        0.2 if cleanup_mode == "failure" else 0.01,
    )
    service = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        adapters={"qidian_public_rank": adapter},
        id_factory=lambda: "unused",
        clock=lambda: NOW,
    )
    started = asyncio.get_running_loop().time()

    with pytest.raises(BaseExceptionGroup) as aggregated:
        await service.refresh(SOURCE_ID, idempotency_key="g" * 64)

    elapsed = asyncio.get_running_loop().time() - started
    assert elapsed < 0.5
    assert any(
        isinstance(error, asyncio.CancelledError)
        for error in aggregated.value.exceptions
    )
    expected_cleanup_error = RuntimeError if cleanup_mode == "failure" else TimeoutError
    assert any(
        isinstance(error, expected_cleanup_error)
        for error in aggregated.value.exceptions
    )
    if cleanup_mode == "timeout":
        assert cleanup_cancelled.is_set()


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
async def test_manual_work_url_is_rejected_from_fixed_source_before_reservation():
    from backend.gateways.market_sources.base import MarketSourceFailure
    from backend.gateways.market_sources.manual_snapshot import ManualSnapshotAdapter
    from backend.services.market_snapshots import MarketSnapshotService

    repository = FakeRepository(_source())
    transaction, _ = _contexts(repository)
    service = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        connection_factory=_connection(repository),
        adapters={},
        manual_adapter=ManualSnapshotAdapter(),
        id_factory=lambda: "unused",
        clock=lambda: NOW,
    )
    payload = {
        **_snapshot().model_dump(mode="json", by_alias=True),
        "entries": [
            {
                **_snapshot().entries[0].model_dump(mode="json", by_alias=True),
                "workURL": "https://www.qidian.com:443/book/900000001/",
            }
        ],
    }

    with pytest.raises(MarketSourceFailure) as rejected:
        await service.import_manual(
            SOURCE_ID,
            payload,
            idempotency_key="w" * 64,
        )

    assert rejected.value.code == "MARKET_MANUAL_SNAPSHOT_INVALID"
    assert not {
        event[0]
        for event in repository.events
    }.intersection({"reserve", "publish", "fail"})


@pytest.mark.asyncio
async def test_invalid_manual_payload_is_rejected_before_reservation():
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
    assert repository.failed == []
    assert not any(event[0] == "reserve" for event in repository.events)
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
