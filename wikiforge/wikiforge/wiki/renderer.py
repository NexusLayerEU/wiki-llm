"""Markdown → HTML, plus frontmatter assembly.

`markdown` is configured with `extra` (tables, fenced code, footnotes) and
`codehilite` so Pygments classes land on code blocks; the stylesheet lives in the
frontend. Output is *not* trusted blindly — see `strip_dangerous`.
"""
import re

import markdown as markdown_lib
import yaml

_EXTENSIONS = ["extra", "codehilite", "toc", "sane_lists", "admonition"]
_CONFIG = {"codehilite": {"guess_lang": False, "css_class": "codehilite"}}

# Generated pages come from a model reading user documents, so they are not a
# trusted source. Scripts, event handlers and javascript: URLs are removed before
# the HTML is stored. NFR-4 is explicit that parsed content is never executed.
_SCRIPT = re.compile(r"<script\b.*?</script\s*>", re.IGNORECASE | re.DOTALL)
_IFRAME = re.compile(r"<iframe\b.*?</iframe\s*>", re.IGNORECASE | re.DOTALL)
_ON_ATTR = re.compile(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)
_JS_URL = re.compile(r"(href|src)\s*=\s*(\"|')\s*javascript:[^\"']*(\"|')", re.IGNORECASE)


def strip_dangerous(html: str) -> str:
    html = _SCRIPT.sub("", html)
    html = _IFRAME.sub("", html)
    html = _ON_ATTR.sub("", html)
    return _JS_URL.sub(r'\1="#"', html)


def render_markdown(content: str) -> str:
    renderer = markdown_lib.Markdown(extensions=_EXTENSIONS, extension_configs=_CONFIG)
    return strip_dangerous(renderer.convert(content or ""))


def split_frontmatter(raw: str) -> tuple[dict, str]:
    """Separate YAML frontmatter from the body of a stored .md file."""
    if not raw.startswith("---"):
        return {}, raw
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}, raw
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}, raw
    return (meta if isinstance(meta, dict) else {}), parts[2].lstrip("\n")


def build_markdown_file(frontmatter: dict, body: str) -> str:
    """Serialise a page the way the spec's on-disk format describes."""
    header = yaml.dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{header}\n---\n\n{body.strip()}\n"


def excerpt(content: str, limit: int = 240) -> str:
    """A plain-text snippet for search results and cards."""
    text = re.sub(r"```.*?```", " ", content or "", flags=re.DOTALL)
    text = re.sub(r"[#>*_`|\-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")
