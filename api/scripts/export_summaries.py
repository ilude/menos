#!/usr/bin/env python
"""Export summaries from the vault to local markdown files with frontmatter."""

import argparse
import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from menos.services.di import get_storage_context

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    # Convert to lowercase and replace spaces with hyphens
    slug = text.lower().replace(" ", "-")
    # Remove special characters, keep only alphanumeric and hyphens
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    # Remove consecutive hyphens
    slug = re.sub(r"-+", "-", slug)
    # Strip leading/trailing hyphens
    slug = slug.strip("-")
    return slug


def create_frontmatter(
    title: str,
    video_id: str,
    channel: str | None,
    summary_model: str | None,
    classification_tier: str | None,
    classification_score: int | None,
    classification_labels: list[str] | None,
) -> str:
    """Create YAML frontmatter for markdown file."""
    exported_at = datetime.now(timezone.utc).isoformat()

    frontmatter_dict = {
        "title": title,
        "video_id": video_id,
    }

    if channel:
        frontmatter_dict["channel"] = channel

    if summary_model:
        frontmatter_dict["summary_model"] = summary_model

    if classification_tier:
        frontmatter_dict["classification_tier"] = classification_tier

    if classification_score is not None:
        frontmatter_dict["classification_score"] = classification_score

    if classification_labels:
        frontmatter_dict["classification_labels"] = classification_labels

    frontmatter_dict["exported_at"] = exported_at

    lines = ["---"]
    for key, value in frontmatter_dict.items():
        if isinstance(value, str):
            lines.append(f'{key}: "{value}"')
        elif isinstance(value, list):
            lines.append(f"{key}: {json.dumps(value)}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")

    return "\n".join(lines)


async def export_summaries(
    output_dir: str = "data",
    force: bool = False,
    video_id: str | None = None,
) -> None:
    """Export summaries from vault to local markdown files.

    Args:
        output_dir: Directory to save markdown files
        force: Overwrite existing files
        video_id: Export only a specific video (optional)
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    async with get_storage_context() as (minio, surreal):
        # List YouTube content
        limit = 1 if video_id else 1000
        items, _ = await surreal.list_content(content_type="youtube", limit=limit)

        if video_id:
            # Filter to specific video
            items = [
                item
                for item in items
                if item.metadata and item.metadata.get("video_id") == video_id
            ]

        if not items:
            logger.warning(
                f"No YouTube videos found{f' with ID {video_id}' if video_id else ''}"
            )
            return

        logger.info(f"Exporting {len(items)} video summaries to {output_dir}\n")

        for item in items:
            video_id = item.metadata.get("video_id", "") if item.metadata else ""
            if not video_id:
                logger.warning(f"Skipping item {item.id} - no video_id")
                continue

            title = item.title or f"YouTube: {video_id}"
            channel = (
                item.metadata.get("channel_title") if item.metadata else None
            )
            summary_model = None

            logger.info(f"Exporting {title}...")

            # Read metadata.json from MinIO (has summary_model and channel info)
            metadata_json_path = f"youtube/{video_id}/metadata.json"
            try:
                meta_bytes = await minio.download(metadata_json_path)
                minio_meta = json.loads(meta_bytes.decode("utf-8"))
                summary_model = minio_meta.get("summary_model")
                if not channel:
                    channel = minio_meta.get("channel_title")
            except Exception:
                pass

            # Read summary from MinIO
            summary_path = f"youtube/{video_id}/summary.md"
            try:
                summary_bytes = await minio.download(summary_path)
                summary_text = summary_bytes.decode("utf-8")
            except Exception as e:
                logger.warning(f"  No summary found: {e}")
                summary_text = "(No summary available)"

            # Get classification data from raw SurrealDB record
            classification_tier = None
            classification_score = None
            classification_labels = None

            try:
                raw = surreal.db.query(
                    "SELECT classification_status, classification_tier, "
                    "classification_score, metadata.classification.labels AS labels "
                    "FROM content WHERE id = $id",
                    {"id": item.id},
                )
                parsed = surreal._parse_query_result(raw)
                if parsed:
                    rec = parsed[0]
                    if rec.get("classification_status") == "completed":
                        classification_tier = rec.get("classification_tier")
                        classification_score = rec.get("classification_score")
                        classification_labels = rec.get("labels")
            except Exception as e:
                logger.warning(f"  Could not fetch classification: {e}")

            # Create frontmatter
            frontmatter = create_frontmatter(
                title=title,
                video_id=video_id,
                channel=channel,
                summary_model=summary_model,
                classification_tier=classification_tier,
                classification_score=classification_score,
                classification_labels=classification_labels,
            )

            # Generate filename from title
            filename = f"{slugify(title)}.md"
            filepath = output_path / filename

            # Check if file exists
            if filepath.exists() and not force:
                logger.info(f"  {filename} already exists (use --force to overwrite)")
                continue

            # Write markdown file
            markdown_content = f"{frontmatter}\n\n{summary_text}\n"
            filepath.write_text(markdown_content, encoding="utf-8")
            logger.info(f"  Exported to {filename}")

        logger.info("\nDone!")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Export summaries from the vault to local markdown files"
    )
    parser.add_argument(
        "--output-dir",
        default="data",
        help="Output directory for markdown files (default: data/)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files",
    )
    parser.add_argument(
        "--video-id",
        help="Export only a specific video by ID",
    )

    args = parser.parse_args()

    await export_summaries(
        output_dir=args.output_dir,
        force=args.force,
        video_id=args.video_id,
    )


if __name__ == "__main__":
    asyncio.run(main())
