# Expert Review Suggestions

This document captures suggested expert perspectives for reviewing and improving Menos.

## 1. Information Retrieval / RAG Specialist

**Focus**: Search quality and retrieval architecture

### Review Areas
- Chunking strategy (512 tokens / 50 overlap) - optimization for content types
- Embedding model choice - mxbai-embed-large vs alternatives (e5, bge, nomic-embed)
- RRF fusion parameters and reranking effectiveness
- Query expansion prompts and their impact on recall
- Hybrid search (BM25 + vector) potential
- Evaluation methodology for search quality

### Potential Improvements
- MTEB benchmark comparisons
- Late-interaction models (ColBERT)
- Hypothetical document embeddings (HyDE)
- Adaptive chunking based on content structure
- Search quality metrics and A/B testing framework

---

## 2. Personal Knowledge Management (PKM) / Second Brain Expert

**Focus**: User workflows and ecosystem integration

### Review Areas
- Integration with existing PKM tools (Obsidian, Logseq, Notion)
- Frontmatter schema design for interoperability
- Missing features users expect (tagging, linking, graph views)
- CLI/API ergonomics for daily use
- Sync patterns for multi-device access

### Potential Improvements
- Obsidian plugin for seamless sync
- Bidirectional linking between documents
- Daily notes integration
- Zotero/reference manager integration
- Browser extension for web clipping
- Graph visualization of knowledge connections

