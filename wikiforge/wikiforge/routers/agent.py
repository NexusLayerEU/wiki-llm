"""Agent-facing endpoints: RAG answers and topic context."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_session
from ..llm import LLMError, LLMRequest, get_provider
from ..models import LLMUsage
from ..pipeline.prompts import render_prompt
from ..schemas import AgentQuery, AgentResponse, SourceReference
from ..services.auth import CurrentUser, current_user
from ..services.projects import get_or_404
from ..services.search import search_pages
from ..wiki import excerpt

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])

#: Characters of each page handed to the model. Enough for the substance of a page
#: without letting five long pages overflow the context.
CONTEXT_CHARS = 6000


@router.post("/query", response_model=AgentResponse)
async def query(
    payload: AgentQuery,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> AgentResponse:
    project = await get_or_404(session, payload.project_id)
    hits = await search_pages(session, project.id, payload.question, payload.max_results)

    if not hits:
        return AgentResponse(
            answer=(
                "Nothing in this wiki matches that question. If the documents were "
                "added recently, check that the pipeline has finished publishing them."
            ),
            sources=[], confidence=0.0, wiki_pages=[],
        )

    if not get_settings().llm_configured:
        # Degrade to extractive results rather than 500. The pages found are still
        # useful without a model to summarise them.
        return AgentResponse(
            answer="\n\n".join(
                f"**{page.title}**\n\n{excerpt(page.content_md, 500)}" for page, _ in hits
            ),
            sources=[
                SourceReference(
                    filename=(page.frontmatter or {}).get("sources", [{}])[0].get("file", page.slug),
                    wiki_page=page.slug, relevance=round(score, 3),
                )
                for page, score in hits
            ],
            confidence=round(hits[0][1], 3),
            wiki_pages=[page.slug for page, _ in hits],
        )

    prompt = render_prompt(
        "answer.j2",
        {
            "question": payload.question,
            "output_format": payload.format,
            "pages": [
                {
                    "title": page.title, "slug": page.slug,
                    "content": page.content_md[:CONTEXT_CHARS],
                }
                for page, _ in hits
            ],
        },
    )

    provider = get_provider(project.llm_provider, project.llm_model)
    try:
        response = await provider.complete(
            LLMRequest(
                system_prompt=(
                    "You answer strictly from the wiki excerpts you are given. "
                    "If they do not contain the answer, say so."
                ),
                user_prompt=prompt, temperature=0.2, max_tokens=2048,
            )
        )
    except LLMError as cause:
        raise HTTPException(status_code=503, detail=f"The model is unavailable: {cause}") from cause

    session.add(
        LLMUsage(
            project_id=project.id, provider=response.provider, model=response.model,
            stage="agent_query", tokens_in=response.tokens_in,
            tokens_out=response.tokens_out, latency_ms=response.latency_ms,
        )
    )
    await session.commit()

    return AgentResponse(
        answer=response.content,
        sources=[
            SourceReference(
                filename=(page.frontmatter or {}).get("sources", [{}])[0].get("file", page.slug),
                wiki_page=page.slug, relevance=round(score, 3),
            )
            for page, score in hits
        ] if payload.include_sources else [],
        # The retrieval score, not the model's self-assessment: how well the wiki
        # matched the question is the thing we can actually measure.
        confidence=round(hits[0][1], 3),
        wiki_pages=[page.slug for page, _ in hits],
    )


@router.get("/context/{topic}", response_model=dict)
async def context(
    topic: str,
    project_id: str = Query(...),
    max_results: int = Query(5, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> dict:
    project = await get_or_404(session, project_id)
    hits = await search_pages(session, project.id, topic, max_results)
    return {
        "topic": topic,
        "pages": [
            {
                "slug": page.slug, "title": page.title, "category": page.category,
                "content_excerpt": page.content_md[:2000],
                "relevance": round(score, 4),
            }
            for page, score in hits
        ],
    }
