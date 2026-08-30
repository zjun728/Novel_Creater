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
from backend.config import (
    LOCAL_CONFIG_PATH,
    RuntimeConfiguration,
    clear_runtime_configuration,
    install_runtime_configuration,
    load_runtime_configuration,
)
from backend.gateways.openai_json_transport import (
    OpenAIJSONTransportLifecycleError,
)
from backend.gateways import topic_discussion_provider
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
    manuscripts,
    model_bindings,
    novel_downloads,
    planning,
    project_overview,
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


class _ApplicationLifespanLease:
    def __init__(self) -> None:
        self.body_error: BaseException | None = None


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
        if transfer is None or any(
            existing is transfer for existing in transfers
        ):
            continue
        if type(transfer) not in (asyncio.Future, asyncio.Task):
            return True
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


def _combine_lifespan_errors(
    primary: BaseException | None,
    secondary: BaseException,
) -> BaseException:
    if primary is None:
        return secondary
    return BaseExceptionGroup(
        "application lifespan failed",
        [primary, secondary],
    )


@asynccontextmanager
async def _application_lifespan(
    app: FastAPI,
    runtime_configuration: RuntimeConfiguration,
):
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

    application_lease = _ApplicationLifespanLease()
    scheduler_runtime = None
    application_error = None
    planning_gateway_start_attempted = False
    topic_gateway_start_attempted = False
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
        if runtime_configuration.managed_corpus_root is not None:
            try:
                await project_import_service.reconcile_project_import_staging(
                    managed_corpus_root=runtime_configuration.managed_corpus_root,
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
        app.state.market_scheduler_runtime = None
        planning_gateway_start_attempted = True
        await planning.planning_provider_gateway.start()
        topic_gateway_start_attempted = True
        await topic_discussion_provider.topic_discussion_provider_gateway.start()
        outline_gateway_start_attempted = True
        await chapter_outlines.chapter_outline_provider_gateway.start()
        finalization_quality_start_attempted = True
        await finalization.finalization_quality_gateway.start()
        finalization_extraction_start_attempted = True
        await finalization.finalization_extraction_gateway.start()
        yield application_lease
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
        if topic_gateway_start_attempted:
            topic_cleanup = asyncio.create_task(
                _close_planning_provider_gateway(
                    topic_discussion_provider.topic_discussion_provider_gateway
                ),
                name="topic-discussion-provider-gateway-close",
            )
            topic_close_succeeded, observed_cancellations = (
                await _settle_independent_cleanup(topic_cleanup)
            )
            topic_cleanup = None
            shutdown_cancellations += observed_cancellations
            observed_cancellations = 0
            if not topic_close_succeeded:
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
                [application_lease.body_error]
                if application_lease.body_error is not None
                else []
            )
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


async def _complete_runtime_configuration(
    transfer: asyncio.Future,
    snapshot: RuntimeConfiguration,
):
    result = None
    primary = None
    clear_error = None
    try:
        result = await asyncio.shield(transfer)
    except BaseException as error:
        primary = error
    finally:
        transfer = None
    try:
        clear_runtime_configuration(snapshot)
    except BaseException as error:
        clear_error = error
    finally:
        snapshot = None
    if primary is not None and clear_error is not None:
        raise BaseExceptionGroup(
            "runtime configuration completion failed",
            [primary, clear_error],
        )
    if primary is not None:
        if issubclass(type(primary), (KeyboardInterrupt, SystemExit)):
            raise BaseExceptionGroup(
                "runtime configuration completion failed",
                [primary],
            )
        raise primary
    if clear_error is not None:
        if issubclass(type(clear_error), (KeyboardInterrupt, SystemExit)):
            raise BaseExceptionGroup(
                "runtime configuration completion failed",
                [clear_error],
            )
        raise clear_error
    return result


