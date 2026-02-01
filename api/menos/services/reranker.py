"""Reranker service for improving search result relevance."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from menos.services.llm import LLMProvider


@dataclass
class RankedDocument:
    """Result item from reranking operation.

    Attributes:
        text: Document content
        original_index: Index in the original document list
        score: Relevance score (higher is more relevant)
    """

    text: str
    original_index: int
    score: float


@runtime_checkable
class RerankerProvider(Protocol):
    """Protocol defining the interface for reranker providers."""

    async def rank(self, query: str, documents: list[str]) -> list[RankedDocument]:
        """Rank documents by relevance to query.

        Args:
            query: Search query
            documents: List of document texts to rank

        Returns:
            List of ranked documents, sorted by descending score
        """
        ...

    async def close(self) -> None:
        """Close and cleanup resources."""
        ...


RERANK_PROMPT = """Rank documents by relevance to the query.
Return JSON: {{"rankings": [{{"index": 0, "score": 0.9}}, ...]}}

Score between 0.0 (not relevant) and 1.0 (highly relevant).
Include ALL document indices.

Query: {query}

Documents:
{documents}

Return only the JSON, no other text."""


class RerankerLibraryProvider:
    """Reranker using the `rerankers` library.

    Singleton pattern ensures only one model instance is loaded.
    Uses ThreadPoolExecutor since the library is synchronous.
    """

    _instance: "RerankerLibraryProvider | None" = None
    _lock = asyncio.Lock()
    _executor: ThreadPoolExecutor | None = None
    _reranker = None

    def __new__(cls, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        """Singleton constructor - only one instance per model."""
        # Simple singleton for now - could be per-model if needed
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        """Initialize reranker with specified model.

        Args:
            model_name: Hugging Face model name for cross-encoder

        Raises:
            ImportError: If rerankers library is not installed
        """
        # Only initialize once
        if hasattr(self, "_initialized"):
            return

        self.model_name = model_name
        self._initialized = True

        # Lazy load the library
        try:
            from rerankers import Reranker

            self._Reranker = Reranker
        except ImportError as e:
            raise ImportError(
                "rerankers library not installed. Install with: pip install rerankers"
            ) from e

        # Model will be loaded on first use
        if RerankerLibraryProvider._executor is None:
            RerankerLibraryProvider._executor = ThreadPoolExecutor(max_workers=1)

    def _load_model(self):
        """Load the reranker model (runs in thread)."""
        if RerankerLibraryProvider._reranker is None:
            RerankerLibraryProvider._reranker = self._Reranker(self.model_name)
        return RerankerLibraryProvider._reranker

    def _rank_sync(self, query: str, documents: list[str]) -> list[RankedDocument]:
        """Synchronous ranking operation (runs in thread).

        Args:
            query: Search query
            documents: List of document texts

        Returns:
            List of ranked documents
        """
        reranker = self._load_model()
        results = reranker.rank(query=query, docs=documents)

        # Convert results to RankedDocument objects
        ranked = []
        for result in results.results:
            ranked.append(
                RankedDocument(
                    text=result.text,
                    original_index=result.doc_id,
                    score=result.score,
                )
            )

        return ranked

    async def rank(self, query: str, documents: list[str]) -> list[RankedDocument]:
        """Rank documents by relevance to query.

        Args:
            query: Search query
            documents: List of document texts to rank

        Returns:
            List of ranked documents, sorted by descending score
        """
        if not documents:
            return []

        # Run synchronous ranking in thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            RerankerLibraryProvider._executor,
            self._rank_sync,
            query,
            documents,
        )

    async def close(self) -> None:
        """Close and cleanup resources."""
        if RerankerLibraryProvider._executor is not None:
            RerankerLibraryProvider._executor.shutdown(wait=True)
            RerankerLibraryProvider._executor = None
            RerankerLibraryProvider._reranker = None


class LLMRerankerProvider:
    """Reranker using an LLM provider with a ranking prompt.

    Falls back to original order on parse errors.
    """

    def __init__(self, llm_provider: LLMProvider):
        """Initialize with an LLM provider.

        Args:
            llm_provider: LLM provider for generating rankings
        """
        self.llm_provider = llm_provider

    async def rank(self, query: str, documents: list[str]) -> list[RankedDocument]:
        """Rank documents using LLM-based scoring.

        Args:
            query: Search query
            documents: List of document texts to rank

        Returns:
            List of ranked documents, sorted by descending score.
            Falls back to original order (all scores=1.0) on parse errors.
        """
        if not documents:
            return []

        # Format documents for prompt
        doc_list = "\n".join(
            f"{i}. {doc[:200]}..." if len(doc) > 200 else f"{i}. {doc}"
            for i, doc in enumerate(documents)
        )

        prompt = RERANK_PROMPT.format(query=query, documents=doc_list)

        try:
            # Get LLM response
            response = await self.llm_provider.generate(
                prompt=prompt,
                temperature=0.0,  # Deterministic for ranking
                timeout=30.0,
            )

            # Parse JSON response
            # LLMs sometimes wrap JSON in markdown code blocks
            response = response.strip()
            if response.startswith("```"):
                # Extract JSON from markdown
                lines = response.split("\n")
                response = "\n".join(lines[1:-1]) if len(lines) > 2 else response

            data = json.loads(response)
            rankings = data.get("rankings", [])

            # Build ranked documents
            ranked = []
            for ranking in rankings:
                idx = ranking.get("index")
                score = ranking.get("score", 0.0)

                if idx is not None and 0 <= idx < len(documents):
                    ranked.append(
                        RankedDocument(
                            text=documents[idx],
                            original_index=idx,
                            score=float(score),
                        )
                    )

            # If we got valid rankings, return them
            if ranked:
                # Sort by score descending
                ranked.sort(key=lambda x: x.score, reverse=True)
                return ranked

        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            # Parse error - fall through to original order
            pass

        # Fallback: return original order
        return [
            RankedDocument(text=doc, original_index=i, score=1.0)
            for i, doc in enumerate(documents)
        ]

    async def close(self) -> None:
        """Close and cleanup resources."""
        await self.llm_provider.close()


class NoOpRerankerProvider:
    """No-op reranker that returns documents in original order.

    Useful for testing or disabling reranking.
    """

    async def rank(self, query: str, documents: list[str]) -> list[RankedDocument]:
        """Return documents in original order with score=1.0.

        Args:
            query: Search query (ignored)
            documents: List of document texts

        Returns:
            List of documents in original order, all with score=1.0
        """
        return [
            RankedDocument(text=doc, original_index=i, score=1.0)
            for i, doc in enumerate(documents)
        ]

    async def close(self) -> None:
        """No-op close."""
        pass
