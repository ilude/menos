"""YouTube metadata fetching service using Data API v3."""

import re
from dataclasses import dataclass
from datetime import datetime

from menos.config import settings


@dataclass
class YouTubeMetadata:
    """Full YouTube video metadata."""

    video_id: str
    title: str
    description: str
    description_urls: list[str]
    channel_id: str
    channel_title: str
    published_at: str
    duration: str
    duration_seconds: int
    duration_formatted: str
    view_count: int
    like_count: int | None
    comment_count: int | None
    tags: list[str]
    category_id: str | None
    thumbnails: dict
    fetched_at: str

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "video_id": self.video_id,
            "title": self.title,
            "description": self.description,
            "description_urls": self.description_urls,
            "channel_id": self.channel_id,
            "channel_title": self.channel_title,
            "published_at": self.published_at,
            "duration": self.duration,
            "duration_seconds": self.duration_seconds,
            "duration_formatted": self.duration_formatted,
            "view_count": self.view_count,
            "like_count": self.like_count,
            "comment_count": self.comment_count,
            "tags": self.tags,
            "category_id": self.category_id,
            "thumbnails": self.thumbnails,
            "fetched_at": self.fetched_at,
        }


def extract_urls(text: str) -> list[str]:
    """Extract all URLs from text (e.g., video description)."""
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(url_pattern, text)

    # Clean trailing punctuation
    cleaned_urls = []
    for url in urls:
        url = url.rstrip(".,;:!?)")
        if url.endswith(")") and url.count("(") < url.count(")"):
            url = url.rstrip(")")
        cleaned_urls.append(url)

    # Deduplicate while preserving order
    seen = set()
    unique_urls = []
    for url in cleaned_urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)

    return unique_urls


def parse_duration_to_seconds(duration: str) -> int:
    """Parse ISO 8601 duration to seconds."""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return 0

    hours, minutes, seconds = match.groups()
    hours = int(hours) if hours else 0
    minutes = int(minutes) if minutes else 0
    seconds = int(seconds) if seconds else 0

    return hours * 3600 + minutes * 60 + seconds


def format_duration(duration: str) -> str:
    """Format ISO 8601 duration to human-readable format."""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return duration

    hours, minutes, seconds = match.groups()
    hours = int(hours) if hours else 0
    minutes = int(minutes) if minutes else 0
    seconds = int(seconds) if seconds else 0

    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


class YouTubeMetadataService:
    """Service for fetching YouTube video metadata using Data API v3."""

    def __init__(self, api_key: str | None = None):
        """Initialize metadata service."""
        self.api_key = api_key or settings.youtube_api_key
        self._youtube = None

    def _get_client(self):
        """Lazy-load the YouTube API client."""
        if self._youtube is None:
            if not self.api_key:
                raise ValueError("YouTube API key not configured")
            from googleapiclient.discovery import build

            self._youtube = build("youtube", "v3", developerKey=self.api_key)
        return self._youtube

    def fetch_metadata(self, video_id: str) -> YouTubeMetadata:
        """Fetch metadata for a YouTube video.

        Args:
            video_id: YouTube video ID (11 characters)

        Returns:
            YouTubeMetadata with all available fields

        Raises:
            ValueError: If video not found or API error
        """
        youtube = self._get_client()

        request = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=video_id,
        )
        response = request.execute()

        if not response.get("items"):
            raise ValueError(f"Video not found: {video_id}")

        video = response["items"][0]
        snippet = video["snippet"]
        statistics = video.get("statistics", {})
        content_details = video["contentDetails"]

        duration_iso = content_details["duration"]
        description = snippet.get("description", "")

        return YouTubeMetadata(
            video_id=video_id,
            title=snippet["title"],
            description=description,
            description_urls=extract_urls(description),
            channel_id=snippet["channelId"],
            channel_title=snippet["channelTitle"],
            published_at=snippet["publishedAt"],
            duration=duration_iso,
            duration_seconds=parse_duration_to_seconds(duration_iso),
            duration_formatted=format_duration(duration_iso),
            view_count=int(statistics.get("viewCount", 0)),
            like_count=int(statistics["likeCount"]) if "likeCount" in statistics else None,
            comment_count=int(statistics["commentCount"]) if "commentCount" in statistics else None,
            tags=snippet.get("tags", []),
            category_id=snippet.get("categoryId"),
            thumbnails=snippet.get("thumbnails", {}),
            fetched_at=datetime.now().isoformat(),
        )

    def fetch_metadata_safe(self, video_id: str) -> tuple[YouTubeMetadata | None, str | None]:
        """Fetch metadata with error handling.

        Returns:
            Tuple of (metadata, error_string)
        """
        try:
            metadata = self.fetch_metadata(video_id)
            return metadata, None
        except Exception as e:
            return None, str(e)


def get_youtube_metadata_service() -> YouTubeMetadataService:
    """Get YouTube metadata service instance."""
    return YouTubeMetadataService()
