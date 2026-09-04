from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from backend.tests.support.disposable_mysql import transaction_factory_for


pytestmark = [pytest.mark.mysql, pytest.mark.asyncio]
NOW = 1_721_000_000_000
MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "market-sources-v1.1.0"
    / "manifest.json"
)
V1_MANIFEST = MANIFEST.parent.parent / "market-sources-v1.0.0" / "manifest.json"


def _connection(disposable_mysql):
    @asynccontextmanager
    async def factory():
        yield disposable_mysql.session

    return factory


async def test_v1_to_v11_seed_keeps_snapshot_and_refresh_history(disposable_mysql):
    from backend.domain.market_sources import load_market_source_package
    from backend.gateways.market_sources.manual_snapshot import ManualSnapshotAdapter
    from backend.repositories.market import MarketRepository
    from backend.services.market_sources import MarketSourceSeedService
    from backend.services.market_snapshots import MarketSnapshotService

    ids = iter(f"29000000-0000-0000-0000-{index:012d}" for index in range(1, 100))
    id_factory = lambda: next(ids)
    repository = MarketRepository()
    transaction = transaction_factory_for(disposable_mysql.connection_config)
    seeder = MarketSourceSeedService(
        repository,
        transaction_factory=transaction,
        id_factory=id_factory,
        clock=lambda: NOW,
    )
    await seeder.seed(load_market_source_package(V1_MANIFEST))
    source = await disposable_mysql.session.fetchone(
        "SELECT id FROM market_sources WHERE stable_key='qidian.newsign'"
    )
    snapshot_service = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        connection_factory=_connection(disposable_mysql),
        adapters={},
        manual_adapter=ManualSnapshotAdapter(),
        id_factory=id_factory,
        clock=lambda: NOW,
    )
    snapshot = await snapshot_service.import_manual(
        source["id"],
        {
            "platform": "qidian",
            "rankingName": "newsign",
            "category": "male",
            "capturedAt": NOW,
            "sourceURL": "https://www.qidian.com/rank/newsign/",
            "entries": [
                {
                    "rank": 1,
                    "title": "历史作品",
                    "author": "历史作者",
                    "category": "奇幻",
                    "workURL": "https://www.qidian.com/book/900000001/",
                    "publicMetrics": {},
                }
            ],
        },
        idempotency_key="v" * 64,
    )

    upgraded = await seeder.seed(load_market_source_package(MANIFEST))
    replayed = await seeder.seed(load_market_source_package(MANIFEST))

    assert (upgraded.inserted, upgraded.updated, upgraded.replayed) == (5, 3, 2)
    assert (replayed.inserted, replayed.updated, replayed.replayed) == (0, 0, 10)
    counts = {}
    for table in (
        "market_source_policy_revisions",
        "market_snapshots",
        "market_refresh_requests",
        "market_source_refresh_states",
    ):
        row = await disposable_mysql.session.fetchone(
            f"SELECT COUNT(*) AS count FROM {table}"
        )
        counts[table] = int(row["count"])
    assert counts == {
        "market_source_policy_revisions": 13,
        "market_snapshots": 1,
        "market_refresh_requests": 1,
        "market_source_refresh_states": 10,
    }
    state = await disposable_mysql.session.fetchone(
        "SELECT last_snapshot_id FROM market_source_refresh_states WHERE source_id=%s",
        (source["id"],),
    )
    assert state["last_snapshot_id"] == snapshot["id"]


