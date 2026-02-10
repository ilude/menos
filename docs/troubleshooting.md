# Troubleshooting

## Server Access

```bash
ssh -i ~/.ssh/id_ed25519 anvil@192.168.16.241
```

## Viewing Logs

```bash
# API container logs (follow mode)
docker logs menos-api -f

# All containers
docker compose logs -f

# Specific service
docker compose logs -f surrealdb
docker compose logs -f minio
docker compose logs -f ollama
```

## Common Issues

### SurrealDB v2 Response Format

SurrealDB v2 returns query results as flat lists instead of the v1 `[{"result": [...]}]` wrapper. Code that accesses `result[0].get("result")` will fail silently or error.

**Fix pattern** (used in `storage.py`):
```python
if isinstance(result[0], dict) and "result" in result[0]:
    raw_items = result[0]["result"]  # v1 format
else:
    raw_items = result  # v2 flat list
```

v2 also returns `RecordID` objects instead of plain strings for `id` fields. Check with `hasattr(item["id"], "id")` and extract via `.id`.

### Container Status

```bash
# Check all containers
docker compose ps

# Restart a specific service
docker compose restart menos-api

# Full rebuild
docker compose up -d --build menos-api
```

### NVIDIA Driver Mismatch

After kernel updates, the NVIDIA driver may fail to load. Symptoms: Ollama container crashes, embedding generation fails.

```bash
# Check driver status
nvidia-smi

# Fix: reboot the server
make reboot
```

## Useful Ansible Commands

```bash
# Interactive shell in Ansible container
make shell

# Full deploy (sync code, rebuild, restart)
make deploy

# Quick update (pull images, restart)
make update

# Backup server config
make backup
```

## Health Checks

```bash
# Basic health
curl http://192.168.16.241:8000/health

# Readiness (checks SurrealDB + MinIO + Ollama)
curl http://192.168.16.241:8000/ready
```

## API Testing

Authenticated endpoints require RFC 9421 HTTP signatures. Use the signing script:

```bash
cd api
uv run python scripts/signed_request.py GET /api/v1/youtube
```
