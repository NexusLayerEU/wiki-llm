# WikiForge — Architecture

## System Overview

WikiForge is a monolithic Python application with three logical layers and an async job system.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Web UI (React/Vite)                      │
├─────────────────────────────────────────────────────────────────┤
│                     FastAPI Application                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ Project  │  │  File    │  │  Wiki    │  │   Agent/RAG    │  │
│  │  Router  │  │  Router  │  │  Router  │  │    Router      │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └───────┬────────┘  │
│       │              │              │                │           │
│  ┌────┴──────────────┴──────────────┴────────────────┴────────┐ │
│  │                    Service Layer                            │ │
│  │  ProjectService · FileService · PipelineService             │ │
│  │  WikiService · SearchService · MonitoringService            │ │
│  └──────────────┬───────────────────────────────────────┬─────┘ │
│                 │                                       │       │
│  ┌──────────────┴──────────┐   ┌────────────────────────┴────┐  │
│  │      Job Queue          │   │     LLM Provider Layer      │  │
│  │  (Celery/Redis or       │   │  ┌────────┐ ┌──────┐       │  │
│  │   InProcessQueue)       │   │  │Claude  │ │Gemini│       │  │
│  └──────────────┬──────────┘   │  ├────────┤ ├──────┤       │  │
│                 │              │  │Ollama  │ │Custom│       │  │
│  ┌──────────────┴──────────┐   │  └────────┘ └──────┘       │  │
│  │   Pipeline Executor     │   └─────────────────────────────┘  │
│  │  Ingest → Parse →       │                                    │
│  │  Extract → Classify →   │                                    │
│  │  Generate → CrossLink → │                                    │
│  │  Publish                │                                    │
│  └─────────────────────────┘                                    │
├─────────────────────────────────────────────────────────────────┤
│                    Storage Layer                                 │
│  ┌───────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │  SQLite   │  │  File System │  │  Embedding Store         │  │
│  │ (per proj)│  │  (source +   │  │  (SQLite + numpy or      │  │
│  │           │  │   wiki out)  │  │   chromadb)              │  │
│  └───────────┘  └──────────────┘  └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
         ▲
         │  Filesystem events
┌────────┴────────────────────────────────────────────────────────┐
│                    File Watcher Daemon                           │
│  (watchdog / polling per project source directory)              │
└─────────────────────────────────────────────────────────────────┘
```

## Directory Layout

```
wikiforge/
├── pyproject.toml              # Project metadata, dependencies
├── Dockerfile
├── docker-compose.yml
├── wikiforge/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py               # Configuration loading
│   ├── models/                 # SQLAlchemy models
│   │   ├── __init__.py
│   │   ├── project.py
│   │   ├── source_file.py
│   │   ├── job.py
│   │   ├── wiki_page.py
│   │   └── llm_usage.py
│   ├── schemas/                # Pydantic request/response schemas
│   │   ├── __init__.py
│   │   ├── project.py
│   │   ├── file.py
│   │   ├── wiki.py
│   │   ├── pipeline.py
│   │   └── agent.py
│   ├── routers/                # FastAPI route handlers
│   │   ├── __init__.py
│   │   ├── projects.py
│   │   ├── files.py
│   │   ├── wiki.py
│   │   ├── pipeline.py
│   │   ├── monitoring.py
│   │   └── agent.py
│   ├── services/               # Business logic
│   │   ├── __init__.py
│   │   ├── project_service.py
│   │   ├── file_service.py
│   │   ├── pipeline_service.py
│   │   ├── wiki_service.py
│   │   ├── search_service.py
│   │   └── monitoring_service.py
│   ├── llm/                    # LLM provider abstraction
│   │   ├── __init__.py
│   │   ├── base.py             # Abstract base provider
│   │   ├── registry.py         # Provider registry + factory
│   │   ├── claude.py           # Anthropic Claude provider
│   │   ├── gemini.py           # Google Gemini provider
│   │   ├── ollama.py           # Ollama local provider
│   │   └── prompts/            # Prompt templates (Jinja2)
│   │       ├── extract.j2
│   │       ├── classify.j2
│   │       ├── generate_wiki.j2
│   │       ├── crosslink.j2
│   │       └── rag_query.j2
│   ├── parsers/                # File format parsers
│   │   ├── __init__.py
│   │   ├── base.py             # Abstract parser
│   │   ├── registry.py         # Extension-to-parser mapping
│   │   ├── markdown.py
│   │   ├── docx.py
│   │   ├── doc.py              # Legacy .doc via LibreOffice conversion
│   │   ├── xlsx.py
│   │   ├── csv_parser.py
│   │   └── pdf.py
│   ├── pipeline/               # Processing pipeline
│   │   ├── __init__.py
│   │   ├── executor.py         # Pipeline orchestrator
│   │   ├── stages.py           # Stage definitions
│   │   └── job_queue.py        # Queue abstraction (Celery or in-process)
│   ├── watcher/                # File system watcher
│   │   ├── __init__.py
│   │   ├── daemon.py           # Watcher daemon
│   │   └── delta.py            # Change detection (hash-based)
│   ├── wiki/                   # Wiki generation engine
│   │   ├── __init__.py
│   │   ├── generator.py        # Markdown generation
│   │   ├── crosslinker.py      # Cross-reference detection
│   │   ├── tree.py             # Navigation tree builder
│   │   └── renderer.py         # Markdown → HTML rendering
│   └── static/                 # Built frontend assets
│       └── ...
├── frontend/                   # React frontend source
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── App.tsx
│       ├── pages/
│       ├── components/
│       └── api/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── prompts/                    # Prompt templates (alternative flat layout)
└── docs/                       # These specification documents
```

## Component Responsibilities

### FastAPI Application (`main.py`)
- Mounts routers, initializes services
- Serves static frontend assets at `/`
- Serves wiki HTML at `/wiki/{project_slug}/`
- CORS configuration for development
- Lifespan events: start file watchers, initialize DB

### Service Layer
Each service encapsulates domain logic and is injected into routers via FastAPI dependency injection.

| Service | Responsibility |
|---------|---------------|
| `ProjectService` | CRUD projects, validate directories, manage project lifecycle |
| `FileService` | Track source files, compute hashes, manage file metadata |
| `PipelineService` | Enqueue jobs, track pipeline progress, report status |
| `WikiService` | Read/write wiki pages, build navigation tree, render HTML |
| `SearchService` | Semantic search over wiki pages using embeddings |
| `MonitoringService` | Aggregate metrics: token usage, job stats, watcher health |

### LLM Provider Layer (`llm/`)
Abstraction over multiple LLM providers. See `LLM_PROVIDER.md` for full spec.

### Parsers (`parsers/`)
Format-specific content extractors. See `FILE_PARSERS.md` for full spec.

### Pipeline (`pipeline/`)
Job-based processing pipeline. See `PIPELINE.md` for full spec.

### File Watcher (`watcher/`)
Filesystem monitoring daemon. See `FILE_WATCHER.md` for full spec.

## Data Flow

### Happy Path: New File Detected

```
1. File watcher detects new file in /data/project/source/
2. FileService computes SHA-256 hash, creates SourceFile record (status=PENDING)
3. PipelineService creates Job records for each stage
4. Job Queue picks up INGEST job:
   a. Copy file to working directory
   b. Update SourceFile status → INGESTED
