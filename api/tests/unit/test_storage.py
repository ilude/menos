"""Unit tests for storage services."""

import io
from unittest.mock import MagicMock

import pytest

from menos.models import (
    ChunkModel,
    ContentEntityEdge,
    ContentMetadata,
    EdgeType,
    EntityModel,
    EntityType,
    LinkModel,
)
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

    @pytest.mark.asyncio
    async def test_find_content_by_title(self):
        """Test finding content by title."""
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": "content:test123",
                        "content_type": "document",
                        "title": "Python Guide",
                        "mime_type": "text/plain",
                        "file_size": 100,
                        "file_path": "test/file.txt",
                    }
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")
        result = await repo.find_content_by_title("Python Guide")

        assert result is not None
        assert result.title == "Python Guide"
        assert result.id == "content:test123"

    @pytest.mark.asyncio
    async def test_find_content_by_title_not_found(self):
        """Test finding non-existent content by title."""
        mock_db = MagicMock()
        mock_db.query.return_value = [{"result": []}]

        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")
        result = await repo.find_content_by_title("Nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_create_link(self):
        """Test link creation."""
        mock_db = MagicMock()
        mock_db.create.return_value = [{"id": "link:abc123"}]

        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")
        link = LinkModel(
            source="source123",
            target="target456",
            link_text="Example Link",
            link_type="wiki",
        )

        result = await repo.create_link(link)

        assert result.id == "abc123"
        assert result.created_at is not None
        mock_db.create.assert_called_once()
        # Verify record references are created
        call_args = mock_db.create.call_args[0]
        assert call_args[1]["source"] == "content:source123"
        assert call_args[1]["target"] == "content:target456"

    @pytest.mark.asyncio
    async def test_create_link_without_target(self):
        """Test creating link with unresolved target."""
        mock_db = MagicMock()
        mock_db.create.return_value = [{"id": "link:abc123"}]

        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")
        link = LinkModel(
            source="source123",
            target=None,
            link_text="Unresolved Link",
            link_type="wiki",
        )

        result = await repo.create_link(link)

        assert result.id == "abc123"
        assert result.target is None

    @pytest.mark.asyncio
    async def test_delete_links_by_source(self):
        """Test deleting all links from a source."""
        mock_db = MagicMock()
        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")

        await repo.delete_links_by_source("test123")

        mock_db.query.assert_called_once()
        call_args = mock_db.query.call_args[0]
        assert "DELETE (SELECT id FROM link WHERE source = $source)" in call_args[0]
        assert call_args[1] == {"source": "content:test123"}

    @pytest.mark.asyncio
    async def test_get_links_by_source(self):
        """Test getting all links from a source."""
        mock_db = MagicMock()
        mock_record_id = MagicMock()
        mock_record_id.id = "content:source123"
        mock_target_id = MagicMock()
        mock_target_id.id = "content:target456"

        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": MagicMock(id="link:1"),
                        "source": mock_record_id,
                        "target": mock_target_id,
                        "link_text": "Link 1",
                        "link_type": "wiki",
                    },
                    {
                        "id": MagicMock(id="link:2"),
                        "source": mock_record_id,
                        "target": None,
                        "link_text": "Link 2",
                        "link_type": "markdown",
                    },
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")
        links = await repo.get_links_by_source("source123")

        assert len(links) == 2
        assert links[0].source == "content:source123"
        assert links[0].target == "content:target456"
        assert links[0].link_text == "Link 1"
        assert links[1].target is None

    @pytest.mark.asyncio
    async def test_get_links_by_target(self):
        """Test getting all links pointing to a target (backlinks)."""
        mock_db = MagicMock()
        mock_source_id = MagicMock()
        mock_source_id.id = "content:source123"
        mock_target_id = MagicMock()
        mock_target_id.id = "content:target456"

        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": MagicMock(id="link:1"),
                        "source": mock_source_id,
                        "target": mock_target_id,
                        "link_text": "Target Doc",
                        "link_type": "wiki",
                    },
                    {
                        "id": MagicMock(id="link:2"),
                        "source": MagicMock(id="content:source789"),
                        "target": mock_target_id,
                        "link_text": "Another Link",
                        "link_type": "markdown",
                    },
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")
        backlinks = await repo.get_links_by_target("target456")

        assert len(backlinks) == 2
        assert backlinks[0].source == "content:source123"
        assert backlinks[0].target == "content:target456"
        assert backlinks[0].link_text == "Target Doc"
        assert backlinks[1].source == "content:source789"
        assert backlinks[1].target == "content:target456"
        mock_db.query.assert_called_once()
        call_args = mock_db.query.call_args[0]
        assert "SELECT * FROM link WHERE target = $target" in call_args[0]
        assert call_args[1] == {"target": "content:target456"}

    @pytest.mark.asyncio
    async def test_get_links_by_target_empty(self):
        """Test getting backlinks when none exist."""
        mock_db = MagicMock()
        mock_db.query.return_value = [{"result": []}]

        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")
        backlinks = await repo.get_links_by_target("target456")

        assert len(backlinks) == 0

    @pytest.mark.asyncio
    async def test_get_links_by_target_handles_record_ids(self):
        """Test that get_links_by_target properly converts RecordID objects."""
        mock_db = MagicMock()

        # Simulate RecordID objects
        mock_source_id = MagicMock()
        mock_source_id.id = "content:source123"
        mock_target_id = MagicMock()
        mock_target_id.id = "content:target456"
        mock_link_id = MagicMock()
        mock_link_id.id = "link:abc"

        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": mock_link_id,
                        "source": mock_source_id,
                        "target": mock_target_id,
                        "link_text": "Test Link",
                        "link_type": "wiki",
                    }
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "test-ns", "test-db")
        backlinks = await repo.get_links_by_target("target456")

        assert len(backlinks) == 1
        assert backlinks[0].id == "link:abc"
        assert backlinks[0].source == "content:source123"
        assert backlinks[0].target == "content:target456"


