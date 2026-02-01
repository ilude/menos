"""Smoke test fixtures for live API testing."""

import os
from pathlib import Path

import httpx
import pytest

from menos.client.signer import RequestSigner


@pytest.fixture(scope="session")
def smoke_base_url():
    """Get the base URL for the live API from environment.

    Uses SMOKE_TEST_URL env var, defaults to http://localhost:8000
    """
    url = os.environ.get("SMOKE_TEST_URL", "http://localhost:8000")
    return url.rstrip("/")


@pytest.fixture(scope="session")
def smoke_request_signer():
    """Create RequestSigner from SSH key file.

    Uses SMOKE_TEST_KEY_FILE env var, defaults to ~/.ssh/id_ed25519
    Gracefully handles missing key file with informative error.
    """
    key_path = os.environ.get(
        "SMOKE_TEST_KEY_FILE",
        str(Path.home() / ".ssh" / "id_ed25519")
    )
    key_path = Path(key_path)

    if not key_path.exists():
        pytest.skip(
            f"Smoke test SSH key not found at {key_path}. "
            f"Set SMOKE_TEST_KEY_FILE environment variable or ensure "
            f"~/.ssh/id_ed25519 exists."
        )

    try:
        return RequestSigner.from_file(key_path)
    except ValueError as e:
        pytest.skip(f"Invalid SSH key format: {e}. Only Ed25519 keys are supported.")
    except Exception as e:
        pytest.skip(f"Failed to load SSH key: {e}")


@pytest.fixture(scope="session")
def smoke_http_client(smoke_base_url):
    """Create httpx client for smoke tests with extended timeout."""
    with httpx.Client(base_url=smoke_base_url, timeout=30.0) as client:
        yield client


@pytest.fixture(scope="session")
def smoke_authed_headers(smoke_request_signer):
    """Factory fixture to generate auth headers for requests.

    Usage:
        headers = smoke_authed_headers("GET", "/api/endpoint", host="example.com")
    """
    def _make_headers(
        method: str,
        path: str,
        body: bytes | None = None,
        host: str | None = None,
    ) -> dict[str, str]:
        """Generate signed request headers.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path (must start with /)
            body: Optional request body for POST/PUT requests
            host: Host header value (defaults to localhost)

        Returns:
            Dictionary of signed headers ready to send with request
        """
        return smoke_request_signer.sign_request(
            method,
            path,
            body=body,
            host=host or "localhost"
        )

    return _make_headers


def pytest_configure(config):
    """Register custom markers for smoke tests."""
    config.addinivalue_line(
        "markers",
        "smoke: mark test as smoke test (requires live API)"
    )
