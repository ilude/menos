#!/usr/bin/env python
"""Script to ingest YouTube videos from a list file."""

import sys
import re
import httpx
import json
import os
from pathlib import Path

# Add the api directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

from youtube_transcript_api import YouTubeTranscriptApi

from menos.client.signer import RequestSigner
from menos.services.youtube import YouTubeService, TranscriptSegment, YouTubeTranscript


def extract_url(line: str) -> str | None:
    """Extract YouTube URL from a line."""
    match = re.search(r'(https?://[^\s]+youtube[^\s]+)', line)
    if match:
        return match.group(1)
    return None


def fetch_transcript_with_cookies(video_id: str, cookies_path: str | None = None) -> YouTubeTranscript:
    """Fetch transcript using cookies if available."""
    if cookies_path and Path(cookies_path).exists():
        api = YouTubeTranscriptApi(cookies_path=cookies_path)
    else:
        api = YouTubeTranscriptApi()

    fetched = api.fetch(video_id, languages=("en",))
    segments = [
        TranscriptSegment(text=entry.text, start=entry.start, duration=entry.duration)
        for entry in fetched
    ]
    return YouTubeTranscript(video_id=video_id, segments=segments, language="en")


def main():
    # Load private key for signing
    key_path = os.path.expanduser("~/.ssh/id_ed25519")
    signer = RequestSigner.from_file(key_path)

    # API endpoint
    base_url = "http://192.168.16.241:8000"

    # Check for cookies file
    cookies_path = os.path.expanduser("~/.config/menos/cookies.txt")
    if Path(cookies_path).exists():
        print(f"Using cookies from: {cookies_path}\n")
    else:
        print("No cookies file found. YouTube may block requests.")
        print(f"To use cookies, export from browser to: {cookies_path}\n")

    # Initialize YouTube service for video ID extraction
    youtube_service = YouTubeService()

    # Read videos file
    videos_file = Path(__file__).parent.parent / "data" / "youtube-videos.txt"
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
                # Extract video ID and fetch transcript locally
                video_id = youtube_service.extract_video_id(url)
                print(f"    Fetching transcript locally for {video_id}...")
                transcript = fetch_transcript_with_cookies(video_id, cookies_path)

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
                    host="192.168.16.241:8000",
                )
                headers["content-type"] = "application/json"

                response = client.post(
                    "/api/v1/youtube/upload",
                    content=body_bytes,
                    headers=headers,
                )

                if response.status_code == 200:
                    data = response.json()
                    print(f"    OK: {data.get('video_id')} - {data.get('chunks_created')} chunks")
                else:
                    print(f"    ERROR {response.status_code}: {response.text[:200]}")
            except Exception as e:
                print(f"    EXCEPTION: {e}")

            print()


if __name__ == "__main__":
    main()
