"""Menos - YouTube transcript store service."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from menos import database as db
from menos.routers import search, videos


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    await db.init_db()
    yield


app = FastAPI(
    title="Menos",
    description="YouTube transcript store service",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(videos.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}
