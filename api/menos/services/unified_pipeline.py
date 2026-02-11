"""Unified pipeline service combining classification and entity extraction in one LLM call."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from menos.config import Settings
from menos.models import (
    EntityType,
    ExtractedEntity,
    PreDetectedValidation,
    UnifiedResult,
)
from menos.services.classification import LABEL_PATTERN, VALID_TIERS, _dedup_label
from menos.services.entity_extraction import (
    _confidence_to_float,
    _edge_type_from_string,
    _entity_type_from_string,
    _parse_topic_hierarchy,
)
from menos.services.llm import LLMProvider
from menos.services.llm_json import extract_json
from menos.services.storage import SurrealDBRepository

logger = logging.getLogger(__name__)

UNIFIED_PROMPT_TEMPLATE = """You are a content analyst. Evaluate the content and provide \
classification ratings, tags, and entity extraction in a single response.

CONTENT TYPE: {content_type}
CONTENT TITLE: {title}

## EXISTING TAGS (prefer these over creating new ones)
{existing_tags}

## PRE-DETECTED ENTITIES (already found via URL/keyword matching)
{pre_detected_entities_json}

## EXISTING TOPICS (strongly prefer these)
{existing_topics}

## RULES

### Tags
- Assign up to 10 tags from existing tags above
- You may create up to {max_new_tags} NEW tags if needed (lowercase, hyphenated)
- Tags must be single lowercase words or hyphenated (e.g. "kubernetes", "home-lab")

### Quality Rating
- Assign a quality tier: S (exceptional), A (great), B (good), C (mediocre), D (poor)
- Assign a quality score from 1-100 where 50 = average, 80+ = exceptional, <30 = low value
- Provide brief explanations (2-3 bullet points each)

### Summary
- Generate a summary: a 2-3 sentence overview followed by 3-5 bullet points of main topics

### Topics
- Extract 3-7 hierarchical topics
- Format: "Parent > Child > Grandchild" (e.g., "AI > LLMs > RAG")
- PREFER existing topics over creating new ones

### Pre-detected Validations
- For each pre-detected entity, confirm edge_type:
  discusses, mentions, uses, cites, demonstrates

### Additional Entities
- Only extract repos/tools/papers NOT in the pre-detected list
- Must be substantively discussed, not just name-dropped

<CONTENT>
{content_text}
</CONTENT>

