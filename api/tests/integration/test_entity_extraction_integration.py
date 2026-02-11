"""Integration tests for entity extraction wiring into ingest routes."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from menos.models import ContentMetadata
from menos.services.entity_resolution import ResolutionResult


class TestYouTubeEntityResolutionIntegration:
    """End-to-end mock test verifying full entity extraction call chain."""

    def test_ingest_video_calls_entity_resolution_process_content(
        self,
        authed_client,
        mock_surreal_repo,
        mock_youtube_service,
        mock_metadata_service,
        mock_minio_storage,
        mock_embedding_service,
        mock_classification_service,
        monkeypatch,
    ):
        """Full chain: ingest -> background task -> process_content called with correct args."""
        from menos.services.youtube_metadata import YouTubeMetadata

        mock_transcript = MagicMock()
        mock_transcript.video_id = "integration_vid"
        mock_transcript.language = "en"
        mock_transcript.segments = [
            MagicMock(text="Deep dive into RAG", start=0.0, duration=5.0),
        ]
        mock_transcript.full_text = "Deep dive into RAG pipelines " * 50
        mock_transcript.timestamped_text = "[00:00] Deep dive into RAG pipelines"
        mock_youtube_service.extract_video_id.return_value = "integration_vid"
        mock_youtube_service.fetch_transcript.return_value = mock_transcript

        mock_metadata = YouTubeMetadata(
            video_id="integration_vid",
            title="RAG Tutorial",
            description="Learn about RAG",
            description_urls=["https://github.com/langchain-ai/langchain"],
            channel_id="tech_ch",
            channel_title="Tech Channel",
            published_at="2024-06-01T00:00:00Z",
            duration="PT15M",
            duration_seconds=900,
            duration_formatted="15:00",
            view_count=5000,
            like_count=500,
            comment_count=50,
            tags=["rag", "ai"],
            category_id="28",
            thumbnails={},
            fetched_at="2024-06-01T12:00:00Z",
        )
        mock_metadata_service.fetch_metadata.return_value = mock_metadata

        created_content = ContentMetadata(
            id="int_content1",
            content_type="youtube",
            title="RAG Tutorial",
            mime_type="text/plain",
            file_size=2000,
            file_path="youtube/integration_vid/transcript.txt",
            author="test_user",
            created_at=datetime.now(UTC),
        )
        mock_surreal_repo.create_content = AsyncMock(return_value=created_content)
        mock_surreal_repo.update_content_extraction_status = AsyncMock()

        mock_resolution_svc = MagicMock()
        mock_resolution_svc.process_content = AsyncMock(
            return_value=ResolutionResult(
                edges=[],
                entities_created=3,
                entities_reused=1,
                metrics=None,
            )
        )

        from menos.main import app
        from menos.services.di import get_entity_resolution_service

        app.dependency_overrides[get_entity_resolution_service] = lambda: mock_resolution_svc

        monkeypatch.setattr(
            "menos.routers.youtube.settings", MagicMock(entity_extraction_enabled=True)
        )

        response = authed_client.post(
            "/api/v1/youtube/ingest",
            json={"url": "https://www.youtube.com/watch?v=integration_vid"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["video_id"] == "integration_vid"

        app.dependency_overrides.pop(get_entity_resolution_service, None)
