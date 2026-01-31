"""Dependency injection container for services."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from minio import Minio
from surrealdb import Surreal

from menos.config import settings
from menos.services.storage import MinIOStorage, SurrealDBRepository


@asynccontextmanager
async def get_storage_context() -> AsyncGenerator[tuple[MinIOStorage, SurrealDBRepository], None]:
    """Create and manage storage service instances.

    Yields:
        Tuple of (MinIOStorage, SurrealDBRepository)
    """
    # Initialize MinIO
    minio_client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    minio_storage = MinIOStorage(minio_client, settings.minio_bucket)

    # Initialize SurrealDB
    db = Surreal(settings.surrealdb_url)
    surreal_repo = SurrealDBRepository(
        db,
        settings.surrealdb_namespace,
        settings.surrealdb_database,
        settings.surrealdb_user,
        settings.surrealdb_password,
    )

    try:
        await surreal_repo.connect()
        yield minio_storage, surreal_repo
    finally:
        # SurrealDB blocking HTTP client doesn't implement close()
        pass


async def get_minio_storage() -> MinIOStorage:
    """Get MinIO storage instance for dependency injection."""
    minio_client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    return MinIOStorage(minio_client, settings.minio_bucket)


async def get_surreal_repo() -> SurrealDBRepository:
    """Get SurrealDB repository instance for dependency injection."""
    db = Surreal(settings.surrealdb_url)
    repo = SurrealDBRepository(
        db,
        settings.surrealdb_namespace,
        settings.surrealdb_database,
        settings.surrealdb_user,
        settings.surrealdb_password,
    )
    await repo.connect()
    return repo
