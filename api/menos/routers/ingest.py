"""Unified URL ingestion endpoint."""

import hashlib
import io
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
    minio_storage: MinIOStorage,
    surreal_repo: SurrealDBRepository,
    orchestrator: PipelineOrchestrator,
    detected_video_id: str,
) -> IngestResponse:
    video_id = detected_video_id or youtube_service.extract_video_id(url)
    resource_key = generate_resource_key("youtube", video_id)

    existing = await surreal_repo.find_content_by_resource_key(resource_key)
    if existing and existing.id:
        return IngestResponse(
            content_id=existing.id,
            content_type=existing.content_type,
            title=existing.title or f"YouTube: {video_id}",
            job_id=None,
        )

    transcript = youtube_service.fetch_transcript(video_id)
    transcript_text = transcript.full_text
    file_path = f"youtube/{video_id}/transcript.txt"

    file_size = await minio_storage.upload(
        file_path,
        io.BytesIO(transcript.timestamped_text.encode("utf-8")),
        "text/plain",
    )

    title = f"YouTube: {video_id}"
    metadata = ContentMetadata(
        content_type="youtube",
        title=title,
        mime_type="text/plain",
        file_size=file_size,
        file_path=file_path,
        author=key_id,
        metadata={
            "video_id": video_id,
            "language": transcript.language,
            "segment_count": len(transcript.segments),
            "resource_key": resource_key,
        },
    )
    created = await surreal_repo.create_content(metadata)
    content_id = created.id or video_id

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
