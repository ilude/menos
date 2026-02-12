---
created: 2026-02-11
completed:
---

# Team Plan: Unified URL Ingestion

## Objective

Build a single `POST /api/v1/ingest` endpoint that accepts any URL, auto-detects type (YouTube, web article), and routes to the appropriate extractor. YouTube URLs continue through the existing transcript flow; web URLs route to Docling for HTML→Markdown conversion, then into the unified pipeline.

**End state:**
- Users submit any URL to a single endpoint
- YouTube videos → existing YouTube ingestion
- Web pages → Docling extraction → content storage + unified pipeline
- Resource key deduplication prevents re-ingestion of the same URL
- Tests verify routing, dedup, Docling integration

## Project Context

- **Language**: Python 3.12+ (FastAPI, Pydantic)
- **Database**: SurrealDB (metadata), MinIO (file storage)
- **Existing patterns**:
  - YouTube ingestion: `api/menos/routers/youtube.py`, `api/menos/services/youtube.py`
  - URL detection: `api/menos/services/url_detector.py`
  - Resource keys: `api/menos/services/resource_key.py` (format: `yt:VIDEO_ID`, `url:SHA256`)
  - Pipeline orchestration: `api/menos/services/pipeline_orchestrator.py`
  - DI wiring: `api/menos/services/di.py`
- **Test command**: `cd api && uv run pytest tests/unit/ -v`
- **Lint command**: `cd api && uv run ruff check menos/`
- **Deployment**: Ansible + Docker Compose stack (menos-api, surrealdb, minio, ollama)

## Complexity Analysis

**Medium complexity** — involves Docker infra changes, new HTTP service client, new router, tests.

**Risks:**
- Docling container may be resource-heavy (requires GPU for optimal PDF extraction)
- URL normalization edge cases (redirects, query params)
- Deduplication may need URL canonicalization (www vs non-www, trailing slash)

**Mitigations:**
- Start with CPU-only Docling image (smaller, slower but functional)
- Test with common URL patterns (YouTube shorts, mobile links, articles)
- Use SHA-256 hash of normalized URL for dedup

## Team Members

**Orchestrator** — coordinates work, verifies acceptance criteria, updates plan status

**Wave 1 (Infrastructure)**
- **infra-agent** — Add Docling service to Docker Compose

**Wave 2 (API Implementation)**
- **docling-agent** — Build Docling HTTP client service
- **router-agent** — Build `/api/v1/ingest` router with URL detection + routing
- **test-agent** — Write unit tests for Docling client, router, URL routing logic

## Execution Waves

### Wave 1: Infrastructure Setup

**Goal:** Docling service running in Docker Compose stack

**Tasks:**

#### Task 1.1: Add Docling container to docker-compose.yml
**Owner:** infra-agent
**Deps:** None
**Files:**
- `infra/ansible/files/menos/docker-compose.yml` (add docling-serve service)

**Implementation:**
- Add `docling-serve` service using `quay.io/docling-project/docling-serve-cpu` image
- Expose port `5001:5001` (Docling default)
- Environment: `DOCLING_SERVE_ENABLE_UI=0` (disable UI for production)
- Add to `menos-api` `depends_on` list
- Document image choice (CPU-only for simplicity; GPU variant available later)

**Acceptance:**
- [ ] Docling service defined in docker-compose.yml
- [ ] Service accessible at `http://docling-serve:5001` from menos-api container
- [ ] No UI enabled (production mode)
- [ ] menos-api waits for docling-serve to start

---

### Wave 2: API Implementation

**Goal:** `/api/v1/ingest` endpoint working with YouTube + Docling routing

**Tasks:**

#### Task 2.1: Build Docling HTTP client service
**Owner:** docling-agent
**Deps:** Task 1.1
**Files:**
- `api/menos/services/docling.py` (new)
- `api/menos/services/di.py` (add `get_docling_client`)
- `api/menos/config.py` (add `DOCLING_URL`)

**Implementation:**
- Create `DoclingClient` service class
- Method: `async def extract_markdown(url: str) -> DoclingResult` (DoclingResult has `markdown: str`, `title: str | None`)
- HTTP POST to `http://docling-serve:5001/v1/convert/source` with JSON payload:
  ```json
  {
    "sources": [{"kind": "http", "url": "https://example.com"}],
    "options": {
      "to_formats": ["md"],
      "image_export_mode": "placeholder"
    }
  }
  ```
- Parse response, extract Markdown from result
- Raise `HTTPException(503)` if Docling unavailable or returns error
- Config: `DOCLING_URL` env var (default: `http://docling-serve:5001`)
- DI: `get_docling_client()` provider in `di.py`

**Acceptance:**
- [ ] `DoclingClient` class with `extract_markdown` method
- [ ] Calls Docling `/v1/convert/source` endpoint correctly
- [ ] Returns Markdown text and title (extracted from HTML `<title>` or first `<h1>`)
- [ ] Config setting for `DOCLING_URL`
- [ ] DI provider added to `di.py`
- [ ] Handles Docling errors gracefully (raises 503 on timeout/unavailable)

