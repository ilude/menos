"""Database models for SurrealDB."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ChunkModel(BaseModel):
    """A chunk of content with embedding."""

    id: str | None = None
    content_id: str
    text: str
    chunk_index: int
    embedding: list[float] | None = None
    created_at: datetime | None = None


class ContentMetadata(BaseModel):
    """Metadata for stored content."""

    id: str | None = None
    content_type: str
    title: str | None = None
    description: str | None = None
    mime_type: str
    file_size: int
    file_path: str
    author: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LinkModel(BaseModel):
    """Link between content items."""

    id: str | None = None
    source: str  # Content ID
    target: str | None = None  # Content ID, nullable for unresolved links
    link_text: str
    link_type: str  # "wiki" or "markdown"
    created_at: datetime | None = None
