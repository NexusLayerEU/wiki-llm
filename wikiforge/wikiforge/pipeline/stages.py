"""The seven pipeline stages.

Each stage takes a source file id, does one thing, advances the file's status, and
commits. Stages are idempotent: re-running one overwrites its own output rather
than appending, so a retry after a partial failure is safe (NFR-3).

Content sent to the model is truncated per stage. A 300-page PDF would otherwise
blow the context window and fail the whole file; a truncated page with a warning is
more useful than no page.
"""
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..llm import LLMError, LLMRequest, get_provider, parse_json_reply
from ..models import (
    Classification, ExtractedData, LLMUsage, ParsedContent, Project, SourceFile, WikiPage,
)
from ..parsers import ParserError, parse_file
from ..services.slugs import slugify
from ..wiki import (
    build_markdown_file, build_navigation_tree, build_search_index, cosine,
    from_bytes, render_markdown, to_bytes, vectorise,
)

logger = logging.getLogger(__name__)

STAGE_ORDER = ["ingest", "parse", "extract", "classify", "generate", "crosslink", "publish"]

#: Per-stage input ceilings, in characters.
EXTRACT_CHAR_LIMIT = 24_000
GENERATE_CHAR_LIMIT = 40_000

#: Floor for offering a page to the model as a candidate.
#:
#: Deliberately low. Hashed term-frequency vectors over short pages score genuinely
#: related documents around 0.08-0.15, so a "sensible-looking" threshold like 0.3
#: silently disables cross-linking altogether. This filter exists only to bound the
#: prompt — the model, which sees titles and topics, makes the actual judgement.
CROSSLINK_PREFILTER = 0.04
CROSSLINK_MAX_CANDIDATES = 10


