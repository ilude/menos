# Menos

YouTube transcript store service. Centralized storage for YouTube video transcripts and metadata, accessible from multiple machines.

## Status

**MVP / Proof of Concept** - Core scaffolding complete, not yet tested.

## Features

- Fetch and store YouTube transcripts (via youtube-transcript-api with Webshare proxy)
- Fetch and store video metadata (via YouTube Data API)
- Full-text search across all transcripts (SQLite FTS5)
- REST API for remote access
- Client-side summary generation (keeps API keys centralized on server)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              Menos Service (Docker)                          │
│                                                              │
│  FastAPI + SQLite + FTS5                                    │
│                                                              │
│  POST /api/v1/videos/{id}     → fetch & store               │
│  GET  /api/v1/videos/{id}     → retrieve                    │
│  GET  /api/v1/videos          → list with filters           │
│  GET  /api/v1/search?q=       → full-text search            │
│  PUT  /api/v1/videos/{id}/summary → store summary           │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Docker & Docker Compose
- YouTube Data API key
- Webshare proxy credentials (for transcript fetching)

### Run with Docker

```bash
# Copy and edit environment
cp .env.example .env
# Edit .env with your API keys

# Start service
docker compose up -d

# Test
curl http://localhost:8420/health
```

### Development

```bash
# Install dependencies
uv sync

# Run locally
uv run uvicorn menos.main:app --reload

# Run tests
uv run pytest
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/videos/{video_id}` | Fetch and store video |
| GET | `/api/v1/videos/{video_id}` | Get video details |
| GET | `/api/v1/videos/{video_id}/transcript` | Get transcript only |
| PUT | `/api/v1/videos/{video_id}/summary` | Store client-generated summary |
| DELETE | `/api/v1/videos/{video_id}` | Delete video |
| GET | `/api/v1/videos` | List videos (optional: `?channel=`) |
| GET | `/api/v1/search?q=` | Full-text search |
| GET | `/health` | Health check |

## Client Usage

The `/yt` command in Claude Code can be updated to use this service:

```python
# Instead of local fetching:
response = httpx.post(f"{MENOS_URL}/api/v1/videos/{video_id}")
video = response.json()

# Summary generated client-side, then stored:
httpx.put(f"{MENOS_URL}/api/v1/videos/{video_id}/summary", json={"summary": summary})
```

## Configuration

| Variable | Description |
|----------|-------------|
| `YOUTUBE_API_KEY` | YouTube Data API key |
| `WEBSHARE_PROXY_USERNAME` | Webshare proxy username |
| `WEBSHARE_PROXY_PASSWORD` | Webshare proxy password |
| `DATABASE_PATH` | SQLite database path (default: `/data/menos.db`) |

## Future Enhancements

- [ ] Authentication (API key or mTLS)
- [ ] Semantic search (mgrep or local embeddings)
- [ ] Batch import from existing `/yt` logs
- [ ] Channel subscriptions / auto-fetch
- [ ] Server-side summary generation (Claude API)

## License

MIT
