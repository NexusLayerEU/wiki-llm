# --- stage 1: build the UI ---------------------------------------------------
FROM node:20-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json* ./
# `npm ci` when there is a lockfile, `npm install` when there is not — the repo
# ships one, but the image must still build without it.
RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; \
    else npm install --no-audit --no-fund; fi
COPY frontend/ ./
# Vite writes to ../wikiforge/static, so give it somewhere to land.
RUN mkdir -p /wikiforge/static && npm run build

# --- stage 2: python deps ----------------------------------------------------
FROM python:3.12-slim AS deps
WORKDIR /app
# PyMuPDF ships wheels for this platform; keep the toolchain out of the runtime.
RUN pip install --no-cache-dir --upgrade pip
COPY pyproject.toml ./
COPY wikiforge/__init__.py ./wikiforge/
RUN pip install --no-cache-dir --prefix=/install .

# --- stage 3: runtime --------------------------------------------------------
FROM python:3.12-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WIKIFORGE_DATA_DIR=/data \
    WIKIFORGE_PORT=8000

RUN useradd --create-home --uid 10001 forge \
 && mkdir -p /data && chown -R forge:forge /data

COPY --from=deps /install /usr/local
COPY wikiforge/ ./wikiforge/
COPY --from=ui /wikiforge/static ./wikiforge/static

USER forge
EXPOSE 8000

# The health endpoint answers before any LLM is configured, so this reports the
# process, not the router's availability.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=4).status==200 else 1)"

CMD ["uvicorn", "wikiforge.main:app", "--host", "0.0.0.0", "--port", "8000"]