class StageError(RuntimeError):
    """A stage failed. `retryable` decides whether the queue tries again."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clean_page_body(body: str) -> str:
    """Strip the artefacts models leave around a generated page.

    Two are common enough to handle rather than hope about:

    * The whole page wrapped in a code fence, despite being told not to.
    * A leading acknowledgement line — "Rewrite:", "Here is the wiki page:" —
      which the Gemini routes in particular emit. Left in, it becomes the first
      line of a published page.

    A line is only dropped as preamble if it precedes the first Markdown heading,
    so a page that legitimately opens with prose is untouched.
    """
    body = (body or "").strip()

    if body.startswith("```"):
        lines = body.splitlines()
        if len(lines) > 2:
            end = -1 if lines[-1].strip().startswith("```") else len(lines)
            body = "\n".join(lines[1:end]).strip()

    lines = body.splitlines()
    first_heading = next((i for i, line in enumerate(lines) if line.lstrip().startswith("#")), None)
    # Only ever discard a couple of short lines, and only ahead of the heading.
    if first_heading is not None and 0 < first_heading <= 2:
        preamble = " ".join(lines[:first_heading]).strip()
        if len(preamble) <= 120:
            body = "\n".join(lines[first_heading:]).strip()

    return body


async def _get_file(session: AsyncSession, source_file_id: str) -> SourceFile:
    source_file = await session.get(SourceFile, source_file_id)
    if source_file is None:
        raise StageError(f"Source file {source_file_id} no longer exists")
    return source_file


async def _get_project(session: AsyncSession, project_id: str) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise StageError(f"Project {project_id} no longer exists")
    return project


async def _call_llm(
    session: AsyncSession, project: Project, stage: str, job_id: str | None,
    request: LLMRequest,
) -> str:
    """Run one model call and record its usage."""
    provider = get_provider(project.llm_provider, project.llm_model)
    try:
        response = await provider.complete(request)
    except LLMError as cause:
        raise StageError(str(cause), retryable=cause.retryable) from cause

    session.add(
        LLMUsage(
            project_id=project.id, job_id=job_id, provider=response.provider,
            model=response.model, stage=stage, tokens_in=response.tokens_in,
            tokens_out=response.tokens_out, latency_ms=response.latency_ms,
            cost_usd=response.cost_usd,
        )
    )
    return response.content


# --------------------------------------------------------------------------- 1
async def ingest(session: AsyncSession, source_file_id: str, job_id: str | None = None) -> None:
    source_file = await _get_file(session, source_file_id)
    project = await _get_project(session, source_file.project_id)
    path = Path(project.source_dir) / source_file.filepath

    if not path.is_file():
        source_file.status = "deleted"
        source_file.error_message = f"File is no longer at {path}"
        await session.commit()
        raise StageError(f"Source file missing: {path}")

    payload = path.read_bytes()
    source_file.content_hash = hashlib.sha256(payload).hexdigest()
    source_file.file_size = len(payload)
    source_file.error_message = None
    source_file.status = "ingested"
    await session.commit()


# --------------------------------------------------------------------------- 2
async def parse(session: AsyncSession, source_file_id: str, job_id: str | None = None) -> None:
    source_file = await _get_file(session, source_file_id)
    project = await _get_project(session, source_file.project_id)
    path = Path(project.source_dir) / source_file.filepath

    try:
        document = parse_file(str(path))
    except (ParserError, ValueError) as cause:
        # A file we cannot read is a permanent condition, not a transient one.
        raise StageError(str(cause), retryable=False) from cause

    await session.execute(
        delete(ParsedContent).where(ParsedContent.source_file_id == source_file_id)
    )
    session.add(
        ParsedContent(
            source_file_id=source_file_id,
            content_text=document.full_text,
            content_structured=document.to_dict(),
            file_metadata={**document.metadata, "warnings": document.warnings},
            section_count=document.section_count,
            word_count=document.word_count,
        )
    )

    if not document.full_text.strip():
        raise StageError(
            "; ".join(document.warnings) or "No text could be extracted", retryable=False
        )

    source_file.status = "parsed"
    await session.commit()


# --------------------------------------------------------------------------- 3
async def extract(session: AsyncSession, source_file_id: str, job_id: str | None = None) -> None:
    from .prompts import render_prompt

    source_file = await _get_file(session, source_file_id)
    project = await _get_project(session, source_file.project_id)
    parsed = (
        await session.execute(
            select(ParsedContent).where(ParsedContent.source_file_id == source_file_id)
        )
    ).scalar_one_or_none()
    if parsed is None:
        raise StageError("Nothing parsed for this file yet")

    prompt = render_prompt(
        "extract.j2",
        {
            "filename": source_file.filename,
            "file_type": source_file.file_extension,
            "section_count": parsed.section_count,
            "content": parsed.content_text[:EXTRACT_CHAR_LIMIT],
        },
    )
    raw = await _call_llm(
        session, project, "extract", job_id,
        LLMRequest(
            system_prompt="You are a document analysis expert. Return valid JSON only.",
            user_prompt=prompt, response_format="json", temperature=0.2, max_tokens=2048,
        ),
    )

    try:
        data = parse_json_reply(raw)
    except ValueError as cause:
        raise StageError(f"Extract returned unusable JSON: {cause}", retryable=True) from cause
    if not isinstance(data, dict):
        raise StageError("Extract returned JSON that was not an object", retryable=True)

    await session.execute(
        delete(ExtractedData).where(ExtractedData.source_file_id == source_file_id)
    )
    session.add(
        ExtractedData(
            source_file_id=source_file_id,
            summary=str(data.get("summary") or "").strip(),
            topics=[str(topic) for topic in (data.get("topics") or [])][:12],
            entities=[e for e in (data.get("entities") or []) if isinstance(e, dict)][:40],
            key_points=[str(point) for point in (data.get("key_points") or [])][:12],
            raw_llm_output=raw[:20_000],
        )
    )
    source_file.status = "extracted"
    await session.commit()


# --------------------------------------------------------------------------- 4
async def classify(session: AsyncSession, source_file_id: str, job_id: str | None = None) -> None:
    from .prompts import render_prompt

    source_file = await _get_file(session, source_file_id)
    project = await _get_project(session, source_file.project_id)
    extracted = (
        await session.execute(
            select(ExtractedData).where(ExtractedData.source_file_id == source_file_id)
        )
    ).scalar_one_or_none()
    if extracted is None:
        raise StageError("Nothing extracted for this file yet")

    rows = (
        await session.execute(
            select(WikiPage.category, func.count(WikiPage.id))
            .where(WikiPage.project_id == project.id)
            .group_by(WikiPage.category)
        )
    ).all()

    prompt = render_prompt(
        "classify.j2",
        {
            "summary": extracted.summary or source_file.filename,
            "topics": extracted.topics or [],
            "key_points": extracted.key_points or [],
            "existing_categories": [{"name": name, "count": count} for name, count in rows],
        },
    )
    raw = await _call_llm(
        session, project, "classify", job_id,
        LLMRequest(
            system_prompt="You are a wiki organiser. Return valid JSON only.",
            user_prompt=prompt, response_format="json", temperature=0.2, max_tokens=1536,
        ),
    )

    try:
        data = parse_json_reply(raw)
    except ValueError as cause:
        raise StageError(f"Classify returned unusable JSON: {cause}", retryable=True) from cause

    title = str(data.get("page_title") or Path(source_file.filename).stem).strip()
    slug = slugify(str(data.get("page_slug") or title), fallback=slugify(title))

    # A file that has been classified before keeps the slug it was given.
    #
    # The model is asked to name the page every time this stage runs, and it will
    # happily phrase it differently on a second pass — "ssh-port-forwarding-asr-engine"
    # one run, "asr-engine-ssh-tunnel-setup" the next. Since the slug is how the
    # generate stage finds the page to update, letting it drift makes reprocessing
    # create a *second* page and orphan the first, which breaks the idempotency the
    # pipeline is supposed to have. The slug is the page's identity and its URL; the
    # title is free to change.
    previous = (
        await session.execute(
            select(Classification.page_slug).where(
                Classification.source_file_id == source_file_id
            )
        )
    ).scalar_one_or_none()
    if previous:
        slug = previous

    # The model is asked for a slug but is not trusted to make it unique. A slug
    # already used by *another* file's page gets suffixed; the same file keeps its
    # slug so re-processing updates the page instead of spawning a duplicate.
    taken = (
        await session.execute(
            select(Classification.page_slug)
            .join(SourceFile, SourceFile.id == Classification.source_file_id)
            .where(
                SourceFile.project_id == project.id,
                Classification.source_file_id != source_file_id,
            )
        )
    ).scalars().all()
    if not previous and slug in set(taken):
        suffix = 2
        while f"{slug}-{suffix}" in set(taken):
            suffix += 1
        slug = f"{slug}-{suffix}"

    await session.execute(
        delete(Classification).where(Classification.source_file_id == source_file_id)
    )
    session.add(
        Classification(
            source_file_id=source_file_id,
            category=str(data.get("category") or "Uncategorised").strip() or "Uncategorised",
            subcategory=(str(data["subcategory"]).strip() or None)
            if data.get("subcategory") else None,
            page_title=title or "Untitled",
            page_slug=slug,
            confidence=float(data.get("confidence") or 0.0),
            raw_llm_output=raw[:20_000],
        )
    )
    source_file.status = "classified"
    await session.commit()


# --------------------------------------------------------------------------- 5
async def generate(session: AsyncSession, source_file_id: str, job_id: str | None = None) -> None:
    from .prompts import render_prompt

    source_file = await _get_file(session, source_file_id)
    project = await _get_project(session, source_file.project_id)

    parsed = (await session.execute(
        select(ParsedContent).where(ParsedContent.source_file_id == source_file_id)
    )).scalar_one_or_none()
    extracted = (await session.execute(
        select(ExtractedData).where(ExtractedData.source_file_id == source_file_id)
    )).scalar_one_or_none()
    classification = (await session.execute(
        select(Classification).where(Classification.source_file_id == source_file_id)
    )).scalar_one_or_none()
    if not (parsed and extracted and classification):
        raise StageError("Earlier stages have not produced their output yet")

    prompt = render_prompt(
        "generate_wiki.j2",
        {
            "page_title": classification.page_title,
            "category": classification.category,
            "subcategory": classification.subcategory,
            "content": parsed.content_text[:GENERATE_CHAR_LIMIT],
            "summary": extracted.summary or "",
            "key_points": extracted.key_points or [],
        },
    )
    body = await _call_llm(
        session, project, "generate", job_id,
        LLMRequest(
            system_prompt="You are a technical wiki writer. Output Markdown only.",
            user_prompt=prompt, temperature=0.3, max_tokens=8192,
        ),
    )

    body = _clean_page_body(body)

    now = _utcnow()
    frontmatter = {
        "title": classification.page_title,
        "slug": classification.page_slug,
        "category": classification.category,
        "subcategory": classification.subcategory,
        "sources": [{"file": source_file.filename, "hash": source_file.content_hash}],
        "topics": extracted.topics or [],
        "summary": extracted.summary or "",
        "generated_by": f"{project.llm_provider}/{project.llm_model}",
        "version": 1,
        "word_count": len(body.split()),
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    page = (await session.execute(
        select(WikiPage).where(
            WikiPage.project_id == project.id, WikiPage.slug == classification.page_slug
        )
    )).scalar_one_or_none()

    if page is None:
        page = WikiPage(
            project_id=project.id, slug=classification.page_slug,
            title=classification.page_title, category=classification.category,
            subcategory=classification.subcategory, content_md=body,
            frontmatter=frontmatter, source_file_ids=[source_file_id],
            word_count=len(body.split()),
        )
        session.add(page)
    else:
        # Keep the version counter and creation date across regenerations; the page
        # has a history even though the Markdown is replaced wholesale.
        frontmatter["version"] = page.version + 1
        frontmatter["created_at"] = (page.frontmatter or {}).get(
            "created_at", now.isoformat()
        )
        page.title = classification.page_title
        page.category = classification.category
        page.subcategory = classification.subcategory
        page.content_md = body
        page.frontmatter = frontmatter
        page.word_count = len(body.split())
        page.version += 1
        page.updated_at = now
        ids = list(page.source_file_ids or [])
        if source_file_id not in ids:
            ids.append(source_file_id)
        page.source_file_ids = ids

    source_file.status = "generated"
    await session.commit()


def _vector_text(page) -> str:
    """What gets vectorised for a page.

    Title and topics are repeated ahead of the body so they carry more weight than
    an equal number of body words: they are the distilled subject of the page, and
    two pages about the same thing share topics long before they share prose.
    """
    topics = " ".join((page.frontmatter or {}).get("topics", []))
    return f"{page.title} {page.title} {topics} {topics}\n{page.content_md}"


# --------------------------------------------------------------------------- 6
async def crosslink(session: AsyncSession, source_file_id: str, job_id: str | None = None) -> None:
    from .prompts import render_prompt

    source_file = await _get_file(session, source_file_id)
    project = await _get_project(session, source_file.project_id)
    classification = (await session.execute(
        select(Classification).where(Classification.source_file_id == source_file_id)
    )).scalar_one_or_none()
    if classification is None:
        raise StageError("This file has not been classified")

    page = (await session.execute(
        select(WikiPage).where(
            WikiPage.project_id == project.id, WikiPage.slug == classification.page_slug
        )
    )).scalar_one_or_none()
    if page is None:
        raise StageError("The wiki page for this file does not exist yet")

    vector = vectorise(_vector_text(page))
    page.embedding = to_bytes(vector)

    others = (await session.execute(
        select(WikiPage).where(
            WikiPage.project_id == project.id, WikiPage.slug != page.slug
        )
    )).scalars().all()

    candidates = []
    for other in others:
        other_vector = from_bytes(other.embedding)
        if other_vector is None:
            # A page published before this stage ever ran has no vector; compute one
            # now rather than skip it, or early pages would never gain links.
            other_vector = vectorise(_vector_text(other))
            other.embedding = to_bytes(other_vector)
        score = cosine(vector, other_vector)
        if score >= CROSSLINK_PREFILTER:
            candidates.append(
                {
                    "slug": other.slug, "title": other.title,
                    "topics": (other.frontmatter or {}).get("topics", []),
                    "similarity": score,
                }
            )

    candidates.sort(key=lambda item: item["similarity"], reverse=True)
    candidates = candidates[:CROSSLINK_MAX_CANDIDATES]

    cross_refs: list[dict] = []
    if candidates:
        extracted = (await session.execute(
            select(ExtractedData).where(ExtractedData.source_file_id == source_file_id)
        )).scalar_one_or_none()
        prompt = render_prompt(
            "crosslink.j2",
            {
                "current_title": page.title,
                "current_summary": (extracted.summary if extracted else "") or "",
                "current_topics": (extracted.topics if extracted else []) or [],
                "candidates": candidates,
            },
        )
        try:
            raw = await _call_llm(
                session, project, "crosslink", job_id,
                LLMRequest(
                    system_prompt="You judge wiki page relationships. Return a JSON array.",
                    user_prompt=prompt, response_format="json", temperature=0.2,
                    max_tokens=1536,
                ),
            )
            judged = parse_json_reply(raw)
        except (StageError, ValueError) as cause:
            # Cross-links are an enhancement. Losing them must not cost the page, so
            # fall back to the lexical scores rather than failing the stage.
            logger.warning("crosslink refinement failed for %s: %s", page.slug, cause)
            judged = [
                {"slug": c["slug"], "title": c["title"], "relevance": round(c["similarity"], 3)}
                for c in candidates[:5]
            ]

        known = {c["slug"] for c in candidates}
        for item in judged if isinstance(judged, list) else []:
            if not isinstance(item, dict):
                continue
            slug = item.get("slug")
            # Only accept slugs that were offered — models invent plausible pages.
            if slug in known:
                cross_refs.append(
                    {
                        "slug": slug,
                        "title": str(item.get("title") or slug),
                        "relevance": round(float(item.get("relevance") or 0.0), 4),
                        "reason": str(item.get("reason") or "")[:200],
                    }
                )

    page.cross_refs = cross_refs
    frontmatter = dict(page.frontmatter or {})
    frontmatter["cross_refs"] = cross_refs
    page.frontmatter = frontmatter

    source_file.status = "crosslinked"
    await session.commit()


# --------------------------------------------------------------------------- 7
async def publish(session: AsyncSession, source_file_id: str, job_id: str | None = None) -> None:
    import json

    source_file = await _get_file(session, source_file_id)
    project = await _get_project(session, source_file.project_id)
    classification = (await session.execute(
        select(Classification).where(Classification.source_file_id == source_file_id)
    )).scalar_one_or_none()
    if classification is None:
        raise StageError("This file has not been classified")

    page = (await session.execute(
        select(WikiPage).where(
            WikiPage.project_id == project.id, WikiPage.slug == classification.page_slug
        )
    )).scalar_one_or_none()
    if page is None:
        raise StageError("The wiki page for this file does not exist yet")

    page.content_html = render_markdown(page.content_md)

    pages = (await session.execute(
        select(WikiPage).where(WikiPage.project_id == project.id)
    )).scalars().all()

    # Writing the wiki to disk is what FR-5 promises ("exportable as static site"),
    # but a read-only or full volume must not lose the page — the database row is
    # the source of truth, so a write failure is a warning, not a stage failure.
    try:
        output_dir = Path(project.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{page.slug}.md").write_text(
            build_markdown_file(page.frontmatter or {}, page.content_md), encoding="utf-8"
        )
        (output_dir / f"{page.slug}.html").write_text(page.content_html, encoding="utf-8")
        (output_dir / "tree.json").write_text(
            json.dumps(build_navigation_tree(project.name, list(pages)), indent=2),
            encoding="utf-8",
        )
        (output_dir / "index.json").write_text(
            json.dumps(build_search_index(list(pages)), indent=2), encoding="utf-8"
        )
    except OSError as cause:
        logger.warning("could not write wiki output for %s: %s", page.slug, cause)

    source_file.status = "published"
    source_file.processed_at = _utcnow()
    source_file.error_message = None
    await session.commit()


STAGE_FUNCTIONS = {
    "ingest": ingest, "parse": parse, "extract": extract, "classify": classify,
    "generate": generate, "crosslink": crosslink, "publish": publish,
}
