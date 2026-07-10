"""Minimal test-only app factory for disposable control-plane verification."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Awaitable, Callable

from fastapi import FastAPI

from backend.control_plane.draft_write_service import DraftWriteService
from backend.control_plane.draft_write_transaction import ConnectionLike, PoolLike
from backend.routers.control_plane_draft_writes import create_router


def create_disposable_test_app(
    *,
    pool: PoolLike,
    expected_schema: str,
    run_token: str,
    environ: Mapping[str, str],
    uuid_factory: Callable[[], str],
    clock_ms: Callable[[], int],
    after_candidate_insert: Callable[[int], Awaitable[None]] | None = None,
    commit_operation: Callable[[ConnectionLike], Awaitable[None]] | None = None,
) -> FastAPI:
    """Create an isolated app without reading product globals or process state."""

    app = FastAPI()
    if environ.get("CONTROL_PLANE_DRAFT_WRITES_ENABLED") == "true":
        service = DraftWriteService(
            pool=pool,
            expected_schema=expected_schema,
            run_token=run_token,
            uuid_factory=uuid_factory,
            clock_ms=clock_ms,
            after_candidate_insert=after_candidate_insert,
            commit_operation=commit_operation,
        )
        app.include_router(create_router(service=service), prefix="/api")
    return app
