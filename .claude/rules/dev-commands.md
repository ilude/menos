# Development Commands

All commands run from `api/` directory.

## Setup & Run

```bash
uv sync                                          # Install dependencies
uv run uvicorn menos.main:app --reload           # Run locally (port 8000)
```

## Testing

```bash
uv run pytest                                    # All tests (smoke excluded)
uv run pytest tests/unit/ -v                     # Unit tests only
uv run pytest tests/unit/test_youtube.py -v      # Specific file
uv run pytest tests/integration/ -v              # Integration tests
```

Tests use `MagicMock` for sync methods (SurrealDB, httpx response.json) and `AsyncMock` for async methods (httpx client.post).

## Smoke Tests (Live Deployment)

```bash
uv run pytest tests/smoke/ -m smoke -v
# Or CLI runner:
uv run python scripts/smoke_test.py --url http://api.example.com -v
```

| Variable | Description |
|----------|-------------|
| `SMOKE_TEST_URL` | Target API URL |
| `SMOKE_TEST_KEY_FILE` | SSH private key for auth |

## Linting

```bash
uv run ruff check menos/                         # Lint
uv run ruff format menos/                        # Format
```

## Scripts

```bash
PYTHONPATH=. uv run python scripts/ingest_videos.py      # Ingest YouTube videos
PYTHONPATH=. uv run python scripts/refetch_metadata.py   # Re-fetch YouTube metadata
PYTHONPATH=. uv run python scripts/query.py "SELECT * FROM content LIMIT 5"  # Ad-hoc queries
```
