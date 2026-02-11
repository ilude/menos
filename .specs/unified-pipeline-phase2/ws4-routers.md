---
created: 2026-02-11
completed:
status: blocked
blocked_by: ws1, ws2, ws3
parent: plan.md
---

# Team Plan: WS4 — Router/API Cutover

## Objective

Hard cutover all ingest routers and scripts to use the unified pipeline. Add job management
endpoints (status, reprocess, cancel). Wire callback notifications.

## Depends On
- WS1 (unified pipeline service)
- WS2 (config + DI)
- WS3 (schema + job model)

## Tasks from Master Plan

### Task 7: Hard cutover ingest routers
- `youtube.py`: replace dual background tasks with single unified pipeline job
- `content.py`: same cutover for markdown uploads
- All ingest returns `job_id` immediately (async)

### Task 8: Rewrite scripts to unified status model
- `classify_content.py` → uses `processing_status`
- `reprocess_content.py` → uses `processing_status`
- `export_summaries.py` → uses unified fields

### Task 8a: Reprocess API endpoint
- Single-item reprocess, async, owner-scoped
- Uses stored transcript/content + metadata first
- Fetches external metadata only when required fields missing
- Returns existing `job_id` if active job exists

### Task 8c: Job status endpoint
- `GET /api/v1/jobs/{job_id}` — minimal by default
- `?verbose=true` — full diagnostics tier

### Task 8g: Job cancellation endpoint
- Best-effort cancellation
- `pending` → immediate cancel
- `processing` → cancel between pipeline stages only
- Terminal state: `cancelled`

### Task 8d: Callback notifications
- Optional callbacks with HMAC-SHA256 signatures
- Fixed retry: 3 attempts, exponential backoff
- Stable `callback_event_id` for idempotent receivers
- Payload includes `schema_version`
- Delivery state independent from pipeline outcome

## Files to Create
- `api/menos/routers/jobs.py`
- `api/menos/services/callbacks.py`
- Tests for all new endpoints

## Files to Modify
- `api/menos/routers/youtube.py`
- `api/menos/routers/content.py`
- `api/menos/main.py` (register jobs router)
- `api/scripts/classify_content.py`
- `api/scripts/reprocess_content.py`
- `api/scripts/export_summaries.py`

## Acceptance Criteria
- [ ] All ingest goes through unified pipeline
- [ ] No dual-task background code remains in routers
- [ ] Job endpoints work (create, status, cancel)
- [ ] Reprocess endpoint works for single items
- [ ] Scripts use `processing_status`
- [ ] Callbacks fire with valid HMAC signatures
- [ ] All tests pass

## Final Step: Commit

After validation passes, create a commit with all WS4 changes:
- Determine semver bump level (`major` — breaking change to ingest API contract, returns job_id)
- Run `make version-bump-major` from repo root
- Stage all changed files (excluding unrelated/untracked files)
- Commit message format: `feat!: hard cutover ingest to unified pipeline with job-based API`
- Include bump level and rationale in commit body
