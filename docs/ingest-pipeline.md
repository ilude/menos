# Ingest Pipeline

## Overview

Menos supports two content ingest paths: YouTube video transcripts and general content uploads (markdown, text). Both paths converge into a shared pipeline that stores files in MinIO, persists metadata to SurrealDB, generates vector embeddings, and triggers background classification.

## Entry Points

```mermaid
flowchart LR
    A["POST /api/v1/youtube/ingest"] --> D[Ingest Pipeline]
    C["POST /api/v1/content"] --> D
    E["scripts/ingest_videos.py"] -->|"Signed HTTP"| A

    style A fill:#4a9eff,color:#fff
    style C fill:#6c63ff,color:#fff
    style E fill:#ff9f43,color:#fff
```

| Entry Point | Use Case |
|---|---|
| `POST /youtube/ingest` | Ingest by YouTube URL — server fetches transcript (with optional Webshare proxy) and metadata |
| `POST /content` | General file upload (markdown, text, PDF) |
| `ingest_videos.py` | Batch ingestion from `data/youtube-videos.txt` via `/youtube/ingest` |

## Complete Pipeline Flow

```mermaid
flowchart TD
    subgraph Entry["Entry Points"]
        YI["YouTube Ingest\n(URL)"]
        CU["Content Upload\n(file)"]
    end

    subgraph Fetch["Stage 1: Fetch & Extract"]
        VID["Extract Video ID\n(regex validation)"]
        TF["Fetch Transcript\n(youtube-transcript-api)"]
        MF["Fetch Metadata\n(YouTube Data API v3)"]
        FP["Parse Frontmatter\n(YAML extraction)"]
    end

    subgraph Store["Stage 2: Persist"]
        MINIO["Upload to MinIO\n(transcript.txt + metadata.json)"]
        SURREAL["Create content record\n(SurrealDB)"]
    end

    subgraph Process["Stage 3: Process"]
        LINK["Extract Links\n(wiki-links + markdown)"]
        CHUNK["Chunk Text\n(512 chars, 50 overlap)"]
        EMBED["Generate Embeddings\n(Ollama mxbai-embed-large)"]
        STORE_CHUNKS["Store Chunks\n(SurrealDB)"]
    end

    subgraph Classify["Stage 4: Background Classification"]
        PROFILE["Build Interest Profile\n(top topics, tags, channels)"]
        LLM["LLM Classification\n(labels, tier, score, summary)"]
        DEDUP["Deduplicate Labels\n(Levenshtein distance ≤ 2)"]
        SAVE["Update Content Record\n(tier, score, labels, summary)"]
    end

    RESPONSE["Return HTTP Response\n(content ID, chunks created)"]

    YI --> VID --> TF
    TF --> MF
    CU --> FP --> MINIO

    MF -->|"non-blocking\n(continues on failure)"| MINIO
    TF --> MINIO
    MINIO --> SURREAL

    SURREAL --> LINK
    SURREAL --> CHUNK
    LINK -->|"markdown only"| SURREAL
    CHUNK --> EMBED --> STORE_CHUNKS

    STORE_CHUNKS --> RESPONSE

    SURREAL -.->|"fire-and-forget\nasync task"| PROFILE
    PROFILE --> LLM --> DEDUP --> SAVE

    style Entry fill:#f0f4ff,stroke:#4a9eff
    style Fetch fill:#fff3e6,stroke:#ff9f43
    style Store fill:#e8f5e9,stroke:#4caf50
    style Process fill:#f3e5f5,stroke:#9c27b0
    style Classify fill:#fff8e1,stroke:#ffc107
    style RESPONSE fill:#4caf50,color:#fff
```

## Stage Details

### Stage 1: Fetch & Extract

#### YouTube Ingest Path

