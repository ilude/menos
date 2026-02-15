"""Unified URL ingestion endpoint."""

import hashlib
import io
import json
import logging
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fastapi import APIRouter, Depends
from pydantic import AnyHttpUrl, BaseModel

from menos.auth.dependencies import AuthenticatedKeyId
from menos.models import ContentMetadata
from menos.services.di import (
    get_docling_client,
    get_minio_storage,
    get_pipeline_orchestrator,
    get_surreal_repo,
)
from menos.services.docling import DoclingClient
from menos.services.pipeline_orchestrator import PipelineOrchestrator
from menos.services.resource_key import generate_resource_key
from menos.services.storage import MinIOStorage, SurrealDBRepository
from menos.services.url_detector import URLDetector
from menos.services.youtube import YouTubeService, get_youtube_service
from menos.services.youtube_metadata import (
    YouTubeMetadataService,
    get_youtube_metadata_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])

EXPLICIT_TRACKING_PARAMS = {
    "gbraid",
    "wbraid",
    "mc_cid",
    "mc_eid",
    "hsenc",
    "_hsmi",
    "hsctatracking",
}


class IngestRequest(BaseModel):
    """Unified ingest request."""

    url: AnyHttpUrl


class IngestResponse(BaseModel):
    """Unified ingest response."""

    content_id: str
    content_type: str
    title: str
    job_id: str | None = None


@router.post("", response_model=IngestResponse)
async def ingest_url(
    body: IngestRequest,
    key_id: AuthenticatedKeyId,
    docling_client: DoclingClient = Depends(get_docling_client),
    youtube_service: YouTubeService = Depends(get_youtube_service),
    metadata_service: YouTubeMetadataService = Depends(get_youtube_metadata_service),
    minio_storage: MinIOStorage = Depends(get_minio_storage),
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
    orchestrator: PipelineOrchestrator = Depends(get_pipeline_orchestrator),
):
    """Ingest YouTube or web URLs through a single endpoint."""
    raw_url = str(body.url)
    detector = URLDetector()
    detected = detector.classify_url(raw_url)

    if detected.url_type == "youtube":
        return await _ingest_youtube(
            url=raw_url,
            key_id=key_id,
            youtube_service=youtube_service,
            metadata_service=metadata_service,
            minio_storage=minio_storage,
            surreal_repo=surreal_repo,
            orchestrator=orchestrator,
            detected_video_id=detected.extracted_id,
        )

    return await _ingest_web(
        url=raw_url,
        key_id=key_id,
        docling_client=docling_client,
        minio_storage=minio_storage,
        surreal_repo=surreal_repo,
        orchestrator=orchestrator,
    )


