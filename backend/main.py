"""Novel Creator Writer Core V1 FastAPI entrypoint."""

from contextlib import asynccontextmanager
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.database import close_pool, connection
from backend.routers import (
    application_settings,
    assets,
    canon,
    chapter_sessions,
    contracts,
    corpus,
    market_sources,
    model_bindings,
    planning,
    projects,
    providers,
    seeds,
    story_engines,
)
from backend.schema_version import verify_schema_version
from backend.security.paths import resolve_spa_file
from backend.security.redaction import install_error_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async with connection() as session:
            await verify_schema_version(session)
        yield
    finally:
        await close_pool()


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
app.include_router(contracts.router, prefix="/api")
app.include_router(planning.router, prefix="/api")
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
