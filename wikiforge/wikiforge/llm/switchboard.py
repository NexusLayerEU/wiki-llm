"""SwitchBoard provider — OpenAI-compatible chat completions.

Two wire-level quirks are handled here rather than at every call site.

1. **Non-streaming replies arrive as `text/event-stream`.** SwitchBoard answers a
   plain `chat/completions` request with `data: {...}` lines and a trailing
   `data: [DONE]` with no separator, so `response.json()` raises "Extra data".
   `_extract_text` reads either shape.

2. **Reasoning tokens are charged against `max_tokens`.** Gemini 3 through the `ag/`
   routes spends output budget on thinking before emitting a character, so a small
   ceiling returns an empty string rather than a short answer. The floor below is
   why a "give me one word" call still asks for room.
"""
import json
import time

import httpx

from ..config import get_settings
from .base import LLMError, LLMRequest, LLMResponse

#: Below roughly this, a thinking model can burn the whole budget and return "".
MIN_MAX_TOKENS = 1024


class SwitchBoardProvider:
    provider_name = "switchboard"

    def __init__(self, model: str | None = None) -> None:
        settings = get_settings()
        self._base_url = settings.switchboard_url.rstrip("/")
        self._api_key = settings.switchboard_api_key
        self._model = model or settings.switchboard_model
        self._timeout = settings.llm_timeout_seconds

    @property
    def model(self) -> str:
        return self._model

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if not self._api_key:
            raise LLMError(
                "SWITCHBOARD_API_KEY is not set, so no model can be reached.",
                retryable=False,
            )

        payload: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "max_tokens": max(request.max_tokens, MIN_MAX_TOKENS),
            "temperature": request.temperature,
        }

        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.TimeoutException as cause:
            raise LLMError(f"SwitchBoard timed out after {self._timeout}s", retryable=True) from cause
        except httpx.HTTPError as cause:
            raise LLMError(f"Could not reach SwitchBoard: {cause}", retryable=True) from cause

        latency_ms = int((time.monotonic() - started) * 1000)

        # 5xx means it failed over between upstreams and lost; 4xx is our fault.
        if response.status_code >= 500:
            raise LLMError(
                f"SwitchBoard returned {response.status_code}: {response.text[:200]}",
                retryable=True,
            )
        if response.status_code >= 400:
            raise LLMError(
                f"SwitchBoard rejected the request ({response.status_code}): "
                f"{response.text[:300]}",
                retryable=False,
            )

        text, usage, model_used = _extract_text(response.text)
        if not text.strip():
            raise LLMError(
                "SwitchBoard returned an empty completion — usually the output budget "
                "was spent on reasoning tokens. Raise max_tokens.",
                retryable=True,
            )

        return LLMResponse(
            content=text,
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
            latency_ms=latency_ms,
            model=model_used or self._model,
            provider=self.provider_name,
            cost_usd=0.0,  # The router does not report cost; left at zero, not guessed.
        )


def _extract_text(body: str) -> tuple[str, dict, str]:
    """Pull the assistant text out of either a JSON object or an SSE stream."""
    body = body.strip()
    if not body:
        return "", {}, ""

    # The plain-JSON case, and the "JSON plus trailing junk" case.
    if body.startswith("{"):
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            decoder = json.JSONDecoder()
            try:
                data, _ = decoder.raw_decode(body)
            except json.JSONDecodeError as cause:
                raise LLMError(f"Unreadable reply from SwitchBoard: {body[:200]}") from cause
        return _from_object(data)

    # The SSE case: accumulate deltas across events.
    text_parts: list[str] = []
    usage: dict = {}
    model_used = ""
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if not chunk or chunk == "[DONE]":
            continue
        try:
            event = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        model_used = event.get("model") or model_used
        if event.get("usage"):
            usage = event["usage"]
        for choice in event.get("choices") or []:
            delta = choice.get("delta") or {}
            message = choice.get("message") or {}
            text_parts.append(delta.get("content") or message.get("content") or "")

    if not text_parts:
        raise LLMError(f"No completion found in SwitchBoard reply: {body[:200]}")
    return "".join(text_parts), usage, model_used


def _from_object(data: dict) -> tuple[str, dict, str]:
    if data.get("error"):
        message = data["error"]
        if isinstance(message, dict):
            message = message.get("message", str(message))
        raise LLMError(f"SwitchBoard error: {message}", retryable=False)

    choices = data.get("choices") or []
    if not choices:
        raise LLMError(f"SwitchBoard reply had no choices: {str(data)[:200]}")
    message = choices[0].get("message") or {}
    delta = choices[0].get("delta") or {}
    text = message.get("content") or delta.get("content") or ""
    return text, data.get("usage") or {}, data.get("model", "")