async def _ingest_youtube(
    url: str,
    key_id: str,
    youtube_service: YouTubeService,
    metadata_service: YouTubeMetadataService,
    minio_storage: MinIOStorage,
    surreal_repo: SurrealDBRepository,
    orchestrator: PipelineOrchestrator,
    detected_video_id: str,
) -> IngestResponse:
    video_id = detected_video_id or youtube_service.extract_video_id(url)
    resource_key = generate_resource_key("youtube", video_id)

    existing = await surreal_repo.find_content_by_resource_key(resource_key)

    # Check if existing record has complete metadata (non-placeholder title)
    has_placeholder_title = (
        existing and existing.title and existing.title.startswith(f"YouTube: {video_id}")
    )

    # Return early only if record exists AND has real metadata
    if existing and existing.id and not has_placeholder_title:
        return IngestResponse(
            content_id=existing.id,
            content_type=existing.content_type,
            title=existing.title or f"YouTube: {video_id}",
            job_id=None,
        )

    # Handle existing record with incomplete metadata
    if existing and existing.id and has_placeholder_title:
        logger.info("Updating existing record %s with YouTube metadata", existing.id)

        # Get transcript data from existing record
        existing_meta = existing.metadata or {}
        language = existing_meta.get("language", "en")
        segment_count = existing_meta.get("segment_count", 0)

        # Fetch rich metadata from YouTube Data API
        yt_metadata = None
        try:
            yt_metadata = metadata_service.fetch_metadata(video_id)
            logger.info("Fetched metadata for video %s: %s", video_id, yt_metadata.title)
        except Exception as e:
            logger.warning("Failed to fetch YouTube metadata for %s: %s", video_id, e)
            # If metadata fetch fails again, return existing record unchanged
            return IngestResponse(
                content_id=existing.id,
                content_type=existing.content_type,
                title=existing.title or f"YouTube: {video_id}",
                job_id=None,
            )

        # Update title and metadata fields
        title = yt_metadata.title if yt_metadata else f"YouTube: {video_id}"
        updated_metadata = {
            **existing_meta,
            "published_at": yt_metadata.published_at if yt_metadata else None,
            "fetched_at": yt_metadata.fetched_at if yt_metadata else None,
            "channel_id": yt_metadata.channel_id if yt_metadata else None,
            "channel_title": yt_metadata.channel_title if yt_metadata else None,
            "duration_seconds": yt_metadata.duration_seconds if yt_metadata else None,
            "view_count": yt_metadata.view_count if yt_metadata else None,
            "like_count": yt_metadata.like_count if yt_metadata else None,
            "description_urls": yt_metadata.description_urls if yt_metadata else [],
        }

        # Update SurrealDB record (use direct query like refetch script)
        surreal_repo.db.query(
            "UPDATE content SET title = $title, tags = $tags, metadata = $metadata WHERE id = $id",
            {
                "title": title,
                "tags": yt_metadata.tags if yt_metadata else [],
                "metadata": updated_metadata,
                "id": existing.id,
            },
        )
        logger.info("Updated metadata for video %s in database", video_id)

        # Read transcript for metadata.json
        try:
            transcript_bytes = await minio_storage.download(existing.file_path)
            transcript_text = transcript_bytes.decode("utf-8")
        except Exception as e:
            logger.warning("Failed to read transcript for metadata: %s", e)
            transcript_text = ""

        # Update MinIO metadata.json
        metadata_path = f"youtube/{video_id}/metadata.json"
        metadata_dict = {
            "id": existing.id,
            "video_id": video_id,
            "title": title,
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
            "language": language,
            "segment_count": segment_count,
            "transcript_length": len(transcript_text),
            "file_size": existing.file_size,
            "author": existing.author,
            "created_at": existing.created_at.isoformat() if existing.created_at else None,
            "fetched_at": yt_metadata.fetched_at if yt_metadata else None,
        }
        await minio_storage.upload(
            metadata_path,
            io.BytesIO(json.dumps(metadata_dict, indent=2).encode("utf-8")),
            "application/json",
        )

        logger.info("Updated metadata for video %s", video_id)
        return IngestResponse(
            content_id=existing.id,
            content_type="youtube",
            title=title,
            job_id=None,
        )

    # New video ingestion flow
    transcript = youtube_service.fetch_transcript(video_id)
    transcript_text = transcript.full_text
    file_path = f"youtube/{video_id}/transcript.txt"

    file_size = await minio_storage.upload(
        file_path,
        io.BytesIO(transcript.timestamped_text.encode("utf-8")),
        "text/plain",
    )

    # Fetch rich metadata from YouTube Data API
    yt_metadata = None
    try:
        yt_metadata = metadata_service.fetch_metadata(video_id)
        logger.info("Fetched metadata for video %s: %s", video_id, yt_metadata.title)
    except Exception as e:
        logger.warning("Failed to fetch YouTube metadata for %s: %s", video_id, e)

    title = yt_metadata.title if yt_metadata else f"YouTube: {video_id}"
    content_metadata = {
        "video_id": video_id,
        "language": transcript.language,
        "segment_count": len(transcript.segments),
        "resource_key": resource_key,
        "published_at": yt_metadata.published_at if yt_metadata else None,
        "fetched_at": yt_metadata.fetched_at if yt_metadata else None,
        "channel_id": yt_metadata.channel_id if yt_metadata else None,
        "channel_title": yt_metadata.channel_title if yt_metadata else None,
        "duration_seconds": yt_metadata.duration_seconds if yt_metadata else None,
        "view_count": yt_metadata.view_count if yt_metadata else None,
        "like_count": yt_metadata.like_count if yt_metadata else None,
        "description_urls": yt_metadata.description_urls if yt_metadata else [],
    }

    metadata = ContentMetadata(
        content_type="youtube",
        title=title,
        mime_type="text/plain",
        file_size=file_size,
        file_path=file_path,
        author=key_id,
        tags=yt_metadata.tags if yt_metadata else [],
        metadata=content_metadata,
    )
    created = await surreal_repo.create_content(metadata)
    content_id = created.id or video_id

    # Save metadata.json to MinIO
    metadata_path = f"youtube/{video_id}/metadata.json"
    metadata_dict = {
        "id": content_id,
        "video_id": video_id,
        "title": title,
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
        "transcript_length": len(transcript_text),
        "file_size": file_size,
        "author": key_id,
        "created_at": created.created_at.isoformat() if created.created_at else None,
        "fetched_at": yt_metadata.fetched_at if yt_metadata else None,
    }
    await minio_storage.upload(
        metadata_path,
        io.BytesIO(json.dumps(metadata_dict, indent=2).encode("utf-8")),
        "application/json",
    )

    job = await orchestrator.submit(
        content_id,
        transcript_text,
        "youtube",
        title,
        resource_key,
    )

    return IngestResponse(
        content_id=content_id,
        content_type="youtube",
        title=title,
        job_id=job.id if job else None,
    )


