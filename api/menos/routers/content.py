"""Content CRUD endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel

from menos.auth.dependencies import AuthenticatedKeyId
from menos.models import ContentMetadata
from menos.services.di import get_minio_storage, get_surreal_repo
from menos.services.storage import MinIOStorage, SurrealDBRepository

router = APIRouter(prefix="/content", tags=["content"])


class ContentItem(BaseModel):
    """Content item response."""

    id: str
    content_type: str
    title: str | None = None
    created_at: str
    metadata: dict | None = None


class ContentList(BaseModel):
    """Paginated content list."""

    items: list[ContentItem]
    total: int
    offset: int
    limit: int


class ContentCreateResponse(BaseModel):
    """Response for content creation."""

    id: str
    file_path: str
    file_size: int


@router.get("", response_model=ContentList)
async def list_content(
    key_id: AuthenticatedKeyId,
    content_type: Annotated[str | None, Query(description="Filter by content type")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
):
    """List stored content."""
    items, total = await surreal_repo.list_content(
        offset=offset,
        limit=limit,
        content_type=content_type,
    )

    content_items = [
        ContentItem(
            id=item.id or "",
            content_type=item.content_type,
            title=item.title,
            created_at=item.created_at.isoformat() if item.created_at else "",
            metadata=item.metadata,
        )
        for item in items
    ]
    return ContentList(items=content_items, total=total, offset=offset, limit=limit)


@router.get("/{content_id}")
async def get_content(
    content_id: str,
    key_id: AuthenticatedKeyId,
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
):
    """Get content metadata by ID."""
    metadata = await surreal_repo.get_content(content_id)
    if not metadata:
        return {"error": "Content not found"}

    return {
        "id": metadata.id,
        "content_type": metadata.content_type,
        "title": metadata.title,
        "created_at": metadata.created_at.isoformat() if metadata.created_at else None,
        "metadata": metadata.metadata,
    }


@router.post("", response_model=ContentCreateResponse)
async def create_content(
    key_id: AuthenticatedKeyId,
    file: UploadFile,
    content_type: str,
    title: Annotated[str | None, Query()] = None,
    minio_storage: MinIOStorage = Depends(get_minio_storage),
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
):
    """Upload new content."""
    content_id = str(uuid.uuid4())
    file_path = f"{content_type}/{content_id}/{file.filename}"

    # Upload to MinIO
    file_size = await minio_storage.upload(
        file_path,
        file.file,
        file.content_type or "application/octet-stream",
    )

    # Store metadata in SurrealDB
    metadata = ContentMetadata(
        content_type=content_type,
        title=title or file.filename,
        mime_type=file.content_type or "application/octet-stream",
        file_size=file_size,
        file_path=file_path,
        author=key_id,
    )
    created = await surreal_repo.create_content(metadata)

    return ContentCreateResponse(
        id=created.id or content_id,
        file_path=file_path,
        file_size=file_size,
    )


@router.delete("/{content_id}")
async def delete_content(
    content_id: str,
    key_id: AuthenticatedKeyId,
    minio_storage: MinIOStorage = Depends(get_minio_storage),
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
):
    """Delete content by ID."""
    metadata = await surreal_repo.get_content(content_id)
    if not metadata:
        return {"error": "Content not found"}

    # Delete from MinIO
    await minio_storage.delete(metadata.file_path)

    # Delete chunks from SurrealDB
    await surreal_repo.delete_chunks(content_id)

    # Delete metadata from SurrealDB
    await surreal_repo.delete_content(content_id)

    return {"status": "deleted", "id": content_id}
