# WikiForge — Data Models

## Database Design

Each project gets its own SQLite database at `{data_dir}/{project_slug}/wikiforge.db`. A global SQLite database at `{data_dir}/wikiforge_global.db` stores project-level records.

### Global Database

#### `projects` Table

```sql
CREATE TABLE projects (
    id              TEXT PRIMARY KEY,           -- UUID4
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL UNIQUE,        -- URL-safe name
    source_dir      TEXT NOT NULL,               -- Absolute path to source directory
    output_dir      TEXT NOT NULL,               -- Absolute path to wiki output
    llm_provider    TEXT NOT NULL DEFAULT 'anthropic',  -- 'anthropic' | 'gemini' | 'ollama'
    llm_model       TEXT NOT NULL DEFAULT 'claude-sonnet-4-20250514',
    watch_interval  INTEGER NOT NULL DEFAULT 10, -- Seconds between filesystem polls
    update_mode     TEXT NOT NULL DEFAULT 'delta', -- 'delta' | 'full'
    status          TEXT NOT NULL DEFAULT 'created', -- 'created' | 'active' | 'paused' | 'error'
    wiki_url        TEXT,                        -- Populated after first build
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### Per-Project Database

#### `source_files` Table

```sql
CREATE TABLE source_files (
    id              TEXT PRIMARY KEY,           -- UUID4
    filename        TEXT NOT NULL,              -- Original filename
    filepath        TEXT NOT NULL,              -- Relative path from source_dir
    file_extension  TEXT NOT NULL,              -- '.md', '.docx', '.pdf', etc.
    file_size       INTEGER NOT NULL,           -- Bytes
    content_hash    TEXT NOT NULL,              -- SHA-256 of file contents
    status          TEXT NOT NULL DEFAULT 'pending',
    -- Status values: pending | ingested | parsed | extracted | classified
    --                | generated | crosslinked | published | error | deleted
    error_message   TEXT,                       -- Error details if status='error'
    discovered_at   TEXT NOT NULL DEFAULT (datetime('now')),
    processed_at    TEXT,                       -- Timestamp of last successful publish
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_source_files_status ON source_files(status);
CREATE INDEX idx_source_files_hash ON source_files(content_hash);
```

#### `parsed_content` Table

```sql
CREATE TABLE parsed_content (
    id              TEXT PRIMARY KEY,
    source_file_id  TEXT NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
    content_text    TEXT NOT NULL,              -- Full extracted text
    content_structured JSON,                    -- Structured representation (headings, tables, etc.)
    metadata        JSON,                       -- File-specific metadata (author, dates, etc.)
    section_count   INTEGER DEFAULT 0,
    word_count      INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_file_id)
);
```

#### `extracted_data` Table

```sql
CREATE TABLE extracted_data (
    id              TEXT PRIMARY KEY,
    source_file_id  TEXT NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
    summary         TEXT,                       -- LLM-generated summary
    topics          JSON,                       -- Array of topic strings
    entities        JSON,                       -- Array of {name, type} objects
    key_points      JSON,                       -- Array of key point strings
    raw_llm_output  TEXT,                       -- Full LLM response for debugging
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_file_id)
);
```

#### `classifications` Table

```sql
CREATE TABLE classifications (
    id              TEXT PRIMARY KEY,
    source_file_id  TEXT NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
    category        TEXT NOT NULL,              -- Top-level wiki category
    subcategory     TEXT,                       -- Optional subcategory
    page_title      TEXT NOT NULL,              -- Suggested wiki page title
    page_slug       TEXT NOT NULL,              -- URL-safe page identifier
    confidence      REAL DEFAULT 0.0,           -- LLM confidence score 0-1
    raw_llm_output  TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_file_id)
);
```

#### `wiki_pages` Table

```sql
CREATE TABLE wiki_pages (
    id              TEXT PRIMARY KEY,
    slug            TEXT NOT NULL UNIQUE,        -- URL path segment
    title           TEXT NOT NULL,
    category        TEXT NOT NULL,
    subcategory     TEXT,
    content_md      TEXT NOT NULL,               -- Generated Markdown content
    content_html    TEXT,                         -- Rendered HTML (cached)
    frontmatter     JSON,                        -- YAML frontmatter as JSON
    source_file_ids JSON NOT NULL,               -- Array of contributing source file IDs
    word_count      INTEGER DEFAULT 0,
    embedding       BLOB,                        -- Page embedding vector (numpy bytes)
    cross_refs      JSON,                        -- Array of {slug, title, score} objects
    version         INTEGER NOT NULL DEFAULT 1,  -- Incremented on update
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_wiki_pages_category ON wiki_pages(category);
CREATE INDEX idx_wiki_pages_slug ON wiki_pages(slug);
```

#### `jobs` Table

```sql
CREATE TABLE jobs (
    id              TEXT PRIMARY KEY,
    source_file_id  TEXT NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
    stage           TEXT NOT NULL,              -- Pipeline stage name
    status          TEXT NOT NULL DEFAULT 'queued',
    -- Status values: queued | running | completed | failed | cancelled
    priority        INTEGER NOT NULL DEFAULT 5, -- 1 (highest) to 10 (lowest)
    attempt         INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 3,
    error_message   TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_stage ON jobs(stage);
CREATE INDEX idx_jobs_source_file ON jobs(source_file_id);
```

#### `llm_usage` Table

```sql
CREATE TABLE llm_usage (
    id              TEXT PRIMARY KEY,
    job_id          TEXT REFERENCES jobs(id),
    provider        TEXT NOT NULL,              -- 'anthropic' | 'gemini' | 'ollama'
    model           TEXT NOT NULL,
    stage           TEXT NOT NULL,              -- Which pipeline stage
    tokens_in       INTEGER NOT NULL DEFAULT 0,
    tokens_out      INTEGER NOT NULL DEFAULT 0,
    latency_ms      INTEGER NOT NULL DEFAULT 0,
    cost_usd        REAL DEFAULT 0.0,           -- Estimated cost
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_llm_usage_created ON llm_usage(created_at);
```

## File State Machine

```
                     ┌──────────────────────────────────────────────┐
                     │                                              │
   ┌─────────┐   ┌──┴──────┐   ┌────────┐   ┌───────────┐   ┌────┴──────┐
   │ PENDING  │──▶│INGESTED │──▶│ PARSED │──▶│ EXTRACTED │──▶│CLASSIFIED │
   └─────────┘   └─────────┘   └────────┘   └───────────┘   └───────────┘
        │                                                         │
        │              ┌─────────────┐   ┌────────────┐   ┌──────┴────┐
        │              │ CROSSLINKED │◀──│ GENERATED  │◀──┘           │
        │              └──────┬──────┘   └────────────┘              │
        │                     │                                      │
        │              ┌──────┴──────┐                               │
        │              │  PUBLISHED  │                               │
        │              └─────────────┘                               │
        │                                                            │
        │    ┌─────────┐                                             │
        ├───▶│  ERROR   │◀── (any stage can fail) ◀──────────────────┘
        │    └─────────┘
        │    ┌─────────┐
        └───▶│ DELETED  │◀── (file removed from source dir)
             └─────────┘
```

On re-processing (file modified), status resets to `PENDING` and goes through the pipeline again.

## Wiki Page Frontmatter Format

Each generated wiki page is a Markdown file with YAML frontmatter:

```yaml
---
title: "Kubernetes Deployment Guide"
slug: "kubernetes-deployment"
category: "Infrastructure"
subcategory: "Container Orchestration"
sources:
  - file: "k8s-deployment-guide.md"
    hash: "a1b2c3d4..."
  - file: "infrastructure-specs.docx"
    hash: "e5f6g7h8..."
topics:
  - "kubernetes"
  - "deployment"
  - "container orchestration"
cross_refs:
  - slug: "nginx-load-balancing"
    title: "Nginx Load Balancing"
    relevance: 0.87
  - slug: "oci-configuration"
    title: "OCI Configuration"
    relevance: 0.72
generated_by: "anthropic/claude-sonnet-4-20250514"
version: 3
word_count: 1240
created_at: "2026-04-10T14:32:08Z"
updated_at: "2026-04-10T15:01:22Z"
---

# Kubernetes Deployment Guide

Content here...
```

## Structured Content Format (Internal)

The `content_structured` field in `parsed_content` uses this JSON schema:

```json
{
  "type": "document",
  "title": "Original Document Title",
  "sections": [
    {
      "heading": "Section Title",
      "level": 1,
      "content": "Plain text content of the section...",
      "children": [
        {
          "heading": "Subsection",
          "level": 2,
          "content": "Subsection text..."
        }
      ]
    }
  ],
  "tables": [
    {
      "caption": "Server Inventory",
      "headers": ["Hostname", "IP", "Role"],
      "rows": [
        ["srv-01", "10.0.1.1", "K8s master"],
        ["srv-02", "10.0.1.2", "K8s worker"]
      ]
    }
  ],
  "metadata": {
    "author": "John Doe",
    "created": "2026-01-15",
    "modified": "2026-03-20",
    "page_count": 12
  }
}
```

## Navigation Tree Format

The wiki navigation tree is a JSON structure stored at `{output_dir}/tree.json`:

```json
{
  "project": "OSPD Documentation",
  "generated_at": "2026-04-10T15:01:22Z",
  "categories": [
    {
      "name": "Infrastructure",
      "slug": "infrastructure",
      "children": [
        {
          "name": "Kubernetes Deployment",
          "slug": "kubernetes-deployment",
          "sources": 2,
          "word_count": 1240
        },
        {
          "name": "Nginx Load Balancing",
          "slug": "nginx-load-balancing",
          "sources": 1,
          "word_count": 890
        }
      ]
    },
    {
      "name": "Security",
      "slug": "security",
      "children": []
    }
  ]
}
```

## Pydantic Schemas (API Layer)

### ProjectCreate

```python
class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    source_dir: str = Field(..., description="Absolute path to source directory")
    output_dir: str = Field(..., description="Absolute path to wiki output directory")
    llm_provider: Literal["anthropic", "gemini", "ollama"] = "anthropic"
    llm_model: str = "claude-sonnet-4-20250514"
    watch_interval: int = Field(10, ge=1, le=3600)
    update_mode: Literal["delta", "full"] = "delta"
```

### ProjectResponse

```python
class ProjectResponse(BaseModel):
    id: str
    name: str
    slug: str
    source_dir: str
    output_dir: str
    llm_provider: str
    llm_model: str
    watch_interval: int
    update_mode: str
    status: str
    wiki_url: str | None
    file_count: int
    page_count: int
    created_at: datetime
    updated_at: datetime
```

### FileResponse

```python
class FileResponse(BaseModel):
    id: str
    filename: str
    filepath: str
    file_extension: str
    file_size: int
    status: str
    error_message: str | None
    wiki_page_slug: str | None
    discovered_at: datetime
    processed_at: datetime | None
```

### WikiPageResponse

```python
class WikiPageResponse(BaseModel):
    slug: str
    title: str
    category: str
    subcategory: str | None
    content_md: str          # When format=md
    content_html: str | None # When format=html
    sources: list[str]
    cross_refs: list[CrossRef]
    version: int
    word_count: int
    updated_at: datetime

class CrossRef(BaseModel):
    slug: str
    title: str
    relevance: float
```

### PipelineStatus

```python
class PipelineStatus(BaseModel):
    project_id: str
    total_files: int
    files_by_status: dict[str, int]
    active_jobs: list[JobStatus]
    progress_pct: float
    eta_seconds: int | None

class JobStatus(BaseModel):
    id: str
    source_file: str
    stage: str
    status: str
    attempt: int
    started_at: datetime | None
```

### AgentQuery / AgentResponse

```python
class AgentQuery(BaseModel):
    question: str
    project_id: str
    format: Literal["markdown", "html", "text"] = "markdown"
    include_sources: bool = True
    max_results: int = Field(5, ge=1, le=20)

class AgentResponse(BaseModel):
    answer: str
    sources: list[SourceReference]
    confidence: float
    wiki_pages: list[str]  # Slugs of relevant pages

class SourceReference(BaseModel):
    filename: str
    wiki_page: str | None
    relevance: float
```
