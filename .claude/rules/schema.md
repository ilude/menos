---
paths:
  - "api/**/*.py"
  - "api/scripts/**"
---

# Database Schema

## SurrealDB Tables

### content (ContentMetadata)

| Field | Type | Notes |
|-------|------|-------|
| id | str\|None | SurrealDB RecordID, e.g. `content:abc123` |
| content_type | str | `"youtube"`, `"pdf"`, `"text"` |
| title | str\|None | |
| description | str\|None | |
| mime_type | str | e.g. `"text/plain"` |
| file_size | int | bytes |
| file_path | str | MinIO path |
| author | str\|None | |
| tags | list[str] | default `[]` |
| created_at | datetime\|None | UTC |
| updated_at | datetime\|None | UTC |
| metadata | dict | varies by content_type |

### chunk (ChunkModel)

| Field | Type | Notes |
|-------|------|-------|
| id | str\|None | SurrealDB RecordID |
| content_id | str | FK to content table |
| text | str | 512 chars + 50 char overlap |
| chunk_index | int | 0-based position |
| embedding | list[float]\|None | vector embedding |
| created_at | datetime\|None | UTC |

## SurrealDB v2 Result Handling
- Direct list format vs wrapped `{"result": [...]}` — handle both
- RecordID objects: check `hasattr(value, "id")` and use `value.id`

## Key Patterns
- Storage access: `async with get_storage_context() as (minio, surreal)` from `menos.services.di`
- Scripts run from `api/` dir with `PYTHONPATH=. uv run python scripts/<name>.py`
- Query tool: `api/scripts/query.py` — read-only SurrealQL queries
