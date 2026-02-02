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
    tags: list[str] | None = None
    entities: list[str] | None = None  # Entity IDs to filter by
    entity_types: list[str] | None = None  # Filter by entity type
    topics: list[str] | None = None  # Filter by topic hierarchy (e.g., "AI > LLMs")
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
    """Semantic vector search across content.

    Supports filtering by:
    - content_type: Type of content (youtube, markdown, etc.)
    - tags: Content must have ALL specified tags
    - entities: Content must be linked to ALL specified entity IDs
    - entity_types: Content must have entities of specified types
    - topics: Content must discuss topics matching the hierarchy pattern
    """
    # Generate query embedding
    query_embedding = await embedding_service.embed_query(body.query)

    # Build WHERE clause with tag filtering
    where_clause = "WHERE vector::similarity::cosine(embedding, $embedding) > 0.3"
    params = {"embedding": query_embedding, "limit": body.limit}

    if body.tags:
        where_clause += " AND content_id.tags CONTAINSALL $tags"
        params["tags"] = body.tags

    # Native SurrealDB vector search with cosine similarity
    search_results = surreal_repo.db.query(
        f"""
        SELECT text, content_id,
               vector::similarity::cosine(embedding, $embedding) AS score
        FROM chunk
        {where_clause}
        ORDER BY score DESC
        LIMIT $limit
        """,
        params,
    )

    # Handle SurrealDB v2 query result format
    chunks: list[dict] = []
    if search_results and isinstance(search_results, list) and len(search_results) > 0:
        result_item = search_results[0]
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

    # Apply entity filters if specified
    if body.entities or body.entity_types or body.topics:
        filtered_content = await _filter_by_entities(
            surreal_repo,
            list(best_per_content.keys()),
            body.entities,
            body.entity_types,
            body.topics,
        )
        best_per_content = {
            k: v for k, v in best_per_content.items() if k in filtered_content
        }

    # Get content metadata only for matched IDs
    id_to_meta: dict[str, dict] = {}
    content_list: list[dict] = []

    content_ids = list(best_per_content.keys())
    if content_ids:
        content_refs = [f"content:{cid}" for cid in content_ids]
        content_results = surreal_repo.db.query(
            "SELECT * FROM content WHERE id IN $ids",
            {"ids": content_refs}
        )

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


async def _filter_by_entities(
    surreal_repo: SurrealDBRepository,
    content_ids: list[str],
    entity_ids: list[str] | None,
    entity_types: list[str] | None,
    topics: list[str] | None,
) -> set[str]:
    """Filter content IDs by entity constraints.

    Args:
        surreal_repo: Database repository
        content_ids: Content IDs to filter
        entity_ids: Must be linked to ALL these entities
        entity_types: Must have entities of these types
        topics: Must discuss topics matching these patterns

    Returns:
        Set of content IDs that match all constraints
    """
    if not content_ids:
        return set()

    matching = set(content_ids)

    # Filter by specific entity IDs
    if entity_ids:
        entity_refs = [f"entity:{eid}" for eid in entity_ids]
        for entity_ref in entity_refs:
            result = surreal_repo.db.query(
                """
                SELECT content_id FROM content_entity
                WHERE entity_id = $entity_id AND content_id IN $content_ids
                """,
                {
                    "entity_id": entity_ref,
                    "content_ids": [f"content:{cid}" for cid in matching],
                },
            )
            raw_items = surreal_repo._parse_query_result(result)
            matched_content = set()
            for item in raw_items:
                cid = item.get("content_id")
                if hasattr(cid, "id"):
                    cid = cid.id
                else:
                    cid = str(cid).split(":")[-1]
                matched_content.add(cid)
            matching &= matched_content

    # Filter by entity types
    if entity_types and matching:
        result = surreal_repo.db.query(
            """
            SELECT content_id FROM content_entity
            WHERE content_id IN $content_ids
            AND entity_id.entity_type IN $entity_types
            """,
            {
                "content_ids": [f"content:{cid}" for cid in matching],
                "entity_types": entity_types,
            },
        )
        raw_items = surreal_repo._parse_query_result(result)
        matched_content = set()
        for item in raw_items:
            cid = item.get("content_id")
            if hasattr(cid, "id"):
                cid = cid.id
            else:
                cid = str(cid).split(":")[-1]
            matched_content.add(cid)
        matching &= matched_content

    # Filter by topics (partial hierarchy match)
    if topics and matching:
        for topic_pattern in topics:
            # Parse topic hierarchy pattern (e.g., "AI > LLMs")
            hierarchy = [p.strip() for p in topic_pattern.split(">")]

            result = surreal_repo.db.query(
                """
                SELECT content_id FROM content_entity
                WHERE content_id IN $content_ids
                AND entity_id.entity_type = 'topic'
                AND entity_id.hierarchy CONTAINSALL $hierarchy
                """,
                {
                    "content_ids": [f"content:{cid}" for cid in matching],
                    "hierarchy": hierarchy,
                },
            )
            raw_items = surreal_repo._parse_query_result(result)
            matched_content = set()
            for item in raw_items:
                cid = item.get("content_id")
                if hasattr(cid, "id"):
                    cid = cid.id
                else:
                    cid = str(cid).split(":")[-1]
                matched_content.add(cid)
            matching &= matched_content

    return matching


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
