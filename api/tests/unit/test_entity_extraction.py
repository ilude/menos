"""Unit tests for entity extraction service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from menos.models import EdgeType, EntityModel, EntitySource, EntityType


class TestEntityExtractionService:
    """Tests for EntityExtractionService."""

    @pytest.fixture
    def mock_llm_provider(self):
        """Create mock LLM provider."""
        provider = MagicMock()
        provider.generate = AsyncMock(return_value='{"topics": [], "pre_detected_validations": [], "additional_entities": []}')
        return provider

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        settings = MagicMock()
        settings.entity_extraction_enabled = True
        settings.entity_max_topics_per_content = 7
        settings.entity_min_confidence = 0.6
        return settings

    @pytest.fixture
    def extraction_service(self, mock_llm_provider, mock_settings):
        """Create extraction service with mocks."""
        from menos.services.entity_extraction import EntityExtractionService

        return EntityExtractionService(
            llm_provider=mock_llm_provider,
            settings=mock_settings,
        )

    def test_should_skip_llm_when_disabled(self, extraction_service, mock_settings):
        """Test that LLM is skipped when extraction is disabled."""
        mock_settings.entity_extraction_enabled = False

        result = extraction_service.should_skip_llm(
            content_text="Some content",
            content_type="youtube",
            pre_detected=[],
        )

        assert result is True

    def test_should_skip_llm_short_content(self, extraction_service):
        """Test that LLM is skipped for short content."""
        result = extraction_service.should_skip_llm(
            content_text="Short",
            content_type="youtube",
            pre_detected=[],
        )

        assert result is True

    def test_should_not_skip_llm_for_long_content(self, extraction_service):
        """Test that LLM is not skipped for long content."""
        long_text = "a" * 1000

        result = extraction_service.should_skip_llm(
            content_text=long_text,
            content_type="youtube",
            pre_detected=[],
        )

        assert result is False

    def test_should_skip_llm_many_predetected_changelog(self, extraction_service):
        """Test that LLM is skipped for changelogs with many pre-detected entities."""
        pre_detected = [
            EntityModel(
                entity_type=EntityType.REPO,
                name=f"repo{i}",
                normalized_name=f"repo{i}",
                source=EntitySource.URL_DETECTED,
            )
            for i in range(6)
        ]

        result = extraction_service.should_skip_llm(
            content_text="a" * 1000,
            content_type="changelog",
            pre_detected=pre_detected,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_extract_entities_skipped(self, extraction_service):
        """Test extraction when LLM is skipped."""
        result, metrics = await extraction_service.extract_entities(
            content_text="Short",
            content_type="youtube",
            title="Test Video",
        )

        assert metrics.llm_skipped is True
        assert len(result.topics) == 0

    @pytest.mark.asyncio
    async def test_extract_entities_parses_topics(self, extraction_service, mock_llm_provider):
        """Test that topics are parsed from LLM response."""
        mock_llm_provider.generate = AsyncMock(
            return_value="""
            {
                "topics": [
                    {"name": "AI > LLMs > RAG", "confidence": "high", "edge_type": "discusses"}
                ],
                "pre_detected_validations": [],
                "additional_entities": []
            }
            """
        )

        result, metrics = await extraction_service.extract_entities(
            content_text="a" * 1000,
            content_type="youtube",
            title="RAG Tutorial",
        )

        assert metrics.llm_skipped is False
        assert len(result.topics) == 1
        assert result.topics[0].name == "RAG"
        assert result.topics[0].hierarchy == ["AI", "LLMs", "RAG"]
        assert result.topics[0].edge_type == EdgeType.DISCUSSES

    @pytest.mark.asyncio
    async def test_extract_entities_parses_validations(self, extraction_service, mock_llm_provider):
        """Test that pre-detected validations are parsed."""
        mock_llm_provider.generate = AsyncMock(
            return_value="""
            {
                "topics": [],
                "pre_detected_validations": [
                    {"entity_id": "entity:langchain", "edge_type": "uses", "confirmed": true}
                ],
                "additional_entities": []
            }
            """
        )

        result, metrics = await extraction_service.extract_entities(
            content_text="a" * 1000,
            content_type="youtube",
            title="LangChain Tutorial",
        )

        assert len(result.pre_detected_validations) == 1
        assert result.pre_detected_validations[0].entity_id == "entity:langchain"
        assert result.pre_detected_validations[0].edge_type == EdgeType.USES
        assert result.pre_detected_validations[0].confirmed is True

    @pytest.mark.asyncio
    async def test_extract_entities_parses_additional(self, extraction_service, mock_llm_provider):
        """Test that additional entities are parsed."""
        mock_llm_provider.generate = AsyncMock(
            return_value="""
            {
                "topics": [],
                "pre_detected_validations": [],
                "additional_entities": [
                    {"type": "repo", "name": "FAISS", "confidence": "medium", "edge_type": "mentions"}
                ]
            }
            """
        )

        result, metrics = await extraction_service.extract_entities(
            content_text="a" * 1000,
            content_type="youtube",
            title="Vector Search",
        )

        assert len(result.additional_entities) == 1
        assert result.additional_entities[0].name == "FAISS"
        assert result.additional_entities[0].entity_type == EntityType.REPO
        assert result.additional_entities[0].edge_type == EdgeType.MENTIONS

    @pytest.mark.asyncio
    async def test_extract_entities_handles_markdown_json(self, extraction_service, mock_llm_provider):
        """Test that JSON in markdown code blocks is parsed."""
        mock_llm_provider.generate = AsyncMock(
            return_value="""
            ```json
            {
                "topics": [
                    {"name": "Python", "confidence": "high", "edge_type": "discusses"}
                ],
                "pre_detected_validations": [],
                "additional_entities": []
            }
            ```
            """
        )

        result, metrics = await extraction_service.extract_entities(
            content_text="a" * 1000,
            content_type="markdown",
            title="Python Guide",
        )

        assert len(result.topics) == 1
        assert result.topics[0].name == "Python"

    @pytest.mark.asyncio
    async def test_extract_entities_respects_max_topics(self, extraction_service, mock_llm_provider, mock_settings):
        """Test that max topics limit is respected."""
        mock_settings.entity_max_topics_per_content = 2

        mock_llm_provider.generate = AsyncMock(
            return_value="""
            {
                "topics": [
                    {"name": "AI", "confidence": "high", "edge_type": "discusses"},
                    {"name": "ML", "confidence": "high", "edge_type": "discusses"},
                    {"name": "DL", "confidence": "high", "edge_type": "discusses"},
                    {"name": "NLP", "confidence": "high", "edge_type": "discusses"}
                ],
                "pre_detected_validations": [],
                "additional_entities": []
            }
            """
        )

        result, metrics = await extraction_service.extract_entities(
            content_text="a" * 1000,
            content_type="youtube",
            title="AI Overview",
        )

        assert len(result.topics) == 2

    @pytest.mark.asyncio
    async def test_extract_entities_filters_low_confidence(self, extraction_service, mock_llm_provider, mock_settings):
        """Test that low confidence topics are filtered."""
        mock_settings.entity_min_confidence = 0.6

        mock_llm_provider.generate = AsyncMock(
            return_value="""
            {
                "topics": [
                    {"name": "AI", "confidence": "high", "edge_type": "discusses"},
                    {"name": "Maybe", "confidence": "low", "edge_type": "mentions"}
                ],
                "pre_detected_validations": [],
                "additional_entities": []
            }
            """
        )

        result, metrics = await extraction_service.extract_entities(
            content_text="a" * 1000,
            content_type="youtube",
            title="AI Overview",
        )

        # "high" = 0.9, "low" = 0.5, min = 0.6
        assert len(result.topics) == 1
        assert result.topics[0].name == "AI"

    @pytest.mark.asyncio
    async def test_extract_entities_handles_llm_error(self, extraction_service, mock_llm_provider):
        """Test graceful handling of LLM errors."""
        mock_llm_provider.generate = AsyncMock(side_effect=Exception("LLM error"))

        result, metrics = await extraction_service.extract_entities(
            content_text="a" * 1000,
            content_type="youtube",
            title="Test",
        )

        # Should return empty result, not raise
        assert len(result.topics) == 0
        assert metrics.llm_skipped is False

    @pytest.mark.asyncio
    async def test_extract_entities_handles_invalid_json(self, extraction_service, mock_llm_provider):
        """Test graceful handling of invalid JSON response."""
        mock_llm_provider.generate = AsyncMock(return_value="This is not JSON")

        result, metrics = await extraction_service.extract_entities(
            content_text="a" * 1000,
            content_type="youtube",
            title="Test",
        )

        # Should return empty result, not raise
        assert len(result.topics) == 0
