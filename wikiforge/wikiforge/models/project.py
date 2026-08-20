"""A project binds a source directory to a wiki output directory."""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from ._common import new_id, utcnow

#: Lifecycle states. `error` is set by the watcher or pipeline, never by the user.
PROJECT_STATUSES = ("created", "active", "paused", "error")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    source_dir: Mapped[str] = mapped_column(String, nullable=False)
    output_dir: Mapped[str] = mapped_column(String, nullable=False)
    llm_provider: Mapped[str] = mapped_column(String, nullable=False, default="switchboard")
    llm_model: Mapped[str] = mapped_column(String, nullable=False, default="ag/claude-sonnet-4-6")
    watch_interval: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    update_mode: Mapped[str] = mapped_column(String, nullable=False, default="delta")
    status: Mapped[str] = mapped_column(String, nullable=False, default="created")
    wiki_url: Mapped[str | None] = mapped_column(String, nullable=True)
    owner: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
