"""Semantic search for YouTube videos in SurrealDB.

Usage:
    PYTHONPATH=. uv run python scripts/search_videos.py "machine learning tutorial"
    PYTHONPATH=. uv run python scripts/search_videos.py "AI agents" --limit 20
"""

import argparse
import asyncio
import sys

from menos.services.di import get_storage_context
from menos.services.embeddings import get_embedding_service


async def search_videos(query: str, limit: int = 10) -> None:
    """Search for videos using semantic similarity."""
    print(f"\n{'=' * 80}")
    print("Semantic Video Search")
    print(f"{'=' * 80}")
    print(f"Query: '{query}'")
    print(f"Limit: {limit}")
    print()

    # Generate query embedding
    embedding_service = get_embedding_service()
    try:
        print("Generating embedding...")
        query_embedding = await embedding_service.embed_query(query)
    except Exception as e:
        print(f"\nEmbedding generation failed: {e}")
        print("Make sure Ollama is running.")
        return
    finally:
        await embedding_service.close()

    async with get_storage_context() as (_minio, repo):
        # Run vector similarity search
        search_results = repo.db.query(
            """
            SELECT text, content_id,
                   vector::similarity::cosine(embedding, $embedding) AS score
            FROM chunk
            WHERE vector::similarity::cosine(embedding, $embedding) > 0.3
            ORDER BY score DESC
            LIMIT $limit
            """,
            {"embedding": query_embedding, "limit": limit * 3},
        )

        chunks = repo._parse_query_result(search_results)

        if not chunks:
            print(f"No results found for '{query}'\n")
            return

        # Group by content_id, keep best score per content
        best_by_content: dict[str, dict] = {}
        for chunk in chunks:
            content_id = chunk.get("content_id")
            if hasattr(content_id, "id"):
                content_id = content_id.id
            elif isinstance(content_id, str) and ":" in content_id:
                content_id = content_id.split(":")[-1]

            score = chunk.get("score", 0.0)
            if content_id not in best_by_content or score > best_by_content[content_id]["score"]:
                best_by_content[content_id] = {"content_id": content_id, "score": score}

        # Sort by score and limit
        ranked = sorted(best_by_content.values(), key=lambda x: x["score"], reverse=True)
        ranked = ranked[:limit]

        # Fetch content metadata for matched IDs
        print(f"\nFound {len(ranked)} results:\n")
        print(f"{'=' * 80}\n")

        for i, result in enumerate(ranked, 1):
            content_id = result["content_id"]
            score = result["score"]

            content = await repo.get_content(content_id)
            if not content:
                continue

            title = (content.title or "Unknown")[:60]
            video_id = (
                content.metadata.get("video_id", "unknown") if content.metadata else "unknown"
            )
            channel = (
                content.metadata.get("channel_title", "Unknown")
                if content.metadata
                else "Unknown"
            )

            print(f"[{i}] {title}")
            print(f"    Score: {score:.4f}")
            print(f"    ID: {video_id}")
            print(f"    Channel: {channel}")
            print(f"    URL: https://youtube.com/watch?v={video_id}")
            print()

        print(f"{'=' * 80}\n")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Semantic search for YouTube videos in SurrealDB"
    )
    parser.add_argument(
        "query",
        help="Search query string (e.g., 'machine learning tutorial')",
    )
    parser.add_argument(
        "--limit", "-l", type=int, default=10,
        help="Maximum number of results (default: 10)",
    )

    args = parser.parse_args()

    try:
        asyncio.run(search_videos(args.query, args.limit))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)


if __name__ == "__main__":
    main()
