from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from backend.tests.support.disposable_mysql import transaction_factory_for


pytestmark = [pytest.mark.mysql, pytest.mark.asyncio]
NOW = 1_721_000_000_000
SOURCE_ID = "71000000-0000-0000-0000-000000000101"
OLD_SNAPSHOT_ID = "71000000-0000-0000-0000-000000000201"
OLD_REQUEST_ID = "71000000-0000-0000-0000-000000000301"


class MutableClock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


async def _insert_source(
    session,
    *,
    source_id=SOURCE_ID,
    stable_key="synthetic.scheduler",
    policy_status="verified_public",
    enabled=False,
    interval_minutes=2,
    next_run_at=None,
    last_snapshot=False,
):
    from backend.domain.json_contracts import canonical_hash, canonical_json
    from backend.domain.market_sources import SourcePolicy

    policy = SourcePolicy(
        status=policy_status,
        checkedAt=NOW,
        evidenceURL="https://evidence.example/synthetic-scheduler",
        evidenceHash="e" * 64,
        allowedOrigins=("https://www.qidian.com",),
        pathPrefixes=("/rank/newsign/",),
        requestIntervalSeconds=interval_minutes * 60,
        policyVersion="synthetic-scheduler-policy-v1",
        enabled=enabled,
    )
    policy_id = source_id
    policy_hash = canonical_hash(policy)
    await session.execute(
        """INSERT INTO market_sources
           (id,stable_key,adapter_key,display_name,public_config_json,status,
            created_at,updated_at)
           VALUES (%s,%s,'qidian_public_rank','Synthetic Scheduler Source',
                   %s,'active',%s,%s)""",
        (
            source_id,
            stable_key,
            canonical_json(
                {
                    "platform": "qidian",
                    "rankingName": "newsign",
                    "category": "male",
                }
            ),
            NOW,
            NOW,
        ),
    )
    await session.execute(
        """INSERT INTO market_source_policy_revisions
           (id,source_id,revision,policy_status,policy_version,checked_at,
            evidence_url,evidence_hash,allowed_origins_json,
            path_prefixes_json,enabled,interval_minutes,next_run_at,
            content_hash,created_at)
           VALUES (%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            policy_id,
            source_id,
            policy.status,
            policy.policy_version,
            policy.checked_at,
            policy.evidence_url,
            policy.evidence_hash,
            canonical_json(list(policy.allowed_origins)),
            canonical_json(list(policy.path_prefixes)),
            int(enabled),
            interval_minutes,
            next_run_at,
            policy_hash,
            NOW,
        ),
    )
    await session.execute(
        """INSERT INTO market_source_policy_heads
           (source_id,revision_id,revision,content_hash,updated_at)
           VALUES (%s,%s,1,%s,%s)""",
        (source_id, policy_id, policy_hash, NOW),
    )
    snapshot_id = None
    last_succeeded_at = None
    if last_snapshot:
        snapshot_id = OLD_SNAPSHOT_ID
        last_succeeded_at = NOW - 10_000
        await session.execute(
            """INSERT INTO market_snapshots
               (id,source_id,captured_at,platform,ranking_name,category,
                source_url,content_hash,entry_count,created_at)
               VALUES (%s,%s,%s,'qidian','newsign','male',
                       'https://www.qidian.com/rank/newsign/',%s,1,%s)""",
            (
                snapshot_id,
                source_id,
                last_succeeded_at,
                "a" * 64,
                last_succeeded_at,
            ),
        )
    await session.execute(
        """INSERT INTO market_source_refresh_states
           (source_id,last_snapshot_id,refresh_status,lease_owner,
            lease_expires_at,last_attempted_at,last_succeeded_at,next_run_at,
            public_error_code,updated_at)
           VALUES (%s,%s,'idle',NULL,NULL,NULL,%s,%s,NULL,%s)""",
        (source_id, snapshot_id, last_succeeded_at, next_run_at, NOW),
    )


def _read_connection(transaction_factory):
    @asynccontextmanager
    async def connection():
        async with transaction_factory() as session:
            yield session

    return connection


def _snapshot(captured_at):
    from backend.domain.market import MarketEntry, MarketSnapshot

    return MarketSnapshot(
        platform="qidian",
        rankingName="newsign",
        category="male",
        capturedAt=captured_at,
        sourceURL="https://www.qidian.com/rank/newsign/",
        entries=(
            MarketEntry(
                rank=1,
                title="租约调度合成书",
                author="合成作者",
                category="奇幻",
                workURL="https://www.qidian.com/book/900000701/",
                publicMetrics={},
            ),
        ),
    )


async def test_schedule_update_is_revision_cas_idempotent_and_rejects_manual_before_mutation(
    disposable_mysql,
):
    from backend.domain.market_sources import (
        MarketSourceConflict,
        MarketSourceFailure,
    )
    from backend.repositories.market import MarketRepository
    from backend.services.market_sources import MarketSourceService

    manual_source_id = "71000000-0000-0000-0000-000000000102"
    disabled_source_id = "71000000-0000-0000-0000-000000000103"
    await _insert_source(disposable_mysql.session)
    await _insert_source(
        disposable_mysql.session,
        source_id=manual_source_id,
        stable_key="synthetic.manual",
        policy_status="manual_only",
    )
    await _insert_source(
        disposable_mysql.session,
        source_id=disabled_source_id,
        stable_key="synthetic.disabled",
        policy_status="disabled",
    )
    transaction = transaction_factory_for(disposable_mysql.connection_config)
    repository = MarketRepository()
    service = MarketSourceService(
        repository,
        snapshot_service=None,
        connection_factory=_read_connection(transaction),
        transaction_factory=transaction,
        clock=lambda: NOW,
    )

    initial = await service.get_source(SOURCE_ID)
    assert {
        "revision": initial["schedule_revision"],
        "enabled": initial["schedule_enabled"],
        "interval_minutes": initial["schedule_interval_minutes"],
        "next_run_at": initial["schedule_next_run_at"],
    } == {
        "revision": 1,
        "enabled": False,
        "interval_minutes": 2,
        "next_run_at": None,
    }

    first = await service.update_schedule(
        SOURCE_ID,
        expected_revision=1,
        enabled=True,
        interval_minutes=5,
        idempotency_key="s" * 64,
    )
    await disposable_mysql.session.execute(
        """UPDATE market_source_refresh_states
           SET public_error_code='MARKET_HTML_UNKNOWN'
           WHERE source_id=%s""",
        (SOURCE_ID,),
    )
    replay = await service.update_schedule(
        SOURCE_ID,
        expected_revision=1,
        enabled=True,
        interval_minutes=5,
        idempotency_key="s" * 64,
    )

    assert first == replay == {
        "source_id": SOURCE_ID,
        "revision": 2,
        "enabled": True,
        "interval_minutes": 5,
        "next_run_at": NOW,
        "policy_status": "verified_public",
        "recovery_reason": None,
    }
    count = await disposable_mysql.session.fetchone(
        """SELECT COUNT(*) AS count FROM market_source_policy_revisions
           WHERE source_id=%s""",
        (SOURCE_ID,),
    )
    assert count["count"] == 2
    with pytest.raises(MarketSourceConflict):
        await service.update_schedule(
            SOURCE_ID,
            expected_revision=1,
            enabled=False,
            interval_minutes=5,
            idempotency_key="t" * 64,
        )
    reloaded = await service.get_source(SOURCE_ID)
    assert {
        "revision": reloaded["schedule_revision"],
        "enabled": reloaded["schedule_enabled"],
        "interval_minutes": reloaded["schedule_interval_minutes"],
        "next_run_at": reloaded["schedule_next_run_at"],
    } == {
        "revision": 2,
        "enabled": True,
        "interval_minutes": 5,
        "next_run_at": NOW,
    }

    for rejected_source_id, key in (
        (manual_source_id, "m" * 64),
        (disabled_source_id, "d" * 64),
    ):
        with pytest.raises(MarketSourceFailure) as rejected:
            await service.update_schedule(
                rejected_source_id,
                expected_revision=1,
                enabled=True,
                interval_minutes=5,
                idempotency_key=key,
            )
        assert rejected.value.code == "MARKET_POLICY_NOT_VERIFIED"
        rows = await disposable_mysql.session.fetchone(
            """SELECT COUNT(*) AS count FROM market_source_policy_revisions
               WHERE source_id=%s""",
            (rejected_source_id,),
        )
        state = await disposable_mysql.session.fetchone(
            """SELECT next_run_at FROM market_source_refresh_states
               WHERE source_id=%s""",
            (rejected_source_id,),
        )
        assert rows["count"] == 1
        assert state["next_run_at"] is None


async def test_two_workers_share_bounded_owner_lease_and_success_runs_from_completion(
    disposable_mysql,
):
    from backend.repositories.market import MarketRepository
    from backend.services.market_scheduler import MarketScheduler
    from backend.services.market_snapshots import MarketSnapshotService

    await _insert_source(
        disposable_mysql.session,
        enabled=True,
        interval_minutes=2,
        next_run_at=NOW,
    )
    transaction = transaction_factory_for(disposable_mysql.connection_config)
    repository = MarketRepository()
    clock = MutableClock(NOW)

    class BlockingAdapter:
        adapter_version = "synthetic-scheduler-adapter-v1"

        def __init__(self):
            self.calls = 0
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def fetch(self, **kwargs):
            self.calls += 1
            self.started.set()
            await self.release.wait()
            return _snapshot(clock())

    adapter = BlockingAdapter()
    snapshots = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        adapters={"qidian_public_rank": adapter},
        id_factory=lambda: str(uuid4()),
        clock=clock,
    )
    scheduler = lambda: MarketScheduler(
        repository,
        connection_factory=_read_connection(transaction),
        executor=snapshots.refresh_scheduled,
        clock=clock,
        enabled=True,
    )

    first_task = asyncio.create_task(scheduler().run_once())
    await asyncio.wait_for(adapter.started.wait(), timeout=5)
    lease = await disposable_mysql.session.fetchone(
        """SELECT refresh_status,lease_owner,lease_expires_at
           FROM market_source_refresh_states WHERE source_id=%s""",
        (SOURCE_ID,),
    )
    assert lease["refresh_status"] == "leased"
    assert lease["lease_owner"] is not None
    assert 0 < lease["lease_expires_at"] - NOW <= 60_000

    second = await asyncio.wait_for(scheduler().run_once(), timeout=5)
    assert [result.status for result in second] == ["skipped"]
    assert adapter.calls == 1

    completed_at = NOW + 500
    clock.value = completed_at
    adapter.release.set()
    first = await asyncio.wait_for(first_task, timeout=5)

    assert [result.status for result in first] == ["succeeded"]
    state = await disposable_mysql.session.fetchone(
        """SELECT refresh_status,last_succeeded_at,next_run_at
           FROM market_source_refresh_states WHERE source_id=%s""",
        (SOURCE_ID,),
    )
    assert state == {
        "refresh_status": "idle",
        "last_succeeded_at": completed_at,
        "next_run_at": completed_at + 2 * 60_000,
    }


async def test_scheduled_failure_uses_bounded_backoff_and_retains_last_success(
    disposable_mysql,
):
    from backend.domain.market_sources import MarketSourceFailure
    from backend.repositories.market import MarketRepository
    from backend.services.market_scheduler import (
        MAX_FAILURE_BACKOFF_MS,
        MarketScheduler,
    )
    from backend.services.market_snapshots import MarketSnapshotService

    await _insert_source(
        disposable_mysql.session,
        enabled=True,
        interval_minutes=60,
        next_run_at=NOW,
        last_snapshot=True,
    )
    transaction = transaction_factory_for(disposable_mysql.connection_config)
    repository = MarketRepository()
    clock = MutableClock(NOW)

    class FailingAdapter:
        adapter_version = "synthetic-failing-adapter-v1"

        async def fetch(self, **kwargs):
            clock.value = NOW + 700
            raise MarketSourceFailure("MARKET_HTML_UNKNOWN")

    snapshots = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        adapters={"qidian_public_rank": FailingAdapter()},
        clock=clock,
    )
    scheduler = MarketScheduler(
        repository,
        connection_factory=_read_connection(transaction),
        executor=snapshots.refresh_scheduled,
        clock=clock,
        enabled=True,
    )

    results = await scheduler.run_once()

    assert [result.status for result in results] == ["failed"]
    state = await disposable_mysql.session.fetchone(
        """SELECT last_snapshot_id,last_succeeded_at,next_run_at,
                  public_error_code
           FROM market_source_refresh_states WHERE source_id=%s""",
        (SOURCE_ID,),
    )
    assert state["last_snapshot_id"] == OLD_SNAPSHOT_ID
    assert state["last_succeeded_at"] == NOW - 10_000
    assert state["public_error_code"] == "MARKET_HTML_UNKNOWN"
    assert clock() + 60_000 <= state["next_run_at"]
    assert state["next_run_at"] <= clock() + MAX_FAILURE_BACKOFF_MS

    retry_at = state["next_run_at"]

    class RecoveryAdapter:
        adapter_version = "synthetic-recovery-adapter-v1"

        def __init__(self):
            self.calls = 0

        async def fetch(self, **kwargs):
            self.calls += 1
            return _snapshot(clock())

    recovery = RecoveryAdapter()
    snapshots.adapters["qidian_public_rank"] = recovery
    clock.value = retry_at

    retried = await scheduler.run_once()

    assert [result.status for result in retried] == ["succeeded"]
    assert recovery.calls == 1
    recovered_state = await disposable_mysql.session.fetchone(
        """SELECT last_succeeded_at,next_run_at
           FROM market_source_refresh_states WHERE source_id=%s""",
        (SOURCE_ID,),
    )
    assert recovered_state == {
        "last_succeeded_at": retry_at,
        "next_run_at": retry_at + 60 * 60_000,
    }


async def test_explicit_refresh_does_not_advance_the_scheduled_executor_clock(
    disposable_mysql,
):
    from backend.repositories.market import MarketRepository
    from backend.services.market_scheduler import MarketScheduler
    from backend.services.market_snapshots import MarketSnapshotService

    scheduled_at = NOW + 60_000
    await _insert_source(
        disposable_mysql.session,
        enabled=True,
        interval_minutes=2,
        next_run_at=scheduled_at,
    )
    transaction = transaction_factory_for(disposable_mysql.connection_config)
    repository = MarketRepository()

    clock = MutableClock(NOW)

    class ExplicitAdapter:
        adapter_version = "synthetic-explicit-adapter-v1"

        def __init__(self):
            self.calls = 0

        async def fetch(self, **kwargs):
            self.calls += 1
            return _snapshot(clock())

    adapter = ExplicitAdapter()
    snapshots = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        adapters={"qidian_public_rank": adapter},
        id_factory=lambda: str(uuid4()),
        clock=clock,
    )

    await snapshots.refresh(SOURCE_ID, idempotency_key="e" * 64)

    state = await disposable_mysql.session.fetchone(
        """SELECT last_succeeded_at,next_run_at
           FROM market_source_refresh_states WHERE source_id=%s""",
        (SOURCE_ID,),
    )
    assert state == {
        "last_succeeded_at": NOW,
        "next_run_at": scheduled_at,
    }

    clock.value = scheduled_at
    scheduler = MarketScheduler(
        repository,
        connection_factory=_read_connection(transaction),
        executor=snapshots.refresh_scheduled,
        clock=clock,
        enabled=True,
    )
    scheduled = await scheduler.run_once()

    assert [result.status for result in scheduled] == ["succeeded"]
    assert adapter.calls == 2


async def test_expired_scheduled_lease_is_recovered_by_new_owner(
    disposable_mysql,
):
    from backend.domain.json_contracts import canonical_hash
    from backend.repositories.market import MarketRepository
    from backend.services.market_scheduler import (
        MarketScheduler,
        scheduled_idempotency_key,
    )
    from backend.services.market_snapshots import MarketSnapshotService

    await _insert_source(
        disposable_mysql.session,
        enabled=True,
        interval_minutes=1,
        next_run_at=NOW,
    )
    request_hash = canonical_hash(
        {"sourceId": SOURCE_ID, "mode": "scheduled"}
    )
    expired_key = scheduled_idempotency_key(
        SOURCE_ID,
        next_run_at=NOW,
        attempt_at=NOW - 60_000,
    )
    await disposable_mysql.session.execute(
        """INSERT INTO market_refresh_requests
           (id,source_id,idempotency_key,request_hash,policy_revision,
            input_manifest_hash,status,snapshot_id,result_hash,
            public_error_code,created_at,completed_at)
           VALUES (%s,%s,%s,%s,1,%s,'running',NULL,NULL,NULL,%s,NULL)""",
        (
            OLD_REQUEST_ID,
            SOURCE_ID,
            expired_key,
            request_hash,
            canonical_hash({"expired": True}),
            NOW - 90_000,
        ),
    )
    await disposable_mysql.session.execute(
        """UPDATE market_source_refresh_states
           SET refresh_status='leased',lease_owner=%s,lease_expires_at=%s,
               last_attempted_at=%s
           WHERE source_id=%s""",
        (OLD_REQUEST_ID, NOW - 1, NOW - 60_000, SOURCE_ID),
    )
    transaction = transaction_factory_for(disposable_mysql.connection_config)
    repository = MarketRepository()

    class SuccessAdapter:
        adapter_version = "synthetic-recovery-adapter-v1"

        async def fetch(self, **kwargs):
            return _snapshot(NOW)

    snapshots = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        adapters={"qidian_public_rank": SuccessAdapter()},
        id_factory=lambda: str(uuid4()),
        clock=lambda: NOW,
    )
    scheduler = MarketScheduler(
        repository,
        connection_factory=_read_connection(transaction),
        executor=snapshots.refresh_scheduled,
        clock=lambda: NOW,
        enabled=True,
    )

    results = await scheduler.run_once()

    assert [result.status for result in results] == ["succeeded"]
    expired = await disposable_mysql.session.fetchone(
        """SELECT status,public_error_code,completed_at
           FROM market_refresh_requests WHERE id=%s""",
        (OLD_REQUEST_ID,),
    )
    assert expired == {
        "status": "outcome_unknown",
        "public_error_code": "MARKET_REFRESH_LEASE_EXPIRED",
        "completed_at": NOW,
    }
    state = await disposable_mysql.session.fetchone(
        """SELECT refresh_status,lease_owner,last_succeeded_at,next_run_at
           FROM market_source_refresh_states WHERE source_id=%s""",
        (SOURCE_ID,),
    )
    assert state == {
        "refresh_status": "idle",
        "lease_owner": None,
        "last_succeeded_at": NOW,
        "next_run_at": NOW + 60_000,
    }


@pytest.mark.parametrize("terminal_method", ("fail_refresh", "abandon_refresh"))
async def test_expired_owner_cannot_finalize_failure_or_cancellation(
    disposable_mysql,
    terminal_method,
):
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.market_sources import MarketSourceConflict
    from backend.repositories.market import MarketRepository

    await _insert_source(disposable_mysql.session)
    transaction = transaction_factory_for(disposable_mysql.connection_config)
    repository = MarketRepository()
    request_hash = canonical_hash(
        {"sourceId": SOURCE_ID, "mode": "automatic"}
    )
    async with transaction() as session:
        reservation = await repository.reserve_refresh(
            session,
            source_id=SOURCE_ID,
            idempotency_key="f" * 64,
            request_hash=request_hash,
            input_manifest_hash=canonical_hash({"ownerFence": True}),
            now_ms=NOW,
            enforce_cooldown=True,
        )

    with pytest.raises(MarketSourceConflict):
        async with transaction() as session:
            await getattr(repository, terminal_method)(
                session,
                request_id=reservation["request_id"],
                source_id=SOURCE_ID,
                public_error_code="MARKET_REFRESH_FAILED",
                completed_at=NOW + 30_000,
            )

    request = await disposable_mysql.session.fetchone(
        """SELECT status,public_error_code,completed_at
           FROM market_refresh_requests WHERE id=%s""",
        (reservation["request_id"],),
    )
    state = await disposable_mysql.session.fetchone(
        """SELECT refresh_status,lease_owner,lease_expires_at
           FROM market_source_refresh_states WHERE source_id=%s""",
        (SOURCE_ID,),
    )
    assert request == {
        "status": "running",
        "public_error_code": None,
        "completed_at": None,
    }
    assert state == {
        "refresh_status": "leased",
        "lease_owner": reservation["request_id"],
        "lease_expires_at": NOW + 30_000,
    }
