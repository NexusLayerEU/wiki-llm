# WikiForge — LLM Provider Abstraction

> **2026-07-02 update — use ModelRouter, not per-provider API keys.**
> This product should NOT implement separate Anthropic/Gemini/Ollama clients with their
> own API keys (as the sections below originally described). All NexusLayer products
> route LLM calls through **ModelRouter** (`https://router.nexuslayer.eu`, Contabo VPS
> 184.174.34.245 — not the homelab), which already provides multi-provider routing,
> fallback, and centralized key management (design goals #1 and #4 below are handled
> by ModelRouter itself, not by this product). Auth is the shared NexusLayer SSO JWT
> (`Authorization: Bearer <token>`) forwarded from the caller's own session — see the
> `modelrouter` skill (or `aiidentityserver` skill) for the exact token/flow.
>
> ModelRouter is an **Anthropic Messages API-compatible chat proxy only** — it has no
> embeddings endpoint. If/when this pipeline needs embeddings (see "Ollama Provider"
> section below), that must go directly to a real, reachable embedding provider (e.g.
> a local Ollama sidecar, as BrainVault now does), not through ModelRouter.
>
> When implementing `wikiforge/llm/`, replace the Claude/Gemini/Ollama-with-own-keys
> providers below with a single `ModelRouterProvider` that POSTs to
> `{MODELROUTER_URL:-https://router.nexuslayer.eu}/v1/messages` with the caller's
> forwarded SSO token — mirroring the pattern already working in BrainVault's
> `RagService.kt` (`/Users/admin/Documents/Thomas-SRC/NextLayer/products/release/brain-vault/backend/src/main/kotlin/app/brainvault/api/service/RagService.kt`).
> Keep a separate, explicit embedding path (not through ModelRouter) for anything
> needing vectors.

## Design Goals

1. Support multiple LLM providers without pipeline code changes
2. Normalize request/response formats across providers
3. Track token usage and cost per call
4. Support fallback chains (primary → secondary provider)
5. Handle rate limiting and retries transparently

## Provider Interface

```python
# wikiforge/llm/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class ProviderName(str, Enum):
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OLLAMA = "ollama"


@dataclass
class LLMRequest:
    """Normalized request to any LLM provider."""
    system_prompt: str
    user_prompt: str
    max_tokens: int = 4096
    temperature: float = 0.3
    response_format: str | None = None  # "json" to request JSON output
    # Optional: structured output schema for providers that support it
    json_schema: dict | None = None


@dataclass
class LLMResponse:
    """Normalized response from any LLM provider."""
    content: str                    # The text response
    tokens_in: int                  # Input token count
    tokens_out: int                 # Output token count
    latency_ms: int                 # Request duration in ms
    model: str                      # Actual model used
    provider: ProviderName          # Which provider handled it
    cost_usd: float                 # Estimated cost
    raw_response: dict | None = None  # Original API response for debugging


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""

    provider_name: ProviderName

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Send a completion request and return normalized response."""
        ...

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Generate embedding vector for text. Returns float list."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider is configured and reachable."""
        ...

    @abstractmethod
    def estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        """Estimate USD cost for given token counts."""
        ...

    def get_model_name(self) -> str:
        """Return the model identifier string."""
        return self.model
```

## Anthropic Claude Provider

