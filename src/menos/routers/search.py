"""Search endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query

from menos import database as db
from menos.models import SearchResponse, SearchResult

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=SearchResponse)
async def search_videos(
    q: Annotated[str, Query(description="Search query", min_length=1)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
):
    """Full-text search across all transcripts and summaries."""
    results = await db.search_videos(q, limit=limit)
    return SearchResponse(
        query=q,
        results=[SearchResult(**r) for r in results],
        total=len(results),
    )
