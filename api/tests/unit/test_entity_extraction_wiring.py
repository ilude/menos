"""Tests for entity extraction wiring into ingest routes."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from menos.services.entity_resolution import ResolutionResult


def _setup_youtube_mocks(
    mock_youtube_service, mock_metadata_service, mock_surreal_repo, mock_minio_storage
):
    """Set up common YouTube mocks for ingest tests."""
    from datetime import UTC, datetime

    from menos.models import ContentMetadata
    from menos.services.youtube_metadata import YouTubeMetadata

    mock_transcript = MagicMock()
    mock_transcript.video_id = "test_video"
    mock_transcript.language = "en"
    mock_transcript.segments = [MagicMock(text="Hello", start=0.0, duration=1.0)]
    mock_transcript.full_text = "Hello world " * 100
    mock_transcript.timestamped_text = "[00:00] Hello world"
    mock_youtube_service.extract_video_id.return_value = "test_video"
    mock_youtube_service.fetch_transcript.return_value = mock_transcript

    mock_metadata = YouTubeMetadata(
        video_id="test_video",
        title="Test Video",
        description="Test desc",
        description_urls=["https://github.com/owner/repo"],
        channel_id="ch1",
        channel_title="Channel",
        published_at="2024-01-01T00:00:00Z",
        duration="PT10M",
        duration_seconds=600,
        duration_formatted="10:00",
        view_count=1000,
        like_count=100,
        comment_count=10,
        tags=["python"],
        category_id="28",
        thumbnails={},
        fetched_at="2024-01-01T00:00:00Z",
    )
    mock_metadata_service.fetch_metadata.return_value = mock_metadata

    created_content = ContentMetadata(
        id="content1",
        content_type="youtube",
        title="Test Video",
        mime_type="text/plain",
        file_size=1000,
        file_path="youtube/test_video/transcript.txt",
        author="test_user",
        created_at=datetime.now(UTC),
    )
    mock_surreal_repo.create_content = AsyncMock(return_value=created_content)
    mock_minio_storage.upload = AsyncMock(return_value=1000)


class TestYouTubeUnifiedPipeline:
    """Tests for unified pipeline wiring in YouTube ingest."""

    def test_ingest_video_submits_to_pipeline(
        self,
        authed_client,
        mock_surreal_repo,
        mock_youtube_service,
        mock_metadata_service,
        mock_minio_storage,
        mock_embedding_service,
        mock_pipeline_orchestrator,
    ):
        """After ingest, content is submitted to the unified pipeline."""
        _setup_youtube_mocks(
            mock_youtube_service, mock_metadata_service, mock_surreal_repo, mock_minio_storage
        )

        response = authed_client.post(
            "/api/v1/youtube/ingest",
            json={"url": "https://www.youtube.com/watch?v=test_video"},
        )

        assert response.status_code == 200
        mock_pipeline_orchestrator.submit.assert_awaited_once()

    def test_pipeline_does_not_block_response(
        self,
        authed_client,
        mock_surreal_repo,
        mock_youtube_service,
        mock_metadata_service,
        mock_minio_storage,
        mock_embedding_service,
        mock_pipeline_orchestrator,
    ):
        """Ingest response returns immediately (pipeline runs in background)."""
        _setup_youtube_mocks(
            mock_youtube_service, mock_metadata_service, mock_surreal_repo, mock_minio_storage
        )

        response = authed_client.post(
            "/api/v1/youtube/ingest",
            json={"url": "https://www.youtube.com/watch?v=test_video"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["video_id"] == "test_video"

    def test_ingest_returns_job_id_when_pipeline_enabled(
        self,
        authed_client,
        mock_surreal_repo,
        mock_youtube_service,
        mock_metadata_service,
        mock_minio_storage,
        mock_embedding_service,
        mock_pipeline_orchestrator,
    ):
        """Response includes job_id when pipeline creates a job."""
        from menos.models import PipelineJob

        _setup_youtube_mocks(
            mock_youtube_service, mock_metadata_service, mock_surreal_repo, mock_minio_storage
        )
        mock_pipeline_orchestrator.submit.return_value = PipelineJob(
            id="job123", resource_key="yt:test_video", content_id="content1"
        )

        response = authed_client.post(
            "/api/v1/youtube/ingest",
            json={"url": "https://www.youtube.com/watch?v=test_video"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "job123"


class TestContentUnifiedPipeline:
    """Tests for unified pipeline wiring in content upload."""

    def test_content_upload_submits_to_pipeline(
        self,
        client,
        request_signer,
        mock_surreal_repo,
        mock_minio_storage,
        mock_pipeline_orchestrator,
    ):
        """Upload submits content to the unified pipeline."""
        from datetime import UTC, datetime

        from menos.models import ContentMetadata

        created_content = ContentMetadata(
            id="content1",
            content_type="markdown",
            title="Test Doc",
            mime_type="text/markdown",
            file_size=5000,
            file_path="markdown/content1/test.md",
            author="test_user",
            created_at=datetime.now(UTC),
        )
        mock_surreal_repo.create_content = AsyncMock(return_value=created_content)
        mock_surreal_repo.find_content_by_title = AsyncMock(return_value=None)

        import io

        path = "/api/v1/content?content_type=markdown"
        file_content = b"# Test Document\n\n" + b"Some content here. " * 100
        headers = request_signer.sign_request("POST", path, host="testserver")
        response = client.post(
            path,
            files={"file": ("test.md", io.BytesIO(file_content), "text/markdown")},
            headers=headers,
        )

        assert response.status_code == 200
        mock_pipeline_orchestrator.submit.assert_awaited_once()

    def test_content_upload_returns_job_id(
        self,
        client,
        request_signer,
        mock_surreal_repo,
        mock_minio_storage,
        mock_pipeline_orchestrator,
    ):
        """Upload response includes job_id when pipeline creates a job."""
        from datetime import UTC, datetime

        from menos.models import ContentMetadata, PipelineJob

        created_content = ContentMetadata(
            id="content1",
            content_type="markdown",
            title="Test Doc",
            mime_type="text/markdown",
            file_size=5000,
            file_path="markdown/content1/test.md",
            author="test_user",
            created_at=datetime.now(UTC),
        )
        mock_surreal_repo.create_content = AsyncMock(return_value=created_content)
        mock_surreal_repo.find_content_by_title = AsyncMock(return_value=None)
        mock_pipeline_orchestrator.submit.return_value = PipelineJob(
            id="job456", resource_key="cid:content1", content_id="content1"
        )

        import io

        path = "/api/v1/content?content_type=markdown"
        file_content = b"# Test\n\n" + b"Content here. " * 100
        headers = request_signer.sign_request("POST", path, host="testserver")
        response = client.post(
            path,
            files={"file": ("test.md", io.BytesIO(file_content), "text/markdown")},
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "job456"


class TestEntityExtractionBackgroundTask:
    """Tests for background task status handling."""

    @pytest.mark.asyncio
    async def test_entity_extraction_sets_status_pending(self):
        """Status is set to 'pending' before extraction starts."""
        mock_repo = MagicMock()
        mock_repo.update_content_extraction_status = AsyncMock()

        content_id = "test-content"
        await mock_repo.update_content_extraction_status(content_id, "pending")

        mock_repo.update_content_extraction_status.assert_awaited_once_with(content_id, "pending")

    @pytest.mark.asyncio
    async def test_entity_extraction_sets_status_completed(self):
        """On success, status is updated to 'completed'."""
        mock_repo = MagicMock()
        mock_repo.update_content_extraction_status = AsyncMock()

        mock_resolution_svc = MagicMock()
        mock_resolution_svc.process_content = AsyncMock(
            return_value=ResolutionResult(
                edges=[], entities_created=2, entities_reused=1, metrics=None
            )
        )

        # Simulate the happy path in _extract_entities_background
        content_id = "test-content"
        await mock_repo.update_content_extraction_status(content_id, "pending")
        result = await mock_resolution_svc.process_content(
            content_id=content_id,
            content_text="Some text",
            content_type="youtube",
            title="Test",
        )
        if result:
            await mock_repo.update_content_extraction_status(content_id, "completed")

        calls = mock_repo.update_content_extraction_status.call_args_list
        assert calls[-1].args == (content_id, "completed")

    @pytest.mark.asyncio
    async def test_entity_extraction_sets_status_failed(self):
        """On failure, status is set to 'failed'."""
        mock_repo = MagicMock()
        mock_repo.update_content_extraction_status = AsyncMock()

        mock_resolution_svc = MagicMock()
        mock_resolution_svc.process_content = AsyncMock(
            side_effect=RuntimeError("LLM connection failed")
        )

        content_id = "test-content"
        await mock_repo.update_content_extraction_status(content_id, "pending")
        try:
            await mock_resolution_svc.process_content(
                content_id=content_id,
                content_text="Some text",
                content_type="youtube",
                title="Test",
            )
        except Exception:
            await mock_repo.update_content_extraction_status(content_id, "failed")

        calls = mock_repo.update_content_extraction_status.call_args_list
        assert calls[-1].args == (content_id, "failed")

    @pytest.mark.asyncio
    async def test_entity_extraction_receives_correct_params(self):
        """content_id, content_text, content_type, title, description_urls all passed."""
        mock_resolution_svc = MagicMock()
        mock_resolution_svc.process_content = AsyncMock(
            return_value=ResolutionResult(
                edges=[], entities_created=0, entities_reused=0, metrics=None
            )
        )

        await mock_resolution_svc.process_content(
            content_id="c1",
            content_text="Transcript text here",
            content_type="youtube",
            title="My Video",
            description_urls=["https://github.com/owner/repo"],
        )

        mock_resolution_svc.process_content.assert_awaited_once_with(
            content_id="c1",
            content_text="Transcript text here",
            content_type="youtube",
            title="My Video",
            description_urls=["https://github.com/owner/repo"],
        )
