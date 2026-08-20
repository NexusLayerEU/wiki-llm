"""Provider lookup.

Only SwitchBoard is implemented. `model_router_client` survives from the earlier
tree and still works, but SwitchBoard is the configured path: it reaches the
Antigravity (`ag/`) Gemini routes, which ModelRouter does not.
"""
from .base import LLMRequest, LLMResponse
from .switchboard import SwitchBoardProvider

_PROVIDERS = {"switchboard": SwitchBoardProvider}


def get_provider(provider: str = "switchboard", model: str | None = None) -> SwitchBoardProvider:
    factory = _PROVIDERS.get((provider or "switchboard").lower())
    if factory is None:
        # An unknown provider on a project row should not take the pipeline down;
        # the configured default is a better outcome than a crash.
        factory = SwitchBoardProvider
    return factory(model=model)


__all__ = ["get_provider", "LLMRequest", "LLMResponse", "SwitchBoardProvider"]
