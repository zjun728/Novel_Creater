"""Explicit source seeding and public inventory reads."""

from __future__ import annotations

from dataclasses import dataclass
import time
from uuid import NAMESPACE_URL, uuid4, uuid5

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.market import MAX_MARKET_SOURCES
from backend.domain.market_sources import (
    MarketSourceNotFound,
    MarketSourcePackage,
)


class MarketSourceSeedConflict(RuntimeError):
    """Existing built-in rows differ from the fixed package."""


@dataclass(frozen=True)
class MarketSourceSeedReport:
    package_version: str
    source_count: int
    package_hash: str
    inserted: int
    replayed: int


def _policy_row(source_id: str, revision_id: str, source, now_ms: int) -> dict:
    policy = source.policy
    return {
        "id": revision_id,
        "source_id": source_id,
        "revision": 1,
        "policy_status": policy.status,
        "policy_version": policy.policy_version,
        "checked_at": policy.checked_at,
        "evidence_url": policy.evidence_url,
        "evidence_hash": policy.evidence_hash,
        "allowed_origins_json": canonical_json(list(policy.allowed_origins)),
        "path_prefixes_json": canonical_json(list(policy.path_prefixes)),
        "enabled": int(policy.enabled),
        "interval_minutes": policy.request_interval_seconds // 60,
        "next_run_at": None,
        "content_hash": source.policy_hash,
        "created_at": now_ms,
    }


def _same_existing(existing: dict, source, expected_policy: dict) -> bool:
    source_fields = (
        existing.get("stable_key") == source.stable_key,
        existing.get("adapter_key") == source.adapter_key,
        existing.get("display_name") == source.display_name,
        existing.get("public_config_json")
        == canonical_json(dict(source.public_config)),
        existing.get("status") == "active",
    )
    policy = existing.get("policy")
    head = existing.get("head")
    if policy is None or head is None:
        return False
    policy_fields = (
        policy.get("source_id") == existing.get("id"),
        policy.get("revision") == 1,
        policy.get("policy_status") == expected_policy["policy_status"],
        policy.get("policy_version") == expected_policy["policy_version"],
        policy.get("checked_at") == expected_policy["checked_at"],
        policy.get("evidence_url") == expected_policy["evidence_url"],
        policy.get("evidence_hash") == expected_policy["evidence_hash"],
        policy.get("allowed_origins_json")
        == expected_policy["allowed_origins_json"],
        policy.get("path_prefixes_json") == expected_policy["path_prefixes_json"],
        int(policy.get("enabled")) == expected_policy["enabled"],
        policy.get("interval_minutes") == expected_policy["interval_minutes"],
        policy.get("next_run_at") is None,
        policy.get("content_hash") == expected_policy["content_hash"],
        head.get("revision_id") == policy.get("id"),
        head.get("revision") == 1,
        head.get("content_hash") == expected_policy["content_hash"],
    )
    return all((*source_fields, *policy_fields))


class MarketSourceSeedService:
    def __init__(
        self,
        repository,
        *,
        transaction_factory,
        id_factory=None,
        clock=None,
    ) -> None:
        self.repository = repository
        self._transaction = transaction_factory
        self._id = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: int(time.time() * 1000))

    async def seed(self, package: MarketSourcePackage) -> MarketSourceSeedReport:
        now_ms = self._clock()
        inserted = 0
        replayed = 0
        async with self._transaction() as session:
            await self.repository.lock_schema_guard(session)
            inventory = await self.repository.list_seed_inventory(session)
            by_key = {row["stable_key"]: row for row in inventory}
            if set(by_key) - {source.stable_key for source in package.sources}:
                raise MarketSourceSeedConflict()

            plans = []
            for source in package.sources:
                existing = by_key.get(source.stable_key)
                if existing is None:
                    plans.append(source)
                    continue
                expected_policy = _policy_row(
                    existing["id"],
                    existing.get("policy", {}).get("id", ""),
                    source,
                    now_ms,
                )
                if not _same_existing(existing, source, expected_policy):
                    raise MarketSourceSeedConflict()
                replayed += 1

            for source in plans:
                source_id = self._id()
                revision_id = self._id()
                source_row = {
                    "id": source_id,
                    "stable_key": source.stable_key,
                    "adapter_key": source.adapter_key,
                    "display_name": source.display_name,
                    "public_config_json": canonical_json(
                        dict(source.public_config)
                    ),
                    "status": "active",
                    "created_at": now_ms,
                    "updated_at": now_ms,
                }
                policy_row = _policy_row(
                    source_id,
                    revision_id,
                    source,
                    now_ms,
                )
                await self.repository.insert_source(session, source_row)
                await self.repository.insert_policy_revision(session, policy_row)
                await self.repository.insert_policy_head(
                    session,
                    {
                        "source_id": source_id,
                        "revision_id": revision_id,
                        "revision": 1,
                        "content_hash": source.policy_hash,
                        "updated_at": now_ms,
                    },
                )
                await self.repository.insert_refresh_state(
                    session,
                    {"source_id": source_id, "updated_at": now_ms},
                )
                inserted += 1
        return MarketSourceSeedReport(
            package_version=package.package_version,
            source_count=len(package.sources),
            package_hash=canonical_hash(package.manifest),
            inserted=inserted,
            replayed=replayed,
        )


