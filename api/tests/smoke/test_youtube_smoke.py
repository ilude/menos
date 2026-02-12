"""Smoke tests for YouTube endpoints."""

import pytest


@pytest.mark.smoke
class TestYouTubeSmoke:
    """Smoke tests for YouTube endpoints."""

    def test_youtube_list_requires_auth(self, smoke_http_client):
        """GET /api/v1/youtube returns 401 without auth."""
        response = smoke_http_client.get("/api/v1/youtube")
        assert response.status_code == 401

    def test_youtube_list_returns_list(self, smoke_authed_get):
        """GET /api/v1/youtube returns a list with valid auth."""
        response = smoke_authed_get("/api/v1/youtube")
        assert response.status_code == 200

        videos = response.json()
        assert isinstance(videos, list)

    def test_youtube_list_item_structure(self, smoke_authed_get):
        """GET /api/v1/youtube items have expected structure."""
        response = smoke_authed_get("/api/v1/youtube")
        assert response.status_code == 200

        videos = response.json()
        if videos:
            first = videos[0]
            assert isinstance(first["id"], str)
            assert isinstance(first["video_id"], str)
            assert isinstance(first["title"], str)
            assert isinstance(first["chunk_count"], int)

    def test_youtube_get_video(self, smoke_authed_get, smoke_first_youtube_video_id):
        """GET /api/v1/youtube/{video_id} returns video details."""
        response = smoke_authed_get(f"/api/v1/youtube/{smoke_first_youtube_video_id}")
        assert response.status_code == 200

        video = response.json()
        assert isinstance(video["video_id"], str)
        assert isinstance(video["content_id"], str)
        assert isinstance(video["chunk_count"], int)
        # Pipeline fields may be None if not yet processed
        assert "transcript" in video
        assert "summary" in video
        assert "quality_tier" in video

    def test_youtube_get_transcript(self, smoke_authed_get, smoke_first_youtube_video_id):
        """GET /api/v1/youtube/{video_id}/transcript returns plain text."""
        response = smoke_authed_get(
            f"/api/v1/youtube/{smoke_first_youtube_video_id}/transcript"
        )
        assert response.status_code == 200
        assert "text/plain" in response.headers.get("content-type", "")
        assert len(response.text) > 0

    def test_youtube_get_video_not_found(self, smoke_authed_get):
        """GET /api/v1/youtube/{video_id} returns 404 for unknown video."""
        response = smoke_authed_get("/api/v1/youtube/NONEXISTENT99")
        assert response.status_code == 404

    def test_youtube_channels(self, smoke_authed_get):
        """GET /api/v1/youtube/channels returns channels list."""
        response = smoke_authed_get("/api/v1/youtube/channels")
        assert response.status_code == 200

        data = response.json()
        assert "channels" in data
        assert isinstance(data["channels"], list)

    def test_youtube_channels_item_structure(self, smoke_authed_get):
        """GET /api/v1/youtube/channels items have expected structure."""
        response = smoke_authed_get("/api/v1/youtube/channels")
        assert response.status_code == 200

        data = response.json()
        channels = data["channels"]
        if channels:
            first = channels[0]
            assert isinstance(first["channel_id"], str)
            assert isinstance(first["channel_title"], str)
            assert isinstance(first["video_count"], int)
