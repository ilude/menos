"""YouTube ingestion endpoints."""

import io
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from menos.auth.dependencies import AuthenticatedKeyId
from menos.models import ChunkModel, ContentMetadata
from menos.services.chunking import ChunkingService
from menos.services.di import (
    get_minio_storage,
    get_pipeline_orchestrator,
    get_surreal_repo,
)
from menos.services.embeddings import EmbeddingService, get_embedding_service
from menos.services.pipeline_orchestrator import PipelineOrchestrator
from menos.services.resource_key import generate_resource_key
from menos.services.storage import MinIOStorage, SurrealDBRepository
from menos.services.youtube import YouTubeService, get_youtube_service
from menos.services.youtube_metadata import (
    YouTubeMetadataService,
    get_youtube_metadata_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/youtube", tags=["youtube"])


class YouTubeIngestRequest(BaseModel):
    """Request to ingest a YouTube video."""

    url: str
    generate_embeddings: bool = True


class YouTubeIngestResponse(BaseModel):
    """Response after ingesting a video."""

    id: str
    video_id: str
    title: str
    transcript_length: int
    chunks_created: int
    file_path: str
    job_id: str | None = None


class YouTubeVideoInfo(BaseModel):
    """Video information response."""

    id: str
    video_id: str
    title: str | None
    transcript_preview: str
    chunk_count: int


class YouTubeVideoDetail(BaseModel):
    """Detailed video information response."""

    video_id: str
    content_id: str
    title: str | None
    channel_title: str | None = None
    channel_id: str | None = None
    duration_seconds: int | None = None
    published_at: str | None = None
    view_count: int | None = None
    like_count: int | None = None
    transcript: str | None = None
    summary: str | None = None
    tags: list[str] = []
    topics: list[str] = []
    entities: list[str] = []
    quality_tier: str | None = None
    quality_score: int | None = None
    description_urls: list[str] = []
    chunk_count: int = 0
    processing_status: str | None = None


class YouTubeChannelInfo(BaseModel):
    """Channel information response."""

    channel_id: str
    channel_title: str
    video_count: int


class YouTubeChannelsResponse(BaseModel):
    """Response containing list of channels."""

    channels: list[YouTubeChannelInfo]


@router.post("/ingest", response_model=YouTubeIngestResponse)
async def ingest_video(
    body: YouTubeIngestRequest,
    key_id: AuthenticatedKeyId,
    youtube_service: YouTubeService = Depends(get_youtube_service),
    minio_storage: MinIOStorage = Depends(get_minio_storage),
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    metadata_service: YouTubeMetadataService = Depends(get_youtube_metadata_service),
    orchestrator: PipelineOrchestrator = Depends(get_pipeline_orchestrator),
):
    """Ingest a YouTube video transcript.

    Fetches the transcript, stores it in MinIO, saves metadata to SurrealDB,
    and optionally generates embeddings for search.
    """
    # Extract video ID and fetch transcript
    video_id = youtube_service.extract_video_id(body.url)
    transcript = youtube_service.fetch_transcript(video_id)

    # Fetch rich metadata from YouTube Data API
    yt_metadata = None
    try:
        yt_metadata = metadata_service.fetch_metadata(video_id)
        logger.info(f"Fetched metadata for video {video_id}: {yt_metadata.title}")
    except Exception as e:
        logger.warning(f"Failed to fetch YouTube metadata for {video_id}: {e}")

    # Prepare file paths
    timestamped_content = transcript.timestamped_text
    file_path = f"youtube/{video_id}/transcript.txt"
    metadata_path = f"youtube/{video_id}/metadata.json"

    # Upload transcript to MinIO
    file_data = io.BytesIO(timestamped_content.encode("utf-8"))
    file_size = await minio_storage.upload(file_path, file_data, "text/plain")

    # Create metadata in SurrealDB
    video_title = yt_metadata.title if yt_metadata else f"YouTube: {video_id}"
    metadata = ContentMetadata(
        content_type="youtube",
        title=video_title,
        mime_type="text/plain",
        file_size=file_size,
        file_path=file_path,
        author=key_id,
        tags=yt_metadata.tags if yt_metadata else [],
        metadata={
            "video_id": video_id,
            "language": transcript.language,
            "segment_count": len(transcript.segments),
            "channel_id": yt_metadata.channel_id if yt_metadata else None,
            "channel_title": yt_metadata.channel_title if yt_metadata else None,
            "duration_seconds": yt_metadata.duration_seconds if yt_metadata else None,
        },
    )
    created = await surreal_repo.create_content(metadata)
    content_id = created.id or video_id

    # Save metadata.json to MinIO (include rich YouTube metadata if available)
    metadata_dict = {
        "id": content_id,
        "video_id": video_id,
        "title": yt_metadata.title if yt_metadata else metadata.title,
        "description": yt_metadata.description if yt_metadata else None,
        "description_urls": yt_metadata.description_urls if yt_metadata else [],
        "channel_id": yt_metadata.channel_id if yt_metadata else None,
        "channel_title": yt_metadata.channel_title if yt_metadata else None,
        "published_at": yt_metadata.published_at if yt_metadata else None,
        "duration": yt_metadata.duration_formatted if yt_metadata else None,
        "duration_seconds": yt_metadata.duration_seconds if yt_metadata else None,
        "view_count": yt_metadata.view_count if yt_metadata else None,
        "like_count": yt_metadata.like_count if yt_metadata else None,
        "tags": yt_metadata.tags if yt_metadata else [],
        "thumbnails": yt_metadata.thumbnails if yt_metadata else {},
        "language": transcript.language,
        "segment_count": len(transcript.segments),
        "transcript_length": len(transcript.full_text),
        "file_size": file_size,
        "author": key_id,
        "created_at": created.created_at.isoformat() if created.created_at else None,
        "fetched_at": yt_metadata.fetched_at if yt_metadata else None,
    }
    metadata_json = json.dumps(metadata_dict, indent=2)
    await minio_storage.upload(
        metadata_path, io.BytesIO(metadata_json.encode("utf-8")), "application/json"
    )

    # Chunk the transcript and create embeddings
    chunks_created = 0
    if body.generate_embeddings:
        chunking_service = ChunkingService(chunk_size=512, overlap=50)
        text_chunks = chunking_service.chunk_text(transcript.full_text)

        for i, chunk_text in enumerate(text_chunks):
            # Generate embedding
            try:
                embedding = await embedding_service.embed(chunk_text)
            except Exception:
                embedding = None

            # Store chunk
            chunk = ChunkModel(
                content_id=content_id,
                text=chunk_text,
                chunk_index=i,
                embedding=embedding,
            )
            await surreal_repo.create_chunk(chunk)
            chunks_created += 1

    # Submit to unified pipeline
    resource_key = generate_resource_key("youtube", video_id)
    job = await orchestrator.submit(
        content_id, transcript.full_text, "youtube", video_title, resource_key
    )

    return YouTubeIngestResponse(
        id=content_id,
        video_id=video_id,
        title=video_title,
        transcript_length=len(transcript.full_text),
        chunks_created=chunks_created,
        file_path=file_path,
        job_id=job.id if job else None,
    )


@router.get("/channels", response_model=YouTubeChannelsResponse)
async def list_channels(
    key_id: AuthenticatedKeyId,
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
):
    """Get all YouTube channels with video counts.

    Returns a list of unique channels from ingested videos with the number
    of videos from each channel.

    Args:
        key_id: Authenticated user ID
        surreal_repo: Database repository

    Returns:
        Response containing list of channels with video counts
    """
    items, _ = await surreal_repo.list_content(content_type="youtube", limit=1000)

    channels_map: dict[str, tuple[str, int]] = {}

    for item in items:
        if not item.metadata:
            continue

        channel_id = item.metadata.get("channel_id")
        channel_title = item.metadata.get("channel_title")

        if channel_id:
            if channel_id not in channels_map:
                channels_map[channel_id] = (channel_title or "Unknown Channel", 0)
            title, count = channels_map[channel_id]
            channels_map[channel_id] = (title, count + 1)

    channels = [
        YouTubeChannelInfo(
            channel_id=channel_id,
            channel_title=title,
            video_count=count,
        )
        for channel_id, (title, count) in sorted(
            channels_map.items(), key=lambda x: x[1][1], reverse=True
        )
    ]

    return YouTubeChannelsResponse(channels=channels)


@router.get("/{video_id}", response_model=YouTubeVideoDetail)
async def get_video(
    video_id: str,
    key_id: AuthenticatedKeyId,
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
    minio_storage: MinIOStorage = Depends(get_minio_storage),
):
    """Get detailed information about an ingested YouTube video."""
    item = await _find_video_content(video_id, surreal_repo)
    if not item:
        raise HTTPException(status_code=404, detail="Video not found")

    meta = item.metadata or {}
    unified = meta.get("unified_result") or {}

    # Get chunk count
    chunks = await surreal_repo.get_chunks(item.id or "")

    # Get full transcript
    transcript = None
    try:
        content = await minio_storage.download(item.file_path)
        transcript = content.decode("utf-8")
    except Exception:
        pass

    # Extract topic/entity names from unified_result dicts
    topics = [t["name"] for t in unified.get("topics", []) if "name" in t]
    entities = [
        e["name"]
        for e in unified.get("additional_entities", [])
        if "name" in e
    ]

    # Get description_urls: try metadata first, then MinIO metadata.json
    description_urls = meta.get("description_urls") or []
    if not description_urls:
        try:
            minio_meta_path = f"youtube/{video_id}/metadata.json"
            raw = await minio_storage.download(minio_meta_path)
            minio_meta = json.loads(raw.decode("utf-8"))
            description_urls = minio_meta.get("description_urls", [])
        except Exception:
            description_urls = []

    return YouTubeVideoDetail(
        video_id=video_id,
        content_id=item.id or "",
        title=item.title,
        channel_title=meta.get("channel_title"),
        channel_id=meta.get("channel_id"),
        duration_seconds=meta.get("duration_seconds"),
        published_at=meta.get("published_at"),
        view_count=meta.get("view_count"),
        like_count=meta.get("like_count"),
        transcript=transcript,
        summary=unified.get("summary"),
        tags=unified.get("tags", []),
        topics=topics,
        entities=entities,
        quality_tier=unified.get("tier"),
        quality_score=unified.get("quality_score"),
        description_urls=description_urls,
        chunk_count=len(chunks),
        processing_status=meta.get("processing_status"),
    )


@router.get("/{video_id}/transcript")
async def get_video_transcript(
    video_id: str,
    key_id: AuthenticatedKeyId,
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
    minio_storage: MinIOStorage = Depends(get_minio_storage),
):
    """Get raw transcript text for a YouTube video."""
    item = await _find_video_content(video_id, surreal_repo)
    if not item:
        raise HTTPException(status_code=404, detail="Video not found")

    try:
        transcript_bytes = await minio_storage.download(item.file_path)
    except Exception:
        raise HTTPException(
            status_code=404, detail="Transcript not found"
        )

    return Response(content=transcript_bytes, media_type="text/plain")


async def _find_video_content(
    video_id: str, surreal_repo: SurrealDBRepository
) -> ContentMetadata | None:
    """Find content record by YouTube video_id."""
    items, _ = await surreal_repo.list_content(content_type="youtube")
    for item in items:
        if item.metadata and item.metadata.get("video_id") == video_id:
            return item
    return None


@router.get("", response_model=list[YouTubeVideoInfo])
async def list_videos(
    key_id: AuthenticatedKeyId,
    channel_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
):
    """List all ingested YouTube videos.

    Args:
        key_id: Authenticated user ID
        channel_id: Optional filter by YouTube channel ID
        limit: Maximum number of videos to return
        surreal_repo: Database repository

    Returns:
        List of YouTube videos, optionally filtered by channel
    """
    items, _ = await surreal_repo.list_content(content_type="youtube", limit=limit)

    videos = []
    for item in items:
        video_id = item.metadata.get("video_id", "") if item.metadata else ""
        item_channel_id = item.metadata.get("channel_id") if item.metadata else None

        if channel_id and item_channel_id != channel_id:
            continue

        chunks = await surreal_repo.get_chunks(item.id or "")

        videos.append(
            YouTubeVideoInfo(
                id=item.id or "",
                video_id=video_id,
                title=item.title,
                transcript_preview="",
                chunk_count=len(chunks),
            )
        )

    return videos
