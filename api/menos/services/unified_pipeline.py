"""Unified pipeline service combining classification and entity extraction in one LLM call."""

import asyncio
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

## TAG CO-OCCURRENCE PATTERNS
{tag_cooccurrence}

## QUALITY DISTRIBUTION (calibrate your ratings)
Current distribution: {tier_distribution}
Aim for a balanced distribution. Most content should be B or C tier.

## KNOWN ALIASES
{known_aliases}

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
    alias_mappings: list[tuple[str, str]] | None = None,
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
            if alias_mappings is not None and normalize_name(new_tag) != normalize_name(
                existing_match
            ):
                alias_mappings.append((new_tag, existing_match))
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

    @staticmethod
    def _format_cooccurrence(cooccurrence: dict[str, list[str]]) -> str:
        if not cooccurrence:
            return "None yet"
        lines = [
            f"- {tag} often appears with: {', '.join(related_tags)}"
            for tag, related_tags in sorted(cooccurrence.items())
            if related_tags
        ]
        return "\n".join(lines) if lines else "None yet"

    @staticmethod
    def _format_distribution(distribution: dict[str, int]) -> str:
        if not distribution:
            return "No data"
        total = sum(max(count, 0) for count in distribution.values())
        if total <= 0:
            return "No data"

        parts = []
        for tier in ["S", "A", "B", "C", "D"]:
            count = max(distribution.get(tier, 0), 0)
            pct = round((count / total) * 100)
            parts.append(f"{tier}={pct}%")
        return ", ".join(parts)

    @staticmethod
    def _format_aliases(aliases: dict[str, str]) -> str:
        if not aliases:
            return "None yet"
        return ", ".join(f"{variant} -> {canonical}" for variant, canonical in aliases.items())

    async def _resolve_prompt_topics(self, existing_topics: list[str] | None) -> list[str]:
        if existing_topics:
            return existing_topics

        topic_entities = await self.repo.get_topic_hierarchy()
        topics = []
        for topic in topic_entities:
            if topic.hierarchy:
                topics.append(" > ".join(topic.hierarchy))
            elif topic.name:
                topics.append(topic.name)
        return topics

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

        # Fetch prompt context
        t0 = time.monotonic()
        try:
            (
                tags_data,
                prompt_topics,
                tag_cooccurrence,
                tier_distribution,
                known_aliases,
            ) = await asyncio.gather(
                self.repo.list_tags_with_counts(),
                self._resolve_prompt_topics(existing_topics),
                self.repo.get_tag_cooccurrence(),
                self.repo.get_tier_distribution(),
                self.repo.get_tag_aliases(),
            )
            existing_tags = [t["name"] for t in tags_data]
        except Exception as e:
            raise PipelineStageError(
                "context_fetch",
                "CONTEXT_FETCH_ERROR",
                str(e)[:500],
            ) from e
        context_fetch_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "stage.context_fetch job_id=%s content_id=%s ms=%d tags=%d topics=%d",
            job_id,
            content_id,
            context_fetch_ms,
            len(existing_tags),
            len(prompt_topics),
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

        # Format prompt context
        topics_str = ", ".join(prompt_topics[:20]) if prompt_topics else "None yet"
        cooccurrence_str = self._format_cooccurrence(tag_cooccurrence)
        distribution_str = self._format_distribution(tier_distribution)
        aliases_str = self._format_aliases(known_aliases)

        # Build prompt
        prompt = UNIFIED_PROMPT_TEMPLATE.format(
            content_type=content_type,
            title=title,
            existing_tags=(", ".join(existing_tags[:50]) if existing_tags else "None yet"),
            pre_detected_entities_json=pre_detected_json,
            existing_topics=topics_str,
            tag_cooccurrence=cooccurrence_str,
            tier_distribution=distribution_str,
            known_aliases=aliases_str,
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

        # Parse response (with one retry if JSON extraction fails)
        t0 = time.monotonic()
        data = extract_json(response)
        if not data:
            logger.warning(
                "stage.parse.retry job_id=%s content_id=%s raw_len=%d",
                job_id,
                content_id,
                len(response),
            )
            correction_prompt = (
                "Your previous response was not valid JSON. "
                "Convert the following content into the exact JSON format requested. "
                "Respond ONLY with valid JSON, no markdown, no explanation.\n\n"
                f"{response[:3000]}"
            )
            try:
                retry_response = await llm_provider.generate(
                    correction_prompt,
                    temperature=0.1,
                    max_tokens=3000,
                    timeout=60.0,
                )
                data = extract_json(retry_response)
            except Exception:
                pass

        if not data:
            raise PipelineStageError(
                "parse",
                "EMPTY_RESPONSE",
                f"Empty unified pipeline response for {content_id}",
            )

        alias_mappings: list[tuple[str, str]] = []
        result = parse_unified_response(data, existing_tags, self.settings, alias_mappings)
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

        if alias_mappings:
            unique_aliases = sorted(set(alias_mappings))
            await asyncio.gather(
                *[
                    self.repo.record_tag_alias(variant=variant, canonical=canonical)
                    for variant, canonical in unique_aliases
                ]
            )

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
