"""YouTube metadata fetcher using YouTube Data API."""

import json
from datetime import datetime

import httpx

from menos.config import settings

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


async def fetch_metadata(video_id: str) -> dict | None:
    """Fetch video metadata from YouTube Data API."""
    if not settings.youtube_api_key:
        print("YouTube API key not configured")
        return None

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{YOUTUBE_API_BASE}/videos",
                params={
                    "id": video_id,
                    "part": "snippet,contentDetails,statistics",
                    "key": settings.youtube_api_key,
                },
            )
            response.raise_for_status()
            data = response.json()

        if not data.get("items"):
            return None

        item = data["items"][0]
        snippet = item.get("snippet", {})
        content = item.get("contentDetails", {})
        stats = item.get("statistics", {})

        duration_str = content.get("duration", "")
        duration_seconds = parse_iso_duration(duration_str)

        published_str = snippet.get("publishedAt", "")
        published_at = None
        if published_str:
            published_at = datetime.fromisoformat(published_str.replace("Z", "+00:00"))

        return {
            "title": snippet.get("title"),
            "channel_name": snippet.get("channelTitle"),
            "channel_id": snippet.get("channelId"),
            "description": snippet.get("description"),
            "published_at": published_at.isoformat() if published_at else None,
            "duration_seconds": duration_seconds,
            "view_count": int(stats.get("viewCount", 0)),
            "metadata_json": json.dumps(data),
        }

    except Exception as e:
        print(f"Failed to fetch metadata for {video_id}: {e}")
        return None


def parse_iso_duration(duration_str: str) -> int:
    """Parse ISO 8601 duration to seconds."""
    if not duration_str or not duration_str.startswith("PT"):
        return 0

    duration_str = duration_str[2:]
    seconds = 0

    if "H" in duration_str:
        hours, duration_str = duration_str.split("H")
        seconds += int(hours) * 3600

    if "M" in duration_str:
        minutes, duration_str = duration_str.split("M")
        seconds += int(minutes) * 60

    if "S" in duration_str:
        secs = duration_str.replace("S", "")
        seconds += int(secs)

    return seconds
