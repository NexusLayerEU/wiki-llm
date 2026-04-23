# WikiForge — Processing Pipeline

## Pipeline Stages

The pipeline processes each file through 7 sequential stages. Each stage is an independent job that can be retried on failure.

```
INGEST → PARSE → EXTRACT → CLASSIFY → GENERATE → CROSSLINK → PUBLISH
```

### Stage 1: INGEST
**Input**: File path detected by watcher or uploaded via API
**Output**: File copied to working directory, SourceFile record created
**LLM**: No
```python
async def ingest(source_file_id: str):
    source_file = db.get(SourceFile, source_file_id)
    filepath = project.source_dir / source_file.filepath

    # Verify file exists and is readable
    if not filepath.exists():
        raise FileNotFoundError(f"Source file missing: {filepath}")

    # Compute hash for change detection
    content_hash = sha256(filepath.read_bytes()).hexdigest()

    # Check if already processed with same hash
    if source_file.content_hash == content_hash and source_file.status == "published":
        return  # Skip — file unchanged

    source_file.content_hash = content_hash
    source_file.file_size = filepath.stat().st_size
    source_file.status = "ingested"
    db.commit()
```

### Stage 2: PARSE
**Input**: Ingested source file
**Output**: ParsedContent record in database
**LLM**: No
```python
async def parse(source_file_id: str):
    source_file = db.get(SourceFile, source_file_id)
    filepath = project.source_dir / source_file.filepath

    parser = ParserRegistry.get_parser(str(filepath))
    if not parser:
        source_file.status = "error"
        source_file.error_message = f"No parser for {source_file.file_extension}"
        db.commit()
        return

    parsed = parser.parse(str(filepath))

    # Store parsed content
    db.upsert(ParsedContent(
        source_file_id=source_file_id,
        content_text=parsed.full_text,
        content_structured=parsed.to_dict(),  # Sections, tables as JSON
        metadata=parsed.metadata,
        section_count=parsed.section_count,
        word_count=parsed.word_count,
    ))

    source_file.status = "parsed"
    db.commit()
```

### Stage 3: EXTRACT
**Input**: Parsed content
**Output**: ExtractedData record (summary, topics, entities, key points)
**LLM**: Yes — uses `extract.j2` prompt
```python
async def extract(source_file_id: str):
    source_file = db.get(SourceFile, source_file_id)
    parsed = db.get_by(ParsedContent, source_file_id=source_file_id)

    # Build LLM request using prompt template
    prompt = render_template("extract.j2", {
        "filename": source_file.filename,
        "file_type": source_file.file_extension,
        "section_count": parsed.section_count,
        "content": parsed.content_text,
    })

    llm = get_provider(project.llm_provider, project.llm_model)
    response = await llm.complete(LLMRequest(
        system_prompt="You are a document analysis expert. Return valid JSON only.",
        user_prompt=prompt,
        response_format="json",
        temperature=0.2,
    ))

    # Track usage
    track_llm_usage(response, stage="extract", job_id=job.id)

    # Parse LLM JSON response
    data = json.loads(response.content)

    db.upsert(ExtractedData(
        source_file_id=source_file_id,
        summary=data["summary"],
        topics=data["topics"],
        entities=data["entities"],
        key_points=data["key_points"],
        raw_llm_output=response.content,
    ))

    source_file.status = "extracted"
    db.commit()
```

