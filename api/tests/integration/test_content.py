"""Integration tests for content endpoints."""

import io


class TestContentEndpoints:
    """Tests for content CRUD endpoints."""

    def test_content_list_requires_auth(self, client):
        """Test that content list requires authentication."""
        from fastapi.testclient import TestClient
        unauthenticated_client = TestClient(client.app)
        response = unauthenticated_client.get("/api/v1/content")

        assert response.status_code == 401
        data = response.json()
        assert "detail" in data

    def test_content_create_requires_auth(self, client):
        """Test that content creation requires authentication."""
        from fastapi.testclient import TestClient
        unauthenticated_client = TestClient(client.app)
        response = unauthenticated_client.post(
            "/api/v1/content",
            files={"file": ("test.txt", io.BytesIO(b"test"), "text/plain")},
        )

        assert response.status_code == 401

    def test_content_delete_requires_auth(self, client):
        """Test that content deletion requires authentication."""
        from fastapi.testclient import TestClient
        unauthenticated_client = TestClient(client.app)
        response = unauthenticated_client.delete("/api/v1/content/123")

        assert response.status_code == 401
