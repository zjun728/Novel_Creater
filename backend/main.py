"""Novel Creator Writer Core V1 FastAPI entrypoint."""

import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.database import close_pool, connection
from backend.gateways.openai_json_transport import (
    OpenAIJSONTransportLifecycleError,
)
from backend.routers import (
    application_settings,
    assets,
    bibles,
    canon,
    chapter_outlines,
    chapter_sessions,
    contracts,
    corpus,
    market_sources,
    model_bindings,
    planning,
    projects,
    providers,
    seeds,
    style_trials,
    story_engines,
)
from backend.schema_version import verify_schema_version
from backend.runtime.market_scheduler import build_market_scheduler_runtime
from backend.security.paths import resolve_spa_file
from backend.security.redaction import install_error_handlers


async def _close_planning_provider_gateway(gateway) -> bool:
    try:
        await gateway.aclose()
    except BaseException:
        return False
    finally:
        gateway = None
    return True


async def _close_pool_for_lifespan() -> BaseException | None:
    try:
        await close_pool()
    except BaseException as error:
        return error
    return None


async def _settle_independent_cleanup(
    cleanup: asyncio.Task,
) -> tuple[object, int]:
    current = asyncio.current_task()
    observed_cancellations = 0
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            if current is None or current.cancelling() == 0:
                continue
            pending_cancellations = current.cancelling()
            for _ in range(pending_cancellations):
                current.uncancel()
            observed_cancellations += pending_cancellations
    succeeded = cleanup.result()
    current = None
    cleanup = None
    return succeeded, observed_cancellations


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler_runtime = None
    application_error = None
    planning_gateway_start_attempted = False
    outline_gateway_start_attempted = False
    shutdown_cancellations = 0
    pool_close_transferred = False
    app.state.market_scheduler_shutdown_transfer = None
    try:
        async with connection() as session:
            await verify_schema_version(session)
        scheduler_runtime = build_market_scheduler_runtime()
        app.state.market_scheduler_runtime = scheduler_runtime
        scheduler_runtime.start()
        planning_gateway_start_attempted = True
        await planning.planning_provider_gateway.start()
        outline_gateway_start_attempted = True
        await chapter_outlines.chapter_outline_provider_gateway.start()
        yield
    except BaseException as error:
        application_error = error
    finally:
        cleanup_errors = []
        if outline_gateway_start_attempted:
            outline_cleanup = asyncio.create_task(
                _close_planning_provider_gateway(
                    chapter_outlines.chapter_outline_provider_gateway
                ),
                name="chapter-outline-provider-gateway-close",
            )
            outline_close_succeeded, observed_cancellations = (
                await _settle_independent_cleanup(outline_cleanup)
            )
            outline_cleanup = None
            shutdown_cancellations += observed_cancellations
            observed_cancellations = 0
            if not outline_close_succeeded:
                cleanup_errors.append(
                    OpenAIJSONTransportLifecycleError(
                        "OpenAI JSON transport lifecycle failed"
                    )
                )
        if planning_gateway_start_attempted:
            planning_cleanup = asyncio.create_task(
                _close_planning_provider_gateway(
                    planning.planning_provider_gateway
                ),
                name="planning-provider-gateway-close",
            )
            planning_close_succeeded, observed_cancellations = (
                await _settle_independent_cleanup(planning_cleanup)
            )
            planning_cleanup = None
            shutdown_cancellations += observed_cancellations
            observed_cancellations = 0
            if not planning_close_succeeded:
                cleanup_errors.append(
                    OpenAIJSONTransportLifecycleError(
                        "OpenAI JSON transport lifecycle failed"
                    )
                )
        if scheduler_runtime is not None:
            try:
                await scheduler_runtime.stop()
            except BaseException as error:
                cleanup_transfer = getattr(
                    error,
                    "cleanup_transfer",
                    None,
                )
                if cleanup_transfer is not None:
                    app.state.market_scheduler_shutdown_transfer = (
                        cleanup_transfer.start_pool_close(close_pool)
                    )
                    pool_close_transferred = True
                cleanup_errors.append(error)
        if not pool_close_transferred:
            pool_cleanup = asyncio.create_task(
                _close_pool_for_lifespan(),
                name="application-database-pool-close",
            )
            pool_error, observed_cancellations = (
                await _settle_independent_cleanup(pool_cleanup)
            )
            pool_cleanup = None
            shutdown_cancellations += observed_cancellations
            observed_cancellations = 0
            if pool_error is not None:
                cleanup_errors.append(pool_error)
        current = asyncio.current_task()
        if current is not None:
            for _ in range(shutdown_cancellations):
                current.cancel()
        current = None
        all_errors = (
            ([application_error] if application_error is not None else [])
            + (
                [asyncio.CancelledError()]
                if shutdown_cancellations
                else []
            )
            + cleanup_errors
        )
        if len(all_errors) == 1:
            raise all_errors[0]
        if all_errors:
            raise BaseExceptionGroup(
                "application shutdown cleanup failed",
                all_errors,
            )


app = FastAPI(title="Novel Creator API", version="1.0", lifespan=lifespan)
app.state.provider_profile_service = providers.build_provider_profile_service()
install_error_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router, prefix="/api")
app.include_router(providers.router, prefix="/api")
app.include_router(application_settings.router, prefix="/api")
app.include_router(model_bindings.router, prefix="/api")
app.include_router(seeds.router, prefix="/api")
app.include_router(story_engines.router, prefix="/api")
app.include_router(style_trials.router, prefix="/api")
app.include_router(contracts.router, prefix="/api")
app.include_router(bibles.router, prefix="/api")
app.include_router(planning.router, prefix="/api")
app.include_router(chapter_outlines.router, prefix="/api")
app.include_router(chapter_sessions.router, prefix="/api")
app.include_router(assets.router, prefix="/api")
app.include_router(corpus.router, prefix="/api")
app.include_router(canon.router, prefix="/api")
app.include_router(market_sources.router, prefix="/api")


@app.get("/api/health")
async def health():
    payload = {"ok": True}
    browser_run_nonce = os.environ.get("M2_BROWSER_RUN_NONCE")
    if browser_run_nonce:
        payload["browserRunNonce"] = browser_run_nonce
    return payload


FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"

if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount(
            "/assets", StaticFiles(directory=assets_dir), name="frontend-assets"
        )

    @app.get("/")
    async def serve_frontend_index():
        return FileResponse(resolve_spa_file(FRONTEND_DIST, "index.html"))

    @app.get("/{path:path}")
    async def serve_frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")
        return FileResponse(resolve_spa_file(FRONTEND_DIST, path))
