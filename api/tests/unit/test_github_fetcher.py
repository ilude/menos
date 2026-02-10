"""Unit tests for GitHub fetcher."""

from datetime import UTC, datetime

import httpx
import pytest
from pytest_httpx import HTTPXMock

from menos.services.entity_fetchers.github import GitHubFetcher, RepoMetadata


class TestGitHubFetcher:
    """Tests for GitHub repository metadata fetcher."""

    @pytest.fixture
    def fetcher(self) -> GitHubFetcher:
        """Create a GitHub fetcher without proxy."""
        return GitHubFetcher()

    @pytest.fixture
    def fetcher_with_proxy(self) -> GitHubFetcher:
        """Create a GitHub fetcher with proxy credentials."""
        return GitHubFetcher(proxy_username="test_user", proxy_password="test_pass")

    @pytest.fixture
    def mock_repo_response(self) -> dict:
        """Mock GitHub API response for a repository."""
        return {
            "html_url": "https://github.com/python/cpython",
            "owner": {"login": "python"},
            "name": "cpython",
            "description": "The Python programming language",
            "stargazers_count": 50000,
            "language": "Python",
            "topics": ["python", "programming", "cpython"],
        }

    async def test_fetch_repo_success(
        self, fetcher: GitHubFetcher, mock_repo_response: dict, httpx_mock: HTTPXMock
    ):
        """Test successful repository fetch."""
        httpx_mock.add_response(
            url="https://api.github.com/repos/python/cpython",
            json=mock_repo_response,
        )

        result = await fetcher.fetch_repo("python", "cpython")

        assert result is not None
        assert isinstance(result, RepoMetadata)
        assert result.url == "https://github.com/python/cpython"
        assert result.owner == "python"
        assert result.name == "cpython"
        assert result.description == "The Python programming language"
        assert result.stars == 50000
        assert result.language == "Python"
        assert result.topics == ["python", "programming", "cpython"]
        assert isinstance(result.fetched_at, datetime)
        assert result.fetched_at.tzinfo == UTC

    async def test_fetch_repo_not_found(self, fetcher: GitHubFetcher, httpx_mock: HTTPXMock):
        """Test repository not found returns None."""
        httpx_mock.add_response(
            url="https://api.github.com/repos/nonexistent/repo",
            status_code=404,
        )

        result = await fetcher.fetch_repo("nonexistent", "repo")

        assert result is None

    async def test_fetch_repo_minimal_data(
        self, fetcher: GitHubFetcher, httpx_mock: HTTPXMock
    ):
        """Test repository with minimal data (no description, language, topics)."""
        mock_response = {
            "html_url": "https://github.com/test/minimal",
            "owner": {"login": "test"},
            "name": "minimal",
        }

        httpx_mock.add_response(
            url="https://api.github.com/repos/test/minimal",
            json=mock_response,
        )

        result = await fetcher.fetch_repo("test", "minimal")

        assert result is not None
        assert result.url == "https://github.com/test/minimal"
        assert result.owner == "test"
        assert result.name == "minimal"
        assert result.description is None
        assert result.stars == 0
        assert result.language is None
        assert result.topics == []

    async def test_proxy_configuration(self, fetcher_with_proxy: GitHubFetcher):
        """Test proxy configuration is set correctly."""
        assert fetcher_with_proxy.proxy is not None
        assert isinstance(fetcher_with_proxy.proxy, httpx.Proxy)
        assert "p.webshare.io" in str(fetcher_with_proxy.proxy.url)
        assert fetcher_with_proxy.proxy.raw_auth == (b"test_user", b"test_pass")

    async def test_no_proxy_configuration(self, fetcher: GitHubFetcher):
        """Test fetcher without proxy has no proxy configuration."""
        assert fetcher.proxy is None

    async def test_retry_on_rate_limit(self, fetcher: GitHubFetcher, httpx_mock: HTTPXMock):
        """Test retry logic on rate limit (403)."""
        httpx_mock.add_response(
            url="https://api.github.com/repos/python/cpython",
            status_code=403,
            text="API rate limit exceeded",
        )
        httpx_mock.add_response(
            url="https://api.github.com/repos/python/cpython",
            json={
                "html_url": "https://github.com/python/cpython",
                "owner": {"login": "python"},
                "name": "cpython",
                "stargazers_count": 50000,
            },
        )

        result = await fetcher.fetch_repo("python", "cpython")

        assert result is not None
        assert result.name == "cpython"

    async def test_retry_on_connection_error(
        self, fetcher: GitHubFetcher, httpx_mock: HTTPXMock, mock_repo_response: dict
    ):
        """Test retry logic on connection error."""
        httpx_mock.add_exception(httpx.ConnectError("Connection failed"))
        httpx_mock.add_response(
            url="https://api.github.com/repos/python/cpython",
            json=mock_repo_response,
        )

        result = await fetcher.fetch_repo("python", "cpython")

        assert result is not None
        assert result.name == "cpython"

    async def test_retry_on_timeout(
        self, fetcher: GitHubFetcher, httpx_mock: HTTPXMock, mock_repo_response: dict
    ):
        """Test retry logic on timeout."""
        httpx_mock.add_exception(httpx.TimeoutException("Request timeout"))
        httpx_mock.add_response(
            url="https://api.github.com/repos/python/cpython",
            json=mock_repo_response,
        )

        result = await fetcher.fetch_repo("python", "cpython")

        assert result is not None
        assert result.name == "cpython"

    async def test_exhausted_retries_raises_error(
        self, fetcher: GitHubFetcher, httpx_mock: HTTPXMock
    ):
        """Test that exhausted retries raise HTTPError."""
        for _ in range(fetcher.MAX_RETRIES):
            httpx_mock.add_exception(httpx.ConnectError("Connection failed"))

        with pytest.raises(httpx.ConnectError):
            await fetcher.fetch_repo("python", "cpython")

    async def test_server_error_raises_exception(
        self, fetcher: GitHubFetcher, httpx_mock: HTTPXMock
    ):
        """Test that server errors (500) raise exceptions."""
        httpx_mock.add_response(
            url="https://api.github.com/repos/python/cpython",
            status_code=500,
            text="Internal Server Error",
        )

        with pytest.raises(httpx.HTTPStatusError):
            await fetcher.fetch_repo("python", "cpython")

    async def test_fetch_repo_with_zero_stars(
        self, fetcher: GitHubFetcher, httpx_mock: HTTPXMock
    ):
        """Test repository with zero stars."""
        mock_response = {
            "html_url": "https://github.com/test/newrepo",
            "owner": {"login": "test"},
            "name": "newrepo",
            "stargazers_count": 0,
        }

        httpx_mock.add_response(
            url="https://api.github.com/repos/test/newrepo",
            json=mock_response,
        )

        result = await fetcher.fetch_repo("test", "newrepo")

        assert result is not None
        assert result.stars == 0

    async def test_fetch_repo_with_empty_topics(
        self, fetcher: GitHubFetcher, httpx_mock: HTTPXMock
    ):
        """Test repository with empty topics list."""
        mock_response = {
            "html_url": "https://github.com/test/notopics",
            "owner": {"login": "test"},
            "name": "notopics",
            "topics": [],
        }

        httpx_mock.add_response(
            url="https://api.github.com/repos/test/notopics",
            json=mock_response,
        )

        result = await fetcher.fetch_repo("test", "notopics")

        assert result is not None
        assert result.topics == []

    async def test_url_construction(self, fetcher: GitHubFetcher, httpx_mock: HTTPXMock):
        """Test that URL is constructed correctly."""
        httpx_mock.add_response(
            url="https://api.github.com/repos/owner123/repo-name",
            json={
                "html_url": "https://github.com/owner123/repo-name",
                "owner": {"login": "owner123"},
                "name": "repo-name",
            },
        )

        result = await fetcher.fetch_repo("owner123", "repo-name")

        assert result is not None
        assert result.owner == "owner123"
        assert result.name == "repo-name"


class TestRepoMetadata:
    """Tests for RepoMetadata dataclass."""

    def test_repo_metadata_creation(self):
        """Test creating RepoMetadata instance."""
        now = datetime.now(UTC)
        metadata = RepoMetadata(
            url="https://github.com/python/cpython",
            owner="python",
            name="cpython",
            description="The Python programming language",
            stars=50000,
            language="Python",
            topics=["python", "programming"],
            fetched_at=now,
        )

        assert metadata.url == "https://github.com/python/cpython"
        assert metadata.owner == "python"
        assert metadata.name == "cpython"
        assert metadata.description == "The Python programming language"
        assert metadata.stars == 50000
        assert metadata.language == "Python"
        assert metadata.topics == ["python", "programming"]
        assert metadata.fetched_at == now

    def test_repo_metadata_with_none_values(self):
        """Test RepoMetadata with None values for optional fields."""
        now = datetime.now(UTC)
        metadata = RepoMetadata(
            url="https://github.com/test/repo",
            owner="test",
            name="repo",
            description=None,
            stars=0,
            language=None,
            topics=[],
            fetched_at=now,
        )

        assert metadata.description is None
        assert metadata.language is None
        assert metadata.topics == []
        assert metadata.stars == 0