```mermaid
sequenceDiagram
    participant Client
    participant Router as youtube.py router
    participant YTSvc as YouTubeService
    participant MetaSvc as YouTubeMetadataService

    Client->>Router: POST /youtube/ingest {url}
    Router->>YTSvc: extract_video_id(url)
    YTSvc-->>Router: video_id

    Router->>YTSvc: fetch_transcript(video_id)
    Note over YTSvc: Optional Webshare proxy<br/>for IP-blocked regions
    YTSvc-->>Router: YouTubeTranscript

    Router->>MetaSvc: fetch_metadata(video_id)
    Note over MetaSvc: YouTube Data API v3<br/>(non-blocking, skipped on failure)
    MetaSvc-->>Router: YouTubeMetadata | None
```

**Transcript output:**
- `full_text` — plain text (all segments joined)
- `timestamped_text` — each segment prefixed with `[MM:SS]`

**Metadata extracted:** title, description, channel info, duration, view count, likes, tags, thumbnails, published date, description URLs.

#### Content Upload Path

```mermaid
sequenceDiagram
    participant Client
    participant Router as content.py router
    participant FP as FrontmatterParser

    Client->>Router: POST /content {file, content_type, tags}
    Router->>FP: parse(file_content)
    FP-->>Router: title, tags, body
    Note over Router: Merge frontmatter tags<br/>with query param tags<br/>(deduplicated)
```

### Stage 2: Persist to Storage

```mermaid
sequenceDiagram
    participant Router
    participant MinIO as MinIOStorage
    participant DB as SurrealDBRepository

    Router->>MinIO: upload(path, stream, mime_type)
    Note over MinIO: YouTube: 2 files<br/>transcript.txt + metadata.json

    Router->>DB: create_content(ContentMetadata)
    Note over DB: Auto-generates RecordID<br/>Sets created_at, updated_at
    DB-->>Router: content record with ID
```

**MinIO file layout:**
```
youtube/{video_id}/transcript.txt     # Timestamped transcript
youtube/{video_id}/metadata.json      # Rich metadata (JSON)
youtube/{video_id}/summary.md         # Classification summary (added later)
content/{id}/original_filename        # General uploads
```

### Stage 3: Process

#### Link Extraction (Markdown Only)

```mermaid
flowchart LR
    MD["Markdown Content"] --> STRIP["Strip Code Blocks"]
    STRIP --> WIKI["Extract Wiki-Links\n[[Title]] or [[Title|text]]"]
    STRIP --> MKDN["Extract Markdown Links\n[text](path)"]
    WIKI --> RESOLVE["Resolve by Title Match\n(SurrealDB lookup)"]
    MKDN -->|"skip external URLs"| RESOLVE
    RESOLVE --> STORE["Store link records\n(source → target)"]
    RESOLVE -->|"unresolved"| NULL["Store with target = NULL"]
```

#### Chunking & Embedding

```mermaid
flowchart TD
    TEXT["Full Text Content"] --> CHUNK["ChunkingService\n(512 chars, 50 overlap)"]
    CHUNK --> C1["Chunk 0"]
    CHUNK --> C2["Chunk 1"]
    CHUNK --> CN["Chunk N"]

    C1 --> E1["Ollama\nmxbai-embed-large"]
    C2 --> E2["Ollama\nmxbai-embed-large"]
    CN --> EN["Ollama\nmxbai-embed-large"]

    E1 --> V1["1024-dim vector"]
    E2 --> V2["1024-dim vector"]
    EN --> VN["1024-dim vector"]

    V1 --> DB["SurrealDB chunk table\n(MTREE cosine index)"]
    V2 --> DB
    VN --> DB
```

- Chunks are word-boundary aware (breaks at last space before 512-char limit)
- Overlap of 50 characters ensures context continuity across boundaries
- Embedding failures are non-fatal — `embedding` set to `NULL`
- Only runs when `generate_embeddings=true` in the request

### Stage 4: Background Classification

