"""Content CRUD endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from menos.auth.dependencies import AuthenticatedKeyId

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


@router.get("", response_model=ContentList)
async def list_content(
    key_id: AuthenticatedKeyId,
    content_type: Annotated[str | None, Query(description="Filter by content type")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """List stored content."""
    # TODO: Implement with SurrealDB
    return ContentList(items=[], total=0, offset=offset, limit=limit)


@router.get("/{content_id}")
async def get_content(
    content_id: str,
    key_id: AuthenticatedKeyId,
):
    """Get content by ID."""
    # TODO: Implement with SurrealDB + MinIO
    return {"id": content_id, "status": "not_implemented"}


@router.post("")
async def create_content(
    key_id: AuthenticatedKeyId,
):
    """Upload new content."""
    # TODO: Implement with MinIO upload + SurrealDB metadata
    return {"status": "not_implemented"}


@router.delete("/{content_id}")
async def delete_content(
    content_id: str,
    key_id: AuthenticatedKeyId,
):
    """Delete content by ID."""
    # TODO: Implement
    return {"status": "not_implemented"}
