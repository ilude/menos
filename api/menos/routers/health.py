"""Health and status endpoints."""

import os

import httpx
from fastapi import APIRouter
from minio import Minio
from surrealdb import Surreal

from menos.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    """Basic health check - always returns ok if service is running."""
    return {
        "status": "ok",
        "git_sha": os.environ.get("GIT_SHA", "unknown"),
        "build_date": os.environ.get("BUILD_DATE", "unknown"),
    }


async def check_surrealdb() -> str:
    """Check SurrealDB connectivity."""
    try:
        db = Surreal(settings.surrealdb_url)
        db.signin({"username": settings.surrealdb_user, "password": settings.surrealdb_password})
        db.use(settings.surrealdb_namespace, settings.surrealdb_database)
        db.query("INFO FOR DB")
        db.close()
        return "ok"
    except Exception as e:
        return f"error: {e}"


async def check_minio() -> str:
    """Check MinIO connectivity."""
    try:
        client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        client.bucket_exists(settings.minio_bucket)
        return "ok"
    except Exception as e:
        return f"error: {e}"


async def check_ollama() -> str:
    """Check Ollama connectivity."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{settings.ollama_url}/api/tags")
            response.raise_for_status()
            return "ok"
    except Exception as e:
        return f"error: {e}"


@router.get("/ready")
async def ready():
    """Readiness check - verifies dependencies are available."""
    checks = {
        "surrealdb": await check_surrealdb(),
        "minio": await check_minio(),
        "ollama": await check_ollama(),
    }
    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "ready" if all_ok else "degraded",
        "checks": checks,
    }
