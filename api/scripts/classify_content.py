#!/usr/bin/env python
"""Batch classify existing content with quality ratings and labels.

Run with: PYTHONPATH=. uv run python scripts/classify_content.py
Use --dry-run to preview changes without applying them.
Use --force to reclassify already-classified content.
Use --content-type to filter by content type (e.g., youtube, markdown).
Use --limit to cap the total number of items to process.
"""

import argparse
import asyncio
import logging
from datetime import datetime

from minio import Minio
from surrealdb import Surreal

from menos.config import settings
from menos.services.classification import ClassificationService, VaultInterestProvider
from menos.services.di import build_openrouter_chain
from menos.services.llm import OllamaLLMProvider
from menos.services.llm_providers import (
    AnthropicProvider,
    NoOpLLMProvider,
    OpenAIProvider,
)
from menos.services.storage import MinIOStorage, SurrealDBRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _create_classification_service(
    surreal_repo: SurrealDBRepository,
) -> ClassificationService | None:
    """Create classification service with all dependencies.

    Args:
        surreal_repo: SurrealDB repository

    Returns:
        ClassificationService or None if dependencies unavailable
    """
    if not settings.classification_enabled:
        logger.info("Classification disabled in settings")
        return None

    provider_type = settings.classification_provider
    model = settings.classification_model

    try:
        if provider_type == "ollama":
            llm_provider = OllamaLLMProvider(settings.ollama_url, model)
        elif provider_type == "openai":
            if not settings.openai_api_key:
                raise ValueError("openai_api_key must be set")
            llm_provider = OpenAIProvider(settings.openai_api_key, model)
        elif provider_type == "anthropic":
            if not settings.anthropic_api_key:
                raise ValueError("anthropic_api_key must be set")
            llm_provider = AnthropicProvider(settings.anthropic_api_key, model)
        elif provider_type == "openrouter":
            llm_provider = build_openrouter_chain(model)
        elif provider_type == "none":
            llm_provider = NoOpLLMProvider()
        else:
            raise ValueError(f"Unknown provider: {provider_type}")
    except Exception as e:
        logger.error("Failed to create LLM provider: %s", e)
        return None

    interest_provider = VaultInterestProvider(
        repo=surreal_repo,
        top_n=settings.classification_interest_top_n,
    )

    return ClassificationService(
        llm_provider=llm_provider,
        interest_provider=interest_provider,
        repo=surreal_repo,
        settings=settings,
    )


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Batch classify content with quality ratings and labels"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying them",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reclassify already-classified content",
    )
    parser.add_argument(
        "--content-type",
        type=str,
        default=None,
        help="Filter by content type (e.g., youtube, markdown)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum number of items to process (0 = unlimited)",
    )
    args = parser.parse_args()

    # Initialize MinIO
    logger.info("Connecting to MinIO at %s", settings.minio_url)
    minio_client = Minio(
        settings.minio_url,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    minio_storage = MinIOStorage(minio_client, settings.minio_bucket)

    # Initialize SurrealDB
    logger.info("Connecting to SurrealDB at %s", settings.surrealdb_url)
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
        logger.error("Failed to connect to SurrealDB: %s", e)
        return

    # Create classification service
    classification_service = _create_classification_service(surreal_repo)
    if not classification_service:
        logger.error("Classification service not available")
        return

    # Pre-cache interest profile once
    logger.info("Caching interest profile...")
    try:
        interests = await classification_service.interest_provider.get_interests()
        logger.info(
            "Interest profile: %d topics, %d tags, %d channels",
            len(interests.get("topics", [])),
            len(interests.get("tags", [])),
            len(interests.get("channels", [])),
        )
    except Exception as e:
        logger.warning("Failed to cache interest profile: %s", e)

    # Process content in batches
    stats = {"total": 0, "classified": 0, "skipped": 0, "failed": 0}
    start_time = datetime.now()
    offset = 0
    batch_size = 20
    batch_num = 1

    while True:
        if args.limit and stats["total"] >= args.limit:
            break

        logger.info("Fetching batch %d (offset=%d)", batch_num, offset)
        items, total = await surreal_repo.list_content(
            offset=offset,
            limit=batch_size,
            content_type=args.content_type,
        )

        if not items:
            break

        for item in items:
            if args.limit and stats["total"] >= args.limit:
                break

            stats["total"] += 1
            content_id = item.id

            if not content_id:
                logger.warning("Skipping item with no ID: %s", item.title)
                stats["skipped"] += 1
                continue

            # Skip already classified unless --force
            if not args.force and item.metadata.get("classification"):
                logger.info("  Skipping %s (already classified)", content_id)
                stats["skipped"] += 1
                continue

            logger.info(
                "Processing %s: %s (%s)",
                content_id,
                item.title,
                item.content_type,
            )

            if args.dry_run:
                logger.info("  [DRY RUN] Would classify content")
                stats["classified"] += 1
                continue

            # Download content text
            try:
                content_bytes = await minio_storage.download(item.file_path)
                content_text = content_bytes.decode("utf-8")
            except Exception as e:
                logger.error("  Failed to download content: %s", e)
                stats["failed"] += 1
                continue

            # Set status to processing before LLM call (enables resume on interrupt)
            await surreal_repo.update_content_classification_status(content_id, "processing")

            try:
                result = await classification_service.classify_content(
                    content_id=content_id,
                    content_text=content_text,
                    content_type=item.content_type,
                    title=item.title or "Untitled",
                )

                if result:
                    await surreal_repo.update_content_classification(
                        content_id, result.model_dump()
                    )
                    logger.info(
                        "  Classified: tier=%s score=%d labels=%s",
                        result.tier,
                        result.quality_score,
                        result.labels,
                    )
                    stats["classified"] += 1
                else:
                    await surreal_repo.update_content_classification_status(
                        content_id, "failed"
                    )
                    logger.warning("  Classification returned None")
                    stats["failed"] += 1

            except Exception as e:
                logger.error("  Classification failed: %s", e)
                await surreal_repo.update_content_classification_status(
                    content_id, "failed"
                )
                stats["failed"] += 1

        offset += batch_size
        batch_num += 1

        if offset >= total:
            break

    # Report stats
    duration = (datetime.now() - start_time).total_seconds()
    logger.info("=" * 60)
    logger.info("Classification complete!")
    logger.info("Duration: %.2f seconds", duration)
    logger.info("Total: %d", stats["total"])
    logger.info("Classified: %d", stats["classified"])
    logger.info("Skipped: %d", stats["skipped"])
    logger.info("Failed: %d", stats["failed"])
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
