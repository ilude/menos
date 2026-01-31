"""Configuration settings."""

from pathlib import Path

from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    model_config = ConfigDict(env_file=".env")

    # SurrealDB
    surrealdb_url: str = "http://localhost:8000"
    surrealdb_user: str = "root"
    surrealdb_password: str = "root"
    surrealdb_namespace: str = "menos"
    surrealdb_database: str = "menos"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minio"
    minio_secret_key: str = "minio123"
    minio_secure: bool = False
    minio_bucket: str = "menos"

    # Ollama
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "mxbai-embed-large"

    # Auth
    ssh_public_keys_path: Path = Path("/keys")

    # Webshare Proxy (for YouTube)
    webshare_proxy_username: str | None = None
    webshare_proxy_password: str | None = None


settings = Settings()