class MarketSourceService:
    """Read inventory and delegate explicit snapshot commands."""

    def __init__(
        self,
        repository,
        snapshot_service,
        *,
        connection_factory,
        transaction_factory=None,
        clock=None,
    ) -> None:
        self.repository = repository
        self.snapshot_service = snapshot_service
        self._connection = connection_factory
        self._transaction = transaction_factory
        self._clock = clock or (lambda: int(time.time() * 1000))

    def _public_source(self, row: dict) -> dict:
        config = row["public_config"]
        policy = row.get("policy")
        policy_hash_valid = bool(
            policy is not None
            and row.get("policy_hash") == canonical_hash(policy)
        )
        now_ms = self._clock()
        policy_fresh = bool(
            policy is not None
            and -5 * 60 * 1000
            <= now_ms - policy.checked_at
            <= 30 * 24 * 60 * 60 * 1000
        )
        automatic_allowed = bool(
            policy is not None
            and policy.status == "verified_public"
            and policy_hash_valid
            and policy_fresh
        )
        return {
            "id": row["id"],
            "stable_key": row["stable_key"],
            "display_name": row["display_name"],
            "adapter_key": row["adapter_key"],
            "platform": config["platform"],
            "ranking_name": config["rankingName"],
            "category": config["category"],
            "policy_status": None if policy is None else policy.status,
            "policy_version": None if policy is None else policy.policy_version,
            "checked_at": None if policy is None else policy.checked_at,
            "evidence_url": None if policy is None else policy.evidence_url,
            "automatic_refresh_allowed": automatic_allowed,
            "refresh_status": row.get("refresh_status") or "idle",
            "last_attempted_at": row.get("last_attempted_at"),
            "last_succeeded_at": row.get("last_succeeded_at"),
            "last_snapshot_id": row.get("last_snapshot_id"),
            "public_error_code": row.get("public_error_code"),
            "schedule_revision": (
                None if policy is None else int(row["policy_revision"])
            ),
            "schedule_enabled": (
                None if policy is None else policy.enabled
            ),
            "schedule_interval_minutes": (
                None
                if policy is None
                else policy.request_interval_seconds // 60
            ),
            "schedule_next_run_at": row.get("schedule_next_run_at"),
        }

    async def list_sources(self):
        async with self._connection() as session:
            rows = await self.repository.list_sources(session)
        return tuple(
            self._public_source(row) for row in rows[:MAX_MARKET_SOURCES]
        )

    async def get_source(self, source_id: str):
        async with self._connection() as session:
            row = await self.repository.get_source(session, source_id)
        if row is None:
            raise MarketSourceNotFound()
        return self._public_source(row)

    async def list_snapshots(self, source_id: str):
        await self.get_source(source_id)
        return await self.snapshot_service.list_snapshots(source_id)

    async def get_snapshot(self, source_id: str, snapshot_id: str):
        return await self.snapshot_service.get_snapshot(source_id, snapshot_id)

    async def import_manual(self, source_id: str, snapshot, idempotency_key: str):
        return await self.snapshot_service.import_manual(
            source_id,
            snapshot,
            idempotency_key=idempotency_key,
        )

    async def refresh(self, source_id: str, idempotency_key: str):
        return await self.snapshot_service.refresh(
            source_id,
            idempotency_key=idempotency_key,
        )

    async def update_schedule(
        self,
        source_id: str,
        *,
        expected_revision: int,
        enabled: bool,
        interval_minutes: int,
        idempotency_key: str,
    ):
        if self._transaction is None:
            raise RuntimeError("market schedule updates require a transaction")
        revision_id = str(
            uuid5(
                NAMESPACE_URL,
                f"market-schedule:{source_id}:{idempotency_key}",
            )
        )
        async with self._transaction() as session:
            return await self.repository.update_schedule(
                session,
                source_id=source_id,
                revision_id=revision_id,
                expected_revision=expected_revision,
                enabled=enabled,
                interval_minutes=interval_minutes,
                now_ms=self._clock(),
            )
