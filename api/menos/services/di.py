"""Dependency injection container for services."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import lru_cache

from minio import Minio
from surrealdb import Surreal

from menos.config import settings
from menos.services.agent import AgentService
from menos.services.embeddings import get_embedding_service
from menos.services.llm import LLMProvider, OllamaLLMProvider
from menos.services.llm_providers import (
    AnthropicProvider,
    FallbackProvider,
    NoOpLLMProvider,
    OpenAIProvider,
    OpenRouterProvider,
)
from menos.services.reranker import (
    LLMRerankerProvider,
    NoOpRerankerProvider,
    RerankerLibraryProvider,
    RerankerProvider,
)
from menos.services.storage import MinIOStorage, SurrealDBRepository


@asynccontextmanager
async def get_storage_context() -> AsyncGenerator[tuple[MinIOStorage, SurrealDBRepository], None]:
    """Create and manage storage service instances.

    Yields:
        Tuple of (MinIOStorage, SurrealDBRepository)
    """
    # Initialize MinIO
    minio_client = Minio(
        settings.minio_url,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    minio_storage = MinIOStorage(minio_client, settings.minio_bucket)

    # Initialize SurrealDB (blocking HTTP client needs http:// not ws://)
    surreal_url = settings.surrealdb_url.replace("ws://", "http://").replace("wss://", "https://")
    db = Surreal(surreal_url)
    surreal_repo = SurrealDBRepository(
        db,
        settings.surrealdb_namespace,
        settings.surrealdb_database,
        settings.surrealdb_user,
        settings.surrealdb_password,
    )

    try:
        await surreal_repo.connect()
        yield minio_storage, surreal_repo
    finally:
        # SurrealDB blocking HTTP client doesn't implement close()
        pass


async def get_minio_storage() -> MinIOStorage:
    """Get MinIO storage instance for dependency injection."""
    minio_client = Minio(
        settings.minio_url,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    return MinIOStorage(minio_client, settings.minio_bucket)


async def get_surreal_repo() -> SurrealDBRepository:
    """Get SurrealDB repository instance for dependency injection."""
    surreal_url = settings.surrealdb_url.replace("ws://", "http://").replace("wss://", "https://")
    db = Surreal(surreal_url)
    repo = SurrealDBRepository(
        db,
        settings.surrealdb_namespace,
        settings.surrealdb_database,
        settings.surrealdb_user,
        settings.surrealdb_password,
    )
    await repo.connect()
    return repo


def build_openrouter_chain(model: str = "") -> LLMProvider:
    """Build an OpenRouter provider with fallback chain.

    If model is specified, returns a plain OpenRouterProvider for that model.
    If model is empty, returns a FallbackProvider with pony-alpha as primary,
    then aurora-alpha, GPT-OSS 120B, DeepSeek R1, then Gemma 3 27B.

    Args:
        model: Specific model to use, or empty for fallback chain

    Returns:
        LLMProvider instance (single or fallback chain)
    """
    key = settings.openrouter_api_key
    if not key:
        raise ValueError("openrouter_api_key must be set for openrouter provider")

    if model:
        return OpenRouterProvider(key, model)

    chain = [
        ("pony", OpenRouterProvider(key, "openrouter/pony-alpha")),
        ("aurora", OpenRouterProvider(key, "openrouter/aurora-alpha")),
        ("gpt-oss", OpenRouterProvider(key, "openai/gpt-oss-120b:free")),
        ("deepseek", OpenRouterProvider(key, "deepseek/deepseek-r1-0528:free")),
        ("gemma3", OpenRouterProvider(key, "google/gemma-3-27b-it:free")),
    ]
    return FallbackProvider(chain)


@lru_cache(maxsize=1)
def get_expansion_provider() -> LLMProvider:
    """Get singleton expansion LLM provider based on settings.

    Returns the appropriate LLM provider instance for query expansion:
    - "ollama" -> OllamaLLMProvider
    - "openai" -> OpenAIProvider
    - "anthropic" -> AnthropicProvider
    - "openrouter" -> OpenRouterProvider
    - "none" -> NoOpLLMProvider

    Returns:
        LLMProvider instance configured for expansion
    """
    provider_type = settings.agent_expansion_provider
    model = settings.agent_expansion_model

    if provider_type == "ollama":
        return OllamaLLMProvider(settings.ollama_url, model)
    elif provider_type == "openai":
        if not settings.openai_api_key:
            raise ValueError("openai_api_key must be set when using openai expansion provider")
        return OpenAIProvider(settings.openai_api_key, model)
    elif provider_type == "anthropic":
        if not settings.anthropic_api_key:
            msg = "anthropic_api_key must be set for anthropic expansion provider"
            raise ValueError(msg)
        return AnthropicProvider(settings.anthropic_api_key, model)
    elif provider_type == "openrouter":
        return build_openrouter_chain(model)
    elif provider_type == "none":
        return NoOpLLMProvider()
    else:
        raise ValueError(f"Unknown expansion provider: {provider_type}")


@lru_cache(maxsize=1)
def get_synthesis_provider() -> LLMProvider:
    """Get singleton synthesis LLM provider based on settings.

    Returns the appropriate LLM provider instance for result synthesis:
    - "ollama" -> OllamaLLMProvider
    - "openai" -> OpenAIProvider
    - "anthropic" -> AnthropicProvider
    - "openrouter" -> OpenRouterProvider
    - "none" -> NoOpLLMProvider

    Returns:
        LLMProvider instance configured for synthesis
    """
    provider_type = settings.agent_synthesis_provider
    model = settings.agent_synthesis_model

    if provider_type == "ollama":
        return OllamaLLMProvider(settings.ollama_url, model)
    elif provider_type == "openai":
        if not settings.openai_api_key:
            msg = "openai_api_key must be set for openai synthesis provider"
            raise ValueError(msg)
        return OpenAIProvider(settings.openai_api_key, model)
    elif provider_type == "anthropic":
        if not settings.anthropic_api_key:
            msg = "anthropic_api_key must be set for anthropic synthesis provider"
            raise ValueError(msg)
        return AnthropicProvider(settings.anthropic_api_key, model)
    elif provider_type == "openrouter":
        return build_openrouter_chain(model)
    elif provider_type == "none":
        return NoOpLLMProvider()
    else:
        raise ValueError(f"Unknown synthesis provider: {provider_type}")


@lru_cache(maxsize=1)
def get_reranker() -> RerankerProvider:
    """Get singleton reranker provider based on settings.

    Returns the appropriate reranker provider instance:
    - "rerankers" -> RerankerLibraryProvider
    - "llm" -> LLMRerankerProvider using synthesis provider
    - "none" -> NoOpRerankerProvider

    Returns:
        RerankerProvider instance configured for reranking
    """
    provider_type = settings.agent_rerank_provider
    model = settings.agent_rerank_model

    if provider_type == "rerankers":
        return RerankerLibraryProvider(model)
    elif provider_type == "llm":
        synthesis_provider = get_synthesis_provider()
        return LLMRerankerProvider(synthesis_provider)
    elif provider_type == "none":
        return NoOpRerankerProvider()
    else:
        raise ValueError(f"Unknown reranker provider: {provider_type}")


@lru_cache(maxsize=1)
def get_entity_extraction_provider() -> LLMProvider:
    """Get singleton entity extraction LLM provider based on settings.

    Returns:
        LLMProvider instance configured for entity extraction
    """
    provider_type = settings.entity_extraction_provider
    model = settings.entity_extraction_model

    if provider_type == "ollama":
        return OllamaLLMProvider(settings.ollama_url, model)
    elif provider_type == "openai":
        if not settings.openai_api_key:
            raise ValueError("openai_api_key must be set for openai entity extraction provider")
        return OpenAIProvider(settings.openai_api_key, model)
    elif provider_type == "anthropic":
        if not settings.anthropic_api_key:
            msg = "anthropic_api_key must be set for anthropic entity extraction provider"
            raise ValueError(msg)
        return AnthropicProvider(settings.anthropic_api_key, model)
    elif provider_type == "openrouter":
        return build_openrouter_chain(model)
    elif provider_type == "none":
        return NoOpLLMProvider()
    else:
        raise ValueError(f"Unknown entity extraction provider: {provider_type}")


@lru_cache(maxsize=1)
def get_classification_provider() -> LLMProvider:
    """Get singleton classification LLM provider based on settings.

    Returns:
        LLMProvider instance configured for classification
    """
    provider_type = settings.classification_provider
    model = settings.classification_model

    if provider_type == "ollama":
        return OllamaLLMProvider(settings.ollama_url, model)
    elif provider_type == "openai":
        if not settings.openai_api_key:
            raise ValueError("openai_api_key must be set for openai classification provider")
        return OpenAIProvider(settings.openai_api_key, model)
    elif provider_type == "anthropic":
        if not settings.anthropic_api_key:
            msg = "anthropic_api_key must be set for anthropic classification provider"
            raise ValueError(msg)
        return AnthropicProvider(settings.anthropic_api_key, model)
    elif provider_type == "openrouter":
        return build_openrouter_chain(model)
    elif provider_type == "none":
        return NoOpLLMProvider()
    else:
        raise ValueError(f"Unknown classification provider: {provider_type}")


async def get_classification_service():
    """Get ClassificationService instance for dependency injection."""
    from menos.services.classification import ClassificationService, VaultInterestProvider

    provider = get_classification_provider()
    repo = await get_surreal_repo()
    interest_provider = VaultInterestProvider(
        repo=repo,
        top_n=settings.classification_interest_top_n,
    )
    return ClassificationService(
        llm_provider=provider,
        interest_provider=interest_provider,
        repo=repo,
        settings=settings,
    )


async def get_entity_resolution_service():
    """Get EntityResolutionService instance for dependency injection."""
    from menos.services.entity_extraction import EntityExtractionService
    from menos.services.entity_resolution import EntityResolutionService
    from menos.services.keyword_matcher import EntityKeywordMatcher
    from menos.services.sponsored_filter import SponsoredFilter
    from menos.services.url_detector import URLDetector

    llm_provider = get_entity_extraction_provider()
    repo = await get_surreal_repo()
    extraction_service = EntityExtractionService(
        llm_provider=llm_provider,
        settings=settings,
    )
    keyword_matcher = EntityKeywordMatcher()
    url_detector = URLDetector()
    sponsored_filter = SponsoredFilter()

    return EntityResolutionService(
        repository=repo,
        extraction_service=extraction_service,
        keyword_matcher=keyword_matcher,
        settings=settings,
        url_detector=url_detector,
        sponsored_filter=sponsored_filter,
    )


async def get_agent_service() -> AgentService:
    """Get AgentService instance for dependency injection.

    Constructs AgentService with all required dependencies:
    - expansion_provider from get_expansion_provider()
    - synthesis_provider from get_synthesis_provider()
    - reranker from get_reranker()
    - embedding_service from get_embedding_service()
    - surreal_repo from get_surreal_repo()

    Returns:
        Configured AgentService instance
    """
    expansion_provider = get_expansion_provider()
    synthesis_provider = get_synthesis_provider()
    reranker = get_reranker()
    embedding_service = get_embedding_service()
    surreal_repo = await get_surreal_repo()

    return AgentService(
        expansion_provider=expansion_provider,
        reranker=reranker,
        synthesis_provider=synthesis_provider,
        embedding_service=embedding_service,
        surreal_repo=surreal_repo,
    )


@lru_cache(maxsize=1)
def get_unified_pipeline_provider() -> LLMProvider:
    """Get singleton unified pipeline LLM provider based on settings.

    Returns:
        LLMProvider instance configured for unified pipeline
    """
    provider_type = settings.unified_pipeline_provider
    model = settings.unified_pipeline_model

    if provider_type == "ollama":
        return OllamaLLMProvider(settings.ollama_url, model)
    elif provider_type == "openai":
        if not settings.openai_api_key:
            raise ValueError("openai_api_key must be set for openai unified pipeline provider")
        return OpenAIProvider(settings.openai_api_key, model)
    elif provider_type == "anthropic":
        if not settings.anthropic_api_key:
            msg = "anthropic_api_key must be set for anthropic unified pipeline provider"
            raise ValueError(msg)
        return AnthropicProvider(settings.anthropic_api_key, model)
    elif provider_type == "openrouter":
        return build_openrouter_chain(model)
    elif provider_type == "none":
        return NoOpLLMProvider()
    else:
        raise ValueError(f"Unknown unified pipeline provider: {provider_type}")


async def get_unified_pipeline_service():
    """Get UnifiedPipelineService instance for dependency injection."""
    from menos.services.unified_pipeline import UnifiedPipelineService

    provider = get_unified_pipeline_provider()
    repo = await get_surreal_repo()
    return UnifiedPipelineService(
        llm_provider=provider,
        repo=repo,
        settings=settings,
    )
