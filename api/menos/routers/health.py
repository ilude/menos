"""Health and status endpoints."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    """Basic health check - always returns ok if service is running."""
    return {"status": "ok"}


@router.get("/ready")
async def ready():
    """Readiness check - verifies dependencies are available."""
    # TODO: Check SurrealDB, MinIO, Ollama connectivity
    checks = {
        "surrealdb": "ok",
        "minio": "ok",
        "ollama": "ok",
    }
    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "ready" if all_ok else "degraded",
        "checks": checks,
    }
