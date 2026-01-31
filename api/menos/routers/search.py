"""Search endpoints."""

import math

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from menos.auth.dependencies import AuthenticatedKeyId
from menos.services.di import get_surreal_repo
from menos.services.embeddings import EmbeddingService, get_embedding_service
from menos.services.storage import SurrealDBRepository

router = APIRouter(prefix="/search", tags=["search"])


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SearchQuery(BaseModel):
    """Search request."""

    query: str
    content_type: str | None = None
    limit: int = 20


class SearchResult(BaseModel):
    """Single search result."""

    id: str
    content_type: str
    title: str | None
    score: float
    snippet: str | None = None


class SearchResponse(BaseModel):
    """Search response."""

    query: str
    results: list[SearchResult]
    total: int


@router.post("", response_model=SearchResponse)
async def vector_search(
    body: SearchQuery,
    key_id: AuthenticatedKeyId,
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    surreal_repo: SurrealDBRepository = Depends(get_surreal_repo),
):
    """Semantic vector search across content."""
    # Generate query embedding
    query_embedding = await embedding_service.embed(body.query)

    # Fetch all chunks with embeddings from SurrealDB
    chunks = surreal_repo.db.query("SELECT text, content_id, embedding FROM chunk")

    # Calculate similarity scores
    scores: list[tuple[str, float, str]] = []
    for chunk in chunks:
        embedding = chunk.get("embedding")
        if embedding:
            sim = cosine_similarity(query_embedding, embedding)
            scores.append((str(chunk["content_id"]), sim, chunk["text"]))

    # Group by content_id, keep best match per content
    best_per_content: dict[str, tuple[float, str]] = {}
    for content_id, score, text in scores:
        if content_id not in best_per_content or score > best_per_content[content_id][0]:
            best_per_content[content_id] = (score, text)

    # Get content metadata for titles
    content_list = surreal_repo.db.query("SELECT * FROM content")
    id_to_meta: dict[str, dict] = {}
    for content in content_list:
        rid = content.get("id")
        if hasattr(rid, "record_id"):
            rid = str(rid.record_id)
        id_to_meta[str(rid)] = {
            "title": content.get("title"),
            "content_type": content.get("content_type", "unknown"),
        }

    # Build results sorted by score
    sorted_results = sorted(
        best_per_content.items(),
        key=lambda x: x[1][0],
        reverse=True,
    )[: body.limit]

    results = []
    for content_id, (score, text) in sorted_results:
        meta = id_to_meta.get(content_id, {})
        results.append(
            SearchResult(
                id=content_id,
                content_type=meta.get("content_type", "unknown"),
                title=meta.get("title"),
                score=round(score, 4),
                snippet=text[:200] if text else None,
            )
        )

    return SearchResponse(
        query=body.query,
        results=results,
        total=len(results),
    )
