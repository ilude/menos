"""Search endpoints."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from menos.auth.dependencies import AuthenticatedKeyId
from menos.services.agent import AgentService
from menos.services.di import get_agent_service, get_surreal_repo
from menos.services.embeddings import EmbeddingService, get_embedding_service
from menos.services.storage import SurrealDBRepository

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


class AgenticSearchQuery(BaseModel):
    """Agentic search request."""

    query: str
    content_type: str | None = None
    limit: int = 10


class SourceReference(BaseModel):
    """Source document reference."""

    id: str
    content_type: str
    title: str | None
    score: float
    snippet: str | None = None


class TimingInfo(BaseModel):
    """Timing breakdown for agentic search."""

    expansion_ms: float
    retrieval_ms: float
    rerank_ms: float
    synthesis_ms: float
    total_ms: float


class AgenticSearchResponse(BaseModel):
    """Agentic search response."""

    query: str
    answer: str
    sources: list[SourceReference]
    timing: TimingInfo


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

    # Native SurrealDB vector search with cosine similarity
    # Returns chunks with their similarity scores directly
    search_results = surreal_repo.db.query(
        """
        SELECT text, content_id,
               vector::similarity::cosine(embedding, $embedding) AS score
        FROM chunk
        WHERE vector::similarity::cosine(embedding, $embedding) > 0.3
        ORDER BY score DESC
        LIMIT $limit
        """,
        {"embedding": query_embedding, "limit": body.limit},
    )

    # Handle SurrealDB v2 query result format
    chunks: list[dict] = []
    if search_results and isinstance(search_results, list) and len(search_results) > 0:
        result_item = search_results[0]
        # Handle both wrapped format {"result": [...]} and direct list format
        if isinstance(result_item, dict) and "result" in result_item:
            chunks = result_item["result"]
        elif isinstance(result_item, dict) and "score" in result_item:
            chunks = search_results

    # Group by content_id, keep best match per content
    best_per_content: dict[str, tuple[float, str]] = {}
    for chunk in chunks:
        content_id = str(chunk.get("content_id", ""))
        score = float(chunk.get("score", 0.0))
        text = chunk.get("text", "")
        if content_id and (
            content_id not in best_per_content
            or score > best_per_content[content_id][0]
        ):
            best_per_content[content_id] = (score, text)

    # Get content metadata for titles
    content_results = surreal_repo.db.query("SELECT * FROM content")
    id_to_meta: dict[str, dict] = {}
    content_list: list[dict] = []
    if content_results and isinstance(content_results, list) and len(content_results) > 0:
        result_item = content_results[0]
        if isinstance(result_item, dict) and "result" in result_item:
            content_list = result_item["result"]
        elif isinstance(result_item, dict) and "id" in result_item:
            content_list = content_results

    for content in content_list:
        rid = content.get("id")
        if hasattr(rid, "record_id"):
            rid = str(rid.record_id)
        elif hasattr(rid, "id"):
            rid = rid.id
        else:
            rid = str(rid)
        id_to_meta[rid] = {
            "title": content.get("title"),
            "content_type": content.get("content_type", "unknown"),
        }

    # Build results sorted by score
    sorted_results = sorted(
        best_per_content.items(),
        key=lambda x: x[1][0],
        reverse=True,
    )

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


@router.post("/agentic", response_model=AgenticSearchResponse)
async def agentic_search(
    body: AgenticSearchQuery,
    key_id: AuthenticatedKeyId,
    agent_service: AgentService = Depends(get_agent_service),
):
    """Agentic search with LLM-powered query expansion, reranking, and answer synthesis."""
    result = await agent_service.search(
        query=body.query,
        content_type=body.content_type,
        limit=body.limit,
    )

    sources = [SourceReference(**s) for s in result.sources]
    timing = TimingInfo(**result.timing)

    return AgenticSearchResponse(
        query=body.query,
        answer=result.answer,
        sources=sources,
        timing=timing,
    )
