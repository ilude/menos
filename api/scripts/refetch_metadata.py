#!/usr/bin/env python
"""Refetch YouTube metadata for existing videos."""

import asyncio
import io
import json
import logging

from menos.services.di import get_storage_context
from menos.services.youtube_metadata import YouTubeMetadataService

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


async def refetch_all():
    """Refetch metadata for all YouTube videos."""
    async with get_storage_context() as (minio, surreal):
        metadata_service = YouTubeMetadataService()

        # List all YouTube videos
        items, _ = await surreal.list_content(content_type="youtube", limit=100)
        logger.info(f"Found {len(items)} YouTube videos to process\n")

        for item in items:
            video_id = item.metadata.get("video_id", "") if item.metadata else ""
            if not video_id:
                logger.warning(f"Skipping item {item.id} - no video_id")
                continue

            logger.info(f"Processing {video_id}...")

            # Fetch rich metadata from YouTube Data API
            try:
                yt_metadata = metadata_service.fetch_metadata(video_id)
                logger.info(f"  Title: {yt_metadata.title}")
            except Exception as e:
                logger.error(f"  Failed to fetch metadata: {e}")
                continue

            # Read existing transcript
            transcript_path = f"youtube/{video_id}/transcript.txt"
            try:
                transcript_bytes = await minio.download(transcript_path)
                transcript_text = transcript_bytes.decode("utf-8")
            except Exception as e:
                logger.error(f"  Failed to read transcript: {e}")
                continue

            # Update metadata.json
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
                "segment_count": item.metadata.get("segment_count") if item.metadata else None,
                "transcript_length": len(transcript_text),
                "file_size": item.file_size,
                "author": item.author,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "fetched_at": yt_metadata.fetched_at,
            }
            metadata_json = json.dumps(metadata_dict, indent=2)
            await minio.upload(
                metadata_path, io.BytesIO(metadata_json.encode("utf-8")), "application/json"
            )
            logger.info("  Updated metadata.json")

            # Update title in SurrealDB
            try:
                surreal.db.query(
                    "UPDATE content SET title = $title WHERE id = $id",
                    {"title": yt_metadata.title, "id": item.id},
                )
                logger.info("  Updated SurrealDB title")
            except Exception as e:
                logger.error(f"  Failed to update SurrealDB: {e}")

            logger.info("")

        logger.info("Done!")


if __name__ == "__main__":
    asyncio.run(refetch_all())
