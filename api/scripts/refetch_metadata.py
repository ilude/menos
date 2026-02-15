#!/usr/bin/env python
"""Refetch YouTube metadata for existing videos.

Fetches rich metadata from YouTube Data API and backfills both
MinIO metadata.json and SurrealDB content metadata fields.

Usage:
    PYTHONPATH=. uv run python scripts/refetch_metadata.py
    PYTHONPATH=. uv run python scripts/refetch_metadata.py --limit 200
    PYTHONPATH=. uv run python scripts/refetch_metadata.py --delay 10
    PYTHONPATH=. uv run python scripts/refetch_metadata.py --db-only
"""

import argparse
import asyncio
import io
import json
import logging
import time

from surrealdb import RecordID

from menos.services.di import get_storage_context
from menos.services.youtube_metadata import YouTubeMetadataService

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Re-authenticate before JWT expires (SurrealDB default: 1 hour)
REAUTH_INTERVAL_SECONDS = 45 * 60


async def refetch_all(limit: int = 1000, delay: int = 30, db_only: bool = False):
    """Refetch metadata for all YouTube videos."""
    async with get_storage_context() as (minio, surreal):
        metadata_service = YouTubeMetadataService()

        # List all YouTube videos
        items, _ = await surreal.list_content(content_type="youtube", limit=limit)
        logger.info(f"Found {len(items)} YouTube videos to process\n")

        success_count = 0
        skip_count = 0
        fail_count = 0
        db_fail_count = 0
        last_auth_time = time.monotonic()

        for i, item in enumerate(items):
            video_id = item.metadata.get("video_id", "") if item.metadata else ""
            if not video_id:
                logger.warning(f"Skipping item {item.id} - no video_id")
                skip_count += 1
                continue

            # Re-authenticate if approaching JWT expiry
            elapsed = time.monotonic() - last_auth_time
            if elapsed > REAUTH_INTERVAL_SECONDS:
                logger.info("  Re-authenticating SurrealDB (JWT refresh)...")
                surreal.db.signin({"username": surreal.username, "password": surreal.password})
                surreal.db.use(surreal.namespace, surreal.database)
                last_auth_time = time.monotonic()

            logger.info(f"[{i + 1}/{len(items)}] Processing {video_id}...")

            if db_only:
                # Read metadata from MinIO instead of YouTube API
                metadata_path = f"youtube/{video_id}/metadata.json"
                try:
                    meta_bytes = await minio.download(metadata_path)
                    meta_json = json.loads(meta_bytes.decode("utf-8"))
                except Exception as e:
                    logger.error(f"  Failed to read metadata.json from MinIO: {e}")
                    fail_count += 1
                    continue

                logger.info(f"  Title: {meta_json.get('title', 'unknown')}")

                # Update SurrealDB from MinIO metadata
                try:
                    existing_meta = item.metadata or {}
                    existing_meta.update(
                        {
                            "published_at": meta_json.get("published_at"),
                            "fetched_at": meta_json.get("fetched_at"),
                            "channel_id": meta_json.get("channel_id"),
                            "channel_title": meta_json.get("channel_title"),
                            "duration_seconds": meta_json.get("duration_seconds"),
                            "view_count": meta_json.get("view_count"),
                            "like_count": meta_json.get("like_count"),
                            "description_urls": meta_json.get("description_urls", []),
                        }
                    )
                    surreal.db.query(
                        "UPDATE content SET "
                        "title = $title, "
                        "tags = $tags, "
                        "metadata = $metadata "
                        "WHERE id = $id",
                        {
                            "title": meta_json.get("title", f"YouTube: {video_id}"),
                            "tags": meta_json.get("tags", []),
                            "metadata": existing_meta,
                            "id": RecordID("content", item.id),
                        },
                    )
                    logger.info("  Updated SurrealDB (title, tags, metadata)")
                except Exception as e:
                    logger.error(f"  Failed to update SurrealDB: {e}")
                    db_fail_count += 1

                success_count += 1
                logger.info("")
                continue

            # Full mode: fetch from YouTube API
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
                "segment_count": (item.metadata.get("segment_count") if item.metadata else None),
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
                existing_meta.update(
                    {
                        "published_at": yt_metadata.published_at,
                        "fetched_at": yt_metadata.fetched_at,
                        "channel_id": yt_metadata.channel_id,
                        "channel_title": yt_metadata.channel_title,
                        "duration_seconds": yt_metadata.duration_seconds,
                        "view_count": yt_metadata.view_count,
                        "like_count": yt_metadata.like_count,
                        "description_urls": yt_metadata.description_urls,
                    }
                )
                # Normalize ID: handle both "abc123" and "content:abc123" formats
                raw_id = str(item.id).split(":")[-1]
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
                        "id": RecordID("content", raw_id),
                    },
                )
                logger.info("  Updated SurrealDB (title, tags, metadata)")
            except Exception as e:
                logger.error(f"  Failed to update SurrealDB: {e}")
                db_fail_count += 1

            success_count += 1

            # Rate limit pause between videos (full mode only)
            if i < len(items) - 1:
                logger.info(f"  Waiting {delay}s before next video...")
                time.sleep(delay)

            logger.info("")

        logger.info("=" * 60)
        logger.info(
            f"Done! {success_count} updated, {fail_count} failed, "
            f"{db_fail_count} db errors, {skip_count} skipped"
        )


def main():
    parser = argparse.ArgumentParser(description="Refetch YouTube metadata")
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Maximum number of videos to process (default: 1000)",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=30,
        help="Seconds to wait between API calls (default: 30)",
    )
    parser.add_argument(
        "--db-only",
        action="store_true",
        help="Only update SurrealDB from existing MinIO metadata.json (no YouTube API calls)",
    )
    args = parser.parse_args()

    try:
        asyncio.run(refetch_all(limit=args.limit, delay=args.delay, db_only=args.db_only))
    except KeyboardInterrupt:
        logger.info("\nInterrupted.")


if __name__ == "__main__":
    main()
