"""Dormant router factory for disposable draft-pair transaction tests."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request

from backend.control_plane.draft_write_errors import DraftWriteError
from backend.control_plane.draft_write_models import parse_manifest_bytes, to_command
from backend.control_plane.draft_write_service import DraftWriteService
from backend.control_plane.restricted_jcs import canonical_sha256


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$", flags=re.ASCII)
IDEMPOTENCY_PATTERN = re.compile(r"^[!-~]{1,120}$", flags=re.ASCII)
MAX_MANIFEST_BYTES = 4 * 1024 * 1024


def _header_error(name: str) -> DraftWriteError:
    if name.lower() == "idempotency-key":
        return DraftWriteError(
            code="invalid_idempotency_key",
            http_status=400,
            message="Idempotency key is invalid.",
        )
    return DraftWriteError(
        code="invalid_manifest_hash",
        http_status=400,
        message="Manifest hash is invalid.",
    )


def require_single_header(request: Request, name: str) -> str:
    """Return one syntactically valid control header or a safe 400 error."""

    values = request.headers.getlist(name)
    if len(values) != 1:
        raise _header_error(name)
    value = values[0]
    if name.lower() == "idempotency-key":
        if not IDEMPOTENCY_PATTERN.fullmatch(value):
            raise _header_error(name)
    elif name.lower() == "x-manifest-sha256":
        if not SHA256_PATTERN.fullmatch(value):
            raise _header_error(name)
    return value


def to_http_exception(error: DraftWriteError) -> HTTPException:
    """Map a domain error without exposing request, SQL, or schema details."""

    return HTTPException(
        status_code=error.http_status,
        detail={
            "code": error.code,
            "message": error.message,
            "retryable": error.retryable,
        },
    )


async def read_limited_manifest_body(request: Request) -> bytes:
    """Read the body stream up to the cumulative manifest byte limit."""

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_MANIFEST_BYTES:
            raise DraftWriteError(
                code="invalid_manifest",
                http_status=400,
                message="Manifest exceeds the maximum allowed size.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def create_router(*, service: DraftWriteService) -> APIRouter:
    router = APIRouter(tags=["control-plane-draft-writes"])

    @router.post("/projects/{project_id}/draft-write-batches")
    async def create_draft_write_batch(project_id: str, request: Request) -> dict[str, object]:
        try:
            supplied_hash = require_single_header(request, "X-Manifest-SHA256")
            idempotency_key = require_single_header(request, "Idempotency-Key")
            raw = await read_limited_manifest_body(request)
            parsed, manifest_value = parse_manifest_bytes(raw)
            if canonical_sha256(manifest_value) != supplied_hash:
                raise DraftWriteError(
                    code="invalid_manifest_hash",
                    http_status=400,
                    message="Manifest hash does not match the request body.",
                )
            command = to_command(
                route_project_id=project_id,
                request=parsed,
                idempotency_key=idempotency_key,
                manifest_sha256=supplied_hash,
            )
            return (await service.submit(command)).to_wire()
        except DraftWriteError as error:
            raise to_http_exception(error) from None

    return router
