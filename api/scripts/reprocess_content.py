#!/usr/bin/env python
"""Reprocess existing content to populate PKM data structures.

This script reprocesses existing content to:
- Parse frontmatter from markdown files and extract tags
- Extract wiki-links and markdown links from markdown content
- Populate the link table
- Extract tags from YouTube video metadata.json
- Update content tags in database
- Extract entities (topics, repos, papers, tools) from content

Run with: uv run python scripts/reprocess_content.py
Use --dry-run to preview changes without applying them.
Use --entities-only to only run entity extraction (skip tags/links).
Use --skip-entities to skip entity extraction (only run tags/links).
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

    def __init__(
        self,
        surreal_repo: SurrealDBRepository,
        minio_storage: MinIOStorage,
        entity_resolution_service=None,
    ):
        """Initialize reprocessor with storage services.

        Args:
            surreal_repo: SurrealDB repository for metadata operations
            minio_storage: MinIO storage for file operations
            entity_resolution_service: Optional entity resolution service
        """
        self.surreal_repo = surreal_repo
        self.minio_storage = minio_storage
        self.entity_resolution = entity_resolution_service
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
            "entities_created": 0,
            "entity_edges_created": 0,
        }

    async def reprocess_all_content(
        self,
        dry_run: bool = False,
        entities_only: bool = False,
        skip_entities: bool = False,
    ) -> None:
        """Reprocess all content in the database.

        Args:
            dry_run: If True, preview changes without applying them
            entities_only: If True, only run entity extraction
            skip_entities: If True, skip entity extraction
        """
        start_time = datetime.now()
        logger.info("Starting content reprocessing...")
        if dry_run:
            logger.info("DRY RUN MODE - No changes will be applied")
        if entities_only:
            logger.info("ENTITIES ONLY MODE - Only running entity extraction")
        if skip_entities:
            logger.info("SKIP ENTITIES MODE - Skipping entity extraction")

        # Refresh entity matcher cache if doing entity extraction
        if self.entity_resolution and not skip_entities and not dry_run:
            logger.info("Refreshing entity matcher cache...")
            await self.entity_resolution.refresh_matcher_cache()

        # Fetch all content in batches
        offset = 0
        limit = 20 if not skip_entities else 50  # Smaller batch for entity extraction
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
                    await self._reprocess_item(
                        item,
                        dry_run=dry_run,
                        entities_only=entities_only,
                        skip_entities=skip_entities,
                    )
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
        if not entities_only:
            logger.info(f"Tags updated: {self.stats['tags_updated']}")
            logger.info(f"Links created: {self.stats['links_created']}")
        if not skip_entities:
            logger.info(f"Entities created: {self.stats['entities_created']}")
            logger.info(f"Entity edges created: {self.stats['entity_edges_created']}")
        logger.info("=" * 80)

    async def _reprocess_item(
        self,
        item,
        dry_run: bool,
        entities_only: bool = False,
        skip_entities: bool = False,
    ) -> None:
        """Reprocess a single content item.

        Args:
            item: ContentMetadata object
            dry_run: If True, preview changes without applying them
            entities_only: If True, only run entity extraction
            skip_entities: If True, skip entity extraction
        """
        content_id = item.id
        content_type = item.content_type

        logger.info(f"Processing {content_type}: {content_id} - {item.title}")

        # Check if entity extraction already done (skip if --entities-only and completed)
        if entities_only:
            extraction_status = getattr(item, "entity_extraction_status", None)
            if extraction_status == "completed":
                logger.info("  Entity extraction already completed, skipping")
                self.stats["skipped"] += 1
                return

        # Original PKM reprocessing (tags, links)
        if not entities_only:
            if content_type == "youtube":
                await self._reprocess_youtube(item, dry_run)
            elif item.mime_type == "text/markdown" or (
                item.file_path and item.file_path.endswith(".md")
            ):
                await self._reprocess_markdown(item, dry_run)
            else:
                logger.info(f"  Skipping non-markdown content: {item.mime_type}")

        # Entity extraction
        if not skip_entities and self.entity_resolution:
            await self._reprocess_entities(item, dry_run)

    async def _reprocess_entities(self, item, dry_run: bool) -> None:
        """Extract and store entities for a content item.

        Args:
            item: ContentMetadata object
            dry_run: If True, preview changes without applying them
        """
        content_id = item.id
        content_type = item.content_type

        # Get content text
        content_text = await self._get_content_text(item)
        if not content_text:
            logger.info("  No content text available for entity extraction")
            return

        # Get description URLs for YouTube content
        description_urls = []
        if content_type == "youtube":
            description_urls = await self._get_youtube_description_urls(item)

        logger.info(f"  Extracting entities from {len(content_text)} chars...")

        if dry_run:
            logger.info("  [DRY RUN] Would extract entities from content")
            return

        try:
            # Mark as processing
            await self.surreal_repo.update_content_extraction_status(
                content_id, "processing"
            )

            # Run entity resolution pipeline
            result = await self.entity_resolution.process_content(
                content_id=content_id,
                content_text=content_text,
                content_type=content_type,
                title=item.title or "Untitled",
                description_urls=description_urls,
            )

            self.stats["entities_created"] += result.entities_created
            self.stats["entity_edges_created"] += len(result.edges)

            logger.info(
                f"  Created {result.entities_created} entities, "
                f"{len(result.edges)} edges"
            )

            if result.metrics:
                logger.info(
                    f"  Metrics: pre_detected={result.metrics.pre_detected_count}, "
                    f"llm_extracted={result.metrics.llm_extracted_count}, "
                    f"llm_skipped={result.metrics.llm_skipped}"
                )

        except Exception as e:
            logger.error(f"  Entity extraction failed: {e}")
            await self.surreal_repo.update_content_extraction_status(
                content_id, "failed"
            )
            raise

    async def _get_content_text(self, item) -> str | None:
        """Get the text content for entity extraction.

        Args:
            item: ContentMetadata object

        Returns:
            Content text or None
        """
        content_type = item.content_type

        if content_type == "youtube":
            # Get transcript from MinIO
            video_id = item.metadata.get("video_id") if item.metadata else None
            if not video_id:
                return None

            transcript_path = f"youtube/{video_id}/transcript.txt"
            try:
                transcript_bytes = await self.minio_storage.download(transcript_path)
                return transcript_bytes.decode("utf-8")
            except Exception:
                return None

        elif item.file_path and item.file_path.endswith(".md"):
            try:
                content_bytes = await self.minio_storage.download(item.file_path)
                content_text = content_bytes.decode("utf-8")
                # Strip frontmatter
                body, _ = self.frontmatter_parser.parse(content_text)
                return body
            except Exception:
                return None

        return None

    async def _get_youtube_description_urls(self, item) -> list[str]:
        """Extract URLs from YouTube video description.

        Args:
            item: ContentMetadata for YouTube video

        Returns:
            List of URLs from description
        """
        video_id = item.metadata.get("video_id") if item.metadata else None
        if not video_id:
            return []

        metadata_path = f"youtube/{video_id}/metadata.json"
        try:
            metadata_bytes = await self.minio_storage.download(metadata_path)
            metadata_dict = json.loads(metadata_bytes.decode("utf-8"))
            description = metadata_dict.get("description", "")

            # Simple URL extraction
            import re
            url_pattern = r'https?://[^\s<>"\'\\]+'
            urls = re.findall(url_pattern, description)
            return urls
        except Exception:
            return []

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


def _create_entity_resolution_service(surreal_repo: SurrealDBRepository):
    """Create entity resolution service with all dependencies.

    Args:
        surreal_repo: SurrealDB repository

    Returns:
        EntityResolutionService or None if dependencies unavailable
    """
    if not settings.entity_extraction_enabled:
        logger.info("Entity extraction disabled in settings")
        return None

    try:
        from menos.services.di import build_openrouter_chain
        from menos.services.entity_extraction import EntityExtractionService
        from menos.services.entity_resolution import EntityResolutionService
        from menos.services.keyword_matcher import EntityKeywordMatcher
        from menos.services.llm import OllamaLLMProvider

        # Create LLM provider based on config
        if settings.entity_extraction_provider == "openrouter":
            llm_provider = build_openrouter_chain(settings.entity_extraction_model)
        else:
            llm_provider = OllamaLLMProvider(
                base_url=settings.ollama_url,
                model=settings.entity_extraction_model,
            )

        # Create extraction service
        extraction_service = EntityExtractionService(
            llm_provider=llm_provider,
            settings=settings,
        )

        # Create keyword matcher
        keyword_matcher = EntityKeywordMatcher()

        # Try to import optional fetchers
        url_detector = None
        sponsored_filter = None
        github_fetcher = None
        arxiv_fetcher = None

        try:
            from menos.services.url_detector import URLDetector
            url_detector = URLDetector()
        except ImportError:
            logger.warning("URL detector not available")

        try:
            from menos.services.sponsored_filter import SponsoredFilter
            sponsored_filter = SponsoredFilter()
        except ImportError:
            logger.warning("Sponsored filter not available")

        try:
            from menos.services.entity_fetchers.github import GitHubFetcher
            github_fetcher = GitHubFetcher(
                proxy_username=settings.webshare_proxy_username,
                proxy_password=settings.webshare_proxy_password,
            )
        except ImportError:
            logger.warning("GitHub fetcher not available")

        try:
            from menos.services.entity_fetchers.arxiv import ArxivFetcher
            arxiv_fetcher = ArxivFetcher()
        except ImportError:
            logger.warning("ArXiv fetcher not available")

        # Create resolution service
        return EntityResolutionService(
            repository=surreal_repo,
            extraction_service=extraction_service,
            keyword_matcher=keyword_matcher,
            settings=settings,
            url_detector=url_detector,
            sponsored_filter=sponsored_filter,
            github_fetcher=github_fetcher,
            arxiv_fetcher=arxiv_fetcher,
        )

    except ImportError as e:
        logger.warning(f"Entity extraction services not available: {e}")
        return None


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
    parser.add_argument(
        "--entities-only",
        action="store_true",
        help="Only run entity extraction (skip tags/links processing)",
    )
    parser.add_argument(
        "--skip-entities",
        action="store_true",
        help="Skip entity extraction (only run tags/links processing)",
    )
    args = parser.parse_args()

    if args.entities_only and args.skip_entities:
        logger.error("Cannot use both --entities-only and --skip-entities")
        return

    # Initialize MinIO client
    logger.info(f"Connecting to MinIO at {settings.minio_url}")
    minio_client = Minio(
        settings.minio_url,
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

    # Create entity resolution service (if not skipping entities)
    entity_resolution = None
    if not args.skip_entities:
        entity_resolution = _create_entity_resolution_service(surreal_repo)
        if args.entities_only and not entity_resolution:
            logger.error("Entity extraction requested but service not available")
            return

    # Run reprocessing
    reprocessor = ContentReprocessor(
        surreal_repo,
        minio_storage,
        entity_resolution_service=entity_resolution,
    )
    await reprocessor.reprocess_all_content(
        dry_run=args.dry_run,
        entities_only=args.entities_only,
        skip_entities=args.skip_entities,
    )


if __name__ == "__main__":
    asyncio.run(main())
