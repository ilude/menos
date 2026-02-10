#!/usr/bin/env python
"""Script to ingest YouTube videos from a list file.

Uses Webshare proxy to avoid YouTube rate limiting.

Environment variables:
    WEBSHARE_PROXY_USERNAME - Webshare proxy username
    WEBSHARE_PROXY_PASSWORD - Webshare proxy password
"""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import WebshareProxyConfig

from menos.client.signer import RequestSigner
from menos.config import settings
from menos.services.youtube import TranscriptSegment, YouTubeService, YouTubeTranscript


def load_secrets_file() -> None:
    """Load secrets from ~/.dotfiles/.secrets if env vars not set."""
    secrets_path = Path.home() / ".dotfiles" / ".secrets"
    if not secrets_path.exists():
        return

    for line in secrets_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if match:
            name, value = match.groups()
            value = value.strip("'\"")
            if name not in os.environ:
                os.environ[name] = value


def extract_url(line: str) -> str | None:
    """Extract YouTube URL from a line."""
    match = re.search(r"(https?://[^\s]+youtube[^\s]+)", line)
    if match:
        return match.group(1)
    return None


def get_transcript_api() -> YouTubeTranscriptApi:
    """Get YouTube API with proxy if credentials available."""
    username = os.getenv("WEBSHARE_PROXY_USERNAME")
    password = os.getenv("WEBSHARE_PROXY_PASSWORD")

    if username and password:
        print("Using Webshare proxy\n")
        proxy_config = WebshareProxyConfig(
            proxy_username=username,
            proxy_password=password,
        )
        return YouTubeTranscriptApi(proxy_config=proxy_config)

    print("No proxy configured (direct connection)\n")
    return YouTubeTranscriptApi()


def fetch_transcript(api: YouTubeTranscriptApi, video_id: str) -> YouTubeTranscript:
    """Fetch transcript using the API."""
    fetched = api.fetch(video_id, languages=("en",))
    segments = [
        TranscriptSegment(text=entry.text, start=entry.start, duration=entry.duration)
        for entry in fetched
    ]
    return YouTubeTranscript(video_id=video_id, segments=segments, language="en")


def main():
    # Load secrets first
    load_secrets_file()

    # Load private key for signing
    key_path = os.path.expanduser("~/.ssh/id_ed25519")
    signer = RequestSigner.from_file(key_path)

    # API endpoint
    base_url = settings.api_base_url

    # Get transcript API with proxy support
    transcript_api = get_transcript_api()

    # Initialize YouTube service for video ID extraction
    youtube_service = YouTubeService()

    # Read videos file (relative to repo root)
    videos_file = Path(__file__).parent.parent.parent / "data" / "youtube-videos.txt"
    content = videos_file.read_text()

    # Extract URLs
    urls = []
    for line in content.split("\n"):
        url = extract_url(line)
        if url:
            urls.append(url)

    print(f"Found {len(urls)} videos to ingest\n")

    # Ingest each video
    with httpx.Client(base_url=base_url, timeout=120) as client:
        for i, url in enumerate(urls, 1):
            print(f"[{i}/{len(urls)}] Ingesting: {url}")

            try:
                # Extract video ID and fetch transcript
                video_id = youtube_service.extract_video_id(url)
                print(f"    Fetching transcript for {video_id}...")
                transcript = fetch_transcript(transcript_api, video_id)

                # Prepare upload request with pre-fetched transcript
                body = {
                    "video_id": video_id,
                    "transcript_text": transcript.full_text,
                    "timestamped_text": transcript.timestamped_text,
                    "language": transcript.language,
                    "generate_embeddings": True,
                }
                body_bytes = json.dumps(body).encode()

                headers = signer.sign_request(
                    "POST",
                    "/api/v1/youtube/upload",
                    body=body_bytes,
                    host=urlparse(settings.api_base_url).netloc,
                )
                headers["content-type"] = "application/json"

                response = client.post(
                    "/api/v1/youtube/upload",
                    content=body_bytes,
                    headers=headers,
                )

                if response.status_code == 200:
                    data = response.json()
                    print(
                        f"    OK: {data.get('video_id')} - {data.get('chunks_created')} chunks"
                    )
                else:
                    print(f"    ERROR {response.status_code}: {response.text}")
            except Exception as e:
                print(f"    EXCEPTION: {e}")

            print()


if __name__ == "__main__":
    main()
