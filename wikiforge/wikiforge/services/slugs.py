"""Slug generation, shared by projects and pages."""
import re
import unicodedata

_NON_WORD = re.compile(r"[^\w\s-]", re.UNICODE)
_SPACES = re.compile(r"[\s_]+")
_DASHES = re.compile(r"-{2,}")


def slugify(value: str, *, fallback: str = "untitled", max_length: int = 80) -> str:
    """Lowercase, hyphenated, URL-safe.

    Greek and other non-Latin text is transliterated where a decomposition exists
    and otherwise kept, because dropping it entirely turns a Greek page title into
    an empty slug. Callers still resolve collisions.
    """
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = _NON_WORD.sub("", text).strip().lower()
    text = _SPACES.sub("-", text)
    text = _DASHES.sub("-", text).strip("-")
    return (text[:max_length].strip("-") or fallback)


async def unique_slug(session, model, base: str, *, project_id: str | None = None) -> str:
    """Append -2, -3 … until the slug is free."""
    from sqlalchemy import select

    candidate = base
    suffix = 1
    while True:
        query = select(model).where(model.slug == candidate)
        if project_id is not None and hasattr(model, "project_id"):
            query = query.where(model.project_id == project_id)
        existing = (await session.execute(query.limit(1))).scalar_one_or_none()
        if existing is None:
            return candidate
        suffix += 1
        candidate = f"{base}-{suffix}"