**Status**: Under active review - see [PKM Features Gap Analysis](#pkm-features-gap-analysis)

---

## 3. MLOps / Production AI Systems Engineer

**Focus**: Scalability, reliability, and operational concerns

### Review Areas
- Embedding pipeline performance and caching strategies
- SurrealDB vector index scaling characteristics
- Ollama resource management and request queuing
- Monitoring/observability for LLM-based systems
- Batch ingestion performance
- Graceful degradation when Ollama is unavailable

### Potential Improvements
- Embedding cache layer (avoid re-embedding unchanged content)
- Async batch processing queue
- Request rate limiting
- OpenTelemetry tracing for LLM calls
- GPU utilization metrics
- Model warm-up strategies on startup

---

## PKM Features Gap Analysis

**Review Date**: 2026-02-01
**Reviewer Perspective**: PKM / Second Brain Expert

### Executive Summary

Menos has strong semantic search foundations but lacks the organizational features PKM users expect. Tags exist in the schema but are inaccessible via API. No linking, backlinks, or graph features exist. SurrealDB's graph capabilities are completely untapped.

| Feature | Status | Priority |
|---------|--------|----------|
| Tags | Schema exists, API missing | High |
| Frontmatter parsing | Not implemented | High |
| Wiki-style links | Not implemented | High |
| Backlinks | Not implemented | Medium |
| Graph visualization | Not implemented | Medium |
| Collections/folders | Not implemented | Low |

---

### Current State

#### What Exists
- **Tags field**: Defined in `ContentMetadata` model (`api/menos/models.py:31`) as `list[str]`
- **Database column**: `tags` field exists in SurrealDB schema (`migrations/20260201-100000_initial_schema.surql:13`)
- **YouTube tags**: Extracted from YouTube API but stored only in metadata JSON, not in the `tags` field
- **Channel metadata**: `channel_id` and `channel_title` captured for YouTube videos

#### What's Missing
- No API endpoints to create, update, or filter by tags
- No frontmatter parsing for markdown files
- No link extraction from content
- No relationship/edge tables in SurrealDB
- No graph traversal queries
- No backlink tracking

---

### Gap 1: Tagging System

**Current Implementation**: Tags field exists but is orphaned - never populated, never queryable.

#### Problems
1. `POST /api/v1/content` doesn't accept tags in the request body
2. No `PATCH` endpoint to update tags after creation
3. `GET /api/v1/content` has no tag filtering
4. `POST /api/v1/search` ignores tags entirely
5. YouTube video tags are stored in MinIO JSON but not the database

#### User Expectations (from Obsidian/Logseq users)
- Add tags inline with `#tag` syntax or in frontmatter
- Browse all tags with counts
- Filter search results by tag
- Hierarchical tags (`#project/menos`, `#project/other`)
- Tag suggestions/autocomplete

#### Recommended Implementation

**Phase 1: API Support**
```
POST   /api/v1/content          - Accept tags[] in body
PATCH  /api/v1/content/{id}     - Update tags
GET    /api/v1/tags             - List all tags with counts
GET    /api/v1/content?tags=a,b - Filter by tags (AND/OR)
POST   /api/v1/search           - Add tags filter parameter
```

**Phase 2: Tag Extraction**
- Parse `#hashtags` from markdown content during ingestion
- Extract tags from YAML frontmatter
- Sync YouTube API tags to database `tags` field

**Phase 3: Tag Index**
```sql
DEFINE INDEX idx_content_tags ON content FIELDS tags;
```

**Effort Estimate**: Phase 1 is straightforward API work. Phase 2 requires markdown parsing.

---

### Gap 2: Bidirectional Linking

**Current Implementation**: None. Documents are isolated islands connected only by semantic similarity.

#### Problems
1. No wiki-link parsing (`[[document title]]` or `[[id]]`)
2. No URL extraction and resolution for internal links
3. No backlink tracking (what links TO this document)
4. No "related documents" based on explicit links
5. YouTube description URLs are extracted but not stored as relationships

#### User Expectations
- Wiki-style links: `[[Other Document]]` creates a relationship
- Backlinks panel: "These 5 documents link to this one"
- Forward links: "This document links to these 3 documents"
- Broken link detection
- Link suggestions based on content

#### Recommended Implementation

**Database Schema (leveraging SurrealDB graph features)**
```sql
-- Edge table for document links
DEFINE TABLE link SCHEMAFULL;
DEFINE FIELD source ON link TYPE record<content>;
DEFINE FIELD target ON link TYPE record<content>;
DEFINE FIELD link_text ON link TYPE string;        -- The anchor text
DEFINE FIELD link_type ON link TYPE string;        -- wiki, url, reference
DEFINE FIELD created_at ON link TYPE datetime DEFAULT time::now();

-- Indexes for efficient traversal
DEFINE INDEX idx_link_source ON link FIELDS source;
DEFINE INDEX idx_link_target ON link FIELDS target;
```

**API Endpoints**
```
GET /api/v1/content/{id}/links          - Forward links from this document
GET /api/v1/content/{id}/backlinks      - Documents linking TO this document
GET /api/v1/content/{id}/related        - Combined links + semantic similarity
```

**Link Extraction Service**
```python
# New service: api/menos/services/linking.py
class LinkExtractor:
    def extract_wiki_links(self, content: str) -> list[WikiLink]
    def extract_markdown_links(self, content: str) -> list[MarkdownLink]
    def resolve_link(self, link_text: str) -> str | None  # Returns content_id
```

**Effort Estimate**: Medium. Requires new service, schema migration, and ingestion pipeline changes.

---

### Gap 3: Graph Visualization

**Current Implementation**: None. SurrealDB supports graph queries but they're unused.

#### Problems
1. No visual representation of knowledge structure
2. No way to explore connections between documents
3. No clustering or community detection
4. Can't see "neighborhoods" around a topic

#### User Expectations (from Obsidian Graph View)
- Interactive node-link diagram
- Filter by tags, content type, date range
- Cluster by topic or tag
- Search within graph
- Zoom to local neighborhood of a document

#### Recommended Implementation

**Phase 1: Graph Data API**
```
GET /api/v1/graph                       - Full graph (nodes + edges)
GET /api/v1/graph/neighborhood/{id}     - 1-2 hop neighborhood
GET /api/v1/graph/clusters              - Topic clusters via embeddings
```

**Response Format**
```json
{
  "nodes": [
    {"id": "content:xxx", "title": "...", "type": "markdown", "tags": [...]}
  ],
  "edges": [
    {"source": "content:xxx", "target": "content:yyy", "type": "wiki_link"}
  ]
}
```

**Phase 2: Semantic Edges**
Add edges for documents with high embedding similarity (>0.85):
```sql
-- Could be computed periodically or on-demand
SELECT id, title,
  (SELECT id, title FROM content
   WHERE id != $parent.id
   AND vector::similarity::cosine(embedding, $parent.embedding) > 0.85
  ) AS similar
FROM content;
```

**Phase 3: Frontend Visualization**
- Use D3.js force-directed graph or Cytoscape.js
- Could be a separate static site or Obsidian plugin

**Effort Estimate**: Phase 1 API is straightforward. Phase 2 requires embedding aggregation (currently per-chunk). Phase 3 is frontend work.

---

### Gap 4: YouTube-Specific Relationships

**Current Implementation**: Videos are isolated. Channel/playlist metadata exists but isn't queryable.

#### Problems
1. Can't list all videos from a channel
2. No playlist support
3. No "related videos" feature
4. Description URLs not stored as relationships

#### Recommended Implementation

**Quick Wins**
```
GET /api/v1/youtube?channel_id=xxx      - Filter by channel
GET /api/v1/youtube/channels            - List channels with video counts
```

**Future: Playlist Support**
```sql
DEFINE TABLE playlist SCHEMAFULL;
DEFINE FIELD playlist_id ON playlist TYPE string;
DEFINE FIELD title ON playlist TYPE string;
DEFINE FIELD videos ON playlist TYPE array<record<content>>;
```

---

### Implementation Roadmap

#### Phase 1: Tag System (Foundation)
1. Add `tags` parameter to content upload endpoint
2. Add tag filtering to list/search endpoints
3. Create `/api/v1/tags` endpoint
4. Add tag index to SurrealDB
5. Parse frontmatter tags on markdown ingestion

#### Phase 2: Link Extraction
1. Create `link` edge table in SurrealDB
2. Build `LinkExtractor` service for wiki-links and markdown links
3. Extract and store links during content ingestion
4. Add backlinks/forward-links endpoints

#### Phase 3: Graph API
1. Create graph data endpoint returning nodes/edges
2. Add neighborhood query for local exploration
3. Consider semantic similarity edges

#### Phase 4: Visualization (Optional)
1. Build simple web UI for graph exploration
2. Or: Create Obsidian plugin that consumes the graph API

---

### Quick Wins (Can implement immediately)

1. **Expose tags in content upload** - Just add `tags` to the Pydantic model and pass through
2. **YouTube channel filtering** - Filter on `metadata.channel_id` in existing list endpoint
3. **Tag listing endpoint** - Simple aggregation query on existing data
4. **Frontmatter parsing** - Use `python-frontmatter` library during ingestion

---

### Dependencies & Considerations

- **Frontmatter parsing**: Add `python-frontmatter` to dependencies
- **Link resolution**: Need title-to-ID index for wiki-link resolution
- **Graph queries**: SurrealDB graph syntax differs from SQL - need to learn `->` and `<-` operators
- **Embedding aggregation**: Currently embeddings are per-chunk; graph view may need document-level embeddings
- **API versioning**: Consider `/api/v2/` for breaking changes to content model
