# Entity Extraction - Future Refinements

**Status:** Backlog (for future phases)
**Created:** 2026-02-01
**Source:** Knowledge base review by sub-agents

This document captures refinements identified during knowledge base review that are deferred to future phases.

---

## 1. Architecture Refinements

### 1.1 Orchestrator Pattern (from architecture/orchestrator.md)

Use tool-less reasoning agents for LLM extraction to prevent nested deadlock:

```python
# Coordinator has all data tools
entity_coordinator = Agent(
    model='anthropic:claude-3-5-sonnet',
    tools=[fetch_content, fetch_urls, search_existing_entities, store_entity]
)

# Tool-less reasoning agents (no tools = no deadlock risk)
entity_analyzer = Agent(model='haiku', system_prompt="Extract entities...")
topic_hierarchizer = Agent(model='haiku', system_prompt="Build topic hierarchies...")
```

**Benefits:** Prevents nested agent deadlocks, better model cost optimization.

### 1.2 Message Bus Integration (from architecture/message-bus.md)

Queue-based async processing using Celery:

```python
@app.task(bind=True, max_retries=3)
def extract_entities_task(self, content_id: str):
    """Extract entities for content (async)."""
    coordinator = EntityCoordinator()
    result = coordinator.process_content(content_id)
    return {"content_id": content_id, "entities_found": len(result.entities)}
```

**Task queues:**
- `entity_extraction_queue` - LLM-based extraction (slower)
- `entity_metadata_queue` - External API calls (rate-limited)
- `entity_resolution_queue` - Normalization + DB lookups (fast)

### 1.3 Working Memory for Extraction State

Store extraction progress in database for resumability:

```sql
DEFINE FIELD entity_extraction_progress ON content TYPE option<object>;
-- { status: "processing", urls_detected: 5, entities_extracted: 12, last_stage: "resolution" }
```

---

## 2. New Entity Types

### 2.1 Insights (from evermemos-inspiration)

Atomic, independently-searchable learnings from content:

```json
{
  "entity_type": "insight",
  "name": "Dependency injection enables swapping implementations",
  "metadata": {
    "source_timestamp": "12:34",
    "confidence": 0.92,
    "applicable_to": ["testing", "modularity", "architecture"],
    "insight_category": "semantic_knowledge"
  }
}
```

### 2.2 Techniques (from specs/discussions-needed)

Actionable methods that can be matched to projects:

```json
{
  "entity_type": "technique",
  "name": "Semantic Chunking",
  "metadata": {
    "applicability_criteria": "Long documents with clear topic boundaries",
    "difficulty": "medium",
    "prerequisites": ["embeddings", "clustering"],
    "alternatives": ["fixed-size chunking", "sentence-based chunking"]
  }
}
```

---

## 3. Recommendation Engine Integration

### 3.1 Entity-Aware Preference Vectors (from specs/recommendation-engine)

Track user affinity per entity:

```python
class PreferenceEvolutionService:
    async def update_on_content_rating(self, content_id: str, rating: int, user_id: str):
        entities = await entity_repo.get_entities_for_content(content_id)
        weight = (rating - 3) / 10  # 1=-0.2, 3=0, 5=+0.2
        for entity in entities:
            await update_entity_preference(user_id, entity.id, weight)
```

### 3.2 Multi-Signal Scoring

Add entity signal to recommendation scoring:

```
score = w_chunk * chunk_score
      + w_global * global_score
      + w_preference * preference_score
      + w_entity * entity_match_score  # NEW
```

### 3.3 Entity-Based Cold-Start

Use extracted entities to bootstrap recommendations when ratings are sparse.

---

## 4. Memory Type Taxonomy (from evermemos-inspiration)

Add `memory_category` field mapping to EverMemOS 7-type taxonomy:

| Entity Type | Memory Category |
|-------------|-----------------|
| topic | semantic_knowledge |
| insight | semantic_knowledge OR fact |
| repo | profile |
| paper | semantic_knowledge |
| tool | profile |
| person | profile |

---

## 5. Search Enhancements

### 5.1 Multi-Round Recall

```python
async def search_with_entity_fallback(query: str, entity_filters: list[str], min_results: int = 5):
    # Round 1: Exact entity match
    results = await search(query, entities=entity_filters)
    if len(results) >= min_results:
        return results

    # Round 2: Expand to related entities
    related = await find_related_entities(entity_filters)
    results.extend(await search(query, entities=related))
    if len(results) >= min_results:
        return results

    # Round 3: LLM-guided refinement (expensive)
    refined_queries = await llm_refine_search(query, entity_filters, results)
    for refined in refined_queries:
        results.extend(await search(refined))
```

### 5.2 Entity Embeddings

Add 1024-dim embeddings to entities for semantic entity search.

---

## 6. Prompt Engineering Improvements

### 6.1 Verbalized Sampling

Request 3-5 alternative entity sets with probabilities to prevent mode collapse.

### 6.2 Multi-Stage Prompting

Quality assessment → extraction → verification pipeline.

### 6.3 Model Hierarchy

- Orchestrator (Sonnet): decides which chunks need extraction
- Extraction (Haiku): bulk entity extraction on chunks
- Synthesis (Sonnet): merges results and resolves conflicts

---

## 7. Scalability Improvements

### 7.1 Rate Limit Tracking in Redis

```python
class APIRateLimiter:
    def __init__(self, api_name: str, limit: int, window: str):
        # Use Redis backend (shared across workers)

    async def can_proceed(self) -> bool:
        """Check if API call is allowed."""
```

### 7.2 Incremental Metadata Updates

Only re-fetch entities older than 7 days:

```python
async def fetch_metadata_if_stale(entity: Entity, max_age_days: int = 7):
    if entity.metadata.get("fetched_at"):
        age = datetime.now() - entity.metadata["fetched_at"]
        if age.days < max_age_days:
            return entity  # Use cached
    return await fetch_fresh_metadata(entity)
```

### 7.3 Batch Processing with Deduplication

Reduce DB roundtrips during reprocessing by batching entity resolution.

---

## 8. UI Considerations (from specs/ui-roadmap)

### 8.1 Entity Sidebar (Phase 3)

Panel showing:
- Entities extracted from current conversation
- Related content for selected entity
- Quick actions: add to project, merge duplicates

### 8.2 Topic Hierarchy Navigation

Breadcrumb navigation: "AI → LLMs → RAG" with clickable levels.

### 8.3 Graph Visualization Enhancements

- `color_by_type` (topics=blue, repos=green, papers=orange)
- `size_by_mentions` (frequently mentioned entities larger)
- `cluster_by_hierarchy` (topics grouped by parent)

---

## 9. Quality & Feedback

### 9.1 Extraction Quality Metrics

Track: entities per content, new vs existing ratio, confidence distribution.

### 9.2 User Feedback Loop

Allow corrections to improve prompts over time:
- False positives (extracted but not discussed)
- False negatives (missed important entities)

---

## Priority Order for Future Phases

| Phase | Refinements |
|-------|-------------|
| **Phase 2** | Message bus integration, async processing |
| **Phase 3** | Entity embeddings, preference learning |
| **Phase 4** | Insights entity type, techniques entity type |
| **Phase 5** | UI integration (sidebar, graph enhancements) |
| **Phase 6** | Multi-round recall, model hierarchy |