async def test_manual_snapshot_publication_is_immutable_idempotent_and_updates_head_last(
    disposable_mysql,
):
    from backend.domain.market_sources import load_market_source_package
    from backend.gateways.market_sources.manual_snapshot import ManualSnapshotAdapter
    from backend.repositories.market import MarketRepository
    from backend.services.market_sources import MarketSourceSeedService
    from backend.services.market_snapshots import MarketSnapshotService

    ids = iter(f"30000000-0000-0000-0000-{index:012d}" for index in range(1, 100))
    id_factory = lambda: next(ids)
    repository = MarketRepository()
    transaction = transaction_factory_for(disposable_mysql.connection_config)
    package = load_market_source_package(MANIFEST)
    seeder = MarketSourceSeedService(
        repository,
        transaction_factory=transaction,
        id_factory=id_factory,
        clock=lambda: NOW,
    )
    await seeder.seed(package)
    source_row = await disposable_mysql.session.fetchone(
        "SELECT id FROM market_sources WHERE stable_key='qidian.newsign'"
    )
    source_id = source_row["id"]
    service = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        connection_factory=_connection(disposable_mysql),
        adapters={},
        manual_adapter=ManualSnapshotAdapter(),
        id_factory=id_factory,
        clock=lambda: NOW,
    )
    payload = {
        "platform": "qidian",
        "rankingName": "newsign",
        "category": "male",
        "capturedAt": NOW,
        "sourceURL": "https://www.qidian.com/rank/newsign/",
        "entries": [
            {
                "rank": 1,
                "title": "雾港天文钟",
                "author": "合成作者甲",
                "category": "奇幻",
                "workURL": "https://www.qidian.com/book/900000001/",
                "publicMetrics": {"weeklyRecommendations": 321},
            },
            {
                "rank": 2,
                "title": "纸城夜航",
                "author": "合成作者乙",
                "category": "悬疑",
                "workURL": "https://www.qidian.com/book/900000002/",
                "publicMetrics": {"weeklyRecommendations": 210},
            },
        ],
    }

    first = await service.import_manual(source_id, payload, idempotency_key="a" * 64)
    replay = await service.import_manual(source_id, payload, idempotency_key="a" * 64)
    reused = await service.import_manual(source_id, payload, idempotency_key="b" * 64)

    assert first == replay == reused
    assert first["entry_count"] == len(first["entries"]) == 2
    assert [entry["rank"] for entry in first["entries"]] == [1, 2]
    counts = {}
    for table in (
        "market_snapshots",
        "market_snapshot_entries",
        "market_snapshot_manifests",
        "market_refresh_requests",
    ):
        row = await disposable_mysql.session.fetchone(
            f"SELECT COUNT(*) AS count FROM {table}"
        )
        counts[table] = int(row["count"])
    assert counts == {
        "market_snapshots": 1,
        "market_snapshot_entries": 2,
        "market_snapshot_manifests": 1,
        "market_refresh_requests": 2,
    }
    state = await disposable_mysql.session.fetchone(
        "SELECT last_snapshot_id,last_succeeded_at,public_error_code "
        "FROM market_source_refresh_states WHERE source_id=%s",
        (source_id,),
    )
    assert state == {
        "last_snapshot_id": first["id"],
        "last_succeeded_at": NOW,
        "public_error_code": None,
    }
    request = await disposable_mysql.session.fetchone(
        """SELECT r.request_hash,r.input_manifest_hash,s.adapter_key,
                  s.public_config_json,r.policy_revision,p.content_hash
           FROM market_refresh_requests r
           JOIN market_sources s ON s.id=r.source_id
           JOIN market_source_policy_revisions p
             ON p.source_id=r.source_id AND p.revision=r.policy_revision
           WHERE r.source_id=%s AND r.idempotency_key=%s""",
        (source_id, "a" * 64),
    )
    from backend.domain.json_contracts import canonical_hash
    import json

    assert request["input_manifest_hash"] == canonical_hash(
        {
            "sourceId": source_id,
            "adapterKey": request["adapter_key"],
            "publicConfig": json.loads(request["public_config_json"]),
            "policyRevision": request["policy_revision"],
            "policyHash": request["content_hash"],
            "requestHash": request["request_hash"],
        }
    )
    detail = await service.get_snapshot(source_id, first["id"])
    assert [entry["rank"] for entry in detail["entries"]] == [1, 2]
    assert "raw" not in repr(detail).casefold()


