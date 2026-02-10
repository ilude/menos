"""Content classification service for quality rating and labeling."""

import json
import logging
import re
import time
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from Levenshtein import distance

from menos.config import Settings
from menos.models import ClassificationResult
from menos.services.llm import LLMProvider
from menos.services.normalization import normalize_name
from menos.services.storage import SurrealDBRepository

logger = logging.getLogger(__name__)

VALID_TIERS = {"S", "A", "B", "C", "D"}
LABEL_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")

CLASSIFICATION_PROMPT_TEMPLATE = """You are a content quality classifier. Evaluate the content \
and assign quality ratings and labels.

## EXISTING LABELS (prefer these over creating new ones)
{existing_labels}

## USER INTEREST PROFILE (bias quality ratings toward these interests)
Topics: {interest_topics}
Tags: {interest_tags}
Channels: {interest_channels}

## RULES
- Assign up to 10 labels from existing labels above
- You may create up to {max_new_labels} NEW labels if needed (lowercase, hyphenated)
- Labels must be single lowercase words or hyphenated (e.g. "kubernetes", "home-lab")
- Assign a quality tier: S (exceptional), A (great), B (good), C (mediocre), D (poor)
- Assign a quality score from 1-100 where 50 = average, 80+ = exceptional, <30 = low value
- Bias ratings toward the user's interest profile above
- Provide brief explanations (2-3 bullet points each)

## CALIBRATION
- Score 50 = average content with moderate relevance
- Score 80+ = exceptional content highly relevant to interests
- Score <30 = low value or irrelevant content
- S tier = must-read, directly relevant to core interests
- D tier = skip, little value or relevance

<CONTENT>
{content_text}
</CONTENT>

Respond ONLY with valid JSON (no markdown, no code blocks):
{{
  "labels": ["existing-label-1", "existing-label-2"],
  "new_labels": ["genuinely-new-label"],
  "tier": "B",
  "tier_explanation": ["Reason 1", "Reason 2"],
  "quality_score": 55,
  "score_explanation": ["Reason 1", "Reason 2"]
}}"""


@runtime_checkable
class InterestProvider(Protocol):
    """Protocol for providing user interest data."""

    async def get_interests(self) -> dict[str, list[str]]:
        """Get user interests for classification bias.

        Returns:
            Dict with keys: topics, tags, channels
        """
        ...


class VaultInterestProvider:
    """Interest provider that derives interests from vault content."""

    def __init__(self, repo: SurrealDBRepository, top_n: int = 15):
        """Initialize with storage repository.

        Args:
            repo: SurrealDB repository
            top_n: Number of top items per signal
        """
        self.repo = repo
        self.top_n = top_n
        self._cache: dict[str, list[str]] | None = None
        self._cache_time: float = 0
        self._cache_ttl: float = 300.0  # 5 minutes

    async def get_interests(self) -> dict[str, list[str]]:
        """Get interests with TTL caching."""
        now = time.monotonic()
        if self._cache is not None and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        self._cache = await self.repo.get_interest_profile(top_n=self.top_n)
        self._cache_time = now
        return self._cache


def _extract_json_from_response(response: str) -> dict[str, Any]:
    """Extract JSON from LLM response, handling markdown code blocks.

    Args:
        response: Raw LLM response

    Returns:
        Parsed JSON dictionary
    """
    response = response.strip()
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass

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

    logger.warning("Failed to parse classification JSON: %s", response[:200])
    return {}


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


