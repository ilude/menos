"""Display URL classification statistics from SurrealDB.

Shows summary statistics about URL filtering results across all YouTube videos.

Usage:
    PYTHONPATH=. uv run python scripts/url_filter_status.py
"""

import asyncio
import sys

from menos.services.di import get_storage_context


async def show_status() -> None:
    """Query SurrealDB and display URL filter statistics."""
    async with get_storage_context() as (_minio, repo):
        # Get all YouTube content
        offset = 0
        batch_size = 50
        total_videos = 0
        videos_with_urls = 0
        videos_filtered = 0
        total_urls = 0
        content_urls = 0
        blocked_urls = 0

        while True:
            items, count = await repo.list_content(
                content_type="youtube", limit=batch_size, offset=offset
            )
            if not items:
                break

            for item in items:
                total_videos += 1
                metadata = item.metadata or {}

                # Check for URL filter results
                filter_results = metadata.get("url_filter_results")
                description_urls = metadata.get("description_urls", [])

                if description_urls:
                    videos_with_urls += 1
                    total_urls += len(description_urls)

                if filter_results:
                    videos_filtered += 1
                    content_urls += len(filter_results.get("content_urls", []))
                    blocked_urls += len(filter_results.get("blocked_urls", []))

            offset += batch_size
            if count < batch_size:
                break

        # Display summary
        print(f"\n{'=' * 60}")
        print("URL Filter Status")
        print(f"{'=' * 60}\n")

        print("Video Statistics:")
        print(f"  Total YouTube videos:    {total_videos}")
        print(f"  Videos with URLs:        {videos_with_urls}")
        print(f"  Videos filtered:         {videos_filtered}")

        unfiltered = videos_with_urls - videos_filtered
        if unfiltered > 0:
            print(f"  Videos not yet filtered: {unfiltered}")

        print("\nURL Statistics:")
        print(f"  Total URLs found:        {total_urls}")
        print(f"  Content URLs:            {content_urls}")
        print(f"  Blocked URLs:            {blocked_urls}")

        if total_urls > 0:
            content_pct = content_urls / total_urls * 100
            blocked_pct = blocked_urls / total_urls * 100
            unclassified = total_urls - content_urls - blocked_urls
            print(f"\n  Content rate:            {content_pct:.1f}%")
            print(f"  Blocked rate:            {blocked_pct:.1f}%")
            if unclassified > 0:
                print(f"  Unclassified:            {unclassified}")

        print(f"\n{'=' * 60}\n")


def main() -> None:
    """Main entry point."""
    try:
        asyncio.run(show_status())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)


if __name__ == "__main__":
    main()
