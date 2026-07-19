"""Public evidence-backed market source routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, ConfigDict, Field

from backend.database import connection, transaction
from backend.domain.market_sources import MarketSourceFailure
from backend.gateways.market_sources.base import HttpxMarketTransport
from backend.gateways.market_sources.manual_snapshot import ManualSnapshotAdapter
from backend.gateways.market_sources.qidian_public_rank import (
    QidianPublicRankAdapter,
)
from backend.gateways.market_sources.qq_reading_public_rank import (
    QQReadingPublicRankAdapter,
)
from backend.repositories.market import MarketRepository
from backend.services.market_snapshots import MarketSnapshotService
from backend.services.market_sources import MarketSourceService


router = APIRouter(tags=["market-sources"])
BoundedId = Annotated[str, Path(min_length=1, max_length=36)]


class _Request(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        populate_by_name=True,
        hide_input_in_errors=True,
    )


class RefreshRequest(_Request):
    idempotencyKey: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]{64}$",
    )

    @property
    def idempotency_key(self) -> str:
        return self.idempotencyKey


class ManualImportRequest(RefreshRequest):
    model_config = ConfigDict(
        strict=True,
        extra="allow",
        populate_by_name=True,
        hide_input_in_errors=True,
    )
    snapshot: object


def _source_view(row: dict) -> dict:
    return {
        "id": row["id"],
        "stableKey": row["stable_key"],
        "displayName": row["display_name"],
        "adapterKey": row["adapter_key"],
        "platform": row["platform"],
        "rankingName": row["ranking_name"],
        "category": row["category"],
        "policyStatus": row["policy_status"],
        "policyVersion": row["policy_version"],
        "checkedAt": row["checked_at"],
        "evidenceURL": row["evidence_url"],
        "automaticRefreshAllowed": row["automatic_refresh_allowed"],
        "refreshStatus": row["refresh_status"],
        "lastAttemptedAt": row["last_attempted_at"],
        "lastSucceededAt": row["last_succeeded_at"],
        "lastSnapshotId": row["last_snapshot_id"],
        "publicErrorCode": row["public_error_code"],
    }


def _entry_view(row: dict) -> dict:
    return {
        "rank": row["rank"],
        "title": row["title"],
        "author": row["author"],
        "category": row["category"],
        "workURL": row["work_url"],
        "publicMetrics": row["public_metrics"],
    }


def _snapshot_view(row: dict, *, detail: bool) -> dict:
    value = {
        "id": row["id"],
        "sourceId": row["source_id"],
        "capturedAt": row["captured_at"],
        "platform": row["platform"],
        "rankingName": row["ranking_name"],
        "category": row["category"],
        "sourceURL": row["source_url"],
        "contentHash": row["content_hash"],
        "entryCount": row["entry_count"],
    }
    if detail:
        value["entries"] = [_entry_view(entry) for entry in row.get("entries", ())]
    return value


def get_market_source_service() -> MarketSourceService:
    repository = MarketRepository()
    transport = HttpxMarketTransport()
    snapshot_service = MarketSnapshotService(
        repository,
        transaction_factory=transaction,
        connection_factory=connection,
        adapters={
            "qidian_public_rank": QidianPublicRankAdapter(transport),
            "qq_reading_public_rank": QQReadingPublicRankAdapter(transport),
        },
        manual_adapter=ManualSnapshotAdapter(),
    )
    return MarketSourceService(
        repository,
        snapshot_service,
        connection_factory=connection,
    )


@router.get("/market-sources")
async def list_market_sources(
    service: MarketSourceService = Depends(get_market_source_service),
):
    return [_source_view(row) for row in await service.list_sources()]


@router.get("/market-sources/{source_id}")
async def get_market_source(
    source_id: BoundedId,
    service: MarketSourceService = Depends(get_market_source_service),
):
    return _source_view(await service.get_source(source_id))


@router.get("/market-sources/{source_id}/snapshots")
async def list_market_snapshots(
    source_id: BoundedId,
    service: MarketSourceService = Depends(get_market_source_service),
):
    return [
        _snapshot_view(row, detail=False)
        for row in await service.list_snapshots(source_id)
    ]


@router.get("/market-sources/{source_id}/snapshots/{snapshot_id}")
async def get_market_snapshot(
    source_id: BoundedId,
    snapshot_id: BoundedId,
    service: MarketSourceService = Depends(get_market_source_service),
):
    return _snapshot_view(
        await service.get_snapshot(source_id, snapshot_id),
        detail=True,
    )


@router.post("/market-sources/{source_id}/manual-import")
async def import_manual_market_snapshot(
    source_id: BoundedId,
    data: ManualImportRequest,
    service: MarketSourceService = Depends(get_market_source_service),
):
    if data.__pydantic_extra__:
        raise MarketSourceFailure("MARKET_MANUAL_SNAPSHOT_INVALID")
    snapshot = ManualSnapshotAdapter().parse(data.snapshot)
    result = await service.import_manual(
        source_id,
        snapshot.model_dump(mode="json", by_alias=True),
        data.idempotency_key,
    )
    return _snapshot_view(result, detail=True)


@router.post("/market-sources/{source_id}/refresh")
async def refresh_market_source(
    source_id: BoundedId,
    data: RefreshRequest,
    service: MarketSourceService = Depends(get_market_source_service),
):
    result = await service.refresh(source_id, data.idempotency_key)
    return _snapshot_view(result, detail=True)
