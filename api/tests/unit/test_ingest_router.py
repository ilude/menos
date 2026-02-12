"""Unit tests for unified ingest router."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from menos.models import ContentMetadata
from menos.routers.ingest import canonicalize_web_url
from menos.services.docling import DoclingResult
from menos.services.url_detector import DetectedURL
from menos.services.youtube import TranscriptSegment, YouTubeTranscript


def _youtube_transcript() -> YouTubeTranscript:
    return YouTubeTranscript(
        video_id="dQw4w9WgXcQ",
        language="en",
        segments=[TranscriptSegment(text="hello", start=0.0, duration=1.0)],
    )


def test_ingest_routes_youtube_urls_to_youtube_flow(
    authed_client,
    mock_surreal_repo,
    mock_youtube_service,
    mock_docling_client,
    mock_pipeline_orchestrator,
):
    mock_youtube_service.fetch_transcript.return_value = _youtube_transcript()
    mock_surreal_repo.create_content.return_value = ContentMetadata(
        id="content-y1",
        content_type="youtube",
        title="YouTube: dQw4w9WgXcQ",
        mime_type="text/plain",
        file_size=100,
        file_path="youtube/dQw4w9WgXcQ/transcript.txt",
    )
    mock_pipeline_orchestrator.submit = AsyncMock(return_value=MagicMock(id="job-y1"))

    response = authed_client.post("/api/v1/ingest", json={"url": "https://youtu.be/dQw4w9WgXcQ"})

    assert response.status_code == 200
    assert response.json() == {
        "content_id": "content-y1",
        "content_type": "youtube",
        "title": "YouTube: dQw4w9WgXcQ",
        "job_id": "job-y1",
    }
    assert mock_docling_client.extract_markdown.await_count == 0


def test_ingest_routes_web_urls_to_docling_flow(
    authed_client,
    mock_surreal_repo,
    mock_docling_client,
    mock_pipeline_orchestrator,
    mock_minio_storage,
):
    url = "https://www.Example.com/article/?b=2&utm_source=x&a=1#section"
    canonical = canonicalize_web_url(url)

    mock_docling_client.extract_markdown = AsyncMock(
        return_value=DoclingResult(markdown="# Web Title\nBody", title="Web Title")
    )
    mock_surreal_repo.create_content.return_value = ContentMetadata(
        id="content-w1",
        content_type="web",
        title="Web Title",
        mime_type="text/markdown",
        file_size=100,
        file_path="web/hash/content.md",
    )
    mock_pipeline_orchestrator.submit = AsyncMock(return_value=MagicMock(id="job-w1"))

    response = authed_client.post("/api/v1/ingest", json={"url": url})

    assert response.status_code == 200
    assert response.json() == {
        "content_id": "content-w1",
        "content_type": "web",
        "title": "Web Title",
        "job_id": "job-w1",
    }
    mock_docling_client.extract_markdown.assert_awaited_once()
    called_url = mock_docling_client.extract_markdown.await_args.args[0]
    assert called_url == "https://www.example.com/article/?b=2&utm_source=x&a=1#section"
    uploaded_path = mock_minio_storage.upload.await_args.args[0]
    assert uploaded_path.endswith("/content.md")
    assert canonical == "https://example.com/article?a=1&b=2"


def test_ingest_unknown_classification_falls_back_to_docling(
    authed_client,
    mock_docling_client,
    mock_surreal_repo,
):
    mock_docling_client.extract_markdown = AsyncMock(
        return_value=DoclingResult(markdown="# Unknown\nBody", title="Unknown")
    )
    mock_surreal_repo.create_content.return_value = ContentMetadata(
        id="content-u1",
        content_type="web",
        title="Unknown",
        mime_type="text/markdown",
        file_size=100,
        file_path="web/hash/content.md",
    )

    with patch(
        "menos.routers.ingest.URLDetector.classify_url",
        return_value=DetectedURL(url="https://example.com", url_type="unknown", extracted_id=""),
    ):
        response = authed_client.post("/api/v1/ingest", json={"url": "https://example.com"})

    assert response.status_code == 200
    assert response.json()["content_type"] == "web"
    assert mock_docling_client.extract_markdown.await_count == 1


def test_ingest_dedupe_returns_existing_content_and_no_enqueue(
    authed_client,
    mock_surreal_repo,
    mock_docling_client,
    mock_pipeline_orchestrator,
):
    mock_surreal_repo.find_content_by_resource_key = AsyncMock(
        return_value=ContentMetadata(
            id="existing-1",
            content_type="web",
            title="Existing",
            mime_type="text/markdown",
            file_size=10,
            file_path="web/existing/content.md",
        )
    )

    response = authed_client.post("/api/v1/ingest", json={"url": "https://example.com/path"})

    assert response.status_code == 200
    assert response.json() == {
        "content_id": "existing-1",
        "content_type": "web",
        "title": "Existing",
        "job_id": None,
    }
    assert mock_docling_client.extract_markdown.await_count == 0
    assert mock_pipeline_orchestrator.submit.await_count == 0


def test_ingest_returns_docling_errors(
    authed_client,
    mock_docling_client,
):
    mock_docling_client.extract_markdown = AsyncMock(
        side_effect=HTTPException(status_code=503, detail="Docling service unavailable")
    )

    response = authed_client.post("/api/v1/ingest", json={"url": "https://example.com/fail"})

    assert response.status_code == 503


def test_ingest_rejects_invalid_url(authed_client):
    response = authed_client.post("/api/v1/ingest", json={"url": "notaurl"})
    assert response.status_code == 422


def test_canonicalization_is_deterministic_and_strips_tracking():
    url_a = "https://WWW.Example.com/path/?b=2&utm_source=abc&A=1&fbclid=123&gBraId=456#frag"
    url_b = "https://example.com/path?A=1&b=2"

    canonical_a = canonicalize_web_url(url_a)
    canonical_b = canonicalize_web_url(url_b)

    assert canonical_a == canonical_b
    assert canonical_a == "https://example.com/path?A=1&b=2"
    assert "utm_source" not in canonical_a
    assert "fbclid" not in canonical_a
    assert "gBraId" not in canonical_a
