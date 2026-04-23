# WikiForge — Configuration

## Configuration File

WikiForge reads configuration from `config.yaml` in the working directory, with environment variable overrides.

```yaml
# config.yaml — WikiForge configuration

# ──────────────────────────────────────────
# Server
# ──────────────────────────────────────────
server:
  host: "0.0.0.0"
  port: 8000
  workers: 1                    # Uvicorn workers (1 for dev, 2-4 for prod)
  reload: false                 # Auto-reload on code changes (dev only)
  cors_origins:                 # Allowed CORS origins
    - "http://localhost:5173"   # Vite dev server
    - "http://localhost:8000"

# ──────────────────────────────────────────
# Data Storage
# ──────────────────────────────────────────
data:
  base_dir: "./data"            # Base directory for all project data
  global_db: "./data/wikiforge_global.db"  # Global database path

# ──────────────────────────────────────────
# LLM Providers
# ──────────────────────────────────────────
llm:
  default_provider: "anthropic"
  default_model: "claude-sonnet-4-20250514"

  providers:
    anthropic:
      api_key: ${ANTHROPIC_API_KEY}
      models:
        - "claude-sonnet-4-20250514"
        - "claude-haiku-4-5-20251001"
        - "claude-opus-4-6"

    gemini:
      api_key: ${GOOGLE_API_KEY}
      models:
        - "gemini-2.5-flash"
        - "gemini-2.5-pro"

    ollama:
      base_url: "http://localhost:11434"
      models:
        - "llama3.1:8b"
        - "llama3.1:70b"
        - "mistral:7b"
        - "qwen2.5:14b"
        - "qwen2.5:32b"
        - "deepseek-r1:14b"

  fallback_chain:
    - ["anthropic", "claude-sonnet-4-20250514"]
    - ["gemini", "gemini-2.5-flash"]
    - ["ollama", "llama3.1:8b"]

  embedding:
    provider: "gemini"
    model: "text-embedding-004"
    # Alternatives:
    # provider: "ollama"
    # model: "nomic-embed-text"

# ──────────────────────────────────────────
# Pipeline
# ──────────────────────────────────────────
pipeline:
  queue_backend: "in_process"   # "in_process" (no Redis) or "celery"
  max_workers: 4                # Concurrent pipeline workers
  retry:
    max_attempts: 3
    base_delay: 2               # seconds
    max_delay: 60
    exponential_base: 2

  # LLM call settings per stage
  stages:
    extract:
      temperature: 0.2
      max_tokens: 4096
    classify:
      temperature: 0.2
      max_tokens: 2048
    generate:
      temperature: 0.3
      max_tokens: 8192
    crosslink:
      temperature: 0.2
      max_tokens: 2048

# ──────────────────────────────────────────
# File Watcher
# ──────────────────────────────────────────
watcher:
  mode: "polling"               # "polling" or "watchdog"
  default_interval: 10          # seconds (overridable per project)
  debounce: 5                   # seconds — batch rapid changes
  supported_extensions:
    - ".md"
    - ".markdown"
    - ".doc"
    - ".docx"
    - ".xlsx"
    - ".xls"
    - ".csv"
    - ".tsv"
    - ".pdf"

# ──────────────────────────────────────────
# Wiki
# ──────────────────────────────────────────
wiki:
  base_url: "http://localhost:8000/wiki"  # Base URL for wiki links
  crosslink_threshold: 0.5      # Minimum similarity for cross-references
  max_crosslinks: 10            # Max cross-references per page

# ──────────────────────────────────────────
# API
# ──────────────────────────────────────────
api:
  auth_key: ${WIKIFORGE_API_KEY}  # Optional — if unset, API is open
  rate_limit:
    read: 100                   # requests per minute
    write: 20
    agent: 10

# ──────────────────────────────────────────
# Logging
# ──────────────────────────────────────────
logging:
  level: "INFO"                 # DEBUG, INFO, WARNING, ERROR
  format: "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
  file: null                    # Log to file (null = stdout only)

# ──────────────────────────────────────────
# Celery (only if pipeline.queue_backend = "celery")
# ──────────────────────────────────────────
celery:
  broker_url: "redis://localhost:6379/0"
  result_backend: "redis://localhost:6379/1"
```

