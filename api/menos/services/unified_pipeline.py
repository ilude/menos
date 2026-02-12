"""Unified pipeline service combining classification and entity extraction in one LLM call."""

import json
import logging
import re
import time
from datetime import UTC, datetime
from typing import Any

from Levenshtein import distance

from menos.config import Settings
from menos.models import (
    EdgeType,
    EntityType,
    ExtractedEntity,
    PreDetectedValidation,
    UnifiedResult,
)
from menos.services.llm import LLMProvider
from menos.services.llm_json import extract_json
from menos.services.normalization import normalize_name
from menos.services.storage import SurrealDBRepository

logger = logging.getLogger(__name__)

VALID_TIERS = {"S", "A", "B", "C", "D"}
LABEL_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


def _dedup_label(
    new_label: str,
    existing_labels: list[str],
    max_distance: int = 2,
) -> str | None:
    """Check if a new label is a near-duplicate of an existing label.

    Uses normalize_name() + Levenshtein distance for deterministic matching.

    Args:
        new_label: The candidate new label
        existing_labels: Known labels in the vault
        max_distance: Maximum edit distance to consider as duplicate

    Returns:
        Existing label name if duplicate found, None if genuinely new
    """
    normalized_new = normalize_name(new_label)

    for existing in existing_labels:
        normalized_existing = normalize_name(existing)
        if distance(normalized_new, normalized_existing) <= max_distance:
            return existing

    return None


def _parse_topic_hierarchy(topic_str: str) -> list[str]:
    """Parse a topic hierarchy string into a list of components.

    "AI > LLMs > RAG" -> ["AI", "LLMs", "RAG"]
    """
    parts = [p.strip() for p in topic_str.split(">")]
    return [p for p in parts if p]


def _confidence_to_float(confidence: str) -> float:
    """Convert confidence string to float value."""
    mapping = {"high": 0.9, "medium": 0.7, "low": 0.5}
    return mapping.get(confidence.lower(), 0.6)


def _edge_type_from_string(edge_str: str) -> EdgeType:
    """Convert edge type string to EdgeType enum."""
    mapping = {
        "discusses": EdgeType.DISCUSSES,
        "mentions": EdgeType.MENTIONS,
        "cites": EdgeType.CITES,
        "uses": EdgeType.USES,
        "demonstrates": EdgeType.DEMONSTRATES,
    }
    return mapping.get(edge_str.lower(), EdgeType.MENTIONS)


def _entity_type_from_string(type_str: str) -> EntityType:
    """Convert entity type string to EntityType enum."""
    mapping = {
        "topic": EntityType.TOPIC,
        "repo": EntityType.REPO,
        "paper": EntityType.PAPER,
        "tool": EntityType.TOOL,
        "person": EntityType.PERSON,
    }
    return mapping.get(type_str.lower(), EntityType.TOPIC)


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


class PipelineStageError(Exception):
    """Error with pipeline stage context for observability."""

    def __init__(self, stage: str, code: str, message: str):
        self.stage = stage
        self.code = code
        self.message = message
        super().__init__(f"[{stage}] {code}: {message}")


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
    max_new = settings.unified_pipeline_max_new_tags
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

    def _provider_for_job(self, job_id: str | None) -> LLMProvider:
        """Return provider with per-job metering context when supported."""
        if not job_id:
            return self.llm
        with_context = getattr(self.llm, "with_context", None)
        if callable(with_context):
            return with_context(f"pipeline:{job_id}")
        return self.llm

    async def process(
        self,
        content_id: str,
        content_text: str,
        content_type: str,
        title: str,
        pre_detected: list | None = None,
        existing_topics: list[str] | None = None,
        job_id: str | None = None,
    ) -> UnifiedResult | None:
        """Run unified classification + entity extraction pipeline.

        Args:
            content_id: Content ID
            content_text: Full content text
            content_type: Type of content (youtube, markdown, etc.)
            title: Content title
            pre_detected: Pre-detected entity models
            existing_topics: Known topic strings
            job_id: Pipeline job ID for log correlation

        Returns:
            UnifiedResult or None if skipped/failed
        """
        if not self.settings.unified_pipeline_enabled:
            logger.debug(
                "Unified pipeline disabled, skipping %s job_id=%s",
                content_id,
                job_id,
            )
            return None

        pre_detected = pre_detected or []
        existing_topics = existing_topics or []

        # Truncate content to 10k chars
        t0 = time.monotonic()
        truncated = content_text[:10000]
        if len(content_text) > 10000:
            truncated += "\n\n[Content truncated...]"
        truncation_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "stage.truncation job_id=%s content_id=%s ms=%d",
            job_id,
            content_id,
            truncation_ms,
        )

        # Get existing tags
        t0 = time.monotonic()
        try:
            tags_data = await self.repo.list_tags_with_counts()
            existing_tags = [t["name"] for t in tags_data]
        except Exception as e:
            raise PipelineStageError(
                "tag_fetch",
                "TAG_FETCH_ERROR",
                str(e)[:500],
            ) from e
        tag_fetch_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "stage.tag_fetch job_id=%s content_id=%s ms=%d tags=%d",
            job_id,
            content_id,
            tag_fetch_ms,
            len(existing_tags),
        )

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
            max_new_tags=self.settings.unified_pipeline_max_new_tags,
            content_text=truncated,
        )

        # Call LLM
        t0 = time.monotonic()
        llm_provider = self._provider_for_job(job_id)
        try:
            response = await llm_provider.generate(
                prompt,
                temperature=0.3,
                max_tokens=3000,
                timeout=120.0,
            )
        except Exception as e:
            raise PipelineStageError(
                "llm_call",
                "LLM_CALL_ERROR",
                str(e)[:500],
            ) from e
        llm_ms = int((time.monotonic() - t0) * 1000)
        token_estimate = len(prompt) // 4 + len(response) // 4
        logger.info(
            "stage.llm_call job_id=%s content_id=%s ms=%d token_est=%d",
            job_id,
            content_id,
            llm_ms,
            token_estimate,
        )

        # Parse response
        t0 = time.monotonic()
        data = extract_json(response)
        if not data:
            raise PipelineStageError(
                "parse",
                "EMPTY_RESPONSE",
                f"Empty unified pipeline response for {content_id}",
            )

        result = parse_unified_response(data, existing_tags, self.settings)
        if result is None:
            raise PipelineStageError(
                "parse",
                "PARSE_FAILED",
                f"Failed to parse unified response for {content_id}",
            )
        parse_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "stage.parse job_id=%s content_id=%s ms=%d",
            job_id,
            content_id,
            parse_ms,
        )

        # Record model name and timestamp
        result.model = getattr(llm_provider, "model", "fallback_chain")
        result.processed_at = datetime.now(UTC).isoformat()

        logger.info(
            "pipeline.complete job_id=%s content_id=%s tier=%s score=%d tags=%s topics=%d",
            job_id,
            content_id,
            result.tier,
            result.quality_score,
            result.tags,
            len(result.topics),
        )

        return result
