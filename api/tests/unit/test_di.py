"""Unit tests for unified pipeline DI wiring."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from menos.services.llm import LLMProvider


class TestGetUnifiedPipelineProvider:
    """Tests for get_unified_pipeline_provider factory."""

    def setup_method(self):
        """Clear lru_cache between tests."""
        from menos.services.di import get_unified_pipeline_provider

        get_unified_pipeline_provider.cache_clear()

    def test_returns_noop_for_none_provider(self):
        """Provider type 'none' returns NoOpLLMProvider."""
        from menos.services.di import get_unified_pipeline_provider

        mock_settings = MagicMock()
        mock_settings.unified_pipeline_provider = "none"
        mock_settings.unified_pipeline_model = ""

        with patch("menos.services.di.settings", mock_settings):
            provider = get_unified_pipeline_provider()

        assert isinstance(provider, LLMProvider)

    def test_returns_ollama_provider(self):
        """Provider type 'ollama' returns OllamaLLMProvider."""
        from menos.services.di import get_unified_pipeline_provider

        mock_settings = MagicMock()
        mock_settings.unified_pipeline_provider = "ollama"
        mock_settings.unified_pipeline_model = "test-model"
        mock_settings.ollama_url = "http://localhost:11434"

        with patch("menos.services.di.settings", mock_settings):
            provider = get_unified_pipeline_provider()

        assert isinstance(provider, LLMProvider)

    def test_raises_for_unknown_provider(self):
        """Unknown provider type raises ValueError."""
        from menos.services.di import get_unified_pipeline_provider

        mock_settings = MagicMock()
        mock_settings.unified_pipeline_provider = "invalid"
        mock_settings.unified_pipeline_model = ""

        with patch("menos.services.di.settings", mock_settings):
            with pytest.raises(ValueError, match="Unknown unified pipeline provider"):
                get_unified_pipeline_provider()

    def test_openrouter_requires_api_key(self):
        """OpenRouter provider uses build_openrouter_chain."""
        from menos.services.di import get_unified_pipeline_provider

        mock_settings = MagicMock()
        mock_settings.unified_pipeline_provider = "openrouter"
        mock_settings.unified_pipeline_model = "test-model"
        mock_settings.openrouter_api_key = "test-key"

        with patch("menos.services.di.settings", mock_settings):
            provider = get_unified_pipeline_provider()

        assert isinstance(provider, LLMProvider)


class TestGetUnifiedPipelineService:
    """Tests for get_unified_pipeline_service factory."""

    def setup_method(self):
        """Clear lru_cache between tests."""
        from menos.services.di import get_unified_pipeline_provider

        get_unified_pipeline_provider.cache_clear()

    @pytest.mark.asyncio
    async def test_returns_unified_pipeline_service(self):
        """Factory returns a UnifiedPipelineService instance."""
        from menos.services.di import get_unified_pipeline_service
        from menos.services.unified_pipeline import UnifiedPipelineService

        mock_settings = MagicMock()
        mock_settings.unified_pipeline_provider = "none"
        mock_settings.unified_pipeline_model = ""

        mock_repo = MagicMock()
        mock_repo.connect = AsyncMock()

        with (
            patch("menos.services.di.settings", mock_settings),
            patch("menos.services.di.get_surreal_repo", AsyncMock(return_value=mock_repo)),
        ):
            service = await get_unified_pipeline_service()

        assert isinstance(service, UnifiedPipelineService)
