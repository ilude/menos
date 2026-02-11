"""YouTube ingestion endpoints."""

import asyncio
import io
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from menos.auth.dependencies import AuthenticatedKeyId
from menos.models import ChunkModel, ContentMetadata
from menos.services.chunking import ChunkingService
from menos.services.classification import ClassificationService
from menos.services.di import (
    get_classification_service,
    get_minio_storage,
    get_surreal_repo,
)
from menos.services.embeddings import EmbeddingService, get_embedding_service
from menos.services.storage import MinIOStorage, SurrealDBRepository
from menos.services.youtube import YouTubeService, get_youtube_service
from menos.services.youtube_metadata import (
    YouTubeMetadataService,
    get_youtube_metadata_service,
)
from menos.tasks import background_tasks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/youtube", tags=["youtube"])


class YouTubeIngestRequest(BaseModel):
    """Request to ingest a YouTube video."""

    url: str
    generate_embeddings: bool = True


class YouTubeUploadRequest(BaseModel):
    """Request to upload a pre-fetched YouTube transcript."""

    video_id: str
    transcript_text: str
    timestamped_text: str | None = None
    language: str = "en"
    generate_embeddings: bool = True


class YouTubeIngestResponse(BaseModel):
    """Response after ingesting a video."""

    id: str
    video_id: str
    title: str
    transcript_length: int
    chunks_created: int
    file_path: str
    classification_status: str | None = None


class YouTubeVideoInfo(BaseModel):
    """Video information response."""

    id: str
    video_id: str
    title: str | None
    transcript_preview: str
    chunk_count: int


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
    classification_service: ClassificationService = Depends(get_classification_service),
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

    # Launch classification as fire-and-forget background task
    classification_status = None
    min_len = classification_service.settings.classification_min_content_length
    if len(transcript.full_text) >= min_len:
        await surreal_repo.update_content_classification_status(content_id, "pending")
        classification_status = "pending"

        async def _classify_background():
            try:
                result = await classification_service.classify_content(
                    content_id=content_id,
                    content_text=transcript.full_text,
                    content_type="youtube",
                    title=video_title,
                )
                if result:
                    await surreal_repo.update_content_classification(
                        content_id, result.model_dump()
                    )
                    if result.summary:
                        summary_path = f"youtube/{video_id}/summary.md"
                        summary_data = io.BytesIO(result.summary.encode("utf-8"))
                        await minio_storage.upload(summary_path, summary_data, "text/markdown")
                    logger.info(
                        "Classification complete for %s: tier=%s score=%d",
                        content_id,
                        result.tier,
                        result.quality_score,
                    )
                else:
                    await surreal_repo.update_content_classification_status(content_id, "failed")
                    logger.warning("Classification returned no result for %s", content_id)
            except asyncio.CancelledError:
                logger.warning("Classification cancelled for %s (shutdown?)", content_id)
                try:
                    await surreal_repo.update_content_classification_status(content_id, "failed")
                except Exception:
                    pass
                raise
            except Exception as e:
                logger.error(
                    "Background classification failed for %s: %s", content_id, e, exc_info=True
                )
                try:
                    await surreal_repo.update_content_classification_status(content_id, "failed")
                except Exception as inner_e:
                    logger.error(
                        "Failed to mark classification as failed for %s: %s",
                        content_id,
                        inner_e,
                    )

        task = asyncio.create_task(_classify_background())
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

    return YouTubeIngestResponse(
        id=content_id,
        video_id=video_id,
        title=video_title,
        transcript_length=len(transcript.full_text),
        chunks_created=chunks_created,
        file_path=file_path,
        classification_status=classification_status,
    )


