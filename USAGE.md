# WikiForge (WikiLLM) — Usage Guide

> Drop files into a folder. Get a structured, cross-linked, searchable wiki — automatically.

**API + UI:** `http://192.168.68.111:8000`

---

## Table of Contents

1. [What is WikiForge?](#1-what-is-wikiforge)
2. [Quick Start](#2-quick-start)
3. [File Watcher Guide](#3-file-watcher-guide)
4. [Pipeline Stages](#4-pipeline-stages)
5. [Semantic Search](#5-semantic-search)
6. [RAG Query](#6-rag-query)
7. [LLM Provider Configuration](#7-llm-provider-configuration)
8. [API Reference](#8-api-reference)
9. [Integration Examples](#9-integration-examples)
10. [Complete Example: DevOps Documentation Wiki](#10-complete-example-devops-documentation-wiki)

---

## 1. What is WikiForge?

WikiForge is a self-hosted, AI-powered document-to-wiki engine. It watches a directory of source files, processes them through a 7-stage LLM pipeline, and produces a navigable, cross-linked, searchable wiki — kept in sync as files change.

**Core workflow:**

```
Drop files → File Watcher → 7-Stage LLM Pipeline → Wiki Pages → REST API + Web UI
(.md/.docx/.pdf/.xlsx)   (Ingest→Parse→Extract     (cross-linked, (search, RAG,
                          →Classify→Generate         categorized)   agent queries)
                          →CrossLink→Publish)
```

**Who it's for:**
- DevOps/infrastructure teams with scattered runbooks, specs, and Terraform docs
- Organizations with legacy documentation in mixed formats (Word, PDF, Excel)
- Anyone who wants an AI-organized, queryable knowledge base from raw files

WikiForge uses [ModelRouter](../ModelRouter) for all LLM operations. Every processing stage is observable — token usage and costs are tracked per file, per stage.

---

## 2. Quick Start

### Step 1 — Create a Project

```bash
curl -s -X POST http://192.168.68.111:8000/api/v1/projects \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Engineering Docs",
    "source_dir": "/data/eng-docs/source",
    "output_dir": "/data/eng-docs/wiki",
    "llm_provider": "anthropic",
    "llm_model": "claude-sonnet-4-20250514",
    "watch_interval": 30,
    "update_mode": "delta"
  }'
```

Save the returned `id` as `PROJECT_ID`.

### Step 2 — Drop Files

Place supported files into `source_dir`:

```bash
cp runbook-deploy.md        /data/eng-docs/source/
cp infrastructure-spec.docx /data/eng-docs/source/
cp cost-report.xlsx         /data/eng-docs/source/
cp network-architecture.pdf /data/eng-docs/source/
```

Or upload via API:

```bash
curl -X POST http://192.168.68.111:8000/api/v1/projects/$PROJECT_ID/files \
  -F "file=@./runbook-deploy.md"
```

### Step 3 — Activate File Watching

```bash
curl -X POST http://192.168.68.111:8000/api/v1/projects/$PROJECT_ID/activate
```

WikiForge begins polling the source directory every `watch_interval` seconds. New and changed files are automatically queued for processing.

### Step 4 — Trigger Immediate Processing (optional)

Don't want to wait for the next poll cycle:

```bash
curl -X POST http://192.168.68.111:8000/api/v1/projects/$PROJECT_ID/process
```

### Step 5 — Monitor Pipeline

```bash
curl http://192.168.68.111:8000/api/v1/projects/$PROJECT_ID/pipeline/status
```

```json
{
  "project_id": "proj_abc123",
  "status": "processing",
  "current_stage": "generate",
  "queued_files": 3,
  "processing_files": 1,
  "completed_files": 12,
  "failed_files": 0,
  "stages": {
    "ingest": { "completed": 16, "failed": 0 },
    "parse":  { "completed": 16, "failed": 0 },
    "extract":{ "completed": 15, "failed": 0 },
    "classify":{"completed": 14, "failed": 0 },
    "generate":{"completed": 12, "failed": 0 },
    "crosslink":{"completed": 12,"failed": 0 },
    "publish": {"completed": 12, "failed": 0 }
  }
}
```

### Step 6 — Browse the Wiki

Open the web UI: **http://192.168.68.111:8000/wiki/`<project-slug>`/**

Or list pages via API:

```bash
curl http://192.168.68.111:8000/api/v1/projects/$PROJECT_ID/wiki
```

---

## 3. File Watcher Guide

### Supported Formats

| Extension | Description |
|-----------|-------------|
| `.md` | Markdown |
| `.doc` / `.docx` | Microsoft Word |
| `.xls` / `.xlsx` | Microsoft Excel |
| `.csv` | Comma-separated values |
| `.pdf` | PDF documents |

### `watch_interval`

How often (in seconds) WikiForge polls the source directory for changes.

| Scenario | Recommended interval |
|----------|----------------------|
| Active development docs (frequent changes) | `10` – `30` |
| Stable documentation | `60` – `300` |
| Batch processing (no live watching needed) | Deactivate + use `/process` |

```bash
# Update watch interval without rebuilding
curl -X PUT http://192.168.68.111:8000/api/v1/projects/$PROJECT_ID \
  -H "Content-Type: application/json" \
  -d '{"watch_interval": 60}'
```

### `update_mode`: delta vs full

| Mode | Description | When to use |
|------|-------------|-------------|
| `delta` | Only re-process files whose SHA-256 hash has changed | Default — efficient for live watching |
| `full` | Re-process every file regardless of changes | After LLM model change or prompt update |

**Switch to full rebuild:**

```bash
# One-time full rebuild (does not change stored update_mode)
curl -X POST http://192.168.68.111:8000/api/v1/projects/$PROJECT_ID/rebuild
```

```bash
# Change project to always do full re-processing
curl -X PUT http://192.168.68.111:8000/api/v1/projects/$PROJECT_ID \
  -H "Content-Type: application/json" \
  -d '{"update_mode": "full"}'
```

### Change Detection

WikiForge computes a SHA-256 hash of each file's content. A file is re-processed only if:
1. `update_mode` is `delta` AND the hash has changed since last processing, OR
2. The file is newly discovered (no prior hash), OR
3. `update_mode` is `full`

To force re-processing of a specific file, touch it:

```bash
touch /data/eng-docs/source/runbook-deploy.md
```

---

## 4. Pipeline Stages

Each file passes through 7 sequential stages. LLM calls only happen at stages 3, 4, and 5.

```
INGEST → PARSE → EXTRACT → CLASSIFY → GENERATE → CROSSLINK → PUBLISH
  (no LLM)  (no LLM)  (LLM ✓)   (LLM ✓)    (LLM ✓)    (no LLM)   (no LLM)
```

### Stage 1: INGEST

**What happens:** File is discovered, copied to the working directory, and hashed for change detection. A `SourceFile` record is created in the database.  
**LLM:** No  
**Fails if:** File is missing, unreadable, or not in a supported format.

### Stage 2: PARSE

**What happens:** The appropriate parser extracts raw text and structured content from the file.

| Format | Parser |
|--------|--------|
| `.md` | Direct text extraction |
| `.docx` | `python-docx` — headings, paragraphs, tables |
| `.xlsx` / `.csv` | `pandas` — sheet names, headers, row data |
| `.pdf` | `pdfminer` / `pypdf2` — text blocks, metadata |

**Output:** Full text, section structure, metadata (title, author, page count), word count.  
**LLM:** No

### Stage 3: EXTRACT

**What happens:** LLM reads the parsed content and extracts structured metadata.  
**LLM:** Yes — `extract.j2` prompt  
**Output:** `ExtractedData` record containing:

```json
{
  "summary": "A 2-sentence summary of the document",
  "topics": ["deployment", "kubernetes", "rollback"],
  "entities": ["nginx", "PostgreSQL", "us-east-1"],
  "key_points": [
    "Zero-downtime deployments require at least 2 replicas",
    "Rollback must complete within 5 minutes of detection"
  ],
  "document_type": "runbook",
  "audience": "DevOps engineers"
}
```

### Stage 4: CLASSIFY

**What happens:** LLM assigns the document to a wiki category and determines its position in the knowledge hierarchy.  
**LLM:** Yes — `classify.j2` prompt  
**Output:**

```json
{
  "category": "Infrastructure / Kubernetes",
  "subcategory": "Deployment Runbooks",
  "wiki_section": "operations",
  "tags": ["kubernetes", "deployment", "runbook", "critical"],
  "priority": "high"
}
```

Categories are project-specific and emerge dynamically from content — WikiForge does not require predefined taxonomies.

### Stage 5: GENERATE

**What happens:** LLM writes the wiki page content — a structured, readable article derived from the source document.  
**LLM:** Yes — `generate.j2` prompt  
**Output:** A Markdown wiki page with:
- YAML frontmatter (title, tags, category, source file, last updated)
- Introduction paragraph
- Organized sections with headings
- Preserved tables and code blocks from source
- Cross-reference placeholders (resolved in stage 6)

```markdown
---
title: "Kubernetes Deployment Runbook"
slug: "kubernetes-deployment-runbook"
category: "Infrastructure / Kubernetes"
tags: ["kubernetes", "deployment", "runbook"]
source_file: "runbook-deploy.md"
last_updated: "2025-04-21T09:30:00Z"
---

# Kubernetes Deployment Runbook

This runbook covers zero-downtime deployments to the production Kubernetes cluster...

## Prerequisites
- Access to `kubectl` with production context
- Deployment manifest in `/k8s/deployments/`

## Deployment Procedure
...
```

### Stage 6: CROSSLINK

**What happens:** Semantic similarity is computed across all wiki pages. Related pages are linked automatically.  
**LLM:** No (uses vector embeddings from stage 5 output)  
**Output:** Each wiki page gets a `related_pages` section:

```markdown
## Related Pages
- [Kubernetes Rollback Procedure](../kubernetes-rollback-procedure)
- [Incident Response Runbook](../incident-response-runbook)
- [Helm Chart Configuration](../helm-chart-configuration)
```

### Stage 7: PUBLISH

**What happens:** Wiki page is written to `output_dir`, the web index is updated, and search embeddings are refreshed.  
**LLM:** No  
**Output:** Accessible at `/wiki/<project-slug>/<page-slug>/` and via API.

---

## 5. Semantic Search

WikiForge uses vector embeddings to support semantic search across all wiki pages — finding conceptually related content, not just keyword matches.

### Search via API

```bash
# Basic search
curl "http://192.168.68.111:8000/api/v1/projects/$PROJECT_ID/search?q=kubernetes+deployment+rollback"

# With pagination and format
curl "http://192.168.68.111:8000/api/v1/projects/$PROJECT_ID/search?q=database+migration+best+practices&limit=5&format=json"
```

**Response:**

```json
{
  "query": "kubernetes deployment rollback",
  "results": [
    {
      "page_slug": "kubernetes-deployment-runbook",
      "title": "Kubernetes Deployment Runbook",
      "category": "Infrastructure / Kubernetes",
      "score": 0.94,
      "excerpt": "...rollback must complete within 5 minutes of detection. Use `kubectl rollout undo` to revert to the previous deployment...",
      "url": "http://192.168.68.111:8000/wiki/eng-docs/kubernetes-deployment-runbook/"
    },
    {
      "page_slug": "incident-response-runbook",
      "title": "Incident Response Runbook",
      "score": 0.81,
      "excerpt": "...for deployment-related incidents, initiate rollback immediately before investigating root cause..."
    }
  ],
  "total": 2
}
```

### Python Search Client

```python
import requests

def search_wiki(project_id: str, query: str, top_k: int = 5, api_key: str = None) -> list[dict]:
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    resp = requests.get(
        f"http://192.168.68.111:8000/api/v1/projects/{project_id}/search",
        params={"q": query, "limit": top_k, "format": "json"},
        headers=headers
    )
    resp.raise_for_status()
    return resp.json()["results"]


# Example
results = search_wiki("proj_abc123", "how to scale postgres read replicas")
for r in results:
    print(f"[{r['score']:.2f}] {r['title']}: {r['excerpt'][:100]}")
```

---

## 6. RAG Query

The RAG (Retrieval-Augmented Generation) endpoint lets you ask natural-language questions against your wiki. WikiForge retrieves the most relevant pages as context, then generates a grounded answer.

### Query via API

```bash
curl -X GET "http://192.168.68.111:8000/api/v1/projects/$PROJECT_ID/query" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is the rollback procedure for a failed Kubernetes deployment?",
    "context_pages": 5
  }'
```

**Response:**

```json
{
  "question": "What is the rollback procedure for a failed Kubernetes deployment?",
  "answer": "To roll back a failed Kubernetes deployment: (1) Run `kubectl rollout undo deployment/<name>` to revert to the previous revision. (2) Verify pod health with `kubectl get pods -w`. (3) If the rollback doesn't stabilize within 5 minutes, escalate per the Incident Response Runbook. For persistent failures, check the Helm Chart Configuration page for version pinning options.",
  "sources": [
    {
      "page_slug": "kubernetes-deployment-runbook",
      "title": "Kubernetes Deployment Runbook",
      "relevance": 0.96
    },
    {
      "page_slug": "incident-response-runbook",
      "title": "Incident Response Runbook",
      "relevance": 0.74
    }
  ],
  "tokens_used": 1840
}
```

### Tune Context Window

`context_pages` controls how many wiki pages are retrieved as context for the answer. Higher values give richer context but cost more tokens.

| Use case | Recommended `context_pages` |
|----------|------------------------------|
| Simple factual queries | 2–3 |
| Multi-step procedures | 4–6 |
| Architecture overview questions | 6–10 |

### Python RAG Client

```python
import requests
from dataclasses import dataclass

@dataclass
class RAGResult:
    answer: str
    sources: list[dict]
    tokens_used: int

def query_wiki(
    project_id: str,
    question: str,
    context_pages: int = 5,
    api_key: str = None
) -> RAGResult:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    resp = requests.get(
        f"http://192.168.68.111:8000/api/v1/projects/{project_id}/query",
        headers=headers,
        json={"question": question, "context_pages": context_pages}
    )
    resp.raise_for_status()
    data = resp.json()
    return RAGResult(
        answer=data["answer"],
        sources=data["sources"],
        tokens_used=data["tokens_used"]
    )


# Example
result = query_wiki("proj_abc123", "What ports does nginx expose in production?")
print(result.answer)
print("Sources:", [s["title"] for s in result.sources])
```

---

## 7. LLM Provider Configuration

LLM provider is configured per project. WikiForge uses [ModelRouter](../ModelRouter) as the backend.

### Anthropic Claude (default)

```json
{
  "llm_provider": "anthropic",
  "llm_model": "claude-sonnet-4-20250514"
}
```

### Google Gemini

```json
{
  "llm_provider": "gemini",
  "llm_model": "gemini-2.5-pro"
}
```

### Local Ollama (air-gapped deployments)

```json
{
  "llm_provider": "ollama",
  "llm_model": "llama3.3:70b",
  "ollama_base_url": "http://gpu-server.internal:11434"
}
```

### Switch Provider Without Rebuilding

Update the project and trigger a rebuild — only the LLM stages (Extract, Classify, Generate) re-run.

```bash
curl -X PUT http://192.168.68.111:8000/api/v1/projects/$PROJECT_ID \
  -H "Content-Type: application/json" \
  -d '{"llm_provider": "gemini", "llm_model": "gemini-2.5-flash"}'

# Full rebuild to apply new model to existing pages
curl -X POST http://192.168.68.111:8000/api/v1/projects/$PROJECT_ID/rebuild
```

### Track Token Costs

```bash
curl http://192.168.68.111:8000/api/v1/projects/$PROJECT_ID/metrics
```

```json
{
  "project_id": "proj_abc123",
  "total_tokens": 284000,
  "total_cost_usd": 1.14,
  "by_stage": {
    "extract":  { "tokens": 95000,  "cost_usd": 0.38 },
    "classify": { "tokens": 42000,  "cost_usd": 0.17 },
    "generate": { "tokens": 147000, "cost_usd": 0.59 }
  },
  "by_file": {
    "infrastructure-spec.docx": { "tokens": 48000, "cost_usd": 0.19 },
    "runbook-deploy.md":        { "tokens": 12000, "cost_usd": 0.05 }
  }
}
```

---

## 8. API Reference

### Projects

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/projects` | List all projects |
| `POST` | `/api/v1/projects` | Create project |
| `GET` | `/api/v1/projects/{id}` | Get project details |
| `PUT` | `/api/v1/projects/{id}` | Update project config |
| `DELETE` | `/api/v1/projects/{id}` | Delete project + data |
| `POST` | `/api/v1/projects/{id}/activate` | Start file watching |
| `POST` | `/api/v1/projects/{id}/pause` | Pause file watching |
| `POST` | `/api/v1/projects/{id}/process` | Trigger immediate processing |
| `POST` | `/api/v1/projects/{id}/rebuild` | Full rebuild of all pages |

### Files

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/projects/{id}/files` | List files + processing status |
| `POST` | `/api/v1/projects/{id}/files` | Upload file |

**Query parameters for file listing:**  
`status` · `extension` · `sort` (filename/modified/status) · `limit` · `offset`

### Wiki

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/projects/{id}/wiki` | List wiki pages |
| `GET` | `/api/v1/projects/{id}/wiki/{slug}` | Get page (add `?format=md\|html\|json`) |
| `GET` | `/api/v1/projects/{id}/search?q=query` | Semantic search |
| `GET` | `/api/v1/projects/{id}/query` | RAG question answering |

### Monitoring

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/projects/{id}/pipeline/status` | Current pipeline progress |
| `GET` | `/api/v1/projects/{id}/metrics` | Token usage + cost breakdown |
| `GET` | `/api/v1/health` | Service health check |

---

## 9. Integration Examples

### WikiLLM + ModelRouter

[ModelRouter](../ModelRouter) is WikiForge's LLM backend. Configure it once per project and switch freely between providers.

**Use ModelRouter's routing features** (failover, cost limits):

```json
{
  "llm_provider": "anthropic",
  "llm_model": "claude-sonnet-4-20250514"
}
```

ModelRouter automatically handles:
- Rate limit retries with exponential backoff
- Failover to a secondary provider if the primary is down
- Per-request cost tracking reported to WatchGrid

**Switch from Anthropic to Gemini when Claude is rate-limited:**

```bash
curl -X PUT http://192.168.68.111:8000/api/v1/projects/$PROJECT_ID \
  -H "Content-Type: application/json" \
  -d '{
    "llm_provider": "gemini",
    "llm_model": "gemini-2.5-flash"
  }'
```

ModelRouter's routing config (set at the ModelRouter level, not WikiForge):

```yaml
# ModelRouter routing rule for WikiForge
- project_tag: "wikiforge"
  primary: anthropic/claude-sonnet-4-20250514
  fallback: gemini/gemini-2.5-flash
  max_cost_per_request_usd: 0.10
```

---

### WikiLLM + AgentShop

[AgentShop](../AgentVault) agents can query WikiForge as a real-time knowledge base before executing tasks. This prevents agents from operating on stale or hallucinated information.

**Agent queries WikiForge before executing a task:**

```python
import requests

WIKIFORGE = "http://192.168.68.111:8000/api/v1"
PROJECT_ID = "proj_devops"

class WikiForgeKnowledgeBase:
    """WikiForge adapter for AgentShop agents."""

    def __init__(self, project_id: str, api_key: str = None):
        self.project_id = project_id
        self.headers = {}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    def get_context(self, task_description: str, top_k: int = 5) -> str:
        """Retrieve relevant wiki pages as context for a task."""
        # Semantic search first
        results = requests.get(
            f"{WIKIFORGE}/projects/{self.project_id}/search",
            params={"q": task_description, "limit": top_k},
            headers=self.headers
        ).json().get("results", [])

        if not results:
            return ""

        # Fetch full page content for top results
        context_parts = []
        for r in results[:3]:
            page = requests.get(
                f"{WIKIFORGE}/projects/{self.project_id}/wiki/{r['page_slug']}",
                params={"format": "md"},
                headers=self.headers
            )
            if page.ok:
                context_parts.append(f"### {r['title']}\n\n{page.text[:2000]}")

        return "\n\n---\n\n".join(context_parts)

    def ask(self, question: str, context_pages: int = 5) -> str:
        """Ask a RAG question and get a grounded answer."""
        resp = requests.get(
            f"{WIKIFORGE}/projects/{self.project_id}/query",
            json={"question": question, "context_pages": context_pages},
            headers={**self.headers, "Content-Type": "application/json"}
        )
        resp.raise_for_status()
        return resp.json()["answer"]


# AgentShop agent using WikiForge
class DevOpsAgent:
    def __init__(self):
        self.kb = WikiForgeKnowledgeBase(project_id=PROJECT_ID)

    def deploy_service(self, service_name: str, version: str):
        # Step 1: Get relevant documentation before acting
        procedure = self.kb.ask(
            f"What is the deployment procedure for {service_name}? "
            "What checks must pass before deploying?"
        )
        print(f"[KB] Deployment context:\n{procedure}\n")

        # Step 2: Check for known issues
        known_issues = self.kb.ask(
            f"Are there any known issues or caveats when deploying {service_name} {version}?"
        )
        print(f"[KB] Known issues:\n{known_issues}\n")

        # Step 3: Execute deployment with informed context
        print(f"Deploying {service_name}:{version}...")
        # ... actual deployment logic ...
```

---

### WikiLLM + BrainVault

Export wiki pages into [BrainVault](../BrainVault) as personal notes — making them part of your personal knowledge base, searchable alongside your own notes.

```python
import requests

WIKIFORGE = "http://192.168.68.111:8000/api/v1"
BRAINVAULT = "http://192.168.68.111:8500/api/v1"

def sync_wiki_to_brainvault(
    project_id: str,
    bv_token: str,
    notebook_id: str,
    category_filter: str = None
) -> list[str]:
    """
    Export all WikiForge pages (optionally filtered by category)
    into BrainVault as notes.

    Returns list of created note IDs.
    """
    # 1. List wiki pages
    params = {}
    if category_filter:
        params["category"] = category_filter

    pages_resp = requests.get(f"{WIKIFORGE}/projects/{project_id}/wiki", params=params)
    pages_resp.raise_for_status()
    pages = pages_resp.json().get("pages", [])

    created_ids = []

    for page in pages:
        # 2. Fetch page content in Markdown
        content_resp = requests.get(
            f"{WIKIFORGE}/projects/{project_id}/wiki/{page['slug']}",
            params={"format": "md"}
        )
        if not content_resp.ok:
            continue

        # 3. Create note in BrainVault
        note = {
            "title": page["title"],
            "content": content_resp.text,
            "tags": page.get("tags", []) + ["wikiforge", project_id],
            "notebookId": notebook_id,
            "source": f"WikiForge:{project_id}/{page['slug']}"
        }

        note_resp = requests.post(
            f"{BRAINVAULT}/notes",
            headers={
                "Authorization": f"Bearer {bv_token}",
                "Content-Type": "application/json"
            },
            json=note
        )
        if note_resp.ok:
            created_ids.append(note_resp.json()["id"])
            print(f"  ✓ Synced: {page['title']}")
        else:
            print(f"  ✗ Failed: {page['title']} — {note_resp.text}")

    return created_ids


# Example: sync all Infrastructure pages
synced = sync_wiki_to_brainvault(
    project_id="proj_devops",
    bv_token="bv_token_xxxx",
    notebook_id="nb_infra",
    category_filter="Infrastructure"
)
print(f"\nSynced {len(synced)} pages to BrainVault")
```

---

### WikiLLM + FlowMesh

[FlowMesh](../flowmesh) can trigger WikiForge rebuilds and query wiki pages as steps in a pipeline.

**Trigger a rebuild from FlowMesh after docs are updated:**

```json
{
  "nodeType": "WEBHOOK",
  "name": "Rebuild Wiki",
  "config": {
    "method": "POST",
    "url": "http://192.168.68.111:8000/api/v1/projects/proj_devops/rebuild",
    "headers": {
      "Authorization": "Bearer wf_api_key_xxxx",
      "Content-Type": "application/json"
    }
  }
}
```

**Query wiki in a FlowMesh pipeline step (SCRIPT node):**

```python
# FlowMesh SCRIPT node: get runbook context before deploying
import requests, json, sys

wiki_result = requests.get(
    "http://192.168.68.111:8000/api/v1/projects/proj_devops/query",
    headers={"Content-Type": "application/json"},
    json={
        "question": f"What are the deployment steps for {sys.argv[1]}?",
        "context_pages": 4
    }
).json()

print(wiki_result["answer"])
# Pass answer downstream in pipeline context
with open("wiki_context.json", "w") as f:
    json.dump(wiki_result, f)
```

**Full FlowMesh pipeline: docs update → wiki rebuild → agent deployment:**

```json
{
  "name": "Docs-to-Deploy Pipeline",
  "nodes": [
    {
      "id": "git-pull",
      "type": "SCRIPT",
      "name": "Pull latest docs",
      "config": { "command": "git -C /data/devops-docs pull origin main" }
    },
    {
      "id": "wiki-rebuild",
      "type": "WEBHOOK",
      "name": "Rebuild WikiForge",
      "config": {
        "method": "POST",
        "url": "http://192.168.68.111:8000/api/v1/projects/proj_devops/rebuild"
      },
      "dependsOn": ["git-pull"]
    },
    {
      "id": "notify",
      "type": "WEBHOOK",
      "name": "Notify Slack",
      "config": {
        "method": "POST",
        "url": "https://hooks.slack.com/services/T00/B00/xxx",
        "body": { "text": "Wiki rebuilt from latest docs ✓" }
      },
      "dependsOn": ["wiki-rebuild"]
    }
  ]
}
```

---

### WikiLLM + WatchGrid

[WatchGrid](../watchgrid) tracks LLM processing costs per WikiForge project.

```bash
# View token costs for a specific project
curl "http://192.168.68.111:9000/api/v1/costs?service=wikiforge&project_id=proj_devops&period=month" \
  -H "Authorization: Bearer $WATCHGRID_TOKEN"
```

```json
{
  "service": "wikiforge",
  "project_id": "proj_devops",
  "period": "2025-04",
  "total_usd": 2.87,
  "total_tokens": 718000,
  "by_stage": {
    "extract":  { "tokens": 240000, "usd": 0.96 },
    "classify": { "tokens": 106000, "usd": 0.42 },
    "generate": { "tokens": 372000, "usd": 1.49 }
  },
  "most_expensive_files": [
    { "file": "infrastructure-spec.docx", "tokens": 48000, "usd": 0.19 },
    { "file": "api-design-doc.pdf",       "tokens": 39000, "usd": 0.16 }
  ]
}
```

**Set a cost alert:**

```bash
curl -X POST http://192.168.68.111:9000/api/v1/alerts \
  -H "Authorization: Bearer $WATCHGRID_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "service": "wikiforge",
    "threshold_usd": 5.00,
    "period": "month",
    "notify": { "slack": "https://hooks.slack.com/services/T00/B00/xxx" }
  }'
```

---

## 10. Complete Example: DevOps Documentation Wiki

This end-to-end example creates a production-ready DevOps documentation wiki from Terraform docs, Kubernetes runbooks, and architecture PDFs.

### Scenario

- **Source files:** Terraform module docs, K8s runbooks, architecture diagrams (PDF), incident postmortems (Word)
- **Goal:** Auto-wiki + semantic search + agent queries before deployments
- **Provider:** Anthropic Claude via ModelRouter

### Setup Script

```python
#!/usr/bin/env python3
"""
DevOps Documentation Wiki — full setup and query example.

Prerequisites:
  - WikiForge running at http://192.168.68.111:8000
  - Source files in /data/devops-docs/source/
"""

import requests
import time
import json

BASE = "http://192.168.68.111:8000/api/v1"
HEADERS = {"Content-Type": "application/json"}
# If API key is set in WikiForge config.yaml:
# HEADERS["Authorization"] = "Bearer your_wiki_api_key"


def create_devops_wiki() -> dict:
    """Create and activate a DevOps documentation wiki project."""

    # 1. Create project
    r = requests.post(f"{BASE}/projects", headers=HEADERS, json={
        "name": "DevOps Documentation",
        "source_dir": "/data/devops-docs/source",
        "output_dir": "/data/devops-docs/wiki",
        "llm_provider": "anthropic",
        "llm_model": "claude-sonnet-4-20250514",
        "watch_interval": 30,
        "update_mode": "delta"
    })
    r.raise_for_status()
    project = r.json()
    project_id = project["id"]
    print(f"✓ Project created: {project_id}")

    # 2. Activate file watching
    r = requests.post(f"{BASE}/projects/{project_id}/activate", headers=HEADERS)
    r.raise_for_status()
    print(f"✓ File watcher activated")

    # 3. Trigger immediate processing of existing files
    r = requests.post(f"{BASE}/projects/{project_id}/process", headers=HEADERS)
    r.raise_for_status()
    print(f"✓ Processing triggered")

    return project


def wait_for_processing(project_id: str, timeout: int = 600):
    """Poll until all files have been processed or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = requests.get(
            f"{BASE}/projects/{project_id}/pipeline/status",
            headers=HEADERS
        ).json()

        queued = status.get("queued_files", 0)
        processing = status.get("processing_files", 0)
        completed = status.get("completed_files", 0)

        print(f"  Pipeline: {completed} done, {processing} processing, {queued} queued...")

        if queued == 0 and processing == 0:
            print(f"✓ All files processed ({completed} pages)")
            return status

        time.sleep(15)

    raise TimeoutError("Wiki processing did not complete in time")


def demo_queries(project_id: str):
    """Demonstrate semantic search and RAG queries."""
    print("\n--- Semantic Search ---")

    queries = [
        "kubernetes pod crash loop debug",
        "terraform aws vpc module usage",
        "database backup and restore procedure"
    ]

    for q in queries:
        results = requests.get(
            f"{BASE}/projects/{project_id}/search",
            params={"q": q, "limit": 3},
            headers=HEADERS
        ).json().get("results", [])

        print(f"\nQuery: '{q}'")
        for r in results:
            print(f"  [{r['score']:.2f}] {r['title']}")

    print("\n--- RAG Queries ---")

    questions = [
        "What is the process for zero-downtime Kubernetes deployments?",
        "How do I create a new VPC using the Terraform modules?",
        "What are the steps to restore the production database from backup?"
    ]

    for question in questions:
        result = requests.get(
            f"{BASE}/projects/{project_id}/query",
            headers={**HEADERS},
            json={"question": question, "context_pages": 4}
        ).json()

        print(f"\nQ: {question}")
        print(f"A: {result['answer'][:300]}...")
        print(f"   Sources: {[s['title'] for s in result['sources']]}")
        print(f"   Tokens used: {result['tokens_used']}")


def show_metrics(project_id: str):
    """Print cost metrics for the project."""
    metrics = requests.get(
        f"{BASE}/projects/{project_id}/metrics",
        headers=HEADERS
    ).json()

    print(f"\n--- Processing Costs ---")
    print(f"Total: ${metrics['total_cost_usd']:.4f} ({metrics['total_tokens']:,} tokens)")
    for stage, data in metrics.get("by_stage", {}).items():
        print(f"  {stage:10s}: ${data['cost_usd']:.4f} ({data['tokens']:,} tokens)")


if __name__ == "__main__":
    project = create_devops_wiki()
    project_id = project["id"]

    print("\nWaiting for pipeline to complete...")
    wait_for_processing(project_id)

    demo_queries(project_id)
    show_metrics(project_id)

    print(f"\n✓ Wiki available at: http://192.168.68.111:8000/wiki/{project['slug']}/")
```

### Drop Files and Watch

```bash
# Place source documents
SOURCE="/data/devops-docs/source"
mkdir -p $SOURCE

cp ./terraform/modules/vpc/README.md          $SOURCE/terraform-vpc-module.md
cp ./runbooks/k8s-deployment.md               $SOURCE/
cp ./runbooks/incident-response.md            $SOURCE/
cp ./architecture/system-architecture.pdf     $SOURCE/
cp ./postmortems/2025-03-db-outage.docx       $SOURCE/
cp ./infra/network-topology.xlsx              $SOURCE/

echo "Dropped $(ls $SOURCE | wc -l) files — WikiForge will process them automatically"
```

### Agent Querying WikiForge Before Deployments

```python
#!/usr/bin/env python3
"""
Example: DevOps deployment agent that queries WikiForge
for procedures and known issues before deploying.
"""

import requests
import subprocess
import sys

WIKI_BASE = "http://192.168.68.111:8000/api/v1"
PROJECT_ID = "proj_devops-documentation"


def wiki_ask(question: str, context_pages: int = 4) -> str:
    resp = requests.get(
        f"{WIKI_BASE}/projects/{PROJECT_ID}/query",
        headers={"Content-Type": "application/json"},
        json={"question": question, "context_pages": context_pages}
    )
    resp.raise_for_status()
    return resp.json()["answer"]


def deploy_service(service: str, version: str, namespace: str = "production"):
    print(f"\n{'='*60}")
    print(f"Deploying {service}:{version} to {namespace}")
    print(f"{'='*60}\n")

    # Step 1: Fetch deployment procedure from wiki
    print("[1/4] Querying WikiForge for deployment procedure...")
    procedure = wiki_ask(
        f"What are the exact steps to deploy the {service} service? "
        "Include pre-deployment checks and rollback instructions."
    )
    print(f"Procedure:\n{procedure}\n")

    # Step 2: Check for known issues with this service/version
    print("[2/4] Checking for known issues...")
    known_issues = wiki_ask(
        f"Are there any known issues, caveats, or prerequisites "
        f"for deploying {service} version {version}?"
    )
    print(f"Known issues:\n{known_issues}\n")

    # Step 3: Get rollback procedure (always have it ready)
    print("[3/4] Fetching rollback procedure...")
    rollback = wiki_ask(
        f"What is the rollback procedure for {service} if the deployment fails? "
        "Include specific kubectl commands."
    )
    print(f"Rollback procedure:\n{rollback}\n")

    # Step 4: Execute deployment
    print("[4/4] Executing deployment...")
    result = subprocess.run([
        "kubectl", "set", "image",
        f"deployment/{service}",
        f"{service}={service}:{version}",
        "-n", namespace
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Deployment failed: {result.stderr}")
        print(f"\nExecuting rollback per wiki procedure...")
        subprocess.run([
            "kubectl", "rollout", "undo",
            f"deployment/{service}", "-n", namespace
        ])
    else:
        print(f"✓ Deployment successful: {result.stdout}")


if __name__ == "__main__":
    service = sys.argv[1] if len(sys.argv) > 1 else "api-gateway"
    version = sys.argv[2] if len(sys.argv) > 2 else "v2.4.1"
    deploy_service(service, version)
```

**What happens end-to-end:**

1. Terraform docs, runbooks, PDFs are dropped into `/data/devops-docs/source/`
2. WikiForge detects new files within `watch_interval` seconds
3. Each file passes through the 7-stage pipeline — structured wiki pages are generated
4. Cross-links between related pages are added automatically (e.g., K8s runbook ↔ incident response)
5. Wiki is live at `http://192.168.68.111:8000/wiki/devops-documentation/`
6. Deployment agents query WikiForge RAG before executing — grounded in actual docs
7. WatchGrid tracks LLM costs per stage, per file
8. When docs are updated, only changed files are re-processed (`delta` mode)
9. FlowMesh triggers a rebuild whenever the docs repo is pushed to
