"""Jinja environment for the prompt templates."""
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


@lru_cache
def _environment() -> Environment:
    # StrictUndefined so a renamed template variable fails loudly here rather than
    # silently sending the model a prompt with a hole in it.
    return Environment(
        loader=FileSystemLoader(str(_PROMPT_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_prompt(template_name: str, context: dict) -> str:
    return _environment().get_template(template_name).render(**context)
