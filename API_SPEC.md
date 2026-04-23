# WikiForge — API Specification

## Base URL

```
http://localhost:8000/api/v1
```

## Authentication

Optional API key authentication via header:
```
Authorization: Bearer <api_key>
```

Configured in `config.yaml` under `api.auth_key`. If not set, API is open.

## Content Negotiation

Wiki content endpoints accept `format` query parameter:
- `md` — Raw Markdown (default)
- `html` — Rendered HTML
- `json` — Structured JSON with metadata

---

## Endpoints

### Projects

#### `GET /projects`
List all projects.

**Response** `200 OK`
```json
{
  "projects": [
    {
      "id": "uuid",
      "name": "OSPD Documentation",
      "slug": "ospd-docs",
      "source_dir": "/data/ospd/source",
      "output_dir": "/data/ospd/wiki-output",
      "llm_provider": "anthropic",
      "llm_model": "claude-sonnet-4-20250514",
      "status": "active",
      "wiki_url": "http://localhost:8000/wiki/ospd-docs/",
      "file_count": 42,
      "page_count": 38,
      "created_at": "2026-04-01T10:00:00Z",
      "updated_at": "2026-04-10T14:32:00Z"
    }
  ]
}
```

#### `POST /projects`
Create a new project.

**Request**
```json
{
  "name": "OSPD Documentation",
  "source_dir": "/data/ospd/source",
  "output_dir": "/data/ospd/wiki-output",
  "llm_provider": "anthropic",
  "llm_model": "claude-sonnet-4-20250514",
  "watch_interval": 10,
  "update_mode": "delta"
}
```

**Response** `201 Created`
```json
{
  "id": "uuid",
  "name": "OSPD Documentation",
  "slug": "ospd-docs",
  "wiki_url": null,
  "status": "created"
}
```

