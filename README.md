# Menos

Self-hosted content vault with semantic search. Centralized store for markdown/frontmatter files and structured data accessible from multiple machines.

## Status

**Phase 0 Complete** - Infrastructure scaffold ready, API stub implemented.

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  REST API       │────▶│  SurrealDB      │────▶│  HNSW Vector    │
│  (FastAPI)      │     │  (metadata +    │     │  Index          │
│                 │     │   embeddings)   │     │                 │
└────────┬────────┘     └─────────────────┘     └─────────────────┘
         │
         │              ┌─────────────────┐     ┌─────────────────┐
         └─────────────▶│  MinIO          │     │  Ollama         │
                        │  (file storage) │     │  (mxbai-embed)  │
                        └─────────────────┘     └─────────────────┘
```

### Components

| Component | Purpose |
|-----------|---------|
| **SurrealDB** | Metadata + vector search (HNSW indexes) |
| **MinIO** | S3-compatible file storage |
| **Ollama** | Local embeddings (mxbai-embed-large) |
| **FastAPI** | REST API with RFC 9421 HTTP signature auth |

## Authentication

Uses [RFC 9421 HTTP Message Signatures](https://datatracker.ietf.org/doc/rfc9421/) with ed25519 keys.

1. Register your SSH public key with the service
2. Sign requests with your private key
3. Server verifies signature against registered public key

Your existing `~/.ssh/id_ed25519` key works directly.

## Quick Start

### Local Development

```bash
# Start infrastructure
make dev

# Check status
make status

# View logs
make dev-logs

# Stop
make dev-down
```

### Remote Deployment

```bash
# Set target host
export MENOS_HOST=your-server.com

# Build Ansible container
make build

# Deploy full stack
make deploy

# Quick update (pull + restart)
make update

# Backup current config
make backup
```

## API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/health` | No | Health check |
| GET | `/ready` | No | Readiness check |
| GET | `/api/v1/auth/keys` | No | List authorized key IDs |
| GET | `/api/v1/auth/whoami` | Yes | Verify authentication |
| POST | `/api/v1/auth/keys/reload` | Yes | Reload keys from disk |
| GET | `/api/v1/content` | Yes | List content |
| GET | `/api/v1/content/{id}` | Yes | Get content |
| POST | `/api/v1/content` | Yes | Upload content |
| DELETE | `/api/v1/content/{id}` | Yes | Delete content |
| POST | `/api/v1/search` | Yes | Semantic vector search |

## Project Structure

```
menos/
├── api/                    # FastAPI application
│   ├── menos/
│   │   ├── auth/           # RFC 9421 signature verification
│   │   ├── routers/        # API endpoints
│   │   └── services/       # SurrealDB, MinIO, Ollama clients
│   ├── Dockerfile
│   └── pyproject.toml
├── infra/
│   └── ansible/            # Deployment automation
│       ├── files/menos/    # Remote compose stack
│       ├── inventory/      # Server configuration
│       └── playbooks/      # Deploy, update, backup
├── docs/                   # Documentation
├── _archive/               # Previous implementations
└── Makefile                # Dev and deploy commands
```

## Configuration

Environment variables (set in `.env`):

| Variable | Description |
|----------|-------------|
| `SURREALDB_PASSWORD` | SurrealDB root password |
| `MINIO_ROOT_USER` | MinIO admin username |
| `MINIO_ROOT_PASSWORD` | MinIO admin password |
| `DATA_PATH` | Data directory (default: `/data/menos`) |

## Implementation Status

- [x] Phase -1: Archive v0 scaffold
- [x] Phase 0: Infrastructure (Ansible, Compose, Makefile)
- [x] Phase 1: API scaffold with RFC 9421 auth
- [ ] Phase 2: Storage (MinIO + SurrealDB integration)
- [ ] Phase 3: Search (Ollama embeddings + HNSW)
- [ ] Phase 4: YouTube migration
- [ ] Phase 5: Agentic search

## License

MIT
