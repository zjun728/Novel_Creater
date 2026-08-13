"""Bounded allowlist-only corpus discovery, import, and preview routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from backend.domain.corpus import (
    FRAGMENT_PAGE_DEFAULT,
    FRAGMENT_PAGE_MAX,
    FRAGMENT_PREVIEW_CHARS,
    PREVIEW_DEFAULT_CHARS,
    PREVIEW_MAX_CHARS,
)
from backend.services.corpus_import import IDEMPOTENCY_KEY_PATTERN
from backend.services.corpus_library import (
    MAX_DISPLAY_NAME_CHARS,
    MAX_NOTES_CHARS,
    MAX_REFERENCE_TAGS,
    VERSION_LIST_DEFAULT,
    VERSION_LIST_MAX,
)
from backend.services.creative_assets import (
    CreativeAssetService,
    build_creative_asset_service,
)


router = APIRouter(tags=["corpus"])
_DISCOVERY_REASON_CODES = (
    "nonTxt", "unreadable", "reparse", "traversal", "unsafeType"
)


class CorpusImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotencyKey: str = Field(
        min_length=16,
        max_length=64,
        pattern=IDEMPOTENCY_KEY_PATTERN,
    )
    relativePath: str = Field(min_length=1, max_length=2048)
    sourceId: str | None = Field(default=None, min_length=1, max_length=36)
    createDistinctSource: bool = False
    displayName: str | None = Field(
        default=None, min_length=1, max_length=MAX_DISPLAY_NAME_CHARS
    )
    referenceTags: tuple[str, ...] = Field(
        default=(), max_length=MAX_REFERENCE_TAGS
    )
    notes: str = Field(default="", max_length=MAX_NOTES_CHARS)


class CorpusLifecycleCommand(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    expectedRevision: int = Field(ge=1)


class CorpusPermanentDeleteCommand(CorpusLifecycleCommand):
    confirmPermanentDelete: bool


def get_corpus_service() -> CreativeAssetService:
    return build_creative_asset_service()


def _value(row, *keys, default=None):
    for key in keys:
        if key in row:
            return row[key]
    return default


def _short_hash(value) -> str:
    return value[:12] if isinstance(value, str) else ""


def _import_dto(row) -> dict:
    return {
        "importId": row["id"],
        "status": row["status"],
        "sourceId": _value(row, "corpus_source_id", "source_id"),
        "sourceRevision": _value(row, "source_revision"),
        "sourceRevisionId": _value(row, "source_revision_id"),
        "sourceLabel": row["relative_path"],
        "shortHash": _short_hash(row.get("source_hash")),
        "errorCode": row.get("public_error_code"),
    }


def _source_summary(row) -> dict:
    archived_at = row.get("archived_at")
    return {
        "id": row["id"],
        "revisionId": row["revision_id"],
        "revision": int(row["revision"]),
        "contentHash": row["source_hash"],
        "name": row["title"],
        "sourceLabel": row["relative_path"],
        "shortHash": _short_hash(row.get("source_hash")),
        "encoding": row["encoding"],
        "state": "archived" if archived_at is not None else "active",
        "referenceTags": list(row.get("reference_tags") or ()),
        "archivedAt": archived_at,
        "chapterCount": int(row.get("chapter_count") or 0),
        "fragmentCount": int(row.get("fragment_count") or 0),
        "referenceCount": int(row.get("reference_count") or 0),
        "historicalReferenceCount": int(
            row.get("historical_reference_count") or 0
        ),
        "deleteEligible": row.get("delete_eligible") is True,
        "deleteReason": row.get("delete_reason"),
    }


def _source_detail(row) -> dict:
    return {
        **_source_summary(row),
        "notes": str(row.get("notes") or ""),
    }


def _version_dto(row) -> dict:
    archived_at = row.get("archived_at")
    return {
        "id": row["id"],
        "revisionId": row["revision_id"],
        "revision": int(row["revision"]),
        "contentHash": row["source_hash"],
        "shortHash": _short_hash(row.get("source_hash")),
        "name": row["title"],
        "sourceLabel": row["relative_path"],
        "encoding": row["encoding"],
        "state": "archived" if archived_at is not None else "active",
        "referenceTags": list(row.get("reference_tags") or ()),
        "notes": str(row.get("notes") or ""),
        "archivedAt": archived_at,
        "referenceCount": int(row.get("reference_count") or 0),
        "isCurrent": row.get("is_current") in (True, 1),
        "importedAt": int(row.get("imported_at") or 0),
    }


@router.get("/corpus/discovery")
async def discovery(
    cursor: str | None = Query(default=None, max_length=4096),
    limit: int = Query(default=50, ge=1, le=200),
    service=Depends(get_corpus_service),
):
    result = await service.discovery(cursor=cursor, limit=limit)
    return {
        "items": [{
            "relativePath": item["relativePath"],
            "byteSize": int(item["byteSize"]),
            "preflightStatus": item["preflightStatus"],
        } for item in result["items"]],
        "nextCursor": result.get("nextCursor"),
        "reasonCounts": {
            reason: int(result["reasonCounts"][reason])
            for reason in _DISCOVERY_REASON_CODES
            if reason in result.get("reasonCounts", {})
        },
        "scanStrategy": result["scanStrategy"],
    }


@router.post("/corpus/imports")
async def create_import(
    request: CorpusImportRequest,
    service=Depends(get_corpus_service),
):
    row = await service.import_source(
        request.relativePath,
        request.idempotencyKey,
        source_id=request.sourceId,
        create_distinct_source=request.createDistinctSource,
        display_name=request.displayName,
        reference_tags=request.referenceTags,
        notes=request.notes,
    )
    return _import_dto(row)


@router.get("/corpus/imports/{import_id}")
async def get_import(
    import_id: str = Path(min_length=1, max_length=36),
    service=Depends(get_corpus_service),
):
    return _import_dto(await service.get_import(import_id))


@router.get("/corpus/sources")
async def list_sources(
    search: str | None = Query(default=None, max_length=200),
    state: str | None = Query(default=None, pattern="^(active|archived|all)$"),
    service=Depends(get_corpus_service),
):
    return {"items": [
        _source_summary(row)
        for row in await service.list_sources(search=search, state=state)
    ]}


@router.get("/corpus/sources/{source_id}")
async def get_source(
    source_id: str = Path(min_length=1, max_length=36),
    preview_chars: int = Query(
        default=PREVIEW_DEFAULT_CHARS,
        alias="previewChars",
        ge=1,
        le=PREVIEW_MAX_CHARS,
    ),
    service=Depends(get_corpus_service),
):
    row = await service.get_source(source_id, preview_chars)
    return {
        **_source_detail(row),
        "preview": str(row.get("preview") or "")[:preview_chars],
    }


@router.get("/corpus/sources/{source_id}/versions")
async def list_source_versions(
    source_id: str = Path(min_length=1, max_length=36),
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(
        default=VERSION_LIST_DEFAULT, ge=1, le=VERSION_LIST_MAX
    ),
    service=Depends(get_corpus_service),
):
    page = await service.list_versions(
        source_id, cursor=cursor, limit=limit
    )
    return {
        "items": [
            _version_dto(row)
            for row in page["items"]
        ],
        "nextCursor": page.get("nextCursor"),
    }


@router.post("/corpus/sources/{source_id}/archive")
async def archive_source(
    command: CorpusLifecycleCommand,
    source_id: str = Path(min_length=1, max_length=36),
    service=Depends(get_corpus_service),
):
    return _source_summary(
        await service.archive_source(source_id, command.expectedRevision)
    )


@router.post("/corpus/sources/{source_id}/restore")
async def restore_source(
    command: CorpusLifecycleCommand,
    source_id: str = Path(min_length=1, max_length=36),
    service=Depends(get_corpus_service),
):
    return _source_summary(
        await service.restore_source(source_id, command.expectedRevision)
    )


@router.delete(
    "/corpus/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def permanently_delete_source(
    command: CorpusPermanentDeleteCommand,
    source_id: str = Path(min_length=1, max_length=36),
    service=Depends(get_corpus_service),
):
    await service.permanently_delete_source(
        source_id,
        command.expectedRevision,
        command.confirmPermanentDelete,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/corpus/sources/{source_id}/chapters")
async def list_chapters(
    source_id: str = Path(min_length=1, max_length=36),
    service=Depends(get_corpus_service),
):
    rows = await service.list_chapters(source_id)
    return {"items": [{
        "id": row["id"],
        "order": int(row["chapter_order"]),
        "title": row["title"],
        "byteStart": int(row["raw_byte_start"]),
        "byteEnd": int(row["raw_byte_end"]),
        "charStart": int(row["normalized_char_start"]),
        "charEnd": int(row["normalized_char_end"]),
        "shortHash": _short_hash(row.get("content_hash")),
    } for row in rows]}


@router.get("/corpus/chapters/{chapter_id}/fragments")
async def list_fragments(
    chapter_id: str = Path(min_length=1, max_length=36),
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(
        default=FRAGMENT_PAGE_DEFAULT, ge=1, le=FRAGMENT_PAGE_MAX
    ),
    service=Depends(get_corpus_service),
):
    result = await service.list_fragments(chapter_id, cursor, limit)
    return {
        "items": [{
            "id": row["id"],
            "order": int(row["fragment_order"]),
            "charStart": int(row["chapter_char_start"]),
            "charEnd": int(row["chapter_char_end"]),
            "contentHash": row["content_hash"],
            "shortHash": _short_hash(row.get("content_hash")),
            "preview": str(row.get("normalized_text") or "")[
                :FRAGMENT_PREVIEW_CHARS
            ],
        } for row in result["items"]],
        "nextCursor": result.get("nextCursor"),
    }


__all__ = ("get_corpus_service", "router")
