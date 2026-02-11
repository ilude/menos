"""Menos API - Centralized content vault with semantic search."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from surrealdb import Surreal

from menos.config import get_settings
from menos.routers import auth, content, entities, graph, health, jobs, search, youtube
from menos.services.migrator import MigrationService
from menos.tasks import background_tasks

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

_log_handler = logging.StreamHandler()
_log_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
)
logging.getLogger("menos").setLevel(LOG_LEVEL)
logging.getLogger("menos").addHandler(_log_handler)

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
    if background_tasks:
        logger.info("Waiting for %d background task(s)...", len(background_tasks))
        _done, pending = await asyncio.wait(background_tasks, timeout=30.0)
        for t in pending:
            t.cancel()


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
app.include_router(jobs.content_router, prefix="/api/v1")
app.include_router(jobs.jobs_router, prefix="/api/v1")
