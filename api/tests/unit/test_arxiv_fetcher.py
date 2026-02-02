"""Unit tests for ArXiv fetcher service."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from menos.services.entity_fetchers.arxiv import ArxivFetcher, PaperMetadata


# Sample XML response from arXiv API
MOCK_ARXIV_RESPONSE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>ArXiv Query</title>
  <entry>
    <id>http://arxiv.org/abs/2301.12345v1</id>
    <published>2023-01-29T10:30:45Z</published>
    <title>Attention Is All You Need</title>
    <summary>
      The dominant sequence transduction models are based on complex recurrent or
      convolutional neural networks that include an encoder and a decoder.
    </summary>
    <author>
      <name>Ashish Vaswani</name>
    </author>
    <author>
      <name>Noam Shazeer</name>
    </author>
    <link href="http://arxiv.org/abs/2301.12345v1" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2301.12345v1" rel="related" type="application/pdf"/>
    <link title="doi" href="http://dx.doi.org/10.1234/example.doi" rel="related"/>
  </entry>
</feed>"""

MOCK_ARXIV_RESPONSE_NO_DOI = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>ArXiv Query</title>
  <entry>
    <id>http://arxiv.org/abs/cs/0703110v1</id>
    <published>2007-03-22T15:20:30Z</published>
    <title>Old Paper Without DOI</title>
    <summary>This is an older paper from the cs archive without a DOI.</summary>
    <author>
      <name>John Doe</name>
    </author>
    <link href="http://arxiv.org/abs/cs/0703110v1" rel="alternate" type="text/html"/>
  </entry>
</feed>"""

MOCK_ARXIV_RESPONSE_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>ArXiv Query</title>
</feed>"""

MOCK_ARXIV_RESPONSE_MALFORMED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2301.99999v1</id>
  </entry>