#### Task 2.2: Build unified ingest router
**Owner:** router-agent
**Deps:** Task 2.1
**Files:**
- `api/menos/routers/ingest.py` (new)
- `api/menos/main.py` (register router)

**Implementation:**
- Router: `POST /api/v1/ingest`
- Request model: `{"url": str}`
- Response model: `{"content_id": str, "content_type": str, "title": str, "job_id": str | None}`
- URL type detection:
  - YouTube regex: `re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]+)")`
  - If YouTube → delegate to existing YouTube ingestion logic (reuse `YouTubeService`, `PipelineOrchestrator`)
  - Else → assume web article, call `DoclingClient.extract_markdown`
- Deduplication:
  - YouTube: resource key `yt:{video_id}` (existing pattern)
  - Web: resource key `url:{sha256(normalized_url)}` (normalize: lowercase domain, remove trailing slash, strip `www.`)
  - Check if resource key exists in DB before ingesting
  - If exists, return existing `content_id` (idempotent)
- Web ingestion flow:
  1. Normalize URL
  2. Check for existing resource key
  3. Call Docling to extract Markdown
  4. Store Markdown in MinIO at `web/{url_hash}/content.md`
  5. Create content record in SurrealDB (content_type: `web`, title from Docling, file_path, resource_key)
  6. Submit to pipeline orchestrator
  7. Return response
- Register router in `main.py` with prefix `/api/v1`

**Acceptance:**
- [ ] `POST /api/v1/ingest` endpoint defined
- [ ] Accepts `{"url": str}` request body
- [ ] Detects YouTube URLs (regex) → routes to YouTube ingestion
- [ ] Detects web URLs → routes to Docling extraction
- [ ] Creates resource key for deduplication (`yt:VIDEO_ID` or `url:SHA256`)
- [ ] Checks for duplicate resource key before ingesting
- [ ] Stores Markdown in MinIO at `web/{hash}/content.md`
- [ ] Creates content record in SurrealDB with `content_type: web`
- [ ] Submits to pipeline orchestrator (same as YouTube flow)
- [ ] Returns `{"content_id": ..., "content_type": ..., "title": ..., "job_id": ...}`
- [ ] Router registered in `main.py`

#### Task 2.3: Write unit tests
**Owner:** test-agent
**Deps:** Task 2.2
**Files:**
- `api/tests/unit/test_docling_client.py` (new)
- `api/tests/unit/test_ingest_router.py` (new)

**Implementation:**
- Test `DoclingClient`:
  - Mock `httpx.AsyncClient.post` response
  - Verify correct payload sent to Docling API
  - Verify Markdown extraction from response
  - Test error handling (Docling unavailable, bad response)
- Test ingest router:
  - Mock `DoclingClient`, `YouTubeService`, `SurrealDBRepository`, `MinIOStorage`, `PipelineOrchestrator`
  - Test YouTube URL detection → routes to YouTube flow
  - Test web URL → routes to Docling flow
  - Test deduplication (existing resource key returns existing content)
  - Test URL normalization (www removal, trailing slash)
  - Test error cases (Docling unavailable, invalid URL)

**Acceptance:**
- [ ] `test_docling_client.py` covers `extract_markdown` method
- [ ] Tests verify correct Docling API call (payload, headers)
- [ ] Tests verify Markdown extraction and error handling
- [ ] `test_ingest_router.py` covers URL routing logic
- [ ] Tests verify YouTube detection and delegation
- [ ] Tests verify web URL extraction and storage
- [ ] Tests verify deduplication behavior (idempotent on re-ingest)
- [ ] Tests verify URL normalization (www, trailing slash)
- [ ] All tests pass (`uv run pytest tests/unit/ -v`)
- [ ] No linter warnings (`uv run ruff check menos/`)

---

## Dependency Graph

```
Wave 1 (Infrastructure)
├─ 1.1 Add Docling to docker-compose.yml

Wave 2 (API Implementation)
├─ 2.1 Build Docling client service [depends: 1.1]
├─ 2.2 Build ingest router [depends: 2.1]
└─ 2.3 Write unit tests [depends: 2.2]
```

**Critical path:** 1.1 → 2.1 → 2.2 → 2.3

---

## Notes

**Docling API Reference:**
- Endpoint: `POST /v1/convert/source`
- Payload: `{"sources": [{"kind": "http", "url": "..."}], "options": {"to_formats": ["md"], "image_export_mode": "placeholder"}}`
- Response: JSON with converted document (Markdown string in `result` field)
- Docs: https://github.com/DS4SD/docling-serve

**URL Normalization Strategy:**
- Lowercase domain
- Remove `www.` prefix
- Remove trailing slash
- Keep path, query params (for article specificity)
- SHA-256 hash of normalized URL for resource key

**Future Enhancements** (out of scope):
- Support for arXiv, GitHub repos, PyPI, npm (use existing `URLDetector` patterns)
- GPU-enabled Docling container for faster PDF extraction
- Content chunking and embedding generation for web articles (currently only YouTube does this)
- Retry logic for transient Docling failures
