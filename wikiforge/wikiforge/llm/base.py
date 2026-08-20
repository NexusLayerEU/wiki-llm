"""Normalised LLM request/response shapes."""
from dataclasses import dataclass, field


class LLMError(RuntimeError):
    """Any failure talking to the model. Carries whether a retry is worth it."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass
class LLMRequest:
    system_prompt: str
    user_prompt: str
    max_tokens: int = 4096
    temperature: float = 0.3
    # "json" asks the model for JSON. Not a hard guarantee from any provider, so
    # callers still go through `parse_json_reply`.
    response_format: str | None = None


@dataclass
class LLMResponse:
    content: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    model: str = ""
    provider: str = "switchboard"
    cost_usd: float = 0.0
    raw_response: dict | None = field(default=None, repr=False)
