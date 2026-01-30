"""YouTube transcript fetching service."""

import re
from dataclasses import dataclass

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)


@dataclass
class TranscriptSegment:
    """A segment of transcript with timing."""

    text: str
    start: float
    duration: float


@dataclass
class YouTubeTranscript:
    """Full transcript with metadata."""

    video_id: str
    segments: list[TranscriptSegment]
    language: str

    @property
    def full_text(self) -> str:
        """Get full transcript as plain text."""
        return " ".join(seg.text for seg in self.segments)

    @property
    def timestamped_text(self) -> str:
        """Get transcript with timestamps."""
        lines = []
        for seg in self.segments:
            minutes = int(seg.start // 60)
            seconds = int(seg.start % 60)
            lines.append(f"[{minutes:02d}:{seconds:02d}] {seg.text}")
        return "\n".join(lines)


class YouTubeService:
    """Service for fetching YouTube transcripts."""

    VIDEO_ID_PATTERNS = [
        r"(?:v=|/)([0-9A-Za-z_-]{11}).*",
        r"^([0-9A-Za-z_-]{11})$",
    ]

    def extract_video_id(self, url_or_id: str) -> str:
        """Extract video ID from URL or validate ID.

        Args:
            url_or_id: YouTube URL or video ID

        Returns:
            11-character video ID

        Raises:
            ValueError: If video ID cannot be extracted
        """
        for pattern in self.VIDEO_ID_PATTERNS:
            match = re.search(pattern, url_or_id)
            if match:
                return match.group(1)
        raise ValueError(f"Could not extract video ID from: {url_or_id}")

    def fetch_transcript(
        self,
        video_id: str,
        languages: list[str] | None = None,
    ) -> YouTubeTranscript:
        """Fetch transcript for a video.

        Args:
            video_id: YouTube video ID
            languages: Preferred languages in order (default: ["en"])

        Returns:
            YouTubeTranscript with segments

        Raises:
            ValueError: If transcript is unavailable
        """
        if languages is None:
            languages = ["en"]

        try:
            # Create API instance and fetch transcript (new API in v1.x)
            api = YouTubeTranscriptApi()
            fetched = api.fetch(video_id, languages=tuple(languages))

            segments = [
                TranscriptSegment(
                    text=entry.text,
                    start=entry.start,
                    duration=entry.duration,
                )
                for entry in fetched
            ]

            return YouTubeTranscript(
                video_id=video_id,
                segments=segments,
                language=languages[0] if languages else "en",
            )

        except VideoUnavailable as e:
            raise ValueError(f"Video unavailable: {video_id}") from e
        except TranscriptsDisabled as e:
            raise ValueError(f"Transcripts disabled for video: {video_id}") from e
        except NoTranscriptFound as e:
            raise ValueError(f"No transcript found for video: {video_id}") from e
        except Exception as e:
            raise ValueError(f"Failed to fetch transcript: {e}") from e


def get_youtube_service() -> YouTubeService:
    """Get YouTube service instance."""
    return YouTubeService()
