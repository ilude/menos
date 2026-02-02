"""Semantic Scholar paper metadata fetching service."""

import asyncio
from datetime import datetime
from difflib import SequenceMatcher

import httpx

from .arxiv import PaperMetadata


class SemanticScholarFetcher:
    """Service for fetching paper metadata from Semantic Scholar API."""

    API_BASE_URL = "https://api.semanticscholar.org/graph/v1"
    RATE_LIMIT_DELAY = 3.0  # 100 requests per 5 minutes = 3 seconds between requests
    TIMEOUT = 30.0
    TITLE_MATCH_THRESHOLD = 0.8  # Minimum similarity score for title matching

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize Semantic Scholar fetcher.

        Args:
            api_key: Optional Semantic Scholar API key for higher rate limits
        """
        self.api_key = api_key
        self._last_request_time: float | None = None

    async def _rate_limit(self) -> None:
        """Apply rate limiting between requests."""
        if self._last_request_time is not None:
            elapsed = asyncio.get_event_loop().time() - self._last_request_time
            if elapsed < self.RATE_LIMIT_DELAY:
                await asyncio.sleep(self.RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()

    def _normalize_title(self, title: str) -> str:
        """Normalize title for comparison."""
        return title.lower().strip()

    def _title_similarity(self, title1: str, title2: str) -> float:
        """Calculate similarity score between two titles.

        Args:
            title1: First title
            title2: Second title

        Returns:
            Similarity score between 0.0 and 1.0
        """
        normalized1 = self._normalize_title(title1)
        normalized2 = self._normalize_title(title2)
        return SequenceMatcher(None, normalized1, normalized2).ratio()

    def _build_paper_url(self, paper: dict) -> str:
        """Build paper URL from paper data.

        Priority: arxivId > paperId
        """
        arxiv_id = paper.get("externalIds", {}).get("ArXiv") or paper.get("arxivId")
        if arxiv_id:
            return f"https://arxiv.org/abs/{arxiv_id}"
        paper_id = paper.get("paperId")
        if paper_id:
            return f"https://www.semanticscholar.org/paper/{paper_id}"
        return ""

    def _extract_arxiv_id(self, paper: dict) -> str:
        """Extract arXiv ID from paper data."""
        return paper.get("externalIds", {}).get("ArXiv") or paper.get("arxivId") or ""

    def _parse_authors(self, paper: dict) -> list[str]:
        """Extract author names from paper data."""
        authors = []
        for author in paper.get("authors", []):
            name = author.get("name")
            if name:
                authors.append(name)
        return authors

    def _parse_year_to_datetime(self, year: int | None) -> datetime | None:
        """Convert year to datetime (January 1st of that year)."""
        if year is None:
            return None
        try:
            return datetime(year, 1, 1)
        except (ValueError, TypeError):
            return None

    async def search_paper(self, title: str) -> PaperMetadata | None:
        """Search for a paper by title and return metadata if found.

        Args:
            title: Paper title to search for

        Returns:
            PaperMetadata if a high-confidence match is found, None otherwise

        Example:
            >>> fetcher = SemanticScholarFetcher()
            >>> metadata = await fetcher.search_paper("Attention Is All You Need")
            >>> if metadata:
            ...     print(f"Found: {metadata.title}")
        """
        await self._rate_limit()

        try:
            headers = {}
            if self.api_key:
                headers["x-api-key"] = self.api_key

            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                response = await client.get(
                    f"{self.API_BASE_URL}/paper/search",
                    params={
                        "query": title,
                        "fields": "paperId,title,authors,abstract,externalIds,year",
                        "limit": 1,
                    },
                    headers=headers,
                )
                response.raise_for_status()

                data = response.json()
                papers = data.get("data", [])

                if not papers:
                    return None

                # Get top result
                paper = papers[0]

                # Verify title similarity
                result_title = paper.get("title", "")
                if not result_title:
                    return None

                similarity = self._title_similarity(title, result_title)
                if similarity < self.TITLE_MATCH_THRESHOLD:
                    return None

                # Extract metadata
                abstract = paper.get("abstract") or ""
                authors = self._parse_authors(paper)
                year = paper.get("year")
                published_at = self._parse_year_to_datetime(year)
                doi = paper.get("externalIds", {}).get("DOI")
                arxiv_id = self._extract_arxiv_id(paper)
                url = self._build_paper_url(paper)

                return PaperMetadata(
                    url=url,
                    arxiv_id=arxiv_id,
                    title=result_title,
                    authors=authors,
                    abstract=abstract,
                    published_at=published_at,
                    doi=doi,
                    fetched_at=datetime.now(),
                )

        except (httpx.HTTPError, KeyError, Exception):
            return None
