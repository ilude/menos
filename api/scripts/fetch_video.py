#!/usr/bin/env python
"""Fetch video transcript and metadata from the menos API.

Usage:
    PYTHONPATH=. uv run python scripts/fetch_video.py VIDEO_ID
    PYTHONPATH=. uv run python scripts/fetch_video.py Q7r--i9lLck
    PYTHONPATH=. uv run python scripts/fetch_video.py Q7r--i9lLck --transcript-only
    PYTHONPATH=. uv run python scripts/fetch_video.py Q7r--i9lLck --save /tmp/
    PYTHONPATH=. uv run python scripts/fetch_video.py "https://youtube.com/watch?v=Q7r--i9lLck"
    PYTHONPATH=. uv run python scripts/fetch_video.py Q7r--i9lLck --json
    PYTHONPATH=. uv run python scripts/fetch_video.py Q7r--i9lLck --preview
"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from menos.client.signer import RequestSigner
from menos.config import settings

# YouTube URL patterns for video ID extraction
_YT_PATTERNS = [
    # youtube.com/watch?v=ID
    re.compile(r"(?:youtube\.com/watch\?.*v=)([\w-]{11})"),
    # youtu.be/ID
    re.compile(r"youtu\.be/([\w-]{11})"),
    # youtube.com/embed/ID
    re.compile(r"youtube\.com/embed/([\w-]{11})"),
]
_RAW_VIDEO_ID = re.compile(r"^[\w-]{11}$")


def extract_video_id(value: str) -> str:
    """Extract an 11-char YouTube video ID from a URL or raw ID."""
    value = value.strip()

    # Check raw 11-char ID first
    if _RAW_VIDEO_ID.match(value):
        return value

    # Try URL patterns
    for pattern in _YT_PATTERNS:
        match = pattern.search(value)
        if match:
            return match.group(1)

    # Fallback: try parsing as URL with query param v=
    try:
        parsed = urlparse(value)
        qs = parse_qs(parsed.query)
        if "v" in qs and len(qs["v"][0]) == 11:
            return qs["v"][0]
    except Exception:
        pass

    # If nothing matched, return original (let the API handle validation)
    return value


def _build_signer_and_host(key_path: str) -> tuple[RequestSigner, str, str]:
    """Build a request signer and extract host from settings."""
    base_url = settings.api_base_url
    parsed = urlparse(base_url)
    host = parsed.hostname
    if parsed.port and parsed.port not in (80, 443):
        host = f"{host}:{parsed.port}"
    signer = RequestSigner.from_file(key_path)
    return signer, base_url, host


def _signed_get(
    signer: RequestSigner, base_url: str, host: str, path: str, timeout: float
) -> httpx.Response:
    """Make a signed GET request."""
    sig_headers = signer.sign_request("GET", path, host=host)
    return httpx.get(f"{base_url}{path}", headers=sig_headers, timeout=timeout)


def _format_duration(seconds: int | None) -> str:
    """Format duration_seconds into HH:MM:SS or MM:SS."""
    if seconds is None:
        return "Unknown"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _format_number(n: int | None) -> str:
    """Format a number with comma separators."""
    if n is None:
        return "N/A"
    return f"{n:,}"


def _print_formatted(data: dict, preview: bool) -> None:
    """Print video data in human-readable format."""
    title = data.get("title", "Unknown")
    channel = data.get("channel_title", "Unknown")
    duration = _format_duration(data.get("duration_seconds"))
    views = _format_number(data.get("view_count"))
    likes = _format_number(data.get("like_count"))
    published = data.get("published_at", "Unknown")
    if published and "T" in str(published):
        published = str(published).split("T")[0]

    print(f"\n=== {title} ===")
    print(f"Channel: {channel}")
    print(f"Duration: {duration} | Views: {views} | Likes: {likes}")
    print(f"Published: {published}")
    print(f"Status: {data.get('processing_status', 'unknown')}")

    # Pipeline results
    quality_tier = data.get("quality_tier")
    quality_score = data.get("quality_score")
    summary = data.get("summary")
    tags = data.get("tags", [])
    topics = data.get("topics", [])
    entities = data.get("entities", [])
    chunk_count = data.get("chunk_count")

    if any([quality_tier, summary, tags, topics, entities]):
        print("\n--- Pipeline Results ---")
        if quality_tier is not None:
            score_str = f" ({quality_score}/100)" if quality_score is not None else ""
            print(f"Quality: {quality_tier}{score_str}")
        if summary:
            print(f"Summary: {summary}")
        if tags:
            print(f"Tags: {', '.join(tags)}")
        if topics:
            print(f"Topics: {', '.join(topics)}")
        if entities:
            print(f"Entities: {', '.join(entities)}")
        if chunk_count is not None:
            print(f"Chunks: {chunk_count}")

    # Transcript
    transcript = data.get("transcript")
    if transcript:
        print("\n--- Transcript ---")
        if preview:
            text = transcript[:2000]
            if len(transcript) > 2000:
                text += f"\n\n... [truncated, {len(transcript):,} chars total]"
            print(text)
        else:
            print(transcript)
    else:
        print("\n--- No transcript available ---")

    print()


def main() -> None:
    """Main entry point."""
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Fetch video transcript and metadata from the menos API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  PYTHONPATH=. uv run python scripts/fetch_video.py Q7r--i9lLck
  PYTHONPATH=. uv run python scripts/fetch_video.py Q7r--i9lLck --transcript-only
  PYTHONPATH=. uv run python scripts/fetch_video.py Q7r--i9lLck --save /tmp/
  PYTHONPATH=. uv run python scripts/fetch_video.py "https://youtube.com/watch?v=Q7r--i9lLck"
  PYTHONPATH=. uv run python scripts/fetch_video.py Q7r--i9lLck --json
  PYTHONPATH=. uv run python scripts/fetch_video.py Q7r--i9lLck --preview
        """,
    )
    parser.add_argument(
        "video",
        help="YouTube video ID or URL",
    )
    parser.add_argument(
        "--transcript-only",
        action="store_true",
        help="Fetch only the raw transcript text",
    )
    parser.add_argument(
        "--save",
        metavar="DIR",
        help="Save transcript and metadata to DIR",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output as JSON for piping",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Show first 2000 chars of transcript instead of full",
    )
    parser.add_argument(
        "--key",
        default=str(Path.home() / ".ssh" / "id_ed25519"),
        help="Path to ed25519 private key (default: ~/.ssh/id_ed25519)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30,
        help="Request timeout in seconds (default: 30)",
    )

    args = parser.parse_args()
    video_id = extract_video_id(args.video)

    try:
        signer, base_url, host = _build_signer_and_host(args.key)
    except Exception as e:
        print(f"Failed to load signing key: {e}", file=sys.stderr)
        sys.exit(1)

    # Transcript-only mode
    if args.transcript_only:
        path = f"/api/v1/youtube/{video_id}/transcript"
        try:
            response = _signed_get(signer, base_url, host, path, args.timeout)
        except httpx.ConnectError as e:
            print(f"Connection error: {e}", file=sys.stderr)
            sys.exit(1)

        if response.status_code == 404:
            print(f"Video '{video_id}' not found.", file=sys.stderr)
            sys.exit(1)
        if not response.is_success:
            print(
                f"Error {response.status_code}: {response.text}",
                file=sys.stderr,
            )
            sys.exit(1)

        transcript = response.text
        if args.save:
            save_dir = Path(args.save)
            save_dir.mkdir(parents=True, exist_ok=True)
            out_path = save_dir / f"{video_id}_transcript.txt"
            out_path.write_text(transcript, encoding="utf-8")
            print(f"Saved transcript to {out_path}", file=sys.stderr)
        else:
            print(transcript)

        sys.exit(0)

    # Full metadata mode
    path = f"/api/v1/youtube/{video_id}"
    try:
        response = _signed_get(signer, base_url, host, path, args.timeout)
    except httpx.ConnectError as e:
        print(f"Connection error: {e}", file=sys.stderr)
        sys.exit(1)

    if response.status_code == 404:
        print(f"Video '{video_id}' not found.", file=sys.stderr)
        sys.exit(1)
    if not response.is_success:
        print(
            f"Error {response.status_code}: {response.text}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data = response.json()
    except (json.JSONDecodeError, ValueError):
        print(f"Invalid JSON response: {response.text}", file=sys.stderr)
        sys.exit(1)

    # Save mode
    if args.save:
        save_dir = Path(args.save)
        save_dir.mkdir(parents=True, exist_ok=True)

        # Save metadata JSON
        meta_path = save_dir / f"{video_id}_metadata.json"
        meta_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Saved metadata to {meta_path}", file=sys.stderr)

        # Save transcript text
        transcript = data.get("transcript", "")
        if transcript:
            tx_path = save_dir / f"{video_id}_transcript.txt"
            tx_path.write_text(transcript, encoding="utf-8")
            print(f"Saved transcript to {tx_path}", file=sys.stderr)
        else:
            print("No transcript available to save.", file=sys.stderr)

    # Output
    if args.json_output:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    elif not args.save:
        _print_formatted(data, args.preview)
    else:
        # When saving, also print a brief summary to stdout
        title = data.get("title", "Unknown")
        print(f"Fetched: {title}")


if __name__ == "__main__":
    main()
