# Team Plan: Port CLI Tools from agent-spike to menos

## Objective
Port applicable CLI functionality from `agent-spike/compose/cli/` into the menos project. Menos is a self-hosted content vault with YouTube ingestion via FastAPI + SurrealDB + MinIO. It already has core YouTube services (transcript fetching, metadata, ingestion script) but lacks channel-level fetching, CLI query tools, and URL classification.

## Source Analysis

### What agent-spike has vs menos:

| agent-spike Script | Menos Equivalent | Action |
|---|---|---|
| `fetch_channel_videos.py` | None | **Port** - Channel-level video discovery to CSV |
| `filter_description_urls.py` | `extract_urls()` only | **Port** - Add content vs marketing classification |
| `url_filter_status.py` | None | **Port** - Dashboard for URL filter patterns |
| `update_video_metadata.py` | `refetch_metadata.py` exists | **Skip** - Already covered |
| `list_videos.py` | API only, no CLI | **Port** - CLI wrapper for listing videos |
| `search_videos.py` | API only, no CLI | **Port** - CLI wrapper for semantic search |
| `delete_video.py` | No equivalent | **Port** - CLI video deletion with confirmation |
| `migrate_to_surrealdb.py` | N/A | **Skip** - agent-spike migration specific |
| `populate_surrealdb_from_archive.py` | N/A | **Skip** - agent-spike migration specific |
| `backfill_embeddings.py` | N/A | **Skip** - agent-spike migration specific |
| `validate_data.py` | N/A | **Skip** - agent-spike migration specific |
| `base.py` | None | **Skip** - Menos uses standard package imports |

### Scripts to Port (6 total):
1. `fetch_channel_videos.py` - Fetch all videos from a YouTube channel to CSV
2. `filter_description_urls.py` - Classify URLs in video descriptions (heuristic + LLM)
3. `url_filter_status.py` - Pattern learning dashboard
4. `list_videos.py` - CLI to list videos in SurrealDB
5. `search_videos.py` - CLI semantic search
6. `delete_video.py` - CLI video deletion

## Project Context
- **Language**: Python 3.12+
- **Package manager**: uv
- **Test command**: `cd api && uv run pytest -v`
- **Lint command**: `cd api && uv run ruff check .`
- **Target directory**: `api/scripts/` (existing script location in menos)
- **Services directory**: `api/menos/services/` (business logic)
- **Config**: `api/menos/config.py` (Pydantic Settings, already has `youtube_api_key`)

## Adaptation Notes

Scripts must be adapted to menos patterns:
- Use `menos.config.settings` for configuration (not `os.getenv` + env_loader)
- Use `menos.services.youtube_metadata.YouTubeMetadataService` (already exists with google-api-python-client)
- Use `menos.services.storage.SurrealDBRepository` for DB queries
- Use `menos.services.storage.MinIOStorage` for object storage
- `google-api-python-client` already in `pyproject.toml` dependencies
- No `base.py` setup needed - menos uses proper package imports
- Follow ruff lint rules (line-length 100, select E/F/I/UP)

## Team Members
| Name | Agent | Role |
|------|-------|------|
| port-cli-builder | builder (sonnet) | Implement all scripts |
| port-cli-validator | validator (haiku) | Verify lint, tests, no secrets |

## Tasks

### Task 1: Port channel video fetcher
- **Owner**: port-cli-builder
- **Blocked By**: none
- **Description**: Create `api/scripts/fetch_channel_videos.py` adapted from agent-spike's version. Must use `menos.config.settings.youtube_api_key` instead of env_loader. Output CSVs to `data/queues/` (create directory). Use `YouTubeMetadataService._get_client()` pattern for API client, or create client inline. Support `--channel-url`, `--months`, `--output` args.
- **Acceptance Criteria**:
  - [ ] Script exists at `api/scripts/fetch_channel_videos.py`
  - [ ] Uses `menos.config.settings` for YouTube API key
  - [ ] Accepts channel URL, months-back, and output file arguments
  - [ ] Outputs CSV with title, url, upload_date, view_count, duration, description
  - [ ] Passes `ruff check`

