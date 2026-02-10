"""Menos API - Centralized content vault with semantic search."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from surrealdb import Surreal

from menos.config import get_settings
from menos.routers import auth, classification, content, entities, graph, health, search, youtube
from menos.services.migrator import MigrationService

logger = logging.getLogger(__name__)


def run_migrations() -> None:
    """Run database migrations on startup."""
    settings = get_settings()
    migrations_dir = Path(__file__).parent.parent / "migrations"

    if not migrations_dir.exists():
        logger.warning(f"Migrations directory not found: {migrations_dir}")
        return

    try:
        db = Surreal(settings.surrealdb_url)
        db.signin({"username": settings.surrealdb_user, "password": settings.surrealdb_password})
        db.use(settings.surrealdb_namespace, settings.surrealdb_database)

        migrator = MigrationService(db, migrations_dir)
        status = migrator.status()

        if not status["pending"]:
            logger.info("Database migrations: all up to date")
            return

        logger.info(f"Running {len(status['pending'])} pending migration(s)...")
        applied = migrator.migrate()
        logger.info(f"Applied migrations: {', '.join(applied)}")

    except Exception as e:
        logger.error(f"Migration failed: {e} - app continuing without migration")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup."""
    run_migrations()
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
app.include_router(entities.router, prefix="/api/v1")
app.include_router(graph.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")
app.include_router(youtube.router, prefix="/api/v1")
app.include_router(classification.router, prefix="/api/v1")
