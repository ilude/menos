---
created: 2026-02-11
completed:
---

# Team Plan: Content Cross-Referencing via Shared Entities

## Objective

Enable on-demand discovery of related content through shared entities. Given a content_id, find other content that shares the most entities, ranked by relevance (shared entity count).

## Project Context

- **Language**: Python 3.12+ (FastAPI, Pydantic)
- **Database**: SurrealDB (supports graph traversal)
- **Test command**: `cd api && uv run pytest tests/unit/ -v`
- **Lint command**: `cd api && uv run ruff check menos/`
- **Existing systems**:
  - `entity` table: stores 5 entity types (TOPIC, REPO, PAPER, TOOL, PERSON)
  - `content_entity` edge table: connects content to entities
  - `api/menos/routers/graph.py`: knowledge graph visualization endpoints
  - `api/menos/services/storage.py`: SurrealDBRepository pattern

## Complexity Analysis

**Scope**: Small, focused feature
- **Lines of code**: ~150 (query + model + storage method + tests)
- **Files touched**: 3 (models.py, storage.py, test_storage.py)
- **Complexity**: Low - single SurrealDB graph query, straightforward data model
- **Risk**: Low - read-only query, no schema changes, no API surface changes

**Unknowns**:
- Exact SurrealDB graph traversal syntax (needs experimentation)
- Performance with large entity graphs (deferred - optimize if pain emerges)

## Team Members

| Name | Agent | Model | Role |
|------|-------|-------|------|
| crossref-builder-1 | builder | sonnet | Query, model, storage, tests |
| crossref-validator-1 | validator | haiku | Wave validation |

## Execution Waves

### Wave 1: Core Implementation
**Builder_1** implements:

1. **Pydantic model** (`api/menos/models.py`):
   ```python
   class RelatedContent(BaseModel):
       content_id: str
       title: str
       content_type: str
       shared_entity_count: int
       shared_entities: list[str]
   ```

2. **Storage method** (`api/menos/services/storage.py`):
   ```python
   async def get_related_content(
       self,
       content_id: str,
       limit: int = 10
   ) -> list[RelatedContent]:
       """Find content related through shared entities.

       Args:
           content_id: Source content to find relations for
           limit: Maximum number of related items to return

       Returns:
           List of related content, sorted by shared_entity_count DESC
       """
   ```

3. **SurrealDB graph query**:
   - Start from `content_entity` WHERE `content_id = $content_id`
   - Traverse to entities
   - Traverse back to other content via `content_entity`
   - Group by content, count shared entities, collect entity names
   - Exclude self (`WHERE other_content.id != $content_id`)
   - Sort by shared_entity_count DESC
   - Limit results

   Example query structure (syntax needs verification):
   ```surql
   SELECT
       other_content.id AS content_id,
       other_content.title AS title,
       other_content.content_type AS content_type,
       count() AS shared_entity_count,
       array::group(entity.name) AS shared_entities
   FROM content_entity
   WHERE content_id = $content_id
   -- Traverse through entity to other content_entity edges
   -- Group and aggregate
   ORDER BY shared_entity_count DESC
   LIMIT $limit
   ```

4. **Unit tests** (`api/tests/unit/test_storage.py`):
   - Mock SurrealDB response with sample related content
   - Verify correct query parameters passed
   - Verify RecordID conversion for content_id param
   - Verify results sorted by shared_entity_count
   - Verify empty result handling
   - Verify limit parameter applied

**Acceptance Criteria**:
- [ ] `RelatedContent` model added to `models.py`
- [ ] `get_related_content()` method added to `SurrealDBRepository`
- [ ] SurrealDB query returns related content with shared entity counts
- [ ] Results exclude self (source content_id)
- [ ] Results sorted by shared_entity_count DESC
- [ ] Limit parameter respected
- [ ] Unit tests pass: `uv run pytest tests/unit/test_storage.py::test_get_related_content -v`
- [ ] Lint passes: `uv run ruff check menos/`
- [ ] RecordID objects handled correctly (see gotchas.md)

### Wave 1 Validation
- **V1: Validate wave 1** [haiku] — crossref-validator-1, blockedBy: [T1]
  - Run `cd api && uv run pytest tests/unit/ -v` — all tests pass
  - Run `cd api && uv run ruff check menos/` — no lint errors
  - Verify `RelatedContent` model exists in models.py
  - Verify `get_related_content()` method exists in storage.py

## Dependency Graph

```
Wave 1: T1 (crossref-builder-1) → V1 (crossref-validator-1)
```

## Deferred Decisions

**Not in scope** (to be addressed in future specs):
- REST endpoint design (path, parameters, response format)
- Caching strategy (if query performance becomes pain point)
- Pre-computation at ingestion time (if real-time query too slow)
- Filtering by entity type or confidence threshold
- GraphQL vs REST API surface

**Rationale**: Start with core query logic, validate usefulness with real data before committing to API design or optimization strategies.

## Notes

- **On-demand only**: No pre-computation, query runs at request time
- **Graph query experimentation**: Builder may need to iterate on SurrealDB syntax
- **RecordID gotcha**: Remember to use `RecordID("content", content_id)` for WHERE clause parameters (see `.claude/rules/gotchas.md`)
- **Test isolation**: Mock SurrealDB responses, no live database required for unit tests
