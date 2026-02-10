"""Database models for SurrealDB."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    """Types of entities that can be extracted from content."""

    TOPIC = "topic"
    REPO = "repo"
    PAPER = "paper"
    TOOL = "tool"
    PERSON = "person"


class EdgeType(str, Enum):
    """Types of edges between content and entities."""

    DISCUSSES = "discusses"  # Primary subject matter of the content
    MENTIONS = "mentions"  # Referenced but not the main focus
    CITES = "cites"  # Academic citation or detailed discussion
    USES = "uses"  # Demonstrates, recommends, or uses the tool
    DEMONSTRATES = "demonstrates"  # Tutorial or walkthrough of the tool


class EntitySource(str, Enum):
    """Source of entity creation."""

    AI_EXTRACTED = "ai_extracted"
    URL_DETECTED = "url_detected"
    USER_CREATED = "user_created"
    API_FETCHED = "api_fetched"


class ChunkModel(BaseModel):
    """A chunk of content with embedding."""

    id: str | None = None
    content_id: str
    text: str
    chunk_index: int
    embedding: list[float] | None = None
    created_at: datetime | None = None


class ContentMetadata(BaseModel):
    """Metadata for stored content."""

    id: str | None = None
    content_type: str
    title: str | None = None
    description: str | None = None
    mime_type: str
    file_size: int
    file_path: str
    author: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LinkModel(BaseModel):
    """Link between content items."""

    id: str | None = None
    source: str  # Content ID
    target: str | None = None  # Content ID, nullable for unresolved links
    link_text: str
    link_type: str  # "wiki" or "markdown"
    created_at: datetime | None = None


class EntityModel(BaseModel):
    """An extracted entity (topic, repo, paper, tool, person)."""

    id: str | None = None
    entity_type: EntityType
    name: str  # Display name
    normalized_name: str  # For matching (lowercase, no separators)
    description: str | None = None
    hierarchy: list[str] | None = None  # ["AI", "LLMs", "RAG"] breadcrumb for topics
    metadata: dict[str, Any] = Field(default_factory=dict)
    # For repos: { url, owner, stars, language, topics, fetched_at }
    # For papers: { url, arxiv_id, doi, authors, abstract, published_at, fetched_at }
    # For topics: { aliases, parent_topic }
    # For tools: { url, category }
    created_at: datetime | None = None
    updated_at: datetime | None = None
    source: EntitySource = EntitySource.AI_EXTRACTED


class ContentEntityEdge(BaseModel):
    """Edge between content and an entity."""

    id: str | None = None
    content_id: str  # Content ID (without prefix)
    entity_id: str  # Entity ID (without prefix)
    edge_type: EdgeType
    confidence: float | None = None  # 0.0-1.0 extraction confidence
    mention_count: int | None = None  # How many times mentioned
    source: EntitySource = EntitySource.AI_EXTRACTED
    created_at: datetime | None = None


class ExtractedEntity(BaseModel):
    """An entity extracted by the LLM (before resolution)."""

    entity_type: EntityType
    name: str
    confidence: str  # "high", "medium", "low"
    edge_type: EdgeType
    hierarchy: list[str] | None = None  # For topics: parsed from "AI > LLMs > RAG"


class PreDetectedValidation(BaseModel):
    """Validation of a pre-detected entity by the LLM."""

    entity_id: str
    edge_type: EdgeType
    confirmed: bool


class ExtractionResult(BaseModel):
    """Result of LLM entity extraction."""

    topics: list[ExtractedEntity] = Field(default_factory=list)
    pre_detected_validations: list[PreDetectedValidation] = Field(default_factory=list)
    additional_entities: list[ExtractedEntity] = Field(default_factory=list)


class ExtractionMetrics(BaseModel):
    """Metrics for entity extraction pipeline."""

    content_id: str
    pre_detected_count: int = 0  # Entities found via code
    llm_extracted_count: int = 0  # Entities found via LLM
    llm_skipped: bool = False  # Did we skip LLM?
    llm_tokens_used: int = 0  # Token count if LLM called
    total_latency_ms: int = 0


class ClassificationResult(BaseModel):
    """Result of content classification (quality tier + labels)."""

    labels: list[str] = Field(default_factory=list)
    tier: str = ""  # S, A, B, C, D
    tier_explanation: list[str] = Field(default_factory=list)
    quality_score: int = 0  # 1-100
    score_explanation: list[str] = Field(default_factory=list)
    model: str = ""
    classified_at: str = ""
