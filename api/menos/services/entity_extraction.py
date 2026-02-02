"""LLM-based entity extraction service for extracting topics and entities from content."""

import json
import logging
import re
import time
from typing import Any

from menos.config import Settings
from menos.models import (
    EdgeType,
    EntityModel,
    EntityType,
    ExtractedEntity,
    ExtractionMetrics,
    ExtractionResult,
    PreDetectedValidation,
)
from menos.services.llm import LLMProvider

logger = logging.getLogger(__name__)

# Prompt template for entity extraction
EXTRACTION_PROMPT_TEMPLATE = """You are an expert content analyst. Your primary job is TOPIC EXTRACTION.

CONTENT TYPE: {content_type}
CONTENT TITLE: {title}

## PRE-DETECTED ENTITIES (already found via URL/keyword matching)
The following entities were detected with high confidence - DO NOT re-extract these:
{pre_detected_entities_json}

## YOUR TASKS

1. TOPICS: Extract 3-7 hierarchical topics (this is your PRIMARY task)
   - Format: "Parent > Child > Grandchild" (e.g., "AI > LLMs > RAG")
   - Include both broad categories and specific concepts
   - PREFER existing topics over creating new ones

2. VALIDATE: For each pre-detected entity, confirm edge_type:
   - discusses: Primary subject of content
   - mentions: Referenced but not focus
   - uses: Demonstrated or used
   - cites: Academic citation

3. ADDITIONAL ENTITIES (only if missed by pre-detection):
   - Only extract repos/tools/papers NOT in pre-detected list
   - Must be substantively discussed, not just name-dropped

<CONTENT>
{content_text}
</CONTENT>

EXISTING TOPICS (strongly prefer these):
{existing_topics}

Respond ONLY with valid JSON (no markdown, no code blocks):
{{
  "topics": [
    {{"name": "AI > LLMs > RAG", "confidence": "high", "edge_type": "discusses"}}
  ],
  "pre_detected_validations": [
    {{"entity_id": "entity:langchain", "edge_type": "uses", "confirmed": true}}
  ],
  "additional_entities": [
    {{"type": "repo", "name": "FAISS", "confidence": "medium", "edge_type": "mentions"}}
  ]
}}"""


def _parse_topic_hierarchy(topic_str: str) -> list[str]:
    """Parse a topic hierarchy string into a list of components.

    Args:
        topic_str: Topic string like "AI > LLMs > RAG"

    Returns:
        List of hierarchy components: ["AI", "LLMs", "RAG"]
    """
    parts = [p.strip() for p in topic_str.split(">")]
    return [p for p in parts if p]  # Filter empty strings


def _confidence_to_float(confidence: str) -> float:
    """Convert confidence string to float value.

    Args:
        confidence: "high", "medium", or "low"

    Returns:
        Float confidence value
    """
    mapping = {"high": 0.9, "medium": 0.7, "low": 0.5}
    return mapping.get(confidence.lower(), 0.6)


def _edge_type_from_string(edge_str: str) -> EdgeType:
    """Convert edge type string to EdgeType enum.

    Args:
        edge_str: Edge type string

    Returns:
        EdgeType enum value
    """
    mapping = {
        "discusses": EdgeType.DISCUSSES,
        "mentions": EdgeType.MENTIONS,
        "cites": EdgeType.CITES,
        "uses": EdgeType.USES,
        "demonstrates": EdgeType.DEMONSTRATES,
    }
    return mapping.get(edge_str.lower(), EdgeType.MENTIONS)


def _entity_type_from_string(type_str: str) -> EntityType:
    """Convert entity type string to EntityType enum.

    Args:
        type_str: Entity type string

    Returns:
        EntityType enum value
    """
    mapping = {
        "topic": EntityType.TOPIC,
        "repo": EntityType.REPO,
        "paper": EntityType.PAPER,
        "tool": EntityType.TOOL,
        "person": EntityType.PERSON,
    }
    return mapping.get(type_str.lower(), EntityType.TOPIC)