async def test_refresh_lease_blocks_other_key_and_cooldown_opens_no_transport(
    disposable_mysql,
):
    from backend.domain.json_contracts import canonical_hash, canonical_json
    from backend.domain.market import MarketEntry, MarketSnapshot
    from backend.domain.market_sources import (
        MarketSourceFailure,
        SourcePolicy,
        load_market_source_package,
    )
    from backend.repositories.market import MarketRepository
    from backend.services.market_sources import MarketSourceSeedService
    from backend.services.market_snapshots import MarketSnapshotService

    ids = iter(f"50000000-0000-0000-0000-{index:012d}" for index in range(1, 100))
    id_factory = lambda: next(ids)
    repository = MarketRepository()
    transaction = transaction_factory_for(disposable_mysql.connection_config)
    package = load_market_source_package(MANIFEST)
    await MarketSourceSeedService(
        repository,
        transaction_factory=transaction,
        id_factory=id_factory,
        clock=lambda: NOW,
    ).seed(package)
    source = await disposable_mysql.session.fetchone(
        "SELECT id FROM market_sources WHERE stable_key='qidian.newsign'"
    )
    source_id = source["id"]
    policy = SourcePolicy(
        status="verified_public",
        checkedAt=NOW,
        evidenceURL="https://evidence.example/qidian-public-rank",
        evidenceHash="e" * 64,
        allowedOrigins=("https://www.qidian.com",),
        pathPrefixes=("/rank/newsign/",),
        requestIntervalSeconds=60,
        policyVersion="integration-public-policy-v1",
        enabled=False,
    )
    policy_id = "50000000-0000-0000-0000-000000000901"
    policy_hash = canonical_hash(policy)
    await disposable_mysql.session.execute(
        """INSERT INTO market_source_policy_revisions
           (id,source_id,revision,policy_status,policy_version,checked_at,
            evidence_url,evidence_hash,allowed_origins_json,
            path_prefixes_json,enabled,interval_minutes,next_run_at,
            content_hash,created_at)
           VALUES (%s,%s,2,%s,%s,%s,%s,%s,%s,%s,0,1,NULL,%s,%s)""",
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
            policy_hash,
            NOW,
        ),
    )
    await disposable_mysql.session.execute(
        """UPDATE market_source_policy_heads
           SET revision_id=%s,revision=2,content_hash=%s,updated_at=%s
           WHERE source_id=%s""",
        (policy_id, policy_hash, NOW, source_id),
    )

    class BlockingAdapter:
        adapter_version = "blocking-public-adapter-v1"

        def __init__(self):
            self.calls = 0
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def fetch(self, **kwargs):
            self.calls += 1
            if self.calls > 1:
                raise AssertionError("transport reopened while lease/cooldown active")
            self.started.set()
            await self.release.wait()
            return MarketSnapshot(
                platform="qidian",
                ranking_name="newsign",
                category="male",
                captured_at=NOW,
                source_url="https://www.qidian.com/rank/newsign/",
                entries=(
                    MarketEntry(
                        rank=1,
                        title="并发租约合成书",
                        author="合成作者",
                        category="奇幻",
                        work_url="https://www.qidian.com/book/900000099/",
                        public_metrics={},
                    ),
                ),
            )

    adapter = BlockingAdapter()
    service = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        connection_factory=_connection(disposable_mysql),
        adapters={"qidian_public_rank": adapter},
        id_factory=id_factory,
        clock=lambda: NOW,
    )

    first_task = asyncio.create_task(
        service.refresh(source_id, idempotency_key="l" * 64)
    )
    await asyncio.wait_for(adapter.started.wait(), timeout=5)
    try:
        with pytest.raises(MarketSourceFailure) as busy:
            await service.refresh(source_id, idempotency_key="o" * 64)
        assert busy.value.code == "MARKET_REFRESH_IN_PROGRESS"
        assert adapter.calls == 1
    finally:
        adapter.release.set()
        first = await asyncio.wait_for(first_task, timeout=5)
    replay = await service.refresh(source_id, idempotency_key="l" * 64)
    assert replay == first
    assert replay["entry_count"] == len(replay["entries"]) == 1
    assert adapter.calls == 1

    with pytest.raises(MarketSourceFailure) as cooldown:
        await service.refresh(source_id, idempotency_key="c" * 64)
    assert cooldown.value.code == "MARKET_REFRESH_COOLDOWN"
    assert adapter.calls == 1
    state = await disposable_mysql.session.fetchone(
        """SELECT refresh_status,lease_owner,lease_expires_at,last_attempted_at,
                  last_snapshot_id,last_succeeded_at,public_error_code
           FROM market_source_refresh_states WHERE source_id=%s""",
        (source_id,),
    )
    assert state == {
        "refresh_status": "idle",
        "lease_owner": None,
        "lease_expires_at": None,
        "last_attempted_at": NOW,
        "last_snapshot_id": first["id"],
        "last_succeeded_at": NOW,
        "public_error_code": None,
    }


