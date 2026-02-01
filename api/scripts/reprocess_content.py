#!/usr/bin/env python
"""Reprocess existing content to populate PKM data structures.

This script reprocesses existing content to:
- Parse frontmatter from markdown files and extract tags
- Extract wiki-links and markdown links from markdown content
- Populate the link table
- Extract tags from YouTube video metadata.json
- Update content tags in database

Run with: uv run python scripts/reprocess_content.py
Use --dry-run to preview changes without applying them.
"""

import argparse
import asyncio
import json
import logging
from datetime import datetime

from minio import Minio
from surrealdb import Surreal

from menos.config import settings
from menos.models import LinkModel
from menos.services.frontmatter import FrontmatterParser
from menos.services.linking import LinkExtractor
from menos.services.storage import MinIOStorage, SurrealDBRepository

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class ContentReprocessor:
    """Reprocesses existing content to populate new PKM data structures."""

    def __init__(self, surreal_repo: SurrealDBRepository, minio_storage: MinIOStorage):
        """Initialize reprocessor with storage services.

        Args:
            surreal_repo: SurrealDB repository for metadata operations
            minio_storage: MinIO storage for file operations
        """
        self.surreal_repo = surreal_repo
        self.minio_storage = minio_storage
        self.frontmatter_parser = FrontmatterParser()
        self.link_extractor = LinkExtractor()

        # Statistics
        self.stats = {
            "total": 0,
            "processed": 0,
            "skipped": 0,
            "errors": 0,
            "tags_updated": 0,
            "links_created": 0,
        }

    async def reprocess_all_content(self, dry_run: bool = False) -> None:
        """Reprocess all content in the database.

        Args:
            dry_run: If True, preview changes without applying them
        """
        start_time = datetime.now()
        logger.info("Starting content reprocessing...")
        if dry_run:
            logger.info("DRY RUN MODE - No changes will be applied")

        # Fetch all content in batches
        offset = 0
        limit = 50
        batch_num = 1

        while True:
            logger.info(f"Fetching batch {batch_num} (offset={offset}, limit={limit})")
            items, total = await self.surreal_repo.list_content(offset=offset, limit=limit)

            if not items:
                break

            self.stats["total"] += len(items)

            for item in items:
                if not item.id:
                    logger.warning(f"Skipping item with no ID: {item.title}")
                    self.stats["skipped"] += 1
                    continue

                try:
                    await self._reprocess_item(item, dry_run)
                    self.stats["processed"] += 1
                except Exception as e:
                    logger.error(f"Error processing content {item.id} ({item.title}): {e}")
                    self.stats["errors"] += 1

            # Move to next batch
            offset += limit
            batch_num += 1

            # Stop if we've processed all items
            if offset >= total:
                break

        # Log summary
        duration = (datetime.now() - start_time).total_seconds()
        logger.info("=" * 80)
        logger.info("Reprocessing complete!")
        logger.info(f"Duration: {duration:.2f} seconds")
        logger.info(f"Total items: {self.stats['total']}")
        logger.info(f"Processed: {self.stats['processed']}")
        logger.info(f"Skipped: {self.stats['skipped']}")
        logger.info(f"Errors: {self.stats['errors']}")
        logger.info(f"Tags updated: {self.stats['tags_updated']}")
        logger.info(f"Links created: {self.stats['links_created']}")
        logger.info("=" * 80)

    async def _reprocess_item(self, item, dry_run: bool) -> None:
        """Reprocess a single content item.

        Args:
            item: ContentMetadata object
            dry_run: If True, preview changes without applying them
        """
        content_id = item.id
        content_type = item.content_type

        logger.info(f"Processing {content_type}: {content_id} - {item.title}")

        if content_type == "youtube":
            await self._reprocess_youtube(item, dry_run)
        elif item.mime_type == "text/markdown" or (
            item.file_path and item.file_path.endswith(".md")
        ):
            await self._reprocess_markdown(item, dry_run)
        else:
            logger.info(f"  Skipping non-markdown content: {item.mime_type}")
            self.stats["skipped"] += 1

    async def _reprocess_youtube(self, item, dry_run: bool) -> None:
        """Reprocess YouTube video to extract tags from metadata.json.

        Args:
            item: ContentMetadata for YouTube video
            dry_run: If True, preview changes without applying them
        """
        content_id = item.id
        video_id = item.metadata.get("video_id") if item.metadata else None

        if not video_id:
            logger.warning(f"  No video_id in metadata for {content_id}")
            return

        # Construct metadata.json path
        metadata_path = f"youtube/{video_id}/metadata.json"

        try:
            # Fetch metadata.json from MinIO
            metadata_bytes = await self.minio_storage.download(metadata_path)
            metadata_dict = json.loads(metadata_bytes.decode("utf-8"))

            # Extract tags from metadata.json
            tags_from_metadata = metadata_dict.get("tags", [])

            if not tags_from_metadata:
                logger.info(f"  No tags in metadata.json for {video_id}")
                return

            # Merge with existing tags in DB (avoid duplicates)
            existing_tags = set(item.tags or [])
            new_tags = [tag for tag in tags_from_metadata if tag not in existing_tags]

            if not new_tags:
                logger.info(f"  All tags already present in DB for {video_id}")
                return

            merged_tags = list(existing_tags) + new_tags
            logger.info(
                f"  Found {len(tags_from_metadata)} tags in metadata.json, "
                f"adding {len(new_tags)} new tags"
            )

            if not dry_run:
                # Update content tags
                item.tags = merged_tags
                await self.surreal_repo.update_content(content_id, item)
                self.stats["tags_updated"] += 1
            else:
                logger.info(f"  [DRY RUN] Would update tags to: {merged_tags}")

        except Exception as e:
            logger.error(f"  Failed to fetch or parse metadata.json: {e}")
            raise

    async def _reprocess_markdown(self, item, dry_run: bool) -> None:
        """Reprocess markdown content to extract frontmatter and links.

        Args:
            item: ContentMetadata for markdown document
            dry_run: If True, preview changes without applying them
        """
        content_id = item.id
        file_path = item.file_path

        try:
            # Fetch content from MinIO
            content_bytes = await self.minio_storage.download(file_path)
            content_text = content_bytes.decode("utf-8")

            # Parse frontmatter
            body, frontmatter_metadata = self.frontmatter_parser.parse(content_text)

            # Extract tags from frontmatter
            tags_from_frontmatter = self.frontmatter_parser.extract_tags(
                frontmatter_metadata, explicit_tags=None
            )

            # Merge with existing tags (avoid duplicates)
            existing_tags = set(item.tags or [])
            new_tags = [tag for tag in tags_from_frontmatter if tag not in existing_tags]

            tags_updated = False
            if new_tags:
                merged_tags = list(existing_tags) + new_tags
                logger.info(
                    f"  Found {len(tags_from_frontmatter)} tags in frontmatter, "
                    f"adding {len(new_tags)} new tags"
                )
                tags_updated = True

                if not dry_run:
                    item.tags = merged_tags
                    await self.surreal_repo.update_content(content_id, item)
                    self.stats["tags_updated"] += 1
                else:
                    logger.info(f"  [DRY RUN] Would update tags to: {merged_tags}")
            else:
                logger.info("  No new tags from frontmatter")

            # Extract links
            extracted_links = self.link_extractor.extract_links(content_text)

            if not extracted_links:
                logger.info("  No links found in content")
                if not tags_updated:
                    self.stats["skipped"] += 1
                return

            logger.info(f"  Found {len(extracted_links)} links")

            if not dry_run:
                # Delete existing links for idempotency
                await self.surreal_repo.delete_links_by_source(content_id)

                # Create new links
                for link in extracted_links:
                    # Try to resolve link target by title
                    target_id = None
                    target_content = await self.surreal_repo.find_content_by_title(
                        link.target
                    )
                    if target_content and target_content.id:
                        target_id = target_content.id
                        logger.info(
                            f"    Resolved link '{link.link_text}' -> "
                            f"'{link.target}' to content {target_id}"
                        )
                    else:
                        logger.info(
                            f"    Unresolved link '{link.link_text}' -> '{link.target}'"
                        )

                    # Store link
                    link_model = LinkModel(
                        source=content_id,
                        target=target_id,
                        link_text=link.link_text,
                        link_type=link.link_type,
                    )
                    await self.surreal_repo.create_link(link_model)
                    self.stats["links_created"] += 1
            else:
                logger.info(f"  [DRY RUN] Would create {len(extracted_links)} links:")
                for link in extracted_links[:5]:  # Show first 5
                    logger.info(
                        f"    - {link.link_type}: '{link.link_text}' -> '{link.target}'"
                    )
                if len(extracted_links) > 5:
                    logger.info(f"    ... and {len(extracted_links) - 5} more")

        except Exception as e:
            logger.error(f"  Failed to fetch or process markdown content: {e}")
            raise


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Reprocess existing content to populate PKM data structures"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying them",
    )
    args = parser.parse_args()

    # Initialize MinIO client
    logger.info(f"Connecting to MinIO at {settings.minio_endpoint}")
    minio_client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    minio_storage = MinIOStorage(minio_client, settings.minio_bucket)

    # Initialize SurrealDB repository
    logger.info(f"Connecting to SurrealDB at {settings.surrealdb_url}")
    db = Surreal(settings.surrealdb_url)
    surreal_repo = SurrealDBRepository(
        db=db,
        namespace=settings.surrealdb_namespace,
        database=settings.surrealdb_database,
        username=settings.surrealdb_user,
        password=settings.surrealdb_password,
    )

    try:
        await surreal_repo.connect()
        logger.info("Connected to SurrealDB successfully")
    except Exception as e:
        logger.error(f"Failed to connect to SurrealDB: {e}")
        logger.error("Please ensure SurrealDB is running and accessible")
        return

    # Run reprocessing
    reprocessor = ContentReprocessor(surreal_repo, minio_storage)
    await reprocessor.reprocess_all_content(dry_run=args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
