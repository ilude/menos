# AGENTS.md

This file provides guidance to AI coding assistants working with code in this repository.

## Project Overview

**Menos** is a self-hosted content vault with semantic search. Centralized storage for YouTube transcripts, markdown files, and structured data accessible from multiple machines.

**Status**: Phase 5 complete - Agentic search with LLM-powered query expansion and synthesis.

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
api/
├── migrations/              # Database migrations (SurrealQL)
│   ├── 20260201-100000_initial_schema.surql
│   └── 20260201-100100_add_indexes.surql
├── scripts/
│   └── migrate.py           # Migration CLI tool
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
    │   ├── content.py       # Content CRUD
    │   ├── search.py        # Semantic search
    │   └── youtube.py       # YouTube ingestion
    └── services/            # Business logic (no FastAPI dependencies)
        ├── storage.py       # MinIOStorage, SurrealDBRepository
        ├── embeddings.py    # Ollama embedding generation
        ├── chunking.py      # Text chunking for embeddings
        ├── youtube.py       # YouTube transcript fetching
        ├── llm.py           # LLMProvider protocol, OllamaLLMProvider
        ├── llm_providers.py # OpenAI, Anthropic, OpenRouter providers
        ├── reranker.py      # RerankerProvider protocol and implementations
        ├── agent.py         # AgentService (3-stage agentic search)
        ├── migrator.py      # Database migration service
        └── di.py            # Dependency injection helpers
```

### Key Design Patterns

1. **Service layer independence**: Services have no FastAPI dependencies - they handle business logic. Routers compose services and handle HTTP concerns.

2. **RFC 9421 authentication**: All protected endpoints verify ed25519 signatures. Uses `@method`, `@target-uri`, `content-digest` for request integrity.

3. **SurrealDB sync methods**: The surrealdb Python client uses synchronous methods (create, select, query) despite the async service layer.

4. **Storage separation**: MinIO for file content, SurrealDB for metadata and embeddings.

5. **Agentic search pipeline**: 3-stage search with LLM providers:
   - Query expansion: LLM generates multiple search queries
   - Retrieval: Multi-query vector search with RRF (Reciprocal Rank Fusion)
   - Synthesis: LLM generates answer with citations from retrieved results

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
| `AGENT_EXPANSION_PROVIDER` | LLM for query expansion (ollama/openai/anthropic/openrouter/none) |
| `AGENT_EXPANSION_MODEL` | Model name for expansion |
| `AGENT_SYNTHESIS_PROVIDER` | LLM for synthesis (ollama/openai/anthropic/openrouter/none) |
| `AGENT_SYNTHESIS_MODEL` | Model name for synthesis |
| `AGENT_RERANK_PROVIDER` | Reranker (rerankers/llm/none) |
| `AGENT_RERANK_MODEL` | Cross-encoder model for reranking |
| `OPENAI_API_KEY` | OpenAI API key (optional) |
| `ANTHROPIC_API_KEY` | Anthropic API key (optional) |
| `OPENROUTER_API_KEY` | OpenRouter API key (optional) |

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
- `POST /api/v1/search/agentic` - Agentic search (query expansion → RRF → rerank → synthesis)

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

## Smoke Tests

Smoke tests verify a live deployment works correctly.

```bash
cd api

# Run all smoke tests
uv run pytest tests/smoke/ -m smoke -v

# Or use the CLI runner
uv run python scripts/smoke_test.py --url http://api.example.com -v
```

Tests cover:
- `/health` and `/ready` endpoints
- Auth key listing and verification
- Vector search endpoint
- Agentic search endpoint (with timing validation)

Environment variables:
| Variable | Description |
|----------|-------------|
| `SMOKE_TEST_URL` | Target API URL |
| `SMOKE_TEST_KEY_FILE` | SSH private key for auth |

## Database Migrations

Menos uses a custom migration system for SurrealDB schema changes. See [ADR-001](docs/adr/001-database-migrations.md) for design rationale.

### Migration Files

Migrations are versioned `.surql` files in `api/migrations/`:

```
api/migrations/
├── 20260201-100000_initial_schema.surql
├── 20260201-100100_add_indexes.surql
└── ...
```

**Naming convention**: `YYYYMMDD-HHMMSS_description.surql`

### Commands

```bash
cd api

# Check migration status
uv run python scripts/migrate.py status

# Apply pending migrations
uv run python scripts/migrate.py up

# Create new migration file
uv run python scripts/migrate.py create add_user_preferences
```

### How It Works

1. Migrations are tracked in a `_migrations` table in SurrealDB
2. Each migration runs once and is recorded with its timestamp
3. Migrations execute in filename order (timestamp ensures correct sequence)
4. All migrations use `IF NOT EXISTS` for idempotency

### Writing Migrations

```sql
-- Migration: add_feature_flags
-- Always use IF NOT EXISTS for safety

DEFINE TABLE IF NOT EXISTS feature_flag SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS name ON feature_flag TYPE string;
DEFINE FIELD IF NOT EXISTS enabled ON feature_flag TYPE bool DEFAULT false;
DEFINE INDEX IF NOT EXISTS idx_feature_flag_name ON feature_flag FIELDS name UNIQUE;
```

## Deployment

Uses Ansible in a Docker container to deploy to remote server:

```bash
cd infra/ansible
docker compose run --rm ansible ansible-playbook -i inventory/hosts.yml playbooks/deploy.yml
```

Remote stack runs: SurrealDB, MinIO, Ollama, menos-api containers.

### Deployment Flow

1. **Ansible deploys** → copies files, rebuilds containers
2. **Container restarts** → menos-api starts
3. **Migrations run automatically** → on app startup via lifespan handler
4. **App serves traffic** → migrations logged, failures don't crash app

### Testing Migrations

To test migration system changes:

1. Make changes locally, commit and push
2. Deploy via Ansible (or manually sync files + rebuild)
3. Check logs: `docker compose logs menos-api`
4. Verify: `docker exec menos-api python -c "from menos.services.migrator import MigrationService; ..."`

**Note**: Vector indexes use `CONCURRENTLY` to build in the background without transaction conflicts. Monitor progress with:
```sql
INFO FOR INDEX idx_chunk_embedding ON chunk;
-- Returns: {"building":{"initial":N,"pending":0,"status":"indexing"}} or {"status":"ready"}

### Manual Deployment (without Ansible)

If Ansible isn't available, sync files directly:

```bash
# Copy updated files
scp -r api/menos/ user@server:/apps/menos/api/
scp -r api/migrations/ user@server:/apps/menos/api/

# Rebuild and restart
ssh user@server "cd /apps/menos && docker compose build menos-api && docker compose up -d menos-api"

# Check logs
ssh user@server "docker compose -f /apps/menos/docker-compose.yml logs --tail=50 menos-api"
```