async def test_expired_refresh_lease_is_persistently_recovered_during_cooldown(
    disposable_mysql,
):
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.market_sources import (
        MarketSourceFailure,
        load_market_source_package,
    )
    from backend.repositories.market import MarketRepository
    from backend.services.market_sources import MarketSourceSeedService
    from backend.services.market_snapshots import MarketSnapshotService

    ids = iter(f"60000000-0000-0000-0000-{index:012d}" for index in range(1, 100))
    repository = MarketRepository()
    transaction = transaction_factory_for(disposable_mysql.connection_config)
    await MarketSourceSeedService(
        repository,
        transaction_factory=transaction,
        id_factory=lambda: next(ids),
        clock=lambda: NOW,
    ).seed(load_market_source_package(MANIFEST))
    source = await disposable_mysql.session.fetchone(
        "SELECT id FROM market_sources WHERE stable_key='qidian.newsign'"
    )
    source_id = source["id"]
    request_hash = canonical_hash(
        {"sourceId": source_id, "mode": "automatic"}
    )
    async with transaction() as session:
        reservation = await repository.reserve_refresh(
            session,
            source_id=source_id,
            idempotency_key="x" * 64,
            request_hash=request_hash,
            input_manifest_hash=canonical_hash({}),
            now_ms=NOW,
            enforce_cooldown=True,
        )
    assert reservation["kind"] == "reserved"

    class NoTransportAdapter:
        adapter_version = "no-transport-v1"

        async def fetch(self, **kwargs):
            raise AssertionError("expired lease recovery must not open transport")

    service = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        adapters={"qidian_public_rank": NoTransportAdapter()},
        clock=lambda: NOW + 30_001,
    )
    with pytest.raises(MarketSourceFailure) as cooldown:
        await service.refresh(source_id, idempotency_key="y" * 64)

    assert cooldown.value.code == "MARKET_REFRESH_COOLDOWN"
    state = await disposable_mysql.session.fetchone(
        """SELECT refresh_status,lease_owner,lease_expires_at,
                  last_attempted_at,public_error_code
           FROM market_source_refresh_states WHERE source_id=%s""",
        (source_id,),
    )
    assert state == {
        "refresh_status": "idle",
        "lease_owner": None,
        "lease_expires_at": None,
        "last_attempted_at": NOW,
        "public_error_code": "MARKET_REFRESH_LEASE_EXPIRED",
    }
    expired = await disposable_mysql.session.fetchone(
        """SELECT status,public_error_code,completed_at
           FROM market_refresh_requests WHERE id=%s""",
        (reservation["request_id"],),
    )
    assert expired == {
        "status": "outcome_unknown",
        "public_error_code": "MARKET_REFRESH_LEASE_EXPIRED",
        "completed_at": NOW + 30_001,
    }


