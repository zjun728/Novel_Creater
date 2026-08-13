"""Public evidence-backed market source routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from backend.database import connection, transaction
from backend.domain.market_analysis import MarketAnalysisFailure
from backend.domain.market_sources import MarketSourceFailure
from backend.gateways.market_analysis_provider import (
    MarketAnalysisProviderGateway,
)
from backend.gateways.market_sources.base import HttpxMarketTransport
from backend.gateways.market_sources.manual_snapshot import (
    MAX_MANUAL_SNAPSHOT_BYTES,
    ManualSnapshotAdapter,
)
from backend.gateways.market_sources.qidian_public_rank import (
    QidianPublicRankAdapter,
)
from backend.gateways.market_sources.qq_reading_public_rank import (
    QQReadingPublicRankAdapter,
)
from backend.repositories.market import MarketRepository
from backend.services.market_snapshots import MarketSnapshotService
from backend.services.market_analysis import AnalyzeMarket, MarketAnalysisService
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
    model_config = ConfigDict(
        strict=True,
        extra="allow",
        populate_by_name=True,
        hide_input_in_errors=True,
    )
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
    snapshot: dict[str, object]


class ScheduleRequest(_Request):
    expectedRevision: int = Field(ge=1)
    enabled: bool
    intervalMinutes: int = Field(ge=1, le=525_600)
    idempotencyKey: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]{64}$",
    )


class AnalysisRequest(_Request):
    model_config = ConfigDict(
        strict=True,
        extra="allow",
        populate_by_name=True,
        hide_input_in_errors=True,
    )
    snapshotIds: tuple[str, ...] = Field(min_length=1, max_length=4)
    idempotencyKey: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]{64}$",
    )

    @field_validator("snapshotIds", mode="before")
    @classmethod
    def freeze_snapshot_ids(cls, value):
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def unique_snapshot_ids(self):
        if len(self.snapshotIds) != len(set(self.snapshotIds)):
            raise ValueError("snapshot IDs must be unique")
        if any(not item or len(item) > 36 for item in self.snapshotIds):
            raise ValueError("snapshot ID is invalid")
        return self


async def _read_manual_body(request: Request) -> bytes:
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            length = int(declared_length)
        except ValueError:
            raise MarketSourceFailure("MARKET_MANUAL_SNAPSHOT_INVALID") from None
        if length < 0:
            raise MarketSourceFailure("MARKET_MANUAL_SNAPSHOT_INVALID")
        if length > MAX_MANUAL_SNAPSHOT_BYTES:
            raise MarketSourceFailure("MARKET_MANUAL_BODY_TOO_LARGE")

    body = bytearray()
    try:
        async for chunk in request.stream():
            remaining = MAX_MANUAL_SNAPSHOT_BYTES + 1 - len(body)
            if remaining > 0:
                body.extend(chunk[:remaining])
            if len(body) > MAX_MANUAL_SNAPSHOT_BYTES or len(chunk) > remaining:
                raise MarketSourceFailure("MARKET_MANUAL_BODY_TOO_LARGE")
    except MarketSourceFailure:
        raise
    except Exception:
        raise MarketSourceFailure("MARKET_MANUAL_SNAPSHOT_INVALID") from None
    return bytes(body)


async def _parse_manual_import(request: Request) -> ManualImportRequest:
    raw = await _read_manual_body(request)
    try:
        data = ManualImportRequest.model_validate_json(raw, strict=True)
    except (ValidationError, ValueError, RecursionError):
        raise MarketSourceFailure("MARKET_MANUAL_SNAPSHOT_INVALID") from None
    if data.__pydantic_extra__:
        raise MarketSourceFailure("MARKET_MANUAL_SNAPSHOT_INVALID")
    return data


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
        "scheduleRevision": row["schedule_revision"],
        "scheduleEnabled": row["schedule_enabled"],
        "scheduleIntervalMinutes": row["schedule_interval_minutes"],
        "scheduleNextRunAt": row["schedule_next_run_at"],
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
        entries = row.get("entries")
        if (
            not isinstance(entries, (tuple, list))
            or len(entries) != row["entry_count"]
        ):
            raise MarketSourceFailure("MARKET_REFRESH_FAILED")
        value["entries"] = [_entry_view(entry) for entry in entries]
    return value


def _recovery_reason(value) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return MarketSourceFailure(value).code
    except TypeError:
        return None


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
        transaction_factory=transaction,
    )


def get_market_analysis_service() -> MarketAnalysisService:
    return MarketAnalysisService(
        MarketRepository(),
        transaction_factory=transaction,
        connection_factory=connection,
        provider_gateway=MarketAnalysisProviderGateway(),
    )


def _analysis_view(result) -> dict:
    def value(name: str):
        return (
            result.get(name)
            if isinstance(result, dict)
            else getattr(result, name)
        )

    analysis = value("analysis")
    if analysis is not None and not isinstance(analysis, dict):
        analysis = analysis.model_dump(mode="json", by_alias=True)
    public_error_code = value("public_error_code")
    if public_error_code not in {
        "MARKET_ANALYSIS_CANCELLED",
        "MARKET_ANALYSIS_PROVIDER_FAILED",
        "MARKET_ANALYSIS_INVALID_RESPONSE",
        "MARKET_ANALYSIS_INPUT_CHANGED",
    }:
        public_error_code = None
    return {
        "id": value("id"),
        "projectId": value("project_id"),
        "inputManifestHash": value("input_manifest_hash"),
        "promptPolicyVersion": value("policy_version"),
        "status": value("status"),
        "analysis": analysis,
        "resultHash": value("result_hash"),
        "publicErrorCode": public_error_code,
        "createdAt": value("created_at"),
        "completedAt": value("completed_at"),
    }


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
    request: Request,
    service: MarketSourceService = Depends(get_market_source_service),
):
    data = await _parse_manual_import(request)
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
    if data.__pydantic_extra__:
        raise MarketSourceFailure("MARKET_REFRESH_COMMAND_INVALID")
    result = await service.refresh(source_id, data.idempotency_key)
    return _snapshot_view(result, detail=True)


@router.put("/market-sources/{source_id}/schedule")
async def update_market_source_schedule(
    source_id: BoundedId,
    data: ScheduleRequest,
    service: MarketSourceService = Depends(get_market_source_service),
):
    result = await service.update_schedule(
        source_id,
        expected_revision=data.expectedRevision,
        enabled=data.enabled,
        interval_minutes=data.intervalMinutes,
        idempotency_key=data.idempotencyKey,
    )
    return {
        "sourceId": result["source_id"],
        "revision": result["revision"],
        "enabled": result["enabled"],
        "intervalMinutes": result["interval_minutes"],
        "nextRunAt": result["next_run_at"],
        "policyStatus": result["policy_status"],
        "recoveryReason": _recovery_reason(result["recovery_reason"]),
    }


@router.post("/projects/{project_id}/market-analyses")
async def analyze_market_snapshots(
    project_id: BoundedId,
    data: AnalysisRequest,
    service: MarketAnalysisService = Depends(get_market_analysis_service),
):
    if data.__pydantic_extra__:
        raise MarketAnalysisFailure("MARKET_ANALYSIS_INVALID_REQUEST")
    result = await service.analyze(
        AnalyzeMarket(
            project_id=project_id,
            snapshot_ids=data.snapshotIds,
            idempotency_key=data.idempotencyKey,
        )
    )
    return _analysis_view(result)


@router.get("/projects/{project_id}/market-analyses/{analysis_id}")
async def get_market_analysis(
    project_id: BoundedId,
    analysis_id: BoundedId,
    service: MarketAnalysisService = Depends(get_market_analysis_service),
):
    return _analysis_view(await service.get(project_id, analysis_id))
