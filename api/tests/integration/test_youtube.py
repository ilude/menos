"""Integration tests for YouTube API endpoints."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from menos.models import ContentMetadata


class TestYouTubeChannelFiltering:
    """Tests for YouTube channel filtering."""

    def test_list_videos_without_channel_filter(self, authed_client, mock_surreal_repo):
        """Test listing videos without channel filter returns all videos."""
        video1 = ContentMetadata(
            id="content1",
            content_type="youtube",
            title="Video 1",
            mime_type="text/plain",
            file_size=1000,
            file_path="youtube/vid1/transcript.txt",
            author="test_user",
            metadata={
                "video_id": "vid1",
                "channel_id": "channel_a",
                "channel_title": "Channel A",
            },
            created_at=datetime.now(UTC),
        )
        video2 = ContentMetadata(
            id="content2",
            content_type="youtube",
            title="Video 2",
            mime_type="text/plain",
            file_size=2000,
            file_path="youtube/vid2/transcript.txt",
            author="test_user",
            metadata={
                "video_id": "vid2",
                "channel_id": "channel_b",
                "channel_title": "Channel B",
            },
            created_at=datetime.now(UTC),
        )

        mock_surreal_repo.list_content = AsyncMock(return_value=([video1, video2], 2))
        mock_surreal_repo.get_chunks = AsyncMock(return_value=[])

        response = authed_client.get("/api/v1/youtube")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["video_id"] == "vid1"
        assert data[1]["video_id"] == "vid2"

    def test_list_videos_with_channel_filter(self, client, request_signer, mock_surreal_repo):
        """Test listing videos filtered by channel_id."""
        video1 = ContentMetadata(
            id="content1",
            content_type="youtube",
            title="Video 1",
            mime_type="text/plain",
            file_size=1000,
            file_path="youtube/vid1/transcript.txt",
            author="test_user",
            metadata={
                "video_id": "vid1",
                "channel_id": "channel_a",
                "channel_title": "Channel A",
            },
            created_at=datetime.now(UTC),
        )
        video2 = ContentMetadata(
            id="content2",
            content_type="youtube",
            title="Video 2",
            mime_type="text/plain",
            file_size=2000,
            file_path="youtube/vid2/transcript.txt",
            author="test_user",
            metadata={
                "video_id": "vid2",
                "channel_id": "channel_b",
                "channel_title": "Channel B",
            },
            created_at=datetime.now(UTC),
        )

        mock_surreal_repo.list_content = AsyncMock(return_value=([video1, video2], 2))
        mock_surreal_repo.get_chunks = AsyncMock(return_value=[])

        # Sign path WITH query params to match server verification
        path = "/api/v1/youtube"
        full_path = path + "?channel_id=channel_a"
        headers = request_signer.sign_request("GET", full_path, host="testserver")
        response = client.get(full_path, headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["video_id"] == "vid1"

    def test_list_videos_with_nonexistent_channel(self, client, request_signer, mock_surreal_repo):
        """Test filtering by non-existent channel returns empty list."""
        video1 = ContentMetadata(
            id="content1",
            content_type="youtube",
            title="Video 1",
            mime_type="text/plain",
            file_size=1000,
            file_path="youtube/vid1/transcript.txt",
            author="test_user",
            metadata={
                "video_id": "vid1",
                "channel_id": "channel_a",
                "channel_title": "Channel A",
            },
            created_at=datetime.now(UTC),
        )

        mock_surreal_repo.list_content = AsyncMock(return_value=([video1], 1))
        mock_surreal_repo.get_chunks = AsyncMock(return_value=[])

        path = "/api/v1/youtube"
        full_path = path + "?channel_id=nonexistent"
        headers = request_signer.sign_request("GET", full_path, host="testserver")
        response = client.get(full_path, headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0

    def test_list_videos_requires_auth(self, client):
        """Test that list videos requires authentication."""
        response = client.get("/api/v1/youtube")

        assert response.status_code == 401


class TestYouTubeChannelsEndpoint:
    """Tests for YouTube channels listing endpoint."""

    def test_list_channels_returns_all_channels(self, authed_client, mock_surreal_repo):
        """Test listing channels returns all unique channels with counts."""
        video1 = ContentMetadata(
            id="content1",
            content_type="youtube",
            title="Video 1",
            mime_type="text/plain",
            file_size=1000,
            file_path="youtube/vid1/transcript.txt",
            author="test_user",
            metadata={
                "video_id": "vid1",
                "channel_id": "channel_a",
                "channel_title": "Channel A",
            },
            created_at=datetime.now(UTC),
        )
        video2 = ContentMetadata(
            id="content2",
            content_type="youtube",
            title="Video 2",
            mime_type="text/plain",
            file_size=2000,
            file_path="youtube/vid2/transcript.txt",
            author="test_user",
            metadata={
                "video_id": "vid2",
                "channel_id": "channel_a",
                "channel_title": "Channel A",
            },
            created_at=datetime.now(UTC),
        )
        video3 = ContentMetadata(
            id="content3",
            content_type="youtube",
            title="Video 3",
            mime_type="text/plain",
            file_size=3000,
            file_path="youtube/vid3/transcript.txt",
            author="test_user",
            metadata={
                "video_id": "vid3",
                "channel_id": "channel_b",
                "channel_title": "Channel B",
            },
            created_at=datetime.now(UTC),
        )

        mock_surreal_repo.list_content = AsyncMock(return_value=([video1, video2, video3], 3))

        response = authed_client.get("/api/v1/youtube/channels")

        assert response.status_code == 200
        data = response.json()
        assert "channels" in data
        assert len(data["channels"]) == 2

        channels = data["channels"]
        assert channels[0]["channel_id"] == "channel_a"
        assert channels[0]["channel_title"] == "Channel A"
        assert channels[0]["video_count"] == 2

        assert channels[1]["channel_id"] == "channel_b"
        assert channels[1]["channel_title"] == "Channel B"
        assert channels[1]["video_count"] == 1

    def test_list_channels_sorts_by_video_count_desc(self, authed_client, mock_surreal_repo):
        """Test that channels are sorted by video count in descending order."""
        video1 = ContentMetadata(
            id="content1",
            content_type="youtube",
            title="Video 1",
            mime_type="text/plain",
            file_size=1000,
            file_path="youtube/vid1/transcript.txt",
            author="test_user",
            metadata={
                "video_id": "vid1",
                "channel_id": "channel_a",
                "channel_title": "Channel A",
            },
            created_at=datetime.now(UTC),
        )
        video2 = ContentMetadata(
            id="content2",
            content_type="youtube",
            title="Video 2",
            mime_type="text/plain",
            file_size=2000,
            file_path="youtube/vid2/transcript.txt",
            author="test_user",
            metadata={
                "video_id": "vid2",
                "channel_id": "channel_b",
                "channel_title": "Channel B",
            },
            created_at=datetime.now(UTC),
        )
        video3 = ContentMetadata(
            id="content3",
            content_type="youtube",
            title="Video 3",
            mime_type="text/plain",
            file_size=3000,
            file_path="youtube/vid3/transcript.txt",
            author="test_user",
            metadata={
                "video_id": "vid3",
                "channel_id": "channel_b",
                "channel_title": "Channel B",
            },
            created_at=datetime.now(UTC),
        )
        video4 = ContentMetadata(
            id="content4",
            content_type="youtube",
            title="Video 4",
            mime_type="text/plain",
            file_size=4000,
            file_path="youtube/vid4/transcript.txt",
            author="test_user",
            metadata={
                "video_id": "vid4",
                "channel_id": "channel_b",
                "channel_title": "Channel B",
            },
            created_at=datetime.now(UTC),
        )

        mock_surreal_repo.list_content = AsyncMock(
            return_value=([video1, video2, video3, video4], 4)
        )

        response = authed_client.get("/api/v1/youtube/channels")

        assert response.status_code == 200
        data = response.json()
        channels = data["channels"]

        assert channels[0]["channel_id"] == "channel_b"
        assert channels[0]["video_count"] == 3
        assert channels[1]["channel_id"] == "channel_a"
        assert channels[1]["video_count"] == 1

    def test_list_channels_skips_videos_without_channel_id(self, authed_client, mock_surreal_repo):
        """Test that videos without channel_id are skipped in channel listing."""
        video1 = ContentMetadata(
            id="content1",
            content_type="youtube",
            title="Video 1",
            mime_type="text/plain",
            file_size=1000,
            file_path="youtube/vid1/transcript.txt",
            author="test_user",
            metadata={
                "video_id": "vid1",
                "channel_id": "channel_a",
                "channel_title": "Channel A",
            },
            created_at=datetime.now(UTC),
        )
        video2 = ContentMetadata(
            id="content2",
            content_type="youtube",
            title="Video 2",
            mime_type="text/plain",
            file_size=2000,
            file_path="youtube/vid2/transcript.txt",
            author="test_user",
            metadata={
                "video_id": "vid2",
            },
            created_at=datetime.now(UTC),
        )

        mock_surreal_repo.list_content = AsyncMock(return_value=([video1, video2], 2))

        response = authed_client.get("/api/v1/youtube/channels")

        assert response.status_code == 200
        data = response.json()
        assert len(data["channels"]) == 1
        assert data["channels"][0]["channel_id"] == "channel_a"

    def test_list_channels_requires_auth(self, client):
        """Test that list channels endpoint requires authentication."""
        response = client.get("/api/v1/youtube/channels")

        assert response.status_code == 401

    def test_list_channels_empty_list(self, authed_client, mock_surreal_repo):
        """Test listing channels when no videos exist."""
        mock_surreal_repo.list_content = AsyncMock(return_value=([], 0))

        response = authed_client.get("/api/v1/youtube/channels")

        assert response.status_code == 200
        data = response.json()
        assert data["channels"] == []

    def test_list_channels_handles_missing_metadata(self, authed_client, mock_surreal_repo):
        """Test listing channels handles videos with empty metadata."""
        video1 = ContentMetadata(
            id="content1",
            content_type="youtube",
            title="Video 1",
            mime_type="text/plain",
            file_size=1000,
            file_path="youtube/vid1/transcript.txt",
            author="test_user",
            metadata={},
            created_at=datetime.now(UTC),
        )

        mock_surreal_repo.list_content = AsyncMock(return_value=([video1], 1))

        response = authed_client.get("/api/v1/youtube/channels")

        assert response.status_code == 200
        data = response.json()
        assert data["channels"] == []
