---
created: 2026-02-11
completed:
status: blocked-by-phase1
---

# Team Plan: Unified Pipeline — Merge LLM Calls (Phase 2)

## Prerequisites
- Phase 1 complete: Entity extraction wired into ingestion (`.specs/unified-pipeline-docs/plan.md`)
- Phase 1 deployed and validated with real content
- Both classification and entity extraction running as separate background tasks

## Objective
Merge classification and entity extraction into a single LLM call. Create a unified pipeline service that orchestrates 4 phases (deterministic pre-enrichment, single LLM pass, post-processing, persist). Implement the hybrid knowledge graph model with flat labels for filtering and rich entity nodes for graph traversal.

## Design Decisions (from brainstorm session 2026-02-11)

These decisions were made during a structured brainstorming session:

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Single LLM Pass** | Merge classification (tier, score, summary, labels) and entity extraction (topics, entity validations) into one LLM call. Cost/latency savings: 1 call instead of 2. |
| 2 | **Hybrid Knowledge Graph** | Flat labels (on content record) for filtering/search + rich entity nodes (Topic, Repo, Paper, Tool with hierarchy) for graph traversal. Two layers, two purposes. |
| 3 | **Label Seeding** | LLM sees existing labels for vocabulary consistency (prevents "ML" vs "machine-learning" drift). This is NOT scoring bias — just vocabulary control. |
| 4 | **Link Extraction Before LLM** | Deterministic pre-enrichment (links, URLs, keyword matching) feeds into the LLM call as context. LLM validates pre-detected entities rather than re-extracting. |
| 5 | **Full Pass Always** | No `classification_min_content_length` gate. Every content item gets the full pipeline regardless of length. |
| 6 | **Interest Profile = Derived View** | Read-only aggregation of labels + channels. No longer an input to classification (removes circular dependency). `get_interest_profile()` becomes a simple query. |

### Approach Selected: B (Single LLM Pass)
Three approaches were evaluated:
- A: Sequential (classification first, no interest context) — simplest but labels drift
- **B: Single LLM Pass** — one combined prompt, cheapest, accepted risk of prompt complexity
- C: Seeded (lightweight interest context) — best quality but 2 LLM calls

### Knowledge Graph Model Selected: C (Hybrid)
Three models were evaluated:
- A: Labels as flat graph nodes — simple but no hierarchy
- B: Unified entities (labels ARE topic entities) — richest but complex
- **C: Hybrid** — labels for filtering/search + entities for depth. Independent layers, different UX needs.

## Pipeline Design (4 Phases)

```
Ingest Content (YouTube or Markdown)
    │ (background task, doesn't block response)
    ▼
Phase 1: Deterministic Pre-enrichment
├─ Extract Links (wiki + markdown + URLs)
├─ URL Detection (GitHub, arXiv, DOI, PyPI, npm)
└─ Keyword/Fuzzy Entity Match (against cached entity DB)
    │
    ▼
Phase 2: Single LLM Pass
Input:
  • Content text (truncated to 10k chars)
  • Pre-enrichment results (links, detected entities)
  • Existing labels list (vocabulary consistency)
  • Existing topics list (topic reuse)
Output (structured JSON):
  • tier (S/A/B/C/D)
  • score (1-100)
  • summary (2-3 sentences + bullets)
  • labels (up to 10, reusing existing vocabulary)
  • topics (hierarchical: "AI > LLMs > RAG")
  • entity validations (confirm/reject pre-detected)
  • additional entities (missed by deterministic steps)
    │
    ▼
Phase 3: Post-processing
├─ Deduplicate labels (Levenshtein ≤ 2)
├─ Resolve entities (match existing / create new)
└─ Fetch external metadata (GitHub API, arXiv API — optional)
    │
    ▼
Phase 4: Persist
├─ Update content (labels, tier, score, summary, processing_status)
├─ Store entity edges (content_entity table)
├─ Store links (link table)
└─ Upload summary.md to MinIO
```

## Hybrid Knowledge Graph

### Two Layers, Two Purposes

| Layer | Storage | Purpose | UX |
|-------|---------|---------|-----|
| **Labels** | Flat array on content record | Filtering, faceted search, interest profile | Sidebar tags, search filters, "More like this" |
| **Entities** | Entity table + content_entity edges | Graph traversal, deep exploration, recommendations | Knowledge graph view, topic drill-down, connections |

Labels and entities are intentionally independent. The LLM produces both in one pass:
- Labels: flat strings, max 10, deduplicated against existing
- Topics: hierarchical ("AI > LLMs > RAG"), stored as entity nodes
- Other entities: Repos, Papers, Tools (detected by URL/keyword + validated by LLM)

A label "RAG" and topic "AI > LLMs > RAG" may coexist — they serve different queries.

### Interest Profile (Derived View)

```sql
-- Top labels by frequency
SELECT labels, count() AS cnt FROM content GROUP BY labels ORDER BY cnt DESC LIMIT 15
-- Top channels
SELECT metadata.channel_title, count() AS cnt FROM content
  WHERE content_type = 'youtube' GROUP BY metadata.channel_title ORDER BY cnt DESC LIMIT 10
```

### Graph Queries Enabled

