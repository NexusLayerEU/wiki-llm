"""Wiki pages, navigation tree, search and the cross-reference graph."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import WikiPage
from ..schemas import PageSummary, SearchHit, WikiPageResponse
from ..services.auth import CurrentUser, current_user
from ..services.projects import get_or_404
from ..services.search import search_pages
from ..wiki import build_graph, build_markdown_file, build_navigation_tree, excerpt, render_markdown

router = APIRouter(prefix="/api/v1/projects", tags=["wiki"])


async def _pages_of(session: AsyncSession, project_id: str) -> list[WikiPage]:
    return list(
        (
            await session.execute(
                select(WikiPage)
                .where(WikiPage.project_id == project_id)
                .order_by(WikiPage.category.asc(), WikiPage.title.asc())
            )
        ).scalars().all()
    )


@router.get("/{project_id}/pages", response_model=dict)
async def list_pages(
    project_id: str,
    category: str | None = None,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> dict:
    project = await get_or_404(session, project_id)
    pages = await _pages_of(session, project.id)
    if category:
        pages = [page for page in pages if page.category == category]

    return {
        "pages": [
            PageSummary(
                slug=page.slug, title=page.title, category=page.category,
                subcategory=page.subcategory, word_count=page.word_count,
                version=page.version,
                sources=[
                    source.get("file", "")
                    for source in (page.frontmatter or {}).get("sources", [])
                ],
                cross_ref_count=len(page.cross_refs or []),
                snippet=excerpt(page.content_md, 200),
                updated_at=page.updated_at,
            )
            for page in pages
        ],
        "categories": sorted({page.category for page in await _pages_of(session, project.id)}),
    }


@router.get("/{project_id}/pages/{slug}")
async def get_page(
    project_id: str, slug: str,
    format: str = Query("json", pattern="^(md|html|json)$"),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
):
    project = await get_or_404(session, project_id)
    page = (
        await session.execute(
            select(WikiPage).where(WikiPage.project_id == project.id, WikiPage.slug == slug)
        )
    ).scalar_one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail=f"No page '{slug}'.")

    if format == "md":
        return Response(
            content=build_markdown_file(page.frontmatter or {}, page.content_md),
            media_type="text/markdown; charset=utf-8",
        )
    if format == "html":
        html = page.content_html or render_markdown(page.content_md)
        return Response(content=html, media_type="text/html; charset=utf-8")

    frontmatter = page.frontmatter or {}
    return WikiPageResponse(
        slug=page.slug, title=page.title, category=page.category,
        subcategory=page.subcategory, content_md=page.content_md,
        content_html=page.content_html or render_markdown(page.content_md),
        sources=frontmatter.get("sources", []),
        cross_refs=page.cross_refs or [],
        topics=frontmatter.get("topics", []),
        summary=frontmatter.get("summary", ""),
        version=page.version, word_count=page.word_count,
        created_at=page.created_at, updated_at=page.updated_at,
    )


@router.get("/{project_id}/tree", response_model=dict)
async def get_tree(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> dict:
    project = await get_or_404(session, project_id)
    return build_navigation_tree(project.name, await _pages_of(session, project.id))


@router.get("/{project_id}/search", response_model=dict)
async def search(
    project_id: str,
    q: str = Query(..., min_length=1),
    max_results: int = Query(5, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> dict:
    project = await get_or_404(session, project_id)
    hits = await search_pages(session, project.id, q, max_results)
    return {
        "query": q,
        "results": [
            SearchHit(
                slug=page.slug, title=page.title, category=page.category,
                relevance=round(score, 4), snippet=excerpt(page.content_md, 240),
            )
            for page, score in hits
        ],
    }


@router.get("/{project_id}/graph", response_model=dict)
async def get_graph(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> dict:
    project = await get_or_404(session, project_id)
    return build_graph(await _pages_of(session, project.id))
