"""Project queries shared by the routers."""
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Project, SourceFile, WikiPage
from ..schemas import ProjectResponse


async def get_or_404(session: AsyncSession, project_id: str) -> Project:
    """Look a project up by id or slug — the API_SPEC examples use both."""
    project = await session.get(Project, project_id)
    if project is None:
        project = (
            await session.execute(select(Project).where(Project.slug == project_id))
        ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail=f"No project '{project_id}'.")
    return project


async def to_response(session: AsyncSession, project: Project) -> ProjectResponse:
    files = (
        await session.execute(
            select(func.count(SourceFile.id)).where(
                SourceFile.project_id == project.id, SourceFile.status != "deleted"
            )
        )
    ).scalar() or 0
    pages = (
        await session.execute(
            select(func.count(WikiPage.id)).where(WikiPage.project_id == project.id)
        )
    ).scalar() or 0
    return ProjectResponse(
        **{
            column.name: getattr(project, column.name)
            for column in Project.__table__.columns
            if column.name in ProjectResponse.model_fields
        },
        file_count=files,
        page_count=pages,
    )


def managed_dirs(slug: str) -> tuple[Path, Path]:
    """Where a project's files live when the caller does not supply paths."""
    root = get_settings().data_dir / "projects" / slug
    return root / "source", root / "wiki"