class ClassificationService:
    """Service for classifying content quality and assigning labels."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        interest_provider: InterestProvider,
        repo: SurrealDBRepository,
        settings: Settings,
    ):
        """Initialize classification service.

        Args:
            llm_provider: LLM provider for classification
            interest_provider: Provider for user interest data
            repo: SurrealDB repository for label lookups
            settings: Application settings
        """
        self.llm = llm_provider
        self.interest_provider = interest_provider
        self.repo = repo
        self.settings = settings

    async def classify_content(
        self,
        content_id: str,
        content_text: str,
        content_type: str,
        title: str,
    ) -> ClassificationResult | None:
        """Classify content with quality tier, score, and labels.

        Args:
            content_id: Content ID
            content_text: Full content text
            content_type: Type of content (youtube, markdown, etc.)
            title: Content title

        Returns:
            ClassificationResult or None if skipped/failed
        """
        if not self.settings.classification_enabled:
            logger.debug("Classification disabled, skipping %s", content_id)
            return None

        if len(content_text) < self.settings.classification_min_content_length:
            logger.debug(
                "Content too short for classification (%d chars): %s",
                len(content_text),
                content_id,
            )
            return None

        # Truncate content to 10k chars
        truncated = content_text[:10000]
        if len(content_text) > 10000:
            truncated += "\n\n[Content truncated...]"

        # Get existing labels and interests
        try:
            tags_data = await self.repo.list_tags_with_counts()
            existing_labels = [t["name"] for t in tags_data]
        except Exception:
            existing_labels = []

        try:
            interests = await self.interest_provider.get_interests()
        except Exception:
            interests = {"topics": [], "tags": [], "channels": []}

        # Build prompt
        prompt = CLASSIFICATION_PROMPT_TEMPLATE.format(
            existing_labels=(
                ", ".join(existing_labels[:50]) if existing_labels else "None yet"
            ),
            interest_topics=", ".join(interests.get("topics", [])) or "None yet",
            interest_tags=", ".join(interests.get("tags", [])) or "None yet",
            interest_channels=(
                ", ".join(interests.get("channels", [])) or "None yet"
            ),
            max_new_labels=self.settings.classification_max_new_labels,
            content_text=truncated,
        )

        # Call LLM
        try:
            response = await self.llm.generate(
                prompt,
                temperature=0.3,
                max_tokens=2000,
                timeout=60.0,
            )
        except Exception as e:
            logger.error("Classification LLM call failed for %s: %s", content_id, e)
            return None

        # Parse response
        data = _extract_json_from_response(response)
        if not data:
            logger.warning("Empty classification response for %s", content_id)
            return None

        # Validate and build result
        result = self._parse_classification_response(data, existing_labels)

        # Record model name and timestamp
        result.model = getattr(self.llm, "model", "fallback_chain")
        result.classified_at = datetime.now(UTC).isoformat()

        logger.info(
            "Classified %s: tier=%s score=%d labels=%s",
            content_id,
            result.tier,
            result.quality_score,
            result.labels,
        )

        return result

    def _parse_classification_response(
        self,
        data: dict[str, Any],
        existing_labels: list[str],
    ) -> ClassificationResult:
        """Parse and validate LLM classification response.

        Args:
            data: Parsed JSON from LLM
            existing_labels: Known labels for dedup

        Returns:
            Validated ClassificationResult
        """
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

        # Validate labels from existing
        raw_labels = data.get("labels", [])
        if not isinstance(raw_labels, list):
            raw_labels = []
        labels = [
            lbl for lbl in raw_labels
            if isinstance(lbl, str) and LABEL_PATTERN.match(lbl)
        ]

        # Process new labels with deterministic dedup
        raw_new_labels = data.get("new_labels", [])
        if not isinstance(raw_new_labels, list):
            raw_new_labels = []

        max_new = self.settings.classification_max_new_labels
        new_count = 0
        for new_label in raw_new_labels:
            if new_count >= max_new:
                break
            if not isinstance(new_label, str) or not LABEL_PATTERN.match(new_label):
                continue

            # Deterministic dedup: check against existing labels
            existing_match = _dedup_label(new_label, existing_labels + labels)
            if existing_match:
                # Map to existing label if not already in labels
                if existing_match not in labels:
                    labels.append(existing_match)
            else:
                # Genuinely new label
                if new_label not in labels:
                    labels.append(new_label)
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

        return ClassificationResult(
            labels=labels,
            tier=tier,
            tier_explanation=tier_explanation,
            quality_score=score,
            score_explanation=score_explanation,
        )
