# Architecture

## Project Overview

**Menos** is a self-hosted content vault with semantic search. Centralized storage for YouTube transcripts, markdown files, and structured data accessible from multiple machines.

**Stack**: Python 3.12+, FastAPI, SurrealDB, MinIO, Ollama, httpx, Pydantic

## Directory Structure

```
api/
├── migrations/              # Database migrations (SurrealQL)
├── scripts/
│   ├── migrate.py           # Migration CLI tool
│   ├── query.py             # Read-only SurrealQL queries
│   ├── ingest_videos.py     # YouTube batch ingestion
│   ├── refetch_metadata.py  # Re-fetch YouTube metadata
│   ├── fetch_channel_videos.py  # Fetch channel videos to CSV
│   ├── list_videos.py       # List YouTube videos from SurrealDB
│   ├── search_videos.py     # Semantic search CLI
│   ├── delete_video.py      # Delete a video with confirmation
│   ├── filter_description_urls.py  # Classify description URLs
│   └── url_filter_status.py # URL filter statistics
└── menos/
    ├── main.py              # FastAPI app entry point
    ├── config.py            # Pydantic Settings (env-based configuration)
    ├── models.py            # Pydantic models for content and chunks
    ├── auth/                # RFC 9421 HTTP signature authentication
    │   ├── dependencies.py  # FastAPI auth dependencies
    │   ├── keys.py          # Public key store
    │   └── verifier.py      # Signature verification
    ├── client/              # Client-side request signing
    │   └── signer.py        # Sign requests with ed25519 keys
    ├── routers/             # FastAPI route handlers
    │   ├── auth.py          # Auth endpoints
    │   ├── content.py       # Content CRUD, tags, links/backlinks
    │   ├── graph.py         # Knowledge graph visualization
    │   ├── health.py        # Health check (returns git SHA)
    │   ├── search.py        # Semantic search
    │   └── youtube.py       # YouTube ingestion
    └── services/            # Business logic (no FastAPI dependencies)
        ├── storage.py       # MinIOStorage, SurrealDBRepository
        ├── embeddings.py    # Ollama embedding generation
        ├── chunking.py      # Text chunking for embeddings
        ├── youtube.py       # YouTube transcript fetching
        ├── frontmatter.py   # YAML frontmatter parsing
        ├── linking.py       # Wiki-link and markdown link extraction
        ├── llm.py           # LLMProvider protocol, OllamaLLMProvider
        ├── llm_providers.py # OpenAI, Anthropic, OpenRouter providers
        ├── reranker.py      # RerankerProvider protocol and implementations
        ├── agent.py         # AgentService (3-stage agentic search)
        ├── migrator.py      # Database migration service
        ├── url_filter.py    # Heuristic URL classification
        └── di.py            # Dependency injection helpers
```

## Key Design Patterns

1. **Service layer independence**: Services have no FastAPI dependencies — they handle business logic. Routers compose services and handle HTTP concerns.

2. **RFC 9421 authentication**: All protected endpoints verify ed25519 signatures. Uses `@method`, `@target-uri`, `content-digest` for request integrity.

3. **SurrealDB sync methods**: The surrealdb Python client uses synchronous methods (create, select, query) despite the async service layer.

4. **Storage separation**: MinIO for file content, SurrealDB for metadata and embeddings.

5. **Agentic search pipeline**: 3-stage search with LLM providers:
   - Query expansion: LLM generates multiple search queries
   - Retrieval: Multi-query vector search with RRF (Reciprocal Rank Fusion)
   - Synthesis: LLM generates answer with citations from retrieved results

## Code Style

- Line length: 100 characters (ruff)
- Async service methods even when calling sync SurrealDB client
- Pydantic models for all API inputs/outputs
- Type hints throughout
