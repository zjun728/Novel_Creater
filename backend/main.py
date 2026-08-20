"""Novel Creator Writer Core V1 FastAPI entrypoint."""

import asyncio
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.database import close_pool, connection, transaction
from backend.config import LOCAL_CONFIG_PATH, MANAGED_CORPUS_ROOT
from backend.gateways.openai_json_transport import (
    OpenAIJSONTransportLifecycleError,
)
from backend.domain.routers import (
    application_settings,
    assets,
    bibles,
    canon,
    chapter_outlines,
    chapter_sessions,
    contracts,
    corpus,
    finalization,
    market_sources,
    model_bindings,
    novel_downloads,
    planning,
    project_packages,
    project_imports,
    projects,
    providers,
    seeds,
    style_trials,
    story_engines,
)
from backend.runtime.draft_operation_tasks import DraftOperationTasksDrainPending
from backend.runtime.market_scheduler import build_market_scheduler_runtime
from backend.schema_version import verify_schema_version
from backend.security.paths import resolve_spa_file
from backend.security.redaction import install_error_handlers
from backend.services import project_imports as project_import_service
from backend.services.product_database_lifecycle_lock import (
    product_database_lifecycle_lock,
)


_project_package_logger = logging.getLogger("backend.project_packages")
_project_import_logger = logging.getLogger("backend.project_imports")


class DraftOperationTaskRegistryLifecycleError(RuntimeError):
    pass


async def _close_draft_operation_task_registry(
    registry,
) -> tuple[bool, object | None]:
    try:
        await registry.aclose()
    except DraftOperationTasksDrainPending as error:
        return False, error.cleanup_transfer
    except BaseException:
        return False, None
    finally:
        registry = None
    return True, None


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


def _previous_shutdown_transfer_failed(app: FastAPI) -> bool:
    draft_transfer = getattr(
        app.state,
        "draft_operation_shutdown_transfer",
        None,
    )
    market_transfer = getattr(
        app.state,
        "market_scheduler_shutdown_transfer",
        None,
    )
    transfers = []
    for transfer in (draft_transfer, market_transfer):
        if transfer is not None and not any(
            existing is transfer for existing in transfers
        ):
            transfers.append(transfer)

    failed = False
    for transfer in transfers:
        try:
            if not transfer.done() or transfer.cancelled():
                failed = True
                continue
            transfer.result()
        except BaseException:
            failed = True

    if draft_transfer is not None:
        registry_closed = (
            getattr(
                chapter_sessions.draft_operation_task_registry,
                "state",
                None,
            )
            == "closed"
        )
        if not registry_closed:
            failed = True
    return failed


