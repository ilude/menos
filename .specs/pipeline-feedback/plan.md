---
created: 2026-02-11
completed:
---

# Team Plan: Pipeline Quality Feedback Loop

## Objective

Inject learned context into the unified pipeline LLM prompt to improve tagging consistency, quality calibration, and entity normalization. Add three feedback signals: tag co-occurrence patterns, quality tier distribution, and entity consolidation history.

## Project Context

- **Language**: Python 3.12+ (FastAPI, Pydantic)
- **Key files**: `api/menos/services/unified_pipeline.py`, `api/menos/services/storage.py`
- **Test command**: `cd api && uv run pytest tests/unit/ -v`
- **Lint command**: `cd api && uv run ruff check menos/`
- **Current state**: Pipeline prompt already has existing tags (top 50), existing topics (up to 20), pre-detected entities. Tag deduplication uses Levenshtein distance ≤ 2.

## Complexity Analysis

| Task | Est. Files | Change Type | Model | Agent |
|------|-----------|-------------|-------|-------|
| T1: Storage queries | 2 (storage.py, test_storage.py) | Add methods | Sonnet 4.5 | Builder |
| T2: Prompt injection | 2 (unified_pipeline.py, test_unified_pipeline.py) | Modify existing | Sonnet 4.5 | Builder |
| T3: Tag alias tracking | 3 (storage.py, unified_pipeline.py, test) | Add tracking | Sonnet 4.5 | Builder |
| V1: Integration test | 1 (new test file) | New test | Sonnet 4.5 | Builder |

## Team Members

- **Builder Agent**: Implements storage queries, prompt injection, tag alias tracking
- **Lead**: Reviews plan, coordinates execution

## Execution Waves

### Wave 1: Storage Query Methods

- **T1: Add feedback signal queries to storage**

  Add three new methods to `SurrealDBRepository` in `api/menos/services/storage.py`:

  1. `get_tag_cooccurrence(min_count: int = 3, limit: int = 20) -> dict[str, list[str]]`
     - Query: For each tag, find other tags appearing on same content ≥ min_count times
     - Return: `{"kubernetes": ["containers", "docker", "devops"], "rag": ["llms", "embeddings"]}`
     - Algorithm: Self-join on content.tags array, group by tag pair, count, filter, limit

  2. `get_tier_distribution() -> dict[str, int]`
     - Query: `SELECT tier, count() FROM content WHERE processing_status = 'completed' GROUP BY tier`
     - Return: `{"S": 5, "A": 42, "B": 180, "C": 60, "D": 8}`

  3. `get_tag_aliases(limit: int = 50) -> dict[str, str]`
     - Query historical tag normalization patterns (defer implementation detail to builder)
     - Return: `{"langchain": "LangChain", "open-ai": "openai", "k8s": "kubernetes"}`
     - Note: May require new table or computed from dedup history

  **Acceptance Criteria:**
  - All three methods implemented in `storage.py`
  - Unit tests in `test_storage.py` with mocked SurrealDB responses
  - Methods handle empty results gracefully (return empty dict)
  - SurrealDB query syntax validated (no syntax errors on mock calls)

### Wave 2: Prompt Injection

- **T2: Inject feedback signals into pipeline prompt**

  Modify `UnifiedPipelineService.process()` in `api/menos/services/unified_pipeline.py`:

  1. Fetch feedback data alongside existing tag fetch:
     ```python
     tag_cooccurrence = self.storage.get_tag_cooccurrence()
     tier_dist = self.storage.get_tier_distribution()
     tag_aliases = self.storage.get_tag_aliases()
     ```

  2. Add three new sections to prompt template after `## EXISTING TOPICS`:

     ```
     ## TAG CO-OCCURRENCE PATTERNS
     {format_cooccurrence(tag_cooccurrence)}

     ## QUALITY DISTRIBUTION (calibrate your ratings)
     Current distribution: {format_distribution(tier_dist)}
     Aim for a balanced distribution. Most content should be B or C tier.

     ## KNOWN ALIASES
     {format_aliases(tag_aliases)}
     ```

  3. Implement formatting helpers:
     - `format_cooccurrence()`: "kubernetes often appears with: containers, docker, devops"
     - `format_distribution()`: "S=2%, A=15%, B=60%, C=20%, D=3%"
     - `format_aliases()`: "langchain → LangChain, open-ai → openai, k8s → kubernetes"

  **Acceptance Criteria:**
  - Prompt template includes all three new sections
  - Formatting helpers implemented as private methods
  - Unit tests verify prompt format with sample feedback data
  - Empty feedback data handled gracefully (sections still present but show "None" or "No data")
  - No regression in existing pipeline tests

### Wave 3: Tag Alias Tracking

- **T3: Log tag normalizations for alias feedback**

  Capture when `parse_unified_response()` maps a variant to canonical form via Levenshtein:

  1. In `unified_pipeline.py`, add logging/storage call when tag deduplication occurs
  2. Store mapping: `self.storage.record_tag_alias(variant="langchain", canonical="LangChain")`
  3. Implement `record_tag_alias()` in storage.py (choose approach: dedicated table vs. computed)
  4. Update `get_tag_aliases()` to query stored mappings

  **Acceptance Criteria:**
  - Tag normalization events captured during `parse_unified_response()`
  - `record_tag_alias()` implemented in storage.py
  - Unit test verifies alias recording on Levenshtein match
  - `get_tag_aliases()` returns recorded mappings
  - No performance regression (alias recording is async/batched if needed)

### Wave 4: Validation

- **V1: Integration test for feedback loop** (blockedBy: [T1, T2, T3])

  Create `api/tests/unit/test_pipeline_feedback.py`:

  1. Mock storage to return sample feedback data
  2. Run pipeline with mocked LLM
  3. Assert prompt contains all three feedback sections
  4. Verify formatting of each section matches expected template
  5. Test edge cases: empty feedback, very large co-occurrence lists

  **Acceptance Criteria:**
  - New test file with ≥5 test cases
  - All tests pass
  - Code coverage for new storage methods ≥80%
  - Ruff linting passes with no warnings

## Dependency Graph

```
T1 (Storage queries)
  ↓
T2 (Prompt injection) ← depends on T1
  ↓
T3 (Alias tracking) ← depends on T1, T2
  ↓
V1 (Integration test) ← depends on T1, T2, T3
```

## Notes

- **No migration required** unless T3 needs dedicated table (decision deferred to builder)
- **Prompt only**: LLM decides whether to use hints; no auto-apply post-processing
- **Performance**: All queries run once per pipeline invocation; cache if latency issues arise
- **Future work**: Track hint effectiveness (did LLM follow co-occurrence patterns?)
