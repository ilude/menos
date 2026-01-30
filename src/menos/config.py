"""Configuration settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    youtube_api_key: str = ""
    webshare_proxy_username: str = ""
    webshare_proxy_password: str = ""
    database_path: str = "/data/menos.db"

    @property
    def proxy_url(self) -> str | None:
        """Build proxy URL if credentials are set."""
        if self.webshare_proxy_username and self.webshare_proxy_password:
            return (
                f"http://{self.webshare_proxy_username}:"
                f"{self.webshare_proxy_password}@p.webshare.io:80"
            )
        return None

    class Config:
        env_file = ".env"


settings = Settings()
