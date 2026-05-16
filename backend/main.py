"""
Novel Creator — FastAPI 后端入口
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import get_pool, close_pool
from routers import projects, providers, chapters, seeds, novel, export, market


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    yield
    await close_pool()


app = FastAPI(title="Novel Creator API", version="0.1", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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


@app.get("/api/health")
async def health():
    return {"ok": True}
