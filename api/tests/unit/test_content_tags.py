"""Unit tests for content tags parameter and tags listing."""

import io
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from menos.models import ContentMetadata
from menos.routers.content import create_content, list_tags
from menos.services.storage import MinIOStorage, SurrealDBRepository


@pytest.fixture
def mock_classification_svc():
    """Mock classification service for content creation tests."""
    svc = MagicMock()
    svc.classify_content = AsyncMock(return_value=None)
    svc.settings = MagicMock()
    svc.settings.classification_min_content_length = 500
    return svc


class TestContentTagsParameter:
    """Tests for content tags parameter in POST /api/v1/content endpoint."""

    @pytest.mark.asyncio
    async def test_create_content_with_tags(self, mock_classification_svc):
        """Test creating content with tags stored in metadata."""
        mock_minio = MagicMock(spec=MinIOStorage)
        mock_minio.upload = AsyncMock(return_value=100)

        mock_repo = MagicMock(spec=SurrealDBRepository)
        created_metadata = ContentMetadata(
            id="test-123",
            content_type="document",
            title="test.txt",
            mime_type="text/plain",
            file_size=100,
            file_path="document/test-123/test.txt",
            author="test-key",
            tags=["important", "review", "urgent"],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        mock_repo.create_content = AsyncMock(return_value=created_metadata)

        # Mock the UploadFile with async read
        mock_file = MagicMock()
        mock_file.filename = "test.txt"
        mock_file.content_type = "text/plain"
        mock_file.file = io.BytesIO(b"test content")
        mock_file.read = AsyncMock(return_value=b"test content")
        mock_file.seek = AsyncMock()

        # Call the endpoint with tags
        result = await create_content(
            key_id="test-key",
            file=mock_file,
            content_type="document",
            title="test.txt",
            tags=["important", "review", "urgent"],
            minio_storage=mock_minio,
            surreal_repo=mock_repo,
            classification_service=mock_classification_svc,
        )

        # Verify the result
        assert result.id == "test-123"
        assert result.file_size == 100
        assert result.file_path.startswith("document/")
        assert result.file_path.endswith("/test.txt")

        # Verify that create_content was called with the tags
        mock_repo.create_content.assert_called_once()
        call_args = mock_repo.create_content.call_args
        assert call_args is not None
        metadata = call_args[0][0]  # First positional argument
        assert isinstance(metadata, ContentMetadata)
        assert metadata.tags == ["important", "review", "urgent"]

    @pytest.mark.asyncio
    async def test_create_content_without_tags(self, mock_classification_svc):
        """Test creating content without tags defaults to empty list."""
        mock_minio = MagicMock(spec=MinIOStorage)
        mock_minio.upload = AsyncMock(return_value=100)

        mock_repo = MagicMock(spec=SurrealDBRepository)
        created_metadata = ContentMetadata(
            id="test-456",
            content_type="document",
            title="test.txt",
            mime_type="text/plain",
            file_size=100,
            file_path="document/test-456/test.txt",
            author="test-key",
            tags=[],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        mock_repo.create_content = AsyncMock(return_value=created_metadata)

        # Mock the UploadFile with async read
        mock_file = MagicMock()
        mock_file.filename = "test.txt"
        mock_file.content_type = "text/plain"
        mock_file.file = io.BytesIO(b"test content")
        mock_file.read = AsyncMock(return_value=b"test content")
        mock_file.seek = AsyncMock()

        # Call the endpoint without tags
        result = await create_content(
            key_id="test-key",
            file=mock_file,
            content_type="document",
            title="test.txt",
            tags=None,
            minio_storage=mock_minio,
            surreal_repo=mock_repo,
            classification_service=mock_classification_svc,
        )

        # Verify the result
        assert result.id == "test-456"

        # Verify that create_content was called with empty tags list
        mock_repo.create_content.assert_called_once()
        call_args = mock_repo.create_content.call_args
        assert call_args is not None
        metadata = call_args[0][0]
        assert metadata.tags == []

    @pytest.mark.asyncio
    async def test_create_content_with_empty_tags_list(self, mock_classification_svc):
        """Test creating content with empty tags list."""
        mock_minio = MagicMock(spec=MinIOStorage)
        mock_minio.upload = AsyncMock(return_value=100)

        mock_repo = MagicMock(spec=SurrealDBRepository)
        created_metadata = ContentMetadata(
            id="test-789",
            content_type="document",
            title="test.txt",
            mime_type="text/plain",
            file_size=100,
            file_path="document/test-789/test.txt",
            author="test-key",
            tags=[],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        mock_repo.create_content = AsyncMock(return_value=created_metadata)

        # Mock the UploadFile with async read
        mock_file = MagicMock()
        mock_file.filename = "test.txt"
        mock_file.content_type = "text/plain"
        mock_file.file = io.BytesIO(b"test content")
        mock_file.read = AsyncMock(return_value=b"test content")
        mock_file.seek = AsyncMock()

        # Call the endpoint with empty tags list
        result = await create_content(
            key_id="test-key",
            file=mock_file,
            content_type="document",
            title="test.txt",
            tags=[],
            minio_storage=mock_minio,
            surreal_repo=mock_repo,
            classification_service=mock_classification_svc,
        )

        # Verify the result
        assert result.id == "test-789"

        # Verify that create_content was called with empty tags list
        mock_repo.create_content.assert_called_once()
        call_args = mock_repo.create_content.call_args
        assert call_args is not None
        metadata = call_args[0][0]
        assert metadata.tags == []

class TestContentUpdateEndpoint:
    """Tests for PATCH /api/v1/content/{id} endpoint."""

    @pytest.mark.asyncio
    async def test_update_content_tags(self):
        """Test updating content tags."""
        from menos.routers.content import update_content

        mock_repo = MagicMock(spec=SurrealDBRepository)
        original_metadata = ContentMetadata(
            id="test-123",
            content_type="document",
            title="test.txt",
            mime_type="text/plain",
            file_size=100,
            file_path="document/test-123/test.txt",
            author="test-key",
            tags=["old-tag"],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        updated_metadata = ContentMetadata(
            id="test-123",
            content_type="document",
            title="test.txt",
            mime_type="text/plain",
            file_size=100,
            file_path="document/test-123/test.txt",
            author="test-key",
            tags=["new-tag1", "new-tag2"],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        mock_repo.get_content = AsyncMock(return_value=original_metadata)
        mock_repo.update_content = AsyncMock(return_value=updated_metadata)

        from menos.routers.content import ContentUpdateRequest
        update_request = ContentUpdateRequest(tags=["new-tag1", "new-tag2"])

        result = await update_content(
            content_id="test-123",
            update_request=update_request,
            key_id="test-key",
            surreal_repo=mock_repo,
        )

        assert result["id"] == "test-123"
        assert result["tags"] == ["new-tag1", "new-tag2"]
        mock_repo.get_content.assert_called_once_with("test-123")
        mock_repo.update_content.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_content_not_found(self):
        """Test updating non-existent content returns 404."""
        from menos.routers.content import update_content

        mock_repo = MagicMock(spec=SurrealDBRepository)
        mock_repo.get_content = AsyncMock(return_value=None)

        from menos.routers.content import ContentUpdateRequest
        update_request = ContentUpdateRequest(tags=["new-tag"])

        result = await update_content(
            content_id="nonexistent",
            update_request=update_request,
            key_id="test-key",
            surreal_repo=mock_repo,
        )

        assert result[0]["error"] == "Content not found"
        assert result[1] == 404

    @pytest.mark.asyncio
    async def test_update_content_title_and_description(self):
        """Test updating content title and description."""
        from menos.routers.content import update_content

        mock_repo = MagicMock(spec=SurrealDBRepository)
        original_metadata = ContentMetadata(
            id="test-456",
            content_type="document",
            title="old-title",
            description="old description",
            mime_type="text/plain",
            file_size=100,
            file_path="document/test-456/test.txt",
            author="test-key",
            tags=[],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        updated_metadata = ContentMetadata(
            id="test-456",
            content_type="document",
            title="new-title",
            description="new description",
            mime_type="text/plain",
            file_size=100,
            file_path="document/test-456/test.txt",
            author="test-key",
            tags=[],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        mock_repo.get_content = AsyncMock(return_value=original_metadata)
        mock_repo.update_content = AsyncMock(return_value=updated_metadata)

        from menos.routers.content import ContentUpdateRequest
        update_request = ContentUpdateRequest(
            title="new-title",
            description="new description",
        )

        result = await update_content(
            content_id="test-456",
            update_request=update_request,
            key_id="test-key",
            surreal_repo=mock_repo,
        )

        assert result["id"] == "test-456"
        assert result["title"] == "new-title"
        assert result["description"] == "new description"
        mock_repo.update_content.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_content_partial_update(self):
        """Test partial update only changes specified fields."""
        from menos.routers.content import update_content

        mock_repo = MagicMock(spec=SurrealDBRepository)
        original_metadata = ContentMetadata(
            id="test-789",
            content_type="document",
            title="original-title",
            description="original description",
            mime_type="text/plain",
            file_size=100,
            file_path="document/test-789/test.txt",
            author="test-key",
            tags=["original-tag"],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        updated_metadata = ContentMetadata(
            id="test-789",
            content_type="document",
            title="original-title",
            description="original description",
            mime_type="text/plain",
            file_size=100,
            file_path="document/test-789/test.txt",
            author="test-key",
            tags=["new-tag"],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        mock_repo.get_content = AsyncMock(return_value=original_metadata)
        mock_repo.update_content = AsyncMock(return_value=updated_metadata)

        from menos.routers.content import ContentUpdateRequest
        update_request = ContentUpdateRequest(tags=["new-tag"])

        result = await update_content(
            content_id="test-789",
            update_request=update_request,
            key_id="test-key",
            surreal_repo=mock_repo,
        )

        assert result["id"] == "test-789"
        assert result["tags"] == ["new-tag"]
        assert result["title"] == "original-title"
        assert result["description"] == "original description"


class TestListTagsEndpoint:
    """Tests for GET /api/v1/tags endpoint."""

    @pytest.mark.asyncio
    async def test_list_tags_with_counts(self):
        """Test listing all tags with their counts."""
        mock_repo = MagicMock(spec=SurrealDBRepository)
        mock_repo.list_tags_with_counts = AsyncMock(
            return_value=[
                {"name": "python", "count": 15},
                {"name": "api", "count": 8},
                {"name": "database", "count": 5},
            ]
        )

        result = await list_tags(
            key_id="test-key",
            surreal_repo=mock_repo,
        )

        assert len(result.tags) == 3
        assert result.tags[0].name == "python"
        assert result.tags[0].count == 15
        assert result.tags[1].name == "api"
        assert result.tags[1].count == 8
        assert result.tags[2].name == "database"
        assert result.tags[2].count == 5
        mock_repo.list_tags_with_counts.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_tags_empty(self):
        """Test listing tags when no content has tags."""
        mock_repo = MagicMock(spec=SurrealDBRepository)
        mock_repo.list_tags_with_counts = AsyncMock(return_value=[])

        result = await list_tags(
            key_id="test-key",
            surreal_repo=mock_repo,
        )

        assert len(result.tags) == 0
        mock_repo.list_tags_with_counts.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_tags_preserves_order_from_service(self):
        """Test that endpoint preserves the order from list_tags_with_counts."""
        mock_repo = MagicMock(spec=SurrealDBRepository)
        mock_repo.list_tags_with_counts = AsyncMock(
            return_value=[
                {"name": "python", "count": 15},
                {"name": "zebra", "count": 10},
                {"name": "apple", "count": 10},
                {"name": "database", "count": 5},
            ]
        )

        result = await list_tags(
            key_id="test-key",
            surreal_repo=mock_repo,
        )

        assert len(result.tags) == 4
        assert result.tags[0].name == "python"
        assert result.tags[0].count == 15
        assert result.tags[1].name == "zebra"
        assert result.tags[1].count == 10
        assert result.tags[2].name == "apple"
        assert result.tags[2].count == 10
        assert result.tags[3].name == "database"
        assert result.tags[3].count == 5


class TestSurrealDBRepositoryListTagsWithCounts:
    """Tests for SurrealDBRepository.list_tags_with_counts method."""

    @pytest.mark.asyncio
    async def test_list_tags_with_counts_single_items(self):
        """Test listing tags where each tag appears once."""
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {"tag": "python", "count": 1},
                    {"tag": "api", "count": 1},
                    {"tag": "database", "count": 1},
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")
        result = await repo.list_tags_with_counts()

        assert len(result) == 3
        assert result[0] == {"name": "api", "count": 1}
        assert result[1] == {"name": "database", "count": 1}
        assert result[2] == {"name": "python", "count": 1}

    @pytest.mark.asyncio
    async def test_list_tags_with_counts_multiple_occurrences(self):
        """Test listing tags with varying counts."""
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {"tag": "python", "count": 2},
                    {"tag": "api", "count": 3},
                    {"tag": "database", "count": 1},
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")
        result = await repo.list_tags_with_counts()

        assert len(result) == 3
        assert result[0] == {"name": "api", "count": 3}
        assert result[1] == {"name": "python", "count": 2}
        assert result[2] == {"name": "database", "count": 1}

    @pytest.mark.asyncio
    async def test_list_tags_with_counts_empty(self):
        """Test listing tags when no content has tags."""
        mock_db = MagicMock()
        mock_db.query.return_value = []

        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")
        result = await repo.list_tags_with_counts()

        assert result == []

    @pytest.mark.asyncio
    async def test_list_tags_with_counts_no_result_key(self):
        """Test listing tags when query returns list without result key."""
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {"tag": "python", "count": 1},
            {"tag": "api", "count": 1},
        ]

        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")
        result = await repo.list_tags_with_counts()

        assert len(result) == 2
        assert result[0] == {"name": "api", "count": 1}
        assert result[1] == {"name": "python", "count": 1}

    @pytest.mark.asyncio
    async def test_list_tags_sorted_correctly(self):
        """Test that tags are sorted by count descending, then name ascending."""
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {"tag": "python", "count": 3},
                    {"tag": "zebra", "count": 2},
                    {"tag": "apple", "count": 2},
                    {"tag": "database", "count": 1},
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")
        result = await repo.list_tags_with_counts()

        assert len(result) == 4
        assert result[0] == {"name": "python", "count": 3}
        assert result[1] == {"name": "apple", "count": 2}
        assert result[2] == {"name": "zebra", "count": 2}
        assert result[3] == {"name": "database", "count": 1}
