"""LLM service for text generation using Ollama."""

import httpx

from menos.config import settings


class LLMService:
    """Service for generating text using Ollama models."""

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def generate(self, prompt: str, timeout: float = 120.0) -> str:
        """Generate text from a prompt.

        Args:
            prompt: The prompt to generate from
            timeout: Request timeout in seconds (default 120s for long generations)

        Returns:
            Generated text response
        """
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")


def get_llm_service() -> LLMService:
    """Get LLM service instance for dependency injection."""
    return LLMService(
        base_url=settings.ollama_url,
        model=settings.ollama_summary_model,
    )