### Stage 4: CLASSIFY
**Input**: Extracted data + existing wiki categories
**Output**: Classification record (category, page title, slug)
**LLM**: Yes — uses `classify.j2` prompt
```python
async def classify(source_file_id: str):
    extracted = db.get_by(ExtractedData, source_file_id=source_file_id)

    # Get existing categories for context
    existing_categories = db.query(
        "SELECT DISTINCT category, COUNT(*) as page_count FROM wiki_pages GROUP BY category"
    )

    prompt = render_template("classify.j2", {
        "summary": extracted.summary,
        "topics": extracted.topics,
        "key_points": extracted.key_points,
        "existing_categories": existing_categories,
    })

    llm = get_provider(project.llm_provider, project.llm_model)
    response = await llm.complete(LLMRequest(
        system_prompt="You are a wiki organizer. Return valid JSON only.",
        user_prompt=prompt,
        response_format="json",
        temperature=0.2,
    ))

    track_llm_usage(response, stage="classify", job_id=job.id)
    data = json.loads(response.content)

    db.upsert(Classification(
        source_file_id=source_file_id,
        category=data["category"],
        subcategory=data.get("subcategory"),
        page_title=data["page_title"],
        page_slug=data["page_slug"],
        confidence=data.get("confidence", 0.0),
        raw_llm_output=response.content,
    ))

    source_file.status = "classified"
    db.commit()
```

### Stage 5: GENERATE
**Input**: Parsed content + extracted data + classification
**Output**: Wiki page Markdown file + WikiPage record
**LLM**: Yes — uses `generate_wiki.j2` prompt
```python
async def generate(source_file_id: str):
    parsed = db.get_by(ParsedContent, source_file_id=source_file_id)
    extracted = db.get_by(ExtractedData, source_file_id=source_file_id)
    classification = db.get_by(Classification, source_file_id=source_file_id)

    prompt = render_template("generate_wiki.j2", {
        "page_title": classification.page_title,
        "category": classification.category,
        "subcategory": classification.subcategory,
        "content": parsed.content_text,
        "summary": extracted.summary,
        "key_points": extracted.key_points,
    })

    llm = get_provider(project.llm_provider, project.llm_model)
    response = await llm.complete(LLMRequest(
        system_prompt="You are a technical wiki writer. Output Markdown only.",
        user_prompt=prompt,
        temperature=0.3,
        max_tokens=8192,
    ))

    track_llm_usage(response, stage="generate", job_id=job.id)

    # Build frontmatter
    frontmatter = {
        "title": classification.page_title,
        "slug": classification.page_slug,
        "category": classification.category,
        "subcategory": classification.subcategory,
        "sources": [{"file": source_file.filename, "hash": source_file.content_hash}],
        "topics": extracted.topics,
        "generated_by": f"{project.llm_provider}/{project.llm_model}",
        "version": 1,  # Incremented on updates
        "created_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }

    # Write Markdown file with frontmatter
    md_content = f"---\n{yaml.dump(frontmatter)}---\n\n{response.content}"
    output_path = project.output_dir / f"{classification.page_slug}.md"
    output_path.write_text(md_content, encoding="utf-8")

    # Create/update WikiPage record
    existing = db.get_by(WikiPage, slug=classification.page_slug)
    if existing:
        existing.content_md = response.content
        existing.frontmatter = frontmatter
        existing.version += 1
        existing.updated_at = datetime.utcnow()
    else:
        db.add(WikiPage(
            slug=classification.page_slug,
            title=classification.page_title,
            category=classification.category,
            subcategory=classification.subcategory,
            content_md=response.content,
            frontmatter=frontmatter,
            source_file_ids=[source_file_id],
            word_count=len(response.content.split()),
        ))

    source_file.status = "generated"
    db.commit()
```