```python
# wikiforge/llm/claude.py

import time
import anthropic
from .base import BaseLLMProvider, LLMRequest, LLMResponse, ProviderName


class ClaudeProvider(BaseLLMProvider):
    provider_name = ProviderName.ANTHROPIC

    # Pricing per million tokens (update as needed)
    PRICING = {
        "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
        "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
        "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    }

    def __init__(self, model: str = "claude-sonnet-4-20250514", api_key: str | None = None):
        self.model = model
        self.client = anthropic.AsyncAnthropic(api_key=api_key)  # Falls back to ANTHROPIC_API_KEY env var

    async def complete(self, request: LLMRequest) -> LLMResponse:
        start = time.monotonic()

        message = await self.client.messages.create(
            model=self.model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            system=request.system_prompt,
            messages=[{"role": "user", "content": request.user_prompt}],
        )

        latency = int((time.monotonic() - start) * 1000)
        tokens_in = message.usage.input_tokens
        tokens_out = message.usage.output_tokens

        return LLMResponse(
            content=message.content[0].text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency,
            model=self.model,
            provider=self.provider_name,
            cost_usd=self.estimate_cost(tokens_in, tokens_out),
            raw_response=message.model_dump(),
        )

    async def embed(self, text: str) -> list[float]:
        # Anthropic does not have a native embedding API.
        # Use Voyager model via the API if available, or fall back to a local model.
        # For now, use a lightweight local embedding (see _local_embed).
        return await _local_embed(text)

    def is_available(self) -> bool:
        try:
            return self.client.api_key is not None
        except Exception:
            return False

    def estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        pricing = self.PRICING.get(self.model, {"input": 3.0, "output": 15.0})
        return (tokens_in * pricing["input"] + tokens_out * pricing["output"]) / 1_000_000
```

## Google Gemini Provider

```python
# wikiforge/llm/gemini.py

import time
from google import genai
from .base import BaseLLMProvider, LLMRequest, LLMResponse, ProviderName


class GeminiProvider(BaseLLMProvider):
    provider_name = ProviderName.GEMINI

    PRICING = {
        "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
        "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    }

    def __init__(self, model: str = "gemini-2.5-flash", api_key: str | None = None):
        self.model = model
        self.client = genai.Client(api_key=api_key)  # Falls back to GOOGLE_API_KEY env var

    async def complete(self, request: LLMRequest) -> LLMResponse:
        start = time.monotonic()

        config = genai.types.GenerateContentConfig(
            system_instruction=request.system_prompt,
            max_output_tokens=request.max_tokens,
            temperature=request.temperature,
        )

        # If JSON output requested, set response_mime_type
        if request.response_format == "json":
            config.response_mime_type = "application/json"
            if request.json_schema:
                config.response_schema = request.json_schema

        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=request.user_prompt,
            config=config,
        )

        latency = int((time.monotonic() - start) * 1000)
        tokens_in = response.usage_metadata.prompt_token_count or 0
        tokens_out = response.usage_metadata.candidates_token_count or 0

        return LLMResponse(
            content=response.text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency,
            model=self.model,
            provider=self.provider_name,
            cost_usd=self.estimate_cost(tokens_in, tokens_out),
            raw_response=None,  # Gemini response objects are not easily serializable
        )

    async def embed(self, text: str) -> list[float]:
        result = await self.client.aio.models.embed_content(
            model="text-embedding-004",
            contents=text,
        )
        return result.embeddings[0].values

    def is_available(self) -> bool:
        try:
            return self.client._api_key is not None
        except Exception:
            return False

    def estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        pricing = self.PRICING.get(self.model, {"input": 0.15, "output": 0.60})
        return (tokens_in * pricing["input"] + tokens_out * pricing["output"]) / 1_000_000
```

## Ollama Provider (Local Models)

```python
# wikiforge/llm/ollama.py

import time
import httpx
from .base import BaseLLMProvider, LLMRequest, LLMResponse, ProviderName


class OllamaProvider(BaseLLMProvider):
    provider_name = ProviderName.OLLAMA

    def __init__(self, model: str = "llama3.1:8b", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url.rstrip("/")

    async def complete(self, request: LLMRequest) -> LLMResponse:
        start = time.monotonic()

        payload = {
            "model": self.model,
            "system": request.system_prompt,
            "prompt": request.user_prompt,
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }

        if request.response_format == "json":
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{self.base_url}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()

        latency = int((time.monotonic() - start) * 1000)

        return LLMResponse(
            content=data["response"],
            tokens_in=data.get("prompt_eval_count", 0),
            tokens_out=data.get("eval_count", 0),
            latency_ms=latency,
            model=self.model,
            provider=self.provider_name,
            cost_usd=0.0,  # Local models have no API cost
            raw_response=data,
        )

    async def embed(self, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
            )
            resp.raise_for_status()
            return resp.json()["embedding"]

    def is_available(self) -> bool:
        try:
            import httpx
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    def estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        return 0.0  # Local inference is free (compute cost not tracked)
```

