"""Unit tests for Semantic Scholar fetcher."""

from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from menos.services.entity_fetchers.semantic_scholar import SemanticScholarFetcher


class TestSemanticScholarFetcher:
    """Tests for Semantic Scholar paper fetcher."""

    @pytest.fixture
    def fetcher(self):
        """Create fetcher instance."""
        return SemanticScholarFetcher()

    @pytest.fixture
    def fetcher_with_key(self):
        """Create fetcher instance with API key."""
        return SemanticScholarFetcher(api_key="test-api-key")

    @pytest.fixture
    def mock_paper_response(self):
        """Mock Semantic Scholar API response with paper data."""
        return {
            "data": [
                {
                    "paperId": "abc123",
                    "title": "Attention Is All You Need",
                    "authors": [
                        {"name": "Ashish Vaswani"},
                        {"name": "Noam Shazeer"},
                    ],
                    "abstract": "The dominant sequence transduction models...",
                    "externalIds": {
                        "ArXiv": "1706.03762",
                        "DOI": "10.5555/3295222.3295349",
                    },
                    "year": 2017,
                }
            ]
        }

    @pytest.fixture
    def mock_empty_response(self):
        """Mock empty API response."""
        return {"data": []}

    def test_normalize_title(self, fetcher):
        """Test title normalization."""
        title = "  Attention Is All You Need  "
        normalized = fetcher._normalize_title(title)
        assert normalized == "attention is all you need"

    def test_title_similarity_exact_match(self, fetcher):
        """Test title similarity with exact match."""
        title1 = "Attention Is All You Need"
        title2 = "Attention Is All You Need"
        similarity = fetcher._title_similarity(title1, title2)
        assert similarity == 1.0

    def test_title_similarity_case_insensitive(self, fetcher):
        """Test title similarity is case insensitive."""
        title1 = "Attention Is All You Need"
        title2 = "attention is all you need"
        similarity = fetcher._title_similarity(title1, title2)
        assert similarity == 1.0

    def test_title_similarity_different_titles(self, fetcher):
        """Test title similarity with different titles."""
        title1 = "Attention Is All You Need"
        title2 = "BERT: Pre-training of Deep Bidirectional Transformers"
        similarity = fetcher._title_similarity(title1, title2)
        assert similarity < 0.5

    def test_title_similarity_slight_variation(self, fetcher):
        """Test title similarity with slight variation."""
        title1 = "Attention Is All You Need"
        title2 = "Attention is all you need!"
        similarity = fetcher._title_similarity(title1, title2)
        assert similarity > 0.9

    def test_build_paper_url_with_arxiv(self, fetcher):
        """Test building URL when arXiv ID is present."""
        paper = {
            "paperId": "abc123",
            "externalIds": {"ArXiv": "1706.03762"},
        }
        url = fetcher._build_paper_url(paper)
        assert url == "https://arxiv.org/abs/1706.03762"

    def test_build_paper_url_without_arxiv(self, fetcher):
        """Test building URL when only paper ID is present."""
        paper = {"paperId": "abc123", "externalIds": {}}
        url = fetcher._build_paper_url(paper)
        assert url == "https://www.semanticscholar.org/paper/abc123"

    def test_build_paper_url_with_legacy_arxiv_field(self, fetcher):
        """Test building URL with legacy arxivId field."""
        paper = {
            "paperId": "abc123",
            "arxivId": "1706.03762",
            "externalIds": {},
        }
        url = fetcher._build_paper_url(paper)
        assert url == "https://arxiv.org/abs/1706.03762"

    def test_extract_arxiv_id_from_external_ids(self, fetcher):
        """Test extracting arXiv ID from externalIds."""
        paper = {"externalIds": {"ArXiv": "1706.03762"}}
        arxiv_id = fetcher._extract_arxiv_id(paper)
        assert arxiv_id == "1706.03762"

    def test_extract_arxiv_id_from_legacy_field(self, fetcher):
        """Test extracting arXiv ID from legacy arxivId field."""
        paper = {"arxivId": "1706.03762", "externalIds": {}}
        arxiv_id = fetcher._extract_arxiv_id(paper)
        assert arxiv_id == "1706.03762"

    def test_extract_arxiv_id_missing(self, fetcher):
        """Test extracting arXiv ID when not present."""
        paper = {"externalIds": {}}
        arxiv_id = fetcher._extract_arxiv_id(paper)
        assert arxiv_id == ""

    def test_parse_authors(self, fetcher):
        """Test parsing author names."""
        paper = {
            "authors": [
                {"name": "Ashish Vaswani"},
                {"name": "Noam Shazeer"},
                {"name": "Niki Parmar"},
            ]
        }
        authors = fetcher._parse_authors(paper)
        assert authors == ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"]

    def test_parse_authors_empty(self, fetcher):
        """Test parsing when no authors present."""
        paper = {"authors": []}
        authors = fetcher._parse_authors(paper)
        assert authors == []

    def test_parse_authors_missing_names(self, fetcher):
        """Test parsing authors with missing name fields."""
        paper = {"authors": [{"name": "Author 1"}, {}, {"name": "Author 2"}]}
        authors = fetcher._parse_authors(paper)
        assert authors == ["Author 1", "Author 2"]

    def test_parse_year_to_datetime(self, fetcher):
        """Test converting year to datetime."""
        result = fetcher._parse_year_to_datetime(2017)
        assert result == datetime(2017, 1, 1)

    def test_parse_year_to_datetime_none(self, fetcher):
        """Test converting None year."""
        result = fetcher._parse_year_to_datetime(None)
        assert result is None

    def test_parse_year_to_datetime_invalid(self, fetcher):
        """Test converting invalid year."""
        result = fetcher._parse_year_to_datetime(99999)
        assert result is None

    @pytest.mark.asyncio
    async def test_search_paper_success(self, fetcher, mock_paper_response):
        """Test successful paper search."""
        mock_response = Mock()
        mock_response.json.return_value = mock_paper_response
        mock_response.raise_for_status = Mock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.get.return_value = mock_response

            result = await fetcher.search_paper("Attention Is All You Need")

        assert result is not None
        assert result.title == "Attention Is All You Need"
        assert result.arxiv_id == "1706.03762"
        assert result.doi == "10.5555/3295222.3295349"
        assert result.authors == ["Ashish Vaswani", "Noam Shazeer"]
        assert result.abstract == "The dominant sequence transduction models..."
        assert result.url == "https://arxiv.org/abs/1706.03762"
        assert result.published_at == datetime(2017, 1, 1)
        assert isinstance(result.fetched_at, datetime)

    @pytest.mark.asyncio
    async def test_search_paper_with_api_key(self, fetcher_with_key, mock_paper_response):
        """Test search includes API key in headers."""
        mock_response = Mock()
        mock_response.json.return_value = mock_paper_response
        mock_response.raise_for_status = Mock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.get.return_value = mock_response

            await fetcher_with_key.search_paper("Attention Is All You Need")

            call_kwargs = mock_client_instance.get.call_args.kwargs
            assert "headers" in call_kwargs
            assert call_kwargs["headers"]["x-api-key"] == "test-api-key"

    @pytest.mark.asyncio
    async def test_search_paper_no_results(self, fetcher, mock_empty_response):
        """Test search with no results."""
        mock_response = Mock()
        mock_response.json.return_value = mock_empty_response
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.get.return_value = mock_response

            result = await fetcher.search_paper("Nonexistent Paper Title")

        assert result is None

    @pytest.mark.asyncio
    async def test_search_paper_low_similarity(self, fetcher):
        """Test search rejects low similarity matches."""
        mock_response_data = {
            "data": [
                {
                    "paperId": "xyz789",
                    "title": "Completely Different Paper Title",
                    "authors": [{"name": "Author"}],
                    "abstract": "Abstract text",
                    "externalIds": {},
                    "year": 2020,
                }
            ]
        }

        mock_response = Mock()
        mock_response.json.return_value = mock_response_data
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.get.return_value = mock_response

            result = await fetcher.search_paper("Attention Is All You Need")

        assert result is None

    @pytest.mark.asyncio
    async def test_search_paper_missing_title(self, fetcher):
        """Test search with missing title in response."""
        mock_response_data = {
            "data": [
                {
                    "paperId": "abc123",
                    "authors": [{"name": "Author"}],
                    "abstract": "Abstract",
                    "externalIds": {},
                }
            ]
        }

        mock_response = Mock()
        mock_response.json.return_value = mock_response_data
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.get.return_value = mock_response

            result = await fetcher.search_paper("Some Title")

        assert result is None

    @pytest.mark.asyncio
    async def test_search_paper_http_error(self, fetcher):
        """Test search handles HTTP errors."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.get.side_effect = httpx.HTTPError("Network error")

            result = await fetcher.search_paper("Attention Is All You Need")

        assert result is None

    @pytest.mark.asyncio
    async def test_search_paper_invalid_json(self, fetcher):
        """Test search handles invalid JSON response."""
        mock_response = Mock()
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.get.return_value = mock_response

            result = await fetcher.search_paper("Some Title")

        assert result is None

    @pytest.mark.asyncio
    async def test_rate_limiting(self, fetcher):
        """Test rate limiting delays subsequent requests."""
        mock_response_data = {"data": []}

        mock_response = Mock()
        mock_response.json.return_value = mock_response_data
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.get.return_value = mock_response

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await fetcher.search_paper("Paper 1")
                await fetcher.search_paper("Paper 2")

                mock_sleep.assert_called()
