#!/usr/bin/env python
"""Refetch YouTube metadata for existing videos.

Fetches rich metadata from YouTube Data API and backfills both
MinIO metadata.json and SurrealDB content metadata fields.

Usage:
    PYTHONPATH=. uv run python scripts/refetch_metadata.py
    PYTHONPATH=. uv run python scripts/refetch_metadata.py --limit 200
    PYTHONPATH=. uv run python scripts/refetch_metadata.py --delay 10
"""

import argparse
import asyncio
import io
import json
import logging
import time

from menos.services.di import get_storage_context
from menos.services.youtube_metadata import YouTubeMetadataService

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


async def refetch_all(limit: int = 1000, delay: int = 30):
    """Refetch metadata for all YouTube videos."""
    async with get_storage_context() as (minio, surreal):
        metadata_service = YouTubeMetadataService()

        # List all YouTube videos
        items, _ = await surreal.list_content(content_type="youtube", limit=limit)
        logger.info(f"Found {len(items)} YouTube videos to process\n")

        success_count = 0
        skip_count = 0
        fail_count = 0

        for i, item in enumerate(items):
            video_id = item.metadata.get("video_id", "") if item.metadata else ""
            if not video_id:
                logger.warning(f"Skipping item {item.id} - no video_id")
                skip_count += 1
                continue

            logger.info(f"[{i + 1}/{len(items)}] Processing {video_id}...")

            # Fetch rich metadata from YouTube Data API
            try:
                yt_metadata = metadata_service.fetch_metadata(video_id)
                logger.info(f"  Title: {yt_metadata.title}")
            except Exception as e:
                logger.error(f"  Failed to fetch metadata: {e}")
                fail_count += 1
                continue

            # Read existing transcript
            transcript_path = f"youtube/{video_id}/transcript.txt"
            try:
                transcript_bytes = await minio.download(transcript_path)
                transcript_text = transcript_bytes.decode("utf-8")
            except Exception as e:
                logger.error(f"  Failed to read transcript: {e}")
                fail_count += 1
                continue

            # Update metadata.json in MinIO
            metadata_path = f"youtube/{video_id}/metadata.json"
            metadata_dict = {
                "id": item.id,
                "video_id": video_id,
                "title": yt_metadata.title,
                "description": yt_metadata.description,
                "description_urls": yt_metadata.description_urls,
                "channel_id": yt_metadata.channel_id,
                "channel_title": yt_metadata.channel_title,
                "published_at": yt_metadata.published_at,
                "duration": yt_metadata.duration_formatted,
                "duration_seconds": yt_metadata.duration_seconds,
                "view_count": yt_metadata.view_count,
                "like_count": yt_metadata.like_count,
                "tags": yt_metadata.tags,
                "thumbnails": yt_metadata.thumbnails,
                "language": item.metadata.get("language", "en") if item.metadata else "en",
                "segment_count": (
                    item.metadata.get("segment_count") if item.metadata else None
                ),
                "transcript_length": len(transcript_text),
                "file_size": item.file_size,
                "author": item.author,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "fetched_at": yt_metadata.fetched_at,
            }
            metadata_json = json.dumps(metadata_dict, indent=2)
            await minio.upload(
                metadata_path,
                io.BytesIO(metadata_json.encode("utf-8")),
                "application/json",
            )
            logger.info("  Updated metadata.json in MinIO")

            # Backfill SurrealDB content record: title, tags, and metadata fields
            try:
                existing_meta = item.metadata or {}
                existing_meta.update({
                    "published_at": yt_metadata.published_at,
                    "fetched_at": yt_metadata.fetched_at,
                    "channel_id": yt_metadata.channel_id,
                    "channel_title": yt_metadata.channel_title,
                    "duration_seconds": yt_metadata.duration_seconds,
                    "view_count": yt_metadata.view_count,
                    "like_count": yt_metadata.like_count,
                    "description_urls": yt_metadata.description_urls,
                })
                surreal.db.query(
                    "UPDATE content SET "
                    "title = $title, "
                    "tags = $tags, "
                    "metadata = $metadata "
                    "WHERE id = $id",
                    {
                        "title": yt_metadata.title,
                        "tags": yt_metadata.tags,
                        "metadata": existing_meta,
                        "id": item.id,
                    },
                )
                logger.info("  Updated SurrealDB (title, tags, metadata)")
            except Exception as e:
                logger.error(f"  Failed to update SurrealDB: {e}")

            success_count += 1

            # Rate limit pause between videos
            if i < len(items) - 1:
                logger.info(f"  Waiting {delay}s before next video...")
                time.sleep(delay)

            logger.info("")

        logger.info("=" * 60)
        logger.info(
            f"Done! {success_count} updated, {fail_count} failed, {skip_count} skipped"
        )


def main():
    parser = argparse.ArgumentParser(description="Refetch YouTube metadata")
    parser.add_argument(
        "--limit", type=int, default=1000,
        help="Maximum number of videos to process (default: 1000)",
    )
    parser.add_argument(
        "--delay", type=int, default=30,
        help="Seconds to wait between API calls (default: 30)",
    )
    args = parser.parse_args()

    try:
        asyncio.run(refetch_all(limit=args.limit, delay=args.delay))
    except KeyboardInterrupt:
        logger.info("\nInterrupted.")


if __name__ == "__main__":
    main()