### Stage 6: CROSSLINK
**Input**: Generated wiki page + all other wiki pages
**Output**: Cross-reference links embedded in wiki pages
**LLM**: Yes (for embedding) + uses `crosslink.j2` prompt for refinement
```python
async def crosslink(source_file_id: str):
    classification = db.get_by(Classification, source_file_id=source_file_id)
    wiki_page = db.get_by(WikiPage, slug=classification.page_slug)
    extracted = db.get_by(ExtractedData, source_file_id=source_file_id)

    # Generate embedding for this page
    llm = get_provider(project.llm_provider, project.llm_model)
    embedding = await llm.embed(wiki_page.content_md[:4000])
    wiki_page.embedding = numpy.array(embedding, dtype="float32").tobytes()

    # Find similar pages by cosine similarity
    all_pages = db.query(WikiPage).filter(WikiPage.slug != wiki_page.slug).all()
    candidates = []

    for page in all_pages:
        if page.embedding:
            page_emb = numpy.frombuffer(page.embedding, dtype="float32")
            current_emb = numpy.array(embedding, dtype="float32")
            similarity = numpy.dot(current_emb, page_emb) / (
                numpy.linalg.norm(current_emb) * numpy.linalg.norm(page_emb)
            )
            if similarity > 0.3:  # Pre-filter threshold
                candidates.append({
                    "slug": page.slug,
                    "title": page.title,
                    "summary": page.frontmatter.get("summary", ""),
                    "topics": page.frontmatter.get("topics", []),
                    "similarity": float(similarity),
                })

    # If we have candidates, use LLM to refine and explain connections
    if candidates:
        # Sort by similarity, take top 10
        candidates.sort(key=lambda x: x["similarity"], reverse=True)
        candidates = candidates[:10]

        prompt = render_template("crosslink.j2", {
            "current_title": wiki_page.title,
            "current_summary": extracted.summary,
            "current_topics": extracted.topics,
            "candidates": candidates,
        })

        response = await llm.complete(LLMRequest(
            system_prompt="You are analyzing wiki page connections. Return valid JSON array.",
            user_prompt=prompt,
            response_format="json",
            temperature=0.2,
        ))

        track_llm_usage(response, stage="crosslink", job_id=job.id)
        cross_refs = json.loads(response.content)
    else:
        cross_refs = []

    wiki_page.cross_refs = cross_refs
    source_file.status = "crosslinked"
    db.commit()
```

### Stage 7: PUBLISH
**Input**: Cross-linked wiki page
**Output**: HTML rendered, navigation tree updated, wiki index refreshed
**LLM**: No
```python
async def publish(source_file_id: str):
    classification = db.get_by(Classification, source_file_id=source_file_id)
    wiki_page = db.get_by(WikiPage, slug=classification.page_slug)

    # Render Markdown → HTML
    html = render_markdown(wiki_page.content_md, {
        "cross_refs": wiki_page.cross_refs,
        "title": wiki_page.title,
    })
    wiki_page.content_html = html

    # Rebuild navigation tree
    tree = build_navigation_tree(db.query(WikiPage).all())
    tree_path = project.output_dir / "tree.json"
    tree_path.write_text(json.dumps(tree, indent=2))

    # Update wiki index
    index = build_search_index(db.query(WikiPage).all())
    index_path = project.output_dir / "index.json"
    index_path.write_text(json.dumps(index))

    # Write HTML file
    html_path = project.output_dir / f"{wiki_page.slug}.html"
    html_path.write_text(html)

    source_file.status = "published"
    source_file.processed_at = datetime.utcnow()
    db.commit()
```

## Job Queue

### Interface

```python
# wikiforge/pipeline/job_queue.py

from abc import ABC, abstractmethod


class JobQueue(ABC):
    @abstractmethod
    async def enqueue(self, stage: str, source_file_id: str, priority: int = 5) -> str:
        """Add a job to the queue. Returns job ID."""
        ...

    @abstractmethod
    async def get_status(self, job_id: str) -> dict:
        """Get job status."""
        ...

    @abstractmethod
    async def cancel(self, job_id: str) -> bool:
        """Cancel a queued job."""
        ...
```

### In-Process Queue (Redis-free mode)

```python
class InProcessQueue(JobQueue):
    """Simple asyncio-based queue for single-process deployments."""

    def __init__(self, max_workers: int = 4):
        self._queue = asyncio.PriorityQueue()
        self._workers = []
        self._max_workers = max_workers

    async def start(self):
        for i in range(self._max_workers):
            worker = asyncio.create_task(self._worker_loop(i))
            self._workers.append(worker)

    async def _worker_loop(self, worker_id: int):
        while True:
            priority, job = await self._queue.get()
            try:
                await self._execute_job(job)
            except Exception as e:
                await self._handle_failure(job, e)
            finally:
                self._queue.task_done()
```