class TestMinIOStorageErrors:
    """Tests for MinIO error paths."""

    @pytest.mark.asyncio
    async def test_download_s3_error(self):
        from minio.error import S3Error

        mock_client = MagicMock()
        mock_client.get_object.side_effect = S3Error(
            "NoSuchKey", "Not found", "resource", "", "", ""
        )
        storage = MinIOStorage(mock_client, "test-bucket")

        with pytest.raises(RuntimeError, match="MinIO download failed"):
            await storage.download("missing/file.txt")

    @pytest.mark.asyncio
    async def test_delete_s3_error(self):
        from minio.error import S3Error

        mock_client = MagicMock()
        mock_client.remove_object.side_effect = S3Error(
            "AccessDenied", "Forbidden", "resource", "", "", ""
        )
        storage = MinIOStorage(mock_client, "test-bucket")

        with pytest.raises(RuntimeError, match="MinIO delete failed"):
            await storage.delete("protected/file.txt")

    @pytest.mark.asyncio
    async def test_upload_s3_error(self):
        from minio.error import S3Error

        mock_client = MagicMock()
        mock_client.put_object.side_effect = S3Error(
            "NoSuchBucket", "Bucket missing", "resource", "", "", ""
        )
        storage = MinIOStorage(mock_client, "test-bucket")

        data = io.BytesIO(b"test")
        with pytest.raises(RuntimeError, match="MinIO upload failed"):
            await storage.upload("test/file.txt", data, "text/plain")


class TestParseQueryResult:
    """Tests for _parse_query_result edge cases."""

    def _make_repo(self):
        return SurrealDBRepository(MagicMock(), "ns", "db")

    def test_empty_list(self):
        repo = self._make_repo()
        assert repo._parse_query_result([]) == []

    def test_none_input(self):
        repo = self._make_repo()
        assert repo._parse_query_result(None) == []

    def test_not_a_list(self):
        repo = self._make_repo()
        assert repo._parse_query_result("bad") == []

    def test_wrapped_result_format(self):
        repo = self._make_repo()
        result = [{"result": [{"id": "1"}, {"id": "2"}]}]
        assert repo._parse_query_result(result) == [{"id": "1"}, {"id": "2"}]

    def test_wrapped_result_none(self):
        repo = self._make_repo()
        result = [{"result": None}]
        assert repo._parse_query_result(result) == []

    def test_direct_list_format(self):
        repo = self._make_repo()
        result = [{"id": "1", "name": "x"}, {"id": "2", "name": "y"}]
        assert repo._parse_query_result(result) == result


class TestCreateContentRecordID:
    """Test create_content with RecordID object variants."""

    @pytest.mark.asyncio
    async def test_create_content_with_record_id_object(self):
        mock_db = MagicMock()
        mock_rid = MagicMock()
        mock_rid.record_id = "abc123"
        mock_db.create.return_value = [{"id": mock_rid}]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        metadata = ContentMetadata(
            content_type="document",
            mime_type="text/plain",
            file_size=50,
            file_path="test.txt",
        )
        result = await repo.create_content(metadata)
        assert result.id == "abc123"

    @pytest.mark.asyncio
    async def test_create_content_dict_return(self):
        mock_db = MagicMock()
        mock_db.create.return_value = {"id": "content:dict123"}

        repo = SurrealDBRepository(mock_db, "ns", "db")
        metadata = ContentMetadata(
            content_type="document",
            mime_type="text/plain",
            file_size=50,
            file_path="test.txt",
        )
        result = await repo.create_content(metadata)
        assert result.id == "dict123"

    @pytest.mark.asyncio
    async def test_create_content_empty_result(self):
        mock_db = MagicMock()
        mock_db.create.return_value = []

        repo = SurrealDBRepository(mock_db, "ns", "db")
        metadata = ContentMetadata(
            content_type="document",
            mime_type="text/plain",
            file_size=50,
            file_path="test.txt",
        )
        result = await repo.create_content(metadata)
        assert result.id is None


class TestListContentFilters:
    """Test list_content with content_type and tags filters."""

    @pytest.mark.asyncio
    async def test_list_content_with_content_type_filter(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": "content:1",
                        "content_type": "youtube",
                        "mime_type": "text/plain",
                        "file_size": 100,
                        "file_path": "yt/1.txt",
                    }
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        items, total = await repo.list_content(content_type="youtube")

        assert len(items) == 1
        assert total == 1
        call_args = mock_db.query.call_args
        assert "content_type = $content_type" in call_args[0][0]
        assert call_args[0][1]["content_type"] == "youtube"

    @pytest.mark.asyncio
    async def test_list_content_with_tags_filter(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [{"result": []}]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        items, total = await repo.list_content(tags=["python", "api"])

        assert len(items) == 0
        call_args = mock_db.query.call_args
        assert "tags CONTAINSALL $tags" in call_args[0][0]
        assert call_args[0][1]["tags"] == ["python", "api"]

    @pytest.mark.asyncio
    async def test_list_content_with_record_id_objects(self):
        mock_id = MagicMock()
        mock_id.id = "abc123"
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": mock_id,
                        "content_type": "document",
                        "mime_type": "text/plain",
                        "file_size": 100,
                        "file_path": "test.txt",
                    }
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        items, total = await repo.list_content()

        assert len(items) == 1
        assert items[0].id == "abc123"


