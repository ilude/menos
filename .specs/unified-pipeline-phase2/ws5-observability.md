---
created: 2026-02-11
completed:
status: blocked
blocked_by: ws3, ws4
parent: plan.md
---

# Team Plan: WS5 — Observability + Retention + Cleanup

## Objective

Add structured logging, correlation IDs, job metrics, audit events, retention controls,
graph endpoint alignment, and remove dead legacy code.

## Depends On
- WS3 (job model for metrics)
- WS4 (routers for observability instrumentation)

## Tasks from Master Plan

### Task 8e: Observability baseline
- Structured logs with correlation IDs across pipeline stages
- Core metrics: job duration and stage latency
- Optional metric: LLM token usage (if provider reports reliably)
- Audit events: full-tier access, reprocess triggers, cancellation, callback delivery
- Error taxonomy: `error_code`, `error_message`, `error_stage`

### Task 8f: Retention/purge controls
- Compact tier: 6-month retention
- Full tier: 2-month retention
- Idempotent purge mechanism (scheduled or startup hook)

### Task 9: Graph endpoint hard contract alignment
- `/api/v1/graph` contract aligns with unified pipeline data model
- Underlying queries use `processing_status` instead of legacy fields

### Task 10: Remove min-length gate
- Remove 500-char minimum content length gate from pipeline

### Task 11: Delete dead legacy code
- Remove legacy dual-task status helpers
- Remove legacy parser compatibility aliases tied to `labels`
- Remove any dead imports, unused functions

## Files to Modify
- `api/menos/services/unified_pipeline.py` (observability, min-length removal)
- `api/menos/services/storage.py` (retention purge queries)
- `api/menos/routers/graph.py` (contract alignment)
- Various files (dead code cleanup)

## Acceptance Criteria
- [ ] Correlation IDs present in all pipeline log entries
- [ ] Job metrics tracked (duration and stages; tokens if available)
- [ ] Audit events for key actions
- [ ] Purge mechanism works and is idempotent
- [ ] Graph endpoint uses unified data model
- [ ] Min-length gate removed
- [ ] No dead legacy code remains
- [ ] All tests pass, zero warnings

## Final Step: Commit

After validation passes, create a commit with all WS5 changes:
- Determine semver bump level (likely `minor` — observability + cleanup, no contract changes)
- Run `make version-bump-minor` from repo root
- Stage all changed files (excluding unrelated/untracked files)
- Commit message format: `feat: add pipeline observability, retention controls, and remove legacy code`
- Include bump level and rationale in commit body