</feed>"""


class TestPaperMetadata:
    """Tests for PaperMetadata dataclass."""

    def test_paper_metadata_creation(self):
        """Test creating PaperMetadata instance."""
        fetched_at = datetime.now()
        published_at = datetime(2023, 1, 29, 10, 30, 45)

        metadata = PaperMetadata(
            url="https://arxiv.org/abs/2301.12345",
            arxiv_id="2301.12345",
            title="Test Paper",
            authors=["Author One", "Author Two"],
            abstract="This is a test abstract.",
            published_at=published_at,
            doi="10.1234/example.doi",
            fetched_at=fetched_at,
        )

        assert metadata.url == "https://arxiv.org/abs/2301.12345"
        assert metadata.arxiv_id == "2301.12345"
        assert metadata.title == "Test Paper"
        assert metadata.authors == ["Author One", "Author Two"]
        assert metadata.abstract == "This is a test abstract."
        assert metadata.published_at == published_at
        assert metadata.doi == "10.1234/example.doi"
        assert metadata.fetched_at == fetched_at

    def test_paper_metadata_optional_fields_none(self):
        """Test PaperMetadata with optional fields as None."""
        metadata = PaperMetadata(
            url="https://arxiv.org/abs/2301.12345",
            arxiv_id="2301.12345",
            title="Test Paper",
            authors=[],
            abstract="Abstract",
            published_at=None,
            doi=None,
            fetched_at=datetime.now(),
        )

        assert metadata.published_at is None
        assert metadata.doi is None
        assert metadata.authors == []


class TestArxivFetcher:
    """Tests for ArxivFetcher service."""

    @pytest.mark.asyncio
    async def test_fetch_paper_success(self):
        """Test successful paper fetch with complete metadata."""
        fetcher = ArxivFetcher()

        mock_response = MagicMock()
        mock_response.text = MOCK_ARXIV_RESPONSE
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.get.return_value = mock_response

            metadata = await fetcher.fetch_paper("2301.12345")

        assert metadata is not None
        assert metadata.arxiv_id == "2301.12345"
        assert metadata.title == "Attention Is All You Need"
        assert "sequence transduction models" in metadata.abstract
        assert metadata.authors == ["Ashish Vaswani", "Noam Shazeer"]
        assert metadata.published_at == datetime(2023, 1, 29, 10, 30, 45, tzinfo=timezone.utc)
        assert metadata.doi == "10.1234/example.doi"
        assert metadata.url == "http://arxiv.org/abs/2301.12345v1"
        assert isinstance(metadata.fetched_at, datetime)

    @pytest.mark.asyncio
    async def test_fetch_paper_without_doi(self):
        """Test fetching paper without DOI."""
        fetcher = ArxivFetcher()

        mock_response = MagicMock()
        mock_response.text = MOCK_ARXIV_RESPONSE_NO_DOI
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.get.return_value = mock_response

            metadata = await fetcher.fetch_paper("cs/0703110")

        assert metadata is not None
        assert metadata.arxiv_id == "cs/0703110"
        assert metadata.title == "Old Paper Without DOI"
        assert metadata.doi is None
        assert metadata.published_at == datetime(2007, 3, 22, 15, 20, 30, tzinfo=timezone.utc)

    @pytest.mark.asyncio
    async def test_fetch_paper_not_found(self):
        """Test fetching non-existent paper returns None."""
        fetcher = ArxivFetcher()

        mock_response = MagicMock()
        mock_response.text = MOCK_ARXIV_RESPONSE_EMPTY
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.get.return_value = mock_response

            metadata = await fetcher.fetch_paper("9999.99999")

        assert metadata is None

    @pytest.mark.asyncio
    async def test_fetch_paper_malformed_response(self):
        """Test handling malformed XML response returns None."""
        fetcher = ArxivFetcher()

        mock_response = MagicMock()
        mock_response.text = MOCK_ARXIV_RESPONSE_MALFORMED
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.get.return_value = mock_response

            metadata = await fetcher.fetch_paper("2301.99999")

        assert metadata is None

    @pytest.mark.asyncio
    async def test_fetch_paper_http_error(self):
        """Test handling HTTP errors returns None."""
        fetcher = ArxivFetcher()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.get.side_effect = httpx.HTTPError("Network error")

            metadata = await fetcher.fetch_paper("2301.12345")

        assert metadata is None

    @pytest.mark.asyncio
    async def test_fetch_paper_timeout(self):
        """Test handling timeout errors returns None."""
        fetcher = ArxivFetcher()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.get.side_effect = httpx.TimeoutException("Request timeout")

            metadata = await fetcher.fetch_paper("2301.12345")

        assert metadata is None

    @pytest.mark.asyncio
    async def test_fetch_paper_invalid_xml(self):
        """Test handling invalid XML returns None."""
        fetcher = ArxivFetcher()

        mock_response = MagicMock()
        mock_response.text = "This is not XML"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.get.return_value = mock_response

            metadata = await fetcher.fetch_paper("2301.12345")

        assert metadata is None

    @pytest.mark.asyncio
    async def test_rate_limiting(self):
        """Test rate limiting between requests."""
        fetcher = ArxivFetcher()

        mock_response = MagicMock()
        mock_response.text = MOCK_ARXIV_RESPONSE
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.get.return_value = mock_response

            # First request - no delay
            start_time = datetime.now()
            await fetcher.fetch_paper("2301.12345")

            # Second request - should have delay
            await fetcher.fetch_paper("2301.12346")
            elapsed = (datetime.now() - start_time).total_seconds()

            # Should take at least the rate limit delay
            assert elapsed >= ArxivFetcher.RATE_LIMIT_DELAY

    @pytest.mark.asyncio
    async def test_api_request_params(self):
        """Test that API request includes correct parameters."""
        fetcher = ArxivFetcher()

        mock_response = MagicMock()
        mock_response.text = MOCK_ARXIV_RESPONSE
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.get.return_value = mock_response

            await fetcher.fetch_paper("2301.12345")

            # Verify API call was made with correct parameters
            mock_client_instance.get.assert_called_once()
            call_args = mock_client_instance.get.call_args
            assert call_args[0][0] == ArxivFetcher.API_BASE_URL
            assert call_args[1]["params"]["id_list"] == "2301.12345"

    @pytest.mark.asyncio
    async def test_whitespace_normalization(self):
        """Test that title and abstract whitespace is normalized."""
        # XML with extra whitespace
        xml_with_whitespace = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2301.12345v1</id>
    <published>2023-01-29T10:30:45Z</published>
    <title>
      Title With
      Multiple    Spaces
      And Newlines
    </title>
    <summary>
      Abstract with
      irregular   spacing
      and line breaks.
    </summary>
    <author>
      <name>Test Author</name>
    </author>
    <link href="http://arxiv.org/abs/2301.12345v1" rel="alternate" type="text/html"/>
  </entry>
</feed>"""

        fetcher = ArxivFetcher()

        mock_response = MagicMock()
        mock_response.text = xml_with_whitespace
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.get.return_value = mock_response

            metadata = await fetcher.fetch_paper("2301.12345")

        assert metadata is not None
        # Whitespace should be normalized
        assert metadata.title == "Title With Multiple Spaces And Newlines"
        assert metadata.abstract == "Abstract with irregular spacing and line breaks."

    @pytest.mark.asyncio
    async def test_old_arxiv_id_format(self):
        """Test handling old-style arXiv IDs (e.g., cs/0703110)."""
        fetcher = ArxivFetcher()

        mock_response = MagicMock()
        mock_response.text = MOCK_ARXIV_RESPONSE_NO_DOI
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.get.return_value = mock_response

            metadata = await fetcher.fetch_paper("cs/0703110")

        assert metadata is not None
        assert metadata.arxiv_id == "cs/0703110"
