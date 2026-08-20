"""In-process job queue.

The spec offers Celery+Redis or an in-process queue. This is the in-process one and
it is the only one wired up: a single container with three workers, no broker to
run or monitor. Swapping in Celery means implementing `enqueue` against the same
`Job` rows.

Stages for one file must run in order, so the queue does not simply run seven jobs
concurrently. `_run_file` walks a file through the stages sequentially, and the
worker pool gives concurrency *across* files. That is also what keeps the LLM
concurrency at roughly `workers`, which matters because the `ag/` routes rate-limit.
"""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

from ..config import get_settings
from ..database import SessionLocal
from ..models import Job, SourceFile
from .stages import STAGE_FUNCTIONS, STAGE_ORDER, StageError

logger = logging.getLogger(__name__)

#: Seconds to wait before retrying a retryable stage. Deliberately generous: the
#: usual cause is the router rate-limiting, and hammering it makes that worse.
RETRY_DELAY_SECONDS = 8


class InProcessQueue:
    def __init__(self, workers: int | None = None) -> None:
        settings = get_settings()
        self._max_workers = workers or settings.workers
        self._queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._active: dict[str, str] = {}  # source_file_id -> stage, for the dashboard
        self._started = False

    # -- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        for index in range(self._max_workers):
            self._workers.append(asyncio.create_task(self._worker_loop(index)))
        logger.info("job queue started with %d workers", self._max_workers)

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        for worker in self._workers:
            try:
                await worker
            except asyncio.CancelledError:
                pass
        self._workers.clear()
        self._started = False

    # -- api ---------------------------------------------------------------
    async def enqueue_file(self, project_id: str, source_file_id: str) -> None:
        """Queue a file to be walked through every stage."""
        await self._queue.put((project_id, source_file_id))

    @property
    def depth(self) -> int:
        return self._queue.qsize()

    @property
    def active(self) -> dict[str, str]:
        return dict(self._active)

    # -- internals ---------------------------------------------------------
    async def _worker_loop(self, worker_id: int) -> None:
        while True:
            project_id, source_file_id = await self._queue.get()
            try:
                await self._run_file(project_id, source_file_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # a worker must never die on one bad file
                logger.exception("worker %d crashed on file %s", worker_id, source_file_id)
            finally:
                self._active.pop(source_file_id, None)
                self._queue.task_done()

    async def _run_file(self, project_id: str, source_file_id: str) -> None:
        for stage in STAGE_ORDER:
            self._active[source_file_id] = stage
            ok = await self._run_stage(project_id, source_file_id, stage)
            if not ok:
                return  # the file is marked error; later stages would fail anyway

    async def _run_stage(self, project_id: str, source_file_id: str, stage: str) -> bool:
        function = STAGE_FUNCTIONS[stage]

        async with SessionLocal() as session:
            job = Job(
                project_id=project_id, source_file_id=source_file_id, stage=stage,
                status="running", priority=STAGE_ORDER.index(stage) + 1, attempt=1,
                started_at=datetime.now(timezone.utc),
            )
            session.add(job)
            await session.commit()
            job_id = job.id

        attempt = 0
        while True:
            attempt += 1
            async with SessionLocal() as session:
                try:
                    await function(session, source_file_id, job_id)
                except StageError as cause:
                    await session.rollback()
                    retryable = cause.retryable and attempt < 3
                    await self._finish_job(
                        job_id, "failed" if not retryable else "queued",
                        str(cause), attempt,
                    )
                    if retryable:
                        logger.info(
                            "stage %s for %s failed (attempt %d), retrying: %s",
                            stage, source_file_id, attempt, cause,
                        )
                        await asyncio.sleep(RETRY_DELAY_SECONDS)
                        continue
                    await self._mark_file_error(source_file_id, f"{stage}: {cause}")
                    return False
                except Exception as cause:  # unexpected — record it, do not retry
                    await session.rollback()
                    logger.exception("stage %s raised for %s", stage, source_file_id)
                    await self._finish_job(job_id, "failed", str(cause), attempt)
                    await self._mark_file_error(source_file_id, f"{stage}: {cause}")
                    return False

            await self._finish_job(job_id, "completed", None, attempt)
            return True

    async def _finish_job(
        self, job_id: str, status: str, error: str | None, attempt: int
    ) -> None:
        async with SessionLocal() as session:
            values: dict = {"status": status, "attempt": attempt}
            if error is not None:
                values["error_message"] = error[:2000]
            if status in {"completed", "failed"}:
                values["completed_at"] = datetime.now(timezone.utc)
            await session.execute(update(Job).where(Job.id == job_id).values(**values))
            await session.commit()

    async def _mark_file_error(self, source_file_id: str, message: str) -> None:
        async with SessionLocal() as session:
            source_file = await session.get(SourceFile, source_file_id)
            if source_file is not None:
                source_file.status = "error"
                source_file.error_message = message[:2000]
                await session.commit()

    async def requeue_unfinished(self) -> int:
        """On startup, pick up files left mid-pipeline by a restart.

        Jobs live in memory, so a container restart abandons anything in flight. The
        file rows survive, and any file not published and not errored is resumable.
        """
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    select(SourceFile.project_id, SourceFile.id).where(
                        SourceFile.status.notin_(["published", "error", "deleted"])
                    )
                )
            ).all()
        for project_id, source_file_id in rows:
            await self.enqueue_file(project_id, source_file_id)
        if rows:
            logger.info("requeued %d unfinished file(s) after restart", len(rows))
        return len(rows)


_queue: InProcessQueue | None = None


def get_queue() -> InProcessQueue:
    global _queue
    if _queue is None:
        _queue = InProcessQueue()
    return _queue
