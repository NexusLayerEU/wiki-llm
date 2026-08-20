"""Source file listing, upload, deletion, reprocessing and directory sync."""
import hashlib
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import Classification, SourceFile, WikiPage
from ..parsers import SUPPORTED_EXTENSIONS
from ..pipeline import get_queue
from ..schemas import FileList
from ..schemas import FileResponse as FileSchema
from ..services.auth import CurrentUser, current_user
from ..services.projects import get_or_404

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/projects", tags=["files"])

#: Read in chunks so a large upload never sits in memory whole.
CHUNK_BYTES = 1024 * 1024
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


async def _page_slug_for(session: AsyncSession, source_file_id: str) -> str | None:
    return (
        await session.execute(
            select(Classification.page_slug).where(
                Classification.source_file_id == source_file_id
            )
        )
    ).scalar_one_or_none()


@router.get("/{project_id}/files", response_model=FileList)
async def list_files(
    project_id: str,
    status_filter: str | None = None,
    extension: str | None = None,
    sort: str = "filename",
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> FileList:
    project = await get_or_404(session, project_id)
    limit = max(1, min(limit, 500))

    query = select(SourceFile).where(SourceFile.project_id == project.id)
    if status_filter:
        query = query.where(SourceFile.status == status_filter)
    if extension:
        query = query.where(SourceFile.file_extension == extension.lower())

    total = (
        await session.execute(select(func.count()).select_from(query.subquery()))
    ).scalar() or 0

    order = {
        "filename": SourceFile.filename.asc(),
        "modified": SourceFile.updated_at.desc(),
        "status": SourceFile.status.asc(),
        "size": SourceFile.file_size.desc(),
    }.get(sort, SourceFile.filename.asc())

    rows = (
        await session.execute(query.order_by(order).limit(limit).offset(offset))
    ).scalars().all()

    files = []
    for source_file in rows:
        files.append(
            FileSchema(
                **{
                    field: getattr(source_file, field)
                    for field in FileSchema.model_fields
                    if field != "wiki_page_slug"
                },
                wiki_page_slug=await _page_slug_for(session, source_file.id),
            )
        )
    return FileList(files=files, total=total, limit=limit, offset=offset)


@router.post("/{project_id}/files", status_code=status.HTTP_202_ACCEPTED)
async def upload_files(
    project_id: str,
    files: list[UploadFile] = File(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> dict:
    project = await get_or_404(session, project_id)
    source_dir = Path(project.source_dir)
    source_dir.mkdir(parents=True, exist_ok=True)

    uploaded: list[dict] = []
    rejected: list[dict] = []

    for upload in files:
        # Take the basename only: a multipart filename can contain path separators,
        # and "../../etc/whatever" must not escape the source directory.
        name = Path(upload.filename or "unnamed").name
        extension = Path(name).suffix.lower()

        if extension not in SUPPORTED_EXTENSIONS:
            rejected.append({"filename": name, "reason": f"{extension or 'no extension'} is not supported"})
            continue

        destination = source_dir / name
        written = 0
        digest = hashlib.sha256()
        try:
            with destination.open("wb") as handle:
                while chunk := await upload.read(CHUNK_BYTES):
                    written += len(chunk)
                    if written > MAX_UPLOAD_BYTES:
                        raise ValueError("file exceeds the 100 MB limit")
                    digest.update(chunk)
                    handle.write(chunk)
        except (OSError, ValueError) as cause:
            destination.unlink(missing_ok=True)
            rejected.append({"filename": name, "reason": str(cause)})
            continue

        existing = (
            await session.execute(
                select(SourceFile).where(
                    SourceFile.project_id == project.id, SourceFile.filepath == name
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            source_file = SourceFile(
                project_id=project.id, filename=name, filepath=name,
                file_extension=extension, file_size=written,
                content_hash=digest.hexdigest(), status="pending",
            )
            session.add(source_file)
        else:
            source_file = existing
            source_file.file_size = written
            source_file.content_hash = digest.hexdigest()
            source_file.status = "pending"
            source_file.error_message = None

        await session.commit()
        uploaded.append({"filename": name, "id": source_file.id, "status": "pending"})
        await get_queue().enqueue_file(project.id, source_file.id)

    if not uploaded and rejected:
        raise HTTPException(status_code=400, detail={"rejected": rejected})
    return {"uploaded": uploaded, "rejected": rejected}


@router.get("/{project_id}/files/{file_id}/content")
async def file_content(
    project_id: str, file_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
):
    """Return a source file exactly as it was uploaded.

    Needed for two-way sync: without it a client can push notes but never recover
    them onto a second machine. Text formats come back as UTF-8 text; anything
    binary (PDF, xlsx) as a download, so one endpoint serves both.
    """
    project = await get_or_404(session, project_id)
    source_file = await session.get(SourceFile, file_id)
    if source_file is None or source_file.project_id != project.id:
        raise HTTPException(status_code=404, detail="No such file in this project.")

    path = Path(project.source_dir) / source_file.filepath
    # Re-derive the path from the stored relative filepath and confirm it stays
    # inside the project. A filepath that escaped validation must not read /etc.
    try:
        resolved = path.resolve()
        resolved.relative_to(Path(project.source_dir).resolve())
    except (ValueError, OSError) as cause:
        raise HTTPException(status_code=400, detail="That file path is not valid.") from cause

    if not resolved.is_file():
        raise HTTPException(
            status_code=410,
            detail="The file is recorded but no longer on disk.",
        )

    TEXT = {".md", ".markdown", ".txt", ".csv", ".tsv"}
    if source_file.file_extension in TEXT:
        return Response(
            content=resolved.read_text(encoding="utf-8", errors="replace"),
            media_type="text/plain; charset=utf-8",
            headers={"X-Content-Hash": source_file.content_hash},
        )
    return FileResponse(
        resolved, filename=source_file.filename,
        headers={"X-Content-Hash": source_file.content_hash},
    )


@router.delete("/{project_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    project_id: str, file_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> None:
    project = await get_or_404(session, project_id)
    source_file = await session.get(SourceFile, file_id)
    if source_file is None or source_file.project_id != project.id:
        raise HTTPException(status_code=404, detail="No such file in this project.")

    slug = await _page_slug_for(session, file_id)
    if slug:
        page = (
            await session.execute(
                select(WikiPage).where(
                    WikiPage.project_id == project.id, WikiPage.slug == slug
                )
            )
        ).scalar_one_or_none()
        # Only remove the page if this was its only source; a page built from two
        # files should survive losing one of them.
        if page is not None and set(page.source_file_ids or []) <= {file_id}:
            await session.delete(page)
            for suffix in (".md", ".html"):
                (Path(project.output_dir) / f"{slug}{suffix}").unlink(missing_ok=True)

    (Path(project.source_dir) / source_file.filepath).unlink(missing_ok=True)
    await session.delete(source_file)
    await session.commit()


@router.post("/{project_id}/files/{file_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
async def reprocess(
    project_id: str, file_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> dict:
    project = await get_or_404(session, project_id)
    source_file = await session.get(SourceFile, file_id)
    if source_file is None or source_file.project_id != project.id:
        raise HTTPException(status_code=404, detail="No such file in this project.")

    source_file.status = "pending"
    source_file.error_message = None
    await session.commit()
    await get_queue().enqueue_file(project.id, source_file.id)
    return {"status": "queued", "file_id": file_id}


@router.post("/{project_id}/trigger-sync", response_model=dict)
async def trigger_sync(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> dict:
    """Re-scan the source directory and queue anything new or changed.

    This is the delta detection FR-8 describes, driven on demand rather than by a
    background watcher: one endpoint, called by the UI and by `POST` from outside,
    with no daemon to supervise.
    """
    project = await get_or_404(session, project_id)
    source_dir = Path(project.source_dir)
    if not source_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"{source_dir} is not a directory.")

    known = {
        row.filepath: row
        for row in (
            await session.execute(
                select(SourceFile).where(SourceFile.project_id == project.id)
            )
        ).scalars().all()
    }

    seen: set[str] = set()
    new_files = modified = 0
    queue = get_queue()

    for path in sorted(source_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        relative = str(path.relative_to(source_dir))
        seen.add(relative)
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as cause:
            logger.warning("could not read %s: %s", path, cause)
            continue

        existing = known.get(relative)
        if existing is None:
            source_file = SourceFile(
                project_id=project.id, filename=path.name, filepath=relative,
                file_extension=path.suffix.lower(), file_size=path.stat().st_size,
                content_hash=digest, status="pending",
            )
            session.add(source_file)
            await session.commit()
            await queue.enqueue_file(project.id, source_file.id)
            new_files += 1
        elif existing.content_hash != digest:
            existing.status = "pending"
            existing.content_hash = digest
            existing.file_size = path.stat().st_size
            existing.error_message = None
            await session.commit()
            await queue.enqueue_file(project.id, existing.id)
            modified += 1

    deleted = 0
    for relative, row in known.items():
        if relative not in seen and row.status != "deleted":
            row.status = "deleted"
            deleted += 1
    await session.commit()

    return {"new_files": new_files, "modified_files": modified, "deleted_files": deleted}
