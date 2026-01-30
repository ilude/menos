"""Storage services for MinIO and SurrealDB."""

import io
from datetime import UTC, datetime
from typing import BinaryIO

from minio import Minio
from minio.error import S3Error
from surrealdb import Surreal

from menos.models import ChunkModel, ContentMetadata


class MinIOStorage:
    """MinIO client wrapper for file storage."""

    def __init__(self, client: Minio, bucket: str):
        """Initialize MinIO storage.

        Args:
            client: Minio client instance
            bucket: Bucket name for storing files
        """
        self.client = client
        self.bucket = bucket

    async def upload(self, file_path: str, data: BinaryIO, content_type: str) -> int:
        """Upload file to MinIO.

        Args:
            file_path: Path where to store file
            data: File data stream
            content_type: MIME type of file

        Returns:
            File size in bytes

        Raises:
            S3Error: If upload fails
        """
        try:
            data.seek(0, 2)  # Seek to end
            file_size = data.tell()
            data.seek(0)  # Reset to start

            self.client.put_object(
                self.bucket,
                file_path,
                data,
                file_size,
                content_type=content_type,
            )
            return file_size
        except S3Error as e:
            raise RuntimeError(f"MinIO upload failed: {e}") from e

    async def download(self, file_path: str) -> bytes:
        """Download file from MinIO.

        Args:
            file_path: Path to file

        Returns:
            File contents as bytes

        Raises:
            S3Error: If download fails
        """
        try:
            response = self.client.get_object(self.bucket, file_path)
            return response.read()
        except S3Error as e:
            raise RuntimeError(f"MinIO download failed: {e}") from e

    async def delete(self, file_path: str) -> None:
        """Delete file from MinIO.

        Args:
            file_path: Path to file

        Raises:
            S3Error: If deletion fails
        """
        try:
            self.client.remove_object(self.bucket, file_path)
        except S3Error as e:
            raise RuntimeError(f"MinIO delete failed: {e}") from e


class SurrealDBRepository:
    """SurrealDB client wrapper for metadata storage."""

    def __init__(
        self,
        db: Surreal,
        namespace: str,
        database: str,
        username: str = "root",
        password: str = "root",
    ):
        """Initialize SurrealDB repository.

        Args:
            db: Surreal database connection
            namespace: Database namespace
            database: Database name
            username: Database username
            password: Database password
        """
        self.db = db
        self.namespace = namespace
        self.database = database
        self.username = username
        self.password = password

    async def connect(self) -> None:
        """Connect to database, authenticate, and select namespace/database."""
        # Authenticate with credentials
        self.db.signin({"username": self.username, "password": self.password})
        # Select namespace and database
        self.db.use(self.namespace, self.database)

    async def create_content(self, metadata: ContentMetadata) -> ContentMetadata:
        """Create content metadata record.

        Args:
            metadata: Content metadata

        Returns:
            Created metadata with ID

        Raises:
            Exception: If creation fails
        """
        now = datetime.now(UTC)
        metadata.created_at = now
        metadata.updated_at = now

        result = self.db.create("content", metadata.model_dump(exclude_none=True))
        if result:
            metadata.id = result[0]["id"].split(":")[-1]
        return metadata

    async def get_content(self, content_id: str) -> ContentMetadata | None:
        """Get content metadata by ID.

        Args:
            content_id: Content ID

        Returns:
            Content metadata or None if not found
        """
        result = self.db.select(f"content:{content_id}")
        if result:
            return ContentMetadata(**result[0])
        return None

    async def list_content(
        self,
        offset: int = 0,
        limit: int = 50,
        content_type: str | None = None,
    ) -> tuple[list[ContentMetadata], int]:
        """List content metadata.

        Args:
            offset: Query offset
            limit: Query limit
            content_type: Optional filter by content type

        Returns:
            Tuple of (content list, total count)
        """
        where_clause = ""
        if content_type:
            where_clause = f" WHERE content_type = '{content_type}'"

        result = self.db.query(
            f"SELECT * FROM content{where_clause} LIMIT {limit} OFFSET {offset}"
        )
        if result and result[0].get("result"):
            items = [ContentMetadata(**item) for item in result[0]["result"]]
            return items, len(items)
        return [], 0

    async def update_content(self, content_id: str, metadata: ContentMetadata) -> ContentMetadata:
        """Update content metadata.

        Args:
            content_id: Content ID
            metadata: Updated metadata

        Returns:
            Updated metadata

        Raises:
            Exception: If update fails
        """
        metadata.updated_at = datetime.now(UTC)
        result = self.db.update(f"content:{content_id}", metadata.model_dump(exclude_none=True))
        if result:
            return ContentMetadata(**result[0])
        raise RuntimeError(f"Failed to update content {content_id}")

    async def delete_content(self, content_id: str) -> None:
        """Delete content metadata.

        Args:
            content_id: Content ID
        """
        self.db.delete(f"content:{content_id}")

    async def create_chunk(self, chunk: ChunkModel) -> ChunkModel:
        """Create content chunk.

        Args:
            chunk: Chunk data

        Returns:
            Created chunk with ID
        """
        chunk.created_at = datetime.now(UTC)
        result = self.db.create("chunk", chunk.model_dump(exclude_none=True))
        if result:
            chunk.id = result[0]["id"].split(":")[-1]
        return chunk

    async def get_chunks(self, content_id: str) -> list[ChunkModel]:
        """Get all chunks for content.

        Args:
            content_id: Content ID

        Returns:
            List of chunks
        """
        result = self.db.query(f"SELECT * FROM chunk WHERE content_id = '{content_id}'")
        if result and result[0].get("result"):
            return [ChunkModel(**item) for item in result[0]["result"]]
        return []

    async def delete_chunks(self, content_id: str) -> None:
        """Delete all chunks for content.

        Args:
            content_id: Content ID
        """
        self.db.query(f"DELETE FROM chunk WHERE content_id = '{content_id}'")