### Celery Queue (Production mode)

```python
class CeleryQueue(JobQueue):
    """Celery-backed queue for multi-worker deployments."""

    def __init__(self, celery_app):
        self.app = celery_app

    async def enqueue(self, stage: str, source_file_id: str, priority: int = 5) -> str:
        task = self.app.send_task(
            f"wikiforge.pipeline.tasks.{stage}",
            args=[source_file_id],
            priority=priority,
        )
        return task.id
```

## Pipeline Executor

```python
# wikiforge/pipeline/executor.py

STAGE_ORDER = ["ingest", "parse", "extract", "classify", "generate", "crosslink", "publish"]

class PipelineExecutor:
    def __init__(self, queue: JobQueue, db: Database):
        self.queue = queue
        self.db = db

    async def process_file(self, source_file_id: str):
        """Enqueue all pipeline stages for a file."""
        for i, stage in enumerate(STAGE_ORDER):
            job = Job(
                source_file_id=source_file_id,
                stage=stage,
                status="queued",
                priority=i + 1,  # Earlier stages have higher priority
            )
            self.db.add(job)
            await self.queue.enqueue(stage, source_file_id, priority=i + 1)

    async def reprocess_file(self, source_file_id: str, from_stage: str = "ingest"):
        """Re-enqueue from a specific stage (for retries or updates)."""
        start_idx = STAGE_ORDER.index(from_stage)
        for i, stage in enumerate(STAGE_ORDER[start_idx:], start=start_idx):
            await self.queue.enqueue(stage, source_file_id, priority=i + 1)

    async def rebuild_project(self, project_id: str):
        """Full rebuild: reprocess all files from ingest."""
        files = self.db.query(SourceFile).filter_by(project_id=project_id).all()
        for f in files:
            f.status = "pending"
            await self.process_file(f.id)

    def get_progress(self, project_id: str) -> dict:
        """Calculate pipeline progress for a project."""
        files = self.db.query(SourceFile).filter_by(project_id=project_id).all()
        total = len(files)
        if total == 0:
            return {"progress_pct": 0, "total": 0, "by_status": {}}

        by_status = {}
        for f in files:
            by_status[f.status] = by_status.get(f.status, 0) + 1

        published = by_status.get("published", 0)
        progress = (published / total) * 100 if total > 0 else 0

        return {
            "progress_pct": round(progress, 1),
            "total_files": total,
            "files_by_status": by_status,
            "published": published,
        }
```

## Retry and Error Handling

```python
RETRY_CONFIG = {
    "max_attempts": 3,
    "base_delay": 2,       # seconds
    "max_delay": 60,        # seconds
    "exponential_base": 2,  # delay = base_delay * (exponential_base ^ attempt)
}

async def execute_with_retry(stage_func, source_file_id: str, job: Job):
    for attempt in range(RETRY_CONFIG["max_attempts"]):
        try:
            job.attempt = attempt + 1
            job.status = "running"
            job.started_at = datetime.utcnow()
            db.commit()

            await stage_func(source_file_id)

            job.status = "completed"
            job.completed_at = datetime.utcnow()
            db.commit()
            return

        except RateLimitError as e:
            # Respect provider rate limits
            wait = e.retry_after or RETRY_CONFIG["max_delay"]
            logger.warning(f"Rate limited, waiting {wait}s")
            await asyncio.sleep(wait)

        except Exception as e:
            delay = min(
                RETRY_CONFIG["base_delay"] * (RETRY_CONFIG["exponential_base"] ** attempt),
                RETRY_CONFIG["max_delay"],
            )
            logger.error(f"Stage {job.stage} attempt {attempt+1} failed: {e}")

            if attempt + 1 >= RETRY_CONFIG["max_attempts"]:
                job.status = "failed"
                job.error_message = str(e)
                source_file = db.get(SourceFile, source_file_id)
                source_file.status = "error"
                source_file.error_message = f"Stage {job.stage} failed: {e}"
                db.commit()
                return

            await asyncio.sleep(delay)
```
