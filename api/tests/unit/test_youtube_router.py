"""Unit tests for YouTube router endpoints."""

import json

import pytest

from menos.models import ContentMetadata


@pytest.fixture
def video_content():
    """Content record with full unified_result metadata."""
    return ContentMetadata(
        id="test-content-1",
        content_type="youtube",
        title="Test Video",
        mime_type="text/plain",
        file_size=1000,
        file_path="youtube/test_vid/transcript.txt",
        metadata={
            "video_id": "test_vid",
            "channel_id": "UC123",
            "channel_title": "Test Channel",
            "duration_seconds": 600,
            "published_at": "2025-01-15T00:00:00Z",
            "view_count": 5000,
            "like_count": 200,
            "processing_status": "completed",
            "description_urls": ["https://example.com"],
            "unified_result": {
                "summary": "A test summary",
                "tags": ["python", "testing"],
                "tier": "A",
                "quality_score": 85,
                "topics": [
                    {
                        "name": "Python",
                        "entity_type": "topic",
                        "confidence": "high",
                        "edge_type": "discusses",
                    }
                ],
                "additional_entities": [
                    {
                        "name": "pytest",
                        "entity_type": "tool",
                        "confidence": "high",
                        "edge_type": "uses",
                    }
                ],
            },
        },
    )


@pytest.fixture
def bare_video_content():
    """Content record with no pipeline results yet."""
    return ContentMetadata(
        id="test-content-2",
        content_type="youtube",
        title="New Video",
        mime_type="text/plain",
        file_size=500,
        file_path="youtube/new_vid/transcript.txt",
        metadata={
            "video_id": "new_vid",
            "channel_id": "UC456",
            "channel_title": "Other Channel",
        },
    )


class TestGetVideoDetail:
    def test_happy_path(
        self, authed_client, mock_surreal_repo, mock_minio_storage, video_content
    ):
        mock_surreal_repo.list_content.return_value = ([video_content], 1)
        mock_surreal_repo.get_chunks.return_value = [
            {"id": "c1"},
            {"id": "c2"},
        ]
        mock_minio_storage.download.return_value = b"full transcript text"

        resp = authed_client.get("/api/v1/youtube/test_vid")

        assert resp.status_code == 200
        data = resp.json()
        assert data["video_id"] == "test_vid"
        assert data["content_id"] == "test-content-1"
        assert data["title"] == "Test Video"
        assert data["channel_title"] == "Test Channel"
        assert data["channel_id"] == "UC123"
        assert data["duration_seconds"] == 600
        assert data["published_at"] == "2025-01-15T00:00:00Z"
        assert data["view_count"] == 5000
        assert data["like_count"] == 200
        assert data["transcript"] == "full transcript text"
        assert data["summary"] == "A test summary"
        assert data["tags"] == ["python", "testing"]
        assert data["topics"] == ["Python"]
        assert data["entities"] == ["pytest"]
        assert data["quality_tier"] == "A"
        assert data["quality_score"] == 85
        assert data["description_urls"] == ["https://example.com"]
        assert data["chunk_count"] == 2
        assert data["processing_status"] == "completed"

    def test_not_found(self, authed_client, mock_surreal_repo):
        mock_surreal_repo.list_content.return_value = ([], 0)

        resp = authed_client.get("/api/v1/youtube/nonexistent")

        assert resp.status_code == 404

    def test_no_pipeline_results(
        self,
        authed_client,
        mock_surreal_repo,
        mock_minio_storage,
        bare_video_content,
    ):
        mock_surreal_repo.list_content.return_value = (
            [bare_video_content],
            1,
        )
        mock_surreal_repo.get_chunks.return_value = []
        mock_minio_storage.download.return_value = b"raw transcript"

        resp = authed_client.get("/api/v1/youtube/new_vid")

        assert resp.status_code == 200
        data = resp.json()
        assert data["video_id"] == "new_vid"
        assert data["title"] == "New Video"
        assert data["summary"] is None
        assert data["tags"] == []
        assert data["topics"] == []
        assert data["entities"] == []
        assert data["quality_tier"] is None
        assert data["quality_score"] is None
        assert data["description_urls"] == []
        assert data["chunk_count"] == 0
        assert data["processing_status"] is None

    def test_description_urls_from_minio_fallback(
        self,
        authed_client,
        mock_surreal_repo,
        mock_minio_storage,
    ):
        """When metadata has no description_urls, fall back to MinIO metadata.json."""
        content = ContentMetadata(
            id="test-content-3",
            content_type="youtube",
            title="Fallback Video",
            mime_type="text/plain",
            file_size=500,
            file_path="youtube/fb_vid/transcript.txt",
            metadata={"video_id": "fb_vid"},
        )
        mock_surreal_repo.list_content.return_value = ([content], 1)
        mock_surreal_repo.get_chunks.return_value = []

        minio_meta = json.dumps(
            {"description_urls": ["https://fallback.com"]}
        ).encode()

        def download_side_effect(path):
            if path.endswith("metadata.json"):
                return minio_meta
            return b"transcript"

        mock_minio_storage.download.side_effect = download_side_effect

        resp = authed_client.get("/api/v1/youtube/fb_vid")

        assert resp.status_code == 200
        data = resp.json()
        assert data["description_urls"] == ["https://fallback.com"]


class TestGetVideoTranscript:
    def test_returns_plain_text(
        self, authed_client, mock_surreal_repo, mock_minio_storage, video_content
    ):
        mock_surreal_repo.list_content.return_value = ([video_content], 1)
        mock_minio_storage.download.return_value = b"full transcript text"

        resp = authed_client.get("/api/v1/youtube/test_vid/transcript")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/plain; charset=utf-8"
        assert resp.text == "full transcript text"

    def test_not_found(self, authed_client, mock_surreal_repo):
        mock_surreal_repo.list_content.return_value = ([], 0)

        resp = authed_client.get("/api/v1/youtube/nonexistent/transcript")

        assert resp.status_code == 404

    def test_transcript_file_missing(
        self, authed_client, mock_surreal_repo, mock_minio_storage, video_content
    ):
        mock_surreal_repo.list_content.return_value = ([video_content], 1)
        mock_minio_storage.download.side_effect = Exception("Not found")

        resp = authed_client.get("/api/v1/youtube/test_vid/transcript")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Transcript not found"
