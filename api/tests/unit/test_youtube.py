"""Unit tests for YouTube service."""

import pytest

from menos.services.youtube import TranscriptSegment, YouTubeService, YouTubeTranscript


class TestYouTubeService:
    """Tests for YouTube transcript service."""

    def test_extract_video_id_from_watch_url(self):
        """Test extracting ID from standard watch URL."""
        service = YouTubeService()
        url = "https://www.youtube.com/watch?v=RpvQH0r0ecM"

        result = service.extract_video_id(url)

        assert result == "RpvQH0r0ecM"

    def test_extract_video_id_from_short_url(self):
        """Test extracting ID from youtu.be short URL."""
        service = YouTubeService()
        url = "https://youtu.be/RpvQH0r0ecM"

        result = service.extract_video_id(url)

        assert result == "RpvQH0r0ecM"

    def test_extract_video_id_from_embed_url(self):
        """Test extracting ID from embed URL."""
        service = YouTubeService()
        url = "https://www.youtube.com/embed/RpvQH0r0ecM"

        result = service.extract_video_id(url)

        assert result == "RpvQH0r0ecM"

    def test_extract_video_id_raw_id(self):
        """Test with raw video ID."""
        service = YouTubeService()
        video_id = "RpvQH0r0ecM"

        result = service.extract_video_id(video_id)

        assert result == "RpvQH0r0ecM"

    def test_extract_video_id_with_params(self):
        """Test extracting ID from URL with extra parameters."""
        service = YouTubeService()
        url = "https://www.youtube.com/watch?v=RpvQH0r0ecM&t=123&list=xyz"

        result = service.extract_video_id(url)

        assert result == "RpvQH0r0ecM"

    def test_extract_video_id_invalid(self):
        """Test with invalid URL raises error."""
        service = YouTubeService()

        with pytest.raises(ValueError, match="Could not extract"):
            service.extract_video_id("not-a-valid-url")


class TestYouTubeTranscript:
    """Tests for YouTubeTranscript dataclass."""

    def test_full_text(self):
        """Test full_text property."""
        transcript = YouTubeTranscript(
            video_id="test",
            segments=[
                TranscriptSegment(text="Hello", start=0.0, duration=1.0),
                TranscriptSegment(text="world", start=1.0, duration=1.0),
            ],
            language="en",
        )

        assert transcript.full_text == "Hello world"

    def test_timestamped_text(self):
        """Test timestamped_text property."""
        transcript = YouTubeTranscript(
            video_id="test",
            segments=[
                TranscriptSegment(text="Hello", start=0.0, duration=1.0),
                TranscriptSegment(text="world", start=65.5, duration=1.0),
            ],
            language="en",
        )

        result = transcript.timestamped_text

        assert "[00:00] Hello" in result
        assert "[01:05] world" in result
