from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from backend.tests.support.disposable_mysql import transaction_factory_for


pytestmark = [pytest.mark.mysql, pytest.mark.asyncio]
NOW = 1_721_000_000_000
MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "market-sources-v1.0.0"
    / "manifest.json"
)


def _connection(disposable_mysql):
    @asynccontextmanager
    async def factory():
        yield disposable_mysql.session

    return factory


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
