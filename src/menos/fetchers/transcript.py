"""YouTube transcript fetcher."""

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import WebshareProxyConfig

from menos.config import settings


def fetch_transcript(video_id: str) -> str | None:
    """Fetch transcript for a YouTube video.

    Returns timestamped transcript text or None if unavailable.
    """
    try:
        # Configure proxy if credentials available
        proxy_config = None
        if settings.webshare_proxy_username and settings.webshare_proxy_password:
            proxy_config = WebshareProxyConfig(
                proxy_username=settings.webshare_proxy_username,
                proxy_password=settings.webshare_proxy_password,
            )

        # Fetch transcript
        if proxy_config:
            ytt_api = YouTubeTranscriptApi(proxy_config=proxy_config)
            transcript_list = ytt_api.fetch(video_id)
        else:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)

        # Format with timestamps
        lines = []
        for entry in transcript_list:
            start = entry["start"]
            minutes = int(start // 60)
            seconds = int(start % 60)
            timestamp = f"[{minutes:02d}:{seconds:02d}]"
            text = entry["text"].replace("\n", " ")
            lines.append(f"{timestamp} {text}")

        return "\n".join(lines)

    except Exception as e:
        # Log but don't fail - transcript might not be available
        print(f"Failed to fetch transcript for {video_id}: {e}")
        return None
