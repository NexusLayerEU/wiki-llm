# WikiForge — Development Guide

## Prerequisites

- Python 3.11+
- Node.js 18+ (for frontend)
- LibreOffice (for .doc conversion) — `apt install libreoffice-writer`
- Redis (optional, only for Celery queue mode)

## Quick Start

```bash
# 1. Clone and setup
git clone <repo-url> wikiforge
cd wikiforge

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -e ".[dev]"

# 4. Create config
cp config.example.yaml config.yaml
# Edit config.yaml — set your LLM API keys

# 5. Set environment variables
export ANTHROPIC_API_KEY="sk-ant-..."
# OR
export GOOGLE_API_KEY="AIza..."
# OR ensure Ollama is running at localhost:11434

# 6. Initialize data directory
mkdir -p data

# 7. Run the server
python -m wikiforge.main
# → Server at http://localhost:8000

# 8. (Optional) Frontend dev server
cd frontend
npm install
npm run dev
# → Frontend at http://localhost:5173 (proxies API to :8000)
```

## Project Structure Summary

```
wikiforge/
├── wikiforge/           # Python backend
│   ├── main.py          # FastAPI entry point
│   ├── config.py        # Configuration loader
│   ├── models/          # SQLAlchemy ORM models
│   ├── schemas/         # Pydantic request/response schemas
│   ├── routers/         # FastAPI route handlers
│   ├── services/        # Business logic layer
│   ├── llm/             # LLM provider abstraction
│   ├── parsers/         # File format parsers
│   ├── pipeline/        # Processing pipeline + job queue
│   ├── watcher/         # File system watcher
│   └── wiki/            # Wiki generation + rendering
├── frontend/            # React frontend
├── tests/               # Test suite
├── docs/                # These specification documents
├── config.yaml          # Runtime configuration
├── pyproject.toml       # Python project metadata
├── Dockerfile
└── docker-compose.yml
```

## Python Dependencies

```toml
# pyproject.toml

[project]
name = "wikiforge"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    # Web framework
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.30.0",
    "python-multipart>=0.0.9",     # File uploads
    "websockets>=12.0",             # WebSocket support

    # Database
    "sqlalchemy>=2.0",
    "aiosqlite>=0.20.0",           # Async SQLite

    # File parsers
    "python-docx>=1.1.0",          # .docx
    "openpyxl>=3.1.0",             # .xlsx
    "PyMuPDF>=1.24.0",             # PDF (import as fitz)

    # LLM providers
    "anthropic>=0.34.0",            # Claude
    "google-genai>=1.0.0",          # Gemini
    "httpx>=0.27.0",                # Ollama HTTP client

    # Wiki rendering
    "markdown>=3.6",
    "Pygments>=2.18.0",            # Code highlighting

    # Utilities
    "pyyaml>=6.0",
    "jinja2>=3.1.0",               # Prompt templates
    "numpy>=1.26.0",               # Embeddings math
    "pydantic>=2.7.0",
    "pydantic-settings>=2.3.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
    "httpx>=0.27",                 # Test client
    "ruff>=0.5.0",                 # Linting
    "mypy>=1.10",                  # Type checking
]

celery = [
    "celery[redis]>=5.4.0",
]

watchdog = [
    "watchdog>=4.0.0",
]
```

## Development Workflow

### Running in Development Mode

```bash
# Backend with auto-reload
uvicorn wikiforge.main:app --reload --port 8000

# Frontend with hot reload (separate terminal)
cd frontend && npm run dev
```

### Code Quality

```bash
# Linting
ruff check wikiforge/
ruff format wikiforge/

# Type checking
mypy wikiforge/

# Run all checks
ruff check . && mypy wikiforge/ && pytest
```

## Testing Strategy

### Unit Tests

Test individual components in isolation with mocked dependencies.

```
tests/
├── unit/
│   ├── test_parsers/
│   │   ├── test_markdown_parser.py
│   │   ├── test_docx_parser.py
│   │   ├── test_xlsx_parser.py
│   │   ├── test_pdf_parser.py
│   │   └── test_parser_registry.py
│   ├── test_llm/
│   │   ├── test_provider_registry.py
│   │   ├── test_claude_provider.py
│   │   ├── test_gemini_provider.py
│   │   └── test_ollama_provider.py
│   ├── test_pipeline/
│   │   ├── test_stages.py
│   │   ├── test_executor.py
│   │   └── test_job_queue.py
│   ├── test_watcher/
│   │   ├── test_delta_detector.py
│   │   └── test_daemon.py
│   ├── test_wiki/
│   │   ├── test_renderer.py
│   │   ├── test_crosslinker.py
│   │   └── test_tree_builder.py
│   └── test_services/
│       ├── test_project_service.py
│       ├── test_file_service.py
│       └── test_search_service.py
├── integration/
│   ├── test_api_projects.py
│   ├── test_api_files.py
│   ├── test_api_wiki.py
│   ├── test_api_pipeline.py
│   ├── test_api_agent.py
│   └── test_full_pipeline.py
└── fixtures/
    ├── sample.md
    ├── sample.docx
    ├── sample.xlsx
    ├── sample.pdf
    └── sample.csv
```

