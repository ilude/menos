# AGENTS.md

This file provides guidance to AI coding assistants working with code in this repository.

## Project Overview

**Menos** is a YouTube transcript store service. Centralized storage for YouTube video transcripts and metadata, accessible from multiple machines.

**Status**: MVP/Proof of concept - Core scaffolding complete, not yet tested.

**Stack**: Python 3.11+, FastAPI, SQLite with FTS5, httpx, Pydantic

## Development Commands

```bash
# Install dependencies
uv sync

# Run locally (port 8000)
uv run uvicorn menos.main:app --reload

# Run tests
uv run pytest

# Lint and format
uv run ruff check src/
uv run ruff format src/

# Docker (port 8420)
docker compose up -d
docker compose logs -f
docker compose down
```

## Architecture

```
src/menos/
├── main.py              # FastAPI app + lifespan context manager
├── config.py            # Pydantic Settings (env-based configuration)
├── models.py            # Request/response Pydantic models
├── database.py          # SQLite operations + FTS5 full-text search
├── fetchers/            # Service layer (NO FastAPI dependencies)
│   ├── transcript.py    # YouTube Transcript API with proxy support
│   └── metadata.py      # YouTube Data API v3
└── routers/             # FastAPI route handlers
    ├── videos.py        # CRUD endpoints
    └── search.py        # Full-text search endpoint
```

### Key Design Patterns

1. **Service layer independence**: Fetchers have no FastAPI dependencies - pure functions that return data or None on error. Routers compose services and handle HTTP concerns.

2. **Graceful degradation**: Services return `None` on error rather than raising. Routers translate to appropriate HTTP status codes.

3. **Full async**: All I/O uses async/await (httpx, aiosqlite).

4. **FTS5 auto-sync**: Database triggers keep full-text search index synchronized with main table.

## Configuration

Environment variables (see `.env.example`):
- `YOUTUBE_API_KEY` - YouTube Data API key
- `WEBSHARE_PROXY_USERNAME` / `WEBSHARE_PROXY_PASSWORD` - Proxy for transcripts
- `DATABASE_PATH` - SQLite location (default: `/data/menos.db`)

## API Endpoints

All prefixed with `/api/v1/`:
- `POST /videos/{id}` - Fetch and store from YouTube
- `GET /videos/{id}` - Get stored video
- `GET /videos/{id}/transcript` - Transcript only
- `PUT /videos/{id}/summary` - Store client-generated summary
- `DELETE /videos/{id}` - Remove video
- `GET /videos` - List videos (filter: `?channel=`)
- `GET /search?q=` - Full-text search with BM25 ranking
- `GET /health` - Health check

## Code Style

- Line length: 100 characters (ruff)
- Async first for all I/O
- Pydantic models for all API inputs/outputs
- Services return `None` on error; routers raise `HTTPException`

## Future Patterns (from REFERENCE.md)

When the project matures, adopt from agent-spike:
- Multi-stage Docker build
- Service classes with dependency injection
- Correlation ID middleware
- Makefile targets
- Comprehensive test fixtures
