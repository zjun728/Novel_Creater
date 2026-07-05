"""
Novel Creator — FastAPI 后端入口
"""
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from database import get_pool, close_pool, ensure_schema
from routers import projects, providers, chapters, seeds, novel, export, market, settings_library, volumes, correction_tasks, story_blocks, ai_proxy, experience_cards, project_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    await ensure_schema()
    yield
    await close_pool()


app = FastAPI(title="Novel Creator API", version="0.1", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(projects.router, prefix="/api")
app.include_router(providers.router, prefix="/api")
app.include_router(chapters.router, prefix="/api")
app.include_router(seeds.router, prefix="/api")
app.include_router(novel.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(market.router, prefix="/api")
app.include_router(settings_library.router, prefix="/api")
app.include_router(volumes.router, prefix="/api")
app.include_router(correction_tasks.router, prefix="/api")
app.include_router(story_blocks.router, prefix="/api")
app.include_router(ai_proxy.router, prefix="/api")
app.include_router(experience_cards.router, prefix="/api")
app.include_router(project_state.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"ok": True}


FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"

if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/")
    async def serve_frontend_index():
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{path:path}")
    async def serve_frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")
        file_path = FRONTEND_DIST / path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIST / "index.html")