### Example Unit Test

```python
# tests/unit/test_parsers/test_markdown_parser.py

import pytest
from pathlib import Path
from wikiforge.parsers.markdown import MarkdownParser


@pytest.fixture
def parser():
    return MarkdownParser()


@pytest.fixture
def sample_md(tmp_path):
    content = """---
title: Test Document
author: Test Author
---

# Main Title

Some introductory text.

## Section One

Content of section one.

## Section Two

| Header A | Header B |
|----------|----------|
| Cell 1   | Cell 2   |
| Cell 3   | Cell 4   |
"""
    filepath = tmp_path / "test.md"
    filepath.write_text(content)
    return filepath


def test_parse_extracts_title(parser, sample_md):
    result = parser.parse(str(sample_md))
    assert result.title == "Main Title"


def test_parse_extracts_sections(parser, sample_md):
    result = parser.parse(str(sample_md))
    assert result.section_count >= 2
    headings = [s.heading for s in result.sections]
    assert "Section One" in headings
    assert "Section Two" in headings


def test_parse_extracts_tables(parser, sample_md):
    result = parser.parse(str(sample_md))
    assert len(result.tables) == 1
    assert result.tables[0].headers == ["Header A", "Header B"]
    assert len(result.tables[0].rows) == 2


def test_parse_extracts_frontmatter(parser, sample_md):
    result = parser.parse(str(sample_md))
    assert result.metadata.get("title") == "Test Document"
    assert result.metadata.get("author") == "Test Author"


def test_parse_counts_words(parser, sample_md):
    result = parser.parse(str(sample_md))
    assert result.word_count > 0
```

### Example Integration Test

```python
# tests/integration/test_api_projects.py

import pytest
from httpx import AsyncClient, ASGITransport
from wikiforge.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_create_project(client, tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    response = await client.post("/api/v1/projects", json={
        "name": "Test Project",
        "source_dir": str(source_dir),
        "output_dir": str(output_dir),
        "llm_provider": "ollama",
        "llm_model": "llama3.1:8b",
    })

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Project"
    assert data["slug"] == "test-project"
    assert data["status"] == "created"


@pytest.mark.asyncio
async def test_list_projects(client):
    response = await client.get("/api/v1/projects")
    assert response.status_code == 200
    assert "projects" in response.json()
```

### Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=wikiforge --cov-report=html

# Specific test file
pytest tests/unit/test_parsers/test_markdown_parser.py

# Integration tests only
pytest tests/integration/

# Verbose output
pytest -v -s
```

## Implementation Order

Recommended build sequence for a CLI agent:

### Phase 1: Foundation
1. `config.py` — Configuration loading
2. `models/` — All SQLAlchemy models
3. `schemas/` — All Pydantic schemas
4. `main.py` — FastAPI app skeleton with health endpoint

### Phase 2: Parsers
5. `parsers/base.py` + `parsers/registry.py`
6. `parsers/markdown.py` — Start with the simplest format
7. `parsers/docx.py`
8. `parsers/xlsx.py` + `parsers/csv_parser.py`
9. `parsers/pdf.py`
10. `parsers/doc.py` (requires LibreOffice)

### Phase 3: LLM Layer
11. `llm/base.py` — Abstract interface
12. `llm/ollama.py` — Start with Ollama (no API key needed for testing)
13. `llm/claude.py`
14. `llm/gemini.py`
15. `llm/registry.py` — Provider factory
16. `llm/prompts/` — All Jinja2 prompt templates

### Phase 4: Pipeline
17. `pipeline/job_queue.py` — In-process queue first
18. `pipeline/stages.py` — All 7 stage implementations
19. `pipeline/executor.py` — Pipeline orchestrator

### Phase 5: Wiki Engine
20. `wiki/renderer.py` — Markdown → HTML
21. `wiki/tree.py` — Navigation tree builder
22. `wiki/crosslinker.py` — Cross-reference system
23. `wiki/generator.py` — Page generation orchestration

### Phase 6: Services + API
24. `services/` — All service classes
25. `routers/projects.py`
26. `routers/files.py`
27. `routers/wiki.py`
28. `routers/pipeline.py`
29. `routers/monitoring.py`
30. `routers/agent.py`

### Phase 7: File Watcher
31. `watcher/delta.py`
32. `watcher/daemon.py`

### Phase 8: Frontend
33. React app setup (Vite + TypeScript)
34. API client layer
35. Pages and components

### Phase 9: Production
36. Docker + docker-compose
37. Celery integration
38. Static site exporter

## Key Design Principles for Developers

1. **Every LLM call goes through `llm/registry.py`** — never import a provider directly in pipeline code
2. **Parsers are stateless** — they take a filepath and return a ParsedContent
3. **Pipeline stages are idempotent** — safe to retry at any stage
4. **Services own business logic** — routers are thin, just handle HTTP
5. **SQLite per project** — projects are fully isolated at the data layer
6. **Prompts are templates** — editable without code changes
7. **File watcher is a daemon** — runs as a background asyncio task
