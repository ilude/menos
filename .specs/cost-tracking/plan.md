---
created: 2026-02-11
completed:
---

# Team Plan: LLM Cost Tracking

## Objective

Track every LLM API call with token counts, cost estimates, duration, and context. Enable cost visibility and budget monitoring for content processing pipeline and agentic search features.

## Project Context

- **Language**: Python 3.12+ (FastAPI, Pydantic, SurrealDB)
- **Test command**: `cd api && uv run pytest tests/unit/ -v`
- **Lint command**: `cd api && uv run ruff check menos/`
- **Key files**:
  - `api/menos/services/llm.py` — LLMProvider protocol
  - `api/menos/services/llm_providers.py` — Cloud provider implementations
  - `api/menos/services/unified_pipeline.py` — Content processing (uses LLM)
  - `api/menos/services/agent.py` — Agentic search (uses LLM)
  - `api/menos/services/di.py` — Dependency injection wiring
  - `api/menos/services/storage.py` — SurrealDB repository

## Background

Current state:
- LLM calls happen in unified pipeline (tags, summary, entities) and agentic search (expansion, synthesis)
- Unified pipeline estimates tokens: `len(prompt) // 4 + len(response) // 4`
- No cost tracking, no visibility into API spend
- Providers: OpenAI, Anthropic, OpenRouter, Ollama, FallbackProvider, NoOp

Target state:
- Every `generate()` call logged to SurrealDB with token counts, cost, duration, context
- `GET /api/v1/usage` endpoint with date range and provider filters
- Cost estimates based on per-model pricing table
- Context strings identify call source: `pipeline:{job_id}`, `search:expansion`, `search:synthesis`

## Complexity Analysis

| Task | Est. Files | Change Type | Model | Agent |
|------|-----------|-------------|-------|-------|
| T1: Schema migration for llm_usage | 1 | New migration | Sonnet | builder |
| T2: Pricing table config | 1 | New module | Sonnet | builder |
| T3: Metering decorator | 1 | New service | Sonnet | builder |
| T4: DI wiring integration | 1 | Modify | Sonnet | builder |
| T5: Usage router endpoint | 2 | New router | Sonnet | builder |
| T6: Unit tests | 3 | New tests | Sonnet | builder |

## Team Members

| Name | Agent | Model | Role |
|------|-------|-------|------|
| Schema Builder | builder | Sonnet 4.5 | Create llm_usage table migration |
| Config Builder | builder | Sonnet 4.5 | Define pricing table for model costs |
| Metering Builder | builder | Sonnet 4.5 | Implement metering decorator wrapper |
| DI Builder | builder | Sonnet 4.5 | Wire metering into provider chain |
| API Builder | builder | Sonnet 4.5 | Create usage endpoint and models |
| Test Builder | builder | Sonnet 4.5 | Write unit tests for metering + endpoint |

## Execution Waves

### Wave 1: Infrastructure
**Dependencies**: None

- **T1: Create llm_usage table migration** [Sonnet] — Schema Builder
  - Create `api/migrations/YYYYMMDD-HHMMSS_llm_usage_table.surql`
  - Define `llm_usage` table with fields:
    - `provider: string` — Provider name (openrouter, openai, anthropic, ollama, etc.)
    - `model: string` — Full model identifier (openrouter/aurora-alpha, gpt-4o-mini, etc.)
    - `input_tokens: int` — Estimated input token count
    - `output_tokens: int` — Estimated output token count
    - `estimated_cost: float` — USD cost estimate
    - `context: string` — Call context (pipeline:JOB_ID, search:expansion, search:synthesis)
    - `duration_ms: int` — Call duration in milliseconds
    - `created_at: datetime` — Timestamp (default time::now())
  - Add index on `created_at` for efficient date range queries
  - Follow existing migration pattern from `20260211-120100_pipeline_job.surql`

  **Acceptance Criteria**:
  - Migration file exists with correct naming convention
  - All fields defined with correct types
  - Index on `created_at` field
  - Migration runs successfully: `cd api && uv run python scripts/migrate.py`