@pytest.mark.parametrize("preexisting_snapshot", (False, True))
@pytest.mark.parametrize("competitor_recovers", (False, True))
async def test_expired_holder_cannot_publish_or_reuse_snapshot(
    disposable_mysql,
    preexisting_snapshot,
    competitor_recovers,
):
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.market import MarketEntry, MarketSnapshot
    from backend.domain.market_sources import (
        MarketSourceFailure,
        load_market_source_package,
    )
    from backend.gateways.market_sources.manual_snapshot import ManualSnapshotAdapter
    from backend.repositories.market import MarketRepository
    from backend.services.market_sources import MarketSourceSeedService
    from backend.services.market_snapshots import MarketSnapshotService

    ids = iter(f"70000000-0000-0000-0000-{index:012d}" for index in range(1, 200))
    id_factory = lambda: next(ids)
    repository = MarketRepository()
    transaction = transaction_factory_for(disposable_mysql.connection_config)
    await MarketSourceSeedService(
        repository,
        transaction_factory=transaction,
        id_factory=id_factory,
        clock=lambda: NOW - 60_000,
    ).seed(load_market_source_package(MANIFEST))
    source = await disposable_mysql.session.fetchone(
        "SELECT id FROM market_sources WHERE stable_key='qidian.newsign'"
    )
    source_id = source["id"]
    snapshot = MarketSnapshot(
        platform="qidian",
        rankingName="newsign",
        category="male",
        capturedAt=NOW,
        sourceURL="https://www.qidian.com/rank/newsign/",
        entries=(
            MarketEntry(
                rank=1,
                title="过期租约合成书",
                author="合成作者",
                category="奇幻",
                workURL="https://www.qidian.com/book/900000199/",
                publicMetrics={},
            ),
        ),
    )
    if preexisting_snapshot:
        seed_service = MarketSnapshotService(
            repository,
            transaction_factory=transaction,
            adapters={},
            manual_adapter=ManualSnapshotAdapter(),
            id_factory=id_factory,
            clock=lambda: NOW - 60_000,
        )
        await seed_service.import_manual(
            source_id,
            snapshot.model_dump(mode="json", by_alias=True),
            idempotency_key="p" * 64,
        )
        await disposable_mysql.session.execute(
            """UPDATE market_source_refresh_states
               SET last_snapshot_id=NULL,last_succeeded_at=NULL,
                   public_error_code=NULL,updated_at=%s
               WHERE source_id=%s""",
            (NOW, source_id),
        )

    now = {"value": NOW}
    competitor = {"reservation": None}

    class ExpiringAdapter:
        adapter_version = "expiring-public-adapter-v1"

        def __init__(self):
            self.calls = 0

        async def fetch(self, **kwargs):
            self.calls += 1
            now["value"] = NOW + 30_001
            if competitor_recovers:
                competitor_hash = canonical_hash(
                    {"sourceId": source_id, "mode": "manual-competitor"}
                )
                async with transaction() as session:
                    competitor["reservation"] = await repository.reserve_refresh(
                        session,
                        source_id=source_id,
                        idempotency_key="z" * 64,
                        request_hash=competitor_hash,
                        input_manifest_hash=canonical_hash({}),
                        now_ms=now["value"],
                        enforce_cooldown=False,
                    )
            return snapshot

    adapter = ExpiringAdapter()
    service = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        adapters={"qidian_public_rank": adapter},
        id_factory=id_factory,
        clock=lambda: now["value"],
    )

    with pytest.raises(MarketSourceFailure) as expired:
        await service.refresh(source_id, idempotency_key="h" * 64)

    assert expired.value.code == "MARKET_REFRESH_LEASE_EXPIRED"
    assert adapter.calls == 1
    counts = await disposable_mysql.session.fetchone(
        """SELECT
             (SELECT COUNT(*) FROM market_snapshots) AS snapshots,
             (SELECT COUNT(*) FROM market_snapshot_entries) AS entries,
             (SELECT COUNT(*) FROM market_snapshot_manifests) AS manifests"""
    )
    expected_count = int(preexisting_snapshot)
    assert counts == {
        "snapshots": expected_count,
        "entries": expected_count,
        "manifests": expected_count,
    }
    holder = await disposable_mysql.session.fetchone(
        """SELECT status,snapshot_id,result_hash,public_error_code,completed_at
           FROM market_refresh_requests
           WHERE source_id=%s AND idempotency_key=%s""",
        (source_id, "h" * 64),
    )
    assert holder == {
        "status": "outcome_unknown",
        "snapshot_id": None,
        "result_hash": None,
        "public_error_code": "MARKET_REFRESH_LEASE_EXPIRED",
        "completed_at": NOW + 30_001,
    }
    state = await disposable_mysql.session.fetchone(
        """SELECT last_snapshot_id,refresh_status,lease_owner,lease_expires_at,
                  last_attempted_at,last_succeeded_at,public_error_code
           FROM market_source_refresh_states WHERE source_id=%s""",
        (source_id,),
    )
    if competitor_recovers:
        takeover = competitor["reservation"]
        assert takeover is not None and takeover["kind"] == "reserved"
        assert state == {
            "last_snapshot_id": None,
            "refresh_status": "leased",
            "lease_owner": takeover["request_id"],
            "lease_expires_at": NOW + 60_001,
            "last_attempted_at": NOW,
            "last_succeeded_at": None,
            "public_error_code": "MARKET_REFRESH_LEASE_EXPIRED",
        }
        competitor_request = await disposable_mysql.session.fetchone(
            """SELECT status,snapshot_id,public_error_code
               FROM market_refresh_requests WHERE id=%s""",
            (takeover["request_id"],),
        )
        assert competitor_request == {
            "status": "running",
            "snapshot_id": None,
            "public_error_code": None,
        }
    else:
        assert state == {
            "last_snapshot_id": None,
            "refresh_status": "idle",
            "lease_owner": None,
            "lease_expires_at": None,
            "last_attempted_at": NOW,
            "last_succeeded_at": None,
            "public_error_code": "MARKET_REFRESH_LEASE_EXPIRED",
        }