## Provider Registry

```python
# wikiforge/llm/registry.py

from .base import BaseLLMProvider, ProviderName, LLMRequest, LLMResponse
from .claude import ClaudeProvider
from .gemini import GeminiProvider
from .ollama import OllamaProvider
import logging

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Factory and registry for LLM providers with fallback support."""

    _providers: dict[str, type[BaseLLMProvider]] = {
        "anthropic": ClaudeProvider,
        "gemini": GeminiProvider,
        "ollama": OllamaProvider,
    }

    def __init__(self):
        self._instances: dict[str, BaseLLMProvider] = {}

    def get_provider(self, provider_name: str, model: str, **kwargs) -> BaseLLMProvider:
        """Get or create a provider instance."""
        cache_key = f"{provider_name}:{model}"

        if cache_key not in self._instances:
            provider_cls = self._providers.get(provider_name)
            if not provider_cls:
                raise ValueError(
                    f"Unknown provider '{provider_name}'. "
                    f"Available: {list(self._providers.keys())}"
                )
            self._instances[cache_key] = provider_cls(model=model, **kwargs)

        return self._instances[cache_key]

    @classmethod
    def register_provider(cls, name: str, provider_cls: type[BaseLLMProvider]):
        """Register a custom provider class."""
        cls._providers[name] = provider_cls

    async def complete_with_fallback(
        self,
        request: LLMRequest,
        providers: list[tuple[str, str]],  # List of (provider_name, model) tuples
    ) -> LLMResponse:
        """Try providers in order, falling back on failure.

        Args:
            request: The LLM request
            providers: Ordered list of (provider_name, model) to try

        Returns:
            LLMResponse from the first successful provider

        Raises:
            RuntimeError if all providers fail
        """
        errors = []

        for provider_name, model in providers:
            try:
                provider = self.get_provider(provider_name, model)
                if not provider.is_available():
                    logger.warning(f"Provider {provider_name}/{model} not available, skipping")
                    errors.append(f"{provider_name}/{model}: not available")
                    continue

                return await provider.complete(request)

            except Exception as e:
                logger.error(f"Provider {provider_name}/{model} failed: {e}")
                errors.append(f"{provider_name}/{model}: {e}")
                continue

        raise RuntimeError(
            f"All LLM providers failed. Errors: {'; '.join(errors)}"
        )


# Global registry singleton
registry = ProviderRegistry()
```

## Prompt Templates

Prompts are stored as Jinja2 templates in `wikiforge/llm/prompts/`. This allows customization without code changes.

### Extract Prompt (`extract.j2`)

```jinja2
You are a document analysis expert. Extract structured information from the following document content.

## Document Info
- Filename: {{ filename }}
- Type: {{ file_type }}
- Sections found: {{ section_count }}

## Document Content
{{ content | truncate(12000) }}

## Instructions
Analyze the document and return a JSON object with these fields:
- "summary": A 2-3 sentence summary of the document
- "topics": Array of 3-8 topic keywords
- "entities": Array of objects with {"name": string, "type": "person"|"system"|"technology"|"organization"|"location"}
- "key_points": Array of 3-10 key points or facts from the document

Return ONLY valid JSON, no markdown fences or explanation.
```

### Classify Prompt (`classify.j2`)

```jinja2
You are a wiki organizer. Given the extracted data from a document, determine where it belongs in a wiki structure.

## Document Summary
{{ summary }}

## Topics
{{ topics | join(", ") }}

## Key Points
{% for point in key_points %}
- {{ point }}
{% endfor %}

## Existing Wiki Categories
{% for cat in existing_categories %}
- {{ cat.name }} ({{ cat.page_count }} pages)
{% endfor %}

## Instructions
Return a JSON object:
- "category": The top-level wiki category (use an existing one if appropriate, or suggest a new one)
- "subcategory": Optional subcategory within the category (null if not needed)
- "page_title": A clear, descriptive title for the wiki page
- "page_slug": URL-safe version of the title (lowercase, hyphens, no special chars)
- "confidence": Your confidence in this classification (0.0 to 1.0)

Return ONLY valid JSON.
```

