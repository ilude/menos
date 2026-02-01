"""Integration tests for content endpoints."""

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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

    def test_content_patch_requires_auth(self, client):
        """Test that content patch requires authentication."""
        from fastapi.testclient import TestClient
        unauthenticated_client = TestClient(client.app)
        response = unauthenticated_client.patch(
            "/api/v1/content/123",
            json={"tags": ["tag1"]},
        )

        assert response.status_code == 401


class TestLinkExtraction:
    """Tests for link extraction during content upload."""

    @pytest.mark.asyncio
    async def test_extract_links_from_markdown(self):
        """Test that links are extracted from markdown content."""
        from menos.models import ContentMetadata, LinkModel
        from menos.routers.content import _extract_and_store_links
        from menos.services.storage import SurrealDBRepository

        content = """
        # My Document

        See [[Python]] for more info.
        Also check [[Django|the framework]].
        """

        mock_db = MagicMock()
        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")

        # Mock methods
        repo.find_content_by_title = AsyncMock(return_value=None)
        repo.delete_links_by_source = AsyncMock()
        repo.create_link = AsyncMock()

        await _extract_and_store_links("test123", content, repo)

        # Verify links were extracted and stored
        repo.delete_links_by_source.assert_called_once_with("test123")
        assert repo.create_link.call_count == 2

        # Check first link
        first_call = repo.create_link.call_args_list[0][0][0]
        assert first_call.source == "test123"
        assert first_call.link_text == "Python"
        assert first_call.link_type == "wiki"
        assert first_call.target is None  # Not resolved

    @pytest.mark.asyncio
    async def test_resolve_link_target(self):
        """Test that link targets are resolved when content exists."""
        from menos.models import ContentMetadata
        from menos.routers.content import _extract_and_store_links
        from menos.services.storage import SurrealDBRepository

        content = "See [[Python Guide]] for details."

        mock_db = MagicMock()
        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")

        # Mock Python Guide content exists
        target_content = ContentMetadata(
            id="target456",
            content_type="document",
            title="Python Guide",
            mime_type="text/markdown",
            file_size=100,
            file_path="docs/python.md",
        )

        repo.find_content_by_title = AsyncMock(return_value=target_content)
        repo.delete_links_by_source = AsyncMock()
        repo.create_link = AsyncMock()

        await _extract_and_store_links("source123", content, repo)

        # Verify target was resolved
        repo.find_content_by_title.assert_called_once_with("Python Guide")
        link_arg = repo.create_link.call_args[0][0]
        assert link_arg.target == "target456"

    @pytest.mark.asyncio
    async def test_markdown_links_extracted(self):
        """Test that markdown links are extracted."""
        from menos.routers.content import _extract_and_store_links
        from menos.services.storage import SurrealDBRepository

        content = "See [docs](./README.md) and [guide](guide.md)."

        mock_db = MagicMock()
        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")

        repo.find_content_by_title = AsyncMock(return_value=None)
        repo.delete_links_by_source = AsyncMock()
        repo.create_link = AsyncMock()

        await _extract_and_store_links("test123", content, repo)

        assert repo.create_link.call_count == 2

        # Check markdown links
        calls = repo.create_link.call_args_list
        assert calls[0][0][0].link_type == "markdown"
        assert calls[0][0][0].target is None
        assert calls[1][0][0].link_type == "markdown"

    @pytest.mark.asyncio
    async def test_no_links_in_content(self):
        """Test that no errors occur when content has no links."""
        from menos.routers.content import _extract_and_store_links
        from menos.services.storage import SurrealDBRepository

        content = "Just plain text with no links."

        mock_db = MagicMock()
        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")

        repo.find_content_by_title = AsyncMock(return_value=None)
        repo.delete_links_by_source = AsyncMock()
        repo.create_link = AsyncMock()

        await _extract_and_store_links("test123", content, repo)

        # Should not attempt to delete or create links
        repo.delete_links_by_source.assert_not_called()
        repo.create_link.assert_not_called()

    @pytest.mark.asyncio
    async def test_links_deleted_before_creation(self):
        """Test that existing links are deleted before new ones are created."""
        from menos.routers.content import _extract_and_store_links
        from menos.services.storage import SurrealDBRepository

        content = "Link: [[Test]]"

        mock_db = MagicMock()
        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")

        repo.find_content_by_title = AsyncMock(return_value=None)
        repo.delete_links_by_source = AsyncMock()
        repo.create_link = AsyncMock()

        await _extract_and_store_links("test123", content, repo)

        # Verify delete was called before create
        assert repo.delete_links_by_source.called
        assert repo.create_link.called

        # Check order by comparing call times
        delete_call_time = repo.delete_links_by_source.call_args
        create_call_time = repo.create_link.call_args
        assert delete_call_time is not None
        assert create_call_time is not None

    @pytest.mark.asyncio
    async def test_mixed_link_types_extracted(self):
        """Test that both wiki and markdown links are extracted."""
        from menos.routers.content import _extract_and_store_links
        from menos.services.storage import SurrealDBRepository

        content = """
        Wiki: [[Python]]
        Markdown: [guide](./guide.md)
        Another wiki: [[Django]]
        """

        mock_db = MagicMock()
        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")

        repo.find_content_by_title = AsyncMock(return_value=None)
        repo.delete_links_by_source = AsyncMock()
        repo.create_link = AsyncMock()

        await _extract_and_store_links("test123", content, repo)

        assert repo.create_link.call_count == 3

        calls = repo.create_link.call_args_list
        link_types = [call[0][0].link_type for call in calls]
        assert "wiki" in link_types
        assert "markdown" in link_types

    @pytest.mark.asyncio
    async def test_links_in_code_blocks_ignored(self):
        """Test that links in code blocks are not extracted."""
        from menos.routers.content import _extract_and_store_links
        from menos.services.storage import SurrealDBRepository

        content = """
        Normal: [[Python]]

        ```python
        # [[Should not extract]]
        url = "[also ignored](file.md)"
        ```

        Valid: [[Django]]
        """

        mock_db = MagicMock()
        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")

        repo.find_content_by_title = AsyncMock(return_value=None)
        repo.delete_links_by_source = AsyncMock()
        repo.create_link = AsyncMock()

        await _extract_and_store_links("test123", content, repo)

        # Only 2 links should be extracted (Python and Django)
        assert repo.create_link.call_count == 2

        calls = repo.create_link.call_args_list
        targets = [call[0][0].link_text for call in calls]
        assert "Python" in targets
        assert "Django" in targets
        assert "Should not extract" not in targets
