---
created: 2026-02-11
completed:
status: blocked
blocked_by: ws1, ws2, ws3, ws4, ws5
parent: plan.md
---

# Team Plan: WS6 — Validation + Release Readiness

## Objective

Full end-to-end verification that the unified pipeline is the only ingest path, all contracts
are honored, and the codebase is release-ready.

## Depends On
- All previous workstreams (WS1-WS5)

## Tasks from Master Plan

### Task 12: Full verification
- `uv run ruff check menos/` — zero warnings
- `uv run ruff format --check menos/` — all formatted
- `uv run pytest tests/unit/ -v` — all pass
- `uv run pytest tests/integration/ -v` — all pass
- Real-content ingest smoke test against live deployment
- Callback/job/observability validation
- Verify `tags` is canonical everywhere (no `labels` references in runtime code)
- Verify `processing_status` is the only active status model
- Verify `pipeline_version` is persisted on job/content correctly
- Verify health/version endpoint exposes `app_version`

## Verification Commands
```bash
cd api && uv run ruff check menos/
cd api && uv run ruff format --check menos/
cd api && uv run pytest tests/unit/ -v
cd api && uv run pytest tests/integration/ -v
cd api && uv run pytest tests/smoke/ -m smoke -v
```

## Definition of Done (from master plan)
- [ ] Unified pipeline is the only ingest processing path
- [ ] `processing_status` is the only active content processing model
- [ ] `tags` naming is canonical across runtime + docs
- [ ] Old dual-task code path is removed
- [ ] Job APIs (trigger/status/cancel) work with defined contracts
- [ ] Callback + observability + retention controls are operational
- [ ] Semver policy and runtime `app_version` are in place
- [ ] Lint/format/tests pass with zero warnings

## Spec Alignment
- Create: `docs/specs/unified-pipeline.md`
- Update: `docs/ingest-pipeline.md`, `docs/schema.md`
- Update: `.claude/rules/architecture.md`, `.claude/rules/schema.md`

## Final Step: Commit

After all verification passes and docs are updated, create a commit:
- Determine semver bump level (`patch` — docs/specs only, no runtime changes)
- Run `make version-bump-patch` from repo root
- Stage all changed files (excluding unrelated/untracked files)
- Commit message format: `docs: update specs, schema docs, and architecture rules for unified pipeline`
- Include bump level and rationale in commit body
