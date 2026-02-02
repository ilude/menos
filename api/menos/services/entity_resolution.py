"""Entity resolution service that orchestrates the full entity extraction pipeline.

This service implements the "Code-First, LLM-Last" principle:
1. URL/Pattern Detection (free, instant)
2. Keyword/Alias Matching (free, fast)
3. External API Fetching (rate-limited but deterministic)
4. LLM Extraction (expensive, only for topics and missed entities)
"""

import logging
from dataclasses import dataclass

from menos.config import Settings
from menos.models import (
    ContentEntityEdge,
    EdgeType,
    EntityModel,
    EntitySource,
    EntityType,
    ExtractionMetrics,
)
from menos.services.entity_extraction import EntityExtractionService
from menos.services.keyword_matcher import EntityKeywordMatcher
from menos.services.normalization import normalize_name
from menos.services.storage import SurrealDBRepository

logger = logging.getLogger(__name__)


@dataclass
class ResolutionResult:
    """Result of entity resolution pipeline."""

    edges: list[ContentEntityEdge]
    entities_created: int
    entities_reused: int
    metrics: ExtractionMetrics | None


class EntityResolutionService:
    """Orchestrates the full entity extraction and resolution pipeline."""

    def __init__(
        self,
        repository: SurrealDBRepository,
        extraction_service: EntityExtractionService,
        keyword_matcher: EntityKeywordMatcher,
        settings: Settings,
        url_detector=None,
        sponsored_filter=None,
        github_fetcher=None,
        arxiv_fetcher=None,
    ):
        self.repo = repository
        self.extraction = extraction_service
        self.matcher = keyword_matcher
        self.settings = settings
        self.url_detector = url_detector
        self.sponsored_filter = sponsored_filter
        self.github_fetcher = github_fetcher
        self.arxiv_fetcher = arxiv_fetcher

    async def refresh_matcher_cache(self) -> None:
        """Refresh the keyword matcher cache from database."""
        entities = await self.repo.list_all_entities()
        self.matcher.load_entities(entities)
        logger.info("Loaded %d entities into keyword matcher cache", len(entities))

    async def process_content(
        self,
        content_id: str,
        content_text: str,
        content_type: str,
        title: str,
        description_urls: list[str] | None = None,
    ) -> ResolutionResult:
        """Process content through the full entity extraction pipeline."""
        edges: list[ContentEntityEdge] = []
        entities_created = 0
        entities_reused = 0
        pre_detected: list[EntityModel] = []

        # Stage 1: URL Detection
        detected_entities = await self._detect_urls(
            content_text,
            description_urls or [],
        )
        pre_detected.extend(detected_entities)

        # Stage 2: Keyword Matching
        matched = self.matcher.find_in_text(content_text)
        for match in matched:
            if match.entity.id and match.entity.id not in [e.id for e in pre_detected]:
                pre_detected.append(match.entity)

        # Stage 3: LLM Extraction (if needed)
        existing_topics = await self._get_existing_topics()
        extraction_result, metrics = await self.extraction.extract_entities(
            content_text=content_text,
            content_type=content_type,
            title=title,
            pre_detected=pre_detected,
            existing_topics=existing_topics,
        )

        # Stage 4: Resolve and store entities
        validation_map = {
            v.entity_id: v for v in extraction_result.pre_detected_validations
        }

        for entity in pre_detected:
            entity_id = f"entity:{entity.id}" if entity.id else f"entity:{entity.normalized_name}"
            validation = validation_map.get(entity_id)
            if validation and not validation.confirmed:
                continue

            edge_type = validation.edge_type if validation else EdgeType.MENTIONS
            resolved, created = await self.repo.find_or_create_entity(
                name=entity.name,
                entity_type=entity.entity_type,
                description=entity.description,
                metadata=entity.metadata,
                source=entity.source,
            )

            if created:
                entities_created += 1
            else:
                entities_reused += 1

            edge = ContentEntityEdge(
                content_id=content_id,
                entity_id=resolved.id or "",
                edge_type=edge_type,
                confidence=0.9,
                source=EntitySource.URL_DETECTED if entity.source == EntitySource.URL_DETECTED else EntitySource.AI_EXTRACTED,
            )
            try:
                await self.repo.create_content_entity_edge(edge)
                edges.append(edge)
            except Exception as e:
                logger.warning("Failed to create edge for %s: %s", entity.name, e)

        # Process LLM-extracted topics
        for topic in extraction_result.topics:
            resolved, created = await self._resolve_topic(topic.name, topic.hierarchy)
            if created:
                entities_created += 1
            else:
                entities_reused += 1

            edge = ContentEntityEdge(
                content_id=content_id,
                entity_id=resolved.id or "",
                edge_type=topic.edge_type,
                confidence=0.85,
                source=EntitySource.AI_EXTRACTED,
            )
            try:
                await self.repo.create_content_entity_edge(edge)
                edges.append(edge)
            except Exception as e:
                logger.warning("Failed to create edge for topic %s: %s", topic.name, e)

        # Process additional LLM-extracted entities
        for entity in extraction_result.additional_entities:
            resolved, created = await self.repo.find_or_create_entity(
                name=entity.name,
                entity_type=entity.entity_type,
                source=EntitySource.AI_EXTRACTED,
            )
            if created:
                entities_created += 1
            else:
                entities_reused += 1

            edge = ContentEntityEdge(
                content_id=content_id,
                entity_id=resolved.id or "",
                edge_type=entity.edge_type,
                confidence=0.7,
                source=EntitySource.AI_EXTRACTED,
            )
            try:
                await self.repo.create_content_entity_edge(edge)
                edges.append(edge)
            except Exception as e:
                logger.warning("Failed to create edge for %s: %s", entity.name, e)

        await self.repo.update_content_extraction_status(content_id, "completed")

        logger.info(
            "Processed content %s: %d edges, %d created, %d reused",
            content_id,
            len(edges),
            entities_created,
            entities_reused,
        )

        return ResolutionResult(
            edges=edges,
            entities_created=entities_created,
            entities_reused=entities_reused,
            metrics=metrics,
        )

    async def _detect_urls(
        self,
        content_text: str,
        description_urls: list[str],
    ) -> list[EntityModel]:
        """Detect entities from URLs in content and description."""
        entities: list[EntityModel] = []
        if not self.url_detector:
            return entities

        all_text = content_text + "\n" + "\n".join(description_urls)
        detected = self.url_detector.detect_urls(all_text)

        if self.sponsored_filter:
            detected = [
                d for d in detected
                if not self.sponsored_filter.is_sponsored_link(d.url, content_text)
            ]

        for url_info in detected:
            entity = await self._url_to_entity(url_info)
            if entity:
                entities.append(entity)

        return entities

    async def _url_to_entity(self, url_info) -> EntityModel | None:
        """Convert a detected URL to an entity."""
        if url_info.url_type == "github_repo":
            return await self._resolve_github_repo(url_info)
        elif url_info.url_type == "arxiv":
            return await self._resolve_arxiv_paper(url_info)
        elif url_info.url_type == "pypi":
            return self._create_tool_entity(url_info, "pypi")
        elif url_info.url_type == "npm":
            return self._create_tool_entity(url_info, "npm")
        return None

    async def _resolve_github_repo(self, url_info) -> EntityModel | None:
        """Resolve a GitHub repository."""
        owner_repo = url_info.extracted_id
        if not owner_repo or "/" not in owner_repo:
            return None

        owner, repo = owner_repo.split("/", 1)
        name = repo
        metadata = {"url": url_info.url, "owner": owner}

        if self.github_fetcher and self.settings.entity_fetch_external_metadata:
            try:
                repo_meta = await self.github_fetcher.fetch_repo(owner, repo)
                if repo_meta:
                    metadata.update({
                        "stars": repo_meta.stars,
                        "language": repo_meta.language,
                        "topics": repo_meta.topics,
                        "fetched_at": repo_meta.fetched_at.isoformat() if repo_meta.fetched_at else None,
                    })
                    if repo_meta.description:
                        name = repo_meta.name or repo
            except Exception as e:
                logger.warning("Failed to fetch GitHub metadata for %s: %s", owner_repo, e)

        return EntityModel(
            entity_type=EntityType.REPO,
            name=name,
            normalized_name=normalize_name(repo),
            description=metadata.get("description"),
            metadata=metadata,
            source=EntitySource.URL_DETECTED,
        )

    async def _resolve_arxiv_paper(self, url_info) -> EntityModel | None:
        """Resolve an arXiv paper."""
        arxiv_id = url_info.extracted_id
        if not arxiv_id:
            return None

        name = f"arXiv:{arxiv_id}"
        metadata = {"url": url_info.url, "arxiv_id": arxiv_id}

        if self.arxiv_fetcher and self.settings.entity_fetch_external_metadata:
            try:
                paper_meta = await self.arxiv_fetcher.fetch_paper(arxiv_id)
                if paper_meta:
                    name = paper_meta.title or name
                    metadata.update({
                        "authors": paper_meta.authors,
                        "abstract": paper_meta.abstract[:500] if paper_meta.abstract else None,
                        "doi": paper_meta.doi,
                        "published_at": paper_meta.published_at.isoformat() if paper_meta.published_at else None,
                        "fetched_at": paper_meta.fetched_at.isoformat() if paper_meta.fetched_at else None,
                    })
            except Exception as e:
                logger.warning("Failed to fetch arXiv metadata for %s: %s", arxiv_id, e)

        return EntityModel(
            entity_type=EntityType.PAPER,
            name=name,
            normalized_name=normalize_name(name),
            description=metadata.get("abstract"),
            metadata=metadata,
            source=EntitySource.URL_DETECTED,
        )

    def _create_tool_entity(self, url_info, registry: str) -> EntityModel:
        """Create a tool entity from a package registry URL."""
        name = url_info.extracted_id or "unknown"
        return EntityModel(
            entity_type=EntityType.TOOL,
            name=name,
            normalized_name=normalize_name(name),
            metadata={"url": url_info.url, "registry": registry},
            source=EntitySource.URL_DETECTED,
        )

    async def _resolve_topic(
        self,
        name: str,
        hierarchy: list[str] | None,
    ) -> tuple[EntityModel, bool]:
        """Resolve a topic, creating parent topics if needed."""
        hierarchy = hierarchy or [name]
        parent_id = None

        for i, level in enumerate(hierarchy[:-1]):
            parent_hierarchy = hierarchy[: i + 1]
            parent, _ = await self.repo.find_or_create_entity(
                name=level,
                entity_type=EntityType.TOPIC,
                hierarchy=parent_hierarchy,
                source=EntitySource.AI_EXTRACTED,
            )
            parent_id = parent.id

        topic, created = await self.repo.find_or_create_entity(
            name=hierarchy[-1],
            entity_type=EntityType.TOPIC,
            hierarchy=hierarchy,
            metadata={"parent_topic": f"entity:{parent_id}"} if parent_id else {},
            source=EntitySource.AI_EXTRACTED,
        )
        return topic, created

    async def _get_existing_topics(self) -> list[str]:
        """Get list of existing topic names for LLM prompt."""
        topics = await self.repo.get_topic_hierarchy()
        return [t.name for t in topics[:50]]