**Errors**
- `400` — Invalid source_dir or output_dir (not absolute path, doesn't exist)
- `409` — Project with same slug already exists

#### `GET /projects/{project_id}`
Get project details.

#### `PUT /projects/{project_id}`
Update project configuration.

#### `DELETE /projects/{project_id}`
Delete project and all associated data.

**Response** `204 No Content`

#### `POST /projects/{project_id}/activate`
Start file watching and processing for this project.

**Response** `200 OK`
```json
{"status": "active", "watcher_started": true}
```

#### `POST /projects/{project_id}/pause`
Pause file watching and processing.

#### `POST /projects/{project_id}/rebuild`
Trigger full rebuild of wiki from all source files.

**Response** `202 Accepted`
```json
{"message": "Full rebuild started", "total_files": 42}
```

---

### Files

#### `GET /projects/{project_id}/files`
List source files and their processing status.

**Query Parameters**
- `status` — Filter by status (pending, published, error, etc.)
- `extension` — Filter by file extension (.md, .pdf, etc.)
- `sort` — Sort field (filename, modified, status). Default: filename
- `limit` — Max results. Default: 50
- `offset` — Pagination offset. Default: 0

**Response** `200 OK`
```json
{
  "files": [
    {
      "id": "uuid",
      "filename": "infrastructure-specs.docx",
      "filepath": "infrastructure-specs.docx",
      "file_extension": ".docx",
      "file_size": 2202009,
      "status": "published",
      "error_message": null,
      "wiki_page_slug": "infrastructure-specifications",
      "discovered_at": "2026-04-10T12:00:00Z",
      "processed_at": "2026-04-10T12:05:30Z"
    }
  ],
  "total": 42,
  "limit": 50,
  "offset": 0
}
```

#### `POST /projects/{project_id}/files`
Upload file(s) for processing.

**Request** `multipart/form-data`
- `files` — One or more files

**Response** `202 Accepted`
```json
{
  "uploaded": [
    {"filename": "new-doc.md", "id": "uuid", "status": "pending"}
  ]
}
```

#### `DELETE /projects/{project_id}/files/{file_id}`
Remove a source file from the project.

**Response** `204 No Content`

Also removes associated wiki page(s) and cross-references.

#### `POST /projects/{project_id}/files/{file_id}/reprocess`
Re-trigger processing pipeline for a specific file.

**Query Parameters**
- `from_stage` — Start from this stage (default: ingest)

**Response** `202 Accepted`

#### `POST /projects/{project_id}/trigger-sync`
Force re-scan of source directory for changes.

**Response** `200 OK`
```json
{"new_files": 2, "modified_files": 1, "deleted_files": 0}
```

---

### Wiki

#### `GET /projects/{project_id}/pages`
List all wiki pages.

**Query Parameters**
- `category` — Filter by category
- `sort` — Sort by title, category, updated_at. Default: category,title

**Response** `200 OK`
```json
{
  "pages": [
    {
      "slug": "kubernetes-deployment",
      "title": "Kubernetes Deployment Guide",
      "category": "Infrastructure",
      "subcategory": "Container Orchestration",
      "word_count": 1240,
      "version": 3,
      "sources": ["k8s-deployment-guide.md", "infrastructure-specs.docx"],
      "cross_ref_count": 4,
      "updated_at": "2026-04-10T14:32:00Z"
    }
  ]
}
```

#### `GET /projects/{project_id}/pages/{slug}`
Get a specific wiki page.

**Query Parameters**
- `format` — `md` (default), `html`, or `json`

**Response** `200 OK` (format=md)
```
---
title: Kubernetes Deployment Guide
category: Infrastructure
---

# Kubernetes Deployment Guide

Content in Markdown...
```

**Response** `200 OK` (format=json)
```json
{
  "slug": "kubernetes-deployment",
  "title": "Kubernetes Deployment Guide",
  "category": "Infrastructure",
  "subcategory": "Container Orchestration",
  "content_md": "# Kubernetes Deployment Guide\n\n...",
  "content_html": "<h1>Kubernetes Deployment Guide</h1>...",
  "sources": [
    {"file": "k8s-deployment-guide.md", "hash": "a1b2c3..."}
  ],
  "cross_refs": [
    {"slug": "nginx-load-balancing", "title": "Nginx Load Balancing", "relevance": 0.87}
  ],
  "topics": ["kubernetes", "deployment"],
  "version": 3,
  "word_count": 1240,
  "created_at": "2026-04-05T10:00:00Z",
  "updated_at": "2026-04-10T14:32:00Z"
}
```

#### `GET /projects/{project_id}/tree`
Get the wiki navigation tree.

**Response** `200 OK`
```json
{
  "generated_at": "2026-04-10T15:01:22Z",
  "categories": [
    {
      "name": "Infrastructure",
      "slug": "infrastructure",
      "children": [
        {"name": "Kubernetes Deployment", "slug": "kubernetes-deployment", "word_count": 1240},
        {"name": "Nginx Load Balancing", "slug": "nginx-load-balancing", "word_count": 890}
      ]
    }
  ]
}
```

#### `GET /projects/{project_id}/search?q={query}`
Semantic search across wiki pages.

**Query Parameters**
- `q` — Search query (required)
- `max_results` — Max results (default: 5, max: 20)

**Response** `200 OK`
```json
{
  "query": "how is the kubernetes cluster configured",
  "results": [
    {
      "slug": "kubernetes-deployment",
      "title": "Kubernetes Deployment Guide",
      "category": "Infrastructure",
      "relevance": 0.92,
      "snippet": "The OSPD K8s cluster runs on OCI ARM instances..."
    }
  ]
}
```

#### `GET /projects/{project_id}/graph`
Get knowledge graph (cross-reference network).

**Response** `200 OK`
```json
{
  "nodes": [
    {"slug": "kubernetes-deployment", "title": "K8s Deployment", "category": "Infrastructure"},
    {"slug": "nginx-load-balancing", "title": "Nginx LB", "category": "Infrastructure"}
  ],
  "edges": [
    {"source": "kubernetes-deployment", "target": "nginx-load-balancing", "weight": 0.87}
  ]
}
```

---

### Pipeline & Monitoring

#### `GET /projects/{project_id}/status`
Get pipeline processing status.

**Response** `200 OK`
```json
{
  "project_id": "uuid",
  "status": "active",
  "total_files": 42,
  "files_by_status": {
    "published": 38,
    "processing": 2,
    "error": 1,
    "pending": 1
  },
  "progress_pct": 90.5,
  "active_jobs": [
    {
      "id": "uuid",
      "source_file": "budget-2026.xlsx",
      "stage": "extract",
      "status": "running",
      "attempt": 1,
      "started_at": "2026-04-10T14:32:00Z"
    }
  ],
  "eta_seconds": 240
}
```

#### `GET /projects/{project_id}/jobs`
List pipeline jobs.

**Query Parameters**
- `status` — Filter: queued, running, completed, failed
- `stage` — Filter by pipeline stage
- `limit` — Default: 50
- `offset` — Default: 0

#### `GET /projects/{project_id}/metrics`
Get LLM usage and cost metrics.

**Query Parameters**
- `period` — `today`, `week`, `month`, `all`. Default: today

**Response** `200 OK`
```json
{
  "period": "today",
  "total_tokens_in": 98420,
  "total_tokens_out": 25680,
  "total_cost_usd": 0.37,
  "by_stage": {
    "extract": {"tokens_in": 42000, "tokens_out": 8500, "calls": 12},
    "classify": {"tokens_in": 18000, "tokens_out": 4200, "calls": 12},
    "generate": {"tokens_in": 32000, "tokens_out": 11000, "calls": 10},
    "crosslink": {"tokens_in": 6420, "tokens_out": 1980, "calls": 10}
  },
  "by_provider": {
    "anthropic": {"tokens_in": 98420, "tokens_out": 25680, "cost_usd": 0.37}
  },
  "avg_latency_ms": 1800
}
```

#### `GET /projects/{project_id}/watcher`
Get file watcher status.

**Response** `200 OK`
```json
{
  "status": "running",
  "source_dir": "/data/ospd/source",
  "poll_interval_sec": 10,
  "last_scan_at": "2026-04-10T14:32:05Z",
  "files_watched": 42,
  "last_change_detected": "2026-04-10T14:30:30Z"
}
```

---

### Agent Integration

#### `POST /agent/query`
Natural language query using RAG over wiki content.

**Request**
```json
{
  "question": "How is the K8s cluster sized for OSPD?",
  "project_id": "ospd-docs",
  "format": "markdown",
  "include_sources": true,
  "max_results": 5
}
```

**Response** `200 OK`
```json
{
  "answer": "The OSPD Kubernetes cluster is deployed on...",
  "sources": [
    {"filename": "k8s-deployment-guide.md", "wiki_page": "kubernetes-deployment", "relevance": 0.94},
    {"filename": "infrastructure-specs.docx", "wiki_page": "infrastructure-specifications", "relevance": 0.78}
  ],
  "confidence": 0.94,
  "wiki_pages": ["kubernetes-deployment", "infrastructure-specifications"]
}
```

#### `GET /agent/context/{topic}`
Get relevant wiki context for a topic (useful for agent tool calls).

**Response** `200 OK`
```json
{
  "topic": "kubernetes",
  "pages": [
    {
      "slug": "kubernetes-deployment",
      "title": "Kubernetes Deployment Guide",
      "content_excerpt": "First 2000 chars of content...",
      "relevance": 0.95
    }
  ]
}
```

#### `GET /agent/openapi.json`
Machine-readable OpenAPI 3.1 specification for all endpoints.

---

### System

#### `GET /health`
Health check.

**Response** `200 OK`
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "uptime_seconds": 3600,
  "llm_providers": {
    "anthropic": "available",
    "gemini": "available",
    "ollama": "unavailable"
  },
  "active_projects": 3,
  "queue_depth": 2
}
```

#### `GET /api/openapi.json`
OpenAPI specification (auto-generated by FastAPI).

---

## Error Response Format

All errors follow this structure:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Project 'xyz' not found",
    "details": {}
  }
}
```