@pytest.mark.parametrize("drift", ("archived", "policy-head"))
async def test_publication_rejects_locked_source_or_policy_drift(
    disposable_mysql,
    drift,
):
    from backend.domain.market import MarketEntry, MarketSnapshot
    from backend.domain.market_sources import (
        MarketSourceFailure,
        load_market_source_package,
    )
    from backend.repositories.market import MarketRepository
    from backend.services.market_sources import MarketSourceSeedService
    from backend.services.market_snapshots import MarketSnapshotService

    ids = iter(f"80000000-0000-0000-0000-{index:012d}" for index in range(1, 100))
    id_factory = lambda: next(ids)
    repository = MarketRepository()
    transaction = transaction_factory_for(disposable_mysql.connection_config)
    await MarketSourceSeedService(
        repository,
        transaction_factory=transaction,
        id_factory=id_factory,
        clock=lambda: NOW,
    ).seed(load_market_source_package(MANIFEST))
    source = await disposable_mysql.session.fetchone(
        "SELECT id FROM market_sources WHERE stable_key='qidian.newsign'"
    )
    source_id = source["id"]
    original_head = await disposable_mysql.session.fetchone(
        """SELECT revision_id,revision,content_hash
           FROM market_source_policy_heads WHERE source_id=%s""",
        (source_id,),
    )

    class DriftingAdapter:
        adapter_version = "drifting-public-adapter-v1"

        async def fetch(self, **kwargs):
            if drift == "archived":
                await disposable_mysql.session.execute(
                    """UPDATE market_sources
                       SET status='archived',updated_at=%s WHERE id=%s""",
                    (NOW + 1, source_id),
                )
            else:
                revision_id = "80000000-0000-0000-0000-000000000901"
                policy_hash = "f" * 64
                await disposable_mysql.session.execute(
                    """INSERT INTO market_source_policy_revisions
                       (id,source_id,revision,policy_status,policy_version,
                        checked_at,evidence_url,evidence_hash,
                        allowed_origins_json,path_prefixes_json,enabled,
                        interval_minutes,next_run_at,content_hash,created_at)
                       SELECT %s,source_id,revision+1,policy_status,
                              policy_version,checked_at,evidence_url,
                              evidence_hash,allowed_origins_json,
                              path_prefixes_json,enabled,interval_minutes,
                              next_run_at,%s,%s
                       FROM market_source_policy_revisions
                       WHERE source_id=%s AND id=%s""",
                    (
                        revision_id,
                        policy_hash,
                        NOW + 1,
                        source_id,
                        original_head["revision_id"],
                    ),
                )
                await disposable_mysql.session.execute(
                    """UPDATE market_source_policy_heads
                       SET revision_id=%s,revision=%s,content_hash=%s,
                           updated_at=%s
                       WHERE source_id=%s""",
                    (
                        revision_id,
                        original_head["revision"] + 1,
                        policy_hash,
                        NOW + 1,
                        source_id,
                    ),
                )
            return MarketSnapshot(
                platform="qidian",
                rankingName="newsign",
                category="male",
                capturedAt=NOW,
                sourceURL="https://www.qidian.com/rank/newsign/",
                entries=(
                    MarketEntry(
                        rank=1,
                        title="漂移边界合成书",
                        author="合成作者",
                        category="奇幻",
                        workURL="https://www.qidian.com/book/900000299/",
                        publicMetrics={},
                    ),
                ),
            )

    service = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        adapters={"qidian_public_rank": DriftingAdapter()},
        id_factory=id_factory,
        clock=lambda: NOW,
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        await service.refresh(source_id, idempotency_key="d" * 64)

    assert rejected.value.code == "MARKET_SOURCE_CONFLICT"
    counts = await disposable_mysql.session.fetchone(
        """SELECT
             (SELECT COUNT(*) FROM market_snapshots) AS snapshots,
             (SELECT COUNT(*) FROM market_snapshot_entries) AS entries,
             (SELECT COUNT(*) FROM market_snapshot_manifests) AS manifests"""
    )
    assert counts == {"snapshots": 0, "entries": 0, "manifests": 0}
    request = await disposable_mysql.session.fetchone(
        """SELECT status,snapshot_id,result_hash,public_error_code
           FROM market_refresh_requests
           WHERE source_id=%s AND idempotency_key=%s""",
        (source_id, "d" * 64),
    )
    assert request == {
        "status": "failed",
        "snapshot_id": None,
        "result_hash": None,
        "public_error_code": "MARKET_SOURCE_CONFLICT",
    }
    state = await disposable_mysql.session.fetchone(
        """SELECT last_snapshot_id,refresh_status,lease_owner,lease_expires_at,
                  last_attempted_at,last_succeeded_at,public_error_code
           FROM market_source_refresh_states WHERE source_id=%s""",
        (source_id,),
    )
    assert state == {
        "last_snapshot_id": None,
        "refresh_status": "idle",
        "lease_owner": None,
        "lease_expires_at": None,
        "last_attempted_at": NOW,
        "last_succeeded_at": None,
        "public_error_code": "MARKET_SOURCE_CONFLICT",
    }
    current_source = await disposable_mysql.session.fetchone(
        "SELECT status FROM market_sources WHERE id=%s",
        (source_id,),
    )
    current_head = await disposable_mysql.session.fetchone(
        """SELECT revision_id,revision,content_hash
           FROM market_source_policy_heads WHERE source_id=%s""",
        (source_id,),
    )
    if drift == "archived":
        assert current_source["status"] == "archived"
        assert current_head == original_head
    else:
        assert current_source["status"] == "active"
        assert current_head != original_head


