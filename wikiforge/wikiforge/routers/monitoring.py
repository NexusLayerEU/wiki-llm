"""Pipeline status, job history, LLM usage metrics."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import Job, LLMUsage, SourceFile
from ..pipeline import get_queue
from ..schemas import JobStatus, PipelineStatus
from ..services.auth import CurrentUser, current_user
from ..services.projects import get_or_404

router = APIRouter(prefix="/api/v1/projects", tags=["monitoring"])

#: Rough seconds per file, used only for the ETA. Measured against ag/gemini-3-flash
#: on a handful of mid-size documents: four LLM stages at a few seconds each.
SECONDS_PER_FILE = 25


@router.get("/{project_id}/status", response_model=PipelineStatus)
async def pipeline_status(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> PipelineStatus:
    project = await get_or_404(session, project_id)

    rows = (
        await session.execute(
            select(SourceFile.status, func.count(SourceFile.id))
            .where(SourceFile.project_id == project.id, SourceFile.status != "deleted")
            .group_by(SourceFile.status)
        )
    ).all()
    by_status = {status: count for status, count in rows}
    total = sum(by_status.values())
    published = by_status.get("published", 0)
    errored = by_status.get("error", 0)

    # Errors count as finished. Without that, a project with one broken file sits at
    # 97% forever and reads as though it is still working.
    settled = published + errored
    progress = (settled / total * 100.0) if total else 0.0

    running = (
        await session.execute(
            select(Job, SourceFile.filename)
            .join(SourceFile, SourceFile.id == Job.source_file_id)
            .where(Job.project_id == project.id, Job.status == "running")
            .order_by(Job.started_at.desc())
            .limit(25)
        )
    ).all()

    outstanding = max(total - settled, 0)
    return PipelineStatus(
        project_id=project.id,
        status=project.status,
        total_files=total,
        files_by_status=by_status,
        progress_pct=round(progress, 1),
        active_jobs=[
            JobStatus(
                id=job.id, source_file=filename, stage=job.stage, status=job.status,
                attempt=job.attempt, started_at=job.started_at,
            )
            for job, filename in running
        ],
        eta_seconds=(outstanding * SECONDS_PER_FILE) or None,
        queue_depth=get_queue().depth,
    )


@router.get("/{project_id}/jobs", response_model=dict)
async def list_jobs(
    project_id: str,
    status: str | None = None,
    stage: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> dict:
    project = await get_or_404(session, project_id)
    query = (
        select(Job, SourceFile.filename)
        .join(SourceFile, SourceFile.id == Job.source_file_id)
        .where(Job.project_id == project.id)
    )
    if status:
        query = query.where(Job.status == status)
    if stage:
        query = query.where(Job.stage == stage)

    total = (
        await session.execute(select(func.count()).select_from(query.subquery()))
    ).scalar() or 0
    rows = (
        await session.execute(
            query.order_by(Job.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()

    return {
        "jobs": [
            {
                "id": job.id, "source_file": filename, "stage": job.stage,
                "status": job.status, "attempt": job.attempt,
                "error_message": job.error_message,
                "started_at": job.started_at, "completed_at": job.completed_at,
                "duration_ms": (
                    int((job.completed_at - job.started_at).total_seconds() * 1000)
                    if job.started_at and job.completed_at else None
                ),
            }
            for job, filename in rows
        ],
        "total": total, "limit": limit, "offset": offset,
    }


@router.get("/{project_id}/metrics", response_model=dict)
async def metrics(
    project_id: str,
    period: str = Query("all", pattern="^(today|week|month|all)$"),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> dict:
    project = await get_or_404(session, project_id)

    query = select(LLMUsage).where(LLMUsage.project_id == project.id)
    if period != "all":
        days = {"today": 1, "week": 7, "month": 30}[period]
        since = datetime.now(timezone.utc) - timedelta(days=days)
        query = query.where(LLMUsage.created_at >= since)

    rows = list((await session.execute(query)).scalars().all())

    by_stage: dict[str, dict] = {}
    by_provider: dict[str, dict] = {}
    for row in rows:
        stage = by_stage.setdefault(
            row.stage, {"tokens_in": 0, "tokens_out": 0, "calls": 0, "latency_ms": 0}
        )
        stage["tokens_in"] += row.tokens_in
        stage["tokens_out"] += row.tokens_out
        stage["calls"] += 1
        stage["latency_ms"] += row.latency_ms

        provider = by_provider.setdefault(
            row.provider, {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "calls": 0}
        )
        provider["tokens_in"] += row.tokens_in
        provider["tokens_out"] += row.tokens_out
        provider["cost_usd"] += row.cost_usd
        provider["calls"] += 1

    for stage in by_stage.values():
        stage["avg_latency_ms"] = round(stage.pop("latency_ms") / stage["calls"]) if stage["calls"] else 0

    return {
        "period": period,
        "total_calls": len(rows),
        "total_tokens_in": sum(row.tokens_in for row in rows),
        "total_tokens_out": sum(row.tokens_out for row in rows),
        # Zero, and honestly so: SwitchBoard does not report per-call cost, and a
        # made-up figure in a cost column is worse than an obvious blank.
        "total_cost_usd": round(sum(row.cost_usd for row in rows), 4),
        "by_stage": by_stage,
        "by_provider": by_provider,
        "avg_latency_ms": (
            round(sum(row.latency_ms for row in rows) / len(rows)) if rows else 0
        ),
    }


@router.get("/{project_id}/watcher", response_model=dict)
async def watcher_status(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> dict:
    project = await get_or_404(session, project_id)
    watched = (
        await session.execute(
            select(func.count(SourceFile.id)).where(
                SourceFile.project_id == project.id, SourceFile.status != "deleted"
            )
        )
    ).scalar() or 0
    last_change = (
        await session.execute(
            select(func.max(SourceFile.updated_at)).where(SourceFile.project_id == project.id)
        )
    ).scalar()

    return {
        # No background poller runs: sync is on demand via trigger-sync. Reporting
        # "running" here would claim a daemon that does not exist.
        "status": "on-demand",
        "source_dir": project.source_dir,
        "poll_interval_sec": project.watch_interval,
        "files_watched": watched,
        "last_change_detected": last_change,
        "queue_depth": get_queue().depth,
    }
