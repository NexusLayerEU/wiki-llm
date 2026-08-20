"""A generated wiki page."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from ._common import new_id, utcnow


class WikiPage(Base):
    __tablename__ = "wiki_pages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Unique per project, not globally: two projects may both have an "overview".
    slug: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False, index=True)
    subcategory: Mapped[str | None] = mapped_column(String, nullable=True)
    content_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    frontmatter: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_file_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    # Term-frequency vector for cross-linking, stored as float32 bytes. The spec used
    # provider embeddings; SwitchBoard serves none, so this is computed locally.
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    cross_refs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
