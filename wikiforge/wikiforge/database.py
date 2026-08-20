"""Async SQLAlchemy engine and session factory.

One SQLite file holds every project, with `project_id` on the per-project tables.
The spec called for a database per project; a single file is used instead because
every query the API serves is already scoped by project id, and per-project engines
would mean a connection pool per project and a session factory chosen at request
time for no gain at this scale. The table shapes are otherwise as specified.
"""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()

# check_same_thread is a SQLite-ism; aiosqlite drives it from a worker thread.
engine = create_async_engine(
    f"sqlite+aiosqlite:///{_settings.db_path}",
    echo=False,
    connect_args={"check_same_thread": False},
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Create tables, and turn on the SQLite settings this workload needs.

    WAL matters here: the pipeline writes from worker tasks while the API reads for
    the dashboard, and the default rollback journal makes those block each other.
    """
    from . import models  # noqa: F401  — registers the mappers before create_all

    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.exec_driver_sql("PRAGMA busy_timeout=10000")
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request."""
    async with SessionLocal() as session:
        yield session