| Query | How |
|-------|-----|
| "Everything about RAG" | Label filter OR topic subtree traversal |
| "How is Video A connected to Video B?" | Shortest path through shared labels/entities |
| "My knowledge clusters" | Community detection on entity-content bipartite graph |
| "What am I ignoring?" | Topics with low content count relative to subtree |
| "Related to this video" | Shared labels (fast) + shared entities (deep) + embedding similarity |

### Recommendation Engine Integration

```
recommendation_score(doc) =
    w_embedding  * cosine(doc.embedding, query_embedding)
  + w_labels     * jaccard(doc.labels, target.labels)
  + w_entities   * shared_entity_count(doc, target) / max_entities
  + w_preference * preference_similarity(doc)
```

## Changes from Phase 1 System

| What | Phase 1 (current) | Phase 2 (this plan) |
|------|-------------------|---------------------|
| LLM calls per content | 2 (classification + entity extraction) | 1 (combined) |
| Interest profile | Input to classification (bias) | Derived read-only view (no bias) |
| Link extraction | Markdown uploads only | All content types, Phase 1 pre-enrichment |
| Min content length gate | Exists for classification | Removed — always runs |
| Status fields | Separate `classification_status` + `entity_extraction_status` | Single `processing_status` |
| Labels | From classification only | From combined pass |
| Topics | From entity extraction only | From combined pass |

## Implementation Tasks (High-Level)

### Prerequisite: Validate prompt quality
1. Create standalone script that runs the combined prompt on 10+ real content items
2. Compare output to existing separate classification + entity extraction results
3. Measure: tier accuracy, label consistency, topic quality, JSON parse success rate
4. Only proceed if quality is at parity or better

### Core Implementation
1. **Extract shared utilities** — `_extract_json_from_response()` exists in both classification.py and entity_extraction.py. Extract to shared module to avoid a third copy.
2. **Create combined prompt template** — Merge `CLASSIFICATION_PROMPT_TEMPLATE` and entity extraction prompt. Use proper Pydantic models (reuse `ExtractedEntity`, `PreDetectedValidation` — NOT `list[dict]`).
3. **Create `UnifiedPipelineService`** — Orchestrates 4 phases. Delegates entity resolution to existing `EntityResolutionService` (don't duplicate). Key decision: the unified service replaces `EntityResolutionService`'s LLM call with the combined prompt but reuses its resolution logic.
4. **Schema migration** — Add `processing_status`, `processed_at`. Remove `classification_min_content_length` config.
5. **Wire into routers** — Replace both background tasks (classification + entity extraction) with one unified pipeline call.
6. **Update `get_interest_profile()`** — Change to label aggregation query.
7. **Update graph endpoint** — Include entity nodes in `/api/v1/graph` response.

### Testing
- TDD: Write tests for combined prompt parser FIRST
- TDD: Write tests for pipeline orchestration FIRST
- Validate prompt against real content before full wiring
- Integration tests for router-level changes

### Documentation
- Create `docs/specs/unified-pipeline.md` (design spec with mermaid diagrams)
- Update `docs/ingest-pipeline.md` (Stage 4 → unified phases)
- Update `docs/schema.md` (processing_status fields)
- Update `.claude/rules/architecture.md` (reference unified pipeline)
- Update `.claude/rules/schema.md` (note new fields)
- Do NOT modify historic specs (entity-extraction.md, recommendation-engine.md, etc.)

## Expert Review Findings (from Phase 1 review, applicable to Phase 2)

Issues to address when implementing Phase 2:

1. **Reuse existing Pydantic models** — `ExtractedEntity`, `PreDetectedValidation`, `ExtractionResult` already exist in models.py. Do NOT use `list[dict]`.
2. **Extract `_extract_json_from_response()`** into shared utility before creating combined parser.
3. **DI factory** — Add `get_unified_pipeline_service()` to di.py. Decide: use `entity_extraction_provider` settings or new `unified_pipeline_provider`.
4. **Service composition** — `UnifiedPipelineService` should wrap `EntityResolutionService`, not duplicate it. Use its resolution methods but replace its LLM call.
5. **Interest profile removal is a behavior change** — Removing scoring bias changes existing classification scores. Document explicitly, consider reprocessing.
6. **Feature flag** — Add `UNIFIED_PIPELINE_ENABLED` (default false) for clean rollback. When false, Phase 1 behavior (separate tasks). When true, unified pipeline.
7. **Combined prompt risk** — Validate against real content BEFORE investing in full wiring. Check JSON parse success rate and output quality.
8. **`max_tokens` for combined response** — Classification uses 3000, entity extraction uses 2000. Combined may need 4000+. Verify with actual models.
9. **Partial success handling** — If entity extraction portion of combined response fails parsing, still persist classification results. Don't lose tier/score/summary because topics were malformed.

## Spec Alignment

This phase supersedes/modifies aspects of these existing specs (which should NOT be edited — they're historic design documents):

| Existing Spec | What Changes |
|---|---|
| `docs/specs/entity-extraction.md` | `should_skip_llm` removed; LLM stage merged with classification |
| `docs/specs/recommendation-engine.md` | Interest profile rewritten as label aggregation; scoring formula adds graph signals |
| `docs/specs/message-bus.md` | `process_content` task definition updated for unified pipeline |
| `docs/specs/orchestrator.md` | No conflicts — operates at query time, pipeline operates at ingest time |
| `docs/specs/ui-roadmap.md` | No conflicts — gains capabilities from richer graph |
