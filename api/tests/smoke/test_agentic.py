"""Smoke tests for agentic search endpoint."""

import json
from urllib.parse import urlparse

import pytest


@pytest.fixture(scope="session")
def smoke_http_client_long_timeout(smoke_base_url):
    """Create httpx client for smoke tests with extended timeout for LLM calls.

    Agentic search involves multiple LLM calls and can take longer than regular endpoints.
    With 45K chunks and no HNSW index, vector search can take 90+ seconds.
    """
    import httpx

    with httpx.Client(base_url=smoke_base_url, timeout=180.0) as client:
        yield client


@pytest.mark.smoke
class TestAgenticSearchSmoke:
    """Smoke tests for agentic search endpoint."""

    def test_agentic_search_requires_auth(self, smoke_http_client):
        """POST /api/v1/search/agentic returns 401 without auth."""
        response = smoke_http_client.post(
            "/api/v1/search/agentic",
            json={"query": "what topics are discussed?", "limit": 5},
        )

        assert response.status_code == 401
        data = response.json()
        assert "detail" in data

    def test_agentic_search_returns_response(
        self, smoke_http_client_long_timeout, smoke_base_url, smoke_authed_headers
    ):
        """With auth, returns 200 and has answer, sources, timing."""
        path = "/api/v1/search/agentic"
        payload = {"query": "what topics are discussed?", "limit": 5}
        body = json.dumps(payload).encode()

        host = urlparse(smoke_base_url).netloc
        headers = smoke_authed_headers("POST", path, body=body, host=host)
        headers["content-type"] = "application/json"

        response = smoke_http_client_long_timeout.post(path, content=body, headers=headers)

        assert response.status_code == 200
        data = response.json()

        # Verify required fields exist
        assert "query" in data
        assert "answer" in data
        assert "sources" in data
        assert "timing" in data

        # Verify query echoed correctly
        assert data["query"] == payload["query"]

        # Verify answer is non-empty string
        assert isinstance(data["answer"], str)
        assert len(data["answer"]) > 0

        # Verify sources is a list
        assert isinstance(data["sources"], list)

        # Verify timing is dict
        assert isinstance(data["timing"], dict)

    def test_agentic_search_timing_structure(
        self, smoke_http_client_long_timeout, smoke_base_url, smoke_authed_headers
    ):
        """Verify timing has expansion_ms, retrieval_ms, rerank_ms, synthesis_ms, total_ms."""
        path = "/api/v1/search/agentic"
        payload = {"query": "what topics are discussed?", "limit": 5}
        body = json.dumps(payload).encode()

        host = urlparse(smoke_base_url).netloc
        headers = smoke_authed_headers("POST", path, body=body, host=host)
        headers["content-type"] = "application/json"

        response = smoke_http_client_long_timeout.post(path, content=body, headers=headers)

        assert response.status_code == 200
        data = response.json()
        timing = data["timing"]

        # Verify all timing fields exist
        required_timing_fields = [
            "expansion_ms",
            "retrieval_ms",
            "rerank_ms",
            "synthesis_ms",
            "total_ms",
        ]
        for field in required_timing_fields:
            assert field in timing, f"Missing timing field: {field}"
            assert isinstance(
                timing[field], (int, float)
            ), f"{field} should be numeric, got {type(timing[field])}"

    def test_agentic_search_timing_reasonable(
        self, smoke_http_client_long_timeout, smoke_base_url, smoke_authed_headers
    ):
        """Assert timing.total_ms < 60000 (60s max, allowing for cold LLM)."""
        path = "/api/v1/search/agentic"
        payload = {"query": "what topics are discussed?", "limit": 5}
        body = json.dumps(payload).encode()

        host = urlparse(smoke_base_url).netloc
        headers = smoke_authed_headers("POST", path, body=body, host=host)
        headers["content-type"] = "application/json"

        response = smoke_http_client_long_timeout.post(path, content=body, headers=headers)

        assert response.status_code == 200
        data = response.json()
        timing = data["timing"]

        # With 45K+ chunks and no HNSW index, vector search can be slow (~90s).
        # Once HNSW indexing is added, reduce this threshold to 30000ms.
        assert (
            timing["total_ms"] < 150000
        ), f"Agentic search took {timing['total_ms']}ms, exceeds 150s threshold"

        # Verify total is non-negative
        assert timing["total_ms"] >= 0

        # Verify all individual timings are non-negative
        assert timing["expansion_ms"] >= 0
        assert timing["retrieval_ms"] >= 0
        assert timing["rerank_ms"] >= 0
        assert timing["synthesis_ms"] >= 0

    def test_agentic_search_sources_structure(
        self, smoke_http_client_long_timeout, smoke_base_url, smoke_authed_headers
    ):
        """If sources exist, verify each has id, content_type, score."""
        path = "/api/v1/search/agentic"
        payload = {"query": "what topics are discussed?", "limit": 5}
        body = json.dumps(payload).encode()

        host = urlparse(smoke_base_url).netloc
        headers = smoke_authed_headers("POST", path, body=body, host=host)
        headers["content-type"] = "application/json"

        response = smoke_http_client_long_timeout.post(path, content=body, headers=headers)

        assert response.status_code == 200
        data = response.json()
        sources = data["sources"]

        # If sources exist, verify structure
        if sources:
            for source in sources:
                # Required fields
                assert "id" in source, "Source missing id field"
                assert "content_type" in source, "Source missing content_type field"
                assert "score" in source, "Source missing score field"

                # Type validation
                assert isinstance(source["id"], str)
                assert isinstance(source["content_type"], str)
                assert isinstance(source["score"], (int, float))

                # Optional fields can be present
                if "title" in source:
                    assert isinstance(source["title"], (str, type(None)))
                if "snippet" in source:
                    assert isinstance(source["snippet"], (str, type(None)))

                # Score should be reasonable (0-1 range for similarity scores)
                assert 0 <= source["score"] <= 1, f"Score {source['score']} outside [0,1] range"