### Generate Wiki Page Prompt (`generate_wiki.j2`)

```jinja2
You are a technical wiki writer. Generate a well-structured wiki page from the source material below.

## Page Classification
- Title: {{ page_title }}
- Category: {{ category }}
{% if subcategory %}- Subcategory: {{ subcategory }}{% endif %}

## Source Material
{{ content | truncate(15000) }}

## Extracted Summary
{{ summary }}

## Key Points
{% for point in key_points %}
- {{ point }}
{% endfor %}

## Instructions
Write a comprehensive wiki page in Markdown format. Requirements:
1. Start with a level-1 heading matching the page title
2. Use level-2 and level-3 headings to organize content logically
3. Preserve technical accuracy — do not invent information
4. Include code blocks with language tags where applicable
5. Use tables where data is tabular
6. Write in clear, professional technical documentation style
7. If the source contains configuration details, include them verbatim
8. Target 500-2000 words depending on source material depth

Output ONLY the Markdown content. Do not include frontmatter — that is added separately.
```

### Cross-link Prompt (`crosslink.j2`)

```jinja2
You are analyzing wiki pages to find meaningful cross-references.

## Current Page
Title: {{ current_title }}
Summary: {{ current_summary }}
Topics: {{ current_topics | join(", ") }}

## Candidate Pages
{% for page in candidates %}
### {{ page.title }}
Summary: {{ page.summary }}
Topics: {{ page.topics | join(", ") }}
Slug: {{ page.slug }}

{% endfor %}

## Instructions
For each candidate page, determine if it has a meaningful connection to the current page.
Return a JSON array of objects for RELEVANT pages only:
- "slug": The candidate page slug
- "title": The candidate page title
- "relevance": Relevance score 0.0 to 1.0
- "reason": Brief explanation of the connection

Only include pages with relevance >= 0.5. Return ONLY valid JSON array.
```

### RAG Query Prompt (`rag_query.j2`)

```jinja2
You are a wiki knowledge assistant. Answer the user's question using ONLY the provided wiki context.

## Wiki Context
{% for page in context_pages %}
### {{ page.title }} ({{ page.slug }})
{{ page.content | truncate(3000) }}

{% endfor %}

## User Question
{{ question }}

## Instructions
1. Answer the question using ONLY information from the wiki context above
2. If the context doesn't contain enough information, say so clearly
3. Reference the source page titles when making claims
4. Format your answer in {{ format }} format
5. Be concise but thorough

Answer:
```

## Configuration

Provider configuration is read from environment variables and/or config file:

```yaml
# config.yaml
llm:
  default_provider: anthropic
  default_model: claude-sonnet-4-20250514

  providers:
    anthropic:
      api_key: ${ANTHROPIC_API_KEY}  # Or set env var directly
      models:
        - claude-sonnet-4-20250514
        - claude-haiku-4-5-20251001

    gemini:
      api_key: ${GOOGLE_API_KEY}
      models:
        - gemini-2.5-flash
        - gemini-2.5-pro

    ollama:
      base_url: http://localhost:11434
      models:
        - llama3.1:8b
        - mistral:7b
        - qwen2.5:14b

  fallback_chain:
    - ["anthropic", "claude-sonnet-4-20250514"]
    - ["gemini", "gemini-2.5-flash"]
    - ["ollama", "llama3.1:8b"]

  # Embedding provider (used for cross-linking and search)
  embedding:
    provider: gemini              # gemini has a good embedding API
    model: text-embedding-004
    # Alternative: use ollama for local embeddings
    # provider: ollama
    # model: nomic-embed-text
```

## Adding a Custom Provider

To add a new LLM provider:

1. Create a new file in `wikiforge/llm/` (e.g., `openai.py`)
2. Implement `BaseLLMProvider` interface
3. Register it in `registry.py` or at runtime:

```python
from wikiforge.llm.registry import registry
from wikiforge.llm.my_provider import MyProvider

registry.register_provider("my_provider", MyProvider)
```

4. Add configuration in `config.yaml`
5. Use it in project settings: `llm_provider: "my_provider"`