## Environment Variables

All configuration values can be overridden by environment variables with the prefix `WIKIFORGE_`:

| Environment Variable | Config Path | Example |
|---------------------|-------------|---------|
| `ANTHROPIC_API_KEY` | `llm.providers.anthropic.api_key` | `sk-ant-...` |
| `GOOGLE_API_KEY` | `llm.providers.gemini.api_key` | `AIza...` |
| `WIKIFORGE_API_KEY` | `api.auth_key` | `wf-key-...` |
| `WIKIFORGE_PORT` | `server.port` | `8000` |
| `WIKIFORGE_DATA_DIR` | `data.base_dir` | `/data` |
| `WIKIFORGE_LOG_LEVEL` | `logging.level` | `DEBUG` |
| `WIKIFORGE_LLM_PROVIDER` | `llm.default_provider` | `ollama` |
| `WIKIFORGE_LLM_MODEL` | `llm.default_model` | `llama3.1:8b` |
| `WIKIFORGE_QUEUE` | `pipeline.queue_backend` | `celery` |
| `REDIS_URL` | `celery.broker_url` | `redis://redis:6379/0` |
| `OLLAMA_BASE_URL` | `llm.providers.ollama.base_url` | `http://ollama:11434` |

## Configuration Loader

```python
# wikiforge/config.py

import os
import yaml
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class Config:
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    data_base_dir: str = "./data"
    llm_default_provider: str = "anthropic"
    llm_default_model: str = "claude-sonnet-4-20250514"
    pipeline_queue_backend: str = "in_process"
    pipeline_max_workers: int = 4
    watcher_mode: str = "polling"
    watcher_default_interval: int = 10
    log_level: str = "INFO"
    api_auth_key: str | None = None

    @classmethod
    def load(cls, config_path: str = "config.yaml") -> "Config":
        config = cls()

        # Load YAML if exists
        path = Path(config_path)
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f)
            if data:
                config._apply_yaml(data)

        # Override with environment variables
        config._apply_env()

        return config

    def _apply_yaml(self, data: dict):
        if "server" in data:
            self.server_host = data["server"].get("host", self.server_host)
            self.server_port = data["server"].get("port", self.server_port)
        if "data" in data:
            self.data_base_dir = data["data"].get("base_dir", self.data_base_dir)
        if "llm" in data:
            self.llm_default_provider = data["llm"].get("default_provider", self.llm_default_provider)
            self.llm_default_model = data["llm"].get("default_model", self.llm_default_model)
        # ... etc for all fields

    def _apply_env(self):
        if v := os.getenv("WIKIFORGE_PORT"):
            self.server_port = int(v)
        if v := os.getenv("WIKIFORGE_DATA_DIR"):
            self.data_base_dir = v
        if v := os.getenv("WIKIFORGE_LLM_PROVIDER"):
            self.llm_default_provider = v
        if v := os.getenv("WIKIFORGE_LLM_MODEL"):
            self.llm_default_model = v
        if v := os.getenv("WIKIFORGE_LOG_LEVEL"):
            self.log_level = v
        if v := os.getenv("WIKIFORGE_API_KEY"):
            self.api_auth_key = v
        if v := os.getenv("WIKIFORGE_QUEUE"):
            self.pipeline_queue_backend = v
```

## Docker Compose

```yaml
# docker-compose.yml

version: "3.8"

services:
  wikiforge:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data
      - ./config.yaml:/app/config.yaml
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - GOOGLE_API_KEY=${GOOGLE_API_KEY}
      - WIKIFORGE_API_KEY=${WIKIFORGE_API_KEY}
      - WIKIFORGE_QUEUE=celery
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis

  worker:
    build: .
    command: celery -A wikiforge.pipeline.celery_app worker --loglevel=info --concurrency=4
    volumes:
      - ./data:/data
      - ./config.yaml:/app/config.yaml
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - GOOGLE_API_KEY=${GOOGLE_API_KEY}
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  # Optional: local LLM inference
  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]

volumes:
  ollama_data:
```

## Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application
COPY wikiforge/ wikiforge/
COPY frontend/dist/ wikiforge/static/

# Default command
CMD ["uvicorn", "wikiforge.main:app", "--host", "0.0.0.0", "--port", "8000"]
```