**Standard error codes:**
- `400` — `VALIDATION_ERROR` — Invalid request body or parameters
- `401` — `UNAUTHORIZED` — Missing or invalid API key
- `404` — `NOT_FOUND` — Resource not found
- `409` — `CONFLICT` — Resource already exists
- `422` — `UNPROCESSABLE` — Valid syntax but semantic error
- `429` — `RATE_LIMITED` — Too many requests
- `500` — `INTERNAL_ERROR` — Server error

## Rate Limiting

Default limits (configurable):
- 100 requests/minute per IP for read endpoints
- 20 requests/minute per IP for write/LLM endpoints
- `/agent/query` — 10 requests/minute (LLM-heavy)

Rate limit headers included in responses:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1712764800
```

## WebSocket (Optional)

`WS /ws/projects/{project_id}/events`

Real-time event stream for pipeline progress:
```json
{"event": "job_started", "data": {"file": "budget.xlsx", "stage": "extract"}}
{"event": "job_completed", "data": {"file": "budget.xlsx", "stage": "extract", "duration_ms": 1200}}
{"event": "page_published", "data": {"slug": "budget-2026", "title": "Budget 2026"}}
{"event": "file_detected", "data": {"filename": "new-report.pdf"}}
{"event": "error", "data": {"file": "broken.doc", "stage": "parse", "message": "Corrupt file"}}
```
