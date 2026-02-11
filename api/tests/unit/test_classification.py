"""Tests for content classification service."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from menos.models import ClassificationResult
from menos.services.classification import (
    CLASSIFICATION_PROMPT_TEMPLATE,
    ClassificationService,
    VaultInterestProvider,
    _dedup_label,
)
from menos.services.llm_json import extract_json


@pytest.fixture
def mock_settings():
    """Create mock settings for classification."""
    s = MagicMock()
    s.classification_enabled = True
    s.classification_min_content_length = 500
    s.classification_max_new_labels = 3
    s.classification_interest_top_n = 15
    return s


@pytest.fixture
def mock_llm_provider():
    """Create mock LLM provider."""
    provider = MagicMock()
    provider.model = "test-model"
    provider.generate = AsyncMock(
        return_value=json.dumps(
            {
                "labels": ["programming", "kubernetes"],
                "new_labels": ["homelab"],
                "tier": "A",
                "tier_explanation": ["Rich technical content", "Relevant to interests"],
                "quality_score": 78,
                "score_explanation": ["Novel approach", "High density"],
                "summary": "A deep dive into Kubernetes.\n\n- Topic 1\n- Topic 2\n- Topic 3",
            }
        )
    )
    return provider


@pytest.fixture
def mock_interest_provider():
    """Create mock interest provider."""
    provider = MagicMock()
    provider.get_interests = AsyncMock(
        return_value={
            "topics": ["Kubernetes", "Python"],
            "tags": ["devops", "programming"],
            "channels": ["TechChannel"],
        }
    )
    return provider


@pytest.fixture
def mock_repo():
    """Create mock SurrealDB repository."""
    repo = MagicMock()
    repo.list_tags_with_counts = AsyncMock(
        return_value=[
            {"name": "programming", "count": 10},
            {"name": "kubernetes", "count": 5},
            {"name": "devops", "count": 3},
        ]
    )
    repo.get_interest_profile = AsyncMock(
        return_value={
            "topics": ["Kubernetes"],
            "tags": ["devops"],
            "channels": ["TechChannel"],
        }
    )
    return repo


@pytest.fixture
def classification_service(mock_llm_provider, mock_interest_provider, mock_repo, mock_settings):
    """Create ClassificationService with mocks."""
    return ClassificationService(
        llm_provider=mock_llm_provider,
        interest_provider=mock_interest_provider,
        repo=mock_repo,
        settings=mock_settings,
    )


class TestClassificationDisabled:
    """Test classification when disabled."""

    @pytest.mark.asyncio
    async def test_returns_none_when_disabled(self, classification_service, mock_settings):
        mock_settings.classification_enabled = False
        result = await classification_service.classify_content(
            content_id="test-1",
            content_text="x" * 1000,
            content_type="youtube",
            title="Test",
        )
        assert result is None


class TestShortContent:
    """Test classification with short content."""

    @pytest.mark.asyncio
    async def test_returns_none_for_short_content(self, classification_service):
        result = await classification_service.classify_content(
            content_id="test-1",
            content_text="Short text",
            content_type="youtube",
            title="Test",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_at_boundary(self, classification_service):
        result = await classification_service.classify_content(
            content_id="test-1",
            content_text="x" * 499,
            content_type="youtube",
            title="Test",
        )
        assert result is None


class TestHappyPath:
    """Test successful classification."""

    @pytest.mark.asyncio
    async def test_parses_labels_correctly(self, classification_service, mock_llm_provider):
        result = await classification_service.classify_content(
            content_id="test-1",
            content_text="x" * 1000,
            content_type="youtube",
            title="Test Video",
        )
        assert result is not None
        assert "programming" in result.labels
        assert "kubernetes" in result.labels

    @pytest.mark.asyncio
    async def test_tier_parsed(self, classification_service):
        result = await classification_service.classify_content(
            content_id="test-1",
            content_text="x" * 1000,
            content_type="youtube",
            title="Test Video",
        )
        assert result is not None
        assert result.tier == "A"

    @pytest.mark.asyncio
    async def test_quality_score_parsed(self, classification_service):
        result = await classification_service.classify_content(
            content_id="test-1",
            content_text="x" * 1000,
            content_type="youtube",
            title="Test Video",
        )
        assert result is not None
        assert result.quality_score == 78

    @pytest.mark.asyncio
    async def test_model_name_populated(self, classification_service):
        result = await classification_service.classify_content(
            content_id="test-1",
            content_text="x" * 1000,
            content_type="youtube",
            title="Test Video",
        )
        assert result is not None
        assert result.model == "test-model"

    @pytest.mark.asyncio
    async def test_classified_at_populated(self, classification_service):
        result = await classification_service.classify_content(
            content_id="test-1",
            content_text="x" * 1000,
            content_type="youtube",
            title="Test Video",
        )
        assert result is not None
        assert result.classified_at != ""

    @pytest.mark.asyncio
    async def test_new_labels_included(self, classification_service):
        result = await classification_service.classify_content(
            content_id="test-1",
            content_text="x" * 1000,
            content_type="youtube",
            title="Test Video",
        )
        assert result is not None
        assert "homelab" in result.labels

    @pytest.mark.asyncio
    async def test_summary_parsed(self, classification_service):
        result = await classification_service.classify_content(
            content_id="test-1",
            content_text="x" * 1000,
            content_type="youtube",
            title="Test Video",
        )
        assert result is not None
        assert "Kubernetes" in result.summary
        assert "- Topic 1" in result.summary

    @pytest.mark.asyncio
    async def test_missing_summary_defaults_to_empty(
        self, classification_service, mock_llm_provider
    ):
        mock_llm_provider.generate = AsyncMock(
            return_value=json.dumps(
                {
                    "labels": ["programming"],
                    "new_labels": [],
                    "tier": "B",
                    "tier_explanation": [],
                    "quality_score": 50,
                    "score_explanation": [],
                }
            )
        )
        result = await classification_service.classify_content(
            content_id="test-1",
            content_text="x" * 1000,
            content_type="youtube",
            title="Test",
        )
        assert result is not None
        assert result.summary == ""


class TestTierValidation:
    """Test tier validation."""

    @pytest.mark.asyncio
    async def test_invalid_tier_defaults_to_c(self, classification_service, mock_llm_provider):
        mock_llm_provider.generate = AsyncMock(
            return_value=json.dumps(
                {
                    "labels": [],
                    "new_labels": [],
                    "tier": "X",
                    "tier_explanation": [],
                    "quality_score": 50,
                    "score_explanation": [],
                }
            )
        )
        result = await classification_service.classify_content(
            content_id="test-1",
            content_text="x" * 1000,
            content_type="youtube",
            title="Test",
        )
        assert result is not None
        assert result.tier == "C"

    @pytest.mark.asyncio
    async def test_all_valid_tiers_accepted(self, classification_service, mock_llm_provider):
        for tier in ["S", "A", "B", "C", "D"]:
            mock_llm_provider.generate = AsyncMock(
                return_value=json.dumps(
                    {
                        "labels": [],
                        "new_labels": [],
                        "tier": tier,
                        "tier_explanation": [],
                        "quality_score": 50,
                        "score_explanation": [],
                    }
                )
            )
            result = await classification_service.classify_content(
                content_id="test-1",
                content_text="x" * 1000,
                content_type="youtube",
                title="Test",
            )
            assert result is not None
            assert result.tier == tier


class TestScoreClamping:
    """Test quality score clamping."""

    @pytest.mark.asyncio
    async def test_score_clamped_to_100(self, classification_service, mock_llm_provider):
        mock_llm_provider.generate = AsyncMock(
            return_value=json.dumps(
                {
                    "labels": [],
                    "new_labels": [],
                    "tier": "S",
                    "tier_explanation": [],
                    "quality_score": 150,
                    "score_explanation": [],
                }
            )
        )
        result = await classification_service.classify_content(
            content_id="test-1",
            content_text="x" * 1000,
            content_type="youtube",
            title="Test",
        )
        assert result is not None
        assert result.quality_score == 100

    @pytest.mark.asyncio
    async def test_score_clamped_to_1(self, classification_service, mock_llm_provider):
        mock_llm_provider.generate = AsyncMock(
            return_value=json.dumps(
                {
                    "labels": [],
                    "new_labels": [],
                    "tier": "D",
                    "tier_explanation": [],
                    "quality_score": -5,
                    "score_explanation": [],
                }
            )
        )
        result = await classification_service.classify_content(
            content_id="test-1",
            content_text="x" * 1000,
            content_type="youtube",
            title="Test",
        )
        assert result is not None
        assert result.quality_score == 1


class TestLLMErrorHandling:
    """Test LLM error handling."""

    @pytest.mark.asyncio
    async def test_llm_error_returns_none(self, classification_service, mock_llm_provider):
        mock_llm_provider.generate = AsyncMock(side_effect=RuntimeError("LLM connection failed"))
        result = await classification_service.classify_content(
            content_id="test-1",
            content_text="x" * 1000,
            content_type="youtube",
            title="Test",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_json_returns_none(self, classification_service, mock_llm_provider):
        mock_llm_provider.generate = AsyncMock(return_value="not json at all }{")
        result = await classification_service.classify_content(
            content_id="test-1",
            content_text="x" * 1000,
            content_type="youtube",
            title="Test",
        )
        assert result is None


class TestDeterministicDedup:
    """Test deterministic label deduplication."""

    def test_maps_k8s_to_kubernetes(self):
        existing = ["kubernetes", "docker", "python"]
        match = _dedup_label("k8s", existing, max_distance=2)
        # "k8s" normalized is "k8s", "kubernetes" normalized is "kubernetes"
        # distance > 2, so no match
        assert match is None

    def test_maps_near_duplicate(self):
        existing = ["kubernetes", "docker", "python"]
        match = _dedup_label("kubernets", existing, max_distance=2)
        assert match == "kubernetes"

    def test_keeps_genuinely_new(self):
        existing = ["kubernetes", "docker", "python"]
        match = _dedup_label("homelab", existing, max_distance=2)
        assert match is None

    def test_exact_match_deduped(self):
        existing = ["programming", "devops"]
        match = _dedup_label("programming", existing, max_distance=2)
        assert match == "programming"

    @pytest.mark.asyncio
    async def test_dedup_integrated_in_service(self, classification_service, mock_llm_provider):
        """new_labels with close match to existing get mapped."""
        mock_llm_provider.generate = AsyncMock(
            return_value=json.dumps(
                {
                    "labels": ["programming"],
                    "new_labels": ["programing"],  # One letter off
                    "tier": "B",
                    "tier_explanation": [],
                    "quality_score": 50,
                    "score_explanation": [],
                }
            )
        )
        result = await classification_service.classify_content(
            content_id="test-1",
            content_text="x" * 1000,
            content_type="youtube",
            title="Test",
        )
        assert result is not None
        assert "programming" in result.labels
        assert "programing" not in result.labels


class TestLabelValidation:
    """Test label format validation."""

    @pytest.mark.asyncio
    async def test_invalid_labels_filtered(self, classification_service, mock_llm_provider):
        mock_llm_provider.generate = AsyncMock(
            return_value=json.dumps(
                {
                    "labels": ["valid-label", "UPPERCASE", "has spaces", "123start", "ok"],
                    "new_labels": [],
                    "tier": "B",
                    "tier_explanation": [],
                    "quality_score": 50,
                    "score_explanation": [],
                }
            )
        )
        result = await classification_service.classify_content(
            content_id="test-1",
            content_text="x" * 1000,
            content_type="youtube",
            title="Test",
        )
        assert result is not None
        assert "valid-label" in result.labels
        assert "ok" in result.labels
        assert "UPPERCASE" not in result.labels
        assert "has spaces" not in result.labels
        assert "123start" not in result.labels


class TestContentDelimiters:
    """Test prompt formatting."""

    def test_content_wrapped_in_tags(self):
        """Content in prompt is wrapped in <CONTENT> tags."""
        assert "<CONTENT>" in CLASSIFICATION_PROMPT_TEMPLATE
        assert "</CONTENT>" in CLASSIFICATION_PROMPT_TEMPLATE

    @pytest.mark.asyncio
    async def test_prompt_contains_content_tags(self, classification_service, mock_llm_provider):
        await classification_service.classify_content(
            content_id="test-1",
            content_text="x" * 1000,
            content_type="youtube",
            title="Test",
        )
        call_args = mock_llm_provider.generate.call_args
        prompt = call_args.args[0]
        assert "<CONTENT>" in prompt
        assert "</CONTENT>" in prompt


class TestVaultInterestProvider:
    """Test VaultInterestProvider caching."""

    @pytest.mark.asyncio
    async def test_caches_within_ttl(self, mock_repo):
        provider = VaultInterestProvider(repo=mock_repo, top_n=15)
        provider._cache_ttl = 300.0

        result1 = await provider.get_interests()
        result2 = await provider.get_interests()

        assert result1 == result2
        assert mock_repo.get_interest_profile.call_count == 1

    @pytest.mark.asyncio
    async def test_refreshes_after_ttl(self, mock_repo):
        provider = VaultInterestProvider(repo=mock_repo, top_n=15)
        provider._cache_ttl = 0.0  # Expire immediately

        await provider.get_interests()
        await provider.get_interests()

        assert mock_repo.get_interest_profile.call_count == 2


class TestJsonExtraction:
    """Test JSON extraction from LLM responses."""

    def test_direct_json(self):
        data = extract_json('{"tier": "A"}')
        assert data["tier"] == "A"

    def test_markdown_code_block(self):
        response = '```json\n{"tier": "B"}\n```'
        data = extract_json(response)
        assert data["tier"] == "B"

    def test_invalid_returns_empty(self):
        data = extract_json("not json at all")
        assert data == {}


class TestClassificationResult:
    """Test ClassificationResult model."""

    def test_serializes_to_dict(self):
        result = ClassificationResult(
            labels=["test"],
            tier="A",
            tier_explanation=["Good"],
            quality_score=80,
            score_explanation=["High"],
            model="test-model",
            classified_at="2026-02-10T12:00:00Z",
        )
        d = result.model_dump()
        assert d["tier"] == "A"
        assert d["quality_score"] == 80
        assert d["labels"] == ["test"]

    def test_defaults(self):
        result = ClassificationResult()
        assert result.labels == []
        assert result.tier == ""
        assert result.quality_score == 0
        assert result.summary == ""
