from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path

import pytest

from backend.domain.json_contracts import canonical_json


ASSETS = (
    Path(__file__).resolve().parents[2]
    / "assets"
)
V1_MANIFEST = ASSETS / "market-sources-v1.0.0" / "manifest.json"
MANIFEST = ASSETS / "market-sources-v1.1.0" / "manifest.json"


class FakeMarketSeedRepository:
    def __init__(self):
        self.sources = {}
        self.policies = {}
        self.policy_history = []
        self.heads = {}
        self.states = {}
        self.snapshot_count = 0
        self.refresh_history = []
        self.schema_locks = 0
        self.reject_updates = False
        self.fail_stage = None
        self.source_update_calls = []

    def id_for(self, stable_key):
        return next(
            source_id
            for source_id, source in self.sources.items()
            if source["stable_key"] == stable_key
        )

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
        self.policy_history.append(deepcopy(row))
        if self.fail_stage == "after_policy_insert":
            raise RuntimeError("injected after policy insert")

    async def insert_policy_head(self, session, row):
        self.heads[row["source_id"]] = deepcopy(row)

    async def insert_refresh_state(self, session, row):
        self.states[row["source_id"]] = deepcopy(row)

    async def update_source_definition(
        self, session, *, source_id, expected_updated_at, source, now_ms
    ):
        row = self.sources[source_id]
        if (
            self.reject_updates
            or row["updated_at"] != expected_updated_at
            or row["status"] != "active"
        ):
            from backend.services.market_sources import MarketSourceSeedConflict
            raise MarketSourceSeedConflict()
        row.update(
            adapter_key=source.adapter_key,
            display_name=source.display_name,
            public_config_json=canonical_json(dict(source.public_config)),
            updated_at=now_ms,
        )
        self.source_update_calls.append(source.stable_key)
        if self.fail_stage == "after_source_update":
            raise RuntimeError("injected after source update")

    async def replace_policy_head(
        self, session, *, source_id, expected_revision, row
    ):
        head = self.heads[source_id]
        if head["revision"] != expected_revision:
            from backend.services.market_sources import MarketSourceSeedConflict
            raise MarketSourceSeedConflict()
        self.heads[source_id] = deepcopy(row)
        if self.fail_stage == "at_head_cas":
            raise RuntimeError("injected at head compare-and-swap")


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
async def test_seed_synchronizes_v1_to_v1_1_without_touching_snapshots():
    from backend.domain.market_sources import load_market_source_package
    from backend.services.market_sources import MarketSourceSeedService

    v1 = load_market_source_package(V1_MANIFEST)
    package = load_market_source_package(MANIFEST)
    repository = FakeMarketSeedRepository()
    ids = iter(f"00000000-0000-0000-0000-{index:012d}" for index in range(1, 40))
    service = MarketSourceSeedService(
        repository,
        transaction_factory=_transaction(repository),
        id_factory=lambda: next(ids),
        clock=lambda: 1_721_000_000_000,
    )

    first = await service.seed(v1)
    replay = await service.seed(package)
    writes_after_upgrade = (
        tuple(repository.source_update_calls),
        len(repository.policy_history),
    )
    reordered = package.model_copy(update={"sources": tuple(reversed(package.sources))})
    reordered_replay = await service.seed(reordered)

    assert (first.inserted, first.replayed) == (5, 0)
    assert (replay.inserted, replay.updated, replay.replayed) == (5, 3, 2)
    assert (
        reordered_replay.inserted,
        reordered_replay.updated,
        reordered_replay.replayed,
    ) == (0, 0, 10)
    assert repository.schema_locks == 3
    assert len(repository.sources) == len(repository.states) == 10
    qq_id = next(key for key, value in repository.sources.items() if value["stable_key"] == "qq-reading.male-popular")
    assert repository.heads[qq_id]["revision"] == 2
    assert repository.source_update_calls == [
        "fanqie.reading",
        "qimao.public-catalog",
    ]
    assert repository.heads[repository.id_for("qidian.newsign")]["revision"] == 1
    assert repository.heads[repository.id_for("shuqi.public-catalog")]["revision"] == 1
    assert repository.heads[repository.id_for("fanqie.reading")]["revision"] == 2
    assert repository.heads[repository.id_for("qimao.public-catalog")]["revision"] == 2
    fanqie_policies = [
        policy
        for policy in repository.policy_history
        if policy["source_id"] == repository.id_for("fanqie.reading")
    ]
    assert len(fanqie_policies) == 2
    assert fanqie_policies[0]["content_hash"] == fanqie_policies[1]["content_hash"]
    qq_policies = [
        policy
        for policy in repository.policy_history
        if policy["source_id"] == repository.id_for("qq-reading.male-popular")
    ]
    qimao_policies = [
        policy
        for policy in repository.policy_history
        if policy["source_id"] == repository.id_for("qimao.public-catalog")
    ]
    assert qq_policies[0]["content_hash"] != qq_policies[1]["content_hash"]
    assert qimao_policies[0]["content_hash"] != qimao_policies[1]["content_hash"]
    assert writes_after_upgrade == (
        tuple(repository.source_update_calls),
        len(repository.policy_history),
    )
    assert len(repository.policy_history) == 13
    assert repository.snapshot_count == 0
    assert all(policy["enabled"] == 0 for policy in repository.policies.values())


@pytest.mark.asyncio
async def test_seed_rolls_back_all_changes_on_compare_and_swap_conflict():
    from backend.domain.market_sources import load_market_source_package
    from backend.services.market_sources import (
        MarketSourceSeedConflict,
        MarketSourceSeedService,
    )

    package = load_market_source_package(MANIFEST)
    repository = FakeMarketSeedRepository()
    ids = iter(f"10000000-0000-0000-0000-{index:012d}" for index in range(1, 40))
    service = MarketSourceSeedService(
        repository,
        transaction_factory=_transaction(repository),
        id_factory=lambda: next(ids),
        clock=lambda: 1_721_000_000_000,
    )
    await service.seed(load_market_source_package(V1_MANIFEST))
    repository.reject_updates = True
    before = deepcopy(repository.__dict__)

    with pytest.raises(MarketSourceSeedConflict):
        await service.seed(package)

    assert repository.__dict__ == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fail_stage",
    ("after_source_update", "after_policy_insert", "at_head_cas"),
)
async def test_seed_rolls_back_every_write_stage_and_preserves_history(fail_stage):
    from backend.domain.market_sources import load_market_source_package
    from backend.services.market_sources import MarketSourceSeedService

    repository = FakeMarketSeedRepository()
    ids = iter(
        f"20000000-0000-0000-0000-{index:012d}" for index in range(1, 40)
    )
    service = MarketSourceSeedService(
        repository,
        transaction_factory=_transaction(repository),
        id_factory=lambda: next(ids),
        clock=lambda: 1_721_000_000_000,
    )
    await service.seed(load_market_source_package(V1_MANIFEST))
    repository.snapshot_count = 3
    repository.refresh_history = ["existing-refresh"]
    repository.fail_stage = fail_stage
    before = deepcopy(repository.__dict__)

    with pytest.raises(RuntimeError, match="^injected"):
        await service.seed(load_market_source_package(MANIFEST))

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
    assert "package_version=market-sources-v1.1.0" in output[0]
    assert "source_count=10" in output[0]
