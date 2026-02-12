"""Content CRUD endpoints."""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from menos.auth.dependencies import AuthenticatedKeyId
from menos.models import ContentMetadata, LinkModel
from menos.services.di import (
    get_minio_storage,
    get_pipeline_orchestrator,
    get_surreal_repo,
)
from menos.services.frontmatter import FrontmatterParser
from menos.services.linking import LinkExtractor
from menos.services.pipeline_orchestrator import PipelineOrchestrator
from menos.services.resource_key import generate_resource_key
from menos.services.storage import MinIOStorage, SurrealDBRepository

logger = logging.getLogger(__name__)

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
    job_id: str | None = None


class ContentUpdateRequest(BaseModel):
    """Request model for updating content metadata."""

    tags: list[str] | None = None
    title: str | None = None
    description: str | None = None


class Tag(BaseModel):
    """Tag with count."""

    name: str
    count: int


class TagList(BaseModel):
    """List of tags with counts."""

    tags: list[Tag]


class LinkedDocument(BaseModel):
    """Metadata about a linked document."""

    id: str
    title: str | None = None
    content_type: str


class LinkResponse(BaseModel):
    """Response for a single link with target/source metadata."""

    link_text: str
    link_type: str
    target: LinkedDocument | None = None
    source: LinkedDocument | None = None


class LinksListResponse(BaseModel):
    """Response for links list."""

    links: list[LinkResponse]


class ContentDetailResponse(BaseModel):
    """Detailed content response with pipeline results."""

    id: str
    content_type: str
    title: str | None = None
    description: str | None = None
    mime_type: str
    file_size: int
    file_path: str
    tags: list[str] = []
    created_at: str | None = None
    updated_at: str | None = None
    processing_status: str | None = None
    summary: str | None = None
    quality_tier: str | None = None
    quality_score: int | None = None
    pipeline_tags: list[str] = []
    topics: list[str] = []
    entities: list[str] = []
    metadata: dict | None = None


class ContentStatsResponse(BaseModel):
    """Aggregate content statistics."""

    total: int
    by_status: dict[str, int]
    by_content_type: dict[str, int]


class ContentEntityResponse(BaseModel):
    """Entity linked to a content item."""

    id: str
    name: str
    entity_type: str
    edge_type: str
    confidence: float | None = None


class ContentEntitiesListResponse(BaseModel):
    """List of entities for a content item."""

    items: list[ContentEntityResponse]
    total: int


class ContentChunkResponse(BaseModel):
    """A chunk belonging to a content item."""

    id: str | None = None
    chunk_index: int
    text: str
    embedding: list[float] | None = None


class ContentChunksListResponse(BaseModel):
    """List of chunks for a content item."""

    items: list[ContentChunkResponse]
    total: int


@router.get("/tags", response_model=TagList)
async def list_tags(
    key_id: AuthenticatedKeyId,
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
):
    """Get all tags with their counts, sorted by count descending then alphabetically."""
    tags_data = await surreal_repo.list_tags_with_counts()
    return TagList(tags=[Tag(name=t["name"], count=t["count"]) for t in tags_data])


