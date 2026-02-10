#!/usr/bin/env python
"""Refetch metadata and regenerate summaries for selected videos from youtube-videos.txt."""

import asyncio
import io
import json
import logging
import re
from pathlib import Path

from menos.services.di import build_openrouter_chain, get_storage_context
from menos.services.youtube_metadata import YouTubeMetadataService

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def extract_video_ids(filepath: Path) -> list[str]:
    """Extract YouTube video IDs from the videos file."""
    content = filepath.read_text()
    urls = re.findall(r"youtube\.com/watch\?v=([A-Za-z0-9_-]+)", content)
    return urls


async def refetch_selected():
    """Refetch metadata and regenerate summaries for videos in youtube-videos.txt."""
    videos_file = Path(__file__).parent.parent.parent / "data" / "youtube-videos.txt"
    target_ids = extract_video_ids(videos_file)
    logger.info(f"Found {len(target_ids)} video IDs to process\n")

    async with get_storage_context() as (minio, surreal):
        metadata_service = YouTubeMetadataService()
        llm_service = build_openrouter_chain()

        # Build lookup of existing content by video_id
        items, _ = await surreal.list_content(content_type="youtube", limit=1000)
        video_map = {}
        for item in items:
            vid = item.metadata.get("video_id", "") if item.metadata else ""
            if vid in target_ids:
                video_map[vid] = item

        for vid in target_ids:
            item = video_map.get(vid)
            if not item:
                logger.warning(f"Video {vid} not found in DB, skipping")
                continue

            logger.info(f"Processing {vid}...")

            # Fetch YouTube metadata
            try:
                yt = metadata_service.fetch_metadata(vid)
                logger.info(f"  Title: {yt.title}")
            except Exception as e:
                logger.error(f"  Failed to fetch metadata: {e}")
                continue

            # Read transcript
            try:
                tb = await minio.download(f"youtube/{vid}/transcript.txt")
                transcript_text = tb.decode("utf-8")
            except Exception as e:
                logger.error(f"  Failed to read transcript: {e}")
                continue

            # Update metadata.json
            md = {
                "id": item.id,
                "video_id": vid,
                "title": yt.title,
                "description": yt.description,
                "description_urls": yt.description_urls,
                "channel_id": yt.channel_id,
                "channel_title": yt.channel_title,
                "published_at": yt.published_at,
                "duration": yt.duration_formatted,
                "duration_seconds": yt.duration_seconds,
                "view_count": yt.view_count,
                "like_count": yt.like_count,
                "tags": yt.tags,
                "thumbnails": yt.thumbnails,
                "language": item.metadata.get("language", "en") if item.metadata else "en",
                "transcript_length": len(transcript_text),
                "file_size": item.file_size,
                "author": item.author,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "fetched_at": yt.fetched_at,
                "summary_model": getattr(llm_service, "model", "openrouter/pony-alpha"),
            }
            metadata_json = json.dumps(md, indent=2)
            await minio.upload(
                f"youtube/{vid}/metadata.json",
                io.BytesIO(metadata_json.encode("utf-8")),
                "application/json",
            )
            logger.info("  Updated metadata.json")

            # Regenerate summary using classification prompt
            try:
                system_prompt = """\
# IDENTITY and PURPOSE

You are an ultra-wise and brilliant classifier and judge of content. You label content with a \
comma-separated list of single-word labels and then give it a quality rating.

Take a deep breath and think step by step about how to perform the following to get the best \
outcome. You have a lot of freedom to do this the way you think is best.

# STEPS:

- Label the content with up to 20 single-word labels, such as: cybersecurity, philosophy, \
nihilism, poetry, writing, etc. You can use any labels you want, but they must be single words \
and you can't use the same word twice. This goes in a section called LABELS:.

- Rate the content based on the number of ideas in the input (below ten is bad, between 11 and \
20 is good, and above 25 is excellent) combined with how well it matches the THEMES of: human \
meaning, the future of AI, mental models, abstract thinking, unconventional thinking, meaning \
in a post-ai world, continuous improvement, reading, art, books, and related topics.

## Use the following rating levels:

- S Tier: (Must Consume Original Content Immediately): 18+ ideas and/or STRONG theme matching \
with the themes in STEP #2.

- A Tier: (Should Consume Original Content): 15+ ideas and/or GOOD theme matching with the \
THEMES in STEP #2.

- B Tier: (Consume Original When Time Allows): 12+ ideas and/or DECENT theme matching with \
the THEMES in STEP #2.

- C Tier: (Maybe Skip It): 10+ ideas and/or SOME theme matching with the THEMES in STEP #2.

- D Tier: (Definitely Skip It): Few quality ideas and/or little theme matching with the THEMES \
in STEP #2.

- Provide a score between 1 and 100 for the overall quality ranking, where 100 is a perfect \
match with the highest number of high quality ideas, and 1 is the worst match with a low number \
of the worst ideas.

The output should look like the following:

LABELS:

Cybersecurity, Writing, Running, Copywriting, etc.

RATING:

S Tier: (Must Consume Original Content Immediately)

Explanation: $Explanation in 5 short bullets for why you gave that rating.$

CONTENT SCORE:

$The 1-100 quality score$

Explanation: $Explanation in 5 short bullets for why you gave that score.$

## OUTPUT INSTRUCTIONS

1. You only output Markdown.
2. Do not give warnings or notes; only output the requested sections."""

                user_prompt = f"# Content Title: {yt.title}\n\n# Transcript:\n\n{transcript_text}"
                summary = await llm_service.generate(
                    user_prompt,
                    system_prompt=system_prompt,
                    max_tokens=4096,
                    temperature=0.3,
                )
                await minio.upload(
                    f"youtube/{vid}/summary.md",
                    io.BytesIO(summary.encode("utf-8")),
                    "text/markdown",
                )
                logger.info("  Regenerated summary.md")
            except Exception as e:
                logger.error(f"  Failed to generate summary: {e}")

            # Update SurrealDB title
            try:
                surreal.db.query(
                    "UPDATE content SET title = $title WHERE id = $id",
                    {"title": yt.title, "id": item.id},
                )
                logger.info("  Updated SurrealDB title")
            except Exception as e:
                logger.error(f"  Failed to update SurrealDB: {e}")

            logger.info("")

        logger.info("Done!")


if __name__ == "__main__":
    asyncio.run(refetch_selected())