5. Job Queue picks up PARSE job:
   a. ParserRegistry selects parser by extension
   b. Parser extracts structured content (text, headings, tables, metadata)
   c. Store ParsedContent in DB
   d. Update status → PARSED
6. Job Queue picks up EXTRACT job:
   a. LLM call: extract key topics, entities, summary from parsed content
   b. Store ExtractedData in DB
   c. Update status → EXTRACTED
7. Job Queue picks up CLASSIFY job:
   a. LLM call: determine wiki category and page title
   b. Store classification result
   c. Update status → CLASSIFIED
8. Job Queue picks up GENERATE job:
   a. LLM call: generate wiki-formatted Markdown page
   b. Write .md file with YAML frontmatter to wiki output directory
   c. Create WikiPage record
   d. Update status → GENERATED
9. Job Queue picks up CROSSLINK job:
   a. Compute embedding for new page
   b. Find similar existing pages (cosine similarity > threshold)
   c. Insert cross-reference links into affected pages
   d. Update status → CROSSLINKED
10. Job Queue picks up PUBLISH job:
    a. Rebuild navigation tree
    b. Render updated pages to HTML
    c. Update wiki index
    d. Update status → PUBLISHED
```

### Delta Update: Existing File Modified

```
1. File watcher detects modified file (hash changed)
2. FileService updates hash, sets status → PENDING
3. PipelineService creates new Job records
4. Same pipeline as above, but:
   - GENERATE stage overwrites existing wiki page
   - CROSSLINK stage re-evaluates all cross-references
   - PUBLISH stage does incremental rebuild
```

### File Deleted

```
1. File watcher detects missing file
2. FileService marks SourceFile as DELETED
3. WikiService removes associated wiki page(s)
4. CrossLinker removes references to deleted page from other pages
5. WikiService rebuilds navigation tree
```

## Concurrency Model

- **FastAPI**: async handlers for API routes (non-blocking I/O)
- **Pipeline jobs**: executed by Celery workers (or in-process thread pool)
- **File watcher**: separate daemon thread per project
- **LLM calls**: async where provider SDK supports it, otherwise run in thread executor
- **Database**: SQLite with WAL mode for concurrent reads; write serialization via queue

## Error Handling Strategy

| Error Type | Handling |
|-----------|---------|
| File parse failure | Mark file as ERROR, log details, skip in pipeline, continue other files |
| LLM call failure | Retry up to 3 times with exponential backoff, then mark job FAILED |
| LLM rate limit | Respect Retry-After header, pause queue for that provider |
| File watcher error | Log and restart watcher after backoff |
| Database error | Transaction rollback, retry once |
| Invalid file format | Mark as UNSUPPORTED, log, skip |

## Deployment Architectures

### Minimal (Single Process)
- Everything runs in one Python process
- In-process task queue (no Redis needed)
- SQLite for storage
- Suitable for small teams, < 100 files per project

### Standard (Docker Compose)
```yaml
services:
  wikiforge:     # FastAPI + frontend
  worker:        # Celery worker(s)
  redis:         # Job queue broker
  # Optional:
  ollama:        # Local LLM inference
```

### Production
- Multiple Celery workers for parallel processing
- Redis Sentinel or cluster for HA
- Nginx reverse proxy with TLS
- Volume mounts for source/output directories