@router.get("", response_model=ContentList)
async def list_content(
    key_id: AuthenticatedKeyId,
    content_type: Annotated[str | None, Query(description="Filter by content type")] = None,
    tags: Annotated[
        str | None, Query(description="Filter by tags (comma-separated, must have ALL)")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
):
    """List stored content."""
    tags_list = [t.strip() for t in tags.split(",")] if tags else None
    items, total = await surreal_repo.list_content(
        offset=offset,
        limit=limit,
        content_type=content_type,
        tags=tags_list,
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


@router.get("/stats", response_model=ContentStatsResponse)
async def get_content_stats(
    key_id: AuthenticatedKeyId,
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
):
    """Get aggregate content statistics."""
    stats = await surreal_repo.get_content_stats()
    return ContentStatsResponse(**stats)


@router.get("/{content_id}", response_model=ContentDetailResponse)
async def get_content(
    content_id: str,
    key_id: AuthenticatedKeyId,
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
):
    """Get content metadata by ID."""
    metadata = await surreal_repo.get_content(content_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Content not found")

    # Extract pipeline results from unified_result
    unified = (metadata.metadata or {}).get("unified_result") or {}

    return ContentDetailResponse(
        id=metadata.id or "",
        content_type=metadata.content_type,
        title=metadata.title,
        description=metadata.description,
        mime_type=metadata.mime_type,
        file_size=metadata.file_size,
        file_path=metadata.file_path,
        tags=metadata.tags,
        created_at=(
            metadata.created_at.isoformat() if metadata.created_at else None
        ),
        updated_at=(
            metadata.updated_at.isoformat() if metadata.updated_at else None
        ),
        processing_status=(metadata.metadata or {}).get(
            "processing_status"
        ),
        summary=unified.get("summary") or None,
        quality_tier=unified.get("tier") or None,
        quality_score=unified.get("quality_score") or None,
        pipeline_tags=unified.get("tags", []),
        topics=[
            t["name"]
            for t in unified.get("topics", [])
            if isinstance(t, dict)
        ],
        entities=[
            e["name"]
            for e in unified.get("additional_entities", [])
            if isinstance(e, dict)
        ],
        metadata=metadata.metadata,
    )


@router.post("", response_model=ContentCreateResponse)
async def create_content(
    key_id: AuthenticatedKeyId,
    file: UploadFile,
    content_type: str,
    title: Annotated[str | None, Query()] = None,
    tags: Annotated[list[str] | None, Query()] = None,
    minio_storage: MinIOStorage = Depends(get_minio_storage),
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
    orchestrator: PipelineOrchestrator = Depends(get_pipeline_orchestrator),
):
    """Upload new content."""
    content_id = str(uuid.uuid4())
    file_path = f"{content_type}/{content_id}/{file.filename}"

    # Read file content for frontmatter parsing if markdown
    file_content = await file.read()
    await file.seek(0)  # Reset for MinIO upload

    # Parse frontmatter from markdown files
    frontmatter_metadata = {}
    final_title = title
    final_tags = tags

    if file.filename and file.filename.endswith(".md"):
        parser = FrontmatterParser()
        _, frontmatter_metadata = parser.parse(file_content)

        # Extract title from frontmatter if not provided explicitly
        if not title:
            final_title = parser.extract_title(frontmatter_metadata, default=file.filename)

        # Merge tags from frontmatter and explicit parameter
        final_tags = parser.extract_tags(frontmatter_metadata, explicit_tags=tags)

    # Upload to MinIO
    file_size = await minio_storage.upload(
        file_path,
        file.file,
        file.content_type or "application/octet-stream",
    )

    # Store metadata in SurrealDB
    metadata = ContentMetadata(
        content_type=content_type,
        title=final_title or file.filename,
        mime_type=file.content_type or "application/octet-stream",
        file_size=file_size,
        file_path=file_path,
        author=key_id,
        tags=final_tags or [],
    )
    created = await surreal_repo.create_content(metadata)

    # Extract and store links from markdown content
    if file.filename and file.filename.endswith(".md"):
        await _extract_and_store_links(
            content_id=created.id or content_id,
            content=file_content.decode("utf-8"),
            surreal_repo=surreal_repo,
        )

    # Submit to unified pipeline
    text_content = file_content.decode("utf-8")
    final_content_id = created.id or content_id
    resource_key = generate_resource_key(content_type, final_content_id)
    job = await orchestrator.submit(
        final_content_id,
        text_content,
        content_type,
        metadata.title or "Untitled",
        resource_key,
    )

    return ContentCreateResponse(
        id=final_content_id,
        file_path=file_path,
        file_size=file_size,
        job_id=job.id if job else None,
    )


async def _extract_and_store_links(
    content_id: str,
    content: str,
    surreal_repo: SurrealDBRepository,
) -> None:
    """Extract links from content and store them in the database.

    Args:
        content_id: ID of the source content
        content: Markdown content to extract links from
        surreal_repo: Database repository
    """
    extractor = LinkExtractor()
    extracted_links = extractor.extract_links(content)

    if not extracted_links:
        return

    # Delete existing links for this content (for re-ingestion)
    await surreal_repo.delete_links_by_source(content_id)

    # Resolve and store each link
    for link in extracted_links:
        # Try to resolve link target to content ID by title
        target_id = None
        target_content = await surreal_repo.find_content_by_title(link.target)
        if target_content and target_content.id:
            target_id = target_content.id

        # Store link (even if target is unresolved)
        link_model = LinkModel(
            source=content_id,
            target=target_id,
            link_text=link.link_text,
            link_type=link.link_type,
        )
        await surreal_repo.create_link(link_model)


@router.patch("/{content_id}")
async def update_content(
    content_id: str,
    update_request: ContentUpdateRequest,
    key_id: AuthenticatedKeyId,
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
):
    """Update content metadata by ID."""
    metadata = await surreal_repo.get_content(content_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Content not found")

    # Apply updates to metadata
    if update_request.tags is not None:
        metadata.tags = update_request.tags
    if update_request.title is not None:
        metadata.title = update_request.title
    if update_request.description is not None:
        metadata.description = update_request.description

    # Update in database
    updated = await surreal_repo.update_content(content_id, metadata)

    return {
        "id": updated.id,
        "content_type": updated.content_type,
        "title": updated.title,
        "description": updated.description,
        "created_at": updated.created_at.isoformat() if updated.created_at else None,
        "updated_at": updated.updated_at.isoformat() if updated.updated_at else None,
        "tags": updated.tags,
        "metadata": updated.metadata,
    }


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
        raise HTTPException(status_code=404, detail="Content not found")

    # Delete from MinIO
    await minio_storage.delete(metadata.file_path)

    # Delete chunks from SurrealDB
    await surreal_repo.delete_chunks(content_id)

    # Delete links from SurrealDB
    await surreal_repo.delete_links_by_source(content_id)

    # Delete metadata from SurrealDB
    await surreal_repo.delete_content(content_id)

    return {"status": "deleted", "id": content_id}


@router.get("/{content_id}/links", response_model=LinksListResponse)
async def get_content_links(
    content_id: str,
    key_id: AuthenticatedKeyId,
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
):
    """Get forward links from this document.

    Returns links where this document is the source, including metadata
    about the target documents.
    """
    # Verify content exists
    content = await surreal_repo.get_content(content_id)
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    # Get links
    links = await surreal_repo.get_links_by_source(content_id)

    # Build response with target metadata
    link_responses = []
    for link in links:
        target_doc = None
        if link.target:
            target_metadata = await surreal_repo.get_content(link.target)
            if target_metadata:
                target_doc = LinkedDocument(
                    id=target_metadata.id or link.target,
                    title=target_metadata.title,
                    content_type=target_metadata.content_type,
                )

        link_responses.append(
            LinkResponse(
                link_text=link.link_text,
                link_type=link.link_type,
                target=target_doc,
            )
        )

    return LinksListResponse(links=link_responses)


@router.get("/{content_id}/backlinks", response_model=LinksListResponse)
async def get_content_backlinks(
    content_id: str,
    key_id: AuthenticatedKeyId,
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
):
    """Get backlinks to this document.

    Returns links where this document is the target, including metadata
    about the source documents.
    """
    # Verify content exists
    content = await surreal_repo.get_content(content_id)
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    # Get backlinks
    backlinks = await surreal_repo.get_links_by_target(content_id)

    # Build response with source metadata
    link_responses = []
    for link in backlinks:
        source_doc = None
        if link.source:
            source_metadata = await surreal_repo.get_content(link.source)
            if source_metadata:
                source_doc = LinkedDocument(
                    id=source_metadata.id or link.source,
                    title=source_metadata.title,
                    content_type=source_metadata.content_type,
                )

        link_responses.append(
            LinkResponse(
                link_text=link.link_text,
                link_type=link.link_type,
                source=source_doc,
            )
        )

    return LinksListResponse(links=link_responses)


@router.get("/{content_id}/entities", response_model=ContentEntitiesListResponse)
async def get_content_entities(
    content_id: str,
    key_id: AuthenticatedKeyId,
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
):
    """Get entities linked to this content item."""
    content = await surreal_repo.get_content(content_id)
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    entities_with_edges = await surreal_repo.get_entities_for_content(content_id)

    items = [
        ContentEntityResponse(
            id=entity.id or "",
            name=entity.name,
            entity_type=entity.entity_type.value,
            edge_type=edge.edge_type.value,
            confidence=edge.confidence,
        )
        for entity, edge in entities_with_edges
    ]

    return ContentEntitiesListResponse(items=items, total=len(items))


@router.get("/{content_id}/chunks", response_model=ContentChunksListResponse)
async def get_content_chunks(
    content_id: str,
    key_id: AuthenticatedKeyId,
    include_embeddings: Annotated[bool, Query()] = False,
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
):
    """Get chunks for this content item."""
    content = await surreal_repo.get_content(content_id)
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    chunks = await surreal_repo.get_chunks(content_id)

    items = [
        ContentChunkResponse(
            id=chunk.id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            embedding=chunk.embedding if include_embeddings else None,
        )
        for chunk in chunks
    ]

    return ContentChunksListResponse(items=items, total=len(items))


@router.get("/{content_id}/download")
async def download_content(
    content_id: str,
    key_id: AuthenticatedKeyId,
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
    minio_storage: MinIOStorage = Depends(get_minio_storage),
):
    """Download the original file for a content item."""
    content = await surreal_repo.get_content(content_id)
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    try:
        data = await minio_storage.download(content.file_path)
    except RuntimeError:
        raise HTTPException(status_code=404, detail="File not found in storage")

    filename = content.file_path.rsplit("/", 1)[-1]
    return Response(
        content=data,
        media_type=content.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
