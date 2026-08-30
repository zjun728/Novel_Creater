from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path

import pytest


MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "market-sources-v1.0.0"
    / "manifest.json"
)


class FakeMarketSeedRepository:
    def __init__(self):
        self.sources = {}
        self.policies = {}
        self.heads = {}
        self.states = {}
        self.schema_locks = 0

    async def lock_schema_guard(self, session):
        self.schema_locks += 1

    async def list_seed_inventory(self, session):
        return tuple(
            {
                **source,
                "policy": self.policies.get(source_id),
                "head": self.heads.get(source_id),
            }
            for source_id, source in self.sources.items()
        )

    async def insert_source(self, session, row):
        self.sources[row["id"]] = deepcopy(row)

    async def insert_policy_revision(self, session, row):
        self.policies[row["source_id"]] = deepcopy(row)

    async def insert_policy_head(self, session, row):
        self.heads[row["source_id"]] = deepcopy(row)

    async def insert_refresh_state(self, session, row):
        self.states[row["source_id"]] = deepcopy(row)


def _transaction(repo):
    @asynccontextmanager
    async def factory():
        snapshot = deepcopy(repo.__dict__)
        try:
            yield object()
        except BaseException:
            repo.__dict__.clear()
            repo.__dict__.update(snapshot)
            raise

    return factory


@pytest.mark.asyncio
async def test_explicit_seed_is_idempotent_and_never_enables_automatic_refresh():
    from backend.domain.market_sources import load_market_source_package
    from backend.services.market_sources import MarketSourceSeedService

    package = load_market_source_package(MANIFEST)
    repository = FakeMarketSeedRepository()
    ids = iter(f"00000000-0000-0000-0000-{index:012d}" for index in range(1, 20))
    service = MarketSourceSeedService(
        repository,
        transaction_factory=_transaction(repository),
        id_factory=lambda: next(ids),
        clock=lambda: 1_721_000_000_000,
    )

    first = await service.seed(package)
    replay = await service.seed(package)

    assert (first.inserted, first.replayed) == (5, 0)
    assert (replay.inserted, replay.replayed) == (0, 5)
    assert repository.schema_locks == 2
    assert len(repository.sources) == len(repository.states) == 5
    assert all(policy["policy_status"] == "manual_only" for policy in repository.policies.values())
    assert all(policy["enabled"] == 0 for policy in repository.policies.values())


@pytest.mark.asyncio
async def test_seed_rejects_existing_stable_key_drift_without_mutation():
    from backend.domain.market_sources import load_market_source_package
    from backend.services.market_sources import (
        MarketSourceSeedConflict,
        MarketSourceSeedService,
    )

    package = load_market_source_package(MANIFEST)
    repository = FakeMarketSeedRepository()
    ids = iter(f"10000000-0000-0000-0000-{index:012d}" for index in range(1, 20))
    service = MarketSourceSeedService(
        repository,
        transaction_factory=_transaction(repository),
        id_factory=lambda: next(ids),
        clock=lambda: 1_721_000_000_000,
    )
    await service.seed(package)
    next(iter(repository.sources.values()))["adapter_key"] = "tampered"
    before = deepcopy(repository.__dict__)

    with pytest.raises(MarketSourceSeedConflict):
        await service.seed(package)

    assert repository.__dict__ == before


@pytest.mark.asyncio
async def test_validate_only_cli_never_imports_or_opens_database(monkeypatch):
    from backend.scripts import seed_market_sources

    output = []
    monkeypatch.setattr(
        "backend.database.transaction",
        lambda: pytest.fail("database must not open"),
    )

    result = await seed_market_sources.run_cli(
        ["--validate-only"],
        output=output.append,
    )

    assert result == 0
    assert "package_version=market-sources-v1.0.0" in output[0]
    assert "source_count=5" in output[0]
