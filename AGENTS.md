# AGENTS.md

This file provides guidance to AI coding assistants working with code in this repository.

## Project Overview

**Menos** is a self-hosted content vault with semantic search. Centralized storage for YouTube transcripts, markdown files, and structured data accessible from multiple machines.

**Status**: Phase 4 complete - YouTube ingestion and semantic search implemented.

**Stack**: Python 3.12+, FastAPI, SurrealDB, MinIO, Ollama, httpx, Pydantic

## Development Commands

```bash
cd api

# Install dependencies
uv sync

# Run tests
uv run pytest

# Run specific test file
uv run pytest tests/unit/test_youtube.py -v

# Lint and format
uv run ruff check menos/
uv run ruff format menos/

# Run locally (port 8000)
uv run uvicorn menos.main:app --reload

# Ingest YouTube videos (requires cookies for YouTube)
uv run python scripts/ingest_videos.py
```

## Architecture

```
api/menos/
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
│   ├── content.py       # Content CRUD
│   ├── search.py        # Semantic search
│   └── youtube.py       # YouTube ingestion
└── services/            # Business logic (no FastAPI dependencies)
    ├── storage.py       # MinIOStorage, SurrealDBRepository
    ├── embeddings.py    # Ollama embedding generation
    ├── chunking.py      # Text chunking for embeddings
    ├── youtube.py       # YouTube transcript fetching
    └── di.py            # Dependency injection helpers
```

### Key Design Patterns

1. **Service layer independence**: Services have no FastAPI dependencies - they handle business logic. Routers compose services and handle HTTP concerns.

2. **RFC 9421 authentication**: All protected endpoints verify ed25519 signatures. Uses `@method`, `@target-uri`, `content-digest` for request integrity.

3. **SurrealDB sync methods**: The surrealdb Python client uses synchronous methods (create, select, query) despite the async service layer.

4. **Storage separation**: MinIO for file content, SurrealDB for metadata and embeddings.

## Configuration

Environment variables (see `api/menos/config.py`):

| Variable | Description |
|----------|-------------|
| `SURREALDB_URL` | SurrealDB connection URL |
| `SURREALDB_NAMESPACE` | Database namespace |
| `SURREALDB_DATABASE` | Database name |
| `SURREALDB_USER` | Database username |
| `SURREALDB_PASSWORD` | Database password |
| `MINIO_ENDPOINT` | MinIO server endpoint |
| `MINIO_ACCESS_KEY` | MinIO access key |
| `MINIO_SECRET_KEY` | MinIO secret key |
| `MINIO_BUCKET` | MinIO bucket name |
| `MINIO_SECURE` | Use HTTPS for MinIO |
| `OLLAMA_URL` | Ollama API URL |
| `OLLAMA_MODEL` | Embedding model name |
| `AUTHORIZED_KEYS_PATH` | Path to authorized SSH keys |

## API Endpoints

All authenticated endpoints require RFC 9421 HTTP signature headers.

### Auth
- `GET /api/v1/auth/keys` - List authorized key IDs (public)
- `GET /api/v1/auth/whoami` - Verify authentication
- `POST /api/v1/auth/keys/reload` - Reload keys from disk

### Content
- `GET /api/v1/content` - List content
- `GET /api/v1/content/{id}` - Get content metadata
- `POST /api/v1/content` - Upload content
- `DELETE /api/v1/content/{id}` - Delete content

### Search
- `POST /api/v1/search` - Semantic vector search

### YouTube
- `POST /api/v1/youtube/ingest` - Ingest video by URL (fetches transcript server-side)
- `POST /api/v1/youtube/upload` - Upload pre-fetched transcript (for IP-blocked servers)
- `GET /api/v1/youtube/{video_id}` - Get video info
- `GET /api/v1/youtube` - List ingested videos

## Code Style

- Line length: 100 characters (ruff)
- Async service methods even when calling sync SurrealDB client
- Pydantic models for all API inputs/outputs
- Type hints throughout

## Testing

```bash
cd api

# All unit tests
uv run pytest tests/unit/ -v

# Specific test
uv run pytest tests/unit/test_storage.py -v
```

Tests use `MagicMock` for sync methods (SurrealDB, httpx response.json) and `AsyncMock` for async methods (httpx client.post).

## Deployment

Uses Ansible in a Docker container to deploy to remote server:

```bash
cd infra/ansible
docker compose run --rm ansible ansible-playbook -i inventory/hosts.yml playbooks/deploy.yml
```

Remote stack runs: SurrealDB, MinIO, Ollama, menos-api containers.