```mermaid
flowchart TD
    TRIGGER["Content Created\n(≥ min_content_length)"] --> STATUS["Set classification_status = pending"]
    STATUS --> PROFILE["Build Interest Profile"]

    subgraph Profile["Interest Profiling (cached 5 min)"]
        TOPICS["Top Topics\n(from content_entity edges)"]
        TAGS["Top Tags\n(recency-weighted)"]
        CHANNELS["Top YouTube Channels\n(by video count)"]
    end

    PROFILE --> TOPICS & TAGS & CHANNELS
    TOPICS & TAGS & CHANNELS --> PROMPT["Construct LLM Prompt\n(content truncated to 10k chars)"]

    PROMPT --> LLM["LLM Call\n(configurable provider)"]
    LLM -->|"retry: 3x\nbackoff: 1s, 2s, 4s"| PARSE["Parse JSON Response"]

    PARSE --> DEDUP["Deduplicate Labels\n(Levenshtein ≤ 2 → existing label)"]
    DEDUP --> CLAMP["Validate & Clamp\n(score: 1-100, tier: S/A/B/C/D)"]
    CLAMP --> SAVE["Update Content Record"]
    CLAMP --> SUMMARY["Save summary.md to MinIO"]

    LLM -->|"all retries failed"| FAIL["Set classification_status = failed"]

    style TRIGGER fill:#4caf50,color:#fff
    style FAIL fill:#f44336,color:#fff
```

**Classification output:**
| Field | Description |
|---|---|
| `labels` | Topic labels (deduplicated against existing) |
| `tier` | Quality tier: S, A, B, C, or D |
| `quality_score` | 1–100 numeric score |
| `tier_explanation` | Why this tier was assigned |
| `score_explanation` | Why this score was assigned |
| `summary` | Markdown-formatted content summary |
| `model` | Which LLM produced the result |

## Response Timeline

```mermaid
gantt
    title Ingest Response Timeline
    dateFormat X
    axisFormat %s

    section Synchronous
    Extract Video ID         :vid, 0, 1
    Fetch Transcript         :tf, 1, 4
    Fetch Metadata           :mf, 4, 6
    Upload to MinIO          :mu, 6, 8
    Create SurrealDB Record  :sr, 8, 9
    Chunk Text               :ch, 9, 10
    Generate Embeddings      :em, 10, 40
    HTTP Response Returned   :milestone, 40, 40

    section Async Background
    Build Interest Profile   :ip, 40, 45
    LLM Classification       :lc, 45, 80
    Save Classification      :sc, 80, 82
```

The HTTP response returns after embedding generation completes. Classification runs entirely in the background and does not block the response.

## Configuration

| Variable | Stage | Description |
|---|---|---|
| `WEBSHARE_PROXY_USERNAME/PASSWORD` | Fetch | Optional proxy for transcript fetching |
| `YOUTUBE_API_KEY` | Fetch | YouTube Data API v3 for metadata |
| `MINIO_URL/ACCESS_KEY/SECRET_KEY/BUCKET` | Persist | MinIO connection |
| `SURREALDB_URL/NAMESPACE/DATABASE/USER/PASSWORD` | Persist | SurrealDB connection |
| `OLLAMA_URL` | Embed | Ollama server URL |
| `OLLAMA_MODEL` | Embed | Embedding model (mxbai-embed-large) |
| `CLASSIFICATION_ENABLED` | Classify | Enable/disable background classification |
| `CLASSIFICATION_MIN_CONTENT_LENGTH` | Classify | Minimum chars to trigger classification |
| `CLASSIFICATION_MAX_NEW_LABELS` | Classify | Max new labels created per content |
| `AGENT_SYNTHESIS_PROVIDER` | Classify | LLM provider (ollama/openai/anthropic/openrouter) |
| `AGENT_SYNTHESIS_MODEL` | Classify | LLM model name |

## Error Handling

| Failure | Impact | Behavior |
|---|---|---|
| Transcript fetch fails | Fatal | Returns HTTP error, ingest aborted |
| Metadata fetch fails | Non-fatal | Continues with generic title |
| MinIO upload fails | Fatal | Returns HTTP error |
| SurrealDB write fails | Fatal | Returns HTTP error |
| Embedding generation fails | Non-fatal | Chunk stored with `embedding = NULL` |
| Classification LLM fails | Non-fatal | Status set to `failed`, no classification data |
| Classification cancelled (shutdown) | Non-fatal | Status set to `failed`, logged as warning |
