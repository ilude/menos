"""Storage services for MinIO and SurrealDB."""

from datetime import UTC, datetime
from typing import BinaryIO

from minio import Minio
from minio.error import S3Error
from surrealdb import Surreal

from menos.models import (
    ChunkModel,
    ContentEntityEdge,
    ContentMetadata,
    EntityModel,
    EntityType,
    LinkModel,
)
from menos.services.normalization import normalize_name


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

    def _parse_query_result(self, result: list) -> list[dict]:
        """Parse SurrealDB query result handling v2 format variations.

        Args:
            result: Raw query result from SurrealDB

        Returns:
            List of record dictionaries
        """
        if (
            not result
            or not isinstance(result, list)
            or len(result) == 0
        ):
            return []
        first = result[0]
        if isinstance(first, dict) and "result" in first:
            return first["result"] or []
        return result

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
            # Handle both dict (new) and list (old) return types
            record = result[0] if isinstance(result, list) else result
            record_id = record["id"]
            # Handle RecordID object or string
            if hasattr(record_id, "record_id"):
                metadata.id = str(record_id.record_id)
            else:
                metadata.id = str(record_id).split(":")[-1]
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
        tags: list[str] | None = None,
    ) -> tuple[list[ContentMetadata], int]:
        """List content metadata.

        Args:
            offset: Query offset
            limit: Query limit
            content_type: Optional filter by content type
            tags: Optional filter by tags (must have all specified tags)

        Returns:
            Tuple of (content list, total count)
        """
        # Build parameterized query
        params: dict = {"limit": limit, "offset": offset}
        where_clauses = []
        if content_type:
            where_clauses.append("content_type = $content_type")
            params["content_type"] = content_type
        if tags:
            where_clauses.append("tags CONTAINSALL $tags")
            params["tags"] = tags

        where_clause = ""
        if where_clauses:
            where_clause = " WHERE " + " AND ".join(where_clauses)

        result = self.db.query(
            f"SELECT * FROM content{where_clause} LIMIT $limit START $offset",
            params,
        )
        # Use the helper
        raw_items = self._parse_query_result(result)
        # Convert RecordID objects to strings
        items = []
        for item in raw_items:
            item_copy = dict(item)
            if "id" in item_copy and hasattr(item_copy["id"], "id"):
                item_copy["id"] = item_copy["id"].id
            items.append(ContentMetadata(**item_copy))
        return items, len(items)

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
        result = self.db.update(
            f"content:{content_id}", metadata.model_dump(exclude_none=True)
        )
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
            # Handle both dict (new) and list (old) return types
            record = result[0] if isinstance(result, list) else result
            record_id = record["id"]
            # Handle RecordID object or string
            if hasattr(record_id, "record_id"):
                chunk.id = str(record_id.record_id)
            else:
                chunk.id = str(record_id).split(":")[-1]
        return chunk

    async def get_chunks(self, content_id: str) -> list[ChunkModel]:
        """Get all chunks for content.

        Args:
            content_id: Content ID

        Returns:
            List of chunks
        """
        result = self.db.query(
            "SELECT * FROM chunk WHERE content_id = $content_id",
            {"content_id": content_id},
        )
        raw_items = self._parse_query_result(result)
        return [ChunkModel(**item) for item in raw_items]

    async def delete_chunks(self, content_id: str) -> None:
        """Delete all chunks for content.

        Args:
            content_id: Content ID
        """
        self.db.query(
            "DELETE (SELECT id FROM chunk WHERE content_id = $content_id)",
            {"content_id": content_id},
        )

    async def list_tags_with_counts(self) -> list[dict[str, str | int]]:
        """Get all tags with their counts, sorted by count descending then alphabetically.

        Returns:
            List of dicts with 'name' and 'count' keys, sorted by count (desc) then name (asc)
        """
        result = self.db.query(
            "SELECT array::flatten(tags) as tag FROM content WHERE tags != NONE "
            "GROUP BY tag FETCH tag UNGROUP"
        )

        tags_data = []
        if result and isinstance(result, list) and len(result) > 0:
            # Handle both old format (wrapped in result key) and new format (direct list)
            if isinstance(result[0], dict) and "result" in result[0]:
                raw_items = result[0]["result"]
            else:
                raw_items = result

            # Count occurrences of each tag and build response
            tag_counts: dict[str, int] = {}
            for item in raw_items:
                if isinstance(item, dict):
                    tag = item.get("tag")
                    if tag:
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1

            # Sort by count descending, then by name ascending
            sorted_tags = sorted(tag_counts.items(), key=lambda x: (-x[1], x[0]))

            tags_data = [{"name": name, "count": count} for name, count in sorted_tags]

        return tags_data

    async def find_content_by_title(self, title: str) -> ContentMetadata | None:
        """Find content by exact title match.

        Args:
            title: Content title to search for

        Returns:
            Content metadata or None if not found
        """
        result = self.db.query(
            "SELECT * FROM content WHERE title = $title LIMIT 1",
            {"title": title},
        )
        raw_items = self._parse_query_result(result)

        if raw_items:
            item = dict(raw_items[0])
            if "id" in item and hasattr(item["id"], "id"):
                item["id"] = item["id"].id
            return ContentMetadata(**item)
        return None

    async def create_link(self, link: LinkModel) -> LinkModel:
        """Create link between content items.

        Args:
            link: Link data

        Returns:
            Created link with ID
        """
        link.created_at = datetime.now(UTC)
        link_data = link.model_dump(exclude_none=True)

        # Convert IDs to record references
        link_data["source"] = f"content:{link_data['source']}"
        if link_data.get("target"):
            link_data["target"] = f"content:{link_data['target']}"

        result = self.db.create("link", link_data)
        if result:
            record = result[0] if isinstance(result, list) else result
            record_id = record["id"]
            if hasattr(record_id, "record_id"):
                link.id = str(record_id.record_id)
            else:
                link.id = str(record_id).split(":")[-1]
        return link

    async def delete_links_by_source(self, content_id: str) -> None:
        """Delete all links originating from a content item.

        Args:
            content_id: Source content ID
        """
        self.db.query(
            "DELETE (SELECT id FROM link WHERE source = $source)",
            {"source": f"content:{content_id}"},
        )

    async def get_links_by_source(self, content_id: str) -> list[LinkModel]:
        """Get all links originating from a content item.

        Args:
            content_id: Source content ID

        Returns:
            List of links
        """
        result = self.db.query(
            "SELECT * FROM link WHERE source = $source",
            {"source": f"content:{content_id}"},
        )
        raw_items = self._parse_query_result(result)

        links = []
        for item in raw_items:
            item_copy = dict(item)
            # Convert record references to simple IDs
            if "source" in item_copy:
                source_val = item_copy["source"]
                item_copy["source"] = (
                    source_val.id
                    if hasattr(source_val, "id")
                    else str(source_val).split(":")[-1]
                )
            if "target" in item_copy and item_copy["target"]:
                target_val = item_copy["target"]
                item_copy["target"] = (
                    target_val.id
                    if hasattr(target_val, "id")
                    else str(target_val).split(":")[-1]
                )
            if "id" in item_copy and hasattr(item_copy["id"], "id"):
                item_copy["id"] = item_copy["id"].id
            links.append(LinkModel(**item_copy))
        return links

    async def get_links_by_target(self, content_id: str) -> list[LinkModel]:
        """Get all links pointing to a content item (backlinks).

        Args:
            content_id: Target content ID

        Returns:
            List of links
        """
        result = self.db.query(
            "SELECT * FROM link WHERE target = $target",
            {"target": f"content:{content_id}"},
        )
        raw_items = self._parse_query_result(result)

        links = []
        for item in raw_items:
            item_copy = dict(item)
            # Convert record references to simple IDs
            if "source" in item_copy:
                source_val = item_copy["source"]
                item_copy["source"] = (
                    source_val.id
                    if hasattr(source_val, "id")
                    else str(source_val).split(":")[-1]
                )
            if "target" in item_copy and item_copy["target"]:
                target_val = item_copy["target"]
                item_copy["target"] = (
                    target_val.id
                    if hasattr(target_val, "id")
                    else str(target_val).split(":")[-1]
                )
            if "id" in item_copy and hasattr(item_copy["id"], "id"):
                item_copy["id"] = item_copy["id"].id
            links.append(LinkModel(**item_copy))
        return links

    async def get_graph_data(
        self,
        tags: list[str] | None = None,
        content_type: str | None = None,
        limit: int = 500,
    ) -> tuple[list[ContentMetadata], list[LinkModel]]:
        """Get graph data for visualization.

        Args:
            tags: Optional filter by tags (must have all specified tags)
            content_type: Optional filter by content type
            limit: Maximum number of nodes to return

        Returns:
            Tuple of (nodes, edges) where nodes are ContentMetadata and edges are LinkModel
        """
        # Build content query with filters
        params: dict = {"limit": limit}
        where_clauses = []
        if content_type:
            where_clauses.append("content_type = $content_type")
            params["content_type"] = content_type
        if tags:
            where_clauses.append("tags CONTAINSALL $tags")
            params["tags"] = tags

        where_clause = ""
        if where_clauses:
            where_clause = " WHERE " + " AND ".join(where_clauses)

        # Get content nodes
        content_result = self.db.query(
            f"SELECT * FROM content{where_clause} LIMIT $limit",
            params,
        )

        nodes = []
        node_ids = set()

        raw_items = self._parse_query_result(content_result)
        for item in raw_items:
            item_copy = dict(item)
            if "id" in item_copy and hasattr(item_copy["id"], "id"):
                item_copy["id"] = item_copy["id"].id
            node = ContentMetadata(**item_copy)
            if node.id:
                nodes.append(node)
                node_ids.add(node.id)

        # Get all links where both source and target are in our node set
        edges = []
        if node_ids:
            # Build query for links between nodes
            node_refs = [f"content:{nid}" for nid in node_ids]
            link_result = self.db.query(
                "SELECT * FROM link WHERE source IN $ids OR target IN $ids",
                {"ids": node_refs},
            )

            raw_links = self._parse_query_result(link_result)
            for item in raw_links:
                item_copy = dict(item)
                # Convert record references to simple IDs
                if "source" in item_copy:
                    source_val = item_copy["source"]
                    source_id = (
                        source_val.id
                        if hasattr(source_val, "id")
                        else str(source_val).split(":")[-1]
                    )
                    item_copy["source"] = source_id
                else:
                    continue

                if "target" in item_copy and item_copy["target"]:
                    target_val = item_copy["target"]
                    target_id = (
                        target_val.id
                        if hasattr(target_val, "id")
                        else str(target_val).split(":")[-1]
                    )
                    item_copy["target"] = target_id
                else:
                    item_copy["target"] = None

                if "id" in item_copy and hasattr(item_copy["id"], "id"):
                    item_copy["id"] = item_copy["id"].id

                # Only include links where both source and target are in node set
                # (or target is None for unresolved links)
                link = LinkModel(**item_copy)
                if link.source in node_ids and (
                    link.target is None or link.target in node_ids
                ):
                    edges.append(link)

        return nodes, edges

    async def get_neighborhood(
        self,
        content_id: str,
        depth: int = 1,
    ) -> tuple[list[ContentMetadata], list[LinkModel]]:
        """Get local neighborhood graph around a content item.

        Args:
            content_id: Center node ID
            depth: Number of hops to traverse (1-3)

        Returns:
            Tuple of (nodes, edges) in the neighborhood
        """
        # First check if center node exists
        center_node = await self.get_content(content_id)
        if not center_node:
            return [], []

        # Track visited nodes and edges
        visited_nodes: dict[str, ContentMetadata] = {content_id: center_node}
        all_edges: dict[str, LinkModel] = {}
        current_layer = {content_id}

        # Traverse depth layers
        for _ in range(depth):
            next_layer = set()

            for node_id in current_layer:
                # Get forward links (outgoing)
                outgoing = await self.get_links_by_source(node_id)
                for link in outgoing:
                    all_edges[link.id or ""] = link

                    # Add target node if not visited
                    if link.target and link.target not in visited_nodes:
                        target_node = await self.get_content(link.target)
                        if target_node:
                            visited_nodes[link.target] = target_node
                            next_layer.add(link.target)

                # Get backlinks (incoming)
                incoming = await self.get_links_by_target(node_id)
                for link in incoming:
                    all_edges[link.id or ""] = link

                    # Add source node if not visited
                    if link.source and link.source not in visited_nodes:
                        source_node = await self.get_content(link.source)
                        if source_node:
                            visited_nodes[link.source] = source_node
                            next_layer.add(link.source)

            current_layer = next_layer
            if not current_layer:
                break

        # Convert to lists
        nodes = list(visited_nodes.values())
        edges = list(all_edges.values())

        return nodes, edges

    # ==================== Entity Methods ====================

    def _extract_entity_id(self, record_id) -> str:
        """Extract entity ID string from SurrealDB record ID."""
        if hasattr(record_id, "record_id"):
            return str(record_id.record_id)
        elif hasattr(record_id, "id"):
            return str(record_id.id)
        else:
            return str(record_id).split(":")[-1]

    def _parse_entity(self, item: dict) -> EntityModel:
        """Parse a raw entity record into EntityModel."""
        item_copy = dict(item)
        if "id" in item_copy:
            item_copy["id"] = self._extract_entity_id(item_copy["id"])
        return EntityModel(**item_copy)

    def _parse_content_entity_edge(self, item: dict) -> ContentEntityEdge:
        """Parse a raw content_entity record into ContentEntityEdge."""
        item_copy = dict(item)
        if "id" in item_copy:
            item_copy["id"] = self._extract_entity_id(item_copy["id"])
        if "content_id" in item_copy:
            cid = item_copy["content_id"]
            item_copy["content_id"] = cid.id if hasattr(cid, "id") else str(cid).split(":")[-1]
        if "entity_id" in item_copy:
            eid = item_copy["entity_id"]
            item_copy["entity_id"] = eid.id if hasattr(eid, "id") else str(eid).split(":")[-1]
        return ContentEntityEdge(**item_copy)

    async def create_entity(self, entity: EntityModel) -> EntityModel:
        """Create a new entity.

        Args:
            entity: Entity to create

        Returns:
            Created entity with ID
        """
        now = datetime.now(UTC)
        entity.created_at = now
        entity.updated_at = now

        # Ensure normalized_name is set
        if not entity.normalized_name:
            entity.normalized_name = normalize_name(entity.name)

        result = self.db.create("entity", entity.model_dump(exclude_none=True, mode="json"))
        if result:
            record = result[0] if isinstance(result, list) else result
            entity.id = self._extract_entity_id(record["id"])
        return entity

    async def get_entity(self, entity_id: str) -> EntityModel | None:
        """Get entity by ID.

        Args:
            entity_id: Entity ID

        Returns:
            Entity or None if not found
        """
        result = self.db.select(f"entity:{entity_id}")
        if result:
            return self._parse_entity(result[0] if isinstance(result, list) else result)
        return None

    async def find_entity_by_normalized_name(
        self,
        normalized_name: str,
        entity_type: EntityType | None = None,
    ) -> EntityModel | None:
        """Find entity by normalized name.

        Args:
            normalized_name: Normalized entity name
            entity_type: Optional filter by entity type

        Returns:
            Entity or None if not found
        """
        params: dict = {"normalized_name": normalized_name}
        query = "SELECT * FROM entity WHERE normalized_name = $normalized_name"

        if entity_type:
            query += " AND entity_type = $entity_type"
            params["entity_type"] = entity_type.value

        query += " LIMIT 1"
        result = self.db.query(query, params)
        raw_items = self._parse_query_result(result)

        if raw_items:
            return self._parse_entity(raw_items[0])
        return None

    async def find_entity_by_alias(self, alias: str) -> EntityModel | None:
        """Find entity that has this alias in metadata.aliases.

        Args:
            alias: Alias to search for

        Returns:
            Entity or None if not found
        """
        normalized_alias = normalize_name(alias)
        result = self.db.query(
            "SELECT * FROM entity WHERE metadata.aliases CONTAINS $alias LIMIT 1",
            {"alias": normalized_alias},
        )
        raw_items = self._parse_query_result(result)

        if raw_items:
            return self._parse_entity(raw_items[0])
        return None

    async def update_entity(self, entity_id: str, updates: dict) -> EntityModel | None:
        """Update entity fields.

        Args:
            entity_id: Entity ID
            updates: Dictionary of fields to update

        Returns:
            Updated entity or None if not found
        """
        updates["updated_at"] = datetime.now(UTC)
        result = self.db.update(f"entity:{entity_id}", updates)
        if result:
            record = result[0] if isinstance(result, list) else result
            return self._parse_entity(record)
        return None

    async def delete_entity(self, entity_id: str) -> None:
        """Delete entity and all its edges.

        Args:
            entity_id: Entity ID
        """
        # Delete all edges to this entity
        self.db.query(
            "DELETE (SELECT id FROM content_entity WHERE entity_id = $entity_id)",
            {"entity_id": f"entity:{entity_id}"},
        )
        # Delete the entity
        self.db.delete(f"entity:{entity_id}")

    async def list_entities(
        self,
        entity_type: EntityType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[EntityModel], int]:
        """List entities with optional filtering.

        Args:
            entity_type: Optional filter by entity type
            limit: Maximum number to return
            offset: Number to skip

        Returns:
            Tuple of (entities, count)
        """
        params: dict = {"limit": limit, "offset": offset}
        where_clause = ""

        if entity_type:
            where_clause = " WHERE entity_type = $entity_type"
            params["entity_type"] = entity_type.value

        result = self.db.query(
            f"SELECT * FROM entity{where_clause} ORDER BY name LIMIT $limit START $offset",
            params,
        )
        raw_items = self._parse_query_result(result)
        entities = [self._parse_entity(item) for item in raw_items]
        return entities, len(entities)

    async def list_all_entities(self) -> list[EntityModel]:
        """List all entities (for caching in keyword matcher).

        Returns:
            List of all entities
        """
        result = self.db.query("SELECT * FROM entity")
        raw_items = self._parse_query_result(result)
        return [self._parse_entity(item) for item in raw_items]

    async def create_content_entity_edge(self, edge: ContentEntityEdge) -> ContentEntityEdge:
        """Create a content-entity edge.

        Args:
            edge: Edge to create

        Returns:
            Created edge with ID
        """
        edge.created_at = datetime.now(UTC)
        edge_data = edge.model_dump(exclude_none=True, mode="json")

        # Convert IDs to record references
        edge_data["content_id"] = f"content:{edge_data['content_id']}"
        edge_data["entity_id"] = f"entity:{edge_data['entity_id']}"

        result = self.db.create("content_entity", edge_data)
        if result:
            record = result[0] if isinstance(result, list) else result
            edge.id = self._extract_entity_id(record["id"])
        return edge

    async def get_entities_for_content(
        self, content_id: str
    ) -> list[tuple[EntityModel, ContentEntityEdge]]:
        """Get all entities linked to a content item.

        Args:
            content_id: Content ID

        Returns:
            List of (entity, edge) tuples
        """
        result = self.db.query(
            """
            SELECT *, entity_id.* AS entity FROM content_entity
            WHERE content_id = $content_id
            """,
            {"content_id": f"content:{content_id}"},
        )
        raw_items = self._parse_query_result(result)

        entities_with_edges = []
        for item in raw_items:
            # Extract the nested entity data
            entity_data = item.pop("entity", None)
            if entity_data:
                entity = self._parse_entity(entity_data)
                edge = self._parse_content_entity_edge(item)
                entities_with_edges.append((entity, edge))
        return entities_with_edges

    async def get_content_for_entity(
        self,
        entity_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[tuple[ContentMetadata, ContentEntityEdge]]:
        """Get all content linked to an entity.

        Args:
            entity_id: Entity ID
            limit: Maximum number to return
            offset: Number to skip

        Returns:
            List of (content, edge) tuples
        """
        result = self.db.query(
            """
            SELECT *, content_id.* AS content FROM content_entity
            WHERE entity_id = $entity_id
            LIMIT $limit START $offset
            """,
            {"entity_id": f"entity:{entity_id}", "limit": limit, "offset": offset},
        )
        raw_items = self._parse_query_result(result)

        content_with_edges = []
        for item in raw_items:
            content_data = item.pop("content", None)
            if content_data:
                # Parse content
                if "id" in content_data and hasattr(content_data["id"], "id"):
                    content_data["id"] = content_data["id"].id
                content = ContentMetadata(**content_data)
                edge = self._parse_content_entity_edge(item)
                content_with_edges.append((content, edge))
        return content_with_edges

    async def delete_content_entity_edges(self, content_id: str) -> None:
        """Delete all entity edges for a content item.

        Args:
            content_id: Content ID
        """
        self.db.query(
            "DELETE (SELECT id FROM content_entity WHERE content_id = $content_id)",
            {"content_id": f"content:{content_id}"},
        )

    async def find_or_create_entity(
        self,
        name: str,
        entity_type: EntityType,
        **kwargs,
    ) -> tuple[EntityModel, bool]:
        """Find existing entity or create new one.

        Args:
            name: Entity name
            entity_type: Entity type
            **kwargs: Additional fields for entity creation

        Returns:
            Tuple of (entity, was_created)
        """
        normalized = normalize_name(name)

        # Try to find by normalized name
        existing = await self.find_entity_by_normalized_name(normalized, entity_type)
        if existing:
            return existing, False

        # Try to find by alias
        existing = await self.find_entity_by_alias(name)
        if existing and existing.entity_type == entity_type:
            return existing, False

        # Create new entity
        entity = EntityModel(
            entity_type=entity_type,
            name=name,
            normalized_name=normalized,
            **kwargs,
        )
        created = await self.create_entity(entity)
        return created, True

    async def update_content_extraction_status(
        self,
        content_id: str,
        status: str,
    ) -> None:
        """Update entity extraction status on content.

        Args:
            content_id: Content ID
            status: Status string (pending, processing, completed, failed)
        """
        self.db.query(
            """
            UPDATE content SET
                entity_extraction_status = $status,
                entity_extraction_at = time::now(),
                updated_at = time::now()
            WHERE id = $content_id
            """,
            {"content_id": f"content:{content_id}", "status": status},
        )

    async def get_topic_hierarchy(self) -> list[EntityModel]:
        """Get all topic entities for building hierarchy view.

        Returns:
            List of topic entities
        """
        result = self.db.query(
            "SELECT * FROM entity WHERE entity_type = 'topic' ORDER BY hierarchy, name"
        )
        raw_items = self._parse_query_result(result)
        return [self._parse_entity(item) for item in raw_items]

    # ==================== Classification Methods ====================

    async def update_content_classification_status(
        self,
        content_id: str,
        status: str,
    ) -> None:
        """Update classification status on content.

        Args:
            content_id: Content ID
            status: Status string (pending, processing, completed, failed)
        """
        self.db.query(
            """
            UPDATE content SET
                classification_status = $status,
                updated_at = time::now()
            WHERE id = $content_id
            """,
            {"content_id": f"content:{content_id}", "status": status},
        )

    async def update_content_classification(
        self,
        content_id: str,
        classification_dict: dict,
    ) -> None:
        """Store classification result on content using targeted UPDATE.

        Merges classification into metadata without clobbering other keys.
        Sets top-level indexed fields for queryability.

        Args:
            content_id: Content ID
            classification_dict: Classification result as dict
        """
        self.db.query(
            """
            UPDATE content SET
                metadata.classification = $data,
                classification_status = 'completed',
                classification_tier = $tier,
                classification_score = $score,
                classification_at = time::now(),
                updated_at = time::now()
            WHERE id = $content_id
            """,
            {
                "content_id": f"content:{content_id}",
                "data": classification_dict,
                "tier": classification_dict.get("tier", ""),
                "score": classification_dict.get("quality_score", 0),
            },
        )

    async def get_interest_profile(
        self,
        top_n: int = 15,
        recent_days: int = 90,
    ) -> dict[str, list[str]]:
        """Get multi-signal interest profile for classification bias.

        Derives interests from:
        1. Entity topic discusses edges (highest weight)
        2. Tag frequency with recency weighting
        3. Channel affinity for YouTube (repeat ingestion = strong signal)

        Args:
            top_n: Number of top items per signal
            recent_days: Time window in days for recency weighting

        Returns:
            Dict with topics, tags, channels lists
        """
        # Top topics by discusses edge count
        topic_result = self.db.query(
            """
            SELECT entity_id.name AS name, count() AS cnt
            FROM content_entity
            WHERE edge_type = 'discusses'
                AND entity_id.entity_type = 'topic'
            GROUP BY name
            ORDER BY cnt DESC
            LIMIT $limit
            """,
            {"limit": top_n},
        )
        topic_items = self._parse_query_result(topic_result)
        topics = [item["name"] for item in topic_items if item.get("name")]

        # Top tags with recency weighting
        tag_result = self.db.query(
            """
            SELECT tag, count() AS cnt
            FROM (SELECT array::flatten(tags) AS tag FROM content
                  WHERE tags != NONE AND created_at > time::now() - $window
                  UNGROUP)
            GROUP BY tag
            ORDER BY cnt DESC
            LIMIT $limit
            """,
            {"limit": top_n, "window": f"{recent_days}d"},
        )
        tag_items = self._parse_query_result(tag_result)
        tags = [item["tag"] for item in tag_items if item.get("tag")]

        # Top YouTube channels by video count
        channel_result = self.db.query(
            """
            SELECT metadata.channel_title AS channel, count() AS cnt
            FROM content
            WHERE content_type = 'youtube'
                AND metadata.channel_title != NONE
            GROUP BY channel
            ORDER BY cnt DESC
            LIMIT $limit
            """,
            {"limit": top_n},
        )
        channel_items = self._parse_query_result(channel_result)
        channels = [item["channel"] for item in channel_items if item.get("channel")]

        return {"topics": topics, "tags": tags, "channels": channels}

    async def find_potential_duplicates(self, max_distance: int = 1) -> list[list[EntityModel]]:
        """Find potential duplicate entities based on normalized names.

        This loads all entities and uses Levenshtein distance for comparison.

        Args:
            max_distance: Maximum edit distance to consider as duplicate

        Returns:
            List of groups of potential duplicates
        """
        from menos.services.normalization import find_near_duplicates

        all_entities = await self.list_all_entities()
        return find_near_duplicates(
            all_entities,
            lambda e: e.normalized_name,
            max_distance,
        )
