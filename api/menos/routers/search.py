"""Search endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel

from menos.auth.dependencies import AuthenticatedKeyId

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
):
    """Semantic vector search across content."""
    # TODO: Implement with Ollama embeddings + SurrealDB HNSW
    return SearchResponse(
        query=body.query,
        results=[],
        total=0,
    )
