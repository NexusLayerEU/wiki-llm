"""
ModelRouter client for WikiLLM's pipeline stages (Extract/Classify/Generate).

All LLM calls go through the shared NexusLayer ModelRouter (Anthropic Messages
API-compatible proxy) instead of calling a provider directly. Auth is the
*calling user's own* SSO bearer token — ModelRouter validates it and routes to
whichever provider that user has configured, it is never a static API key.

Mirrors the pattern already used by BrainVault's RagService.callLLM (Kotlin):
https://router.nexuslayer.eu/v1/messages

Note: ModelRouter is chat-completion only — it has no embeddings endpoint.
Do not use this client for embedding/vector-search needs.
"""
import os
from typing import Optional

import httpx

MODELROUTER_URL = os.getenv("MODELROUTER_URL", "https://router.nexuslayer.eu")
MODELROUTER_MODEL = os.getenv("MODELROUTER_MODEL", "claude-haiku-4-5-20251001")


class ModelRouterError(Exception):
    pass


async def call_llm(
    user_token: str,
    messages: list[dict],
    system: Optional[str] = None,
    max_tokens: int = 1024,
    temperature: Optional[float] = None,
    model: Optional[str] = None,
) -> str:
    """
    Send a chat completion through ModelRouter and return the assistant's text.

    `user_token` is the raw SSO bearer token of the user on whose behalf this
    call is made (from `request.state.sso_token`, set by sso_middleware.py's
    `get_current_user` dependency) — required, ModelRouter authenticates and
    routes based on this token, not a static service key.
    """
    if not user_token:
        raise ModelRouterError("No SSO token available for ModelRouter call")

    body = {
        "model": model or MODELROUTER_MODEL,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        body["system"] = system
    if temperature is not None:
        body["temperature"] = temperature

    async with httpx.AsyncClient(timeout=90.0) as client:
        try:
            resp = await client.post(
                f"{MODELROUTER_URL}/v1/messages",
                json=body,
                headers={
                    "Authorization": user_token if user_token.startswith("Bearer ") else f"Bearer {user_token}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise ModelRouterError(f"ModelRouter returned {e.response.status_code}: {e.response.text}") from e
        except httpx.HTTPError as e:
            raise ModelRouterError(f"ModelRouter request failed: {e}") from e

    data = resp.json()
    content = data.get("content", [])
    return "".join(block.get("text", "") for block in content if block.get("type") == "text")
