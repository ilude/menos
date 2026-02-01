"""Unit tests for storage services."""

import io
from unittest.mock import MagicMock

import pytest

from menos.models import ChunkModel, ContentMetadata
from menos.services.storage import MinIOStorage, SurrealDBRepository


class TestMinIOStorage:
    """Tests for MinIO storage service."""

    def test_init(self):
        """Test MinIO storage initialization."""
        mock_client = MagicMock()
        storage = MinIOStorage(mock_client, "test-bucket")

        assert storage.client == mock_client
        assert storage.bucket == "test-bucket"

    @pytest.mark.asyncio
    async def test_upload(self):
        """Test file upload to MinIO."""
        mock_client = MagicMock()
        storage = MinIOStorage(mock_client, "test-bucket")

        data = io.BytesIO(b"test content")
        result = await storage.upload("test/file.txt", data, "text/plain")

        assert result == 12  # len(b"test content")
        mock_client.put_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_error(self):
        """Test upload error handling."""
        mock_client = MagicMock()
        mock_client.put_object.side_effect = Exception("Upload failed")
        storage = MinIOStorage(mock_client, "test-bucket")

        data = io.BytesIO(b"test content")
        with pytest.raises(Exception):
            await storage.upload("test/file.txt", data, "text/plain")

    @pytest.mark.asyncio
    async def test_download(self):
        """Test file download from MinIO."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.read.return_value = b"test content"
        mock_client.get_object.return_value = mock_response

        storage = MinIOStorage(mock_client, "test-bucket")
        result = await storage.download("test/file.txt")

        assert result == b"test content"
        mock_client.get_object.assert_called_once_with("test-bucket", "test/file.txt")

    @pytest.mark.asyncio
    async def test_delete(self):
        """Test file deletion from MinIO."""
        mock_client = MagicMock()
        storage = MinIOStorage(mock_client, "test-bucket")

        await storage.delete("test/file.txt")

        mock_client.remove_object.assert_called_once_with("test-bucket", "test/file.txt")


class TestSurrealDBRepository:
    """Tests for SurrealDB repository."""

    def test_init(self):
        """Test repository initialization."""
        mock_db = MagicMock()
        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")

        assert repo.db == mock_db
        assert repo.namespace == "test-ns"
        assert repo.database == "test-db"

    @pytest.mark.asyncio
    async def test_connect(self):
        """Test database connection."""
        mock_db = MagicMock()
        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")

        await repo.connect()

        mock_db.use.assert_called_once_with("test-ns", "test-db")

    @pytest.mark.asyncio
    async def test_create_content(self):
        """Test content creation."""
        mock_db = MagicMock()
        mock_db.create.return_value = [{"id": "content:test123"}]

        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")
        metadata = ContentMetadata(
            content_type="document",
            mime_type="text/plain",
            file_size=100,
            file_path="test/file.txt",
        )

        result = await repo.create_content(metadata)

        assert result.id == "test123"
        assert result.created_at is not None
        assert result.updated_at is not None
        mock_db.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_content(self):
        """Test getting content by ID."""
        mock_db = MagicMock()
        mock_db.select.return_value = [
            {
                "id": "content:test123",
                "content_type": "document",
                "mime_type": "text/plain",
                "file_size": 100,
                "file_path": "test/file.txt",
            }
        ]

        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")
        result = await repo.get_content("test123")

        assert result is not None
        assert result.content_type == "document"
        mock_db.select.assert_called_once_with("content:test123")

    @pytest.mark.asyncio
    async def test_get_content_not_found(self):
        """Test getting non-existent content."""
        mock_db = MagicMock()
        mock_db.select.return_value = []

        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")
        result = await repo.get_content("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_list_content(self):
        """Test listing content."""
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": "content:1",
                        "content_type": "document",
                        "mime_type": "text/plain",
                        "file_size": 100,
                        "file_path": "test/file1.txt",
                    },
                    {
                        "id": "content:2",
                        "content_type": "document",
                        "mime_type": "text/plain",
                        "file_size": 200,
                        "file_path": "test/file2.txt",
                    },
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")
        items, total = await repo.list_content(offset=0, limit=50)

        assert len(items) == 2
        assert total == 2
        mock_db.query.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_content(self):
        """Test content deletion."""
        mock_db = MagicMock()
        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")

        await repo.delete_content("test123")

        mock_db.delete.assert_called_once_with("content:test123")

    @pytest.mark.asyncio
    async def test_create_chunk(self):
        """Test chunk creation."""
        mock_db = MagicMock()
        mock_db.create.return_value = [{"id": "chunk:xyz"}]

        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")
        chunk = ChunkModel(
            content_id="test123",
            text="test chunk",
            chunk_index=0,
        )

        result = await repo.create_chunk(chunk)

        assert result.id == "xyz"
        assert result.created_at is not None

    @pytest.mark.asyncio
    async def test_get_chunks(self):
        """Test getting chunks for content."""
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": "chunk:1",
                        "content_id": "test123",
                        "text": "chunk 1",
                        "chunk_index": 0,
                    },
                    {
                        "id": "chunk:2",
                        "content_id": "test123",
                        "text": "chunk 2",
                        "chunk_index": 1,
                    },
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")
        chunks = await repo.get_chunks("test123")

        assert len(chunks) == 2
        assert chunks[0].text == "chunk 1"
