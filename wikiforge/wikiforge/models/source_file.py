"""Source files and the per-stage records the pipeline writes about them."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from ._common import new_id, utcnow

#: The file state machine, in pipeline order. `error` and `deleted` are terminal
#: until the file changes on disk, which resets it to `pending`.
FILE_STATUSES = (
    "pending", "ingested", "parsed", "extracted", "classified",
    "generated", "crosslinked", "published", "error", "deleted",
)


class SourceFile(Base):
    __tablename__ = "source_files"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String, nullable=False)
    filepath: Mapped[str] = mapped_column(String, nullable=False)
    file_extension: Mapped[str] = mapped_column(String, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str] = mapped_column(String, nullable=False, default="", index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ParsedContent(Base):
    """Text and structure pulled out of a file. No LLM involved."""

    __tablename__ = "parsed_content"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    source_file_id: Mapped[str] = mapped_column(
        String, ForeignKey("source_files.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    content_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_structured: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    file_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    section_count: Mapped[int] = mapped_column(Integer, default=0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExtractedData(Base):
    """What the model found in the text: summary, topics, entities, key points."""

    __tablename__ = "extracted_data"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    source_file_id: Mapped[str] = mapped_column(
        String, ForeignKey("source_files.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    topics: Mapped[list | None] = mapped_column(JSON, nullable=True)
    entities: Mapped[list | None] = mapped_column(JSON, nullable=True)
    key_points: Mapped[list | None] = mapped_column(JSON, nullable=True)
    raw_llm_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Classification(Base):
    """Where the page belongs in the wiki, and what to call it."""

    __tablename__ = "classifications"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    source_file_id: Mapped[str] = mapped_column(
        String, ForeignKey("source_files.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    category: Mapped[str] = mapped_column(String, nullable=False, default="Uncategorised")
    subcategory: Mapped[str | None] = mapped_column(String, nullable=True)
    page_title: Mapped[str] = mapped_column(String, nullable=False, default="Untitled")
    page_slug: Mapped[str] = mapped_column(String, nullable=False, default="untitled")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    raw_llm_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
