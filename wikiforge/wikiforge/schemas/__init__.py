"""Pydantic request/response models, per DATA_MODELS.md."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    # Both directories are optional: with none given the service manages them under
    # its data dir, which is what the UI does. A path is for mounted volumes.
    source_dir: str | None = None
    output_dir: str | None = None
    llm_provider: str = "switchboard"
    llm_model: str = "ag/claude-sonnet-4-6"
    watch_interval: int = Field(10, ge=1, le=3600)
    update_mode: Literal["delta", "full"] = "delta"


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    llm_provider: str | None = None
    llm_model: str | None = None
    watch_interval: int | None = Field(None, ge=1, le=3600)
    update_mode: Literal["delta", "full"] | None = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    source_dir: str
    output_dir: str
    llm_provider: str
    llm_model: str
    watch_interval: int
    update_mode: str
    status: str
    wiki_url: str | None = None
    file_count: int = 0
    page_count: int = 0
    created_at: datetime
    updated_at: datetime


class FileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    filepath: str
    file_extension: str
    file_size: int
    # SHA-256 of the bytes on disk. A sync client diffs against this instead of
    # downloading every file to find out what changed.
    content_hash: str = ""
    status: str
    error_message: str | None = None
    wiki_page_slug: str | None = None
    discovered_at: datetime
    processed_at: datetime | None = None


class FileList(BaseModel):
    files: list[FileResponse]
    total: int
    limit: int
    offset: int


class CrossRef(BaseModel):
    slug: str
    title: str
    relevance: float = 0.0
    reason: str | None = None


class PageSummary(BaseModel):
    slug: str
    title: str
    category: str
    subcategory: str | None = None
    word_count: int = 0
    version: int = 1
    sources: list[str] = []
    cross_ref_count: int = 0
    snippet: str = ""
    updated_at: datetime


class WikiPageResponse(BaseModel):
    slug: str
    title: str
    category: str
    subcategory: str | None = None
    content_md: str = ""
    content_html: str | None = None
    sources: list[dict] = []
    cross_refs: list[CrossRef] = []
    topics: list[str] = []
    summary: str = ""
    version: int = 1
    word_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class JobStatus(BaseModel):
    id: str
    source_file: str
    stage: str
    status: str
    attempt: int
    started_at: datetime | None = None


class PipelineStatus(BaseModel):
    project_id: str
    status: str
    total_files: int
    files_by_status: dict[str, int]
    progress_pct: float
    active_jobs: list[JobStatus]
    eta_seconds: int | None = None
    queue_depth: int = 0


class SearchHit(BaseModel):
    slug: str
    title: str
    category: str
    relevance: float
    snippet: str


class AgentQuery(BaseModel):
    question: str = Field(..., min_length=2)
    project_id: str
    format: Literal["markdown", "html", "text"] = "markdown"
    include_sources: bool = True
    max_results: int = Field(5, ge=1, le=20)


class SourceReference(BaseModel):
    filename: str
    wiki_page: str | None = None
    relevance: float = 0.0


class AgentResponse(BaseModel):
    answer: str
    sources: list[SourceReference] = []
    confidence: float = 0.0
    wiki_pages: list[str] = []
