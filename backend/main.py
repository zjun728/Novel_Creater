"""Novel Creator Writer Core V1 FastAPI entrypoint."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.database import close_pool, connection
from backend.routers import canon, model_bindings, projects, providers, seeds
from backend.schema_version import verify_schema_version
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
app.include_router(model_bindings.router, prefix="/api")
app.include_router(seeds.router, prefix="/api")
app.include_router(canon.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"ok": True}


FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"

if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount(
            "/assets", StaticFiles(directory=assets_dir), name="frontend-assets"
        )

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