def _extract_json_from_response(response: str) -> dict[str, Any]:
    """Extract JSON from LLM response, handling markdown code blocks.

    Args:
        response: Raw LLM response

    Returns:
        Parsed JSON dictionary
    """
    # Try direct parse first
    response = response.strip()
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass

    # Try to extract from markdown code blocks
    patterns = [
        r"```json\s*\n?(.*?)\n?```",
        r"```\s*\n?(.*?)\n?```",
        r"\{[\s\S]*\}",
    ]

    for pattern in patterns:
        match = re.search(pattern, response, re.DOTALL)
        if match:
            try:
                json_str = match.group(1) if "```" in pattern else match.group(0)
                return json.loads(json_str)
            except (json.JSONDecodeError, IndexError):
                continue

    # Return empty result if parsing fails
    logger.warning("Failed to parse LLM response as JSON: %s", response[:200])
    return {"topics": [], "pre_detected_validations": [], "additional_entities": []}


class EntityExtractionService:
    """Service for extracting entities from content using LLM.

    This service is called AFTER code-based extraction (URL detection, keyword matching)
    has identified high-confidence entities. The LLM's primary job is:
    1. Extract topics/subjects from the content
    2. Validate edge types for pre-detected entities
    3. Find any entities missed by code-based detection
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        settings: Settings,
    ):
        """Initialize extraction service.

        Args:
            llm_provider: LLM provider for text generation
            settings: Application settings
        """
        self.llm = llm_provider
        self.settings = settings

    def should_skip_llm(
        self,
        content_text: str,
        content_type: str,
        pre_detected: list[EntityModel],
    ) -> bool:
        """Determine if LLM call can be skipped.

        Args:
            content_text: Content text
            content_type: Type of content
            pre_detected: Already detected entities

        Returns:
            True if LLM should be skipped
        """
        # Skip if extraction is disabled
        if not self.settings.entity_extraction_enabled:
            return True

        # Skip if content is too short (not enough for topics)
        if len(content_text) < 500:
            logger.debug("Skipping LLM: content too short (%d chars)", len(content_text))
            return True

        # Skip if we already have sufficient entities AND content type doesn't benefit
        # from topic extraction
        if len(pre_detected) >= 5 and content_type in ["changelog", "release_notes"]:
            logger.debug(
                "Skipping LLM: sufficient entities (%d) for %s",
                len(pre_detected),
                content_type,
            )
            return True

        return False

    async def extract_entities(
        self,
        content_text: str,
        content_type: str,
        title: str,
        pre_detected: list[EntityModel] | None = None,
        existing_topics: list[str] | None = None,
    ) -> tuple[ExtractionResult, ExtractionMetrics]:
        """Extract entities from content using LLM.

        Args:
            content_text: The content to analyze
            content_type: Type of content (youtube, markdown, etc.)
            title: Content title
            pre_detected: Entities already detected by code-based methods
            existing_topics: Known topics to prefer

        Returns:
            Tuple of (ExtractionResult, ExtractionMetrics)
        """
        content_id = title  # For metrics
        pre_detected = pre_detected or []
        existing_topics = existing_topics or []

        start_time = time.time()

        # Check if we should skip LLM
        if self.should_skip_llm(content_text, content_type, pre_detected):
            metrics = ExtractionMetrics(
                content_id=content_id,
                pre_detected_count=len(pre_detected),
                llm_extracted_count=0,
                llm_skipped=True,
                llm_tokens_used=0,
                total_latency_ms=int((time.time() - start_time) * 1000),
            )
            return ExtractionResult(), metrics

        # Truncate content if too long (keep first 10k chars for LLM)
        truncated_content = content_text[:10000]
        if len(content_text) > 10000:
            truncated_content += "\n\n[Content truncated...]"

        # Format pre-detected entities for prompt
        pre_detected_json = json.dumps(
            [
                {
                    "entity_id": f"entity:{e.id}" if e.id else f"entity:{e.normalized_name}",
                    "type": e.entity_type.value,
                    "name": e.name,
                }
                for e in pre_detected
            ],
            indent=2,
        )

        # Format existing topics
        topics_str = ", ".join(existing_topics[:20]) if existing_topics else "None yet"

        # Build prompt
        prompt = EXTRACTION_PROMPT_TEMPLATE.format(
            content_type=content_type,
            title=title,
            pre_detected_entities_json=pre_detected_json,
            content_text=truncated_content,
            existing_topics=topics_str,
        )

        # Call LLM
        try:
            response = await self.llm.generate(
                prompt,
                temperature=0.3,  # Lower temperature for more consistent JSON
                max_tokens=2000,
                timeout=120.0,
            )
        except Exception as e:
            logger.error("LLM extraction failed: %s", e)
            metrics = ExtractionMetrics(
                content_id=content_id,
                pre_detected_count=len(pre_detected),
                llm_extracted_count=0,
                llm_skipped=False,
                llm_tokens_used=0,
                total_latency_ms=int((time.time() - start_time) * 1000),
            )
            return ExtractionResult(), metrics

        # Parse response
        data = _extract_json_from_response(response)

        # Convert to ExtractionResult
        result = self._parse_extraction_response(data)

        # Calculate metrics
        llm_count = len(result.topics) + len(result.additional_entities)
        metrics = ExtractionMetrics(
            content_id=content_id,
            pre_detected_count=len(pre_detected),
            llm_extracted_count=llm_count,
            llm_skipped=False,
            llm_tokens_used=len(prompt.split()) + len(response.split()),  # Rough estimate
            total_latency_ms=int((time.time() - start_time) * 1000),
        )

        logger.info(
            "Entity extraction complete: %d topics, %d additional entities, %dms",
            len(result.topics),
            len(result.additional_entities),
            metrics.total_latency_ms,
        )

        return result, metrics

    def _parse_extraction_response(self, data: dict[str, Any]) -> ExtractionResult:
        """Parse LLM JSON response into ExtractionResult.

        Args:
            data: Parsed JSON data

        Returns:
            ExtractionResult with parsed entities
        """
        topics: list[ExtractedEntity] = []
        validations: list[PreDetectedValidation] = []
        additional: list[ExtractedEntity] = []

        # Parse topics
        for topic_data in data.get("topics", []):
            if not isinstance(topic_data, dict):
                continue

            name = topic_data.get("name", "")
            if not name:
                continue

            hierarchy = _parse_topic_hierarchy(name)
            confidence = topic_data.get("confidence", "medium")
            edge_type = topic_data.get("edge_type", "discusses")

            # Apply max topics limit
            if len(topics) >= self.settings.entity_max_topics_per_content:
                break

            # Apply min confidence filter
            conf_value = _confidence_to_float(confidence)
            if conf_value < self.settings.entity_min_confidence:
                continue

            topics.append(
                ExtractedEntity(
                    entity_type=EntityType.TOPIC,
                    name=hierarchy[-1] if hierarchy else name,  # Leaf topic name
                    confidence=confidence,
                    edge_type=_edge_type_from_string(edge_type),
                    hierarchy=hierarchy,
                )
            )

        # Parse pre-detected validations
        for val_data in data.get("pre_detected_validations", []):
            if not isinstance(val_data, dict):
                continue

            entity_id = val_data.get("entity_id", "")
            if not entity_id:
                continue

            validations.append(
                PreDetectedValidation(
                    entity_id=entity_id,
                    edge_type=_edge_type_from_string(val_data.get("edge_type", "mentions")),
                    confirmed=val_data.get("confirmed", True),
                )
            )

        # Parse additional entities
        for ent_data in data.get("additional_entities", []):
            if not isinstance(ent_data, dict):
                continue

            name = ent_data.get("name", "")
            ent_type = ent_data.get("type", "tool")
            if not name:
                continue

            confidence = ent_data.get("confidence", "medium")
            conf_value = _confidence_to_float(confidence)
            if conf_value < self.settings.entity_min_confidence:
                continue

            additional.append(
                ExtractedEntity(
                    entity_type=_entity_type_from_string(ent_type),
                    name=name,
                    confidence=confidence,
                    edge_type=_edge_type_from_string(ent_data.get("edge_type", "mentions")),
                    hierarchy=None,
                )
            )

        return ExtractionResult(
            topics=topics,
            pre_detected_validations=validations,
            additional_entities=additional,
        )
