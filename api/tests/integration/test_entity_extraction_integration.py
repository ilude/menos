"""Integration tests for pipeline orchestrator wiring into ingest routes."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from menos.models import ContentMetadata, PipelineJob


class TestYouTubeIngestPipelineIntegration:
    """End-to-end mock test verifying ingest calls pipeline orchestrator."""

    def test_ingest_video_submits_to_pipeline_orchestrator(
        self,
        authed_client,
        mock_surreal_repo,
        mock_youtube_service,
        mock_metadata_service,
        mock_minio_storage,
        mock_embedding_service,
        mock_pipeline_orchestrator,
    ):
        """Full chain: ingest -> orchestrator.submit called with correct args."""
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

        submitted_job = PipelineJob(
            id="pipeline-job-1",
            resource_key="yt:integration_vid",
            content_id="int_content1",
        )
        mock_pipeline_orchestrator.submit = AsyncMock(return_value=submitted_job)

        response = authed_client.post(
            "/api/v1/youtube/ingest",
            json={"url": "https://www.youtube.com/watch?v=integration_vid"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["video_id"] == "integration_vid"
        assert data["job_id"] == "pipeline-job-1"

        # Verify orchestrator was called with correct args
        mock_pipeline_orchestrator.submit.assert_called_once_with(
            "int_content1",
            mock_transcript.full_text,
            "youtube",
            "RAG Tutorial",
            "yt:integration_vid",
        )
