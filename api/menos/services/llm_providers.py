"""Cloud LLM provider implementations for OpenAI, Anthropic, and OpenRouter."""

import asyncio
from typing import Any

import httpx

from menos.services.llm import LLMProvider


class OpenAIProvider:
    """LLM provider implementation using OpenAI Chat Completions API.

    Uses the standard chat completions endpoint with exponential backoff retry logic.
    """

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        """Initialize OpenAI provider.

        Args:
            api_key: OpenAI API key
            model: Model identifier (e.g., gpt-4o-mini, gpt-4-turbo)
        """
        self.api_key = api_key
        self.model = model
        self.client: httpx.AsyncClient | None = None
        self.base_url = "https://api.openai.com/v1"

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy initialize HTTP client with auth headers."""
        if self.client is None:
            self.client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self.client

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float = 60.0,
    ) -> str:
        """Generate text using OpenAI Chat Completions API.

        Args:
            prompt: The user message/prompt
            system_prompt: Optional system message to guide generation
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0-2.0)
            timeout: Request timeout in seconds

        Returns:
            Generated text response

        Raises:
            RuntimeError: If generation fails after all retries
        """
        max_retries = 3
        base_delay = 1.0

        for attempt in range(max_retries):
            try:
                client = await self._get_client()

                messages: list[dict[str, str]] = []
                if system_prompt is not None:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})

                payload: dict[str, Any] = {
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }

                response = await client.post(
                    "/chat/completions",
                    json=payload,
                    timeout=timeout,
                )
                response.raise_for_status()
                data = response.json()

                return data["choices"][0]["message"]["content"]

            except httpx.HTTPError as e:
                if attempt == max_retries - 1:
                    raise RuntimeError(
                        f"OpenAI generation failed after {max_retries} retries: {e}"
                    ) from e

                delay = base_delay * (2**attempt)
                await asyncio.sleep(delay)

        return ""

    async def close(self) -> None:
        """Close the HTTP client and cleanup resources."""
        if self.client is not None:
            await self.client.aclose()
            self.client = None


class AnthropicProvider:
    """LLM provider implementation using Anthropic Messages API.

    Uses the Messages API with required anthropic-version header.
    """

    def __init__(self, api_key: str, model: str = "claude-3-5-haiku-20241022"):
        """Initialize Anthropic provider.

        Args:
            api_key: Anthropic API key
            model: Model identifier (e.g., claude-3-5-haiku-20241022, claude-3-5-sonnet-20241022)
        """
        self.api_key = api_key
        self.model = model
        self.client: httpx.AsyncClient | None = None
        self.base_url = "https://api.anthropic.com/v1"

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy initialize HTTP client with auth and version headers."""
        if self.client is None:
            self.client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
            )
        return self.client

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float = 60.0,
    ) -> str:
        """Generate text using Anthropic Messages API.

        Args:
            prompt: The user message/prompt
            system_prompt: Optional system prompt to guide generation
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0-2.0)
            timeout: Request timeout in seconds

        Returns:
            Generated text response

        Raises:
            RuntimeError: If generation fails after all retries
        """
        max_retries = 3
        base_delay = 1.0

        for attempt in range(max_retries):
            try:
                client = await self._get_client()

                payload: dict[str, Any] = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }

                if system_prompt is not None:
                    payload["system"] = system_prompt

                response = await client.post(
                    "/messages",
                    json=payload,
                    timeout=timeout,
                )
                response.raise_for_status()
                data = response.json()

                return data["content"][0]["text"]

            except httpx.HTTPError as e:
                if attempt == max_retries - 1:
                    raise RuntimeError(
                        f"Anthropic generation failed after {max_retries} retries: {e}"
                    ) from e

                delay = base_delay * (2**attempt)
                await asyncio.sleep(delay)

        return ""

    async def close(self) -> None:
        """Close the HTTP client and cleanup resources."""
        if self.client is not None:
            await self.client.aclose()
            self.client = None


class OpenRouterProvider:
    """LLM provider implementation using OpenRouter API.

    OpenRouter provides access to multiple LLM providers through an OpenAI-compatible API.
    Requires HTTP-Referer header for tracking.
    """

    def __init__(self, api_key: str, model: str = "openai/gpt-4o-mini"):
        """Initialize OpenRouter provider.

        Args:
            api_key: OpenRouter API key
            model: Model identifier in provider/model format (e.g., openai/gpt-4o-mini)
        """
        self.api_key = api_key
        self.model = model
        self.client: httpx.AsyncClient | None = None
        self.base_url = "https://openrouter.ai/api/v1"

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy initialize HTTP client with auth and referer headers."""
        if self.client is None:
            self.client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "HTTP-Referer": "menos",
                    "Content-Type": "application/json",
                },
            )
        return self.client

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float = 60.0,
    ) -> str:
        """Generate text using OpenRouter Chat Completions API.

        Args:
            prompt: The user message/prompt
            system_prompt: Optional system message to guide generation
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0-2.0)
            timeout: Request timeout in seconds

        Returns:
            Generated text response

        Raises:
            RuntimeError: If generation fails after all retries
        """
        max_retries = 3
        base_delay = 1.0

        for attempt in range(max_retries):
            try:
                client = await self._get_client()

                messages: list[dict[str, str]] = []
                if system_prompt is not None:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})

                payload: dict[str, Any] = {
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }

                response = await client.post(
                    "/chat/completions",
                    json=payload,
                    timeout=timeout,
                )
                response.raise_for_status()
                data = response.json()

                return data["choices"][0]["message"]["content"]

            except httpx.HTTPError as e:
                if attempt == max_retries - 1:
                    raise RuntimeError(
                        f"OpenRouter generation failed after {max_retries} retries: {e}"
                    ) from e

                delay = base_delay * (2**attempt)
                await asyncio.sleep(delay)

        return ""

    async def close(self) -> None:
        """Close the HTTP client and cleanup resources."""
        if self.client is not None:
            await self.client.aclose()
            self.client = None


class NoOpLLMProvider:
    """No-operation LLM provider for testing or disabling LLM features.

    Returns empty strings without making any network calls.
    """

    def __init__(self, api_key: str = "", model: str = "noop"):
        """Initialize NoOp provider.

        Args:
            api_key: Unused, accepted for interface compatibility
            model: Unused, accepted for interface compatibility
        """
        self.api_key = api_key
        self.model = model

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float = 60.0,
    ) -> str:
        """Return empty string without generating anything.

        Args:
            prompt: Ignored
            system_prompt: Ignored
            max_tokens: Ignored
            temperature: Ignored
            timeout: Ignored

        Returns:
            Empty string
        """
        return ""

    async def close(self) -> None:
        """No resources to cleanup."""
        pass


# Type assertions to ensure protocol compliance
_openai: LLMProvider = OpenAIProvider(api_key="test")
_anthropic: LLMProvider = AnthropicProvider(api_key="test")
_openrouter: LLMProvider = OpenRouterProvider(api_key="test")
_noop: LLMProvider = NoOpLLMProvider()