@asynccontextmanager
async def lifespan(app: FastAPI):
    lock_context = product_database_lifecycle_lock(LOCAL_CONFIG_PATH)
    lock_lease = lock_context.__enter__()
    lock_owned = True
    runtime_configuration = None
    runtime_configuration_owned = False

    def exit_lifecycle_lock(error: BaseException | None) -> None:
        nonlocal lock_owned
        try:
            lock_context.__exit__(None, error, None)
        except BaseException as outgoing:
            error = None
            BaseException.__traceback__.__set__(outgoing, None)
            raise outgoing from None
        finally:
            lock_owned = False

    def clear_runtime_configuration_once() -> BaseException | None:
        nonlocal runtime_configuration_owned
        if not runtime_configuration_owned:
            return None
        try:
            clear_runtime_configuration(runtime_configuration)
        except BaseException as error:
            return error
        finally:
            runtime_configuration_owned = False
        return None

    application_error = None
    body_error = None
    try:
        try:
            runtime_configuration = load_runtime_configuration(
                config_path=LOCAL_CONFIG_PATH,
            )
            install_runtime_configuration(runtime_configuration)
            runtime_configuration_owned = True
            previous_draft_transfer = getattr(
                app.state,
                "draft_operation_shutdown_transfer",
                None,
            )
            previous_market_transfer = getattr(
                app.state,
                "market_scheduler_shutdown_transfer",
                None,
            )
            application_context = _application_lifespan(
                app,
                runtime_configuration,
            )
            try:
                application_lease = await application_context.__aenter__()
            except BaseException as error:
                application_error = error
            else:
                try:
                    yield
                except BaseException as error:
                    body_error = error
                if type(application_lease) is _ApplicationLifespanLease:
                    application_lease.body_error = body_error
                try:
                    application_suppressed = await application_context.__aexit__(
                        None,
                        None,
                        None,
                    )
                except BaseException as error:
                    if type(application_lease) is _ApplicationLifespanLease:
                        application_error = error
                    else:
                        application_error = _combine_lifespan_errors(
                            body_error,
                            error,
                        )
                else:
                    if (
                        type(application_lease) is not _ApplicationLifespanLease
                        and body_error is not None
                        and not application_suppressed
                    ):
                        application_error = body_error

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
            publish_draft = (
                draft_transfer is not None
                and draft_transfer is not previous_draft_transfer
            )
            publish_market = (
                market_transfer is not None
                and market_transfer is not previous_market_transfer
            )
            transfers = []
            for transfer in (
                draft_transfer if publish_draft else None,
                market_transfer if publish_market else None,
            ):
                if transfer is None or any(
                    existing is transfer for existing in transfers
                ):
                    continue
                if type(transfer) not in (asyncio.Future, asyncio.Task):
                    raise TypeError
                transfers.append(transfer)
            if len(transfers) > 1:
                raise ValueError
            if transfers:
                runtime_transfer_coroutine = _complete_runtime_configuration(
                    transfers[0],
                    runtime_configuration,
                )
                try:
                    runtime_transfer = asyncio.create_task(
                        runtime_transfer_coroutine,
                        name="runtime-configuration-shutdown-transfer",
                    )
                except BaseException:
                    runtime_transfer_coroutine.close()
                    raise
                try:
                    completion = lock_lease.defer_until(runtime_transfer)
                except BaseException:
                    runtime_transfer.cancel()
                    raise
                runtime_configuration_owned = False
                if publish_draft:
                    app.state.draft_operation_shutdown_transfer = completion
                if publish_market:
                    app.state.market_scheduler_shutdown_transfer = completion
        except BaseException as error:
            application_error = _combine_lifespan_errors(
                application_error,
                error,
            )

        clear_error = clear_runtime_configuration_once()
        if clear_error is not None:
            application_error = _combine_lifespan_errors(
                application_error,
                clear_error,
            )
            clear_error = None

        if application_error is None:
            exit_lifecycle_lock(None)
            return

        try:
            exit_lifecycle_lock(application_error)
        except BaseException:
            application_error = None
            body_error = None
            application_context = None
            lock_context = None
            raise
        raise application_error
    finally:
        if lock_owned:
            clear_error = clear_runtime_configuration_once()
            if clear_error is not None:
                application_error = _combine_lifespan_errors(
                    application_error,
                    clear_error,
                )
                clear_error = None
            exit_lifecycle_lock(application_error)


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
app.include_router(project_overview.router, prefix="/api")
app.include_router(novel_downloads.router, prefix="/api")
app.include_router(manuscripts.router, prefix="/api")
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
