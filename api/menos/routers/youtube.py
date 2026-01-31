"""YouTube ingestion endpoints."""

import io
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from menos.auth.dependencies import AuthenticatedKeyId
from menos.models import ChunkModel, ContentMetadata
from menos.services.chunking import ChunkingService
from menos.services.di import get_minio_storage, get_surreal_repo
from menos.services.embeddings import EmbeddingService, get_embedding_service
from menos.services.storage import MinIOStorage, SurrealDBRepository
from menos.services.youtube import YouTubeService, get_youtube_service

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


class YouTubeVideoInfo(BaseModel):
    """Video information response."""

    id: str
    video_id: str
    title: str | None
    transcript_preview: str
    chunk_count: int


@router.post("/ingest", response_model=YouTubeIngestResponse)
async def ingest_video(
    body: YouTubeIngestRequest,
    key_id: AuthenticatedKeyId,
    youtube_service: YouTubeService = Depends(get_youtube_service),
    minio_storage: MinIOStorage = Depends(get_minio_storage),
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
):
    """Ingest a YouTube video transcript.

    Fetches the transcript, stores it in MinIO, saves metadata to SurrealDB,
    and optionally generates embeddings for search.
    """
    # Extract video ID and fetch transcript
    video_id = youtube_service.extract_video_id(body.url)
    transcript = youtube_service.fetch_transcript(video_id)

    # Prepare file paths
    timestamped_content = transcript.timestamped_text
    file_path = f"youtube/{video_id}/transcript.txt"
    metadata_path = f"youtube/{video_id}/metadata.json"

    # Upload transcript to MinIO
    file_data = io.BytesIO(timestamped_content.encode("utf-8"))
    file_size = await minio_storage.upload(file_path, file_data, "text/plain")

    # Create metadata in SurrealDB
    metadata = ContentMetadata(
        content_type="youtube",
        title=f"YouTube: {video_id}",
        mime_type="text/plain",
        file_size=file_size,
        file_path=file_path,
        author=key_id,
        metadata={
            "video_id": video_id,
            "language": transcript.language,
            "segment_count": len(transcript.segments),
        },
    )
    created = await surreal_repo.create_content(metadata)
    content_id = created.id or video_id

    # Save metadata.json to MinIO
    metadata_dict = {
        "id": content_id,
        "video_id": video_id,
        "title": metadata.title,
        "language": transcript.language,
        "segment_count": len(transcript.segments),
        "transcript_length": len(transcript.full_text),
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

    return YouTubeIngestResponse(
        id=content_id,
        video_id=video_id,
        title=f"YouTube: {video_id}",
        transcript_length=len(transcript.full_text),
        chunks_created=chunks_created,
        file_path=file_path,
    )


@router.post("/upload", response_model=YouTubeIngestResponse)
async def upload_transcript(
    body: YouTubeUploadRequest,
    key_id: AuthenticatedKeyId,
    minio_storage: MinIOStorage = Depends(get_minio_storage),
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
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

    return YouTubeIngestResponse(
        id=content_id,
        video_id=video_id,
        title=f"YouTube: {video_id}",
        transcript_length=len(body.transcript_text),
        chunks_created=chunks_created,
        file_path=transcript_path,
    )


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
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
):
    """List all ingested YouTube videos."""
    items, _ = await surreal_repo.list_content(content_type="youtube", limit=limit)

    videos = []
    for item in items:
        video_id = item.metadata.get("video_id", "") if item.metadata else ""
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
