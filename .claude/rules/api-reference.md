---
paths:
  - "api/**/*.py"
---

# API Reference

## Configuration

Environment variables (see `api/menos/config.py`):

| Variable | Description |
|----------|-------------|
| `SURREALDB_URL` | SurrealDB connection URL |
| `SURREALDB_NAMESPACE` | Database namespace |
| `SURREALDB_DATABASE` | Database name |
| `SURREALDB_USER` | Database username |
| `SURREALDB_PASSWORD` | Database password |
| `MINIO_URL` | MinIO server endpoint |
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

## Endpoints

All authenticated endpoints require RFC 9421 HTTP signature headers.

### Auth
- `GET /api/v1/auth/keys` — List authorized key IDs (public)
- `GET /api/v1/auth/whoami` — Verify authentication
- `POST /api/v1/auth/keys/reload` — Reload keys from disk

### Content
- `GET /api/v1/content` — List content (`tags`, `content_type` query params)
- `GET /api/v1/content/{id}` — Get content metadata
- `POST /api/v1/content` — Upload content (`tags` repeatable param; auto-extracts frontmatter + wiki-links)
- `PATCH /api/v1/content/{id}` — Update metadata (tags, title, description)
- `DELETE /api/v1/content/{id}` — Delete content and associated links

### Tags
- `GET /api/v1/tags` — List all tags with counts (sorted by count DESC)

### Links
- `GET /api/v1/content/{id}/links` — Forward links from document
- `GET /api/v1/content/{id}/backlinks` — Documents linking TO this document

### Graph
- `GET /api/v1/graph` — Full knowledge graph (`tags`, `content_type`, `limit` 1-1000)
- `GET /api/v1/graph/neighborhood/{id}` — Local neighborhood (`depth` 1-3)

### Search
- `POST /api/v1/search` — Semantic vector search (`{"query": "...", "tags": [...], "limit": 20}`)
- `POST /api/v1/search/agentic` — Agentic search (expansion + RRF + rerank + synthesis)

### YouTube
- `POST /api/v1/youtube/ingest` — Ingest video by URL
- `POST /api/v1/youtube/upload` — Upload pre-fetched transcript
- `GET /api/v1/youtube/{video_id}` — Get video info
- `GET /api/v1/youtube` — List videos (`channel_id` filter)
- `GET /api/v1/youtube/channels` — List channels with counts

### Health
- `GET /health` — Returns `{"status": "ok", "git_sha": "...", "build_date": "..."}`

## PKM Features

### Tagging
- Tags via query param: `POST /content?tags=a&tags=b`
- Tags from YAML frontmatter merged with explicit tags (deduplicated)
- Filter content/search by tags with AND logic

### Frontmatter Parsing
Auto-extracts from markdown uploads: `title` populates content.title, `tags` merged with query params.

### Link Extraction
Auto-extracts wiki-links `[[Title]]` and markdown links `[text](path)` during upload. External URLs skipped. Links in code blocks ignored. Unresolved links stored with null target.

### Graph Visualization
Returns JSON for D3.js/Cytoscape: `{"nodes": [...], "edges": [...]}`.
