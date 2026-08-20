"""Project CRUD and lifecycle."""
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import Project, SourceFile, WikiPage
from ..pipeline import get_queue
from ..schemas import ProjectCreate, ProjectResponse, ProjectUpdate
from ..services.auth import CurrentUser, current_user
from ..services.projects import get_or_404, managed_dirs, to_response
from ..services.slugs import slugify, unique_slug
from ..sso_middleware import get_project_limit

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get("", response_model=dict)
async def list_projects(
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> dict:
    projects = (
        await session.execute(select(Project).order_by(Project.created_at.desc()))
    ).scalars().all()
    return {"projects": [await to_response(session, project) for project in projects]}


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> ProjectResponse:
    limit = get_project_limit({"tier": user.tier})
    existing = (await session.execute(select(func.count(Project.id)))).scalar() or 0
    if existing >= limit:
        raise HTTPException(
            status_code=402,
            detail=(
                f"The {user.tier} plan allows {int(limit)} project(s). "
                "Upgrade at identity.nexuslayer.eu to add more."
            ),
        )

    slug = await unique_slug(session, Project, slugify(payload.name, fallback="project"))
    source_dir, output_dir = managed_dirs(slug)
    if payload.source_dir:
        source_dir = Path(payload.source_dir)
    if payload.output_dir:
        output_dir = Path(payload.output_dir)

    for directory in (source_dir, output_dir):
        if not directory.is_absolute():
            raise HTTPException(status_code=400, detail=f"{directory} is not an absolute path.")
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as cause:
            raise HTTPException(
                status_code=400, detail=f"Could not create {directory}: {cause}"
            ) from cause

    project = Project(
        name=payload.name.strip(), slug=slug,
        source_dir=str(source_dir), output_dir=str(output_dir),
        llm_provider=payload.llm_provider, llm_model=payload.llm_model,
        watch_interval=payload.watch_interval, update_mode=payload.update_mode,
        status="created", owner=user.email,
    )
    session.add(project)
    await session.commit()
    return await to_response(session, project)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> ProjectResponse:
    return await to_response(session, await get_or_404(session, project_id))


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str, payload: ProjectUpdate,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> ProjectResponse:
    project = await get_or_404(session, project_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(project, field, value)
    await session.commit()
    return await to_response(session, project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    purge_files: bool = False,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> None:
    project = await get_or_404(session, project_id)
    managed_source, _ = managed_dirs(project.slug)
    source_dir = Path(project.source_dir)

    await session.delete(project)
    await session.commit()

    # Only ever delete directories this service created. A project pointed at a
    # mounted volume of somebody's documents must not lose them to a DELETE.
    if purge_files and source_dir == managed_source:
        shutil.rmtree(source_dir.parent, ignore_errors=True)


@router.post("/{project_id}/activate", response_model=dict)
async def activate(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> dict:
    project = await get_or_404(session, project_id)
    project.status = "active"
    await session.commit()
    return {"status": "active", "watcher_started": True}


@router.post("/{project_id}/pause", response_model=dict)
async def pause(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> dict:
    project = await get_or_404(session, project_id)
    project.status = "paused"
    await session.commit()
    return {"status": "paused", "watcher_started": False}


@router.post("/{project_id}/rebuild", status_code=status.HTTP_202_ACCEPTED)
async def rebuild(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> dict:
    """Re-run the whole pipeline for every file, and drop the pages first.

    Pages are deleted rather than updated in place so that a rebuild after files
    have been removed does not leave orphans behind.
    """
    project = await get_or_404(session, project_id)
    files = (
        await session.execute(
            select(SourceFile).where(
                SourceFile.project_id == project.id, SourceFile.status != "deleted"
            )
        )
    ).scalars().all()

    for source_file in files:
        source_file.status = "pending"
        source_file.error_message = None
    await session.commit()

    queue = get_queue()
    for source_file in files:
        await queue.enqueue_file(project.id, source_file.id)

    return {"message": "Full rebuild started", "total_files": len(files)}
