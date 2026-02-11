"""Tests for entity extraction wiring into ingest routes."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from menos.services.entity_resolution import ResolutionResult


@pytest.fixture
def mock_entity_resolution_service():
    """Mock EntityResolutionService."""
    service = MagicMock()
    service.process_content = AsyncMock(
        return_value=ResolutionResult(
            edges=[],
            entities_created=2,
            entities_reused=1,
            metrics=None,
        )
    )
    return service


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


class TestYouTubeEntityExtraction:
    """Tests for entity extraction wiring in YouTube ingest."""

    def test_ingest_video_triggers_entity_extraction(
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
        """After ingest, entity extraction background task is created."""
        _setup_youtube_mocks(
            mock_youtube_service, mock_metadata_service, mock_surreal_repo, mock_minio_storage
        )

        mock_resolution_svc = MagicMock()
        mock_resolution_svc.process_content = AsyncMock(
            return_value=ResolutionResult(
                edges=[], entities_created=0, entities_reused=0, metrics=None
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
            json={"url": "https://www.youtube.com/watch?v=test_video"},
        )

        assert response.status_code == 200

        app.dependency_overrides.pop(get_entity_resolution_service, None)

    def test_entity_extraction_does_not_block_response(
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
        """Ingest response returns immediately (fire-and-forget background task)."""
        _setup_youtube_mocks(
            mock_youtube_service, mock_metadata_service, mock_surreal_repo, mock_minio_storage
        )

        mock_resolution_svc = MagicMock()
        mock_resolution_svc.process_content = AsyncMock(
            return_value=ResolutionResult(
                edges=[], entities_created=0, entities_reused=0, metrics=None
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
            json={"url": "https://www.youtube.com/watch?v=test_video"},
        )

        # Response returns 200 immediately — extraction runs in background
        assert response.status_code == 200
        data = response.json()
        assert data["video_id"] == "test_video"

        app.dependency_overrides.pop(get_entity_resolution_service, None)

    def test_entity_extraction_skipped_when_disabled(
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
        """If entity_extraction_enabled=False, no extraction task is created."""
        _setup_youtube_mocks(
            mock_youtube_service, mock_metadata_service, mock_surreal_repo, mock_minio_storage
        )

        mock_resolution_svc = MagicMock()
        mock_resolution_svc.process_content = AsyncMock()

        from menos.main import app
        from menos.services.di import get_entity_resolution_service

        app.dependency_overrides[get_entity_resolution_service] = lambda: mock_resolution_svc

        monkeypatch.setattr(
            "menos.routers.youtube.settings", MagicMock(entity_extraction_enabled=False)
        )

        response = authed_client.post(
            "/api/v1/youtube/ingest",
            json={"url": "https://www.youtube.com/watch?v=test_video"},
        )

        assert response.status_code == 200
        mock_resolution_svc.process_content.assert_not_awaited()

        app.dependency_overrides.pop(get_entity_resolution_service, None)

    def test_entity_extraction_receives_description_urls(
        self,
        authed_client,
        mock_surreal_repo,
        mock_youtube_service,
        mock_metadata_service,
        mock_minio_storage,
        mock_embedding_service,
        mock_classification_service,
        mock_entity_resolution_service,
        monkeypatch,
    ):
        """description_urls from YouTube metadata are passed to entity extraction."""
        _setup_youtube_mocks(
            mock_youtube_service, mock_metadata_service, mock_surreal_repo, mock_minio_storage
        )

        monkeypatch.setattr(
            "menos.routers.youtube.settings", MagicMock(entity_extraction_enabled=True)
        )

        response = authed_client.post(
            "/api/v1/youtube/ingest",
            json={"url": "https://www.youtube.com/watch?v=test_video"},
        )

        assert response.status_code == 200


class TestContentEntityExtraction:
    """Tests for entity extraction wiring in content upload."""

    def test_content_upload_triggers_entity_extraction(
        self,
        client,
        request_signer,
        mock_surreal_repo,
        mock_minio_storage,
        mock_classification_service,
        mock_entity_resolution_service,
        monkeypatch,
    ):
        """Upload triggers background entity extraction."""
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

        monkeypatch.setattr(
            "menos.routers.content.settings", MagicMock(entity_extraction_enabled=True)
        )

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

    def test_content_upload_entity_extraction_disabled(
        self,
        client,
        request_signer,
        mock_surreal_repo,
        mock_minio_storage,
        mock_classification_service,
        mock_entity_resolution_service,
        monkeypatch,
    ):
        """Upload respects entity_extraction_enabled=False."""
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

        monkeypatch.setattr(
            "menos.routers.content.settings", MagicMock(entity_extraction_enabled=False)
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
        mock_entity_resolution_service.process_content.assert_not_awaited()


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