### Task 2: Port CLI query tools (list, search, delete)
- **Owner**: port-cli-builder
- **Blocked By**: none
- **Description**: Create three scripts in `api/scripts/`:
  - `list_videos.py` - List videos from SurrealDB with pagination (--limit, --offset)
  - `search_videos.py` - Semantic search using Ollama embeddings (query, --limit, --channel)
  - `delete_video.py` - Delete video with confirmation (video_id, --yes)
  All must use `menos.services.di.get_storage_context()` for DB/MinIO access and `menos.services.storage.SurrealDBRepository` for queries.
- **Acceptance Criteria**:
  - [ ] Three scripts exist in `api/scripts/`
  - [ ] Each uses menos service layer (not raw DB calls)
  - [ ] list_videos supports --limit and --offset
  - [ ] search_videos uses Ollama embeddings for semantic search
  - [ ] delete_video requires confirmation unless --yes
  - [ ] All pass `ruff check`

### Task 3: Port URL classification system
- **Owner**: port-cli-builder
- **Blocked By**: none
- **Description**: Port the URL filtering system. This has two parts:
  1. Create `api/menos/services/url_filter.py` - Heuristic URL classification (content vs marketing). Port the heuristic rules from agent-spike's `compose/services/youtube/url_filter.py`. Skip the LLM classification and pattern learning system initially - just port the heuristic filter.
  2. Create `api/scripts/filter_description_urls.py` - CLI to process video descriptions through the filter. Process single video or --all.
  3. Create `api/scripts/url_filter_status.py` - Simple stats display (count of filtered URLs per category).
  NOTE: The agent-spike version has a complex self-improving pattern system with LLM re-evaluation. For menos, start with heuristics only. The LLM integration can be added later.
- **Acceptance Criteria**:
  - [ ] `api/menos/services/url_filter.py` exists with heuristic classification
  - [ ] `api/scripts/filter_description_urls.py` processes video descriptions
  - [ ] `api/scripts/url_filter_status.py` shows basic stats
  - [ ] Heuristic rules cover common marketing domains (social media, merch, patreon, etc.)
  - [ ] All pass `ruff check`

### Task 4: Add unit tests for new functionality
- **Owner**: port-cli-builder
- **Blocked By**: Task 1, Task 2, Task 3
- **Description**: Add tests for the URL filter service (the only new service-layer code). Scripts are harder to unit test, so focus on the service:
  - `api/tests/unit/test_url_filter.py` - Test heuristic classification rules
  Tests should use the existing test patterns in menos (pytest-asyncio, MagicMock for sync methods).
- **Acceptance Criteria**:
  - [ ] `api/tests/unit/test_url_filter.py` exists
  - [ ] Tests cover content URL detection
  - [ ] Tests cover marketing URL blocking
  - [ ] Tests cover edge cases (empty description, no URLs)
  - [ ] All tests pass with `cd api && uv run pytest -v`

### Task 5: Validate all changes
- **Owner**: port-cli-validator
- **Blocked By**: Task 1, Task 2, Task 3, Task 4
- **Description**: Run linters, tests, and content checks on all builder output. Verify no hardcoded secrets, no debug statements, all files follow menos patterns.
- **Acceptance Criteria**:
  - [ ] `cd api && uv run ruff check .` passes
  - [ ] `cd api && uv run pytest -v` passes
  - [ ] No hardcoded API keys or secrets
  - [ ] No debug print statements left behind
  - [ ] Scripts use menos service patterns consistently

## Dependency Graph
```
Task 1 (channel fetcher)  --\
Task 2 (CLI tools)         --+--> Task 4 (tests) --> Task 5 (validator)
Task 3 (URL filter)       --/
```
