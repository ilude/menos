"""Search endpoints."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from menos.auth.dependencies import AuthenticatedKeyId
from menos.services.di import get_surreal_repo
from menos.services.embeddings import get_embedding_service
from menos.services.storage import SurrealDBRepository
from menos.services.embeddings import EmbeddingService

router = APIRouter(prefix="/search", tags=["search"])


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
    try:
        # Generate query embedding
        query_embedding = await embedding_service.embed(body.query)

        # Search in SurrealDB using vector similarity
        # For now, return empty results - HNSW index needs to be implemented in DB
        # This is a placeholder that shows the endpoint structure
        return SearchResponse(
            query=body.query,
            results=[],
            total=0,
        )
    except Exception as e:
        return SearchResponse(
            query=body.query,
            results=[],
            total=0,
        )