- **T2: Create pricing configuration module** [Sonnet] — Config Builder
  - Create `api/menos/services/llm_pricing.py`
  - Define `PRICING` dict with per-model pricing:
    - OpenRouter: `openrouter/aurora-alpha` (free), `openai/gpt-oss-120b:free` (free), `deepseek/deepseek-r1-0528:free` (free), `google/gemma-3-27b-it:free` (free)
    - OpenAI: `gpt-4o-mini` ($0.15/$0.60 per 1M tokens input/output), `gpt-4-turbo` ($10/$30)
    - Anthropic: `claude-3-5-haiku-20241022` ($1/$5), `claude-3-5-sonnet-20241022` ($3/$15)
    - Ollama models (free, $0/$0)
  - Function `get_model_pricing(provider: str, model: str) -> dict[str, float]` returns `{"input": x, "output": y}` per 1M tokens
  - Return `{"input": 0.0, "output": 0.0}` for unknown models

  **Acceptance Criteria**:
  - Pricing dict covers all providers used in the project
  - Prices match current API pricing (as of Feb 2026)
  - Function returns correct pricing for known models
  - Unknown models return zero cost (no crash)
  - Unit test verifies pricing lookups

- **T3: Implement LLM metering decorator** [Sonnet] — Metering Builder
  - Create `api/menos/services/llm_metering.py`
  - Implement `MeteringLLMProvider` class:
    - Wraps any `LLMProvider` instance
    - Intercepts `generate()` calls
    - Measures duration with `time.perf_counter()`
    - Estimates tokens: `len(prompt) // 4` for input, `len(response) // 4` for output
    - Looks up cost from pricing table
    - Writes record to `llm_usage` table via `SurrealDBRepository`
    - Returns original response unchanged (pass-through)
  - Constructor accepts: `provider: LLMProvider, repo: SurrealDBRepository, context_prefix: str, provider_name: str, model_name: str`
  - Implement `async def close()` that calls wrapped provider's close
  - Write usage record asynchronously (don't block response)

  **Acceptance Criteria**:
  - Decorator implements `LLMProvider` protocol
  - `generate()` calls wrapped provider and logs usage
  - Token estimation uses `len(text) // 4` formula
  - Cost calculated from pricing table
  - Duration captured in milliseconds
  - Context string includes prefix (e.g., "pipeline:abc123")
  - Unit tests with mocked DB verify logging behavior
  - No exceptions raised if DB write fails (log error and continue)

### Wave 2: Integration & API
**Dependencies**: [T1, T2, T3]

- **T4: Wire metering into DI container** [Sonnet] — DI Builder
  - Modify `api/menos/services/di.py`
  - Wrap providers in `get_expansion_provider()`, `get_synthesis_provider()`, `get_unified_pipeline_provider()` with `MeteringLLMProvider`
  - Pass appropriate context prefixes: `"search:expansion"`, `"search:synthesis"`, `"pipeline"`
  - For unified pipeline, update `UnifiedPipelineService` to pass job_id to metering context: `"pipeline:{job_id}"`
  - Extract provider name and model from wrapped provider for metering constructor
  - Don't wrap `NoOpLLMProvider` (no metering for no-op)

  **Acceptance Criteria**:
  - All LLM providers (except NoOp) wrapped with metering
  - Context strings correctly identify call source
  - Pipeline context includes job_id for granular tracking
  - Existing functionality unchanged (pass-through behavior)
  - No circular dependencies in DI wiring

- **T5: Create usage reporting endpoint** [Sonnet] — API Builder
  - Create `api/menos/routers/usage.py`
  - Define `UsageQuery` model:
    - `start_date: datetime | None = None`
    - `end_date: datetime | None = None`
    - `provider: str | None = None`
    - `model: str | None = None`
  - Define `UsageResponse` model:
    - `total_calls: int`
    - `total_input_tokens: int`
    - `total_output_tokens: int`
    - `estimated_total_cost: float`
    - `breakdown: list[dict]` — Per-provider/model breakdown with counts and costs
  - Implement `GET /api/v1/usage` endpoint:
    - Accepts query params: `start_date`, `end_date`, `provider`, `model`
    - Queries `llm_usage` table with WHERE filters
    - Aggregates: SUM(input_tokens), SUM(output_tokens), SUM(estimated_cost), COUNT(*)
    - Groups by provider + model for breakdown
  - Requires RFC 9421 auth
  - Register router in `api/menos/main.py`

  **Acceptance Criteria**:
  - Endpoint returns correct aggregated totals
  - Date range filtering works (inclusive bounds)
  - Provider/model filters work
  - Breakdown includes per-provider and per-model stats
  - Auth required
  - Response follows UsageResponse schema
  - Endpoint documented in `.claude/rules/api-reference.md`

### Wave 3: Testing
**Dependencies**: [T1, T2, T3, T4, T5]

- **T6: Comprehensive unit tests** [Sonnet] — Test Builder
  - Create `api/tests/unit/test_llm_metering.py`:
    - Test metering decorator intercepts calls
    - Test token estimation accuracy
    - Test cost calculation for various models
    - Test DB write on successful generation
    - Test error handling (DB write fails, provider fails)
    - Test context string formatting
  - Create `api/tests/unit/test_llm_pricing.py`:
    - Test pricing lookup for all known models
    - Test unknown model returns zero cost
    - Test pricing data structure validity
  - Create `api/tests/unit/test_usage_router.py`:
    - Test usage endpoint with mocked DB
    - Test date range filtering
    - Test provider/model filtering
    - Test aggregation logic
    - Test empty results case
  - All tests must pass with zero warnings

  **Acceptance Criteria**:
  - Test coverage >80% for new modules
  - All edge cases covered (empty data, invalid dates, etc.)
  - Mock DB operations (no live DB in unit tests)
  - Tests pass: `cd api && uv run pytest tests/unit/test_llm_*.py tests/unit/test_usage_router.py -v`
  - No warnings from pytest or ruff

## Dependency Graph

```
T1 (Schema) ───┐
               │
T2 (Pricing) ──┼──> T3 (Metering) ──┬──> T4 (DI) ──┐
               │                     │              ├──> T6 (Tests)
               │                     └──> T5 (API) ─┘
               │
               └──> (blocks all downstream)
```

## Implementation Notes

### Token Estimation Formula
Use `len(text) // 4` for both input and output. This is a rough approximation (1 char ≈ 0.25 tokens). Acceptable for cost tracking purposes. Real token counts from API responses would require provider-specific parsing.

### Pricing Table Updates
Pricing must be kept up-to-date manually. Consider adding a comment with last-updated date. Future enhancement: fetch pricing from provider APIs.

### Context String Format
- Unified pipeline: `"pipeline:{job_id}"` (e.g., `"pipeline:pipeline_job:abc123"`)
- Search expansion: `"search:expansion"`
- Search synthesis: `"search:synthesis"`

### Metering Error Handling
DB write failures should NOT break LLM calls. Log error, emit warning, continue. This ensures metering doesn't become a single point of failure.

### FallbackProvider Metering
`FallbackProvider` tries multiple providers in sequence. Each sub-provider should be individually metered. Wrap each provider in the fallback chain, not the `FallbackProvider` itself.

### Cost Calculation
```python
cost = (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price
```

### SurrealDB Query Pattern
```python
# Aggregation query example
query = """
SELECT
  count() AS total_calls,
  math::sum(input_tokens) AS total_input_tokens,
  math::sum(output_tokens) AS total_output_tokens,
  math::sum(estimated_cost) AS estimated_total_cost
FROM llm_usage
WHERE created_at >= $start AND created_at <= $end
  AND provider = $provider
"""
```

## Success Metrics

1. Every LLM call logged to `llm_usage` table
2. Usage endpoint returns accurate cost data
3. Date range and filter queries work correctly
4. No performance degradation in LLM calls (metering is async)
5. All unit tests pass with >80% coverage
6. Linter passes with no warnings
7. Cost estimates within 10% of actual provider costs (manual verification)

## Future Extensions

- Real token counts from provider API responses (parse usage objects)
- Budget alerts (webhook when monthly cost exceeds threshold)
- Cost breakdown by content type (YouTube vs markdown)
- Grafana dashboard for cost visualization
- Token count caching (avoid re-estimating same prompts)
- Provider API key rotation tracking
- Cost attribution per user (if multi-tenant)