class TestUpdateContent:
    """Tests for update_content."""

    @pytest.mark.asyncio
    async def test_update_content_success(self):
        mock_db = MagicMock()
        mock_db.update.return_value = [
            {
                "id": "content:test123",
                "content_type": "document",
                "title": "Updated Title",
                "mime_type": "text/plain",
                "file_size": 100,
                "file_path": "test.txt",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        metadata = ContentMetadata(
            content_type="document",
            title="Updated Title",
            mime_type="text/plain",
            file_size=100,
            file_path="test.txt",
        )
        result = await repo.update_content("test123", metadata)

        assert result.title == "Updated Title"
        assert result.updated_at is not None
        mock_db.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_content_failure(self):
        mock_db = MagicMock()
        mock_db.update.return_value = []

        repo = SurrealDBRepository(mock_db, "ns", "db")
        metadata = ContentMetadata(
            content_type="document",
            mime_type="text/plain",
            file_size=100,
            file_path="test.txt",
        )
        with pytest.raises(RuntimeError, match="Failed to update content"):
            await repo.update_content("missing", metadata)


class TestCreateChunkRecordID:
    """Test create_chunk with RecordID object."""

    @pytest.mark.asyncio
    async def test_create_chunk_record_id_object(self):
        mock_db = MagicMock()
        mock_rid = MagicMock()
        mock_rid.record_id = "chunk_abc"
        mock_db.create.return_value = [{"id": mock_rid}]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        chunk = ChunkModel(
            content_id="test123", text="some text", chunk_index=0
        )
        result = await repo.create_chunk(chunk)
        assert result.id == "chunk_abc"

    @pytest.mark.asyncio
    async def test_create_chunk_dict_return(self):
        mock_db = MagicMock()
        mock_db.create.return_value = {"id": "chunk:dictret"}

        repo = SurrealDBRepository(mock_db, "ns", "db")
        chunk = ChunkModel(
            content_id="test123", text="some text", chunk_index=0
        )
        result = await repo.create_chunk(chunk)
        assert result.id == "dictret"


class TestDeleteChunks:
    """Tests for delete_chunks."""

    @pytest.mark.asyncio
    async def test_delete_chunks(self):
        mock_db = MagicMock()
        repo = SurrealDBRepository(mock_db, "ns", "db")

        await repo.delete_chunks("test123")

        mock_db.query.assert_called_once()
        call_args = mock_db.query.call_args[0]
        assert "DELETE" in call_args[0]
        assert "chunk" in call_args[0]
        assert call_args[1] == {"content_id": "test123"}


class TestListTagsWithCounts:
    """Tests for list_tags_with_counts."""

    @pytest.mark.asyncio
    async def test_tags_with_counts(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {"tag": "python", "count": 3},
                    {"tag": "api", "count": 2},
                    {"tag": "docker", "count": 1},
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        result = await repo.list_tags_with_counts()

        assert result[0] == {"name": "python", "count": 3}
        assert result[1] == {"name": "api", "count": 2}
        assert result[2] == {"name": "docker", "count": 1}

    @pytest.mark.asyncio
    async def test_tags_empty_result(self):
        mock_db = MagicMock()
        mock_db.query.return_value = []

        repo = SurrealDBRepository(mock_db, "ns", "db")
        result = await repo.list_tags_with_counts()
        assert result == []

    @pytest.mark.asyncio
    async def test_tags_direct_list_format(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {"tag": "ml", "count": 2},
            {"tag": "nlp", "count": 1},
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        result = await repo.list_tags_with_counts()

        assert result[0] == {"name": "ml", "count": 2}
        assert result[1] == {"name": "nlp", "count": 1}

    @pytest.mark.asyncio
    async def test_tags_skips_none_tags(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {"result": [{"tag": "python", "count": 1}, {"tag": None, "count": 0}, {"other": "x"}]}
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        result = await repo.list_tags_with_counts()
        assert len(result) == 1
        assert result[0]["name"] == "python"


class TestFindContentByTitleRecordID:
    """Test find_content_by_title with RecordID objects."""

    @pytest.mark.asyncio
    async def test_find_content_by_title_with_record_id(self):
        mock_id = MagicMock()
        mock_id.id = "abc123"
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": mock_id,
                        "content_type": "document",
                        "title": "Test",
                        "mime_type": "text/plain",
                        "file_size": 100,
                        "file_path": "test.txt",
                    }
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        result = await repo.find_content_by_title("Test")

        assert result is not None
        assert result.id == "abc123"


class TestExtractEntityId:
    """Tests for _extract_entity_id helper."""

    def _make_repo(self):
        return SurrealDBRepository(MagicMock(), "ns", "db")

    def test_with_record_id_attribute(self):
        repo = self._make_repo()
        mock_rid = MagicMock(spec=["record_id"])
        mock_rid.record_id = "abc123"
        assert repo._extract_entity_id(mock_rid) == "abc123"

    def test_with_id_attribute(self):
        repo = self._make_repo()
        mock_rid = MagicMock(spec=["id"])
        mock_rid.id = "def456"
        assert repo._extract_entity_id(mock_rid) == "def456"

    def test_with_string(self):
        repo = self._make_repo()
        assert repo._extract_entity_id("entity:ghi789") == "ghi789"

    def test_with_plain_string(self):
        repo = self._make_repo()
        assert repo._extract_entity_id("simple") == "simple"


class TestParseEntity:
    """Tests for _parse_entity helper."""

    def _make_repo(self):
        return SurrealDBRepository(MagicMock(), "ns", "db")

    def test_parse_entity_basic(self):
        repo = self._make_repo()
        entity = repo._parse_entity({
            "id": "entity:abc",
            "entity_type": "topic",
            "name": "Machine Learning",
            "normalized_name": "machinelearning",
        })
        assert entity.id == "abc"
        assert entity.name == "Machine Learning"
        assert entity.entity_type == EntityType.TOPIC

    def test_parse_entity_with_record_id(self):
        repo = self._make_repo()
        mock_rid = MagicMock(spec=["id"])
        mock_rid.id = "xyz789"
        entity = repo._parse_entity({
            "id": mock_rid,
            "entity_type": "tool",
            "name": "Docker",
            "normalized_name": "docker",
        })
        assert entity.id == "xyz789"


class TestParseContentEntityEdge:
    """Tests for _parse_content_entity_edge helper."""

    def _make_repo(self):
        return SurrealDBRepository(MagicMock(), "ns", "db")

    def test_parse_edge_with_string_ids(self):
        repo = self._make_repo()
        edge = repo._parse_content_entity_edge({
            "id": "content_entity:abc",
            "content_id": "content:c1",
            "entity_id": "entity:e1",
            "edge_type": "discusses",
        })
        assert edge.id == "abc"
        assert edge.content_id == "c1"
        assert edge.entity_id == "e1"

    def test_parse_edge_with_record_id_objects(self):
        repo = self._make_repo()
        mock_cid = MagicMock()
        mock_cid.id = "content_abc"
        mock_eid = MagicMock()
        mock_eid.id = "entity_xyz"
        edge = repo._parse_content_entity_edge({
            "id": "content_entity:edge1",
            "content_id": mock_cid,
            "entity_id": mock_eid,
            "edge_type": "mentions",
        })
        assert edge.content_id == "content_abc"
        assert edge.entity_id == "entity_xyz"


class TestEntityCRUD:
    """Tests for entity create/read/update/delete."""

    @pytest.mark.asyncio
    async def test_create_entity(self):
        mock_db = MagicMock()
        mock_db.create.return_value = [{"id": "entity:new1"}]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        entity = EntityModel(
            entity_type=EntityType.TOPIC,
            name="Machine Learning",
            normalized_name="machinelearning",
        )
        result = await repo.create_entity(entity)

        assert result.id == "new1"
        assert result.created_at is not None
        assert result.updated_at is not None
        mock_db.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_entity_auto_normalize(self):
        mock_db = MagicMock()
        mock_db.create.return_value = [{"id": "entity:new2"}]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        entity = EntityModel(
            entity_type=EntityType.TOOL,
            name="Lang Chain",
            normalized_name="",
        )
        result = await repo.create_entity(entity)
        assert result.normalized_name == "langchain"

    @pytest.mark.asyncio
    async def test_get_entity_found(self):
        mock_db = MagicMock()
        mock_db.select.return_value = [
            {
                "id": "entity:e1",
                "entity_type": "topic",
                "name": "NLP",
                "normalized_name": "nlp",
            }
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        result = await repo.get_entity("e1")

        assert result is not None
        assert result.name == "NLP"
        mock_db.select.assert_called_once_with("entity:e1")

    @pytest.mark.asyncio
    async def test_get_entity_not_found(self):
        mock_db = MagicMock()
        mock_db.select.return_value = []

        repo = SurrealDBRepository(mock_db, "ns", "db")
        result = await repo.get_entity("missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_entity_dict_return(self):
        mock_db = MagicMock()
        mock_db.select.return_value = {
            "id": "entity:e2",
            "entity_type": "person",
            "name": "Alice",
            "normalized_name": "alice",
        }

        repo = SurrealDBRepository(mock_db, "ns", "db")
        result = await repo.get_entity("e2")

        assert result is not None
        assert result.name == "Alice"

    @pytest.mark.asyncio
    async def test_update_entity_success(self):
        mock_db = MagicMock()
        mock_db.update.return_value = [
            {
                "id": "entity:e1",
                "entity_type": "topic",
                "name": "Deep Learning",
                "normalized_name": "deeplearning",
            }
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        result = await repo.update_entity(
            "e1", {"name": "Deep Learning"}
        )

        assert result is not None
        assert result.name == "Deep Learning"

    @pytest.mark.asyncio
    async def test_update_entity_not_found(self):
        mock_db = MagicMock()
        mock_db.update.return_value = []

        repo = SurrealDBRepository(mock_db, "ns", "db")
        result = await repo.update_entity("missing", {"name": "X"})
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_entity(self):
        mock_db = MagicMock()
        repo = SurrealDBRepository(mock_db, "ns", "db")

        await repo.delete_entity("e1")

        assert mock_db.query.call_count == 1
        mock_db.delete.assert_called_once_with("entity:e1")


class TestFindEntityByNormalizedName:
    """Tests for find_entity_by_normalized_name."""

    @pytest.mark.asyncio
    async def test_found_without_type(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": "entity:e1",
                        "entity_type": "topic",
                        "name": "ML",
                        "normalized_name": "ml",
                    }
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        result = await repo.find_entity_by_normalized_name("ml")

        assert result is not None
        assert result.name == "ML"

    @pytest.mark.asyncio
    async def test_found_with_type_filter(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": "entity:e2",
                        "entity_type": "tool",
                        "name": "Docker",
                        "normalized_name": "docker",
                    }
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        result = await repo.find_entity_by_normalized_name(
            "docker", EntityType.TOOL
        )

        assert result is not None
        call_args = mock_db.query.call_args[0]
        assert "entity_type = $entity_type" in call_args[0]
        assert call_args[1]["entity_type"] == "tool"

    @pytest.mark.asyncio
    async def test_not_found(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [{"result": []}]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        result = await repo.find_entity_by_normalized_name("missing")
        assert result is None


class TestFindEntityByAlias:
    """Tests for find_entity_by_alias."""

    @pytest.mark.asyncio
    async def test_found(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": "entity:e1",
                        "entity_type": "topic",
                        "name": "Machine Learning",
                        "normalized_name": "machinelearning",
                    }
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        result = await repo.find_entity_by_alias("ML")
        assert result is not None
        assert result.name == "Machine Learning"

    @pytest.mark.asyncio
    async def test_not_found(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [{"result": []}]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        result = await repo.find_entity_by_alias("Nonexistent")
        assert result is None


class TestListEntities:
    """Tests for list_entities and list_all_entities."""

    @pytest.mark.asyncio
    async def test_list_entities_no_filter(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": "entity:1",
                        "entity_type": "topic",
                        "name": "AI",
                        "normalized_name": "ai",
                    },
                    {
                        "id": "entity:2",
                        "entity_type": "tool",
                        "name": "Docker",
                        "normalized_name": "docker",
                    },
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        entities, count = await repo.list_entities()

        assert len(entities) == 2
        assert count == 2

    @pytest.mark.asyncio
    async def test_list_entities_with_type_filter(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": "entity:1",
                        "entity_type": "topic",
                        "name": "AI",
                        "normalized_name": "ai",
                    }
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        entities, count = await repo.list_entities(
            entity_type=EntityType.TOPIC
        )

        assert len(entities) == 1
        call_args = mock_db.query.call_args[0]
        assert "entity_type = $entity_type" in call_args[0]
        assert call_args[1]["entity_type"] == "topic"

    @pytest.mark.asyncio
    async def test_list_all_entities(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": "entity:1",
                        "entity_type": "topic",
                        "name": "AI",
                        "normalized_name": "ai",
                    }
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        entities = await repo.list_all_entities()

        assert len(entities) == 1
        assert entities[0].name == "AI"


class TestContentEntityEdgeCRUD:
    """Tests for content-entity edge operations."""

    @pytest.mark.asyncio
    async def test_create_content_entity_edge(self):
        mock_db = MagicMock()
        mock_db.create.return_value = [
            {"id": "content_entity:edge1"}
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        edge = ContentEntityEdge(
            content_id="c1",
            entity_id="e1",
            edge_type=EdgeType.DISCUSSES,
            confidence=0.9,
        )
        result = await repo.create_content_entity_edge(edge)

        assert result.id == "edge1"
        assert result.created_at is not None
        call_data = mock_db.create.call_args[0][1]
        assert call_data["content_id"] == "content:c1"
        assert call_data["entity_id"] == "entity:e1"

    @pytest.mark.asyncio
    async def test_delete_content_entity_edges(self):
        mock_db = MagicMock()
        repo = SurrealDBRepository(mock_db, "ns", "db")

        await repo.delete_content_entity_edges("c1")

        mock_db.query.assert_called_once()
        call_args = mock_db.query.call_args[0]
        assert "DELETE" in call_args[0]
        assert "content_entity" in call_args[0]
        assert call_args[1] == {"content_id": "content:c1"}


class TestGetEntitiesForContent:
    """Tests for get_entities_for_content."""

    @pytest.mark.asyncio
    async def test_with_results(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": "content_entity:edge1",
                        "content_id": "content:c1",
                        "entity_id": "entity:e1",
                        "edge_type": "discusses",
                        "entity": {
                            "id": "entity:e1",
                            "entity_type": "topic",
                            "name": "ML",
                            "normalized_name": "ml",
                        },
                    }
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        results = await repo.get_entities_for_content("c1")

        assert len(results) == 1
        entity, edge = results[0]
        assert entity.name == "ML"
        assert edge.edge_type == EdgeType.DISCUSSES

    @pytest.mark.asyncio
    async def test_empty_results(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [{"result": []}]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        results = await repo.get_entities_for_content("c1")
        assert results == []

    @pytest.mark.asyncio
    async def test_skips_items_without_entity(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": "content_entity:edge1",
                        "content_id": "content:c1",
                        "entity_id": "entity:e1",
                        "edge_type": "discusses",
                        # No "entity" key
                    }
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        results = await repo.get_entities_for_content("c1")
        assert results == []


class TestGetContentForEntity:
    """Tests for get_content_for_entity."""

    @pytest.mark.asyncio
    async def test_with_results(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": "content_entity:edge1",
                        "content_id": "content:c1",
                        "entity_id": "entity:e1",
                        "edge_type": "discusses",
                        "content": {
                            "id": "content:c1",
                            "content_type": "document",
                            "mime_type": "text/plain",
                            "file_size": 100,
                            "file_path": "test.txt",
                            "title": "Test Doc",
                        },
                    }
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        results = await repo.get_content_for_entity("e1")

        assert len(results) == 1
        content, edge = results[0]
        assert content.title == "Test Doc"
        assert edge.edge_type == EdgeType.DISCUSSES

    @pytest.mark.asyncio
    async def test_with_record_id_in_content(self):
        mock_cid = MagicMock()
        mock_cid.id = "c1"
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": "content_entity:edge1",
                        "content_id": "content:c1",
                        "entity_id": "entity:e1",
                        "edge_type": "mentions",
                        "content": {
                            "id": mock_cid,
                            "content_type": "youtube",
                            "mime_type": "text/plain",
                            "file_size": 200,
                            "file_path": "yt.txt",
                        },
                    }
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        results = await repo.get_content_for_entity("e1")

        assert len(results) == 1
        content, _ = results[0]
        assert content.id == "c1"

    @pytest.mark.asyncio
    async def test_skips_items_without_content(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": "content_entity:edge1",
                        "content_id": "content:c1",
                        "entity_id": "entity:e1",
                        "edge_type": "discusses",
                    }
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        results = await repo.get_content_for_entity("e1")
        assert results == []


class TestFindOrCreateEntity:
    """Tests for find_or_create_entity."""

    @pytest.mark.asyncio
    async def test_finds_by_normalized_name(self):
        mock_db = MagicMock()
        existing = {
            "id": "entity:e1",
            "entity_type": "topic",
            "name": "ML",
            "normalized_name": "ml",
        }
        mock_db.query.return_value = [{"result": [existing]}]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        entity, was_created = await repo.find_or_create_entity(
            "ML", EntityType.TOPIC
        )

        assert not was_created
        assert entity.name == "ML"

    @pytest.mark.asyncio
    async def test_finds_by_alias(self):
        mock_db = MagicMock()
        # First query (find_entity_by_normalized_name) returns nothing
        # Second query (find_entity_by_alias) returns the entity
        mock_db.query.side_effect = [
            [{"result": []}],
            [
                {
                    "result": [
                        {
                            "id": "entity:e1",
                            "entity_type": "topic",
                            "name": "Machine Learning",
                            "normalized_name": "machinelearning",
                        }
                    ]
                }
            ],
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        entity, was_created = await repo.find_or_create_entity(
            "ML", EntityType.TOPIC
        )

        assert not was_created
        assert entity.name == "Machine Learning"

    @pytest.mark.asyncio
    async def test_creates_new_entity(self):
        mock_db = MagicMock()
        # Both find queries return nothing
        mock_db.query.side_effect = [
            [{"result": []}],
            [{"result": []}],
        ]
        mock_db.create.return_value = [{"id": "entity:new1"}]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        entity, was_created = await repo.find_or_create_entity(
            "New Topic", EntityType.TOPIC
        )

        assert was_created
        assert entity.id == "new1"
        assert entity.name == "New Topic"

    @pytest.mark.asyncio
    async def test_alias_match_wrong_type_creates_new(self):
        mock_db = MagicMock()
        # find_by_normalized_name returns nothing
        # find_by_alias returns entity with different type
        mock_db.query.side_effect = [
            [{"result": []}],
            [
                {
                    "result": [
                        {
                            "id": "entity:e1",
                            "entity_type": "person",
                            "name": "Docker",
                            "normalized_name": "docker",
                        }
                    ]
                }
            ],
        ]
        mock_db.create.return_value = [{"id": "entity:new2"}]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        entity, was_created = await repo.find_or_create_entity(
            "Docker", EntityType.TOOL
        )

        assert was_created
        assert entity.id == "new2"


class TestUpdateContentExtractionStatus:
    """Tests for update_content_extraction_status."""

    @pytest.mark.asyncio
    async def test_update_extraction_status(self):
        mock_db = MagicMock()
        repo = SurrealDBRepository(mock_db, "ns", "db")

        await repo.update_content_extraction_status("c1", "completed")

        mock_db.query.assert_called_once()
        call_args = mock_db.query.call_args[0]
        assert "entity_extraction_status" in call_args[0]
        assert call_args[1]["content_id"] == "content:c1"
        assert call_args[1]["status"] == "completed"


class TestGetTopicHierarchy:
    """Tests for get_topic_hierarchy."""

    @pytest.mark.asyncio
    async def test_returns_topics(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": "entity:t1",
                        "entity_type": "topic",
                        "name": "AI",
                        "normalized_name": "ai",
                        "hierarchy": ["AI"],
                    },
                    {
                        "id": "entity:t2",
                        "entity_type": "topic",
                        "name": "ML",
                        "normalized_name": "ml",
                        "hierarchy": ["AI", "ML"],
                    },
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        topics = await repo.get_topic_hierarchy()

        assert len(topics) == 2
        assert topics[0].name == "AI"
        assert topics[1].hierarchy == ["AI", "ML"]

    @pytest.mark.asyncio
    async def test_empty_topics(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [{"result": []}]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        topics = await repo.get_topic_hierarchy()
        assert topics == []


class TestClassificationMethods:
    """Tests for classification-related methods."""

    @pytest.mark.asyncio
    async def test_update_classification_status(self):
        mock_db = MagicMock()
        repo = SurrealDBRepository(mock_db, "ns", "db")

        await repo.update_content_classification_status(
            "c1", "processing"
        )

        mock_db.query.assert_called_once()
        call_args = mock_db.query.call_args[0]
        assert "classification_status" in call_args[0]
        assert call_args[1]["content_id"] == "content:c1"
        assert call_args[1]["status"] == "processing"

    @pytest.mark.asyncio
    async def test_update_content_classification(self):
        mock_db = MagicMock()
        repo = SurrealDBRepository(mock_db, "ns", "db")

        classification = {
            "tier": "A",
            "quality_score": 85,
            "labels": ["tutorial"],
        }
        await repo.update_content_classification("c1", classification)

        mock_db.query.assert_called_once()
        call_args = mock_db.query.call_args[0]
        assert "metadata.classification" in call_args[0]
        assert "classification_tier" in call_args[0]
        assert "classification_score" in call_args[0]
        assert call_args[1]["data"] == classification
        assert call_args[1]["tier"] == "A"
        assert call_args[1]["score"] == 85

    @pytest.mark.asyncio
    async def test_update_content_classification_defaults(self):
        mock_db = MagicMock()
        repo = SurrealDBRepository(mock_db, "ns", "db")

        classification = {"labels": ["reference"]}
        await repo.update_content_classification("c1", classification)

        call_args = mock_db.query.call_args[0]
        assert call_args[1]["tier"] == ""
        assert call_args[1]["score"] == 0


class TestGetInterestProfile:
    """Tests for get_interest_profile."""

    @pytest.mark.asyncio
    async def test_returns_all_signals(self):
        mock_db = MagicMock()
        mock_db.query.side_effect = [
            [{"result": [{"name": "AI"}, {"name": "ML"}]}],
            [{"result": [{"tag": "python"}, {"tag": "ml"}]}],
            [
                {
                    "result": [
                        {"channel": "3Blue1Brown"},
                        {"channel": "Fireship"},
                    ]
                }
            ],
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        profile = await repo.get_interest_profile()

        assert profile["topics"] == ["AI", "ML"]
        assert profile["tags"] == ["python", "ml"]
        assert profile["channels"] == ["3Blue1Brown", "Fireship"]

    @pytest.mark.asyncio
    async def test_handles_empty_results(self):
        mock_db = MagicMock()
        mock_db.query.side_effect = [
            [{"result": []}],
            [{"result": []}],
            [{"result": []}],
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        profile = await repo.get_interest_profile()

        assert profile == {"topics": [], "tags": [], "channels": []}

    @pytest.mark.asyncio
    async def test_skips_none_values(self):
        mock_db = MagicMock()
        mock_db.query.side_effect = [
            [{"result": [{"name": "AI"}, {"name": None}]}],
            [{"result": [{"tag": None}]}],
            [{"result": [{"channel": "Test"}, {"other": "x"}]}],
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        profile = await repo.get_interest_profile()

        assert profile["topics"] == ["AI"]
        assert profile["tags"] == []
        assert profile["channels"] == ["Test"]


class TestFindPotentialDuplicates:
    """Tests for find_potential_duplicates."""

    @pytest.mark.asyncio
    async def test_finds_duplicates(self):
        mock_db = MagicMock()
        # list_all_entities query
        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": "entity:1",
                        "entity_type": "topic",
                        "name": "Machine Learning",
                        "normalized_name": "machinelearning",
                    },
                    {
                        "id": "entity:2",
                        "entity_type": "topic",
                        "name": "Machine Learnin",
                        "normalized_name": "machinelearnin",
                    },
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        groups = await repo.find_potential_duplicates(max_distance=1)

        assert len(groups) == 1
        assert len(groups[0]) == 2

    @pytest.mark.asyncio
    async def test_no_duplicates(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {
                "result": [
                    {
                        "id": "entity:1",
                        "entity_type": "topic",
                        "name": "Python",
                        "normalized_name": "python",
                    },
                    {
                        "id": "entity:2",
                        "entity_type": "tool",
                        "name": "Docker",
                        "normalized_name": "docker",
                    },
                ]
            }
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        groups = await repo.find_potential_duplicates()

        assert groups == []


class TestGetGraphData:
    """Tests for get_graph_data."""

    @pytest.mark.asyncio
    async def test_graph_data_basic(self):
        mock_db = MagicMock()
        # Use IDs without prefix so ContentMetadata.id matches
        # edge source/target after split(":")[-1]
        mock_db.query.side_effect = [
            # Content query
            [
                {
                    "result": [
                        {
                            "id": "c1",
                            "content_type": "document",
                            "mime_type": "text/plain",
                            "file_size": 100,
                            "file_path": "a.txt",
                            "title": "Doc A",
                        },
                        {
                            "id": "c2",
                            "content_type": "document",
                            "mime_type": "text/plain",
                            "file_size": 200,
                            "file_path": "b.txt",
                            "title": "Doc B",
                        },
                    ]
                }
            ],
            # Link query
            [
                {
                    "result": [
                        {
                            "id": "link:l1",
                            "source": "content:c1",
                            "target": "content:c2",
                            "link_text": "Link",
                            "link_type": "wiki",
                        }
                    ]
                }
            ],
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        nodes, edges = await repo.get_graph_data()

        assert len(nodes) == 2
        assert len(edges) == 1
        assert edges[0].source == "c1"
        assert edges[0].target == "c2"

    @pytest.mark.asyncio
    async def test_graph_data_with_filters(self):
        mock_db = MagicMock()
        mock_db.query.side_effect = [
            [{"result": []}],
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        nodes, edges = await repo.get_graph_data(
            tags=["python"], content_type="youtube", limit=100
        )

        assert nodes == []
        assert edges == []
        call_args = mock_db.query.call_args[0]
        assert "content_type = $content_type" in call_args[0]
        assert "tags CONTAINSALL $tags" in call_args[0]

    @pytest.mark.asyncio
    async def test_graph_data_filters_edges_to_node_set(self):
        mock_db = MagicMock()
        mock_db.query.side_effect = [
            # Content: only c1
            [
                {
                    "result": [
                        {
                            "id": "c1",
                            "content_type": "document",
                            "mime_type": "text/plain",
                            "file_size": 100,
                            "file_path": "a.txt",
                        }
                    ]
                }
            ],
            # Links: c1->c2 (c2 not in node set) and c1->None
            [
                {
                    "result": [
                        {
                            "id": "link:l1",
                            "source": "content:c1",
                            "target": "content:c2",
                            "link_text": "External",
                            "link_type": "wiki",
                        },
                        {
                            "id": "link:l2",
                            "source": "content:c1",
                            "target": None,
                            "link_text": "Unresolved",
                            "link_type": "wiki",
                        },
                    ]
                }
            ],
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        nodes, edges = await repo.get_graph_data()

        assert len(nodes) == 1
        # l1 excluded (c2 not in node set), l2 included (None target)
        assert len(edges) == 1
        assert edges[0].target is None

    @pytest.mark.asyncio
    async def test_graph_data_with_record_id_objects(self):
        mock_src = MagicMock()
        mock_src.id = "c1"
        mock_tgt = MagicMock()
        mock_tgt.id = "c2"
        mock_nid1 = MagicMock()
        mock_nid1.id = "c1"
        mock_nid2 = MagicMock()
        mock_nid2.id = "c2"

        mock_db = MagicMock()
        mock_db.query.side_effect = [
            [
                {
                    "result": [
                        {
                            "id": mock_nid1,
                            "content_type": "document",
                            "mime_type": "text/plain",
                            "file_size": 100,
                            "file_path": "a.txt",
                        },
                        {
                            "id": mock_nid2,
                            "content_type": "document",
                            "mime_type": "text/plain",
                            "file_size": 200,
                            "file_path": "b.txt",
                        },
                    ]
                }
            ],
            [
                {
                    "result": [
                        {
                            "id": MagicMock(id="l1"),
                            "source": mock_src,
                            "target": mock_tgt,
                            "link_text": "Link",
                            "link_type": "wiki",
                        }
                    ]
                }
            ],
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        nodes, edges = await repo.get_graph_data()

        assert len(nodes) == 2
        assert len(edges) == 1

    @pytest.mark.asyncio
    async def test_graph_data_link_missing_source(self):
        mock_db = MagicMock()
        mock_db.query.side_effect = [
            [
                {
                    "result": [
                        {
                            "id": "c1",
                            "content_type": "document",
                            "mime_type": "text/plain",
                            "file_size": 100,
                            "file_path": "a.txt",
                        }
                    ]
                }
            ],
            # Link missing "source" key
            [
                {
                    "result": [
                        {
                            "id": "link:l1",
                            "target": "content:c1",
                            "link_text": "Bad",
                            "link_type": "wiki",
                        }
                    ]
                }
            ],
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        nodes, edges = await repo.get_graph_data()

        assert len(nodes) == 1
        assert len(edges) == 0


class TestGetNeighborhood:
    """Tests for get_neighborhood."""

    @pytest.mark.asyncio
    async def test_center_node_not_found(self):
        mock_db = MagicMock()
        mock_db.select.return_value = []

        repo = SurrealDBRepository(mock_db, "ns", "db")
        nodes, edges = await repo.get_neighborhood("missing")

        assert nodes == []
        assert edges == []

    @pytest.mark.asyncio
    async def test_neighborhood_depth_1(self):
        mock_db = MagicMock()

        # get_content("center") for center node
        mock_db.select.side_effect = [
            # Center node
            [
                {
                    "id": "content:center",
                    "content_type": "document",
                    "mime_type": "text/plain",
                    "file_size": 100,
                    "file_path": "center.txt",
                }
            ],
            # get_content("neighbor1") for outgoing target
            [
                {
                    "id": "content:neighbor1",
                    "content_type": "document",
                    "mime_type": "text/plain",
                    "file_size": 200,
                    "file_path": "n1.txt",
                }
            ],
        ]

        # get_links_by_source("center") then
        # get_links_by_target("center")
        mock_db.query.side_effect = [
            # outgoing links from center
            [
                {
                    "result": [
                        {
                            "id": "link:out1",
                            "source": "content:center",
                            "target": "content:neighbor1",
                            "link_text": "Out",
                            "link_type": "wiki",
                        }
                    ]
                }
            ],
            # incoming links to center
            [{"result": []}],
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        nodes, edges = await repo.get_neighborhood("center", depth=1)

        assert len(nodes) == 2
        assert len(edges) == 1
        node_ids = {n.id for n in nodes}
        assert "content:center" in node_ids or "center" in node_ids

    @pytest.mark.asyncio
    async def test_neighborhood_no_links(self):
        mock_db = MagicMock()
        mock_db.select.return_value = [
            {
                "id": "content:lonely",
                "content_type": "document",
                "mime_type": "text/plain",
                "file_size": 50,
                "file_path": "lonely.txt",
            }
        ]
        mock_db.query.side_effect = [
            [{"result": []}],  # outgoing
            [{"result": []}],  # incoming
        ]

        repo = SurrealDBRepository(mock_db, "ns", "db")
        nodes, edges = await repo.get_neighborhood("lonely")

        assert len(nodes) == 1
        assert len(edges) == 0
