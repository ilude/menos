"""GitHub repository metadata fetcher."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx


@dataclass
class RepoMetadata:
    """GitHub repository metadata."""

    url: str
    owner: str
    name: str
    description: str | None
    stars: int
    language: str | None
    topics: list[str]
    fetched_at: datetime


class GitHubFetcher:
    """Fetches GitHub repository metadata via Webshare proxy."""

    GITHUB_API_BASE = "https://api.github.com"
    MAX_RETRIES = 3
    INITIAL_RETRY_DELAY = 1.0
    MAX_RETRY_DELAY = 16.0

    def __init__(
        self,
        proxy_username: str,
        proxy_password: str,
        timeout: float = 10.0,
    ):
        """Initialize GitHub fetcher.

        Args:
            proxy_username: Webshare proxy username
            proxy_password: Webshare proxy password
            timeout: HTTP request timeout in seconds
        """
        self.timeout = timeout
        proxy_url = f"http://{proxy_username}:{proxy_password}@p.webshare.io:80"
        self.proxy = httpx.Proxy(url=proxy_url)

    async def fetch_repo(self, owner: str, repo: str) -> RepoMetadata | None:
        """Fetch repository metadata from GitHub API.

        Args:
            owner: Repository owner (username or organization)
            repo: Repository name

        Returns:
            RepoMetadata if successful, None if repository not found

        Raises:
            httpx.HTTPError: For other HTTP errors (500, network issues, etc.)
        """
        url = f"{self.GITHUB_API_BASE}/repos/{owner}/{repo}"

        async with httpx.AsyncClient(
            proxy=self.proxy,
            timeout=self.timeout,
            follow_redirects=True,
        ) as client:
            response = await self._fetch_with_retry(client, url)

            if response is None:
                return None

            data = response.json()

            return RepoMetadata(
                url=data["html_url"],
                owner=data["owner"]["login"],
                name=data["name"],
                description=data.get("description"),
                stars=data.get("stargazers_count", 0),
                language=data.get("language"),
                topics=data.get("topics", []),
                fetched_at=datetime.now(UTC),
            )

    async def _fetch_with_retry(self, client: httpx.AsyncClient, url: str) -> httpx.Response | None:
        """Fetch URL with exponential backoff retry logic.

        Args:
            client: httpx async client
            url: URL to fetch

        Returns:
            Response if successful, None if 404

        Raises:
            httpx.HTTPError: For non-404 HTTP errors after exhausting retries
        """
        delay = self.INITIAL_RETRY_DELAY

        for attempt in range(self.MAX_RETRIES):
            try:
                response = await client.get(url)

                if response.status_code == 404:
                    return None

                if response.status_code == 403:
                    if "rate limit" in response.text.lower():
                        if attempt < self.MAX_RETRIES - 1:
                            await asyncio.sleep(delay)
                            delay = min(delay * 2, self.MAX_RETRY_DELAY)
                            continue

                response.raise_for_status()
                return response

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    return None
                if e.response.status_code == 403 and attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, self.MAX_RETRY_DELAY)
                    continue
                raise

            except httpx.ProxyError as e:
                raise httpx.ProxyError(
                    f"Webshare proxy connection failed. Check "
                    f"WEBSHARE_PROXY_USERNAME and WEBSHARE_PROXY_PASSWORD "
                    f"in .env. Original error: {e}"
                ) from e

            except (httpx.ConnectError, httpx.TimeoutException):
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, self.MAX_RETRY_DELAY)
                    continue
                raise

        raise httpx.HTTPError(f"Failed to fetch {url} after {self.MAX_RETRIES} attempts")


def get_github_fetcher(
    proxy_username: str,
    proxy_password: str,
) -> GitHubFetcher:
    """Get GitHub fetcher instance.

    Args:
        proxy_username: Webshare proxy username
        proxy_password: Webshare proxy password

    Returns:
        Configured GitHubFetcher instance
    """
    return GitHubFetcher(proxy_username=proxy_username, proxy_password=proxy_password)