@pytest.mark.parametrize("phase", ("fetch", "publish"))
async def test_cancelled_refresh_persists_owner_safe_outcome_unknown(
    disposable_mysql,
    phase,
):
    from backend.domain.market import MarketEntry, MarketSnapshot
    from backend.domain.market_sources import load_market_source_package
    from backend.repositories.market import MarketRepository
    from backend.services.market_sources import MarketSourceSeedService
    from backend.services.market_snapshots import MarketSnapshotService

    started = asyncio.Event()
    blocked = asyncio.Event()

    class CancellingPublishRepository(MarketRepository):
        async def publish_snapshot(self, session, **values):
            if phase == "publish":
                started.set()
                await blocked.wait()
            return await super().publish_snapshot(session, **values)

    ids = iter(f"90000000-0000-0000-0000-{index:012d}" for index in range(1, 100))
    id_factory = lambda: next(ids)
    repository = CancellingPublishRepository()
    transaction = transaction_factory_for(disposable_mysql.connection_config)
    await MarketSourceSeedService(
        repository,
        transaction_factory=transaction,
        id_factory=id_factory,
        clock=lambda: NOW,
    ).seed(load_market_source_package(MANIFEST))
    source = await disposable_mysql.session.fetchone(
        "SELECT id FROM market_sources WHERE stable_key='qidian.newsign'"
    )
    source_id = source["id"]

    class CancellingFetchAdapter:
        adapter_version = "cancelling-public-adapter-v1"

        async def fetch(self, **kwargs):
            if phase == "fetch":
                started.set()
                await blocked.wait()
            return MarketSnapshot(
                platform="qidian",
                rankingName="newsign",
                category="male",
                capturedAt=NOW,
                sourceURL="https://www.qidian.com/rank/newsign/",
                entries=(
                    MarketEntry(
                        rank=1,
                        title="取消边界合成书",
                        author="合成作者",
                        category="奇幻",
                        workURL="https://www.qidian.com/book/900000399/",
                        publicMetrics={},
                    ),
                ),
            )

    service = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        adapters={"qidian_public_rank": CancellingFetchAdapter()},
        id_factory=id_factory,
        clock=lambda: NOW,
    )

    refresh = asyncio.create_task(
        service.refresh(source_id, idempotency_key="k" * 64)
    )
    await asyncio.wait_for(started.wait(), timeout=5)
    refresh.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(refresh, timeout=5)

    request = await disposable_mysql.session.fetchone(
        """SELECT status,snapshot_id,result_hash,public_error_code,completed_at
           FROM market_refresh_requests
           WHERE source_id=%s AND idempotency_key=%s""",
        (source_id, "k" * 64),
    )
    assert request == {
        "status": "outcome_unknown",
        "snapshot_id": None,
        "result_hash": None,
        "public_error_code": "MARKET_REFRESH_CANCELLED",
        "completed_at": NOW,
    }
    state = await disposable_mysql.session.fetchone(
        """SELECT last_snapshot_id,refresh_status,lease_owner,lease_expires_at,
                  last_attempted_at,last_succeeded_at,public_error_code
           FROM market_source_refresh_states WHERE source_id=%s""",
        (source_id,),
    )
    assert state == {
        "last_snapshot_id": None,
        "refresh_status": "idle",
        "lease_owner": None,
        "lease_expires_at": None,
        "last_attempted_at": NOW,
        "last_succeeded_at": None,
        "public_error_code": "MARKET_REFRESH_CANCELLED",
    }
    assert await disposable_mysql.session.fetchone(
        "SELECT id FROM market_snapshots LIMIT 1"
    ) is None
