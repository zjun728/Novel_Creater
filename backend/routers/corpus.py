"""Bounded allowlist-only corpus discovery, import, and preview routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.config import CORPUS_ROOT
from backend.database import transaction
from backend.domain.corpus import (
    FRAGMENT_PAGE_DEFAULT,
    FRAGMENT_PAGE_MAX,
    FRAGMENT_PREVIEW_CHARS,
    PREVIEW_DEFAULT_CHARS,
    PREVIEW_MAX_CHARS,
)
from backend.repositories.corpus import CorpusRepository
from backend.services.corpus_import import (
    CorpusImportService,
    IDEMPOTENCY_KEY_PATTERN,
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


def get_corpus_service() -> CorpusImportService:
    return CorpusImportService(
        CorpusRepository(),
        corpus_root=CORPUS_ROOT,
        transaction_factory=transaction,
        connection_factory=transaction,
    )


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
        "relativePath": row["relative_path"],
        "shortHash": _short_hash(row.get("source_hash")),
        "errorCode": row.get("public_error_code"),
    }


def _source_summary(row) -> dict:
    return {
        "id": row["id"],
        "name": row["title"],
        "relativePath": row["relative_path"],
        "shortHash": _short_hash(row.get("source_hash")),
        "encoding": row["encoding"],
        "state": row["status"],
        "chapterCount": int(row.get("chapter_count") or 0),
        "fragmentCount": int(row.get("fragment_count") or 0),
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
        request.relativePath, request.idempotencyKey
    )
    return _import_dto(row)


@router.get("/corpus/imports/{import_id}")
async def get_import(
    import_id: str = Path(min_length=1, max_length=36),
    service=Depends(get_corpus_service),
):
    return _import_dto(await service.get_import(import_id))


@router.get("/corpus/sources")
async def list_sources(service=Depends(get_corpus_service)):
    return {"items": [
        _source_summary(row) for row in await service.list_sources()
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
        **_source_summary(row),
        "preview": str(row.get("preview") or "")[:preview_chars],
    }


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
            "shortHash": _short_hash(row.get("content_hash")),
            "preview": str(row.get("normalized_text") or "")[
                :FRAGMENT_PREVIEW_CHARS
            ],
        } for row in result["items"]],
        "nextCursor": result.get("nextCursor"),
    }


__all__ = ("get_corpus_service", "router")