Respond ONLY with valid JSON (no markdown, no code blocks):
{{
  "tags": ["existing-tag-1", "existing-tag-2"],
  "new_tags": ["genuinely-new-tag"],
  "tier": "B",
  "tier_explanation": ["Reason 1", "Reason 2"],
  "quality_score": 55,
  "score_explanation": ["Reason 1", "Reason 2"],
  "summary": "2-3 sentence overview.\\n\\n- Bullet 1\\n- Bullet 2",
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


def parse_unified_response(
    data: dict[str, Any],
    existing_tags: list[str],
    settings: Settings,
) -> UnifiedResult | None:
    """Parse and validate a unified LLM response.

    Args:
        data: Parsed JSON from LLM
        existing_tags: Known tags for dedup
        settings: Application settings

    Returns:
        UnifiedResult or None if payload is malformed
    """
    if not data:
        return None

    # Require at least one recognizable field to consider it valid
    recognized = {
        "tags",
        "new_tags",
        "tier",
        "quality_score",
        "topics",
        "pre_detected_validations",
        "additional_entities",
        "summary",
    }
    if not any(k in data for k in recognized):
        return None

    # --- Classification fields ---

    # Validate tier
    tier = str(data.get("tier", "C")).upper()
    if tier not in VALID_TIERS:
        tier = "C"

    # Validate and clamp score
    raw_score = data.get("quality_score", 50)
    try:
        score = int(raw_score)
    except (ValueError, TypeError):
        score = 50
    score = max(1, min(100, score))

    # Validate tags
    raw_tags = data.get("tags", [])
    if not isinstance(raw_tags, list):
        raw_tags = []
    tags = [t for t in raw_tags if isinstance(t, str) and LABEL_PATTERN.match(t)]

    # Process new tags with deterministic dedup
    raw_new_tags = data.get("new_tags", [])
    if not isinstance(raw_new_tags, list):
        raw_new_tags = []

    new_tags: list[str] = []
    max_new = settings.classification_max_new_labels
    new_count = 0
    for new_tag in raw_new_tags:
        if new_count >= max_new:
            break
        if not isinstance(new_tag, str) or not LABEL_PATTERN.match(new_tag):
            continue

        existing_match = _dedup_label(new_tag, existing_tags + tags)
        if existing_match:
            if existing_match not in tags:
                tags.append(existing_match)
        else:
            if new_tag not in tags:
                tags.append(new_tag)
                new_tags.append(new_tag)
                new_count += 1

    # Validate explanations
    tier_explanation = data.get("tier_explanation", [])
    if not isinstance(tier_explanation, list):
        tier_explanation = []
    tier_explanation = [str(e) for e in tier_explanation if e]

    score_explanation = data.get("score_explanation", [])
    if not isinstance(score_explanation, list):
        score_explanation = []
    score_explanation = [str(e) for e in score_explanation if e]

    # Extract summary
    summary = data.get("summary", "")
    if not isinstance(summary, str):
        summary = ""

    # --- Entity extraction fields ---

    # Parse topics
    topics: list[ExtractedEntity] = []
    raw_topics = data.get("topics", [])
    if not isinstance(raw_topics, list):
        raw_topics = []

    for topic_data in raw_topics:
        if not isinstance(topic_data, dict):
            continue

        name = topic_data.get("name", "")
        if not name:
            continue

        if len(topics) >= settings.entity_max_topics_per_content:
            break

        confidence = topic_data.get("confidence", "medium")
        conf_value = _confidence_to_float(confidence)
        if conf_value < settings.entity_min_confidence:
            continue

        hierarchy = _parse_topic_hierarchy(name)
        edge_type = topic_data.get("edge_type", "discusses")

        topics.append(
            ExtractedEntity(
                entity_type=EntityType.TOPIC,
                name=hierarchy[-1] if hierarchy else name,
                confidence=confidence,
                edge_type=_edge_type_from_string(edge_type),
                hierarchy=hierarchy,
            )
        )

    # Parse pre-detected validations
    validations: list[PreDetectedValidation] = []
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
    additional: list[ExtractedEntity] = []
    for ent_data in data.get("additional_entities", []):
        if not isinstance(ent_data, dict):
            continue

        name = ent_data.get("name", "")
        ent_type = ent_data.get("type", "tool")
        if not name:
            continue

        confidence = ent_data.get("confidence", "medium")
        conf_value = _confidence_to_float(confidence)
        if conf_value < settings.entity_min_confidence:
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

    return UnifiedResult(
        tags=tags,
        new_tags=new_tags,
        tier=tier,
        tier_explanation=tier_explanation,
        quality_score=score,
        score_explanation=score_explanation,
        summary=summary,
        topics=topics,
        pre_detected_validations=validations,
        additional_entities=additional,
    )


class UnifiedPipelineService:
    """Service for unified content classification and entity extraction."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        repo: SurrealDBRepository,
        settings: Settings,
    ):
        """Initialize unified pipeline service.

        Args:
            llm_provider: LLM provider for text generation
            repo: SurrealDB repository for tag lookups
            settings: Application settings
        """
        self.llm = llm_provider
        self.repo = repo
        self.settings = settings

    async def process(
        self,
        content_id: str,
        content_text: str,
        content_type: str,
        title: str,
        pre_detected: list | None = None,
        existing_topics: list[str] | None = None,
    ) -> UnifiedResult | None:
        """Run unified classification + entity extraction pipeline.

        Args:
            content_id: Content ID
            content_text: Full content text
            content_type: Type of content (youtube, markdown, etc.)
            title: Content title
            pre_detected: Pre-detected entity models
            existing_topics: Known topic strings

        Returns:
            UnifiedResult or None if skipped/failed
        """
        if not self.settings.unified_pipeline_enabled:
            logger.debug("Unified pipeline disabled, skipping %s", content_id)
            return None

        pre_detected = pre_detected or []
        existing_topics = existing_topics or []

        # Truncate content to 10k chars
        truncated = content_text[:10000]
        if len(content_text) > 10000:
            truncated += "\n\n[Content truncated...]"

        # Get existing tags
        try:
            tags_data = await self.repo.list_tags_with_counts()
            existing_tags = [t["name"] for t in tags_data]
        except Exception:
            existing_tags = []

        # Format pre-detected entities for prompt
        pre_detected_json = json.dumps(
            [
                {
                    "entity_id": (f"entity:{e.id}" if e.id else f"entity:{e.normalized_name}"),
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
        prompt = UNIFIED_PROMPT_TEMPLATE.format(
            content_type=content_type,
            title=title,
            existing_tags=(", ".join(existing_tags[:50]) if existing_tags else "None yet"),
            pre_detected_entities_json=pre_detected_json,
            existing_topics=topics_str,
            max_new_tags=self.settings.classification_max_new_labels,
            content_text=truncated,
        )

        # Call LLM
        try:
            response = await self.llm.generate(
                prompt,
                temperature=0.3,
                max_tokens=3000,
                timeout=120.0,
            )
        except Exception as e:
            logger.error("Unified pipeline LLM call failed for %s: %s", content_id, e)
            return None

        # Parse response
        data = extract_json(response)
        if not data:
            logger.warning("Empty unified pipeline response for %s", content_id)
            return None

        # Validate and build result
        result = parse_unified_response(data, existing_tags, self.settings)
        if result is None:
            logger.warning("Failed to parse unified response for %s", content_id)
            return None

        # Record model name and timestamp
        result.model = getattr(self.llm, "model", "fallback_chain")
        result.processed_at = datetime.now(UTC).isoformat()

        logger.info(
            "Unified pipeline %s: tier=%s score=%d tags=%s topics=%d",
            content_id,
            result.tier,
            result.quality_score,
            result.tags,
            len(result.topics),
        )

        return result
