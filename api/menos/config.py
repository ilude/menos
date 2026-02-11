"""Configuration settings."""

from pathlib import Path
from typing import Literal

from pydantic import ConfigDict
from pydantic_settings import BaseSettings

# Type aliases for agent configuration
LLMProviderType = Literal["ollama", "openai", "anthropic", "openrouter", "none"]
RerankerProviderType = Literal["rerankers", "llm", "none"]


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    model_config = ConfigDict(
        env_file=[".env", "../.env"],
        extra="ignore",
    )

    # Menos API (for client scripts)
    api_base_url: str = "http://localhost:8000"

    # SurrealDB
    surrealdb_url: str = "http://localhost:8000"
    surrealdb_user: str = "root"
    surrealdb_password: str = "root"
    surrealdb_namespace: str = "menos"
    surrealdb_database: str = "menos"

    # MinIO
    minio_url: str = "localhost:9000"
    minio_access_key: str = "minio"
    minio_secret_key: str = "minio123"
    minio_secure: bool = False
    minio_bucket: str = "menos"

    # Ollama (embeddings only)
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "mxbai-embed-large"

    # Auth
    ssh_public_keys_path: Path = Path("/keys")

    # Webshare Proxy (required for YouTube transcript fetching)
    webshare_proxy_username: str
    webshare_proxy_password: str

    # YouTube Data API
    youtube_api_key: str | None = None

    # Agent settings
    agent_expansion_provider: LLMProviderType = "openrouter"
    agent_expansion_model: str = ""
    agent_rerank_provider: RerankerProviderType = "none"
    agent_rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-12-v2"
    agent_synthesis_provider: LLMProviderType = "openrouter"
    agent_synthesis_model: str = ""

    # Cloud LLM API keys
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    openrouter_api_key: str | None = None

    # Entity Extraction
    entity_extraction_enabled: bool = True
    entity_extraction_provider: LLMProviderType = "openrouter"
    entity_extraction_model: str = ""

    # Content Classification
    classification_enabled: bool = True
    classification_provider: LLMProviderType = "openrouter"
    classification_model: str = ""
    classification_max_new_labels: int = 3
    classification_interest_top_n: int = 15
    classification_min_content_length: int = 500

    # API Keys for Metadata Fetching (optional)
    semantic_scholar_api_key: str | None = None

    # Extraction Limits
    entity_max_topics_per_content: int = 7
    entity_min_confidence: float = 0.6
    entity_fetch_external_metadata: bool = True


settings = Settings()


def get_settings() -> Settings:
    """Get application settings (for dependency injection)."""
    return settings