@asynccontextmanager
async def _application_lifespan(app: FastAPI):
    if _previous_shutdown_transfer_failed(app):
        raise DraftOperationTaskRegistryLifecycleError(
            "Draft operation task registry lifecycle failed"
        ) from None

    try:
        project_packages.cleanup_stale_project_package_roots(
            project_packages.PROJECT_PACKAGE_TEMP_PARENT
        )
    except Exception:
        _project_package_logger.warning(
            "project_package_stale_cleanup_failed"
        )

    scheduler_runtime = None
    application_error = None
    planning_gateway_start_attempted = False
    outline_gateway_start_attempted = False
    finalization_quality_start_attempted = False
    finalization_extraction_start_attempted = False
    draft_registry_start_attempted = False
    shutdown_cancellations = 0
    pool_close_transferred = False
    pool_close_blocked = False
    draft_cleanup_transfer = None
    market_cleanup_transfer = None
    app.state.draft_operation_shutdown_transfer = None
    app.state.market_scheduler_shutdown_transfer = None
    try:
        async with connection() as session:
            await verify_schema_version(session)
        if MANAGED_CORPUS_ROOT is not None:
            try:
                await project_import_service.reconcile_project_import_staging(
                    managed_corpus_root=MANAGED_CORPUS_ROOT,
                    connection_factory=connection,
                    transaction_factory=transaction,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                _project_import_logger.warning(
                    "project_import_startup_reconciliation_failed"
                )
        draft_registry_start_attempted = True
        await chapter_sessions.draft_operation_task_registry.start()
        scheduler_runtime = build_market_scheduler_runtime()
        app.state.market_scheduler_runtime = scheduler_runtime
        scheduler_runtime.start()
        planning_gateway_start_attempted = True
        await planning.planning_provider_gateway.start()
        outline_gateway_start_attempted = True
        await chapter_outlines.chapter_outline_provider_gateway.start()
        finalization_quality_start_attempted = True
        await finalization.finalization_quality_gateway.start()
        finalization_extraction_start_attempted = True
        await finalization.finalization_extraction_gateway.start()
        yield
    except BaseException as error:
        application_error = error
    finally:
        cleanup_errors = []
        if draft_registry_start_attempted:
            draft_registry_cleanup = asyncio.create_task(
                _close_draft_operation_task_registry(
                    chapter_sessions.draft_operation_task_registry
                ),
                name="draft-operation-task-registry-close",
            )
            draft_registry_close_result, observed_cancellations = (
                await _settle_independent_cleanup(draft_registry_cleanup)
            )
            (
                draft_registry_close_succeeded,
                draft_cleanup_transfer,
            ) = draft_registry_close_result
            draft_registry_cleanup = None
            shutdown_cancellations += observed_cancellations
            observed_cancellations = 0
            if not draft_registry_close_succeeded:
                pool_close_blocked = draft_cleanup_transfer is None
                cleanup_errors.append(
                    DraftOperationTaskRegistryLifecycleError(
                        "Draft operation task registry lifecycle failed"
                    )
                )
        if finalization_extraction_start_attempted:
            extraction_cleanup = asyncio.create_task(
                _close_planning_provider_gateway(
                    finalization.finalization_extraction_gateway
                ),
                name="finalization-extraction-provider-close",
            )
            extraction_close_succeeded, observed_cancellations = (
                await _settle_independent_cleanup(extraction_cleanup)
            )
            extraction_cleanup = None
            shutdown_cancellations += observed_cancellations
            observed_cancellations = 0
            if not extraction_close_succeeded:
                cleanup_errors.append(
                    OpenAIJSONTransportLifecycleError(
                        "OpenAI JSON transport lifecycle failed"
                    )
                )
        if finalization_quality_start_attempted:
            quality_cleanup = asyncio.create_task(
                _close_planning_provider_gateway(
                    finalization.finalization_quality_gateway
                ),
                name="finalization-quality-provider-close",
            )
            quality_close_succeeded, observed_cancellations = (
                await _settle_independent_cleanup(quality_cleanup)
            )
            quality_cleanup = None
            shutdown_cancellations += observed_cancellations
            observed_cancellations = 0
            if not quality_close_succeeded:
                cleanup_errors.append(
                    OpenAIJSONTransportLifecycleError(
                        "OpenAI JSON transport lifecycle failed"
                    )
                )
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
                market_cleanup_transfer = getattr(
                    error,
                    "cleanup_transfer",
                    None,
                )
                cleanup_errors.append(error)
        if market_cleanup_transfer is not None:
            if draft_cleanup_transfer is not None:

                async def close_pool_after_draft_drain():
                    await draft_cleanup_transfer.start_pool_close(close_pool)

                final_transfer = market_cleanup_transfer.start_pool_close(
                    close_pool_after_draft_drain
                )
                app.state.draft_operation_shutdown_transfer = final_transfer
            elif pool_close_blocked:

                async def reject_transferred_pool_close():
                    raise DraftOperationTaskRegistryLifecycleError(
                        "Draft operation task registry lifecycle failed"
                    )

                final_transfer = market_cleanup_transfer.start_pool_close(
                    reject_transferred_pool_close
                )
            else:
                final_transfer = market_cleanup_transfer.start_pool_close(close_pool)
            app.state.market_scheduler_shutdown_transfer = final_transfer
            pool_close_transferred = True
        elif draft_cleanup_transfer is not None:
            final_transfer = draft_cleanup_transfer.start_pool_close(close_pool)
            app.state.draft_operation_shutdown_transfer = final_transfer
            pool_close_transferred = True
        if not pool_close_transferred and not pool_close_blocked:
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    lock_context = product_database_lifecycle_lock(LOCAL_CONFIG_PATH)
    lock_context.__enter__()
    application_context = _application_lifespan(app)
    application_error = None
    body_error = None
    try:
        await application_context.__aenter__()
    except BaseException as error:
        application_error = error
    else:
        try:
            yield
        except BaseException as error:
            body_error = error
        try:
            application_suppressed = await application_context.__aexit__(
                type(body_error) if body_error is not None else None,
                body_error,
                body_error.__traceback__ if body_error is not None else None,
            )
        except BaseException as error:
            application_error = error
        else:
            if body_error is not None and not application_suppressed:
                application_error = body_error

    if application_error is None:
        lock_context.__exit__(None, None, None)
        return

    try:
        lock_context.__exit__(
            type(application_error),
            application_error,
            application_error.__traceback__,
        )
    except BaseException:
        application_error = None
        body_error = None
        application_context = None
        lock_context = None
        raise
    raise application_error


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
app.include_router(novel_downloads.router, prefix="/api")
app.include_router(project_packages.router, prefix="/api")
app.include_router(project_imports.router, prefix="/api")
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
app.include_router(finalization.router, prefix="/api")
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
