"""Page search.

Two signals, combined: lexical cosine over the whole page (the same vectoriser the
cross-linker uses) and a direct substring match on title and body. The substring
term is what makes searching for an exact identifier — an IP, a hostname, a command
— actually find the page, which a bag-of-words score alone does poorly.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import WikiPage
from ..wiki import cosine, from_bytes, vectorise

TITLE_HIT_BONUS = 0.45
BODY_HIT_BONUS = 0.15


async def search_pages(
    session: AsyncSession, project_id: str, query: str, limit: int = 5
) -> list[tuple[WikiPage, float]]:
    pages = list(
        (
            await session.execute(select(WikiPage).where(WikiPage.project_id == project_id))
        ).scalars().all()
    )
    if not pages:
        return []

    query_vector = vectorise(query)
    needle = query.strip().lower()

    scored: list[tuple[WikiPage, float]] = []
    for page in pages:
        # `or` is not usable here: a numpy array has no unambiguous truth value.
        vector = from_bytes(page.embedding)
        if vector is None:
            vector = vectorise(f"{page.title}\n{page.content_md}")
        score = cosine(query_vector, vector)
        if needle and needle in page.title.lower():
            score += TITLE_HIT_BONUS
        elif needle and needle in page.content_md.lower():
            score += BODY_HIT_BONUS
        if score > 0.01:
            scored.append((page, min(score, 1.0)))

    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:limit]