async def _ingest_web(
    url: str,
    key_id: str,
    docling_client: DoclingClient,
    minio_storage: MinIOStorage,
    surreal_repo: SurrealDBRepository,
    orchestrator: PipelineOrchestrator,
) -> IngestResponse:
    canonical_url = canonicalize_web_url(url)
    url_hash = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()
    resource_key = f"url:{url_hash}"

    existing = await surreal_repo.find_content_by_resource_key(resource_key)
    if existing and existing.id:
        return IngestResponse(
            content_id=existing.id,
            content_type=existing.content_type,
            title=existing.title or canonical_url,
            job_id=None,
        )

    result = await docling_client.extract_markdown(url)

    file_path = f"web/{url_hash}/content.md"
    file_size = await minio_storage.upload(
        file_path,
        io.BytesIO(result.markdown.encode("utf-8")),
        "text/markdown",
    )

    title = result.title or canonical_url
    metadata = ContentMetadata(
        content_type="web",
        title=title,
        mime_type="text/markdown",
        file_size=file_size,
        file_path=file_path,
        author=key_id,
        metadata={
            "source_url": url,
            "canonical_url": canonical_url,
            "resource_key": resource_key,
        },
    )
    created = await surreal_repo.create_content(metadata)
    content_id = created.id or url_hash

    job = await orchestrator.submit(content_id, result.markdown, "web", title, resource_key)

    return IngestResponse(
        content_id=content_id,
        content_type="web",
        title=title,
        job_id=job.id if job else None,
    )


def canonicalize_web_url(url: str) -> str:
    """Deterministically canonicalize web URLs for dedupe."""
    parsed = urlparse(url)

    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]

    netloc = host
    if parsed.port:
        netloc = f"{host}:{parsed.port}"

    path = parsed.path or ""
    if path not in {"", "/"} and path.endswith("/"):
        path = path.rstrip("/")

    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    filtered = [item for item in query_items if not _is_tracking_param(item[0])]
    filtered.sort(key=lambda item: (item[0], item[1]))
    query = urlencode(filtered, doseq=True)

    return urlunparse((parsed.scheme, netloc, path, "", query, ""))


def _is_tracking_param(key: str) -> bool:
    lowered = key.lower()
    if lowered.startswith("utm_"):
        return True
    if lowered.endswith("clid"):
        return True
    return lowered in EXPLICIT_TRACKING_PARAMS
