"""ArXiv paper metadata fetching service."""

import asyncio
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime

import httpx


@dataclass
class PaperMetadata:
    """ArXiv paper metadata."""

    url: str
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    published_at: datetime | None
    doi: str | None
    fetched_at: datetime


class ArxivFetcher:
    """Service for fetching ArXiv paper metadata using ArXiv API."""

    API_BASE_URL = "http://export.arxiv.org/api/query"
    RATE_LIMIT_DELAY = 3.0  # 3 seconds between requests per arXiv API guidelines
    TIMEOUT = 30.0

    # ArXiv Atom namespace
    ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

    def __init__(self) -> None:
        """Initialize ArXiv fetcher."""
        self._last_request_time: float | None = None

    async def _rate_limit(self) -> None:
        """Apply rate limiting between requests."""
        if self._last_request_time is not None:
            elapsed = asyncio.get_event_loop().time() - self._last_request_time
            if elapsed < self.RATE_LIMIT_DELAY:
                await asyncio.sleep(self.RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()

    def _parse_authors(self, entry: ET.Element) -> list[str]:
        """Extract authors from entry XML."""
        authors = []
        for author in entry.findall("atom:author", self.ATOM_NS):
            name_elem = author.find("atom:name", self.ATOM_NS)
            if name_elem is not None and name_elem.text:
                authors.append(name_elem.text.strip())
        return authors

    def _parse_doi(self, entry: ET.Element) -> str | None:
        """Extract DOI from entry XML if available."""
        for link in entry.findall("atom:link", self.ATOM_NS):
            title = link.get("title")
            if title == "doi":
                href = link.get("href")
                if href and href.startswith("http://dx.doi.org/"):
                    return href.replace("http://dx.doi.org/", "")
        return None

    def _parse_published_date(self, entry: ET.Element) -> datetime | None:
        """Extract published date from entry XML."""
        published_elem = entry.find("atom:published", self.ATOM_NS)
        if published_elem is not None and published_elem.text:
            try:
                # arXiv uses ISO 8601 format: 2023-11-17T10:30:45Z
                return datetime.fromisoformat(published_elem.text.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    async def fetch_paper(self, arxiv_id: str) -> PaperMetadata | None:
        """Fetch metadata for an ArXiv paper.

        Args:
            arxiv_id: ArXiv paper ID (e.g., "2301.12345" or "cs/0703110")

        Returns:
            PaperMetadata if successful, None if error occurs

        Example:
            >>> fetcher = ArxivFetcher()
            >>> metadata = await fetcher.fetch_paper("2301.12345")
            >>> if metadata:
            ...     print(f"Title: {metadata.title}")
        """
        await self._rate_limit()

        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                response = await client.get(
                    self.API_BASE_URL,
                    params={"id_list": arxiv_id},
                )
                response.raise_for_status()

                # Parse XML response
                root = ET.fromstring(response.text)

                # Find the entry element
                entry = root.find("atom:entry", self.ATOM_NS)
                if entry is None:
                    # No results found
                    return None

                # Extract title
                title_elem = entry.find("atom:title", self.ATOM_NS)
                if title_elem is None or not title_elem.text:
                    return None
                title = " ".join(title_elem.text.split())  # Normalize whitespace

                # Extract abstract
                summary_elem = entry.find("atom:summary", self.ATOM_NS)
                if summary_elem is None or not summary_elem.text:
                    return None
                abstract = " ".join(summary_elem.text.split())  # Normalize whitespace

                # Extract paper URL
                paper_url = f"https://arxiv.org/abs/{arxiv_id}"
                for link in entry.findall("atom:link", self.ATOM_NS):
                    if link.get("type") == "text/html":
                        href = link.get("href")
                        if href:
                            paper_url = href
                        break

                # Extract optional fields
                authors = self._parse_authors(entry)
                published_at = self._parse_published_date(entry)
                doi = self._parse_doi(entry)

                return PaperMetadata(
                    url=paper_url,
                    arxiv_id=arxiv_id,
                    title=title,
                    authors=authors,
                    abstract=abstract,
                    published_at=published_at,
                    doi=doi,
                    fetched_at=datetime.now(),
                )

        except (httpx.HTTPError, ET.ParseError, Exception):
            # Return None on any error
            return None
