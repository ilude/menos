"""Menos API - Centralized content vault with semantic search."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from menos.routers import auth, content, health, search, youtube


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup."""
    # TODO: Initialize SurrealDB connection
    # TODO: Initialize MinIO client
    # TODO: Pull Ollama embedding model
    yield


app = FastAPI(
    title="Menos",
    description="Centralized content vault with semantic search",
    version="0.1.0",
    lifespan=lifespan,
)

# Public endpoints
app.include_router(health.router)

# Auth endpoints (mixed public/protected)
app.include_router(auth.router, prefix="/api/v1")

# Protected endpoints
app.include_router(content.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")
app.include_router(youtube.router, prefix="/api/v1")
