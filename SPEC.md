# WikiForge — Project Specification

## What Is WikiForge

WikiForge is a self-hosted, AI-powered document-to-wiki engine. It watches directories of source files (Markdown, Word, Excel, PDF), uses LLM processing to extract, classify, and restructure content, then publishes a navigable wiki with a full REST API.

## Core Value Proposition

Drop files into a folder → get a structured, cross-linked, searchable wiki — automatically kept in sync when files change.

## Target Users

- DevOps/infrastructure teams with scattered documentation
- Organizations with legacy docs in mixed formats
- Anyone who wants AI-organized knowledge bases from raw files

## Project Structure

This specification is split across the following documents. **Read them in order.**

| # | Document | Purpose |
|---|----------|---------|
| 1 | `SPEC.md` (this file) | Overview, goals, constraints |
| 2 | `ARCHITECTURE.md` | System design, components, data flow |
| 3 | `DATA_MODELS.md` | Database schemas, file formats, state machines |
| 4 | `LLM_PROVIDER.md` | Multi-provider LLM abstraction layer |
| 5 | `FILE_PARSERS.md` | File ingestion and content extraction |
| 6 | `PIPELINE.md` | Processing pipeline stages and job system |
| 7 | `WIKI_ENGINE.md` | Wiki generation, cross-linking, rendering |
| 8 | `API_SPEC.md` | REST API specification (OpenAPI-style) |
| 9 | `WEB_UI.md` | Frontend UI specification |
| 10 | `FILE_WATCHER.md` | Auto-sync and delta detection system |
| 11 | `CONFIG.md` | Configuration format and defaults |
| 12 | `DEVELOPMENT.md` | Setup, dev workflow, testing strategy |

## Functional Requirements

### FR-1: Project Management
- Users create projects, each with a name, source directory, and wiki output directory
- Projects are independent — separate processing pipelines, separate wiki namespaces
- Projects store configuration (LLM provider, watch interval, update mode)

### FR-2: File Ingestion
- Supported formats: `.md`, `.doc`, `.docx`, `.xlsx`, `.xls`, `.csv`, `.pdf`
- Files are discovered via filesystem watching (configurable poll interval)
- Each file is hashed (SHA-256) for change detection
- Files can also be uploaded via API

### FR-3: LLM Processing Pipeline
- 7-stage pipeline: Ingest → Parse → Extract → Classify → Generate → Cross-link → Publish
- Each stage produces observable output and logs
- Pipeline supports delta processing (only changed files re-processed)
- Pipeline supports full rebuild on demand
- Token usage is tracked per file, per stage, per project

### FR-4: Multi-Provider LLM Support
- Must support: Anthropic Claude, Google Gemini, Ollama (local models)
- Provider is configurable per project
- Abstraction layer normalizes request/response formats
- Fallback chain: if primary provider fails, try secondary

### FR-5: Wiki Output
- Wiki pages are generated as Markdown files with YAML frontmatter
- Cross-references between pages are auto-detected via semantic similarity
- Wiki has a navigable tree structure (auto-categorized)
- Wiki is served as rendered HTML via built-in web server
- Wiki content is exportable as static site

### FR-6: REST API
- Full CRUD for projects
- File upload and management
- Wiki content retrieval (Markdown, HTML, JSON)
- Semantic search across wiki pages
- Agent-friendly endpoints (RAG query, context retrieval)
- OpenAPI 3.1 spec served at `/api/openapi.json`
- Health check endpoint

### FR-7: Monitoring & Observability
- Real-time pipeline progress per project
- LLM token usage and cost tracking
- File watcher health status
- Processing logs with timestamps and severity
- Job queue depth and throughput

### FR-8: Auto-Update
- File watcher detects new/modified/deleted files
- Delta mode: only reprocess changed files and affected wiki pages
- Full mode: rebuild entire wiki on any change
- Configurable debounce to batch rapid changes

### FR-9: Web UI
- Dashboard with project overview and stats
- File browser showing source files and their processing status
- Wiki preview with navigation tree
- Pipeline visualization with real-time progress
- Monitoring dashboard with usage charts
- Project settings editor
- API explorer with interactive documentation

## Non-Functional Requirements

### NFR-1: Technology Stack
- **Language**: Python 3.11+
- **Web framework**: FastAPI
- **Task queue**: Celery with Redis broker (or fallback to in-process queue for single-node)
- **Database**: SQLite per project (via SQLAlchemy)
- **Frontend**: React (Vite) or static HTML/JS
- **File parsing**: python-docx, openpyxl, PyMuPDF, python-pptx
- **LLM SDKs**: anthropic, google-genai, ollama-python

### NFR-2: Performance
- File parsing should complete within 30 seconds per file (up to 50MB)
- LLM processing latency depends on provider but should timeout at 120s
- Wiki pages should render in under 200ms
- File watcher should detect changes within the configured poll interval

### NFR-3: Reliability
- Pipeline jobs must be idempotent — safe to retry on failure
- Partial pipeline failures should not corrupt existing wiki content
- File watcher should recover from filesystem errors gracefully

### NFR-4: Security
- API keys for LLM providers stored in environment variables or config file (never in DB)
- Optional API key authentication for WikiForge API
- No execution of content from parsed files

### NFR-5: Deployment
- Single-binary or single `docker-compose up` deployment
- All data stored in local filesystem (no external dependencies except Redis for queue)
- Optional: Redis-free mode using in-process task queue

## Glossary

| Term | Definition |
|------|-----------|
| Project | A named configuration binding a source directory to a wiki output |
| Source file | A document in a supported format placed in a project's source directory |
| Pipeline | The sequence of processing stages a file goes through |
| Job | A single unit of work in the pipeline (one stage for one file) |
| Wiki page | A generated Markdown file with metadata, part of the wiki output |
| Delta mode | Processing mode that only handles changed files |
| Provider | An LLM service (Claude, Gemini, Ollama) |