@router.post("/upload", response_model=YouTubeIngestResponse)
async def upload_transcript(
    body: YouTubeUploadRequest,
    key_id: AuthenticatedKeyId,
    minio_storage: MinIOStorage = Depends(get_minio_storage),
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    classification_service: ClassificationService = Depends(get_classification_service),
):
    """Upload a pre-fetched YouTube transcript.

    Use this when the server cannot fetch transcripts directly (IP blocked).
    Client fetches the transcript locally and uploads it here.
    """
    video_id = body.video_id
    content_to_store = body.timestamped_text or body.transcript_text
    transcript_path = f"youtube/{video_id}/transcript.txt"
    metadata_path = f"youtube/{video_id}/metadata.json"

    # Upload transcript to MinIO
    file_data = io.BytesIO(content_to_store.encode("utf-8"))
    file_size = await minio_storage.upload(transcript_path, file_data, "text/plain")

    # Create metadata object
    metadata = ContentMetadata(
        content_type="youtube",
        title=f"YouTube: {video_id}",
        mime_type="text/plain",
        file_size=file_size,
        file_path=transcript_path,
        author=key_id,
        tags=[],
        metadata={
            "video_id": video_id,
            "language": body.language,
            "transcript_length": len(body.transcript_text),
        },
    )

    # Save metadata to SurrealDB
    created = await surreal_repo.create_content(metadata)
    content_id = created.id or video_id

    # Also save metadata.json to MinIO
    metadata_dict = {
        "id": content_id,
        "video_id": video_id,
        "title": metadata.title,
        "language": body.language,
        "transcript_length": len(body.transcript_text),
        "file_size": file_size,
        "author": key_id,
        "created_at": created.created_at.isoformat() if created.created_at else None,
    }
    metadata_json = json.dumps(metadata_dict, indent=2)
    await minio_storage.upload(
        metadata_path, io.BytesIO(metadata_json.encode("utf-8")), "application/json"
    )

    # Chunk the transcript and create embeddings
    chunks_created = 0
    if body.generate_embeddings:
        chunking_service = ChunkingService(chunk_size=512, overlap=50)
        text_chunks = chunking_service.chunk_text(body.transcript_text)

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

    # Launch classification as fire-and-forget background task
    classification_status = None
    min_len = classification_service.settings.classification_min_content_length
    if len(body.transcript_text) >= min_len:
        await surreal_repo.update_content_classification_status(content_id, "pending")
        classification_status = "pending"
        transcript_text = body.transcript_text

        async def _classify_background():
            try:
                result = await classification_service.classify_content(
                    content_id=content_id,
                    content_text=transcript_text,
                    content_type="youtube",
                    title=f"YouTube: {video_id}",
                )
                if result:
                    await surreal_repo.update_content_classification(
                        content_id, result.model_dump()
                    )
                    if result.summary:
                        summary_path = f"youtube/{video_id}/summary.md"
                        summary_data = io.BytesIO(result.summary.encode("utf-8"))
                        await minio_storage.upload(summary_path, summary_data, "text/markdown")
                    logger.info(
                        "Classification complete for %s: tier=%s score=%d",
                        content_id,
                        result.tier,
                        result.quality_score,
                    )
                else:
                    await surreal_repo.update_content_classification_status(content_id, "failed")
                    logger.warning("Classification returned no result for %s", content_id)
            except asyncio.CancelledError:
                logger.warning("Classification cancelled for %s (shutdown?)", content_id)
                try:
                    await surreal_repo.update_content_classification_status(content_id, "failed")
                except Exception:
                    pass
                raise
            except Exception as e:
                logger.error(
                    "Background classification failed for %s: %s", content_id, e, exc_info=True
                )
                try:
                    await surreal_repo.update_content_classification_status(content_id, "failed")
                except Exception as inner_e:
                    logger.error(
                        "Failed to mark classification as failed for %s: %s",
                        content_id,
                        inner_e,
                    )

        task = asyncio.create_task(_classify_background())
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

    return YouTubeIngestResponse(
        id=content_id,
        video_id=video_id,
        title=f"YouTube: {video_id}",
        transcript_length=len(body.transcript_text),
        chunks_created=chunks_created,
        file_path=transcript_path,
        classification_status=classification_status,
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


@router.get("/{video_id}", response_model=YouTubeVideoInfo)
async def get_video(
    video_id: str,
    key_id: AuthenticatedKeyId,
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
    minio_storage: MinIOStorage = Depends(get_minio_storage),
):
    """Get information about an ingested YouTube video."""
    # Find content by video_id in metadata
    items, _ = await surreal_repo.list_content(content_type="youtube")

    for item in items:
        if item.metadata and item.metadata.get("video_id") == video_id:
            # Get chunk count
            chunks = await surreal_repo.get_chunks(item.id or "")

            # Get transcript preview
            try:
                content = await minio_storage.download(item.file_path)
                preview = content.decode("utf-8")[:500] + "..."
            except Exception:
                preview = "(transcript unavailable)"

            return YouTubeVideoInfo(
                id=item.id or "",
                video_id=video_id,
                title=item.title,
                transcript_preview=preview,
                chunk_count=len(chunks),
            )

    return YouTubeVideoInfo(
        id="",
        video_id=video_id,
        title=None,
        transcript_preview="Video not found",
        chunk_count=0,
    )


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
